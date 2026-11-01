"""Real child-process fault tests for the foreground execution service."""
from concurrent.futures import CancelledError
from dataclasses import replace
import gc
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import weakref

import numpy as np
from color_tools.blender_runtime.execution.contracts import CapacityError, ExecutionError, JobSpec, RuntimeLimits, RuntimeProfile
from color_tools.blender_runtime.execution import constants as policy
import color_tools.blender_runtime.execution
from color_tools.blender_runtime.execution.runtime import ExecutionRuntime
from color_tools.blender_runtime import App
from color_tools.blender_runtime.execution.machines import ExecutionMachines
from .test_app import MachineFixture


FIXTURE = Path(__file__).with_name('helper_fixture.py')


class RuntimeRegressionTests(MachineFixture, unittest.TestCase):
    def setUp(self):
        self.directory = self.enterContext(tempfile.TemporaryDirectory())
        self.runtimes = []
        self.machines = ExecutionMachines(*(self.machine(name) for name in ("attempt", "gpu", "retry", "startup")))
        self.addCleanup(self.close)

    def close(self):
        for runtime in self.runtimes:
            runtime.shutdown()

    def runtime(self, mode='normal', **limits):
        defaults = dict(startup_seconds=3., stalled_seconds=3., shutdown_seconds=.1)
        settings = replace(RuntimeLimits(), **(defaults | limits))
        profile = RuntimeProfile(lanes=('linear', 'bulk', 'gpu', 'scope_gpu'),
            gpu_probes=(('gpu_probe', 'gpu'), ('scope_probe', 'scope_gpu')),
            uncached_operations=('scope_register',))
        app = App(package="runtime_tests", storage_name="runtime_tests")
        runtime = ExecutionRuntime(self.directory, app=app, machines=self.machines, limits=settings, profile=profile,
            package=Path(color_tools.blender_runtime.execution.__file__).parent.parent.parent,
            environment=dict(os.environ, PYTHONPATH=os.pathsep.join(sys.path)),
            launcher=lambda config: [sys.executable, str(FIXTURE), config['config_path'], mode])
        self.runtimes.append(runtime)
        return runtime

    def pump(self, runtime, condition, timeout=6):
        end = time.monotonic() + timeout
        while not condition() and time.monotonic() < end:
            runtime.poll()
            time.sleep(.002)
        self.assertTrue(condition(), 'Execution did not reach the required state')

    def receipts(self, runtime, role='bulk'):
        path = runtime.session.path / ('fixture-' + role + '.jsonl')
        return [] if not path.exists() else [json.loads(line) for line in path.read_text().splitlines()]

    def test_real_helper_roundtrip_wait_pumps_without_timers(self):
        runtime = self.runtime()
        values = np.arange(120, dtype='f4').reshape(10, 12)[:, ::2]
        handle = runtime.submit(JobSpec('fixture', {'value': values}))
        actual = handle.result(timeout=6)
        self.assertNotEqual(actual['pid'], os.getpid())
        np.testing.assert_array_equal(actual['value'], values)
        self.assertFalse(actual['value'].flags.writeable)
        self.assertEqual(actual['generation'], 1)
        report = runtime.shutdown()
        self.assertTrue(report.clean)
        self.assertEqual(json.loads((runtime.session.path / 'journal.json').read_text())['clean'], report.clean)
        np.testing.assert_array_equal(actual['value'], values)

    def test_actor_thread_consumer_finalizer_defers_cancel_to_foreground(self):
        runtime=self.runtime()
        held=[runtime.submit(JobSpec('fixture',{'value':1}))]
        job=held[0]._job
        identity=held[0].identity
        released=threading.Event()
        def collect_on_actor():
            held.clear()
            gc.collect()
            released.set()
        runtime.app.actors.loop.call_soon_threadsafe(collect_on_actor)
        self.assertTrue(released.wait(2))
        self.assertIn(identity,job.consumers)
        self.assertFalse(job.finished)
        runtime.app.drain_finalizers()
        self.assertNotIn(identity,job.consumers)
        self.assertTrue(job.finished)
        self.assertFalse(runtime.helpers)
        runtime.shutdown()
        runtime.app.close()

    def test_cancel_keeps_physical_lane_until_helper_receipt(self):
        runtime = self.runtime()
        gate = Path(self.directory) / 'release'
        first = runtime.submit(JobSpec('fixture', {'gate': str(gate), 'label': 'first'}))
        self.pump(runtime, lambda: first.progress == .25)
        first.cancel()
        second = runtime.submit(JobSpec('fixture', {'value': 'second', 'label': 'second'}))
        for _ in range(10):
            runtime.poll();time.sleep(.002)
        self.assertTrue(first.done())
        self.assertFalse(first.retired())
        self.assertEqual(first._job.state.phase, policy.CANCELLING)
        self.assertEqual(second.status, 'queued')
        self.assertEqual(len(self.receipts(runtime)), 1)
        gate.touch()
        self.assertEqual(second.result(timeout=6)['value'], 'second')
        self.assertTrue(first.retired())
        with self.assertRaises(CancelledError):
            first.result()

    def test_shared_consumer_survives_other_cancellation_and_reuses_result(self):
        runtime = self.runtime()
        gate = Path(self.directory) / 'release'
        spec = JobSpec('fixture', {'gate': str(gate), 'value': 42}, key='shared')
        first, second = runtime.submit(spec), runtime.submit(spec)
        self.pump(runtime, lambda: second.progress == .25)
        first.cancel()
        self.assertEqual(second._job.state.phase, policy.RUNNING)
        self.assertEqual(second._job.state.interests, 1)
        gate.touch()
        self.assertEqual(second.result(timeout=6)['value'], 42)
        cached = runtime.submit(spec)
        self.assertIs(cached.result(), second.result())
        self.assertEqual(len(self.receipts(runtime)), 1)

    def test_consumer_capacity_bounds_stream_events_and_retains_terminal_receipts(self):
        runtime = self.runtime(pending_jobs=1)
        gate = Path(self.directory) / 'release'
        spec = JobSpec('fixture', {'gate': str(gate), 'stream': 32, 'value': 'final'}, key='shared')
        handles = [runtime.submit(spec) for _ in range(4)]
        with self.assertRaisesRegex(CapacityError, 'consumer'):
            runtime.submit(spec)
        end = time.monotonic() + 6
        while handles[0].progress != .32 and time.monotonic() < end:
            runtime._pump();time.sleep(.002)
        self.assertEqual(handles[0].progress, .32)
        self.assertEqual(len(runtime.events), 8)
        for handle in handles:
            events = {event.kind: event.value for event in runtime.events if event.handle == handle.identity}
            self.assertEqual(events, {'progress': .32, 'preview': {'preview': 32}})
        handles[0].cancel()
        gate.touch()
        runtime.wait_exact(handles[1:], deadline=time.monotonic() + 6)
        events = runtime.poll()
        self.assertEqual({event.handle: event.kind for event in events},
                         {handle.identity: 'cancelled' if index == 0 else 'complete'
                          for index, handle in enumerate(handles)})
        self.assertEqual(len(events), 4)
        self.assertFalse(runtime.poll())

    def test_completed_cache_hit_produces_terminal_event_for_poll_callers(self):
        runtime = self.runtime()
        spec = JobSpec('fixture', {'value': 'cached'}, key='cached')
        first = runtime.submit(spec)
        first.result(timeout=6)
        runtime.poll()
        cached = runtime.submit(spec)
        events = runtime.poll()
        self.assertEqual([(event.handle, event.kind) for event in events], [(cached.identity, 'complete')])
        self.assertEqual(events[0].value['value'], 'cached')
        self.assertEqual(len(self.receipts(runtime)), 1)

    def test_cached_consumers_and_events_are_released_when_handles_are_dropped(self):
        runtime = self.runtime(pending_jobs=1)
        spec = JobSpec('fixture', {'value': 'cached'}, key='cached')
        first = runtime.submit(spec)
        first.result(timeout=6)
        runtime.poll()
        for _ in range(100):
            cached = runtime.submit(spec)
            self.assertTrue(cached.done())
            del cached
        gc.collect()
        self.assertEqual(first._job.consumers, {first.identity})
        self.assertEqual(len(runtime.handles), 1)
        self.assertFalse(runtime.events)
        self.assertEqual(len(self.receipts(runtime)), 1)

    def test_abandoned_last_consumer_cancels_without_freeing_live_slot(self):
        runtime = self.runtime()
        gate = Path(self.directory) / 'release'
        handle = runtime.submit(JobSpec('fixture', {'gate': str(gate)}))
        self.pump(runtime, lambda: handle.progress == .25)
        job, reference = handle._job, weakref.ref(handle)
        del handle;gc.collect()
        self.assertIsNone(reference())
        runtime.poll()
        self.assertEqual(job.state.phase, policy.CANCELLING)
        self.assertFalse(job.finished)
        gate.touch()
        self.pump(runtime, lambda: job.finished)

    def test_actual_kill_retries_in_fresh_generation_and_attempt(self):
        runtime = self.runtime()
        gate = Path(self.directory) / 'release'
        handle = runtime.submit(JobSpec('fixture', {'gate': str(gate), 'value': 'retained inputs'}))
        self.pump(runtime, lambda: handle.progress == .25)
        old = runtime.helpers['bulk']
        identity = handle._job.state.identity
        old.process.kill();old.process.wait(timeout=3)
        gate.touch()
        result = handle.result(timeout=6)
        self.assertEqual(result['value'], 'retained inputs')
        self.assertEqual(result['generation'], 2)
        self.assertNotEqual(result['pid'], old.process.pid)
        self.assertNotEqual(handle._job.state.identity, identity)

    def test_helper_kill_during_incremental_staging_releases_partial_input(self):
        runtime = self.runtime()
        handle = runtime.submit(JobSpec('fixture', {'value': 23, 'unused': np.zeros(1024 * 1024, dtype='f4')}))
        original = runtime.payloads.encode_iter
        def slowed(value, files):
            generator = original(value, files)
            try:
                while True:
                    try:
                        value = next(generator)
                    except StopIteration as finished:
                        return finished.value
                    time.sleep(.006)
                    yield value
            finally:
                generator.close()
        with patch.object(runtime.payloads, 'encode_iter', side_effect=slowed):
            self.pump(runtime, lambda: bool(handle._job.input_files))
            stage, attempt = handle._job.stage, handle._job.state.identity
            partial = tuple(runtime.session.path / name for name in handle._job.input_files)
            helper = runtime.helpers['bulk']
            self.assertIsNone(helper.active)
            helper.process.kill();helper.process.wait(timeout=3)
            runtime.poll()
            self.assertIsNone(stage.gi_frame)
            self.assertNotEqual(handle._job.state.identity, attempt)
            self.assertTrue(all(not path.exists() for path in partial))
            self.assertEqual(handle._job.retries, 0)
        self.assertEqual(handle.result(timeout=6)['value'], 23)
        self.assertEqual(runtime.generations['bulk'], 2)
        self.assertEqual(len(self.receipts(runtime)), 1)
        self.assertEqual(runtime.startup_failures['bulk'], 0)

    def test_gpu_failure_moves_active_and_already_queued_interests_to_cpu(self):
        runtime = self.runtime()
        first = runtime.submit(JobSpec('fixture', {'value': 'first', 'fail_gpu': True}, lane='gpu'))
        second = runtime.submit(JobSpec('fixture', {'value': 'second'}, lane='gpu'))
        self.assertEqual(first.result(timeout=6)['value'], 'first')
        self.assertEqual(second.result(timeout=6)['value'], 'second')
        self.assertEqual((first.backend, second.backend), ('bulk', 'bulk'))
        self.assertEqual(len(self.receipts(runtime, 'gpu')), 1)
        self.assertEqual(len(self.receipts(runtime, 'bulk')), 2)
        self.assertIn('Fixture computation failure', second.fallback_reason)

    def test_scope_gpu_has_an_independent_physical_slot_and_generation(self):
        runtime = self.runtime()
        gate = Path(self.directory) / 'release-lut'
        lut = runtime.submit(JobSpec('fixture', {'gate': str(gate)}, lane='gpu'))
        self.pump(runtime, lambda: lut.progress == .25)
        scope = runtime.submit(JobSpec('scope_update', {'value': 'visual'}, lane='scope_gpu'))
        visual = scope.result(timeout=6)
        self.assertEqual((scope.backend, scope.generation, visual['role']), ('scope_gpu', 1, 'scope_gpu'))
        self.assertNotEqual(visual['pid'], runtime.helpers['gpu'].process.pid)
        self.assertFalse(lut.done())
        gate.touch()
        lut.result(timeout=6)

    def test_gpu_role_failures_do_not_disable_the_other_role(self):
        for failed_role, healthy_role in (('gpu', 'scope_gpu'), ('scope_gpu', 'gpu')):
            with self.subTest(failed_role=failed_role):
                runtime = self.runtime()
                failed = runtime.submit(JobSpec('fixture', {'fail_gpu': True, 'value': 'fallback'}, lane=failed_role))
                with self.assertLogs('color_tools.blender_runtime.execution.runtime', level='WARNING'):
                    self.assertEqual(failed.result(timeout=6)['value'], 'fallback')
                self.assertEqual(failed.backend, 'bulk')
                self.assertEqual(runtime.gpu_status(failed_role)['state'], 'fallback')
                self.assertEqual(runtime.gpu_status(failed_role)['diagnostic'].role, failed_role)
                self.assertEqual(runtime.gpu_status(healthy_role), dict(state='ready', reason='', diagnostic=None))
                healthy = runtime.submit(JobSpec('fixture', {'value': 'healthy'}, lane=healthy_role))
                self.assertEqual(healthy.result(timeout=6)['role'], healthy_role)
                self.assertEqual(healthy.backend, healthy_role)

    def test_scope_gpu_probe_only_restores_its_own_role_and_is_uncached(self):
        runtime = self.runtime('probe_gate')
        for role in ('gpu', 'scope_gpu'):
            handle = runtime.submit(JobSpec('fixture', {'fail_gpu': True}, lane=role))
            with self.assertLogs('color_tools.blender_runtime.execution.runtime', level='WARNING'):
                handle.result(timeout=6)
        old = runtime.helpers['scope_gpu']
        probe = runtime.retry_gpu('scope_gpu')
        self.assertIs(runtime.retry_gpu('scope_gpu'), probe)
        self.assertEqual(runtime.gpu_status('scope_gpu')['state'], 'probing')
        self.assertEqual(runtime.gpu_status()['state'], 'fallback')
        during = runtime.submit(JobSpec('scope_update', {'value': 'during'}, lane='scope_gpu'))
        self.assertEqual(during.result(timeout=6)['role'], 'bulk')
        self.pump(runtime, lambda: probe.progress == .25)
        (runtime.session.path / 'probe-release').touch()
        self.assertTrue(probe.result(timeout=6)['conformance'])
        self.assertEqual(runtime.gpu_status('scope_gpu')['state'], 'ready')
        self.assertEqual(runtime.gpu_status()['state'], 'fallback')
        self.assertNotEqual(runtime.helpers['scope_gpu'].process.pid, old.process.pid)
        self.assertEqual(runtime.generations['scope_gpu'], 2)
        self.assertEqual([row['operation'] for row in self.receipts(runtime, 'scope_gpu')],
                         ['fixture', 'scope_probe'])

    def test_scope_gpu_cancellation_preserves_preview_and_physical_occupancy(self):
        runtime = self.runtime()
        gate = Path(self.directory) / 'release-scope'
        first = runtime.submit(JobSpec('scope_update', {'gate': str(gate), 'stream': 1}, lane='scope_gpu'))
        self.pump(runtime, lambda: first.preview is not None)
        self.assertEqual(first.preview, {'preview': 1})
        first.cancel()
        second = runtime.submit(JobSpec('scope_update', {'value': 'newest'}, lane='scope_gpu'))
        runtime.poll()
        self.assertTrue(first.done())
        self.assertFalse(first.retired())
        self.assertEqual(first.preview, {'preview': 1})
        self.assertEqual(second.status, 'queued')
        gate.touch()
        self.assertEqual(second.result(timeout=6)['value'], 'newest')
        self.assertTrue(first.retired())

    def test_scope_preview_remains_available_when_terminal_event_supersedes_it(self):
        runtime = self.runtime()
        handle = runtime.submit(JobSpec('scope_update', {'stream': 1, 'value': 'stats'}, lane='scope_gpu'))
        self.assertEqual(handle.result(timeout=6)['value'], 'stats')
        events = runtime.poll()
        self.assertEqual([(event.handle, event.kind) for event in events], [(handle.identity, 'complete')])
        self.assertEqual(handle.preview, {'preview': 1})

    def test_role_specific_results_and_registrations_cannot_be_shared_from_cache(self):
        runtime = self.runtime()
        lut = runtime.submit(JobSpec('fixture', {'value': 'lut'}, lane='gpu', key='same'))
        self.assertEqual(lut.result(timeout=6)['value'], 'lut')
        scope = runtime.submit(JobSpec('fixture', {'value': 'scope'}, lane='scope_gpu', key='same'))
        self.assertEqual(scope.result(timeout=6)['value'], 'scope')
        self.assertIsNot(lut._job, scope._job)
        with self.assertRaisesRegex(ExecutionError, 'fresh helper acknowledgement'):
            runtime.submit(JobSpec('scope_register', {}, lane='scope_gpu', key='source'))
        with self.assertRaisesRegex(ExecutionError, 'explicit retry'):
            runtime.submit(JobSpec('scope_probe', {}, lane='scope_gpu'))
        with self.assertRaisesRegex(ValueError, 'Unknown GPU role'):
            runtime.retry_gpu('bulk')
        with self.assertRaisesRegex(ValueError, 'Unknown GPU role'):
            runtime.gpu_status('bulk')

    def test_stale_generation_and_attempt_replies_are_ignored(self):
        runtime = self.runtime()
        handle = runtime.submit(JobSpec('fixture', {'stale': True, 'value': 'current'}))
        self.assertEqual(handle.result(timeout=6)['value'], 'current')

    def test_gpu_probe_is_fresh_uncached_and_keeps_valid_cpu_results(self):
        runtime = self.runtime('probe_gate')
        spec = JobSpec('fixture', {'value': 'valid output', 'fail_gpu': True, 'long_trace': True}, lane='gpu', key='grade')
        initial = runtime.submit(spec)
        with self.assertLogs('color_tools.blender_runtime.execution.runtime', level='WARNING') as logged:
            result = initial.result(timeout=6)
        self.assertEqual(len(logged.records), 1)
        health = runtime.gpu_status()
        self.assertEqual(health['state'], 'fallback')
        diagnostic = health['diagnostic']
        self.assertEqual((diagnostic.backend, diagnostic.device), ('METAL', 'Fixture device'))
        self.assertTrue(diagnostic.traceback.endswith('full traceback detail\n' * 400))
        self.assertEqual(diagnostic.fingerprint, runtime.fingerprint)
        saved = json.loads(Path(diagnostic.diagnostic_path).read_text())
        self.assertEqual(saved['traceback'], diagnostic.traceback)
        self.assertTrue(Path(saved['helper_log_path']).exists())
        old = runtime.helpers['gpu']
        probe = runtime.retry_gpu()
        self.assertIs(runtime.retry_gpu(), probe)
        self.assertEqual(runtime.gpu_status()['state'], 'probing')
        cached = runtime.submit(spec)
        self.assertIs(cached.result(), result)
        during = runtime.submit(JobSpec('fixture', {'value': 'during probe'}, lane='gpu'))
        self.assertEqual(during.result(timeout=6)['value'], 'during probe')
        self.assertEqual(during.backend, 'bulk')
        self.pump(runtime, lambda: probe.progress == .25)
        self.assertFalse(probe.done())
        self.assertEqual(runtime.gpu_status()['state'], 'probing')
        (runtime.session.path / 'probe-release').touch()
        self.assertTrue(probe.result(timeout=6)['conformance'])
        self.assertEqual(runtime.gpu_status()['state'], 'ready')
        self.assertIsNone(runtime.gpu_failure)
        self.assertEqual(probe.backend, 'gpu')
        self.assertIsNotNone(old.process.poll())
        self.assertEqual(runtime.generations['gpu'], 2)
        self.assertNotEqual(runtime.helpers['gpu'].process.pid, old.process.pid)
        self.assertIs(runtime.submit(spec).result(), result)
        next_job = runtime.submit(JobSpec('fixture', {'value': 'new GPU job'}, lane='gpu'))
        self.assertEqual(next_job.result(timeout=6)['value'], 'new GPU job')
        self.assertEqual(next_job.backend, 'gpu')
        self.assertEqual([row['operation'] for row in self.receipts(runtime, 'gpu')],
                         ['fixture', 'gpu_probe', 'fixture'])
        self.assertEqual(len(self.receipts(runtime, 'bulk')), 2)

    def test_failed_or_invalid_gpu_probe_never_falls_back_or_spins(self):
        for mode in ('probe_fail', 'probe_invalid'):
            with self.subTest(mode=mode):
                runtime = self.runtime(mode)
                with self.assertLogs('color_tools.blender_runtime.execution.runtime', level='WARNING') as logged:
                    probe = runtime.retry_gpu()
                    with self.assertRaises(ExecutionError):probe.result(timeout=6)
                self.assertEqual(len(logged.records), 1)
                self.assertEqual(runtime.gpu_status()['state'], 'fallback')
                self.assertEqual(probe.backend, 'gpu')
                self.assertFalse(self.receipts(runtime, 'bulk'))
                for _ in range(10):runtime.poll()
                self.assertEqual(runtime.generations['gpu'], 1)
                normal = runtime.submit(JobSpec('fixture', {'value': 'CPU after failure'}, lane='gpu'))
                self.assertEqual(normal.result(timeout=6)['value'], 'CPU after failure')
                self.assertEqual(normal.backend, 'bulk')
                self.assertEqual(len(self.receipts(runtime, 'gpu')), 1)

    def test_gpu_probe_ignores_stale_receipts_and_is_private_admission(self):
        runtime = self.runtime('probe_stale')
        with self.assertRaises(ExecutionError):runtime.submit(JobSpec('gpu_probe', {}, lane='gpu'))
        with self.assertRaises(ExecutionError):runtime.submit(JobSpec('gpu_probe', {}, key='cached'))
        probe = runtime.retry_gpu()
        self.assertTrue(probe.result(timeout=6)['conformance'])
        self.assertEqual(runtime.gpu_status()['state'], 'ready')
        self.assertEqual(len(self.receipts(runtime, 'gpu')), 1)
        self.assertFalse(runtime.cache)

    def test_gpu_crash_logs_one_incident_for_multiple_queued_requests(self):
        runtime = self.runtime()
        gate = Path(self.directory) / 'release-gpu'
        first = runtime.submit(JobSpec('fixture', {'value': 1, 'gate': str(gate)}, lane='gpu'))
        second = runtime.submit(JobSpec('fixture', {'value': 2}, lane='gpu'))
        self.pump(runtime, lambda: first.progress == .25)
        process = runtime.helpers['gpu'].process
        process.kill();process.wait(timeout=3);gate.touch()
        with self.assertLogs('color_tools.blender_runtime.execution.runtime', level='WARNING') as logged:
            self.assertEqual(first.result(timeout=6)['value'], 1)
            self.assertEqual(second.result(timeout=6)['value'], 2)
        self.assertEqual(len(logged.records), 1)
        self.assertEqual(len(runtime.diagnostics), 1)
        self.assertEqual((first.backend, second.backend), ('bulk', 'bulk'))

    def test_idle_gpu_death_requires_explicit_validated_recovery(self):
        runtime = self.runtime()
        first = runtime.submit(JobSpec('fixture', {'value': 7}, lane='gpu'))
        first.result(timeout=6)
        process = runtime.helpers['gpu'].process
        process.kill();process.wait(timeout=3)
        with self.assertLogs('color_tools.blender_runtime.execution.runtime', level='WARNING') as logged:runtime.poll()
        self.assertEqual(len(logged.records), 1)
        self.assertEqual(runtime.gpu_status()['state'], 'fallback')
        second = runtime.submit(JobSpec('fixture', {'value': 8}, lane='gpu'))
        self.assertEqual(second.result(timeout=6)['value'], 8)
        self.assertEqual(second.backend, 'bulk')
        self.assertEqual(runtime.generations['gpu'], 1)
        runtime.retry_gpu().result(timeout=6)
        self.assertEqual(runtime.gpu_status()['state'], 'ready')
        self.assertEqual(runtime.generations['gpu'], 2)

    def test_malformed_terminal_payload_requires_exit_before_retry(self):
        runtime = self.runtime()
        handle = runtime.submit(JobSpec('fixture', {'malformed_first': True, 'value': 'valid retry'}))
        self.assertEqual(handle.result(timeout=6)['value'], 'valid retry')
        rows = self.receipts(runtime)
        self.assertEqual([row['generation'] for row in rows], [1, 2])
        self.assertNotEqual(rows[0]['pid'], rows[1]['pid'])

    def test_repeated_crash_and_deterministic_failure_are_terminal(self):
        runtime = self.runtime()
        crashed = runtime.submit(JobSpec('fixture', {'crash': True}))
        with self.assertRaises(ExecutionError):
            crashed.result(timeout=6)
        self.assertEqual(len(self.receipts(runtime)), 2)
        failed = runtime.submit(JobSpec('fixture', {'fail': True}))
        with self.assertRaisesRegex(ExecutionError, 'Fixture computation failure'):
            failed.result(timeout=6)
        self.assertEqual(len(self.receipts(runtime)), 3)

    def test_crashing_job_cannot_exhaust_queued_peers_retry_budgets(self):
        for role in ('bulk', 'linear'):
            with self.subTest(role=role):
                runtime = self.runtime()
                crashed = runtime.submit(JobSpec('fixture', {'crash': True, 'label': 'A'}, lane=role))
                peers = [runtime.submit(JobSpec('fixture', {'value': label, 'label': label}, lane=role))
                         for label in ('B', 'C')]
                attempts = [peer._job.state.identity for peer in peers]
                with self.assertRaises(ExecutionError):
                    crashed.result(timeout=6)
                for label, peer, attempt in zip(('B', 'C'), peers, attempts):
                    self.assertEqual(peer.result(timeout=6)['value'], label)
                    self.assertEqual(peer._job.retries, 0)
                    self.assertNotEqual(peer._job.state.identity, attempt)
                self.assertEqual([row['value'] for row in self.receipts(runtime, role)],
                                 ['A', 'A', 'B', 'C'])
                self.assertEqual(crashed._job.retries, 1)

    def test_rebound_peer_keeps_its_own_active_crash_retry(self):
        for role in ('bulk', 'linear'):
            with self.subTest(role=role):
                runtime = self.runtime()
                gate = Path(self.directory) / ('release-' + role)
                crashed = runtime.submit(JobSpec('fixture', {'crash': True, 'label': 'A'}, lane=role))
                peer = runtime.submit(JobSpec('fixture', {'gate': str(gate), 'value': 'B', 'label': 'B'}, lane=role))
                with self.assertRaises(ExecutionError):
                    crashed.result(timeout=6)
                self.pump(runtime, lambda: peer.progress == .25)
                self.assertEqual(peer._job.retries, 0)
                helper = runtime.helpers[role]
                helper.process.kill();helper.process.wait(timeout=3)
                gate.touch()
                self.assertEqual(peer.result(timeout=6)['value'], 'B')
                self.assertEqual(peer._job.retries, 1)
                self.assertEqual([row['value'] for row in self.receipts(runtime, role)],
                                 ['A', 'A', 'B', 'B'])


    def test_failure_receipts_make_fresh_traceback_free_errors(self):
        runtime = self.runtime()
        for inputs, kind in (({'fail': True}, ExecutionError), ({'cancel_receipt': True}, CancelledError)):
            with self.subTest(kind=kind):
                handle = runtime.submit(JobSpec('fixture', inputs))
                first = handle.exception(timeout=6)
                second = handle.exception()
                self.assertIsInstance(first, kind)
                self.assertIsInstance(second, kind)
                self.assertIsNot(first, second)
                self.assertEqual(first.args, second.args)
                self.assertIsNone(first.__traceback__)
                self.assertIsNone(second.__traceback__)
                self.assertIsNone(first.__context__)
                self.assertNotIsInstance(handle._job.error, BaseException)
                del handle
                self.assertFalse(runtime.handles)
                self.assertFalse(runtime.events)

    def test_startup_failure_is_bounded(self):
        runtime = self.runtime('bad_hello')
        handle = runtime.submit(JobSpec('fixture', {}))
        with self.assertRaises(ExecutionError):
            handle.result(timeout=6)
        self.assertEqual(runtime.generations['bulk'], 2)

    def test_missing_handshake_reaches_startup_deadline(self):
        runtime = self.runtime('no_hello', startup_seconds=.1)
        handle = runtime.submit(JobSpec('fixture', {}))
        with self.assertRaisesRegex(ExecutionError, 'deadline'):
            handle.result(timeout=6)
        self.assertEqual(runtime.generations['bulk'], 2)
        self.assertFalse(runtime.helpers)

    def test_multiple_queued_jobs_share_bounded_helper_startup_failures(self):
        for mode in ('bad_hello', 'no_hello'):
            for role in ('bulk', 'linear'):
                with self.subTest(mode=mode, role=role):
                    runtime = self.runtime(mode, startup_seconds=.1 if mode == 'no_hello' else 3.)
                    handles = [runtime.submit(JobSpec('fixture', {'value': value}, lane=role)) for value in range(3)]
                    for handle in handles:
                        with self.assertRaises(ExecutionError):
                            handle.result(timeout=6)
                        self.assertEqual(handle._job.retries, 0)
                    self.assertEqual(runtime.generations[role], 2)
                    self.assertFalse(self.receipts(runtime, role))
                    self.assertFalse(runtime.helpers)
                    # Exhaustion applies to the current queue. A later request
                    # can start a newly repaired helper without inheriting it.
                    runtime.launcher = lambda config: [sys.executable, str(FIXTURE), config['config_path']]
                    # The deliberately tiny no-hello fault deadline is not a
                    # startup requirement for a healthy process under test load.
                    runtime.limits = replace(runtime.limits, startup_seconds=3.)
                    recovered = runtime.submit(JobSpec('fixture', {'value': 'recovered'}, lane=role))
                    self.assertEqual(recovered.result(timeout=6)['value'], 'recovered')

    def test_launch_failures_are_bounded_for_the_entire_cpu_queue(self):
        runtime = self.runtime()
        handles = [runtime.submit(JobSpec('fixture', {'value': value})) for value in range(3)]
        with patch.object(sys.modules[ExecutionRuntime.__module__], 'Helper', side_effect=OSError('Cannot launch')) as launch:
            for handle in handles:
                with self.assertRaisesRegex(ExecutionError, 'Cannot launch'):
                    handle.result(timeout=6)
                self.assertEqual(handle._job.retries, 0)
        self.assertEqual(launch.call_count, 2)
        self.assertEqual(runtime.generations['bulk'], 2)

    def test_dispatch_resets_helper_startup_failures(self):
        runtime = self.runtime()
        runtime.launcher = lambda config: [sys.executable, str(FIXTURE), config['config_path'],
            'bad_hello' if config['generation'] in (1, 3) else 'normal']
        gate = Path(self.directory) / 'release-after-startup'
        active = runtime.submit(JobSpec('fixture', {'gate': str(gate), 'value': 'active'}))
        peer = runtime.submit(JobSpec('fixture', {'value': 'peer'}))
        self.pump(runtime, lambda: active.progress == .25)
        self.assertEqual(runtime.generations['bulk'], 2)
        self.assertEqual(runtime.startup_failures['bulk'], 0)
        helper = runtime.helpers['bulk']
        helper.process.kill();helper.process.wait(timeout=3)
        gate.touch()
        self.assertEqual(active.result(timeout=6)['value'], 'active')
        self.assertEqual(peer.result(timeout=6)['value'], 'peer')
        self.assertEqual(runtime.generations['bulk'], 4)
        self.assertEqual((active._job.retries, peer._job.retries), (1, 0))

    def test_dispatch_send_failure_retires_process_before_retry(self):
        runtime = self.runtime()
        gate = Path(self.directory) / 'release'
        first = runtime.submit(JobSpec('fixture', {'gate': str(gate), 'value': 'first'}))
        self.pump(runtime, lambda: first.progress == .25)
        helper = runtime.helpers['bulk']
        gate.touch()
        first.result(timeout=6)
        original = helper.send
        def fail_dispatch(message):
            if message['kind'] == 'run':
                raise BufferError('Injected send failure after admission')
            return original(message)
        second = runtime.submit(JobSpec('fixture', {'value': 'retry'}))
        with patch.object(helper, 'send', side_effect=fail_dispatch):
            self.assertEqual(second.result(timeout=6)['value'], 'retry')
        self.assertIsNotNone(helper.process.poll())
        self.assertEqual(runtime.generations['bulk'], 2)

    def test_stage_one_lane_progresses_while_bulk_is_occupied(self):
        runtime = self.runtime()
        bulk = runtime.submit(JobSpec('fixture', {'hang': True}))
        self.pump(runtime, lambda: bulk.progress == .25)
        stage_one = runtime.submit(JobSpec('fixture', {'value': 'feedback'}, lane='linear'))
        self.assertEqual(stage_one.result(timeout=6)['value'], 'feedback')
        self.assertFalse(bulk.done())
        self.assertNotEqual(runtime.helpers['linear'].process.pid, runtime.helpers['bulk'].process.pid)

    def test_real_hang_watchdog_kills_and_retries_once(self):
        runtime = self.runtime(stalled_seconds=.12)
        handle = runtime.submit(JobSpec('fixture', {'hang': True}))
        with self.assertRaisesRegex(ExecutionError, 'deadline'):
            handle.result(timeout=6)
        self.assertEqual(len(self.receipts(runtime)), 2)
        self.assertFalse(runtime.helpers)

    def test_capacity_counts_active_inputs_and_queued_jobs(self):
        runtime = self.runtime(pending_jobs=2, payload_bytes=128)
        first = runtime.submit(JobSpec('fixture', {'value': np.zeros(16, dtype='f4')}))
        second = runtime.submit(JobSpec('fixture', {'value': np.zeros(16, dtype='f4')}))
        with self.assertRaises(CapacityError):
            runtime.submit(JobSpec('fixture', {}))
        first.cancel()
        with self.assertRaises(CapacityError):
            runtime.submit(JobSpec('fixture', {'value': np.zeros(17, dtype='f4')}))
        third = runtime.submit(JobSpec('fixture', {'value': np.zeros(16, dtype='f4')}))
        self.assertEqual(second.status, 'queued')
        self.assertEqual(third.status, 'queued')

    def test_execution_has_no_arbitrary_callback_retention(self):
        runtime = self.runtime()
        values = np.arange(32, dtype='f4')
        reference = weakref.ref(values)
        handle = runtime.submit(JobSpec('fixture', {'value': 7, 'unused': values}))
        self.assertFalse(hasattr(handle, 'add_done_callback'))
        del values
        self.assertIsNone(reference())
        self.assertEqual(handle.result(timeout=6)['value'], 7)

    def test_submit_seals_before_retention_and_rejects_arbitrary_graphs(self):
        runtime = self.runtime()
        class NativeReference:pass
        class ForeignList(list):pass
        for value in (NativeReference(), ForeignList([1]), np.array([object()], dtype=object)):
            with self.subTest(kind=type(value).__name__), self.assertRaises(TypeError):
                runtime.submit(JobSpec('fixture', {'value': value}))
            self.assertFalse(runtime.jobs)
            self.assertFalse(runtime.handles)
        cycle = [];cycle.append(cycle)
        with self.assertRaisesRegex(ValueError, 'cycles'):
            runtime.submit(JobSpec('fixture', {'value': cycle}))
        original = {'value': {'nested': [1, 2]}, 'unused': np.arange(3, dtype='f4')}
        handle = runtime.submit(JobSpec('fixture', original))
        original['value']['nested'].append(NativeReference())
        original['unused'][0] = 99
        self.assertEqual(handle._job.spec.inputs['value']['nested'], (1, 2))
        self.assertEqual(handle._job.spec.inputs['unused'][0], 0)
        with self.assertRaises(TypeError):handle._job.spec.inputs['value']['x'] = 1
        self.assertEqual(handle.result(timeout=6)['value']['nested'], (1, 2))

    def test_array_sealing_drops_subclass_attributes_and_backing_owners(self):
        runtime = self.runtime()
        class NativeReference:pass
        class ForeignArray(np.ndarray):pass
        node = NativeReference(); reference = weakref.ref(node)
        array = np.arange(12, dtype='f4').view(ForeignArray)
        array.native = node
        # A plain ndarray view can retain the subclass through its base chain.
        view = np.ndarray(array.shape, dtype=array.dtype, buffer=array)
        handle = runtime.submit(JobSpec('fixture', {'value': view, 'other': array}))
        del node, view, array
        self.assertIsNone(reference())
        for key in ('value', 'other'):
            value = handle._job.spec.inputs[key]
            self.assertIs(type(value), np.ndarray)
            self.assertIsNone(value.base)
            self.assertTrue(value.flags.owndata)
            self.assertFalse(value.flags.writeable)
        result = handle.result(timeout=6)['value']
        self.assertIs(type(result), np.ndarray)
        self.assertIsNone(result.base)
        self.assertFalse(result.flags.writeable)
        metadata = np.dtype('f4', metadata={'native': NativeReference()})
        with self.assertRaises(TypeError):
            runtime.submit(JobSpec('fixture', {'value': np.zeros(2, dtype=metadata)}))
        class MisreportedArray(np.ndarray):
            @property
            def dtype(self):return np.dtype('f4')
        for array in (np.array([NativeReference()],dtype=object),np.zeros(2,dtype=metadata)):
            with self.assertRaises(TypeError):
                runtime.submit(JobSpec('fixture', {'value': array.view(MisreportedArray)}))

    def test_result_cache_obeys_byte_budget_without_invalidating_consumer(self):
        runtime = self.runtime(result_bytes=16)
        values = np.arange(8, dtype='f4')
        spec = JobSpec('fixture', {'value': values}, key='large-result')
        first = runtime.submit(spec)
        actual = first.result(timeout=6)['value']
        self.assertFalse(runtime.cache)
        second = runtime.submit(spec)
        np.testing.assert_array_equal(second.result(timeout=6)['value'], values)
        np.testing.assert_array_equal(actual, values)
        self.assertEqual(len(self.receipts(runtime)), 2)

    def test_cleanup_failure_preserves_unclean_journal_for_recovery(self):
        runtime = self.runtime()
        path = runtime.session.path
        (path / 'array-orphan.npy').write_bytes(b'partial')
        with patch.object(runtime.payloads, 'close', side_effect=OSError('Injected cleanup failure')):
            report = runtime.shutdown()
        self.assertFalse(report.clean)
        self.assertFalse(json.loads((path / 'journal.json').read_text())['clean'])
        self.assertFalse(runtime.physical_terminal())
        self.assertFalse(runtime.session.lease.file.closed)
        # Failed owned-file retirement retains the lease. A retry can finish
        # physical cleanup without rewriting the historical dirty receipt.
        retried = runtime.shutdown()
        self.assertTrue(runtime.physical_terminal())
        self.assertFalse(retried.clean)
        self.assertEqual(retried.errors, report.errors)
        replacement = self.runtime()
        self.assertIn((path.name, False), replacement.session.recovered)
        self.assertFalse(path.exists())

    def test_shutdown_hung_helper_confirms_exit_before_clean_record(self):
        runtime = self.runtime()
        handle = runtime.submit(JobSpec('fixture', {'hang': True}))
        self.pump(runtime, lambda: handle.progress == .25)
        process = runtime.helpers['bulk'].process
        report = runtime.shutdown()
        self.assertTrue(report.clean, report.errors)
        self.assertIsNotNone(process.poll())
        self.assertTrue(handle.retired())
        with self.assertRaises(ExecutionError):
            runtime.submit(JobSpec('fixture', {}))
