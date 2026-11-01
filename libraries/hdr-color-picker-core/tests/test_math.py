"""Current picker invariants and independent references for its ACES transform."""
from dataclasses import FrozenInstanceError
import json
from pathlib import Path
import unittest

import numpy as np

from color_tools import hdr_color_picker_core as model
from color_tools.color_core import aces2


class PickerMathTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.archived = json.loads(
            (Path(__file__).parent / "fixtures/legacy_rust.json").read_text())

    def test_archived_aces2_forward_vectors_remain_independent_references(self):
        rows = np.asarray(self.archived["forward_rows"], dtype=float)
        np.testing.assert_allclose(
            aces2.forward_to_xyz_d65(rows[:, :3]), rows[:, 3:6], rtol=1e-12, atol=1e-12)

    def test_d65_neutral_center_and_immutable_pick(self):
        code = (model.REFERENCE_WHITE_J, 0.5, 0.5)
        xyz = model.code_to_xyz(code)
        np.testing.assert_allclose(
            xyz, (0.9504559270516724, 1.0, 1.0890577507598789), rtol=0, atol=2e-12)
        pick = model.evaluate(*code)
        self.assertTrue(pick.valid)
        np.testing.assert_allclose(pick.rec2020, (1.0, 1.0, 1.0), rtol=0, atol=2e-12)
        with self.assertRaises(FrozenInstanceError):
            pick.valid = False

    def test_radial_mapping_is_finite_monotonic_and_invertible(self):
        saturation = np.array((0.0, 0.01, 0.1, 1.0, 10.0, 50.0, 100.0))
        radius = model._radius_from_saturation(
            saturation, model.RADIUS_K, model.RADIUS_CUBIC)
        self.assertTrue(np.all(np.isfinite(radius)))
        self.assertEqual(radius[0], 0.0)
        self.assertTrue(np.all(np.diff(radius) > 0.0))
        self.assertTrue(np.all((radius >= 0.0) & (radius < 1.0)))
        restored = model._saturation_from_radius(
            radius, model.RADIUS_K, model.RADIUS_CUBIC)
        np.testing.assert_allclose(restored, saturation, rtol=2e-12, atol=2e-12)

    def test_radius_is_independent_of_lightness(self):
        codes = np.array([
            (j, 0.2, 0.76) for j in (0.12, 0.30, 0.55, 0.82)
        ])
        xyz = model.code_to_xyz(codes)
        jhk, saturation, hue, _ = model._xyz_to_jsh(xyz)
        self.assertTrue(np.all(np.diff(jhk) > 0.0))
        np.testing.assert_allclose(saturation, saturation[0], rtol=2e-10, atol=2e-10)
        np.testing.assert_allclose(hue, hue[0], rtol=0, atol=2e-12)

    def test_c2_center_behavior_and_exact_edge_rejection(self):
        h = 1e-3
        radius = model._radius_from_saturation(
            np.array((0.0, h, 2.0 * h)), model.RADIUS_K, model.RADIUS_CUBIC)
        second_difference = (radius[2] - 2.0 * radius[1] + radius[0]) / (h * h)
        self.assertLess(abs(second_difference), 2e-3)
        self.assertTrue(np.isnan(model.code_to_xyz((0.5, 1.0, 0.5))).all())

    def test_coordinate_round_trip(self):
        codes = np.array([
            (0.08, 0.5, 0.5),
            (model.REFERENCE_WHITE_J, 0.5, 0.5),
            (0.32, 0.22, 0.78),
            (0.76, 0.74, 0.28),
        ])
        xyz = model.code_to_xyz(codes)
        restored, valid = model.xyz_to_code(xyz)
        self.assertTrue(valid.all())
        np.testing.assert_allclose(restored, codes, rtol=2e-9, atol=2e-9)

    def test_slice_orientation_validity_and_scalar_agreement(self):
        rgba = model.render_slice(0.5, 33, 17)
        self.assertEqual(rgba.dtype, np.dtype("f4"))
        self.assertTrue(np.isfinite(rgba).all())
        for y in range(17):
            for x in range(33):
                pick = model.evaluate(0.5, x / 32, 1 - y / 16)
                self.assertEqual(bool(rgba[y, x, 3]), pick.valid)
                np.testing.assert_allclose(
                    rgba[y, x, :3], pick.acescg if pick.valid else (0, 0, 0),
                    rtol=6e-8, atol=1e-8)

    def test_invalid_dimensions_and_nonfinite_controls(self):
        for dimensions in ((0, 4), (4, 0), (-1, 4), (4097, 4097)):
            with self.assertRaises(ValueError):
                model.render_slice(0.5, *dimensions)
        for code in ((np.nan, 0.5, 0.5), (0.5, np.inf, 0.5), (1.1, 0.5, 0.5)):
            self.assertFalse(model.evaluate(*code).valid)
        self.assertFalse(model.render_slice(np.nan, 4, 4).any())


if __name__ == "__main__":
    unittest.main()
