import unittest

from policy.preparation_join import Effects, Event, State, new, step


class PreparationJoinTests(unittest.TestCase):
    def test_completion_is_admitted_only_after_each_component_retires(self):
        state = new("revision")
        self.assertEqual(state, State("revision", True, True, True))

        for component in ("tone", "linear"):
            state, effects = step(state, Event("revision", component))
            self.assertEqual(effects, Effects())

        state, effects = step(state, Event("revision", "boundary"))
        self.assertEqual(state, State("revision", False, False, False))
        self.assertEqual(effects, Effects("revision"))

    def test_first_error_waits_for_all_children_and_is_retained(self):
        state = new("revision")
        state, effects = step(state, Event("revision", "tone", "tone failed"))
        self.assertEqual(state.error, "tone failed")
        self.assertEqual(effects, Effects())

        state, effects = step(state, Event("revision", "boundary", "boundary failed"))
        self.assertEqual(state.error, "tone failed")
        self.assertEqual(effects, Effects())

        state, effects = step(state, Event("revision", "linear"))
        self.assertEqual(effects, Effects("revision", "tone failed"))

    def test_stale_and_duplicate_receipts_do_not_change_state(self):
        state = new("revision")
        stale, effects = step(state, Event("other", "linear"))
        self.assertEqual((stale, effects), (state, Effects()))

        state, _ = step(state, Event("revision", "linear"))
        duplicate, effects = step(state, Event("revision", "linear", "late error"))
        self.assertEqual((duplicate, effects), (state, Effects()))


if __name__ == "__main__":
    unittest.main()
