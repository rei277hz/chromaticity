"""Verify native Compositor dragging reaches the actual live Viewer display."""

from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from tools.perceptual_grade.reports.compositor_display_timing import run


class CompositorDisplayNativeTests(unittest.TestCase):
    def test_real_widgets_reach_live_viewer_pixels(self):
        with tempfile.TemporaryDirectory(prefix="pg-compositor-display-test-") as directory:
            report = run(SimpleNamespace(
                output_dir=Path(directory), baseline=None, sessions=1,
                drag_duration=.6, interval_ms=50., capture_interval_ms=5.,
                warmup=.2, timeout=240.,
            ))
        self.assertTrue(report["completed"])
        self.assertTrue(report["summary"]["valid"], report["summary"]["errors"])
        self.assertEqual(report["profile"]["scenarios"], ["drag"])
        session = report["sessions"][0]
        groups = {row["control"]: row for row in report["summary"]["groups"]}
        for control in ("exposure", "fit"):
            self.assertGreater(groups[control]["counts"]["accepted"], 0)
            self.assertGreater(groups[control]["counts"]["displayed"], 0)
            self.assertEqual(groups[control]["counts"]["missing"], 0)
            final = [sample for sample in session["samples"] if sample["control"] == control][-1]
            self.assertEqual(final["outcome"], "displayed")
        for sample in session["samples"]:
            if sample["outcome"] == "displayed":
                self.assertLessEqual(sample["accepted_ns"], sample["capture"]["start_ns"])
                self.assertEqual(len(sample["capture"]["observed"]), 4)


if __name__ == "__main__":
    unittest.main()
