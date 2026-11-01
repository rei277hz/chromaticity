"""Inspect a project or exercise native scopes/undo using pinned artifacts.

The supplied .blend is opened without saving. Blender receives an isolated
configuration and extension repository. Evidence survives timeout or a native
crash; helper configuration files and authentication tokens are never copied.
"""
import argparse
from contextlib import ExitStack, contextmanager
from datetime import datetime, timezone
import hashlib
from importlib.machinery import SourceFileLoader
import importlib.util
from importlib.resources import files
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import zipfile


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def write_json(path, value):
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n', encoding='utf8')
    temporary.replace(path)


def display_adapter(resources):
    path = Path(str(resources / 'gui_display.py')).resolve()
    loader = SourceFileLoader('pg_probe_display', str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.virtual_display


@contextmanager
def termination_as_interrupt():
    def interrupted(number, _frame):
        raise KeyboardInterrupt('Received signal ' + str(number))
    previous = {number: signal.getsignal(number) for number in (signal.SIGINT, signal.SIGTERM)}
    try:
        for number in previous:
            signal.signal(number, interrupted)
        yield
    finally:
        for number, handler in previous.items():
            signal.signal(number, handler)


def stop_group(process):
    # The native parent and all its helpers share this isolated process group.
    # Continue deliberately paused helpers before killing them on failure.
    for action in (signal.SIGCONT, signal.SIGKILL):
        try:
            os.killpg(process.pid, action)
        except ProcessLookupError:
            pass
    process.wait(timeout=15)


def preserve_logs(work, output):
    selected = set()
    for pattern in ('helper-*.log', 'gpu-diagnostic-*.json', '*.crash.txt', 'xvfb.log'):
        selected.update(work.rglob(pattern))
    for path in sorted(selected):
        target = output / 'artifacts' / path.relative_to(work)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)


def launch(args, resources, output):
    root_binary = Path(str(resources / 'blender')).resolve()
    candidates = (root_binary / 'Blender.app/Contents/MacOS/Blender', root_binary / 'blender')
    executable = next((path for path in candidates if path.is_file()), None)
    if executable is None:
        raise FileNotFoundError('Pinned native Blender artifact is missing')
    archive_path = Path(str(resources / 'extension.zip')).resolve()
    runner_name = {'inspect':'project_probe_runner.py', 'scopes':'scope_probe_runner.py',
                   'undo':'gui_undo_runner.py'}[args.mode]
    runner = Path(str(resources / runner_name)).resolve()
    report = output / 'report.json'
    scope_options = dict(owner=args.scope_owner, material=args.material, workspace=args.workspace,
                         gui=args.gui, diagnostics=args.scope_diagnostics,
                         page_order=args.scope_page_order,complex_native=args.complex_native)
    receipt = dict(schema=2, mode=args.mode, cycles=args.cycles, node=args.node,
                   scope_options=scope_options if args.mode == 'scopes' else None,
                   started_at=datetime.now(timezone.utc).isoformat(), platform=sys.platform,
                   blend=str(args.blend), blend_sha256=sha256(args.blend),
                   blend_bytes=args.blend.stat().st_size, extension_zip_sha256=sha256(archive_path),
                   blender_binary_sha256=sha256(executable), runner=runner_name,
                   runner_sha256=sha256(runner), launcher_sha256=sha256(__file__),
                   display_adapter_sha256=sha256(Path(str(resources / 'gui_display.py'))),
                   status='preparing', passed=False)
    with zipfile.ZipFile(archive_path) as archive:
        manifest = {item.filename: hashlib.sha256(archive.read(item)).hexdigest()
                    for item in archive.infolist() if not item.is_dir()}
    write_json(output / 'source_hashes.json', manifest)
    write_json(output / 'launch.json', receipt)
    began = time.monotonic()
    code = 1
    with tempfile.TemporaryDirectory(prefix='pg-project-probe-') as directory:
        work = Path(directory)
        package = work / 'repository/perceptual_grade'
        package.mkdir(parents=True)
        with zipfile.ZipFile(archive_path) as archive:
            archive.extractall(package)
        native_temp = work / 'native-temp'
        native_temp.mkdir()
        env = {key: value for key, value in os.environ.items()
               if key not in ('PYTHONPATH', 'PYTHONHOME') and not key.startswith('BLENDER_')}
        env.update(BLENDER_USER_CONFIG=str(work / 'config'),
                   BLENDER_USER_SCRIPTS=str(work / 'scripts'),
                   BLENDER_USER_EXTENSIONS=str(work / 'extensions'),
                   BLENDER_USER_DATAFILES=str(work / 'datafiles'),
                   TMPDIR=str(native_temp), TMP=str(native_temp), TEMP=str(native_temp),
                   OPENBLAS_NUM_THREADS='1', OMP_NUM_THREADS='1')
        command = [str(executable), '--factory-startup', '--disable-autoexec', '--threads', '1']
        gui = args.mode == 'undo' or (args.mode == 'scopes' and args.gui)
        if not gui:
            command.append('--background')
        else:
            command.extend(['--enable-event-simulate', '--window-geometry', '0', '0', '1280', '960'])
        command.extend(['--python-exit-code', '1', '--python', str(runner), '--',
                        str(package.parent), str(report)])
        command.extend([str(args.blend)] if args.mode == 'inspect' else
                       [str(args.blend), args.node, json.dumps(scope_options)] if args.mode == 'scopes' else
                       [str(args.cycles), str(args.blend), args.node])
        receipt.update(command=command, status='launching')
        write_json(output / 'launch.json', receipt)
        process = None
        try:
            with ExitStack() as services:
                services.enter_context(termination_as_interrupt())
                if gui:
                    services.enter_context(display_adapter(resources)(resources, work, env))
                with (output / 'native.log').open('w', encoding='utf8') as log:
                    process = subprocess.Popen(command, cwd=work, env=env,
                        stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                        start_new_session=True)
                    receipt.update(pid=process.pid, status='running')
                    write_json(output / 'launch.json', receipt)
                    try:
                        code = process.wait(timeout=args.timeout)
                    finally:
                        stop_group(process)
                receipt['native_returncode'] = code
                result = json.loads(report.read_text()) if report.is_file() else {}
                receipt['passed'] = code == 0 and result.get('passed') is True
                receipt['status'] = 'complete' if receipt['passed'] else 'failed'
                if code == 0 and not receipt['passed']:
                    code = 1
        except subprocess.TimeoutExpired:
            receipt.update(status='timeout', error='Native probe exceeded its deadline')
            code = 124
        except KeyboardInterrupt:
            receipt.update(status='interrupted', error='Native probe interrupted')
            code = 130
        except Exception as error:
            receipt.update(status='failed', error=str(error), error_type=type(error).__name__)
            code = 1
        finally:
            try:
                if process is not None and process.poll() is None:
                    stop_group(process)
                preserve_logs(work, output)
            finally:
                receipt['elapsed_seconds'] = time.monotonic() - began
                receipt['finished_at'] = datetime.now(timezone.utc).isoformat()
                receipt['blend_sha256_after'] = sha256(args.blend)
                receipt['original_unchanged'] = receipt['blend_sha256_after'] == receipt['blend_sha256']
                if not receipt['original_unchanged']:
                    receipt.update(status='failed', passed=False, error='Source project changed during the probe')
                    code = 1
                receipt['exit_code'] = code
                write_json(output / 'launch.json', receipt)
    print(json.dumps(dict(output_dir=str(output), status=receipt['status'],
                          passed=receipt['passed'], original_unchanged=receipt['original_unchanged']), indent=2))
    return code if code >= 0 else 128 - code


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--blend', type=Path, required=True, help='Existing project; never saved by this probe')
    parser.add_argument('--output-dir', type=Path, required=True, help='New or empty directory for persistent evidence')
    parser.add_argument('--mode', choices=('inspect', 'scopes', 'undo'), default='inspect')
    parser.add_argument('--cycles', type=int, default=2, help='Undo scenarios, at least 2 (default: 2)')
    parser.add_argument('--node', default='Grade', help='Grade node selected for scopes or undo')
    parser.add_argument('--scope-owner', choices=('compositor', 'material', 'world'), default='compositor')
    parser.add_argument('--material', default='', help='Material/World name for shader scopes; required when ambiguous')
    parser.add_argument('--workspace', default='', help='Use the saved workspace and its viewport, e.g. Shading')
    parser.add_argument('--gui', action='store_true', help='Measure the first matching production scope draw in a visible window')
    parser.add_argument('--scope-diagnostics', action='store_true', help='Record scalar native capture phases and execution events')
    parser.add_argument('--scope-page-order',choices=('forward','reverse'),default='forward',help='Scope page visit order for independent cold comparisons')
    parser.add_argument('--complex-native',action='store_true',help='Also measure automatic acquisition of a temporary complex native input')
    parser.add_argument('--cold-runs', type=int, default=1, help='Independent native processes and helper sessions (scopes only)')
    parser.add_argument('--timeout', type=float, default=1800, help='Native process deadline in seconds')
    args = parser.parse_args()
    args.blend = args.blend.expanduser().resolve()
    output = args.output_dir.expanduser().resolve()
    if not args.blend.is_file():
        parser.error('--blend must name an existing file')
    if args.cycles < 2 or args.timeout <= 0:
        parser.error('--cycles must be at least 2 and --timeout must be positive')
    if args.cold_runs < 1:
        parser.error('--cold-runs must be positive')
    if args.mode != 'scopes' and (args.cold_runs != 1 or args.gui or args.scope_diagnostics or args.complex_native or args.scope_page_order!='forward'):
        parser.error('--cold-runs, --gui, --scope-diagnostics, --scope-page-order and --complex-native require --mode scopes')
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        parser.error('--output-dir must be new or empty to preserve prior evidence')
    output.mkdir(parents=True, exist_ok=True)
    resources = files('tools.diagnostics')
    if args.cold_runs == 1:
        return launch(args, resources, output)
    runs = []
    code = 0
    for number in range(1, args.cold_runs + 1):
        directory = output / ('cold-' + str(number))
        directory.mkdir()
        current = launch(args, resources, directory)
        code = code or current
        runs.append(dict(directory=directory.name,
                         launch=json.loads((directory / 'launch.json').read_text()),
                         report=json.loads((directory / 'report.json').read_text())
                         if (directory / 'report.json').is_file() else {}))
        write_json(output / 'summary.json', dict(schema=1, passed=code == 0, runs=runs,
            limitations=['Each cold run has a fresh Blender process, configuration and helper session; operating-system disk caches are not cleared.',
                         'Headless current-state and GUI draw-callback timings are different measurements.',
                         'Inclusive foreground and helper phase durations overlap and must not be summed.']))
    return code


if __name__ == '__main__':
    raise SystemExit(main())
