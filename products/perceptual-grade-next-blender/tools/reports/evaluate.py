"""Generate reproducible reference/native accuracy and cost reports."""
import argparse
from functools import partial
from color_tools.kernel.graph import build_group
from dataclasses import asdict, replace
import hashlib
import importlib
from importlib.resources import files
import json
from pathlib import Path
import time
import numpy as np
from color_tools.kernel import prepare
from . import cases, oracle


def evidence_hashes():
    """Bind numeric evidence to both implementations and the evaluation path."""
    sources = [importlib.import_module(name) for name in (
        'color_tools.kernel',
        'color_tools.color_core.linear',
        'color_tools.color_core.modcam16',
        'color_tools.kernel.graph',
        'color_tools.kernel.prepare',
        'color_tools.kernel.tables',
        'color_tools.kernel.settings',
        'color_tools.kernel.color_prepare',
        'color_tools.kernel.color_graph',
        'color_tools.kernel.boundary',
        'color_tools.kernel.guard_graph',
        'color_tools.kernel.layouts',
        'color_tools.kernel.persistent',
        *(__package__+'.'+name for name in ('cases','full_cases','oracle','native','evaluate','full_evaluate',
                                          'gpu_report','gpu_sampling','gpu_guards','guard_cases','audit_fields','gate_policy')),
    )]
    references = [importlib.import_module(name) for name in (
        'color_tools.perceptual_grade_reference.model',
        'color_tools.perceptual_grade_reference.grading',
        'color_tools.perceptual_grade_reference.appearance',
        'color_tools.perceptual_grade_reference.responses',
        'color_tools.perceptual_grade_reference.cube',
        'color_tools.perceptual_grade_reference.cube_guard',
        'color_tools.perceptual_grade_core.model.tonal_web',
        'color_tools.perceptual_grade_core.model.selective_adaptance',
        'color_tools.perceptual_grade_core.model.hk_guard',
        'color_tools.color_core.scaled',
    )]
    def hashes(modules):
        return {Path(module.__file__).name:hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()
                for module in modules}
    boundary = files('color_tools.kernel').joinpath('output_boundary.npz')
    return {'source_sha256':hashes(sources), 'reference_source_sha256':hashes(references),
            'resource_sha256':{'output_boundary.npz':hashlib.sha256(boundary.read_bytes()).hexdigest()}}


def assess(actual, expected, values):
    valid = actual['valid'] > .5
    ordinary = oracle.metrics(actual['rgb'],expected['rgb'],expected['well_conditioned'])
    near = oracle.metrics(actual['rgb'],expected['rgb'],expected['valid'] & ~expected['well_conditioned'])
    mismatches = np.flatnonzero(valid != expected['valid'])
    # A reference-valid ordinary sample must always be represented as valid.
    invalid_black = float(np.max(abs(actual['rgb'][~valid]),initial=0))
    alpha_error = float(np.max(abs(actual['alpha']-values[:,3]),initial=0))
    finite = bool(all(np.isfinite(actual[name]).all() for name in ('rgb','alpha','valid','margin')))
    passed = (ordinary['max_normalized'] <= 1e-4 and finite and invalid_black == 0.
              and alpha_error <= 2e-6 and not len(mismatches))
    return dict(passed=bool(passed), ordinary=ordinary, near_pole=near,
                reference_invalid=int(np.sum(~expected['valid'])), native_invalid=int(np.sum(~valid)),
                validity_mismatches=mismatches.tolist(), invalid_max_absolute=invalid_black,
                alpha_max_absolute=alpha_error, finite=finite,
                margin_max_absolute=float(np.max(abs(actual['margin']-expected['margin']),initial=0)))


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir',type=Path,required=True)
    parser.add_argument('--samples',type=int,default=1024)
    parser.add_argument('--contexts',nargs='+',choices=('shader','compositor'),default=['shader','compositor'])
    parser.add_argument('--cases',nargs='+')
    parser.add_argument('--spaces',nargs='+',choices=cases.SPACES,default=list(cases.SPACES))
    parser.add_argument('--no-warm',action='store_true')
    parser.add_argument('--ui-boundaries',action='store_true',help='Also evaluate individual UI slider endpoints, integer fits and peak presets')
    args=parser.parse_args(argv)
    if args.samples < 256:
        parser.error('--samples must be at least 256')
    from .native import NativeFixture
    import bpy
    values=cases.rgba(args.samples)
    rows=[]
    for space in args.spaces:
        corpus=list(cases.grades())+(list(cases.ui_boundaries()) if args.ui_boundaries else [])
        for name,linear,tone in corpus:
            if args.cases and name not in args.cases:
                continue
            cases.assert_ui_settings(linear,tone)
            start=time.perf_counter()
            prepared=prepare(linear,tone,space)
            preparation=time.perf_counter()-start
            # Development validation is deliberately outside production preparation.
            from color_tools.kernel.tables import audit_tone
            start=time.perf_counter()
            prepared=replace(prepared,tone=audit_tone(prepared.tone))
            audit_seconds=time.perf_counter()-start
            expected=oracle.evaluate(values[:,:3],linear,tone,space)
            for context in args.contexts:
                fixture=NativeFixture(prepared,values,context,builder=partial(build_group,export=False))
                try:
                    actual=fixture.render()
                    warm=fixture.render()['seconds'] if not args.no_warm else None
                    row=assess(actual,expected,values)
                    row.update(case=name,space=space,context=context,table_cells=prepared.table.cells if prepared.table else 0,
                               table_scalar_error=prepared.table.max_error if prepared.table else 0.,table_probes=prepared.table.probe_count if prepared.table else 0,
                               stats=actual['stats'],preparation_seconds=preparation,
                               initialization_timings=fixture.initialization_timings,
                               cold_readback_seconds=actual['readback_seconds'],
                               cold_fixture_seconds=actual['fixture_seconds'],
                               audit_seconds=audit_seconds,
                               cold_seconds=actual['seconds'],warm_seconds=warm,
                               linear=asdict(linear),tone=asdict(tone))
                    row['passed'] &= row['stats']['expanded_nodes'] <= 300
                    row['passed'] &= prepared.table is None or (prepared.table.monotone and prepared.table.max_error <= 1e-5)
                    rows.append(row)
                    print(f"{context} {space} {name}: error={row['ordinary']['max_normalized']:.6g} nodes={row['stats']['expanded_nodes']} passed={row['passed']}",flush=True)
                finally:
                    fixture.close()
    if not rows:
        parser.error('No evaluation cases selected')
    report={'schema':1,'blender':bpy.app.version_string,'samples_per_case':args.samples,
            **evidence_hashes(),'pixels_sha256':hashlib.sha256(values.tobytes()).hexdigest(),
            'control_domain':'Extension Gizmo/slider ranges, integer Fit, four peak presets, ordered anchors',
            'effective_fit_domain':[-2,2],
            'ui_boundaries':args.ui_boundaries,
            'metric':'max(abs(actual-reference))/(1+max(abs(reference)))',
            'rgb_limit':1e-4,'ordinary_response_limit':300.,'node_limit':300,
            'full_future_graph_limit_exclusive':1000,'passed':all(r['passed'] for r in rows),
            'coverage':{'cycles':'CPU','compositor':'CPU FULL','eevee':'not exercised by this target',
                        'compositor_gpu':'not exercised by this target','half_precision':'outside acceptance'},
            'cases':rows}
    args.output_dir.mkdir(parents=True,exist_ok=True)
    (args.output_dir/'report.json').write_text(json.dumps(report,indent=2,allow_nan=False)+'\n')
    lines=['# Native Linear + Tone evaluation','',
           f"Blender {report['blender']}; {len(rows)} cases × {args.samples} deterministic float32 signed HDR pixels.",
           f"Acceptance: {'PASS' if report['passed'] else 'FAIL'}. RGB normalized error ≤1e-4 where reference |response|≤300; ≤300 expanded nodes.",'',
           '| Context | Space | Case | Cells | Nodes | Max normalized error | Invalid ref/native |',
           '|---|---|---|---:|---:|---:|---:|']
    for row in rows:
        lines.append(f"| {row['context']} | {row['space']} | {row['case']} | {row['table_cells']} | {row['stats']['expanded_nodes']} | {row['ordinary']['max_normalized']:.6g} | {row['reference_invalid']}/{row['native_invalid']} |")
    lines += ['', 'Controls are restricted to the extension Gizmo/UI ranges, effective Tone Fit [-2, 2], four peak presets, and valid landmark spacing.',
              'Full detail, source hashes, error percentiles/worst pixels, pole cases and timings are in report.json.',
              'This report covers raw Linear/Tone in Cycles CPU and full-precision Compositor CPU. Full guarded grading has separate full_report/full_ui_report targets; product integration is deferred.','']
    (args.output_dir/'report.md').write_text('\n'.join(lines))
    if not report['passed']:
        raise SystemExit('Native grading acceptance failed; inspect report.json')


if __name__ == '__main__':
    main()
