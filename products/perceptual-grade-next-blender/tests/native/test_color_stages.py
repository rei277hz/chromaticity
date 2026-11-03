"""Independent Color-stage oracle checks before either export guard."""
from dataclasses import asdict, replace
from functools import partial
from pathlib import Path
from types import SimpleNamespace
import hashlib
import json
import unittest
import numpy as np
import bpy

from color_tools.kernel import prepare, ToneSettings, ColorSettings, WebSettings
from color_tools.perceptual_grade_reference import grading
from color_tools.perceptual_grade_reference.responses import State
from tools.perceptual_grade.reports import cases, full_cases, oracle, color_local, web_toe_local
from tools.perceptual_grade.reports.gate_policy import texture_admission_policy, web_local_limit
from tools.perceptual_grade.reports.native import NativeFixture
from tools.perceptual_grade.reports.color_local import (
    stage_builder, connect_frozen, rounded_state, local_color_frames)
from tools.perceptual_grade.reports.web_toe_local import with_toe_cells


def color_cases():
    yield 'lightness', ColorSettings(lightness=((3., -5., 2., -1.),)*4)
    yield 'chroma', ColorSettings(chroma=((.3, -.2, .1, -.15),)*4)
    yield 'global_gain', ColorSettings(global_gain=.2)
    yield 'hue', ColorSettings(web=WebSettings(hue_degrees=((5., -3., 2., -4., 1., -2.),)*4))
    yield 'web_chroma', ColorSettings(web=WebSettings(log_chroma=((.2, -.1, .1, -.2, .1, 0.),)*4))
    yield 'final_scale', ColorSettings(web=WebSettings(log_scale=((.1, -.1, .2, -.1, .1, 0.),)*4))
    yield 'adaptance', ColorSettings(adaptance=((1., .5),)*4)
    yield 'combined', ColorSettings(lightness=((1., 2., 1., -1.),)*4,
        chroma=((.1, .2, .1, -.1),)*4, adaptance=((1., .5),)*4,
        web=WebSettings(hue_degrees=((5., -3., 2., -4., 1., -2.),)*4,
                        log_chroma=((.2, -.1, .1, -.2, .1, 0.),)*4,
                        log_scale=((.1, -.1, .2, -.1, .1, 0.),)*4))
    yield 'varying_tonal_selectors', full_cases.all_active()


def local_precision_sources(prepared, stage, frozen, *, persistent=False):
    """Mark samples whose result consumes the sole runtime field for a stage."""
    color = prepared.color
    all_samples = np.ones(len(frozen), dtype=bool)
    if stage == 'terms' and color.coefficient_table is not None:
        return {'Color coefficients': all_samples}
    if stage != 'adaptance':
        return {}
    return {'Adaptance parameters': all_samples}


class ColorStageTests(unittest.TestCase):
    persistent_routes = False

    def check_local_precision(self, metrics, required_metrics, local_limit):
        for coordinate in ('h', 'ab', 'energy'):
            self.assertTrue(np.isfinite(metrics[coordinate]))
            self.assertGreaterEqual(metrics[coordinate], 0.)
            self.assertLessEqual(required_metrics[coordinate], local_limit)
        self.assertEqual(metrics['significant_sign_mismatches'], 0)

    def test_local_precision_policy_tracks_compact_for_all_controls_and_heights(self):
        frozen = np.column_stack((np.array((0., 1., 2., 3.)), np.zeros((4, 3))))
        color = SimpleNamespace(coefficient_table=object(), log_gains=np.full((4, 3), .5))
        prepared = SimpleNamespace(color=color)
        for large in (False, True):
            color.log_gains[0, 0] = 2. if large else .5
            for tail in (False, True):
                color.log_gains[-1] = .5 if tail else 0.
                for persistent in (False, True):
                    sources = local_precision_sources(prepared, 'adaptance', frozen,
                                                      persistent=persistent)
                    self.assertEqual(set(sources), {'Adaptance parameters'})
                    np.testing.assert_array_equal(sources['Adaptance parameters'], True)
        self.assertEqual(local_precision_sources(prepared, 'web', frozen), {})
        self.assertEqual(local_precision_sources(prepared, 'scale', frozen), {})
        self.assertEqual(texture_admission_policy('Color coefficients')['local_precision'], 'diagnostic')
        self.assertEqual(texture_admission_policy('Adaptance parameters')['local_precision'], 'diagnostic')
        self.assertEqual(texture_admission_policy('Web parameters')['local_precision'], 'required')

    def test_diagnostic_local_precision_keeps_finiteness_and_energy_sign_checks(self):
        required = dict(h=0., ab=0., energy=0.)
        diagnostic = dict(h=.01, ab=.01, energy=.01, significant_sign_mismatches=0)
        self.check_local_precision(diagnostic, required, 1e-5)
        for changed, gated in ((dict(diagnostic, h=np.nan), required),
                               (dict(diagnostic, significant_sign_mismatches=1), required),
                               (diagnostic, dict(required, ab=1.1e-5))):
            with self.assertRaises(AssertionError):
                self.check_local_precision(changed, gated, 1e-5)

    @classmethod
    def source_identity(cls):
        from tools.perceptual_grade.reports.evaluate import evidence_hashes
        return dict(**evidence_hashes(),
                    test_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                    local_fixture_sha256={Path(module.__file__).name:
                        hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()
                        for module in (color_local, web_toe_local)})

    @classmethod
    def setUpClass(cls):
        cls.identities = cls.source_identity()
        print(json.dumps(dict(kind='color_source_identity', phase='start', **cls.identities)), flush=True)

    @classmethod
    def tearDownClass(cls):
        identities = cls.source_identity()
        print(json.dumps(dict(kind='color_source_identity', phase='end', **identities)), flush=True)
        if identities != cls.identities:
            raise AssertionError('Color acceptance sources changed during the run')

    def test_web_sector_seams_at_adjacent_float32_inputs(self):
        for rotation in (0., -360., 360.):
            with self.subTest(rotation=rotation):
                self.check_web_sector_seams(rotation)

    def check_web_sector_seams(self, rotation):
        """Classification and shifted radial rows must agree at every seam."""
        _, linear, tone, color = next(item for item in full_cases.ui_boundaries()
                                     if item[0] == 'web_alternating_extremes')
        color = replace(color, web=replace(color.web, hue_degrees=((rotation,)*6,)*4))
        prepared = with_toe_cells(prepare(linear, tone, color=color), 524288)
        reference = grading.Color(grading.ColorSettings(**asdict(color)),
                                  grading.Tone(grading.ToneSettings(**asdict(tone))))
        anchors = prepared.color.anchors
        heights = np.unique(np.r_[0., anchors, (anchors[:-1]+anchors[1:])/2,
                                  prepared.color.high*1.25]).astype(np.float32)
        parameters = prepared.color.web_parameters(heights.astype(float))
        source_rows, frozen_rows = [], []
        for h, angles in zip(heights, parameters['target_angles']):
            for angle in angles:
                # atan2 receives these quantized coordinates in both models.
                # Probe both sides of each seam one float32 ULP at a time.
                ab = (5*np.array((np.cos(angle), np.sin(angle)))).astype(np.float32)
                for component in (0, 1):
                    for direction in (-np.inf, None, np.inf):
                        point = ab.copy()
                        if direction is not None:
                            point[component] = np.nextafter(point[component], np.float32(direction))
                        c = np.hypot(*point.astype(float))
                        source_rows.append((80., *point, 80.**2-66*c))
                        frozen_rows.append((h, c, 80.**2-66*c, 1.))
        inputs = np.asarray(source_rows, np.float32)
        frozen = np.asarray(frozen_rows, np.float32)
        source = State(inputs[:, :3].astype(float), inputs[:, 3].astype(float))
        captured = []
        def capture(q, energy):
            captured.append(State(q, energy))
            return q, energy
        final_q, _ = reference.web.apply(source.q, source.energy,
                                         frozen[:, 0].astype(float), transform=capture)
        expected = captured[0]
        expected_scale = np.hypot(final_q[:, 1], final_q[:, 2])/np.hypot(expected.q[:, 1], expected.q[:, 2])
        local_limit = web_local_limit(color, 'web')
        for context in ('shader', 'compositor'):
            with self.subTest(context=context):
                fixture = NativeFixture(prepared, inputs, context,
                    builder=partial(stage_builder, isolated=True, stage='web', local=True))
                connect_frozen(fixture, frozen)
                try:
                    actual = fixture.render()
                finally:
                    fixture.close()
                metrics = oracle.state_metrics(actual['rgb'], actual['valid'], expected.q,
                    expected.energy, source.q, source.energy)
                scale_errors = abs(actual['margin']-expected_scale)/expected_scale
                scale_worst = int(np.argmax(scale_errors))
                scale_error = float(scale_errors[scale_worst])
                print(json.dumps(dict(kind='color_web_seams', context=context, rotation=rotation, samples=len(inputs),
                    state=metrics, scale_relative_error=scale_error,
                    state_error_limit=local_limit, scale_relative_error_limit=local_limit,
                    worst_scale=dict(index=scale_worst, input=inputs[scale_worst].tolist(),
                        frozen=frozen[scale_worst].tolist(),
                        expected=float(expected_scale[scale_worst]), actual=float(actual['margin'][scale_worst]),
                        expected_q=expected.q[scale_worst].tolist(), actual_q=actual['rgb'][scale_worst].tolist()))), flush=True)
                np.testing.assert_array_equal(actual['saturated'], 0.)
                for coordinate in ('h', 'ab', 'energy'):
                    self.assertLessEqual(metrics[coordinate], local_limit)
                self.assertLessEqual(scale_error, local_limit)
                self.assertEqual(metrics['significant_sign_mismatches'], 0)

    def test_raw_color_against_independent_reference(self):
        self.check_color(False)

    def test_isolated_color_at_identical_float32_inputs(self):
        self.check_color(True)

    def test_isolated_sharp_control_boundaries(self):
        selected = ((name, color) for name, _, _, color in full_cases.ui_boundaries()
                    if name in {'lightness_fit_6', 'chroma_fit_6',
                                'web_log_chroma_+1', 'web_log_scale_+1',
                                'adaptance_half_0.05'})
        self.check_color(True, selected)

    def check_color(self, isolated, selected=None):
        values = cases.rgba(256)
        tone = ToneSettings(input_nits=(0., 8., 40., 235., 1150.))
        for name, color in color_cases() if selected is None else selected:
            prepared = prepare(tone=tone, color=color)
            source = oracle.evaluate(values[:, :3], prepared.linear.settings, tone, prepared.space)['tone']
            reference = grading.Color(grading.ColorSettings(**asdict(color)),
                                      grading.Tone(grading.ToneSettings(**asdict(tone))))
            if isolated:
                inputs = np.column_stack((source.q, source.ja*abs(source.ja))).astype(np.float32)
                source = State(inputs[:, :3].astype(float), inputs[:, 3].astype(float))
            else:
                inputs = values
            expected = reference.apply_state(source)
            for context in ('shader', 'compositor'):
                with self.subTest(case=name, context=context):
                    fixture = NativeFixture(prepared, inputs, context,
                                            builder=partial(stage_builder, isolated=isolated))
                    try:
                        actual = fixture.render()
                    finally:
                        fixture.close()
                    metrics = oracle.state_metrics(actual['rgb'], actual['valid'], expected.q,
                        expected.energy, source.q, source.ja*abs(source.ja))
                    raw_q = oracle.metrics(actual['rgb'], expected.q)['max_normalized']
                    ab_errors = np.hypot(*(actual['rgb'][:, 1:]-expected.q[:, 1:]).T)/(1+
                        np.hypot(source.q[:, 1], source.q[:, 2])+
                        np.hypot(expected.q[:, 1], expected.q[:, 2]))
                    worst = int(np.argmax(ab_errors))
                    print(json.dumps(dict(kind='color_stage', case=name, context=context,
                        isolated=isolated, state=metrics, q_output_normalized=raw_q,
                        worst_ab=dict(index=worst, input=source.q[worst].tolist(),
                            expected=expected.q[worst].tolist(), actual=actual['rgb'][worst].tolist()))), flush=True)
                    # Whole-Color accumulation is diagnostic. The normative
                    # internal gate applies at each identical-float32 handoff.
                    self.assertEqual(metrics['significant_sign_mismatches'], 0)
                    self.assertTrue(np.isfinite(actual['rgb']).all())
                    self.assertTrue(np.isfinite(actual['valid']).all())
                    np.testing.assert_array_equal(actual['saturated'], 0.)
                    black = np.all(values[:, :3] == 0., axis=-1)
                    np.testing.assert_array_equal(actual['rgb'][black], 0.)
                    np.testing.assert_array_equal(actual['valid'][black], 0.)

    def test_saturated_raw_state_against_unchanged_float64_reference(self):
        values = full_cases.rgba(count=256)
        color, tone = full_cases.saturation_grade(), ToneSettings()
        prepared = prepare(tone=tone, color=color)
        composed_source = oracle.evaluate(values[:, :3], prepared.linear.settings, tone, prepared.space)['tone']
        reference = grading.Color(grading.ColorSettings(**asdict(color)),
                                  grading.Tone(grading.ToneSettings(**asdict(tone))))
        for isolated, context in ((isolated, context) for isolated in (False, True)
                                  for context in ('shader', 'compositor')):
            with self.subTest(context=context, isolated=isolated):
                source, inputs = composed_source, values
                if isolated:
                    inputs = np.column_stack((source.q, source.ja*abs(source.ja))).astype(np.float32)
                    source = State(inputs[:, :3].astype(float), inputs[:, 3].astype(float))
                expected = reference.apply_state(source)
                fixture = NativeFixture(prepared, inputs, context,
                    builder=partial(stage_builder, isolated=isolated))
                try:
                    actual = fixture.render()
                finally:
                    fixture.close()
                flagged = np.flatnonzero(actual['saturated'] > .5)
                metrics = oracle.state_metrics(actual['rgb'], actual['valid'], expected.q,
                    expected.energy, source.q, source.ja*abs(source.ja))
                regular = ((actual['saturated'] < .5) &
                           (abs(expected.energy) <= np.finfo(np.float32).max))
                local = oracle.state_metrics(actual['rgb'][regular], actual['valid'][regular],
                    expected.q[regular], expected.energy[regular], source.q[regular],
                    (source.ja*abs(source.ja))[regular])
                print(json.dumps(dict(kind='color_saturation', context=context, isolated=isolated,
                    state=metrics, unsaturated_state=local, flagged_indices=flagged.tolist(),
                    q_output_normalized=oracle.metrics(actual['rgb'], expected.q)['max_normalized'],
                    reference_energy=expected.energy[flagged].tolist(),
                    native_energy=actual['valid'][flagged].tolist(),
                    reference_q=expected.q[flagged].tolist(),
                    native_q=actual['rgb'][flagged].tolist())), flush=True)
                self.assertTrue(np.isfinite(actual['rgb']).all())
                self.assertTrue(np.isfinite(actual['valid']).all())
                self.assertGreaterEqual(len(flagged), 4)
                saturated_energy = abs(expected.energy) > np.finfo(np.float32).max
                np.testing.assert_array_equal(actual['saturated'][saturated_energy], 1.)
                np.testing.assert_array_equal(actual['valid'][saturated_energy],
                    np.sign(expected.energy[saturated_energy])*np.finfo(np.float32).max)

    def test_accumulated_color_at_float32_inputs(self):
        for name, linear, tone, color in full_cases.grades():
            if name not in {'all_active', 'all_active_saturation'}:
                continue
            prepared = prepare(linear, tone, color=color)
            values = full_cases.rgba(count=256)
            source = oracle.evaluate(values[:, :3], linear, tone, prepared.space)['tone']
            inputs = np.column_stack((source.q, source.ja*abs(source.ja))).astype(np.float32)
            # Place explicit exterior-response states at the frozen shadow
            # selector, independent of the Linear/Tone combination above.
            from color_tools.perceptual_grade_reference.responses import signed_hk
            ja = float(prepared.tone.target[1])*100
            angle = np.arange(4)*np.pi/2
            inputs[-4:, :3] = np.column_stack((np.full(4, signed_hk(ja, 1.)),
                                              np.cos(angle), np.sin(angle)))
            inputs[-4:, 3] = ja*ja
            source = State(inputs[:, :3].astype(float), inputs[:, 3].astype(float))
            reference = grading.Color(grading.ColorSettings(**asdict(color)),
                                      grading.Tone(grading.ToneSettings(**asdict(tone))))
            expected = reference.apply_state(source)
            for context in ('shader', 'compositor'):
                fixture = NativeFixture(prepared, inputs, context,
                    builder=partial(stage_builder, isolated=True))
                try:
                    actual = fixture.render()
                finally:
                    fixture.close()
                regular = ((actual['saturated'] < .5) &
                           (abs(expected.energy) <= np.finfo(np.float32).max))
                local = oracle.state_metrics(actual['rgb'][regular], actual['valid'][regular],
                    expected.q[regular], expected.energy[regular], source.q[regular], source.energy[regular])
                total = oracle.state_metrics(actual['rgb'], actual['valid'], expected.q,
                    expected.energy, source.q, source.energy)
                print(json.dumps(dict(kind='color_accumulated_float32', case=name, context=context,
                    strategy='1d', unsaturated_state=local, all_state=total,
                    flagged_indices=np.flatnonzero(actual['saturated'] > .5).tolist())), flush=True)
                self.assertTrue(np.isfinite(actual['rgb']).all())
                self.assertTrue(np.isfinite(actual['valid']).all())

    def test_each_substage_at_identical_float32_handoff(self):
        selected = [item for item in full_cases.grades()
                    if item[0] in {'adaptance', 'all_active', 'saturation',
                                   'all_active_saturation'}]
        selected += [item for item in full_cases.ui_boundaries() if item[0] in {
            'all_families_max', 'all_families_max_active_tail',
            'lightness_fit_6', 'chroma_fit_6', 'web_alternating_extremes'}]
        for name, linear, tone, color in selected:
            prepared = with_toe_cells(prepare(linear, tone, color=color), 524288)
            source = oracle.evaluate(full_cases.rgba(count=256)[:, :3], linear, tone, prepared.space)['tone']
            source = State(source.q, source.ja*abs(source.ja))
            reference = grading.Color(grading.ColorSettings(**asdict(color)),
                                      grading.Tone(grading.ToneSettings(**asdict(tone))))
            for stage, source, expected, frozen, expected_scale in local_color_frames(reference, source):
                active = {'terms': prepared.color.lightness_active or prepared.color.chroma_active,
                          'web': prepared.color.web_active, 'adaptance': prepared.color.adaptance_active,
                          'scale': bool(np.any(color.web.log_scale))}
                if not active[stage]:
                    continue
                local_limit = web_local_limit(color, stage)
                inputs, source = rounded_state(source)
                precision_sources = local_precision_sources(prepared, stage, frozen,
                    persistent=self.persistent_routes)
                diagnostic = np.zeros(len(inputs), dtype=bool)
                for role, sampled in precision_sources.items():
                    if texture_admission_policy(role)['local_precision'] == 'diagnostic':
                        diagnostic |= sampled
                for context in ('shader', 'compositor'):
                    with self.subTest(case=name, stage=stage, strategy='1d', context=context):
                        fixture = NativeFixture(prepared, inputs, context,
                            builder=partial(stage_builder, isolated=True, stage=stage, local=True))
                        connect_frozen(fixture, frozen)
                        try:
                            actual = fixture.render()
                        finally:
                            fixture.close()
                        finite = ((actual['saturated'] < .5) &
                                  (abs(expected.energy) <= np.finfo(np.float32).max) &
                                  np.all(abs(expected.q) <= np.finfo(np.float32).max, axis=-1))
                        metrics = oracle.state_metrics(actual['rgb'][finite], actual['valid'][finite],
                            expected.q[finite], expected.energy[finite], source.q[finite], source.energy[finite])
                        required = finite & ~diagnostic
                        required_metrics = oracle.state_metrics(actual['rgb'][required], actual['valid'][required],
                            expected.q[required], expected.energy[required], source.q[required], source.energy[required])
                        total = oracle.state_metrics(actual['rgb'], actual['valid'], expected.q,
                            expected.energy, source.q, source.energy)
                        ci = np.hypot(source.q[:, 1], source.q[:, 2])
                        co = np.hypot(expected.q[:, 1], expected.q[:, 2])
                        errors = np.maximum(abs(actual['valid']-expected.energy)/(1+
                            abs(source.energy)+abs(expected.energy)+66*(ci+co)),
                            np.hypot(*(actual['rgb'][:, 1:]-expected.q[:, 1:]).T)/(1+ci+co))
                        worst = int(np.argmax(np.where(finite, errors, -1)))
                        scale_error = (float(np.max(abs(actual['margin']-expected_scale)/expected_scale))
                                       if expected_scale is not None else None)
                        print(json.dumps(dict(kind='color_local_handoff', case=name, stage=stage,
                            context=context, strategy='1d', finite_samples=int(finite.sum()),
                            state=metrics, all_state=total, scale_relative_error=scale_error,
                            state_error_limit=local_limit,
                            raw_precision_passed=all(metrics[key] <= local_limit for key in ('h', 'ab', 'energy')),
                            required_precision_samples=int(required.sum()),
                            diagnostic_precision_samples=int((finite & diagnostic).sum()),
                            required_precision_state=required_metrics,
                            field_precision_sources={role: dict(samples=int(sampled.sum()),
                                policy=texture_admission_policy(role))
                                for role, sampled in precision_sources.items()},
                            scale_relative_error_limit=local_limit if expected_scale is not None else None,
                            worst=dict(index=worst, input=inputs[worst].tolist(),
                                frozen=frozen[worst].tolist(),
                                expected=expected.q[worst].tolist(), actual=actual['rgb'][worst].tolist(),
                                reference_energy=float(expected.energy[worst]), native_energy=float(actual['valid'][worst])),
                            flagged_indices=np.flatnonzero(actual['saturated'] > .5).tolist())), flush=True)
                        self.assertTrue(np.isfinite(actual['rgb']).all())
                        self.assertTrue(np.isfinite(actual['valid']).all())
                        overflow = ((abs(expected.energy) > np.finfo(np.float32).max) |
                                    np.any(abs(expected.q) > np.finfo(np.float32).max, axis=-1))
                        np.testing.assert_array_equal(actual['saturated'][overflow], 1.)
                        if stage in {'terms', 'web', 'scale'}:
                            representable = ~overflow & (co <= np.finfo(np.float32).max)
                            if stage == 'web' and expected_scale is not None:
                                # Web also computes the final radial scale
                                # before Adaptance, although it returns an
                                # unscaled appearance state at this point.
                                representable &= co*expected_scale <= np.finfo(np.float32).max
                            np.testing.assert_array_equal(actual['saturated'][representable], 0.)
                        if name in {'all_active', 'lightness_fit_6', 'chroma_fit_6',
                                    'web_alternating_extremes'}:
                            # An unexpected diagnostic must not remove an
                            # ordinary sample from the numerical gate.
                            np.testing.assert_array_equal(actual['saturated'], 0.)
                        self.check_local_precision(metrics, required_metrics, local_limit)
                        if scale_error is not None:
                            self.assertTrue(np.isfinite(actual['margin']).all())
                            np.testing.assert_array_equal(actual['saturated'][
                                expected_scale > np.finfo(np.float32).max], 1.)
                            self.assertLessEqual(scale_error, local_limit)
                        self.assertEqual(metrics['significant_sign_mismatches'], 0)


if __name__ == '__main__':
    unittest.main()
