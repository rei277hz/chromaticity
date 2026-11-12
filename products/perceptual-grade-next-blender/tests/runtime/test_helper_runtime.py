"""Lifecycle and join tests for the product-local GPU helper runtime."""

from concurrent.futures import CancelledError
import importlib
from importlib.resources import files
from pathlib import Path
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile


class FakeProcess:
    def __init__(self, *, ignore_terminate=False):
        self.returncode = None
        self.terminated = False
        self.killed = False
        self.ignore_terminate = ignore_terminate

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminated = True
        if not self.ignore_terminate:
            self.returncode = -15

    def kill(self):
        self.killed = True
        self.returncode = -9

    def wait(self, timeout=None):
        return self.returncode


class FakeChannel:
    def __init__(self, process, *, close_after_shutdown=False, exit_on_shutdown=True):
        self.process = process
        self.close_after_shutdown = close_after_shutdown
        self.exit_on_shutdown = exit_on_shutdown
        self.messages = []
        self.pump_calls = 0
        self.closed = False

    def send(self, message):
        self.messages.append(message)

    def pump(self):
        self.pump_calls += 1
        if (self.exit_on_shutdown
                and any(message["kind"] == "shutdown" for message in self.messages)):
            self.process.returncode = 0
            if self.close_after_shutdown:
                raise EOFError("helper closed after shutdown")
        return ()

    def close(self):
        self.closed = True


class FakeJob:
    def __init__(self, runtime, identity, state="running"):
        self.identity = identity
        self.state = state
        self.error = None
        self.value = None
        self.preview = None
        self.runtime = runtime


class FakeJoinRuntime:
    def __init__(self):
        self.cancelled = []

    def _require_handle(self, handle):
        if handle.runtime is not self:
            raise ValueError("foreign handle")

    def poll(self):
        pass

    def cancel(self, handle):
        self.cancelled.append(handle._job.identity)
        return True


class HelperRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix="grade-helper-runtime-")
        root = Path(cls.directory.name)
        package = root / "grade_helper_runtime_test"
        package.mkdir()
        archive = files("tests.perceptual_grade_blender") / "extension.zip"
        with zipfile.ZipFile(archive) as extension:
            extension.extractall(package)
        sys.path.insert(0, str(root))
        cls.module = importlib.import_module(
            "grade_helper_runtime_test.runtime.execution"
        )
        cls.worker = importlib.import_module("grade_helper_runtime_test.runtime.worker")
        cls.adapter = importlib.import_module("grade_helper_runtime_test.lut_helper")

    @classmethod
    def tearDownClass(cls):
        sys.path.remove(cls.directory.name)
        for name in tuple(sys.modules):
            if (name == "grade_helper_runtime_test"
                    or name.startswith("grade_helper_runtime_test.")):
                del sys.modules[name]
        cls.directory.cleanup()

    def runtime(self, process):
        with patch.object(self.module.subprocess, "Popen", return_value=process):
            runtime = self.module.HelperRuntime(
                package=Path(self.directory.name),
                worker_module="unused_worker",
                launcher=lambda _config: ["fake-blender"],
            )
            probe = runtime.start_probe()
        return runtime, probe

    def test_close_flushes_shutdown_and_waits_for_clean_process_exit(self):
        process = FakeProcess()
        runtime, probe = self.runtime(process)
        channel = FakeChannel(process)
        runtime._channel = channel

        runtime.close()

        self.assertFalse(process.terminated)
        self.assertTrue(runtime.physical_terminal())
        self.assertEqual(runtime.phase, "closed")
        self.assertTrue(channel.pump_calls)
        self.assertTrue(channel.closed)
        self.assertTrue(probe.done())
        with self.assertRaises(CancelledError):
            probe.result()

    def test_eof_after_shutdown_is_a_clean_helper_exit(self):
        process = FakeProcess()
        runtime, _probe = self.runtime(process)
        channel = FakeChannel(process, close_after_shutdown=True)
        runtime._channel = channel

        runtime.close()

        self.assertEqual(runtime.phase, "closed")
        self.assertFalse(process.terminated)

    def test_probe_and_shutdown_controls_carry_worker_identity(self):
        process = FakeProcess()
        runtime, probe = self.runtime(process)
        channel = FakeChannel(process)
        runtime._channel = channel
        try:
            runtime._message({"kind": "hello", "protocol": 1,
                              "session": runtime.session,
                              "generation": runtime.state.generation,
                              "token": runtime.token})
            self.assertEqual(channel.messages[0]["kind"], "run")
            runtime.close()
            self.assertEqual(channel.messages[-1]["kind"], "shutdown")
            for message in channel.messages:
                self.assertEqual(message["session"], runtime.session)
                self.assertEqual(message["generation"], runtime.state.generation)
        finally:
            runtime.close()

    def test_shutdown_timeout_escalates_through_reducer_authorized_kill(self):
        process = FakeProcess(ignore_terminate=True)
        runtime, _probe = self.runtime(process)
        runtime.SHUTDOWN_SECONDS = 0
        runtime._channel = FakeChannel(process, exit_on_shutdown=False)

        runtime.close()

        self.assertTrue(process.terminated)
        self.assertTrue(process.killed)
        self.assertTrue(runtime.physical_terminal())
        self.assertEqual(runtime.phase, "closed")

    def test_close_before_helper_connects_terminates_and_reaps_process(self):
        process = FakeProcess()
        runtime, probe = self.runtime(process)

        runtime.close()

        self.assertTrue(process.terminated)
        self.assertTrue(runtime.physical_terminal())
        self.assertEqual(runtime.phase, "closed")
        self.assertTrue(probe.done())

    def test_nonzero_exit_during_close_is_published_as_failure(self):
        process = FakeProcess()
        runtime, probe = self.runtime(process)
        process.returncode = 23

        runtime.close()

        self.assertEqual(runtime.phase, "closed")
        with self.assertRaisesRegex(self.module.HelperError, "status 23"):
            probe.result()

    def test_failed_probe_remains_pollable_after_transport_cleanup(self):
        process = FakeProcess()
        runtime, probe = self.runtime(process)
        process.returncode = 23

        self.assertTrue(probe.poll())
        self.assertEqual(runtime.phase, "failed")
        self.assertIsNone(runtime._listener)
        for _ in range(2):
            self.assertTrue(probe.poll())
            with self.assertRaisesRegex(self.module.HelperError, "status 23"):
                probe.result()
        runtime.close()

    def test_failed_stack_job_close_preserves_the_original_helper_error(self):
        process = FakeProcess()
        runtime, probe = self.runtime(process)
        channel = FakeChannel(process)
        runtime._channel = channel
        envelope = {"session": runtime.session,
                    "generation": runtime.state.generation}
        runtime._message(dict(envelope, kind="hello", protocol=1, token=runtime.token))
        value, files = runtime.payloads.encode(
            {"conformance": True, "backend": "GPU"}, prefix="probe")
        runtime._message(dict(envelope, kind="complete", job=probe._job.identity,
                              value=value, files=files))
        handle = runtime.submit("stack_lut", {})
        job = self.adapter.HelperStackJob(
            SimpleNamespace(runtime=runtime), ((), "ACEScg"), False)
        job.group = runtime.join((handle,))
        runtime._message(dict(envelope, kind="failed", job=handle._job.identity,
                              error="AttributeError: parameters"))

        with self.assertRaisesRegex(self.module.HelperError, "AttributeError: parameters"):
            job.advance()
        self.assertEqual(runtime.phase, "failed")
        self.assertTrue(handle.retired())
        self.assertTrue(job.group.retired())
        job.close()
        job.close()
        self.assertEqual(runtime.state.error, "AttributeError: parameters")
        runtime.close()

    def test_repeated_failed_exit_has_no_effects(self):
        policy = self.module.helper_policy
        state = policy.State("failed", 1, None, None, "original failure")
        updated, effects = policy.step(
            state, policy.Event("exited", generation=1, error="late exit"))
        self.assertEqual(updated, state)
        self.assertEqual(effects, policy.Effects())

    def test_scalar_effects_keep_publication_and_cleanup_order(self):
        policy = self.module.helper_policy
        effects = policy.Effects(
            clear_deadline=True,
            publish_kind="failure",
            publish_id=8,
            publish_error="original",
            probe_publish_kind="failure",
            probe_publish_id=7,
            probe_publish_error="original",
            queue_kind="fail",
            queue_error="original",
            cleanup=True,
        )

        actions = self.module._actions_for(effects)

        self.assertEqual(
            tuple((action.kind, action.job_id, action.error) for action in actions),
            (("clear_deadline", None, None),
             ("publish_failure", 8, "original"),
             ("publish_failure", 7, "original"),
             ("fail_queued", None, "original"),
             ("cleanup", None, None)),
        )

    def test_deadline_precedes_process_control(self):
        policy = self.module.helper_policy
        actions = self.module._actions_for(
            policy.Effects(deadline_stage="terminating", terminate=True))

        self.assertEqual(tuple(action.kind for action in actions),
                         ("deadline", "terminate"))

    def test_close_before_first_helper_request_retires_owned_storage(self):
        runtime = self.module.HelperRuntime(
            package=Path(self.directory.name),
            worker_module="unused_worker",
        )
        temporary_directory = runtime._temporary.name

        runtime.close()

        self.assertEqual(runtime.phase, "closed")
        self.assertFalse(Path(temporary_directory).exists())

    def ready_runtime(self, process):
        runtime, probe = self.runtime(process)
        runtime._channel = FakeChannel(process)
        envelope = {"session": runtime.session,
                    "generation": runtime.state.generation}
        runtime._message(dict(envelope, kind="hello", protocol=1, token=runtime.token))
        value, names = runtime.payloads.encode(
            {"conformance": True, "backend": "GPU"}, prefix="probe")
        runtime._message(dict(envelope, kind="complete", job=probe._job.identity,
                              value=value, files=names))
        self.assertTrue(runtime.gpu_ready)
        return runtime, envelope

    def test_cancel_startup_before_hello_never_promotes_readiness(self):
        process = FakeProcess()
        runtime, probe = self.runtime(process)
        self.assertTrue(probe.cancel())
        self.assertFalse(probe.done())
        self.assertFalse(runtime.gpu_ready)
        self.assertTrue(probe.poll())
        with self.assertRaises(CancelledError):
            probe.result()
        self.assertEqual(runtime.phase, "closed")
        runtime.close()

    def test_cancel_probe_rejects_late_success_before_physical_exit(self):
        process = FakeProcess()
        runtime, probe = self.runtime(process)
        runtime._channel = FakeChannel(process)
        envelope = {"session": runtime.session,
                    "generation": runtime.state.generation}
        runtime._message(dict(envelope, kind="hello", protocol=1, token=runtime.token))
        self.assertTrue(probe.cancel())
        value, names = runtime.payloads.encode(
            {"conformance": True, "backend": "GPU"}, prefix="late")
        runtime._message(dict(envelope, kind="complete", job=probe._job.identity,
                              value=value, files=names))
        self.assertFalse(runtime.gpu_ready)
        self.assertFalse(probe.done())
        with self.assertRaisesRegex(self.module.HelperError, "startup probe"):
            runtime.submit("stack_lut", {})
        self.assertTrue(probe.poll())
        with self.assertRaises(CancelledError):
            probe.result()
        runtime.close()

    def test_cleanup_failure_does_not_hide_retired_stack_failure(self):
        process = FakeProcess()
        runtime, envelope = self.ready_runtime(process)
        handle = runtime.submit("stack_lut", {})
        backend = self.adapter.StackHelperBackend()
        backend.runtime, backend.probe = runtime, runtime._probe
        job = self.adapter.HelperStackJob(backend, ((), "ACEScg"), False)
        job.group = runtime.join((handle,))
        runtime._message(dict(envelope, kind="failed", job=handle._job.identity,
                              error="original worker error"))
        channel = runtime._channel
        with patch.object(channel, "close", side_effect=OSError("cleanup error")) as close:
            with self.assertRaisesRegex(self.module.HelperError, "original worker error"):
                job.advance()
            self.assertEqual(runtime.phase, "retiring")
            self.assertTrue(handle.retired())
            self.assertIs(runtime._channel, channel)
            pump_calls = channel.pump_calls
            for _ in range(2):
                job.close()
                runtime.poll()
            self.assertEqual(channel.pump_calls, pump_calls)
            self.assertEqual(close.call_count, 1)
            with self.assertRaisesRegex(RuntimeError, "cleanup is incomplete"):
                backend._ensure_runtime()
            self.assertIs(backend.runtime, runtime)
            self.assertEqual(close.call_count, 2)
        replacement = SimpleNamespace(start_probe=lambda: object())
        with patch.object(self.adapter, "HelperRuntime", return_value=replacement):
            backend._ensure_runtime()
        self.assertEqual(runtime.phase, "closed")
        self.assertTrue(channel.closed)
        self.assertIs(backend.runtime, replacement)
        self.assertEqual(runtime.state.error, "original worker error")
        with self.assertRaisesRegex(self.module.HelperError, "original worker error"):
            handle.result()

    def test_failed_payload_reclamation_retains_files_after_job_completion(self):
        process = FakeProcess()
        runtime, envelope = self.ready_runtime(process)
        # An explicitly supplied directory makes retained sidecars observable
        # independently of TemporaryDirectory's recursive cleanup.
        runtime._temporary.cleanup()
        runtime._temporary = None
        runtime.directory.mkdir()
        handle = runtime.submit("stack_lut", {})
        path = runtime.directory / "array-retained.npy"
        path.write_bytes(b"owned payload")
        handle._job.input_files = (path.name,)
        runtime.payloads.owned.add(path)
        runtime._message(dict(envelope, kind="failed", job=handle._job.identity,
                              error="original worker error"))
        with patch.object(runtime.payloads, "release", side_effect=OSError("unlink")):
            self.assertTrue(handle.poll())
            self.assertEqual(runtime.phase, "retiring")
            self.assertIn(path, runtime.payloads.owned)
            self.assertTrue(path.exists())
            with self.assertRaisesRegex(self.module.HelperError, "original worker error"):
                handle.result()
        runtime.close()
        self.assertFalse(path.exists())
        self.assertEqual(runtime.payloads.owned, set())
        runtime.directory.rmdir()

    def test_cleanup_retry_does_not_close_already_released_resources(self):
        process = FakeProcess()
        runtime, probe = self.runtime(process)
        channel = FakeChannel(process)
        runtime._channel = channel
        process.returncode = 23
        with patch.object(channel, "close", side_effect=OSError("channel close")) as close:
            with self.assertRaisesRegex(RuntimeError, "cleanup is incomplete"):
                runtime.close()
            self.assertEqual(close.call_count, 1)
            self.assertIs(runtime._channel, channel)
            self.assertIsNone(runtime._listener)
            self.assertIsNone(runtime._log)
            self.assertTrue(probe.done())
        runtime.close()
        self.assertEqual(runtime.phase, "closed")
        with self.assertRaisesRegex(self.module.HelperError, "status 23"):
            probe.result()

    def test_final_kill_timeout_retains_process_for_later_retirement(self):
        class UnretiredProcess(FakeProcess):
            def kill(self):
                self.killed = True
        process = UnretiredProcess(ignore_terminate=True)
        runtime, probe = self.runtime(process)
        runtime._channel = FakeChannel(process, exit_on_shutdown=False)
        ticks = iter(range(100))
        with patch.object(self.module.time, "monotonic", side_effect=lambda: next(ticks)), \
                patch.object(self.module.time, "sleep"):
            with self.assertRaisesRegex(RuntimeError, "did not physically retire"):
                runtime.close()
        self.assertIs(runtime._process, process)
        self.assertEqual(runtime.phase, "unretired")
        self.assertFalse(probe.done())
        self.assertFalse(runtime._channel.closed)
        process.returncode = 0
        runtime.close()
        self.assertEqual(runtime.phase, "closed")
        self.assertTrue(probe.done())

    def test_partial_launch_failure_releases_owned_resources_through_policy(self):
        with patch.object(self.module.subprocess, "Popen", side_effect=OSError("launch failed")):
            runtime = self.module.HelperRuntime(
                package=Path(self.directory.name), worker_module="unused_worker",
                launcher=lambda _config: ["fake-blender"],
            )
            directory = runtime.directory
            probe = runtime.start_probe()
        self.assertTrue(probe.done())
        self.assertEqual(runtime.phase, "failed")
        self.assertIsNone(runtime._listener)
        self.assertIsNone(runtime._log)
        self.assertFalse(directory.exists())
        with self.assertRaisesRegex(self.module.HelperError, "launch failed"):
            probe.result()
        runtime.close()

    def test_preparation_owner_survives_failed_close_until_retry(self):
        preparation = importlib.import_module("grade_helper_runtime_test.runtime.preparation")
        class Owner:
            remaining_failures = 2
            def create_job(self, _payload, _progressive):
                raise AssertionError("no work expected")
            def close(self):
                if self.remaining_failures:
                    self.remaining_failures -= 1
                    raise RuntimeError("owner retained")
        owner = Owner()
        runtime = preparation.PreparationRuntime(lambda value: value)
        runtime.register_polled_lane("host", owner)
        try:
            for _ in range(2):
                with self.assertRaises(ExceptionGroup):
                    runtime.close()
                self.assertIs(runtime._lanes["host"].host_owner, owner)
            runtime.close()
            self.assertIsNone(runtime._lanes["host"].host_owner)
        finally:
            owner.remaining_failures = 0
            runtime.close()

    def test_join_preserves_result_order_and_waits_for_every_child(self):
        runtime = FakeJoinRuntime()
        first = self.module.JobHandle(runtime, FakeJob(runtime, 1, "finished"))
        second = self.module.JobHandle(runtime, FakeJob(runtime, 2, "running"))
        first._job.value = "first"
        group = self.module.JobGroup(runtime, (first, second))

        self.assertFalse(group.poll())
        second._job.state = "finished"
        second._job.value = "second"
        self.assertTrue(group.poll())
        self.assertEqual(group.result(), ("first", "second"))

    def test_join_failure_cancels_siblings_but_waits_for_retirement(self):
        runtime = FakeJoinRuntime()
        first = self.module.JobHandle(runtime, FakeJob(runtime, 1, "finished"))
        second = self.module.JobHandle(runtime, FakeJob(runtime, 2, "running"))
        first._job.error = RuntimeError("child failed")
        group = self.module.JobGroup(runtime, (first, second))

        self.assertFalse(group.poll())
        self.assertEqual(runtime.cancelled, [2])
        second._job.state = "finished"
        self.assertTrue(group.poll())
        with self.assertRaisesRegex(RuntimeError, "child failed"):
            group.result()

    def test_worker_preview_uses_the_run_protocol_job_field(self):
        class Payloads:
            def __init__(self):
                self.prefix = None
                self.transferred = None

            def encode(self, _value, *, prefix):
                self.prefix = prefix
                return {"encoded": True}, ("array-preview.npy",)

            def release(self, files):
                self.transferred = ("released", files)

            def transfer(self, files):
                self.transferred = ("transferred", files)

        sent = []
        payloads = Payloads()
        context = self.worker.WorkerContext(
            {"role": "gpu", "generation": 4, "session": "session"},
            {"kind": "run", "job": 23},
            threading.Event(),
            sent.append,
            payloads,
        )

        context.preview({"quality": "preview"})

        self.assertEqual(payloads.prefix, "gpu-4-23")
        self.assertEqual(sent, [{
            "kind": "preview", "job": 23,
            "value": {"encoded": True}, "files": ("array-preview.npy",),
        }])
        self.assertEqual(payloads.transferred,
                         ("transferred", ("array-preview.npy",)))


if __name__ == "__main__":
    unittest.main()
