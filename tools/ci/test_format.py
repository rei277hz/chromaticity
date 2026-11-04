"""Protect the agreed formatting boundary, including before the first commit."""

from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import format as formatting


PRODUCT = formatting.PRODUCT.as_posix()


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
        tracked = [f"{PRODUCT}/{name}" for name in
                   ("BUCK", "PACKAGE", "requirements/inventory.bzl", "blender_manifest.toml", "requirements/node.inv")]
        untracked = [f"{PRODUCT}/{name}" for name in
                     ("tests/BUCK", "tools/BUCK_TREE", "tools/query.bxl", "tools/untracked.bzl", "tests/fixture.toml", "tests/sample.inv")]
        for name in tracked + untracked:
            self.write(name)
        self.track(tracked)
        return set(tracked + untracked)

    def test_collects_tracked_and_untracked_maintained_files(self):
        expected = self.maintained()
        groups = formatting.inventory()
        self.assertEqual({name for names in groups.values() for name in names}, expected)
        self.assertEqual(groups["build"], [f"{PRODUCT}/BUCK", f"{PRODUCT}/tests/BUCK"])
        self.assertIn(f"{PRODUCT}/PACKAGE", groups["starlark"])
        self.assertIn(f"{PRODUCT}/tests/fixture.toml", groups["toml"])
        self.assertEqual(groups["json"], [f"{PRODUCT}/requirements/node.inv", f"{PRODUCT}/tests/sample.inv"])

    def test_excludes_programs_generated_files_caches_and_symlinks(self):
        expected = self.maintained()
        protected = [f"{PRODUCT}/src/example.{suffix}" for suffix in
                     ("py", "rs", "ts", "js", "mjs", "css", "html", "c", "h", "dctl", "wgsl", "lean", "sh", "json", "yaml")]
        protected += ["BUCK", "build_defs/rules.bzl", "third_party/rust/Cargo.toml",
                      "third_party/rust/BUCK", "third_party/web/dependencies.bzl",
                      "libraries/perceptual-grade-core/BUCK",
                      "libraries/perceptual-grade-core/requirements/inventory.bzl",
                      "libraries/perceptual-grade-core/requirements/output.inv",
                      "products/perceptual-grade-blender/BUCK",
                      "products/perceptual-grade-blender/requirements/output.inv",
                      "products/perceptual-grade-blender/blender_manifest.toml",
                      "products/perceptual-grade-next-blender-backup/BUCK",
                      f"{PRODUCT}/.cargo/tracked.toml", f"{PRODUCT}/buck-out/tracked.bzl"]
        for name in protected:
            self.write(name)
        self.track(protected)
        for name in [f"{PRODUCT}/.cargo/untracked.toml", f"{PRODUCT}/buck-out/untracked.bzl",
                     f"{PRODUCT}/node_modules/package/BUCK", f"{PRODUCT}/src/untracked.py"]:
            self.write(name)
        (self.root / PRODUCT / "linked.toml").symlink_to(self.root / "third_party/rust/Cargo.toml")
        self.track([f"{PRODUCT}/linked.toml"])
        actual = {name for names in formatting.inventory().values() for name in names}
        self.assertEqual(actual, expected)

    def test_empty_inventory_fails_instead_of_passing_silently(self):
        self.write(f"{PRODUCT}/src/program.py")
        self.write(f"{PRODUCT}/tools/package_inventory.json", '{"key":1}')
        self.write("libraries/perceptual-grade-core/BUCK")
        self.write("products/perceptual-grade-blender/blender_manifest.toml")
        with self.assertRaisesRegex(ValueError, "refusing an empty formatting check"):
            formatting.inventory()

    def test_sapling_inventory_collects_tracked_and_unignored_unknown_files(self):
        expected = self.maintained()
        tracked = [f"{PRODUCT}/{name}" for name in
                   ("BUCK", "PACKAGE", "requirements/inventory.bzl", "blender_manifest.toml", "requirements/node.inv")]
        unknown = [f"{PRODUCT}/{name}" for name in
                   ("tests/BUCK", "tools/BUCK_TREE", "tools/query.bxl", "tools/untracked.bzl", "tests/fixture.toml", "tests/sample.inv")]
        unknown += ["libraries/perceptual-grade-core/BUCK", "products/perceptual-grade-blender/BUCK"]
        commands = []

        def run(command, **kwargs):
            commands.append(command)
            if command[:3] == ["git", "rev-parse", "--show-toplevel"]:
                return subprocess.CompletedProcess(command, 128, b"", b"")
            if command == ["sl", "root"]:
                return subprocess.CompletedProcess(command, 0, str(self.root).encode(), b"")
            if command == ["sl", "files", "--print0"]:
                return subprocess.CompletedProcess(command, 0, ("\0".join(tracked) + "\0").encode(), b"")
            if command == ["sl", "status", "--unknown", "--no-status", "--print0"]:
                return subprocess.CompletedProcess(command, 0, ("\0".join(unknown) + "\0").encode(), b"")
            self.fail(f"Unexpected command: {command}")

        with patch.dict(formatting.os.environ, {"CHROMATICITY_SAPLING_BIN": "sl"}), \
                patch.object(formatting.subprocess, "run", side_effect=run):
            groups = formatting.inventory()

        actual = {name for names in groups.values() for name in names}
        self.assertEqual(actual, expected)
        self.assertIn(["sl", "files", "--print0"], commands)
        self.assertIn(["sl", "status", "--unknown", "--no-status", "--print0"], commands)

    def test_check_and_fix_pass_only_explicit_product_paths(self):
        self.write(f"{PRODUCT}/BUCK")
        self.write(f"{PRODUCT}/blender_manifest.toml")
        self.write("libraries/perceptual-grade-core/BUCK")
        self.write("products/perceptual-grade-blender/blender_manifest.toml")
        for arguments, mode in (([], "check"), (["--fix"], "fix")):
            with self.subTest(mode=mode), patch.object(formatting.sys, "argv", ["format.py", *arguments]), \
                    patch.object(formatting, "tool", side_effect=lambda name: name), \
                    patch.object(formatting, "run", return_value=0) as run:
                self.assertEqual(formatting.main(), 0)
            self.assertEqual(run.call_args_list[0].args[0],
                             ["buildifier", f"-mode={mode}", "-lint=off", "-type=build", f"{PRODUCT}/BUCK"])
            self.assertEqual(run.call_args_list[1].args[0],
                             ["taplo", "fmt", *([] if arguments else ["--check"]), f"{PRODUCT}/blender_manifest.toml"])
            self.assertEqual(run.call_count, 2)

    def test_missing_starlark_files_do_not_expand_lint_to_other_products(self):
        self.write(f"{PRODUCT}/BUCK")
        self.write("products/perceptual-grade-blender/rules.bzl")
        with patch.object(formatting.sys, "argv", ["format.py", "--starlark-lint"]), \
                patch.object(formatting, "tool") as tool, patch.object(formatting, "run") as run:
            self.assertEqual(formatting.main(), 0)
        tool.assert_not_called()
        run.assert_not_called()

    def test_empty_format_group_never_invokes_a_recursive_default(self):
        self.write(f"{PRODUCT}/BUCK")
        with patch.object(formatting.sys, "argv", ["format.py"]), \
                patch.object(formatting, "tool", side_effect=lambda name: name) as tool, \
                patch.object(formatting, "run", return_value=0) as run:
            self.assertEqual(formatting.main(), 0)
        tool.assert_called_once_with("buildifier")
        run.assert_called_once_with(
            ["buildifier", "-mode=check", "-lint=off", "-type=build", f"{PRODUCT}/BUCK"])

    def test_inv_check_is_read_only_and_fix_preserves_unicode_and_order(self):
        name = f"{PRODUCT}/requirements/example.inv"
        original = '{\r\n"z":[3,1,2],"a":"\\u8272"}'
        self.write(name, original)
        path = self.root / name
        expected = '{\n  "z": [\n    3,\n    1,\n    2\n  ],\n  "a": "色"\n}\n'.encode("utf-8")
        errors = StringIO()
        with patch.object(formatting.sys, "argv", ["format.py"]), redirect_stderr(errors):
            self.assertEqual(formatting.main(), 1)
        self.assertIn(name, errors.getvalue())
        self.assertEqual(path.read_bytes(), original.encode("utf-8"))
        with patch.object(formatting.sys, "argv", ["format.py", "--fix"]):
            self.assertEqual(formatting.main(), 0)
        self.assertEqual(path.read_bytes(), expected)
        for arguments in ([], ["--fix"]):
            with patch.object(formatting.sys, "argv", ["format.py", *arguments]):
                self.assertEqual(formatting.main(), 0)
            self.assertEqual(path.read_bytes(), expected)

    def test_invalid_inv_reports_its_path_and_is_never_rewritten(self):
        name = f"{PRODUCT}/requirements/broken.inv"
        for original in ('{"unfinished":', '{"key":1,"key":2}',
                         '{"nested":{"key":1,"key":2}}', '{"value":NaN}',
                         '{"value":Infinity}', '{"value":-Infinity}', '{"value":1e999}'):
            for arguments in ([], ["--fix"]):
                with self.subTest(contents=original, arguments=arguments):
                    self.write(name, original)
                    errors = StringIO()
                    with patch.object(formatting.sys, "argv", ["format.py", *arguments]), redirect_stderr(errors):
                        self.assertEqual(formatting.main(), 1)
                    self.assertIn(f"{name}: cannot format JSON:", errors.getvalue())
                    self.assertEqual((self.root / name).read_bytes(), original.encode("utf-8"))

    def test_json_extension_and_excluded_inv_files_are_never_validated_or_fixed(self):
        self.write(f"{PRODUCT}/requirements/example.inv", '{}\n')
        excluded = [f"{PRODUCT}/tools/package_inventory.json",
                    "libraries/perceptual-grade-core/requirements/output.inv",
                    "products/perceptual-grade-blender/requirements/output.inv"]
        for name in excluded:
            self.write(name, "this is deliberately invalid JSON")
        for arguments in ([], ["--fix"]):
            with patch.object(formatting.sys, "argv", ["format.py", *arguments]):
                self.assertEqual(formatting.main(), 0)
            for name in excluded:
                self.assertEqual((self.root / name).read_text(), "this is deliberately invalid JSON")


if __name__ == "__main__":
    unittest.main()
