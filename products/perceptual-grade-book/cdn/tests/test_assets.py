"""Exercise declared downloads and the generated CDN-only book integration."""

import base64
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from pg_book_cdn import build


class AssetsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(__file__).parent
        cls.pins = build.read_pins(cls.root / "pins.bzl")

    def test_cdn_outputs_verify_inputs_and_do_not_bundle_runtime_bytes(self):
        output = self.root / "assets"
        head = (output / "theme/head.hbs").read_text()
        manifest = json.loads((output / "src/downloads/provenance/katex.json").read_text())
        self.assertEqual(manifest["katex"], self.pins["DOC_TOOLS"]["katex"])
        for key in ("stylesheet", "script"):
            spec = manifest["katex"][key]
            data = (self.root / "sources" / spec["out"]).read_bytes()
            expected = "sha384-" + base64.b64encode(hashlib.sha384(data).digest()).decode("ascii")
            self.assertEqual(manifest["integrity"][key], expected)
            self.assertIn('integrity="' + expected + '"', head)
            self.assertIn(spec["url"], head)
        self.assertIn('<script defer ', head)
        self.assertEqual(head.count('crossorigin="anonymous"'), 2)
        files = [path for path in output.rglob("*") if path.is_file()]
        self.assertFalse(any(path.suffix in (".woff", ".woff2", ".ttf", ".js") for path in files))
        self.assertFalse(any(path.name == "katex.min.css" for path in files))
        self.assertFalse((output / "src/vendor").exists())
        font_manifest = json.loads((output / "src/downloads/provenance/fonts.json").read_text())
        self.assertEqual(font_manifest["fonts"], self.pins["DOC_FONTS"])
        css = (output / "theme/fonts.css").read_text()
        for spec in font_manifest["fonts"].values():
            self.assertIn(spec["normal"]["url"], css)
            license = output / "src/downloads/licenses" / spec["license"]["out"]
            self.assertEqual(build.digest(license), spec["license"]["sha256"])

    def test_tampered_declared_download_fails_before_creating_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            sources = root / "sources"
            shutil.copytree(self.root / "sources", sources, copy_function=shutil.copyfile)
            for directory in [sources, *(path for path in sources.rglob("*") if path.is_dir())]:
                directory.chmod(directory.stat().st_mode | 0o700)
            script = self.pins["DOC_TOOLS"]["katex"]["script"]["out"]
            (sources / script).write_bytes(b"tampered")
            output = root / "output"
            with self.assertRaisesRegex(ValueError, "CDN input hash mismatch"):
                build.build(self.root / "pins.bzl", sources, output)
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
