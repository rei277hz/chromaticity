"""Independent inverse accuracy, canonical choice and deterministic search contracts."""
from dataclasses import replace
import unittest
import numpy as np
from color_tools.perceptual_grade_core.model.tonal_web import WebSettings
from color_tools.perceptual_grade_reference.model import Model, Settings, LinearSettings
from color_tools.perceptual_grade_reference.grading import ToneSettings
from color_tools.perceptual_grade_reference.grading import ColorSettings
from color_tools.perceptual_grade_reference.inverse import choose, TOLERANCE, linear_prior
from color_tools.color_core.scaled import Scalar as S
from color_tools.perceptual_grade_reference.appearance import decode
from color_tools.perceptual_grade_reference.responses import HK, hk_energy


class InverseTests(unittest.TestCase):
    def test_reset_linear_singular_and_invalid_targets(self):
        model = Model(Settings(linear=LinearSettings(exposure=1.)))
        x = np.array([[0., 0., 0.], [.2, .3, .4], [-.1, .4, 2.]])
        result = model.inverse(model.forward(x))
        self.assertTrue((result.status == 'root').all())
        np.testing.assert_allclose(model.forward(result.value),model.forward(x),rtol=2e-8,atol=5e-10)
        singular = Model(Settings(linear=LinearSettings(matrix=((1, 0, 0), (0, 0, 0), (0, 0, 0)))))
        reachable = singular.forward_xyz([.2, 0, 0])
        result = singular.inverse_xyz([reachable, [.2, .3, .4], [np.nan, 0, 0]])
        np.testing.assert_array_equal(result.status, ['root', 'approximate', 'invalid'])
        self.assertTrue(np.isfinite(result.value[:2]).all())
        np.testing.assert_allclose(singular.forward_xyz(result.value[0]), reachable, rtol=2e-8, atol=5e-10)
        self.assertEqual(model.inverse(np.empty((0, 3))).value.shape, (0, 3))

    def test_nearest_linear_selection_and_ties(self):
        roots = np.array([[1., 2., 3.], [3., 2., 1.]])
        value, error, status = choose(roots, [TOLERANCE/2, TOLERANCE/3], [2.7, 2., 1.])
        np.testing.assert_array_equal(value, roots[1])
        self.assertEqual(status, 'root')
        self.assertLess(error, TOLERANCE)
        value, _, _ = choose(roots[::-1], [0., 0.], [2., 2., 2.])
        np.testing.assert_array_equal(value, roots[0])
        value, _, status = choose(roots, [1e-3, 2e-3], [2.7, 2., 1.])
        np.testing.assert_array_equal(value, roots[0])
        self.assertEqual(status, 'approximate')

    def test_complete_inverse_and_batch_order(self):
        settings = Settings(linear=LinearSettings(exposure=.3, balance=(.05, -.02)),
                            tone=ToneSettings(input_nits=(0., 8., 40., 235., 1150.)),
                            color=ColorSettings(global_gain=.15, web=WebSettings(
                                hue_degrees=((2.,0.,-1.,0.,1.,0.),(3.,-2.,1.,0.,0.,1.),
                                             (0.,1.,0.,-2.,0.,1.),(-1.,0.,2.,0.,-1.,0.)),
                                log_chroma=((.03,-.02,0.,0.,.01,0.),)*4)))
        model = Model(settings)
        x = np.array([[.2, .3, .4], [.7, .1, .2], [-.01, .2, .5], [0., 0., 0.]])
        y = model.forward(x)
        result = model.inverse(y)
        self.assertTrue((result.status == 'root').all(), result)
        self.assertLess(result.residual.max(), TOLERANCE)
        np.testing.assert_allclose(model.forward(result.value), y, rtol=2e-8, atol=5e-10)
        reversed_result = model.inverse(y[::-1])
        np.testing.assert_array_equal(result.value, reversed_result.value[::-1])
        np.testing.assert_array_equal(result.status, reversed_result.status[::-1])

    def test_black_plateau_canonical_zero(self):
        model = Model(Settings(tone=replace(ToneSettings(), input_nits=(1., 8., 40., 235., 1150.))))
        result = model.inverse([[0., 0., 0.]])
        self.assertEqual(result.status[0], 'root')
        np.testing.assert_array_equal(result.value, 0)

    def test_negative_neutral_inverse_selects_canonical_black(self):
        settings = Settings(tone=ToneSettings(input_nits=(0., 8., 40., 235., 1150.)),
                            color=ColorSettings(web=WebSettings(hue_degrees=((10.,)*6,)*4), global_gain=.1))
        x = np.array([[-.1, -.1, -.1], [-.3, -.3, -.3]])
        for exposure in (0., .3):
            model = Model(replace(settings, linear=LinearSettings(exposure=exposure)))
            y = model.forward(x)
            np.testing.assert_array_equal(y, 0.)
            result = model.inverse(y)
            self.assertTrue((result.status == 'root').all(), result)
            np.testing.assert_array_equal(result.value, 0.)
            np.testing.assert_array_equal(model.forward(result.value), y)

    def test_negative_a_export_inverse_reports_the_complete_forward_residual(self):
        model = Model();q = np.array([.7*np.sqrt(66*20.), 20., 0.])
        source = decode(q, hk_energy(q[0], 20.), model.white)
        target = model.forward_xyz(source)
        self.assertTrue((target@model.xyz_to_rgb.T@model.to_acescg.T>=-1e-14).all())
        result = model.inverse_xyz(target)
        reproduced = model.forward_xyz(result.value)
        expected = np.max(np.abs((reproduced-target)@model.xyz_to_canonical.T))/(1+
                              np.max(np.abs(target@model.xyz_to_canonical.T)))
        self.assertAlmostEqual(float(result.residual),float(expected),places=13)
        self.assertEqual(result.status,'root' if expected<=TOLERANCE else 'approximate')
        self.assertTrue(np.isfinite(result.value).all())
        # The known signed source establishes reachability; this fixed search
        # does not establish global convergence, especially near the gamut knee.

    def test_unreachable_negative_neutral_never_reports_a_root(self):
        model = Model()
        target = np.array([-model.white*.1, -model.white])
        result = model.inverse_xyz(target)
        np.testing.assert_array_equal(result.status, ['approximate', 'approximate'])
        reproduced = model.forward_xyz(result.value)
        expected = np.max(np.abs((reproduced-target) @ model.xyz_to_canonical.T), axis=-1)/(1+
                       np.max(np.abs(target @ model.xyz_to_canonical.T), axis=-1))
        np.testing.assert_allclose(result.residual, expected, rtol=2e-13, atol=2e-15)
        self.assertTrue((result.residual > TOLERANCE).all())

    def test_folded_raw_grade_reproduces_both_known_preimages(self):
        model=Model(Settings(color=ColorSettings(chroma=((0.,-16.,0.,0.),)*4)))
        def fold(c):
            ja2=10000-HK*c
            radius=(35/75)*np.sqrt(ja2)
            high=c*c/(c*c+radius*radius)*c*c/(c*c+4)
            return c*2**(-16*high)
        target_chroma=3.5
        roots=[]
        for lo,hi,ascending in ((1.,6.,True),(15.,30.,False)):
            self.assertLess((fold(lo)-target_chroma)*(fold(hi)-target_chroma),0.)
            self.assertEqual(fold(lo)<fold(hi),ascending)
            for _ in range(64):
                middle=(lo+hi)/2
                if (fold(middle)<target_chroma)==ascending:lo=middle
                else:hi=middle
            roots.append((lo+hi)/2)
        self.assertGreater(roots[1]-roots[0],1.)
        np.testing.assert_allclose([fold(c) for c in roots],target_chroma,rtol=2e-15)
        chroma=np.array(roots);energy=10000-HK*chroma
        q=np.column_stack((np.full(2,100.),chroma,np.zeros(2)))
        self.assertTrue((chroma<model.boundary.capacity(np.sqrt(energy),0.)).all())
        # Independent raw roots are decoded directly, without a radial mapping.
        native=model.boundary.decode(q,energy)
        source=native@np.linalg.inv(model.native_matrix).T@model.cones_to_xyz.T
        target=model.forward_xyz(source)
        np.testing.assert_allclose(target[0],target[1],rtol=2e-12,atol=2e-13)
        found=model.inverse_xyz(target[:1])
        self.assertEqual(found.status[0],'root')
        np.testing.assert_allclose(model.forward_xyz(found.value),target[:1],rtol=2e-8,atol=5e-10)

    def test_high_exposure_inverse_uses_complete_forward_residual(self):
        model = Model(Settings(linear=LinearSettings(exposure=8.)))
        target = model.forward([[1000./2.**8]*3])
        prior = target/2.**8
        mismatch = np.max(np.abs(model.forward(prior)-target))/np.max(np.abs(target))
        self.assertTrue(np.isfinite(mismatch))
        result = model.inverse(target)
        self.assertEqual(result.status[0], 'root')
        self.assertLess(result.residual[0], TOLERANCE)
        np.testing.assert_allclose(model.forward(result.value), target, rtol=3e-10)

    def test_scaled_linear_prior_and_distance_ranking(self):
        model = Model(Settings(linear=LinearSettings(exposure=-np.finfo(float).max)))
        prior = linear_prior(model, model.white)
        self.assertTrue(all(isinstance(v, S) and v > S(np.finfo(float).max) for v in prior))
        roots = [[0., 0., 0.], [1., 1., 1.]]
        value, _, status = choose(roots, [0., 0.], prior)
        np.testing.assert_array_equal(value, roots[1])
        self.assertEqual(status, 'root')
