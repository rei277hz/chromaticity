"""Shared publication data validation and provenance."""
import hashlib
import json
import os
from pathlib import Path


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + '\n', encoding='utf-8')


def manifest(output, inputs, kind, roots):
    """Record declared inputs under stable, caller-supplied logical roots."""
    named = {}
    for path in inputs:
        path = Path(path)
        for prefix, root in roots.items():
            try:
                relative = path.relative_to(root)
            except ValueError:
                continue
            name = prefix + '/' + relative.as_posix()
            value = digest(path)
            if name in named and named[name] != value:
                raise ValueError('Conflicting provenance input: ' + name)
            named[name] = value
            break
        else:
            raise ValueError('Input has no logical provenance root: ' + path.name)
    write_json(output / 'manifest.json', {
        'schema': 1, 'producer': kind,
        'invocation': 'buck2' if os.environ.get('PG_BUCK_ACTION') == '1' else 'authoring-preview',
        'inputs': named,
        'outputs': {p.relative_to(output).as_posix(): digest(p)
                    for p in sorted(output.rglob('*')) if p.is_file() and p.name != 'manifest.json'},
    })


