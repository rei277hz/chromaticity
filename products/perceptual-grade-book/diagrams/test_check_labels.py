"""Run the label checker's browser fixtures in a declared remote Buck test."""
from pathlib import Path
import subprocess
import unittest

from pg_book_diagrams.render import browser_environment


class LabelGeometryTests(unittest.TestCase):
    def test_browser_geometry(self):
        resources = Path(__file__).parent.resolve()
        runtime = resources / "native-runtime"
        with browser_environment(runtime, resources / "fonts") as env:
            subprocess.run([
                str(resources / "node/bin/node"),
                str(resources / "test_check_labels.mjs"),
                "--chromium", str(resources / "chromium/chrome"),
                "--node-modules", str(resources / "npm/node_modules"),
                "--font", str(resources / "fonts/Tinos-Regular.ttf"),
            ], check=True, env=env)


if __name__ == "__main__":
    unittest.main()
