"""Check the packaged Render gate through native terminal receipts."""

from importlib.resources import files
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile


class InstalledRenderTests(unittest.TestCase):
    def test_render_hold_waits_for_matching_terminal_receipt(self):
        resources = files("tests.installed")
        blender = Path(str(resources / "blender" / "blender")).resolve()
        runner = Path(str(resources / "runner.py")).resolve()
        with tempfile.TemporaryDirectory(prefix="pg-next-render-installed-") as temporary:
            root = Path(temporary)
            repository = root / "repository"
            package = repository / "perceptual_grade"
            package.mkdir(parents=True)
            with zipfile.ZipFile(str(resources / "extension.zip")) as archive:
                archive.extractall(package)
            environment = {
                key: value for key, value in os.environ.items()
                if key not in {
                    "PYTHONPATH", "PYTHONHOME", "BLENDER_USER_SCRIPTS",
                    "BLENDER_SYSTEM_SCRIPTS", "BLENDER_SYSTEM_PYTHON",
                }
            }
            environment.update(
                BLENDER_USER_CONFIG=str(root / "config"),
                BLENDER_USER_EXTENSIONS=str(root / "extensions"),
                OPENBLAS_NUM_THREADS="1",
                OMP_NUM_THREADS="1",
                PYTHONDONTWRITEBYTECODE="1",
            )
            if sys.platform == "linux":
                xvfb_root = Path(str(resources / "xvfb")).resolve()
                abi_root = Path(str(resources / "bpy_abi")).resolve()
                environment["LD_LIBRARY_PATH"] = os.pathsep.join((
                    str(xvfb_root / "usr/lib/x86_64-linux-gnu"),
                    str(abi_root / "usr/lib/x86_64-linux-gnu"),
                ))
            report = root / "report.json"
            result = subprocess.run(
                [str(blender), "--background", "--factory-startup",
                 "--disable-autoexec", "--python-exit-code", "1",
                 "--python", str(runner), "--", str(repository), str(report)],
                cwd=root, env=environment, capture_output=True, text=True,
                timeout=300,
            )
            details = result.stdout + "\n" + result.stderr
            if report.is_file():
                details += "\nAcceptance report:\n" + report.read_text()
            self.assertEqual(result.returncode, 0, details)
            data = json.loads(report.read_text())
            self.assertTrue(data["passed"], details)
            self.assertEqual(data["blender"], [5, 2, 2])
            self.assertEqual(data["invocation_count"], 2)
            self.assertTrue(data["wrong_scene_receipt_rejected"])
            self.assertTrue(data["completed_hold_released"])
            self.assertTrue(data["cancelled_hold_released"])
            self.assertTrue(data["duplicate_terminal_rejected"])
            print("Installed Next Render acceptance:", json.dumps(data, sort_keys=True), flush=True)
