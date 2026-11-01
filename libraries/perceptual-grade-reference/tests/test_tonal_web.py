from color_tools.perceptual_grade_reference.appearance import encode_cones
import dataclasses
import unittest
import numpy as np
from color_tools.perceptual_grade_core.model.tonal_web import (
    WebSettings, TonalWeb, radial_map, radial_derivative, radial_coefficient,
    angular_map, rec709_contour,
)
from color_tools.perceptual_grade_reference.grading import Tone, ToneSettings
from color_tools.perceptual_grade_reference.responses import hk_energy
from color_tools.color_core.scaled import Scalar as S


def controls(**kwargs):
    values = {name: np.zeros((4, 6)) for name in ('log_chroma', 'hue_degrees', 'log_scale')}
    for name, edits in kwargs.items():
        for row, column, value in edits:
            values[name][row, column] = value
    return WebSettings(**{name: tuple(map(tuple, value)) for name, value in values.items()})


class TonalWebTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tone = Tone(ToneSettings())
        cls.settings = controls(log_chroma=[(0, 4, .9), (1, 0, -.35), (2, 2, .25)],
                                hue_degrees=[(0, 4, -12), (1, 0, 8), (2, 2, -9)],
                                log_scale=[(0, 4, .12), (1, 0, -.2), (2, 2, .18)])
        cls.web = TonalWeb(cls.settings, cls.tone, encoder=encode_cones)

    def test_reset_and_lazy_geometry(self):
        web = TonalWeb(WebSettings(), self.tone, encoder=encode_cones)
        self.assertIsNone(web._geometry)
        q = np.array([[3., 1e-30, 0.], [-4., 0., 2.], [0., 0., 0.]])
        e = np.array([1.e-50, -2., 0.])
        out, energy = web.apply(q, e, q[:, 0])
        np.testing.assert_array_equal(out, q)
        np.testing.assert_array_equal(energy, e)
        self.assertIsNone(web._geometry)

    def test_geometry_heights_and_contour_handles(self):
        geometry = self.web.geometry
        np.testing.assert_allclose(geometry.q[..., 0], geometry.anchors[:, None]*np.ones((1, 6)), rtol=2e-15)
        for i, h in enumerate(geometry.anchors):
            contour = rec709_contour(h, samples_per_edge=12, encoder=encode_cones)
            np.testing.assert_allclose(contour.q[::12], geometry.q[i], rtol=2e-14, atol=1e-14)
        self.assertTrue(np.all(np.diff(geometry.angles) > 0))

    def test_exact_target_handles(self):
        geometry = self.web.geometry
        q, energy = self.web.apply(geometry.q, geometry.energy, geometry.anchors[:, None])
        p = self.web.parameters(geometry.anchors)
        radii = p['target_radii']*p['scales']
        expected = np.stack((radii*np.cos(p['target_angles']), radii*np.sin(p['target_angles'])), axis=-1)
        np.testing.assert_allclose(q[..., 1:], expected, rtol=2e-14, atol=2e-14)
        self.assertLess(energy[0, 4], 0)
        q1, e1 = TonalWeb(dataclasses.replace(self.settings, log_scale=WebSettings().log_scale), self.tone, encoder=encode_cones).apply(
            geometry.q, geometry.energy, geometry.anchors[:, None])
        np.testing.assert_array_equal(q1[..., 0], geometry.q[..., 0])
        np.testing.assert_allclose(energy, e1*p['scales']**2, rtol=3e-14, atol=1e-10)

    def test_radial_calibration_and_derivatives(self):
        for source in (.05, 1., 50.):
            for target in (.001, .1, 3., 100.):
                toe = min(source, target)*.05
                g = radial_coefficient(source, target, toe)
                self.assertGreater(g, 0)
                self.assertAlmostEqual(radial_map(source, g, toe), target, delta=target*2e-12)
                samples = np.geomspace(1e-9, 1e5, 500)
                self.assertTrue(np.all(radial_derivative(samples, g, toe) > 0))
                self.assertTrue(np.all(np.diff(radial_map(samples, g, toe)) > 0))

    def test_hue_monotonicity_periodicity_and_handles(self):
        p = self.web.parameters(self.web.geometry.anchors[0])
        source, target = p['angles'], p['target_angles']
        samples = np.linspace(source[0], source[0]+2*np.pi, 10001)
        mapped = angular_map(samples, np.broadcast_to(source, (samples.size, 6)),
                             np.broadcast_to(target, (samples.size, 6)))
        self.assertTrue(np.all(np.diff(mapped) > 0))
        np.testing.assert_allclose(angular_map(source, np.broadcast_to(source, (6, 6)),
                                               np.broadcast_to(target, (6, 6))), target, atol=3e-15)
        self.assertAlmostEqual(mapped[-1]-mapped[0], 2*np.pi)

    def test_tonal_anchors_and_c2_extension(self):
        anchors = self.web.geometry.anchors
        p = self.web.parameters(anchors)
        np.testing.assert_allclose(np.log2(p['target_radii']/p['radii']), self.settings.log_chroma, atol=4e-16)
        for h in anchors:
            eps = 1e-3
            a, b, c = [self.web.parameters(h+x)['target_angles'] for x in (-eps, 0, eps)]
            self.assertLess(np.max(abs((c-a)/(2*eps))), 1e-7)
            self.assertLess(np.max(abs((c-2*b+a)/eps**2)), 1e-5)

    def test_neutral_and_direction_independent_derivative(self):
        h = self.web.geometry.anchors[1]
        angle = np.linspace(0, 2*np.pi, 73)
        c = 1e-5
        q = np.stack((np.full_like(angle, h), c*np.cos(angle), c*np.sin(angle)), axis=-1)
        out, _ = self.web.apply(q, hk_energy(h, np.full_like(angle, c)), h)
        np.testing.assert_allclose(out[:, 1:]/c, q[:, 1:]/c, atol=2e-13)
        gray = np.array([h, 0., 0.])
        result, e = self.web.apply(gray, h*h, h)
        np.testing.assert_array_equal(result, gray)
        self.assertEqual(e, h*h)

    def test_scaled_vector_agreement(self):
        geometry = self.web.geometry
        out, energy = self.web.apply(geometry.q, geometry.energy, geometry.anchors[:, None])
        for i in range(4):
            for j in range(6):
                q, e = self.web.scaled_apply(list(map(S, geometry.q[i, j])), S(geometry.energy[i, j]), S(geometry.anchors[i]))
                np.testing.assert_allclose(list(map(float, q)), out[i, j], rtol=3e-14, atol=1e-13)
                self.assertAlmostEqual(float(e), energy[i, j], delta=1e-10+abs(energy[i, j])*3e-14)

    def test_untouched_tonal_row_is_exact(self):
        h = self.web.geometry.anchors[-1]
        q = np.array([[h, 4., 8.], [h, -2., 17.], [h, 1.e-30, 0.]])
        e = hk_energy(h, np.hypot(q[:, 1], q[:, 2]))
        out, energy = self.web.apply(q, e, h)
        np.testing.assert_array_equal(out, q)
        np.testing.assert_array_equal(energy, e)

    def test_direct_drag_retains_scale_and_reaches_cursor(self):
        row, handle = 1, 0
        target = np.array([12., 7.])
        settings = self.web.settings_for_target(row, handle, target)
        self.assertEqual(settings.log_scale, self.settings.log_scale)
        web = TonalWeb(settings, self.tone, encoder=encode_cones)
        q, _ = web.apply(web.geometry.q[row, handle], web.geometry.energy[row, handle], web.geometry.anchors[row])
        np.testing.assert_allclose(q[1:], target, atol=1e-13)
        with self.assertRaises(ValueError):
            self.web.settings_for_target(row, handle, [0., 0.])

    def test_sampled_opponent_jacobian_is_positive(self):
        h = self.web.geometry.anchors[0]
        angle = np.linspace(0, 2*np.pi, 48, endpoint=False)
        radii = np.geomspace(1e-3, 100., 29)
        ab = np.stack((np.cos(angle), np.sin(angle)), axis=-1)[None, :, :]*radii[:, None, None]
        def evaluate(ab):
            c = np.hypot(ab[..., 0], ab[..., 1])
            q = np.concatenate((np.full(c.shape+(1,), h), ab), axis=-1)
            return self.web.apply(q, hk_energy(h, c), h)[0][..., 1:]
        step = radii[:, None, None]*1e-5
        da = (evaluate(ab+step*np.array([1., 0.]))-evaluate(ab-step*np.array([1., 0.])))/(2*step)
        db = (evaluate(ab+step*np.array([0., 1.]))-evaluate(ab-step*np.array([0., 1.])))/(2*step)
        determinant = da[..., 0]*db[..., 1]-da[..., 1]*db[..., 0]
        self.assertGreater(float(np.min(determinant)), 0)

    def test_angular_c2_joins(self):
        p = self.web.parameters(self.web.geometry.anchors[0])
        for angle in p['angles']:
            x = angle+np.array([-2., -1., 0., 1., 2.])*1e-3
            y = angular_map(x, np.broadcast_to(p['angles'], (5, 6)),
                            np.broadcast_to(p['target_angles'], (5, 6)))
            left = (y[2]-2*y[1]+y[0])/1e-6
            right = (y[4]-2*y[3]+y[2])/1e-6
            self.assertLess(abs(left), .02)
            self.assertLess(abs(right), .02)

    def test_settings_are_validated_immutable_values(self):
        supplied = np.zeros((4, 6))
        settings = WebSettings(log_chroma=supplied)
        supplied[0, 0] = 10.
        self.assertEqual(settings, WebSettings())
        self.assertEqual(hash(settings), hash(WebSettings()))
        with self.assertRaises(ValueError):
            controls(hue_degrees=[(0, 0, float('nan'))])
        with self.assertRaises(ValueError):
            WebSettings(log_chroma=[[0.]])

    def test_invalid_states(self):
        for web in (self.web, TonalWeb(WebSettings(), self.tone, encoder=encode_cones)):
            for q, e, h in (([1., 2.], 0., 1.), ([1., 0., 0.], np.inf, 1.),
                            ([np.nan, 0., 0.], 0., 1.), ([1., 0., 0.], 0., np.nan)):
                with self.assertRaises(ValueError):
                    web.apply(q, e, h)
            with self.assertRaises(ValueError):
                web.scaled_apply([S(), S()], S(), S())

    def test_extreme_gain_keeps_resolvable_toe_and_scaled_agreement(self):
        gain = 2.**64
        self.assertGreater(radial_map(1.e-5, gain, 1.)/1.e-5, 1.04)
        self.assertGreater(radial_derivative(1.e-5, gain, 1.), 1.2)
        web = TonalWeb(WebSettings(log_chroma=((64.,)*6,)*4), self.tone, encoder=encode_cones)
        h = web.geometry.anchors[0]
        toe = web.parameters(h)['chroma_toe']
        q = np.array([h, toe*1.e-5, 0.])
        energy = hk_energy(h, q[1])
        vector, ev = web.apply(q, energy, h)
        scaled, es = web.scaled_apply(q, S(energy), S(h))
        np.testing.assert_allclose(vector, list(map(float, scaled)), rtol=2e-14)
        self.assertAlmostEqual(ev/float(es), 1., places=13)
        self.assertGreater(vector[1]/q[1], 1.04)

    def test_extreme_finite_controls_and_scaled_exponents(self):
        h = self.web.geometry.anchors[0]
        for chroma_gain in (-64., 64.):
            for scale_gain in (-64., 64.):
                settings = WebSettings(log_chroma=((chroma_gain,)*6,)*4,
                                       log_scale=((scale_gain,)*6,)*4)
                web = TonalWeb(settings, self.tone, encoder=encode_cones)
                q = np.array([h, 4., 3.])
                energy = hk_energy(h, 5.)
                out, eo = web.apply(q, energy, h)
                scaled, es = web.scaled_apply(q, S(energy), S(h))
                self.assertTrue(np.isfinite(out).all())
                self.assertTrue(np.isfinite(eo))
                np.testing.assert_allclose(out, list(map(float, scaled)), rtol=1e-13, atol=1e-80)
                self.assertAlmostEqual(eo/float(es), 1., places=12)
        for exponent in (-2000, 2000):
            chroma = S(.5, exponent)
            energy = S(.5, exponent)
            q, e = self.web.scaled_apply([S(h), chroma, S()], energy, S(h))
            self.assertTrue(all(isinstance(v, S) for v in q))
            self.assertIsInstance(e, S)

    def test_pure_hue_keeps_carried_energy_exact(self):
        web = TonalWeb(WebSettings(hue_degrees=((17.,)*6,)*4), self.tone, encoder=encode_cones)
        angle = np.linspace(0., 2*np.pi, 101)
        h = self.web.geometry.anchors[1]
        c = np.full_like(angle, 10.)
        q = np.stack((np.full_like(angle, h), c*np.cos(angle), c*np.sin(angle)), axis=-1)
        e = hk_energy(h, np.hypot(q[:, 1], q[:, 2]))
        _, out = web.apply(q, e, h)
        np.testing.assert_array_equal(out, e)

    def test_reject_crossed_collapsed_nonfinite(self):
        for settings in (controls(hue_degrees=[(0, 0, 179)]), controls(log_chroma=[(0, 0, -2000)]),
                         controls(log_scale=[(0, 0, 2000)])):
            with self.assertRaises(ValueError):
                TonalWeb(settings, self.tone, encoder=encode_cones)


if __name__ == '__main__':
    unittest.main()
