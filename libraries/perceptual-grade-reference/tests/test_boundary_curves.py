"""Independent derivative and high-precision roots for C2 boundary joins."""
from decimal import Decimal, localcontext
import unittest
import numpy as np
from color_tools.perceptual_grade_reference.boundary_curves import PATCH, rounded_weights, rounded_linear, depressed_root


class BoundaryCurvesTests(unittest.TestCase):
    def test_convex_periodic_weights_and_wrap_derivatives(self):
        axis = np.array([0., 30., 100., 190., 300.])
        x = np.linspace(-370., 730., 10001)
        ids, weights = rounded_weights(axis, x, 360.)
        self.assertTrue((weights >= -2e-16).all())
        np.testing.assert_allclose(weights.sum(axis=-1), 1., atol=3e-16)
        values = np.array([1., 4., 7., 2., 5.])
        for order in range(3):
            i, w = rounded_weights(axis, np.array([-1e-9, 1e-9]), 360., order)
            v = np.sum(values[i]*w, axis=-1)
            self.assertLess(abs(v[0]-v[1]), 1e-8)
        self.assertEqual(ids.shape, (len(x), 3))

    def test_depressed_cubic_against_decimal_bracketing(self):
        with localcontext() as ctx:
            ctx.prec = 90
            D = Decimal.from_float
            for a in (1e-20, 1., 1e20):
                for ratio in (-1/6, -1e-15, 0., 1e-15, 1., 1e10):
                    b = ratio*a
                    for target in (1e-100, 1e-12, .001, .4, 1.):
                        v = a*target+b*target**3
                        aa, bb, vv = map(D, (a, b, v))
                        lo, hi = Decimal(0), D(max(1., 2*target))
                        for _ in range(700):
                            t = (lo+hi)/2
                            if aa*t+bb*t*t*t < vv:lo = t
                            else:hi = t
                        expected = float((lo+hi)/2)
                        actual = float(depressed_root(a, b, v))
                        self.assertLess(abs(actual/expected-1), 6e-15)

