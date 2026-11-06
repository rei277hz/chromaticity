"""Exercise native drag observation and publication after actual file loads."""

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


class GestureReloadGuiTests(unittest.TestCase):
    def test_loaded_windows_publish_drag_previews_and_restore_observers(self):
        resources = files("tests.perceptual_grade_blender")
        blender_root = Path(str(resources / "blender")).resolve()
        blender = next((path for path in (
            blender_root / "Blender.app/Contents/MacOS/Blender", blender_root / "blender"
        ) if path.is_file()), None)
        self.assertIsNotNone(blender, "Pinned native Blender artifact missing")
        runner = Path(str(resources / "gesture_reload_runner.py")).resolve()
        with tempfile.TemporaryDirectory(prefix="pg-gesture-reload-") as directory:
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
                    output, _ = process.communicate(timeout=240)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    output, _ = process.communicate(timeout=10)
                    self.fail("Native reload drag test timed out\n" + output[-16000:])
                data = json.loads(report.read_text()) if report.exists() else {}
                details = output[-16000:] + "\n" + json.dumps(data, indent=2)
                self.assertEqual(process.returncode, 0, details)
                self.assertTrue(data.get("passed"), details)
                self.assertEqual([item["mode"] for item in data["drags"]],
                                 ["MATERIAL", "RENDERED", "COMPOSITOR"], details)
                for result in data["drags"]:
                    self.assertGreaterEqual(result["lagging_publications"], 2, details)
                    self.assertGreaterEqual(result["distinct_parameter_images"], 2, details)
                    self.assertGreaterEqual(result["native_slider_changes"], 30, details)
                self.assertEqual(len(data["loads"]), 3, details)
                self.assertEqual(data["router_before_repair"], [True, False, True], details)
                for loaded in data["loads"]:
                    self.assertTrue(loaded["router_timer"], details)
                    self.assertEqual(loaded["observer_count"], 0, details)
                    self.assertGreater(loaded["restored_token"], loaded["previous_token"], details)
                self.assertTrue(data["loads"][-1]["pending_router_guarded"], details)
                self.assertTrue(data["disabled_router_removed"], details)
                self.assertTrue(data["reenabled_router_restored"], details)


if __name__ == "__main__":
    unittest.main()
