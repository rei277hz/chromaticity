from color_tools.perceptual_grade_blender.model.bake_inverse_gpu import Program as ReferenceGPUProgram
"""Fresh reference LUT bake timings, comparing the H-K flag in one run."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace
from datetime import datetime
import hashlib
import importlib
from importlib.resources import files
import json
import os
from pathlib import Path
import platform
from statistics import median
import subprocess
import sys
from time import perf_counter
import traceback

import numpy as np

from color_tools.perceptual_grade_core.model import bake_inverse
from color_tools.perceptual_grade_core.model.boundary_polynomial import PolynomialTable
from color_tools.perceptual_grade_reference.grading import ToneSettings
from color_tools.perceptual_grade_reference.grading import ColorSettings
from color_tools.perceptual_grade_core.model.tonal_web import WebSettings
from color_tools.perceptual_grade_reference.model import Settings
from tests.reference.legacy_capacity import LegacyCapacityModel
from tests.reference.legacy_capacity import LegacyCapacityBakeStack
from tools.analysis import hk_bake_phases


CASES = ('forward', 'inverse', 'raw_stack')
LABELS = {'forward': 'Forward A', 'inverse': 'Inverse B',
          'raw_stack': 'Forward A → inverse B (raw Stack)',
          'separate_rgb_luts': 'Separate forward A + inverse B RGB LUTs'}
CPU_CHUNK = 65536
THREAD_ENV = ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS',
              'NUMEXPR_NUM_THREADS', 'VECLIB_MAXIMUM_THREADS', 'LP_NUM_THREADS',
              'LIBGL_ALWAYS_SOFTWARE', 'GALLIUM_DRIVER', 'MESA_SHADER_CACHE_DIR',
              'MESA_SHADER_CACHE_DISABLE')


def settings():
    a = Settings(tone=ToneSettings(input_nits=(0., 7., 45., 203., 1000.)),
        color=ColorSettings(global_gain=.15, web=WebSettings(
            hue_degrees=((0.,)*6,(3.,2.,1.,-1.,-2.,0.),(0.,)*6,(0.,)*6),
            log_chroma=((0.,)*6,(.03,0.,-.02,0.,.01,0.),(0.,)*6,(0.,)*6),
            log_scale=((0.,)*6,(0.,)*6,(.02,0.,0.,-.01,0.,0.),(0.,)*6)),
            adaptance=((0., 0.), (0., 0.), (0., .01), (0., 0.)),
            lightness=((0., 0., 0., 0.), (0., .1, 0., 0.),
                       (0., 0., 0., 0.), (0., 0., 0., 0.))))
    return a, replace(a, color=replace(a.color, global_gain=.10))


def lattice(size):
    axis = .01*np.expm1(np.linspace(0., 1., size)*np.log1p(1024/.01))
    axis[0], axis[-1] = 0., 1024.
    return np.stack(np.meshgrid(axis, axis, axis, indexing='ij'), -1).reshape(-1, 3).astype('f4')


def fresh_stack(name, table, enabled):
    a, b = settings()
    values, directions = {'forward': ([a], ['FORWARD']),
        'inverse': ([b], ['INVERSE']),
        'raw_stack': ([a, b], ['FORWARD', 'INVERSE'])}[name]
    return LegacyCapacityBakeStack(values, directions, table, hk_guard=enabled, program_factory=ReferenceGPUProgram)


def cpu_bake(stack, rgb):
    with ThreadPoolExecutor(max_workers=4, thread_name_prefix='PG timing') as pool:
        return np.concatenate(list(pool.map(stack.bake_native,
            [rgb[i:i+CPU_CHUNK] for i in range(0, len(rgb), CPU_CHUNK)])))


def digest(value):
    return hashlib.sha256(value).hexdigest()


def same_bits(a, b):
    return a.shape == b.shape and a.dtype == b.dtype and a.tobytes() == b.tobytes()


def source_fingerprints():
    names = ['appearance', 'grading', 'tonal_web', 'selective_adaptance', 'model', 'stack', 'stack_kernel',
             'responses', 'cube_guard', 'hk_guard', 'bake', 'bake_gpu', 'bake_inverse',
             'bake_inverse_gpu', 'boundary_gpu', 'boundary_polynomial', 'tone_table']
    gpu_modules = {'bake_gpu', 'bake_inverse_gpu', 'boundary_gpu'}
    shared_modules = {'tonal_web', 'selective_adaptance', 'stack_kernel', 'hk_guard',
                      'bake', 'bake_inverse', 'boundary_polynomial', 'tone_table'}
    modules = [('color_tools.perceptual_grade_blender.model.' if name in gpu_modules else
                'color_tools.perceptual_grade_core.model.' if name in shared_modules else
                'color_tools.perceptual_grade_reference.') + name for name in names]
    modules += ['tests.reference.legacy_capacity',
                'tools.analysis.bake_time_breakdown', 'tools.analysis.hk_bake_phases',
                'tools.analysis.hk_bake_gpu_phases', 'tools.analysis.inverse_gpu_startup']
    return {name: digest(Path(importlib.import_module(name).__file__).read_bytes()) for name in modules}


def read_optional(path):
    try:
        return Path(path).read_text().strip()
    except OSError:
        return None


def provenance():
    cpu = read_optional('/proc/cpuinfo') or ''
    model = next((line.split(':', 1)[1].strip() for line in cpu.splitlines()
                  if line.startswith('model name')), platform.processor())
    try:
        buck = subprocess.run(['buck2', '--version'], capture_output=True, text=True,
                              timeout=10, check=False).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        buck = None
    return dict(platform=platform.platform(), machine=platform.machine(), cpu=model,
        logical_cpus=os.cpu_count(), affinity=sorted(os.sched_getaffinity(0)) if hasattr(os, 'sched_getaffinity') else None,
        python=sys.version, numpy=np.__version__, buck2=buck,
        cpu_quota=read_optional('/sys/fs/cgroup/cpu.max'),
        memory_limit=read_optional('/sys/fs/cgroup/memory.max'),
        thread_environment={name: os.environ.get(name) for name in THREAD_ENV},
        source_sha256=source_fingerprints(),
        resource_sha256={name: digest((files('color_tools.perceptual_grade_reference')/name).read_bytes())
                         for name in ('d65_cube.npz', 'd65_boundary.npz')})


def diagnostics(stack, name, rgb, values):
    if not np.isfinite(values).all():
        raise ArithmeticError('Nonfinite bake output')
    result = dict(finite=True, output_sha256=digest(values.tobytes()),
        minimum_rgb=float(values[:, :3].min()), maximum_rgb=float(values[:, :3].max()))
    if name != 'forward':
        if name == 'raw_stack':
            limit = np.full(len(rgb), bake_inverse.TOLERANCE, dtype='f4')
        else:
            limit = stack.solvers[-1].acceptance_limit(rgb)
        residual = values[:, 3]
        result.update(approximate_pixels=int(np.count_nonzero(residual > limit)),
            maximum_residual=float(residual.max()),
            residual_quantiles=dict(zip(('p50', 'p90', 'p99', 'p99_9'),
                np.percentile(residual, [50, 90, 99, 99.9]).tolist())))
    return result


def trial(name, backend, enabled, table, rgb, program, instrumented=False, expected=None):
    start = perf_counter()
    stack = fresh_stack(name, table, enabled)
    if backend == 'GPU':
        stack.program = program
    setup = perf_counter()-start
    before_upload = getattr(program, 'parameter_upload_total_seconds', 0.) if backend == 'GPU' else 0.
    began = perf_counter()
    if instrumented and backend == 'CPU':
        values, phases = hk_bake_phases.run([stack], stack.bake_native, rgb,
                                          chunk=CPU_CHUNK, expected=expected)
    elif instrumented:
        from tools.analysis import hk_bake_gpu_phases
        values, phases = hk_bake_gpu_phases.run(program,
            lambda rows: stack.bake_native(rows, 'GPU'), rgb, expected=expected)
    else:
        values = cpu_bake(stack, rgb) if backend == 'CPU' else stack.bake_native(rgb, 'GPU')
        phases = None
    bake = perf_counter()-began
    # For instrumentation, identity verification and profile aggregation follow
    # the measured operation. Use its exact operation wall interval as bake.
    if phases is not None:
        bake = phases['wall_seconds']
    record = dict(setup_seconds=setup, tone_preparation_seconds=stack.tone_table_seconds,
        bake_seconds=bake, total_seconds=setup+bake,
        tone_tables=[dict(cells=t.cells, bytes=t.bytes, tolerance=t.tolerance,
                         preparation_probe_relative_error=t.max_error) for t in stack.tone_tables])
    if backend == 'GPU':
        record['parameter_upload_seconds'] = program.parameter_upload_total_seconds-before_upload
    if phases is not None:
        record['phases'] = phases
    record['diagnostics'] = diagnostics(stack, name, rgb, values)
    return values, record


def sum_records(a, b):
    result = {name: a[name]+b[name] for name in (
        'setup_seconds', 'tone_preparation_seconds', 'bake_seconds', 'total_seconds')}
    result['components'] = {'forward': a, 'inverse': b}
    if 'parameter_upload_seconds' in a:
        result['parameter_upload_seconds'] = a['parameter_upload_seconds']+b['parameter_upload_seconds']
    if 'phases' in a:
        pa, pb = a['phases'], b['phases']
        result['phases'] = dict(wall_seconds=pa['wall_seconds']+pb['wall_seconds'],
            bit_identical=pa['bit_identical'] and pb['bit_identical'],
            description='Sum of two separate completed instrumented bakes; sequential-job accounting.')
        for key in ('critical_worker_seconds', 'all_worker_seconds'):
            if key in pa:
                result['phases'][key] = {name: pa[key][name]+pb[key][name] for name in pa[key]}
        if 'api' in pa:
            result['phases']['api'] = {}
            for name in pa['api'].keys() | pb['api'].keys():
                rows = [p['api'].get(name, {}) for p in (pa, pb)]
                result['phases']['api'][name] = {key: sum(row.get(key, 0) for row in rows)
                    for key in ('calls', 'seconds', 'exclusive_seconds')}
            result['phases']['host_remainder_seconds'] = pa['host_remainder_seconds']+pb['host_remainder_seconds']
    return result


def summarize(report):
    lines = ['# Fresh LUT bake time breakdown', '',
        f'Status: **{report["status"]}**. Run {report["started_at"]}.', '',
        f'{report["size"]}³ = {report["vertices_per_lut"]:,} production-shaped vertices per LUT. '
        f'One initial full bake is retained separately, followed by {report["repeats"]} uninstrumented trials and one instrumented bake.', '',
        'All times below are milliseconds. Tone-table construction is a subset of setup; it is not added a second time. '
        'Immutable lookup/GPU initialization/program preparation are reported separately.']
    provenance = report.get('provenance')
    if provenance:
        lines += ['', f'Host: {provenance["cpu"]}; {provenance["platform"]}. '
            f'{provenance["logical_cpus"]} logical CPUs; affinity {provenance["affinity"]}; '
            f'cgroup CPU quota: `{provenance["cpu_quota"]}`.', '',
            f'Python {provenance["python"].splitlines()[0]}; NumPy {provenance["numpy"]}; '
            f'Buck2 `{provenance["buck2"]}`.', '',
            f'CPU: {report["cpu_workers"]} workers, {report["cpu_chunk"]:,}-row chunks. '
            f'GPU: {report["gpu_batch"]:,}-row dispatch batches.']
        environment = ', '.join(f'{name}={value}' for name, value in
            provenance['thread_environment'].items() if value is not None)
        lines += ['', 'Explicit thread/driver environment: `'+(environment or '(none)')+'`.']
    if 'gpu' in report:
        gpu = report['gpu']
        lines += ['', f'GPU backend: {gpu["backend"]}; {gpu["renderer"]}; '
            f'vendor {gpu["vendor"]}; Blender {gpu["blender"]}.']
    preparation = [
        ('lookup_preparation_seconds', 'Shared boundary lookup preparation'),
        ('lattice_preparation_seconds', 'Shared lattice preparation'),
        ('gpu_initialization_seconds', 'Blender/GPU initialization'),
        ('gpu_program_preparation_seconds', 'Shared GPU program preparation'),
        ('gpu_shader_creation_seconds', 'Shader creation (subset of program preparation)'),
    ]
    if any(key in report for key, _ in preparation):
        lines += ['', '| Shared preparation, excluded from per-bake totals | ms |',
                  '| --- | ---: |']
        lines += [f'| {label} | {1000*report[key]:.2f} |'
                  for key, label in preparation if key in report]
    lines += ['', 'Repeated-trial columns show median [minimum, maximum].', '',
        '| Workload | Backend | H–K | Initial total | Setup | Tone subset | Bake | Total |',
        '| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |']
    for name, case in report.get('cases', {}).items():
        for backend, versions in case['backends'].items():
            for mode, data in versions.items():
                values = data.get('trials', [])
                initial = data.get('initial', {}).get('total_seconds')
                if not values:
                    continue
                def spread(key):
                    times = [1000*row[key] for row in values]
                    return f'{median(times):.2f} [{min(times):.2f}, {max(times):.2f}]'
                first = '—' if initial is None else f'{1000*initial:.2f}'
                lines.append(f'| {LABELS[name]} | {backend} | {mode} | {first} | {spread("setup_seconds")} | '
                    f'{spread("tone_preparation_seconds")} | {spread("bake_seconds")} | '
                    f'{spread("total_seconds")} |')
    lines += ['', '| Workload | Backend | H–K off total median | H–K on total median | Difference | Ratio |',
              '| --- | --- | ---: | ---: | ---: | ---: |']
    for name, case in report.get('cases', {}).items():
        for backend, versions in case['backends'].items():
            if any(not versions.get(mode, {}).get('trials') for mode in ('off', 'on')):
                continue
            off, on = [median(row['total_seconds'] for row in versions[mode]['trials']) for mode in ('off', 'on')]
            lines.append(f'| {LABELS[name]} | {backend} | {1000*off:.2f} | {1000*on:.2f} | {1000*(on-off):+.2f} | {on/off:.3f}× |')
    lines += ['', '## Inverse diagnostics', '',
        'Approximate means the returned candidate exceeds this path’s acceptance tolerance; '
        'counts show median [minimum, maximum] across repeated trials. CPU solve-lane counts '
        'come from the separate instrumented bake and include repeated solver calls. '
        'The GPU shader does not expose solve-lane counters. Inverse candidates come from '
        'the raw appearance solve or simple analytic path, with complete-forward validation '
        'and no additional RGB refinement.', '',
        'Grade A uses global chroma gain 0.15 stops and B uses 0.10 stops. The raw A→inverse B '
        'fixture can require source colors outside AP1; those are returned as validated approximations. '
        'These counts combine gamut-domain limits with finite-search limits, and are not counts of raw '
        'solver failures. Known in-cube mixed web targets are checked separately by the CPU/GPU inverse tests.', '',
        '| Workload | Backend | H–K | Approximate vertices | Largest residual | Raw-solve lanes |',
        '| --- | --- | --- | ---: | ---: | ---: |']
    for name in ('inverse', 'raw_stack'):
        for backend, versions in report.get('cases', {}).get(name, {}).get('backends', {}).items():
            for mode, data in versions.items():
                diagnostics = [row['diagnostics'] for row in data.get('trials', [])]
                if not diagnostics:
                    continue
                counts = [row['approximate_pixels'] for row in diagnostics]
                count = f'{median(counts):,.0f} [{min(counts):,}, {max(counts):,}]'
                residual = max(row['maximum_residual'] for row in diagnostics)
                phases = data.get('instrumented', {}).get('phases', {})
                lanes = '—' if 'raw_solve_rows' not in phases else f'{phases["raw_solve_rows"]:,}'
                lines.append(f'| {LABELS[name]} | {backend} | {mode} | {count} | '
                    f'{residual:.6g} | {lanes} |')
    raw_equality = report.get('cases', {}).get('raw_stack', {}).get('same_output_bits', {})
    if raw_equality:
        lines += ['', 'Raw Stack H–K off/on strict shape/dtype/byte equality: '+
                  ', '.join(f'{backend}={value}' for backend, value in raw_equality.items())+'.']
    for name, case in report.get('cases', {}).items():
        lines += ['', '## '+LABELS[name], '', case['description']]
        for backend, versions in case['backends'].items():
            profiles = {mode: data['instrumented']['phases'] for mode, data in versions.items() if 'instrumented' in data}
            if not profiles:
                continue
            lines += ['', f'### {backend} instrumented bake phases', '',
                      '| Phase | H–K off ms | H–K on ms |', '| --- | ---: | ---: |']
            if backend == 'CPU':
                names = {**hk_bake_phases.PHASES, 'host_idle': 'Host coordination and gaps on finishing worker'}
                for key, label in names.items():
                    times = ['—' if mode not in profiles else f'{1000*profiles[mode]["critical_worker_seconds"][key]:.2f}' for mode in ('off', 'on')]
                    lines.append('| '+label+' | '+' | '.join(times)+' |')
            else:
                names = sorted(set().union(*(p['api'] for p in profiles.values())))
                for key in names:
                    times = ['—' if mode not in profiles else f'{1000*profiles[mode]["api"].get(key, {}).get("exclusive_seconds", 0):.2f}' for mode in ('off', 'on')]
                    lines.append('| '+key+' | '+' | '.join(times)+' |')
                times = ['—' if mode not in profiles else f'{1000*profiles[mode]["host_remainder_seconds"]:.2f}' for mode in ('off', 'on')]
                lines.append('| Host orchestration/conversion | '+' | '.join(times)+' |')
            times = ['—' if mode not in profiles else f'{1000*profiles[mode]["wall_seconds"]:.2f}' for mode in ('off', 'on')]
            lines.append('| Instrumented bake total | '+' | '.join(times)+' |')
    lines += ['', '## Measurement scope', '', *('- '+v for v in report['limitations'])]
    if 'failure' in report:
        lines += ['', 'Failure: `'+report['failure']['message']+'`. See report.json for the traceback.']
    return '\n'.join(lines)+'\n'


def write_report(output, report):
    output.mkdir(parents=True, exist_ok=True)
    for name, content in [('report.json', json.dumps(report, indent=2)+'\n'),
                          ('summary.md', summarize(report))]:
        temporary = output/(name+'.tmp')
        temporary.write_text(content)
        temporary.replace(output/name)


def run(output, size=65, repeats=3, cpu_only=False):
    report = dict(status='running', started_at=datetime.now().astimezone().isoformat(),
        size=size, vertices_per_lut=size**3, repeats=repeats, cpu_workers=4, cpu_chunk=CPU_CHUNK,
        gpu_batch=4096, command=sys.argv, cases={}, execution_order=[],
        settings={key: asdict(value) for key, value in zip(('A', 'B'), settings())},
        solver=dict(strategy='raw_appearance_candidates_with_complete_forward_validation',
            full_rgb_refinement=False, raw_iterations=bake_inverse.ITERATIONS,
            stopping=float(bake_inverse.SEARCH_TOLERANCE), raw_tolerance=float(bake_inverse.TOLERANCE),
            rgb_relative=float(bake_inverse.RGB_RELATIVE_TOLERANCE), rgb_absolute=float(bake_inverse.RGB_ABSOLUTE_TOLERANCE),
            finite_difference_step=float(bake_inverse.STEP)),
        limitations=[
            'Each invocation performs fresh measurements. No historical baseline, saved LUT reuse, or timing gate is used.',
            'One initial full bake is reported separately for each workload/backend/H-K mode; every subsequent trial constructs a fresh grade and recomputes all vertices.',
            'Immutable lookup and GPU program objects are shared within this run; tone tables and grade parameter uploads are rebuilt for each trial.',
            'Setup includes tone-table preparation. Total is setup plus bake, excluding common startup and untimed diagnostics.',
            'Separate RGB LUTs is the additive cost of the independently measured forward and inverse regular grids, not inverse(forward(lattice)).',
            'Raw Stack A→inverse B passes raw appearance and bypasses H-K export repair; A/B have distinct gains and do not trigger matching-pair cancellation.',
            'Inverse search generates raw-appearance or analytic candidates, then validates complete-forward reproduction; it performs no additional complete-forward RGB refinement.',
            'CPU phases are exclusive intervals on the finishing worker, including scheduling; all-worker sums overlap. Instrumentation adds overhead.',
            'GPU phases are host API intervals around actual llvmpipe dispatch/readback, not hardware execution timers or mathematical shader phases.',
            'Initial GPU uses the current driver-cache policy and is not guaranteed cold. No existing driver cache is removed.',
            'No Blender UI/timer delay, RGBE packing, image installation, scopes, LUT interpolation, or physical-GPU latency is measured.',
            'Inverse residual counts describe candidate acceptance, not a global convergence or inverse-existence certificate.',
            'The fixture retains A gain=0.15 and B gain=0.10 stops. Raw A-to-inverse-B can require out-of-cube source RGB; complete-forward validation reports that domain limit as an approximation.',
            'Negative-energy raw targets can give a black guarded seed; the finite raw solve retains that existing initialization limitation.'])
    write_report(output, report)
    began = perf_counter()
    try:
        if not cpu_only:
            os.environ['LIBGL_ALWAYS_SOFTWARE'] = '1'
            os.environ['GALLIUM_DRIVER'] = 'llvmpipe'
        report['provenance'] = provenance()
        start = perf_counter()
        table = PolynomialTable(LegacyCapacityModel().boundary.cache)
        report['lookup_preparation_seconds'] = perf_counter()-start
        report['cpu_lookup_bytes'] = sum(v.nbytes for v in table.expanded.values())
        start = perf_counter()
        rgb = lattice(size)
        report['lattice_preparation_seconds'] = perf_counter()-start
        report['lattice'] = dict(shaper='0.01 * expm1(u * log1p(1024 / 0.01))',
            domain=[0., 1024.], dtype=str(rgb.dtype), sha256=digest(rgb.tobytes()))
        program = None
        backends = ('CPU',) if cpu_only else ('CPU', 'GPU')
        if not cpu_only:
            start = perf_counter()
            import bpy, gpu
            bpy.context.preferences.system.gpu_backend = 'OPENGL'
            gpu.init()
            report['gpu_initialization_seconds'] = perf_counter()-start
            renderer = gpu.platform.renderer_get()
            vendor_get = getattr(gpu.platform, 'vendor_get', lambda: None)
            report['gpu'] = dict(renderer=renderer, blender=bpy.app.version_string,
                backend=gpu.platform.backend_type_get(), vendor=vendor_get())
            if 'llvmpipe' not in renderer.lower():
                raise RuntimeError('This report requires llvmpipe; actual renderer: '+renderer)
            initial = fresh_stack('inverse', table, False)
            start = perf_counter()
            program = initial.prepare_gpu()
            report['gpu_program_preparation_seconds'] = perf_counter()-start
            report['gpu_shader_creation_seconds'] = program.compile_seconds
            report['gpu_lookup_bytes'] = program.lookup_bytes
        write_report(output, report)
        descriptions = {
            'forward': 'One forward RGB LUT with mixed grade A and active tone adjustment.',
            'inverse': 'One inverse RGB LUT for mixed grade B and active tone adjustment.',
            'raw_stack': 'One nonmatching forward A→inverse B Stack LUT with a raw appearance handoff.'}
        for name in CASES:
            case = dict(description=descriptions[name], vertices=size**3, backends={})
            report['cases'][name] = case
            for backend in backends:
                versions = {mode: dict(trials=[]) for mode in ('off', 'on')}
                case['backends'][backend] = versions
                expected = {}
                # Initial results remain visible and are not folded into medians.
                for mode in ('off', 'on'):
                    values, record = trial(name, backend, mode == 'on', table, rgb, program)
                    versions[mode]['initial'] = record
                    expected[mode] = values
                    report['execution_order'].append(dict(workload=name, backend=backend, mode=mode, kind='initial'))
                    write_report(output, report)
                    print(f'{name} {backend} H-K {mode} initial: {record["total_seconds"]:.6f}s', flush=True)
                for repeat in range(repeats):
                    for mode in (('off', 'on') if repeat % 2 == 0 else ('on', 'off')):
                        values, record = trial(name, backend, mode == 'on', table, rgb, program)
                        record['trial'] = repeat+1
                        versions[mode]['trials'].append(record)
                        expected[mode] = values
                        report['execution_order'].append(dict(workload=name, backend=backend, mode=mode, kind='measured', trial=repeat+1))
                        write_report(output, report)
                        print(f'{name} {backend} H-K {mode} trial {repeat+1}/{repeats}: {record["total_seconds"]:.6f}s', flush=True)
                for mode in ('off', 'on'):
                    _, record = trial(name, backend, mode == 'on', table, rgb, program,
                                      instrumented=True, expected=expected[mode])
                    versions[mode]['instrumented'] = record
                    report['execution_order'].append(dict(workload=name, backend=backend, mode=mode, kind='instrumented'))
                    write_report(output, report)
                    print(f'{name} {backend} H-K {mode} instrumented: {record["total_seconds"]:.6f}s', flush=True)
                if name == 'raw_stack':
                    identical = same_bits(expected['off'], expected['on'])
                    case.setdefault('same_output_bits', {})[backend] = identical
                    if not identical:
                        raise ArithmeticError(f'{backend} raw Stack output differs between H-K off/on')
        combined = dict(description='Sum of the corresponding independently baked forward A and inverse B regular-grid LUTs. '
            'This represents two LUT constructions, not a composed RGB roundtrip.', vertices=2*size**3, backends={})
        for backend in backends:
            combined['backends'][backend] = {}
            for mode in ('off', 'on'):
                a, b = [report['cases'][name]['backends'][backend][mode] for name in ('forward', 'inverse')]
                combined['backends'][backend][mode] = dict(initial=sum_records(a['initial'], b['initial']),
                    trials=[sum_records(x, y) for x, y in zip(a['trials'], b['trials'])],
                    instrumented=sum_records(a['instrumented'], b['instrumented']))
        report['cases']['separate_rgb_luts'] = combined
        report.update(status='complete', completed_at=datetime.now().astimezone().isoformat(),
                      elapsed_seconds=perf_counter()-began)
        write_report(output, report)
        print(f'Reports: {output}/report.json and {output}/summary.md', flush=True)
        return report
    except BaseException as error:
        report.update(status='failed', elapsed_seconds=perf_counter()-began,
            failure=dict(type=type(error).__name__, message=str(error), traceback=traceback.format_exc()))
        write_report(output, report)
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, default=Path('buck-out/bake-time-breakdown'))
    parser.add_argument('--size', type=int, default=65)
    parser.add_argument('--repeats', type=int, default=3,
                        help='Uninstrumented trials after one separately reported initial full bake.')
    parser.add_argument('--cpu-only', action='store_true')
    args = parser.parse_args()
    if args.size < 2 or args.repeats < 1:
        parser.error('size >= 2 and repeats >= 1 required')
    run(args.output_dir, args.size, args.repeats, args.cpu_only)
