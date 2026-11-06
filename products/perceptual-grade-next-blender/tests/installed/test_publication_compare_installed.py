"""Check all publication strategies through the installed Blender extension."""

from importlib.resources import files
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile

from .gui_support import virtual_display


class PublicationCompareInstalledTests(unittest.TestCase):
    def test_shader_and_compositor_nodes_publish_their_helper_texture(self):
        resources = files("tests.perceptual_grade_blender")
        blender_name = ("Blender.app/Contents/MacOS/Blender" if sys.platform == "darwin"
                        else "blender")
        blender = Path(str(resources / "blender" / blender_name)).resolve()
        runner = Path(str(resources / "publication_compare_runner.py")).resolve()
        with tempfile.TemporaryDirectory(prefix="pg-publication-compare-") as directory:
            root = Path(directory)
            repository = root / "repository"
            package = repository / "grade_publication_compare"
            package.mkdir(parents=True)
            with zipfile.ZipFile(resources / "publication_compare.zip") as archive:
                archive.extractall(package)
            env = {key: value for key, value in os.environ.items()
                   if key not in {"PYTHONPATH", "PYTHONHOME", "BLENDER_USER_SCRIPTS",
                                  "BLENDER_SYSTEM_SCRIPTS", "BLENDER_SYSTEM_PYTHON"}}
            env.update(BLENDER_USER_CONFIG=str(root / "config"),
                       BLENDER_USER_EXTENSIONS=str(root / "extensions"),
                       PYTHONDONTWRITEBYTECODE="1")
            report = root / "report.json"
            with virtual_display(resources, root, env):
                result = subprocess.run(
                    [str(blender), "--factory-startup", "--disable-autoexec",
                     "--window-geometry", "0", "0", "1280", "960",
                     "--python-exit-code", "1", "--python", str(runner), "--",
                     str(repository), str(report)],
                    cwd=root, env=env, capture_output=True, text=True, timeout=180,
                )
            output = result.stdout + "\n" + result.stderr
            self.assertEqual(result.returncode, 0, output)
            data = json.loads(report.read_text())
            self.assertTrue(data["passed"], data)
            self.assertEqual([row["variant"] for row in data["rows"]],
                             ["versioned", "versioned", "original", "original",
                              "banked", "banked"])
            self.assertEqual([row["image_replaced"] for row in data["rows"]],
                             [True, True, False, False, True, True])
            self.assertEqual([row["multiplier"] for row in data["rows"]],
                             [2.0, 2.0, 2.0, 2.0, 2.0, 2.0])
            self.assertTrue(all(row["reader_bindings_stable"] for row in data["rows"]
                                if row["variant"] == "banked"))


if __name__ == "__main__":
    unittest.main()
