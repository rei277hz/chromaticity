"""Native Blender checks for the standalone, non-saving crash diagnostic."""
from tests.support.session import component as _component, SessionTest, patch
from importlib.machinery import SourceFileLoader
from importlib.resources import files
from importlib.util import module_from_spec, spec_from_loader
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
pass
import zipfile

import bpy
grades = _component('graph.grades'); lut = _component('graph.lut'); nodes = _component('graph.nodes'); output_resources = _component('graph.output_resources')
panel = _component('ui.panel')
from tests.support.blender import BlenderTest


BOUNDARIES = ('undo_pre', 'undo_post', 'redo_pre', 'redo_post', 'load_pre', 'load_post')


class UndoTraceTests(BlenderTest):
    def setUp(self):
        super().setUp()
        # Buck export_file resources may have extensionless physical names.
        self.script = str(files('tests.blender') / 'pg_undo_trace.py')
        loader = SourceFileLoader('_pg_undo_trace_test', self.script)
        self.trace = module_from_spec(spec_from_loader(loader.name, loader))
        loader.exec_module(self.trace)
        self.original = lut.adopt_native
        self.previous_profile = sys.getprofile()
        self.previous_state = sys.modules.get(self.trace._STATE_MODULE)
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)

    def tearDown(self):
        try:
            self.trace.stop()
            sys.setprofile(self.previous_profile)
            if self.previous_state is None:
                sys.modules.pop(self.trace._STATE_MODULE, None)
            else:
                sys.modules[self.trace._STATE_MODULE] = self.previous_state
        finally:
            super().tearDown()

    def install(self, name='capture', interval=0):
        return self.trace.install(output_dir=self.root / name, interval=interval,
                                  capture_console=False)

    def node(self):
        tree = bpy.data.node_groups.new('Undo trace premise', 'CompositorNodeTree')
        node = tree.nodes.new(grades.KINDS['CompositorNodeTree'])
        # A real empty kernel exercises snapshot/manifest frame destruction,
        # without constructing or dispatching any numerical LUT workload.
        node.node_tree = bpy.data.node_groups.new('Empty trace kernel', 'CompositorNodeTree')
        return node

    def records(self, directory):
        return [json.loads(line) for line in (directory / 'events.jsonl').read_text().splitlines()]

    def test_install_stop_and_rerun_leave_functions_and_profiler_unchanged(self):
        def prior_profile(frame, event, arg):
            pass
        sys.setprofile(prior_profile)
        watched = (lut.adopt_native, nodes.undo_redo_pre_handler,
                   nodes.reset_cache_handler, panel.PG_OT_reset_stage.execute)
        original_handlers = {name: tuple(getattr(bpy.app.handlers, name)) for name in BOUNDARIES}
        first_path = self.install('first')
        first = sys.modules[self.trace._STATE_MODULE].trace
        self.assertEqual(watched, (lut.adopt_native, nodes.undo_redo_pre_handler,
                                  nodes.reset_cache_handler, panel.PG_OT_reset_stage.execute))
        self.assertIs(sys.getprofile(), prior_profile)
        second_path = self.install('second')
        second = sys.modules[self.trace._STATE_MODULE].trace
        self.assertNotEqual(first_path, second_path)
        self.assertTrue(first.closed)
        self.assertFalse(first.fds)
        tool = second.tool_id
        fds = tuple(second.fds.values()) if isinstance(second.fds, dict) else tuple(second.fds)
        self.trace.stop()
        self.trace.stop()
        self.assertTrue(second.closed)
        self.assertFalse(second.fds)
        self.assertIsNone(sys.monitoring.get_tool(tool))
        for fd in fds:
            with self.assertRaises(OSError):
                os.fstat(fd)
        self.assertIs(lut.adopt_native, self.original)
        self.assertIs(sys.getprofile(), prior_profile)
        for name, callbacks in original_handlers.items():
            self.assertEqual(tuple(getattr(bpy.app.handlers, name)), callbacks)
        for directory in (first_path, second_path):
            events = [record['event'] for record in self.records(directory)]
            self.assertIn('installed', events)
            self.assertEqual(events[-1], 'stopped')
            metadata = json.loads((directory / 'metadata.json').read_text())
            self.assertIn('perceptual_grade_blender/graph/lut.py', metadata['source_sha256'])
            self.assertIn('blender_runtime/policies/attempt.py', metadata['source_sha256'])
            self.assertTrue((directory / 'fatal-python.txt').is_file())
            self.assertTrue((directory / 'periodic-python.txt').is_file())

    def test_real_recovery_records_stacks_lines_and_before_return_markers(self):
        node = self.node()
        path = self.install()
        # Explicit validation owns its bounded snapshot. Recovery adopts the
        # native graph without inspecting or repairing its incomplete layout.
        with self.assertRaises(ValueError):
            lut.validate_output(node)
        self.assertIsNone(lut.adopt_native(node,nodes.output_intent(node)))
        self.assertNotIn(lut.INCOMPLETE,node)
        self.assertIs(lut.adopt_native, self.original)
        self.assertIs(sys.getprofile(), self.previous_profile)
        records = self.records(path)
        def matching(event, suffix):
            return [record for record in records if record['event'] == event
                    and record.get('function', '').endswith(suffix)]
        entered = matching('function_enter', '.adopt_native')
        returned = matching('return_requested', '.adopt_native')
        self.assertTrue(entered)
        self.assertTrue(returned)
        self.assertLess(entered[0]['sequence'], returned[-1]['sequence'])
        self.assertTrue(matching('return_requested', '._output_snapshot'))
        # Explicit manifest validation preserves its failure location. Native
        # adoption has its own trace without reconstructing image resources.
        self.assertTrue(matching('python_raise', '._manifest'))
        self.assertTrue(matching('python_unwind', '._manifest'))
        self.assertTrue(matching('return_requested', '.adopt_native'))
        self.assertFalse(matching('function_enter', '.bank_images'))
        self.assertTrue(matching('line', '.adopt_native'))
        self.assertTrue(entered[0].get('stack'))
        self.assertNotIn('recover_returned', {record['event'] for record in records})

    def test_escaping_error_keeps_trace_operational_and_preserves_exception(self):
        node = self.node()
        path = self.install()
        # Failed runtime adoption propagates without rewriting native output.
        with patch.object(output_resources, 'adopt_native', side_effect=AssertionError('Trace failure premise')):
            with self.assertRaisesRegex(AssertionError, 'Trace failure premise'):
                lut.adopt_native(node,nodes.output_intent(node))
        self.assertIsNone(lut.adopt_native(node,nodes.output_intent(node)))
        self.assertIs(lut.adopt_native, self.original)
        self.assertIs(sys.getprofile(), self.previous_profile)
        records = self.records(path)
        recovery = [row for row in records if row.get('function', '').endswith('.adopt_native')]
        self.assertIn('python_unwind', {row['event'] for row in recovery})
        self.assertIn('return_requested', {row['event'] for row in recovery})
        errors = [row for row in recovery if row['event'] in ('python_raise', 'python_unwind')]
        self.assertTrue(errors)
        self.assertTrue(all('exception_type' not in row and 'locals' not in row for row in errors))
        self.assertTrue(any(row.get('stack') for row in errors))

    def test_stage_reset_is_recorded_before_recovery_without_dispatching_helpers(self):
        node = self.node()
        with patch.object(nodes, 'refresh_node'):
            nodes.initialize_grade(node)
        bpy.context.window_manager.pg_stage = 'CHROMATIC'
        with grades.guarded(node):
            node.pg_chromatic.global_gain = .25
        path = self.install()
        # The production operator and batch property writes run unchanged;
        # the notification is isolated from unrelated numerical work here.
        with patch.object(nodes, 'active_grade', return_value=node), patch.object(grades, 'changed'):
            self.assertEqual(panel.PG_OT_reset_stage.execute(None, bpy.context), {'FINISHED'})
        self.assertEqual(node.pg_chromatic.global_gain, 0.)
        entered = [row.get('function', '') for row in self.records(path)
                   if row['event'] == 'function_enter']
        self.assertTrue(any(name.endswith('.PG_OT_reset_stage.execute') for name in entered))
        self.assertTrue(any(name.endswith('.write_chromatic') for name in entered))

    def test_native_boundary_markers_bracket_original_handlers_and_clean_up(self):
        before = {name: tuple(getattr(bpy.app.handlers, name)) for name in BOUNDARIES}
        path = self.install()
        # Exercise only installed observers: calling original native callbacks
        # manually would not reproduce an actual native undo.
        for name in BOUNDARIES:
            callbacks = tuple(getattr(bpy.app.handlers, name))
            added = [callback for callback in callbacks if callback not in before[name]]
            self.assertEqual(len(added), 2, name)
            self.assertIs(callbacks[0], added[0], name)
            self.assertIs(callbacks[-1], added[-1], name)
            self.assertEqual(callbacks[1:-1], before[name], name)
            for callback in added:
                callback(None)
        events = [record['event'] for record in self.records(path)]
        for name in BOUNDARIES:
            self.assertTrue(any(name in event for event in events), name)
        self.trace.stop()
        for name in BOUNDARIES:
            self.assertEqual(tuple(getattr(bpy.app.handlers, name)), before[name])

    def test_periodic_stack_capture_runs_without_main_thread_timer(self):
        path = self.install(interval=.05)
        # Sleep releases the GIL but dispatches no bpy.app.timers. Sampling
        # must remain useful if Blender's main event loop stops making progress.
        time.sleep(.16)
        self.trace.stop()
        content = (path / 'periodic-python.txt').read_text()
        self.assertIn('test_periodic_stack_capture_runs_without_main_thread_timer', content)

    def test_console_capture_includes_native_writes_and_restores_descriptors(self):
        def identity(fd):
            status = os.fstat(fd)
            return status.st_dev, status.st_ino
        before = {fd: identity(fd) for fd in (1, 2)}
        path = self.trace.install(output_dir=self.root / 'console', interval=0,
                                  capture_console=True)
        try:
            os.write(1, b'PG native stdout capture premise\n')
            os.write(2, b'PG native stderr capture premise\n')
        finally:
            self.trace.stop()
        self.assertEqual({fd: identity(fd) for fd in (1, 2)}, before)
        captured = (path / 'console.log').read_text()
        self.assertIn('PG native stdout capture premise', captured)
        self.assertIn('PG native stderr capture premise', captured)

    def test_cleanup_with_missing_python_console_streams_releases_all_resources(self):
        self.install()
        state = sys.modules[self.trace._STATE_MODULE].trace
        tool = state.tool_id
        fds = tuple(state.fds.values())
        with patch.object(sys, 'stdout', None), patch.object(sys, 'stderr', None):
            self.trace.stop()
        self.assertTrue(state.closed)
        self.assertFalse(state.fds)
        self.assertFalse(state.hooks)
        self.assertFalse(state.cleanup_errors)
        self.assertIsNone(sys.monitoring.get_tool(tool))
        for fd in fds:
            with self.assertRaises(OSError):
                os.fstat(fd)

    def test_recording_survives_text_editor_namespace_reuse(self):
        node = self.node()
        path = self.install()
        state = sys.modules[self.trace._STATE_MODULE]
        saved_globals = dict(vars(self.trace))
        try:
            # Blender can run an unrelated Text Editor script in the same
            # globals. Installed callbacks must own their dependencies.
            vars(self.trace).clear()
            self.assertIsNone(lut.adopt_native(node,nodes.output_intent(node)))
            state.stop()
        finally:
            vars(self.trace).update(saved_globals)
        self.assertTrue(state.trace.closed)
        self.assertFalse(state.trace.fds)
        records = self.records(path)
        self.assertTrue(any(row['event'] == 'function_enter'
                            and row.get('function', '').endswith('.adopt_native')
                            for row in records))
        self.assertEqual(records[-1]['event'], 'stopped')

    def test_collector_preserves_recording_and_only_recent_native_candidates(self):
        path = self.install()
        self.trace.stop()
        native = self.root / 'native-source'
        native.mkdir()
        metadata_path = path / 'metadata.json'
        metadata = json.loads(metadata_path.read_text())
        metadata['blender_tempdir'] = str(native)
        metadata['blend_filepath'] = ''
        metadata_path.write_text(json.dumps(metadata))
        started = metadata['started_epoch']
        for name, modified, content in (
                ('Blender-current.ips', started, 'current native diagnostic'),
                ('Blender-old.ips', started - 60, 'old unrelated diagnostic'),
                ('OtherApplication-current.ips', started, 'unrelated application')):
            candidate = native / name
            candidate.write_text(content)
            os.utime(candidate, (modified, modified))
        with patch.object(Path, 'home', return_value=self.root):
            archive = self.trace.collect_report(path)
        collection = json.loads((path / 'collection.json').read_text())
        local_candidates = [item for item in collection['artifacts']
                            if item['category']=='native-report' and Path(item['source']).parent == native]
        self.assertEqual([Path(item['source']).name for item in local_candidates],
                         ['Blender-current.ips'])
        self.assertFalse(local_candidates[0]['mandatory'])
        self.assertEqual(local_candidates[0]['status'],'included')
        with zipfile.ZipFile(archive) as bundle:
            names = bundle.namelist()
            self.assertIn(path.name + '/events.jsonl', names)
            self.assertIn(path.name + '/metadata.json', names)
            self.assertIn(path.name + '/fatal-python.txt', names)
            chosen = [name for name in names if name.endswith('Blender-current.ips')]
            self.assertEqual(len(chosen), 1)
            self.assertEqual(bundle.read(chosen[0]), b'current native diagnostic')
            self.assertFalse(any(name.endswith('Blender-old.ips') for name in names))
            self.assertFalse(any(name.endswith('OtherApplication-current.ips') for name in names))

    def test_native_launch_groups_reruns_and_records_native_log_offsets(self):
        session = self.root / 'native-launch'
        session.mkdir()
        (session / 'session.json').write_text(json.dumps({'schema': 1, 'launch_id': 'test-launch'}))
        undo_log = session / 'native-undo.log'
        undo_log.write_text('native undo first\n')
        environment = {'PG_UNDO_TRACE_SESSION_DIR': str(session),
                       'PG_UNDO_TRACE_LAUNCH_ID': 'test-launch'}
        with patch.dict(os.environ, environment):
            first = self.trace.install(interval=0, capture_console=False)
            second = self.trace.install(interval=0, capture_console=False)
        self.assertNotEqual(first, second)
        for directory in (first, second):
            self.assertEqual(directory.parent, session / 'python')
            metadata = json.loads((directory / 'metadata.json').read_text())
            self.assertEqual(metadata['native_session_dir'], str(session))
            self.assertEqual(metadata['launch_id'], 'test-launch')
            self.assertGreater(metadata['clock_origin']['wall_time_ns'], 0)
            self.assertGreater(metadata['clock_origin']['monotonic_ns'], 0)
            self.assertTrue(all(row['launch_id'] == 'test-launch' for row in self.records(directory)))
        state = sys.modules[self.trace._STATE_MODULE].trace
        before = self.records(second)[-1]
        with undo_log.open('a') as output:
            output.write('native undo second\n')
        state.emit('native_log_offset_test')
        after = self.records(second)[-1]
        self.assertGreater(after['native_undo_bytes'], before['native_undo_bytes'])
        self.assertEqual(after['native_undo_bytes'], undo_log.stat().st_size)

    def test_missing_native_undo_log_does_not_disable_operation_events(self):
        with patch.dict(os.environ, {'PG_UNDO_TRACE_UNDO_LOG': str(self.root / 'missing.log')}):
            path = self.install()
        state = sys.modules[self.trace._STATE_MODULE].trace
        state.emit('missing_log_test')
        row = self.records(path)[-1]
        self.assertEqual(row['event'], 'missing_log_test')
        self.assertIsNone(row['native_undo_bytes'])
        self.assertFalse(state.write_failed)

    def test_native_collection_delegates_the_whole_launch_after_stopping_recorder(self):
        session = self.root / 'native-launch'
        session.mkdir()
        (session / 'session.json').write_text(json.dumps({'schema': 1, 'launch_id': 'test-launch'}))
        companion_dir = self.root / 'tools'
        companion_dir.mkdir()
        (companion_dir / 'pg_undo_trace_collect.py').write_text(
            'from pathlib import Path\n'
            'import sys\n'
            'def collect_session(directory):\n'
            "    assert sys.modules['_pg_undo_trace_state'].trace.closed\n"
            '    Path(directory, "delegate-called").write_text(str(directory))\n'
            '    return Path(directory).with_suffix(".zip")\n')
        environment = {'PG_UNDO_TRACE_SESSION_DIR': str(session),
                       'PG_UNDO_TRACE_LAUNCH_ID': 'test-launch',
                       'PG_UNDO_TRACE_TOOLS_DIR': str(companion_dir)}
        with patch.dict(os.environ, environment):
            path = self.trace.install(interval=0, capture_console=False)
            archive = self.trace.collect_report(path)
        self.assertEqual(archive, session.with_suffix('.zip'))
        self.assertEqual((session / 'delegate-called').read_text(), str(session))
        self.assertFalse((path / 'collection.json').exists())

    def test_abort_child_writes_fatal_stack_without_a_clean_shutdown(self):
        directory = self.root / 'fatal-child'
        (directory / 'graph').mkdir(parents=True)
        module_path = directory / 'graph' / 'lut.py'
        module_path.write_text('# synthetic watched module\n')
        child_script = directory / 'abort_child.py'
        child_script.write_text(r'''
from importlib.machinery import SourceFileLoader
from importlib.util import module_from_spec, spec_from_loader
import os
from pathlib import Path
import sys
import time
import types
try:
    import resource
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
except ImportError:
    pass
loader = SourceFileLoader('_pg_crash_child', sys.argv[1])
module = module_from_spec(spec_from_loader(loader.name, loader))
loader.exec_module(module)
prefix = 'perceptual_grade_crash_fixture'
lut = types.ModuleType(prefix + '.graph.lut')
lut.__file__ = sys.argv[2]
def _output_snapshot():
    return None
def _manifest():
    return None
def validate_output():
    return None
def read_cube():
    return None
def adopt_native():
    os.abort()
for function in (_output_snapshot, _manifest, validate_output, read_cube, adopt_native):
    setattr(lut, function.__name__, function)
sys.modules[lut.__name__] = lut
# The recorder follows the explicitly registered Session. This synthetic child
# retains its watched component through the same interface before aborting.
application = types.SimpleNamespace(
    app=types.SimpleNamespace(blender=types.SimpleNamespace(native=None), ownership=None),
    component=lambda name: lut if name == 'graph.lut' else None)
lifecycle = types.ModuleType(prefix + '.integration.lifecycle')
lifecycle.registered_session = lambda: application
sys.modules[lifecycle.__name__] = lifecycle
components = types.ModuleType(prefix + '.integration.components')
components.component_items = lambda component: vars(component).items()
sys.modules[components.__name__] = components
trace = module._Trace(prefix, lut, Path(sys.argv[3]))
trace.start(interval=.05, capture_console=False, handlers=False)
time.sleep(.12)
adopt_native()
''', encoding='utf8')
        report = directory / 'capture'
        result = subprocess.run([sys.executable, str(child_script), self.script,
                                 str(module_path), str(report)],
                                cwd=self.root, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True, timeout=20)
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        fatal = report / 'fatal-python.txt'
        self.assertTrue(fatal.is_file(), result.stdout + result.stderr)
        content = fatal.read_text()
        self.assertIn('Fatal Python error', content, result.stdout + result.stderr)
        self.assertIn('adopt_native', content, result.stdout + result.stderr)
        self.assertTrue((report / 'periodic-python.txt').read_text())
        events = self.records(report)
        self.assertTrue(any(row['event'] == 'function_enter'
                            and row.get('function', '').endswith('.adopt_native')
                            for row in events))
        self.assertNotIn('stopped', {row['event'] for row in events})
