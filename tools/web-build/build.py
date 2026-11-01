"""Offline, declared-input builders for npm dependencies and static web products."""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import subprocess
import tarfile
import tempfile
import zipfile


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def safe_path(name):
    path = PurePosixPath(name)
    if (not name or path.is_absolute() or '..' in path.parts or '\\' in name
            or ':' in name or name != path.as_posix()):
        raise ValueError('Unsafe archive path: ' + name)
    return path


def inventory(tree):
    tree = Path(tree)
    if tree.is_symlink() or not tree.is_dir():
        raise ValueError('Site must be a regular directory')
    result = {}
    for path in sorted(tree.rglob('*')):
        if path.is_symlink():
            raise ValueError('Symlink in site: ' + str(path))
        if path.is_dir():
            continue
        if not path.is_file():
            raise ValueError('Special file in site: ' + str(path))
        name = path.relative_to(tree).as_posix()
        safe_path(name)
        if set(PurePosixPath(name).parts) & {'node_modules', 'target', 'src', 'tests', 'photoshop-uxp', 'substance-3d-painter'}:
            raise ValueError('Build source in site: ' + name)
        if path.suffix in {'.ccx', '.ts', '.rs', '.py'}:
            raise ValueError('Source/integration file in site: ' + name)
        result[name] = digest(path)
    if 'index.html' not in result:
        raise ValueError('Site requires index.html at archive root')
    return result


def package_site(tree, archive):
    tree, archive = Path(tree), Path(archive)
    entries = inventory(tree)
    archive.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as bundle:
        for name in entries:
            entry = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
            entry.create_system = 3
            entry.external_attr = (stat.S_IFREG | 0o644) << 16
            entry.compress_type = zipfile.ZIP_DEFLATED
            bundle.writestr(entry, (tree / name).read_bytes(), compresslevel=9)
    return verify_site_archive(archive, tree)


def verify_site_archive(archive, tree):
    entries = inventory(tree)
    seen = {}
    with zipfile.ZipFile(archive) as bundle:
        for entry in bundle.infolist():
            safe_path(entry.filename)
            if entry.filename in seen:
                raise ValueError('Duplicate archive member: ' + entry.filename)
            if entry.filename not in entries:
                raise ValueError('Unexpected archive member: ' + entry.filename)
            if not stat.S_ISREG(entry.external_attr >> 16):
                raise ValueError('Non-regular archive member: ' + entry.filename)
            seen[entry.filename] = hashlib.sha256(bundle.read(entry)).hexdigest()
    if seen != entries:
        raise ValueError('Archive differs from the declared site tree')
    return {'files': entries, 'sha256': digest(archive)}


def extract(archive, destination):
    destination.mkdir(parents=True, exist_ok=True)
    if zipfile.is_zipfile(archive):
        with zipfile.ZipFile(archive) as source:
            for entry in source.infolist():
                safe_path(entry.filename.rstrip('/'))
                if stat.S_ISLNK(entry.external_attr >> 16):
                    raise ValueError('Symlink in tool ZIP')
            source.extractall(destination)
            for entry in source.infolist():
                mode = entry.external_attr >> 16
                if mode & 0o111:
                    (destination / entry.filename).chmod(0o755)
    else:
        with tarfile.open(archive) as source:
            source.extractall(destination, filter='data')


def unpack_tools(args):
    output = args.output_dir
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='web-tools-') as tmp:
        for name, archive in args.archive:
            staging = Path(tmp) / name
            extract(Path(archive), staging)
            roots = list(staging.iterdir())
            root = roots[0] if len(roots) == 1 and roots[0].is_dir() else staging
            shutil.copytree(root, output, dirs_exist_ok=True, symlinks=True)


def unpack_dependencies(args):
    manifest = json.loads(args.manifest.read_text())
    archives = {name: Path(path) for name, path in args.archive}
    output = args.output_dir
    output.mkdir(parents=True, exist_ok=True)
    for spec in manifest['npm']:
        archive = archives[spec['target']]
        if digest(archive) != spec['sha256']:
            raise ValueError('Archive SHA256 mismatch: ' + spec['target'])
        algorithm, expected = spec['integrity'].split('-', 1)
        actual = base64.b64encode(hashlib.new(algorithm, archive.read_bytes()).digest()).decode()
        if actual != expected:
            raise ValueError('npm lock integrity mismatch: ' + spec['path'])
        destination = output / spec['path']
        with tempfile.TemporaryDirectory(prefix='web-dependency-') as tmp:
            staging = Path(tmp)
            extract(archive, staging)
            roots = list(staging.iterdir())
            if len(roots) != 1 or not roots[0].is_dir():
                raise ValueError('Dependency archive must have one root')
            shutil.copytree(roots[0], destination)


def stage_product(output, sources, npm, core, decomposition, references):
    shutil.copytree(sources, output, dirs_exist_ok=True)
    shutil.copytree(npm / 'node_modules', output / 'node_modules')
    shutil.copytree(core, output / 'src/wasm/pkg')
    shutil.copytree(decomposition, output / 'src/wasm/decomposition_pkg')
    shutil.copytree(references, output / 'references', dirs_exist_ok=True)


def build_site(args):
    manifest = json.loads(args.manifest.read_text())
    if digest(args.sources / 'package-lock.json') != manifest['lock_sha256']['npm']:
        raise ValueError('package-lock.json changed; refresh third_party/web declarations')
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='web-site-') as tmp:
        root = Path(tmp)
        stage_product(root, args.sources, args.npm, args.core, args.decomposition, args.references)
        node = str(args.node.resolve() / 'bin/node')
        env = dict(os.environ, ESBUILD_BINARY_PATH=str(root / 'node_modules/@esbuild/linux-x64/bin/esbuild'))
        subprocess.run([node, 'node_modules/typescript/bin/tsc', '--noEmit'], cwd=root, env=env, check=True)
        subprocess.run([node, 'node_modules/vite/bin/vite.js', 'build', '--outDir', str(output / 'site')], cwd=root, env=env, check=True)
        notices = []
        base = root / 'node_modules'
        for path in sorted(base.rglob('*')):
            if path.is_file() and path.name.lower().startswith(('license', 'copying', 'notice', 'copyright')):
                notices.append('\n===== npm: ' + path.relative_to(base).as_posix() + ' =====\n' + path.read_text(errors='replace'))
        notices.append(args.rust_notices.read_text())
        provenance = args.references / 'colorchecker/ColorChecker24_After_Nov2014.metadata.json'
        if provenance.exists():
            notices.append('\n===== ColorChecker provenance =====\n' + provenance.read_text())
        (output / 'site/THIRD_PARTY_NOTICES.txt').write_text(''.join(notices))
    manifest = package_site(output / 'site', output / 'hdr-color-picker-web.zip')
    (output / 'manifest.json').write_text(json.dumps(manifest, indent=2, sort_keys=True) + '\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=['tools', 'deps', 'site'])
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--manifest', type=Path)
    parser.add_argument('--archive', nargs=2, action='append', default=[])
    for name in ['core', 'decomposition', 'sources', 'npm', 'node', 'references', 'rust-notices']:
        parser.add_argument('--' + name, type=Path)
    args = parser.parse_args()
    {'tools': unpack_tools, 'deps': unpack_dependencies, 'site': build_site}[args.operation](args)


if __name__ == '__main__':
    main()
