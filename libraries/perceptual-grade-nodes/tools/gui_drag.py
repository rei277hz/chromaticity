"""Launch fresh native Blender windows and summarize matching preview-draw latency.

The experiment uses a synthetic preview of native grading. It is deliberately
separate from the headless EXR benchmark and from future Next product workflows.
"""
import argparse
from contextlib import nullcontext
import hashlib
import importlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
import time

from .gui_drag_report import summarize_samples, summary
from .gui_drag_runner import SCENARIOS


def available_cpu_affinity():
    if hasattr(os, 'sched_getaffinity'):
        return sorted(os.sched_getaffinity(0))
    return None


def available_cpu_count():
    affinity = available_cpu_affinity()
    return len(affinity) if affinity is not None else (os.cpu_count() or 1)


def host_snapshot():
    result = dict(cpu_count=os.cpu_count(), available_cpu_count=available_cpu_count(),
                  cpu_affinity=available_cpu_affinity(), processor=platform.processor())
    if hasattr(os, 'getloadavg'):
        result['load_average'] = list(os.getloadavg())
    for name in ('cpu', 'io', 'memory'):
        path = Path('/proc/pressure')/name
        if path.is_file():
            result[name+'_pressure'] = path.read_text()
    return result


def source_identities():
    from color_tools import perceptual_grade_nodes, color_core, perceptual_grade_reference
    result = {}
    for module in (perceptual_grade_nodes, color_core, perceptual_grade_reference):
        root = Path(module.__file__).parent
        for path in sorted(root.rglob('*.py')):
            result[f'{root.name}/{path.relative_to(root)}'] = hashlib.sha256(path.read_bytes()).hexdigest()
    root = Path(perceptual_grade_nodes.__file__).parent
    resource = root/'output_boundary.npz'
    result['output_boundary.npz'] = hashlib.sha256(resource.read_bytes()).hexdigest()
    for name in ('tonal_web', 'selective_adaptance', 'hk_guard'):
        module = importlib.import_module('color_tools.perceptual_grade_core.model.'+name)
        result[f'oracle_core/{name}.py'] = hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()
    for name in ('gui_drag.py', 'gui_drag_runner.py', 'gui_drag_report.py', 'native.py', 'cases.py', 'full_cases.py', 'oracle.py'):
        path = Path(__file__).with_name(name)
        result[f'tools/{name}'] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def write_report(output, report):
    (output/'report.json').write_text(json.dumps(report, indent=2, allow_nan=False)+'\n')
    lines = ['# Synthetic native Grade displayed-preview latency', '', report['contract'], '',
             f"Backend: `{report.get('backend', 'cpu')}`; requested native threads: "
             f"{report.get('threads', 'legacy default')} across {report.get('available_cpu_count', 'unknown')} available CPUs. "
             'Backend/device and renderer identities are retained per session.', '',
             f"Numerical acceptance: {report.get('numerical_passed', 'pending')}; "
             f"reference-probe failures: {report.get('reference_probe_failure_count', 'pending')}. "
             'The reference error limit remains 1e-4. Numerical failures are retained while the timing corpus completes.', '',
             '| Context | Scenario | Drawn / accepted | First activation p50 / p95 (s) | Scenario entry p50 / p95 (s) | Repeated p50 / p95 (s) |',
             '|---|---|---:|---:|---:|---:|']
    def values(value):
        return '—' if value is None else f"{value['p50_seconds']:.6f} / {value['p95_seconds']:.6f}"
    for context, result in report['contexts'].items():
        for row in result['groups']:
            lines.append(f"| {context} | {row['scenario']} | {row['drawn_count']} / {row['accepted_count']} | "
                         f"{values(row['first_activation'])} | {values(row['scenario_entry'])} | "
                         f"{values(row['repeated_updates'])} |")
    lines.extend(['', 'Initialization is reported separately in JSON, along with every accepted sample, settings, '
                  'revision, phase duration, image hash and verified framebuffer witness. '
                  'p95 uses nearest rank; these descriptive sample quantiles are not a population guarantee. '
                  'No latency threshold is imposed. Ordinary samples wait for the previous matching draw. '
                  'The explicit burst scenario records every acceptance and marks overwritten samples superseded. '
                  'First activation is per actually active grading family and is separate from scenario entry. '
                  'Independent reference probes are computed before acceptance, then checked against the native '
                  'readback before publication; their untimed preparation cost is recorded.', '',
                  'This measures native render, in-memory readback and an actual GUI preview draw. '
                  'It does not measure automatic native viewport shader updates, Next UI scheduling, input-event '
                  'backlogs, or physical frame presentation. The `software-gpu` backend uses Eevee for Shader '
                  'and GPU Compositor evaluation; Linux Xvfb uses Mesa llvmpipe, which executes GPU work on CPU cores. '
                  'OpenBLAS remains single-threaded to avoid nested NumPy worker pools.', ''])
    (output/'report.md').write_text('\n'.join(lines))


def run(args):
    from .gpu_report import display_environment
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    work = output/'sessions'
    work.mkdir(exist_ok=True)
    identities = source_identities()
    executable = args.blender.resolve()
    if executable.is_dir():
        candidates = (executable/'blender', executable/'Blender.app/Contents/MacOS/Blender')
        executable = next(path for path in candidates if path.is_file())
    if not executable.is_file():
        raise ValueError('Pass a native Blender binary or extracted distribution directory')
    report = dict(schema=1, contract='Accepted setting → native evaluation → in-memory Viewer readback → '
                                   'preview texture → matching actual POST_PIXEL framebuffer draw. '
                                   'Standalone synthetic displayed preview; not Next UI or automatic native viewport evaluation.',
                  size=[args.size]*2, sessions_per_context=args.sessions,
                  samples_per_scenario=args.samples, scenarios=args.scenarios,
                  platform=platform.platform(), cpu_count=os.cpu_count(), backend=args.backend,
                  threads=args.threads, available_cpu_count=available_cpu_count(),
                  cpu_affinity=available_cpu_affinity(),
                  host_start=host_snapshot(),
                  source_sha256=identities, sessions=[], contexts={}, completed=False)
    # Blender loads its own bpy/numpy before these Buck-owned pure Python paths.
    import_paths = [str(Path(path).resolve()) for path in sys.path if path and Path(path).is_dir()]
    runner = Path(__file__).with_name('gui_drag_runner.py').resolve()
    for context in args.contexts:
        for ordinal in range(args.sessions):
            stem = f'{context}-{ordinal}'
            directory = work/stem
            directory.mkdir(exist_ok=True)
            config = dict(output=str(directory/'report.json'), context=context, size=args.size,
                          samples=args.samples, scenarios=args.scenarios, session=ordinal,
                          timeout=args.timeout, import_paths=import_paths,
                          backend=args.backend, threads=args.threads,
                          cpu_affinity=available_cpu_affinity())
            configuration = directory/'configuration.json'
            configuration.write_text(json.dumps(config, indent=2)+'\n')
            service = display_environment(args.xvfb, directory) if args.xvfb else nullcontext(dict(os.environ))
            with service as env, tempfile.TemporaryDirectory(prefix='pg-gui-') as runtime_directory:
                runtime = Path(runtime_directory)
                env.update(BLENDER_USER_CONFIG=str(directory/'config'),
                           BLENDER_USER_EXTENSIONS=str(directory/'extensions'),
                           XDG_RUNTIME_DIR=str(runtime), PYTHONDONTWRITEBYTECODE='1',
                           OPENBLAS_NUM_THREADS='1', OMP_NUM_THREADS=str(args.threads))
                if args.backend == 'software-gpu':
                    env['LP_NUM_THREADS'] = str(args.threads)
                worker_environment = {key: env.get(key) for key in
                                      ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'LP_NUM_THREADS',
                                       'LIBGL_ALWAYS_SOFTWARE', 'GALLIUM_DRIVER')}
                for key in ('PYTHONPATH', 'PYTHONHOME', 'BLENDER_USER_SCRIPTS', 'BLENDER_SYSTEM_SCRIPTS',
                            'BLENDER_SYSTEM_PYTHON'):
                    env.pop(key, None)
                command = [str(executable), '--factory-startup', '--disable-autoexec',
                           '--window-geometry', '0', '0', '1280', '960', '--python-exit-code', '1',
                           '--python', str(runner), '--', '--configuration', str(configuration)]
                begin = time.perf_counter()
                with (directory/'native.log').open('w') as log:
                    process = subprocess.run(command, cwd=directory, env=env, stdout=log,
                                             stderr=subprocess.STDOUT, timeout=args.timeout+120)
            result_path = directory/'report.json'
            result = json.loads(result_path.read_text()) if result_path.exists() else {'completed': False}
            result.update(command=command, process_returncode=process.returncode,
                          process_wall_seconds=time.perf_counter()-begin,
                          report_path=str(result_path), worker_environment=worker_environment)
            for row in result.get('samples', []):
                row['session'] = ordinal
            report['sessions'].append(result)
            for name in args.contexts:
                report['contexts'][name] = summarize_samples([
                    row for session in report['sessions'] if session.get('context') == name
                    for row in session.get('samples', [])])
            write_report(output, report)
            if process.returncode or not result.get('completed') or not result.get('resource_inventory_preserved'):
                raise RuntimeError(f'GUI session {stem} failed; see {directory}/native.log and report.json')
            print(f"{stem}: {result['summary']['drawn_count']} matching preview draws, "
                  f"{result['summary']['superseded_count']} superseded", flush=True)
    report['initialization'] = {
        context: {name: summary([session['initialization'][name] for session in report['sessions']
                                if session['context'] == context and name in session['initialization']])
                  for name in sorted({name for session in report['sessions']
                                      if session['context'] == context for name in session['initialization']})}
        for context in args.contexts}
    report['sources_stable_during_run'] = identities == source_identities()
    report['numerical_passed'] = all(session.get('numerical_passed', session.get('correctness_passed', False))
                                     for session in report['sessions'])
    report['reference_probe_failure_count'] = sum(len(session.get('reference_probe_failures', []))
                                                  for session in report['sessions'])
    report['correctness_passed'] = all(session.get('correctness_passed', False) for session in report['sessions'])
    report['host_finish'] = host_snapshot()
    report['completed'] = report['sources_stable_during_run']
    write_report(output, report)
    if not report['completed']:
        raise RuntimeError('Sources changed during the GUI experiment; retain the report as a partial run')
    if not report['correctness_passed']:
        raise RuntimeError('GUI timing corpus completed, but numerical acceptance failed; see report.json')
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--blender', type=Path, required=True)
    parser.add_argument('--xvfb', type=Path)
    parser.add_argument('--backend', choices=('cpu', 'software-gpu'), default='cpu',
                        help='CPU rendering, or Eevee/GPU Compositor through the software OpenGL fixture')
    parser.add_argument('--threads', type=int, default=available_cpu_count(),
                        help='Native/Mesa worker threads; defaults to the available CPU affinity count')
    parser.add_argument('--size', type=int, default=1024)
    parser.add_argument('--sessions', type=int, default=3)
    parser.add_argument('--samples', type=int, default=60)
    parser.add_argument('--contexts', nargs='+', choices=('shader', 'compositor'), default=['shader', 'compositor'])
    parser.add_argument('--scenarios', nargs='+', choices=SCENARIOS, default=list(SCENARIOS))
    parser.add_argument('--timeout', type=float, default=7200.)
    args = parser.parse_args(argv)
    if args.size < 32 or args.size % 16 or args.samples < 1 or args.sessions < 1 or args.threads < 1:
        parser.error('Require size >=32 divisible by16, and positive samples/sessions/threads')
    if args.samples*(len(args.scenarios)+2*args.scenarios.count('burst_exposure')) >= 65536:
        parser.error('16-bit framebuffer token requires fewer than 65536 samples per session')
    run(args)


if __name__ == '__main__':
    main()
