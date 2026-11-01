"""Exercise static ZIP content validation and deterministic assembly."""

import hashlib
from pathlib import Path
import tempfile
import unittest
import zipfile

from web_build.build import package_site, verify_site_archive


class StaticArchiveTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.site = self.root / "site"
        (self.site / "assets").mkdir(parents=True)
        (self.site / "index.html").write_text('<script type="module" src="./assets/main.js"></script>')
        (self.site / "assets" / "main.js").write_text('console.log("static site");\n')
        (self.site / "assets" / "core.wasm").write_bytes(b"\x00asm\x01\x00\x00\x00")
        self.archive = self.root / "site.zip"

    def test_archive_has_exact_content_and_reproducible_metadata(self):
        first = package_site(self.site, self.archive)
        other = self.root / "again.zip"
        second = package_site(self.site, other)
        self.assertEqual(self.archive.read_bytes(), other.read_bytes())
        self.assertEqual(first, second)
        expected = {
            file.relative_to(self.site).as_posix(): hashlib.sha256(file.read_bytes()).hexdigest()
            for file in sorted(self.site.rglob("*")) if file.is_file()
        }
        self.assertEqual(first["files"], expected)
        self.assertEqual(first["sha256"], hashlib.sha256(self.archive.read_bytes()).hexdigest())
        self.assertEqual(verify_site_archive(self.archive, self.site), first)
        with zipfile.ZipFile(self.archive) as bundle:
            self.assertEqual(bundle.namelist(), sorted(expected))
            self.assertEqual(len({entry.date_time for entry in bundle.infolist()}), 1)
            for entry in bundle.infolist():
                self.assertEqual(entry.external_attr >> 16, 0o100644)
                self.assertEqual(bundle.read(entry), (self.site / entry.filename).read_bytes())

    def test_verifier_rejects_changed_missing_and_unexpected_payloads(self):
        package_site(self.site, self.archive)
        with zipfile.ZipFile(self.archive) as bundle:
            original = {entry.filename: bundle.read(entry) for entry in bundle.infolist()}
        changed = dict(original)
        changed["assets/main.js"] = b"changed"
        missing = {name: data for name, data in original.items() if name != "assets/core.wasm"}
        extra = dict(original, unexpected=b"unexpected")
        for label, contents in (("changed", changed), ("missing", missing), ("extra", extra)):
            with self.subTest(label=label):
                path = self.root / (label + ".zip")
                with zipfile.ZipFile(path, "w") as bundle:
                    for name, data in contents.items():
                        bundle.writestr(name, data)
                with self.assertRaises(ValueError):
                    verify_site_archive(path, self.site)

    def test_verifier_rejects_unsafe_paths_and_duplicate_members(self):
        for name in ("../outside.js", "/absolute.js", "assets/../../outside.js", "assets\\outside.js"):
            with self.subTest(name=name):
                with zipfile.ZipFile(self.archive, "w") as bundle:
                    bundle.writestr(name, b"invalid")
                with self.assertRaises(ValueError):
                    verify_site_archive(self.archive, self.site)
        with zipfile.ZipFile(self.archive, "w") as bundle:
            bundle.writestr("index.html", b"first")
            with self.assertWarns(UserWarning):
                bundle.writestr("index.html", b"second")
        with self.assertRaises(ValueError):
            verify_site_archive(self.archive, self.site)

    def test_packager_rejects_links_to_undeclared_content(self):
        outside = self.root / "outside.js"
        outside.write_text("undeclared input")
        (self.site / "assets" / "linked.js").symlink_to(outside)
        with self.assertRaises(ValueError):
            package_site(self.site, self.archive)


if __name__ == "__main__":
    unittest.main()
