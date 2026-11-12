import unittest

from policy.node import Event, new, step
from color_tools.runtime.stack_observations import (
    grade_is_referenced,
    stack_changed,
)


class StackObservationTests(unittest.TestCase):
    def test_stack_change_preserves_order_and_multiplicity(self):
        previous = (11, 12, 11)
        self.assertFalse(stack_changed(previous, (11, 12, 11)))
        self.assertTrue(stack_changed(previous, (12, 11, 11)))
        self.assertTrue(stack_changed(previous, (11, 12)))
        self.assertTrue(stack_changed(previous, ()))

    def test_grade_reference_uses_current_stack_membership(self):
        grade_ids = (5, 8, 5)
        self.assertTrue(grade_is_referenced(grade_ids, 8))
        self.assertFalse(grade_is_referenced(grade_ids, 13))


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
