import json
from pathlib import Path
import tempfile
import unittest

from tools.perceptual_grade.reports.stack_lut_timing_report import (
    summarize_drags,
    summary,
    validate_profile,
    write_report,
)


class StackLUTTimingReportTests(unittest.TestCase):
    def test_summary_uses_nearest_rank_and_empty_is_missing(self):
        self.assertIsNone(summary([]))
        self.assertEqual(summary(range(1, 101)), {
            "count": 100,
            "p50_seconds": 50,
            "p95_seconds": 95,
        })

    def test_summary_ignores_missing_preview_samples(self):
        rows = [
            {
                "preview_seconds_after_last_update": 0.2,
                "release_to_full_seconds": 1.4,
                "preview_request_to_helper_submit_seconds": 0.1,
                "full_request_to_helper_submit_seconds": 0.8,
                "preview_texture_allocation_seconds": 0.03,
                "preview_worker_between_batches_seconds": 0.5,
                "full_install_seconds": 0.9,
            },
            {
                "preview_seconds_after_last_update": None,
                "release_to_full_seconds": 1.6,
                "preview_request_to_helper_submit_seconds": None,
                "full_request_to_helper_submit_seconds": 0.9,
                "preview_texture_allocation_seconds": 0.04,
                "preview_worker_between_batches_seconds": 0.7,
                "full_install_seconds": 1.0,
            },
        ]
        report = summarize_drags(rows)
        self.assertEqual(report["preview_seconds_after_last_update"]["count"], 1)
        self.assertEqual(report["release_to_full_seconds"]["count"], 2)
        self.assertEqual(report["preview_request_to_helper_submit_seconds"]["count"], 1)
        self.assertEqual(report["full_request_to_helper_submit_seconds"]["count"], 2)
        self.assertEqual(report["preview_texture_allocation_seconds"]["count"], 2)
        self.assertEqual(report["preview_worker_between_batches_seconds"]["count"], 2)
        self.assertEqual(report["full_install_seconds"]["count"], 2)

    def test_missing_preview_is_reported_without_a_latency_gate(self):
        report = {
            "blender": "Blender test",
            "gpu": {"renderer": "llvmpipe"},
            "node_tree": "shader",
            "drags": [{
                "updates": 20,
                "lut_requests": 20,
                "preview_installed": False,
                "preview_seconds_after_last_update": None,
                "release_to_full_seconds": 1.2,
            }],
        }
        with tempfile.TemporaryDirectory() as directory:
            write_report(directory, report)
            output = Path(directory)
            saved = json.loads((output / "report.json").read_text())
            markdown = (output / "report.md").read_text()
        self.assertFalse(saved["drags"][0]["preview_installed"])
        self.assertIn("not observed", markdown)
        self.assertIn("does not include a Blender timer interval", markdown)
        self.assertIn("No latency threshold is applied", markdown)

    def test_profile_validation_accepts_default_shape_and_rejects_invalid_counts(self):
        validate_profile(3, 3, 20, 50.0, 3.0, 900.0)
        for values in ((0, 3, 20, 50.0, 3.0, 900.0),
                       (3, 1, 1, 50.0, 3.0, 900.0),
                       (3, 3, 20, 0.0, 3.0, 900.0),
                       (3, 3, 20, 50.0, -1.0, 900.0)):
            with self.subTest(values=values), self.assertRaises(ValueError):
                validate_profile(*values)


if __name__ == "__main__":
    unittest.main()
