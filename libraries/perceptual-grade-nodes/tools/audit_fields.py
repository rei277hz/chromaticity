"""Offline field-resolution selection and accuracy receipts for the retained corpus.

No production preparation calls this tool. Every lower candidate has a failing
witness; the selected candidate is checked against every distinct applicable
parameter function in the requested corpus. A filtered run is diagnostic only.
"""
import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import time
import numpy as np

from color_tools.perceptual_grade_nodes import prepare_tone
from color_tools.perceptual_grade_nodes.color_prepare import (
    _prepare_color_parameters, _prepare_tables, _generate_field)
from color_tools.perceptual_grade_nodes.layouts import FIELD_CELLS, LAYOUT_SCHEMA, supported_cells
from color_tools.perceptual_grade_nodes.tables import audit_tone, TABLE_ERROR_LIMIT
from . import full_cases
from .gate_policy import audit_field, field_passed, scalar_limits, is_alternating_extreme_web, texture_admission_policy


def _identity(value):
    def native(item):
        if isinstance(item, np.ndarray):
            return item.tolist()
        if isinstance(item, np.generic):
            return item.item()
        raise TypeError(f'Unsupported audit identity value: {type(item).__name__}')
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=native).encode()).hexdigest()


def _key(name, color, tone):
    common = (tone.reference_nits, tone.peak_nits)
    if name == 'Color coefficients':
        relevant = (color.lightness, color.chroma, color.lightness_fit, color.chroma_fit)
    elif name == 'Web parameters':
        relevant = asdict(color.web)
    elif name == 'Web toes':
        relevant = (color.web.log_chroma, color.web.log_scale)
    else:
        relevant = color.adaptance
    # Toe identity excludes hue, but an identical function can belong to cases
    # with different gate policies. Never deduplicate across that distinction.
    exceptional = name in ('Web parameters', 'Web toes') and is_alternating_extreme_web(color)
    return _identity((common, relevant, exceptional))


def run(output_dir, *, cases=None, fields=None, fixed_only=False, cells=None, complete_diagnostics=False):
    from .evaluate import evidence_hashes
    identities = evidence_hashes()
    corpus = list(full_cases.grades()) + list(full_cases.ui_boundaries())
    if cases:
        unknown = set(cases)-{row[0] for row in corpus}
        if unknown:
            raise ValueError(f'Unknown audit cases: {sorted(unknown)}')
        corpus = [row for row in corpus if row[0] in cases]
    if not corpus:
        raise ValueError('No audit cases selected')
    roles = tuple(FIELD_CELLS if fields is None else fields)
    if cells is not None:
        if fixed_only:
            raise ValueError('Explicit cells cannot be combined with fixed-only')
        cells = tuple(sorted(set(cells)))
        if not cells or any(n not in supported_cells(name) for name in roles for n in cells):
            raise ValueError('Explicit cell counts must belong to every selected role\'s supported grids')
    specs = {name: {} for name in roles}
    tones = {}
    began = time.perf_counter()
    for case, _, tone_settings, color_settings in corpus:
        key = _identity(asdict(tone_settings))
        if key not in tones:
            tones[key] = dict(tone=prepare_tone(tone_settings, full_fields=True), cases=[])
        tones[key]['cases'].append(case)
        prepared = _prepare_color_parameters(color_settings, tones[key]['tone'], full_fields=True)
        def collect(name, evaluator, field_layout, mapping, domain, knots=(), scales=None, **kwargs):
            if name not in specs:
                return None
            key = _key(name, color_settings, tone_settings)
            if key not in specs[name]:
                specs[name][key] = dict(args=(name, evaluator, field_layout, mapping, domain, knots, scales),
                                        kwargs=kwargs, settings=color_settings, cases=[])
            specs[name][key]['cases'].append(case)
            return None
        _prepare_tables(prepared, builder=collect)
    tone_rows = []
    for entry in tones.values():
        measured = audit_tone(entry['tone']).table
        tone_rows.append(dict(cases=entry['cases'], cells=measured.cells, max_error=measured.max_error,
                              probe_count=measured.probe_count,
                              passed=measured.monotone and measured.max_error <= TABLE_ERROR_LIMIT))
    results = []
    for name in roles:
        attempts = []
        selected = None
        candidates = (cells if cells is not None else (FIELD_CELLS[name],) if fixed_only else
                      tuple(n for n in supported_cells(name) if n <= FIELD_CELLS[name]))
        for count in candidates:
            case_rows = []
            passed = True
            for spec in specs[name].values():
                table = _generate_field(*spec['args'], **spec['kwargs'], cells=count)
                measured = audit_field(table, spec['args'][1], spec['args'][5], settings=spec['settings'],
                                       stop_on_failure=not complete_diagnostics)
                ok = field_passed(measured, spec['settings'])
                case_rows.append(dict(cases=spec['cases'], passed=ok, max_error=measured.max_error,
                    limits=scalar_limits(measured, spec['settings']),
                    max_relative_interpolation_error=measured.max_relative_interpolation_error,
                    max_absolute_interpolation_error=measured.max_absolute_interpolation_error,
                    probe_count=measured.probe_count, audit_complete=measured.audit_complete, shape=list(measured.pixels.shape),
                    witness=measured.audit_witness))
                if not ok:
                    passed = False
                    if not complete_diagnostics:
                        break
            attempts.append(dict(cells=count, passed=passed, checked_functions=len(case_rows), cases=case_rows))
            print(f'{name}: {count} cells, {len(case_rows)} functions, passed={passed}', flush=True)
            if passed:
                if selected is None:
                    selected = count
                if cells is None and not complete_diagnostics:
                    break
        # A larger grid can change float32 rounding. Certify installed runtime
        # dimensions independently when the selected minimum is smaller.
        fixed_cases = []
        if cells is None and selected is not None and selected != FIELD_CELLS[name]:
            for spec in specs[name].values():
                table = _generate_field(*spec['args'], **spec['kwargs'])
                measured = audit_field(table, spec['args'][1], spec['args'][5], settings=spec['settings'],
                                       stop_on_failure=not complete_diagnostics)
                fixed_cases.append(dict(cases=spec['cases'], passed=field_passed(measured, spec['settings']),
                    limits=scalar_limits(measured, spec['settings']), audit_complete=measured.audit_complete,
                    max_error=measured.max_error, max_relative_interpolation_error=measured.max_relative_interpolation_error,
                    max_absolute_interpolation_error=measured.max_absolute_interpolation_error,
                    probe_count=measured.probe_count, witness=measured.audit_witness))
        if cells is not None:
            fixed_passed = next((row['passed'] for row in attempts if row['cells'] == FIELD_CELLS[name]), None)
        else:
            fixed_passed = (selected is not None and
                            (all(row['passed'] for row in fixed_cases) if fixed_cases else attempts[-1]['passed']))
        results.append(dict(name=name, runtime_cells=FIELD_CELLS[name], selected_cells=selected,
                            admission_policy=texture_admission_policy(name),
                            distinct_functions=len(specs[name]), attempts=attempts,
                            runtime_fixed_cases=fixed_cases, runtime_fixed_passed=fixed_passed))
    complete = not cases and fields is None
    stable = identities == evidence_hashes()
    report = dict(schema=2, layout_schema=LAYOUT_SCHEMA, **identities,
        scope='retained finite corpus; not an exhaustive proof over continuous controls; '
              'raw scalar gates only, not HDR layout admission',
        complete_corpus=complete, complete_case_corpus=not bool(cases),
        selection_performed=not fixed_only and cells is None, requested_cells=cells,
        complete_diagnostics=complete_diagnostics, corpus_cases=len(corpus),
        tone=tone_rows, fields=results, seconds=time.perf_counter()-began,
        sources_stable_during_run=stable,
        passed=stable and all(row['passed'] for row in tone_rows)
               and all(all(attempt['passed'] for attempt in row['attempts']) if cells is not None
                       else row['runtime_fixed_passed'] for row in results),
        minimal_runtime_layout=complete and not fixed_only and cells is None and all(
            row['selected_cells'] == row['runtime_cells'] for row in results))
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir/'report.json').write_text(json.dumps(report, indent=2, allow_nan=False)+'\n')
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', required=True, type=Path)
    parser.add_argument('--cases', nargs='+')
    parser.add_argument('--fields', nargs='+', choices=tuple(FIELD_CELLS))
    parser.add_argument('--fixed-only', action='store_true')
    parser.add_argument('--cells', nargs='+', type=int, help='Explicit supported grids to inspect, without scalar selection')
    parser.add_argument('--complete-diagnostics', action='store_true',
                        help='Traverse every requested grid, function and probe, retaining complete scalar failures')
    args = parser.parse_args(argv)
    report = run(args.output_dir, cases=args.cases, fields=args.fields, fixed_only=args.fixed_only,
                 cells=args.cells, complete_diagnostics=args.complete_diagnostics)
    if not report['passed']:
        raise SystemExit('Field accuracy audit failed; inspect report.json')


if __name__ == '__main__':
    main()
