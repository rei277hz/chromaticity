import unittest

from color_tools.features.grade.policy.node import Event, new, step
from color_tools.features.grade.stack_observations import (
    grade_is_referenced,
    stack_changed,
)


class StackObservationTests(unittest.TestCase):
    def test_stack_change_preserves_order_and_multiplicity(self):
        first = (11, "FORWARD")
        second = (12, "FORWARD")
        previous = (first, second, first)
        self.assertFalse(stack_changed(previous, (first, second, first)))
        self.assertTrue(stack_changed(previous, (second, first, first)))
        self.assertTrue(stack_changed(previous, (first, second)))
        self.assertTrue(stack_changed(previous, ()))
        self.assertTrue(stack_changed(previous, (first, second, (11, "INVERSE"))))

    def test_grade_reference_uses_current_stack_membership(self):
        entries = ((5, "FORWARD"), (8, "INVERSE"), (5, "INVERSE"))
        self.assertTrue(grade_is_referenced(entries, 8))
        self.assertFalse(grade_is_referenced(entries, 13))


class StackPolicyTests(unittest.TestCase):
    def test_stack_replacement_uses_runtime_observation(self):
        state, effects = step(new(), Event("stack_replace", stack_changed=True))
        self.assertEqual(state, new())
        self.assertTrue(effects.rebuild)

        state, effects = step(new(), Event("stack_replace", stack_changed=False))
        self.assertEqual(state, new())
        self.assertFalse(effects.rebuild)

    def test_grade_change_uses_runtime_membership_observation(self):
        state, effects = step(new(), Event("grade_changed", grade_referenced=True))
        self.assertEqual(state, new())
        self.assertTrue(effects.rebuild)

        state, effects = step(new(), Event("grade_changed", grade_referenced=False))
        self.assertEqual(state, new())
        self.assertFalse(effects.rebuild)


if __name__ == "__main__":
    unittest.main()
