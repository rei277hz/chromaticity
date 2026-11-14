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

    def publish(self, ticket, signature="grade-frame"):
        event = self.module.render_preflight.Event(
            "published", ticket.render_identity, ticket.scene_identity,
            ticket.frame, ticket.subframe, ticket.generation,
            signature=signature, published_signature=signature,
        )
        self.assertEqual(ticket.resolve(event).action, "release")

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

    def test_graph_reconciliation_joins_publication_but_defers_during_render(self):
        gate, _running, _manager = self.gate()
        with gate.commit():
            with gate.graph_commit():
                self.assertTrue(gate.blocked())
        gate.evaluation_started("render", 17)
        with self.assertRaises(self.module.PublicationDeferred):
            with gate.graph_commit():
                self.fail("Graph mutation raced an active render")
        ticket = gate.request_render_preflight(17, 17, 1, "0x0.0p+0")
        self.assertIs(gate.take_render_preflight(), ticket)
        with gate.render_preflight(ticket):
            with gate.graph_commit():
                self.publish(ticket)
        gate.evaluation_finished("render", 17)
        with gate.graph_commit():
            pass

    def test_graph_reconciliation_cannot_join_a_compositor_snapshot(self):
        gate, _running, _manager = self.gate(jobs=("COMPOSITE",))
        gate.evaluation_started("compositor", 11)
        with gate.snapshot_commit(11):
            with self.assertRaises(self.module.PublicationDeferred):
                with gate.graph_commit():
                    self.fail("Graph mutation joined a compositor snapshot")

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
        self.assertTrue(gate.evaluation_active("compositor", 11))
        self.assertFalse(gate.evaluation_active("compositor", 12))
        self.assertFalse(gate.evaluation_active("render", 11))
        gate.evaluation_finished("compositor", 12)
        self.assertTrue(gate.blocked())
        self.assertTrue(gate.evaluation_active("compositor", 11))
        gate.evaluation_finished("compositor", 11)
        self.assertFalse(gate.evaluation_active("compositor", 11))
        self.assertFalse(gate.blocked())

    def test_evaluation_active_waits_for_every_matching_receipt(self):
        gate, _running, _manager = self.gate()
        gate.evaluation_started("render", 11)
        gate.evaluation_started("render", 11)
        self.assertTrue(gate.evaluation_active("render", 11))
        gate.evaluation_finished("render", 11)
        self.assertTrue(gate.evaluation_active("render", 11))
        gate.evaluation_finished("render", 11)
        self.assertFalse(gate.evaluation_active("render", 11))

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

    def test_receipts_capture_plain_generations_and_monotonic_epochs(self):
        gate, _running, _manager = self.gate()
        snapshot = {27: 4, 28: 6}
        first = gate.evaluation_started("compositor", 11, snapshot=snapshot)
        snapshot[27] = 5
        self.assertEqual(gate.current_compositor(), (11, first))
        self.assertIsNone(gate.evaluation_finished("compositor", 12))
        receipt = gate.evaluation_finished("compositor", 11, successful=False)
        self.assertEqual((receipt.kind, receipt.identity, receipt.epoch),
                         ("compositor", 11, first))
        self.assertEqual(receipt.snapshot, ((27, 4), (28, 6)))
        self.assertFalse(receipt.successful)
        gate.reset()
        second = gate.evaluation_started("compositor", 11)
        self.assertGreater(second, first)
        with self.assertRaises(TypeError):
            gate.evaluation_started("compositor", 12, snapshot={27: object()})
        self.assertEqual(gate.current_compositor(), (11, second))

    def test_live_admission_requires_real_job_and_exactly_one_matching_snapshot(self):
        gate, running, _manager = self.gate(jobs=("COMPOSITE",))
        with self.assertRaisesRegex(self.module.PublicationDeferred, "observed snapshot"):
            with gate.snapshot_commit(11):
                self.fail("compositor startup gap was admitted")
        epoch = gate.evaluation_started("compositor", 11)
        with self.assertRaises(self.module.PublicationDeferred):
            with gate.snapshot_commit(12):
                self.fail("another scene's snapshot was admitted")
        running.clear()
        with self.assertRaisesRegex(self.module.PublicationDeferred, "COMPOSITE"):
            with gate.snapshot_commit(11):
                self.fail("an unpaired callback without a native job was admitted")
        running.add("COMPOSITE")
        with gate.snapshot_commit(11) as observed:
            self.assertEqual(observed, epoch)
            self.assertFalse(gate.quiescent())
            with self.assertRaises(self.module.PublicationDeferred):
                with gate.commit():
                    self.fail("live snapshot admitted mutable image publication")
            with self.assertRaises(self.module.PublicationDeferred):
                with gate.snapshot_commit(11):
                    self.fail("nested live publication admitted")
        self.assertIsNone(gate.progress_state.epoch)
        for kind, identity in (("compositor", 11), ("compositor", 12), ("render", 11)):
            with self.subTest(kind=kind, identity=identity):
                gate.evaluation_started(kind, identity)
                self.assertIsNone(gate.current_compositor())
                with self.assertRaises(self.module.PublicationDeferred):
                    with gate.snapshot_commit(11):
                        self.fail("overlapping evaluations were admitted")
                gate.evaluation_finished(kind, identity)

    def test_live_admission_preserves_every_unrelated_host_exclusion(self):
        for job in self.module.JOBS:
            if job == "COMPOSITE":
                continue
            with self.subTest(job=job):
                gate, _running, _manager = self.gate(jobs=("COMPOSITE", job))
                gate.evaluation_started("compositor", 11)
                with self.assertRaisesRegex(self.module.PublicationDeferred, job):
                    with gate.snapshot_commit(11):
                        self.fail("unrelated host reader was exempted")
        for options in ({"locked": True}, {"modal": ("OBJECT_OT_bake_image",)}):
            gate, _running, _manager = self.gate(jobs=("COMPOSITE",), **options)
            gate.evaluation_started("compositor", 11)
            with self.assertRaises(self.module.PublicationDeferred):
                with gate.snapshot_commit(11):
                    self.fail("interface or bake lock was exempted")
        gate, _running, _manager = self.gate(jobs=("COMPOSITE",))
        gate.evaluation_started("compositor", 11)
        with gate.callback(), self.assertRaises(self.module.PublicationDeferred):
            with gate.snapshot_commit(11):
                self.fail("publication inside callback admitted")

    def test_supersession_requires_admitted_scope_and_exact_epoch(self):
        gate, _running, _manager = self.gate(jobs=("COMPOSITE",))
        epoch = gate.evaluation_started("compositor", 11)
        with self.assertRaises(self.module.PublicationDeferred):
            gate.superseded(11, epoch)
        with gate.snapshot_commit(11):
            for scene, stale_epoch in ((12, epoch), (11, epoch + 1)):
                with self.assertRaises(self.module.PublicationDeferred):
                    gate.superseded(scene, stale_epoch)
            gate.superseded(11, epoch)
        self.assertEqual((gate.progress_state.scene_id, gate.progress_state.epoch), (11, epoch))
        with self.assertRaisesRegex(self.module.PublicationDeferred, "protected"):
            with gate.snapshot_commit(11):
                self.fail("second live swap was admitted")

    def test_protection_survives_cancellation_and_unrelated_completion(self):
        gate, running, _manager = self.gate(jobs=("COMPOSITE",))
        first = gate.evaluation_started("compositor", 11)
        with gate.snapshot_commit(11):
            gate.superseded(11, first)
        gate.evaluation_finished("compositor", 11, successful=True)
        self.assertEqual(gate.progress_state.epoch, first)
        running.clear()
        with gate.commit():
            self.assertTrue(gate.quiescent())
        self.assertEqual(gate.progress_state.epoch, first)
        running.add("COMPOSITE")
        for scene, successful in ((11, False), (12, True)):
            gate.evaluation_started("compositor", scene)
            with self.assertRaisesRegex(self.module.PublicationDeferred, "protected"):
                with gate.snapshot_commit(scene):
                    self.fail("protected successor was superseded")
            gate.evaluation_finished("compositor", scene, successful=successful)
            self.assertEqual(gate.progress_state.epoch, first)
        successor = gate.evaluation_started("compositor", 11)
        gate.evaluation_finished("compositor", 11, successful=True)
        self.assertIsNone(gate.progress_state.epoch)
        next_epoch = gate.evaluation_started("compositor", 11)
        self.assertGreater(next_epoch, successor)
        with gate.snapshot_commit(11) as observed:
            self.assertEqual(observed, next_epoch)

    def test_reset_cannot_release_protection_while_host_is_busy(self):
        gate, running, _manager = self.gate(jobs=("COMPOSITE",))
        epoch = gate.evaluation_started("compositor", 11)
        with gate.snapshot_commit(11):
            gate.superseded(11, epoch)
        with self.assertRaises(self.module.PublicationDeferred):
            gate.reset()
        self.assertEqual(gate.progress_state.epoch, epoch)
        running.clear()
        with self.assertRaisesRegex(self.module.PublicationDeferred, "active evaluation"):
            gate.reset()
        gate.evaluation_finished("compositor", 11, successful=True)
        gate.reset()
        self.assertIsNone(gate.progress_state.epoch)
        self.assertIsNone(gate.current_compositor())

    def test_live_admission_rechecks_host_and_leases_before_yield(self):
        for race in ("job_ended", "render_started", "callback_started"):
            with self.subTest(race=race):
                bpy, running, _manager = self.host(jobs=("COMPOSITE",))
                gate = self.module.PublicationGate(bpy)
                gate.evaluation_started("compositor", 11)
                observations = []

                def is_running(name):
                    if name == "COMPOSITE":
                        observations.append(name)
                        if len(observations) == 2:
                            if race == "job_ended":
                                running.clear()
                            elif race == "render_started":
                                gate.evaluation_started("render", 19)
                            else:
                                gate._callbacks += 1
                    return name in running

                bpy.app.is_job_running = is_running
                with self.assertRaises(self.module.PublicationDeferred):
                    with gate.snapshot_commit(11):
                        self.fail("reader changed after initial admission")
                self.assertFalse(gate._committing)
                self.assertIsNone(gate._snapshot_active)
                self.assertIsNone(gate.progress_state.epoch)

    def test_worker_cannot_inspect_or_enter_live_publication(self):
        gate = self.module.PublicationGate(SimpleNamespace())
        errors = []

        def publish():
            self.assertFalse(gate.quiescent())
            try:
                with gate.snapshot_commit(11):
                    self.fail("worker publication admitted")
            except self.module.PublicationDeferred as error:
                errors.append(str(error))

        worker = threading.Thread(target=publish)
        worker.start()
        worker.join(5)
        self.assertFalse(worker.is_alive())
        self.assertEqual(len(errors), 1)
        self.assertIn("main thread", errors[0])

    def test_worker_render_waits_for_exact_main_thread_preflight(self):
        gate, running, _manager = self.gate(jobs=("RENDER",))
        gate.evaluation_started("render", 17)
        tickets = []
        submitted = threading.Event()
        results = []

        def callback():
            ticket = gate.request_render_preflight(17, 17, 1, float(0.0).hex())
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
            self.assertFalse(gate.quiescent())
            self.assertTrue(gate.retirement_allowed())
            self.publish(ticket)
        worker.join(5)

        self.assertFalse(worker.is_alive())
        self.assertEqual(results, [None])
        self.assertTrue(ticket._finished.is_set())
        self.assertFalse(gate._committing)
        gate.evaluation_finished("render", 17)
        running.clear()

    def test_retirement_needs_entered_preflight_and_retains_reader_exclusions(self):
        gate, running, manager = self.gate(jobs=("RENDER",), locked=True)
        gate.evaluation_started("render", 17)
        ticket = gate.request_render_preflight(17, 17, 1, float(0.0).hex())
        self.assertFalse(gate.retirement_allowed())
        self.assertIs(gate.take_render_preflight(), ticket)
        self.assertFalse(gate.retirement_allowed())
        with gate.render_preflight(ticket):
            self.assertTrue(gate.retirement_allowed())
            with gate.callback():
                self.assertFalse(gate.retirement_allowed())
            running.add("SHADER_COMPILATION")
            self.assertFalse(gate.retirement_allowed())
            running.remove("SHADER_COMPILATION")
            gate.evaluation_started("compositor", 11)
            self.assertFalse(gate.retirement_allowed())
            gate.evaluation_finished("compositor", 11)
            self.assertTrue(gate.retirement_allowed())
            self.publish(ticket)
        self.assertFalse(gate.retirement_allowed())
        gate.evaluation_finished("render", 17)
        running.clear()
        manager.is_interface_locked = False
        with gate.commit():
            self.assertTrue(gate.retirement_allowed())

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
        first = gate.request_render_preflight(17, 17, 1, float(0.0).hex())
        second = gate.request_render_preflight(17, 17, 2, float(0.0).hex())
        self.assertIs(gate.take_render_preflight(), first)

        with self.assertRaisesRegex(self.module.PublicationDeferred, "not active"):
            with gate.render_preflight(second):
                self.fail("a queued ticket was treated as the active ticket")

        self.assertFalse(first._finished.is_set())
        self.assertFalse(second._finished.is_set())
        self.assertIsNone(gate.take_render_preflight())
        with gate.render_preflight(first):
            self.publish(first)
        self.assertTrue(first._finished.is_set())
        self.assertIs(gate.take_render_preflight(), second)
        with gate.render_preflight(second):
            self.publish(second)
        self.assertTrue(second._finished.is_set())
        gate.evaluation_finished("render", 17)
        running.clear()

    def test_preflight_rejects_another_render_job_or_identity(self):
        gate, running, _manager = self.gate(jobs=("RENDER", "RENDER_PREVIEW"))
        gate.evaluation_started("render", 17)
        ticket = gate.request_render_preflight(17, 17, 1, float(0.0).hex())
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
        ticket = gate.request_render_preflight(99, 99, 1, float(0.0).hex())
        self.assertTrue(ticket.failure_authorized)
        self.assertIs(gate.take_render_preflight(), ticket)
        self.assertTrue(gate.finish_render_preflight_failure(ticket))
        self.assertIsInstance(ticket._error, self.module.PublicationDeferred)
        self.assertFalse(gate.has_render_preflight)
        gate.evaluation_finished("render", 17)
        running.clear()

    def test_preflight_failure_wakes_worker_and_lifecycle_reset_cancels_waiter(self):
        gate, running, manager = self.gate(jobs=("RENDER",))
        gate.evaluation_started("render", 17)
        ticket = gate.request_render_preflight(17, 17, 1, float(0.0).hex())
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
        ticket = gate.request_render_preflight(17, 17, 1, float(0.0).hex())
        results.clear()
        worker = threading.Thread(target=lambda: self._wait(ticket, results))
        worker.start()
        manager.is_interface_locked = True
        with self.assertRaisesRegex(self.module.PublicationDeferred, "interface is locked"):
            gate.reset()
        self.assertFalse(ticket._finished.is_set())
        running.clear()
        manager.is_interface_locked = False
        gate.evaluation_finished("render", 17)
        gate.reset()
        worker.join(5)
        self.assertFalse(worker.is_alive())
        self.assertEqual(len(results), 1)
        self.assertIsInstance(results[0], self.module.PublicationDeferred)
        self.assertFalse(gate.has_render_preflight)

    def test_direct_main_thread_render_uses_scope_without_waiting(self):
        gate, _running, _manager = self.gate()
        gate.evaluation_started("render", 17)
        ticket = gate.request_render_preflight(17, 17, 1, float(0.0).hex())
        self.assertIs(gate.take_render_preflight(), ticket)
        with gate.render_preflight(ticket):
            self.publish(ticket)
        self.assertTrue(ticket._finished.is_set())
        self.assertIsNone(ticket._error)
        with self.assertRaisesRegex(RuntimeError, "main thread cannot wait"):
            ticket.wait()
        gate.evaluation_finished("render", 17)

    def test_terminal_failure_waits_for_host_fail_closed_before_worker_release(self):
        gate, _running, _manager = self.gate(jobs=("RENDER", "OBJECT_BAKE"))
        gate.evaluation_started("render", 17)
        ticket = gate.request_render_preflight(17, 17, 1, float(0.0).hex())
        results = []
        worker = threading.Thread(target=lambda: self._wait(ticket, results))
        worker.start()
        self.assertIs(gate.take_render_preflight(), ticket)
        with self.assertRaisesRegex(self.module.PublicationDeferred, "OBJECT_BAKE"):
            with gate.render_preflight(ticket, deliver_failure=False):
                self.fail("a conflicting bake job was admitted")
        self.assertTrue(ticket.failure_authorized)
        self.assertFalse(ticket._finished.is_set())
        self.assertIs(gate._preflight_active, ticket)
        self.assertTrue(gate.finish_render_preflight_failure(ticket))
        worker.join(5)
        self.assertFalse(worker.is_alive())
        self.assertEqual(len(results), 1)
        self.assertIsInstance(results[0], self.module.PublicationDeferred)
        self.assertFalse(gate.has_render_preflight)
        gate.evaluation_finished("render", 17)

    def test_deferred_worker_preflight_keeps_waiter_blocked_until_reader_retires(self):
        gate, running, _manager = self.gate(jobs=("RENDER", "SHADER_COMPILATION"))
        gate.evaluation_started("render", 17)
        ticket = gate.request_render_preflight(17, 17, 1, float(0.0).hex())
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
            self.publish(ticket)
        worker.join(5)
        self.assertFalse(worker.is_alive())
        self.assertEqual(results, [None])
        gate.evaluation_finished("render", 17)

    def test_preflight_only_exempts_expected_render_not_compositor_or_failures(self):
        gate, running, manager = self.gate(jobs=("RENDER",), locked=True)
        gate.evaluation_started("render", 17)
        ticket = gate.request_render_preflight(17, 17, 1, float(0.0).hex())
        self.assertIs(gate.take_render_preflight(), ticket)
        with gate.render_preflight(ticket):
            self.publish(ticket)
        self.assertIsNone(ticket._error)

        gate.evaluation_started("compositor", 17)
        ticket = gate.request_render_preflight(17, 17, 1, float(0.0).hex())
        self.assertIs(gate.take_render_preflight(), ticket)
        with self.assertRaisesRegex(self.module.PublicationDeferred, "Another native"):
            with gate.render_preflight(ticket):
                self.fail("render preflight exempted an overlapping compositor")
        gate.evaluation_finished("compositor", 17)

        ticket = gate.request_render_preflight(17, 17, 1, float(0.0).hex())
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
