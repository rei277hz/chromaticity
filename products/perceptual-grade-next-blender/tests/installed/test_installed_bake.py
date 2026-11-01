"""Run a direct still-Image Shader Bake through the packaged Next extension."""

from importlib.resources import files
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile


class InstalledBakeTests(unittest.TestCase):
    def test_direct_still_image_shader_bake_publishes_native_result(self):
        resources = files("tests.installed")
        binary_name = "Blender.app/Contents/MacOS/Blender" if sys.platform == "darwin" else "blender"
        blender = Path(str(resources / "blender" / binary_name)).resolve()
        runner = Path(str(resources / "runner.py")).resolve()
        with tempfile.TemporaryDirectory(prefix="pg-next-bake-installed-") as directory:
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
            report = root / "report.json"
            result = subprocess.run(
                [
                    str(blender), "--background", "--factory-startup",
                    "--disable-autoexec", "--python-exit-code", "1",
                    "--python", str(runner), "--", str(repository), str(report),
                ],
                cwd=root,
                env=environment,
                capture_output=True,
                text=True,
                timeout=900,
            )
            details = result.stdout + "\n" + result.stderr
            if report.is_file():
                details += "\nAcceptance report:\n" + report.read_text()
            self.assertEqual(result.returncode, 0, details)
            data = json.loads(report.read_text())
            self.assertTrue(data["passed"], details)
            self.assertTrue(data["extension_origin"].endswith("perceptual_grade/__init__.py"))
            self.assertEqual(data["evaluator"], "native_grade_graph")
            self.assertEqual(data["published_rgba_shape"], [1, 2, 4])
            self.assertTrue(data["pixels_changed"])
            self.assertTrue(data["alpha_preserved"])
            self.assertTrue(data["publication_recovery_cleared"])
            self.assertEqual(data["uv_evaluator"], "native_grade_graph")
            self.assertEqual(data["uv_published_rgba_shape"], [4, 4, 4])
            self.assertGreater(data["uv_covered_pixels"], 0)
            self.assertGreater(data["uv_uncovered_pixels"], 0)
            self.assertTrue(data["uv_source_unchanged"])
            self.assertTrue(data["uv_material_unchanged"])
            self.assertTrue(data["uv_registered_operator_finished"])
            self.assertTrue(data["preflight_failure_cancelled"])
            self.assertEqual(data["preflight_failure_orphans"], [])
            self.assertTrue(data["admitted_failure_cancelled"])
            self.assertEqual(data["admitted_failure_orphans"], [])
            self.assertEqual(data["admitted_failure_phase"], "cancelled")
            self.assertTrue(data["selected_failure_preserved_target"], data)
            print("Installed Next Bake acceptance:", json.dumps(data, sort_keys=True), flush=True)
