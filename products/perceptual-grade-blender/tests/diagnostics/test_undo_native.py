"""Host-side tests for live allocation capture; no Blender or macOS required."""
from importlib.machinery import SourceFileLoader
from importlib.util import module_from_spec, spec_from_loader
from pathlib import Path
from importlib.resources import files
import json
import tempfile
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch


def load(name, filename):
    loader = SourceFileLoader(name, str(files('tests.diagnostics') / filename))
    module = module_from_spec(spec_from_loader(loader.name, loader))
    with patch.object(sys, 'path', [str(files('tests.diagnostics')), *sys.path]):
        loader.exec_module(module)
    return module


class Adapter:
    pid = 123

    def __init__(self):
        self.stopped = True

    def is_stopped(self):
        return self.stopped

    def snapshot(self):
        return dict(pid=self.pid, threads=[], modules=[], stopped=self.stopped)


class NativeCaptureTests(unittest.TestCase):
    def setUp(self):
        self.native = load('_pg_native_test', 'pg_undo_trace_native.py')
        self.root_tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.root_tmp.cleanup)
        self.root = Path(self.root_tmp.name)
        self.adapter = Adapter()
        self.calls = []

    def runner(self, arguments, output, timeout=30, accepted=(0,)):
        arguments = list(map(str, arguments))
        self.calls.append((arguments, timeout))
        path = Path(output)
        if arguments[0] == '/usr/bin/malloc_history':
            path.write_text('ALLOC 0x1000 size=64\n  0 libSystem_malloc.dylib 0x123 + 4\n'
                            'FREE 0x1000 size=64\n  0 libSystem_malloc.dylib 0x456 + 8\n')
        elif arguments[0] == '/usr/bin/leaks':
            Path(arguments[2]).write_bytes(b'memgraph')
            path.write_text('graph created\n')
        return dict(arguments=arguments, timeout_seconds=timeout, output=str(path), status='ok',
                    returncode=0, bytes=path.stat().st_size, sha256=self.native.sha256(path))

    def test_live_targeted_free_history_and_original_fault_snapshot(self):
        capture = self.native.Capture(self.root, self.adapter, runner=self.runner)
        report = capture.execute([0x1000], full_history=True)
        self.assertTrue(report['process_stopped'])
        self.assertTrue(report['free_stack'])
        self.assertEqual(self.calls[0][0], ['/usr/bin/malloc_history', '123', '0x1000'])
        self.assertEqual(self.calls[0][1], 30)
        self.assertEqual(json.loads((self.root / 'fault' / 'native.json').read_text())['stopped'], True)
        self.assertEqual(json.loads((self.root / 'fault' / 'summary.json').read_text()), report)
        self.assertFalse(any(' - 8' in arg for args, _ in self.calls for arg in args))

    def test_unknown_pointer_attempts_bounded_full_history_but_does_not_claim_free_stack(self):
        capture = self.native.Capture(self.root, self.adapter, runner=self.runner)
        report = capture.execute([], full_history=True)
        self.assertFalse(report['free_stack'])
        self.assertEqual(report['graph']['timeout_seconds'], 180)
        self.assertTrue(report['graph']['valid_file'])
        self.assertFalse(report['graph']['query_verified'])
        self.assertTrue(any('not yet established' in item for item in report['limitations']))

    def test_missing_history_still_records_incomplete_evidence(self):
        def failed(arguments, output, timeout=30, accepted=(0,)):
            Path(output).write_text('malloc_history failed')
            return dict(arguments=list(arguments), timeout_seconds=timeout, output=str(output),
                        status='error', returncode=2, bytes=22)
        capture = self.native.Capture(self.root, self.adapter, runner=failed)
        report = capture.execute([0x2000], full_history=False)
        self.assertFalse(report['free_stack'])
        self.assertIn('not yet established', report['limitations'][-1])
        self.assertEqual(report['histories'][0]['status'], 'error')

    def test_refuses_to_query_after_target_is_not_stopped(self):
        self.adapter.stopped = False
        capture = self.native.Capture(self.root, self.adapter, runner=self.runner)
        with self.assertRaisesRegex(RuntimeError, 'stopped'):
            capture.execute([0x1000])
        self.assertEqual(self.calls, [])

    def test_full_history_nonzero_leak_status_one_is_accepted_but_other_failure_is_not(self):
        calls = []
        def runner(arguments, output, timeout=30, accepted=(0,)):
            arguments = list(arguments)
            calls.append(arguments)
            if arguments[0] == '/usr/bin/malloc_history':
                if arguments[1] == '123':
                    Path(output).write_text('history unavailable')
                    return dict(status='error')
                Path(output).write_text('ALLOC 0x3000\n  0 libSystem_malloc.dylib 0x123 + 1\n'
                                        'FREE 0x3000\n  0 libSystem_malloc.dylib 0x456 + 2\n')
                return dict(status='ok')
            Path(arguments[2]).write_bytes(b'graph')
            return dict(status='ok', returncode=1)
        result = self.native.Capture(self.root, self.adapter, runner=runner).execute([0x3000])
        self.assertTrue(result['graph']['valid_file'])
        self.assertEqual(result['graph']['returncode'], 1)
        self.assertTrue(result['free_stack'])
        self.assertTrue(any(args[0] == '/usr/bin/leaks' for args in calls))

    def test_free_header_without_its_own_stack_is_not_free_stack_evidence(self):
        path = self.root / 'truncated.txt'
        path.write_text('ALLOC 0x1000 size=64\n  0 allocator 0x123 + 4\n'
                        'FREE 0x1000 size=64\n')
        evidence = self.native.history_evidence(path)
        self.assertTrue(evidence['allocation'])
        self.assertTrue(evidence['allocation_stack'])
        self.assertTrue(evidence['free'])
        self.assertFalse(evidence['free_stack'])
        self.assertFalse(evidence['stack'])

    def test_free_stack_cannot_substitute_for_missing_allocation_stack(self):
        path = self.root / 'allocation-truncated.txt'
        path.write_text('ALLOC 0x1000 size=64\nFREE 0x1000 size=64\n'
                        '  0 deallocator 0x456 + 8\n')
        evidence = self.native.history_evidence(path)
        self.assertTrue(evidence['free_stack'])
        self.assertFalse(evidence['allocation_stack'])
        self.assertFalse(evidence['stack'])

    def test_pipe_separated_same_line_allocation_and_free_stacks_are_supported(self):
        path = self.root / 'same-line.txt'
        path.write_text('ALLOC 0x1000 [size=7137]: thread_123 | start | main | malloc\n'
                        'FREE 0x1000 [size=7137]: thread_123 | start | main | free\n')
        evidence = self.native.history_evidence(path)
        self.assertTrue(evidence['allocation_stack'])
        self.assertTrue(evidence['free_stack'])
        self.assertTrue(evidence['stack'])

    def test_truncated_free_after_same_line_allocation_stack_is_rejected(self):
        path = self.root / 'same-line-truncated.txt'
        path.write_text('ALLOC 0x1000 [size=7137]: thread_123 | start | main | malloc\n'
                        'FREE 0x1000 [size=7137]: thread_123\n')
        evidence = self.native.history_evidence(path)
        self.assertTrue(evidence['allocation_stack'])
        self.assertTrue(evidence['free'])
        self.assertFalse(evidence['free_stack'])
        self.assertFalse(evidence['stack'])

    def apple_history_fixture(self):
        # Exact final two lifetimes from the 2026-10-18 macOS preflight report:
        # a previous 4096-byte use of this address, then our 7137-byte canary.
        return files('tests.diagnostics') / 'malloc_history_macos_20261018.txt'

    def test_real_apple_frames_need_neither_offsets_nor_public_allocator_names(self):
        evidence = self.native.history_evidence(self.apple_history_fixture())
        self.assertTrue(all(evidence.values()), evidence)

    def test_real_apple_canary_records_match_size_and_symbol_filters(self):
        for filters in ({'expected_size': 7137}, {'expected_symbol': 'pg_canary_allocate'},
                        {'expected_size': 7137, 'expected_symbol': 'pg_canary_allocate'}):
            with self.subTest(filters=filters):
                evidence = self.native.history_evidence(self.apple_history_fixture(), **filters)
                self.assertTrue(all(evidence.values()), evidence)

    def test_canary_filters_reject_wrong_size_symbol_or_unrelated_lifetime(self):
        for filters in ({'expected_size': 71370}, {'expected_symbol': 'pg_canary'},
                        {'expected_size': 4096, 'expected_symbol': 'pg_canary_allocate'},
                        {'expected_size': 7137, 'expected_symbol': 'AutoreleasePoolPage'}):
            with self.subTest(filters=filters):
                evidence = self.native.history_evidence(self.apple_history_fixture(), **filters)
                self.assertFalse(any(evidence.values()), evidence)

    def test_older_complete_lifetime_cannot_supply_truncated_canary_free_stack(self):
        path = self.root / 'canary-free-truncated.txt'
        original = self.apple_history_fixture().read_text()
        free_start = original.rindex('FREE ')
        path.write_text(original[:free_start] +
                        'FREE 0x12000a000-0x12000bbe0 [size=7137]:\n')
        # The earlier lifetime really has complete stacks; filtering must exclude it.
        self.assertTrue(self.native.history_evidence(path)['stack'])
        evidence = self.native.history_evidence(
            path, expected_size=7137, expected_symbol='pg_canary_allocate')
        self.assertTrue(evidence['allocation_stack'])
        self.assertFalse(evidence['free_stack'])
        self.assertFalse(evidence['stack'])

    def test_canary_symbol_must_appear_on_a_stack_line_for_each_record(self):
        path = self.root / 'canary-symbol-note.txt'
        original = self.apple_history_fixture().read_text()
        free_start = original.rindex('FREE ')
        path.write_text(original[:free_start] +
                        'FREE 0x12000a000-0x12000bbe0 [size=7137]:\n'
                        '  0x123 (canary) unrelated_function\n'
                        'note: expected pg_canary_allocate\n')
        evidence = self.native.history_evidence(
            path, expected_size=7137, expected_symbol='pg_canary_allocate')
        self.assertTrue(evidence['allocation_stack'])
        self.assertFalse(evidence['free_stack'])
        self.assertFalse(evidence['stack'])

    def test_size_filter_is_not_taken_from_a_stack_frame(self):
        path = self.root / 'size-not-in-header.txt'
        for separator in (': ', '\n  '):
            with self.subTest(separator=separator):
                path.write_text('ALLOC 0x1000' + separator +
                                '0x123 (canary) pg_canary_allocate size=7137\n'
                                'FREE 0x1000' + separator +
                                '0x456 (canary) pg_canary_allocate size=7137\n')
                evidence = self.native.history_evidence(
                    path, expected_size=7137, expected_symbol='pg_canary_allocate')
                self.assertFalse(any(evidence.values()), evidence)

    def test_apple_multiline_frames_preserve_record_filters(self):
        path = self.root / 'multiline-apple.txt'
        path.write_text(self.apple_history_fixture().read_text().replace(']:', ']:\n  ')
                        .replace(' | ', '\n  '))
        evidence = self.native.history_evidence(
            path, expected_size=7137, expected_symbol='pg_canary_allocate')
        self.assertTrue(all(evidence.values()), evidence)

    def test_capture_does_not_promote_truncated_free_record(self):
        def truncated(arguments, output, timeout=30, accepted=(0,)):
            Path(output).write_text('ALLOC 0x1000\n  0 allocator 0x123 + 4\nFREE 0x1000\n')
            return dict(status='ok')
        result = self.native.Capture(self.root, self.adapter, runner=truncated).execute(
            [0x1000], full_history=False)
        self.assertFalse(result['free_stack'])
        self.assertFalse(result['priority_evidence_complete'])

    def test_unrelated_free_history_cannot_mask_unresolved_priority_image(self):
        def runner(arguments, output, timeout=30, accepted=(0,)):
            arguments = list(map(str, arguments))
            self.calls.append(arguments)
            if arguments[0] == '/usr/bin/leaks':
                Path(arguments[2]).write_bytes(b'graph')
                Path(output).write_text('graph created')
            elif arguments[-1] == '0x1000':
                # First address is the old link involved in the native fault.
                Path(output).write_text('ALLOC 0x1000\n  0 allocator 0x123 + 4\nFREE 0x1000\n')
            else:
                Path(output).write_text('ALLOC 0x2000\n  0 allocator 0x123 + 4\n'
                                        'FREE 0x2000\n  0 deallocator 0x456 + 8\n')
            return dict(status='ok')
        result = self.native.Capture(self.root, self.adapter, runner=runner).execute([0x1000, 0x2000])
        self.assertTrue(any(args[0] == '/usr/bin/leaks' for args in self.calls))
        self.assertEqual(result['priority_address'], '0x1000')
        self.assertTrue(result['any_free_stack'])
        self.assertFalse(result['free_stack'])
        self.assertFalse(result['priority_evidence_complete'])

    def test_live_replacement_does_not_require_free_evidence_after_priority_is_resolved(self):
        def runner(arguments, output, timeout=30, accepted=(0,)):
            arguments = list(map(str, arguments))
            self.calls.append(arguments)
            text = 'ALLOC ' + arguments[-1] + '\n  0 allocator 0x123 + 4\n'
            if arguments[-1] == '0x1000':
                text += 'FREE 0x1000\n  0 deallocator 0x456 + 8\n'
            Path(output).write_text(text)
            return dict(status='ok')
        result = self.native.Capture(self.root, self.adapter, runner=runner).execute([0x1000, 0x2000])
        self.assertTrue(result['free_stack'])
        self.assertTrue(result['priority_evidence_complete'])
        self.assertIsNone(result['graph'])
        self.assertEqual(len(self.calls), 2)

    def test_target_losing_stopped_state_prevents_more_queries_and_graph(self):
        def resumes(arguments, output, timeout=30, accepted=(0,)):
            row = self.runner(arguments, output, timeout, accepted)
            self.adapter.stopped = False
            return row
        result = self.native.Capture(self.root, self.adapter, runner=resumes).execute([0x1000, 0x2000])
        self.assertEqual(len(self.calls), 1)
        self.assertFalse(result['process_stopped'])
        self.assertFalse(result['artifact_complete'])
        self.assertIsNone(result['graph'])
        self.assertTrue(any('did not remain stopped' in item for item in result['limitations']))

    def test_real_tool_timeout_keeps_flushed_output_and_checksum(self):
        path = self.root / 'timeout.txt'
        code = "import time; print('before timeout', flush=True); time.sleep(30)"
        result = self.native.run_tool([sys.executable, '-c', code], path, timeout=1)
        self.assertEqual(result['status'], 'timeout')
        self.assertEqual(path.read_text(), 'before timeout\n')
        self.assertEqual(result['bytes'], len(b'before timeout\n'))
        self.assertEqual(result['sha256'], self.native.sha256(path))
        self.assertLess(result['elapsed_seconds'], 10)


class LLDBProfileTests(unittest.TestCase):
    def test_exact_source_profile_offsets_and_target_expression_absence(self):
        module = load('_pg_lldb_test', 'pg_undo_trace_lldb.py')
        self.assertEqual(module.PROFILE, dict(rna_owner=0, rna_data=16, node_name=48,
                                              node_image=216, id_name=40, id_uid=324))
        source = (files('tests.diagnostics') / 'pg_undo_trace_lldb.py').read_text()
        self.assertNotIn('EvaluateExpression', source)
        self.assertNotIn("HandleCommand('expr", source)
        self.assertIn('ReadMemory', source)


if __name__ == '__main__':
    unittest.main()


class LLDBControlTests(unittest.TestCase):
    def setUp(self):
        self.module = load('_pg_lldb_control_test', 'pg_undo_trace_lldb.py')
        self.api = SimpleNamespace(eStateStopped=1, eStateCrashed=2, eStateExited=3,
                                   eStateDetached=4, eStateInvalid=5, eStateRunning=6,
                                   eStopReasonException=10, eStopReasonSignal=11,
                                   eStopReasonBreakpoint=12, SBEvent=lambda: object())

    def test_async_resume_does_not_reprocess_stale_stop(self):
        process = SimpleNamespace(state=1, stop_id=7)
        process.GetState = lambda: process.state
        process.GetStopID = lambda: process.stop_id
        visits = []
        def event(_seconds, _event):
            visits.append(process.stop_id)
            process.stop_id = 8
        driver = self.module.Driver.__new__(self.module.Driver)
        driver.process = process
        driver.listener = SimpleNamespace(WaitForEvent=event)
        driver.wait_after_stop_id = 7
        with patch.object(self.module, 'lldb', self.api):
            driver.wait_stop(1)
        self.assertEqual(visits, [7])
        self.assertEqual(driver.last_stop_id, 8)
        self.assertIsNone(driver.wait_after_stop_id)

    def test_native_fault_signals_are_distinct_from_semantic_breakpoints(self):
        def thread(reason, number=0):
            return SimpleNamespace(GetStopReason=lambda: reason, GetStopReasonDataCount=lambda: 1,
                                   GetStopReasonDataAtIndex=lambda _index: number)
        with patch.object(self.module, 'lldb', self.api):
            self.assertTrue(self.module.native_fault(thread(11, 11)))
            self.assertTrue(self.module.native_fault(thread(10)))
            self.assertFalse(self.module.native_fault(thread(12)))
            self.assertFalse(self.module.native_fault(thread(11, 19)))

    def test_unsupported_symbol_refuses_reproduction_with_resolution_event(self):
        empty = SimpleNamespace(GetSize=lambda: 0)
        driver = self.module.Driver.__new__(self.module.Driver)
        driver.target = SimpleNamespace(FindFunctions=lambda *_args: empty)
        events = []
        driver.emit = lambda *args, **kwargs: events.append((args, kwargs))
        with patch.object(self.module, 'lldb', SimpleNamespace(eFunctionNameTypeAuto=0)):
            with self.assertRaisesRegex(RuntimeError, 'unresolved'):
                driver.symbol_break('missing_setter', 'setter')
        self.assertEqual(events[0][1]['locations'], 0)

    def test_invalid_dwarf_offset_cannot_select_a_layout(self):
        member_type = SimpleNamespace(IsValid=lambda: True, GetByteSize=lambda: 8)
        member = SimpleNamespace(GetName=lambda: 'id', GetOffsetInBytes=lambda: (1 << 64) - 1,
                                 GetType=lambda: member_type)
        typ = SimpleNamespace(IsValid=lambda: True, GetNumberOfFields=lambda: 1,
                              GetFieldAtIndex=lambda _i: member, GetByteSize=lambda: 384)
        target = SimpleNamespace(FindFirstType=lambda _name: typ)
        self.assertIsNone(self.module.field_offset(target, 'bNode', 'id'))
