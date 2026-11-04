"""Real helper joins and GPU-only admission without the legacy actor runtime."""
from concurrent.futures import CancelledError, InvalidStateError
from dataclasses import replace
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

import color_tools.blender_runtime.execution as execution
from color_tools.blender_runtime.execution.contracts import (
    ExecutionError, JobSpec, RuntimeLimits, RuntimeProfile,
)
from color_tools.blender_runtime.execution.machines import create_execution_machines
from color_tools.blender_runtime.execution.owner import ExecutionOwner, ForeignOwnerError
from color_tools.blender_runtime.execution.runtime import ExecutionRuntime


FIXTURE = Path(__file__).with_name('helper_fixture.py')


class ExecutionJoinTests(unittest.TestCase):
    def setUp(self):
        self.directory = self.enterContext(tempfile.TemporaryDirectory())
        self.runtimes = []
        self.addCleanup(self.close)

    def close(self):
        for runtime in self.runtimes:
            runtime.shutdown()
            runtime.app.close()

    def runtime(self, mode='normal'):
        owner = ExecutionOwner()
        runtime = ExecutionRuntime(
            self.directory, app=owner, machines=create_execution_machines(),
            package=Path(execution.__file__).parent.parent.parent,
            profile=RuntimeProfile(lanes=('linear', 'bulk', 'gpu')),
            limits=replace(RuntimeLimits(), startup_seconds=3., stalled_seconds=3.,
                           shutdown_seconds=.1),
            environment=dict(os.environ, PYTHONPATH=os.pathsep.join(sys.path)),
            launcher=lambda config: [sys.executable, str(FIXTURE), config['config_path'], mode],
        )
        self.runtimes.append(runtime)
        return runtime

    def pump(self, runtime, condition, timeout=6):
        deadline = time.monotonic() + timeout
        while not condition() and time.monotonic() < deadline:
            runtime.poll()
            time.sleep(.002)
        self.assertTrue(condition(), 'Execution did not reach the required state')

    def receipts(self, runtime, lane):
        path = runtime.session.path / ('fixture-' + lane + '.jsonl')
        return [] if not path.exists() else [json.loads(line) for line in path.read_text().splitlines()]

    def test_join_preserves_input_order_with_out_of_order_completion(self):
        runtime = self.runtime()
        gate = Path(self.directory) / 'first-ready'
        first = runtime.submit(JobSpec('fixture', {'value': 'first', 'gate': str(gate)}))
        second = runtime.submit(JobSpec('fixture', {'value': 'second'}, lane='linear'))
        group = runtime.join((first, second))
        self.pump(runtime, lambda: second._job.finished and first.progress == .25)
        with patch.object(runtime, 'wait_exact', side_effect=AssertionError('Join blocked')):
            self.assertFalse(group.poll())
            self.assertFalse(group.done())
            with self.assertRaises(InvalidStateError):
                group.result()
            gate.touch()
            self.pump(runtime, group.poll)
            self.assertEqual(tuple(value['value'] for value in group.result()), ('first', 'second'))
        self.assertTrue(group.retired())
        self.assertIsNone(group.exception())
        self.assertFalse(group.cancel())

    def test_join_preview_waits_for_all_children_and_keeps_input_order(self):
        runtime = self.runtime()
        first_gate = Path(self.directory) / 'first'
        second_gate = Path(self.directory) / 'second'
        first = runtime.submit(JobSpec('fixture', {'gate': str(first_gate), 'stream': 1}))
        second = runtime.submit(JobSpec('fixture', {'gate': str(second_gate)}, lane='linear'))
        group = runtime.join((first, second))
        self.pump(runtime, lambda: first.preview is not None and second.progress == .25)
        self.assertIsNone(group.preview)
        first_gate.touch()
        second_gate.touch()
        self.pump(runtime, group.poll)
        self.assertIsNone(group.preview)

        a_gate = Path(self.directory) / 'a'
        b_gate = Path(self.directory) / 'b'
        a = runtime.submit(JobSpec('fixture', {'gate': str(a_gate), 'stream': 3}))
        b = runtime.submit(JobSpec('fixture', {'gate': str(b_gate), 'stream': 7}, lane='linear'))
        previews = runtime.join((b, a))
        self.pump(runtime, lambda: a.preview is not None and b.preview is not None)
        self.assertEqual(previews.preview, ({'preview': 7}, {'preview': 3}))
        self.assertFalse(previews.done())
        a_gate.touch()
        b_gate.touch()
        self.pump(runtime, previews.poll)

    def test_failure_cancels_peers_but_reports_only_after_physical_retirement(self):
        runtime = self.runtime()
        gate = Path(self.directory) / 'retire'
        peer = runtime.submit(JobSpec('fixture', {'gate': str(gate), 'stream': 1}))
        self.pump(runtime, lambda: peer.progress == .01)
        failed = runtime.submit(JobSpec('fixture', {'fail': True}, lane='linear'))
        group = runtime.join((peer, failed))
        self.pump(runtime, lambda: (group.poll() or peer.cancelled()))
        self.assertTrue(peer.cancelled())
        self.assertFalse(group.retired())
        self.assertIsNone(group.preview)
        with self.assertRaises(InvalidStateError):
            group.exception()
        with self.assertRaises(InvalidStateError):
            group.result()
        gate.touch()
        self.pump(runtime, group.poll)
        with self.assertRaisesRegex(ExecutionError, 'Fixture computation failure'):
            group.result()

    def test_group_cancellation_preserves_an_unrelated_shared_consumer(self):
        runtime = self.runtime()
        gate = Path(self.directory) / 'shared'
        spec = JobSpec('fixture', {'gate': str(gate), 'value': 'shared'}, key='shared')
        child, unrelated = runtime.submit(spec), runtime.submit(spec)
        group = runtime.join((child,))
        self.pump(runtime, lambda: child.progress == .25)
        self.assertTrue(group.cancel())
        self.assertFalse(group.cancel())
        self.assertFalse(unrelated.cancelled())
        self.assertFalse(group.done())
        gate.touch()
        self.pump(runtime, group.poll)
        with self.assertRaises(CancelledError):
            group.result()
        self.assertEqual(unrelated.result()['value'], 'shared')
        self.assertEqual(len(self.receipts(runtime, 'bulk')), 1)

    def test_join_validates_runtime_ownership_and_empty_join_is_complete(self):
        first, second = self.runtime(), self.runtime()
        handle = first.submit(JobSpec('fixture', {'value': 1}))
        with self.assertRaises(ForeignOwnerError):
            second.join((handle,))
        empty = first.join(())
        self.assertTrue(empty.done())
        self.assertEqual(empty.result(), ())
        self.assertEqual(empty.preview, ())
        handle.result(timeout=6)

    def test_plain_execution_owner_does_not_import_actor_runtime(self):
        self.assertFalse(any(
            name.startswith('color_tools.blender_runtime.invariant')
            or name == 'color_tools.blender_runtime.app'
            for name in sys.modules
        ))
        owner = ExecutionOwner()
        owner.close()

    def test_gpu_required_jobs_need_a_validated_gpu_lane(self):
        runtime = self.runtime()
        with self.assertRaisesRegex(ValueError, 'GPU lane'):
            runtime.submit(JobSpec('fixture', {}, requires_gpu=True))
        with self.assertRaisesRegex(ExecutionError, 'current GPU probe'):
            runtime.submit(JobSpec('fixture', {}, lane='gpu', requires_gpu=True))
        runtime.retry_gpu().result(timeout=6)
        required = runtime.submit(JobSpec('fixture', {'value': 'GPU'}, lane='gpu', requires_gpu=True))
        self.assertEqual(required.result(timeout=6)['role'], 'gpu')
        self.assertFalse(self.receipts(runtime, 'bulk'))

    def test_gpu_required_failure_never_falls_back_and_does_not_reuse_cpu_cache(self):
        runtime = self.runtime()
        runtime.retry_gpu().result(timeout=6)
        failed = runtime.submit(JobSpec('fixture', {'fail_gpu': True}, lane='gpu', requires_gpu=True))
        with self.assertLogs('color_tools.blender_runtime.execution.runtime', level='WARNING'):
            with self.assertRaisesRegex(ExecutionError, 'Fixture computation failure'):
                failed.result(timeout=6)
        self.assertEqual(failed.backend, 'gpu')
        self.assertFalse(self.receipts(runtime, 'bulk'))
        with self.assertRaisesRegex(ExecutionError, 'current GPU probe'):
            runtime.submit(JobSpec('fixture', {}, lane='gpu', requires_gpu=True))
        ordinary = runtime.submit(JobSpec('fixture', {'value': 'ordinary'}, lane='gpu', key='same'))
        self.assertEqual(ordinary.result(timeout=6)['role'], 'bulk')
        runtime.retry_gpu().result(timeout=6)
        required = runtime.submit(JobSpec('fixture', {'value': 'required'}, lane='gpu',
                                          key='same', requires_gpu=True))
        self.assertEqual(required.result(timeout=6)['role'], 'gpu')
        self.assertIsNot(required._job, ordinary._job)


if __name__ == '__main__':
    unittest.main()
