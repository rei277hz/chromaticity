"""Actual-decoder cube containment for raw appearance export."""
import unittest
from unittest.mock import patch
import numpy as np

from color_tools.perceptual_grade_reference.model import Model
from color_tools.perceptual_grade_reference.responses import GAMMA, signed_hk
from color_tools.color_core.scaled import Scalar as S
from color_tools.perceptual_grade_reference.cube_guard import guard, guard_scaled


class CubeGuardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.context = Model().boundary

    def ray(self, ja, hue, radius):
        return np.array([signed_hk(ja, radius), radius*np.cos(hue), radius*np.sin(hue)])

    def test_interior_is_unchanged_and_escapes_project_to_legal_rgb(self):
        context = self.context
        heights = np.array([.02, 1., 20., 80., context.white*.75, context.white*.999])
        hues = np.array([0., .4, 1.7, 3.1, 4.8, 6.1])
        radii = context.capacity(heights, hues)
        inside = np.stack([self.ray(j, h, .5*r) for j, h, r in zip(heights, hues, radii)])
        unchanged, energy, rgb = guard(context, inside, heights**2)
        np.testing.assert_array_equal(unchanged, inside)
        np.testing.assert_array_equal(energy, heights**2)
        np.testing.assert_array_equal(rgb, context.decode(inside, energy))

        outside = np.stack([self.ray(j, h, 1.5*r) for j, h, r in zip(heights, hues, radii)])
        projected, projected_energy, tested = guard(context, outside, heights**2)
        self.assertTrue(np.isfinite(tested).all())
        self.assertTrue(np.all((tested >= 0.) & (tested <= 1024.)))
        np.testing.assert_array_equal(projected_energy, heights**2)
        self.assertTrue(np.all(np.hypot(projected[:, 1], projected[:, 2]) <=
                               np.hypot(outside[:, 1], outside[:, 2])))
        np.testing.assert_allclose(np.mod(np.arctan2(projected[:, 2], projected[:, 1]), 2*np.pi), hues % (2*np.pi),
                                   atol=5e-15, rtol=0)
        again, e2, rgb2 = guard(context, projected, projected_energy)
        np.testing.assert_array_equal(again, projected)
        np.testing.assert_array_equal(e2, projected_energy)
        np.testing.assert_array_equal(rgb2, tested)

    def test_fit_is_only_a_seed_and_signed_tips(self):
        context = self.context
        ja = context.white*.61
        hue = 2.3
        radius = context.capacity(ja, hue)
        q = self.ray(ja, hue, radius*5)
        ordinary = guard(context, q, ja*ja)
        with patch.object(type(context), 'capacity', return_value=radius*.1):
            underestimated = guard(context, q, ja*ja)
        with patch.object(type(context), 'capacity', return_value=radius*3):
            overestimated = guard(context, q, ja*ja)
        for result in (underestimated, overestimated):
            self.assertTrue(np.all((result[2] >= 0.) & (result[2] <= 1024.)))
            self.assertLess(abs(np.hypot(*result[0][1:])-np.hypot(*ordinary[0][1:])), 2e-11)

        q = np.array([4., 5., 6.])
        for energy, rgb, j in [(-1., 0., 0.), (0., 0., 0.),
                               (context.white**2*2, 1024., context.white)]:
            got, stored, tested = guard(context, q, energy)
            np.testing.assert_array_equal(got, [j, 0., 0.])
            self.assertEqual(float(stored), j*j)
            np.testing.assert_array_equal(tested, np.full(3, rgb))

    def test_scaled_guard_keeps_tiny_energy_and_actual_containment(self):
        context = self.context
        for ja in (S(1., -300), S(context.white)*.7):
            radius = S(context.capacity(float(ja), 1.2)) if float(ja) else S(1., -300)
            q = [S(signed_hk(float(ja), float(radius))) if ja.e > -100 else ja,
                 radius*S(np.cos(1.2))*4, radius*S(np.sin(1.2))*4]
            projected, energy, tested = guard_scaled(context, q, ja*ja)
            self.assertEqual(energy, ja*ja)
            self.assertTrue(all(S() <= v <= 1024 for v in tested))
            self.assertLessEqual(float((projected[1]*projected[1]+projected[2]*projected[2])**.5),
                                 float((q[1]*q[1]+q[2]*q[2])**.5))


if __name__ == '__main__':
    unittest.main()
