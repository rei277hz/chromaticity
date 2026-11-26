"""Documentation coverage follows declared chapters and actual policy comments."""

from copy import deepcopy
from importlib.resources import files
import json
from pathlib import Path
import re
import tempfile
import unittest

from product_build.technical_report_audit import PRODUCT, audit_report


BOOK = "products/perceptual-grade-book"
REFERENCE = "libraries/perceptual-grade-reference/src"


class TechnicalReportAuditTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.docs = self.root / "book"
        self.product = self.root / "next"
        self.tests = self.root / "next-tests"
        self.book_evidence = self.root / "book-evidence"
        self.reference = self.root / "reference"
        self.roots = {
            PRODUCT: self.product,
            PRODUCT + "/tests": self.tests,
            BOOK: self.book_evidence,
            REFERENCE: self.reference,
        }
        self.source = PRODUCT + "/src/policy/sample.py"
        self.test_source = PRODUCT + "/tests/policy/test_sample.py"
        self.write(self.docs / "src/report/SUMMARY.md", """# Summary

[Technical Report](README.md)
- [Policies](development/policies.md)
""")
        self.write(self.docs / "src/report/README.md", "# Technical Report\n")
        self.write(self.docs / "src/development/policies.md", """# Policies

<a id="grade-policy.overview"></a>

## Contract

<a id="grade-policy.contract"></a>

## Sample

<a id="grade-policy.sample"></a>
""")
        self.write(self.product / "src/policy/__init__.py", "")
        self.write(self.product / "src/policy/sample.py",
                   "# pg-book: technical-report/en#grade-policy.sample\nVALUE = 1\n")
        self.write(self.tests / "policy/test_sample.py", "def test_sample():\n    pass\n")
        self.manifest = {
            "schema": 1,
            "chapters": [self.chapter("README.md"),
                         self.chapter("development/policies.md")],
            "policies": [
                {"anchor": anchor, "kind": "conceptual", "sources": [], "evidence": []}
                for anchor in ("grade-policy.overview", "grade-policy.contract")
            ] + [{
                "anchor": "grade-policy.sample", "kind": "production",
                "sources": [self.source], "evidence": [self.test_source],
            }],
        }
        # Establish a valid baseline so a negative test cannot pass because its
        # fixture was already missing unrelated chapter or source evidence.
        self.assertEqual(self.audit(), {
            "chapters": 2, "policy_sections": 3, "shipped_policies": 1,
        })

    @staticmethod
    def write(path, text):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def chapter(self, path):
        return {
            "path": path, "scope": "blender",
            "review": "Reviewed against the current sample policy and test.",
            "evidence": [self.source, self.test_source],
        }

    def audit(self, manifest=None):
        return audit_report(self.manifest if manifest is None else manifest,
                            self.docs, self.roots)

    def test_report_introduction_and_split_test_resource_are_supported(self):
        self.assertFalse((self.docs / "src/README.md").exists())
        self.assertFalse((self.product / "tests/policy/test_sample.py").exists())
        self.assertEqual(self.audit()["chapters"], len(self.manifest["chapters"]))

    def test_missing_or_duplicate_manifest_chapter_fails(self):
        missing = deepcopy(self.manifest)
        missing["chapters"].pop()
        duplicate = deepcopy(self.manifest)
        duplicate["chapters"].append(deepcopy(duplicate["chapters"][0]))
        for manifest in (missing, duplicate):
            with self.subTest(chapters=manifest["chapters"]), self.assertRaises(ValueError):
                self.audit(manifest)

    def test_new_summary_chapter_requires_review(self):
        with (self.docs / "src/report/SUMMARY.md").open("a", encoding="utf-8") as stream:
            stream.write("- [New chapter](development/new.md)\n")
        self.write(self.docs / "src/development/new.md", "# New chapter\n")
        with self.assertRaises(ValueError):
            self.audit()

    def test_invalid_scope_or_empty_review_fails(self):
        for field, value in (("scope", "unknown"), ("review", "  ")):
            manifest = deepcopy(self.manifest)
            manifest["chapters"][0][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.audit(manifest)

    def test_obsolete_chapter_scopes_are_rejected(self):
        for scope in ("next", "legacy", "mixed"):
            manifest = deepcopy(self.manifest)
            manifest["chapters"][0]["scope"] = scope
            with self.subTest(scope=scope), self.assertRaises(ValueError):
                self.audit(manifest)

    def test_evidence_must_be_an_existing_declared_file(self):
        for evidence in (
                PRODUCT + "/tests/policy/missing.py",
                "products/other/src/policy/sample.py",
                PRODUCT + "/src/policy"):
            manifest = deepcopy(self.manifest)
            manifest["chapters"][0]["evidence"] = [evidence]
            with self.subTest(evidence=evidence), self.assertRaises(ValueError):
                self.audit(manifest)

    def test_evidence_paths_cannot_escape_or_use_noncanonical_spelling(self):
        for evidence in (
                PRODUCT + "/src/policy/../policy/sample.py",
                PRODUCT + "/src/./policy/sample.py",
                "/" + self.source,
                self.source.replace("/src/", "//src/")):
            manifest = deepcopy(self.manifest)
            manifest["chapters"][0]["evidence"] = [evidence]
            with self.subTest(evidence=evidence), self.assertRaises(ValueError):
                self.audit(manifest)

    def test_policy_needs_both_source_and_test_evidence(self):
        for field, value in (("sources", []), ("evidence", []),
                             ("evidence", [self.source])):
            manifest = deepcopy(self.manifest)
            manifest["policies"][-1][field] = value
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                self.audit(manifest)

    def test_missing_source_comment_or_string_only_reference_fails(self):
        for source in (
                "VALUE = 1\n",
                'VALUE = "# pg-book: technical-report/en#grade-policy.sample"\n',
                '"""# pg-book: technical-report/en#grade-policy.sample"""\n'):
            self.write(self.product / "src/policy/sample.py", source)
            with self.subTest(source=source), self.assertRaises(ValueError):
                self.audit()

    def test_manifest_anchor_must_exist_in_the_report(self):
        manifest = deepcopy(self.manifest)
        manifest["policies"][-1]["anchor"] = "grade-policy.missing"
        with self.assertRaises(ValueError):
            self.audit(manifest)

    def test_new_policy_anchor_requires_manifest_coverage(self):
        with (self.docs / "src/development/policies.md").open("a", encoding="utf-8") as stream:
            stream.write('\n## Additional\n\n<a id="grade-policy.additional"></a>\n')
        with self.assertRaises(ValueError):
            self.audit()

    def test_new_shipped_policy_cannot_reuse_another_modules_coverage(self):
        self.write(self.product / "src/policy/additional.py",
                   "# pg-book: technical-report/en#grade-policy.sample\nVALUE = 2\n")
        with self.assertRaises(ValueError):
            self.audit()

    def test_only_overview_and_contract_can_be_conceptual_exemptions(self):
        manifest = deepcopy(self.manifest)
        manifest["policies"][-1].update(kind="conceptual", sources=[], evidence=[])
        with self.assertRaises(ValueError):
            self.audit(manifest)

    def test_source_scan_ignores_test_fixtures_and_unrelated_directories(self):
        self.write(self.tests / "policy/test_fixture.py",
                   "# pg-book: technical-report/en#grade-policy.not-a-section\n")
        self.write(self.product / "generated/fixture.py",
                   "# pg-book: technical-report/en#grade-policy.not-a-section\n")
        self.assertEqual(self.audit()["shipped_policies"], 1)


class DeclaredTechnicalReportAuditTests(unittest.TestCase):
    def test_current_report_and_next_policy_sources_have_complete_coverage(self):
        resources = Path(files("tests.perceptual_grade_blender"))
        manifest = json.loads((resources / "audit.json").read_text(encoding="utf-8"))
        result = audit_report(manifest, resources / "book_report", {
            PRODUCT: resources / "next_sources",
            PRODUCT + "/tests": resources / "next_tests",
            BOOK: resources / "book_evidence",
            REFERENCE: resources / "reference_sources",
        })
        summary = (resources / "book_report/src/report/SUMMARY.md").read_text(encoding="utf-8")
        chapters = re.findall(r"\]\(([^)]+\.md)\)", summary)
        policies = [path for path in (resources / "next_sources/src/policy").glob("*.py")
                    if path.name != "__init__.py"]
        self.assertEqual(result["chapters"], len(chapters))
        self.assertEqual(result["policy_sections"], len(manifest["policies"]))
        self.assertEqual(result["shipped_policies"], len(policies))


if __name__ == "__main__":
    unittest.main()
