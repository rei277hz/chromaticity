"""Installed center-frame Grade semantics under native motion blur."""

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


class InstalledMotionBlurConformanceTests(unittest.TestCase):
    def test_available_engines_center_frame_grade(self):
        resources = files("tests.perceptual_grade_blender")
        blender_root = Path(str(resources / "blender")).resolve()
        blender = next((path for path in (
            blender_root / "Blender.app/Contents/MacOS/Blender",
            blender_root / "blender",
        ) if path.is_file()), None)
        self.assertIsNotNone(blender, "Pinned native Blender artifact missing")
        runner = Path(str(resources / "motion_blur_conformance_runner.py")).resolve()
        with tempfile.TemporaryDirectory(prefix="perceptual-grade-motion-blur-") as temp:
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
            command = [
                str(blender), "--background", "--factory-startup", "--disable-autoexec",
                "--python-exit-code", "1", "--python", str(runner), "--",
                str(repository), str(report),
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
                    self.fail("Motion-blur conformance timed out\n" + output[-20000:])
                data = json.loads(report.read_text()) if report.exists() else {}
                details = output[-20000:] + "\n" + json.dumps(data, indent=2)
                self.assertEqual(process.returncode, 0, details)
                engines = data.get("engines", {})
                eevee_name = next((name for name in ("BLENDER_EEVEE_NEXT", "BLENDER_EEVEE")
                                   if name in engines), None)
                self.assertIsNotNone(eevee_name, details)
                self.assertEqual(data.get("times"), [1.5, 2.5], details)
                for mode in ("shader_grade", "compositor_grade"):
                    mode_engines = data[mode]["engines"]
                    self.assertEqual(set(mode_engines), set(engines), details)
                    for engine, observation in mode_engines.items():
                        self.assertGreater(observation["max_time_output_delta"], 0.02,
                                           details)
                        samples = observation["samples"]
                        self.assertEqual(set(samples), {"1.5", "2.5"}, details)
                        for time, expected_exposure in (("1.5", 1.0), ("2.5", 3.0)):
                            sample = samples[time]
                            self.assertAlmostEqual(
                                sample["exposure"], expected_exposure, places=6,
                                msg=details,
                            )
                            self.assertLessEqual(
                                sample["max_animated_vs_static_error"], 0.005, details,
                            )
                        self.assertGreater(
                            samples["1.5"]["motion_blur_vs_still_delta"], 0.02, details,
                        )

            with virtual_display(resources, root, env):
                execute()


if __name__ == "__main__":
    unittest.main()
