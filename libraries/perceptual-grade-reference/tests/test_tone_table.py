"""Direct scalar inverse tables against independent float64 tone equations."""
import unittest
from unittest.mock import patch
import numpy as np
from color_tools.perceptual_grade_reference.grading import Tone,ToneSettings,normalized_kernel
from color_tools.perceptual_grade_core.model.tone_table import ToneTable,hermite,MAX_CELLS,MAX_BYTES,MAX_ROUNDS,MAX_ROOT_EVALUATIONS


def oracle(tone,h):
    """Independent bisection of the reference equation in normalized t."""
    h=np.asarray(h,dtype=float);low=np.zeros_like(h);high=h/(100*float(tone.slope))
    for _ in range(80):
        middle=(low+high)*.5
        values=np.stack([normalized_kernel(middle,l,r,tone.width)
            for l,r in zip(tone.knots[:-1],tone.knots[1:])],-1)
        value=100*(float(tone.slope)*middle+values@tone.residual)
        below=value<h;low=np.where(below,middle,low);high=np.where(below,high,middle)
    return np.where(h==0,0,(low+high)*.5)


class ToneTableTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        settings=(ToneSettings(input_nits=(0.,7.,45.,203.,1000.)),
            ToneSettings(input_nits=(.01,1.,90.,400.,4000.),fit=-2),
            ToneSettings(input_nits=(0.,.0001,.01,203.,10000.),fit=3),
            ToneSettings(input_nits=(0.,7.,45.,203.,1000.),fit=6))
        cls.cases=[]
        for value in settings:
            tone=Tone(value)
            # Preserve the original explicit accuracy coverage as well as the
            # tuned default; each must meet the precision it requests.
            cls.cases.extend((tone,table) for table in (ToneTable(tone,tolerance=2e-6),ToneTable(tone)))

    def test_preparation_is_bounded_and_runtime_is_direct(self):
        for tone,table in self.cases:
            with self.subTest(fit=tone.settings.fit,tolerance=table.tolerance):
                self.assertLessEqual(table.cells,MAX_CELLS)
                self.assertLessEqual(table.nbytes,MAX_BYTES)
                self.assertLessEqual(table.rounds,MAX_ROUNDS)
                self.assertLessEqual(table.maximum_root_iterations,MAX_ROOT_EVALUATIONS)
                self.assertLess(table.tail_relative_bound,table.tolerance*.25)
                self.assertEqual(table.evaluate(np.float32(0)),0)
                self.assertEqual(table.evaluate(np.zeros((2,3),dtype='f4')).shape,(2,3))
                self.assertTrue(np.isfinite(table.nodes).all())
                self.assertTrue(np.all(np.diff(table.nodes[:,0])>0))
                # The prepared runtime object holds no solver or tone evaluator.
                self.assertFalse(hasattr(table,'curve'))

    def test_near_black_seams_high_tail_and_off_grid_accuracy(self):
        for tone,table in self.cases:
            with self.subTest(fit=tone.settings.fit,tolerance=table.tolerance):
                u=table.nodes[:,0].astype(float)
                interior=u[:-1]+(u[1:]-u[:-1])/3
                seams=(float(table.scale)*np.expm1(u)).astype('f4')
                h=np.unique(np.r_[np.float32(0),np.geomspace(1e-20,1e12,257).astype('f4'),
                    (float(table.scale)*np.expm1(interior)).astype('f4'),seams,
                    np.nextafter(seams,np.float32(np.inf)),
                    np.maximum(0,np.nextafter(seams,np.float32(-np.inf))),
                    table.tail_h,np.nextafter(table.tail_h,np.float32(-np.inf)),
                    np.nextafter(table.tail_h,np.float32(np.inf))])
                actual=table.evaluate(h).astype(float);expected=oracle(tone,h)
                difference=abs(actual-expected)
                limit=np.maximum(table.tolerance*expected,4*float(np.nextafter(np.float32(0),np.float32(1))))
                self.assertTrue(np.all(difference<=limit),(float(np.max(difference/np.maximum(limit,np.finfo(float).tiny))),h[np.argmax(difference/np.maximum(limit,np.finfo(float).tiny))]))
                self.assertTrue(np.all(np.diff(actual)>=0))
                self.assertEqual(actual[0],0)

    def test_quintic_endpoint_jets_and_tail_join(self):
        # Recover the polynomial from six interior samples, independently of
        # the implementation's Hermite factorization. Check derivatives in
        # unit-cell coordinates so tiny cells do not amplify fitting error.
        z=(1-np.cos((np.arange(6)+.5)*np.pi/6))*.5
        for tone,table in self.cases:
            with self.subTest(fit=tone.settings.fit,tolerance=table.tolerance):
                for left,right in zip(table.nodes[:-1].astype(float),table.nodes[1:].astype(float)):
                    width=right[0]-left[0]
                    samples=hermite(left,right,left[0]+width*z)-left[1]
                    polynomial=np.polynomial.Polynomial.fit(z,samples,5,domain=[0.,1.]).convert()
                    scale=max(abs(left[1]),abs(right[1]),abs(width*left[2]),
                        abs(width*right[2]),abs(width*width*left[3]),abs(width*width*right[3]))
                    actual=np.array([polynomial(0),polynomial(1),polynomial.deriv()(0),
                        polynomial.deriv()(1),polynomial.deriv(2)(0),polynomial.deriv(2)(1)])
                    expected=np.array([0,right[1]-left[1],width*left[2],width*right[2],
                        width*width*left[3],width*width*right[3]])
                    np.testing.assert_allclose(actual/scale,expected/scale,rtol=0,atol=2e-11)
                u,q,qu,quu=table.nodes[-1].astype(float)
                h=float(table.scale)*np.expm1(u);factor=h+float(table.scale)
                qh=qu/factor;qhh=(quu-qu)/(factor*factor)
                slope=1/(100*float(table.slope))
                # The polynomial cells share exact stored jets. Their join to
                # the analytic tail has float32 coefficient quantization;
                # this checks value, slope and curvature in relative units.
                jets=np.array([q,q+h*qh,2*h*qh+h*h*qhh])/slope
                expected=np.array([1-100*float(table.intercept)/h,1.,0.])
                np.testing.assert_allclose(jets,expected,rtol=0,atol=8*np.finfo('f4').eps)
                self.assertGreaterEqual(float(table.tail_h),h)
                self.assertLess(float(np.nextafter(table.tail_h,np.float32(-np.inf))),h)
                # Every polynomial evaluation remains strictly below the
                # upper node. This excludes a constant-q clamped strip at
                # the join when log-address and height rounding disagree.
                near=[table.tail_h]
                for _ in range(8):near.append(np.nextafter(near[-1],np.float32(-np.inf)))
                near=np.asarray(near,dtype='f4')
                def checked_hermite(left,right,coordinate):
                    self.assertTrue(np.all(coordinate<table.nodes[-1,0]))
                    return hermite(left,right,coordinate)
                with patch('color_tools.perceptual_grade_core.model.tone_table.hermite',side_effect=checked_hermite):
                    actual=table.evaluate(near)
                expected=oracle(tone,near)
                self.assertTrue(np.all(abs(actual-expected)<=2e-6*expected))

    def test_rejects_invalid_scalar_inputs(self):
        table=self.cases[0][1]
        for values in ([-1.],[np.inf],[np.nan]):
            with self.assertRaises(ValueError):table.evaluate(values)
