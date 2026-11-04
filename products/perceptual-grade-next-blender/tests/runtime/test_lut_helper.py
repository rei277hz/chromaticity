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


class Group:
    def __init__(self, preview=None, result=None, ready=False):
        self._preview = preview
        self._result = result
        self.ready = ready
        self.poll_calls = 0
        self.result_calls = 0
        self.cancel_calls = 0

    @property
    def preview(self):
        return None if self.cancel_calls else self._preview

    def poll(self):
        self.poll_calls += 1
        return self.ready

    def result(self):
        if not self.ready:
            raise AssertionError("group result must not block while pending")
        self.result_calls += 1
        if self.cancel_calls:
            raise CancelledError("joined work cancelled")
        return self._result

    def cancel(self):
        self.cancel_calls += 1

    def retired(self):
        return self.ready


class Runtime:
    def __init__(self, group):
        self.group = group
        self.submissions = []
        self.joined = []

    def submit(self, operation, inputs):
        self.submissions.append((operation, inputs))
        return object()

    def join(self, handles):
        self.joined.append(tuple(handles))
        return self.group


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
        cls.linear_settings = settings_module.LinearSettings

    @classmethod
    def tearDownClass(cls):
        sys.path.remove(cls.directory.name)
        for name in tuple(sys.modules):
            if name == "grade_helper_test" or name.startswith("grade_helper_test."):
                del sys.modules[name]
        cls.directory.cleanup()

    def backend(self, group, probe_ready):
        backend = self.module.StackHelperBackend()
        backend.runtime = Runtime(group)
        backend.probe = Probe(probe_ready)
        return backend

    def test_progressive_submission_waits_for_probe_and_polls_until_preview_then_full(self):
        group = Group(result=({"quality": "full"},))
        backend = self.backend(group, probe_ready=False)
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
            self.assertEqual(len(backend.runtime.joined), 1)
            self.assertEqual(len(backend.runtime.joined[0]), 1)
            self.assertEqual(group.result_calls, 0)
            group._preview = ({"quality": "preview"},)
            self.assertEqual(job.advance(), ("preview", {"quality": "preview"}))
            self.assertEqual(group.result_calls, 0)
            group._preview = None
            group.ready = True
            self.assertEqual(job.advance(), ("full", {"quality": "full"}))
        self.assertEqual(group.poll_calls, 3)
        self.assertEqual(group.result_calls, 1)

    def test_direct_request_does_not_publish_preview(self):
        group = Group(preview=({"quality": "preview"},),
                      result=({"quality": "full"},), ready=True)
        backend = self.backend(group, probe_ready=True)
        job = self.module.HelperStackJob(
            backend, ((self.settings(),), "ACEScg"), False,
        )
        with patch.object(self.module, "thaw_prepared", side_effect=lambda item: item):
            self.assertEqual(job.advance(), ("full", {"quality": "full"}))
        self.assertFalse(job.preview_emitted)
        self.assertFalse(backend.runtime.submissions[0][1]["progressive"])

    def test_superseding_preview_requests_cancellation_and_waits_for_retirement(self):
        group = Group(preview=({"quality": "preview"},),
                      result=({"quality": "full"},), ready=False)
        backend = self.backend(group, probe_ready=True)
        job = self.module.HelperStackJob(
            backend, ((self.settings(),), "ACEScg"), True,
        )
        with patch.object(self.module, "thaw_prepared", side_effect=lambda item: item):
            self.assertEqual(job.advance(), ("preview", {"quality": "preview"}))
            job.cancel()
            self.assertEqual(group.cancel_calls, 1)
            self.assertIsNone(job.advance())
            with self.assertRaises(RuntimeError):
                job.close()
            group.ready = True
            with self.assertRaises(CancelledError):
                job.advance()
        job.close()


if __name__ == "__main__":
    unittest.main()
