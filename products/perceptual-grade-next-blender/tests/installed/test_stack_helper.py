"""Install the ZIP and create actual GPU-backed Stacks in pinned Blender."""

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


class StackHelperTests(unittest.TestCase):
    def test_first_populated_stacks_use_the_real_helper(self):
        resources = files("tests.perceptual_grade_blender")
        blender_root = Path(str(resources / "blender")).resolve()
        blender = next((path for path in (
            blender_root / "blender", blender_root / "Blender.app/Contents/MacOS/Blender",
        ) if path.is_file()), None)
        self.assertIsNotNone(blender, "Pinned native Blender artifact missing")
        runner = Path(str(resources / "stack_helper_runner.py")).resolve()
        with tempfile.TemporaryDirectory(prefix="pg-stack-helper-") as directory:
            root = Path(directory)
            repository = root / "repository"
            package = repository / "perceptual_grade"
            package.mkdir(parents=True)
            with zipfile.ZipFile(str(resources / "extension.zip")) as archive:
                archive.extractall(package)
            env = {key: value for key, value in os.environ.items()
                   if key not in {"PYTHONPATH", "PYTHONHOME", "BLENDER_USER_SCRIPTS",
                                  "BLENDER_SYSTEM_SCRIPTS", "BLENDER_SYSTEM_PYTHON"}}
            env.update(BLENDER_USER_CONFIG=str(root / "config"),
                       BLENDER_USER_EXTENSIONS=str(root / "extensions"),
                       OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1",
                       PYTHONDONTWRITEBYTECODE="1")
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
                    output, _ = process.communicate(timeout=300)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    output, _ = process.communicate(timeout=10)
                    self.fail("Native Stack helper test timed out\n" + output[-16000:])
                self.assertEqual(process.returncode, 0, output[-16000:])
                self.assertTrue(report.is_file(), output[-16000:])
                self.assertEqual(json.loads(report.read_text()), {
                    "passed": True,
                    "contexts": ["ShaderNodeTree", "CompositorNodeTree"],
                    "helper_retired": True,
                })


if __name__ == "__main__":
    unittest.main()
