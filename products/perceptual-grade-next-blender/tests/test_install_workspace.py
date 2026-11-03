"""Filesystem acceptance for destructive ZIP-to-worktree installation."""

import importlib.util
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch
import warnings
import zipfile

try:
    from product_install.install_workspace import install_archive
except ModuleNotFoundError as error:
    if error.name not in {"product_install", "product_install.install_workspace"}:
        raise
    source = Path(__file__).resolve().parents[1] / "tools" / "install_workspace.py"
    spec = importlib.util.spec_from_file_location("install_workspace", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    install_archive = module.install_archive


class InstallWorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.destination = self.root / "workspace"
        self.destination.mkdir()
        (self.destination / ".git").mkdir()
        (self.destination / ".git" / "config").write_bytes(b"git config must survive\n")
        (self.destination / "old.txt").write_bytes(b"previous checkout")
        self.archive = self.root / "product.zip"
        self.product = {
            "__init__.py": b"# extension entrypoint\n",
            "blender_manifest.toml": b'id = "perceptual_grade"\nname = "Perceptual Grade"\n',
            "README.md": b"# Perceptual Grade\n",
            "package/module.py": b"VALUE = 42\n",
            "package/data.bin": bytes(range(256)),
        }

    def write_archive(self, extra=()):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            with zipfile.ZipFile(self.archive, "w", compression=zipfile.ZIP_STORED) as bundle:
                for name, data in self.product.items():
                    bundle.writestr(name, data)
                for name, data in extra:
                    bundle.writestr(name, data)

    def snapshot(self):
        return {str(path.relative_to(self.destination)): path.read_bytes()
                for path in self.destination.rglob("*") if path.is_file()}

    def assert_rejected_without_changes(self):
        before = self.snapshot()
        with self.assertRaises((ValueError, OSError, zipfile.BadZipFile)):
            install_archive(self.archive, self.destination)
        self.assertEqual(self.snapshot(), before)

    def test_installs_zip_bytes_and_preserves_git(self):
        outside = self.root / "outside"
        outside.mkdir()
        (outside / "keep.txt").write_bytes(b"outside target")
        (self.destination / "linked-dir").symlink_to(outside, target_is_directory=True)
        (self.destination / "dangling").symlink_to(self.root / "absent")
        (self.destination / ".hidden").write_bytes(b"hidden stale file")
        nested = self.destination / "old-dir" / ".nested"
        nested.mkdir(parents=True)
        (nested / "stale.txt").write_bytes(b"stale")
        git_stat = (self.destination / ".git").stat()
        self.write_archive()
        self.assertEqual(install_archive(self.archive, self.destination), len(self.product))
        expected = dict(self.product, **{".git/config": b"git config must survive\n"})
        self.assertEqual(self.snapshot(), expected)
        self.assertEqual((self.destination / ".git").stat().st_ino, git_stat.st_ino)
        self.assertEqual((outside / "keep.txt").read_bytes(), b"outside target")
        self.assertFalse((self.destination / "dangling").is_symlink())
        self.assertFalse((self.destination / "linked-dir").exists())
        self.assertFalse((self.destination / "old-dir").exists())

    def test_preserves_git_worktree_file_exactly(self):
        (self.destination / ".git" / "config").unlink()
        (self.destination / ".git").rmdir()
        marker = self.destination / ".git"
        marker.write_bytes(b"gitdir: /some/other/repository/worktrees/product\n")
        before = marker.stat()
        self.write_archive()
        install_archive(self.archive, self.destination)
        self.assertEqual(marker.read_bytes(), b"gitdir: /some/other/repository/worktrees/product\n")
        self.assertEqual(marker.stat().st_ino, before.st_ino)
        self.assertEqual(marker.stat().st_mtime_ns, before.st_mtime_ns)

    def test_accepts_explicit_directories(self):
        self.write_archive([("empty/", b""), ("package/", b"")])
        install_archive(self.archive, self.destination)
        self.assertTrue((self.destination / "empty").is_dir())
        self.assertEqual((self.destination / "package" / "module.py").read_bytes(),
                         self.product["package/module.py"])

    def test_rejects_unsafe_or_git_member_before_removal(self):
        for name in ("../escape", "/absolute", "a/../escape", "a//b", "./name",
                     "a\\b", "C:/name", ".git", ".git/config", ".GIT/config", "bad\nname"):
            with self.subTest(name=name):
                self.write_archive([(name, b"invalid")])
                self.assert_rejected_without_changes()

    def test_rejects_duplicate_or_file_directory_conflict_before_removal(self):
        for entries in (
            [("README.md", b"duplicate")],
            [("package", b"file replaces parent directory")],
            [("README.md/child", b"child below file")],
            [("README.md/", b"")],
        ):
            with self.subTest(entries=entries):
                self.write_archive(entries)
                self.assert_rejected_without_changes()

    def test_rejects_archive_symlinks_before_removal(self):
        link = zipfile.ZipInfo("link")
        link.create_system = 3
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        self.write_archive([(link, b"../outside")])
        self.assert_rejected_without_changes()

    def test_crc_failure_leaves_existing_worktree_intact(self):
        self.write_archive()
        data = self.archive.read_bytes()
        self.assertIn(self.product["package/data.bin"], data)
        changed = self.product["package/data.bin"].replace(b"\x80", b"\x81", 1)
        self.archive.write_bytes(data.replace(self.product["package/data.bin"], changed, 1))
        self.assert_rejected_without_changes()

    def test_missing_or_invalid_zip_leaves_existing_worktree_intact(self):
        self.assert_rejected_without_changes()
        self.archive.write_bytes(b"not a ZIP")
        self.assert_rejected_without_changes()

    def test_rejects_wrong_product_archive_before_removal(self):
        for contents in ({}, {"README.md": b"not an extension"}, {
                "__init__.py": b"", "blender_manifest.toml": b'id = "another_extension"\n'}):
            with self.subTest(contents=contents):
                self.product = contents
                self.write_archive()
                self.assert_rejected_without_changes()

    def test_rejects_destination_without_git_or_with_symlink(self):
        self.write_archive()
        alias = self.root / "alias"
        alias.symlink_to(self.destination, target_is_directory=True)
        with self.assertRaises(ValueError):
            install_archive(self.archive, alias)
        plain = self.root / "plain"
        plain.mkdir()
        marker = plain / "keep"
        marker.write_bytes(b"keep")
        with self.assertRaises(ValueError):
            install_archive(self.archive, plain)
        self.assertEqual(marker.read_bytes(), b"keep")

    def test_rejects_destination_containing_archive_or_current_directory(self):
        self.archive = self.destination / "product.zip"
        self.write_archive()
        self.assert_rejected_without_changes()
        outside_archive = self.root / "product.zip"
        self.archive.rename(outside_archive)
        self.archive = outside_archive
        with patch.object(Path, "cwd", return_value=self.destination):
            self.assert_rejected_without_changes()


if __name__ == "__main__":
    unittest.main()
