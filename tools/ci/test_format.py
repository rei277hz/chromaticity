"""Protect the agreed formatting boundary, including before the first commit."""

from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import format as formatting


class FormattingInventoryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        subprocess.run(["git", "init", "--quiet", str(self.root)], check=True)
        root = patch.object(formatting, "ROOT", self.root)
        root.start()
        self.addCleanup(root.stop)
        self.write(".gitignore", ".cargo/\nbuck-out/\nnode_modules/\n")

    def write(self, name, contents="example = 1\n"):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents)

    def track(self, names):
        subprocess.run(["git", "add", "--force", "--", *names], cwd=self.root, check=True)

    def maintained(self):
        tracked = ["BUCK", "third_party/rust/PACKAGE", "build_defs/rules.bzl", "third_party/rust/Cargo.toml"]
        untracked = ["products/demo/BUCK", "libraries/demo/BUCK_TREE", "build_defs/query.bxl",
                     "build_defs/untracked.bzl", "third_party/rust/fixups/demo/fixups.toml"]
        for name in tracked + untracked:
            self.write(name)
        self.track(tracked)
        return set(tracked + untracked)

    def test_collects_tracked_and_untracked_maintained_files(self):
        expected = self.maintained()
        groups = formatting.inventory()
        self.assertEqual({name for names in groups.values() for name in names}, expected)
        self.assertEqual(groups["build"], ["BUCK", "products/demo/BUCK"])
        self.assertIn("third_party/rust/PACKAGE", groups["starlark"])
        self.assertIn("third_party/rust/fixups/demo/fixups.toml", groups["toml"])

    def test_excludes_programs_generated_files_history_caches_and_symlinks(self):
        expected = self.maintained()
        protected = [f"src/example.{suffix}" for suffix in
                     ("py", "rs", "ts", "js", "mjs", "css", "html", "c", "h", "dctl", "wgsl", "lean", "sh", "json", "yaml")]
        protected += ["third_party/rust/BUCK", "third_party/web/dependencies.bzl",
                      "third_party/rust/tools/versions.json", "third_party/rust/Cargo.lock",
                      "products/perceptual-grade-book/docs/book/book.toml",
                      "products/perceptual-grade-book/docs/BUCK",
                      "third_party/rust/.cargo/tracked.toml", "buck-out/tracked.bzl"]
        for name in protected:
            self.write(name)
        self.track(protected)
        for name in ["third_party/rust/.cargo/untracked.toml", "buck-out/untracked.bzl",
                     "node_modules/package/BUCK", "src/untracked.py"]:
            self.write(name)
        (self.root / "linked.toml").symlink_to("third_party/rust/Cargo.toml")
        self.track(["linked.toml"])
        actual = {name for names in formatting.inventory().values() for name in names}
        self.assertEqual(actual, expected)

    def test_empty_inventory_fails_instead_of_passing_silently(self):
        self.write("src/program.py")
        with self.assertRaisesRegex(ValueError, "refusing an empty formatting check"):
            formatting.inventory()


if __name__ == "__main__":
    unittest.main()
