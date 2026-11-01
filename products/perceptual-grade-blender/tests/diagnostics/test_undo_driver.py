"""Fault-driver failure handling tests without LLDB, Blender, or macOS tools."""
from importlib.machinery import SourceFileLoader
from importlib.util import module_from_spec, spec_from_loader
from importlib.resources import files
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch


def load(name, filename):
    loader = SourceFileLoader(name, str(files('tests.diagnostics') / filename))
    module = module_from_spec(spec_from_loader(loader.name, loader))
    with patch.object(sys, 'path', [str(files('tests.diagnostics')), *sys.path]):
        loader.exec_module(module)
    return module


class FakeProcess:
    def __init__(self):
        self.state = 1
        self.continues = 0
        self.killed = False

    def GetState(self):
        return self.state

    def IsValid(self):
        return True

    def Stop(self):
        self.state = 1

    def Continue(self):
        self.continues += 1
        self.state = 2

    def Kill(self):
        self.killed = True
        self.state = 3


class UndoDriverFailureTests(unittest.TestCase):
    def setUp(self):
        self.module = load('_pg_lldb_driver_test', 'pg_undo_trace_lldb.py')
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.process = FakeProcess()
        self.driver = self.module.Driver.__new__(self.module.Driver)
        self.driver.root = self.root
        self.driver.process = self.process
        self.driver.session = dict(mandatory_artifacts=['session.json', 'native-events.jsonl'])
        self.driver.first_fault_seen = False
        self.driver.last_candidates = []
        self.driver.images = {}
        self.driver.pending = {}
        self.driver.edges = {}
        self.driver.layout = {}
        self.driver.pause_ns = 0
        self.driver.hit_count = 0
        self.driver.snapshot = lambda: dict(pid=4242, threads=[], modules=[], stopped=True)
        self.driver.emit = lambda *_args, **_kwargs: None
        self.driver.listener = None
        self.driver.keep_paused_calls = 0
        self.driver.keep_paused = lambda: setattr(self.driver, 'keep_paused_calls',
                                                   self.driver.keep_paused_calls + 1)
        self.api = SimpleNamespace(eStateStopped=1, eStateCrashed=2, eStateExited=3,
                                   eStateDetached=4, eStateInvalid=5, eStateRunning=6)

    def test_first_fault_captures_then_packages_then_pauses_without_resume(self):
        order = []
        original_snapshot = self.driver.snapshot

        def snapshot():
            order.append('snapshot')
            return original_snapshot()

        self.driver.snapshot = snapshot

        class FakeCapture:
            def __init__(self, root, adapter):
                self.root, self.adapter = root, adapter

            def execute(self, addresses, full_history, force_graph):
                self.assert_stopped()
                order.append('history')
                assert (self.root / 'fault' / 'native.json').is_file()
                return dict(free_stack=False)

            def assert_stopped(self):
                assert self.adapter.is_stopped()

        with patch.object(self.module, 'Capture', FakeCapture), \
             patch.object(self.driver, 'package', side_effect=lambda: order.append('package')), \
             patch.object(self.module, 'lldb', self.api):
            self.driver.capture_first_fault()
        self.assertEqual(order, ['snapshot', 'history', 'package'])
        self.assertEqual(self.driver.keep_paused_calls, 1)
        self.assertEqual(self.process.continues, 0)
        self.assertTrue(self.module.json.loads(
            (self.root / 'fault' / 'native.json').read_text())['stopped'])
        self.assertEqual(self.driver.session['status'], 'fault-paused')
        self.assertEqual(self.driver.session['causal_evidence']['free_stack'], False)

    def test_capture_and_packaging_errors_preserve_snapshot_and_keep_target_paused(self):
        self.driver.is_stopped = lambda: self.process.GetState() == 1
        class BrokenCapture:
            def __init__(self, _root, _adapter):
                pass

            def execute(self, *_args, **_kwargs):
                raise RuntimeError('malloc_history failed')

        with patch.object(self.module, 'Capture', BrokenCapture), \
             patch.object(self.module, 'lldb', self.api), \
             patch.object(self.driver, 'package', side_effect=OSError('disk is full')):
            try:
                self.driver.capture_first_fault()
            except RuntimeError as error:
                self.driver.handle_driver_failure(error)
            else:
                self.fail('Expected native capture query failure')
        self.assertTrue((self.root / 'fault' / 'native.json').is_file())
        snapshot = json.loads((self.root / 'fault' / 'native.json').read_text())
        self.assertEqual(snapshot['pid'], 4242)
        self.assertEqual(self.driver.session['status'], 'fault-capture-incomplete')
        errors = (self.root / 'capture-errors.log').read_text()
        self.assertIn('capture driver: RuntimeError: malloc_history failed', errors)
        self.assertIn('package capture after driver failure: OSError: disk is full', errors)
        self.assertEqual(self.driver.keep_paused_calls, 1)
        self.assertEqual(self.process.state, 1)
        self.assertEqual(self.process.continues, 0)

    def test_manual_pack_retry_failure_does_not_escape_or_resume(self):
        self.driver.is_stopped = lambda: self.process.GetState() == 1
        self.driver.save_session = lambda **fields: self.driver.session.update(fields)
        self.driver.package = lambda: (_ for _ in ()).throw(OSError('archive unavailable'))
        commands = iter(('pack', 'quit'))
        with patch.object(self.module, 'lldb', self.api), \
             patch('builtins.input', side_effect=lambda _prompt='': next(commands)), \
             patch('sys.stderr') as stderr:
            self.module.Driver.keep_paused(self.driver)
        self.assertEqual(self.process.continues, 0)
        self.assertTrue(self.process.killed)
        self.assertEqual(self.driver.session['status'], 'terminated-after-capture')
        self.assertIn('archive unavailable', (self.root / 'capture-errors.log').read_text())


class AllocationPreflightEvidenceTests(unittest.TestCase):
    """Canary validation must reject earlier, unrelated uses of the same address."""
    address = 0x12340000

    def setUp(self):
        self.module = load('_pg_lldb_preflight_test', 'pg_undo_trace_lldb.py')
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def history(self, size=7137, symbol='pg_canary_allocate', *, free_symbol=None):
        # This is Apple's address(module)symbol form, without an offset or a
        # public malloc/free symbol. Both records must belong to the canary.
        free_symbol = symbol if free_symbol is None else free_symbol
        return ('ALLOC 0x12340000-0x12341be0 [size=' + str(size) + ']:\n'
                '  0x100001234 (canary) ' + symbol + '\n'
                'FREE 0x12340000-0x12341be0 [size=' + str(size) + ']:\n'
                '  0x100001256 (canary) ' + free_symbol + '\n')

    def exercise(self, live, graph, *, expected_error=None, live_status='ok'):
        operations = []
        root = self.root
        module = self.module
        driver = module.Driver.__new__(module.Driver)
        driver.root = root

        class Process(list):
            def GetProcessID(self):
                return 4242

        driver.process = Process([object()])
        driver.is_stopped = lambda: True
        driver.kill_disposable = lambda: operations.append('cleanup')
        driver.resume = lambda: operations.append('resume')
        driver.wait_stop = lambda timeout: operations.append(('wait', timeout))

        def launch(executable, arguments, directory, phase):
            operations.append(('launch', phase))
            self.assertEqual(arguments, [])
            self.assertEqual(executable, directory / 'canary')
            (directory / 'launcher-console.log').write_text('PG_ALLOC_CANARY 0x12340000\n')

        driver.launch = launch

        class Capture:
            def __init__(self, directory, adapter):
                self.directory = directory
                assert adapter is driver

            def execute(self, addresses, full_history):
                operations.append('live-history')
                assert addresses == [AllocationPreflightEvidenceTests.address]
                assert full_history is False
                path = self.directory / 'fault' / 'malloc-12340000.txt'
                path.parent.mkdir(exist_ok=True)
                path.write_text(live)
                # Generic capture can find a complete unrelated lifetime. The
                # preflight must independently require the canary-specific one.
                return dict(free_stack=True, histories=[dict(status=live_status,
                            output=str(path), evidence=module.history_evidence(path))])

        def run_tool(arguments, output, timeout=30, accepted=(0,)):
            output = Path(output)
            output.parent.mkdir(parents=True, exist_ok=True)
            if arguments[0] == '/usr/bin/xcrun':
                operations.append('compile')
                output.write_text('compiled fixture\n')
            elif arguments[0] == '/usr/bin/leaks':
                operations.append('graph')
                self.assertEqual(arguments[-1], '4242')
                self.assertEqual(timeout, 180)
                self.assertEqual(accepted, (0, 1))
                Path(arguments[2]).write_bytes(b'fake graph')
                output.write_text('created graph\n')
            elif arguments[0] == '/usr/bin/malloc_history':
                operations.append('graph-history')
                self.assertEqual(arguments[1], str(root / 'preflight-allocation' / 'known.memgraph'))
                self.assertEqual(arguments[2], '0x12340000')
                output.write_text(graph)
            else:
                self.fail('Unexpected native tool: ' + str(arguments))
            return dict(status='ok', returncode=0, output=str(output))

        with patch.object(module, 'Capture', Capture), \
             patch.object(module, 'run_tool', side_effect=run_tool), \
             patch.object(module, 'native_fault', return_value=True), \
             patch.object(module, 'history_evidence', wraps=module.history_evidence) as check:
            if expected_error:
                with self.assertRaisesRegex(RuntimeError, expected_error):
                    driver.allocation_preflight()
            else:
                driver.allocation_preflight()
        filtered_calls = [call for call in check.call_args_list if call.kwargs]
        self.assertTrue(filtered_calls)
        for call in filtered_calls:
            self.assertEqual(call.kwargs, dict(expected_size=7137, expected_symbol='pg_canary_allocate'))
        return root / 'preflight-allocation', operations

    def test_canary_history_passes_live_and_graph_then_cleans_up(self):
        directory, operations = self.exercise(self.history(), self.history())
        self.assertEqual(operations, ['compile', ('launch', 'allocation-preflight'), 'resume',
                                     ('wait', 30), 'live-history', 'graph', 'graph-history', 'cleanup'])
        for name in ('live-check.json', 'graph-check.json'):
            row = json.loads((directory / name).read_text())
            self.assertEqual(row['expected_size'], 7137)
            self.assertEqual(row['expected_symbol'], 'pg_canary_allocate')
            self.assertEqual(row['address'], '0x12340000')
            self.assertTrue(row['process_stopped'])
            self.assertTrue(all(row['evidence'].values()))

    def test_unrelated_live_history_cannot_pass_canary_preflight(self):
        for unrelated in (self.history(size=16), self.history(symbol='other_allocation')):
            with self.subTest(history=unrelated):
                directory, operations = self.exercise(unrelated, self.history(),
                                                       expected_error='Live allocation/free stack preflight failed')
                row = json.loads((directory / 'live-check.json').read_text())
                self.assertFalse(row['evidence']['stack'])
                self.assertEqual(row['query']['status'], 'ok')
                self.assertNotIn('graph', operations)
                self.assertNotIn('cleanup', operations)

    def test_unrelated_graph_history_cannot_satisfy_live_canary(self):
        directory, operations = self.exercise(self.history(), self.history(symbol='older_allocation'),
                                               expected_error='Full-stack-history graph preflight failed')
        self.assertIn('graph-history', operations)
        self.assertNotIn('cleanup', operations)
        live = json.loads((directory / 'live-check.json').read_text())
        graph = json.loads((directory / 'graph-check.json').read_text())
        self.assertTrue(all(live['evidence'].values()))
        self.assertFalse(graph['evidence']['stack'])

    def test_canary_allocation_does_not_borrow_an_unrelated_free_stack(self):
        directory, operations = self.exercise(self.history(free_symbol='older_allocation'), self.history(),
                                               expected_error='Live allocation/free stack preflight failed')
        row = json.loads((directory / 'live-check.json').read_text())
        self.assertTrue(row['evidence']['allocation_stack'])
        self.assertFalse(row['evidence']['free_stack'])
        self.assertNotIn('graph', operations)


    def test_failed_query_cannot_pass_even_with_valid_canary_output(self):
        directory, operations = self.exercise(self.history(), self.history(), live_status='timeout',
                                               expected_error='query=timeout')
        row = json.loads((directory / 'live-check.json').read_text())
        self.assertTrue(all(row['evidence'].values()))
        self.assertEqual(row['query']['status'], 'timeout')
        self.assertNotIn('graph', operations)


class LaunchEvidenceTests(unittest.TestCase):
    """Async native launch failures retain the discriminator before teardown."""

    def setUp(self):
        self.module = load('_pg_lldb_launch_test', 'pg_undo_trace_lldb.py')
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'config.json').write_text('{}')
        (self.root / 'session.json').write_text('{"launch_id":"launch-test"}')
        self.events = []
        self.listeners = []
        self.launches = []
        self.process = Mock()
        self.process.IsValid.return_value = True
        self.process.GetState.return_value = 6
        self.process.GetStopID.return_value = 10
        self.process.GetProcessID.return_value = 47026
        self.process.GetUniqueID.return_value = 2
        self.process.GetExitStatus.return_value = -1
        self.process.GetExitDescription.return_value = 'debugserver connection lost'
        self.process.GetDescription.side_effect = lambda stream: setattr(stream, 'data', 'process 47026 description')
        self.process.Kill.side_effect = lambda: setattr(self.process.GetState, 'return_value', 3)

        class Stream:
            def __init__(self):
                self.data = ''

            def GetData(self):
                return self.data

        class Event:
            def GetType(self):
                return 1

            def GetDescription(self, stream):
                stream.data = 'state transition event'

        owner = self

        class Listener:
            def __init__(self, name):
                self.name = name
                owner.listeners.append(self)

            def WaitForEvent(self, timeout, event):
                if owner.events:
                    source, state, observed_state = owner.events.pop(0)
                    event.source, event.state = source, state
                    owner.process.GetState.return_value = observed_state
                    return True
                owner.fail('Unexpected wait without a queued process event')

            def GetNextEvent(self, event):
                if not owner.events:
                    return False
                return self.WaitForEvent(None, event)

        def launch_info(arguments):
            info = Mock()
            info.arguments = arguments
            return info

        error = Mock()
        error.Success.return_value = True
        error.GetError.return_value = 0
        error.GetType.return_value = 0
        self.error = error
        self.api = SimpleNamespace(eStateStopped=1, eStateCrashed=2, eStateExited=3,
                                   eStateDetached=4, eStateInvalid=5, eStateRunning=6,
                                   eStateLaunching=7, eLaunchFlagStopAtEntry=8,
                                   SBStream=Stream, SBEvent=Event, SBListener=Listener,
                                   SBLaunchInfo=launch_info, SBError=lambda: error,
                                   SBProcess=SimpleNamespace(
                                       EventIsProcessEvent=lambda event: True,
                                       GetProcessFromEvent=lambda event: event.source,
                                       GetStateFromEvent=lambda event: event.state,
                                       GetRestartedFromEvent=lambda event: False))
        self.target = Mock()

        def target_launch(info, error):
            request = json.loads((self.driver.run_dir / 'launch.json').read_text())
            self.assertNotIn('returned', request)
            self.launches.append((request, info))
            return self.process

        self.target.Launch.side_effect = target_launch
        self.debugger = Mock()
        self.debugger.CreateTarget.return_value = self.target
        self.api_patch = patch.object(self.module, 'lldb', self.api)
        self.api_patch.start()
        self.addCleanup(self.api_patch.stop)
        self.driver = self.module.Driver(self.debugger, self.root)
        self.driver.module_identity = lambda: dict(uuid='test', executable='/app/Blender', triple='arm64-test')

    def launch(self, phase='blender-preflight'):
        return self.driver.launch('/app/Blender', ['--factory-startup', '--background'],
                                  self.root / phase, phase)

    def journal(self):
        return [json.loads(line) for line in (self.root / 'native-events.jsonl').read_text().splitlines()]

    def test_exited_minus_one_preserves_exit_description_before_disposal(self):
        self.process.GetState.return_value = self.api.eStateExited
        with self.assertRaisesRegex(RuntimeError, 'Inferior exited.*exit_status=-1.*debugserver connection lost'):
            self.launch()
        launch = json.loads((self.root / 'blender-preflight' / 'launch.json').read_text())
        self.assertEqual(launch['executable'], '/app/Blender')
        self.assertEqual(launch['arguments'], ['--factory-startup', '--background'])
        self.assertEqual(launch['environment']['MallocStackLoggingNoCompact'], '1')
        self.assertTrue(launch['returned']['error_success'])
        self.assertEqual(launch['returned']['process']['state_name'], 'exited')
        self.driver.kill_disposable()
        before = json.loads((self.root / 'blender-preflight' / 'before-dispose.json').read_text())
        self.assertEqual(before['exit_description'], 'debugserver connection lost')
        self.assertEqual(before['description'], 'process 47026 description')
        self.assertEqual(before['state'], self.api.eStateExited)
        self.assertEqual(before['stop_id'], 10)
        self.process.Kill.assert_called_once()
        self.debugger.DeleteTarget.assert_called_once_with(self.target)
        self.assertEqual([row['event'] for row in self.journal()], [
            'process_launch_requested', 'process_launch_returned', 'process_observed', 'process_observed'])

    def test_detached_and_invalid_are_not_reported_as_exited(self):
        for state, name in ((self.api.eStateDetached, 'detached'), (self.api.eStateInvalid, 'invalid')):
            with self.subTest(name=name):
                self.process.GetState.return_value = state
                with self.assertRaisesRegex(RuntimeError, 'Inferior ' + name + ' before expected stop'):
                    self.launch(name)
                row = json.loads((self.root / name / 'wait-stop-failure.json').read_text())
                self.assertEqual(row['state_name'], name)
                self.assertEqual(row['pid'], 47026)

    def test_async_launch_records_request_return_and_current_process_event_in_order(self):
        self.process.GetState.return_value = self.api.eStateLaunching
        self.events = [(self.process, self.api.eStateStopped, self.api.eStateStopped)]
        self.launch()
        rows = self.journal()
        self.assertEqual([row['event'] for row in rows], [
            'process_launch_requested', 'process_launch_returned', 'process_event', 'process_launched'])
        self.assertEqual(rows[1]['result']['process']['state_name'], 'launching')
        self.assertEqual(rows[2]['observation']['state_name'], 'stopped')
        self.assertTrue(rows[2]['observation']['current_process'])

    def test_each_launch_uses_fresh_listener_and_old_event_cannot_supply_a_stop(self):
        self.process.GetState.return_value = self.api.eStateStopped
        self.launch('allocation-preflight')
        previous = Mock()
        previous.GetProcessID.return_value = 46963
        previous.GetUniqueID.return_value = 1
        self.process.GetState.return_value = self.api.eStateRunning
        self.events = [(previous, self.api.eStateStopped, self.api.eStateRunning),
                       (self.process, self.api.eStateStopped, self.api.eStateStopped)]
        self.launch()
        self.assertEqual(len(self.listeners), 2)
        self.assertIsNot(self.listeners[0], self.listeners[1])
        for (_, info), listener in zip(self.launches, self.listeners):
            info.SetListener.assert_called_once_with(listener)
        observed = [row['observation'] for row in self.journal() if row['event'] == 'process_event']
        self.assertEqual([row['current_process'] for row in observed], [False, True])
        self.assertEqual(self.events, [])

    def test_process_event_journal_is_bounded(self):
        self.process.GetState.return_value = self.api.eStateRunning
        self.events = [(self.process, self.api.eStateRunning, self.api.eStateRunning)] * 5
        self.events.append((self.process, self.api.eStateStopped, self.api.eStateStopped))
        with patch.object(self.module, 'PROCESS_EVENT_LIMIT', 2):
            self.launch()
        events = [row['event'] for row in self.journal()]
        self.assertEqual(events.count('process_event'), 2)
        self.assertEqual(events.count('process_event_limit'), 1)

    def test_terminal_error_survives_snapshot_write_and_event_formatting_failures(self):
        self.process.GetState.return_value = self.api.eStateExited
        self.events = [(self.process, self.api.eStateExited, self.api.eStateExited)]
        real_write = self.module.write_json

        def fail_observation(path, value):
            if Path(path).name in ('wait-stop-failure.json', 'before-dispose.json'):
                raise OSError('disk is full')
            return real_write(path, value)

        self.process.GetStopID.side_effect = RuntimeError('stop ID unavailable')
        self.process.GetDescription.side_effect = RuntimeError('description unavailable')
        with patch.object(self.module, 'write_json', side_effect=fail_observation), \
             patch.object(self.driver, 'record_process_event', side_effect=RuntimeError('event formatter failed')):
            with self.assertRaisesRegex(RuntimeError, 'Inferior exited.*exit_status=-1.*debugserver connection lost'):
                self.launch()
            self.driver.kill_disposable()
        launch = json.loads((self.root / 'blender-preflight' / 'launch.json').read_text())
        self.assertEqual(launch['returned']['process']['stop_id_unavailable'], 'stop ID unavailable')
        errors = (self.root / 'capture-errors.log').read_text()
        self.assertIn('disk is full', errors)
        self.assertIn('event formatter failed', errors)
        self.process.Kill.assert_called_once()

    def test_event_formatting_error_does_not_replace_successful_async_stop(self):
        self.events = [(self.process, self.api.eStateStopped, self.api.eStateStopped)]
        with patch.object(self.driver, 'record_process_event', side_effect=RuntimeError('SBStream unavailable')):
            self.launch()
        self.assertEqual(self.driver.last_stop_id, 10)
        self.assertIn('SBStream unavailable', (self.root / 'capture-errors.log').read_text())

    def test_launch_diagnostic_failures_do_not_mask_returned_launch_error(self):
        self.error.Success.return_value = False
        self.error.__str__ = Mock(return_value='launch rejected for test')
        real_write = self.module.write_json
        real_emit = self.driver.emit

        def fail_returned_write(path, value):
            if Path(path).name == 'launch.json' and 'returned' in value:
                raise OSError('returned result disk error')
            return real_write(path, value)

        def fail_returned_event(event, **fields):
            if event == 'process_launch_returned':
                raise OSError('returned event disk error')
            return real_emit(event, **fields)

        with patch.object(self.module, 'write_json', side_effect=fail_returned_write), \
             patch.object(self.driver, 'emit', side_effect=fail_returned_event):
            with self.assertRaisesRegex(RuntimeError, 'Debugger launch denied/failed: launch rejected for test'):
                self.launch()
        errors = (self.root / 'capture-errors.log').read_text()
        self.assertIn('returned result disk error', errors)
        self.assertIn('returned event disk error', errors)

    def test_failed_preflight_diagnostics_cannot_skip_cleanup_and_packaging(self):
        self.driver.allocation_preflight = Mock(side_effect=RuntimeError('original preflight failure'))
        self.driver.blender_preflight = Mock()
        self.driver.reproduce = Mock()
        self.driver.emit = Mock(side_effect=OSError('journal unavailable'))
        self.driver.kill_disposable = Mock(side_effect=RuntimeError('cleanup failed'))
        self.driver.package = Mock()
        real_write = self.module.write_json

        def fail_preflight_write(path, value):
            if Path(path).name == 'preflight.json':
                raise OSError('preflight write failed')
            return real_write(path, value)

        with patch.object(self.module, 'write_json', side_effect=fail_preflight_write):
            self.driver.run()
        self.driver.kill_disposable.assert_called_once()
        self.driver.package.assert_called_once()
        self.driver.blender_preflight.assert_not_called()
        self.driver.reproduce.assert_not_called()
        session = json.loads((self.root / 'session.json').read_text())
        self.assertEqual(session['status'], 'preflight-failed')
        self.assertEqual(session['error'], 'original preflight failure')
        errors = (self.root / 'capture-errors.log').read_text()
        for message in ('original preflight failure', 'journal unavailable', 'preflight write failed', 'cleanup failed'):
            self.assertIn(message, errors)



if __name__ == '__main__':
    unittest.main()
