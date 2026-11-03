"""Image-sized native grading timings with an identical transport baseline.

Each cold measurement starts a fresh Python/Blender process. Timings include
the evaluation fixture and EXR transport; they are not isolated shader timings.
"""
import argparse
from functools import partial
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time
import numpy as np

from color_tools.kernel import prepare
from color_tools.kernel.boundary import prepare_boundary
from color_tools.kernel.graph import Graph, BuiltGrade, build_group, count_nodes
from . import cases, full_cases
from .evaluate import evidence_hashes

VARIANTS = ('passthrough', 'linear_tone', 'full')


def available_threads():
    if hasattr(os, 'sched_getaffinity'):
        return len(os.sched_getaffinity(0))
    return os.cpu_count() or 1


def thread_snapshot():
    names = []
    task_root = Path('/proc/self/task')
    if task_root.is_dir():
        for path in task_root.glob('*/comm'):
            try:
                names.append(path.read_text().strip())
            except OSError:
                pass
    return dict(process_thread_count=len(names), thread_names=sorted(set(names)),
                thread_name_counts={name:names.count(name) for name in sorted(set(names))},
                llvmpipe_worker_count=sum(name.startswith('llvmpipe-') for name in names))


def software_gpu_info():
    import bpy
    import gpu
    bpy.context.preferences.system.gpu_backend = 'OPENGL'
    gpu.init()
    info = dict(type=gpu.platform.backend_type_get(), renderer=gpu.platform.renderer_get(),
                vendor=gpu.platform.vendor_get(), version=gpu.platform.version_get(),
                compute_shaders=gpu.capabilities.compute_shader_support_get())
    info['software'] = any(name in info['renderer'].lower() for name in ('llvmpipe', 'softpipe'))
    if not info['software']:
        raise RuntimeError('software-gpu did not initialize a Mesa software renderer: '+repr(info))
    return info


def software_gpu_environment(env, xvfb, threads):
    root = Path(xvfb).resolve()
    libs = str(root/'usr/lib/x86_64-linux-gnu')
    return dict(env, LD_LIBRARY_PATH=libs+(':'+env['LD_LIBRARY_PATH'] if env.get('LD_LIBRARY_PATH') else ''),
                LIBGL_DRIVERS_PATH=str(root/'usr/lib/x86_64-linux-gnu/dri'),
                __GLX_VENDOR_LIBRARY_NAME='mesa', LIBGL_ALWAYS_SOFTWARE='1',
                GALLIUM_DRIVER='llvmpipe', LP_NUM_THREADS=str(threads),
                OPENBLAS_NUM_THREADS='1', OMP_NUM_THREADS=str(threads))


def passthrough_group(prepared, tree_type):
    """Match every diagnostic transport channel without any grading work."""
    import bpy
    tree = bpy.data.node_groups.new('Benchmark transport baseline', tree_type)
    graph = Graph(tree, prepared)
    tree.interface.new_socket(name='Color', in_out='INPUT', socket_type='NodeSocketColor')
    if tree_type == 'ShaderNodeTree':
        tree.interface.new_socket(name='Alpha', in_out='INPUT', socket_type='NodeSocketFloat')
    tree.interface.new_socket(name='Color', in_out='OUTPUT', socket_type='NodeSocketColor')
    for name in ('Alpha', 'Decode Valid', 'Pole Margin', 'Saturated'):
        tree.interface.new_socket(name=name, in_out='OUTPUT', socket_type='NodeSocketFloat')
    source, output = tree.nodes.new('NodeGroupInput'), tree.nodes.new('NodeGroupOutput')
    if tree_type == 'CompositorNodeTree':
        separate = tree.nodes.new('CompositorNodeSeparateColor')
        separate.mode = 'RGB'
        graph.connect(source.outputs['Color'], separate.inputs['Image'])
        alpha = separate.outputs['Alpha']
    else:
        alpha = source.outputs['Alpha']
    for value, name in ((source.outputs['Color'], 'Color'), (alpha, 'Alpha'),
                        (1., 'Decode Valid'), (400., 'Pole Margin'), (0., 'Saturated')):
        graph.connect(value, output.inputs[name])
    return BuiltGrade(tree, (), (), prepared, count_nodes(tree))


def _summary(values):
    values = np.asarray(values, dtype=float)
    median = float(np.median(values))
    return dict(count=len(values), median=median, minimum=float(np.min(values)),
                maximum=float(np.max(values)), mean=float(np.mean(values)),
                standard_deviation=float(np.std(values)),
                median_absolute_deviation=float(np.median(abs(values-median))),
                p10=float(np.percentile(values, 10)), p90=float(np.percentile(values, 90)))


def worker(output, variant, context, size, warm_runs, ordinal, backend='cpu', threads=None):
    import bpy
    from .native import NativeFixture
    gpu_info = software_gpu_info() if backend == 'software-gpu' else None
    values = cases.rgba(size*size)
    _, linear, tone = next(row for row in cases.grades() if row[0] == 'combined')
    boundary_loading = 0.
    if variant == 'full':
        context_parameters = prepare()
        start = time.perf_counter()
        boundary = prepare_boundary(context_parameters.fl, context_parameters.aw, context_parameters.gamma)
        boundary_loading = time.perf_counter()-start
    start = time.perf_counter()
    if variant == 'full':
        prepared, builder = prepare(linear, tone, color=full_cases.all_active(), boundary=boundary), build_group
    elif variant == 'linear_tone':
        prepared, builder = prepare(linear, tone), partial(build_group, export=False)
    else:
        prepared, builder = prepare(), passthrough_group
    preparation = time.perf_counter()-start
    start = time.perf_counter()
    engine = 'BLENDER_EEVEE' if backend == 'software-gpu' and context == 'shader' else 'CYCLES'
    device = 'GPU' if backend == 'software-gpu' else 'CPU'
    fixture = NativeFixture(prepared, values, context, engine=engine, device=device,
                            threads=threads, builder=builder)
    # Keep benchmark transport independent of graded-output entropy. The
    # acceptance fixture retains ZIP; this local configuration changes no
    # numerical values or runtime/evaluator source.
    fixture.scene.render.image_settings.exr_codec = 'NONE'
    file_outputs = [node for node in fixture.comp.nodes
                    if node.bl_idname == 'CompositorNodeOutputFile']
    for node in file_outputs:
        node.format.exr_codec = 'NONE'
    construction = time.perf_counter()-start
    wall, render, hashes, saturated, transport_bytes = [], [], [], [], []
    transport_rgb_errors, transport_alpha_errors = [], []
    try:
        for run in range(warm_runs+1):
            # Republish identical pixels so warm compositor runs cannot be
            # satisfied solely by an unchanged-image result cache. This host
            # publication is outside the timed render/readback interval.
            fixture.input_image.pixels.foreach_set(values.ravel())
            fixture.input_image.update()
            start = time.perf_counter()
            actual = fixture.render()
            wall.append(time.perf_counter()-start)
            render.append(actual['seconds'])
            if not all(np.isfinite(actual[name]).all() for name in ('rgb', 'alpha', 'valid', 'margin', 'saturated')):
                raise AssertionError('Benchmark encountered nonfinite native output')
            alpha_error = float(np.max(abs(actual['alpha']-values[:, 3])/(1+abs(values[:, 3]))))
            rgb_error = (float(np.max(abs(actual['rgb']-values[:, :3])/
                                      (1+np.max(abs(values[:, :3]), axis=-1, keepdims=True))))
                         if variant == 'passthrough' else None)
            transport_alpha_errors.append(alpha_error)
            if rgb_error is not None:
                transport_rgb_errors.append(rgb_error)
            if backend == 'cpu':
                if not np.array_equal(actual['alpha'], values[:, 3]):
                    raise AssertionError('Benchmark transport changed alpha')
                if variant == 'passthrough' and not np.array_equal(actual['rgb'], values[:, :3]):
                    raise AssertionError('Benchmark baseline transport changed input pixels')
            else:
                if alpha_error > 1e-4:
                    raise AssertionError(f'GPU transport alpha error {alpha_error} exceeds 1e-4')
                if variant == 'passthrough' and rgb_error > 1e-4:
                    raise AssertionError(f'GPU passthrough RGB error {rgb_error} exceeds 1e-4')
            hashes.append(hashlib.sha256(actual['rgb'].tobytes()).hexdigest())
            saturated.append(int(np.count_nonzero(actual['saturated'] > .5)))
            transport_bytes.append(sum(path.stat().st_size for path in Path(fixture.directory.name).glob('*.exr')))
        result = dict(variant=variant, context=context, process_index=ordinal,
                      process_id=os.getpid(), blender=bpy.app.version_string,
                      backend=backend, threads=threads, engine=engine,
                      compositor_device=device, render_backend=gpu_info,
                      native_threads=fixture.scene.render.threads,
                      native_threads_mode=fixture.scene.render.threads_mode,
                      worker_environment={key:os.environ.get(key) for key in
                          ('DISPLAY', 'OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'LP_NUM_THREADS',
                           'LIBGL_ALWAYS_SOFTWARE', 'GALLIUM_DRIVER', 'LIBGL_DRIVERS_PATH')},
                      process_threads=thread_snapshot(),
                      web_representation=('1d' if fixture.built.prepared.color.web_active else 'none'),
                      size=[size, size], pixels=size*size,
                      pixels_sha256=hashlib.sha256(values.tobytes()).hexdigest(),
                      boundary_loading_seconds=boundary_loading,
                      preparation_seconds=preparation, construction_seconds=construction,
                      initialization_timings=fixture.initialization_timings,
                      node_budget_passed=(actual['stats']['expanded_nodes']<1000 if variant=='full'
                                          else actual['stats']['expanded_nodes']<=300),
                      transport=dict(file_format='OPEN_EXR', exr_codec='NONE', color_depth='32',
                                     color_mode='RGBA', output_files=len(file_outputs)),
                      transport_bytes_per_run=transport_bytes,
                      max_normalized_rgb_transport_error=(max(transport_rgb_errors) if transport_rgb_errors else None),
                      max_normalized_alpha_transport_error=max(transport_alpha_errors),
                      normalized_rgb_transport_error_per_run=transport_rgb_errors,
                      normalized_alpha_transport_error_per_run=transport_alpha_errors,
                      gpu_transport_accuracy_limit=(1e-4 if backend == 'software-gpu' else None),
                      cold_fixture_seconds=wall[0], warm_fixture_seconds=wall[1:],
                      cold_render_seconds=render[0], warm_render_seconds=render[1:],
                      stats=actual['stats'], saturated_samples=saturated,
                      deterministic_output=len(set(hashes)) == 1, output_sha256=hashes,
                      warm_fixture_summary=_summary(wall[1:]))
    finally:
        fixture.close()
    output.write_text(json.dumps(result, indent=2, allow_nan=False)+'\n')


def run(output_dir, *, size=1024, processes=3, warm_runs=7,
        contexts=('shader', 'compositor'), variants=VARIANTS,
        backend='cpu', threads=None, xvfb=None):
    identities = evidence_hashes()
    benchmark_hash = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    work = output_dir/'processes'
    work.mkdir(exist_ok=True)
    if backend == 'software-gpu':
        if xvfb is None:
            raise ValueError('The software-gpu backend requires the pinned --xvfb fixture')
        threads = threads or available_threads()
    script = ('import sys; sys.path[:]=' + repr(sys.path) + '; '
              'from tools.perceptual_grade.reports.benchmark import main; main(sys.argv[1:])')
    env = dict(os.environ, OPENBLAS_NUM_THREADS='1', OMP_NUM_THREADS='1')
    runs = []
    # Rotate variant order between repetitions to expose/order-average cache
    # and host-load effects; each individual measurement still has a new process.
    for context in contexts:
        for repeat in range(processes):
            order = tuple(variants[repeat % len(variants):])+tuple(variants[:repeat % len(variants)])
            for variant in order:
                stem = f'{context}-{variant}-{repeat}'
                output = work/(stem+'.json')
                command = [sys.executable, '-c', script, '--worker', '--output-dir', str(output_dir.resolve()),
                           '--worker-output', str(output.resolve()), '--variant', variant, '--context', context,
                           '--size', str(size), '--warm-runs', str(warm_runs), '--ordinal', str(repeat),
                           '--backend', backend]
                if threads is not None:
                    command.extend(['--threads', str(threads)])
                start = time.perf_counter()
                if backend == 'software-gpu':
                    from .gpu_report import display_environment
                    display_dir = work/(stem+'-display')
                    display_dir.mkdir(exist_ok=True)
                    with display_environment(xvfb, display_dir) as display_env:
                        worker_env = software_gpu_environment(display_env, xvfb, threads)
                        with (work/(stem+'.log')).open('w') as log:
                            process = subprocess.run(command, env=worker_env, stdout=log,
                                                     stderr=subprocess.STDOUT, timeout=3600)
                else:
                    with (work/(stem+'.log')).open('w') as log:
                        process = subprocess.run(command, env=env, stdout=log, stderr=subprocess.STDOUT,
                                                 timeout=3600)
                if process.returncode:
                    raise RuntimeError(f'Benchmark worker failed ({process.returncode}); see {work/(stem+".log")}')
                result = json.loads(output.read_text())
                result['process_wall_seconds'] = time.perf_counter()-start
                runs.append(result)
                print(f"{context} {variant} process {repeat+1}/{processes}: "
                      f"cold fixture {result['cold_fixture_seconds']:.4f}s, "
                      f"warm median {result['warm_fixture_summary']['median']:.4f}s", flush=True)
    groups = []
    for context in contexts:
        for variant in variants:
            selected = [row for row in runs if row['context'] == context and row['variant'] == variant]
            groups.append(dict(context=context, variant=variant,
                cold_fixture=_summary([row['cold_fixture_seconds'] for row in selected]),
                warm_fixture=_summary([value for row in selected for value in row['warm_fixture_seconds']]),
                warm_render=_summary([value for row in selected for value in row['warm_render_seconds']]),
                per_process_warm_median=_summary([row['warm_fixture_summary']['median'] for row in selected]),
                boundary_loading=_summary([row['boundary_loading_seconds'] for row in selected]),
                preparation=_summary([row['preparation_seconds'] for row in selected]),
                construction=_summary([row['construction_seconds'] for row in selected]),
                max_normalized_rgb_transport_error=(max(row['max_normalized_rgb_transport_error'] for row in selected)
                                                    if variant == 'passthrough' else None),
                max_normalized_alpha_transport_error=max(row['max_normalized_alpha_transport_error'] for row in selected),
                render_backends=[json.loads(value) for value in sorted({json.dumps(row['render_backend'], sort_keys=True)
                                                                      for row in selected})],
                engine=sorted({row['engine'] for row in selected}),
                compositor_devices=sorted({row['compositor_device'] for row in selected}),
                native_threads=sorted({row['native_threads'] for row in selected}),
                initialization={name: _summary([row['initialization_timings'][name] for row in selected])
                                for name in selected[0]['initialization_timings']},
                node_budget_passed=all(row['node_budget_passed'] for row in selected),
                web_representations=sorted({row['web_representation'] for row in selected}),
                expanded_nodes=sorted({row['stats']['expanded_nodes'] for row in selected}),
                texture_bytes=sorted({row['stats']['texture_bytes'] for row in selected})))
    sources_stable = (identities == evidence_hashes()
                      and benchmark_hash == hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    report = dict(schema=2, **identities, benchmark_sha256=benchmark_hash,
                  sources_stable_during_run=sources_stable,
                  node_budget_enforced_during_construction=False,
                  node_budget_passed=all(row['node_budget_passed'] for row in runs),
                  platform=platform.platform(), processor=platform.processor(), cpu_count=os.cpu_count(),
                  available_cpu_count=available_threads(),
                  cpu_affinity=(sorted(os.sched_getaffinity(0)) if hasattr(os, 'sched_getaffinity') else None),
                  backend=backend, threads=threads,
                  contexts=contexts, variants=variants,
                  xvfb_fixture=str(Path(xvfb).resolve()) if xvfb is not None else None,
                  size=[size, size], cold_processes_per_case=processes, warm_runs_per_process=warm_runs,
                  transport=dict(file_format='OPEN_EXR', exr_codec='NONE', color_depth='32', color_mode='RGBA'),
                  timing_contract='Fixture wall time includes render, AOV/compositor work, uncompressed float32 '
                                  'RGBA EXR writes and readback. Benchmark-only NONE compression removes graded-output '
                                  'entropy from compression cost; per-run file bytes are recorded to verify fixed transport size. '
                                  'Render time excludes Python EXR readback. Identical input pixels are republished '
                                  'before each timed run to invalidate image evaluation; publication itself is untimed. '
                                  'Neither metric isolates node evaluation. Boundary loading is separate from '
                                  'grade-dependent preparation. Initialization phases separately record scene/input, '
                                  'grade graph (including image creation/packing), and output fixture setup. '
                                  'The legacy construction field includes all fixture setup. These costs are not drag latency; '
                                  'use gui_drag for an initialized-tree update. Boundary geometry generation belongs to its Buck build target.',
                  comparison_contract='Same deterministic pixels and NativeFixture for passthrough, raw Linear+Tone '
                                      'and full all-active guarded grading with 1D Web. Oversized full graphs are '
                                      'temporarily buildable but the original <1000 node acceptance remains reported. '
                                      'The variants measure different work; no speedup '
                                      'or isolated shader-cost claim follows from subtracting the baseline.',
                  accuracy_scope='Timing diagnostic only. Finite outputs are required. CPU alpha/passthrough RGB '
                                 'remain bit-exact; software-GPU alpha/passthrough RGB use a 1e-4 maximum normalized '
                                 'transport-error limit and retain their measured errors. Graded RGB accuracy is not '
                                 'independently certified by this benchmark.',
                  groups=groups, runs=runs)
    (output_dir/'report.json').write_text(json.dumps(report, indent=2, allow_nan=False)+'\n')
    lines = ['# Native image-sized benchmark', '',
             f'{size} × {size} pixels; {processes} fresh processes per case; {warm_runs} warm runs per process.',
             f"Backend: `{backend}`; requested native/software-renderer threads: {threads if threads is not None else 'Blender automatic'}.",
             report['timing_contract'], report['comparison_contract'], report['accuracy_scope'], '',
             '| Context | Work | Web fields | Cold median (s) | Warm median (s) | Warm MAD (s) | Nodes | Texture bytes |',
             '|---|---|---|---:|---:|---:|---:|---:|']
    for row in groups:
        lines.append(f"| {row['context']} | {row['variant']} | {','.join(row['web_representations'])} | {row['cold_fixture']['median']:.5f} | "
                     f"{row['warm_fixture']['median']:.5f} | {row['warm_fixture']['median_absolute_deviation']:.5f} | "
                     f"{row['expanded_nodes']} | {row['texture_bytes']} |")
    lines += ['', '| Context | Work | Boundary load (s) | Initial preparation (s) | Scene/input (s) | Grade graph (s) | Output fixture (s) | Node budget |',
              '|---|---|---:|---:|---:|---:|---:|---|']
    for row in groups:
        lines.append(f"| {row['context']} | {row['variant']} | {row['boundary_loading']['median']:.5f} | "
                     f"{row['preparation']['median']:.5f} | "
                     f"{row['initialization']['scene_and_input_seconds']['median']:.5f} | "
                     f"{row['initialization']['grade_graph_seconds']['median']:.5f} | "
                     f"{row['initialization']['output_fixture_seconds']['median']:.5f} | "
                     f"{'PASS' if row['node_budget_passed'] else 'FAIL'} |")
    lines += ['', 'JSON includes individual process/run timings, percentiles, variability, preparation/build costs, '
              'source/pixel hashes, saturation counts and output determinism. Accuracy acceptance is separate.', '']
    (output_dir/'report.md').write_text('\n'.join(lines))
    if not sources_stable:
        raise RuntimeError('Benchmark sources changed during the run; results cannot certify one source snapshot')
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', required=True, type=Path)
    parser.add_argument('--size', type=int, default=1024)
    parser.add_argument('--processes', type=int, default=3)
    parser.add_argument('--warm-runs', '--warmruns', type=int, default=7)
    parser.add_argument('--contexts', nargs='+', choices=('shader', 'compositor'), default=['shader', 'compositor'])
    parser.add_argument('--variants', nargs='+', choices=VARIANTS, default=list(VARIANTS))
    parser.add_argument('--backend', choices=('cpu', 'software-gpu'), default='cpu')
    parser.add_argument('--threads', type=int)
    parser.add_argument('--xvfb', type=Path)
    parser.add_argument('--worker', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--worker-output', type=Path, help=argparse.SUPPRESS)
    parser.add_argument('--variant', choices=VARIANTS, help=argparse.SUPPRESS)
    parser.add_argument('--context', choices=('shader', 'compositor'), help=argparse.SUPPRESS)
    parser.add_argument('--ordinal', type=int, default=0, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.size < 16 or args.processes < 1 or args.warm_runs < 1 or (args.threads is not None and args.threads < 1):
        parser.error('Require size >= 16, processes >= 1, warm runs >= 1 and positive supplied threads')
    if args.worker:
        worker(args.worker_output, args.variant, args.context, args.size, args.warm_runs,
               args.ordinal, backend=args.backend, threads=args.threads)
    else:
        run(args.output_dir, size=args.size, processes=args.processes, warm_runs=args.warm_runs,
            contexts=tuple(args.contexts), variants=tuple(args.variants), backend=args.backend,
            threads=args.threads, xvfb=args.xvfb)


if __name__ == '__main__':
    main()
