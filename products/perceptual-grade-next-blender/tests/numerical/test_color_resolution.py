"""Portable authoring-domain repair, independent of native graph evaluation."""

from dataclasses import replace
import importlib
import math
import unittest
from unittest.mock import patch

import numpy as np

from color_tools.color_core.modcam16 import GAMMA, INVERSE, eccentricity
from color_tools.kernel import ColorSettings, Settings, ToneSettings, WebSettings, prepare_tone
from color_tools.kernel.color_resolution import (
    HUE_MIN_GAP, HUE_REPAIR_GAP, adaptation_context, float32,
    hue_source_angles, limit_adaptance_pair, project_hue_offsets, resolve_settings,
)


def gaps(values):
    return np.diff(np.r_[values, values[0] + 360.])


def responses(pair, anchor, aw):
    angle = math.atan2(pair[1], pair[0])
    opponent = np.asarray(pair) * aw / (1204. * eccentricity(angle))
    neutral = aw / 3.05 * (anchor / 100.) ** (1. / GAMMA)
    return neutral + INVERSE[:, 1:] @ opponent


class ColorResolutionTests(unittest.TestCase):
    def test_context_matches_preparation_without_building_tone_tables(self):
        module = importlib.import_module("color_tools.kernel.prepare")
        for peak in (500., 1000., 2000., 4000., 1.e6):
            expected = prepare_tone(ToneSettings(peak_nits=peak))
            settings = Settings(tone=ToneSettings(peak_nits=peak))
            with patch.object(module, "prepare_tone", side_effect=AssertionError("Tone table build")):
                anchors, aw = adaptation_context(settings)
                angles = hue_source_angles(settings)
            np.testing.assert_array_equal(anchors, 100. * expected.target[1:])
            self.assertEqual(aw, expected.aw)
            self.assertEqual(np.shape(angles), (4, 6))
            self.assertTrue(np.all(np.apply_along_axis(gaps, 1, np.asarray(angles)) > 4.))
            changed_input = replace(settings, tone=replace(settings.tone,
                input_nits=(2., 3., 400., 800.), black_compression_nits=1., fit=2.), space="ACEScg")
            self.assertIs(hue_source_angles(settings), hue_source_angles(changed_input))
            self.assertEqual(adaptation_context(settings), adaptation_context(changed_input))

    def test_valid_defaults_and_near_pole_legacy_pair_remain_exact(self):
        default = Settings()
        self.assertIs(resolve_settings(default), default)
        valid = replace(default, color=ColorSettings(
            adaptance=((-260.8694152832031, 0.), (2., -1.), (-2., 5.), (4., -1.))))
        self.assertIs(resolve_settings(valid), valid)
        for peak in (500., 1000., 2000., 4000.):
            anchors, aw = adaptation_context(Settings(tone=ToneSettings(peak_nits=peak)))
            for anchor, span in zip(anchors, (4., 10., 20., 25.)):
                for a in (-span, span):
                    for b in (-span, span):
                        pair = (a, b)
                        self.assertEqual(limit_adaptance_pair(pair, anchor, aw), pair)

    def test_adaptance_repairs_preserve_tint_direction_and_physical_domain(self):
        for peak in (500., 1000., 2000., 4000.):
            anchors, aw = adaptation_context(Settings(tone=ToneSettings(peak_nits=peak)))
            for anchor in anchors:
                for requested in ((1.e6, 0.), (-1.e6, 0.), (0., 1.e6), (0., -1.e6),
                                  (1.e6, -2.e6), (-2.e6, 1.e6), (1.e308, -1.e308)):
                    with self.subTest(peak=peak, anchor=anchor, requested=requested):
                        limited = limit_adaptance_pair(requested, anchor, aw)
                        decoded = responses(limited, anchor, aw)
                        self.assertTrue(np.all(decoded > 0.))
                        self.assertTrue(np.all(decoded < 400.))
                        self.assertEqual(tuple(float32(value) for value in limited), limited)
                        direction = np.asarray(requested) / max(map(abs, requested))
                        actual = np.asarray(limited) / max(map(abs, limited))
                        np.testing.assert_allclose(actual, direction, rtol=2.e-7, atol=1.e-7)
                        self.assertEqual(limit_adaptance_pair(limited, anchor, aw), limited)

    def test_exact_cyclic_projection_matches_independent_kkt_witness(self):
        source = np.arange(6) * 60.
        optimum = np.array((50., 54., 58., 150., 240., 406.))
        # Active edge normals times nonnegative multipliers supply the
        # projection's normal-cone certificate, including the wrapped edge.
        normal = np.zeros(6)
        for edge, multiplier in ((0, 13.), (1, 9.), (5, 17.)):
            normal[edge] -= multiplier
            normal[(edge + 1) % 6] += multiplier
        requested = optimum - normal
        actual = source + project_hue_offsets(source, requested - source)
        np.testing.assert_allclose(actual, optimum, rtol=0., atol=1.e-12)
        self.assertTrue(np.all(gaps(actual) >= 4. - 1.e-12))
        offset = tuple(optimum - source)
        self.assertEqual(project_hue_offsets(source, offset), offset)
        translated = source + project_hue_offsets(source, requested - source + 720.)
        np.testing.assert_allclose(translated, optimum + 720., atol=1.e-12)

    def test_projection_respects_fixed_roots_bounds_and_wrapped_components(self):
        source = tuple(float(index * 60) for index in range(6))
        requested = (310., -300., 80., -100., -200., 100.)
        bounds = {index: (-360., 360.) for index in range(6)}
        fixed = {0: 310.}
        actual = project_hue_offsets(source, requested, gap=HUE_REPAIR_GAP,
                                     fixed=fixed, bounds=bounds)
        self.assertEqual(actual[0], fixed[0])
        self.assertTrue(all(-360. <= value <= 360. for value in actual))
        self.assertTrue(np.all(gaps(np.asarray(source) + actual) >= HUE_REPAIR_GAP - 1.e-9))
        self.assertEqual(project_hue_offsets(source, actual, gap=HUE_REPAIR_GAP,
                                            fixed=fixed, bounds=bounds), actual)
        # Fixed values can make the convex constraint set empty.
        with self.assertRaisesRegex(ValueError, "cannot satisfy"):
            project_hue_offsets(source, (0.,) * 6, fixed={0: 300., 1: -300.})
        with self.assertRaises(ValueError):
            project_hue_offsets(source, requested, fixed={0: 400.}, bounds=bounds)

    def test_bounded_projection_matches_independent_normal_cone_certificate(self):
        source = np.arange(6) * 60.
        optimum = np.array((10., 14., 120., 180., 240., 300.))
        requested = (30., -6., 100., 180., 240., 350.)
        # The first edge has multiplier20, the third target's lower bound
        # multiplier20, and the fixed sixth target has unrestricted multiplier.
        result = project_hue_offsets(source, np.asarray(requested) - source,
            fixed={5: 0.}, bounds={2: (0., 100.)})
        np.testing.assert_allclose(source + result, optimum, rtol=0., atol=1.e-12)

    def test_resolved_animated_snapshot_is_safe_idempotent_and_does_not_mutate_keys(self):
        authored_hues = ((350., -350., 240., -240., 120., -120.),) * 4
        authored_adaptance = ((1.e6, -1.e6),) * 4
        authored = Settings(color=ColorSettings(adaptance=authored_adaptance,
            web=WebSettings(hue_degrees=authored_hues)))
        resolved = resolve_settings(authored)
        self.assertIsNot(resolved, authored)
        self.assertEqual(authored.color.web.hue_degrees, authored_hues)
        self.assertEqual(authored.color.adaptance, authored_adaptance)
        self.assertIs(resolve_settings(resolved), resolved)
        source = hue_source_angles(resolved)
        anchors, aw = adaptation_context(resolved)
        for angles, offsets, pair, anchor in zip(source, resolved.color.web.hue_degrees,
                                                resolved.color.adaptance, anchors):
            self.assertGreaterEqual(min(gaps(np.asarray(angles) + offsets)), HUE_MIN_GAP)
            self.assertTrue(all(-360. <= value <= 360. for value in offsets))
            self.assertTrue(np.all(responses(pair, anchor, aw) > 0.))
            self.assertTrue(np.all(responses(pair, anchor, aw) < 400.))

    def test_peak_change_recomputes_highlight_domain_and_geometry(self):
        high = Settings(tone=ToneSettings(peak_nits=4000.))
        low = replace(high, tone=replace(high.tone, peak_nits=500.))
        high_anchors, aw = adaptation_context(high)
        low_anchors, _ = adaptation_context(low)
        self.assertEqual(high_anchors[:3], low_anchors[:3])
        self.assertNotEqual(high_anchors[3], low_anchors[3])
        self.assertEqual(hue_source_angles(high)[:3], hue_source_angles(low)[:3])
        self.assertNotEqual(hue_source_angles(high)[3], hue_source_angles(low)[3])
        pair = limit_adaptance_pair((1.e6, 0.), high_anchors[3], aw)
        low = replace(low, color=ColorSettings(adaptance=((0., 0.),) * 3 + (pair,)))
        resolved = resolve_settings(low)
        decoded = responses(resolved.color.adaptance[3], low_anchors[3], aw)
        self.assertTrue(np.all(decoded > 0.))
        self.assertTrue(np.all(decoded < 400.))

    def test_nonfinite_controls_and_invalid_calibration_are_rejected(self):
        for value in (math.nan, math.inf, -math.inf):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    float32(value)
                with self.assertRaises(ValueError):
                    limit_adaptance_pair((value, 0.), 100., 30.)
                with self.assertRaises(ValueError):
                    project_hue_offsets(tuple(range(6)), (value,) * 6)
        for gap in (0., 60., math.nan):
            with self.assertRaises(ValueError):
                project_hue_offsets(tuple(range(6)), (0.,) * 6, gap=gap)
        with self.assertRaises(ValueError):
            limit_adaptance_pair((0., 0.), 1.e12, 30.)


if __name__ == "__main__":
    unittest.main()
