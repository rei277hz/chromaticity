"""Stage 1 control/matrix parity against independently constructed Colour math."""
from dataclasses import replace
import unittest
import numpy as np
from color_tools.perceptual_grade_core.model import linear
from tests.support import reference as oracle


class LinearTests(unittest.TestCase):
    def test_controls_and_property_precision_d65(self):
        rng=np.random.default_rng(572)
        for space in ['Linear Rec.709','Linear Rec.2020',linear.GradeSpace('D65')]:
            p=linear.neutral_parameters(space)
            values=[p,replace(p,source_x=float(np.float32(p.source_x)),source_y=float(np.float32(p.source_y)))]
            values += [replace(p,**{name:value}) for name in linear.PARAM_NAMES for value in linear.LIMITS[name]]
            values += [replace(p,exposure=.7,cr_balance=.1,yb_heading=-5,cr_spread=20)]
            values += [linear.Parameters(**{name:float(rng.uniform(*linear.LIMITS[name])) for name in linear.PARAM_NAMES}) for _ in range(8)]
            for p in values:
                with self.subTest(space=space,params=p):
                    expected=oracle.matrix(p,space)
                    actual=np.asarray(linear.matrices(p,space)['xyz'])
                    self.assertLess(float(oracle.error(actual,expected).max()),3e-12)

    def test_source_white_projection_and_invalid_values(self):
        points=np.array([[.8,-.1],[0,0],[.9,.9],[.3127,.329],[.1,.5]])
        expected=np.array([oracle.model.source_white(point) for point in points])
        np.testing.assert_allclose([linear.safe_source_white(p) for p in points],expected,atol=2e-14,rtol=0)
        with self.assertRaises(ValueError):linear.safe_source_white((float('nan'),.3))
        with self.assertRaisesRegex(ValueError,'positive finite'):
            linear.adaptation(linear.D65,(.9,.01))
