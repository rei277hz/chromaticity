"""The signed appearance stage and its inverse."""
from dataclasses import replace
import unittest

import numpy as np

from color_tools.perceptual_grade_reference.grading import Tone, ToneSettings
from color_tools.perceptual_grade_reference.unified_chroma import UnifiedChroma, UnifiedChromaSettings


class UnifiedChromaTests(unittest.TestCase):
    def test_default_is_identity_in_both_directions(self):
        points = [[0., -0., 0.], [-40., 12., 1.], [0., 25., -20.], [230., 15., -30.]]
        stage = UnifiedChroma(UnifiedChromaSettings())
        for evaluate in (stage.forward, stage.inverse):
            actual = evaluate(points)
            np.testing.assert_array_equal(actual, points)
            self.assertTrue(np.signbit(actual[0, 1]))

    def test_both_directions_at_all_fits_and_peaks(self):
        points = np.array([
            [0., 0., 0.], [-90., 0., 0.], [67., 0., 0.], [0., 12., -16.],
            [-72., 42., 73.], [110., -36., 40.], [5000., 1200., -3300.],
            [-1.e-100, 0., 0.], [0., 1.e-100, -2.e-100], [1.e-9, -4.e-11, 1.e-12],
        ]).reshape(2, 5, 3)
        settings = UnifiedChromaSettings(
            input_nits=(2.4, 42., 225., 1600.), black_compression_nits=1.7,
            muted_gain=-2., vivid_gain=2., saturation_crossover=.22,
            shadow_chroma=1.5, highlight_chroma=-1.3, tone_crossover=35.,
        )
        for peak in (500, 1000, 2000, 4000):
            for fit in range(-2, 3):
                with self.subTest(peak=peak, fit=fit):
                    stage = UnifiedChroma(replace(settings, peak_nits=peak, fit=fit))
                    forward = stage.forward(points)
                    np.testing.assert_array_equal(np.sign(forward), np.sign(points))
                    self.assertFalse(np.array_equal(forward, points))
                    np.testing.assert_allclose(stage.inverse(forward), points, atol=0., rtol=2.e-12)
                    np.testing.assert_allclose(stage.forward(stage.inverse(points)), points,
                                               atol=0., rtol=2.e-12)

    def test_black_compression_keeps_distinct_dark_inputs_and_target_peak(self):
        settings = UnifiedChromaSettings(
            input_nits=(50., 20., 15., 1500.), black_compression_nits=2., peak_nits=4000,
        )
        neutral = Tone(ToneSettings())
        source, target = 100. * neutral.nits_to_j([1500., 4000.])
        j = np.r_[-source, -np.geomspace(2., 1.e-10, 15), 0.,
                  np.geomspace(1.e-10, 2., 15), source]
        points = np.stack((j, np.zeros_like(j), np.zeros_like(j)), axis=-1)
        stage = UnifiedChroma(settings)
        actual = stage.forward(points)
        self.assertTrue(np.all(np.diff(actual[:, 0]) > 0.))
        np.testing.assert_allclose(actual[[0, -1], 0], [-target, target], rtol=2.e-14)
        np.testing.assert_array_equal(actual[:, 1:], 0.)
        np.testing.assert_allclose(stage.inverse(actual), points, atol=0., rtol=2.e-12)

    def test_chroma_crossover_and_tonal_gain_use_incoming_lightness(self):
        p, tone_crossover, muted, vivid = .32, 45., -1., 1.7
        settings = UnifiedChromaSettings(
            muted_gain=muted, vivid_gain=vivid, saturation_crossover=p,
            shadow_chroma=-2., highlight_chroma=2., tone_crossover=tone_crossover,
        )
        a = (35. / 75.) * tone_crossover * p / (1. - p)
        points = np.array([[tone_crossover, a, 0.], [-tone_crossover, a, 0.], [0., 1., 0.]])
        mapped = UnifiedChroma(settings).forward(points)
        expected = [a * 2. ** ((muted + vivid) / 2.), a * 2. ** ((muted + vivid) / 2.),
                    2. ** (vivid - 2.)]
        np.testing.assert_allclose(mapped[:, 1], expected, rtol=1.e-14)
        np.testing.assert_array_equal(mapped[:, 0], points[:, 0])
