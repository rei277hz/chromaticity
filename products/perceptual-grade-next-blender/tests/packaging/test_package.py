from importlib.resources import files
import tomllib
import unittest
import zipfile


class PackageTests(unittest.TestCase):
    def test_archive_contains_grade_runtime_and_linear_node_library(self):
        resource = files("tests.perceptual_grade_blender") / "extension.zip"
        with zipfile.ZipFile(resource) as archive:
            names = set(archive.namelist())
            self.assertTrue({
                "__init__.py",
                "lut_gpu.py",
                "lut_codec.py",
                "lut_helper.py",
                "lut_worker.py",
                "blender_runtime/execution/worker_main.py",
                "blender_runtime/execution/runtime.py",
                "nodes.py",
                "blender_manifest.toml",
                "LICENSE",
                "README.md",
                "policy/__init__.py",
                "policy/preparation.py",
                "policy/node.py",
                "kernel/__init__.py",
                "kernel/graph.py",
                "kernel/prepare.py",
                "kernel/lut.py",
                "preparation_runtime.py",
                "color_core/__init__.py",
                "color_core/linear.py",
            }.issubset(names))
            self.assertFalse(any(name.startswith("perceptual_grade_blender/")
                                 for name in names))
            self.assertNotIn("perceptual_grade_core/registration.py", names)
            self.assertFalse(any(name.startswith("perceptual_grade_core/") for name in names))
            self.assertFalse(any(name.startswith("src/") for name in names))
            self.assertNotIn("kernel/output_boundary.npz", names)
            manifest = tomllib.loads(archive.read("blender_manifest.toml").decode())
            self.assertEqual(manifest["id"], "perceptual_grade")
            self.assertEqual(manifest["name"], "Perceptual Grade")
            self.assertEqual(manifest["blender_version_min"], "5.2.0")
            self.assertEqual(manifest["license"], ["SPDX:GPL-3.0-or-later"])
            self.assertFalse(any(name.startswith("invariant/") for name in names))
            self.assertFalse(any(name.endswith("_contracts.py") for name in names))


if __name__ == "__main__":
    unittest.main()
