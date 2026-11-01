import unittest

import numpy as np

from color_tools.perceptual_grade_next_core.model import (
    CHROMA_CROSSOVER,
    GradeModel,
    StackModel,
    ToneMap,
    drivers,
    rgb_matrix,
    source_white,
    xyz_matrix,
)
from color_tools.perceptual_grade_next_core.model.linear import CAT16
from color_tools.perceptual_grade_next_core.settings import (
    ColorSettings,
    Direction,
    GradeSettings,
    LinearSettings,
    StackEntry,
    StackSettings,
    ToneSettings,
)


class SettingsTests(unittest.TestCase):
    def test_current_fit_domains_and_fixed_context(self):
        self.assertEqual(ToneSettings(fit=-2.0).fit, -2.0)
        self.assertEqual(ToneSettings(fit=2.0).fit, 2.0)
        self.assertEqual(ColorSettings(lightness_fit=-2.0, chroma_fit=6.0).chroma_fit, 6.0)
        with self.assertRaises(ValueError):
            ToneSettings(fit=2.0001)
        with self.assertRaises(ValueError):
            ColorSettings(lightness_fit=-2.0001)
        with self.assertRaises(ValueError):
            GradeSettings(grading_white="D60")
        with self.assertRaises(ValueError):
            ToneSettings(reference_nits=200.0)

    def test_stack_entries_preserve_order_and_direction(self):
        forward = StackEntry(direction="FORWARD")
        inverse = StackEntry(direction=Direction.INVERSE)
        stack = StackSettings((forward, inverse))
        self.assertEqual(stack.entries, (forward, inverse))
        self.assertEqual(stack.entries[1].direction, Direction.INVERSE)
        with self.assertRaises(ValueError):
            StackEntry(direction="SIDEWAYS")


class DriverTests(unittest.TestCase):
    def test_current_reference_crossover_and_signed_symmetry(self):
        ja = 75.0
        chroma = CHROMA_CROSSOVER * abs(ja)
        positive = drivers((20.0, chroma, 0.0), ja)
        negative = drivers((20.0, chroma, 0.0), -ja)
        self.assertAlmostEqual(positive[0], positive[1], places=15)
        np.testing.assert_array_equal(positive, negative)

    def test_neutral_and_zero_lightness_limits(self):
        np.testing.assert_array_equal(drivers((20.0, 0.0, 0.0), 50.0), np.zeros(4))
        q = (20.0, 3.0, 4.0)
        value = drivers(q, 0.0)
        self.assertEqual(value[0], 0.0)
        self.assertGreater(value[1], 0.0)
        self.assertAlmostEqual(value[2], 3.0 / np.hypot(5.0, 2.0))
        self.assertAlmostEqual(value[3], 4.0 / np.hypot(5.0, 2.0))

    def test_batched_driver_shape(self):
        q = np.array(((20.0, 2.0, 0.0), (30.0, 0.0, 5.0)))
        actual = drivers(q, np.array((10.0, -20.0)))
        self.assertEqual(actual.shape, (2, 4))
        self.assertTrue(np.isfinite(actual).all())


class LinearTests(unittest.TestCase):
    def test_neutral_linear_settings_are_identity_in_each_space(self):
        neutral = LinearSettings()
        for space in ("Linear Rec.709", "Linear Rec.2020", "ACEScg"):
            np.testing.assert_allclose(rgb_matrix(neutral, space), np.eye(3), atol=2e-15)

    def test_exposure_and_source_white_matrix_are_finite(self):
        exposure = rgb_matrix(LinearSettings(exposure=1.0), "Linear Rec.2020")
        np.testing.assert_allclose(exposure, 2.0 * np.eye(3), atol=4e-15)
        point = source_white((0.0, 0.0))
        self.assertTrue(np.isfinite(point).all())
        self.assertTrue(np.all(CAT16 @ np.asarray((point[0] / point[1], 1.0,
                                                    (1.0 - sum(point)) / point[1])) > 0.0))

    def test_authoritative_xyz_matrix_is_preserved(self):
        matrix = ((1.0, 0.1, 0.0), (0.0, 0.9, 0.0), (0.0, 0.0, 1.1))
        np.testing.assert_array_equal(xyz_matrix(LinearSettings(matrix=matrix)), matrix)


class ToneTests(unittest.TestCase):
    def test_supported_fit_changes_width_and_limits_match(self):
        narrow = ToneMap(ToneSettings(fit=-2.0))
        wide = ToneMap(ToneSettings(fit=2.0))
        self.assertEqual(narrow.width, 0.2)
        self.assertEqual(wide.width, 0.0125)

    def test_active_map_is_monotone_and_inverse_reports_matching_residual(self):
        settings = ToneSettings(input_nits=(0.0, 1.0, 50.0, 203.0, 1000.0), fit=0.7)
        tone = ToneMap(settings)
        source = np.linspace(0.0, 500.0, 201)
        mapped = tone.remap(source)
        reproduced = tone.remap(tone.inverse(mapped))
        self.assertTrue(np.all(np.diff(mapped) >= 0.0))
        np.testing.assert_allclose(reproduced, mapped, atol=2e-9, rtol=2e-12)


class GradeStackTests(unittest.TestCase):
    def test_grade_identity_is_finite_and_keeps_shape(self):
        model = GradeModel()
        values = np.asarray(((0.0, 0.0, 0.0), (0.18, 0.18, 0.18),
                             (1.0, 0.2, 0.05)))
        output = model.apply_rgb(values)
        self.assertEqual(output.shape, values.shape)
        self.assertTrue(np.isfinite(output).all())

    def test_appearance_decoder_roundtrips_interior_ap1_values(self):
        model = GradeModel()
        values = np.asarray(((0.0, 0.0, 0.0), (0.18, 0.18, 0.18),
                             (0.8, 0.25, 0.08), (0.02, 0.12, 0.4)))
        appearance = model.enter_ap1(values)
        decoded = model.boundary.decode(appearance.q, appearance.energy)
        np.testing.assert_allclose(decoded, values, rtol=4e-10, atol=4e-10)

    def test_empty_stack_is_a_value_preserving_boundary_operation(self):
        stack = StackModel()
        values = np.asarray(((0.0, 0.0, 0.0), (0.18, 0.18, 0.18)))
        np.testing.assert_allclose(stack.apply_rgb(values), values, atol=2e-14, rtol=2e-14)
        input_matrix, output_matrix = stack.lut_endpoint_matrices
        np.testing.assert_array_equal(input_matrix, np.eye(3))
        np.testing.assert_array_equal(output_matrix, np.eye(3))


if __name__ == "__main__":
    unittest.main()
