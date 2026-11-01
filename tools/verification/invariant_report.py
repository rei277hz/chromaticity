"""Build-only validation of shared Invariant evidence against shipped bytes."""
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path, PurePosixPath
import stat


@dataclass(frozen=True)
class InvariantProofs:
    root: Path


def _digest(value):
    return hashlib.sha256(value).hexdigest()


def _object(pairs):
    result = {}
    for name, value in pairs:
        if name in result:
            raise ValueError('Duplicate proof evidence key: ' + name)
        result[name] = value
    return result


def _read(path):
    if path.is_symlink() or not path.is_file():
        raise ValueError('Proof evidence must be a regular file: ' + str(path))
    data = path.read_bytes()
    return json.loads(data, object_pairs_hook=_object), data


def _path(name):
    if type(name) is not str or not name:
        raise ValueError('Invalid proof path')
    value = PurePosixPath(name)
    if value.is_absolute() or '..' in value.parts or '\\' in name or ':' in name or value.as_posix() != name:
        raise ValueError('Unsafe proof path: ' + name)
    return value


def _hashes(root):
    if root.is_symlink() or not root.is_dir():
        raise ValueError('Proof inputs must be a regular directory')
    result = {}
    for path in sorted(root.rglob('*')):
        mode = path.lstat().st_mode
        if stat.S_ISDIR(mode):
            continue
        if not stat.S_ISREG(mode):
            raise ValueError('Non-regular proof input')
        result[path.relative_to(root).as_posix()] = _digest(path.read_bytes())
    return result


def _names(values, label):
    if type(values) is not list or any(type(name) is not str or not name for name in values):
        raise ValueError('Invalid ' + label + ' inventory')
    if values != sorted(set(values)):
        raise ValueError('Unsorted or duplicate ' + label + ' inventory')
    return values


def validate_bundle(root, entries):
    root = Path(root)
    if root.is_symlink() or not root.is_dir():
        raise ValueError('Proof evidence bundle must be a regular directory')
    manifest, _ = _read(root / 'manifest.json')
    if set(manifest) != {'version', 'machines'} or manifest['version'] != 1:
        raise ValueError('Unsupported shared proof manifest')
    machines = manifest['machines']
    if type(machines) is not dict or not machines:
        raise ValueError('Required shared machine evidence is absent')
    accepted, validators, prefixes = {}, set(), set()
    for name, spec in sorted(machines.items()):
        if type(spec) is not dict or set(spec) != {'path', 'runtime_source', 'runtime_contracts'}:
            raise ValueError('Invalid proof machine descriptor')
        prefix, source, contracts = (str(_path(spec[key])) for key in ('path', 'runtime_source', 'runtime_contracts'))
        if prefix in prefixes or contracts in validators:
            raise ValueError('Duplicate proof machine evidence prefix or validator')
        # A shared implementation may have several independent specifications;
        # each receipt below must bind the same shipped source bytes itself.
        prefixes.add(prefix); validators.add(contracts)
        if source not in entries or contracts not in entries:
            raise ValueError('Checked runtime source or validator is absent: ' + name)
        directory = root / prefix
        for parent in (directory, directory / 'proof'):
            if parent.is_symlink() or not parent.is_dir():
                raise ValueError('Proof evidence must use regular directories')
        hashes = _hashes(directory / 'inputs')
        receipt, receipt_bytes = _read(directory / 'proof/receipt.json')
        report, report_bytes = _read(directory / 'proof/report.json')
        inventory, _ = _read(directory / 'inputs/inventory.json')
        requirements, _ = _read(directory / 'inputs/requirements.inv')
        if set(inventory) != {'version', 'properties', 'witnesses', 'mutations'} or inventory['version'] != 1:
            raise ValueError('Invalid proof requirement inventory')
        for kind in ('properties', 'witnesses', 'mutations'):
            required = _names(inventory[kind], kind)
            declared = [item['name'] for item in requirements.get(kind, [])]
            if not set(required).issubset(declared):
                raise ValueError('Required ' + kind + ' missing from specification')
            # All delivered named requirements are mandatory. Removing one from
            # the .inv file must not silently reduce the packaging requirement.
            if set(required) != set(declared) or len(declared) != len(set(declared)):
                raise ValueError('Specification and required ' + kind + ' inventories differ')
            key = 'required_' + kind
            if receipt.get(key) != required or report.get(key) != required:
                raise ValueError('Proof requirement binding differs: ' + kind)
        verifier = receipt.get('verifier_sha256')
        if type(verifier) is not dict or not verifier:
            raise ValueError('Missing verifier input identities')
        expected = {'source.py', 'requirements.inv', 'inventory.json', 'solver/z3.whl'}
        expected.update('verifier/' + str(_path(key)) for key in verifier)
        if set(hashes) != expected or any(hashes['verifier/' + key] != value for key, value in verifier.items()):
            raise ValueError('Verifier closure inventory or bytes differ')
        runtime_binder = 'invariant/verification/runtime_contracts.py'
        if (runtime_binder not in entries or
                _digest(entries[runtime_binder]) != hashes.get('verifier/runtime_contracts.py')):
            raise ValueError('Shipped runtime contract evaluator differs from proved verifier')
        closure = _digest(json.dumps(hashes, sort_keys=True, separators=(',', ':')).encode())
        if receipt.get('input_sha256') != hashes or receipt.get('closure_sha256') != closure:
            raise ValueError('Proof input closure differs')
        if receipt.get('version') != 1 or report.get('version') != 1 or report.get('ok') is not True:
            raise ValueError('Unsuccessful or unsupported shared proof')
        if receipt.get('report_sha256') != _digest(report_bytes):
            raise ValueError('Proof report bytes differ')
        if receipt.get('source_sha256') != hashes['source.py'] or _digest(entries[source]) != hashes['source.py']:
            raise ValueError('Shipped policy differs from proved source')
        if receipt.get('requirements_sha256') != hashes['requirements.inv']:
            raise ValueError('Proof specification bytes differ')
        generated_path = directory / 'proof/validators.py'
        if generated_path.is_symlink() or not generated_path.is_file():
            raise ValueError('Generated contracts must be a regular file')
        generated = generated_path.read_bytes()
        if receipt.get('validators_sha256') != _digest(generated) or entries[contracts] != generated:
            raise ValueError('Shipped contracts differ from generated validator')
        obligations = report.get('obligations')
        if type(obligations) is not list or not obligations:
            raise ValueError('Missing proof obligations')
        checks = {}
        for check in obligations:
            if check.get('name') in checks or check.get('ok') is not True:
                raise ValueError('Duplicate or failed proof obligation')
            if check.get('expected') not in ('sat', 'unsat') or check.get('actual') != check['expected']:
                raise ValueError('Unproved obligation')
            checks[check['name']] = check
        for kind, label, expected in [('properties', 'property.', 'unsat'), ('witnesses', 'witness.', 'sat')]:
            for required in inventory[kind]:
                if checks.get(label + required, {}).get('actual') != expected:
                    raise ValueError('Required claim was not checked: ' + required)
        mutations = report.get('mutations')
        if type(mutations) is not list or {item.get('name') for item in mutations} != set(inventory['mutations']):
            raise ValueError('Mutation evidence inventory differs')
        if len(mutations) != len(inventory['mutations']):
            raise ValueError('Duplicate mutation evidence')
        for item in mutations:
            if item.get('ok') is not True or item.get('replay', {}).get('ok') is not True:
                raise ValueError('Mutation lacks a replayed counterexample')
        accepted[name] = {'receipt_sha256': _digest(receipt_bytes), 'report_sha256': _digest(report_bytes),
                          'closure_sha256': closure, 'source_sha256': hashes['source.py'],
                          'validators_sha256': receipt['validators_sha256'],
                          'runtime_source': source, 'runtime_contracts': contracts}
    shipped = {name for name in entries if PurePosixPath(name).name.endswith('_contracts.py')
               and PurePosixPath(name).name != 'runtime_contracts.py'}
    if shipped != validators:
        raise ValueError('Shipped generated contracts lack exact proof coverage')
    return accepted
