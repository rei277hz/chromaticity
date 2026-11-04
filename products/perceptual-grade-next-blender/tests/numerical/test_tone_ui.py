"""Authored Tone controls project only the anchor being edited."""

from dataclasses import replace
import unittest

import numpy as np

from color_tools.kernel import ToneSettings
from color_tools.kernel.prepare import nits_to_j
from color_tools.kernel.tone_ui import TONE_LIMITS, clamp_tone_anchor


class ToneControlTests(unittest.TestCase):
    def test_each_edited_anchor_keeps_a_lightness_gap_without_moving_neighbors(self):
        controls = ToneSettings()
        for index in range(5):
            for value in (-100., 1e7):
                with self.subTest(index=index, value=value):
                    clamped = clamp_tone_anchor(controls, index, value)
                    edited = list(controls.input_nits)
                    edited[index] = clamped
                    self.assertTrue(all(a == b for offset, (a, b) in enumerate(
                        zip(edited, controls.input_nits)) if offset != index))
                    self.assertGreaterEqual(clamped, TONE_LIMITS[index][0] - 1e-10)
                    self.assertLessEqual(clamped, TONE_LIMITS[index][1] + 1e-10)
                    gaps = np.diff(nits_to_j(edited))
                    self.assertGreaterEqual(float(np.min(gaps)), .001 - 1e-12)

    def test_safe_interior_edit_round_trips(self):
        controls = replace(ToneSettings(), input_nits=(0., 5., 50., 210., 1200.))
        for index, value in enumerate(controls.input_nits):
            self.assertAlmostEqual(clamp_tone_anchor(controls, index, value), value,
                                   delta=1e-9)

    def test_invalid_anchor_inputs_are_rejected(self):
        with self.assertRaises(TypeError):
            clamp_tone_anchor(None, 0, 0.)
        for index in (-1, 5, True):
            with self.assertRaises(ValueError):
                clamp_tone_anchor(ToneSettings(), index, 0.)
        with self.assertRaises(ValueError):
            clamp_tone_anchor(ToneSettings(), 0, float("nan"))


if __name__ == "__main__":
    unittest.main()
