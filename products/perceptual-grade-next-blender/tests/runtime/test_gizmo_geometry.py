"""Check the installed Gizmo layout and vectorscope handle geometry."""

import importlib
from functools import partial
from importlib.resources import files
from itertools import combinations
import math
import numpy as np
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import zipfile


class GizmoGeometryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        directory = tempfile.TemporaryDirectory(prefix="pg-gizmo-geometry-")
        cls.addClassCleanup(directory.cleanup)
        package_name = "gizmo_geometry_test_extension"
        package = Path(directory.name) / package_name
        with zipfile.ZipFile(files("tests.perceptual_grade_blender") / "extension.zip") as archive:
            archive.extractall(package)
        sys.path.insert(0, directory.name)
        cls.addClassCleanup(sys.path.remove, directory.name)
        cls.geometry = importlib.import_module(package_name + ".features.vectorscope.geometry")
        cls.appearance_scope = importlib.import_module(
            package_name + ".features.vectorscope.appearance_scope")
        cls.display = importlib.import_module(package_name + ".features.vectorscope.display")
        cls.settings = importlib.import_module(package_name + ".kernel.settings")

    def test_linear_layout_has_scope_and_exposure_rail(self):
        box = self.geometry.layout("LINEAR", 1200, 900, 1.0)
        self.assertIsNotNone(box)
        for name in ("scope", "exposure"):
            self.assertIn(name, box)
        self.assertNotIn("cr_balance", box)
        self.assertNotIn("yb_balance", box)
        x, y, side, height = box["scope"]
        self.assertEqual(side, height)
        self.assertEqual(side, self.geometry.DEFAULT_LINEAR_SIZE)
        self.assertTrue(self.geometry.contains(box["scope"], (x + 1, y + 1)))
        self.assertLess(box["exposure"][0] + box["exposure"][2], x)

    def test_tone_layout_has_side_by_side_plots_and_edge_controls(self):
        for width, height, scale in ((1200, 900, 1.), (304, 256, 1.), (608, 512, 2.)):
            with self.subTest(width=width, height=height, scale=scale):
                box = self.geometry.layout("TONE", width, height, scale)
                self.assertIsNotNone(box)
                for name in ("appearance", "curve", "curve_title", "exposure",
                             "exposure_track", "fit", "fit_track", "peak"):
                    self.assertIn(name, box)
                appearance, curve = box["appearance"], box["curve"]
                self.assertNotIn("before", box)
                self.assertNotIn("after", box)
                self.assertEqual(appearance[3], curve[3])
                self.assertGreaterEqual(appearance[0], box["rect"][0])
                self.assertEqual(appearance[1], curve[1])
                self.assertAlmostEqual(curve[0] - appearance[0] - appearance[2], 34 * scale)
                self.assertGreaterEqual(curve[2], 84 * scale)
                self.assertGreaterEqual(curve[3], 74 * scale)

                curve_x, curve_y, curve_width, curve_height = curve
                curve_right = curve_x + curve_width
                curve_top = curve_y + curve_height
                self.assertEqual(box["exposure_track"],
                                 ((curve_x, curve_y), (curve_right, curve_y)))
                self.assertEqual(box["fit_track"],
                                 ((curve_right, curve_y), (curve_right, curve_top)))
                self.assertEqual(box["exposure"][1] + box["exposure"][3], curve_y)
                self.assertEqual(box["exposure"][0], curve_x)
                self.assertEqual(box["exposure"][2], curve_width)
                self.assertEqual(box["fit"][0], curve_right)
                self.assertEqual(box["fit"][1], curve_y)
                self.assertEqual(box["fit"][3], curve_height)

                title, peak = box["curve_title"], box["peak"]
                self.assertEqual(title[1], peak[1])
                self.assertEqual(title[3], peak[3])
                self.assertAlmostEqual(title[0] + title[2] + 6 * scale, peak[0])
                self.assertLessEqual(peak[0] + peak[2],
                                     box["rect"][0] + box["rect"][2] - 12 * scale)

    def test_tone_curve_uses_selected_peak_as_both_axis_maxima(self):
        rect = (10., 20., 400., 240.)
        for peak in (500., 1000., 2000., 4000.):
            with self.subTest(peak=peak):
                tone = self.settings.ToneSettings(peak_nits=peak)
                maximum = self.geometry.tone_peak_j(tone)
                point = self.geometry.curve_point(rect, maximum, maximum, maximum)
                self.assertEqual(point, (410., 260.))

    def test_saturation_crossover_uses_appearance_axis_at_each_size(self):
        default = self.settings.ToneSettings().saturation_crossover
        self.assertEqual(default, .5)
        values = (0., default, .99)
        for width, height, scale in ((304, 256, 1.), (1200, 900, 1.), (1600, 1200, 2.)):
            with self.subTest(width=width, height=height, scale=scale):
                rect = self.geometry.layout("TONE", width, height, scale)["appearance"]
                x, y, plot_width, plot_height = rect
                for value in values:
                    marker = self.geometry.saturation_crossover_point(rect, value)
                    self.assertAlmostEqual(marker[0], x + plot_width * value)
                    self.assertEqual(marker[1], y)
                    direction = 1. if value <= .5 else -1.
                    for point in ((marker[0] + direction * 4 * scale, y + plot_height / 2),
                                  (marker[0], marker[1] - 4 * scale)):
                        self.assertTrue(self.geometry.saturation_crossover_hit(rect, value, point, scale))
                    for point in ((marker[0] + direction * 6 * scale, y + plot_height / 2),
                                  (marker[0], y + plot_height + scale)):
                        self.assertFalse(self.geometry.saturation_crossover_hit(rect, value, point, scale))

    def test_saturation_crossover_drag_clamps_to_finite_range(self):
        rect = (10., 20., 180., 90.)
        point = self.geometry.saturation_crossover_point
        drag = self.geometry.drag_saturation_crossover
        default = self.settings.ToneSettings().saturation_crossover
        for start in (0., default, .99):
            for end in (0., default, .99):
                with self.subTest(start=start, end=end):
                    self.assertAlmostEqual(drag(rect, start, point(rect, end)[0] - point(rect, start)[0]), end)
        self.assertEqual(drag(rect, default, -180.), 0.)
        self.assertEqual(drag(rect, default, 180.), .99)
        self.assertEqual(drag(rect, default, 0.), default)

    def test_tone_crossover_uses_normalized_output_lightness_for_position_and_drag(self):
        tone = self.settings.ToneSettings(peak_nits=2000.)
        self.assertEqual(tone.tone_crossover, .45)
        rect = self.geometry.layout("TONE", 1200, 900)["appearance"]
        peak_j = self.geometry.tone_peak_j(tone)
        point = self.geometry.tone_crossover_point
        marker, pinned = point(rect, peak_j, tone.tone_crossover)
        self.assertFalse(pinned)
        expected_y = rect[1] + self.appearance_scope.lightness_position(45., peak_j) * rect[3]
        self.assertAlmostEqual(marker[1], expected_y)
        for target in (.1, .45, 1., 1.4):
            end, _ = point(rect, peak_j, target)
            actual = self.geometry.drag_tone_crossover(
                rect, peak_j, tone.tone_crossover, end[1] - marker[1],
            )
            self.assertAlmostEqual(actual, target)

    def test_tone_crossover_pins_above_peak_and_clamps_drag_to_range(self):
        rect = self.geometry.layout("TONE", 1200, 900)["appearance"]
        peak_j = 1.3
        point = self.geometry.tone_crossover_point
        drag = self.geometry.drag_tone_crossover
        marker, pinned = point(rect, peak_j, 1.4)
        self.assertTrue(pinned)
        self.assertEqual(marker, (rect[0], rect[1] + rect[3]))
        moved = drag(rect, peak_j, 1.4, -12.)
        self.assertGreaterEqual(moved, .1)
        self.assertLess(moved, peak_j)
        self.assertFalse(point(rect, peak_j, moved)[1])
        self.assertEqual(drag(rect, peak_j, .1, -1000.), .1)
        self.assertEqual(drag(rect, peak_j, 1.4, 1000.), 1.4)
        self.assertEqual(drag(rect, 2., .45, 1000.), 1.4)

    def test_appearance_crossover_hit_priority_prefers_tone_handle_at_intersection(self):
        tone = self.settings.ToneSettings(saturation_crossover=0.)
        rect = self.geometry.layout("TONE", 1200, 900)["appearance"]
        marker, pinned = self.geometry.tone_crossover_point(
            rect, self.geometry.tone_peak_j(tone), tone.tone_crossover,
        )
        self.assertFalse(pinned)
        self.assertEqual(
            self.geometry.appearance_control_at(rect, tone, marker, 1.),
            "tone_crossover",
        )
        saturation = self.geometry.saturation_crossover_point(rect, 0.)
        self.assertEqual(
            self.geometry.appearance_control_at(
                rect, tone, (saturation[0], marker[1]), 1.,
            ),
            "tone_crossover",
        )
        other = self.settings.ToneSettings()
        other_marker, _ = self.geometry.tone_crossover_point(
            rect, self.geometry.tone_peak_j(other), other.tone_crossover,
        )
        other_saturation = self.geometry.saturation_crossover_point(rect, other.saturation_crossover)
        self.assertEqual(
            self.geometry.appearance_control_at(
                rect, other, (other_saturation[0], other_marker[1]), 1.,
            ),
            "saturation_crossover",
        )

    def test_appearance_gain_hover_regions_and_horizontal_priority(self):
        for width, height, scale in ((304, 256, 1.), (1200, 900, 1.), (1600, 1200, 2.)):
            with self.subTest(width=width, height=height, scale=scale):
                tone = self.settings.ToneSettings()
                rect = self.geometry.layout("TONE", width, height, scale)["appearance"]
                x, y, plot_width, plot_height = rect
                saturation_x, _ = self.geometry.saturation_crossover_point(
                    rect, tone.saturation_crossover,
                )
                (_, tone_y), _ = self.geometry.tone_crossover_point(
                    rect, self.geometry.tone_peak_j(tone), tone.tone_crossover,
                )
                strips = self.geometry.appearance_gain_strips(rect, tone_y, scale)
                self.assertAlmostEqual(strips["shadow_chroma"][3], plot_height * .12)
                self.assertAlmostEqual(strips["highlight_chroma"][3], plot_height * .12)
                guide_clearance = 6 * scale
                body_y = max(
                    (y + plot_height * .25, y + plot_height * .75),
                    key=lambda candidate: abs(candidate - tone_y),
                )
                muted = (saturation_x - guide_clearance, body_y)
                vivid = (saturation_x + guide_clearance, body_y)
                self.assertEqual(self.geometry.appearance_control_at(rect, tone, muted, scale),
                                 "muted_gain")
                self.assertEqual(self.geometry.appearance_control_at(rect, tone, vivid, scale),
                                 "vivid_gain")

                # Moving vertically through the plot body preserves the horizontal selection.
                right_body = (vivid[0], y + plot_height * .85)
                self.assertEqual(self.geometry.appearance_control_at(rect, tone, right_body, scale),
                                 "vivid_gain")
                top_strip = (vivid[0], y + plot_height * .9)
                self.assertEqual(
                    self.geometry.appearance_control_at(rect, tone, top_strip, scale),
                    "highlight_chroma",
                )
                bottom_strip = (muted[0], y + plot_height * .1)
                self.assertEqual(
                    self.geometry.appearance_control_at(rect, tone, bottom_strip, scale),
                    "shadow_chroma",
                )

                self.assertEqual(
                    self.geometry.appearance_control_at(
                        rect, tone, (saturation_x, y + plot_height * .5), scale,
                    ),
                    "saturation_crossover",
                )
                self.assertEqual(
                    self.geometry.appearance_control_at(rect, tone, (x + 12 * scale, tone_y), scale),
                    "tone_crossover",
                )

    def test_appearance_gain_edge_strips_hide_when_tone_guide_intersects_edge(self):
        rect = self.geometry.layout("TONE", 1200, 900)["appearance"]
        strips = self.geometry.appearance_gain_strips(rect, rect[1] + rect[3] - 3., 1.)
        self.assertNotIn("highlight_chroma", strips)
        self.assertIn("shadow_chroma", strips)

    def test_appearance_draws_background_grid_trace_and_crossover_guides(self):
        tone = self.settings.ToneSettings()
        box = self.geometry.layout("TONE", 1200, 900)
        rect = box["appearance"]
        x, y, width, height = rect
        peak_j = self.geometry.tone_peak_j(tone)
        trace = self.appearance_scope.analyze([[[75., 5., 5., 1.]]], peak_j)
        state = SimpleNamespace(appearance=trace, appearance_status="current",
                                tone_histogram=None)
        draw = Mock()
        display = self.display
        colors = display._PALETTE
        with (patch.multiple(display, _fill=draw.fill, _lines=draw.lines, _circle=draw.circle,
                             _text=draw.text, _draw_trace=draw.trace),
              patch.object(display.localization, "tr", partial(display.localization.tr, locale="en"))):
            display._draw_appearance(box, state, "grade", peak_j, tone, "muted_gain")

        self.assertEqual(draw.fill.call_args_list[0].args, (rect, colors["plot"]))
        self.assertEqual(draw.fill.call_args_list[1].args,
                         ((x, y, width * .5, height), colors["plot_highlight"]))
        self.assertGreater(colors["plot_highlight"][0], colors["plot"][0])
        self.assertEqual(colors["plot_highlight"][3], 1.)
        edge_indicators = [call.args for call in draw.lines.call_args_list
                           if call.args[1] == (*colors["text"][:3], .42)]
        self.assertEqual(edge_indicators, [])
        names = [call[0] for call in draw.mock_calls]
        self.assertLess(names.index("fill", 1), names.index("lines"))
        self.assertLess(names.index("lines"), names.index("trace"))

        grid = draw.lines.call_args_list[0].args
        self.assertEqual(grid[1], colors["grid"])
        reference_y = y + height * .8
        np.testing.assert_allclose(grid[0][6:8], [(x, reference_y), (x + width, reference_y)])
        ticks = [call.args for call in draw.text.call_args_list if call.args[0] == "1"]
        self.assertEqual(len(ticks), 2)
        self.assertTrue(all(tick[4] == colors["muted"] for tick in ticks))

        segments = [call.args[0] for call in draw.lines.call_args_list
                    if call.args[1][:3] == colors["C"][:3]]
        marker_x = x + width * .5
        self.assertEqual(segments[0][:4], [(marker_x, y), (marker_x, y + 5.),
                                           (marker_x, y + 10.), (marker_x, y + 15.)])
        radius = self.geometry.CROSSOVER_HANDLE_RADIUS
        self.assertEqual(set(segments[1]), {(marker_x - radius, y), (marker_x, y + radius),
                                            (marker_x + radius, y), (marker_x, y - radius)})
        circle = draw.circle.call_args.args
        tone_y = self.geometry.tone_crossover_point(rect, peak_j, .45)[0][1]
        self.assertEqual(circle[:2], ((x, tone_y), radius))
        self.assertEqual(circle[2][:3], colors["orange"][:3])
        horizontal = next(call.args[0] for call in draw.lines.call_args_list
                          if call.args[1][:3] == colors["orange"][:3])
        self.assertEqual(horizontal[:4], [(x, tone_y), (x + 5., tone_y),
                                           (x + 10., tone_y), (x + 15., tone_y)])

        appearance_title = next(
            call.args for call in draw.text.call_args_list
            if call.args[0] == "Appearance Distribution"
        )
        with (patch.multiple(display, _fill=draw.fill, _lines=draw.lines,
                             _circle=draw.circle, _text=draw.text,
                             _draw_appearance=Mock(), _draw_tone_curve=Mock(),
                             _slider=Mock()),
              patch.object(display.localization, "tr", partial(display.localization.tr, locale="en"))):
            display._draw_tone(box, None, "grade", self.settings.LinearSettings(),
                                tone, None, None)
        tone_title = next(
            call.args for call in draw.text.call_args_list
            if call.args[0] == "Tone Curve"
        )
        self.assertEqual(appearance_title[3], tone_title[3])
        self.assertEqual(tone_title[3], 10 * box["scale"])

    def test_linear_guides_use_half_opacity_orange_and_neutral_skin_line(self):
        rect = self.geometry.layout("LINEAR", 1200, 900)["scope"]
        center = (rect[0] + rect[2] * .5, rect[1] + rect[3] * .5)
        targets = self.geometry.scope_targets(rect)
        colors = self.display._PALETTE
        lines, circles, labels = Mock(), Mock(), Mock()
        with patch.multiple(self.display, _lines=lines, _circle=circles, _text=labels):
            self.display._guides(rect, 1.)

        orange_half = (*colors["orange"][:3], .5)
        rings = [call.args for call in circles.call_args_list
                 if call.args[1] == rect[2] * .5]
        self.assertEqual(len(rings), 1)
        self.assertEqual(rings[0][2], orange_half)
        self.assertEqual(rings[0][3], 1.)

        for label, point in targets.items():
            with self.subTest(target=label):
                target = next(
                    call.args for call in lines.call_args_list
                    if call.kwargs.get("cache") == ("target", rect, 1., label)
                )
                self.assertEqual(target[1], orange_half)
                text_call = next(call.args for call in labels.call_args_list
                                 if call.args[0] == label)
                self.assertEqual(text_call[4], orange_half)
                self.assertFalse(any(
                    tuple(call.args[0]) == (center, point)
                    for call in lines.call_args_list
                    if isinstance(call.args[0], tuple)
                ), f"Unexpected center-to-{label} target segment")

        skin = next(call.args for call in lines.call_args_list
                    if call.args[1] == (*colors["reference"][:3], .32))
        self.assertEqual(skin[0][0], center)
        self.assertEqual(skin[2], 1.)

    def test_appearance_gain_drag_and_prepared_tone_accept_full_stop_range(self):
        rect = (0., 0., 200., 100.)
        for field in self.geometry.APPEARANCE_GAIN_FIELDS:
            with self.subTest(field=field):
                low, high = self.settings.TONE_CHROMA_LIMITS[field]
                self.assertEqual((low, high), (-4., 4.))
                self.assertEqual(self.geometry.drag_appearance_gain(rect, field, 0., 100.), high)
                self.assertEqual(self.geometry.drag_appearance_gain(rect, field, 0., -100.), low)

        points = np.asarray(((-85., 28., -14.), (72., 24., 31.), (130., -52., 17.)))
        for muted, vivid, shadow, highlight in ((-4., 4., -4., 4.), (4., -4., 4., -4.)):
            with self.subTest(muted=muted, vivid=vivid):
                tone = self.settings.ToneSettings(
                    muted_gain=muted, vivid_gain=vivid,
                    shadow_chroma=shadow, highlight_chroma=highlight,
                )
                prepared = self.geometry.tone_model(tone)
                np.testing.assert_allclose(
                    prepared.inverse_appearance(prepared.forward(points)),
                    points, atol=0., rtol=3e-12,
                )

    def test_moved_panel_obeys_region_bounds_and_dpi(self):
        normal = self.geometry.layout("LINEAR", 900, 660, 1.0, (40, 50))
        scaled = self.geometry.layout("LINEAR", 1800, 1320, 2.0, (40, 50))
        self.assertEqual(tuple(value * 2 for value in normal["scope"]), scaled["scope"])
        self.assertEqual(scaled["rect"][:2], (80, 100))
        compact = self.geometry.layout("LINEAR", 304, 256, 1.0, (-50, 10000))
        x, y, width, height = compact["rect"]
        self.assertEqual((x, y, x + width, y + height), (12, 12, 292, 244))
        self.assertLess(compact["tone_tab"][0] + compact["tone_tab"][2], compact["close"][0])

    def test_tone_corner_resize_anchors_the_opposite_corner_at_scaled_dpi(self):
        scale = 2.
        region = (1600, 1200)
        box = self.geometry.layout("TONE", *region, scale, (100, 100), (600, 400))
        cases = (
            ("w", -80, 0, (-80, 0, 80, 0)),
            ("e", 80, 0, (0, 0, 80, 0)),
            ("s", 0, -80, (0, -80, 0, 80)),
            ("n", 0, 80, (0, 0, 0, 80)),
            ("sw", -80, -80, (-80, -80, 80, 80)),
            ("se", 80, -80, (0, -80, 80, 80)),
            ("nw", -80, 80, (-80, 0, 80, 80)),
            ("ne", 80, 80, (0, 0, 80, 80)),
        )
        self.assertEqual(set(box["resize_grips"]), {case[0] for case in cases})
        x, y, width, height = box["rect"]
        for handle, dx, dy, expected in cases:
            with self.subTest(handle=handle):
                position, size = self.geometry.resize(
                    "TONE", box["rect"], box["bounds"], handle, dx, dy, scale)
                resized = self.geometry.layout("TONE", *region, scale, position, size)
                rx, ry, rw, rh = resized["rect"]
                self.assertEqual((rx - x, ry - y, rw - width, rh - height), expected)

    def test_linear_edge_resize_keeps_scope_square_and_stays_in_region(self):
        box = self.geometry.layout("LINEAR", 900, 660)
        position, size = self.geometry.resize(
            "LINEAR", box["rect"], box["bounds"], "e", 1000, 0, 1.)
        resized = self.geometry.layout("LINEAR", 900, 660, 1., position, size)
        self.assertEqual(box["rect"][0], resized["rect"][0])
        self.assertEqual(resized["scope"][2], resized["scope"][3])
        self.assertGreater(resized["scope"][2], box["scope"][2])
        self.assertLessEqual(resized["rect"][0] + resized["rect"][2], 888.)
        self.assertLessEqual(resized["rect"][1] + resized["rect"][3], 648.)

    def test_compact_default_dimensions(self):
        linear = self.geometry.layout("LINEAR", 1200, 900)
        tone = self.geometry.layout("TONE", 1200, 900)
        self.assertEqual(linear["size"], 300.)
        self.assertEqual(tone["size"], (500., 340.))

    def test_targets_and_handles_start_at_all_four_targets(self):
        box = self.geometry.layout("LINEAR", 1200, 900)
        targets = self.geometry.scope_targets(box["scope"])
        settings = self.settings.LinearSettings()
        handles = self.geometry.handle_positions(box["scope"], settings)
        self.assertEqual(set(handles), {"R", "C", "B", "Y"})
        for label, position in handles.items():
            np.testing.assert_allclose(position, targets[label], rtol=0., atol=1e-6)

    def test_balance_rails_are_available_for_each_color_handle(self):
        box = self.geometry.layout("LINEAR", 1200, 900)
        positions = self.geometry.handle_positions(box["scope"], self.settings.LinearSettings())
        rails = self.geometry.balance_rails(box["scope"], positions, box["scale"])
        self.assertEqual(set(rails), {"R", "C", "B", "Y"})
        for label, rect in rails.items():
            self.assertGreater(rect[2], 0.)
            self.assertGreater(rect[3], rect[2])
            self.assertLessEqual(rect[3], box["scope"][3] * .24)
            point = (rect[0] + rect[2] * .5, rect[1] + rect[3] * .5)
            self.assertEqual(
                self.geometry.linear_handle_at(positions, rails, point, box["scale"]),
                "balance_" + label,
            )
            self.assertEqual(
                self.geometry.linear_handle_at(positions, rails, positions[label], box["scale"]),
                label,
            )

    def test_handle_balance_uses_opposite_signs_on_each_axis(self):
        settings = self.settings.LinearSettings(balance=(.75, -.5))
        self.assertAlmostEqual(self.geometry.handle_balance(settings, "R"), -.75)
        self.assertAlmostEqual(self.geometry.handle_balance(settings, "C"), .75)
        self.assertAlmostEqual(self.geometry.handle_balance(settings, "B"), .5)
        self.assertAlmostEqual(self.geometry.handle_balance(settings, "Y"), -.5)

    def test_clipped_handle_can_be_dragged_along_its_underlying_radius(self):
        scope = self.geometry.layout("LINEAR", 1200, 900)["scope"]
        radius = scope[2] / 2
        center = (scope[0] + radius, scope[1] + radius)
        before = self.settings.LinearSettings(spread=(150., 150.))
        handles = self.geometry.handle_positions(scope, before)
        for point in handles.values():
            self.assertAlmostEqual(math.dist(point, center), radius)

        red = handles["R"]
        dx, dy = (red[0] - center[0]) * -.2, (red[1] - center[1]) * -.2
        spread, heading = self.geometry.drag_handle(scope, "R", 150., 0., dx, dy)
        self.assertLess(spread, 150.)
        self.assertAlmostEqual(heading, 0.)
        after = self.settings.LinearSettings(spread=(spread, 150.), heading=(heading, 0.))
        moved = self.geometry.handle_positions(scope, after)["R"]
        self.assertAlmostEqual(math.dist(moved, red), 0.)

        spread, heading = self.geometry.drag_handle(scope, "R", spread, heading, 30 * dx, 30 * dy)
        after = self.settings.LinearSettings(spread=(spread, 150.), heading=(heading, 0.))
        self.assertLess(math.dist(self.geometry.handle_positions(scope, after)["R"], center),
                        radius)

    def test_handle_drag_updates_shared_heading_with_tangential_motion(self):
        scope = self.geometry.layout("LINEAR", 1200, 900)["scope"]
        radius = scope[2] / 2
        center = (scope[0] + radius, scope[1] + radius)
        before = self.geometry.handle_positions(scope, self.settings.LinearSettings())
        for label, opposite in (("B", "Y"), ("Y", "B")):
            with self.subTest(handle=label):
                x, y = before[label]
                spread, heading = self.geometry.drag_handle(
                    scope, label, 0., 0., -(y - center[1]), x - center[0],
                )
                self.assertAlmostEqual(spread, 0.)
                self.assertAlmostEqual(heading, math.degrees(1.))
                after = self.geometry.handle_positions(
                    scope, self.settings.LinearSettings(heading=(0., heading)),
                )
                self.assertNotEqual(after[opposite], before[opposite])
                self.assertEqual(after["R"], before["R"])
                self.assertEqual(after["C"], before["C"])

    def test_collapsed_handles_have_distinct_hit_locations(self):
        scope = self.geometry.layout("LINEAR", 1200, 900)["scope"]
        settings = self.settings.LinearSettings(spread=(-100., -100.))
        handles = self.geometry.handle_positions(scope, settings)
        for first, second in combinations(handles.values(), 2):
            self.assertGreaterEqual(math.dist(first, second), 12.)

    def test_small_regions_have_no_gizmo_layout(self):
        for stage in ("LINEAR", "TONE"):
            self.assertIsNone(self.geometry.layout(stage, 303, 256))
            self.assertIsNone(self.geometry.layout(stage, 304, 255))
            self.assertIsNotNone(self.geometry.layout(stage, 304, 256))


if __name__ == "__main__":
    unittest.main()
