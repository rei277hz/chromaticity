"""Boundary tests for proof-independent deterministic ZIP packaging."""
import json
import stat
import tempfile
from pathlib import Path
import unittest
import warnings
import zipfile

from verification.packaging import package, sources, verify_archive


class PackageBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.tree = self.root / 'tree'
        self.tree.mkdir()
        (self.tree / 'runtime.py').write_bytes(b'value = 7\n')
        (self.tree / 'locale.json').write_bytes(b'{"label": "Example"}')
        self.expected = sources(self.tree)
        self.inventory = {'schema': 1, 'runtime_json': ['locale.json']}
        self.inventory_path = self.root / 'package_inventory.json'
        self.inventory_path.write_text(json.dumps(self.inventory), encoding='utf-8')
        self.archive = self.root / 'candidate.zip'

    def write(self, entries=None, *, duplicate=None, nonregular=None):
        entries = self.expected if entries is None else entries
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', UserWarning)
            with zipfile.ZipFile(self.archive, 'w') as bundle:
                for name, data in entries.items():
                    info = zipfile.ZipInfo(name)
                    if name == nonregular:
                        info.create_system = 3
                        info.external_attr = (stat.S_IFLNK | 0o777) << 16
                    bundle.writestr(info, data)
                if duplicate is not None:
                    bundle.writestr(duplicate, entries[duplicate])

    def verify(self, *, entries=None, inventory=None):
        expected = self.expected if entries is None else entries
        selected = self.inventory if inventory is None else inventory
        return verify_archive(self.archive, selected, expected_sources=expected)

    def test_missing_extra_and_changed_members_reject(self):
        self.write({name: data for name, data in self.expected.items() if name != 'locale.json'})
        with self.assertRaises(ValueError):
            self.verify()

        extra = {**self.expected, 'extra.py': b'pass\n'}
        self.write(extra)
        with self.assertRaises(ValueError):
            self.verify()

        changed = {**self.expected, 'runtime.py': b'value = 8\n'}
        self.write(changed)
        with self.assertRaises(ValueError):
            self.verify()

    def test_duplicate_unsafe_and_nonregular_members_reject(self):
        self.write(duplicate='runtime.py')
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            self.verify()

        for name in ('../escape.py', '/absolute.py', './relative.py',
                     'folder//file.py', 'folder\\file.py', 'C:/drive.py'):
            entries = {**self.expected, name: b'pass\n'}
            self.write(entries)
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.verify(entries=entries)

        self.write(nonregular='runtime.py')
        with self.assertRaisesRegex(ValueError, 'regular files'):
            self.verify()

    def test_json_allowlist_is_exact(self):
        for names in ([], ['locale.json', 'locale.json'], ['locale.json', 'missing.json']):
            selected = {'schema': 1, 'runtime_json': names}
            self.write()
            with self.subTest(names=names), self.assertRaises(ValueError):
                self.verify(inventory=selected)

        entries = {**self.expected, 'extra.json': b'{}'}
        self.write(entries)
        with self.assertRaisesRegex(ValueError, 'Undeclared runtime JSON'):
            self.verify(entries=entries)

    def test_proof_and_build_payloads_reject(self):
        payloads = (
            ('assurance/report.json', b'{}'),
            ('compiler/tool.py', b'pass\n'),
            ('z3/__init__.py', b'pass\n'),
            ('proofs/Contract.v', b'Theorem ok : True.\n'),
            ('machine.receipt.json', b'{}'),
            ('machine.pyc', b'\x00'),
        )
        for name, data in payloads:
            entries = {**self.expected, name: data}
            self.write(entries)
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.verify(entries=entries)

        for source in (b'from z3 import Solver\n', b'from . import compiler\n',
                       b'PROPERTY_IDS = ()\n', b'SPEC_ID = "spec:test"\n',
                       b'data = {"expected_source_sha256": {}}\n'):
            entries = {**self.expected, 'runtime.py': source}
            self.write(entries)
            with self.subTest(source=source), self.assertRaises(ValueError):
                self.verify(entries=entries)

    def test_verification_and_generated_contract_paths_are_build_only(self):
        for name in ('invariant/verification/__init__.py',
                     'invariant/verification/evaluator.py',
                     'other/invariant/verification/runtime_contracts.py',
                     '_vendor/invariant/verification/runtime_contracts.py',
                     'product/_policy_contracts.py'):
            changed = {**self.expected, name: b'pass\n'}
            self.write(changed)
            with self.subTest(path=name), self.assertRaisesRegex(
                    ValueError, 'Build-only evidence or tooling'):
                self.verify(entries=changed)

    def test_deterministic_package_and_failure_cleanup(self):
        first, second = self.root / 'first.zip', self.root / 'second.zip'
        package(self.tree, first, inventory_path=self.inventory_path)
        package(self.tree, second, inventory_path=self.inventory_path)
        self.assertEqual(first.read_bytes(), second.read_bytes())
        self.assertEqual(verify_archive(first, self.inventory, expected_sources=self.expected), self.expected)
        with zipfile.ZipFile(first) as bundle:
            self.assertEqual(bundle.namelist(), sorted(self.expected))
            for item in bundle.infolist():
                self.assertEqual(item.date_time, (2026, 1, 1, 0, 0, 0))
                self.assertEqual(item.external_attr >> 16, 0o100644)

        stale_output = self.root / 'rejected.zip'
        stale_report = self.root / 'package-report.json'
        stale_output.write_bytes(b'old package')
        stale_report.write_bytes(b'old report')
        (self.tree / 'proofs').mkdir()
        (self.tree / 'proofs' / 'Contract.v').write_text('Theorem ok : True.\n')
        with self.assertRaises(ValueError):
            package(self.tree, stale_output, inventory_path=self.inventory_path)
        self.assertFalse(stale_output.exists())
        self.assertFalse(stale_report.exists())
        self.assertFalse((self.root / '.rejected.zip.candidate').exists())

    def test_source_symlinks_and_output_inside_source_tree_reject(self):
        (self.tree / 'linked.py').symlink_to(self.tree / 'runtime.py')
        with self.assertRaisesRegex(ValueError, 'regular files'):
            sources(self.tree)
        (self.tree / 'linked.py').unlink()
        with self.assertRaisesRegex(ValueError, 'outside'):
            package(self.tree, self.tree / 'output.zip', inventory_path=self.inventory_path)


if __name__ == '__main__':
    unittest.main()
