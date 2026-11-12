"""Key real Per-Node Grade sidebar buttons through Blender's event queue."""

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


class KeyframeGuiTests(unittest.TestCase):
    def test_native_sidebar_keyframes_share_auto_key_channels(self):
        resources = files("tests.perceptual_grade_blender")
        blender_root = Path(str(resources / "blender")).resolve()
        blender = next((path for path in (
            blender_root / "Blender.app/Contents/MacOS/Blender", blender_root / "blender"
        ) if path.is_file()), None)
        self.assertIsNotNone(blender, "Pinned native Blender artifact missing")
        runner = Path(str(resources / "keyframe_runner.py")).resolve()
        with tempfile.TemporaryDirectory(prefix="pg-keyframe-gui-") as directory:
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
                OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1",
            )
            with virtual_display(resources, root, env):
                report = root / "report.json"
                process = subprocess.Popen([
                    str(blender), "--factory-startup", "--disable-autoexec",
                    "--enable-event-simulate", "--window-geometry", "0", "0", "1280", "960",
                    "--python-exit-code", "1", "--python", str(runner),
                    "--", str(repository), str(report),
                ], cwd=root, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, start_new_session=True)
                try:
                    output, _ = process.communicate(timeout=180)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    output, _ = process.communicate(timeout=10)
                    self.fail("Native keyframe test timed out\n" + output[-16000:])
                data = json.loads(report.read_text()) if report.exists() else {}
                details = output[-16000:] + "\n" + json.dumps(data, indent=2)
                self.assertEqual(process.returncode, 0, details)
                self.assertTrue(data.get("passed"), details)
                self.assertEqual([case["tree_type"] for case in data["cases"]],
                                 ["ShaderNodeTree", "CompositorNodeTree"], details)
                for case in data["cases"]:
                    self.assertEqual(case["context_menu_channels"], [
                        {
                            "field": field,
                            "action_owner": case["action_owner"],
                            "data_path": case["copied_paths"][field],
                            "frame": 1,
                            "value": value,
                        }
                        for field, value in (("exposure", 1.25), ("fit", 0.25))
                    ], details)
                    self.assertEqual(case["keyed_fields"], ["exposure", "fit"], details)
                    self.assertEqual(case["deleted_fields"], ["exposure", "fit"], details)
                    self.assertEqual(case["auto_key_frames"], [1, 3, 5], details)
                    self.assertEqual(case["channel_count"], 2, details)


if __name__ == "__main__":
    unittest.main()
