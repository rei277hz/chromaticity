"""Compare Image lifetime across native undo in disposable Blender processes.

This diagnostic intentionally exercises invalid native links in fresh factory
scenes. Child crashes are observations, not successful memory-safety tests.
Never load a user project here.
"""
import argparse
from importlib.resources import files
import json
import os
from pathlib import Path
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--repeats', type=int, default=5)
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error('--repeats must be positive')
    root = args.output_dir.resolve()
    root.mkdir(parents=True, exist_ok=True)
    resources = files('tools.diagnostics')
    native = Path(str(resources / 'blender')).resolve()
    binary = next(path for path in (native / 'blender', native / 'Blender.app/Contents/MacOS/Blender')
                  if path.is_file())
    runner = Path(str(resources / 'undo_publication_runner.py')).resolve()
    (root / 'runner.py').write_bytes(runner.read_bytes())
    rows = []
    for mode in ('replace', 'pixels', 'snapshot', 'existing', 'fake_user'):
        for index in range(args.repeats):
            trial = root / f'{mode}-{index:02d}'
            trial.mkdir(exist_ok=False)
            env = {key: value for key, value in os.environ.items()
                   if key not in {'PYTHONPATH', 'PYTHONHOME', 'BLENDER_SYSTEM_SCRIPTS',
                                  'BLENDER_SYSTEM_PYTHON'}}
            env.update(BLENDER_USER_CONFIG=str(trial / 'config'),
                       BLENDER_USER_SCRIPTS=str(trial / 'scripts'),
                       BLENDER_USER_EXTENSIONS=str(trial / 'extensions'),
                       TMPDIR=str(trial), OPENBLAS_NUM_THREADS='1', OMP_NUM_THREADS='1')
            command = [str(binary), '--background', '--factory-startup', '--disable-autoexec',
                       '--threads', '1', '--python-exit-code', '1', '--python', str(runner), '--', mode]
            with (trial / 'console.log').open('w') as log:
                process = subprocess.Popen(command, cwd=trial, env=env,
                                           stdout=log, stderr=subprocess.STDOUT)
                timed_out = False
                try:
                    code = process.wait(timeout=45)
                except subprocess.TimeoutExpired:
                    timed_out = True
                    process.kill()
                    code = process.wait(timeout=10)
            events = [json.loads(line.removeprefix('PG_PUBLICATION_PROBE '))
                      for line in (trial / 'console.log').read_text(errors='replace').splitlines()
                      if line.startswith('PG_PUBLICATION_PROBE ')]
            links = [event for event in events if event['event'] == 'links']
            complete = bool(events and events[-1]['event'] == 'complete')
            row = dict(mode=mode, trial=index, exit_code=code, timed_out=timed_out,
                       complete=complete, observations=len(links),
                       invalid_observations=sum(not event['valid'] for event in links),
                       valid_complete=(code == 0 and complete and len(links) == 7
                                       and all(event['valid'] for event in links)),
                       last_event=events[-1] if events else None,
                       build=next((event for event in events if event['event'] == 'build'), None))
            rows.append(row)
            (root / 'report.json').write_text(json.dumps(rows, indent=2) + '\n')
            print(json.dumps(row), flush=True)


if __name__ == '__main__':
    main()
