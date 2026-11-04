"""Host admission for image publication, isolated from Blender imports."""

import importlib
from importlib.resources import files
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from types import SimpleNamespace
import zipfile


class PublicationGateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix="grade-publication-")
        root = Path(cls.directory.name)
        package = root / "grade_publication_test"
        package.mkdir()
        resource = files("tests.perceptual_grade_blender") / "extension.zip"
        with zipfile.ZipFile(resource) as archive:
            archive.extractall(package)
        sys.path.insert(0, str(root))
        cls.module = importlib.import_module("grade_publication_test.runtime.publication")

    @classmethod
    def tearDownClass(cls):
        sys.path.remove(cls.directory.name)
        for name in tuple(sys.modules):
            if name == "grade_publication_test" or name.startswith("grade_publication_test."):
                del sys.modules[name]
        cls.directory.cleanup()

    def host(self, *, jobs=(), locked=False, modal=()):
        operators = [SimpleNamespace(bl_idname=name) for name in modal]
        window = SimpleNamespace(modal_operators=operators)
        manager = SimpleNamespace(is_interface_locked=locked, windows=[window])
        running = set(jobs)
        bpy = SimpleNamespace(
            data=SimpleNamespace(window_managers=[manager]),
            app=SimpleNamespace(is_job_running=lambda name: name in running),
        )
        return bpy, running, manager

    def gate(self, **kwargs):
        bpy, running, manager = self.host(**kwargs)
        return self.module.PublicationGate(bpy), running, manager

    def test_admits_one_nonreentrant_main_thread_commit(self):
        gate, _running, _manager = self.gate()
        self.assertFalse(gate.blocked())
        with gate.commit():
            self.assertTrue(gate.blocked())
            with self.assertRaisesRegex(self.module.PublicationDeferred, "already active"):
                with gate.commit():
                    self.fail("nested publication was admitted")
        self.assertFalse(gate.blocked())

    def test_defers_for_jobs_interface_lock_and_modal_bake_readers(self):
        for job in self.module.JOBS:
            with self.subTest(job=job):
                gate, _running, _manager = self.gate(jobs=(job,))
                self.assertIn(job, gate.reason())

        gate, _running, _manager = self.gate(locked=True)
        self.assertIn("interface is locked", gate.reason())

        for operator in self.module.MODAL_READERS:
            with self.subTest(operator=operator):
                gate, _running, _manager = self.gate(modal=(operator,))
                self.assertIn("bake operation", gate.reason())

    def test_callback_and_paired_evaluation_fence_image_writes(self):
        gate, _running, _manager = self.gate()
        gate.evaluation_started("render", 17)
        gate.evaluation_started("render", 17)
        gate.evaluation_finished("render", 17)
        self.assertIn("evaluation is active", gate.reason())
        with gate.callback():
            gate.evaluation_finished("render", 17)
            self.assertIn("native callback", gate.reason())
            with self.assertRaises(self.module.PublicationDeferred):
                with gate.commit():
                    self.fail("publication from a native callback was admitted")
        self.assertFalse(gate.blocked())

    def test_unmatched_finish_does_not_release_another_evaluation(self):
        gate, _running, _manager = self.gate()
        gate.evaluation_started("compositor", 11)
        gate.evaluation_finished("compositor", 12)
        self.assertTrue(gate.blocked())
        gate.evaluation_finished("compositor", 11)
        self.assertFalse(gate.blocked())

    def test_commit_rechecks_jobs_after_initial_admission(self):
        observations = iter((False, True, False))
        bpy, _running, _manager = self.host()
        bpy.app.is_job_running = lambda name: next(observations, True) if name == "RENDER" else False
        gate = self.module.PublicationGate(bpy)
        with self.assertRaisesRegex(self.module.PublicationDeferred, "RENDER"):
            with gate.commit():
                self.fail("newly active render was not noticed")
        self.assertFalse(gate.blocked())

    def test_worker_thread_is_rejected_before_blender_is_inspected(self):
        class Unreadable:
            @property
            def data(self):
                raise AssertionError("worker thread inspected Blender data")

            @property
            def app(self):
                raise AssertionError("worker thread inspected Blender jobs")

        gate = self.module.PublicationGate(Unreadable())
        reasons = []
        worker = threading.Thread(target=lambda: reasons.append(gate.reason()))
        worker.start()
        worker.join(5)
        self.assertFalse(worker.is_alive())
        self.assertEqual(len(reasons), 1)
        self.assertIn("main thread", reasons[0])

    def test_worker_render_waits_for_exact_main_thread_preflight(self):
        gate, running, _manager = self.gate(jobs=("RENDER",))
        gate.evaluation_started("render", 17)
        tickets = []
        submitted = threading.Event()
        results = []

        def callback():
            ticket = gate.request_render_preflight(17)
            tickets.append(ticket)
            submitted.set()
            self._wait(ticket, results)

        worker = threading.Thread(target=callback)
        worker.start()
        self.assertTrue(submitted.wait(5))
        ticket, = tickets

        self.assertFalse(ticket._finished.is_set())
        self.assertIs(gate.take_render_preflight(), ticket)
        with gate.render_preflight(ticket):
            self.assertTrue(gate._committing)
            self.assertFalse(ticket._finished.is_set())
        worker.join(5)

        self.assertFalse(worker.is_alive())
        self.assertEqual(results, [None])
        self.assertTrue(ticket._finished.is_set())
        self.assertFalse(gate._committing)
        gate.evaluation_finished("render", 17)
        running.clear()

    @staticmethod
    def _wait(ticket, results):
        try:
            ticket.wait()
        except BaseException as error:
            results.append(error)
        else:
            results.append(None)

    def test_wrong_ticket_cannot_complete_or_release_active_ticket(self):
        gate, running, _manager = self.gate(jobs=("RENDER",))
        gate.evaluation_started("render", 17)
        first = gate.request_render_preflight(17)
        second = gate.request_render_preflight(17)
        self.assertIs(gate.take_render_preflight(), first)

        with self.assertRaisesRegex(self.module.PublicationDeferred, "not active"):
            with gate.render_preflight(second):
                self.fail("a queued ticket was treated as the active ticket")

        self.assertFalse(first._finished.is_set())
        self.assertFalse(second._finished.is_set())
        self.assertIsNone(gate.take_render_preflight())
        with gate.render_preflight(first):
            pass
        self.assertTrue(first._finished.is_set())
        self.assertIs(gate.take_render_preflight(), second)
        with gate.render_preflight(second):
            pass
        self.assertTrue(second._finished.is_set())
        gate.evaluation_finished("render", 17)
        running.clear()

    def test_preflight_rejects_another_render_job_or_identity(self):
        gate, running, _manager = self.gate(jobs=("RENDER", "RENDER_PREVIEW"))
        gate.evaluation_started("render", 17)
        ticket = gate.request_render_preflight(17)
        self.assertIs(gate.take_render_preflight(), ticket)
        with self.assertRaisesRegex(self.module.PublicationDeferred, "one expected"):
            with gate.render_preflight(ticket):
                self.fail("two active render jobs were treated as one expected job")
        self.assertTrue(ticket._finished.is_set())
        self.assertIn("one expected", str(ticket._error))
        gate.evaluation_finished("render", 17)
        running.clear()

        gate, running, _manager = self.gate(jobs=("RENDER",))
        gate.evaluation_started("render", 17)
        with self.assertRaises(self.module.PublicationDeferred):
            gate.request_render_preflight(99)
        self.assertFalse(gate.has_render_preflight)
        gate.evaluation_finished("render", 17)
        running.clear()

    def test_preflight_failure_wakes_worker_and_lifecycle_reset_cancels_waiter(self):
        gate, running, manager = self.gate(jobs=("RENDER",))
        gate.evaluation_started("render", 17)
        ticket = gate.request_render_preflight(17)
        results = []
        worker = threading.Thread(target=lambda: self._wait(ticket, results))
        worker.start()
        self.assertIs(gate.take_render_preflight(), ticket)
        manager.windows[0].modal_operators.append(
            SimpleNamespace(bl_idname="OBJECT_OT_bake_image"))
        with self.assertRaisesRegex(self.module.PublicationDeferred, "bake operation"):
            with gate.render_preflight(ticket):
                self.fail("preflight ignored an image bake reader")
        worker.join(5)
        self.assertFalse(worker.is_alive())
        self.assertEqual(len(results), 1)
        self.assertIsInstance(results[0], self.module.PublicationDeferred)

        manager.windows[0].modal_operators.clear()
        ticket = gate.request_render_preflight(17)
        results.clear()
        worker = threading.Thread(target=lambda: self._wait(ticket, results))
        worker.start()
        manager.is_interface_locked = True
        with self.assertRaisesRegex(self.module.PublicationDeferred, "interface is locked"):
            gate.reset()
        self.assertFalse(ticket._finished.is_set())
        running.clear()
        manager.is_interface_locked = False
        gate.reset()
        worker.join(5)
        self.assertFalse(worker.is_alive())
        self.assertEqual(len(results), 1)
        self.assertIsInstance(results[0], self.module.PublicationDeferred)
        self.assertFalse(gate.has_render_preflight)

    def test_direct_main_thread_render_uses_scope_without_waiting(self):
        gate, _running, _manager = self.gate()
        gate.evaluation_started("render", 17)
        ticket = gate.request_render_preflight(17)
        self.assertIs(gate.take_render_preflight(), ticket)
        with gate.render_preflight(ticket):
            pass
        self.assertTrue(ticket._finished.is_set())
        self.assertIsNone(ticket._error)
        with self.assertRaisesRegex(RuntimeError, "main thread cannot wait"):
            ticket.wait()
        gate.evaluation_finished("render", 17)

    def test_deferred_worker_preflight_keeps_waiter_blocked_until_reader_retires(self):
        gate, running, _manager = self.gate(jobs=("RENDER", "SHADER_COMPILATION"))
        gate.evaluation_started("render", 17)
        ticket = gate.request_render_preflight(17)
        results = []
        worker = threading.Thread(target=lambda: self._wait(ticket, results))
        worker.start()
        self.assertIs(gate.take_render_preflight(), ticket)
        with self.assertRaisesRegex(self.module.PublicationDeferred, "SHADER_COMPILATION"):
            with gate.render_preflight(ticket, defer=True):
                self.fail("preflight ignored shader compilation")
        self.assertFalse(ticket._finished.is_set())
        self.assertTrue(gate.has_render_preflight)
        running.remove("SHADER_COMPILATION")
        self.assertIs(gate.take_render_preflight(), ticket)
        with gate.render_preflight(ticket, defer=True):
            pass
        worker.join(5)
        self.assertFalse(worker.is_alive())
        self.assertEqual(results, [None])
        gate.evaluation_finished("render", 17)

    def test_preflight_only_exempts_expected_render_not_compositor_or_failures(self):
        gate, running, manager = self.gate(jobs=("RENDER",), locked=True)
        gate.evaluation_started("render", 17)
        ticket = gate.request_render_preflight(17)
        self.assertIs(gate.take_render_preflight(), ticket)
        with gate.render_preflight(ticket):
            pass
        self.assertIsNone(ticket._error)

        gate.evaluation_started("compositor", 17)
        ticket = gate.request_render_preflight(17)
        self.assertIs(gate.take_render_preflight(), ticket)
        with self.assertRaisesRegex(self.module.PublicationDeferred, "Another native"):
            with gate.render_preflight(ticket):
                self.fail("render preflight exempted an overlapping compositor")
        gate.evaluation_finished("compositor", 17)

        ticket = gate.request_render_preflight(17)
        self.assertIs(gate.take_render_preflight(), ticket)
        failure = ValueError("exact preparation failed")
        results = []
        worker = threading.Thread(target=lambda: self._wait(ticket, results))
        worker.start()
        with self.assertRaisesRegex(ValueError, "exact preparation failed"):
            with gate.render_preflight(ticket):
                raise failure
        worker.join(5)
        self.assertFalse(worker.is_alive())
        self.assertEqual(results, [failure])
        self.assertIs(ticket._error, failure)
        self.assertFalse(gate._committing)
        self.assertFalse(gate.has_render_preflight)
        gate.evaluation_finished("render", 17)
        running.clear()
        manager.is_interface_locked = False


if __name__ == "__main__":
    unittest.main()
