"""CPU local-stage diagnostics for smaller Color and compact Adaptance fields.

Each native layout receives the same independently rounded float32 stage input
and frozen selectors. This is an accuracy report, not a performance benchmark;
it does not alter runtime layouts or the scalar/local acceptance policies.
"""
import argparse
from dataclasses import asdict
from functools import partial
import hashlib
import importlib
import json
import os
from pathlib import Path
import platform
import sys

import numpy as np

from color_tools.kernel import prepare
from color_tools.kernel.layouts import FIELD_CELLS, supported_cells
from color_tools.perceptual_grade_reference import grading
from color_tools.perceptual_grade_reference.responses import State
from . import cases, full_cases, oracle
from .evaluate import evidence_hashes
from .field_effects import ATTRIBUTES, _candidate
from .gpu_report import _json_values


DEFAULT_CELLS = {'Color coefficients': (16384, 8192),
                 'Adaptance parameters': (8192, 4096, 2048)}
STAGES = {'Color coefficients': 'terms', 'Adaptance parameters': 'adaptance'}
DEFAULT_CASES = ('all_active', 'saturation', 'all_active_saturation',
                 'all_families_max', 'all_families_max_active_tail',
                 'lightness_fit_6', 'chroma_fit_6', 'web_alternating_extremes',
                 'adaptance')
STRICT_UNSATURATED_CASES = frozenset(('all_active', 'lightness_fit_6',
                                    'chroma_fit_6', 'web_alternating_extremes',
                                    'adaptance'))
LOCAL_LIMIT = 1e-5
SAMPLES = 256
THREADS = 8
CONTEXTS = ('shader', 'compositor')


def _hash(data):
    return hashlib.sha256(data).hexdigest()


def _identity():
    modules = [importlib.import_module(__package__+'.'+name) for name in (
        'color_field_local', 'color_local', 'field_effects', 'full_cases',
        'cases', 'oracle', 'native', 'gate_policy', 'gpu_report')]
    return dict(**evidence_hashes(), local_tool_sha256={
        Path(module.__file__).name: _hash(Path(module.__file__).read_bytes())
        for module in modules})


def _witness(index, inputs, frozen, source, expected, actual, errors):
    if index is None:
        return None
    return dict(index=int(index), input=inputs[index].tolist(),
                frozen=frozen[index].tolist(),
                reference_input=source.q[index].tolist(),
                input_energy=float(source.energy[index]),
                reference_q=expected.q[index].tolist(),
                native_q=actual['rgb'][index].tolist(),
                reference_energy=float(expected.energy[index]),
                native_energy=float(actual['valid'][index]),
                native_saturated=float(actual['saturated'][index]),
                errors={name: float(value[index]) for name, value in errors.items()})


def _assessment(actual, source, expected, inputs, frozen, case, stage):
    """Retain the existing identical-handoff gate and its comparison masks."""
    limit = np.finfo(np.float32).max
    ci = np.hypot(source.q[:, 1], source.q[:, 2])
    co = np.hypot(expected.q[:, 1], expected.q[:, 2])
    se = 1+abs(source.energy)+abs(expected.energy)+66*(ci+co)
    sh = 1+np.sqrt(abs(source.energy)+66*ci)+np.sqrt(abs(expected.energy)+66*co)
    sc = 1+ci+co
    with np.errstate(over='ignore', invalid='ignore', divide='ignore'):
        errors = dict(h=abs(actual['rgb'][:, 0]-expected.q[:, 0])/sh,
                      ab=np.hypot(*(actual['rgb'][:, 1:]-expected.q[:, 1:]).T)/sc,
                      energy=abs(actual['valid']-expected.energy)/se,
                      energy_absolute=abs(actual['valid']-expected.energy))
    overflow = ((abs(expected.energy) > limit) |
                np.any(abs(expected.q) > limit, axis=-1))
    finite_reference = (np.isfinite(expected.energy) &
                        np.isfinite(expected.q).all(axis=-1))
    saturated = actual['saturated'] > .5
    finite = (~saturated & ~overflow & finite_reference)
    output_finite = {key: bool(np.isfinite(actual[key]).all())
                     for key in ('rgb', 'valid', 'alpha', 'margin', 'saturated')}
    nonfinite = np.zeros(len(inputs), dtype=bool)
    for key in output_finite:
        values = np.isfinite(actual[key])
        nonfinite |= ~values.all(axis=-1) if values.ndim > 1 else ~values
    state = oracle.state_metrics(actual['rgb'][finite], actual['valid'][finite],
        expected.q[finite], expected.energy[finite], source.q[finite], source.energy[finite])
    all_state = oracle.state_metrics(actual['rgb'], actual['valid'], expected.q,
        expected.energy, source.q, source.energy)
    significant = abs(expected.energy) > LOCAL_LIMIT*se
    sign_mismatch = significant & (np.sign(actual['valid']) != np.sign(expected.energy))
    overflow_flag_mismatch = overflow & ~saturated
    energy_overflow = abs(expected.energy) > limit
    saturated_energy_sign_mismatch = energy_overflow & (
        np.sign(actual['valid']) != np.sign(expected.energy))
    black = (np.all(source.q == 0., axis=-1) & (source.energy == 0.) &
             np.all(expected.q == 0., axis=-1) & (expected.energy == 0.))
    black_changed = black & (np.any(actual['rgb'] != 0., axis=-1) |
                             (actual['valid'] != 0.) | saturated)
    representable = ~overflow & (co <= limit)
    # Terms require an unflagged result for every representable state. The
    # extreme Adaptance cases retain the existing native-stage masking policy;
    # candidate-versus-baseline flag changes are separately rejected below.
    must_be_unsaturated = (np.ones(len(inputs), dtype=bool)
                          if case in STRICT_UNSATURATED_CASES else
                          representable if stage == 'terms' else
                          np.zeros(len(inputs), dtype=bool))
    unexpected_saturation = must_be_unsaturated & saturated
    precision_passed = (bool(finite.any()) and all(
        np.isfinite(state[name]) and state[name] <= LOCAL_LIMIT
        for name in ('h', 'ab', 'energy')))
    safety_passed = (all(output_finite.values()) and bool(finite_reference.all())
                     and not np.any(overflow_flag_mismatch)
                     and not np.any(saturated_energy_sign_mismatch)
                     and not np.any(black_changed)
                     and not np.any(unexpected_saturation)
                     and state['significant_sign_mismatches'] == 0)
    worst = {}
    for name, values in errors.items():
        indices = np.flatnonzero(finite & np.isfinite(values))
        index = int(indices[np.argmax(values[indices])]) if len(indices) else None
        worst[name] = _witness(index, inputs, frozen, source, expected, actual, errors)
    return dict(state=state, all_state=all_state, finite_samples=int(finite.sum()),
                state_error_limit=LOCAL_LIMIT, precision_passed=precision_passed,
                safety_passed=safety_passed, local_passed=bool(precision_passed and safety_passed),
                output_finite=output_finite, reference_finite=bool(finite_reference.all()),
                nonfinite_output_indices=np.flatnonzero(nonfinite).tolist(),
                finite_comparison_indices=np.flatnonzero(finite).tolist(),
                reference_overflow_indices=np.flatnonzero(overflow).tolist(),
                saturated_indices=np.flatnonzero(saturated).tolist(),
                overflow_flag_mismatch_indices=np.flatnonzero(overflow_flag_mismatch).tolist(),
                saturated_energy_sign_mismatch_indices=np.flatnonzero(saturated_energy_sign_mismatch).tolist(),
                exact_black_indices=np.flatnonzero(black).tolist(),
                changed_exact_black_indices=np.flatnonzero(black_changed).tolist(),
                unexpected_saturation_indices=np.flatnonzero(unexpected_saturation).tolist(),
                significant_sign_indices=np.flatnonzero(significant).tolist(),
                significant_sign_mismatch_indices=np.flatnonzero(sign_mismatch).tolist(),
                worst=worst)


def _native_image(fixture, table):
    expected = np.asarray(table.pixels, dtype=np.float32)
    digest = _hash(expected.tobytes())
    images = []
    for image in fixture.built.images:
        pixels = np.empty(int(image.size[0])*int(image.size[1])*4, dtype=np.float32)
        image.pixels.foreach_get(pixels)
        if _hash(pixels.tobytes()) == digest:
            images.append((image, pixels))
    if not images:
        return None
    if len(images) != 1:
        raise AssertionError('Ambiguous native field payload')
    image, pixels = images[0]
    if list(image.size) != [expected.shape[1], expected.shape[0]]:
        raise AssertionError('Native image dimensions differ from the prepared field')
    if not np.array_equal(pixels, expected.ravel()):
        raise AssertionError('Native image content differs from the prepared field')
    return dict(name=image.name, role=table.name, cells=table.cells,
                size=list(image.size), bytes=int(pixels.nbytes),
                pixels_sha256=digest, verified=True, is_float=bool(image.is_float),
                use_half_precision=bool(image.use_half_precision),
                colorspace=image.colorspace_settings.name, alpha_mode=image.alpha_mode)


def _render(prepared, role, stage, inputs, frozen, source, expected, context, case, threads):
    from .color_local import stage_builder, connect_frozen
    from .native import NativeFixture
    fixture = NativeFixture(prepared, inputs, context, engine='CYCLES', device='CPU',
        precision='FULL', threads=threads,
        builder=partial(stage_builder, isolated=True, stage=stage, local=True))
    try:
        execution = dict(backend='cpu', engine=fixture.scene.render.engine,
            compositor_device=fixture.scene.render.compositor_device,
            compositor_precision=fixture.scene.render.compositor_precision,
            requested_threads=threads, native_threads=fixture.scene.render.threads,
            native_threads_mode=fixture.scene.render.threads_mode)
        image = _native_image(fixture, getattr(prepared.color, ATTRIBUTES[role]))
        if image is None:
            return None, dict(status='not_sampled', execution=execution,
                reason='The active local stage omits this field in its selected precision path.',
                native_image_names=[image.name for image in fixture.built.images])
        connect_frozen(fixture, frozen)
        actual = fixture.render()
        assessment = _assessment(actual, source, expected, inputs, frozen, case, stage)
        return actual, dict(status='measured', execution=execution, image=image,
                            stats=actual['stats'], **assessment)
    finally:
        fixture.close()


def _incremental(actual, baseline, source, expected):
    ci = np.hypot(source.q[:, 1], source.q[:, 2])
    co = np.hypot(expected.q[:, 1], expected.q[:, 2])
    delta_q = abs(actual['rgb']-baseline['rgb'])
    delta_energy = abs(actual['valid']-baseline['valid'])
    sh = 1+np.sqrt(abs(source.energy)+66*ci)+np.sqrt(abs(expected.energy)+66*co)
    se = 1+abs(source.energy)+abs(expected.energy)+66*(ci+co)
    with np.errstate(over='ignore', invalid='ignore', divide='ignore'):
        errors = dict(h=delta_q[:, 0]/sh,
            ab=np.hypot(*(actual['rgb'][:, 1:]-baseline['rgb'][:, 1:]).T)/(1+ci+co),
            energy=delta_energy/se)
    return dict(max_normalized={key: float(np.max(value, initial=0)) for key, value in errors.items()},
        changed_saturation_indices=np.flatnonzero(
            (actual['saturated'] > .5) != (baseline['saturated'] > .5)).tolist(),
        changed_energy_sign_indices=np.flatnonzero(
            np.sign(actual['valid']) != np.sign(baseline['valid'])).tolist())


def _markdown(report):
    lines = ['# Smaller Color fields at identical float32 local handoffs', '',
        'CPU accuracy only; no preparation, rendering or interactive performance claim.', '',
        f"Complete: **{report['complete']}**. Sources stable: **{report['sources_stable_during_run']}**.", '',
        '| Case | Space | Context | Field | Cells | Status | Scalar gate | H / opponent / energy | Local gate | Changed flags |',
        '|---|---|---|---|---:|---|---|---|---|---:|']
    for row in (*report['baselines'], *report['rows']):
        state = row.get('state', {})
        errors = ' / '.join(f'{state[name]:.9g}' for name in ('h', 'ab', 'energy')) if state else '—'
        flags = len(row.get('incremental', {}).get('changed_saturation_indices', []))
        scalar = row.get('texture', {}).get('field_passed', '—')
        cells = row.get('cells', '—')
        label = row['role']+(' (baseline)' if row.get('baseline') else '')
        lines.append(f"| {row['case']} | {row['space']} | {row['context']} | {label} | "
            f"{cells} | {row['status']} | {scalar} | {errors} | {row.get('local_passed', '—')} | {flags} |")
    lines += ['', *report['limitations'], '']
    return '\n'.join(lines)


def run(output_dir, *, fields=tuple(DEFAULT_CELLS), cells=None, selected_cases=DEFAULT_CASES,
        spaces=('Linear Rec.709',), full_fields=False):
    import bpy
    from .color_local import local_color_frames, rounded_state
    fields, selected_cases = tuple(fields), tuple(selected_cases)
    if not fields or set(fields)-set(DEFAULT_CELLS):
        raise ValueError('Select Color coefficients and/or Adaptance parameters')
    corpus = {row[0]: row for row in (*full_cases.grades(), *full_cases.ui_boundaries())}
    if not selected_cases or set(selected_cases)-set(corpus):
        raise ValueError('Select known nonempty cases')
    selection = {role: tuple(DEFAULT_CELLS[role] if cells is None else sorted(set(cells), reverse=True))
                 for role in fields}
    for role, sizes in selection.items():
        if not sizes or any(size not in supported_cells(role) or size >= FIELD_CELLS[role]
                            for size in sizes):
            raise ValueError('Select supported cells below the current field size')
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    identities = _identity()
    report = dict(schema=1, **identities,
        scope='Finite retained CPU local-stage corpus at identical float32 handoffs; no runtime changes',
        request=dict(fields=list(fields), cells={role: list(sizes) for role, sizes in selection.items()},
            cases=list(selected_cases), spaces=list(spaces), contexts=list(CONTEXTS),
            samples=SAMPLES, threads=THREADS, full_fields=bool(full_fields)),
        runtime_layout=dict(FIELD_CELLS), state_error_limit=LOCAL_LIMIT,
        execution=dict(blender=bpy.app.version_string, python=sys.version,
            executable=sys.executable, numpy=np.__version__, platform=platform.platform(),
            cpu_affinity=sorted(os.sched_getaffinity(0)) if hasattr(os, 'sched_getaffinity') else None,
            environment={name: os.environ.get(name) for name in
                         ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'LP_NUM_THREADS')}),
        limitations=['This finite local-stage corpus does not establish continuous-control or full-grade acceptance.',
            'Scalar audits preserve their original early-stop failures and limits; partial witnesses are not global maxima.',
            'An omitted compact field is explicitly not sampled and supplies no evidence for its layout.',
            'Every candidate uses the same independently rounded reference-stage input and frozen selectors as its baseline.',
            'Raw full-state errors and native saturation masks are retained alongside the unchanged finite-state comparison mask.',
            'The local-stage graph node count is diagnostic and cannot establish the complete Grade node budget.',
            'This accuracy run makes no timing claim.'], baselines=[], rows=[], complete=False)

    def checkpoint():
        report['sources_stable_during_run'] = identities == _identity()
        (output_dir/'report.json').write_text(json.dumps(_json_values(report), indent=2, allow_nan=False)+'\n')
        (output_dir/'report.md').write_text(_markdown(report))

    for case in selected_cases:
        _, linear, tone, color = corpus[case]
        for space in spaces:
            prepared = prepare(linear, tone, space, color=color, full_fields=full_fields)
            reference = grading.Color(grading.ColorSettings(**asdict(color)),
                                      grading.Tone(grading.ToneSettings(**asdict(tone))))
            values = full_cases.rgba(space, SAMPLES)
            tone_state = oracle.evaluate(values[:, :3], linear, tone, space)['tone']
            initial = State(tone_state.q, tone_state.ja*abs(tone_state.ja))
            frames = {stage: (source, expected, frozen.copy())
                      for stage, source, expected, frozen, _ in local_color_frames(reference, initial)}
            for role in fields:
                stage = STAGES[role]
                active = ((prepared.color.lightness_active or prepared.color.chroma_active)
                          if stage == 'terms' else prepared.color.adaptance_active)
                base_key = dict(case=case, space=space, role=role, stage=stage,
                    settings=dict(linear=asdict(linear), tone=asdict(tone), color=asdict(color)),
                    input_rgba_sha256=_hash(values.tobytes()))
                if not active:
                    for context in CONTEXTS:
                        report['baselines'].append(dict(**base_key, context=context, baseline=True,
                            cells=FIELD_CELLS[role], status='inactive_stage'))
                        for size in selection[role]:
                            report['rows'].append(dict(**base_key, context=context, cells=size,
                                status='inactive_stage', reason='The target stage is inactive for these settings.'))
                    checkpoint()
                    continue
                if getattr(prepared.color, ATTRIBUTES[role]) is None:
                    reason = 'The specialized preparation omits this field for the selected controls.'
                    for context in CONTEXTS:
                        report['baselines'].append(dict(**base_key, context=context, baseline=True,
                            cells=FIELD_CELLS[role], status='not_sampled', reason=reason))
                        for size in selection[role]:
                            report['rows'].append(dict(**base_key, context=context, cells=size,
                                status='not_sampled', reason=reason))
                    checkpoint()
                    continue
                source, expected, frozen = frames[stage]
                inputs, source = rounded_state(source)
                base_key.update(input_state_sha256=_hash(inputs.tobytes()),
                    frozen_sha256=_hash(frozen.tobytes()),
                    reference_q_sha256=_hash(np.asarray(expected.q).tobytes()),
                    reference_energy_sha256=_hash(np.asarray(expected.energy).tobytes()))
                baseline_prepared, baseline_texture = _candidate(prepared, role, FIELD_CELLS[role])
                original = getattr(prepared.color, ATTRIBUTES[role])
                if baseline_texture['pixels_sha256'] != _hash(original.pixels.tobytes()):
                    raise AssertionError('Audited baseline differs from the current runtime field')
                candidates = [(size, *_candidate(prepared, role, size)) for size in selection[role]]
                for context in CONTEXTS:
                    baseline, result = _render(baseline_prepared, role, stage, inputs, frozen,
                        source, expected, context, case, THREADS)
                    baseline_row = dict(**base_key, context=context, baseline=True,
                        cells=FIELD_CELLS[role], texture=baseline_texture, **result)
                    report['baselines'].append(baseline_row)
                    checkpoint()
                    for size, candidate, texture in candidates:
                        actual, result = _render(candidate, role, stage, inputs, frozen,
                            source, expected, context, case, THREADS)
                        row = dict(**base_key, context=context, cells=size, texture=texture, **result)
                        if actual is not None and baseline is not None:
                            incremental = _incremental(actual, baseline, source, expected)
                            row['incremental'] = incremental
                            row['saturation_matches_baseline'] = not incremental['changed_saturation_indices']
                            row['local_admission_passed'] = bool(result['local_passed']
                                and baseline_row['local_passed'] and row['saturation_matches_baseline'])
                            row['scalar_and_local_passed'] = bool(row['local_admission_passed']
                                and texture['field_passed'] and baseline_texture['field_passed'])
                        print(f"{case} {space} {context} {role}/{size}: "
                              f"{row['status']} local={row.get('local_passed')} "
                              f"scalar={texture['field_passed']}", flush=True)
                        report['rows'].append(row)
                        checkpoint()
    report['complete'] = True
    measured = [row for row in report['rows'] if row['status'] == 'measured']
    report['summary'] = dict(baselines=len(report['baselines']), candidates=len(report['rows']),
        measured_candidates=len(measured),
        local_failures=sum(not row['local_passed'] for row in measured),
        scalar_failures=sum(not row['texture']['field_passed'] for row in measured),
        changed_saturation_rows=sum(not row.get('saturation_matches_baseline', False) for row in measured),
        scalar_and_local_passed=bool(measured) and all(row.get('scalar_and_local_passed', False) for row in measured))
    checkpoint()
    if not report['sources_stable_during_run']:
        raise RuntimeError('Sources changed during local-stage diagnostics')
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', required=True, type=Path)
    parser.add_argument('--fields', nargs='+', choices=tuple(DEFAULT_CELLS), default=list(DEFAULT_CELLS))
    parser.add_argument('--cells', nargs='+', type=int)
    parser.add_argument('--cases', nargs='+', default=list(DEFAULT_CASES))
    parser.add_argument('--spaces', nargs='+', choices=cases.SPACES, default=['Linear Rec.709'])
    parser.add_argument('--full-fields', action='store_true',
                        help='Diagnostic persistent preparation; default matches the specialized local-stage regression')
    args = parser.parse_args(argv)
    run(args.output_dir, fields=args.fields, cells=args.cells, selected_cases=args.cases,
        spaces=args.spaces, full_fields=args.full_fields)


if __name__ == '__main__':
    main()
