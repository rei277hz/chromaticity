"""Full native grade accuracy, saturation and expanded-cost evidence."""
import argparse
from dataclasses import asdict, replace
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
import numpy as np
from color_tools.perceptual_grade_nodes import prepare, prepare_linear
from . import cases, full_cases, oracle
from .evaluate import assess, evidence_hashes
from .gpu_report import _json_values
from .gate_policy import field_passed, scalar_limits, texture_admission_policy


def _table_checks(tables):
    """Keep complete, finite diagnostics while separating required precision."""
    return dict(raw_scalar_passed=all(t['passed'] for t in tables),
                required_scalar_passed=all(t['passed'] for t in tables if t['scalar_gate_required']),
                field_diagnostics_passed=all(t['audit_complete'] and t['finite'] for t in tables))


def run(output_dir, *, samples=1024, spaces=cases.SPACES, contexts=('shader','compositor'),
        selected=None, ui_boundaries=False, warm_runs=1, gpu_backend=None):
    identities=evidence_hashes()
    import bpy
    from .native import NativeFixture
    from color_tools.perceptual_grade_nodes.boundary import prepare_boundary
    base=prepare()
    start=time.perf_counter()
    boundary=prepare_boundary(base.fl,base.aw,base.gamma)
    boundary_loading_seconds=time.perf_counter()-start
    rows=[]
    corpus=list(full_cases.grades())+(list(full_cases.ui_boundaries()) if ui_boundaries else [])
    templates={}
    if len({entry[0] for entry in corpus}) != len(corpus):
        raise ValueError('Evaluation case identities must be unique')
    for space in spaces:
        values=full_cases.rgba(space,samples)
        for name,linear,tone,color in corpus:
            if selected and name not in selected: continue
            start=time.perf_counter()
            reused=name in templates
            prepared=(replace(templates[name],linear=prepare_linear(linear,space),space=space)
                      if reused else prepare(linear,tone,space,color=color,boundary=boundary))
            preparation_seconds=time.perf_counter()-start
            from color_tools.perceptual_grade_nodes.tables import audit_tone
            from color_tools.perceptual_grade_nodes.color_prepare import audit_color
            start=time.perf_counter()
            if not reused:
                prepared=replace(prepared,tone=audit_tone(prepared.tone),color=audit_color(prepared.color))
            audit_seconds=time.perf_counter()-start
            expected=oracle.evaluate_full(values[:,:3],linear,tone,color,space)
            for context in contexts:
                engine='BLENDER_EEVEE' if gpu_backend and context=='shader' else 'CYCLES'
                device='GPU' if gpu_backend and context=='compositor' else 'CPU'
                start=time.perf_counter()
                fixture=NativeFixture(prepared,values,context,engine=engine,device=device)
                construction_seconds=time.perf_counter()-start
                try:
                    actual=fixture.render()
                    warm=[fixture.render()['seconds'] for _ in range(warm_runs)]
                    row=assess(actual,expected,values)
                    native=actual['rgb']@np.linalg.inv(expected['to_scene']).T
                    # This reconstruction includes scene-output/readback matrix
                    # roundoff; the isolated guard target checks native sockets.
                    magnitude=np.maximum(1,np.max(abs(native),axis=-1))
                    violation=np.maximum(np.max(-native,axis=-1),np.max(native-1024,axis=-1))
                    containment_error=float(np.max(np.maximum(0,violation)/magnitude,initial=0))
                    table_data=[dict(kind=t.name,cells=t.cells,bytes=t.pixels.nbytes,
                                     limits=scalar_limits(t, color),
                                     admission_policy=texture_admission_policy(t.name),
                                     raw_scalar_passed=field_passed(t, color),
                                     scalar_gate_required=(texture_admission_policy(t.name)['scalar_precision'] == 'required'),
                                     passed=field_passed(t, color),audit_complete=t.audit_complete,
                                     finite=all(np.isfinite(value).all() for value in
                                                (t.pixels,t.scales,t.field_errors,t.max_error,
                                                 t.max_relative_interpolation_error,t.max_absolute_interpolation_error)),
                                     error=t.max_error,probes=t.probe_count,
                                     shape=list(t.pixels.shape),
                                     scales=np.asarray(t.scales).tolist(),
                                     mapper_error=t.max_mapper_error,
                                     field_errors=np.asarray(t.field_errors).tolist(),
                                     relative_interpolation_error=getattr(t,'max_relative_interpolation_error',None),
                                     relative_interpolation_limit=getattr(t,'relative_interpolation_limit',None),
                                     relative_mapper_error=getattr(t,'max_relative_mapper_error',None),
                                     absolute_interpolation_error=getattr(t,'max_absolute_interpolation_error',None),
                                     absolute_interpolation_limit=getattr(t,'absolute_interpolation_limit',None),
                                     max_pointwise_error=getattr(t,'max_pointwise_error',t.max_error))
                                for t in fixture.built.prepared.color.tables]
                    # HDR-admitted fields retain their raw scalar status above,
                    # but this scene-linear report is not their admission test.
                    table_checks=_table_checks(table_data)
                    table_pass=table_checks['required_scalar_passed'] and table_checks['field_diagnostics_passed']
                    row.update(case=name,space=space,context=context,engine=engine,device=device,
                        stats=actual['stats'],tables=table_data,
                        **table_checks,
                        reused_portable_preparation=reused,
                        web_representation=('1d' if prepared.color.web_active else 'none'),
                        saturated_samples=int(np.count_nonzero(actual['saturated']>.5)),
                        saturated_indices=np.flatnonzero(actual['saturated']>.5).tolist(),
                        reconstructed_ap1_max_normalized_violation=containment_error,
                        pixels_sha256=hashlib.sha256(values.tobytes()).hexdigest(),
                        preparation_seconds=preparation_seconds,construction_seconds=construction_seconds,
                        initialization_timings=fixture.initialization_timings,
                        cold_readback_seconds=actual['readback_seconds'],
                        cold_fixture_seconds=actual['fixture_seconds'],
                        audit_seconds=audit_seconds,
                        cold_seconds=actual['seconds'],warm_seconds=warm,
                        warm_median_seconds=float(np.median(warm)) if warm else None,
                        linear=asdict(linear),tone=asdict(tone),color=asdict(color))
                    row['numerical_passed'] = bool(row['passed'] and table_pass
                                                   and (prepared.table is None or
                                                        (prepared.table.monotone and prepared.table.max_error<=1e-5))
                                                   and containment_error<=8e-6
                                                   and np.isfinite(actual['saturated']).all())
                    row['node_budget_passed'] = actual['stats']['expanded_nodes']<1000
                    row['nodes_over_budget'] = max(0, actual['stats']['expanded_nodes']-999)
                    row['passed'] = row['numerical_passed'] and row['node_budget_passed']
                    rows.append(row)
                    # Reuse immutable 1D preparation across contexts/spaces. Every native build
                    # still creates and owns independent image/tree resources.
                    prepared=fixture.built.prepared
                    templates[name]=prepared
                    print(f"{engine}/{device} {space} {name}: error={row['ordinary']['max_normalized']:.6g} "
                          f"nodes={actual['stats']['expanded_nodes']} saturated={row['saturated_samples']} "
                          f"numerical={row['numerical_passed']} budget={row['node_budget_passed']}",flush=True)
                finally:
                    fixture.close()
    if not rows: raise ValueError('No full-grade evaluation cases selected')
    sources_stable=identities==evidence_hashes()
    report=dict(schema=4,blender=bpy.app.version_string,**identities,
                metric='max(abs(actual-reference))/(1+max(abs(reference)))',
                reference='unchanged float64; explicit stage composition; input repair excluded',
                rgb_limit=1e-4,internal_limit=1e-5,boundary_radius_limit=2e-5,
                internal_limit_exception='alternating-extreme Web scalar/local/returned-scale gates: 1e-4; see per-table limits',
                hdr_admitted_fields=['Web toes', 'Color coefficients', 'Adaptance parameters'],
                hdr_admission_report_required=True,
                expanded_node_limit_exclusive=1000,samples_per_case=samples,
                node_budget_enforced_during_construction=False,
                tone_fit_domain=[-2,2],color_fit_domain=[-2,6],backend=gpu_backend,
                boundary_loading_seconds=boundary_loading_seconds,
                boundary_texture_bytes=boundary.pixels.nbytes,
                boundary_internal_error=boundary.max_error,
                boundary_probe_count=boundary.probe_count,
                coverage=('Eevee and Compositor GPU' if gpu_backend else 'Cycles CPU and full-precision Compositor CPU'),
                ui_boundaries=ui_boundaries,sources_stable_during_run=sources_stable,
                numerical_passed=sources_stable and all(row['numerical_passed'] for row in rows),
                node_budget_passed=all(row['node_budget_passed'] for row in rows),
                passed=sources_stable and all(row['passed'] for row in rows),cases=rows)
    _write_report(report, output_dir)
    return report


def _write_report(report, output_dir):
    rows = report['cases']
    samples = report['samples_per_case']
    output_dir=Path(output_dir);output_dir.mkdir(parents=True,exist_ok=True)
    (output_dir/'report.json').write_text(json.dumps(_json_values(report),indent=2,allow_nan=False)+'\n')
    lines=['# Full native grading evaluation','',
           f"Blender {report['blender']}; {len(rows)} cases × {samples} pixels; {report['coverage']}.",
           f"Result: {'PASS' if report['passed'] else 'FAIL'}. All samples, including saturation, retain the 1e-4 RGB gate.",
           f"Numerical acceptance: {'PASS' if report['numerical_passed'] else 'FAIL'}; "
           f"original <1000-node budget: {'PASS' if report['node_budget_passed'] else 'FAIL'}. "
           'Oversized 1D graphs are temporarily allowed to build; combined acceptance still requires both.',
           'Raw scalar precision remains visible per field. Web toes, Color coefficients and Compact Adaptance use HDR worsening for layout admission; consult their source-bound HDR report. Internal-stage and boundary-radius checks are independent.',
           '', '| Context | Space | Case | RGB normalized error | Expanded nodes | Over budget | Saturated pixels |',
           '|---|---|---|---:|---:|---:|---:|']
    for row in rows:
        lines.append(f"| {row['context']} | {row['space']} | {row['case']} | {row['ordinary']['max_normalized']:.6g} | "
                     f"{row['stats']['expanded_nodes']} | {row['nodes_over_budget']} | {row['saturated_samples']} |")
    lines+=['','Scene-space RGB need not be positive: containment is in the reference native AP1 cube.',
            'Preparation measures fixed-layout coefficient generation; audit_seconds records separate development validation. '
            'The legacy construction_seconds field includes scene/fixture initialization; initialization_timings '
            'separates scene/input, grade graph, and output fixture setup. Cold/warm seconds time the native render call, '
            'including EXR writes and excluding Python readback. They are correctness diagnostics, not drag latency.','']
    if report.get('parallel_workers'):
        lines += [report['timing_contract'], '']
    (output_dir/'report.md').write_text('\n'.join(lines))


def run_parallel(output_dir, *, jobs, samples, spaces, contexts, selected=None,
                 ui_boundaries=False, warm_runs=1):
    """Run independent scene-space acceptance workers; benchmark separately.

    Each Blender process owns its resources and prepares its own immutable
    fields. Parallel correctness-fixture timings are not performance evidence.
    """
    identities = evidence_hashes()
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    script = ('import sys; sys.path[:]=' + repr(sys.path) + '; '
              'from tools.perceptual_grade_nodes.full_evaluate import main; main(sys.argv[1:])')
    environment = dict(os.environ, OPENBLAS_NUM_THREADS='1', OMP_NUM_THREADS='1')

    def worker(item):
        index, space = item
        destination = output_dir/'workers'/str(index)
        destination.mkdir(parents=True, exist_ok=True)
        log = destination/'native.log'
        command = [sys.executable, '-c', script, '--output-dir', str(destination),
                   '--spaces', space, '--contexts', *contexts, '--samples', str(samples),
                   '--warm-runs', str(warm_runs)]
        if selected:
            command += ['--cases', *selected]
        if ui_boundaries:
            command.append('--ui-boundaries')
        with log.open('w') as stream:
            result = subprocess.run(command, env=environment, stdout=stream,
                                    stderr=subprocess.STDOUT, timeout=7200)
        path = destination/'report.json'
        if not path.exists():
            raise RuntimeError(f'Acceptance worker for {space} failed ({result.returncode}); see {log}')
        part = json.loads(path.read_text())
        if result.returncode and part['passed']:
            raise RuntimeError(f'Acceptance worker for {space} exited after reporting success; see {log}')
        print(f"{space}: {len(part['cases'])} cases, passed={part['passed']}", flush=True)
        return part

    with ThreadPoolExecutor(max_workers=min(jobs, len(spaces))) as pool:
        parts = list(pool.map(worker, enumerate(spaces)))
    corpus = list(full_cases.grades()) + (list(full_cases.ui_boundaries()) if ui_boundaries else [])
    names = {row[0] for row in corpus if not selected or row[0] in selected}
    expected = {(space, context, name) for space in spaces for context in contexts for name in names}
    rows = [row for part in parts for row in part['cases']]
    actual = [(row['space'], row['context'], row['case']) for row in rows]
    if len(actual) != len(expected) or set(actual) != expected:
        raise AssertionError('Parallel acceptance has missing or duplicate cases')
    stable = identities == evidence_hashes() and all(
        part['sources_stable_during_run'] and all(part[key] == value for key, value in identities.items())
        for part in parts)
    report = dict(parts[0], **identities, cases=rows,
                  passed=stable and all(part['passed'] for part in parts),
                  numerical_passed=stable and all(part['numerical_passed'] for part in parts),
                  node_budget_passed=all(part['node_budget_passed'] for part in parts),
                  sources_stable_during_run=stable,
                  parallel_workers=len(parts),
                  boundary_loading_seconds=sum(part['boundary_loading_seconds'] for part in parts),
                  worker_boundary_loading_seconds=[part['boundary_loading_seconds'] for part in parts],
                  timing_contract='Independent scene-space workers run concurrently. Each prepares its own '
                                  'fields; boundary loading seconds is their sum. Fixture timings are '
                                  'correctness diagnostics; use the uncontended benchmark for performance.')
    _write_report(report, output_dir)
    return report


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir',type=Path,required=True)
    parser.add_argument('--samples',type=int,default=1024)
    parser.add_argument('--spaces',nargs='+',choices=cases.SPACES,default=list(cases.SPACES))
    parser.add_argument('--contexts',nargs='+',choices=('shader','compositor'),default=['shader','compositor'])
    parser.add_argument('--cases',nargs='+')
    parser.add_argument('--ui-boundaries',action='store_true')
    parser.add_argument('--warm-runs',type=int,default=1)
    parser.add_argument('--jobs',type=int,default=1,
                        help='Independent CPU scene-space workers; fixture timings are concurrent')
    args=parser.parse_args(argv)
    if args.samples<256 or args.warm_runs<0 or args.jobs<1:
        parser.error('Need at least 256 samples, nonnegative warm runs and positive jobs')
    runner = run_parallel if args.jobs > 1 and len(args.spaces) > 1 else run
    options = {'jobs': args.jobs} if runner is run_parallel else {}
    report=runner(args.output_dir,samples=args.samples,spaces=args.spaces,contexts=args.contexts,
                  selected=args.cases,ui_boundaries=args.ui_boundaries,warm_runs=args.warm_runs, **options)
    if not report['passed']: raise SystemExit('Full native grading accuracy or cost acceptance failed')


if __name__=='__main__':main()
