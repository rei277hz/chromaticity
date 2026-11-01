"""Exact-output admission across Blender callbacks and portable conversion."""
from tests.support.session import component as _component, SessionTest, patch
import gc
import json
import tempfile
import weakref
from pathlib import Path
pass

import bpy

gpu = _component('graph.gpu'); grades = _component('graph.grades'); lut = _component('graph.lut'); nodes = _component('graph.nodes'); output = _component('graph.output')

from color_tools.perceptual_grade_core.graph import scheduler_policy as policy
from tests.support.blender import BlenderTest, sequence


class OutputTests(BlenderTest):
    def test_render_preserves_adopted_native_output_without_lut_work(self):
        scene = bpy.context.scene
        world = bpy.data.worlds.new('Authored output')
        world.use_nodes = True
        scene.world = world
        node = nodes.create_grade(world.node_tree)
        node[lut.MANIFEST] = 'user-authored metadata'
        lut.resources.selector_socket(node).default_value = -1.
        lut.adopt_native(node, nodes.output_intent(node))
        before = (node.node_tree, node[lut.MANIFEST], lut.resources.selector_socket(node).default_value)
        with patch.object(lut, 'ensure', side_effect=AssertionError('Adopted output regenerated')), \
                patch.object(lut, 'validate_output', side_effect=AssertionError('Adopted output verified')):
            ready = output.prepare_render(scene)
            self.assertEqual(ready, output.snapshot(scene, validate=True))
        self.assertTrue(lut.is_adopted(node))
        self.assertEqual((node.node_tree, node[lut.MANIFEST], lut.resources.selector_socket(node).default_value), before)

    def test_portable_wrapper_conversion_preserves_adopted_output(self):
        tree = bpy.data.node_groups.new('Adopted portable output', 'ShaderNodeTree')
        node = nodes.create_grade(tree)
        name, kernel = node.name, node.node_tree
        node[lut.MANIFEST] = 'authored native output'
        lut.resources.selector_socket(node).default_value = -1.
        lut.adopt_native(node, nodes.output_intent(node))
        with patch.object(lut, 'validate_output', side_effect=AssertionError('Adopted output verified')), \
                patch.object(lut, 'verify_replacement', side_effect=AssertionError('Adopted replacement inspected')):
            grades.representations(portable=True)
            self.assertEqual(tree.nodes[name].bl_idname, 'ShaderNodeGroup')
            self.assertTrue(lut.is_adopted(tree.nodes[name]))
            grades.representations(restore_adopted=True)
        restored = tree.nodes[name]
        self.assertEqual(restored.bl_idname, grades.KINDS['ShaderNodeTree'])
        self.assertEqual(restored.node_tree, kernel)
        self.assertEqual(restored[lut.MANIFEST], 'authored native output')
        self.assertEqual(lut.resources.selector_socket(restored).default_value, -1.)
        self.assertTrue(lut.is_adopted(restored))

    def test_save_restores_original_native_wrapper_and_driver_mute(self):
        tree=bpy.data.node_groups.new('Originally portable','CompositorNodeTree')
        node=nodes.create_grade(tree)
        grades.ensure(node)
        name=node.name
        grades.representations(portable=True)
        node=tree.nodes[name]
        lut.adopt_native(node,nodes.output_intent(node))
        self.assertEqual(node.bl_idname,'CompositorNodeGroup')
        pointer=node.as_pointer()
        curve=tree.animation_data.drivers.find(node.path_from_id()+'["_pg_grade_dependency"]')
        curve.mute=False
        with patch.object(lut,'ensure',side_effect=AssertionError('Save recalculated adopted output')):
            nodes.save_handler()
            self.assertTrue(curve.mute)
            nodes.save_finished_handler()
        self.assertEqual(tree.nodes[name].as_pointer(),pointer)
        self.assertFalse(curve.mute)
        self.assertTrue(lut.is_adopted(tree.nodes[name]))
        nodes.write_chromatic(tree.nodes[name],{'global_gain':.17})
        self.assertFalse(lut.is_adopted(tree.nodes[name]))
        grades.representations()
        self.assertEqual(tree.nodes[name].as_pointer(),pointer)
        self.assertEqual(tree.nodes[name].bl_idname,'CompositorNodeGroup')

    def tearDown(self):
        output.clear()
        super().tearDown()

    def operation(self):
        operation = output.Operation('render', bpy.context.scene)
        self.addCleanup(operation.close)
        return operation

    def test_render_prepares_only_scene_owners_but_save_snapshot_checks_all(self):
        scene = bpy.context.scene
        world = bpy.data.worlds.new('Required world')
        world.use_nodes = True
        scene.world = world
        required = nodes.create_grade(world.node_tree)
        unrelated = nodes.create_grade(bpy.data.node_groups.new('Unrelated output', 'ShaderNodeTree'))
        unrelated[lut.INCOMPLETE] = True
        with patch.object(gpu, 'acquire', return_value=(None, None)):
            ready = output.prepare_render(scene)
            self.assertEqual(ready, output.snapshot(scene, validate=True))
        self.assertEqual(output._nodes(scene), (required,))
        self.assertTrue(unrelated.get(lut.INCOMPLETE))
        self.assertEqual({node.as_pointer() for node in output._nodes()},
                         {required.as_pointer(), unrelated.as_pointer()})
        with self.assertRaisesRegex(RuntimeError, 'pending installation'):
            output.snapshot(scene, validate=True, all_owners=True)

    def test_render_dependencies_include_instances_overrides_lights_and_nested_groups(self):
        scene = bpy.context.scene
        collection = bpy.data.collections.new('Instanced only')
        mesh = bpy.data.meshes.new('Instanced mesh')
        obj = bpy.data.objects.new('Instanced object', mesh)
        collection.objects.link(obj)
        material = bpy.data.materials.new('Instanced material')
        material.use_nodes = True
        mesh.materials.append(material)
        nested = bpy.data.node_groups.new('Nested shader', 'ShaderNodeTree')
        for _ in range(2):
            material.node_tree.nodes.new('ShaderNodeGroup').node_tree = nested
        nested_grade = nodes.create_grade(nested)
        instance = bpy.data.objects.new('Collection instance', None)
        instance.instance_type = 'COLLECTION'
        instance.instance_collection = collection
        scene.collection.objects.link(instance)
        override = bpy.data.materials.new('Render override')
        override.use_nodes = True
        scene.view_layers[0].material_override = override
        override_grade = nodes.create_grade(override.node_tree)
        light = bpy.data.lights.new('Render light', 'AREA')
        light.use_nodes = True
        scene.collection.objects.link(bpy.data.objects.new('Render light', light))
        light_grade = nodes.create_grade(light.node_tree)
        orphan = nodes.create_grade(bpy.data.node_groups.new('Orphan shader', 'ShaderNodeTree'))
        owners = output._nodes(scene)
        self.assertEqual({node.as_pointer() for node in owners},
                         {nested_grade.as_pointer(), override_grade.as_pointer(), light_grade.as_pointer()})
        self.assertEqual(len(owners), 3)  # Repeated native references produce one owner.
        self.assertNotIn(orphan, owners)

    def test_render_dependencies_follow_compositor_scene_references(self):
        scene = bpy.context.scene
        compositor = bpy.data.node_groups.new('Scene compositor', 'CompositorNodeTree')
        scene.compositing_node_group = compositor
        local = nodes.create_grade(compositor)
        referenced = bpy.data.scenes.new('Referenced scene')
        world = bpy.data.worlds.new('Referenced world')
        world.use_nodes = True
        referenced.world = world
        remote = nodes.create_grade(world.node_tree)
        compositor.nodes.new('CompositorNodeRLayers').scene = referenced
        self.assertEqual({node.as_pointer() for node in output._nodes(scene)},
                         {local.as_pointer(), remote.as_pointer()})

    def test_stack_control_dependency_does_not_require_orphan_grade_output(self):
        scene = bpy.context.scene
        world = bpy.data.worlds.new('Stack world')
        world.use_nodes = True
        scene.world = world
        orphan = nodes.create_grade(bpy.data.node_groups.new('Controls only', 'ShaderNodeTree'))
        nodes.write_chromatic(orphan, {'global_gain': .1})
        stack = sequence(world.node_tree, [orphan.pg_grade])
        self.assertEqual(output._nodes(scene), (stack,))

    def test_preview_receipt_cannot_authorize_native_operation(self):
        operation = self.operation()
        self.assertFalse(operation.event('validated', key=operation.state.required, resolution=33).accept)
        self.assertFalse(operation.event('native_begin', key=operation.state.required, token=77).invoke)
        self.assertEqual(operation.state.phase, policy.EXACT_PREPARING)

    def test_changed_rows_invalidate_ready_native_receipt(self):
        operation = self.operation()
        with patch.object(output, 'prepare_render', return_value=('rows', 1)):
            operation.prepare()
        with patch.object(output, 'snapshot', return_value=('rows', 2)):
            with self.assertRaisesRegex(RuntimeError, 'changed after'):
                operation.invoke(lambda: self.fail('Stale native operation was invoked'))
        self.assertEqual(operation.state.phase, policy.EXACT_PREPARING)
        self.assertEqual(operation.state.receipt, 0)
        self.assertEqual(operation.native_calls, 0)

    def test_async_return_retains_lease_until_native_job_stops(self):
        operation = self.operation()
        with patch.object(output, 'prepare_render', return_value=('ready',)), \
                patch.object(output, 'snapshot', return_value=('ready',)):
            operation.prepare()
            operation.invoke(lambda: {'RUNNING_MODAL'})
        token = operation.state.lease
        self.assertGreater(token, 0)
        self.assertFalse(operation.event('native_begin', key=operation.state.required, token=token+1).invoke)
        operation.native_result(1)
        with patch.object(output, 'native_running', return_value=True):
            self.assertFalse(operation.settle())
        self.assertEqual(operation.state.lease, token)
        self.assertTrue(operation.settle())
        self.assertEqual(operation.state.lease, 0)
        self.assertEqual(operation.state.phase, policy.EXACT_COMPLETE)

    def test_frame_edit_reprepares_actual_negative_frame_identity(self):
        scene=bpy.context.scene
        scene.frame_set(4)
        operation=self.operation()
        with patch.object(output,'prepare_render',side_effect=lambda scene:(scene.frame_current,)), \
             patch.object(output,'snapshot',side_effect=lambda scene,**_:(scene.frame_current,)):
            operation.prepare()
            scene.frame_set(-3)
            with self.assertRaisesRegex(RuntimeError,'changed after'):
                operation.invoke(lambda:self.fail('Stale frame was invoked'))
            self.assertEqual(operation.coordinator.state.frame,-3)
            operation.prepare()
            operation.invoke(lambda:{'FINISHED'})
            self.assertEqual(operation.coordinator.state.frame,-3)
            self.assertTrue(operation.settle())
            self.assertEqual(operation.coordinator.state.phase,'complete')

    def test_failed_output_keeps_only_diagnostics_after_close_without_cyclic_gc(self):
        class Owner:
            pass
        references = []
        def fail(*args, **kwargs):
            owner = Owner()
            owner.scene = bpy.context.scene
            references.append(weakref.ref(owner))
            try:
                raise LookupError('Underlying output failure')
            except LookupError as cause:
                raise ValueError('Exact output failed') from cause
        def attempt(phase):
            operation = output.Operation('render', bpy.context.scene)
            references.append(weakref.ref(operation))
            try:
                with patch.object(output, 'prepare_render', new=fail if phase == 'prepare' else lambda scene: ()), \
                     patch.object(output, 'snapshot', new=lambda *a, **k: ()):
                    operation.prepare()
                    operation.invoke(fail)
            except ValueError as error:
                # Immediate failures retain their original exception contract.
                self.assertEqual(str(error), 'Exact output failed')
            else:
                self.fail('Output failure was swallowed')
            finally:
                operation.close()
            self.assertTrue(operation.closed)
            self.assertIsNone(operation.scene)
            self.assertIsNone(operation.window_manager)
            return operation.error
        enabled = gc.isenabled()
        gc.disable()
        try:
            for phase in ('prepare', 'native'):
                failure = attempt(phase)
                self.assertEqual(failure.type_name, 'ValueError')
                self.assertEqual(failure.message, 'Exact output failed')
                self.assertIn('Underlying output failure', failure.detail)
                self.assertFalse(output.busy())
                self.assertTrue(all(reference() is None for reference in references))
        finally:
            if enabled:gc.enable()

    def test_close_releases_scene_only_after_native_stops(self):
        operation = self.operation()
        scene = operation.scene
        operation.window_manager = bpy.context.window_manager
        with patch.object(output, 'prepare_render', return_value=()), \
             patch.object(output, 'snapshot', return_value=()):
            operation.prepare()
            operation.invoke(lambda: {'RUNNING_MODAL'})
        lease = operation.state.lease
        with patch.object(output, 'native_running', return_value=True):
            self.assertFalse(operation.close())
        self.assertIs(operation.scene, scene)
        self.assertIsNotNone(operation.window_manager)
        self.assertEqual(operation.state.lease, lease)
        self.assertTrue(output.busy())
        self.assertTrue(operation.close())
        self.assertIsNone(operation.scene)
        self.assertIsNone(operation.window_manager)
        self.assertEqual(operation.state.lease, 0)
        self.assertFalse(output.busy())

    def test_cancelled_frame_cannot_advance_after_success_callback(self):
        operation = self.operation()
        with patch.object(output, 'prepare_render', return_value=()), patch.object(output, 'snapshot', return_value=()):
            operation.prepare()
            operation.invoke(lambda: {'RUNNING_MODAL'})
        operation.cancel()
        operation.native_result(1)
        operation.settle()
        self.assertEqual(operation.state.phase, policy.EXACT_CANCELLED)
        with self.assertRaisesRegex(RuntimeError, 'cannot advance'):
            operation.next_frame()

    def test_late_receipts_from_prior_frame_and_session_are_rejected(self):
        operation = self.operation()
        old = operation.state
        with patch.object(output, 'prepare_render', return_value=()), patch.object(output, 'snapshot', return_value=()):
            operation.prepare()
            operation.invoke(lambda: {'FINISHED'})
        operation.settle()
        operation.next_frame()
        event = policy.ExactEvent('validated', operation=old.operation, session=old.session,
                                 revision=old.revision, frame=old.frame, key=old.required, resolution=65)
        self.assertFalse(operation.store.preview(event).effects.accept)
        output.clear()
        with self.assertRaisesRegex(RuntimeError, 'expired session'):
            operation.authorize()

    def test_sequence_preflights_every_frame_and_restores_scene(self):
        scene = bpy.context.scene
        scene.frame_start, scene.frame_end, scene.frame_step = 2, 6, 2
        scene.frame_set(11, subframe=.25)
        original = (scene.frame_current, scene.frame_subframe, scene.frame_start, scene.frame_end, scene.frame_step,
                    scene.render.filepath)
        prepared, invoked = [], []
        def prepare(scene):
            prepared.append(scene.frame_current)
            return (scene.frame_current,)
        def native(scene, frame, **kwargs):
            invoked.append((frame, output._active.state.frame, output._active.state.lease))
            self.assertEqual(output._active.state.phase, policy.EXACT_NATIVE)
            return {'FINISHED'}
        with patch.object(output, 'prepare_render', side_effect=prepare), \
                patch.object(output, 'snapshot', side_effect=lambda scene, **_: (scene.frame_current,)), \
                patch.object(output, '_native_render', side_effect=native):
            self.assertEqual(output.guarded_render(scene, animation=True), {'FINISHED'})
        self.assertEqual(prepared, [2, 4, 6])
        self.assertEqual([item[:2] for item in invoked], [(2, 0), (4, 1), (6, 2)])
        self.assertEqual(len({item[2] for item in invoked}), 3)
        self.assertEqual((scene.frame_current, scene.frame_subframe, scene.frame_start, scene.frame_end, scene.frame_step,
                          scene.render.filepath), original)

    def test_sequence_failure_never_invokes_failed_frame(self):
        scene = bpy.context.scene
        scene.frame_start, scene.frame_end = 1, 3
        scene.frame_set(8)
        invoked = []
        def prepare(scene):
            if scene.frame_current == 2:
                raise RuntimeError('Final LUT unavailable')
            return (scene.frame_current,)
        with patch.object(output, 'prepare_render', side_effect=prepare), \
                patch.object(output, 'snapshot', side_effect=lambda scene, **_: (scene.frame_current,)), \
                patch.object(output, '_native_render', side_effect=lambda scene, frame, **_: invoked.append(frame) or {'FINISHED'}):
            with self.assertRaisesRegex(RuntimeError, 'Final LUT unavailable'):
                output.guarded_render(scene, animation=True)
        self.assertEqual(invoked, [1])
        self.assertEqual(scene.frame_current, 8)
        self.assertFalse(output.busy())

    def test_movie_guard_rejects_without_invoking_or_changing_settings(self):
        scene = bpy.context.scene
        scene.render.image_settings.media_type = 'VIDEO'
        scene.render.image_settings.file_format = 'FFMPEG'
        with patch.object(output, '_native_render', side_effect=AssertionError('Movie invoked')):
            with self.assertRaisesRegex(RuntimeError, 'image sequences'):
                output.guarded_render(scene, animation=True)
        self.assertEqual(scene.render.image_settings.file_format, 'FFMPEG')
        self.assertFalse(output.busy())

    def test_save_preparation_failure_does_not_create_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / 'not-saved.blend')
            with patch.object(nodes, 'save_handler', side_effect=RuntimeError('Final save output failed')):
                with self.assertRaisesRegex(RuntimeError, 'Final save output failed'):
                    output.guarded_save(path)
            self.assertFalse(Path(path).exists())
            self.assertFalse(output.busy())

    def test_save_ready_receipt_follows_portable_conversion(self):
        tree = bpy.data.node_groups.new('Portable exact save', 'CompositorNodeTree')
        tree.use_fake_user = True
        node = nodes.create_grade(tree)
        original_pointer = node.as_pointer()
        name = node.name
        operation = output.Operation('save', bpy.context.scene)
        try:
            operation.prepare()
            converted = tree.nodes[name]
            self.assertTrue(grades._saving)
            self.assertNotEqual(converted.as_pointer(), original_pointer)
            self.assertEqual(converted.bl_idname, 'CompositorNodeGroup')
            self.assertEqual(operation.state.phase, policy.EXACT_READY)
            operation.authorize()
            self.assertTrue(output.reuse_save_pre())
            self.assertEqual(operation.native_calls, 1)
        finally:
            operation.close()
        self.assertFalse(grades._saving)

    def test_save_reopen_and_disable_reuse_complete_payloads_without_calculation_or_transfer(self):
        tree = bpy.data.node_groups.new('Saved complete output', 'CompositorNodeTree')
        tree.use_fake_user = True
        node = nodes.create_grade(tree)
        nodes.write_chromatic(node, {'global_gain': .1})
        with patch.object(gpu, 'acquire', return_value=(None, None)):
            lut.ensure(node, nodes.bake_model(node), force=True)
        tree_name, node_name = tree.name, node.name
        expected = lut.validate_output(node, nodes.bake_model(node), final=True)
        finished = []
        finish_save = grades.finish_save
        def finish_when_available():
            self.assertTrue(_component('graph.output_guard').available())
            finished.append(True)
            return finish_save()
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(lut, 'cpu_baker', side_effect=AssertionError('Saved output recalculated')), \
                patch.object(lut.resources, 'transfer_payload', side_effect=AssertionError('Saved output rewritten')), \
                patch.object(lut.resources, 'read_pixels', side_effect=AssertionError('Saved output inspected')), \
                patch.object(grades, 'finish_save', side_effect=finish_when_available):
            path = str(Path(directory) / 'complete.blend')
            self.assertEqual(output.guarded_save(path), {'FINISHED'})
            self.assertTrue(finished)
            self.assertFalse(grades._saving)
            current = bpy.data.node_groups[tree_name].nodes[node_name]
            self.assertTrue(lut.is_adopted(current))
            self.assertEqual(json.loads(current[lut.MANIFEST]),expected)
            bpy.ops.wm.open_mainfile(filepath=path)
            for _ in range(100):
                nodes.recovery_tick()
                if nodes.recovery_status()['state'] in ('completed','failed'):break
            self.assertEqual(nodes.recovery_status()['state'],'completed',nodes.recovery_status())
            current = bpy.data.node_groups[tree_name].nodes[node_name]
            self.assertTrue(lut.is_adopted(current))
            self.assertEqual(json.loads(current[lut.MANIFEST]),expected)
            grades.prepare_disable()
            current = bpy.data.node_groups[tree_name].nodes[node_name]
            self.assertEqual(current.bl_idname, 'CompositorNodeGroup')

