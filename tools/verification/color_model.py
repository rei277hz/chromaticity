"""Compile project theorems and audit their transitive axioms with pinned Lean."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess

ALLOWED_AXIOMS = {'propext', 'Classical.choice', 'Quot.sound'}


def check(lean, dependencies, sources, output):
    lean, dependencies, sources, output = map(lambda p: Path(p).resolve(), (lean, dependencies, sources, output))
    output.mkdir(parents=True, exist_ok=True)
    search = [output, dependencies / '.lake/build/lib/lean']
    search += sorted(dependencies.glob('packages/*/.lake/build/lib/lean'))
    env = dict(os.environ, LEAN_PATH=os.pathsep.join(map(str, search)))
    def invoke(path, destination=None, root=sources):
        args = [str(lean / 'bin/lean'), '-DwarningAsError=true', '-DmaxHeartbeats=1000000', '--root='+str(root)]
        if destination is not None:
            destination.parent.mkdir(parents=True, exist_ok=True)
            args += ['-o', str(destination)]
        result = subprocess.run(args+[str(path)], env=env, text=True, capture_output=True)
        if result.returncode:
            raise RuntimeError(result.stdout+result.stderr)
        return result.stdout
    paths = sorted(sources.glob('PerceptualGrade/*.lean'))
    pending = {'.'.join(p.relative_to(sources).with_suffix('').parts): p for p in paths}
    completed, theorems = [], []
    while pending:
        ready = [name for name, path in pending.items() if not any(
            imp in pending for imp in re.findall(r'^import (PerceptualGrade\.\w+)', path.read_text(), re.M))]
        if not ready:
            raise ValueError('Cyclic project proof imports')
        failures = []
        for name in sorted(ready):
            path = pending.pop(name)
            text = path.read_text()
            if re.search(r'\b(sorry|admit|axiom|unsafe|native_decide)\b', re.sub(r'/\-.*?\-/|--[^\n]*', '', text, flags=re.S)):
                raise ValueError('Unfinished/unchecked project proof in '+name)
            try:
                invoke(path, output / path.relative_to(sources).with_suffix('.olean'))
            except RuntimeError as error:
                failures.append(str(error))
                continue
            theorems.extend('PerceptualGrade.'+t for t in re.findall(r'^(?:theorem|lemma) (\w+)', text, re.M))
            completed.append(name)
        if failures:
            raise RuntimeError('\n'.join(failures))
    if not theorems:
        raise ValueError('No project theorems found')
    audit = output / 'Audit.lean'
    audit.write_text('\n'.join('import '+name for name in completed)+'\n'+
                     '\n'.join('#print axioms '+name for name in theorems)+'\n')
    log = invoke(audit, root=output)
    if len(re.findall(r"(?:depends on axioms|does not depend on any axioms)", log)) != len(theorems):
        raise ValueError('Incomplete theorem axiom audit: '+log)
    axioms = set()
    for match in re.finditer(r'depends on axioms:\s*\[([^\]]*)\]', log):
        axioms.update(a.strip() for a in match[1].split(',') if a.strip())
    if not axioms <= ALLOWED_AXIOMS:
        raise ValueError('Unexpected theorem axioms: '+', '.join(sorted(axioms-ALLOWED_AXIOMS)))
    report = dict(toolchain='4.34.1', modules=completed, theorems=theorems, axioms=sorted(axioms))
    (output / 'checked.json').write_text(json.dumps(report, indent=2)+'\n')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--lean', type=Path, required=True)
    parser.add_argument('--dependencies', type=Path, required=True)
    parser.add_argument('--sources', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    report = check(args.lean, args.dependencies, args.sources, args.output_dir)
    print(f"Checked {len(report['theorems'])} theorems; axioms: {', '.join(report['axioms'])}")


if __name__ == '__main__':
    main()
