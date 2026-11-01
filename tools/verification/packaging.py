"""Deterministic ZIP assembly and validation of declared runtime source bytes."""
import ast
import hashlib
import json
from pathlib import Path, PurePosixPath
import stat
import zipfile

from .invariant_report import InvariantProofs, validate_bundle


_BUILD_MODULES = frozenset({
    'invariant_compiler', 'invariant_verification', 'compiler', 'verification',
    'z3', 'z3_solver', 'rocq', 'coq', 'lean', 'proofs', 'assurance', 'tools',
    '__pycache__', '_generated',
})
_PROOF_NAMES = frozenset({
    'SPEC_ID', 'PROPERTY_IDS', 'MACHINE_NAME', 'RUNTIME_ABI', 'COMPILER_SCHEMA',
    'GRAMMAR_VERSION', 'verify_evidence', 'load_machine', 'spec_id',
    'property_ids', 'required_property_ids', 'required_witnesses',
    'generated_sha256', 'compiler_sha256', 'checker_sha256',
    'runtime_abi_sha256', 'expected_source_sha256', 'required_negative_controls',
    'equivalence_sha256', 'manifest_sha256',
})
_BUILD_SUFFIXES = frozenset({
    '.whl', '.pyc', '.pyo', '.v', '.vo', '.vos', '.vok', '.glob', '.lean',
    '.olean', '.smt2', '.inv',
})
_RUNTIME_CONTRACT_FILES = frozenset({
    'invariant/verification/__init__.py',
    'invariant/verification/runtime_contracts.py',
})
_RUNTIME_CONTRACT_IMPORTS = frozenset({
    'verification.runtime_contracts', 'invariant.verification.runtime_contracts',
})


def _path(name):
    if type(name) is not str:
        raise ValueError('Runtime paths must be strings')
    path = PurePosixPath(name)
    if (not name or not path.parts or path.is_absolute() or '..' in path.parts
            or '\\' in name or ':' in name or name != path.as_posix()
            or any(ord(char) < 32 or ord(char) == 127 for char in name)):
        raise ValueError('Unsafe archive/source path: ' + name)
    return path


def _runtime_json(inventory):
    if (type(inventory) is not dict or inventory.get('schema') != 1
            or set(inventory) != {'schema', 'runtime_json'}):
        raise ValueError('Unsupported runtime inventory')
    names = inventory['runtime_json']
    if type(names) is not list or any(type(name) is not str for name in names):
        raise ValueError('Runtime JSON inventory must be an explicit list of paths')
    if len(set(names)) != len(names):
        raise ValueError('Duplicate runtime JSON inventory member')
    for name in names:
        if _path(name).suffix != '.json':
            raise ValueError('Runtime JSON inventory contains a non-JSON path: ' + name)
    return set(names)


def _runtime_file(name, data, allowed_json):
    path = _path(name)
    blocked_parts = set(path.parts) & _BUILD_MODULES
    if name in _RUNTIME_CONTRACT_FILES:
        blocked_parts.discard('verification')
    if (blocked_parts or path.stem in _BUILD_MODULES
            or path.suffix in _BUILD_SUFFIXES or path.name == 'INVARIANT'
            or path.name.endswith(('.manifest.json', '.receipt.json'))):
        raise ValueError('Build-only evidence or tooling in extension: ' + name)
    if path.suffix == '.json' and name not in allowed_json:
        raise ValueError('Undeclared runtime JSON or proof payload: ' + name)
    if type(data) is not bytes:
        raise ValueError('Runtime sources must be exact bytes: ' + name)
    if path.suffix != '.py':
        return
    for node in ast.walk(ast.parse(data, filename=name)):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            imports = ([node.module or '', *(alias.name for alias in node.names)]
                       if isinstance(node, ast.ImportFrom)
                       else [alias.name for alias in node.names])
            if any(set(module.split('.')) & _BUILD_MODULES
                   for module in imports if module not in _RUNTIME_CONTRACT_IMPORTS):
                raise ValueError('Build-only import in runtime: ' + name)
        identifier = (node.id if isinstance(node, ast.Name) else
                      node.arg if isinstance(node, ast.arg) else
                      node.name if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                                                    ast.ClassDef, ast.alias)) else
                      node.attr if isinstance(node, ast.Attribute) else '')
        if identifier in _PROOF_NAMES:
            raise ValueError('Proof API/identity in runtime: ' + name)
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if node.value in _PROOF_NAMES or node.value.startswith(('property:', 'spec:')):
                raise ValueError('Proof metadata in runtime: ' + name)


def sources(tree):
    """Read the exact Buck-declared source tree, rejecting links and special files."""
    tree = Path(tree)
    if not tree.is_dir() or tree.is_symlink():
        raise ValueError('Runtime source tree must be a directory')
    entries = {}
    for path in sorted(tree.rglob('*')):
        mode = path.lstat().st_mode
        if stat.S_ISDIR(mode):
            continue
        if not stat.S_ISREG(mode):
            raise ValueError('Runtime sources must be regular files: ' + str(path))
        name = path.relative_to(tree).as_posix()
        _path(name)
        entries[name] = path.read_bytes()
    if not entries:
        raise ValueError('Exact declared runtime source inventory is required')
    return entries


def verify_archive(archive, inventory, *, expected_sources):
    """Check final ZIP membership, safe payloads, and equality to source bytes."""
    allowed_json = _runtime_json(inventory)
    if type(expected_sources) is not dict or not expected_sources:
        raise ValueError('Exact declared runtime source inventory is required')
    for name, data in expected_sources.items():
        _runtime_file(name, data, allowed_json)
    contents = {}
    with zipfile.ZipFile(archive) as bundle:
        for entry in bundle.infolist():
            name = entry.filename
            _path(name)
            if name in contents:
                raise ValueError('Duplicate archive member: ' + name)
            if entry.is_dir() or stat.S_IFMT(entry.external_attr >> 16) not in (0, stat.S_IFREG):
                raise ValueError('Product members must be regular files')
            data = bundle.read(entry)
            _runtime_file(name, data, allowed_json)
            contents[name] = data
    if set(contents) != set(expected_sources):
        raise ValueError('Archive member inventory differs from declared runtime sources')
    if {name for name in contents if name.endswith('.json')} != allowed_json:
        raise ValueError('Runtime JSON inventory differs')
    if contents != expected_sources:
        raise ValueError('Archive bytes differ from declared runtime sources')
    return contents


def package(tree, output, *, inventory_path, proof_requirement=None):
    tree, output = Path(tree), Path(output)
    if output.resolve().is_relative_to(tree.resolve()):
        raise ValueError('Package output must be outside the runtime source tree')
    output.parent.mkdir(parents=True, exist_ok=True)
    candidate = output.with_name('.' + output.name + '.candidate')
    report_path = output.parent / 'package-report.json'
    output.unlink(missing_ok=True)
    report_path.unlink(missing_ok=True)
    try:
        inventory_bytes = Path(inventory_path).read_bytes()
        inventory = json.loads(inventory_bytes)
        entries = sources(tree)
        allowed_json = _runtime_json(inventory)
        for name, data in entries.items():
            _runtime_file(name, data, allowed_json)
        machine_proofs = {}
        if proof_requirement is not None:
            if type(proof_requirement) is InvariantProofs:
                machine_proofs = validate_bundle(proof_requirement.root, entries)
            else:
                raise ValueError('Unsupported package proof requirement')
        with zipfile.ZipFile(candidate, 'w', zipfile.ZIP_DEFLATED) as archive:
            for name, data in sorted(entries.items()):
                info = zipfile.ZipInfo(name, (2026, 1, 1, 0, 0, 0))
                info.create_system = 3
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o100644 << 16
                archive.writestr(info, data)
        verify_archive(candidate, inventory, expected_sources=entries)
        report = {
            'schema': 1, 'status': 'accepted', 'passed': True,
            'archive_sha256': hashlib.sha256(candidate.read_bytes()).hexdigest(),
            'inventory_sha256': hashlib.sha256(inventory_bytes).hexdigest(),
            'source_sha256': {name: hashlib.sha256(data).hexdigest()
                              for name, data in sorted(entries.items())},
        }
        if machine_proofs:
            report['machine_proofs'] = machine_proofs
        report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + '\n',
                               encoding='utf-8', newline='\n')
        candidate.replace(output)
    except Exception:
        output.unlink(missing_ok=True)
        report_path.unlink(missing_ok=True)
        raise
    finally:
        candidate.unlink(missing_ok=True)
