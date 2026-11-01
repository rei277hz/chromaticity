"""Acceptance checks for replacing only the color picker in a site checkout."""

import hashlib
import json
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch
import warnings
import zipfile

from hdr_color_picker_publish.publish import publish_archive


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
        self.destination = self.checkout / "color-picker"
        self.destination.mkdir()
        (self.destination / "stale.txt").write_bytes(b"previous publication")
        self.archive = self.root / "site.zip"
        self.manifest = self.root / "manifest.json"
        self.site = {
            "index.html": b'<script type="module" src="./assets/main.js"></script>',
            "THIRD_PARTY_NOTICES.txt": b"dependency notices",
            "assets/main.js": b'console.log("color picker");',
            "assets/main.css": b"body { margin: 0; }",
            "assets/core.wasm": bytes(range(256)),
        }

    def write_archive(self, extra=(), inventory=None):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            with zipfile.ZipFile(self.archive, "w", compression=zipfile.ZIP_STORED) as bundle:
                for name, data in self.site.items():
                    bundle.writestr(name, data)
                for name, data in extra:
                    bundle.writestr(name, data)
        if inventory is None:
            inventory = {name: hashlib.sha256(data).hexdigest() for name, data in self.site.items()}
        self.manifest.write_text(json.dumps({
            "files": inventory,
            "sha256": hashlib.sha256(self.archive.read_bytes()).hexdigest(),
        }))

    def update_archive_checksum(self):
        manifest = json.loads(self.manifest.read_text())
        manifest["sha256"] = hashlib.sha256(self.archive.read_bytes()).hexdigest()
        self.manifest.write_text(json.dumps(manifest))

    def snapshot(self, root=None):
        root = root or self.checkout
        result = {}
        for path in root.rglob("*"):
            relative = str(path.relative_to(root))
            if path.is_symlink():
                result[relative] = ("link", str(path.readlink()))
            elif path.is_dir():
                result[relative] = ("directory",)
            else:
                result[relative] = ("file", path.read_bytes())
        return result

    def assert_rejected_without_changes(self, destination=None):
        before = self.snapshot()
        with self.assertRaises((ValueError, OSError, zipfile.BadZipFile)):
            publish_archive(self.archive, self.manifest, destination or self.destination)
        self.assertEqual(self.snapshot(), before)

    def assert_published_bytes(self):
        self.assertEqual({str(path.relative_to(self.destination)): path.read_bytes()
                          for path in self.destination.rglob("*") if path.is_file()}, self.site)

    def test_clears_all_target_entries_and_extracts_exact_zip_bytes(self):
        (self.destination / ".hidden").write_bytes(b"stale hidden file")
        (self.destination / "old-dir" / ".nested").mkdir(parents=True)
        (self.destination / "old-dir" / ".nested" / "old").write_bytes(b"stale nested file")
        (self.destination / "linked-dir").symlink_to(self.checkout / "sibling", target_is_directory=True)
        (self.destination / "dangling").symlink_to(self.root / "absent")
        git_before = (self.checkout / ".git").stat()
        self.write_archive()
        self.assertEqual(publish_archive(self.archive, self.manifest, self.destination), len(self.site))
        self.assert_published_bytes()
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
        publish_archive(self.archive, self.manifest, self.destination)
        self.assert_published_bytes()
        self.assertEqual((self.checkout / ".git").read_bytes(), b"gitdir: /another/worktree\n")
        self.assertEqual((self.checkout / ".git").stat().st_mtime_ns, git_before.st_mtime_ns)

    def test_accepts_explicit_empty_and_parent_directories(self):
        self.write_archive([("empty/", b""), ("assets/", b"")])
        publish_archive(self.archive, self.manifest, self.destination)
        self.assertTrue((self.destination / "empty").is_dir())
        self.assert_published_bytes()

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
            [("assets", b"file replaces directory")],
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
        content = self.site["assets/core.wasm"]
        data = self.archive.read_bytes()
        self.assertIn(content, data)
        self.archive.write_bytes(data.replace(content, content.replace(b"\x80", b"\x81"), 1))
        self.update_archive_checksum()
        before = self.snapshot()
        with self.assertRaises(zipfile.BadZipFile):
            publish_archive(self.archive, self.manifest, self.destination)
        self.assertEqual(self.snapshot(), before)

    def test_requires_exact_inventory_and_valid_file_checksums(self):
        valid = {name: hashlib.sha256(data).hexdigest() for name, data in self.site.items()}
        for inventory in ([], {}, {**valid, "absent": "0" * 64},
                          {**valid, "index.html": "0" * 64}):
            with self.subTest(inventory=inventory):
                self.write_archive(inventory=inventory)
                self.assert_rejected_without_changes()
        self.write_archive([("unlisted.txt", b"not in inventory")])
        self.assert_rejected_without_changes()

    def test_rejects_archive_checksum_mismatch(self):
        self.write_archive()
        manifest = json.loads(self.manifest.read_text())
        manifest["sha256"] = "0" * 64
        self.manifest.write_text(json.dumps(manifest))
        self.assert_rejected_without_changes()

    def test_rejects_missing_required_files_and_assets(self):
        original = self.site.copy()
        for name in original:
            with self.subTest(missing=name):
                self.site = {key: value for key, value in original.items() if key != name}
                self.write_archive()
                self.assert_rejected_without_changes()

    def test_rejects_missing_or_invalid_manifest(self):
        self.write_archive()
        self.manifest.unlink()
        self.assert_rejected_without_changes()
        for content in (b"invalid JSON", b"[]", b"{}", b'{"files": []}', b'{"files": {}}'):
            with self.subTest(content=content):
                self.manifest.write_bytes(content)
                self.assert_rejected_without_changes()

    def test_missing_and_invalid_archives_do_not_create_or_clear_target(self):
        self.write_archive()
        self.archive.unlink()
        self.assert_rejected_without_changes()
        self.archive.write_bytes(b"not a ZIP")
        self.update_archive_checksum()
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
        self.assert_rejected_without_changes(parent_alias / "color-picker")
        self.assert_rejected_without_changes(self.root / "plain")
        self.assert_rejected_without_changes(self.destination / "nested")

    def test_rejects_repo_root_git_metadata_and_nested_worktree(self):
        self.write_archive()
        self.assert_rejected_without_changes(self.checkout)
        self.assert_rejected_without_changes(self.checkout / ".git")
        (self.destination / ".git").write_bytes(b"gitdir: /nested/worktree")
        self.assert_rejected_without_changes()

    def test_rejects_home_current_directory_and_inputs_inside_target(self):
        self.write_archive()
        with patch.object(Path, "home", return_value=self.destination):
            self.assert_rejected_without_changes()
        with patch.object(Path, "cwd", return_value=self.destination):
            self.assert_rejected_without_changes()
        archive = self.archive
        self.archive = self.destination / "site.zip"
        self.write_archive()
        self.assert_rejected_without_changes()
        self.archive.unlink()
        self.archive = archive
        self.manifest = self.destination / "manifest.json"
        self.write_archive()
        self.assert_rejected_without_changes()


if __name__ == "__main__":
    unittest.main()
