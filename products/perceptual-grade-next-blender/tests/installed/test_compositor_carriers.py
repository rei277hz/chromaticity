"""Exercise precision cuts on real spatial live-Viewer intermediates."""

from importlib.resources import files
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import unittest

from .gui_support import virtual_display


class CompositorCarrierTests(unittest.TestCase):
    def test_live_parameter_graph_carriers(self):
        resources = files("tests.perceptual_grade_blender")
        blender = Path(str(resources / "blender" / (
            "Blender.app/Contents/MacOS/Blender" if sys.platform == "darwin" else "blender"
        ))).resolve()
        runner = Path(str(resources / "compositor_carriers_runner.py")).resolve()
        with tempfile.TemporaryDirectory(prefix="pg-compositor-carriers-") as directory:
            root = Path(directory)
            report = root / "report.json"
            configuration = root / "configuration.json"
            configuration.write_text(json.dumps({
                "python_paths": [path for path in sys.path if path and Path(path).exists()],
                "report": str(report),
            }))
            environment = {key: value for key, value in os.environ.items() if key not in {
                "PYTHONPATH", "PYTHONHOME", "BLENDER_USER_SCRIPTS",
                "BLENDER_SYSTEM_SCRIPTS", "BLENDER_SYSTEM_PYTHON",
            }}
            environment.update(
                BLENDER_USER_CONFIG=str(root / "config"),
                OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1", PYTHONDONTWRITEBYTECODE="1",
                # llvmpipe has its own pool; OpenMP's limit does not bound it.
                LP_NUM_THREADS="2",
            )
            with virtual_display(resources, root, environment):
                process = subprocess.Popen([
                    str(blender), "--factory-startup", "--disable-autoexec",
                    # These 6x8 probes must not claim every worker CPU while
                    # other native acceptance tests run in parallel.
                    "--threads", "2",
                    "--python-exit-code", "1", "--python", str(runner), "--",
                    str(configuration),
                ], cwd=root, env=environment, stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT, text=True, start_new_session=True)
                try:
                    output, _ = process.communicate(timeout=240)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    output, _ = process.communicate(timeout=10)
                    saved_report = report.read_text() if report.exists() else "No carrier report was written."
                    self.fail("Live carrier probe timed out\n" + output[-20000:]
                              + "\nCarrier report:\n" + saved_report)
            data = json.loads(report.read_text()) if report.exists() else {}
            details = output[-20000:] + "\n" + json.dumps(data, indent=2)
            print(details, flush=True)
            self.assertEqual(process.returncode, 0, details)
            self.assertIsNone(data.get("error"), details)
            self.assertEqual(len(data.get("rows", [])), 18, details)
            for row in data["rows"]:
                if row["variant"] == "carriers":
                    # With reset Color and no active H-K repair, the signed
                    # achromatic coordinate must survive the handoff exactly.
                    for pixel in row["pixels"]:
                        self.assertEqual(pixel[0], pixel[1], row)
                if row["variant"] != "production":
                    continue
                error = max(abs(pixel[channel] - value * 2**.5) / (1 + value * 2**.5)
                            for pixel, value in zip(row["pixels"], (.0001, .01, .18, 1., 16., 64.))
                            for channel in range(3))
                limit = .01 if row["precision"] == "AUTO" else 1e-4
                self.assertLessEqual(error, limit, (row, error))
