"""Check real interactive compositor pixels from the installed extension."""

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


class CompositorGuiTests(unittest.TestCase):
    def test_auto_precision_live_updates_and_saved_kernel_repair(self):
        resources = files("tests.perceptual_grade_blender")
        blender_root = Path(str(resources / "blender")).resolve()
        blender = next((path for path in (
            blender_root / "Blender.app/Contents/MacOS/Blender", blender_root / "blender"
        ) if path.is_file()), None)
        self.assertIsNotNone(blender, "Pinned native Blender artifact missing")
        runner = Path(str(resources / "compositor_runner.py")).resolve()
        with tempfile.TemporaryDirectory(prefix="pg-compositor-") as directory:
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
                for phase in ("exercise", "reload"):
                    report = root / (phase + ".json")
                    process = subprocess.Popen([
                        str(blender), "--factory-startup", "--disable-autoexec",
                        "--window-geometry", "0", "0", "1280", "960",
                        "--python-exit-code", "1", "--python", str(runner), "--",
                        str(repository), str(report), phase,
                    ], cwd=root, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                        text=True, start_new_session=True)
                    try:
                        output, _ = process.communicate(timeout=240 if phase == "exercise" else 60)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid, signal.SIGKILL)
                        output, _ = process.communicate(timeout=10)
                        self.fail("Native compositor " + phase + " timed out\n" + output[-16000:])
                    data = json.loads(report.read_text()) if report.exists() else {}
                    details = output[-16000:] + "\n" + json.dumps(data, indent=2)
                    self.assertEqual(process.returncode, 0, details)
                    self.assertTrue(data.get("passed"), details)
                    if phase == "exercise":
                        self.assertEqual(len(data["rows"]), 13, details)
                        self.assertEqual(data["saved_schema"], [3, 3, 3], details)
                        self.assertEqual(data["automatic_updates"], 9, details)
                    else:
                        self.assertEqual(data["loaded_schema"], [3, 3, 3], details)
                        self.assertEqual(data["repaired_schema"], [6, 6, 6], details)
                        self.assertTrue(data["settings_preserved"], details)
                        self.assertEqual(len(data["rows"]), 2, details)


if __name__ == "__main__":
    unittest.main()
