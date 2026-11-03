"""Diagnostic native effects of smaller Color helper fields.

This tool replaces one immutable field at a time in an otherwise unchanged
prepared grade. It does not change runtime layouts or acceptance thresholds.
Field failures are retained and evaluated through the complete native graph;
successful final pixels do not certify a candidate for the continuous domain.
"""
import argparse
from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path
import time

import numpy as np

from color_tools.kernel import prepare, prepare_linear
from color_tools.kernel.boundary import prepare_boundary
from color_tools.kernel.color_prepare import (
    _generate_field, _prepare_tables,
)
from color_tools.kernel.layouts import FIELD_CELLS, supported_cells
from . import cases, full_cases, oracle
from .evaluate import assess, evidence_hashes
from .gpu_report import _json_values
from .gate_policy import audit_field, field_passed, scalar_limits


ATTRIBUTES = {
    'Color coefficients': 'coefficient_table',
    'Web parameters': 'web_table',
    'Web toes': 'web_toe_table',
    'Adaptance parameters': 'adaptance_table',
}
DEFAULT_CASES = {
    'Color coefficients': ('all_active', 'lightness_fit_6', 'chroma_fit_6'),
    'Web parameters': ('all_active', 'web_alternating_extremes'),
    'Web toes': ('all_active', 'web_alternating_extremes'),
    'Adaptance parameters': ('all_active', 'all_families_max_active_tail'),
}


def _sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _incremental(actual, baseline, reference):
    """Compare changed/current native values with a shared reference scale."""
    difference = np.max(abs(actual-baseline), axis=-1)
    normalized = difference/(1+np.max(abs(reference), axis=-1))
    index = int(np.argmax(normalized))
    return dict(max_normalized=float(np.max(normalized)),
                p99_normalized=float(np.percentile(normalized, 99)),
                max_absolute=float(np.max(difference)), worst_index=index,
                worst_candidate=actual[index].tolist(),
                worst_baseline=baseline[index].tolist(),
                worst_reference=reference[index].tolist())


def _selection(fields, selected_cases, audit_report, cell_counts, coarse):
    """Select explicit diagnostics, retaining their provenance in the report."""
    selected = {}
    for field in fields:
        names = list(DEFAULT_CASES[field] if selected_cases is None else selected_cases)
        lower = tuple(size for size in supported_cells(field) if size <= FIELD_CELLS[field]//2)
        sizes = set(lower[-1:]) if cell_counts is None else set(cell_counts)
        reasons = ['explicit cases' if selected_cases is not None else 'representative and extreme controls']
        if coarse:
            sizes.add(supported_cells(field)[0])
        if audit_report is not None:
            receipt = next((row for row in audit_report['fields'] if row['name'] == field), None)
            failures = [] if receipt is None else [row for row in receipt['attempts'] if not row['passed']]
            if failures:
                lower = max(failures, key=lambda row: row['cells'])
                sizes.add(lower['cells'])
                witnesses = [row for row in lower['cases'] if not row['passed']]
                if selected_cases is None and witnesses:
                    names.append(witnesses[0]['cases'][0])
                reasons.append('largest failing scalar-audit candidate')
        sizes = sorted(size for size in sizes if size < FIELD_CELLS[field])
        if any(size not in supported_cells(field) for size in sizes):
            raise ValueError('Candidate counts must belong to the field role\'s supported grids')
        if not sizes:
            raise ValueError(f'No smaller candidate for {field}')
        selected[field] = dict(cases=list(dict.fromkeys(names)), cells=sizes, reasons=reasons)
    return selected


def _candidate(prepared, role, cells):
    """Generate/audit one replacement and preserve all other table objects."""
    original = {table.name: table for table in prepared.color.tables}
    generation = audit = 0.

    def builder(name, evaluator, fields, mapping, domain, knots=(), scales=None, **kwargs):
        nonlocal generation, audit
        if name != role:
            return original[name]
        start = time.perf_counter()
        table = _generate_field(name, evaluator, fields, mapping, domain, knots, scales,
                                cells=cells, **kwargs)
        generation = time.perf_counter()-start
        start = time.perf_counter()
        # HDR-admitted fields keep complete scalar maxima even when their
        # raw interpolation limits fail; audit_field applies that role policy.
        table = audit_field(table, evaluator, knots, settings=prepared.color.settings,
                            stop_on_failure=role != 'Web toes')
        audit = time.perf_counter()-start
        return table

    color = _prepare_tables(prepared.color, builder=builder)
    table = getattr(color, ATTRIBUTES[role])
    for name, value in original.items():
        if name != role and getattr(color, ATTRIBUTES[name]) is not value:
            raise AssertionError('Candidate changed an unrelated table')
    return replace(prepared, color=color), dict(
        name=role, cells=cells, shape=list(table.pixels.shape), bytes=table.pixels.nbytes,
        pixels_sha256=hashlib.sha256(table.pixels.tobytes()).hexdigest(),
        generation_seconds=generation, audit_seconds=audit,
        field_passed=field_passed(table, prepared.color.settings),
        limits=scalar_limits(table, prepared.color.settings),
        max_conditioned_error=table.max_error, max_pointwise_error=table.max_pointwise_error,
        max_mapper_error=table.max_mapper_error,
        relative_interpolation_error=table.max_relative_interpolation_error,
        relative_interpolation_limit=table.relative_interpolation_limit,
        absolute_interpolation_error=table.max_absolute_interpolation_error,
        absolute_interpolation_limit=table.absolute_interpolation_limit,
        audit_complete=table.audit_complete, probes=table.probe_count,
        witness=table.audit_witness)


def _render(prepared, values, context, expected, role=None):
    from .native import NativeFixture
    start = time.perf_counter()
    fixture = NativeFixture(prepared, values, context)
    construction = time.perf_counter()-start
    verification_start = time.perf_counter()
    try:
        image_receipt = None
        if role is not None:
            table = getattr(prepared.color, ATTRIBUTES[role])
            # Graph labels are human-facing and are intentionally not the
            # semantic role names. Match the immutable payload instead; this
            # also proves the candidate reached the native image.
            expected_hash = hashlib.sha256(table.pixels.tobytes()).hexdigest()
            images = []
            for image in fixture.built.images:
                pixels = np.empty(int(image.size[0]) * int(image.size[1]) * 4,
                                  dtype=np.float32)
                image.pixels.foreach_get(pixels)
                if hashlib.sha256(pixels.tobytes()).hexdigest() == expected_hash:
                    images.append(image)
            if not images:
                # Specialized graphs legitimately omit unused fields. They
                # provide no evidence for that candidate's sampling accuracy.
                return None, dict(field_sampled=False, image_names=[image.name for image in fixture.built.images])
            if len(images) != 1:
                raise AssertionError('Candidate image identity is ambiguous')
            image = images[0]
            shape = list(table.pixels.shape)
            if list(image.size) != [shape[1], shape[0]]:
                raise AssertionError('Native image dimensions do not match candidate')
            pixels = np.empty(table.pixels.size, dtype=np.float32)
            image.pixels.foreach_get(pixels)
            if not np.array_equal(pixels, table.pixels.ravel()):
                raise AssertionError('Native image contents do not match candidate')
            image_receipt = dict(name=image.name, size=list(image.size),
                                 bytes=pixels.nbytes, pixels_sha256=hashlib.sha256(pixels.tobytes()).hexdigest())
        verification_seconds = time.perf_counter()-verification_start
        actual = fixture.render()
        result = assess(actual, expected, values)
        native = actual['rgb'] @ np.linalg.inv(expected['to_scene']).T
        magnitude = np.maximum(1., np.max(abs(native), axis=-1))
        violation = np.maximum(np.max(-native, axis=-1), np.max(native-1024., axis=-1))
        containment = float(np.max(np.maximum(0., violation)/magnitude, initial=0))
        result.update(field_sampled=True, image=image_receipt,
                      final_rgb_passed=bool(result['passed'] and containment <= 8e-6
                                            and np.isfinite(actual['saturated']).all()),
                      reconstructed_ap1_max_normalized_violation=containment,
                      saturated_samples=int(np.count_nonzero(actual['saturated'] > .5)),
                      construction_seconds=construction,
                      candidate_image_verification_seconds=verification_seconds,
                      initialization_timings=fixture.initialization_timings,
                      render_seconds=actual['seconds'], readback_seconds=actual['readback_seconds'],
                      fixture_seconds=actual['fixture_seconds'], stats=actual['stats'],
                      node_budget_passed=actual['stats']['expanded_nodes'] < 1000)
        return actual, result
    finally:
        fixture.close()


def run(output_dir, *, samples=1024, spaces=cases.SPACES, contexts=('shader', 'compositor'),
        fields=tuple(ATTRIBUTES), selected_cases=None, audit_path=None, cell_counts=None, coarse=False):
    import bpy
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    identities = evidence_hashes()
    own_hash = _sha256(__file__)
    audit = None if audit_path is None else json.loads(Path(audit_path).read_text())
    if audit is not None:
        for key in ('source_sha256', 'reference_source_sha256', 'resource_sha256'):
            if audit[key] != identities[key]:
                raise ValueError('Field audit belongs to a different source/resource snapshot')
    selection = _selection(fields, selected_cases, audit, cell_counts, coarse)
    corpus = {row[0]: row for row in (*full_cases.grades(), *full_cases.ui_boundaries())}
    names = list(dict.fromkeys(name for row in selection.values() for name in row['cases']))
    unknown = set(names)-set(corpus)
    if unknown:
        raise ValueError(f'Unknown cases: {sorted(unknown)}')
    base = prepare()
    boundary = prepare_boundary(base.fl, base.aw, base.gamma)
    rows, baselines = [], []
    started = time.perf_counter()
    report = dict(schema=1, **identities, tool_sha256=own_hash, blender=bpy.app.version_string,
                  audit_sha256=None if audit_path is None else _sha256(audit_path),
                  scope='diagnostic finite corpus under the scoped Web gate policy; no runtime layout changes',
                  metric='max(abs(candidate-baseline))/(1+max(abs(float64_reference)))',
                  final_rgb_limit=1e-4, added_error_reference_level=1e-5,
                  selection=selection, samples_per_case=samples, spaces=list(spaces), contexts=list(contexts),
                  limitations=['Scalar witnesses are coordinates, not input RGB pixels; the final corpus may not visit each witness.',
                               'A final pass here does not establish local native-stage acceptance or continuous-domain safety.',
                               'Partial field audits retain a failing witness, not a global maximum.',
                               'Specialized graph construction and EXR timing are diagnostic, not interactive latency.'],
                  baselines=baselines, cases=rows, complete=False)

    def checkpoint():
        report['seconds'] = time.perf_counter()-started
        report['sources_stable_during_run'] = identities == evidence_hashes() and own_hash == _sha256(__file__)
        (output_dir/'report.json').write_text(json.dumps(_json_values(report), indent=2, allow_nan=False)+'\n')

    for name in names:
        _, linear, tone, color = corpus[name]
        prepared = prepare(linear, tone, color=color, boundary=boundary, full_fields=True)
        candidates = []
        for role, choice in selection.items():
            if name in choice['cases']:
                for cells in choice['cells']:
                    candidate, field = _candidate(prepared, role, cells)
                    candidates.append((candidate, field))
        for space in spaces:
            values = full_cases.rgba(space, samples)
            expected = oracle.evaluate_full(values[:, :3], linear, tone, color, space)
            current = replace(prepared, linear=prepare_linear(linear, space), space=space)
            for context in contexts:
                baseline, measured = _render(current, values, context, expected)
                baselines.append(dict(case=name, space=space, context=context, **measured))
                for candidate, field in candidates:
                    native = replace(candidate, linear=current.linear, space=space)
                    actual, measured = _render(native, values, context, expected, field['name'])
                    row = dict(case=name, space=space, context=context, field=field,
                               linear=asdict(linear), tone=asdict(tone), color=asdict(color),
                               pixels_sha256=hashlib.sha256(values.tobytes()).hexdigest(), **measured)
                    if actual is not None:
                        incremental = _incremental(actual['rgb'], baseline['rgb'], expected['rgb'])
                        row.update(added_rgb_error=incremental,
                                   baseline_final_rgb_passed=baselines[-1]['final_rgb_passed'],
                                   added_rgb_at_most_1e5=incremental['max_normalized'] <= 1e-5,
                                   field_failed_final_passed=(not field['field_passed'] and measured['final_rgb_passed']),
                                   changed_validity_samples=int(np.count_nonzero((actual['valid'] > .5) != (baseline['valid'] > .5))),
                                   changed_saturation_samples=int(np.count_nonzero((actual['saturated'] > .5) != (baseline['saturated'] > .5))))
                        row['worst_added_error_input'] = values[incremental['worst_index']].tolist()
                        print(f"{name} {space} {context} {field['name']} {field['cells']}: "
                              f"field={field['field_passed']} final={measured['final_rgb_passed']} "
                              f"added={incremental['max_normalized']:.6g}", flush=True)
                    else:
                        print(f"{name} {space} {context} {field['name']}: not sampled", flush=True)
                    rows.append(row)
                    checkpoint()
    report['complete'] = True
    report['baseline_final_rgb_passed'] = all(row['final_rgb_passed'] for row in baselines)
    report['field_fail_final_pass_count'] = sum(row.get('field_failed_final_passed', False) for row in rows)
    checkpoint()
    lines = ['# Smaller helper-field effects on final RGB', '',
             report['scope']+'.', '',
             '| Case | Space | Context | Field | Cells | Field gate | Final RGB gate | Added RGB error |',
             '|---|---|---|---|---:|---|---|---:|']
    for row in rows:
        if row['field_sampled']:
            lines.append(f"| {row['case']} | {row['space']} | {row['context']} | {row['field']['name']} | "
                         f"{row['field']['cells']} | {row['field']['field_passed']} | {row['final_rgb_passed']} | "
                         f"{row['added_rgb_error']['max_normalized']:.8g} |")
    lines += ['', *report['limitations'], '']
    (output_dir/'report.md').write_text('\n'.join(lines))
    if not report['sources_stable_during_run']:
        raise RuntimeError('Sources changed during field-effect diagnostics')
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--samples', type=int, default=1024)
    parser.add_argument('--spaces', nargs='+', choices=cases.SPACES, default=list(cases.SPACES))
    parser.add_argument('--contexts', nargs='+', choices=('shader', 'compositor'), default=['shader', 'compositor'])
    parser.add_argument('--fields', nargs='+', choices=tuple(ATTRIBUTES), default=list(ATTRIBUTES))
    parser.add_argument('--cases', nargs='+')
    parser.add_argument('--audit-report', type=Path)
    parser.add_argument('--candidate-cells', nargs='+', type=int)
    parser.add_argument('--coarse', action='store_true', help='Also measure 2048-cell diagnostic candidates')
    args = parser.parse_args(argv)
    if args.samples < 256:
        parser.error('--samples must be at least 256')
    run(args.output_dir, samples=args.samples, spaces=args.spaces, contexts=args.contexts,
        fields=args.fields, selected_cases=args.cases, audit_path=args.audit_report,
        cell_counts=args.candidate_cells, coarse=args.coarse)


if __name__ == '__main__':
    main()
