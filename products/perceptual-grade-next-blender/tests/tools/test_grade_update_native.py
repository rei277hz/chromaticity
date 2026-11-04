"""Exercise the packaged Grade's actual GUI render-worker preflight."""

from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from tools.perceptual_grade.reports.grade_update_timing import run


class GradeRenderPreflightTests(unittest.TestCase):
    def test_pending_grade_is_reconciled_on_main_before_render_worker_evaluates(self):
        with tempfile.TemporaryDirectory(prefix="grade-render-preflight-") as directory:
            report = run(SimpleNamespace(
                output_dir=Path(directory), stage="both", viewport="solid",
                duration=.2, interval_ms=0., warmup=.2, timeout=180.,
                verify_render_preflight=True,
            ))
        self.assertTrue(report["completed"])
        self.assertTrue(report["resource_inventory_preserved"])
        self.assertTrue(report["final_current"])
        receipt, = report["render_preflight"]
        self.assertFalse(receipt["on_main_thread"])
        self.assertTrue(receipt["current"])
        self.assertEqual(receipt["signature"], report["render_expected_signature"])


if __name__ == "__main__":
    unittest.main()
