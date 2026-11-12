from color_tools.perceptual_grade_reference.appearance import encode_cones
"""Guarded display inversion with original per-point H-K context."""
from dataclasses import replace
import unittest
import numpy as np
from color_tools.perceptual_grade_reference.grading import Tone, ToneSettings, Color, ColorSettings
from color_tools.perceptual_grade_core.model.tonal_web import WebSettings, rec709_contour
from color_tools.perceptual_grade_core.model.saturation import bounded_project
from color_tools.perceptual_grade_core.model.hk_guard import guard
from color_tools.perceptual_grade_reference.responses import signed_hk


class GuardedWarpTests(unittest.TestCase):
    def setUp(self):
        self.tone = Tone(ToneSettings())
        self.adaptance = ((2., -1.), (-3., 2.), (1., 3.), (-2., -1.))

    def color(self, *, adapted=False, stops=0., scale=0.):
        return Color(ColorSettings(adaptance=self.adaptance if adapted else ((0., 0.),)*4,
            web=WebSettings(log_chroma=((stops,)*6,)*4, log_scale=((scale,)*6,)*4)), self.tone)

    def test_guard_context_and_source_arrays(self):
        for adapted in (False, True):
            for scale in (-2., 0., 2.):
                color = self.color(adapted=adapted, stops=1., scale=scale)
                for row in range(4):
                    raw = color.pre_repair_warp_targets(row)
                    reference = np.r_[color.web.geometry.anchors[row]**2, color.web.geometry.energy[row]]
                    q, e = guard(raw.q, raw.energy, reference)
                    q[1:, 1:] *= 2**scale
                    e[1:] *= 2**(2*scale)
                    q[1:, 0] = signed_hk(np.sqrt(e[1:]), np.hypot(q[1:, 1], q[1:, 2]))
                    actual = color.guarded_warp_targets(row)
                    np.testing.assert_allclose(actual.q, q, rtol=3e-13, atol=3e-12)
                    np.testing.assert_allclose(actual.energy, e, rtol=3e-13, atol=3e-10)
                    np.testing.assert_allclose(color.guarded_saturation_targets(row), bounded_project(q, e))
                    source = rec709_contour(color.web.geometry.anchors[row], self.tone.reference, samples_per_edge=4, encoder=encode_cones)
                    actual = color.guarded_warp_state(source, color.web.geometry.anchors[row])
                    expected = color.warp_state(source, color.web.geometry.anchors[row])
                    np.testing.assert_array_equal(actual.q, expected.q)
                    np.testing.assert_array_equal(actual.energy, expected.energy)
                    self.assertTrue(np.all(actual.energy >= 0))

    def test_corner_evaluator_matches_full_web_and_guard(self):
        for adapted in (False, True):
            for scale in (-2., 0., 2.):
                color = self.color(adapted=adapted, stops=.6, scale=scale)
                for row in range(4):
                    raw = color.pre_repair_warp_targets(row)
                    points = color.guarded_saturation_targets(row)
                    for handle in range(6):
                        state, point = color.guarded_corner_evaluator(row, handle)()
                        np.testing.assert_allclose(state.q, raw.q[handle+1], rtol=3e-12, atol=3e-12)
                        np.testing.assert_allclose(state.energy, raw.energy[handle+1], rtol=3e-12, atol=3e-10)
                        np.testing.assert_allclose(point, points[handle+1], rtol=3e-12, atol=3e-12)

    def test_reset_and_center_exact_inverse(self):
        color = self.color()
        for row in range(4):
            np.testing.assert_allclose(color.guarded_saturation_targets(row), color.bounded_saturation_targets(row), atol=1e-15)
            target = np.array([.025, -.017])
            result = Color(color.target_guarded_saturation_settings(row, -1, target), self.tone)
            np.testing.assert_allclose(result.guarded_saturation_targets(row)[0], target, atol=3e-13)

    def test_boundary_and_local_roundtrips_cross_energy_zero(self):
        for adapted in (False, True):
            for scale in (-2., 0., 2.):
                initial = self.color(adapted=adapted, scale=scale)
                for row in range(4):
                    for handle in range(6):
                        boundary = Color(initial.guarded_boundary_settings(row, handle), self.tone)
                        raw = boundary.pre_repair_warp_targets(row)
                        self.assertLess(abs(raw.energy[handle+1])/(1+abs(initial.web.geometry.energy[row,handle])), 2e-11)
                        evaluator = boundary.guarded_corner_evaluator(row, handle)
                        for offset in (-.002, .002):
                            state, point = evaluator(evaluator.log_chroma+offset)
                            # A seed immediately on either side must support the
                            # opposite side without old signed-chart rejection.
                            settings = boundary.target_guarded_saturation_settings(row, handle, point)
                            result = Color(settings, self.tone)
                            np.testing.assert_allclose(result.guarded_saturation_targets(row)[handle+1], point, atol=2e-10, rtol=2e-10)
                            self.assertEqual(result.pre_repair_warp_targets(row).energy[handle+1] < 0, state.energy < 0)
                        rim = boundary.guard_rim_radius(row, handle)
                        np.testing.assert_allclose(rim, np.linalg.norm(boundary.guarded_saturation_targets(row)[handle+1]), rtol=3e-10, atol=3e-10)

    def test_stops_hold_requested_gain_and_solve_display_hue(self):
        color = self.color(adapted=True)
        for row in range(4):
            for handle in range(6):
                boundary = Color(color.guarded_boundary_settings(row, handle), self.tone)
                origin = boundary.guarded_saturation_targets(row)[handle+1]
                angle = np.arctan2(origin[1], origin[0])+.03
                stops = boundary.settings.web.log_chroma[row][handle]+1.
                settings = boundary.target_guarded_hue_settings(row, handle, stops, angle)
                self.assertAlmostEqual(settings.web.log_chroma[row][handle], stops, places=13)
                result = Color(settings, self.tone)
                point = result.guarded_saturation_targets(row)[handle+1]
                self.assertLess(abs(np.sin(np.arctan2(point[1], point[0])-angle)), 2e-11)
                saved = replace(settings, web=WebSettings(**{field:tuple(map(tuple,np.asarray(getattr(settings.web,field),np.float32).astype(float))) for field in ('log_chroma','hue_degrees','log_scale')}))
                np.testing.assert_allclose(Color(saved,self.tone).guarded_saturation_targets(row)[handle+1], point, atol=2e-6)

    def test_scale_preserves_all_guarded_anchor_positions_across_energy_branches(self):
        for adapted in (False, True):
            initial = self.color(adapted=adapted)
            self.assertTrue(np.all(initial.web.geometry.energy > 0))
            for row in range(4):
                for handle in range(6):
                    boundary = initial.guarded_boundary_settings(row, handle)
                    for offset in (-.1, 0., .1):
                        chroma = np.array(boundary.web.log_chroma)
                        chroma[row, handle] += offset
                        settings = replace(boundary, web=replace(boundary.web, log_chroma=tuple(map(tuple,chroma))))
                        base = Color(settings, self.tone)
                        raw = base.pre_repair_warp_targets(row)
                        source_energy = initial.web.geometry.energy[row, handle]
                        if offset < 0:
                            self.assertGreater(raw.energy[handle+1], 0.)
                        elif offset > 0:
                            self.assertLess(raw.energy[handle+1], 0.)
                        else:
                            self.assertLess(abs(raw.energy[handle+1])/(1+source_energy), 2e-11)
                        point = base.guarded_saturation_targets(row)[handle+1]
                        heights = []
                        for stops in (-8., -2., 0., 2., 8.):
                            scale = np.zeros((4,6)); scale[row,handle] = stops
                            color = Color(replace(settings, web=replace(settings.web, log_scale=tuple(map(tuple,scale)))), self.tone)
                            state = color.guarded_warp_targets(row)
                            self.assertGreater(state.energy[handle+1], 0.)
                            heights.append(state.q[handle+1,0])
                            np.testing.assert_allclose(color.guarded_saturation_targets(row)[handle+1], point,
                                                       rtol=4e-13, atol=4e-14)
                        self.assertTrue(np.all(np.diff(heights) > 0))

    def test_active_adaptance_return_from_zero_energy_to_position(self):
        adapted = np.zeros((4,2)); adapted[1] = [7.,-3.]
        scale = np.zeros((4,6)); scale[1,0] = .3
        original = Color(ColorSettings(adaptance=tuple(map(tuple,adapted)),
            web=WebSettings(log_scale=tuple(map(tuple,scale)))), self.tone)
        boundary = Color(original.guarded_boundary_settings(1,0), self.tone)
        point = boundary.guarded_saturation_targets(1)[1]
        for fraction in (.999, .995):
            desired = point*fraction
            settings = boundary.target_guarded_saturation_settings(1, 0, desired)
            actual = Color(settings, self.tone)
            self.assertGreater(actual.pre_repair_warp_targets(1).energy[1], 0.)
            np.testing.assert_allclose(actual.guarded_saturation_targets(1)[1], desired, atol=2e-11)

    def test_invalid_destinations_and_control_order_are_rejected(self):
        color = self.color()
        for target in ([1.,0.],[np.nan,0.],[0.,0.],[-.99,0.]):
            with self.assertRaises(ValueError):color.target_guarded_saturation_settings(1,0,target)
        with self.assertRaises(ValueError):color.target_guarded_hue_settings(1,0,1.,np.nan)


if __name__ == '__main__':
    unittest.main()
