"""Exercise gesture undo boundaries in a native Blender window."""

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


class GestureUndoGuiTests(unittest.TestCase):
    def test_gesture_pushes_independent_undo_states(self):
        resources = files("tests.perceptual_grade_blender")
        blender_root = Path(str(resources / "blender")).resolve()
        blender = next(
            (path for path in (blender_root / "Blender.app/Contents/MacOS/Blender",
                               blender_root / "blender") if path.is_file()),
            None,
        )
        self.assertIsNotNone(blender, "Pinned native Blender artifact missing")
        runner = Path(str(resources / "gesture_undo_runner.py")).resolve()
        with tempfile.TemporaryDirectory(prefix="pg-gesture-undo-") as directory:
            root = Path(directory)
            repository = root / "repository"
            package = repository / "perceptual_grade"
            package.mkdir(parents=True)
            with zipfile.ZipFile(str(resources / "extension.zip")) as archive:
                archive.extractall(package)

            env = {
                key: value
                for key, value in os.environ.items()
                if key not in {
                    "PYTHONPATH",
                    "PYTHONHOME",
                    "BLENDER_USER_SCRIPTS",
                    "BLENDER_SYSTEM_SCRIPTS",
                    "BLENDER_SYSTEM_PYTHON",
                }
            }
            env.update(
                BLENDER_USER_CONFIG=str(root / "config"),
                BLENDER_USER_EXTENSIONS=str(root / "extensions"),
                OPENBLAS_NUM_THREADS="1",
                OMP_NUM_THREADS="1",
            )
            with virtual_display(resources, root, env):
                report = root / "report.json"
                command = [
                    str(blender),
                    "--factory-startup",
                    "--disable-autoexec",
                    "--enable-event-simulate",
                    "--window-geometry",
                    "0",
                    "0",
                    "1280",
                    "960",
                    "--python-exit-code",
                    "1",
                    "--python",
                    str(runner),
                    "--",
                    str(repository),
                    str(report),
                ]
                process = subprocess.Popen(
                    command,
                    cwd=root,
                    env=env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    start_new_session=True,
                )
                try:
                    output, _ = process.communicate(timeout=300)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    output, _ = process.communicate(timeout=10)
                    details = report.read_text() if report.exists() else "No report written"
                    self.fail("Native gesture undo test timed out\n" + output[-16000:]
                              + "\n" + details)
                data = json.loads(report.read_text()) if report.exists() else {}
                details = output[-16000:] + "\n" + json.dumps(data, indent=2)
                if (root / "xvfb.log").exists():
                    details += "\nXvfb:\n" + (root / "xvfb.log").read_text()[-8000:]
                crash = Path(tempfile.gettempdir()) / "blender.crash.txt"
                if process.returncode and crash.is_file():
                    details += "\nNative crash:\n" + crash.read_text(errors="replace")[-24000:]
                self.assertEqual(process.returncode, 0, details)
                self.assertTrue(data.get("passed"), details)
                self.assertEqual(data.get("push_results"), [True] * 6, details)
                self.assertEqual(data.get("fallback_pool"), {
                    "repeated_reconciliation": True,
                    "shared_readers_and_removal": True,
                    "pending_live_pending": True,
                    "save_load": True,
                }, details)
                self.assertGreaterEqual(data.get("cycle_checks", 0), 20, details)
                self.assertEqual(data.get("undo_states"), [
                    {"grade": "present", "exposure": 0.0},
                    {"grade": "present", "exposure": 0.625},
                    {"grade": "present", "exposure": 0.0},
                ], details)


if __name__ == "__main__":
    unittest.main()
