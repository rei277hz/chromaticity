"""Package the declared static site with deterministic ZIP metadata."""
import argparse
import json
from pathlib import Path
from pg_book_build.zip_utils import digest, files, write_zip


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--site', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    entries = files(args.site)
    required = {
        'index.html', '.nojekyll', 'site-manifest.json',
        'manual/index.html', 'manual/en/index.html', 'manual/zh-Hans/index.html',
        'technical/en/index.html',
        'downloads/perceptual_grade-v1.23.2-20261101.zip',
    }
    if required - entries.keys():
        raise ValueError(f'Missing deploy resources: {sorted(required - entries.keys())}')
    expected=json.loads(entries['site-manifest.json'].read_text())['site_files']
    if set(entries)-{'site-manifest.json'}!=set(expected):
        raise ValueError('Deployment file inventory differs from the built site manifest.')
    for name,value in expected.items():
        if digest(entries[name])!=value:
            raise ValueError(f'Deployment input differs from the built site manifest: {name}')
    archive = args.output_dir / 'perceptual-grade-site.zip'
    write_zip(archive, entries)
    (args.output_dir / 'SHA256.json').write_text(json.dumps({archive.name: {
        'sha256': digest(archive), 'bytes': archive.stat().st_size
    }}, indent=2, sort_keys=True) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
