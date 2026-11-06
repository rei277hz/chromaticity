"""Verify diagnostics capture native Shift-drags across both node editors."""

from importlib.resources import files
import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import unittest
import zipfile

from .gui_support import virtual_display


class DragTraceGuiTests(unittest.TestCase):
    def test_native_shader_and_compositor_drags_share_one_trace(self):
        resources = files("tests.perceptual_grade_blender")
        blender_root = Path(str(resources / "blender")).resolve()
        blender = next((path for path in (
            blender_root / "Blender.app/Contents/MacOS/Blender", blender_root / "blender"
        ) if path.is_file()), None)
        self.assertIsNotNone(blender, "Pinned native Blender artifact missing")
        runner = Path(str(resources / "drag_trace_runner.py")).resolve()
        with tempfile.TemporaryDirectory(prefix="pg-drag-trace-") as directory:
            root = Path(directory)
            repository = root / "repository"
            package = repository / "perceptual_grade"
            package.mkdir(parents=True)
            with zipfile.ZipFile(str(resources / "extension.zip")) as archive:
                archive.extractall(package)
            env = {key: value for key, value in os.environ.items() if key not in {
                "PYTHONPATH", "PYTHONHOME", "BLENDER_USER_SCRIPTS",
                "BLENDER_SYSTEM_SCRIPTS", "BLENDER_SYSTEM_PYTHON",
            }}
            env.update(
                BLENDER_USER_CONFIG=str(root / "config"),
                BLENDER_USER_EXTENSIONS=str(root / "extensions"),
                OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1",
            )
            with virtual_display(resources, root, env):
                report = root / "report.json"
                process = subprocess.Popen([
                    str(blender), "--factory-startup", "--disable-autoexec",
                    "--enable-event-simulate", "--window-geometry", "0", "0", "1280", "960",
                    "--python-exit-code", "1", "--python", str(runner),
                    "--", str(repository), str(report),
                ], cwd=root, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, start_new_session=True)
                try:
                    output, _ = process.communicate(timeout=180)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    output, _ = process.communicate(timeout=10)
                    self.fail("Native drag trace test timed out\n" + output[-16000:])
                data = json.loads(report.read_text()) if report.exists() else {}
                details = output[-16000:] + "\n" + json.dumps(data, indent=2)
                self.assertEqual(process.returncode, 0, details)
                self.assertTrue(data.get("passed"), details)
                self.assertEqual([row["tree_type"] for row in data["drags"]],
                                 ["ShaderNodeTree"] * 3 + ["CompositorNodeTree"] * 3)
                self.assertEqual([row["property"] for row in data["drags"]],
                                 ["pg_linear.exposure", "pg_linear.cr_balance", "pg_tone.fit"] * 2)
                self.assertEqual(len(data["traces"]), 2, details)
                self.assertEqual([row["query"] for row in data["menu_searches"]], [
                    "perceptual grade start drag trace", "perceptual grade stop drag trace",
                    "perceptual grade start drag trace", "perceptual grade stop drag trace",
                ], details)
                self.assertTrue(data["menu_registration_cleanup"], details)
                for drag in data["drags"]:
                    self.assertEqual(drag["requested_hz"], 277, details)
                    self.assertGreaterEqual(drag["distinct_values"], 30, details)
                    self.assertGreaterEqual(drag["accepted_before_release"], 30, details)
                print("Native drag fixture:", json.dumps({
                    "size": data["compositor_size"], "precision": data["compositor_precision"],
                }))
                print("Native drag measurements:", json.dumps(data["drags"]))


if __name__ == "__main__":
    unittest.main()
