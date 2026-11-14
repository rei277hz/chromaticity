import unittest

from policy.bake import Effects, Event, State, can_enqueue, new, output_policy, step


class BakePolicyTests(unittest.TestCase):
    def test_request_start_publish_activate(self):
        state, effects = step(new(), Event("request", "a", 1, admitted=True))
        self.assertEqual((state.phase, effects.action), ("queued", "enqueue"))
        state, effects = step(state, Event("start", "a", 1, admitted=True))
        self.assertEqual((state.phase, effects.action), ("running", "start"))
        state, effects = step(state, Event("completed", "a", 1,
                                           current_signature="a", successful=True))
        self.assertEqual((state.phase, effects.action), ("ready", None))
        state, effects = step(state, Event("publish", "a", 1,
                                           current_signature="a", admitted=True))
        self.assertEqual((state.phase, effects.action), ("publishing", "publish"))
        state, effects = step(state, Event("published", "a", 1,
                                           current_signature="a", successful=True))
        self.assertEqual((state.phase, effects.action), ("activating", "activate"))
        state, effects = step(state, Event("activated", "a", 1,
                                           current_signature="a", successful=True))
        self.assertEqual((state.phase, effects.action), ("terminal", "retire"))

    def test_activation_failure_authorizes_rollback(self):
        state, effects = step(State("activating", "a", 1), Event(
            "activated", "a", 1, current_signature="a", successful=False,
            error="activation failed"))
        self.assertEqual((state.phase, effects.action, effects.error),
                         ("terminal", "rollback", "activation failed"))

    def test_stale_generation_is_ignored(self):
        state, _ = step(new(), Event("request", "a", 1, admitted=True))
        state, _ = step(state, Event("start", "a", 1, admitted=True))
        unchanged = step(state, Event("completed", "a", 2,
                                      current_signature="a", successful=True))
        self.assertEqual(unchanged, (state, Effects()))

    def test_edit_cancels_running_request(self):
        state = State("running", "a", 1)
        state, effects = step(state, Event("invalidate", "a", 1,
                                           current_signature="b"))
        self.assertEqual(state.phase, "cancelling")
        self.assertEqual((effects.action, effects.signature, effects.generation),
                         ("cancel", "a", 1))
        state, effects = step(state, Event("cancelled", "a", 1))
        self.assertEqual((state.phase, effects.action), ("terminal", "retire"))

    def test_stale_completion_is_discarded(self):
        state = State("running", "a", 1)
        state, effects = step(state, Event("completed", "a", 1,
                                           current_signature="b", successful=True))
        self.assertEqual((state.phase, effects.action), ("terminal", "discard"))

    def test_queue_is_bounded_and_serial(self):
        self.assertTrue(can_enqueue(0, False, True))
        self.assertTrue(can_enqueue(7, False, True))
        self.assertFalse(can_enqueue(8, False, True))
        self.assertFalse(can_enqueue(0, True, True))
        self.assertFalse(can_enqueue(0, False, False))

    def test_toggle_off_is_represented_by_output_policy(self):
        output = output_policy(False, "a", "a", True)
        self.assertEqual((output.mode, output.use_bake, output.error),
                         ("live", False, None))

    def test_stale_bake_automatically_uses_live_output(self):
        output = output_policy(True, "new", "old", True)
        self.assertEqual((output.mode, output.use_bake, output.error),
                         ("live", False, None))

    def test_invalid_selected_image_fails_closed(self):
        output = output_policy(True, "a", "a", False)
        self.assertEqual(output.mode, "error")
        self.assertFalse(output.use_bake)
        self.assertIsNotNone(output.error)


if __name__ == "__main__":
    unittest.main()
