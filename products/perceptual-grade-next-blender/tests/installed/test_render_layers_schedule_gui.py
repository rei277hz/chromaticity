"""Verify native Grade drags reschedule Render Layers compositor output."""

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


class RenderLayersScheduleGuiTests(unittest.TestCase):
    def test_compositor_grade_drag_updates_render_layers_without_rerender(self):
        resources = files("tests.perceptual_grade_blender")
        blender_root = Path(str(resources / "blender")).resolve()
        blender = next((path for path in (
            blender_root / "Blender.app/Contents/MacOS/Blender", blender_root / "blender"
        ) if path.is_file()), None)
        self.assertIsNotNone(blender, "Pinned native Blender artifact missing")
        runner = Path(str(resources / "render_layers_schedule_runner.py")).resolve()
        with tempfile.TemporaryDirectory(prefix="pg-render-layers-schedule-") as directory:
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
                PYTHONDONTWRITEBYTECODE="1",
            )
            with virtual_display(resources, root, env):
                report = root / "report.json"
                process = subprocess.Popen([
                    str(blender), "--factory-startup", "--disable-autoexec",
                    "--enable-event-simulate", "--window-geometry", "0", "0", "1280", "960",
                    "--python-exit-code", "1", "--python", str(runner), "--",
                    str(repository), str(report),
                ], cwd=root, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, start_new_session=True)
                try:
                    output, _ = process.communicate(timeout=150)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    output, _ = process.communicate(timeout=10)
                    self.fail("Render Layers compositor scheduling test timed out\n"
                              + output[-16000:])
                data = json.loads(report.read_text()) if report.exists() else {}
                details = output[-16000:] + "\n" + json.dumps(data, indent=2)
                self.assertEqual(process.returncode, 0, details)
                self.assertTrue(data.get("passed"), details)
                self.assertEqual(data.get("initial_render_count"), 1, details)
                self.assertEqual(data.get("render_count"), 1, details)
                self.assertGreaterEqual(len(set(data["accepted_exposure"])), 4, details)
                self.assertGreaterEqual(len(data["evaluations"]), 3, details)


if __name__ == "__main__":
    unittest.main()
