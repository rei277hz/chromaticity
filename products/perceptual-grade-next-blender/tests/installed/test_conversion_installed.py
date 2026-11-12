"""Exercise conversion transactions against the packaged Blender extension."""

from importlib.resources import files
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile

from .gui_support import configure_software_graphics


class InstalledConversionTests(unittest.TestCase):
    def test_conversion_transaction_and_animation_remapping(self):
        resources = files("tests.perceptual_grade_blender")
        blender_name = ("Blender.app/Contents/MacOS/Blender" if sys.platform == "darwin"
                        else "blender")
        blender = Path(str(resources / "blender" / blender_name)).resolve()
        runner = Path(str(resources / "conversion_runner.py")).resolve()
        with tempfile.TemporaryDirectory(prefix="pg-conversion-installed-") as directory:
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
                PYTHONDONTWRITEBYTECODE="1",
            )
            configure_software_graphics(resources, root, env)
            report = root / "report.json"
            result = subprocess.run(
                [str(blender), "--background", "--factory-startup", "--disable-autoexec",
                 "--python-exit-code", "1", "--python", str(runner), "--",
                 str(repository), str(report)],
                cwd=root, env=env, capture_output=True, text=True, timeout=540,
            )
            output = result.stdout + "\n" + result.stderr
            self.assertEqual(result.returncode, 0, output[-16000:])
            self.assertEqual(json.loads(report.read_text()), {"passed": True}, output)


if __name__ == "__main__":
    unittest.main()
