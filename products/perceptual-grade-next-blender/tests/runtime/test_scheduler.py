"""Exercise shared work selection, replacement, and cooperative yielding."""

import unittest

from color_tools.runtime.scheduler import WorkScheduler


class SchedulerTests(unittest.TestCase):
    def setUp(self):
        self.now = 0.0
        self.events = []
        self.scheduler = WorkScheduler(clock=lambda: self.now)

    def submit(self, key, kind, *, action=None, **options):
        self.scheduler.submit(key, kind, action or (lambda: self.events.append(key)),
                              **options)

    def advance(self, turns):
        for _ in range(turns):
            self.scheduler.advance()

    def test_foreground_plot_promotes_only_its_transitive_prerequisites(self):
        self.scheduler.focus("main editor")
        self.submit("bake", "bake")
        self.submit("other stack", "consistency")
        self.submit("publication", "consistency", prerequisites=("preparation",))
        self.submit("preparation", "consistency")
        self.submit("foreground plot", "plot", editor="main editor",
                    prerequisites=("publication",), ready=lambda: "publication" in self.events)
        self.submit("other plot", "plot", editor="second editor", prerequisites=("other stack",))
        self.submit("lifecycle", "lifecycle")
        self.submit("render", "render")

        self.assertTrue(self.scheduler.is_promoted("publication"))
        self.assertTrue(self.scheduler.is_promoted("preparation"))
        self.assertFalse(self.scheduler.is_promoted("other stack"))
        self.advance(8)

        self.assertEqual(self.events, [
            "render", "lifecycle", "preparation", "publication", "foreground plot",
            "other stack", "other plot", "bake",
        ])

    def test_newest_plot_per_key_replaces_older_generation(self):
        self.submit("editor", "plot", action=lambda: self.events.append("superseded"))
        self.submit("background", "plot")
        self.submit("editor", "plot", action=lambda: self.events.append("latest"))

        self.advance(2)

        self.assertEqual(self.events, ["latest", "background"])

    def test_reentrant_replacement_survives_completion(self):
        def first():
            self.events.append("first")
            self.submit("owner", "consistency", action=lambda: self.events.append("replacement"))

        self.submit("owner", "consistency", action=first)
        self.advance(2)

        self.assertEqual(self.events, ["first", "replacement"])

    def test_capture_yields_only_to_higher_priority_conflict(self):
        def bake():
            self.events.append("bake")
            return 1.0

        self.submit("bake", "bake", action=bake, pause_group="capture",
                    on_pause=lambda: self.events.append("bake checkpoint"))
        self.advance(1)
        self.submit("unrelated", "consistency")
        self.advance(1)
        self.assertEqual(self.events, ["bake", "unrelated"])

        self.submit("plot", "plot", pause_group="capture")
        self.advance(1)
        self.assertEqual(self.events, ["bake", "unrelated", "bake checkpoint", "plot"])

        self.now = 1.0
        self.advance(1)
        self.assertEqual(self.events[-1], "bake")

    def test_promoted_preparation_keeps_shared_slot_between_polls(self):
        def background():
            self.events.append("background")
            return 0.0

        def prerequisite():
            self.events.append("prerequisite")
            return 0.02 if self.now == 0.0 else None

        self.submit("background", "consistency", action=background,
                    pause_group="stack-preparation")
        self.advance(1)
        self.submit("prerequisite", "consistency", action=prerequisite,
                    pause_group="stack-preparation")
        self.submit("plot", "plot", prerequisites=("prerequisite",))
        self.advance(2)
        self.assertEqual(self.events, ["background", "prerequisite"])
        self.assertTrue(self.scheduler.is_promoted("prerequisite"))

        self.now = 0.02
        self.advance(3)
        self.assertEqual(self.events, ["background", "prerequisite", "prerequisite",
                                       "plot", "background"])
        self.assertFalse(self.scheduler.is_promoted("prerequisite"))

    def test_equal_priority_stack_preparations_take_turns(self):
        self.submit("stack A", "consistency", pause_group="stack-preparation",
                    action=lambda: self.events.append("stack A"))
        self.submit("stack B", "consistency", pause_group="stack-preparation",
                    action=lambda: self.events.append("stack B"))
        self.submit("plot", "plot", prerequisites=("stack A", "stack B"),
                    ready=lambda: False)

        self.advance(2)

        self.assertEqual(self.events, ["stack A", "stack B"])

    def test_preview_releases_promotion_but_not_exact_plot_dependency(self):
        preview_ready = False
        full_ready = False

        def prepare():
            self.events.append("full" if full_ready else "preview")
            return None if full_ready else 0.0

        self.submit("stack", "consistency", pause_group="stack-preparation",
                    action=prepare, promotion_satisfied=lambda: preview_ready)
        self.submit("plot", "plot", prerequisites=("stack",),
                    ready=lambda: full_ready)

        self.advance(1)
        self.assertTrue(self.scheduler.is_promoted("stack"))
        preview_ready = True
        self.assertFalse(self.scheduler.is_promoted("stack"))

        self.advance(1)
        self.assertEqual(self.events, ["preview", "preview"])
        self.assertTrue(self.scheduler.has("stack"))

        full_ready = True
        self.advance(2)
        self.assertEqual(self.events, ["preview", "preview", "full", "plot"])

    def test_recovery_discards_preload_work_then_reopens_plots(self):
        self.submit("old plot", "plot")
        self.submit("old stack", "consistency")
        self.submit("old bake", "bake")
        self.scheduler.set_phase("changing")
        self.scheduler.discard_ordinary()
        self.submit("new plot", "plot")
        self.submit("recovery", "lifecycle")
        self.submit("render", "render")
        self.assertIsNone(self.scheduler.advance())

        self.scheduler.set_phase("recovering")
        self.advance(3)
        self.assertEqual(self.events, ["render", "recovery"])

        self.scheduler.set_phase("ready")
        self.advance(1)
        self.assertEqual(self.events, ["render", "recovery", "new plot"])

    def test_startup_admits_consistency_while_fencing_plots_and_bake(self):
        self.scheduler.set_phase("starting")
        self.submit("startup", "lifecycle", action=lambda: self.events.append("startup"),
                    ready=lambda: "grade" in self.events)
        self.submit("grade", "consistency")
        self.submit("plot", "plot")
        self.submit("bake", "bake")

        self.advance(2)
        self.assertEqual(self.events, ["grade", "startup"])
        self.assertNotIn("plot", self.events)
        self.assertNotIn("bake", self.events)
        self.assertTrue(self.scheduler.has("plot"))
        self.assertTrue(self.scheduler.has("bake"))

        self.scheduler.set_phase("ready")
        self.advance(3)
        self.assertEqual(self.events, ["grade", "startup", "plot", "bake"])

    def test_failure_reports_to_owner_then_waits_for_backoff(self):
        def fail():
            raise RuntimeError("broken receipt")

        self.submit("stack", "consistency", action=fail,
                    on_error=lambda error: self.events.append(str(error)))
        self.assertEqual(self.scheduler.advance(), 0.2)
        self.submit("unrelated", "consistency")
        self.scheduler.wake("stack")
        self.advance(2)
        self.assertEqual(self.events, ["broken receipt", "unrelated"])

        self.now = 0.2
        self.advance(1)
        self.assertEqual(self.events, ["broken receipt", "unrelated", "broken receipt"])

