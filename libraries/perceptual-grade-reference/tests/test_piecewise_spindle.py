"""Independent high-precision anchors and C2/closed-form radial contracts."""
from decimal import Decimal, localcontext
import unittest
import numpy as np
from color_tools.perceptual_grade_reference.piecewise_spindle import (
    JOIN, release_radius, compress_radius, release_derivatives,
)


def decimal_release(x, k, lift):
    """Build the shoulder from its join/end constraints, not simplified H."""
    x, k, lift = map(Decimal.from_float, (float(x), float(k), float(lift)))
    s = Decimal(3)/4
    a = lift*(k-1)/(k*s*s)
    if x <= s:
        return float(x+a*x**3)
    width = 1-s
    start, slope, q = s+a*s**3, 1+3*a*s*s, 3*a*s
    surplus = k-start-slope*width
    h = (surplus*(1+14*width+196*width*width)-q*width*width)/width**3
    t = x-s
    return float(start+slope*t+(q*t*t+h*t**3)/(1+14*t+196*t*t))


class PiecewiseSpindleTests(unittest.TestCase):
    def test_physical_decimal_anchors_and_roundtrips(self):
        x = np.unique(np.r_[0., np.geomspace(1e-300, .01, 60), np.linspace(0, 1, 601),
                            np.nextafter(JOIN, 0), JOIN, np.nextafter(JOIN, 1),
                            np.nextafter(1., 0)])
        with localcontext() as context:
            context.prec = 90
            for lift in (.05, .1, .25):
                for k in (1., np.nextafter(1., 2.), 1.0015993, 2., 17.209697, 1e3, 1e8):
                    with self.subTest(lift=lift, k=k):
                        y = release_radius(x, k, lift)
                        expected = [decimal_release(v, k, lift) for v in x]
                        np.testing.assert_allclose(y, expected, rtol=9e-16, atol=1e-16)
                        np.testing.assert_allclose(compress_radius(y, k, lift), x, rtol=5e-15, atol=0.)
                        self.assertTrue(np.all(np.diff(y) >= 0))
                        self.assertEqual(float(release_radius(1., k, lift)), k)
                        self.assertEqual(float(compress_radius(k, k, lift)), 1.)

    def test_joins_match_value_slope_and_curvature(self):
        # Extrapolate one-sided values/derivatives to each join; resolve the
        # narrowest pole gap so exterior third-order error cannot hide a jump.
        for lift in (.05, .1, .25):
            for k in (1.0015993, 2., 17.209697):
                for pole in (1.001, 1.01, 1.025, 1.05):
                    for join in (JOIN, 1.):
                        step = min(1e-6, (pole-1)/1000)
                        at = np.r_[release_radius(join, k, lift, pole), release_derivatives(join, k, lift, pole)]
                        for sign in (-1, 1):
                            near = join+sign*step*np.array([1., 2., 3.])
                            first, second = release_derivatives(near, k, lift, pole)
                            values = np.stack((release_radius(near, k, lift, pole), first, second))
                            extrapolated = values @ np.array([3., -3., 1.])
                            np.testing.assert_allclose(extrapolated, at, rtol=3e-7, atol=2e-8)

    def test_analytic_derivatives_against_differences(self):
        for lift in (.05, .1, .25):
            x = np.r_[np.linspace(.04, .7, 16), np.linspace(.77, .98, 16), 1.002, 1.005]
            d1, d2 = release_derivatives(x, 5., lift, 1.01)
            step = 2e-6
            finite_first = (release_radius(x+step, 5., lift)-release_radius(x-step, 5., lift))/(2*step)
            finite_second = (release_derivatives(x+step, 5., lift)[0]-release_derivatives(x-step, 5., lift)[0])/(2*step)
            np.testing.assert_allclose(finite_first, d1, rtol=2e-6, atol=1e-8)
            np.testing.assert_allclose(finite_second, d2, rtol=2e-6, atol=1e-8)

    def test_convex_global_action_and_pole_independence(self):
        x = np.linspace(0, 1, 3001)[:, None]
        k = np.array([np.nextafter(1., 2.), 1.0015993, 2., 17.209697, 1e6])
        for lift in (.05, .1, .25):
            slope, curve = release_derivatives(x, k, lift)
            self.assertTrue(np.all(slope >= 1))
            self.assertTrue(np.all(curve >= 0))
            self.assertTrue(np.all(release_radius(x, k, lift) >= x))
            self.assertTrue(np.all(release_radius(x[1:], k[2:], lift) > x[1:]))
            for pole in (1.001, 1.025, 1.05):
                np.testing.assert_array_equal(release_radius(x, k, lift, pole), release_radius(x, k, lift))
                np.testing.assert_array_equal(compress_radius(x*k, k, lift, pole), compress_radius(x*k, k, lift))

    def test_exterior_inverse_and_pole_limit(self):
        for lift in (.05, .1, .25):
            for k in (np.nextafter(1., 2.), 1.0015993, 2., 17.209697, 1e6):
                for pole in (1.001, 1.01, 1.025, 1.05):
                    distance = (pole-1)*np.geomspace(1., 1e-10, 81)
                    x = pole-distance
                    y = release_radius(x, k, lift, pole)
                    np.testing.assert_allclose(compress_radius(y, k, lift, pole), x, rtol=8e-16, atol=1e-15)
                    self.assertTrue(np.all(np.diff(y) >= 0))
                    # Subtract the affine part before measuring the simple-pole
                    # coefficient E*gap^3; this also covers k nearly one.
                    if k > 1.01:
                        gap = pole-1
                        d = gap*np.array([1e-3, 1e-4, 1e-5])
                        x = pole-d
                        m, c = release_derivatives(1., k, lift, pole)
                        coefficient = (release_radius(x, k, lift, pole)-k-m*(x-1))*(pole-x)
                        expected = .5*c*gap**3
                        error = np.abs(coefficient/expected-1)
                        self.assertTrue(np.all(error[1:] < .11*error[:-1]))

    def test_neutral_direction_and_subnormals(self):
        angles = np.linspace(-np.pi, np.pi, 151, endpoint=False)
        k = 1.01 + 16*(1+np.sin(angles))/2
        direction = np.stack((np.cos(angles), np.sin(angles)), axis=-1)
        for mapper in (release_radius, compress_radius):
            previous = None
            for r in (1e-3, 5e-4, 2.5e-4):
                error = np.max(np.linalg.norm((mapper(r, k)-r)[:, None]*direction, axis=-1))/r
                if previous is not None:
                    self.assertLess(error, previous*.26)
                previous = error
            x = np.array([0., np.nextafter(0., 1.), 1e-322, 1e-310])
            np.testing.assert_array_equal(mapper(x, 17.2), x)
        np.testing.assert_array_equal(release_derivatives(0., k)[0], 1.)
        np.testing.assert_array_equal(release_derivatives(0., k)[1], 0.)

    def test_domain_broadcast_and_identity(self):
        x = np.linspace(0, 1, 31)[:, None]
        k = np.array([1., 2., 17.2])
        np.testing.assert_allclose(compress_radius(release_radius(x, k), k), x+np.zeros_like(k), rtol=4e-15, atol=0.)
        arbitrary = np.array([0., .75, 1., 1.1, 100.])
        np.testing.assert_array_equal(release_radius(arbitrary, 1.), arbitrary)
        np.testing.assert_array_equal(compress_radius(arbitrary, 1.), arbitrary)
        for function in (release_radius, compress_radius, release_derivatives):
            for value, ratio in ((-1., 2.), (1., .99), (np.nan, 2.), (1., np.inf), (1., 1e9)):
                with self.assertRaises(ValueError):
                    function(value, ratio)
            for settings in ({'inner_lift': 0}, {'inner_lift': .3}, {'pole': 1.}, {'pole': 1.1}):
                with self.assertRaises(ValueError):
                    function(.5, 2., **settings)
        with self.assertRaises(ValueError):
            release_radius(1.01, 2.)
        self.assertLess(float(compress_radius(np.finfo(float).max, 2.)), 1.01)


if __name__ == '__main__':
    unittest.main()
