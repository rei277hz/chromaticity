"""Build the declared Lean/mathlib source closure offline in a Buck2 output tree."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
from verification.unpack import unpack


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--lean', type=Path, required=True)
    parser.add_argument('--package', nargs=2, action='append', required=True)
    parser.add_argument('--imports', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    names = [name for name, _ in args.package]
    for name, archive in args.package:
        unpack(Path(archive), output / 'packages' / name)
    requirements = ''.join(f'\n[[require]]\nname = "{name}"\npath = "packages/{name}"\n' for name in names)
    (output / 'lakefile.toml').write_text('name = "pg_dependencies"\n\n[[lean_lib]]\nname = "PGDependencies"\n'+requirements)
    (output / 'lean-toolchain').write_text('leanprover/lean4:v4.34.1\n')
    manifest = dict(version='1.1.0', packagesDir='.lake/packages', name='pg_dependencies', lakeDir='.lake',
                    packages=[dict(type='path', name=name, dir='packages/'+name, configFile='lakefile.lean' if
                                   (output / 'packages' / name / 'lakefile.lean').exists() else 'lakefile.toml',
                                   manifestFile='lake-manifest.json', inherited=False) for name in names])
    (output / 'lake-manifest.json').write_text(json.dumps(manifest))
    shutil.copyfile(args.imports, output / 'PGDependencies.lean')
    # The root manifest declares local paths for the entire closure; no git,
    # elan, npm, cache download or dependency update is part of this action.
    subprocess.run([str(args.lean.resolve() / 'bin' / 'lake'), 'build', 'PGDependencies'], cwd=output, check=True)


if __name__ == '__main__':
    main()
