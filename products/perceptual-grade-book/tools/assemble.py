"""Assemble authored chapters, declared generated assets, and historical downloads."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil


def _files(root):
    root = Path(root)
    if not root.is_dir():
        raise ValueError(f'Missing input directory: {root}')
    return {path.relative_to(root).as_posix(): path
            for path in sorted(root.rglob('*')) if path.is_file()}


def _inventory(root):
    return {name: hashlib.sha256(path.read_bytes()).hexdigest()
            for name, path in _files(root).items()}


def verify_historical(historical, manifest):
    """Only published attachments are frozen; chapters are normal editable inputs."""
    specification = json.loads(Path(manifest).read_text(encoding='utf-8'))
    if specification.get('schema') != 1:
        raise ValueError('Expected schema 1 historical attachment manifest')
    expected = specification['files']
    for filename in expected:
        relative = PurePosixPath(filename)
        if (relative.is_absolute() or '..' in relative.parts
                or str(relative) != filename or filename in ('', '.')):
            raise ValueError(f'Invalid historical manifest path: {filename}')
    actual = _inventory(historical)
    missing = sorted(expected.keys() - actual.keys())
    extra = sorted(actual.keys() - expected.keys())
    changed = sorted(name for name in expected.keys() & actual.keys()
                     if expected[name] != actual[name])
    if missing or extra or changed:
        raise ValueError(f'Historical inventory mismatch: missing={missing}, extra={extra}, changed={changed}')
    return specification


def assemble(docs, assets, historical, manifest, output):
    """Validate the complete destination map before copying into a private tree."""
    docs, output = Path(docs), Path(output)
    verify_historical(historical, manifest)
    book = docs / 'book'
    if not (book / 'book.toml').is_file():
        raise ValueError('Missing required docs/book/book.toml')
    sources = {}
    for root in [book, *map(Path, assets), Path(historical)]:
        incoming = _files(root)
        if not incoming:
            raise ValueError(f'Empty book input tree: {root}')
        for name, path in incoming.items():
            if name in sources:
                raise ValueError(f'Conflicting book input destination: {name}')
            sources[name] = path
    for name in sources:
        for parent in PurePosixPath(name).parents:
            if parent.as_posix() in sources:
                raise ValueError(f'File/directory conflict in book inputs: {parent}')
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise ValueError(f'Assembly output must be absent or empty: {output}')
    # Copy bytes without CAS permissions; mdBook edits a private copy later.
    for name, source in sorted(sources.items()):
        destination = output / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
    return output


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('docs', 'historical', 'manifest', 'output-dir'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--assets', type=Path, action='append', required=True)
    args = parser.parse_args(argv)
    assemble(args.docs, args.assets, args.historical, args.manifest, args.output_dir)


if __name__ == '__main__':
    main()
