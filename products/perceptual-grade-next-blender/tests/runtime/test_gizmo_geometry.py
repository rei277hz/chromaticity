"""Check the installed Gizmo layout and vectorscope handle geometry."""

import importlib
from functools import partial
from importlib.resources import files
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

    def test_linear_layout_has_scope_and_three_rails(self):
        box = self.geometry.layout("LINEAR", 1200, 900, 1.0)
        self.assertIsNotNone(box)
        for name in ("scope", "exposure", "cr_balance", "yb_balance"):
            self.assertIn(name, box)
        x, y, side, height = box["scope"]
        self.assertEqual(side, height)
        self.assertEqual(side, self.geometry.DEFAULT_LINEAR_SIZE)
        self.assertTrue(self.geometry.contains(box["scope"], (x + 1, y + 1)))
        self.assertLess(box["exposure"][0] + box["exposure"][2], x)
        self.assertGreater(box["cr_balance"][0], x + side)
        self.assertLess(box["yb_balance"][1] + box["yb_balance"][3], y)

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
                self.assertAlmostEqual(appearance[2], 2 * appearance[3])
                self.assertGreaterEqual(appearance[0], box["rect"][0])
                self.assertLess(appearance[0] + appearance[2], curve[0])
                self.assertAlmostEqual(appearance[1] + appearance[3], curve[1] + curve[3])
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
                self.assertEqual(strips["shadow_chroma"][3], 5 * scale)
                self.assertEqual(strips["highlight_chroma"][3], 5 * scale)
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
                right_body = (vivid[0], y + plot_height - 6 * scale)
                self.assertEqual(self.geometry.appearance_control_at(rect, tone, right_body, scale),
                                 "vivid_gain")
                top_strip = (vivid[0], y + plot_height - 2 * scale)
                self.assertEqual(
                    self.geometry.appearance_control_at(rect, tone, top_strip, scale),
                    "highlight_chroma",
                )
                bottom_strip = (muted[0], y + 2 * scale)
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
        state = SimpleNamespace(appearance=trace, appearance_status="current")
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

    def test_targets_and_handles_start_at_red_and_blue_targets(self):
        box = self.geometry.layout("LINEAR", 1200, 900)
        targets = self.geometry.scope_targets(box["scope"])
        settings = self.settings.LinearSettings()
        handles = self.geometry.handle_positions(box["scope"], settings)
        for axis, target in (("cr", targets["R"]), ("yb", targets["B"])):
            self.assertAlmostEqual(handles[axis][0], target[0], places=6)
            self.assertAlmostEqual(handles[axis][1], target[1], places=6)

    def test_clipped_handle_can_be_dragged_along_its_underlying_radius(self):
        scope = self.geometry.layout("LINEAR", 1200, 900)["scope"]
        radius = scope[2] / 2
        center = (scope[0] + radius, scope[1] + radius)
        before = self.settings.LinearSettings(spread=(150., 150.))
        handles = self.geometry.handle_positions(scope, before)
        for point in handles.values():
            self.assertAlmostEqual(math.dist(point, center), radius)

        red = handles["cr"]
        dx, dy = (red[0] - center[0]) * -.2, (red[1] - center[1]) * -.2
        spread, heading = self.geometry.drag_handle(scope, "cr", 150., 0., dx, dy)
        self.assertLess(spread, 150.)
        self.assertAlmostEqual(heading, 0.)
        after = self.settings.LinearSettings(spread=(spread, 150.), heading=(heading, 0.))
        moved = self.geometry.handle_positions(scope, after)["cr"]
        self.assertAlmostEqual(math.dist(moved, red), 0.)

        spread, heading = self.geometry.drag_handle(scope, "cr", spread, heading, 30 * dx, 30 * dy)
        after = self.settings.LinearSettings(spread=(spread, 150.), heading=(heading, 0.))
        self.assertLess(math.dist(self.geometry.handle_positions(scope, after)["cr"], center),
                        radius)

    def test_handle_drag_updates_heading_with_tangential_motion(self):
        scope = self.geometry.layout("LINEAR", 1200, 900)["scope"]
        radius = scope[2] / 2
        center = (scope[0] + radius, scope[1] + radius)
        blue = self.geometry.scope_targets(scope)["B"]
        spread, heading = self.geometry.drag_handle(
            scope, "yb", 0., 0., -(blue[1] - center[1]), blue[0] - center[0],
        )
        self.assertAlmostEqual(spread, 0.)
        self.assertAlmostEqual(heading, math.degrees(1.))

    def test_collapsed_handles_have_distinct_hit_locations(self):
        scope = self.geometry.layout("LINEAR", 1200, 900)["scope"]
        settings = self.settings.LinearSettings(spread=(-100., -100.))
        handles = self.geometry.handle_positions(scope, settings)
        self.assertGreaterEqual(math.dist(handles["cr"], handles["yb"]), 12.)

    def test_small_regions_have_no_gizmo_layout(self):
        for stage in ("LINEAR", "TONE"):
            self.assertIsNone(self.geometry.layout(stage, 303, 256))
            self.assertIsNone(self.geometry.layout(stage, 304, 255))
            self.assertIsNotNone(self.geometry.layout(stage, 304, 256))


if __name__ == "__main__":
    unittest.main()
