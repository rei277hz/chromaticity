import copy
import json
from importlib.resources import files
from pathlib import Path
import unittest

try:
    from tests.perceptual_grade_next_core import canonical_properties
except ModuleNotFoundError:
    import canonical_properties


class CanonicalPropertyInventoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if __package__ == "tests.perceptual_grade_next_core":
            resources = files(__package__)
            cls.crosswalk = json.loads((resources / "canonical-properties.json").read_text())
            cls.design = (resources / "STATE_MACHINE_DESIGN.md").read_text()
            cls.proof_inputs = Path(str(resources / "proof-inputs"))
            cls.adapter_inputs = Path(str(resources / "adapter-inputs"))
            cls.adapter_test_inputs = Path(str(resources / "adapter-test-inputs"))
        else:
            repository = Path(__file__).resolve().parents[3]
            cls.crosswalk = json.loads((repository / "libraries/perceptual-grade-next-core/requirements/canonical-properties.json").read_text())
            cls.design = (repository / "products/perceptual-grade-next-blender/STATE_MACHINE_DESIGN.md").read_text()
            cls.proof_inputs = repository
            cls.adapter_inputs = repository
            cls.adapter_test_inputs = repository

    def read_source(self, path):
        return (self.proof_inputs / path).read_text()

    def read_evidence(self, path):
        try:
            return (self.adapter_inputs / path).read_bytes()
        except OSError:
            return (self.adapter_test_inputs / path).read_bytes()

    def validate(self, crosswalk=None, read_source=None):
        return canonical_properties.validate(
            copy.deepcopy(self.crosswalk if crosswalk is None else crosswalk),
            self.design,
            self.read_source if read_source is None else read_source,
            self.read_evidence,
        )

    def test_live_crosswalk_covers_design_and_references_required_properties(self):
        report = self.validate()
        self.assertEqual(report["canonical_requirement_count"], 60)
        self.assertGreater(len(report["validated_proof_targets"]), 0)
        self.assertGreater(report["status_counts"]["open"], 0)
        self.assertGreater(report["status_counts"]["partial"], 0)
        self.assertGreater(report["status_counts"]["adapter_premise"], 0)

    def test_missing_or_duplicate_canonical_id_is_rejected(self):
        missing = copy.deepcopy(self.crosswalk)
        missing["requirements"].pop()
        with self.assertRaisesRegex(canonical_properties.InventoryError, "canonical ID mismatch"):
            self.validate(missing)

        duplicate = copy.deepcopy(self.crosswalk)
        duplicate["requirements"].append(copy.deepcopy(duplicate["requirements"][0]))
        with self.assertRaisesRegex(canonical_properties.InventoryError, "duplicate crosswalk IDs"):
            self.validate(duplicate)

    def test_false_full_proof_claim_is_rejected(self):
        changed = copy.deepcopy(self.crosswalk)
        entry = next(item for item in changed["requirements"] if item["status"] == "partial")
        entry["status"] = "proved"
        with self.assertRaisesRegex(canonical_properties.InventoryError, "proved requirements cannot have remaining gaps"):
            self.validate(changed)

    def test_stale_or_unrequired_property_reference_is_rejected(self):
        changed = copy.deepcopy(self.crosswalk)
        entry = next(item for item in changed["requirements"] if item["proofs"])
        alias = entry["proofs"][0]
        changed["proof_catalog"][alias]["property"] = "not_a_real_property"
        with self.assertRaisesRegex(canonical_properties.InventoryError, "missing .inv property"):
            self.validate(changed)

        changed = copy.deepcopy(self.crosswalk)
        entry = next(item for item in changed["requirements"] if item["proofs"])
        alias = entry["proofs"][0]
        proof = changed["proof_catalog"][alias]
        actual_buck = self.read_source("libraries/perceptual-grade-next-core/BUCK")
        altered_buck = actual_buck.replace('"' + proof["property"] + '"', '"another_property"', 1)
        with self.assertRaisesRegex(canonical_properties.InventoryError, "does not require"):
            self.validate(changed, lambda path: altered_buck if path.endswith("/BUCK") else self.read_source(path))

    def test_unknown_gap_is_rejected(self):
        changed = copy.deepcopy(self.crosswalk)
        entry = next(item for item in changed["requirements"] if item["remaining_gaps"])
        entry["remaining_gaps"] = ["made_up_gap"]
        with self.assertRaisesRegex(canonical_properties.InventoryError, "unknown or unexplained gap"):
            self.validate(changed)

    def test_stale_adapter_evidence_path_is_rejected(self):
        changed = copy.deepcopy(self.crosswalk)
        entry = next(item for item in changed["requirements"] if item["adapter_evidence"])
        entry["adapter_evidence"][0] = "products/not-a-real-evidence-file.py"
        with self.assertRaisesRegex(canonical_properties.InventoryError, "missing adapter evidence"):
            self.validate(changed)


if __name__ == "__main__":
    unittest.main()
