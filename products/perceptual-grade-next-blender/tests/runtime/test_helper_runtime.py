"""Lifecycle and join tests for the product-local GPU helper runtime."""

from concurrent.futures import CancelledError
import importlib
from importlib.resources import files
from pathlib import Path
import sys
import tempfile
import threading
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

    def test_close_before_first_helper_request_retires_owned_storage(self):
        runtime = self.module.HelperRuntime(
            package=Path(self.directory.name),
            worker_module="unused_worker",
        )
        temporary_directory = runtime._temporary.name

        runtime.close()

        self.assertEqual(runtime.phase, "closed")
        self.assertFalse(Path(temporary_directory).exists())

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
