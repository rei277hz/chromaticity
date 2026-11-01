#!/usr/bin/env python3
"""Refresh pinned web downloads from application lockfiles and official releases.

This maintenance command uses the network. Buck actions consume the resulting
manifest and never invoke this script. npm tarballs are verified against the
lockfile's SRI value before a SHA256 suitable for Buck is recorded.
"""
import argparse
import ast
import base64
import concurrent.futures
import hashlib
import json
from pathlib import Path
import re
import urllib.request

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
CACHE = Path('/tmp/modcam16-web-downloads')


def fetch(url):
    CACHE.mkdir(exist_ok=True)
    path = CACHE / hashlib.sha256(url.encode()).hexdigest()
    if not path.exists():
        with urllib.request.urlopen(url, timeout=180) as response:
            data = response.read()
        path.write_bytes(data)
    return path.read_bytes()


def target(prefix, value):
    return prefix + '_' + re.sub('[^a-zA-Z0-9_]', '_', value)


def compatible(spec):
    return all(key not in spec or wanted in spec[key]
               for key, wanted in [('os', 'linux'), ('cpu', 'x64'), ('libc', 'glibc')])


def npm_entry(item):
    path, spec = item
    data = fetch(spec['resolved'])
    integrity = spec['integrity']
    valid = False
    for token in integrity.split():
        algorithm, encoded = token.split('-', 1)
        if algorithm in hashlib.algorithms_available:
            valid |= hashlib.new(algorithm, data).digest() == base64.b64decode(encoded)
    if not valid:
        raise ValueError('npm integrity mismatch: ' + path)
    return dict(path=path, version=spec['version'], url=spec['resolved'],
                sha256=hashlib.sha256(data).hexdigest(), integrity=integrity,
                target=target('npm', path.removeprefix('node_modules/')))


def archive(key, url, checksum=None):
    return dict(url=url, sha256=checksum or hashlib.sha256(fetch(url)).hexdigest(),
                filename=url.rsplit('/', 1)[1], target=key + '_archive')


def check(product):
    """Check the checked-in declarations against the npm lockfile without network I/O."""
    manifest = json.loads((HERE / 'dependencies.json').read_text())
    if manifest.get('schema') != 1:
        raise ValueError('Unsupported dependency manifest schema')
    npm_lock = product / 'package-lock.json'
    expected_hashes = {'npm': hashlib.sha256(npm_lock.read_bytes()).hexdigest()}
    if manifest['lock_sha256'] != expected_hashes:
        raise ValueError('npm lockfile changed; refresh the web dependency manifests')
    packages = json.loads(npm_lock.read_text())['packages']
    expected_npm = {path: spec for path, spec in packages.items() if path and compatible(spec)}
    if set(expected_npm) != {spec['path'] for spec in manifest['npm']}:
        raise ValueError('npm dependency closure differs from package-lock.json')
    for spec in manifest['npm']:
        locked = expected_npm[spec['path']]
        if (spec['version'], spec['url'], spec['integrity']) != (
                locked['version'], locked['resolved'], locked['integrity']):
            raise ValueError('npm record differs from lockfile: ' + spec['path'])
        expected_target = target('npm', spec['path'].removeprefix('node_modules/'))
        if spec['target'] != expected_target:
            raise ValueError('Unexpected npm target: ' + spec['target'])
    declarations = ast.parse((HERE / 'dependencies.bzl').read_text())
    values = {node.targets[0].id: ast.literal_eval(node.value)
              for node in declarations.body if isinstance(node, ast.Assign)}
    if values != {'NPM': manifest['npm'], 'TOOLS': manifest['tools']}:
        raise ValueError('Starlark declarations differ from dependencies.json')
    rows = manifest['npm'] + list(manifest['tools'].values())
    if len({spec['target'] for spec in rows}) != len(rows):
        raise ValueError('Duplicate archive target name')
    if any(re.fullmatch('[0-9a-f]{64}', spec['sha256']) is None for spec in rows):
        raise ValueError('Malformed archive SHA256')
    print(f'Web manifests match the npm lockfile ({len(rows)} archives); no network used.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, help='Original application checkout during initial import')
    parser.add_argument('--check', action='store_true', help='Validate existing manifests offline without changing files')
    args = parser.parse_args()
    product = args.source or ROOT / 'products/hdr-color-picker-web'
    if args.check:
        check(product)
        return
    npm_lock = product / 'package-lock.json'
    packages = json.loads(npm_lock.read_text())['packages']
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        npm = list(pool.map(npm_entry, [(p, s) for p, s in packages.items() if p and compatible(s)]))
    version = '26.13.0'
    node_filename = f'node-v{version}-linux-x64.tar.xz'
    node_sums = dict(line.split()[::-1] for line in fetch(f'https://nodejs.org/dist/v{version}/SHASUMS256.txt').decode().splitlines())
    tools = {'node': archive('node', f'https://nodejs.org/dist/v{version}/{node_filename}', node_sums[node_filename])}
    tools['chromium'] = archive('chromium', 'https://cdn.playwright.dev/builds/cft/153.0.8010.12/linux64/chrome-linux64.zip')
    wheel_metadata = json.loads(fetch('https://pypi.org/pypi/opencolorio/2.5.0/json'))
    wheel_name = 'opencolorio-2.5.0-cp313-cp313-manylinux_2_27_x86_64.manylinux_2_28_x86_64.whl'
    wheel = next(row for row in wheel_metadata['urls'] if row['filename'] == wheel_name)
    tools['opencolorio'] = archive('opencolorio', wheel['url'], wheel['digests']['sha256'])
    manifest = dict(schema=1, npm=sorted(npm, key=lambda row: row['path']), tools=tools,
                    lock_sha256={'npm': hashlib.sha256(npm_lock.read_bytes()).hexdigest()})
    (HERE / 'dependencies.json').write_text(json.dumps(manifest, indent=2) + '\n')
    (HERE / 'dependencies.bzl').write_text('"""Generated by update.py; checksums originate in lockfiles and official releases."""\n\n' +
        'NPM = ' + json.dumps(manifest['npm'], indent=4) +
        '\n\nTOOLS = ' + json.dumps(manifest['tools'], indent=4) + '\n')
    print(f'Pinned {len(npm)} npm archives and {len(tools)} tool/wheel archives.')


if __name__ == '__main__':
    main()
