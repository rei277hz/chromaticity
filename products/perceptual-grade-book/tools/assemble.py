"""Verify the frozen import before assembling its original book and supplements."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil


def _inventory(root):
    if not root.is_dir():
        raise ValueError(f'Missing input directory: {root}')
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob('*')) if path.is_file()
    }


def verify_inputs(docs, snapshot, manifest):
    """Check every source byte and reject supplements that replace original paths."""
    docs, snapshot, manifest = Path(docs), Path(snapshot), Path(manifest)
    specification = json.loads(manifest.read_text(encoding='utf-8'))
    if specification.get('schema') != 1 or specification.get('version') != '1.23.2':
        raise ValueError('Expected the schema 1 Perceptual Grade 1.23.2 import manifest')
    for name, root in (('docs', docs), ('snapshot', snapshot)):
        expected = specification[name]
        for filename in expected:
            relative = PurePosixPath(filename)
            if relative.is_absolute() or '..' in relative.parts or str(relative) != filename:
                raise ValueError(f'Invalid {name} manifest path: {filename}')
        actual = _inventory(root)
        missing = sorted(expected.keys() - actual.keys())
        extra = sorted(actual.keys() - expected.keys())
        changed = sorted(path for path in expected.keys() & actual.keys() if expected[path] != actual[path])
        if missing or extra or changed:
            raise ValueError(f'{name} inventory mismatch: missing={missing}, extra={extra}, changed={changed}')
    book = docs / 'book'
    if not (book / 'book.toml').is_file():
        raise ValueError('The original docs/book/book.toml is required')
    for filename in specification['snapshot']:
        destination = book / filename
        if destination.exists() or any(parent.is_file() for parent in destination.parents if parent != book):
            raise ValueError(f'Snapshot conflicts with original docs/book: {filename}')
    return specification


def assemble(docs, snapshot, manifest, output):
    """Copy the verified original book plus missing supplemental files to output."""
    docs, snapshot, output = Path(docs), Path(snapshot), Path(output)
    specification = verify_inputs(docs, snapshot, manifest)
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise ValueError(f'Assembly output must be absent or empty: {output}')
    shutil.copytree(docs / 'book', output, dirs_exist_ok=True, copy_function=shutil.copyfile)
    # The private assembly tree must remain writable even when CAS input
    # directories carried read-only permissions.
    for directory in [output, *(path for path in output.rglob('*') if path.is_dir())]:
        directory.chmod(directory.stat().st_mode | 0o700)
    for filename in sorted(specification['snapshot']):
        destination = output / filename
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(snapshot / filename, destination)
    return output


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('docs', 'snapshot', 'manifest', 'output-dir'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args(argv)
    assemble(args.docs, args.snapshot, args.manifest, args.output_dir)


if __name__ == '__main__':
    main()
