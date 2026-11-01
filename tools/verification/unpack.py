"""Unpack a pinned source/tool archive, removing its single enclosing directory."""
import argparse
from pathlib import Path
import shutil
import tarfile
import zstandard


def unpack(path, destination):
    destination.mkdir(parents=True, exist_ok=True)
    staging = destination / 'archive'
    staging.mkdir()
    with path.open('rb') as source:
        if path.name.endswith('.zst'):
            with zstandard.ZstdDecompressor().stream_reader(source) as stream:
                with tarfile.open(fileobj=stream, mode='r|') as archive:
                    archive.extractall(staging, filter='data')
        else:
            with tarfile.open(fileobj=source, mode='r:*') as archive:
                archive.extractall(staging, filter='data')
    roots = list(staging.iterdir())
    if len(roots) != 1 or not roots[0].is_dir():
        raise ValueError('Expected exactly one archive root')
    for item in roots[0].iterdir():
        shutil.move(item, destination / item.name)
    shutil.rmtree(staging)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    unpack(args.archive, args.output_dir)


if __name__ == '__main__':
    main()
