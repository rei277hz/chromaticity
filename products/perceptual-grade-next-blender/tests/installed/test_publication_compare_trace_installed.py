"""Verify the publication comparison trace through Blender F3 search."""

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


class PublicationCompareTraceInstalledTests(unittest.TestCase):
    def test_f3_trace_captures_all_publication_strategies(self):
        resources = files("tests.perceptual_grade_blender")
        blender_name = ("Blender.app/Contents/MacOS/Blender" if sys.platform == "darwin"
                        else "blender")
        blender = Path(str(resources / "blender" / blender_name)).resolve()
        runner = Path(str(resources / "publication_compare_trace_runner.py")).resolve()
        with tempfile.TemporaryDirectory(prefix="pg-publication-compare-trace-") as directory:
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
                process = subprocess.Popen(
                    [str(blender), "--factory-startup", "--disable-autoexec",
                     "--enable-event-simulate", "--window-geometry", "0", "0",
                     "1280", "960", "--python-exit-code", "1", "--python",
                     str(runner), "--", str(repository), str(report)],
                    cwd=root, env=env, stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT, text=True, start_new_session=True,
                )
                try:
                    output, _ = process.communicate(timeout=180)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    output, _ = process.communicate(timeout=10)
                    self.fail("Publication trace runner timed out\n" + output[-16000:])
            data = json.loads(report.read_text()) if report.exists() else {}
            details = output[-16000:] + "\n" + json.dumps(data, indent=2)
            self.assertEqual(process.returncode, 0, details)
            self.assertTrue(data.get("passed"), details)
            self.assertEqual(data["searches"], [
                "publication compare start drag trace",
                "publication compare stop drag trace",
            ], details)
            expected = {(tree_type, variant) for tree_type in
                        ("ShaderNodeTree", "CompositorNodeTree")
                        for variant in ("versioned", "original", "banked")}
            self.assertEqual({(item["tree_type"], item["variant"])
                              for item in data["publications"]}, expected, details)
            self.assertEqual(set(map(tuple, data["trace"]["callback_pairs"])), expected, details)
            self.assertEqual(set(map(tuple, data["trace"]["stage_pairs"])), expected, details)
            self.assertEqual(data["trace"]["dropped"], 0, details)
            self.assertTrue(data["cleanup"], details)


if __name__ == "__main__":
    unittest.main()
