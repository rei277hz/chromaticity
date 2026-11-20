import unittest

from policy.bake import (
    Effects, Event, State, bake_toggle_available, binding_policy, can_enqueue,
    new, output_policy, persist_source_invalidation, step,
)


class BakePolicyTests(unittest.TestCase):
    def test_request_start_publish_activate(self):
        state, effects = step(new(), Event("request", "a"))
        self.assertEqual((state.phase, effects.action), ("queued", "enqueue"))
        state, effects = step(state, Event("start"))
        self.assertEqual((state.phase, effects.action), ("running", "start"))
        state, effects = step(state, Event(
            "completed", current_signature="a", successful=True))
        self.assertEqual((state.phase, effects.action), ("ready", None))
        state, effects = step(state, Event("publish", current_signature="a"))
        self.assertEqual((state.phase, effects.action), ("publishing", "publish"))
        state, effects = step(state, Event(
            "published", current_signature="a", successful=True))
        self.assertEqual((state.phase, effects.action), ("activating", "activate"))
        state, effects = step(state, Event(
            "activated", current_signature="a", successful=True))
        self.assertEqual((state.phase, effects.action), ("terminal", "retire"))

    def test_activation_failure_authorizes_rollback(self):
        state, effects = step(State("activating", "a"), Event(
            "activated", current_signature="a", successful=False,
            error="activation failed"))
        self.assertEqual((state.phase, effects.action, effects.error),
                         ("terminal", "rollback", "activation failed"))

    def test_start_requires_a_queued_request(self):
        for phase in ("idle", "running", "ready", "terminal"):
            state = State(phase, None if phase in ("idle", "terminal") else "a")
            self.assertEqual(step(state, Event("start")), (state, Effects()))

    def test_edit_cancels_running_request(self):
        state = State("running", "a")
        state, effects = step(state, Event("invalidate", current_signature="b"))
        self.assertEqual(state.phase, "cancelling")
        self.assertEqual(state.signature, "a")
        self.assertEqual(effects, Effects("cancel"))
        state, effects = step(state, Event("cancelled"))
        self.assertEqual((state.phase, effects.action), ("terminal", "retire"))

    def test_stale_completion_is_discarded(self):
        state = State("running", "a")
        state, effects = step(state, Event(
            "completed", current_signature="b", successful=True))
        self.assertEqual((state.phase, effects.action), ("terminal", "discard"))

    def test_queue_is_bounded_and_serial(self):
        self.assertTrue(can_enqueue(0, False))
        self.assertTrue(can_enqueue(7, False))
        self.assertFalse(can_enqueue(8, False))
        self.assertFalse(can_enqueue(0, True))

    def test_toggle_off_selects_live_output(self):
        output = output_policy(False, True)
        self.assertEqual((output.mode, output.error), ("live", None))

    def test_valid_stale_bake_remains_selected(self):
        # Freshness is an adapter warning and does not enter output selection.
        output = output_policy(True, True)
        self.assertEqual((output.mode, output.error), ("baked", None))

    def test_source_invalidation_is_authorized_only_for_tracked_receipt(self):
        self.assertTrue(persist_source_invalidation(True, True))
        self.assertFalse(persist_source_invalidation(False, True))
        self.assertFalse(persist_source_invalidation(True, False))

    def test_invalid_selected_image_fails_closed(self):
        output = output_policy(True, False)
        self.assertEqual(output.mode, "error")
        self.assertIsNotNone(output.error)

    def test_toggle_requires_valid_image_and_live_kernel(self):
        self.assertTrue(bake_toggle_available(True))
        self.assertFalse(bake_toggle_available(False))
        self.assertFalse(bake_toggle_available(True, "live failed"))

    def test_manual_off_retains_valid_bake_binding(self):
        output = output_policy(False, True)
        self.assertEqual((output.mode, output.error), ("live", None))

    def test_shared_image_binding_requires_matching_route_and_valid_artifact(self):
        self.assertEqual(binding_policy("route", True, True).receipt_signature,
                         "route")
        self.assertIsNone(binding_policy("route", False, True).receipt_signature)
        self.assertIsNone(binding_policy("route", True, False).receipt_signature)


if __name__ == "__main__":
    unittest.main()
