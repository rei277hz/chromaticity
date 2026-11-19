"""Keep the handbook's real browser checks independent of Buck temp-path depth."""

from importlib.resources import files
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from pg_book_diagrams.render import browser_environment


class HandbookBrowserTests(unittest.TestCase):
    def setUp(self):
        # This resource-only library is a namespace package. Resolve a concrete
        # file before converting to Path, rather than its MultiplexedPath root.
        self.resources = Path(files("pg_book_diagram_tests") / "test_check_labels.mjs").parent

    def command(self, chromium):
        return [
            str(self.resources / "node/bin/node"),
            str(self.resources / "test_check_labels.mjs"),
            "--chromium", str(chromium),
            "--node-modules", str(self.resources / "npm/node_modules"),
            "--font", str(self.resources / "fonts/Tinos-Regular.ttf"),
        ]

    def environment(self):
        return browser_environment(self.resources / "native-runtime", self.resources / "fonts")

    def test_browser_geometry_with_long_inherited_temp_paths(self):
        with tempfile.TemporaryDirectory() as temporary:
            ambient = Path(temporary) / ("browser-ambient-" + "x" * 120)
            ambient.mkdir()
            self.assertGreater(len(os.fsencode(ambient)), 108)
            inherited = dict.fromkeys(("TMPDIR", "TMP", "TEMP"), str(ambient))
            with patch.dict(os.environ, inherited):
                with self.environment() as env:
                    scratch = Path(env["TMPDIR"])
                    self.assertEqual(scratch.parent, Path("/tmp"))
                    self.assertEqual({env[key] for key in inherited}, {str(scratch)})
                    self.assertEqual(Path(env["FONTCONFIG_FILE"]).parent, scratch)
                    self.assertEqual({key: os.environ[key] for key in inherited}, inherited)
                    # Concurrent scopes cannot share or remove each other's profile.
                    with self.environment() as other_env:
                        other_scratch = Path(other_env["TMPDIR"])
                        self.assertNotEqual(other_scratch, scratch)
                        self.assertTrue(other_scratch.is_dir())
                    self.assertFalse(other_scratch.exists())
                    self.assertTrue(scratch.is_dir())
                    result = subprocess.run(
                        self.command(self.resources / "chromium/chrome"),
                        check=True, capture_output=True, text=True, env=env, timeout=90,
                    )
                    self.assertIn("SVG label collision fixtures passed", result.stdout)
                self.assertFalse(scratch.exists())
                self.assertTrue(ambient.is_dir())
                self.assertEqual({key: os.environ[key] for key in inherited}, inherited)

    def test_browser_temp_cleanup_after_launch_failure(self):
        with self.assertRaises(subprocess.CalledProcessError):
            with self.environment() as env:
                scratch = Path(env["TMPDIR"])
                subprocess.run(
                    self.command(scratch / "missing-chromium"),
                    check=True, capture_output=True, text=True, env=env, timeout=90,
                )
        self.assertFalse(scratch.exists())
