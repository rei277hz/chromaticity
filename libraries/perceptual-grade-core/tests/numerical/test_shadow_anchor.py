"""Verify the derived shadow calibration against the report and runtime models."""
from decimal import Decimal as D, localcontext
from importlib.resources import files
import json
import unittest

import numpy as np
from color_tools.perceptual_grade_core.model import tone
from color_tools.perceptual_grade_reference import appearance, grading


def regression(shadow, midgray, white, high):
    """Independent normal-equation fit of log gaps against indices 0..3."""
    gaps = (shadow, midgray-shadow, white-midgray, high-white)
    logs = tuple(value.ln() for value in gaps)
    slope = (4*sum(D(i)*value for i, value in enumerate(logs))-6*sum(logs))/20
    intercept = (sum(logs)-6*slope)/4
    errors = tuple(value-intercept-i*slope for i, value in enumerate(logs))
    objective = sum(value*value for value in errors)
    derivative = 2*(errors[0]/shadow-errors[1]/(midgray-shadow))
    stationarity = (midgray-shadow)*errors[0]-shadow*errors[1]
    return gaps, intercept, slope, errors, objective, derivative, stationarity


class ShadowAnchorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = json.loads((files('tests.numerical')/'shadow_anchor.json').read_text())

    def assertDecimalClose(self, actual, expected, tolerance='1e-70'):
        self.assertLessEqual(abs(D(actual)-D(expected)), D(tolerance))

    def test_landmarks_match_production_and_independent_neutral_equations(self):
        report = self.report
        self.assertEqual(report['schema'], 1)
        self.assertEqual(report['precision_digits'], 80)
        calibration = report['calibration']
        self.assertEqual(D(calibration['reference_white_nits']), D(203))
        self.assertEqual(D(calibration['midgray_y']), D('.18'))
        self.assertEqual(D(calibration['high_nits']), D(1000))
        production = tone.Model(tone.Parameters())
        reference = grading.Tone(grading.ToneSettings())
        luminance = np.array([0., float(report['solution']['shadow_nits']), .18*203, 203., 1000.])
        expected = np.array([float(report['landmarks'][key])
                             for key in ('black', 'shadow', 'midgray', 'white', 'high')])
        self.assertAlmostEqual(float(calibration['fl']), production.fl, places=15)
        self.assertAlmostEqual(float(calibration['gamma']), tone.GAMMA, places=15)
        for model in (production, reference):
            np.testing.assert_allclose(100*model.nits_to_j(luminance), expected, rtol=3e-15, atol=1e-13)
        # The independent appearance path retains exact neutral chroma zero.
        cones = np.repeat((luminance/203)[:, None], 3, axis=1)
        encoded = appearance.encode_cones(cones)
        np.testing.assert_allclose(encoded.ja, expected, rtol=3e-15, atol=1e-13)
        np.testing.assert_array_equal(encoded.q[:, 1:], 0.)
        np.testing.assert_allclose(production.j_to_nits(expected/100), luminance, rtol=3e-15, atol=1e-13)

    def test_derived_binary64_literal_and_defaults_preserve_identity(self):
        solution = self.report['solution']
        expected = float(D(solution['low_y']))
        self.assertEqual(solution['low_y_binary64'], expected)
        self.assertEqual(tone.LOW_Y, expected)
        self.assertEqual(grading.LOW_Y, expected)
        production = tone.Parameters()
        reference = grading.ToneSettings()
        self.assertEqual(production.input_shadows, expected*203.)
        self.assertEqual(reference.input_nits, production.input_nits)
        self.assertEqual(tone.LEVEL_DEFAULTS, production.input_nits)
        self.assertAlmostEqual(float(solution['shadow_nits']), production.input_shadows, places=14)
        heights = np.array([0., float(self.report['landmarks']['shadow']), 51., 100., 184., 1000.])
        production_model = tone.Model(production)
        reference_model = grading.Tone(reference)
        self.assertFalse(production_model.active)
        self.assertFalse(reference_model.active)
        np.testing.assert_array_equal(production_model.remap_h(heights), heights)
        np.testing.assert_array_equal(reference_model.remap(heights), heights)
        np.testing.assert_array_equal(reference_model.inverse(heights), heights)

    def test_report_fits_all_four_log_gaps(self):
        report = self.report
        with localcontext() as context:
            context.prec = 100
            values = [D(report['landmarks'][key]) for key in ('shadow', 'midgray', 'white', 'high')]
            gaps, intercept, slope, errors, objective, derivative, stationarity = regression(*values)
            fit = report['fit']
            self.assertTrue(all(left < right for left, right in zip(gaps, gaps[1:])))
            for actual, expected in zip(fit['gaps'], gaps):
                self.assertDecimalClose(actual, expected)
            fitted = [(intercept+i*slope).exp() for i in range(4)]
            for index in range(4):
                self.assertDecimalClose(fit['fitted_gaps'][index], fitted[index])
                self.assertDecimalClose(fit['relative_residuals'][index], gaps[index]/fitted[index]-1)
            self.assertDecimalClose(fit['a'], intercept.exp())
            self.assertDecimalClose(fit['r'], slope.exp())
            self.assertDecimalClose(fit['objective'], objective)
            self.assertDecimalClose(fit['derivative'], derivative)
            self.assertDecimalClose(report['solver']['stationarity'], stationarity)
            self.assertDecimalClose(sum(errors), 0)
            self.assertDecimalClose(sum(D(i)*error for i, error in enumerate(errors)), 0)
            self.assertDecimalClose(derivative, 0)
            self.assertDecimalClose(D(report['solution']['shadow_nits']),
                                    D(report['solution']['low_y'])*D(report['calibration']['reference_white_nits']))

    def test_stationary_solution_is_bracketed_and_minimizes_the_objective(self):
        report = self.report
        with localcontext() as context:
            context.prec = 100
            shadow, midgray, white, high = [D(report['landmarks'][key])
                                           for key in ('shadow', 'midgray', 'white', 'high')]
            solver = report['solver']
            self.assertEqual(solver['method'], 'bracketed_bisection')
            self.assertGreaterEqual(solver['iterations'], 230)
            low, high_shadow = map(D, solver['bracket'])
            self.assertLessEqual(low, shadow)
            self.assertLessEqual(shadow, high_shadow)
            self.assertLess(high_shadow-low, D('1e-68'))
            signs = list(map(D, solver['bracket_stationarity']))
            self.assertLessEqual(signs[0], 0)
            self.assertGreaterEqual(signs[1], 0)
            for point, value in zip((low, high_shadow), signs):
                self.assertDecimalClose(regression(point, midgray, white, high)[-1], value)
            bound = D(solver['uniqueness_derivative_lower_bound'])
            self.assertGreater(bound, 0)
            minimum = regression(shadow, midgray, white, high)[4]
            # Verify both local curvature at high precision and the whole
            # admissible interval, including near-black and near-midgray ends.
            candidates = [shadow+sign*D(delta) for sign in (-1, 1)
                          for delta in ('1e-6', '1e-12', '1e-24')]
            candidates += [midgray*D(i)/128 for i in range(1, 128)]
            candidates += [midgray*D(value) for value in ('1e-20', '0.99999999999999999999')]
            for candidate in candidates:
                gaps, _, _, errors, objective, derivative, _ = regression(candidate, midgray, white, high)
                self.assertGreater(objective, minimum)
                self.assertEqual(derivative > 0, candidate > shadow)
                e0_prime = D('.3')/candidate+D('.4')/(midgray-candidate)
                e1_prime = -D('.4')/candidate-D('.7')/(midgray-candidate)
                g_prime = -errors[0]-errors[1]+(midgray-candidate)*e0_prime-candidate*e1_prime
                self.assertGreaterEqual(g_prime, bound)

    def test_fixed_landmarks_rule_out_an_exact_geometric_progression(self):
        report = self.report
        with localcontext() as context:
            context.prec = 100
            midgray, white, high = [D(report['landmarks'][key]) for key in ('midgray', 'white', 'high')]
            exact = report['exact_progression']
            ratio = (high-white)/(white-midgray)
            first = (white-midgray)/(ratio*ratio)
            second = (white-midgray)/ratio
            self.assertDecimalClose(exact['ratio'], ratio)
            self.assertDecimalClose(exact['required_first_gap'], first)
            self.assertDecimalClose(exact['required_second_gap'], second)
            self.assertDecimalClose(exact['implied_midgray'], first+second)
            self.assertDecimalClose(abs(D(exact['mismatch'])), abs(first+second-midgray))
            self.assertGreater(abs(first+second-midgray), D(1))
