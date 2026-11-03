"""Reduced-toe precision diagnostics never bypass retained local safety."""
import unittest
import numpy as np

from color_tools.perceptual_grade_nodes import prepare, ColorSettings
from color_tools.perceptual_grade_reference.responses import State
from tools.perceptual_grade_nodes.web_toe_local import local_result, with_toe_cells


class WebToeLocalTests(unittest.TestCase):
    def test_legacy_toe_override_preserves_inactive_web_without_geometry(self):
        prepared = prepare(color=ColorSettings(lightness=((1., 0., 0., 0.),)*4))
        self.assertIsNone(prepared.color.web_toe_table)
        self.assertIsNone(prepared.color.geometry)
        self.assertIs(with_toe_cells(prepared, 524288), prepared)
        self.assertIsNone(prepared.color.web_toe_table)
        with self.assertRaises(ValueError):
            with_toe_cells(prepared, 123)

    def setUp(self):
        self.expected = State(np.array([[80., 3., 4.]]), np.array([6070.]))
        self.baseline = dict(rgb=self.expected.q.copy(), valid=self.expected.energy.copy(),
                             margin=np.ones(1), saturated=np.zeros(1))

    def measure(self, actual):
        return local_result(actual, self.baseline, self.expected, self.expected, np.ones(1), 1e-5)

    def test_large_precision_error_remains_visible_without_becoming_safety_failure(self):
        actual = {key:value.copy() for key,value in self.baseline.items()}
        actual['rgb'][0, 1] += .1
        actual['margin'][0] = 1.02
        row = self.measure(actual)
        self.assertFalse(row['raw_precision_passed'])
        self.assertTrue(row['safety_passed'])
        self.assertGreater(row['state']['ab'], row['state_error_limit'])
        self.assertGreater(row['scale_relative_error'], row['scale_relative_error_limit'])
        self.assertFalse(row['decode_validity_checked'])

    def test_sign_and_saturation_changes_still_reject_local_safety(self):
        for key, value in (('valid', -6070.), ('saturated', 1.)):
            actual = {name:array.copy() for name,array in self.baseline.items()}
            actual[key][0] = value
            row = self.measure(actual)
            self.assertFalse(row['safety_passed'])
        self.assertEqual(row['changed_saturation_pixels'], 1)

    def test_nonfinite_outputs_fail_safety(self):
        actual = {key:value.copy() for key,value in self.baseline.items()}
        actual['margin'][0] = np.inf
        row = self.measure(actual)
        self.assertFalse(row['finite'])
        self.assertFalse(row['safety_passed'])


if __name__ == '__main__':
    unittest.main()
