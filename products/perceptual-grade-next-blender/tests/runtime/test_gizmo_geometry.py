"""Check the installed Gizmo layout and vectorscope handle geometry."""

import importlib
from importlib.resources import files
import math
from pathlib import Path
import sys
import tempfile
import unittest
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
        cls.geometry = importlib.import_module(package_name + ".gizmo_geometry")
        cls.settings = importlib.import_module(package_name + ".kernel.settings")

    def test_linear_layout_has_scope_and_three_rails(self):
        box = self.geometry.layout("LINEAR", 1200, 900, 1.0)
        self.assertIsNotNone(box)
        for name in ("scope", "exposure", "cr_balance", "yb_balance"):
            self.assertIn(name, box)
        x, y, side, height = box["scope"]
        self.assertEqual(side, height)
        self.assertGreater(side, 300)
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

    def test_moved_panel_obeys_region_bounds_and_dpi(self):
        normal = self.geometry.layout("LINEAR", 900, 660, 1.0, (40, 50))
        scaled = self.geometry.layout("LINEAR", 1800, 1320, 2.0, (40, 50))
        self.assertEqual(tuple(value * 2 for value in normal["scope"]), scaled["scope"])
        self.assertEqual(scaled["rect"][:2], (80, 100))
        compact = self.geometry.layout("LINEAR", 304, 256, 1.0, (-50, 10000))
        x, y, width, height = compact["rect"]
        self.assertEqual((x, y, x + width, y + height), (12, 12, 292, 244))
        self.assertLess(compact["tone_tab"][0] + compact["tone_tab"][2], compact["close"][0])

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
