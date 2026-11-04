"""Collection scheduling queries are ordinary Python, outside policy proofs."""
import unittest

from color_tools.perceptual_grade_core.graph import scheduler_policy as policy


class SchedulerQueryTests(unittest.TestCase):
    def test_production_queries_preserve_uncapped_folds_and_integer_cursors(self):
        self.assertTrue(policy.final_scope_resolution(iter(())))
        self.assertTrue(policy.final_scope_resolution(iter((65,) * 1001)))
        self.assertFalse(policy.final_scope_resolution((65,) * 1000 + (33,)))
        eligible = tuple(index in (2, 11) for index in range(13))
        for cursor, expected in ((-1, 2), (3, 11), (12, 2), (29, 11)):
            self.assertEqual(policy.scope_next(eligible, cursor), expected)
        for cursor in (-100, 0, 100):
            self.assertEqual(policy.scope_next((), cursor), -1)
            self.assertEqual(policy.scope_next((False,) * 13, cursor), -1)


    def test_resolution_scan_still_consumes_the_input_iterable(self):
        seen = []
        def values():
            for value in (33, 65, 65):
                seen.append(value)
                yield value
        self.assertFalse(policy.final_scope_resolution(values()))
        self.assertEqual(seen, [33, 65, 65])


if __name__ == '__main__':
    unittest.main()
