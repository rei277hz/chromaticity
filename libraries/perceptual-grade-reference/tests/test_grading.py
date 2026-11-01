"""Analytic anchors, boundary checks and executable custom-math properties."""
from dataclasses import replace
from decimal import Decimal, localcontext
import unittest
from unittest.mock import Mock
import numpy as np
from color_tools.perceptual_grade_core.model.tonal_web import WebSettings
from color_tools.perceptual_grade_reference.appearance import Appearance
from color_tools.perceptual_grade_reference.grading import Tone, ToneSettings, kernel, coefficient_weights, drivers
from color_tools.perceptual_grade_reference.grading import Color, ColorSettings
from color_tools.perceptual_grade_reference.responses import signed_hk, hk_energy, requested_energy
from color_tools.perceptual_grade_core.model.selective_adaptance import reach_weight
from color_tools.color_core.scaled import Scalar as S, signed_power


class GradingTests(unittest.TestCase):
    def test_kernel_against_independent_decimal_antiderivative(self):
        with localcontext() as ctx:
            ctx.prec = 70
            for t, l, r, w in [(1e-12, 0., .1, .05), (.7, .2, .200000000001, .05),
                                (.99, .01, .98, .00078125), (-.2, .01, .1, .05)]:
                td, ld, rd, wd = map(lambda x: Decimal(str(x)), (t, l, r, w))
                def phi(x):
                    return wd*(1+(x/wd).exp()).ln()
                expected = float(phi(td-ld)-phi(-ld)-phi(td-rd)+phi(-rd))
                # Decimal(str) represents the supplied decimal case; the float
                # interval's width can differ in its last representable bits.
                if r-l < 1e-10:
                    expected *= (r-l)/float(rd-ld)
                self.assertAlmostEqual(float(kernel(t, l, r, w))/expected, 1, places=11)

    def test_tone_monotonicity_plateau_endpoints_and_inverse(self):
        for fit in (-2, 0, 6):
            tone = Tone(ToneSettings(input_nits=(.2, .21, 42, 250, 1300), fit=fit))
            h = np.linspace(100*tone.black+1e-5, 4*tone.high, 1001)
            out = tone.remap(h)
            self.assertTrue(np.all(np.diff(out) > 0))
            np.testing.assert_array_equal(tone.remap([0., 100*tone.black]), 0)
            self.assertEqual(tone.remap(100*(tone.black+tone.span)), tone.high)
            np.testing.assert_allclose(tone.remap(tone.inverse(out[::100])), out[::100], rtol=2e-13, atol=2e-12)
            q = np.array([[100., 20., 0.], [80., 0., 10.]])
            j = np.sqrt(q[:, 0]**2-66*np.hypot(q[:, 1], q[:, 2]))
            stage2 = tone.apply(Appearance(q, j))
            np.testing.assert_allclose(np.linalg.norm(stage2.q[:, 1:], axis=-1)/stage2.ja,
                                       np.linalg.norm(q[:, 1:], axis=-1)/j, rtol=2e-15)
            for adapt in (False, True):
                weights = coefficient_weights(h, tone.coefficient_knots, tone.high, fit, adapt)
                self.assertTrue((weights >= 0).all())
                self.assertTrue((weights.sum(axis=-1) <= 1+5e-16).all())
                if not adapt:
                    np.testing.assert_allclose(weights.sum(axis=-1), 1, atol=5e-16)

    def test_driver_and_adaptance_anchors(self):
        q = np.array([[100., 35., 0.], [0., 0., 0.], [50., 0., 0.]])
        actual = drivers(q, np.array([75., 0., 50.]))
        np.testing.assert_allclose(actual[0, :2], np.full(2, .5*35.**2/(35.**2+4)), rtol=1e-15)
        np.testing.assert_array_equal(actual[1:], 0)
        self.assertEqual(float(reach_weight(12.5, 50.**2, .25)), .5)
        np.testing.assert_array_equal(reach_weight([0., 0.], [0., 2500.], 0.), 1.)
        a = drivers(q[:1], np.array([75.]))[0, :2]
        b = drivers(q[:1]*3, np.array([225.]))[0, :2]
        self.assertAlmostEqual(a[1]/a.sum(), b[1]/b.sum(), places=15)

    def test_driver_regions_signed_ja_and_scaled_grade_response(self):
        chroma = np.tile(35.*np.array([.5, 1., 2.]), 2)
        ja = np.repeat([75., -75.], 3)
        # Include all neutral signs and chromatic J_A=0 as separate limits.
        chroma = np.r_[chroma, 0., 0., 0., 2.]
        ja = np.r_[ja, 75., -75., 0., 0.]
        q = np.column_stack((signed_hk(ja, chroma), chroma, np.zeros_like(chroma)))
        actual = drivers(q, ja)
        visible = chroma**2/(chroma**2+4)
        np.testing.assert_allclose(actual[:, :2].sum(axis=-1), visible, rtol=2e-15)
        np.testing.assert_array_equal(actual[3:6], actual[:3])
        # The membership ratio crosses at (35/75)*abs(J_A).
        np.testing.assert_allclose(actual[:3, 1]/visible[:3], [.2, .5, .8], rtol=2e-15)
        np.testing.assert_array_equal(actual[6:9], 0.)
        np.testing.assert_allclose(actual[9, :2], [0., .5], rtol=2e-15)
        self.assertTrue(np.all((actual[:, :2] >= 0) & (actual[:, :2] <= 1)))
        for index in (0, 1):
            coefficients = tuple(float(i == index) for i in range(4))
            grade = Color(ColorSettings(lightness=(coefficients,)*4), Tone(ToneSettings()))
            output = grade.apply(Appearance(q, ja))
            np.testing.assert_allclose(output[:, 0]-q[:, 0], actual[:, index], atol=2e-14)
            for point, anchor, expected in zip(q, ja, output):
                scaled = grade.scaled_apply([S(v) for v in point], S(anchor))
                np.testing.assert_allclose([float(v) for v in scaled], expected, rtol=2e-15, atol=2e-14)

    def test_crossover_is_hue_independent_and_posttone_weights_are_frozen(self):
        ja = np.array([75., -75., 75., -75.])
        hue = np.array([0., 1., 3., 5.])
        chroma = np.full(4, 35.)
        q = np.column_stack((signed_hk(ja, chroma), chroma*np.cos(hue), chroma*np.sin(hue)))
        actual = drivers(q, ja)
        visible = chroma**2/(chroma**2+4)
        np.testing.assert_allclose(actual[:, :2], np.repeat((visible/2)[:, None], 2, axis=1), rtol=3e-15)
        # Retained lightness and chroma read the same original drivers once.
        settings = ColorSettings(global_gain=.2, chroma=((.1,-.2,.03,.02),)*4,
                                 lightness=((2.,-3.,.1,.2),)*4)
        boundary = Mock()
        boundary.capacity.side_effect = AssertionError('Classifier consulted gamut capacity')
        boundary.capacity_scaled.side_effect = AssertionError('Scaled classifier consulted gamut capacity')
        color = Color(settings, Tone(ToneSettings()), boundary)
        output = color.apply(Appearance(q, ja))
        gain = np.exp2(.2 + actual @ np.asarray(settings.chroma[0]))
        np.testing.assert_allclose(output[:, 1:], q[:,1:]*gain[:,None], rtol=3e-15, atol=3e-14)
        np.testing.assert_allclose(output[:,0]-q[:,0], actual @ np.asarray(settings.lightness[0]), atol=3e-14)
        for point, anchor, expected in zip(q, ja, output):
            scaled = color.scaled_apply(point, anchor)
            np.testing.assert_allclose([float(v) for v in scaled], expected, rtol=3e-15, atol=3e-14)
        boundary.capacity.assert_not_called()
        boundary.capacity_scaled.assert_not_called()

    def test_driver_stable_ratios_and_scaled_chroma_gain_across_magnitudes(self):
        # Representation stress is separate from UI-control accuracy gates.
        magnitudes = np.array([1e-140, 1e-20, 1., 1e20, 1e140])
        c = 35*magnitudes; ja = -75*magnitudes
        q = np.column_stack((signed_hk(ja, c), .6*c, .8*c))
        actual = drivers(q, ja)
        visible = (c/np.hypot(c, 2))**2
        np.testing.assert_allclose(actual[:, :2], np.repeat((visible/2)[:, None], 2, axis=1), rtol=2e-15)
        np.testing.assert_allclose(actual[:, 2:], q[:, 1:]/np.hypot(c, 2)[:, None], rtol=2e-15)
        for point, anchor, expected in zip(q, ja, actual):
            np.testing.assert_array_equal(drivers(point, anchor), expected)
        color = Color(ColorSettings(chroma=((.25, -.125, 0., 0.),)*4), Tone(ToneSettings()))
        expected = q[:, 1:]*np.exp2(actual[:, :2] @ [.25, -.125])[:, None]
        np.testing.assert_allclose(color.apply(Appearance(q, ja))[:, 1:], expected, rtol=3e-15)
        for point, anchor, target in zip(q, ja, expected):
            scaled = color.scaled_apply(point, anchor)
            np.testing.assert_allclose([float(v) for v in scaled[1:]], target, rtol=3e-15)
        # Values outside float64's exponent range remain finite scaled numbers.
        for exponent in (-2000, 2000):
            c = S(35., exponent); ja = S(-75., exponent)
            result = color.scaled_apply([signed_hk(ja, c), c, S()], ja)
            visibility = c*c/(c*c+4)
            expected_gain = (visibility*(.25-.125)/2).exp2()
            self.assertAlmostEqual(float(result[1]/c), float(expected_gain), places=14)

    def test_signed_hk_decimal_anchors_and_inverse(self):
        with localcontext() as ctx:
            ctx.prec = 80
            b = (Decimal(66)*80).sqrt()
            magnitude = (Decimal(25)**2+66*80).sqrt()
            for ja, expected in [(25., magnitude), (-25., 2*b-magnitude)]:
                h = float(signed_hk(ja, 80.))
                self.assertAlmostEqual(h/float(expected), 1., places=15)
                self.assertAlmostEqual(float(hk_energy(h, 80.))/(ja*abs(ja)), 1., places=13)
                self.assertAlmostEqual(float(signed_hk(S(ja), S(80.)))/h, 1., places=15)
        h = np.linspace(-200., 200., 1001)
        np.testing.assert_array_equal(signed_hk(h, np.zeros_like(h)), h)
        np.testing.assert_array_equal(hk_energy(h, np.zeros_like(h)), h*np.abs(h))
        for c in (0., 1., 80., 1000.):
            energy = hk_energy(h, c)
            self.assertTrue((np.diff(energy) > 0).all())
            np.testing.assert_allclose(signed_hk(signed_power(energy, .5), c), h, atol=8e-13)

    def test_carried_signed_energy_and_zero_h_nonblack_controls(self):
        for ja in (-1e-100, 1e-100, -25., 25.):
            q = np.array([float(signed_hk(ja, 80.)), 80., 0.])
            # Rounded H erases the small sign departure; the carried anchor does not.
            self.assertEqual(float(requested_energy(q, q, np.array(ja))), ja*abs(ja))
            scaled = [S(v) for v in q]
            self.assertEqual(requested_energy(scaled, scaled, S(ja)), S(ja)*abs(S(ja)))
        b = np.sqrt(66*80.)
        values = hk_energy(b+np.array([-1., 0., 1.]), 80.)
        np.testing.assert_array_equal(np.sign(values), [-1., 0., 1.])
        base = Appearance(np.array([0., 10., 0.]), np.array(-np.sqrt(1980.)))
        color = Color(ColorSettings(lightness=((0., 1., 0., 0.),)*4), Tone(ToneSettings()))
        self.assertGreater(color.apply(base)[0], 0.)
        scaled = color.scaled_apply([S(v) for v in base.q], S(float(base.ja)))
        np.testing.assert_allclose([float(v) for v in scaled], color.apply(base), atol=3e-14)

    def test_tone_preserves_signed_lightness_and_saturation(self):
        tone = Tone(ToneSettings(input_nits=(0., 8., 40., 235., 1150.)))
        ja = np.array([-75., -5., 0., 5., 75.])
        c = np.array([20., 10., 10., 10., 20.])
        q = np.column_stack((signed_hk(ja, c), c, np.zeros_like(c)))
        output = tone.apply(Appearance(q, ja))
        np.testing.assert_array_equal(np.sign(output.ja), np.sign(ja))
        magnitude = np.hypot(output.ja, np.sqrt(66*np.hypot(output.q[:, 1], output.q[:, 2])))
        np.testing.assert_allclose(magnitude, tone.remap(np.hypot(ja, np.sqrt(66*c))), rtol=3e-15)
        nonzero = ja != 0
        np.testing.assert_allclose(output.q[nonzero, 1]/np.abs(output.ja[nonzero]), c[nonzero]/np.abs(ja[nonzero]), rtol=3e-15)

    def test_creative_gain_can_reverse_chroma_order(self):
        tone = Tone(ToneSettings())
        color = Color(replace(ColorSettings(), chroma=((0., -4., 0., 0.),)*4), tone)
        c = np.array([10., 20., 40.])
        q = np.column_stack((np.full(3, 100.), c, np.zeros(3)))
        j = np.sqrt(10000-66*c)
        out = color.apply(Appearance(q, j))
        self.assertLess(out[0, 1], out[1, 1])
        self.assertGreater(out[1, 1], out[2, 1])
