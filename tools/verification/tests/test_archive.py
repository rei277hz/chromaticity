"""Check each installed product ZIP against its Buck source tree and inventory."""
import hashlib
from importlib.resources import files
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from verification.packaging import package, sources, verify_archive


class ArchiveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.resources = Path(str(files(__package__)))
        # Buck exposes directory resources as links to the declared artifact.
        cls.tree = (cls.resources / 'tree').resolve()
        cls.inventory_path = cls.resources / 'package_inventory.json'
        cls.inventory_bytes = cls.inventory_path.read_bytes()
        cls.inventory = json.loads(cls.inventory_bytes)
        cls.expected = sources(cls.tree)
        cls.product = cls.resources / 'product.zip'

    def test_actual_product_archive_has_exact_runtime_members_and_bytes(self):
        self.assertEqual(verify_archive(self.product, self.inventory,
                                        expected_sources=self.expected), self.expected)
        with zipfile.ZipFile(self.product) as bundle:
            self.assertEqual(bundle.namelist(), sorted(self.expected))
            self.assertFalse(any(name == '_vendor' or name.startswith('_vendor/')
                                 for name in bundle.namelist()))
            self.assertEqual({name for name in bundle.namelist() if name.endswith('.json')},
                             set(self.inventory['runtime_json']))
            for member in bundle.infolist():
                self.assertEqual(member.date_time, (2026, 1, 1, 0, 0, 0))
                self.assertEqual(member.external_attr >> 16, 0o100644)
                self.assertEqual(bundle.read(member.filename), self.expected[member.filename])

    def test_repackaging_is_deterministic_and_matches_product_zip(self):
        with tempfile.TemporaryDirectory() as directory:
            first, second = Path(directory) / 'first.zip', Path(directory) / 'second.zip'
            package(self.tree, first, inventory_path=self.inventory_path)
            report_bytes = (Path(directory) / 'package-report.json').read_bytes()
            report = json.loads(report_bytes)
            package(self.tree, second, inventory_path=self.inventory_path)
            self.assertEqual(first.read_bytes(), second.read_bytes())
            self.assertEqual(first.read_bytes(), self.product.read_bytes())
            self.assertEqual(report['archive_sha256'], hashlib.sha256(first.read_bytes()).hexdigest())
            self.assertEqual(report['inventory_sha256'], hashlib.sha256(self.inventory_bytes).hexdigest())
            self.assertEqual(report['source_sha256'], {
                name: hashlib.sha256(data).hexdigest() for name, data in sorted(self.expected.items())
            })


if __name__ == '__main__':
    unittest.main()
