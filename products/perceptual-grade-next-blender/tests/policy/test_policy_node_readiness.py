import unittest

from policy.node import (
    Effects,
    Event,
    new,
    output_allowed,
    output_mode,
    step,
)


class KernelReadinessTests(unittest.TestCase):
    def transition(self, state, kind, signature=None, error=None, quality="full",
                   preparation_signature=None):
        if kind == "preparation_result" and error is not None \
                and preparation_signature is None:
            preparation_signature = signature
        updated, effects = step(
            state,
            Event(
                kind, signature, error, quality,
                preparation_signature=preparation_signature,
            ),
        )
        self.assertEqual(effects.output_mode, output_mode(updated))
        self.assertEqual(effects.error, updated.error)
        self.assertEqual(effects.output_mode == "current", output_allowed(updated))
        return updated, effects

    def installed(self, signature="grade-a", quality="full"):
        state, _ = self.transition(new(), "request", signature)
        state, _ = self.transition(state, "preparation_result", signature, quality=quality)
        state, _ = self.transition(state, "installation_result", signature, quality=quality)
        return state

    def test_full_quality_preparation_and_installation_are_distinct(self):
        state = new()
        self.assertIsNone(state.desired_signature)
        self.assertIsNone(state.applied_signature)
        self.assertIsNone(state.applied_quality)
        self.assertFalse(state.gesture_active)

        state, effects = self.transition(state, "request", "grade-a")
        self.assertEqual(effects.output_mode, "pending")
        self.assertEqual(effects.prepare_signature, "grade-a")
        state, effects = self.transition(state, "preparation_result", "grade-a")
        self.assertEqual(effects.build_signature, "grade-a")
        self.assertEqual(effects.build_quality, "full")
        self.assertIsNone(state.applied_signature)
        state, effects = self.transition(state, "installation_result", "grade-a")
        self.assertEqual(effects.output_mode, "current")
        self.assertEqual(state.applied_signature, "grade-a")
        self.assertEqual(state.applied_quality, "full")

    def test_last_good_result_stays_visible_after_release(self):
        state, _ = self.transition(self.installed(), "gesture_begin")
        self.assertTrue(state.gesture_active)
        state, effects = self.transition(state, "request", "grade-b")
        self.assertEqual(state.applied_signature, "grade-a")
        self.assertEqual(effects.output_mode, "preview")

        state, effects = self.transition(state, "gesture_release")
        self.assertFalse(state.gesture_active)
        self.assertEqual(state.applied_signature, "grade-a")
        self.assertEqual(state.applied_quality, "full")
        self.assertEqual(effects.output_mode, "preview")
        self.assertFalse(output_allowed(state))

    def test_first_request_without_last_good_is_pending_not_error(self):
        state, effects = self.transition(new(), "request", "grade-a")
        self.assertEqual(effects.output_mode, "pending")
        self.assertIsNone(effects.error)
        self.assertIsNone(state.applied_signature)

    def test_matching_33_preview_survives_release_until_full_install(self):
        state, effects = self.transition(new(), "request", "grade-b")
        self.assertEqual(effects.prepare_signature, "grade-b")
        state, effects = self.transition(
            state, "preparation_result", "grade-b", quality="preview"
        )
        self.assertEqual(effects.build_signature, "grade-b")
        self.assertEqual(effects.build_quality, "preview")
        state, effects = self.transition(
            state, "installation_result", "grade-b", quality="preview"
        )
        self.assertEqual(state.applied_signature, "grade-b")
        self.assertEqual(state.applied_quality, "preview")
        self.assertEqual(effects.output_mode, "preview")
        self.assertFalse(output_allowed(state))

        state, effects = self.transition(state, "gesture_release")
        self.assertEqual(state.applied_signature, "grade-b")
        self.assertEqual(state.applied_quality, "preview")
        self.assertEqual(effects.output_mode, "preview")

        state, effects = self.transition(state, "preparation_result", "grade-b")
        self.assertEqual(effects.build_quality, "full")
        state, effects = self.transition(state, "installation_result", "grade-b")
        self.assertEqual(state.applied_quality, "full")
        self.assertEqual(effects.output_mode, "current")

    def test_superseded_33_preview_is_accepted_only_during_gesture(self):
        state, _ = self.transition(new(), "request", "grade-a")
        state, _ = self.transition(state, "gesture_begin")
        state, _ = self.transition(state, "request", "grade-b")
        state, effects = self.transition(
            state, "preparation_result", "grade-a", quality="preview"
        )
        self.assertEqual(effects.build_signature, "grade-a")
        self.assertEqual(effects.build_quality, "preview")
        state, effects = self.transition(
            state, "installation_result", "grade-a", quality="preview"
        )
        self.assertEqual(state.applied_signature, "grade-a")
        self.assertEqual(effects.output_mode, "preview")

        state, effects = self.transition(state, "gesture_release")
        self.assertEqual(state.applied_signature, "grade-a")
        self.assertEqual(effects.output_mode, "preview")
        unchanged, effects = self.transition(
            state, "installation_result", "grade-a", quality="preview"
        )
        self.assertEqual(unchanged, state)
        self.assertEqual(effects.output_mode, "preview")
        self.assertIsNone(effects.build_signature)

    def test_superseded_full_result_updates_preview_during_gesture(self):
        state, _ = self.transition(new(), "request", "grade-a")
        state, _ = self.transition(state, "gesture_begin")
        state, _ = self.transition(state, "request", "grade-b")
        state, effects = self.transition(state, "preparation_result", "grade-a")
        self.assertEqual(effects.build_signature, "grade-a")
        self.assertEqual(effects.build_quality, "full")
        state, effects = self.transition(state, "installation_result", "grade-a")
        self.assertEqual(state.applied_signature, "grade-a")
        self.assertEqual(state.applied_quality, "full")
        self.assertEqual(effects.output_mode, "preview")
        self.assertFalse(output_allowed(state))

        state, effects = self.transition(state, "gesture_release")
        self.assertEqual(state.applied_signature, "grade-a")
        self.assertEqual(effects.output_mode, "preview")

    def test_late_preview_does_not_replace_full_result_for_same_signature(self):
        state = self.installed("grade-a")
        state, _ = self.transition(state, "gesture_begin")
        state, effects = self.transition(
            state, "preparation_result", "grade-a", quality="preview"
        )
        self.assertEqual(state.applied_quality, "full")
        self.assertIsNone(effects.build_signature)
        state, effects = self.transition(
            state, "installation_result", "grade-a", quality="preview"
        )
        self.assertEqual(state.applied_quality, "full")
        self.assertEqual(effects.output_mode, "current")

    def test_preview_failure_clears_applied_output_and_waits_for_retry(self):
        state = self.installed("grade-b", quality="preview")
        failed, effects = self.transition(
            state, "preparation_result", "grade-b", "65-cube failure"
        )
        self.assertIsNone(failed.applied_signature)
        self.assertIsNone(failed.applied_quality)
        self.assertEqual(failed.error, "65-cube failure")
        self.assertEqual(effects.output_mode, "error")

        unchanged, effects = self.transition(failed, "installation_result", "grade-b")
        self.assertEqual(unchanged, failed)
        self.assertEqual(effects.output_mode, "error")
        retried, effects = self.transition(failed, "request", "grade-b")
        self.assertIsNone(retried.error)
        self.assertEqual(effects.prepare_signature, "grade-b")

    def test_new_demand_outside_gesture_retains_last_good_result(self):
        state, effects = self.transition(self.installed(), "request", "grade-b")
        self.assertEqual(state.applied_signature, "grade-a")
        self.assertEqual(state.applied_quality, "full")
        self.assertEqual(effects.output_mode, "preview")
        self.assertEqual(effects.prepare_signature, "grade-b")
        self.assertFalse(output_allowed(state))

    def test_request_tracks_preparation_correlation_without_losing_stack_order(self):
        state = new(grade_ids=(1, 2, 1))
        state, effects = self.transition(
            state,
            "request",
            "kernel-a",
            preparation_signature="preparation-a",
        )
        self.assertEqual(state.grade_ids, (1, 2, 1))
        self.assertEqual(state.desired_preparation_signature, "preparation-a")
        self.assertEqual(effects.prepare_signature, "preparation-a")

    def test_only_failure_for_current_preparation_demand_sets_error(self):
        state, _ = self.transition(
            new(), "request", "kernel-a", preparation_signature="preparation-a"
        )
        state, _ = self.transition(
            state, "request", "kernel-b", preparation_signature="preparation-b"
        )
        unchanged, effects = self.transition(
            state,
            "preparation_result",
            error="late failure",
            preparation_signature="preparation-a",
        )
        self.assertEqual(unchanged, state)
        self.assertEqual(effects.output_mode, "pending")

        failed, effects = self.transition(
            unchanged,
            "preparation_result",
            error="current failure",
            preparation_signature="preparation-b",
        )
        self.assertEqual(failed.error, "current failure")
        self.assertEqual(effects.output_mode, "error")

    def test_stale_result_after_release_does_not_replace_last_good(self):
        state, _ = self.transition(self.installed("grade-a"), "gesture_begin")
        state, _ = self.transition(state, "request", "grade-b")
        state, effects = self.transition(state, "gesture_release")
        self.assertEqual(state.applied_signature, "grade-a")
        self.assertEqual(effects.output_mode, "preview")

        unchanged, effects = self.transition(
            state, "installation_result", "older-intermediate"
        )
        self.assertEqual(unchanged, state)
        self.assertEqual(effects.output_mode, "preview")
        self.assertIsNone(effects.build_signature)

    def test_current_requests_and_duplicate_receipts_are_idempotent(self):
        state = self.installed()
        for kind in ("request", "preparation_result", "installation_result"):
            unchanged, effects = self.transition(state, kind, "grade-a")
            self.assertEqual(unchanged, state)
            self.assertEqual(effects.output_mode, "current")
            self.assertIsNone(effects.prepare_signature)
            self.assertIsNone(effects.build_signature)

    def test_return_to_applied_settings_updates_preparation_demand(self):
        state, _ = self.transition(self.installed(), "gesture_begin")
        state, _ = self.transition(state, "request", "grade-b")
        state, effects = self.transition(state, "request", "grade-a")
        self.assertEqual(effects.output_mode, "current")
        self.assertEqual(effects.prepare_signature, "grade-a")
        self.assertIsNone(effects.build_signature)

    def test_disposal_clears_lifecycle_and_only_requests_cleanup(self):
        states = (
            new(),
            new("grade-a", desired_preparation_signature="preparation-a"),
            self.installed(),
            new("grade-b", "grade-a", "preview", True, grade_ids=(1, 2, 1),
                desired_preparation_signature="preparation-b"),
            new("grade-a", error="installation failed", grade_ids=(1, 2),
                desired_preparation_signature="preparation-a"),
        )
        for state in states:
            with self.subTest(state=state):
                disposed, effects = step(state, Event("dispose"))
                self.assertEqual(disposed, new())
                self.assertEqual(effects, Effects(dispose=True))
                self.assertFalse(output_allowed(disposed))
                repeated, repeated_effects = step(disposed, Event("dispose"))
                self.assertEqual(repeated, disposed)
                self.assertEqual(repeated_effects, effects)

    def test_correlated_late_receipts_cannot_restore_disposed_demand(self):
        state, _ = step(
            new("grade-a", "grade-a", "full", True, grade_ids=(1,),
                desired_preparation_signature="preparation-a"),
            Event("dispose"),
        )
        for kind in ("preparation_result", "installation_result"):
            for quality in ("preview", "full"):
                for error in (None, "late failure"):
                    with self.subTest(kind=kind, quality=quality, error=error):
                        unchanged, effects = step(state, Event(
                            kind, "grade-a", error, quality,
                            preparation_signature="preparation-a",
                        ))
                        self.assertEqual(unchanged, state)
                        self.assertFalse(output_allowed(unchanged))
                        self.assertIsNone(effects.prepare_signature)
                        self.assertIsNone(effects.build_signature)
                        self.assertIsNone(effects.build_quality)
                        self.assertIsNone(effects.error)
                        self.assertFalse(effects.rebuild)
                        self.assertFalse(effects.dispose)

        # Disposal withdraws demand; it does not introduce a permanent dead
        # state. A new owner lifecycle may explicitly request work again.
        requested, effects = self.transition(state, "request", "grade-b")
        self.assertEqual(effects.prepare_signature, "grade-b")
        prepared, effects = self.transition(requested, "preparation_result", "grade-b")
        self.assertEqual(effects.build_signature, "grade-b")
        installed, _ = self.transition(prepared, "installation_result", "grade-b")
        self.assertTrue(output_allowed(installed))

if __name__ == "__main__":
    unittest.main()
