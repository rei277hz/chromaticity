"""Shared capture jobs retain their originating helper resources."""

from concurrent.futures import CancelledError
import importlib
from importlib.resources import files
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile


class _Probe:
    def __init__(self):
        self.polls = 0

    def poll(self):
        self.polls += 1
        return True

    def result(self):
        return {"conformance": True}


class _Handle:
    def __init__(self, value):
        self.value = value
        self.timings = ()
        self.cancelled = False
        self.done = True

    def poll(self):
        return self.done or self.cancelled

    def result(self):
        if self.cancelled:
            raise CancelledError
        return self.value

    def cancel(self):
        self.cancelled = True


class _Runtime:
    def __init__(self, *args, **kwargs):
        self.terminal = False
        self.closed = False
        self.submitted = []
        self.probe = _Probe()
        self.close_error = None
        self.complete_jobs = True

    @property
    def gpu_ready(self):
        return True

    def start_probe(self):
        return self.probe

    def physical_terminal(self):
        return self.terminal

    def close(self):
        if self.close_error is not None:
            raise self.close_error
        self.closed = True
        self.terminal = True

    def submit(self, operation, inputs, *, profile=False):
        if self.closed:
            raise RuntimeError("Helper runtime has closed")
        self.submitted.append((operation, inputs, profile))
        handle = _Handle({"runtime": self, "operation": operation})
        handle.done = self.complete_jobs
        return handle


class CaptureHelperTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        directory = tempfile.TemporaryDirectory(prefix="pg-capture-helper-test-")
        cls.addClassCleanup(directory.cleanup)
        package_name = "capture_helper_test_extension"
        package = Path(directory.name) / package_name
        with zipfile.ZipFile(files("tests.perceptual_grade_blender") / "extension.zip") as archive:
            archive.extractall(package)
        sys.path.insert(0, directory.name)
        cls.addClassCleanup(sys.path.remove, directory.name)
        cls.module = importlib.import_module(package_name + ".runtime.capture_helper")

    def test_job_keeps_the_runtime_that_accepted_it(self):
        with patch.object(self.module, "HelperRuntime", _Runtime):
            backend = self.module.CaptureHelperBackend()
            first = backend.create_job({"request": 1})
            first_runtime = first.runtime
            first_runtime.terminal = True
            second = backend.create_job({"request": 2}, operation="vectorscope_capture")

            self.assertIs(first.runtime, first_runtime)
            self.assertIsNot(second.runtime, first_runtime)
            with self.assertRaisesRegex(RuntimeError, "runtime has closed"):
                first.advance()
            self.assertEqual(first_runtime.probe.polls, 1)
            self.assertEqual(second.runtime.probe.polls, 0)
            self.assertEqual(second.runtime.submitted, [])
            self.assertEqual(second.advance()["operation"], "vectorscope_capture")

    def test_cancel_before_submission_is_terminal(self):
        with patch.object(self.module, "HelperRuntime", _Runtime):
            backend = self.module.CaptureHelperBackend()
            job = backend.create_job({"request": 1})
            job.cancel()
            with self.assertRaises(CancelledError):
                job.advance()
            self.assertTrue(job.retired())

    def test_cancelled_scope_job_leaves_bake_on_shared_runtime(self):
        with patch.object(self.module, "HelperRuntime", _Runtime):
            backend = self.module.CaptureHelperBackend()
            bake = backend.create_job({"request": 1})
            scope = backend.create_job({"request": 2}, operation="vectorscope_capture")
            self.assertIs(bake.runtime, scope.runtime)
            backend.runtime.complete_jobs = False
            self.assertIsNone(bake.advance())
            self.assertIsNone(scope.advance())

            scope.cancel()
            with self.assertRaises(CancelledError):
                scope.advance()
            self.assertTrue(scope.retired())
            self.assertFalse(bake.retired())

            bake.handle.done = True
            self.assertEqual(bake.advance()["operation"], "bake")

    def test_close_retains_the_runtime_until_cleanup_succeeds(self):
        with patch.object(self.module, "HelperRuntime", _Runtime):
            backend = self.module.CaptureHelperBackend()
            backend.create_job({"request": 1})
            runtime = backend.runtime
            runtime.close_error = RuntimeError("Helper still running")
            with self.assertRaisesRegex(RuntimeError, "Helper still running"):
                backend.close()
            self.assertIs(backend.runtime, runtime)
            self.assertIs(backend.probe, runtime.probe)

            runtime.close_error = None
            backend.close()
            self.assertTrue(runtime.closed)
            self.assertIsNone(backend.runtime)
            self.assertIsNone(backend.probe)


if __name__ == "__main__":
    unittest.main()
