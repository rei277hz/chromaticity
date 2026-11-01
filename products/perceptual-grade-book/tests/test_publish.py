"""Acceptance checks for replacing only the book directory in a site checkout."""

import hashlib
import json
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch
import warnings
import zipfile

from pg_book_build.publish import publish_archive


class PublishTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.checkout = self.root / "website"
        self.checkout.mkdir()
        (self.checkout / ".git").mkdir()
        (self.checkout / ".git" / "config").write_bytes(b"keep Git metadata")
        (self.checkout / "sibling").mkdir()
        (self.checkout / "sibling" / "index.html").write_bytes(b"keep other site")
        self.destination = self.checkout / "perceptual-grade"
        self.destination.mkdir()
        (self.destination / "stale.txt").write_bytes(b"previous publication")
        self.archive = self.root / "site.zip"
        self.site = {
            "index.html": b"<a href='en/index.html'>English</a>",
            ".nojekyll": b"",
            "en/index.html": b"<h1>Perceptual Grade</h1>",
            "zh-Hans/index.html": b"<h1>Perceptual Grade</h1>",
            "downloads/perceptual_grade-v1.23.2-20261101.zip": bytes(range(256)),
        }

    def write_archive(self, extra=(), manifest=None):
        if manifest is None:
            manifest = {
                "schema": 1,
                "build_target": "root//products/perceptual-grade-book:site",
                "site_files": {name: hashlib.sha256(data).hexdigest()
                               for name, data in self.site.items()},
            }
        self.contents = dict(self.site)
        self.contents["site-manifest.json"] = json.dumps(manifest).encode()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            with zipfile.ZipFile(self.archive, "w", compression=zipfile.ZIP_STORED) as bundle:
                for name, data in self.contents.items():
                    bundle.writestr(name, data)
                for name, data in extra:
                    bundle.writestr(name, data)

    def snapshot(self, root=None):
        root = root or self.checkout
        return {str(path.relative_to(root)): path.read_bytes()
                for path in root.rglob("*") if path.is_file()}

    def assert_rejected_without_changes(self, destination=None):
        before = self.snapshot()
        with self.assertRaises((ValueError, OSError, zipfile.BadZipFile)):
            publish_archive(self.archive, destination or self.destination)
        self.assertEqual(self.snapshot(), before)

    def test_clears_all_target_entries_and_extracts_exact_zip_bytes(self):
        (self.destination / ".hidden").write_bytes(b"stale hidden file")
        (self.destination / "old-dir" / ".nested").mkdir(parents=True)
        (self.destination / "old-dir" / ".nested" / "old").write_bytes(b"stale nested file")
        (self.destination / "linked-dir").symlink_to(self.checkout / "sibling", target_is_directory=True)
        (self.destination / "dangling").symlink_to(self.root / "absent")
        git_before = (self.checkout / ".git").stat()
        self.write_archive()
        self.assertEqual(publish_archive(self.archive, self.destination), len(self.contents))
        self.assertEqual(self.snapshot(self.destination), self.contents)
        self.assertEqual((self.checkout / ".git" / "config").read_bytes(), b"keep Git metadata")
        self.assertEqual((self.checkout / ".git").stat().st_ino, git_before.st_ino)
        self.assertEqual((self.checkout / "sibling" / "index.html").read_bytes(), b"keep other site")
        for name in ("old-dir", "linked-dir", "dangling", ".hidden", "stale.txt"):
            self.assertFalse((self.destination / name).exists())
            self.assertFalse((self.destination / name).is_symlink())

    def test_creates_missing_target_and_accepts_git_worktree_file(self):
        (self.destination / "stale.txt").unlink()
        self.destination.rmdir()
        (self.checkout / ".git" / "config").unlink()
        (self.checkout / ".git").rmdir()
        (self.checkout / ".git").write_bytes(b"gitdir: /another/worktree\n")
        git_before = (self.checkout / ".git").stat()
        self.write_archive()
        publish_archive(self.archive, self.destination)
        self.assertEqual(self.snapshot(self.destination), self.contents)
        self.assertEqual((self.checkout / ".git").read_bytes(), b"gitdir: /another/worktree\n")
        self.assertEqual((self.checkout / ".git").stat().st_mtime_ns, git_before.st_mtime_ns)

    def test_accepts_explicit_empty_and_parent_directories(self):
        self.write_archive([("empty/", b""), ("en/", b"")])
        publish_archive(self.archive, self.destination)
        self.assertTrue((self.destination / "empty").is_dir())
        self.assertEqual(self.snapshot(self.destination), self.contents)

    def test_rejects_unsafe_paths_and_git_metadata_before_removal(self):
        for name in ("../escape", "/absolute", "a/../escape", "a//b", "./name",
                     "a\\b", "C:/name", ".git", ".git/config", ".GIT/config",
                     "nested/.git/config", "bad\nname"):
            with self.subTest(name=name):
                self.write_archive([(name, b"invalid")])
                self.assert_rejected_without_changes()

    def test_rejects_duplicate_paths_and_file_directory_conflicts(self):
        for entries in (
            [("index.html", b"duplicate")],
            [("en", b"file replaces directory")],
            [("index.html/child", b"child below file")],
            [("index.html/", b"")],
            [("empty/", b"nonempty directory")],
        ):
            with self.subTest(entries=entries):
                self.write_archive(entries)
                self.assert_rejected_without_changes()

    def test_rejects_symlinks_and_special_files_in_zip(self):
        for kind in (stat.S_IFLNK, stat.S_IFIFO, stat.S_IFCHR):
            with self.subTest(kind=kind):
                member = zipfile.ZipInfo("special")
                member.create_system = 3
                member.external_attr = (kind | 0o777) << 16
                self.write_archive([(member, b"../outside")])
                self.assert_rejected_without_changes()

    def test_crc_failure_leaves_existing_site_intact(self):
        self.write_archive()
        content = self.site["downloads/perceptual_grade-v1.23.2-20261101.zip"]
        data = self.archive.read_bytes()
        self.assertIn(content, data)
        self.archive.write_bytes(data.replace(content, content.replace(b"\x80", b"\x81"), 1))
        self.assert_rejected_without_changes()

    def test_requires_exact_inventory_and_valid_checksums(self):
        valid = {name: hashlib.sha256(data).hexdigest() for name, data in self.site.items()}
        for inventory in ([], {}, {**valid, "absent": "0" * 64},
                          {**valid, "index.html": "0" * 64}):
            with self.subTest(inventory=inventory):
                self.write_archive(manifest={
                    "schema": 1, "build_target": "root//products/perceptual-grade-book:site",
                    "site_files": inventory,
                })
                self.assert_rejected_without_changes()
        self.write_archive([("unlisted.txt", b"not in inventory")])
        self.assert_rejected_without_changes()

    def test_rejects_missing_required_files_and_wrong_manifest(self):
        original = self.site.copy()
        for name in original:
            if name not in {
                    "index.html", ".nojekyll",
                    "downloads/perceptual_grade-v1.23.2-20261101.zip"}:
                continue
            with self.subTest(missing=name):
                self.site = {key: value for key, value in original.items() if key != name}
                self.write_archive()
                self.assert_rejected_without_changes()
        self.site = original
        for manifest in ([], {}, {"schema": 1, "build_target": "another product"}):
            with self.subTest(manifest=manifest):
                self.write_archive(manifest=manifest)
                self.assert_rejected_without_changes()

    def test_missing_and_invalid_archives_do_not_create_or_clear_target(self):
        self.assert_rejected_without_changes()
        self.archive.write_bytes(b"not a ZIP")
        self.assert_rejected_without_changes()
        missing = self.checkout / "new-site"
        self.assert_rejected_without_changes(missing)
        self.assertFalse(missing.exists())

    def test_rejects_symlink_target_or_parent_and_non_checkout_parent(self):
        self.write_archive()
        alias = self.checkout / "alias"
        alias.symlink_to(self.destination, target_is_directory=True)
        self.assert_rejected_without_changes(alias)
        alias.unlink()
        parent_alias = self.root / "alias"
        parent_alias.symlink_to(self.checkout, target_is_directory=True)
        self.assert_rejected_without_changes(parent_alias / "perceptual-grade")
        self.assert_rejected_without_changes(self.root / "plain")
        self.assert_rejected_without_changes(self.destination / "nested")

    def test_rejects_repo_root_git_metadata_and_nested_worktree(self):
        self.write_archive()
        self.assert_rejected_without_changes(self.checkout)
        self.assert_rejected_without_changes(self.checkout / ".git")
        (self.destination / ".git").write_bytes(b"gitdir: /nested/worktree")
        self.assert_rejected_without_changes()

    def test_rejects_home_current_directory_and_archive_inside_target(self):
        self.write_archive()
        with patch.object(Path, "home", return_value=self.destination):
            self.assert_rejected_without_changes()
        with patch.object(Path, "cwd", return_value=self.destination):
            self.assert_rejected_without_changes()
        self.archive = self.destination / "site.zip"
        self.write_archive()
        self.assert_rejected_without_changes()


if __name__ == "__main__":
    unittest.main()
