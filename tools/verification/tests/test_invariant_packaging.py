"""Shared machine evidence must bind the exact sources and runtime contracts."""
import copy
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from verification.invariant_report import InvariantProofs, validate_bundle
from verification.packaging import package


def sha(data):
    return hashlib.sha256(data).hexdigest()


class SharedProofPackagingTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.tree = self.root / 'tree'
        self.evidence = self.root / 'evidence'
        self.inputs = self.evidence / '0/inputs'
        self.proof = self.evidence / '0/proof'
        self.output = self.root / 'out/product.zip'
        self.inventory = self.root / 'inventory.json'
        self.inventory.write_text('{"schema":1,"runtime_json":[]}')
        self.source = 'product/policy.py'
        self.validator = 'product/_policy_contracts.py'
        binder = 'invariant/verification/runtime_contracts.py'
        self.entries = {self.source: b'VALUE = 1\n', self.validator: b'def bind(module):\n    return module\n',
                        binder: b'def bind(module):\n    return module\n'}
        for name, data in self.entries.items():
            path = self.tree / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(data)
        self.required = {'version': 1, 'properties': ['current'], 'witnesses': ['admitted'], 'mutations': ['stale']}
        requirements = {'properties': [{'name': 'current'}], 'witnesses': [{'name': 'admitted'}],
                        'mutations': [{'name': 'stale'}]}
        fixtures = {'source.py': self.entries[self.source], 'requirements.inv': json.dumps(requirements).encode(),
                    'inventory.json': json.dumps(self.required).encode(), 'solver/z3.whl': b'declared fixture wheel',
                    'verifier/checker.py': b'# fixture checker\n', 'verifier/runtime_contracts.py': self.entries[binder]}
        for name, data in fixtures.items():
            path = self.inputs / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(data)
        self.proof.mkdir(parents=True)
        (self.proof / 'validators.py').write_bytes(self.entries[self.validator])
        hashes = {name: sha(data) for name, data in fixtures.items()}
        self.report = {'version': 1, 'ok': True, 'required_properties': ['current'],
                       'required_witnesses': ['admitted'], 'required_mutations': ['stale'],
                       'obligations': [{'name': 'property.current', 'expected': 'unsat', 'actual': 'unsat', 'ok': True},
                                       {'name': 'witness.admitted', 'expected': 'sat', 'actual': 'sat', 'ok': True}],
                       'mutations': [{'name': 'stale', 'ok': True, 'replay': {'ok': True}}]}
        self.receipt = {'version': 1, 'source_sha256': hashes['source.py'],
                        'requirements_sha256': hashes['requirements.inv'],
                        'verifier_sha256': {name.removeprefix('verifier/'): value for name, value in hashes.items() if name.startswith('verifier/')},
                        'input_sha256': hashes,
                        'closure_sha256': sha(json.dumps(hashes, sort_keys=True, separators=(',', ':')).encode()),
                        'validators_sha256': sha(self.entries[self.validator]),
                        'required_properties': ['current'], 'required_witnesses': ['admitted'], 'required_mutations': ['stale']}
        self.write_report()
        self.manifest = {'version': 1, 'machines': {'fixture': {'path': '0', 'runtime_source': self.source,
                                                              'runtime_contracts': self.validator}}}
        (self.evidence / 'manifest.json').write_text(json.dumps(self.manifest))

    def write_report(self):
        data = json.dumps(self.report).encode()
        (self.proof / 'report.json').write_bytes(data)
        self.receipt['report_sha256'] = sha(data)
        (self.proof / 'receipt.json').write_text(json.dumps(self.receipt))

    def build(self):
        package(self.tree, self.output, inventory_path=self.inventory,
                proof_requirement=InvariantProofs(self.evidence))

    def rejected(self):
        self.output.parent.mkdir(exist_ok=True)
        stale = [self.output, self.output.parent / 'package-report.json', self.output.parent / '.product.zip.candidate']
        for path in stale: path.write_text('stale')
        with self.assertRaises((ValueError, OSError)):
            self.build()
        for path in stale: self.assertFalse(path.exists())

    def test_accepted_evidence_is_external_and_deterministic(self):
        self.build(); first = self.output.read_bytes()
        self.build(); self.assertEqual(first, self.output.read_bytes())
        report = json.loads((self.output.parent / 'package-report.json').read_text())
        self.assertEqual(set(report['machine_proofs']), {'fixture'})
        self.assertEqual(report['machine_proofs']['fixture']['closure_sha256'], self.receipt['closure_sha256'])

    def test_every_changed_input_rejects_and_removes_stale_artifacts(self):
        for path in self.inputs.rglob('*'):
            if not path.is_file(): continue
            before = path.read_bytes()
            with self.subTest(path=path.name):
                path.write_bytes(before + b'changed')
                self.rejected()
            path.write_bytes(before)

    def test_source_generated_contract_and_binder_are_bound(self):
        for name in self.entries:
            path = self.tree / name; before = path.read_bytes()
            with self.subTest(path=name):
                path.write_bytes(before + b'CHANGED = True\n')
                self.rejected()
            path.write_bytes(before)
        (self.proof / 'validators.py').write_bytes(b'OTHER = True\n')
        self.rejected()

    def test_missing_or_uncovered_contract_rejects(self):
        path = self.tree / self.validator; path.unlink(); self.rejected()
        path.write_bytes(self.entries[self.validator])
        (path.parent / '_extra_contracts.py').write_text('VALUE = 1\n'); self.rejected()

    def test_one_checked_source_can_back_distinct_requirement_sets(self):
        second_validator = 'product/_policy_second_contracts.py'
        self.entries[second_validator] = self.entries[self.validator] + b'# second specification\n'
        second_path = self.tree / second_validator
        second_path.parent.mkdir(parents=True, exist_ok=True)
        second_path.write_bytes(self.entries[second_validator])

        second_prefix = self.evidence / '1'
        second_prefix.mkdir()
        shutil.copytree(self.evidence / '0/inputs', second_prefix / 'inputs')
        shutil.copytree(self.evidence / '0/proof', second_prefix / 'proof')
        second_requirements = {
            'properties': [{'name': 'another_current'}],
            'witnesses': [{'name': 'another_admitted'}],
            'mutations': [{'name': 'another_stale'}],
        }
        second_inventory = {'version': 1, 'properties': ['another_current'],
                            'witnesses': ['another_admitted'],
                            'mutations': ['another_stale']}
        (second_prefix / 'inputs/requirements.inv').write_text(json.dumps(second_requirements))
        (second_prefix / 'inputs/inventory.json').write_text(json.dumps(second_inventory))
        (second_prefix / 'proof/validators.py').write_bytes(self.entries[second_validator])
        second_report = copy.deepcopy(self.report)
        for kind in ('properties', 'witnesses', 'mutations'):
            second_report['required_' + kind] = second_inventory[kind]
        second_report['obligations'][0]['name'] = 'property.another_current'
        second_report['obligations'][1]['name'] = 'witness.another_admitted'
        second_report['mutations'][0]['name'] = 'another_stale'
        second_report_bytes = json.dumps(second_report).encode()
        (second_prefix / 'proof/report.json').write_bytes(second_report_bytes)
        second_receipt = copy.deepcopy(self.receipt)
        hashes = {path.relative_to(second_prefix / 'inputs').as_posix(): sha(path.read_bytes())
                  for path in (second_prefix / 'inputs').rglob('*') if path.is_file()}
        second_receipt.update(
            requirements_sha256=hashes['requirements.inv'],
            input_sha256=hashes,
            closure_sha256=sha(json.dumps(hashes, sort_keys=True, separators=(',', ':')).encode()),
            validators_sha256=sha(self.entries[second_validator]),
            report_sha256=sha(second_report_bytes),
        )
        for kind in ('properties', 'witnesses', 'mutations'):
            second_receipt['required_' + kind] = second_inventory[kind]
        (second_prefix / 'proof/receipt.json').write_text(json.dumps(second_receipt))
        self.manifest['machines']['fixture_second'] = {
            'path': '1', 'runtime_source': self.source,
            'runtime_contracts': second_validator,
        }
        (self.evidence / 'manifest.json').write_text(json.dumps(self.manifest))

        accepted = validate_bundle(self.evidence, self.entries)
        self.assertEqual(set(accepted), {'fixture', 'fixture_second'})
        self.build()

        descriptor = self.manifest['machines']['fixture_second']
        for field, duplicate in [('runtime_contracts', self.validator), ('path', '0')]:
            previous = descriptor[field]
            descriptor[field] = duplicate
            (self.evidence / 'manifest.json').write_text(json.dumps(self.manifest))
            with self.subTest(field=field), self.assertRaisesRegex(
                    ValueError, 'Duplicate proof machine evidence prefix or validator'):
                validate_bundle(self.evidence, self.entries)
            descriptor[field] = previous
        (self.evidence / 'manifest.json').write_text(json.dumps(self.manifest))
        second_receipt['source_sha256'] = 'unproved second source'
        (second_prefix / 'proof/receipt.json').write_text(json.dumps(second_receipt))
        with self.assertRaisesRegex(ValueError, 'Shipped policy differs from proved source'):
            validate_bundle(self.evidence, self.entries)

    def test_legacy_manifest_paths_do_not_alias_flat_sources(self):
        descriptor = self.manifest['machines']['fixture']
        manifest_path = self.evidence / 'manifest.json'
        for field in ('runtime_source', 'runtime_contracts'):
            before = descriptor[field]
            with self.subTest(field=field):
                descriptor[field] = '_vendor/' + before
                manifest_path.write_text(json.dumps(self.manifest))
                self.rejected()
            descriptor[field] = before
        manifest_path.write_text(json.dumps(self.manifest))
        self.build()

    def test_runtime_binder_requires_its_exact_flat_path(self):
        binder = 'invariant/verification/runtime_contracts.py'
        for replacement in ('_vendor/' + binder, 'other/' + binder,
                            'invariant/verification/alias.py'):
            relocated = {name: data for name, data in self.entries.items() if name != binder}
            relocated[replacement] = self.entries[binder]
            with self.subTest(path=replacement), self.assertRaisesRegex(
                    ValueError, 'Shipped runtime contract evaluator'):
                validate_bundle(self.evidence, relocated)

    def test_failed_missing_unknown_and_unreplayed_evidence_reject(self):
        baseline = copy.deepcopy(self.report)
        updates = [lambda r: r.update(ok=False), lambda r: r['obligations'].pop(),
                   lambda r: r['obligations'][0].update(actual='unknown'),
                   lambda r: r['mutations'][0].pop('replay'),
                   lambda r: r.update(required_properties=[]),
                   lambda r: r['mutations'].append(copy.deepcopy(r['mutations'][0]))]
        for update in updates:
            self.report = copy.deepcopy(baseline); update(self.report); self.write_report(); self.rejected()
        self.report = baseline; self.write_report()

    def test_extra_input_duplicate_key_and_symlink_reject(self):
        extra = self.inputs / 'untracked.py'; extra.write_text('pass\n'); self.rejected(); extra.unlink()
        receipt_path = self.proof / 'receipt.json'; before = receipt_path.read_bytes()
        receipt_path.write_bytes(before[:-1] + b', "version": 1}'); self.rejected(); receipt_path.write_bytes(before)
        source = self.inputs / 'source.py'; before = source.read_bytes(); source.unlink()
        source.symlink_to(self.tree / self.source); self.rejected(); source.unlink(); source.write_bytes(before)
        generated = self.proof / 'validators.py'; before = generated.read_bytes(); generated.unlink()
        generated.symlink_to(self.tree / self.validator); self.rejected(); generated.unlink(); generated.write_bytes(before)
        original = self.proof.with_name('original-proof'); self.proof.rename(original)
        self.proof.symlink_to(original, target_is_directory=True); self.rejected()
        self.proof.unlink(); original.rename(self.proof)

    def test_solver_and_checker_code_remain_forbidden(self):
        for name in ['invariant/verification/checker.py', 'invariant/verification/closure.py',
                     'invariant/lifecycle.inv', 'z3/__init__.py']:
            path = self.tree / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_text('pass\n')
            self.rejected(); path.unlink()
