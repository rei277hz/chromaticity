"""Run the bundled-template native suite under Blender 5.2.4."""

from importlib.resources import files
from contextlib import nullcontext
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from ..installed.gui_support import configure_software_graphics, virtual_display


class TemplateLTSHostTests(unittest.TestCase):
    def test_template_suite_under_pinned_lts_blender(self):
        resources = files("tests.perceptual_grade_blender")
        blender = Path(str(resources / "blender" / (
            "Blender.app/Contents/MacOS/Blender" if sys.platform == "darwin" else "blender"
        ))).resolve()
        runner = Path(str(resources / "template_lts_runner.py")).resolve()
        with tempfile.TemporaryDirectory(prefix="pg-template-lts-") as directory:
            root = Path(directory)
            config = root / "configuration.json"
            config.write_text(json.dumps({
                "python_paths": [path for path in sys.path
                                 if path and Path(path).exists()],
                "test_module": os.environ["PG_TEMPLATE_TEST_MODULE"],
            }), encoding="utf-8")
            environment = {
                key: value for key, value in os.environ.items()
                if key not in {"PYTHONPATH", "PYTHONHOME", "BLENDER_USER_SCRIPTS",
                               "BLENDER_SYSTEM_SCRIPTS", "BLENDER_SYSTEM_PYTHON"}
            }
            environment.update(
                OPENBLAS_NUM_THREADS="1",
                OMP_NUM_THREADS="1",
                PYTHONDONTWRITEBYTECODE="1",
                BLENDER_USER_CONFIG=str(root / "config"),
            )
            configure_software_graphics(resources, root, environment)
            display = (virtual_display(resources, root, environment)
                       if os.environ.get("PG_TEMPLATE_RENDER") == "1" else nullcontext())
            with display:
                try:
                    result = subprocess.run(
                        [str(blender), "--background", "--factory-startup",
                         "--disable-autoexec", "--python-exit-code", "1",
                         "--python", str(runner), "--", str(config)],
                        cwd=root, env=environment, capture_output=True, text=True,
                        timeout=540, check=False,
                    )
                except subprocess.TimeoutExpired as error:
                    output = "\n".join(
                        part.decode(errors="replace") if isinstance(part, bytes) else part or ""
                        for part in (error.stdout, error.stderr))
                    self.fail("Blender template test timed out after 540 seconds\n" + output)
            output = result.stdout + "\n" + result.stderr
            print(output, flush=True)
            self.assertEqual(result.returncode, 0, output)
            self.assertIn("OK", output, output)


if __name__ == "__main__":
    unittest.main()
