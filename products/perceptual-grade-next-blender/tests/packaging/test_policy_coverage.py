"""A shipped policy cannot silently lose its required build evidence."""

import json
from pathlib import Path
import tempfile
import unittest

from product_build.perceptual_grade_package import build, verify_policy_coverage


class PolicyCoverageTests(unittest.TestCase):
    def manifest(self, *sources):
        return {"version": 2, "machines": {
            str(index): {"path": str(index), "runtime_source": source}
            for index, source in enumerate(sources)
        }}

    def test_every_policy_module_requires_evidence(self):
        entries = {"policy/__init__.py": b"", "policy/node.py": b"", "policy/helper.py": b""}
        verify_policy_coverage(entries, self.manifest("policy/node.py", "policy/helper.py"))
        with self.assertRaisesRegex(ValueError, "missing=.*helper"):
            verify_policy_coverage(entries, self.manifest("policy/node.py"))
        entries["policy/new_policy.py"] = b""
        with self.assertRaisesRegex(ValueError, "missing=.*new_policy"):
            verify_policy_coverage(entries, self.manifest("policy/node.py", "policy/helper.py"))

    def test_unshipped_evidence_and_empty_coverage_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "extra=.*old"):
            verify_policy_coverage({"policy/node.py": b""},
                                   self.manifest("policy/node.py", "policy/old.py"))
        with self.assertRaises(ValueError):
            verify_policy_coverage({"policy/__init__.py": b""}, self.manifest())

    def test_multiple_requirement_sets_can_cover_one_source(self):
        verify_policy_coverage({"policy/node.py": b""},
                               self.manifest("policy/node.py", "policy/node.py"))

    def test_failed_coverage_removes_stale_package_artifacts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tree, proofs, output = root / "tree", root / "proofs", root / "out"
            (tree / "policy").mkdir(parents=True)
            (tree / "policy/helper.py").write_text("VALUE = 1\n")
            proofs.mkdir()
            (proofs / "manifest.json").write_text(json.dumps(self.manifest()))
            output.mkdir()
            names = ("perceptual_grade.zip", ".perceptual_grade.zip.candidate", "package-report.json")
            for name in names:
                (output / name).write_text("stale")
            with self.assertRaises(ValueError):
                build(tree, output, root / "inventory.json", proofs)
            self.assertTrue(all(not (output / name).exists() for name in names))
