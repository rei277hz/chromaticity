"""Operation ordering, non-observation and non-retention recorder premises."""
from tests.support.session import component as _component, SessionTest, patch
from importlib.machinery import SourceFileLoader
from importlib.resources import files
from importlib.util import module_from_spec, spec_from_loader
import gc
import json
import os
from pathlib import Path
import sys
import tempfile
pass
import weakref

import bpy
grades = _component('graph.grades'); lut = _component('graph.lut'); nodes = _component('graph.nodes')
from tests.support.session import current_session
from tests.support.blender import BlenderTest


class UndoTraceLifetimeTests(BlenderTest):
    def setUp(self):
        super().setUp()
        self.script = str(files('tests.blender') / 'pg_undo_trace.py')
        loader = SourceFileLoader('_pg_undo_trace_lifetime_test', self.script)
        self.trace = module_from_spec(spec_from_loader(loader.name, loader))
        loader.exec_module(self.trace)
        self.previous_state = sys.modules.get(self.trace._STATE_MODULE)
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)

    def tearDown(self):
        try:
            self.trace.stop()
            if self.previous_state is None:
                sys.modules.pop(self.trace._STATE_MODULE, None)
            else:
                sys.modules[self.trace._STATE_MODULE] = self.previous_state
        finally:
            super().tearDown()

    def install(self, name='capture', capture_console=False):
        return self.trace.install(output_dir=self.root / name, interval=0,
                                  capture_console=capture_console)

    def records(self, directory):
        return [json.loads(line) for line in (directory / 'events.jsonl').read_text().splitlines()]

    def node(self):
        owner = bpy.data.node_groups.new('Trace lifetime owner', 'ShaderNodeTree')
        node = owner.nodes.new(grades.KINDS['ShaderNodeTree'])
        kernel = bpy.data.node_groups.new('Trace lifetime kernel', 'ShaderNodeTree')
        node.node_tree = kernel
        return node, kernel

    def texture(self, kernel, name):
        image = bpy.data.images.new(name, width=1, height=1)
        item = kernel.nodes.new('ShaderNodeTexImage')
        item['_pg_cube_image'] = True
        item.image = image
        return item, image

    def assert_operation_only(self, records):
        forbidden_fields = {'locals', 'result', 'exception_type', 'identity', 'python_type',
                            'python_id', 'resources', 'probe_suppressed'}
        for row in records:
            self.assertFalse(forbidden_fields.intersection(row), row)
            self.assertNotIn(row['event'], {'local_observation', 'resource_probe_begin',
                                           'resource_probe_end'})

    def test_image_lookup_and_adoption_keep_call_relationships_without_identities(self):
        node, kernel = self.node()
        _, image = self.texture(kernel, 'Invalid restored LUT premise')
        path = self.install()
        # An arbitrary image has no runtime producer receipt. Recovery adopts
        # its native graph without inspecting that image or rebuilding banks.
        self.assertIsNone(lut.image_for(node))
        self.assertIsNone(lut.adopt_native(node,nodes.output_intent(node)))
        records = self.records(path)
        self.assert_operation_only(records)
        entries = {row['call_id']: row for row in records if row['event'] == 'function_enter'}
        lookup = next(row for row in entries.values()
                      if row['function'] == 'graph.lut.image_for')
        self.assertTrue(any(row['event'] == 'return_requested'
                            and row['call_id'] == lookup['call_id'] for row in records))
        adoption = next(row for row in entries.values()
                        if row['function'] == 'graph.output_resources.adopt_native')
        runtime = entries[adoption['parent_call_id']]
        self.assertEqual(runtime['function'], 'graph.lut.adopt_native')
        self.assertFalse(any(row['function'] == 'graph.output_resources.bank_images'
                             for row in entries.values()))

    def test_removed_aliases_are_never_observed_in_parent_or_new_child(self):
        _, kernel = self.node()
        texture, image = self.texture(kernel, 'Retired parent alias premise')

        def read_cube(image):
            return id(image)

        def publish(image, texture):
            old = image
            current_session().app.blender.native.remove_image(image)
            texture.image = None
            return lut.read_cube(old) == id(old)

        with patch.object(lut, 'publish', publish), patch.object(lut, 'read_cube', read_cube):
            path = self.install()
            self.assertTrue(lut.publish(image, texture))
            records = self.records(path)
        self.assert_operation_only(records)
        entered = [row for row in records if row['event'] == 'function_enter']
        publisher = next(row for row in entered if row['function'] == 'graph.lut.publish')
        removal = next(row for row in entered if row['function'] == 'blender_runtime.blender.native.remove_image')
        self.assertIsNone(publisher['parent_call_id'])
        self.assertEqual(removal['parent_call_id'], publisher['call_id'])
        child = next(row for row in entered if row['function'] == 'graph.lut.read_cube')
        self.assertEqual(child['parent_call_id'], publisher['call_id'])
        self.assertTrue(any(row['event'] == 'native_operation_before'
                            and row['call_id'] == publisher['call_id'] for row in records))

    def test_one_line_native_store_loops_mark_each_operation_and_completion(self):
        node, kernel = self.node()
        image_pairs = [self.texture(kernel, 'Restore image ' + str(index)) for index in range(2)]
        address_pairs = []
        for index in range(2):
            item = kernel.nodes.new('ShaderNodeGroup')
            helper = bpy.data.node_groups.new('Restore helper ' + str(index), 'ShaderNodeTree')
            address_pairs.append((item, helper))
        snapshot = dict(images=image_pairs, addresses=address_pairs, route=None,
                        rows={}, manifest=None, pending=None)
        # Production rollback now restores scalar values only. Keep native
        # one-line loops as a recorder fixture, with real Blender properties.
        def restore_graph(node, snapshot):
            for item, image in snapshot['images']:item.image = image
            for item, helper in snapshot['addresses']:item.node_tree = helper

        with patch.object(lut, '_restore_graph', restore_graph):
            path = self.install()
            lut._restore_graph(node, snapshot)
            records = self.records(path)
        self.assert_operation_only(records)
        stores = [row for row in records if row['event'] == 'native_operation_before'
                  and row.get('function') == 'graph.lut._restore_graph'
                  and row['operation']['op'] == 'STORE_ATTR']
        self.assertEqual([row['operation']['attribute'] for row in stores],
                         ['image', 'image', 'node_tree', 'node_tree'])
        for index, before in enumerate(stores):
            limit = stores[index + 1]['sequence'] if index + 1 < len(stores) else float('inf')
            completed = [row for row in records if row['event'] == 'native_operation_returned'
                         and row['call_id'] == before['call_id']
                         and row['instruction'] == before['instruction']
                         and before['sequence'] < row['sequence'] < limit]
            self.assertEqual(len(completed), 1)
        self.assertEqual([item.image for item, _ in image_pairs], [image for _, image in image_pairs])
        self.assertEqual([item.node_tree for item, _ in address_pairs],
                         [helper for _, helper in address_pairs])

    def test_hostile_local_return_and_exception_objects_are_never_inspected(self):
        attempted = []

        class HostileType(type):
            def __getattribute__(cls, name):
                if name == '__name__':
                    attempted.append('type-name')
                    raise AssertionError('No diagnostic type name reads')
                return super().__getattribute__(name)

        class Hostile(metaclass=HostileType):
            def __getattribute__(self, name):
                attempted.append(name)
                raise AssertionError('No diagnostic instance reads')

            def __repr__(self):
                attempted.append('repr')
                raise AssertionError('No diagnostic repr')

            def __str__(self):
                attempted.append('str')
                raise AssertionError('No diagnostic str')

        class HostileError(Exception, metaclass=HostileType):
            def __getattribute__(self, name):
                attempted.append('exception:' + name)
                raise AssertionError('No diagnostic exception reads')

        def publish(image):
            return image

        def adopt_native(image, raising=False):
            old = image
            if raising:
                raise HostileError()
            return lut.publish(old)

        with patch.object(lut, 'publish', publish), patch.object(lut, 'adopt_native', adopt_native):
            path = self.install()
            payload = Hostile()
            self.assertIs(lut.adopt_native(payload), payload)
            caught = False
            try:
                lut.adopt_native(payload, True)
            except HostileError:
                caught = True
            self.assertTrue(caught)
            records = self.records(path)
        self.assertEqual(attempted, [])
        self.assert_operation_only(records)
        self.assertTrue(any(row['event'] == 'python_raise' for row in records))
        self.assertTrue(any(row['event'] == 'python_unwind' for row in records))
        self.assertTrue(any(row['event'] == 'return_requested' for row in records))

    def test_operation_before_precedes_property_entry_and_failed_operation_is_not_returned(self):
        observed = []
        holder = {}

        class Texture:
            @property
            def image(self):
                return None

            @image.setter
            def image(self, value):
                observed.extend(self_records(holder['path']))
                raise ValueError('native setter failure premise')

        self_records = self.records

        def publish(texture):
            texture.image = None

        with patch.object(lut, 'publish', publish):
            path = self.install()
            holder['path'] = path
            with self.assertRaisesRegex(ValueError, 'native setter failure premise'):
                lut.publish(Texture())
            records = self.records(path)
        before = next(row for row in observed if row['event'] == 'native_operation_before')
        outcomes = [row for row in records if row['event'] in
                    ('native_operation_returned', 'native_operation_raised')
                    and row['call_id'] == before['call_id']
                    and row['instruction'] == before['instruction']]
        self.assertEqual([row['event'] for row in outcomes], ['native_operation_raised'])
        self.assertEqual(outcomes[0]['mutation_outcome'], 'unknown')
        self.assertGreater(outcomes[0]['sequence'], before['sequence'])
        self.assert_operation_only(records)

    def test_return_and_exception_events_do_not_retain_the_observed_frame_locals(self):
        references = []

        class Payload:
            pass

        def adopt_native(raising=False):
            node = Payload()
            references.append(weakref.ref(node))
            if raising:
                raise RuntimeError('Trace retention premise')
            return None

        with patch.object(lut, 'adopt_native', adopt_native):
            path = self.install()
            lut.adopt_native()
            with self.assertRaisesRegex(RuntimeError, 'Trace retention premise'):
                lut.adopt_native(True)
            gc.collect()
            # A captured frame, f_locals proxy or exception traceback would
            # keep its Payload alive even while the recorder is still active.
            self.assertEqual(len(references), 2)
            self.assertTrue(all(reference() is None for reference in references))
            records = self.records(path)
        self.assertTrue(any(row['event'] == 'return_requested' for row in records))
        self.assertTrue(any(row['event'] == 'python_unwind' for row in records))
        state = sys.modules[self.trace._STATE_MODULE].trace
        self.assertTrue(all(not calls for calls in state.calls.values()))

    def test_console_byte_positions_bracket_flushed_native_output(self):
        path = self.install(capture_console=True)
        state = sys.modules[self.trace._STATE_MODULE].trace
        message = b'Native ID user decrement diagnostic premise\n'
        state.emit('native_console_test_before')
        os.write(2, message)
        state.emit('native_console_test_after')
        records = self.records(path)
        before = next(row for row in records if row['event'] == 'native_console_test_before')
        after = next(row for row in records if row['event'] == 'native_console_test_after')
        self.assertGreaterEqual(after['console_bytes'] - before['console_bytes'], len(message))
        captured = (path / 'console.log').read_bytes()
        self.assertIn(message, captured[before['console_bytes']:after['console_bytes']])
        self.assertLess(before['monotonic_ns'], after['monotonic_ns'])

    def test_suspended_generator_does_not_steal_its_callers_identity(self):
        node, kernel = self.node()
        self.texture(kernel, 'Generator caller premise')

        def publish():
            iterator = (value for value in ('first', 'second'))
            first = next(iterator)
            lut.image_for(node)
            second = next(iterator)
            lut.image_for(node)
            return first, second

        with patch.object(lut, 'publish', publish):
            path = self.install()
            self.assertEqual(lut.publish(), ('first', 'second'))
            records = self.records(path)
        entries = [row for row in records if row['event'] == 'function_enter']
        publisher = next(row for row in entries if row['function'] == 'graph.lut.publish')
        self.assertFalse(any('<genexpr>' in row['function'] for row in entries))
        lookups = [row for row in entries if row['function'] == 'graph.lut.image_for']
        self.assertEqual(len(lookups), 2)
        self.assertTrue(all(row['parent_call_id'] == publisher['call_id'] for row in lookups))
        state = sys.modules[self.trace._STATE_MODULE].trace
        self.assertTrue(all(not calls for calls in state.calls.values()))

    def test_boundary_generations_change_for_native_replacement_but_not_save(self):
        path = self.install()
        state = sys.modules[self.trace._STATE_MODULE].trace
        expected_generation = 0
        for name in ('undo_pre', 'undo_post', 'redo_pre', 'redo_post', 'load_pre',
                     'load_post', 'save_pre', 'save_post', 'save_post_fail'):
            observers = [callback for boundary, callback in state.hooks if boundary == name]
            self.assertEqual(len(observers), 2, name)
            if name in ('undo_pre', 'redo_pre', 'load_pre'):
                expected_generation += 1
            # Do not invoke production pre/post handlers without actual native
            # replacement; only the independent recorder observers run here.
            for observer in observers:
                observer(None)
            events = [row for row in self.records(path) if row['event'] in
                      ('boundary_' + name + '_enter', 'boundary_' + name + '_completed')]
            self.assertEqual([row['generation'] for row in events],
                             [expected_generation, expected_generation], name)
            self.assertEqual(events[0]['boundary_id'], events[1]['boundary_id'])
        self.assertEqual(state.generation, 3)

    def test_native_boundary_preserves_operation_markers_without_observing_aliases(self):
        _, kernel = self.node()
        texture, image = self.texture(kernel, 'Boundary parent alias premise')

        def publish(image, texture, boundary_observer):
            old = image
            boundary_observer(None)
            # Real replacement could already have invalidated old and image.
            # Here the objects remain valid so this premise is safe to run.
            texture.image = None
            return True

        with patch.object(lut, 'publish', publish):
            path = self.install()
            state = sys.modules[self.trace._STATE_MODULE].trace
            observer = next(callback for boundary, callback in state.hooks if boundary == 'undo_pre')
            self.assertTrue(lut.publish(image, texture, observer))
            records = self.records(path)
        publisher = next(row for row in records if row['event'] == 'function_enter'
                         and row.get('function') == 'graph.lut.publish')
        boundary = next(row for row in records if row['event'] == 'boundary_undo_pre_enter')
        operations = [row for row in records if row['event'] == 'native_operation_before'
                      and row['call_id'] == publisher['call_id']]
        self.assertEqual(len(operations), 1)
        self.assert_operation_only(records)
        self.assertGreater(operations[0]['generation'], publisher['generation'])
        self.assertGreater(operations[0]['sequence'], boundary['sequence'])

    def test_text_editor_execution_keeps_recorder_and_operation_code_identity(self):
        # Blender Text Editor commonly omits __file__. Hashing the loaded
        # implementation must still identify exactly which recorder ran.
        original_file = vars(self.trace).pop('__file__')
        try:
            path = self.install()
        finally:
            self.trace.__file__ = original_file
        metadata = json.loads((path / 'metadata.json').read_text())
        self.assertEqual(metadata['schema'], 4)
        self.assertEqual(metadata['recorder_version'], 4)
        self.assertEqual(metadata['tracing_mode'], 'operation-only')
        self.assertFalse(metadata['value_inspection'])
        self.assertFalse(metadata['locals_available'])
        self.assertEqual(metadata['native_identity_fields'], [])
        self.assertIsNone(metadata['script_sha256'])
        digest = metadata['recorder_implementation_sha256']
        self.assertEqual(len(digest), 64)
        self.assertEqual(len(bytes.fromhex(digest)), 32)
        code_map = json.loads((path / 'code-map.json').read_text())
        lookup = next(item for item in code_map if item['label'] == 'graph.lut._output_snapshot')
        self.assertIn(lookup['code_id'], metadata['watched_code_sha256'].values())
        operations = lookup['native_operations']
        self.assertTrue(any(item['op'] == 'LOAD_ATTR' and item['attribute'] == 'image'
                            for item in operations.values()))
        offsets = {item['offset'] for item in lookup['instructions']}
        self.assertTrue(set(map(int, operations)).issubset(offsets))
        self.assertTrue(all(item['line'] is not None for item in operations.values()))
