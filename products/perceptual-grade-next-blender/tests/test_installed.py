from importlib.resources import files
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile


class InstalledExtensionTests(unittest.TestCase):
    def test_extension_hooks_in_blender_background(self):
        resources = files("tests.perceptual_grade_blender")
        blender_name = ("Blender.app/Contents/MacOS/Blender" if sys.platform == "darwin"
                        else "blender")
        blender = Path(str(resources / "blender" / blender_name)).resolve()
        runner = Path(str(resources / "runner.py")).resolve()
        with tempfile.TemporaryDirectory(prefix="perceptual-grade-") as temp:
            root = Path(temp)
            repository = root / "repository"
            extension_dir = repository / "perceptual_grade"
            extension_dir.mkdir(parents=True)
            with zipfile.ZipFile(resources / "extension.zip") as archive:
                archive.extractall(extension_dir)

            env = {key: value for key, value in os.environ.items()
                   if key not in {"PYTHONPATH", "PYTHONHOME", "BLENDER_USER_SCRIPTS",
                                  "BLENDER_SYSTEM_SCRIPTS", "BLENDER_SYSTEM_PYTHON"}}
            env.update(BLENDER_USER_CONFIG=str(root / "config"),
                       BLENDER_USER_EXTENSIONS=str(root / "extensions"),
                       PYTHONDONTWRITEBYTECODE="1")
            report = root / "report.json"
            result = subprocess.run(
                [str(blender), "--background", "--factory-startup", "--disable-autoexec",
                 "--python-exit-code", "1", "--python", str(runner), "--",
                 str(repository), str(report)],
                cwd=root, env=env, capture_output=True, text=True, timeout=180,
            )
            output = result.stdout + "\n" + result.stderr
            self.assertEqual(result.returncode, 0, output)
            self.assertTrue(report.is_file(), output)
            self.assertEqual(json.loads(report.read_text()), {
                "registered": False,
                "blender": [5, 2, 2],
            })


if __name__ == "__main__":
    unittest.main()
