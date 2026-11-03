import unittest

from policy.node import Event, new, step


class StackPolicyTests(unittest.TestCase):
    def test_replacement_tracks_order_and_repeated_occurrences(self):
        state, effects = step(
            new(), Event("stack_replace", grade_ids=(11, 12, 11))
        )
        self.assertEqual(state.grade_ids, (11, 12, 11))
        self.assertTrue(effects.rebuild)

        same, effects = step(
            state, Event("stack_replace", grade_ids=(11, 12, 11))
        )
        self.assertEqual(same, state)
        self.assertFalse(effects.rebuild)

        reordered, effects = step(
            state, Event("stack_replace", grade_ids=(12, 11, 11))
        )
        self.assertEqual(reordered.grade_ids, (12, 11, 11))
        self.assertTrue(effects.rebuild)

    def test_shared_grade_edits_rebuild_only_when_referenced(self):
        state, _ = step(new(), Event("stack_replace", grade_ids=(5, 8)))
        updated, effects = step(state, Event("grade_changed", grade_ids=(8,)))
        self.assertEqual(updated, state)
        self.assertTrue(effects.rebuild)

        _, effects = step(state, Event("grade_changed", grade_ids=(13,)))
        self.assertFalse(effects.rebuild)

    def test_empty_and_unassigned_projection_is_identity(self):
        state, effects = step(new(), Event("stack_replace", grade_ids=()))
        self.assertEqual(state.grade_ids, ())
        self.assertFalse(effects.rebuild)

        unchanged, effects = step(state, Event("grade_changed"))
        self.assertEqual(unchanged, state)
        self.assertFalse(effects.rebuild)


if __name__ == "__main__":
    unittest.main()
