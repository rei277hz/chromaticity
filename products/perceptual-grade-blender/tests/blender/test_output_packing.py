"""Internal LUT persistence stays separate from numerical completion."""
from tests.support.session import component as _component, SessionTest, patch
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

import bpy
import numpy as np

gpu = _component('graph.gpu'); lut = _component('graph.lut'); nodes = _component('graph.nodes'); output_guard = _component('graph.output_guard'); resources = _component('graph.output_resources')
from tests.support.blender import BlenderTest


class NativePackingHelperTests(SessionTest):
    def test_silent_native_pack_failure_requires_observable_success(self):
        for packed_file, dirty in ((None, False), (SimpleNamespace(size=0), False),
                                   (SimpleNamespace(size=12), True)):
            with self.subTest(packed_file=packed_file, dirty=dirty):
                image = SimpleNamespace(pack=Mock(return_value=None), packed_file=packed_file,
                                        is_dirty=dirty, library=None, is_evaluated=False)
                with self.assertRaises(RuntimeError):
                    resources.pack_image(image)
                image.pack.assert_called_once_with()

    def test_native_pack_exception_is_not_reported_as_success(self):
        image = SimpleNamespace(pack=Mock(side_effect=RuntimeError('Native pack failed')),
                                packed_file=SimpleNamespace(size=12), is_dirty=True,
                                library=None, is_evaluated=False)
        with self.assertRaisesRegex(RuntimeError, 'Native pack failed'):
            resources.pack_image(image)


class OutputPackingTests(BlenderTest):
    def setUp(self):
        super().setUp()
        acquire = patch.object(gpu, 'acquire', return_value=(None, None))
        acquire.start()
        self.addCleanup(acquire.stop)

    def node(self, tree_type='CompositorNodeTree', *, complete=False):
        tree = bpy.data.node_groups.new('Packing output', tree_type)
        node = nodes.create_grade(tree)
        if complete:
            nodes.write_chromatic(node, {'global_gain': .1})
            lut.ensure(node, nodes.bake_model(node), force=True)
            lut.validate_output(node, nodes.bake_model(node), final=True)
        return node

    @staticmethod
    def pixels(image):
        values = np.empty(len(image.pixels), np.float32)
        image.pixels.foreach_get(values)
        return values

    def assert_packed(self, image):
        self.assertFalse(image.is_dirty)
        self.assertIsNotNone(image.packed_file)
        self.assertGreater(image.packed_file.size, 0)

    def candidate(self, node, gain=.2):
        nodes.write_chromatic(node, {'global_gain': gain})
        baker = lut._states[node.as_pointer()]['baker']
        baker.finish()
        return baker

    @staticmethod
    def links(node):
        return tuple((item.as_pointer(), item.image.as_pointer())
                     for item in node.node_tree.nodes if item.get('_pg_cube_image'))

    def colliding_records(self):
        left, right = self.node(), self.node()
        records = [resources.record(node.node_tree, node) for node in (left, right)]
        incarnation = max(record['state'].incarnation for record in records)
        for record in records:
            while record['state'].incarnation < incarnation:
                resources.dispatch(record, 'invalidate', incarnation=record['state'].incarnation)
        # Invalidation and each write consume operation counters independently.
        # Reach a real collision through accepted events, without replacing state.
        operation = max(record['state'].operation for record in records)
        with output_guard.publication():
            for node, record in zip((left, right), records):
                while record['state'].operation < operation:
                    token = resources.reserve(node, 33, 'a' * 64)
                    resources.receipt(node, 'fail', token)
        return left, right, records

    def test_same_app_colliding_payload_receipts_cannot_cross_stores(self):
        left, right, records = self.colliding_records()
        with output_guard.publication():
            first = resources.reserve(left, 33, 'a' * 64)
            second = resources.reserve(right, 33, 'a' * 64)
            self.assertEqual({key: value for key, value in first.items() if key not in ('store', 'operation_id')},
                             {key: value for key, value in second.items() if key not in ('store', 'operation_id')})
            self.assertNotEqual(first['store'], second['store'])
            image = resources.bank_images(right)[second['index']]
            saved, pixels = image.get(resources.RECORD), self.pixels(image)
            states = [record['state'] for record in records]
            with patch.object(resources, '_write_record') as write, \
                    patch.object(resources, 'pack_image') as pack, \
                    patch.object(resources, 'validate_pixels') as validate, \
                    patch.object(resources, 'dispatch') as dispatch:
                actions = (
                    lambda: resources.arm(right, first, image),
                    lambda: resources.receipt(right, 'armed', first, validated=True),
                    lambda: resources.ensure_packed(right, first['index'], first),
                    lambda: resources.transfer_payload(image, pixels, SimpleNamespace(signature=first['source']),
                                                       {}, node=right, reservation=first),
                )
                for action in actions:
                    with self.assertRaisesRegex(RuntimeError, 'another Store'):
                        action()
                for effect in (write, pack, validate, dispatch):
                    effect.assert_not_called()
            self.assertEqual([record['state'] for record in records], states)
            self.assertEqual(image.get(resources.RECORD), saved)
            np.testing.assert_array_equal(self.pixels(image).view(np.uint32), pixels.view(np.uint32))
            # Even an otherwise current token cannot write a peer bank's Image.
            with self.assertRaisesRegex(RuntimeError, 'target differs'):
                resources.arm(left, first, image)
            self.assertEqual([record['state'] for record in records], states)
            self.assertEqual(image.get(resources.RECORD), saved)
            self.assertNotEqual(first['operation_id'], second['operation_id'])
            resources.arm(left, first, resources.bank_images(left)[first['index']])
            self.assertNotIn('store', resources.payload_record(resources.bank_images(left)[first['index']]))

    def test_graph_receipts_bind_exact_store_even_when_semantics_collide(self):
        left, right, records = self.colliding_records()
        with output_guard.publication():
            operation = max(record['state'].graph_operation for record in records)
            for node, record in zip((left, right), records):
                while record['state'].graph_operation < operation:
                    token = resources.graph_begin(node, -1, 0, 0)
                    resources.graph_receipt(node, 'graph_fail', token)
            first = resources.graph_begin(left, -1, 0, 0)
            second = resources.graph_begin(right, -1, 0, 0)
            self.assertEqual({key: value for key, value in first.items() if key != 'store'},
                             {key: value for key, value in second.items() if key != 'store'})
            states = [record['state'] for record in records]
            with patch.object(resources, 'dispatch') as dispatch:
                with self.assertRaisesRegex(RuntimeError, 'another Store'):
                    resources.graph_receipt(right, 'fallback', first, validated=True)
                dispatch.assert_not_called()
            self.assertEqual([record['state'] for record in records], states)
            resources.graph_receipt(right, 'fallback', second, validated=True)

    def test_payload_owner_rejects_foreign_session_stale_store_and_scalar_aliases(self):
        node = self.node()
        other = type(self.session)(self.session.machines)
        self.addCleanup(other.close)
        foreign_resources = other.component('graph.output_resources')
        with other.component('graph.output_guard').publication():
            foreign = foreign_resources.reserve(node, 33, 'a' * 64)
        class IntegerAlias(int):
            pass
        class StringAlias(str):
            pass
        with output_guard.publication():
            token = resources.reserve(node, 33, 'a' * 64)
            image = resources.bank_images(node)[token['index']]
            invalid = [foreign, {key: value for key, value in token.items() if key != 'store'}]
            invalid.extend(dict(token, store=value) for value in
                           (True, str(token['store']), IntegerAlias(token['store'])))
            invalid.append(dict(token, session=StringAlias(token['session'])))
            invalid.append(dict(token, incarnation=IntegerAlias(token['incarnation'])))
            saved = image.get(resources.RECORD)
            state = resources.record(node.node_tree, node)['state']
            for value in invalid:
                with self.assertRaisesRegex(RuntimeError, 'another Store'):
                    resources.arm(node, value, image)
            self.assertEqual(resources.record(node.node_tree, node)['state'], state)
            self.assertEqual(image.get(resources.RECORD), saved)
            for index in (True, IntegerAlias(token['index']), -1, 4):
                with self.assertRaisesRegex(RuntimeError, 'target differs|no longer current'):
                    resources.arm(node, dict(token, index=index), image)
            self.assertEqual(resources.record(node.node_tree, node)['state'], state)
            self.assertEqual(image.get(resources.RECORD), saved)
            with self.assertRaisesRegex(RuntimeError, 'operation identity'):
                resources.arm(node, {key: value for key, value in token.items()
                                     if key != 'operation_id'}, image)
            resources.clear()
            replacement = resources.record(node.node_tree, node)
            self.assertNotEqual(replacement['store'].identity, token['store'])
            state = replacement['state']
            with self.assertRaisesRegex(RuntimeError, 'another Store'):
                resources.arm(node, token, image)
            self.assertEqual(replacement['state'], state)
            self.assertEqual(image.get(resources.RECORD), saved)

    def test_initial_and_copied_banks_are_packed_with_independent_storage(self):
        for kind in ('ShaderNodeTree', 'CompositorNodeTree'):
            with self.subTest(kind=kind):
                node = self.node(kind)
                original = resources.bank_images(node)
                for image in original.values():
                    self.assert_packed(image)
                nodes.write_chromatic(node, {'global_gain': .1})
                lut.ensure(node, nodes.bake_model(node), force=True)
                before = self.links(node)
                copied = lut.clone_kernel(node.node_tree)
                owner = node.id_data.nodes.new('ShaderNodeGroup' if kind == 'ShaderNodeTree'
                                               else 'CompositorNodeGroup')
                owner.node_tree = copied
                clone = resources.bank_images(owner)
                for index, image in original.items():
                    self.assert_packed(image)
                    self.assert_packed(clone[index])
                    self.assertNotEqual(image.as_pointer(), clone[index].as_pointer())
                    np.testing.assert_array_equal(self.pixels(image), self.pixels(clone[index]))
                self.assertEqual(self.links(node), before)

    def test_repeated_preview_and_final_publications_keep_every_bank_clean(self):
        for kind in ('ShaderNodeTree', 'CompositorNodeTree'):
            with self.subTest(kind=kind):
                node = self.node(kind, complete=True)
                before = self.links(node)
                images = {image.as_pointer() for image in bpy.data.images}
                # A final cached by the other adapter must not suppress this
                # case's intentional preview/final publication sequence.
                offset = 0. if kind == 'ShaderNodeTree' else 1.
                for gain in (.2 + offset, .3 + offset):
                    baker = self.candidate(node, gain)
                    self.assertTrue(lut.publish(node, baker, force=True, preview=True))
                    self.assertTrue(lut.publish(node, baker, force=True))
                    for image in resources.bank_images(node).values():
                        self.assert_packed(image)
                    self.assertEqual(self.links(node), before)
                    self.assertEqual({image.as_pointer() for image in bpy.data.images}, images)
                    lut.validate_output(node, nodes.bake_model(node), final=True)

    def test_authorized_cached_model_rewrites_externally_edited_old_bank(self):
        node = self.node(complete=True)
        original = lut.image_for(node)
        expected = self.pixels(original)
        old_operation = resources.payload_record(original)['operation_id']
        baker = self.candidate(node, .2)
        self.assertTrue(lut.publish(node, baker, force=True))
        self.assertNotEqual(lut.image_for(node), original)
        edited = self.pixels(original)
        edited[0] = .875
        original.pixels.foreach_set(edited)
        original.update()
        with patch.object(resources, 'transfer_payload', wraps=resources.transfer_payload) as transfer, \
                patch.object(resources, 'read_pixels', side_effect=AssertionError('Bank content inspection')), \
                patch.object(resources, 'pixel_digest', side_effect=AssertionError('Bank content hash')):
            nodes.write_chromatic(node, {'global_gain': .1})
            lut.ensure(node, nodes.bake_model(node), force=True)
        self.assertGreaterEqual(transfer.call_count, 1)
        self.assertEqual(lut.image_for(node), original)
        self.assertNotEqual(resources.payload_record(original)['operation_id'], old_operation)
        np.testing.assert_array_equal(self.pixels(original), expected)

    def test_first_deliberate_reservation_protects_current_native_selection(self):
        node = self.node(complete=True)
        intent = nodes.output_intent(node)
        lut.adopt_native(node, intent)
        resources.selector_socket(node).default_value = 3.
        self.assertTrue(lut.request_intent(node, intent, explicit=True))
        with output_guard.publication():
            token = resources.reserve(node, 65, 'next-model')
            self.assertEqual(token['index'], 2)
            self.assertEqual(resources.record(node.node_tree,node)['state'].protected, 3)
            self.assertEqual(resources.selected_index(node), 3)
            resources.receipt(node, 'fail', token)

    def test_completion_follows_packing_without_payload_readback(self):
        node = self.node(complete=True)
        baker = self.candidate(node)
        original = resources.pack_image
        seen = []
        def pack(image):
            saved = resources.payload_record(image)
            self.assertEqual(saved['phase'], 'WRITING')
            seen.append(saved['operation_id'])
            original(image)
        with patch.object(resources, 'pack_image', side_effect=pack), \
                patch.object(resources, 'read_pixels', side_effect=AssertionError('Producer readback')), \
                patch.object(resources, 'pixel_digest', side_effect=AssertionError('Producer hashing')), \
                patch.object(lut, 'read_cube', side_effect=AssertionError('Producer native decoding')):
            self.assertTrue(lut.publish(node, baker, force=True))
        saved = resources.payload_record(lut.image_for(node))
        self.assertEqual(saved['phase'], 'COMPLETE')
        self.assertEqual(saved['operation_id'], seen[0])
        self.assertEqual(saved['revision'], seen[0])
        self.assert_packed(lut.image_for(node))

    def test_failed_pack_leaves_writing_token_and_retry_has_new_operation(self):
        node = self.node(complete=True)
        baker = self.candidate(node)
        prior = lut._graph_snapshot(node)
        touched = []
        def fail(image):
            touched.append(image)
            raise RuntimeError('Injected native packing failure')
        with patch.object(resources, 'pack_image', side_effect=fail):
            with self.assertRaisesRegex(RuntimeError, 'Injected native packing failure'):
                lut.publish(node, baker, force=True)
        image = touched[0]
        saved = resources.payload_record(image)
        self.assertEqual(saved['phase'], 'WRITING')
        self.assertEqual(lut._graph_snapshot(node), prior)
        index = next(index for index, bank in resources.bank_images(node).items() if bank == image)
        slot = resources.record(node.node_tree, node)['state'].slots[index]
        self.assertFalse(slot.valid)
        self.assertTrue(slot.debt)
        with patch.object(resources, 'read_pixels', side_effect=AssertionError('Retry readback')), \
                patch.object(resources, 'pixel_digest', side_effect=AssertionError('Retry hashing')):
            lut.ensure(node, nodes.bake_model(node), force=True)
        completed = resources.payload_record(lut.image_for(node))
        self.assertEqual(completed['phase'], 'COMPLETE')
        self.assertNotEqual(completed['operation_id'], saved['operation_id'])

    def test_partial_transfer_remains_unclaimed_and_preserves_native_selection(self):
        node = self.node(complete=True)
        baker = self.candidate(node)
        prior = lut._graph_snapshot(node)
        touched = []
        def partial(image, pixels, _cube, _report, **kwargs):
            touched.append(kwargs['reservation']['index'])
            current = self.pixels(image)
            current[:len(current)//2] = np.asarray(pixels).ravel()[:len(current)//2]
            image.pixels.foreach_set(current)
            image.update()
            raise RuntimeError('Interrupted pixel transfer')
        with patch.object(resources, 'transfer_payload', side_effect=partial), \
                patch.object(resources, 'read_pixels', side_effect=AssertionError('Failure inspection')), \
                patch.object(resources, 'pack_image', side_effect=AssertionError('Partial result packing')):
            with self.assertRaisesRegex(RuntimeError, 'Interrupted pixel transfer'):
                lut.publish(node, baker, force=True)
        index = touched[0]
        image = resources.bank_images(node)[index]
        self.assertEqual(resources.payload_record(image)['phase'], 'WRITING')
        slot = resources.record(node.node_tree, node)['state'].slots[index]
        self.assertFalse(slot.valid)
        self.assertTrue(slot.debt)
        self.assertEqual(slot.readability, resources.policy.UNKNOWN)
        self.assertEqual(lut._graph_snapshot(node), prior)

    def test_external_dirty_bank_is_preserved_by_idle_and_save(self):
        node = self.node(complete=True)
        prior = lut._graph_snapshot(node)
        image = resources.bank_images(node)[0]
        values = self.pixels(image)
        values[0] = .375
        image.pixels.foreach_set(values)
        image.update()
        lut.adopt_native(node, nodes.output_intent(node))
        with patch.object(resources, 'pack_image', side_effect=AssertionError('External packing')), \
                patch.object(resources, 'transfer_payload', side_effect=AssertionError('External rewrite')), \
                patch.object(resources, 'read_pixels', side_effect=AssertionError('External inspection')):
            nodes.refresh_node(node, force=True)
            lut.ensure(node, nodes.bake_model(node), force=True)
            resources.pack_output(node)
        self.assertEqual(lut._graph_snapshot(node), prior)
        np.testing.assert_array_equal(self.pixels(image), values)
        self.assertTrue(image.is_dirty)

    def test_native_adoption_preserves_externally_edited_bank(self):
        node = self.node(complete=True)
        selected = resources.selected_index(node)
        image = resources.bank_images(node)[selected]
        values = self.pixels(image)
        values[3] = .5
        image.pixels.foreach_set(values)
        image.update()
        saved = image.get(resources.RECORD)
        with patch.object(resources, 'read_pixels', side_effect=AssertionError('Adoption inspection')), \
                patch.object(resources, 'pack_image', side_effect=AssertionError('Adoption packing')), \
                patch.object(resources, 'transfer_payload', side_effect=AssertionError('Adoption write')):
            lut.adopt_native(node, nodes.output_intent(node))
            lut.ensure(node, nodes.bake_model(node), force=True)
        np.testing.assert_array_equal(self.pixels(image), values)
        self.assertEqual(image.get(resources.RECORD), saved)
        self.assertEqual(resources.selected_index(node), selected)
        self.assertTrue(lut.is_adopted(node))
        self.assertFalse(resources.record(node.node_tree,node)['state'].graph_valid)

    def test_unused_clean_unpacked_legacy_bank_is_not_rewritten(self):
        node = self.node(complete=True)
        index = next(index for index in range(4) if index != resources.selected_index(node))
        old = resources.bank_images(node)[index]
        image = bpy.data.images.new('Legacy generated bank', width=old.size[0], height=old.size[1],
                                    float_buffer=True, alpha=True)
        image.colorspace_settings.name = 'Non-Color'
        image.alpha_mode = 'CHANNEL_PACKED'
        image.file_format = 'OPEN_EXR'
        for name in ('_pg_cube_schema', '_pg_cube_size', '_pg_cube_encoding', resources.SLOT):
            image[name] = old[name]
        textures = [item for item in node.node_tree.nodes if item.get('_pg_cube_image')
                    and item.get(resources.SLOT) == index]
        for item in textures:
            item.image = image
        before = self.pixels(image)
        self.assertFalse(image.is_dirty)
        self.assertIsNone(image.packed_file)
        try:
            with patch.object(lut, 'cpu_baker', side_effect=AssertionError('Legacy bank recalculated')), \
                    patch.object(resources, 'transfer_payload', side_effect=AssertionError('Legacy bank rewritten')), \
                    patch.object(resources, 'read_pixels', side_effect=AssertionError('Legacy bank read')), \
                    patch.object(resources, 'pack_image', side_effect=AssertionError('Clean legacy bank packed')):
                self.assertIsNone(lut.adopt_native(node,nodes.output_intent(node)))
            np.testing.assert_array_equal(self.pixels(image), before)
            self.assertFalse(image.is_dirty)
            self.assertIsNone(image.packed_file)
            self.assertEqual(image.source, 'GENERATED')
        finally:
            for item in textures:
                item.image = old

    def test_shared_kernel_and_image_aliases_refuse_dirty_packing(self):
        node = self.node('ShaderNodeTree')
        index = 0
        image = resources.bank_images(node)[index]
        values = self.pixels(image)
        values[0] = .125
        image.pixels.foreach_set(values)
        image.update()
        original_pack = bytes(image.packed_file.data)
        for kind in ('kernel', 'image'):
            with self.subTest(kind=kind):
                alias = node.id_data.nodes.new('ShaderNodeGroup' if kind == 'kernel' else 'ShaderNodeTexImage')
                if kind == 'kernel':
                    alias.node_tree = node.node_tree
                else:
                    alias.image = image
                try:
                    with output_guard.publication(), \
                            patch.object(resources, 'pack_image', side_effect=AssertionError('Shared bank packed')):
                        with self.assertRaises(RuntimeError):
                            resources.ensure_packed(node, index)
                    self.assertTrue(image.is_dirty)
                    self.assertEqual(bytes(image.packed_file.data), original_pack)
                    np.testing.assert_array_equal(self.pixels(image), values)
                finally:
                    node.id_data.nodes.remove(alias)

    def test_dirty_linked_bank_refuses_packing(self):
        node = self.node('ShaderNodeTree')
        index = 0
        original = resources.bank_images(node)[index]
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'bank.blend'
            bpy.data.libraries.write(str(path), {original})
            with bpy.data.libraries.load(str(path), link=True) as (available, loaded):
                loaded.images = [original.name]
            image = loaded.images[0]
            self.assertIsNotNone(image.library)
            textures = [item for item in node.node_tree.nodes if item.get('_pg_cube_image')
                        and item.get(resources.SLOT) == index]
            for item in textures:
                item.image = image
            try:
                values = self.pixels(image)
                values[0] = .125
                image.pixels.foreach_set(values)
                image.update()
                self.assertTrue(image.is_dirty)
                before = bytes(image.packed_file.data)
                with output_guard.publication(), \
                        patch.object(resources, 'pack_image', side_effect=AssertionError('Linked bank packed')):
                    with self.assertRaises(RuntimeError):
                        resources.ensure_packed(node, index)
                self.assertEqual(bytes(image.packed_file.data), before)
                np.testing.assert_array_equal(self.pixels(image), values)
            finally:
                for item in textures:
                    item.image = original

    def test_packing_does_not_touch_unrelated_dirty_user_images(self):
        user = bpy.data.images.new('User paint', width=8, height=8, float_buffer=True)
        values = np.full(len(user.pixels), .125, np.float32)
        user.pixels.foreach_set(values)
        user.update()
        node = self.node(complete=True)
        resources.pack_output(node)
        self.assertTrue(user.is_dirty)
        self.assertIsNone(user.packed_file)
        np.testing.assert_array_equal(self.pixels(user), values)

    def test_packed_bank_reload_preserves_float32_bits_and_image_links(self):
        for kind in ('ShaderNodeTree', 'CompositorNodeTree'):
            with self.subTest(kind=kind):
                node = self.node(kind)
                links = self.links(node)
                with output_guard.publication():
                    for index, image in resources.bank_images(node).items():
                        values = self.pixels(image)
                        rgba = values.reshape(-1, 4)
                        rgba[:, :3] = np.asarray((.125, -.375, .625), np.float32)
                        rgba[:, 3] = -3. if kind == 'CompositorNodeTree' else 1.
                        values[0] = np.nextafter(np.float32(0), np.float32(1))
                        values[4] = np.float32(-0.)
                        image.pixels.foreach_set(values)
                        image.update()
                        resources.pack_image(image)
                        self.assert_packed(image)
                        image.buffers_free()
                        np.testing.assert_array_equal(self.pixels(image).view(np.uint32), values.view(np.uint32))
                self.assertEqual(self.links(node), links)
