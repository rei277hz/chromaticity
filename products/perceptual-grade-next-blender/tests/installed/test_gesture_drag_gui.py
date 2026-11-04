"""Exercise rapid Grade edits through Blender's actual window event loop."""

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


class GestureDragGuiTests(unittest.TestCase):
    def test_window_events_publish_drag_previews_and_retire_gestures(self):
        resources = files("tests.perceptual_grade_blender")
        blender_root = Path(str(resources / "blender")).resolve()
        blender = next((path for path in (
            blender_root / "Blender.app/Contents/MacOS/Blender", blender_root / "blender"
        ) if path.is_file()), None)
        self.assertIsNotNone(blender, "Pinned native Blender artifact missing")
        runner = Path(str(resources / "gesture_drag_runner.py")).resolve()
        with tempfile.TemporaryDirectory(prefix="pg-gesture-drag-") as directory:
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
                    self.fail("Native drag event test timed out\n" + output[-16000:])
                data = json.loads(report.read_text()) if report.exists() else {}
                details = output[-16000:] + "\n" + json.dumps(data, indent=2)
                self.assertEqual(process.returncode, 0, details)
                self.assertTrue(data.get("passed"), details)
                self.assertGreaterEqual(data.get("lagging_publications", 0), 2, details)
                self.assertGreaterEqual(data.get("distinct_parameter_images", 0), 2, details)
                self.assertGreaterEqual(data.get("native_slider_changes", 0), 30, details)
                self.assertEqual(data.get("drag_undo_pushes"), [], details)
                self.assertEqual(data.get("undo_exposure"), 0.0, details)
                self.assertEqual(data.get("cancellations"), ["ESC", "RIGHTMOUSE"], details)
                self.assertEqual(data.get("deletions"), ["armed", "active"], details)


if __name__ == "__main__":
    unittest.main()
