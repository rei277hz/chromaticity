"""Foreground Stack helper adapter polls without waiting for GPU work."""

import importlib
from importlib.resources import files
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile
from concurrent.futures import CancelledError
from unittest.mock import patch


class Probe:
    def __init__(self, ready=False):
        self.ready = ready
        self.result_calls = 0

    def poll(self):
        return self.ready

    def result(self):
        if not self.ready:
            raise AssertionError("probe result must not be awaited")
        self.result_calls += 1
        return ({"conformance": True},)


class Handle:
    def __init__(self, preview=None, result=None, ready=False):
        self.preview = preview
        self._result = result
        self.ready = ready
        self.poll_calls = 0
        self.result_calls = 0
        self.cancel_calls = 0

    def poll(self):
        self.poll_calls += 1
        return self.ready

    def result(self):
        if not self.ready:
            raise AssertionError("handle result must not block while pending")
        self.result_calls += 1
        if self.cancel_calls:
            raise CancelledError("helper work cancelled")
        return self._result

    def cancel(self):
        self.cancel_calls += 1


class Runtime:
    def __init__(self, handle):
        self.handle = handle
        self.submissions = []

    def submit(self, operation, inputs):
        self.submissions.append((operation, inputs))
        return self.handle


class LUTHelperTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix="grade-helper-adapter-")
        root = Path(cls.directory.name)
        package = root / "grade_helper_test"
        package.mkdir()
        archive = files("tests.perceptual_grade_blender") / "extension.zip"
        with zipfile.ZipFile(archive) as extension:
            extension.extractall(package)
        sys.path.insert(0, str(root))
        cls.module = importlib.import_module("grade_helper_test.lut_helper")
        settings_module = importlib.import_module("grade_helper_test.kernel.settings")
        cls.settings = settings_module.Settings
        cls.stack_entry_settings = settings_module.StackEntrySettings
        cls.linear_settings = settings_module.LinearSettings

    @classmethod
    def tearDownClass(cls):
        sys.path.remove(cls.directory.name)
        for name in tuple(sys.modules):
            if name == "grade_helper_test" or name.startswith("grade_helper_test."):
                del sys.modules[name]
        cls.directory.cleanup()

    def backend(self, handle, probe_ready):
        backend = self.module.StackHelperBackend()
        backend.runtime = Runtime(handle)
        backend.probe = Probe(probe_ready)
        return backend

    def test_progressive_submission_waits_for_probe_and_polls_until_preview_then_full(self):
        handle = Handle(result={"quality": "full"})
        backend = self.backend(handle, probe_ready=False)
        job = self.module.HelperStackJob(
            backend, ((self.settings(linear=self.linear_settings(exposure=.25)),), "ACEScg"), True,
        )
        with patch.object(self.module, "thaw_prepared", side_effect=lambda item: item):
            self.assertIsNone(job.advance())
            self.assertFalse(backend.runtime.submissions)
            backend.probe.ready = True
            self.assertIsNone(job.advance())
            self.assertEqual(len(backend.runtime.submissions), 1)
            operation, inputs = backend.runtime.submissions[0]
            self.assertEqual(operation, "stack_lut")
            self.assertEqual(inputs["working_space"], "ACEScg")
            self.assertEqual(handle.result_calls, 0)
            handle.preview = {"quality": "preview"}
            self.assertEqual(job.advance(), ("preview", {"quality": "preview"}))
            self.assertEqual(handle.result_calls, 0)
            handle.preview = None
            handle.ready = True
            self.assertEqual(job.advance(), ("full", {"quality": "full"}))
        self.assertEqual(handle.poll_calls, 3)
        self.assertEqual(handle.result_calls, 1)

    def test_direct_request_does_not_publish_preview(self):
        handle = Handle(preview={"quality": "preview"},
                        result={"quality": "full"}, ready=True)
        backend = self.backend(handle, probe_ready=True)
        job = self.module.HelperStackJob(
            backend, ((self.settings(),), "ACEScg"), False,
        )
        with patch.object(self.module, "thaw_prepared", side_effect=lambda item: item):
            self.assertEqual(job.advance(), ("full", {"quality": "full"}))
        self.assertFalse(job.preview_emitted)
        self.assertFalse(backend.runtime.submissions[0][1]["progressive"])

    def test_entry_directions_cross_the_helper_boundary_in_order(self):
        handle = Handle(result={"quality": "full"}, ready=True)
        backend = self.backend(handle, probe_ready=True)
        job = self.module.HelperStackJob(
            backend,
            ((
                self.stack_entry_settings(self.settings(), "INVERSE"),
                self.stack_entry_settings(self.settings(), "FORWARD"),
            ), "ACEScg"),
            False,
        )
        with patch.object(self.module, "thaw_prepared", side_effect=lambda item: item):
            self.assertEqual(job.advance(), ("full", {"quality": "full"}))
        self.assertEqual(backend.runtime.submissions[0][1]["directions"],
                         ("INVERSE", "FORWARD"))

    def test_superseding_preview_requests_cancellation_and_waits_for_retirement(self):
        handle = Handle(preview={"quality": "preview"},
                        result={"quality": "full"}, ready=False)
        backend = self.backend(handle, probe_ready=True)
        job = self.module.HelperStackJob(
            backend, ((self.settings(),), "ACEScg"), True,
        )
        with patch.object(self.module, "thaw_prepared", side_effect=lambda item: item):
            self.assertEqual(job.advance(), ("preview", {"quality": "preview"}))
            job.cancel()
            job.cancel()
            self.assertEqual(handle.cancel_calls, 1)
            self.assertIsNone(job.advance())
            with self.assertRaises(RuntimeError):
                job.close()
            handle.ready = True
            with self.assertRaises(CancelledError):
                job.advance()
        job.close()

if __name__ == "__main__":
    unittest.main()
