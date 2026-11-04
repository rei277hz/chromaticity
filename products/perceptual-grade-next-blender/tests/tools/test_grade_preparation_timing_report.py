import json
from pathlib import Path
import tempfile
import unittest

from tools.perceptual_grade.reports.grade_preparation_timing_report import (
    summarize,
    summary,
    write_report,
)


class GradePreparationTimingReportTests(unittest.TestCase):
    def test_summary_uses_nearest_rank_and_empty_is_missing(self):
        self.assertIsNone(summary([]))
        self.assertEqual(summary(range(1, 101)), {
            "count": 100,
            "p50_seconds": 50,
            "p95_seconds": 95,
        })

    def test_summarize_separates_components_builds_and_uploads(self):
        report = {"samples": [
            {
                "preparation": {"linear": 0.1, "tone": 0.2, "boundary": 0.01, "join": 0.21},
                "preparation_total_seconds": 0.23,
                "kernel_build": {"ShaderNodeTree": 0.5, "CompositorNodeTree": 0.6},
                "texture_uploads": [{"seconds": 0.05}],
            },
            {
                "preparation": {"linear": 0.2, "tone": 0.3, "boundary": 0.01, "join": 0.31},
                "preparation_total_seconds": 0.34,
                "kernel_build": {"ShaderNodeTree": 0.7, "CompositorNodeTree": 0.8},
                "texture_uploads": [{"seconds": 0.07}],
            },
        ]}
        result = summarize(report)
        self.assertEqual(result["preparation_tone"]["p50_seconds"], 0.2)
        self.assertEqual(result["ShaderNodeTree_kernel_build"]["count"], 2)
        self.assertEqual(result["texture_upload"]["p95_seconds"], 0.07)

    def test_report_has_no_performance_threshold(self):
        report = {"blender": "test", "samples": [{
            "tone": "reset",
            "preparation": {"linear": 0.01, "tone": 0.02, "boundary": 0.0, "join": 0.02},
            "preparation_total_seconds": 0.03,
            "kernel_build": {"ShaderNodeTree": 0.2, "CompositorNodeTree": 0.3},
            "texture_uploads": [],
        }]}
        with tempfile.TemporaryDirectory() as directory:
            write_report(directory, report)
            output = Path(directory)
            saved = json.loads((output / "report.json").read_text())
            markdown = (output / "report.md").read_text()
        self.assertEqual(saved["summary"]["preparation_total"]["count"], 1)
        self.assertIn("No performance gate is applied", markdown)


if __name__ == "__main__":
    unittest.main()
