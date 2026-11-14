"""Bake admission, cancellation, and publication with controlled native owners."""

from concurrent.futures import CancelledError
from contextlib import contextmanager
import importlib
from importlib.resources import files
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile


class Job:
    def __init__(self, inputs):
        self.result = {"signature": inputs["signature"],
                       "generation": inputs["generation"]}
        self.cancel_calls = 0
        self.retired = False

    def advance(self):
        return self.result if self.retired else None

    def cancel(self):
        self.cancel_calls += 1


class Backend:
    def __init__(self):
        self.jobs = []
        self.close_calls = 0
        self.close_error = None
        self.on_close = lambda: None

    def create_job(self, inputs):
        job = Job(inputs)
        self.jobs.append(job)
        return job

    def close(self):
        self.close_calls += 1
        self.on_close()
        if self.close_error is not None:
            raise self.close_error
        for job in self.jobs:
            job.retired = True


class BakeManagerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix="grade-bake-manager-")
        package = Path(cls.directory.name) / "bake_manager_test"
        package.mkdir()
        with zipfile.ZipFile(files("tests.perceptual_grade_blender") / "extension.zip") as archive:
            archive.extractall(package)
        sys.path.insert(0, cls.directory.name)
        cls.module = importlib.import_module("bake_manager_test.runtime.bake_manager")

    @classmethod
    def tearDownClass(cls):
        sys.path.remove(cls.directory.name)
        for name in tuple(sys.modules):
            if name == "bake_manager_test" or name.startswith("bake_manager_test."):
                del sys.modules[name]
        cls.directory.cleanup()

    def setUp(self):
        self.backend = Backend()
        self.manager = self.module.BakeManager(object(), self.backend)
        self.signatures = {}
        self.events = []
        self.busy = False
        self.admitted = False
        self.admission_attempts = 0
        self.snapshots = tempfile.TemporaryDirectory(prefix="bake-manager-snapshots-")
        self.addCleanup(self.snapshots.cleanup)
        self.snapshot_serial = 0

        def snapshot(_route):
            self.snapshot_serial += 1
            root = Path(self.snapshots.name) / str(self.snapshot_serial)
            root.mkdir()
            path = root / "snapshot.blend"
            path.write_bytes(b"frozen scene")
            return root, path, []

        patcher = patch.object(self.manager, "_snapshot", side_effect=snapshot)
        patcher.start()
        self.addCleanup(patcher.stop)

    def node(self, number):
        self.signatures[number] = "source-" + str(number)
        return SimpleNamespace(as_pointer=lambda: number)

    def current(self, node, _route):
        return self.signatures.get(node.as_pointer())

    @contextmanager
    def admission(self):
        self.admission_attempts += 1
        if self.busy:
            raise self.module.PublicationDeferred("host is rendering")
        self.assertFalse(self.admitted)
        self.admitted = True
        try:
            yield
        finally:
            self.admitted = False

    def request(self, node, **callbacks):
        route = {"signature": self.current(node, None), "scene": "Scene", "domain": "IMAGE"}
        publish = callbacks.pop("publish_callback", lambda *_args: self.events.append("publish"))
        callbacks.setdefault("activate_callback", lambda *_args: self.events.append("activate"))
        callbacks.setdefault("rollback_callback", lambda *_args: self.events.append("rollback"))
        callbacks.setdefault("failure_callback", lambda *_args: self.events.append("failure"))
        callbacks.setdefault("publication_context", self.admission)
        self.manager.request(node, route, publish, self.current, **callbacks)
        return self.manager.jobs[node.as_pointer()]

    def complete(self, job=None, result=None):
        job = self.backend.jobs[-1] if job is None else job
        job.retired = True
        if result is not None:
            job.result = result
        return self.manager.poll()

    def test_bounds_all_accepted_requests_and_reserves_each_node(self):
        first = self.node(1)
        self.request(first)
        with self.assertRaisesRegex(RuntimeError, "already has"):
            self.request(first)
        for number in range(2, 9):
            self.request(self.node(number))
        with self.assertRaisesRegex(RuntimeError, "queue is full"):
            self.request(self.node(9))
        self.assertEqual(self.snapshot_serial, 8)
        self.manager.cancel_all()
        self.assertFalse(self.manager.jobs)

    def test_native_requests_are_serialized_until_the_previous_job_retires(self):
        self.request(self.node(1))
        self.request(self.node(2))
        self.manager.poll()
        self.manager.poll()
        self.assertEqual(len(self.backend.jobs), 1)
        self.complete()
        self.manager.poll()
        self.assertEqual(len(self.backend.jobs), 2)
        self.complete()
        self.assertEqual(self.events, ["publish", "activate", "publish", "activate"])

    def test_stale_active_keeps_artifacts_until_receipt_and_stale_queue_is_removed(self):
        first = self.node(1)
        active = self.request(first)
        second = self.node(2)
        queued = self.request(second)
        self.manager.poll()
        self.signatures[1] = "changed"
        self.assertTrue(self.manager.invalidate(first, "changed"))
        self.assertFalse(self.manager.invalidate(first, "changed"))
        self.assertEqual(self.backend.jobs[0].cancel_calls, 1)
        self.assertTrue(active["root"].is_dir())
        self.assertIs(self.manager.active, active)
        self.assertTrue(self.manager.invalidate(second, None))
        self.assertFalse(queued["root"].exists())
        self.assertNotIn(2, self.manager.jobs)
        self.complete()  # A late successful receipt cannot publish cancelled work.
        self.assertFalse(active["root"].exists())
        self.assertFalse(self.manager.jobs)
        self.assertFalse(self.events)

    def test_queued_signature_change_is_discarded_without_helper_submission(self):
        entry = self.request(self.node(1))
        self.signatures[1] = "changed"
        self.assertFalse(self.manager.poll())
        self.assertFalse(self.backend.jobs)
        self.assertFalse(entry["root"].exists())

    def test_busy_gate_retains_one_ready_artifact_and_retries_without_rebaking(self):
        entry = self.request(self.node(1))
        self.manager.poll()
        self.busy = True
        self.assertTrue(self.complete())
        self.assertEqual(entry["state"].phase, "ready")
        self.assertEqual(tuple(self.manager.publication_queue), (entry,))
        self.assertTrue(entry["root"].is_dir())
        self.assertFalse(self.events)
        self.manager.poll()
        self.assertEqual(len(self.backend.jobs), 1)
        self.assertEqual(self.admission_attempts, 2)
        self.busy = False
        self.assertFalse(self.manager.poll())
        self.assertEqual(self.events, ["publish", "activate"])
        self.assertFalse(entry["root"].exists())
        self.assertFalse(self.manager.jobs)

    def test_edit_discards_deferred_result_before_retrying_host_admission(self):
        entry = self.request(self.node(1))
        self.manager.poll()
        self.busy = True
        self.complete()
        self.signatures[1] = "changed"
        self.assertFalse(self.manager.poll())
        self.assertEqual(self.admission_attempts, 1)
        self.assertFalse(entry["root"].exists())
        self.assertFalse(self.events)

    def test_publish_activation_and_rollback_share_one_admission(self):
        def publish(*_args):
            self.assertTrue(self.admitted)
            self.events.append("publish")

        def activate(*_args):
            self.assertTrue(self.admitted)
            self.events.append("activate")
            raise RuntimeError("selector failed")

        def rollback(*_args):
            self.assertTrue(self.admitted)
            self.events.append("rollback")

        self.request(self.node(1), publish_callback=publish,
                     activate_callback=activate, rollback_callback=rollback)
        self.manager.poll()
        self.complete()
        self.assertEqual(self.events, ["publish", "activate", "rollback", "failure"])
        self.assertEqual(self.admission_attempts, 1)
        self.assertFalse(self.manager.jobs)

    def test_publish_failure_rolls_back_before_leaving_admission(self):
        def publish(*_args):
            self.assertTrue(self.admitted)
            self.events.append("publish")
            raise RuntimeError("upload failed")

        def rollback(*_args):
            self.assertTrue(self.admitted)
            self.events.append("rollback")

        self.request(self.node(1), publish_callback=publish, rollback_callback=rollback)
        self.manager.poll()
        self.complete()
        self.assertEqual(self.events, ["publish", "rollback", "failure"])

    def test_signature_change_during_activation_rolls_back(self):
        def activate(*_args):
            self.signatures[1] = "changed"
            self.events.append("activate")

        self.request(self.node(1), activate_callback=activate)
        self.manager.poll()
        self.complete()
        self.assertEqual(self.events, ["publish", "activate", "rollback", "failure"])

    def test_cancel_all_discards_ready_and_queued_and_waits_for_active_retirement(self):
        ready = self.request(self.node(1))
        self.manager.poll()
        self.busy = True
        self.complete()
        active = self.request(self.node(2))
        self.manager.poll()
        queued = self.request(self.node(3))
        self.manager.cancel_all()
        self.assertFalse(ready["root"].exists())
        self.assertFalse(queued["root"].exists())
        self.assertTrue(active["root"].exists())
        self.assertEqual(self.backend.jobs[-1].cancel_calls, 1)
        self.assertEqual(tuple(self.manager.jobs), (2,))
        self.complete(result=CancelledError("cancelled"))
        self.assertFalse(self.manager.jobs)
        self.assertFalse(self.events)

    def test_close_waits_for_backend_and_preserves_active_ownership_on_failure(self):
        active = self.request(self.node(1))
        self.manager.poll()
        queued = self.request(self.node(2))
        self.backend.on_close = lambda: self.assertTrue(active["root"].is_dir())
        self.backend.close_error = RuntimeError("helper still owns native work")
        with self.assertRaisesRegex(RuntimeError, "native work"):
            self.manager.close()
        self.assertTrue(self.manager.closed)
        self.assertFalse(self.manager.backend_closed)
        self.assertIs(self.manager.close_error, self.backend.close_error)
        self.assertIs(self.manager.active, active)
        self.assertEqual(tuple(self.manager.jobs), (1,))
        self.assertFalse(queued["root"].exists())
        with self.assertRaisesRegex(RuntimeError, "closed"):
            self.request(self.node(3))
        self.backend.close_error = None
        self.manager.close()
        self.assertTrue(self.manager.backend_closed)
        self.assertFalse(active["root"].exists())
        self.assertFalse(self.manager.jobs)
        self.assertIsNone(self.manager.active)
        self.manager.close()
        self.assertEqual(self.backend.close_calls, 2)


if __name__ == "__main__":
    unittest.main()
