"""Match actual installed Shader viewport pixels after native slider input."""

from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from tools.perceptual_grade.reports.shader_display_timing import run


class ShaderDisplayNativeTests(unittest.TestCase):
    def test_real_widgets_reach_matching_window_pixels(self):
        with tempfile.TemporaryDirectory(prefix="pg-shader-display-test-") as directory:
            report = run(SimpleNamespace(
                output_dir=Path(directory), baseline=None, sessions=1, samples=2,
                drag_duration=.4, interval_ms=50., capture_interval_ms=5.,
                warmup=.2, timeout=240.,
            ))
        self.assertTrue(report["completed"])
        self.assertTrue(report["summary"]["valid"], report["summary"]["errors"])
        groups = {(row["control"], row["scenario"]): row
                  for row in report["summary"]["groups"]}
        for control in ("exposure", "fit"):
            isolated = groups[control, "isolated"]["counts"]
            self.assertGreaterEqual(isolated["accepted"], 2)
            self.assertEqual(isolated["displayed"], isolated["accepted"])
            self.assertEqual(isolated["missing"], 0)
            self.assertGreater(groups[control, "drag"]["counts"]["accepted"], 0)
        for sample in report["sessions"][0]["samples"]:
            if sample["outcome"] == "displayed":
                self.assertLessEqual(sample["accepted_ns"], sample["capture"]["start_ns"])
                self.assertEqual(len(sample["capture"]["observed"]), 4)


if __name__ == "__main__":
    unittest.main()
