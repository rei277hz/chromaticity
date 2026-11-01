"""Run the private native Compositor capture through packaged Blender."""

import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
import zipfile

from importlib.resources import files


class InstalledCompositorCaptureTests(unittest.TestCase):
    def test_private_capture_preserves_scene_and_pixels(self):
        resources = files("tests.installed")
        blender = Path(str(resources / "blender/blender")).resolve()
        runner = Path(str(resources / "runner.py")).resolve()
        with tempfile.TemporaryDirectory(prefix="pg-next-compositor-capture-") as temporary:
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
            if os.name == "posix" and Path(str(resources / "xvfb")).exists():
                paths = [
                    str(Path(str(resources)).resolve().parents[1]),
                    str(Path(str(resources / "xvfb")).resolve()
                        / "usr/lib/x86_64-linux-gnu"),
                ]
                if environment.get("LD_LIBRARY_PATH"):
                    paths.append(environment["LD_LIBRARY_PATH"])
                environment["LD_LIBRARY_PATH"] = os.pathsep.join(paths)
            report = root / "report.json"
            result = subprocess.run(
                [str(blender), "--background", "--factory-startup",
                 "--disable-autoexec", "--python-exit-code", "1",
                 "--python", str(runner), "--", str(repository), str(report)],
                cwd=root, env=environment, capture_output=True, text=True,
                timeout=900,
            )
            details = result.stdout + "\n" + result.stderr
            if report.is_file():
                details += "\nAcceptance report:\n" + report.read_text()
            self.assertEqual(result.returncode, 0, details)
            data = json.loads(report.read_text())
            self.assertTrue(data["passed"], details)
            self.assertEqual(data["source_shape"], [2, 2, 4])
            self.assertEqual(data["output_shape"], [2, 2, 4])
            self.assertTrue(data["source_verified"])
            self.assertTrue(data["scene_preserved"])
            self.assertTrue(data["registered_operator_finished"])
            self.assertTrue(data["operator_published"])
            self.assertTrue(data["publication_recovery_cleared"])
            self.assertTrue(data["alpha_preserved"])
            self.assertTrue(data["frozen_input_change_rejected"])
