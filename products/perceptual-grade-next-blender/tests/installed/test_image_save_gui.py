"""Exercise native save-dialog eligibility for generated Grade images."""

from importlib.resources import files
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import unittest
import zipfile

from .gui_support import virtual_display


class ImageSaveGuiTests(unittest.TestCase):
    def test_grade_images_are_saved_without_hiding_unsaved_user_images(self):
        resources = files("tests.perceptual_grade_blender")
        blender_name = ("Blender.app/Contents/MacOS/Blender" if sys.platform == "darwin"
                        else "blender")
        blender = Path(str(resources / "blender" / blender_name)).resolve()
        runner = Path(str(resources / "image_save_runner.py")).resolve()
        with tempfile.TemporaryDirectory(prefix="pg-image-save-") as directory:
            root = Path(directory)
            repository = root / "repository"
            package = repository / "perceptual_grade"
            package.mkdir(parents=True)
            with zipfile.ZipFile(str(resources / "extension.zip")) as archive:
                archive.extractall(package)
            env = {
                key: value for key, value in os.environ.items()
                if key not in {"PYTHONPATH", "PYTHONHOME", "BLENDER_USER_SCRIPTS",
                               "BLENDER_SYSTEM_SCRIPTS", "BLENDER_SYSTEM_PYTHON"}
            }
            env.update(
                BLENDER_USER_CONFIG=str(root / "config"),
                BLENDER_USER_EXTENSIONS=str(root / "extensions"),
                OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1",
                PYTHONDONTWRITEBYTECODE="1",
            )
            with virtual_display(resources, root, env):
                report = root / "report.json"
                process = subprocess.Popen(
                    [str(blender), "--factory-startup", "--disable-autoexec",
                     "--window-geometry", "0", "0", "1280", "960",
                     "--python-exit-code", "1", "--python", str(runner), "--",
                     str(repository), str(report)],
                    cwd=root, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, start_new_session=True,
                )
                try:
                    output, _ = process.communicate(timeout=300)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    output, _ = process.communicate(timeout=10)
                    self.fail("Native image-save test timed out\n" + output[-16000:])
                data = json.loads(report.read_text()) if report.exists() else {}
                details = output[-16000:] + "\n" + json.dumps(data, indent=2)
                self.assertEqual(process.returncode, 0, details)
                self.assertTrue(data.get("passed"), details)
                self.assertEqual(data.get("grade_save"), ["FINISHED"], details)
                self.assertEqual(data.get("user_image_save"), ["INTERFACE"], details)
                self.assertTrue(data.get("serialized_pixels_exact"), details)
                self.assertTrue(data.get("save_fallback_repacked"), details)
                self.assertTrue(data.get("invalidation_order_and_failure_checked"), details)
                self.assertEqual(data.get("transaction_diagnostics"), [
                    "transaction presenter failed", "transaction retirement failed",
                    "transaction upload failed",
                ], details)
                self.assertEqual(data.get("packing_failures"), [
                    {"failures": 1, "silent": False, "rollback_clean": True},
                    {"failures": 1, "silent": True, "rollback_clean": True},
                    {"failures": 2, "silent": False, "rollback_clean": False},
                ], details)


if __name__ == "__main__":
    unittest.main()
