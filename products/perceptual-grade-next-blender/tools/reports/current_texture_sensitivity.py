"""Measure smaller textures against the current Compact-only persistent tree.

One immutable layout per worker: its tree and images survive the complete
control corpus through persistent apply. Accuracy-run durations are not timing
evidence. No runtime layout or admission policy is changed.
"""
import argparse
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import numpy as np

from color_tools.kernel import prepare
from color_tools.kernel.boundary import prepare_boundary
from color_tools.template_build.persistent import build_persistent
from . import cases, full_cases, oracle, current_texture_candidates as candidates
from .evaluate import assess, evidence_hashes
from .hdr_metrics import HDRDisplay
from .hdr_report import _inventory, _payloads
from .gpu_report import _json_values
from .native import NativeFixture


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def identity():
    return dict(sources=evidence_hashes(), diagnostics={
        name: digest((Path(__file__).parent.parent / name) if name == 'build_boundary.py'
                     else Path(__file__).with_name(name)) for name in (
            'current_texture_sensitivity.py', 'current_texture_candidates.py',
            'hdr_metrics.py', 'hdr_report.py', 'gpu_report.py', 'native.py',
            'build_boundary.py', 'prepared_edit_costs.py')})


def assessment(actual, expected, values):
    result = assess(actual, expected, values)
    native = actual['rgb'] @ np.linalg.inv(expected['to_scene']).T
    magnitude = np.maximum(1., np.max(abs(native), axis=-1))
    violation = np.maximum(np.max(-native, axis=-1), np.max(native-1024., axis=-1))
    containment = float(np.max(np.maximum(0., violation)/magnitude, initial=0))
    finite = all(np.isfinite(actual[key]).all() for key in ('rgb','alpha','valid','margin','saturated'))
    return dict(scene_linear=result, containment_max_normalized=containment, finite=finite,
                final_rgb_passed=bool(result['passed'] and finite and containment <= 8e-6))


def run(output_dir, *, variant='baseline', space='Linear Rec.709', context='compositor',
        selected_cases=None, backend='cpu', threads=1, cpus=None):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    start_identity = identity()
    specs = candidates.selection()
    spec = None if variant == 'baseline' else next((s for s in specs if s['id'] == variant), None)
    if variant != 'baseline' and spec is None:
        raise ValueError('Unknown smaller-only candidate: '+variant)
    corpus = list(full_cases.grades()) + list(full_cases.ui_boundaries())
    if selected_cases:
        corpus = [row for row in corpus if row[0] in selected_cases]
        if {row[0] for row in corpus} != set(selected_cases):
            raise ValueError('Unknown or duplicate requested control cases')
    values = full_cases.rgba(space, 1024)
    display = HDRDisplay((space,))
    gpu_info = None
    if backend == 'software-gpu':
        from .prepared_edit_costs import software_gpu_info
        gpu_info = software_gpu_info()
    if cpus:
        for tid in Path('/proc/self/task').iterdir():
            try:
                os.sched_setaffinity(int(tid.name), set(cpus))
            except ProcessLookupError:
                pass
    initial_base = prepare(space=space, full_fields=True)
    boundary = prepare_boundary(initial_base.fl, initial_base.aw, initial_base.gamma)
    initial_base = prepare(space=space, full_fields=True, boundary=boundary)
    cache = {}

    def reduced(base):
        return (base, None) if spec is None else candidates.candidate(base, spec, cache)

    initial, initial_metadata = reduced(initial_base)
    engine = 'BLENDER_EEVEE' if backend == 'software-gpu' and context == 'shader' else 'CYCLES'
    fixture = NativeFixture(initial, values, context, builder=build_persistent, engine=engine,
                            device='GPU' if backend == 'software-gpu' else 'CPU',
                            precision='FULL', threads=threads)
    rows, arrays = [], {'inputs': values}
    node_ids = tuple(n.as_pointer() for n in fixture.built.tree.nodes)
    image_ids = tuple(i.as_pointer() for i in fixture.built.images)
    inventory = _inventory(fixture, initial)
    if set(inventory) != set(_payloads(initial)):
        raise AssertionError('Initial native inventory does not contain every prepared texture')
    total_bytes = sum(item['bytes'] for item in inventory.values())
    execution = dict(backend=backend, threads=threads, engine=fixture.scene.render.engine,
        compositor_device=fixture.scene.render.compositor_device,
        compositor_precision=fixture.scene.render.compositor_precision,
        native_threads=fixture.scene.render.threads, native_threads_mode=fixture.scene.render.threads_mode,
        render_backend=gpu_info, requested_cpu_affinity=cpus,
        initial_expanded_nodes=fixture.built.stats.expanded_nodes)
    previous_base = initial_base
    try:
        for name, linear, tone, color in corpus:
            base = prepare(linear, tone, space, color=color, boundary=boundary,
                           full_fields=True, previous=previous_base)
            candidates.baseline_layout(base)
            prepared, metadata = reduced(base)
            applied = fixture.built.apply(prepared, expected_revision=fixture.built.revision)
            if tuple(n.as_pointer() for n in fixture.built.tree.nodes) != node_ids:
                raise AssertionError('A control edit replaced native nodes')
            if tuple(i.as_pointer() for i in fixture.built.images) != image_ids:
                raise AssertionError('A control edit replaced native images')
            actual = fixture.render()
            expected = oracle.evaluate_full(values[:,:3], linear, tone, color, space)
            reference_codes = display.codes(expected['rgb'], space)
            measured = assessment(actual, expected, values)
            native_codes = (display.codes(actual['rgb'], space) if measured['finite'] else
                            np.full_like(reference_codes, np.nan))
            for key in ('rgb','alpha','valid','margin','saturated'):
                arrays[name+'__'+key] = actual[key]
            arrays[name+'__reference_codes'] = reference_codes
            arrays[name+'__codes'] = native_codes
            rows.append(dict(case=name, space=space, context=context, variant=variant,
                status='measured' if measured['finite'] else 'nonfinite', **measured,
                texture_metadata=metadata, payload_bytes=total_bytes, image_count=len(image_ids),
                settings=dict(linear=asdict(linear), tone=asdict(tone), color=asdict(color))))
            previous_base = base
            print(variant, name, space, context, measured['final_rgb_passed'], flush=True)
    finally:
        fixture.close()
    raw = output_dir/'pixels.npz'
    np.savez_compressed(raw, **arrays)
    stable = start_identity == identity()
    report = dict(schema=1, complete=True, scope=__doc__, identity=start_identity,
        sources=start_identity['sources'], sources_stable_during_run=stable,
        request=dict(variant=variant, candidate=spec, current_layout=candidates.baseline_layout(),
                     cases=[row[0] for row in corpus], case_universe=[row[0] for row in
                     (*full_cases.grades(), *full_cases.ui_boundaries())],
                     samples=1024, space=space, context=context, backend=backend, threads=threads,
                     graph_builder='persistent', fixture_strategy='One immutable layout; persistent apply across cases'),
        execution=execution, display=display.metadata, rows=rows, initial_inventory=inventory,
        initial_metadata=initial_metadata, raw=dict(path=raw.name, sha256=digest(raw)),
        input_sha256=hashlib.sha256(values.tobytes()).hexdigest())
    (output_dir/'report.json').write_text(json.dumps(_json_values(report), indent=2, allow_nan=False)+'\n')
    if not stable:
        raise RuntimeError('Sources changed during sensitivity measurement')
    print('COMPLETE', variant, len(rows), flush=True)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--variant', default='baseline')
    parser.add_argument('--space', choices=cases.SPACES, default='Linear Rec.709')
    parser.add_argument('--context', choices=('shader','compositor'), default='compositor')
    parser.add_argument('--cases', nargs='+')
    parser.add_argument('--backend', choices=('cpu','software-gpu'), default='cpu')
    parser.add_argument('--threads', type=int, default=1)
    parser.add_argument('--cpu', nargs='+', type=int)
    parser.add_argument('--xvfb', type=Path)
    parser.add_argument('--worker', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.threads < 1:
        parser.error('Threads must be positive')
    if args.backend == 'software-gpu' and not args.worker:
        if args.xvfb is None:
            parser.error('Software GPU requires the pinned --xvfb fixture')
        from .gpu_report import display_environment
        from .prepared_edit_costs import software_gpu_environment
        args.output_dir.mkdir(parents=True, exist_ok=True)
        script = ('import sys; sys.path[:]=' + repr(sys.path) + '; '
                  'from tools.perceptual_grade.reports.current_texture_sensitivity import main; main(sys.argv[1:])')
        command = [sys.executable, '-c', script, '--worker', '--output-dir', str(args.output_dir.resolve()),
                   '--variant', args.variant, '--space', args.space, '--context', args.context,
                   '--backend', args.backend, '--threads', str(args.threads)]
        if args.cpu:
            command += ['--cpu', *map(str,args.cpu)]
        if args.cases:
            command += ['--cases', *args.cases]
        with display_environment(args.xvfb, args.output_dir) as environment:
            environment = software_gpu_environment(environment, args.xvfb, args.threads)
            with (args.output_dir/'native.log').open('w') as stream:
                process = subprocess.run(command, env=environment, stdout=stream, stderr=subprocess.STDOUT)
        if process.returncode:
            raise RuntimeError('Software GPU worker failed; inspect native.log')
        return
    run(args.output_dir, variant=args.variant, space=args.space, context=args.context,
        selected_cases=args.cases, backend=args.backend, threads=args.threads, cpus=args.cpu)


if __name__ == '__main__':
    main()
