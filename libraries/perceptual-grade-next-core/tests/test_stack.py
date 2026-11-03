import unittest

from color_tools.perceptual_grade_core.stack import Event, new, step


class StackPolicyTests(unittest.TestCase):
    def test_replacement_tracks_order_and_repeated_occurrences(self):
        state, effects = step(new(), Event("replace", (11, 12, 11), 0))
        self.assertEqual(state.grade_ids, (11, 12, 11))
        self.assertTrue(effects.rebuild)

        same, effects = step(state, Event("replace", (11, 12, 11), 0))
        self.assertEqual(same, state)
        self.assertFalse(effects.rebuild)

        reordered, effects = step(state, Event("replace", (12, 11, 11), 0))
        self.assertEqual(reordered.grade_ids, (12, 11, 11))
        self.assertTrue(effects.rebuild)

    def test_focus_and_shared_grade_edits_have_distinct_effects(self):
        state, _ = step(new(), Event("replace", (5, 8), 0))
        selected, effects = step(state, Event("select", (), 0))
        self.assertEqual(selected, state)
        self.assertFalse(effects.rebuild)

        updated, effects = step(state, Event("grade_changed", (), 8))
        self.assertEqual(updated, state)
        self.assertTrue(effects.rebuild)

        _, effects = step(state, Event("grade_changed", (), 13))
        self.assertFalse(effects.rebuild)

    def test_empty_and_unassigned_projection_is_identity(self):
        state, effects = step(new(), Event("replace", (), 0))
        self.assertEqual(state.grade_ids, ())
        self.assertFalse(effects.rebuild)


if __name__ == "__main__":
    unittest.main()
