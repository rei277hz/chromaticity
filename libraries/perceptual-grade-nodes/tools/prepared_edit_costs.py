"""Measure grading edits on an already initialized persistent native tree.

This is the native counterpart of the optional displayed-preview benchmark.
It does not claim GUI or physical-display latency: initialization is separated,
then each edit includes immutable preparation, persistent image upload/packing/
readback, binding publication, native evaluation and EXR readback.
"""
from dataclasses import replace
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import statistics
import subprocess
import sys
import time
import numpy as np

from color_tools.perceptual_grade_nodes import Settings, prepare, prepare_update
from color_tools.perceptual_grade_nodes.boundary import prepare_boundary
from color_tools.perceptual_grade_nodes.persistent import build_persistent
from . import full_cases
from .evaluate import evidence_hashes
from .native import NativeFixture


def stats(values):
    ordered = sorted(values)
    if not ordered:
        return None
    return dict(count=len(values), minimum=min(ordered),
                median=statistics.median(ordered),
                maximum=max(ordered))


PHASES = ('preparation_seconds', 'apply_wall_seconds', 'evaluation_seconds',
          'native_readback_seconds', 'fixture_seconds', 'end_to_end_seconds')


def summarize_rows(rows):
    """Keep entry transitions separate from edits within the same family."""
    groups = []
    for context, edit in dict.fromkeys((row['context'], row['edit']) for row in rows):
        selected = [row for row in rows if (row['context'], row['edit']) == (context, edit)]
        entries = [row for row in selected if row['scenario_entry']]
        repeated = [row for row in selected if not row['scenario_entry']]
        phases = lambda values: {name: stats([row[name] for row in values]) for name in PHASES}
        groups.append(dict(context=context, edit=edit, samples=len(selected),
            phases=phases(selected), scenario_entry=phases(entries), repeated_updates=phases(repeated),
            scenario_entry_count=len(entries), repeated_update_count=len(repeated),
            apply={name: stats([row['apply'][name] for row in selected]) for name in
                   ('image_upload', 'image_pack', 'image_readback', 'bindings', 'readback_commit', 'total')},
            changed_fields=sorted(set(field for row in selected for field in row['changed_fields'])),
            changed_bindings=sorted(set(row['changed_bindings'] for row in selected))))
    return groups


def write_report(output_dir, report):
    """Summarize raw timings without replacing their measurement identity."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    width = math.ceil(math.sqrt(report['samples']))
    height = math.ceil(report['samples']/width)
    report['schema'] = 2
    report['groups'] = summarize_rows(report['rows'])
    report['image_size'] = [width, height]
    report['summary_tool_sha256'] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    report['scope'] = dict(
        numerical_checks='Finite RGB and unchanged native object identities/dimensions only; no reference-accuracy certification.',
        input='Deterministic signed/HDR sample buffer; not an image-sized performance benchmark.',
        summaries='phases includes all rows; scenario_entry is ordinal 0; repeated_updates excludes ordinal 0.',
        entries='Entry transitions follow the preceding edit family and may be no-ops; they are not necessarily first activation.',
        all_active='Exposure changes with fixed all-active Color and Tone settings; the entry activates the full grade.',
        initialization='Per-context fixture construction is retained on raw rows; base preparation, boundary loading and the warm render are untimed.')
    (output_dir/'report.json').write_text(json.dumps(report, indent=2, allow_nan=False)+'\n')
    def milliseconds(value):
        return '—' if value is None else f"{value['median']*1000:.3f} ms"
    lines = ['# Prepared persistent-tree grading edit diagnostic', '', report['contract'], '',
        f"Backend: `{report.get('backend', 'cpu')}`; requested threads: {report.get('threads', 'legacy default')}. "
        'Actual renderer, device, Blender thread setting and process thread names are retained in JSON.', '',
        f"Scope: **{width} × {height} pixels**, {report['samples']} deterministic inputs, "
        f"{report['repeats']} rows per edit family/context. This small fixture diagnoses host edits and native transport; "
        'the separate 1024×1024 GUI report measures displayed-preview performance.', '',
        'Scenario entry is ordinal 0 and follows the previous edit family. Repeated updates exclude that entry. '
        '`all_active` denotes exposure changes with fixed all-active Color and Tone settings.', '',
        '| Context | Edit | Rows: entry / repeated | Entry end-to-end | Repeated end-to-end median | All-row end-to-end median |',
        '|---|---|---:|---:|---:|---:|']
    for group in report['groups']:
        lines.append(f"| {group['context']} | {group['edit']} | "
            f"{group['scenario_entry_count']} / {group['repeated_update_count']} | "
            f"{milliseconds(group['scenario_entry']['end_to_end_seconds'])} | "
            f"{milliseconds(group['repeated_updates']['end_to_end_seconds'])} | "
            f"{milliseconds(group['phases']['end_to_end_seconds'])} |")
    lines += ['', '| Context | Edit | Preparation median (all rows) | Apply median (all rows) | Evaluation median (all rows) | Readback median (all rows) |',
              '|---|---|---:|---:|---:|---:|']
    for group in report['groups']:
        phase = group['phases']
        lines.append(f"| {group['context']} | {group['edit']} | "
            f"{milliseconds(phase['preparation_seconds'])} | {milliseconds(group['apply']['total'])} | "
            f"{milliseconds(phase['evaluation_seconds'])} | {milliseconds(phase['native_readback_seconds'])} |")
    lines += ['', 'End-to-end is a separately measured wall interval covering preparation, persistent apply and native fixture evaluation/readback. '
        'Phase medians must not be added. GUI event scheduling, preview upload, framebuffer draw and physical presentation are excluded. '
        'The runtime checks finite RGB and preserved native identities/dimensions; this timing diagnostic does not certify independent-reference accuracy.', '',
        'JSON preserves the original `tool_sha256` measurement identity and adds `summary_tool_sha256` for the report generator. Raw timing rows are unchanged.', '']
    (output_dir/'report.md').write_text('\n'.join(lines))


def edit_settings(name, index):
    reset = Settings()
    if name == 'exposure':
        return replace(reset, linear=replace(reset.linear, exposure=.25 + .1*index))
    if name == 'tone_fit':
        tone = replace(reset.tone, fit=-.5 + .5*index)
        return replace(reset, tone=tone)
    if name == 'web_chroma':
        value = .1 + .05*index
        web = replace(reset.color.web, log_chroma=((value,)*6,)*4)
        return replace(reset, color=replace(reset.color, web=web))
    if name == 'web_scale':
        value = .1 + .05*index
        web = replace(reset.color.web, log_scale=((value,)*6,)*4)
        return replace(reset, color=replace(reset.color, web=web))
    if name == 'all_active':
        _, linear, tone, color = next(row for row in full_cases.grades() if row[0] == 'all_active')
        return Settings(linear=replace(linear, exposure=linear.exposure+.05*index),
                        tone=tone, color=color)
    raise ValueError(name)


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


def run(output_dir, *, repeats=3, samples=256, backend='cpu', threads=None, xvfb=None):
    if backend == 'software-gpu' and threads is None:
        threads = available_threads()
    identities = evidence_hashes()
    tool_sha = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    gpu_info = software_gpu_info() if backend == 'software-gpu' else None
    context = prepare()
    boundary = prepare_boundary(context.fl, context.aw, context.gamma)
    base = prepare(full_fields=True, boundary=boundary)
    rows = []
    for context in ('shader', 'compositor'):
        values = full_cases.rgba(count=samples)
        fixture_start = time.perf_counter()
        engine = 'BLENDER_EEVEE' if backend == 'software-gpu' and context == 'shader' else 'CYCLES'
        device = 'GPU' if backend == 'software-gpu' else 'CPU'
        fixture = NativeFixture(base, values, context, engine=engine, device=device,
                                threads=threads, builder=build_persistent)
        initialization = dict(fixture.initialization_timings)
        initialization['wall_seconds'] = time.perf_counter()-fixture_start
        try:
            fixture.render()  # Warm the prepared tree before edit measurements.
            inventory = lambda: (fixture.built.tree.as_pointer(),
                tuple(node.as_pointer() for node in fixture.built.tree.nodes),
                tuple((image.as_pointer(), tuple(image.size)) for image in fixture.built.images))
            original_inventory = inventory()
            previous = base
            for name in ('exposure', 'tone_fit', 'web_chroma', 'web_scale', 'all_active'):
                for ordinal in range(repeats):
                    settings = edit_settings(name, ordinal+1)
                    accepted = time.perf_counter()
                    start = time.perf_counter()
                    prepared = prepare_update(settings, previous)
                    preparation = time.perf_counter()-start
                    start = time.perf_counter()
                    receipt = fixture.built.apply(prepared, expected_revision=fixture.built.revision)
                    apply_wall = time.perf_counter()-start
                    rendered = fixture.render()
                    end_to_end = time.perf_counter()-accepted
                    if not np.isfinite(rendered['rgb']).all():
                        raise RuntimeError('Native edit produced nonfinite RGB')
                    if inventory() != original_inventory:
                        raise RuntimeError('Native tree/node/image identities or dimensions changed')
                    rows.append(dict(context=context, edit=name, ordinal=ordinal,
                        preparation_seconds=preparation, apply_wall_seconds=apply_wall,
                        apply=receipt['phase_seconds'], evaluation_seconds=rendered['seconds'],
                        native_readback_seconds=rendered['readback_seconds'],
                        fixture_seconds=rendered['fixture_seconds'], end_to_end_seconds=end_to_end,
                        changed_fields=list(receipt['changed_fields']),
                        changed_bindings=receipt['changed_bindings'], revision=receipt['revision'],
                        resource_inventory_preserved=True, scenario_entry=ordinal == 0,
                        engine=engine, compositor_device=device,
                        native_threads=fixture.scene.render.threads,
                        native_threads_mode=fixture.scene.render.threads_mode,
                        process_threads=thread_snapshot(),
                        initialization=initialization))
                    previous = prepared
        finally:
            fixture.close()
    stable = identities == evidence_hashes() and tool_sha == hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    report = dict(schema=1, **identities, tool_sha256=tool_sha,
        contract='Prepared persistent tree edit -> immutable preparation -> native image upload/packing/readback '
                 '-> binding publication -> native evaluation -> EXR readback. Initialization and optional GUI '
                 'preview/display are excluded from edit rows.',
        backend=backend, threads=threads, available_cpu_count=available_threads(),
        xvfb_fixture=str(Path(xvfb).resolve()) if xvfb is not None else None,
        blender=fixture.bpy.app.version_string,
        blender_build=fixture.bpy.app.build_hash.decode(),
        cpu_affinity=(sorted(os.sched_getaffinity(0)) if hasattr(os, 'sched_getaffinity') else None),
        render_backend=gpu_info,
        worker_environment={key:os.environ.get(key) for key in
                            ('DISPLAY', 'OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'LP_NUM_THREADS',
                             'LIBGL_ALWAYS_SOFTWARE', 'GALLIUM_DRIVER', 'LIBGL_DRIVERS_PATH')},
        sources_stable_during_run=stable, contexts=('shader','compositor'), repeats=repeats,
        samples=samples, initialization='Per-context initialization is retained on every raw row.',
        rows=rows)
    write_report(output_dir, report)
    if not stable:
        raise RuntimeError('Sources changed during measurement')
    return report


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--repeats', type=int, default=3)
    parser.add_argument('--samples', type=int, default=256)
    parser.add_argument('--backend', choices=('cpu', 'software-gpu'), default='cpu')
    parser.add_argument('--threads', type=int)
    parser.add_argument('--xvfb', type=Path)
    parser.add_argument('--worker', action='store_true', help=argparse.SUPPRESS)
    args=parser.parse_args(argv)
    if args.repeats < 1 or args.samples < 4 or (args.threads is not None and args.threads < 1):
        parser.error('repeats must be positive, samples at least four, and supplied threads positive')
    if args.backend == 'software-gpu' and not args.worker:
        if args.xvfb is None:
            parser.error('software-gpu requires the pinned --xvfb fixture')
        from .gpu_report import display_environment
        args.output_dir.mkdir(parents=True, exist_ok=True)
        script = ('import sys; sys.path[:]=' + repr(sys.path) + '; '
                  'from tools.perceptual_grade_nodes.prepared_edit_costs import main; main(sys.argv[1:])')
        threads = args.threads or available_threads()
        with display_environment(args.xvfb, args.output_dir) as env:
            env = software_gpu_environment(env, args.xvfb, threads)
            command = [sys.executable, '-c', script, '--worker', '--backend', args.backend,
                       '--threads', str(threads), '--output-dir', str(args.output_dir.resolve()),
                       '--repeats', str(args.repeats), '--samples', str(args.samples),
                       '--xvfb', str(args.xvfb.resolve())]
            with (args.output_dir/'native.log').open('w') as log:
                process = subprocess.run(command, env=env, stdout=log, stderr=subprocess.STDOUT, timeout=3600)
            if process.returncode:
                raise RuntimeError(f'Prepared edit worker failed ({process.returncode}); see {args.output_dir}/native.log')
        return
    run(args.output_dir, repeats=args.repeats, samples=args.samples, backend=args.backend,
        threads=args.threads, xvfb=args.xvfb)


if __name__ == '__main__':
    main()
