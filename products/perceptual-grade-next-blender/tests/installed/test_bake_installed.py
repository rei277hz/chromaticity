"""Run native Image, UV, Compositor, and Stack bake acceptance checks."""

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


class BakeInstalledTests(unittest.TestCase):
    def test_native_bakes_and_state_transitions(self):
        resources = files("tests.perceptual_grade_blender")
        blender_root = Path(str(resources / "blender")).resolve()
        blender = next((path for path in (
            blender_root / "Blender.app/Contents/MacOS/Blender",
            blender_root / "blender",
        ) if path.is_file()), None)
        self.assertIsNotNone(blender, "Pinned native Blender artifact missing")
        runner = Path(str(resources / "bake_runner.py")).resolve()
        with tempfile.TemporaryDirectory(prefix="pg-bake-installed-") as directory:
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
                process = subprocess.Popen(
                    [str(blender), "--background", "--factory-startup", "--disable-autoexec",
                     "--python-exit-code", "1", "--python", str(runner), "--",
                     str(repository), str(report)],
                    cwd=root, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, start_new_session=True,
                )
                try:
                    output, _ = process.communicate(timeout=600)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    output, _ = process.communicate(timeout=10)
                    self.fail("Native bake test timed out\n" + output[-20000:])
                data = json.loads(report.read_text()) if report.exists() else {}
                details = output[-20000:] + "\n" + json.dumps(data, indent=2)
                self.assertEqual(process.returncode, 0, details)
                self.assertTrue(data.get("passed"), details)
                self.assertEqual(data.get("domains"), ["IMAGE", "UV", "COMPOSITOR"], details)
                self.assertTrue(data.get("stack"), details)
                self.assertTrue(data.get("packed_float"), details)
                self.assertTrue(data.get("live_restored"), details)
                self.assertTrue(data.get("shared_rebake"), details)
                self.assertTrue(data.get("stale_discarded"), details)
                self.assertTrue(data.get("wrapper_independent"), details)
                self.assertTrue(data.get("wrapper_recovery"), details)
                self.assertTrue(data.get("grade_edit_live_fallback"), details)
                self.assertTrue(data.get("identity_match"), details)
                self.assertTrue(data.get("baked_conversion"), details)
                self.assertTrue(data.get("render_admission"), details)
                self.assertTrue(data.get("source_edit_fallback"), details)
                self.assertTrue(data.get("persistence"), details)
                self.assertTrue(data.get("teardown"), details)


if __name__ == "__main__":
    unittest.main()
