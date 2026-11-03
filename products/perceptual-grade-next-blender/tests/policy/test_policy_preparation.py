import unittest

from policy.preparation import Effects, Event, new, step


class PreparationPolicyTests(unittest.TestCase):
    def test_initial_state_uses_optional_signatures(self):
        state = new()
        self.assertIsNone(state.desired_signature)
        self.assertIsNone(state.running_signature)

    def test_preview_publishes_without_retiring_or_releasing_the_worker(self):
        state, effects = step(new(), Event("request", "a"))
        self.assertEqual(effects.prepare_signature, "a")
        state, effects = step(state, Event("request", "c"))
        self.assertEqual(state, type(state)("c", "a"))

        preview_state, effects = step(state, Event("preparation_preview", "a"))
        self.assertEqual(preview_state, state)
        self.assertEqual(effects, Effects(preview_signature="a"))

        final_state, effects = step(preview_state, Event("preparation_result", "a"))
        self.assertEqual(final_state.running_signature, "c")
        self.assertEqual(effects.prepare_signature, "c")
        self.assertEqual(effects.result_signature, "a")

    def test_drag_keeps_only_latest_successor_until_final_receipt(self):
        state, _ = step(new(), Event("request", "a"))
        for signature in ("b", "c", "d"):
            state, effects = step(state, Event("request", signature))
            self.assertEqual(state.running_signature, "a")
            self.assertEqual(state.desired_signature, signature)
            self.assertEqual(effects, Effects())

        state, effects = step(state, Event("preparation_preview", "a"))
        self.assertEqual(state.running_signature, "a")
        self.assertEqual(effects.preview_signature, "a")
        self.assertIsNone(effects.prepare_signature)

        state, effects = step(state, Event("preparation_result", "a"))
        self.assertEqual(state.running_signature, "d")
        self.assertEqual(effects.prepare_signature, "d")
        self.assertEqual(effects.result_signature, "a")

    def test_current_final_completion_does_not_restart(self):
        state, _ = step(new(), Event("request", "a"))
        state, effects = step(state, Event("preparation_result", "a"))
        self.assertEqual(state, type(state)("a", None))
        self.assertEqual(effects.result_signature, "a")
        self.assertIsNone(effects.prepare_signature)

    def test_obsolete_failure_starts_successor_without_delivering_error(self):
        state, _ = step(new(), Event("request", "a"))
        state, _ = step(state, Event("request", "b"))
        state, effects = step(state, Event("preparation_result", "a", "failed"))
        self.assertEqual(state.running_signature, "b")
        self.assertEqual(effects.prepare_signature, "b")
        self.assertIsNone(effects.result_signature)
        self.assertIsNone(effects.error)

    def test_preview_receipt_is_fenced_to_the_running_signature(self):
        state, _ = step(new(), Event("request", "a"))
        for signature in (None, "b"):
            unchanged, effects = step(state, Event("preparation_preview", signature))
            self.assertEqual(unchanged, state)
            self.assertEqual(effects, Effects())

    def test_withdrawal_keeps_worker_occupied_until_final_receipt(self):
        state, _ = step(new(), Event("request", "a"))
        state, effects = step(state, Event("request"))
        self.assertIsNone(state.desired_signature)
        self.assertEqual(state.running_signature, "a")
        self.assertEqual(effects, Effects())

        state, effects = step(state, Event("preparation_preview", "a"))
        self.assertEqual(state.running_signature, "a")
        self.assertEqual(effects, Effects(preview_signature="a"))
        state, effects = step(state, Event("preparation_result", "a"))
        self.assertEqual(state, new())
        self.assertEqual(effects, Effects())

if __name__ == "__main__":
    unittest.main()
