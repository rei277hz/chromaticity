from importlib.resources import files
import json
import tomllib
import unittest
import zipfile


class PublicationComparePackageTests(unittest.TestCase):
    def test_archive_contains_all_publication_strategies_and_proofs(self):
        root = files("tests.perceptual_grade_blender")
        report = json.loads((root / "publication_compare_report.json").read_text())
        archive_path = root / "publication_compare.zip"
        with zipfile.ZipFile(archive_path) as archive:
            names = set(archive.namelist())
            self.assertTrue({
                "__init__.py",
                "nodes.py",
                "blender_manifest.toml",
                "policy/compositor_publication.py",
                "policy/image_publication.py",
                "policy/parameter_publication.py",
                "policy/bank_publication.py",
                "runtime/compositor_receipts.py",
                "runtime/__init__.py",
                "runtime/drag_trace.py",
                "runtime/image_publication.py",
                "runtime/parameter_publication.py",
                "runtime/bank_publication.py",
                "runtime/publication_compare_diagnostics.py",
                "runtime/publication.py",
            }.issubset(names))
            manifest = tomllib.loads(archive.read("blender_manifest.toml").decode())
            self.assertEqual(manifest["id"], "grade_publication_compare")
            self.assertEqual(manifest["blender_version_min"], "5.2.0")
            policies = {name for name in names if name.startswith("policy/")
                        and name.endswith(".py") and name != "policy/__init__.py"}

        proved = {entry["runtime_source"]
                  for entry in report["machine_proofs"].values()}
        self.assertEqual(proved, policies)
        self.assertEqual(len(proved), 4)


if __name__ == "__main__":
    unittest.main()
