"""Audit-only internal-state perturbation propagation through the reference.

This is a controlled sensitivity experiment, not a native implementation test or
an alternate table-size acceptance report. It injects errors at one handoff and
uses the unchanged independent reference for all downstream operations. Runtime
layouts, thresholds and the reference equations are never changed.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import importlib
import json
from pathlib import Path
import platform
import sys
import time

import numpy as np
from color_tools.perceptual_grade_reference import grading, model
from color_tools.perceptual_grade_reference.responses import State, requested_energy, signed_hk
from color_tools.perceptual_grade_reference.cube_guard import guard as cube_guard
from color_tools.perceptual_grade_core.model.hk_guard import guard as hk_guard
from . import cases, full_cases, oracle

STAGES = ('linear_encoder', 'tone', 'color_terms', 'web_parameters', 'web_toes',
          'web', 'adaptance', 'final_scale', 'hk', 'boundary')
DEFAULT_CASES = ('all_active', 'saturation', 'all_active_saturation',
                 'web_alternating_extremes', 'lightness_fit_6', 'chroma_fit_6',
                 'all_families_max', 'all_families_max_active_tail')
MODES = ('h', 'a', 'b', 'energy', 'float32')


def _json(value):
    """Normalize NumPy scalars and mark nonfinite diagnostic values explicitly."""
    if isinstance(value, np.ndarray):
        return _json(value.tolist())
    if isinstance(value, np.generic):
        return _json(value.item())
    if isinstance(value, float) and not np.isfinite(value):
        return None
    if isinstance(value, dict):
        return {str(key): _json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json(item) for item in value]
    return value


def source_hashes():
    names = ('color_tools.perceptual_grade_reference.appearance',
             'color_tools.perceptual_grade_reference.responses',
             'color_tools.perceptual_grade_reference.grading',
             'color_tools.perceptual_grade_reference.model',
             'color_tools.perceptual_grade_reference.cube',
             'color_tools.perceptual_grade_reference.cube_guard',
             'color_tools.perceptual_grade_core.model.tonal_web',
             'color_tools.perceptual_grade_core.model.selective_adaptance',
             'color_tools.perceptual_grade_core.model.hk_guard',
             'color_tools.color_core.scaled',
             __package__+'.cases', __package__+'.full_cases', __package__+'.oracle')
    result = {name: hashlib.sha256(Path(importlib.import_module(name).__file__).read_bytes()).hexdigest()
              for name in names}
    result['gate_sensitivity.py'] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    return result


def _state(q, energy):
    return State(np.array(q, dtype=float, copy=True), np.array(energy, dtype=float, copy=True))


def _scales(source, expected):
    ci = np.hypot(source.q[:, 1], source.q[:, 2])
    co = np.hypot(expected.q[:, 1], expected.q[:, 2])
    return (1+np.sqrt(abs(source.energy)+66*ci)+np.sqrt(abs(expected.energy)+66*co),
            1+ci+co, 1+abs(source.energy)+abs(expected.energy)+66*(ci+co))


def _metric_arrays(actual, expected, source):
    sh, sc, se = _scales(source, expected)
    return dict(h=abs(actual.q[:, 0]-expected.q[:, 0])/sh,
                ab=np.hypot(*(actual.q[:, 1:]-expected.q[:, 1:]).T)/sc,
                energy=abs(actual.energy-expected.energy)/se)


def _metrics(actual, expected, denominator=None):
    delta = np.max(abs(actual-expected), axis=-1)
    scale = 1+np.max(abs(expected), axis=-1) if denominator is None else denominator
    errors = delta/scale
    finite = np.isfinite(errors)
    index = int(np.argmax(np.where(finite, errors, np.inf))) if len(errors) else None
    return dict(samples=len(errors), finite=bool(finite.all()),
                nonfinite_samples=int(np.sum(~finite)),
                max_normalized=float(np.max(errors[finite], initial=0)) if finite.all() else None,
                p99_normalized=float(np.percentile(errors[finite], 99)) if np.any(finite) else None,
                max_absolute=float(np.max(delta[finite], initial=0)) if finite.all() else None,
                worst_index=index), errors


def _perturb(expected, source, mode, amplitude, sign, *, boundary=False):
    actual = _state(expected.q, expected.energy)
    clipping = 0
    dose = None

    def restore_h(q, energy):
        chroma = np.hypot(q[:, 1], q[:, 2])
        ja = np.sign(energy)*np.sqrt(np.abs(energy))
        q[:, 0] = signed_hk(ja, chroma)
        return q, energy

    def energy_from_h(h, chroma):
        # Algebraically J_A*abs(J_A), using factored branches to avoid
        # cancellation between H squared and 66*C at the J_A=0 boundary.
        b = np.sqrt(np.maximum(0., 66.*chroma))
        u = h-b
        return u*(np.abs(u)+2*b)

    if boundary:
        # A boundary output is already projected. Apply a returned-radius
        # error, then decode directly: re-projection would hide the error.
        radius = np.hypot(expected.q[:, 1], expected.q[:, 2])
        if mode == 'float32':
            changed = radius.astype(np.float32).astype(float)
        else:
            changed = np.maximum(0, radius+sign*amplitude*(1+radius))
        factor = np.divide(changed, radius, out=np.ones_like(radius), where=radius > 0)
        actual.q[:, 1:] *= factor[:, None]
        q, energy = restore_h(actual.q, actual.energy)
        actual = State(q, energy)
    elif mode == 'float32':
        limit = np.finfo(np.float32).max
        clipping = int(np.sum(np.any(abs(actual.q)>limit, axis=-1) | (abs(actual.energy)>limit)))
        q = np.clip(actual.q, -limit, limit).astype(np.float32).astype(float)
        energy = np.clip(actual.energy, -limit, limit).astype(np.float32).astype(float)
        q, energy = restore_h(q, energy)
        actual = State(q, energy)
    else:
        sh, sc, se = _scales(source, expected)
        q = np.array(actual.q, copy=True)
        energy = np.array(actual.energy, copy=True)
        if mode == 'energy':
            energy += sign*amplitude*se
        else:
            column = {'h': 0, 'a': 1, 'b': 2}[mode]
            if mode == 'h':
                target_h = q[:, 0] + sign*amplitude*sh
                chroma = np.hypot(q[:, 1], q[:, 2])
                q[:, 0] = target_h
                energy = energy_from_h(target_h, chroma)
            else:
                q[:, column] += sign*amplitude*sc
        q, energy = restore_h(q, energy)
        if mode == 'h':
            residual = abs(q[:, 0]-target_h)
            b = np.sqrt(66*np.hypot(q[:, 1], q[:, 2]))
            stability_bound = 128*np.finfo(float).eps*(1+abs(target_h)+2*b)
            worst = int(np.argmax(residual/stability_bound))
            dose = dict(metric='H / conditioned S_H',
                        intended_signed=sign*amplitude,
                        realized_signed_min=float(np.min((q[:, 0]-expected.q[:, 0])/sh)),
                        realized_signed_max=float(np.max((q[:, 0]-expected.q[:, 0])/sh)),
                        max_realization_error=float(np.max(residual/sh)),
                        max_float64_stability_bound=float(np.max(stability_bound/sh)),
                        max_residual_over_stability_bound=float(np.max(residual/stability_bound)),
                        worst_index=worst)
            if np.any(residual > stability_bound):
                raise AssertionError(f'H inverse exceeds conditioned float64 stability: {dose}')
        actual = State(q, energy)
    implied = signed_hk(np.sign(actual.energy)*np.sqrt(np.abs(actual.energy)),
                        np.hypot(actual.q[:, 1], actual.q[:, 2]))
    consistency = np.max(np.abs(actual.q[:, 0]-implied)/(1+np.abs(actual.q[:, 0])), initial=0.)
    if not boundary and consistency > 5e-12:
        raise AssertionError(f'Perturbed state violates H-K consistency: {consistency:g}')
    return actual, clipping, dose


def compose(reference, encoded, *, stage=None, mode=None, amplitude=0., sign=1):
    """Compose exact reference stages with one optional post-stage injection.

    Terms reproduce the reference's short term-expression using reference
    coefficient/driver/energy functions. Web's transform callback preserves its
    exact pre-Adaptance scale selection, Adaptance, and final-scale ordering.
    """
    tone, color = reference.tone, reference.color
    source = _state(encoded.q, encoded.ja*abs(encoded.ja))
    captured = {}

    def handoff(name, previous, expected):
        if stage != name:
            return expected
        changed, clipped, dose = _perturb(expected, previous, mode, amplitude, sign,
                                         boundary=name == 'boundary')
        captured.update(source=previous, expected=expected, actual=changed,
                        clipped_to_float32_samples=clipped, h_dose_realization=dose)
        return changed

    source = handoff('linear_encoder', source, source)
    toned = tone.apply(source)
    tone_state = handoff('tone', source, _state(toned.q, toned.ja*abs(toned.ja)))
    c0 = np.hypot(tone_state.q[:, 1], tone_state.q[:, 2])
    h0 = np.hypot(tone_state.ja, np.sqrt(66*c0))
    e0 = tone_state.energy
    p = color.settings
    if any(np.any(value) for value in (p.lightness, p.chroma, p.global_gain)):
        light, chroma = color.terms(h0)
        drivers = grading.drivers(tone_state.q, tone_state.ja)
        gain = np.exp2(p.global_gain+np.sum(chroma*drivers, axis=-1))
        q = np.column_stack((tone_state.q[:, 0]+np.sum(light*drivers, axis=-1),
                             tone_state.q[:, 1:]*gain[:, None]))
        q = np.where((h0 == 0)[:, None], tone_state.q, q)
        energy = np.where(np.all(q == tone_state.q, axis=-1), e0,
                          requested_energy(q, tone_state.q, tone_state.ja))
        terms = _state(q, energy)
    else:
        terms = _state(tone_state.q, e0)
    terms = handoff('color_terms', tone_state, terms)
    adaptation_output = []
    baseline_web_capture = {}
    original_parameters = color.web.parameters
    def capture_web(q, energy):
        baseline_web_capture['state'] = _state(q, energy)
        return q, energy

    color.web.apply(terms.q, terms.energy, h0, transform=capture_web)
    if stage in ('web_parameters', 'web_toes'):
        base_parameters = original_parameters

        def candidate_parameters(height):
            result = {key: np.array(value, copy=True) if isinstance(value, np.ndarray) else value
                      for key, value in base_parameters(height).items()}
            if stage == 'web_parameters':
                result['target_angles'] = result['target_angles'] + sign*amplitude
                result['chroma_coefficients'] = result['chroma_coefficients']*np.exp(sign*amplitude)
                result['scale_coefficients'] = result['scale_coefficients']*np.exp(sign*amplitude)
            else:
                for name in ('angular_toe', 'chroma_toe', 'scale_toe'):
                    result[name] = result[name]*np.exp(sign*amplitude)
            return result

        # A private per-instance override exercises the same reference web
        # equations with altered generated parameters; no production constant
        # or shared class method is changed.
        color.web.parameters = candidate_parameters

    def adapt(q, energy):
        web = _state(q, energy)
        if stage == 'web':
            web = handoff('web', terms, web)
        elif stage in ('web_parameters', 'web_toes'):
            captured.update(source=terms, expected=baseline_web_capture['state'], actual=web,
                            clipped_to_float32_samples=0)
        aq, ae = color.adaptation.apply(web.q, web.energy, h0, c0, e0)
        result = handoff('adaptance', web, _state(aq, ae))
        adaptation_output.append(result)
        return result.q, result.energy

    try:
        q, energy = color.web.apply(terms.q, terms.energy, h0, transform=adapt)
    finally:
        color.web.parameters = original_parameters
    raw = handoff('final_scale', adaptation_output[0], _state(q, energy))
    q, energy = hk_guard(raw.q, raw.energy, e0)
    guarded = handoff('hk', raw, _state(q, energy))
    boundary = oracle.exact_boundary(reference)
    q, energy, native = cube_guard(boundary, guarded.q, guarded.energy)
    projected = handoff('boundary', guarded, _state(q, energy))
    decode_failures = np.zeros(len(q), bool)
    if stage == 'boundary':
        response = boundary.responses(projected.q, projected.energy)
        safe = np.isfinite(response).all(axis=-1) & np.all(abs(response)<400, axis=-1)
        native = np.full_like(projected.q, np.nan)
        if np.any(safe):
            native[safe] = boundary.decode(projected.q[safe], projected.energy[safe])
        decode_failures = ~safe | ~np.isfinite(native).all(axis=-1)
    to_scene = reference.xyz_to_rgb @ reference.cones_to_xyz @ np.linalg.inv(boundary.matrix)
    output = native[:, 1, None]+(native-native[:, 1, None]) @ to_scene.T
    finite = np.isfinite(native).all(axis=-1)
    legal = finite & np.all((native >= 0) & (native <= 1024), axis=-1)
    return dict(rgb=output, native=native, state=projected, capture=captured,
                legal=legal, decode_failures=decode_failures,
                black=projected.energy <= 0, white=projected.energy >= boundary.white**2,
                projected=np.any(q != guarded.q, axis=-1))


def _row(case, space, values, baseline, oracle_rgb, candidate, stage, mode, amplitude, sign):
    captured = candidate['capture']
    local = _metric_arrays(captured['actual'], captured['expected'], captured['source'])
    local_max = np.maximum.reduce(tuple(local.values()))
    if stage == 'boundary':
        radius = np.hypot(captured['expected'].q[:, 1], captured['expected'].q[:, 2])
        local_max = abs(np.hypot(captured['actual'].q[:, 1], captured['actual'].q[:, 2])-radius)/(1+radius)
    metric, final = _metrics(candidate['rgb'], baseline['rgb'], 1+np.max(abs(oracle_rgb), axis=-1))
    total_metric, _ = _metrics(candidate['rgb'], oracle_rgb)
    finite = np.isfinite(final)
    internal_failure = local_max > (2e-5 if stage == 'boundary' else 1e-5)
    small_final = finite & (final <= 1e-5)
    _, _, energy_scale = _scales(captured['source'], captured['expected'])
    sign_mismatches = ((abs(captured['expected'].energy) > 1e-5*energy_scale)
                      & (np.sign(captured['actual'].energy) != np.sign(captured['expected'].energy)))
    index = metric['worst_index']
    local_index = int(np.argmax(local_max))
    large_hidden = internal_failure & small_final
    hidden_index = int(np.argmax(np.where(large_hidden, local_max, -1))) if np.any(large_hidden) else None

    def witness(i):
        if i is None:
            return None
        return dict(index=i, rgb_input=values[i, :3].tolist(),
                    expected_state=captured['expected'].q[i].tolist(),
                    actual_state=captured['actual'].q[i].tolist(),
                    expected_energy=float(captured['expected'].energy[i]),
                    actual_energy=float(captured['actual'].energy[i]),
                    local_error=float(local_max[i]),
                    added_final_error=float(final[i]) if np.isfinite(final[i]) else None,
                    baseline_rgb=baseline['rgb'][i].tolist(),
                    candidate_rgb=candidate['rgb'][i].tolist() if finite[i] else None,
                    baseline_black=bool(baseline['black'][i]), baseline_white=bool(baseline['white'][i]),
                    baseline_projected=bool(baseline['projected'][i]),
                    candidate_black=bool(candidate['black'][i]),
                    candidate_white=bool(candidate['white'][i]),
                    candidate_projected=bool(candidate['projected'][i]),
                    candidate_legal=bool(candidate['legal'][i]))

    parameter_error = ({'angle_absolute_radians': abs(amplitude),
                        'radial_log_coefficient_absolute': abs(amplitude),
                        'radial_coefficient_relative': abs(float(np.expm1(sign*amplitude)))}
                       if stage == 'web_parameters' else
                       {'positive_toe_relative': abs(float(np.expm1(sign*amplitude)))}
                       if stage == 'web_toes' else None)
    return dict(status='evaluated', case=case, space=space, stage=stage, mode=mode,
                amplitude=amplitude, sign=sign, local_metrics={k: float(np.max(v)) for k,v in local.items()},
                injected_parameter_error=parameter_error,
                h_dose_realization=captured.get('h_dose_realization'),
                local_error_max=float(np.max(local_max)),
                local_diagnostic_threshold=(2e-5 if stage == 'boundary' else 1e-5),
                local_error_metric=('abs(delta_radius)/(1+reference_radius)' if stage == 'boundary'
                                    else 'max conditioned H/opponent/energy state errors'),
                added_final_rgb=metric, total_final_rgb=total_metric,
                illegal_native_samples=int(np.sum(~candidate['legal'])),
                decode_failure_samples=int(np.sum(candidate['decode_failures'])),
                clipped_to_float32_samples=captured['clipped_to_float32_samples'],
                significant_energy_sign_mismatches=int(np.sum(sign_mismatches)),
                internal_state_above_diagnostic_threshold_samples=int(np.sum(internal_failure)),
                internal_failure_with_added_rgb_below_1e5_samples=int(np.sum(large_hidden)),
                internal_failure_small_rgb_and_legal_samples=int(np.sum(large_hidden & candidate['legal'])),
                large_internal_at_least_1e2_small_final_samples=int(np.sum((local_max >= .01*(1-1e-12)) & small_final)),
                small_internal_large_final_samples=int(np.sum((local_max <= 1e-5) & (final > 1e-5))),
                worst_final=witness(index), worst_internal=witness(local_index),
                largest_hidden_internal=witness(hidden_index))


def run(output_dir, *, samples=256, amplitudes=(1e-5, 1e-3, 1e-2),
        stages=STAGES, selected=DEFAULT_CASES, spaces=('Linear Rec.709',), modes=MODES):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    hashes = source_hashes()
    began = time.perf_counter()
    corpus = list(full_cases.grades())+list(full_cases.ui_boundaries())
    by_name = {row[0]: row for row in corpus}
    missing = set(selected)-set(by_name)
    if missing:
        raise ValueError(f'Unknown cases: {sorted(missing)}')
    corpus = [by_name[name] for name in selected]
    rows, baselines = [], []
    for space in spaces:
        values = full_cases.rgba(space, samples)
        for name, linear, tone, color in corpus:
            reference = model.Model(model.Settings(linear=model.LinearSettings(**asdict(linear)),
                tone=grading.ToneSettings(**asdict(tone)), color=grading.ColorSettings(**asdict(color))), space)
            expected = oracle.evaluate_full(values[:, :3], linear, tone, color, space)
            baseline = compose(reference, expected['encoded'])
            agreement, _ = _metrics(baseline['rgb'], expected['rgb'])
            if not agreement['finite'] or agreement['max_normalized'] > 1e-10:
                raise AssertionError(f'Unperturbed decomposition differs from full oracle: {name}/{space}: {agreement}')
            baselines.append(dict(case=name, space=space, against_full_oracle=agreement,
                                  rgba_sha256=hashlib.sha256(values.tobytes()).hexdigest(),
                                  linear=asdict(linear), tone=asdict(tone), color=asdict(color)))
            for stage in stages:
                stage_modes = (('radius', 'float32') if stage == 'boundary' else
                               ('parameter',) if stage in ('web_parameters', 'web_toes') else modes)
                for mode in stage_modes:
                    experiments = [(0., 0)] if mode == 'float32' else [(e, sign) for e in amplitudes for sign in (-1, 1)]
                    for amplitude, sign in experiments:
                        try:
                            with np.errstate(over='raise', invalid='raise', divide='raise'):
                                candidate = compose(reference, expected['encoded'], stage=stage, mode=mode,
                                                    amplitude=amplitude, sign=sign)
                                row = _row(name, space, values, baseline, expected['rgb'], candidate,
                                           stage, mode, amplitude, sign)
                        except (ArithmeticError, ValueError) as error:
                            row = dict(status='propagation_failed', case=name, space=space,
                                       stage=stage, mode=mode, amplitude=amplitude, sign=sign,
                                       error_type=type(error).__name__, error=str(error),
                                       affected_samples=samples)
                        rows.append(row)
                print(f'{space} {name} {stage}: {len(rows)} perturbation rows', flush=True)
            (output_dir/'rows.partial.json').write_text(json.dumps(_json(rows), indent=2, allow_nan=False)+'\n')
    stable = hashes == source_hashes()
    report = dict(schema=1, kind='controlled_reference_handoff_sensitivity',
        source_sha256=hashes, sources_stable_during_run=stable, seconds=time.perf_counter()-began,
        interpreter=sys.version, executable=sys.executable, numpy_version=np.__version__,
        platform=platform.platform(),
        samples_per_case=samples, stages=list(stages), amplitudes=list(amplitudes), modes=list(modes),
        baselines=baselines, rows=rows,
        contract=('One post-stage H, a, b or carried-energy perturbation at a time, with +/- amplitude '
                  'in conditioned Color-state diagnostic units (also used here to compare Tone and H-K). '
                  'Web-parameter experiments apply a uniform target-angle error in radians and absolute '
                  'log errors to both radial coefficient families. Web-toe experiments apply the same '
                  'log-relative error to all three positive toes. The parameter functions are restored '
                  'after each experiment; local metrics separately measure the resulting Web state. '
                  'The 1e-5 diagnostic comparison threshold is not the original Tone scalar or H-K '
                  'coordinate gate. Every modified H/a/b/energy handoff restores the signed H-K identity. '
                  'Boundary uses the original radius units. Float32 mode rounds/clamps carried opponent/energy values then restores H; it is not a native-graph simulation. '
                  'Frozen post-Tone selectors are preserved '
                  'after Color begins. Boundary mode perturbs the returned radius and decodes without '
                  'a second guard; illegal and pole results remain failures. The unperturbed decomposition '
                  'must match the independent full oracle within 1e-10 normalized RGB.'),
        limitations=('Controlled state perturbations do not establish attainable table errors, model all '
                     'correlations of native rounding, or certify any gate relaxation. Tone results use '
                     'state-handoff metrics, not its scalar-table gate; H-K state metrics likewise differ '
                     'from its coordinate and energy gates. Linear/encoder uses an encoded-state '
                     'handoff perturbation, not an alternative matrix or encoder implementation. '
                     'Controlled parameter/toe errors are uniform across tonal height and are not actual '
                     'interpolation-error patterns; native table substitutions belong to the separate '
                     'native candidate report. No physical GPU performance or continuous-domain bound is claimed.'),
        original_gates_unchanged=True, baseline_decomposition_passed=all(
            r['against_full_oracle']['max_normalized'] <= 1e-10 for r in baselines))
    (output_dir/'report.json').write_text(json.dumps(_json(report), indent=2, allow_nan=False)+'\n')
    lines=['# Controlled internal-state sensitivity', '', report['contract'], '', report['limitations'], '',
           f"{len(baselines)} grade/space baselines, {samples} pixels each, {len(rows)} controlled perturbations. "
           f"Source stability: {stable}. Existing runtime layouts and acceptance gates are unchanged.", '',
           '| Stage | Largest local diagnostic error | Largest added final RGB error | Local > diagnostic threshold / final ≤1e-5 events | Illegal/pole sample events | Failed propagations |',
           '|---|---:|---:|---:|---:|---:|']
    for stage in stages:
        chosen = [r for r in rows if r['stage'] == stage and r['status'] == 'evaluated']
        failed = sum(r['stage'] == stage and r['status'] != 'evaluated' for r in rows)
        maximum = max((r['added_final_rgb']['max_normalized'] for r in chosen
                       if r['added_final_rgb']['max_normalized'] is not None), default=0)
        lines.append(f"| {stage} | {max((r['local_error_max'] for r in chosen), default=0):.6g} | {maximum:.6g} | "
            f"{sum(r['internal_failure_with_added_rgb_below_1e5_samples'] for r in chosen)} | "
            f"{sum(r['illegal_native_samples'] for r in chosen)} | {failed} |")
    lines += ['', 'These counts are repeated case/perturbation/sample events. A small final error can result from black/white policy or projection masking, and does not certify accurate internal states. The small-RGB counts include boundary leakage; JSON separately counts candidates that also preserve containment. JSON retains per-stage directions, amplitudes, parameter errors, local and total output metrics, full settings, and concrete worst and masked-error witnesses.', '']
    (output_dir/'report.md').write_text('\n'.join(lines))
    if not stable:
        raise RuntimeError('Sensitivity source files changed during the run')
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--samples', type=int, default=256)
    parser.add_argument('--cases', nargs='+', default=list(DEFAULT_CASES))
    parser.add_argument('--spaces', nargs='+', choices=cases.SPACES, default=['Linear Rec.709'])
    parser.add_argument('--stages', nargs='+', choices=STAGES, default=list(STAGES))
    parser.add_argument('--modes', nargs='+', choices=MODES, default=list(MODES))
    parser.add_argument('--amplitudes', nargs='+', type=float, default=[1e-5, 1e-3, 1e-2])
    args = parser.parse_args(argv)
    if args.samples < 256 or any(not np.isfinite(v) or v <= 0 for v in args.amplitudes):
        parser.error('Require at least 256 samples and positive finite amplitudes')
    run(args.output_dir, samples=args.samples, selected=tuple(args.cases), spaces=tuple(args.spaces),
        stages=tuple(args.stages), modes=tuple(args.modes), amplitudes=tuple(args.amplitudes))


if __name__ == '__main__':
    main()
