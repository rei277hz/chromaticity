"""Native persistence, revision and update invariants."""
from dataclasses import replace
from pathlib import Path
from unittest import mock
import unittest
import numpy as np

from color_tools.kernel import (prepare,prepare_linear,prepare_update,
    LinearSettings,ColorSettings,Settings)
from color_tools.template_build.persistent import build_persistent
from color_tools.kernel.boundary import prepare_boundary
from tools.perceptual_grade.reports import cases,full_cases,oracle
from tools.perceptual_grade.reports.native import NativeFixture
from tools.perceptual_grade.reports.evaluate import assess


class PersistentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        context=prepare()
        cls.boundary=prepare_boundary(context.fl,context.aw,context.gamma)
        cls.reset=prepare(full_fields=True,boundary=cls.boundary)

    @staticmethod
    def identities(built):
        return (built.tree.as_pointer(),tuple(node.as_pointer() for node in built.tree.nodes),
                tuple((image.as_pointer(),tuple(image.size)) for image in built.images))

    @staticmethod
    def reachable_images(tree):
        """Follow actual native links from every exposed output/diagnostic."""
        incoming={}
        for link in tree.links:
            incoming.setdefault(link.to_node.as_pointer(),[]).append(link.from_node)
        pending=[node for node in tree.nodes
                 if node.bl_idname=='NodeGroupOutput' and node.is_active_output]
        visited=set();images=set()
        while pending:
            node=pending.pop();pointer=node.as_pointer()
            if pointer in visited:
                continue
            visited.add(pointer)
            image=getattr(node,'image',None)
            if image is not None:
                images.add(image.as_pointer())
            pending.extend(incoming.get(pointer,()))
        return images

    @staticmethod
    def field_pixels(built):
        result={}
        for name,(_,image) in built._graph.image_slots.items():
            values=np.empty(len(image.pixels),dtype=np.float32)
            image.pixels.foreach_get(values)
            result[name]=values
        return result

    def active_update(self,previous):
        _,linear,tone,color=next(row for row in full_cases.grades() if row[0]=='all_active')
        return prepare_update(Settings(linear=linear,tone=tone,color=color),previous)

    @staticmethod
    def corrupt_first_field(built):
        """Model a native upload failing after changing only part of an image."""
        _,image=built._graph.image_slots['tone']
        values=np.empty(len(image.pixels),dtype=np.float32)
        image.pixels.foreach_get(values)
        values[:4]+=1.
        image.pixels.foreach_set(values);image.update()

    def test_linear_edit_preserves_native_identity_and_fields(self):
        import bpy
        bpy.ops.wm.read_factory_settings(use_empty=True)
        prepared=self.reset
        built=build_persistent(prepared)
        try:
            nodes=tuple(node.as_pointer() for node in built.tree.nodes)
            images=tuple((image.as_pointer(),tuple(image.size)) for image in built.images)
            updated=replace(prepared,linear=prepare_linear(LinearSettings(exposure=.7)))
            receipt=built.apply(updated,expected_revision=0)
            self.assertEqual(receipt['changed_fields'],())
            self.assertEqual(built.revision,1)
            self.assertEqual(nodes,tuple(node.as_pointer() for node in built.tree.nodes))
            self.assertEqual(images,tuple((image.as_pointer(),tuple(image.size)) for image in built.images))
            with self.assertRaisesRegex(ValueError,'revision'):
                built.apply(updated,expected_revision=0)
            # A persisted dual-table tree cannot accept updates under the
            # new single-table schema, even with matching image dimensions.
            built.tree['perceptual_grade_nodes_schema']=3
            with self.assertRaisesRegex(ValueError,'schema is obsolete'):
                built.apply(updated,expected_revision=1)
            self.assertEqual(built.revision,1)
            self.assertEqual(nodes,tuple(node.as_pointer() for node in built.tree.nodes))
            self.assertEqual(images,tuple((image.as_pointer(),tuple(image.size)) for image in built.images))
        finally:
            built.dispose()

    def test_neutral_stages_bypass_helper_samplers_in_native_links(self):
        import bpy
        for context in ('ShaderNodeTree','CompositorNodeTree'):
            with self.subTest(context=context):
                bpy.ops.wm.read_factory_settings(use_empty=True)
                built=build_persistent(self.reset,context)
                try:
                    identity=self.identities(built)
                    slots={name:image.as_pointer() for name,(_,image) in built._graph.image_slots.items()}
                    reset_reachable=self.reachable_images(built.tree)
                    self.assertTrue(reset_reachable.isdisjoint(slots.values()))
                    tone=next(row[2] for row in cases.grades() if row[0]=='tone')
                    update=prepare_update(Settings(tone=tone),built.prepared)
                    built.apply(update,expected_revision=0)
                    active_reachable=self.reachable_images(built.tree)
                    self.assertIn(slots['tone'],active_reachable)
                    self.assertTrue(active_reachable.isdisjoint(
                        pointer for name,pointer in slots.items() if name!='tone'))
                    built.apply(self.reset,expected_revision=1)
                    self.assertEqual(self.reachable_images(built.tree),reset_reachable)
                    self.assertEqual(self.identities(built),identity)
                finally:
                    built.dispose()

    def test_updates_keep_authored_stages_all_spaces_and_contexts(self):
        selected=list(full_cases.grades())
        selected+=[row for row in full_cases.ui_boundaries()
                   if row[0] in ('all_families_max','all_families_max_active_tail','web_alternating_extremes')]
        # One fixed graph per context/space traverses reset, every family,
        # both precision policies, and the largest native stress cases.
        prepared={name:prepare(linear,tone,color=color,boundary=self.boundary,full_fields=True)
                  for name,linear,tone,color in selected}
        for space in cases.SPACES:
            values=full_cases.rgba(space,256)
            initial=replace(self.reset,linear=prepare_linear(LinearSettings(),space),space=space)
            for context in ('shader','compositor'):
                fixture=NativeFixture(initial,values,context,builder=build_persistent)
                built=fixture.built;identity=self.identities(built)
                try:
                    self.assertEqual(set(built._graph.image_slots),
                        {'tone','coefficient_table','web_table','web_toe_table','adaptance_table'})
                    sequence=selected+[selected[0]]
                    for name,linear,tone,color in sequence:
                        with self.subTest(space=space,context=context,case=name):
                            grade=replace(prepared[name],linear=prepare_linear(linear,space),space=space)
                            built.apply(grade,expected_revision=built.revision)
                            self.assertEqual(identity,self.identities(built))
                            actual=fixture.render();expected=oracle.evaluate_full(values[:,:3],linear,tone,color,space)
                            result=assess(actual,expected,values)
                            self.assertTrue(result['passed'],result)
                            self.assertTrue(np.isfinite(actual['saturated']).all())
                            if name=='reset':np.testing.assert_array_equal(actual['saturated'],0.)
                    # A real Linear drag preserves the authored all-active
                    # Tone/Color and uploads none of their unchanged fields.
                    name,linear,tone,color=next(row for row in selected if row[0]=='all_active')
                    grade=replace(prepared[name],linear=prepare_linear(linear,space),space=space)
                    built.apply(grade,expected_revision=built.revision)
                    edited=replace(linear,exposure=linear.exposure+.2)
                    update=prepare_update(Settings(edited,tone,space,color),built.prepared)
                    self.assertIs(update.tone,built.prepared.tone)
                    self.assertIs(update.color,built.prepared.color)
                    receipt=built.apply(update,expected_revision=built.revision)
                    self.assertEqual(receipt['changed_fields'],())
                    actual=fixture.render();expected=oracle.evaluate_full(values[:,:3],edited,tone,color,space)
                    self.assertTrue(assess(actual,expected,values)['passed'])
                finally:fixture.close()

    def test_partial_write_rolls_back_and_stale_update_has_no_effect(self):
        values=full_cases.rgba(count=64)
        fixture=NativeFixture(self.reset,values,'compositor',builder=build_persistent)
        built=fixture.built
        try:
            before=fixture.render();identity=self.identities(built)
            update=self.active_update(built.prepared)
            original=built._write
            def fail_after_native_write(prepared):
                original(prepared)
                raise RuntimeError('injected after write')
            with mock.patch.object(built,'_write',side_effect=fail_after_native_write):
                with self.assertRaisesRegex(RuntimeError,'injected'):
                    built.apply(update,expected_revision=0)
            self.assertTrue(built.valid)
            self.assertIs(built.prepared,self.reset)
            self.assertEqual(built.revision,0)
            self.assertEqual(identity,self.identities(built))
            after=fixture.render()
            for name in ('rgb','alpha','valid','margin','saturated'):
                np.testing.assert_array_equal(after[name],before[name])
            with self.assertRaisesRegex(ValueError,'revision'):
                built.apply(update,expected_revision=1)
            built.apply(update,expected_revision=0)
            self.assertEqual(built.revision,1)
        finally:fixture.close()

    def test_partial_image_upload_restores_pixels_and_render(self):
        values=full_cases.rgba(count=64)
        fixture=NativeFixture(self.reset,values,'compositor',builder=build_persistent)
        built=fixture.built
        try:
            before=fixture.render();pixels=self.field_pixels(built)
            update=self.active_update(built.prepared)
            def fail_during_image_write(prepared):
                self.corrupt_first_field(built)
                self.assertFalse(np.array_equal(self.field_pixels(built)['tone'],pixels['tone']))
                raise RuntimeError('injected partial image write')
            with mock.patch.object(built,'_write',side_effect=fail_during_image_write):
                with self.assertRaisesRegex(RuntimeError,'partial image write'):
                    built.apply(update,expected_revision=0)
            self.assertTrue(built.valid)
            self.assertEqual(built.revision,0)
            self.assertIs(built.prepared,self.reset)
            for name,actual in self.field_pixels(built).items():
                np.testing.assert_array_equal(actual,pixels[name])
            after=fixture.render()
            for name in ('rgb','alpha','valid','margin','saturated'):
                np.testing.assert_array_equal(after[name],before[name])
        finally:fixture.close()

    def test_failed_restoration_retains_repair_debt(self):
        import bpy
        bpy.ops.wm.read_factory_settings(use_empty=True)
        built=build_persistent(self.reset,'CompositorNodeTree')
        try:
            update=self.active_update(built.prepared)
            def fail_during_image_write(prepared):
                self.corrupt_first_field(built)
                raise RuntimeError('injected partial image write')
            with (mock.patch.object(built,'_write',side_effect=fail_during_image_write),
                  mock.patch.object(built._graph,'_write_binding',
                                    side_effect=RuntimeError('injected failed native restoration'))):
                with self.assertRaisesRegex(RuntimeError,'partial image write'):
                    built.apply(update,expected_revision=0)
            self.assertFalse(built.valid)
            self.assertEqual(built.revision,0)
            self.assertIs(built.prepared,self.reset)
            with self.assertRaisesRegex(ValueError,'requires recovery'):
                built.apply(update,expected_revision=0)
        finally:built.dispose()

    def test_packed_tree_reopens_without_registration(self):
        import bpy
        values=full_cases.rgba(count=64)
        fixture=NativeFixture(self.reset,values,'compositor',builder=build_persistent)
        try:
            update=self.active_update(fixture.built.prepared)
            receipt=fixture.built.apply(update,expected_revision=0)
            self.assertEqual(set(receipt['changed_fields']),set(fixture.built._graph.image_slots))
            before=fixture.render();name=fixture.built.tree.name
            packed_pixels={image.name:np.asarray(image.pixels[:],dtype=np.float32)
                           for image in fixture.built.images}
            images={image.name:(tuple(image.size),bool(image.packed_file)) for image in fixture.built.images}
            fixture.input_image.pack()
            filename=Path(fixture.directory.name)/'persistent-grade.blend'
            bpy.ops.wm.save_as_mainfile(filepath=str(filename))
            bpy.ops.wm.open_mainfile(filepath=str(filename))
            self.assertTrue(bpy.data.node_groups[name]['perceptual_grade_nodes_persistent'])
            self.assertEqual(bpy.data.node_groups[name]['perceptual_grade_nodes_revision'],1)
            self.assertEqual(images,{key:(tuple(bpy.data.images[key].size),bool(bpy.data.images[key].packed_file)) for key in images})
            for key,expected in packed_pixels.items():
                actual=np.empty(expected.size,dtype=np.float32)
                bpy.data.images[key].pixels.foreach_get(actual)
                np.testing.assert_array_equal(actual,expected)
            after=fixture.render()
            for field in ('rgb','alpha','valid','margin','saturated'):
                np.testing.assert_array_equal(after[field],before[field])
        finally:fixture.close()


if __name__=='__main__':unittest.main()
