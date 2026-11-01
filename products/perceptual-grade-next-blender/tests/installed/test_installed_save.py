"""Check that a modified-Image save failure does not fail the project Save."""

from importlib.resources import files
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile


class InstalledSaveTests(unittest.TestCase):
    def test_unwritable_modified_image_does_not_abort_owned_project_save(self):
        resources = files("tests.installed")
        binary_name = "Blender.app/Contents/MacOS/Blender" if sys.platform == "darwin" else "blender"
        blender = Path(str(resources / "blender" / binary_name)).resolve()
        runner = Path(str(resources / "save_runner.py")).resolve()
        with tempfile.TemporaryDirectory(prefix="pg-next-save-installed-") as directory:
            root = Path(directory)
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
                link_tree = Path(str(resources)).resolve().parents[1]
                abi = link_tree
                system_libraries = Path(str(resources / "xvfb")).resolve() / "usr/lib/x86_64-linux-gnu"
                paths = [str(abi), str(system_libraries)]
                if environment.get("LD_LIBRARY_PATH"):
                    paths.append(environment["LD_LIBRARY_PATH"])
                environment["LD_LIBRARY_PATH"] = os.pathsep.join(paths)
            project = root / "owned-save.blend"
            report = root / "report.json"
            result = subprocess.run(
                [
                    str(blender), "--background", "--factory-startup",
                    "--disable-autoexec", "--python-exit-code", "1",
                    "--python", str(runner), "--", str(repository),
                    str(project), str(report),
                ],
                cwd=root,
                env=environment,
                capture_output=True,
                text=True,
                timeout=300,
            )
            details = result.stdout + "\n" + result.stderr
            if report.is_file():
                details += "\nAcceptance report:\n" + report.read_text()
            self.assertEqual(result.returncode, 0, details)
            data = json.loads(report.read_text())
            self.assertTrue(data["passed"], details)
            self.assertTrue(data["project_exists"], data)
            self.assertEqual(data["save_pre_count"], 1, data)
            self.assertFalse(data["image_output_exists"], data)
            self.assertEqual(data["save_result"], ["FINISHED"], data)
            self.assertIn(data["failed_save_result"], [["CANCELLED"], ["RAISED"]], data)
            self.assertTrue(data["failed_save_hold_released"], data)
            self.assertIn("Unwritable Modified User Image", data["unsaved_image_diagnostics"], data)
            self.assertTrue(data["extension_origin"].endswith("perceptual_grade/__init__.py"))
            print("Installed Next Save acceptance:", json.dumps(data, sort_keys=True), flush=True)
