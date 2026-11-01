from importlib.resources import files
import ast
import hashlib
import json
import tomllib
import zipfile
import unittest


class NextExtensionTests(unittest.TestCase):
    def test_release_license_and_corresponding_source_grant(self):
        with zipfile.ZipFile(files("tests.next_product") / "perceptual_grade_next.zip") as archive:
            legal_files = [name for name in archive.namelist()
                           if name.rsplit("/", 1)[-1].lower().startswith(("license", "copying", "notice"))]
            self.assertEqual(legal_files, ["LICENSE"])
            explanation, gpl = archive.read("LICENSE").split(b"                    GNU GENERAL PUBLIC LICENSE", 1)
            self.assertEqual(hashlib.sha256(b"                    GNU GENERAL PUBLIC LICENSE" + gpl).hexdigest(),
                             "3972dc9744f6499f0f9b2dbf76696f2ae7ad8af9b23dde66d6af86c9dfb36986")
            explanation_text = " ".join(explanation.decode().split())
            for grant in ("GPL-3.0-or-later", "Corresponding Source", "MIT OR Apache-2.0", "CC0-1.0"):
                self.assertIn(grant, explanation_text)
            self.assertIn(b"perceptual_grade_nodes/output_boundary.npz", explanation)
            self.assertEqual(tomllib.loads(archive.read("blender_manifest.toml").decode())["license"],
                             ["SPDX:GPL-3.0-or-later"])

    def test_runtime_component_ownership_and_dependencies_are_independent(self):
        resources = files("tests.next_product")
        components = json.loads((resources / "runtime_components.json").read_text())
        self.assertEqual(set(components), {
            "color_core",
            "perceptual_grade_next_core",
            "perceptual_grade_nodes",
            "perceptual_grade_next_blender",
        })
        expected = {
            "color_core": ("root//libraries/color-core", []),
            "perceptual_grade_next_core": (
                "root//libraries/perceptual-grade-next-core", ["color_core"]
            ),
            "perceptual_grade_nodes": (
                "root//libraries/perceptual-grade-nodes", ["color_core"]
            ),
            "perceptual_grade_next_blender": (
                "root//products/perceptual-grade-next-blender",
                ["perceptual_grade_next_core", "perceptual_grade_nodes"],
            ),
        }
        for package, (owner, dependencies) in expected.items():
            with self.subTest(package=package):
                self.assertEqual(components[package]["owner"], owner)
                self.assertEqual(components[package]["dependencies"], dependencies)
        self.assertNotIn("perceptual_grade_core", components)
        self.assertNotIn("perceptual_grade_blender", components)

        tree = resources / "extension_tree"
        declared_files = {
            f"{package}/{name}"
            for package, component in components.items()
            for name in component["files"]
        }
        packaged_component_files = {
            path.relative_to(tree).as_posix()
            for path in tree.rglob("*")
            if path.is_file() and path.relative_to(tree).parts[0] in components
        }
        self.assertEqual(packaged_component_files, declared_files)

    def test_runtime_json_inventory_matches_the_declared_package(self):
        resources = files("tests.next_product")
        inventory = json.loads((resources / "package_inventory.json").read_text())
        tree = resources / "extension_tree"
        json_sources = sorted(
            path.relative_to(tree).as_posix()
            for path in tree.rglob("*.json") if path.is_file()
        )
        self.assertEqual(inventory, {"schema": 1, "runtime_json": json_sources})

    def test_archive_matches_its_declared_tree_and_owns_no_old_runtime(self):
        resource_root = files("tests.next_product")
        tree = resource_root / "extension_tree"
        expected = {
            path.relative_to(tree).as_posix(): path.read_bytes()
            for path in tree.rglob("*") if path.is_file()
        }
        with zipfile.ZipFile(resource_root / "perceptual_grade_next.zip") as archive:
            self.assertIsNone(archive.testzip())
            self.assertEqual(set(archive.namelist()), set(expected))
            self.assertEqual({name: archive.read(name) for name in expected}, expected)
            names = set(expected)
            self.assertIn("blender_manifest.toml", names)
            self.assertIn("README.md", names)
            self.assertIn("perceptual_grade_next_blender/native_grade.py", names)
            self.assertIn("perceptual_grade_next_core/__init__.py", names)
            self.assertIn("perceptual_grade_nodes/persistent.py", names)
            self.assertIn("perceptual_grade_next_blender/operators.py", names)
            self.assertIn("__init__.py", names)
            self.assertIn("perceptual_grade_next_blender/__init__.py", names)
            self.assertNotIn("perceptual_grade_core/__init__.py", names)
            self.assertNotIn("perceptual_grade_blender/__init__.py", names)
            self.assertFalse(any(name.startswith(("tests/", "tools/", "buck-out/")) for name in names))

        manifest = (tree / "blender_manifest.toml").read_text()
        self.assertIn('id = "perceptual_grade"', manifest)
        self.assertIn('version = "0.1.0"', manifest)
        entrypoint = (tree / "__init__.py").read_text()
        self.assertIn("perceptual_grade_next_blender import register", entrypoint)

    def test_product_runtime_has_no_old_pair_imports_or_eager_blender_import(self):
        source_root = files("tests.next_product") / "extension_tree"
        package_root = source_root / "perceptual_grade_next_blender"
        sources = sorted(package_root.rglob("*.py"))
        self.assertTrue(sources)
        for path in sources:
            tree = ast.parse(path.read_text(), filename=str(path))
            for node in tree.body:
                if isinstance(node, ast.Import):
                    self.assertFalse(any(alias.name == "bpy" or alias.name.startswith("bpy.")
                                         for alias in node.names), path)
                elif isinstance(node, ast.ImportFrom):
                    self.assertFalse(node.module == "bpy" or
                                     (node.module or "").startswith("bpy."), path)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    modules = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom):
                    modules = [node.module or ""]
                else:
                    continue
                self.assertFalse(any(
                    module.split(".")[0] == prefix
                    for module in modules
                    for prefix in ("perceptual_grade_core", "perceptual_grade_blender")
                ), path)

        core_root = source_root / "perceptual_grade_next_core"
        core_sources = sorted(core_root.rglob("*.py"))
        self.assertTrue(core_sources)
        for path in core_sources:
            tree = ast.parse(path.read_text(), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    modules = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom):
                    modules = [node.module or ""]
                else:
                    continue
                self.assertFalse(any(module.startswith("color_tools.") for module in modules), path)
                self.assertFalse(any(module.split(".")[0] in {
                    "perceptual_grade_core", "perceptual_grade_reference",
                    "perceptual_grade_blender",
                } for module in modules), path)


if __name__ == "__main__":
    unittest.main()
