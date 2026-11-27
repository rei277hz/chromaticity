"""Synchronous render-preflight dispatch tests."""

import unittest
from threading import Thread

from color_tools.runtime.scheduler import WorkScheduler


class RenderDispatchTests(unittest.TestCase):
    def setUp(self):
        self.now = 0.0
        self.events = []
        self.scheduler = WorkScheduler(clock=lambda: self.now)

    def submit(self, key, kind, *, action=None, **options):
        self.scheduler.submit(key, kind, action or (lambda: self.events.append(key)), **options)

    def test_only_submitted_render_task_runs(self):
        self.submit("background", "consistency")
        self.submit("manual bake", "bake")
        self.submit("render", "render")

        self.assertTrue(self.scheduler.dispatch_render("render"))
        self.assertEqual(self.events, ["render"])
        self.assertTrue(self.scheduler.has("background"))
        self.assertTrue(self.scheduler.has("manual bake"))
        self.assertFalse(self.scheduler.has("render"))

        self.scheduler.advance()
        self.assertEqual(self.events, ["render", "background"])

    def test_dispatch_pauses_active_capture_before_render(self):
        def capture():
            self.events.append("capture")
            return 1.0

        self.submit("capture", "bake", action=capture,
                    pause_group="capture",
                    on_pause=lambda: self.events.append("capture checkpoint"))
        self.scheduler.advance()
        self.submit("render", "render")

        self.assertTrue(self.scheduler.dispatch_render("render"))
        self.assertEqual(self.events, ["capture", "capture checkpoint", "render"])
        self.assertTrue(self.scheduler.has("capture"))
        self.assertFalse(self.scheduler.has("render"))

    def test_dispatch_rejects_unsubmitted_or_nested_work(self):
        self.assertFalse(self.scheduler.dispatch_render("missing"))
        self.submit("not render", "consistency")
        self.assertFalse(self.scheduler.dispatch_render("not render"))

        nested = []
        self.submit("render", "render",
                    action=lambda: nested.append(self.scheduler.dispatch_render("render")))
        self.assertTrue(self.scheduler.dispatch_render("render"))
        self.assertEqual(nested, [False])
        self.assertFalse(self.scheduler.dispatch_render("render"))

    def test_dispatch_obeys_lifecycle_admission(self):
        self.scheduler.set_phase("changing")
        self.submit("render", "render")
        self.assertFalse(self.scheduler.dispatch_render("render"))
        self.assertEqual(self.events, [])
        self.scheduler.set_phase("recovering")
        self.assertTrue(self.scheduler.dispatch_render("render"))
        self.assertEqual(self.events, ["render"])

    def test_dispatch_preserves_remaining_phases_for_timer(self):
        phases = iter((0.25, None))

        def render():
            self.events.append("render phase")
            return next(phases)

        self.scheduler.submit("multi-phase render", "render", render)
        self.assertTrue(self.scheduler.dispatch_render("multi-phase render"))
        self.assertTrue(self.scheduler.has("multi-phase render"))
        self.scheduler.advance()
        self.assertEqual(self.events, ["render phase"])
        self.now = 0.25
        self.scheduler.advance()
        self.assertEqual(self.events, ["render phase", "render phase"])
        self.assertFalse(self.scheduler.has("multi-phase render"))

    def test_dispatch_rejects_worker_thread(self):
        self.submit("render", "render")
        results = []
        worker = Thread(target=lambda: results.append(self.scheduler.dispatch_render("render")))
        worker.start()
        worker.join()
        self.assertEqual(results, [False])
        self.assertTrue(self.scheduler.has("render"))

    def test_dispatch_removes_failed_task_before_propagating(self):
        def fail():
            raise RuntimeError("preflight failed")

        self.scheduler.submit("render", "render", fail)
        with self.assertRaisesRegex(RuntimeError, "preflight failed"):
            self.scheduler.dispatch_render("render")
        self.assertFalse(self.scheduler.has("render"))
