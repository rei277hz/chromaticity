"""Keep the current Buck2 fit report aligned with the deployed mapping."""
from importlib.resources import files
import json
import math
import unittest

from color_tools.hdr_color_picker_core import RADIUS_CUBIC, RADIUS_K


class RadiusFitTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = json.loads((files("tests.hdr_picker") / "radius_fit.json").read_text())

    def test_fit_matches_runtime_parameters_and_compactification(self):
        report = self.report
        curve = report["curve"]
        self.assertEqual(report["schema"], 2)
        self.assertEqual(curve["family"], "cubic_tangent_compactification")
        self.assertAlmostEqual(curve["K"], RADIUS_K, delta=1e-10)
        self.assertAlmostEqual(curve["A"], RADIUS_CUBIC, delta=1e-10)
        self.assertGreater(curve["K"], 0.0)
        self.assertGreaterEqual(curve["A"], 0.0)
        self.assertEqual(curve["unit_circle_edge"], "infinite saturation; rejected by decoder")

    def test_fit_workload_and_held_out_scores_are_auditable(self):
        report = self.report
        workload = report["workload"]
        self.assertEqual(workload["seed"], 20260912)
        self.assertEqual(workload["train_count"], 5000)
        self.assertEqual(workload["validation_count"], 5000)
        self.assertEqual(workload["test_count"], 10000)
        self.assertEqual(workload["fit_steps"], 16)
        self.assertEqual(workload["evaluation_steps"], 64)
        self.assertEqual(workload["gamut_weights_percent"], {
            "rec709_sdr": 70, "display_p3_hdr": 20, "rec2020_hdr": 10,
        })
        self.assertEqual(workload["rgb_ranges"], {
            "rec709_sdr": [0.0, 1.0],
            "display_p3_hdr": [0.0, 10.0],
            "rec2020_hdr": [0.0, 10.0],
        })
        self.assertEqual(report["fit"]["optimization"]["method"],
                         "deterministic_2d_grid_then_local_grid_refinement")
        for split in ("validation", "test"):
            score = report["scores"][split]
            self.assertGreater(score["count"], 0)
            self.assertTrue(math.isfinite(score["rms_cv_percent"]))
            self.assertTrue(math.isfinite(score["median_cv_percent"]))
            self.assertTrue(math.isfinite(score["p95_cv_percent"]))
            self.assertGreater(score["rms_cv_percent"], 0.0)


if __name__ == "__main__":
    unittest.main()
