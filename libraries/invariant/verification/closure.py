"""Bind a proof to the exact declared source, checker and solver distribution."""
import hashlib
import json
from pathlib import Path
import stat
import zipfile


def digest(data):
    return hashlib.sha256(data).hexdigest()


def closure_digest(hashes):
    return digest(json.dumps(hashes, sort_keys=True, separators=(',', ':')).encode())


def file_hashes(root):
    root = Path(root)
    if root.is_symlink() or not root.is_dir():
        raise ValueError('Proof closure must be a regular directory')
    result = {}
    for path in sorted(root.rglob('*')):
        mode = path.lstat().st_mode
        if stat.S_ISDIR(mode):
            continue
        if not stat.S_ISREG(mode):
            raise ValueError('Non-regular proof input: ' + str(path))
        result[path.relative_to(root).as_posix()] = digest(path.read_bytes())
    return result


def validate(root, source, requirements, *, properties, witnesses, mutations,
             verifier_dir, solver_hashes):
    """Check the declared closure against the code actually executing this proof."""
    root, verifier_dir = Path(root), Path(verifier_dir)
    hashes = file_hashes(root)
    verifier = {p.name: digest(p.read_bytes()) for p in verifier_dir.glob('*.py')
                if p.name != '__init__.py'}
    expected = {'source.py', 'requirements.inv', 'inventory.json', 'solver/z3.whl'}
    expected.update('verifier/' + name for name in verifier)
    if set(hashes) != expected:
        raise ValueError('Proof input closure inventory differs')
    if hashes['source.py'] != digest(Path(source).read_bytes()):
        raise ValueError('Proof source differs from declared closure')
    if hashes['requirements.inv'] != digest(Path(requirements).read_bytes()):
        raise ValueError('Proof requirements differ from declared closure')
    inventory = json.loads((root / 'inventory.json').read_text())
    required = {'version': 1, 'properties': sorted(set(properties)),
                'witnesses': sorted(set(witnesses)), 'mutations': sorted(set(mutations))}
    if inventory != required:
        raise ValueError('Proof requirement inventory differs')
    if any(hashes['verifier/' + name] != value for name, value in verifier.items()):
        raise ValueError('Running verifier differs from declared closure')
    with zipfile.ZipFile(root / 'solver/z3.whl') as wheel:
        names = wheel.namelist()
        if len(names) != len(set(names)):
            raise ValueError('Duplicate solver wheel member')
        for name, value in solver_hashes.items():
            if name == 'libz3':
                members = [p for p in names if p.startswith('z3/lib/libz3.')
                           and ('.so' in p or p.endswith('.dylib'))]
                if not members or value not in {digest(wheel.read(p)) for p in members}:
                    raise ValueError('Running native solver differs from declared wheel')
            elif digest(wheel.read('z3/' + name)) != value:
                raise ValueError('Running solver wrapper differs from declared wheel')
    return hashes


def bind_receipt(output, hashes):
    """Bind the successful proof receipt to its exact verifier input closure."""
    output = Path(output)
    receipt_path = output / 'receipt.json'
    receipt = json.loads(receipt_path.read_text())
    receipt.update(input_sha256=hashes, closure_sha256=closure_digest(hashes))
    receipt_path.write_text(json.dumps(receipt, sort_keys=True, indent=2) + '\n')
