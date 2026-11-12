"""Verify continuous Blender animation rendering in background and GUI modes."""

from importlib.resources import files
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import unittest
import zipfile

from .gui_support import virtual_display


class InstalledAnimationTests(unittest.TestCase):
    def _run(self, *, gui):
        resources = files("tests.perceptual_grade_blender")
        blender_root = Path(str(resources / "blender")).resolve()
        blender = next((path for path in (
            blender_root / "Blender.app/Contents/MacOS/Blender",
            blender_root / "blender",
        ) if path.is_file()), None)
        self.assertIsNotNone(blender, "Pinned native Blender artifact missing")
        runner = Path(str(resources / "animation_runner.py")).resolve()
        with tempfile.TemporaryDirectory(prefix="perceptual-grade-animation-") as temp:
            root = Path(temp)
            repository = root / "repository"
            extension_dir = repository / "perceptual_grade"
            extension_dir.mkdir(parents=True)
            with zipfile.ZipFile(resources / "extension.zip") as archive:
                archive.extractall(extension_dir)
            env = {key: value for key, value in os.environ.items()
                   if key not in {"PYTHONPATH", "PYTHONHOME", "BLENDER_USER_SCRIPTS",
                                  "BLENDER_SYSTEM_SCRIPTS", "BLENDER_SYSTEM_PYTHON"}}
            env.update(
                BLENDER_USER_CONFIG=str(root / "config"),
                BLENDER_USER_EXTENSIONS=str(root / "extensions"),
                OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1",
                PYTHONDONTWRITEBYTECODE="1",
            )
            report = root / "report.json"
            command = [str(blender)]
            if gui:
                command += ["--window-geometry", "0", "0", "1280", "960"]
            else:
                command += ["--background"]
            command += [
                "--factory-startup", "--disable-autoexec", "--python-exit-code", "1",
                "--python", str(runner), "--", str(repository), str(report),
                "gui" if gui else "background",
            ]

            def execute():
                process = subprocess.Popen(
                    command, cwd=root, env=env, stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT, text=True, start_new_session=True,
                )
                try:
                    output, _ = process.communicate(timeout=300)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    output, _ = process.communicate(timeout=10)
                    self.fail("Continuous animation render timed out\n" + output[-20000:])
                data = json.loads(report.read_text()) if report.exists() else {}
                details = output[-20000:] + "\n" + json.dumps(data, indent=2)
                self.assertEqual(process.returncode, 0, details)
                self.assertEqual(data.get("animation"), "continuous-native-verified", details)
                self.assertEqual(data.get("mode"), "gui" if gui else "background", details)
                self.assertEqual(data.get("render_starts"), 2, details)
                self.assertEqual(data.get("render_writes"), [1, 2, 3, 1, 2, 3], details)
                self.assertEqual(data.get("frames"), [1, 2, 3, 1, 2, 3], details)
                levels = data["sequence_levels"]
                self.assertEqual(len(levels), 3, details)
                self.assertEqual(len({round(level, 5) for level in levels}), 3, details)
                if data.get("movie_supported"):
                    self.assertGreater(data.get("movie_bytes", 0), 0, details)
                else:
                    self.assertEqual(data.get("movie_bytes"), 0, details)

            with virtual_display(resources, root, env):
                execute()

    def test_continuous_animation_in_background(self):
        self._run(gui=False)

    def test_continuous_animation_in_gui_worker(self):
        self._run(gui=True)


if __name__ == "__main__":
    unittest.main()
