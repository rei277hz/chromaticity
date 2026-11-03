"""Independent Color preparation, frozen drivers and parameter atlas gates."""
from dataclasses import asdict, replace
import json
import unittest
import numpy as np

from color_tools.kernel import ColorSettings, WebSettings, ToneSettings, prepare as runtime_prepare
from color_tools.kernel.color_prepare import (
    COLOR_TABLE_ERROR_LIMIT, _audit_field, _generate_field, _prepare_tables, drivers, audit_color)
from color_tools.kernel.layouts import FIELD_LATTICE, supported_cells
from color_tools.perceptual_grade_reference.grading import (
    Color, ColorSettings as ReferenceColor, Tone, ToneSettings as ReferenceTone,
    drivers as reference_drivers)
from tools.perceptual_grade.reports.gate_policy import (
    field_passed, scalar_limits, texture_admission_policy)


def prepare(*args, **kwargs):
    """Numerical tests explicitly audit fixed runtime fields outside updates."""
    value = runtime_prepare(*args, **kwargs)
    return replace(value, color=audit_color(value.color))


def oracle(settings, tone=ToneSettings()):
    return Color(ReferenceColor(**asdict(settings)), Tone(ReferenceTone(**asdict(tone))))


def legacy_toe(prepared):
    """Strict scalar regression uses the original precision, apart from admission."""
    if prepared.web_toe_table.cells == 524288:
        return prepared.web_toe_table
    originals = {table.name: table for table in prepared.tables}
    def builder(name, evaluator, fields, mapping, domain, knots=(), scales=None, **kwargs):
        if name != 'Web toes':
            return originals[name]
        table = _generate_field(name, evaluator, fields, mapping, domain, knots, scales,
                                cells=524288, **kwargs)
        return _audit_field(table, evaluator, knots)
    return _prepare_tables(prepared, builder=builder).web_toe_table


class ColorPreparationTests(unittest.TestCase):
    def check_field_audit(self, table, settings):
        """Keep raw precision complete even for HDR-admitted field layouts."""
        limits = scalar_limits(table, settings)
        policy = texture_admission_policy(table.name)
        print(json.dumps(dict(kind='color_scalar_audit', role=table.name,
            cells=table.cells, admission=policy, scalar_limits=limits,
            scalar_passed=field_passed(table, settings), audit_complete=table.audit_complete,
            probe_count=table.probe_count, conditioned_error=table.max_error,
            pointwise_error=table.max_pointwise_error, mapper_error=table.max_mapper_error,
            relative_interpolation_error=table.max_relative_interpolation_error,
            absolute_interpolation_error=table.max_absolute_interpolation_error,
            field_errors=table.field_errors.tolist(), witness=table.audit_witness)), flush=True)
        self.assertTrue(table.audit_complete)
        self.assertGreater(table.probe_count, 0)
        self.assertTrue(np.isfinite(table.pixels).all())
        for measured in (table.max_error, table.max_pointwise_error,
                         table.max_mapper_error, table.max_relative_interpolation_error,
                         table.max_absolute_interpolation_error, table.field_errors):
            self.assertTrue(np.isfinite(measured).all())
            self.assertTrue(np.all(np.asarray(measured) >= 0.))
        if policy['scalar_precision'] == 'required':
            self.assertTrue(field_passed(table, settings), (table.name, limits))

    def test_small_toe_scalar_failure_remains_a_complete_diagnostic(self):
        evaluator = lambda x: np.stack((1+x*x, 2+2*x*x, 3+3*x*x, np.zeros_like(x)), axis=-1)
        table = _generate_field('Web toes', evaluator, {'toes': (0, 1, 2)}, 'linear', 1.,
                                cells=256, relative_columns=(0, 1, 2))
        measured = _audit_field(table, evaluator)
        self.assertTrue(measured.audit_complete)
        self.assertGreater(measured.max_relative_interpolation_error, 1e-6)
        self.assertFalse(field_passed(measured, ColorSettings()))
        self.assertIn('relative', measured.audit_witness)

    def test_hdr_scalar_diagnostics_still_require_finite_complete_audits(self):
        evaluator = lambda x: np.stack((np.sin(1000*x), np.zeros_like(x),
                                         np.zeros_like(x), np.zeros_like(x)), axis=-1)
        table = _generate_field('Color coefficients', evaluator, {'lightness': (0,)},
                                'linear', 1., cells=2048)
        measured = _audit_field(table, evaluator)
        self.assertFalse(field_passed(measured, ColorSettings()))
        self.check_field_audit(measured, ColorSettings())
        for invalid in (replace(measured, audit_complete=False),
                        replace(measured, pixels=np.full_like(measured.pixels, np.nan)),
                        replace(measured, max_error=np.inf),
                        replace(measured, name='Web parameters'),
                        replace(measured, name='Tone')):
            with self.subTest(role=invalid.name, complete=invalid.audit_complete), self.assertRaises(AssertionError):
                self.check_field_audit(invalid, ColorSettings())

    def test_small_toe_grids_are_role_scoped_and_sample_endpoints(self):
        self.assertEqual(supported_cells('Web toes')[:8], tuple(range(256, 2049, 256)))
        for name in ('Color coefficients', 'Web parameters'):
            self.assertEqual(supported_cells(name), FIELD_LATTICE)
        self.assertEqual(supported_cells('Adaptance parameters'), tuple(sorted((3072, *FIELD_LATTICE))))
        with self.assertRaisesRegex(ValueError, 'Unknown Color field role'):
            supported_cells('Adaptance interior parameters')
        evaluator = lambda x: np.stack((1+x, 2+2*x, 3+3*x, np.zeros_like(x)), axis=-1)
        for cells in supported_cells('Web toes')[:8]:
            table = _generate_field('Web toes', evaluator, {'toe': (0,)}, 'linear', 1., cells=cells)
            self.assertEqual(table.pixels.shape, (1, cells+1, 4))
            self.assertEqual(table.pixels.nbytes, (cells+1)*16)
            np.testing.assert_array_equal(table.evaluate((0., 1.))[..., 0, :],
                                          np.array(((1., 2., 3., 0.), (2., 4., 6., 0.)), np.float32))
            probes = np.array((0., .1234567, .5, .999999, 1.), np.float32)
            np.testing.assert_allclose(table.evaluate(probes)[..., 0, :3], evaluator(probes)[:, :3], atol=2e-6)
        with self.assertRaises(ValueError):
            _generate_field('Web parameters', evaluator, {'toe': (0,)}, 'linear', 1., cells=1024)
        for role in ('Color coefficients', 'Web parameters', 'Web toes'):
            with self.subTest(role=role), self.assertRaises(ValueError):
                _generate_field(role, evaluator, {'value': (0,)}, 'linear', 1., cells=3072)
        compact = _generate_field('Adaptance parameters', evaluator, {'value': (0, 1, 2)},
                                  'response_compact', 0., cells=3072)
        self.assertEqual(compact.pixels.shape, (1, 3073, 4))
        self.assertEqual(compact.memory_bytes, 49168)
        np.testing.assert_allclose(compact.evaluate(probes)[..., 0, :3], evaluator(probes)[:, :3], atol=2e-6)

    def test_reuse_rejects_prior_color_with_old_layout_and_keeps_matching_layout(self):
        from color_tools.kernel.color_prepare import _prepare_color_parameters
        from color_tools.kernel import prepare_tone
        from color_tools.kernel.layouts import FIELD_CELLS
        settings = ColorSettings(lightness=((1., -2., .5, -.25),)*4,
            adaptance=((2., -1.),)*4, web=WebSettings(log_chroma=((.1,)*6,)*4))
        tone = prepare_tone(full_fields=True)
        current = _prepare_color_parameters(settings, tone, full_fields=True)
        built = _prepare_tables(current)
        self.assertEqual(built.web_table.cells, FIELD_CELLS['Web parameters'])
        self.assertEqual(tuple(built.web_table.pixels.shape), (32, 4097, 4))
        self.assertEqual(built.web_table.pixels.nbytes, 2097664)
        self.assertEqual(built.coefficient_table.cells, 8192)
        self.assertEqual(built.coefficient_table.pixels.shape, (2, 8193, 4))
        self.assertEqual(built.coefficient_table.pixels.nbytes, 262176)
        self.assertEqual(built.adaptance_table.cells, 3072)
        self.assertEqual(built.adaptance_table.pixels.shape, (1, 3073, 4))
        self.assertEqual(built.adaptance_table.pixels.nbytes, 49168)
        obsolete_cells = {'Color coefficients': 131072, 'Web parameters': 32768,
                          'Web toes': 1280, 'Adaptance parameters': 16384}
        originals = {table.name: table for table in built.tables}
        def prior_builder(name, *args, **kwargs):
            if name not in obsolete_cells:
                return originals[name]
            return _generate_field(name, *args, cells=obsolete_cells[name], **kwargs)
        stale = _prepare_tables(current, builder=prior_builder)
        rebuilt = _prepare_tables(current, previous=stale)
        reused = _prepare_tables(current, previous=built)
        for expected, old, actual, same in zip(built.tables, stale.tables,
                                                rebuilt.tables, reused.tables):
            with self.subTest(role=expected.name):
                self.assertEqual(actual.cells, FIELD_CELLS[expected.name])
                self.assertEqual(actual.pixels.shape, expected.pixels.shape)
                np.testing.assert_array_equal(actual.pixels, expected.pixels)
                self.assertIs(same, expected)
                if expected.name in obsolete_cells:
                    self.assertEqual(old.cells, obsolete_cells[expected.name])
                    self.assertNotEqual(old.pixels.shape, expected.pixels.shape)
                    self.assertIsNot(actual, old)
                else:
                    self.assertIs(actual, old)

    def test_reset_owns_no_parameter_images(self):
        prepared = prepare().color
        self.assertFalse(prepared.active)
        self.assertEqual(prepared.tables, ())
        self.assertIsNone(prepared.geometry)
        np.testing.assert_array_equal(prepared.log_gains, 0.)

    def test_frozen_driver_memberships_match_signed_reference(self):
        rng = np.random.default_rng(20261029)
        q = rng.normal(size=(2048, 3))*100
        ja = rng.normal(size=2048)*100
        q[:3] = ((0, 0, 0), (10, 0, 0), (10, 35, 0))
        ja[:3] = (0, -10, 75)
        np.testing.assert_allclose(drivers(q, ja), reference_drivers(q, ja), rtol=2e-15, atol=2e-15)
        np.testing.assert_array_equal(drivers(q[:2], ja[:2]), 0.)
        self.assertAlmostEqual(drivers(q[2], ja[2])[0], drivers(q[2], ja[2])[1])
        np.testing.assert_array_equal(drivers(q, ja), drivers(q, -ja))
        chromatic_zero = drivers(np.array((1., 4., 0.)), 0.)
        self.assertEqual(chromatic_zero[0], 0.)
        self.assertAlmostEqual(chromatic_zero[1], .8)

    def test_color_fit_six_and_ui_amplitudes_keep_complete_scalar_diagnostics(self):
        lightness = ((30, 100, 20, -20), (50, 200, 20, -20),
                     (100, 400, 30, -30), (200, 700, 50, -50))
        chroma = ((4, 16, 4, -4), (4, 16, 2, -2), (4, 16, 1, -1), (4, 16, 1, -1))
        for fit in (-2., 0., 3., 6.):
            settings = ColorSettings(lightness=lightness, chroma=chroma,
                                     lightness_fit=fit, chroma_fit=fit)
            prepared = prepare(color=settings).color
            expected = oracle(settings)
            h = np.r_[np.linspace(0, prepared.high, 20003), -10., 0., prepared.high*100]
            actual_terms, expected_terms = prepared.terms(h), expected.terms(h)
            np.testing.assert_allclose(actual_terms, expected_terms, rtol=3e-12, atol=3e-12)
            table = prepared.coefficient_table
            self.check_field_audit(table, settings)
            coordinate = table.coordinate(h)
            for name, reference in zip(('lightness', 'chroma'), expected_terms):
                sampled = table.field(name, coordinate)
                scale = np.array([table.scales[row, channel] for row, channel in table.fields[name]])
                error = np.max(abs(sampled-reference)/np.maximum(1+abs(reference), scale))
                print(json.dumps(dict(kind='color_sampled_scalar', field=name, fit=fit,
                    conditioned_error=float(error), error_limit=COLOR_TABLE_ERROR_LIMIT,
                    scalar_precision=texture_admission_policy(table.name)['scalar_precision'])), flush=True)
                self.assertTrue(np.isfinite(sampled).all())
                if texture_admission_policy(table.name)['scalar_precision'] == 'required':
                    self.assertLessEqual(error, COLOR_TABLE_ERROR_LIMIT)
            self.assertFalse(table.pixels.flags.writeable)
            with self.assertRaises(TypeError): table.fields['new'] = ((0, 0),)

    def test_web_geometry_and_parameter_fields_match_reference(self):
        settings = ColorSettings(web=WebSettings(
            log_chroma=((.1, -.2, .3, -.1, .2, -.1),)*4,
            hue_degrees=((3, -4, 5, -6, 1, 2),)*4,
            log_scale=((.1, .2, -.1, -.2, .1, 0),)*4))
        for peak in (500., 1000., 2000., 4000.):
            tone = ToneSettings(peak_nits=peak)
            prepared, expected = prepare(tone=tone, color=settings).color, oracle(settings, tone)
            np.testing.assert_allclose(prepared.geometry.q, expected.web.geometry.q, rtol=2e-13, atol=2e-12)
            h = np.r_[0., prepared.anchors, np.linspace(0., 2*prepared.high, 1001)]
            actual = prepared.web_parameters(h)
            for name, reference in expected.web.parameters(h).items():
                np.testing.assert_allclose(actual[name], reference, rtol=2e-13, atol=2e-12)
            np.testing.assert_array_equal(prepared.web_toes(h),
                np.stack((actual['angular_toe'], actual['chroma_toe'], actual['scale_toe']), axis=-1))
            table = prepared.web_table
            self.assertEqual(table.semantic_rows, 29)
            self.assertEqual(table.pixels.shape[0], 32*table.segments)
            self.assertEqual((table.angular_row, table.radial_row), (5, 17))
            self.check_field_audit(table, settings)
            self.assertLessEqual(table.max_absolute_interpolation_error, 3e-6)
            self.assertTrue(prepared.web_toe_table.audit_complete)
            self.assertTrue(np.isfinite(prepared.web_toe_table.max_relative_interpolation_error))
            self.assertLessEqual(legacy_toe(prepared).max_relative_interpolation_error, 1e-6)

    def test_adaptance_calibration_and_compact_infinite_tail(self):
        settings = ColorSettings(adaptance=((2, -3), (4, 1), (-2, 5), (4, -1)))
        prepared, expected = prepare(color=settings).color, oracle(settings)
        np.testing.assert_array_equal(prepared.log_gains, expected.adaptation.log_gains)
        h = np.r_[0., prepared.anchors, np.geomspace(1e-10, 1e25, 2049)]
        logs, k = prepared.adaptation_parameters(h)
        ref_logs, ref_k = expected.adaptation.parameters(h)
        np.testing.assert_allclose(logs, ref_logs, rtol=3e-15, atol=3e-15)
        np.testing.assert_allclose(k, ref_k, rtol=3e-15, atol=3e-15)
        table = prepared.adaptance_table
        self.check_field_audit(table, settings)
        x = table.coordinate(h, prepared.aw)
        for name, expected in (('log_gains', logs), ('log_k', np.log(k))):
            actual = table.field(name, x)
            scale = table.scales[0, :3] if name == 'log_gains' else table.scales[0, 3]
            error = float(np.max(abs(actual-expected)/np.maximum(1+abs(expected), scale)))
            print(json.dumps(dict(kind='compact_adaptance_sampled_scalar', field=name,
                conditioned_error=error, error_limit=COLOR_TABLE_ERROR_LIMIT,
                scalar_precision=texture_admission_policy(table.name)['scalar_precision'])), flush=True)
            self.assertTrue(np.isfinite(actual).all())
            if texture_admission_policy(table.name)['scalar_precision'] == 'required':
                self.assertLessEqual(error, COLOR_TABLE_ERROR_LIMIT)
        endpoint = table.field('log_k', 1., dtype=np.float64)
        limit = np.log(3.05/np.dot(np.exp(-2*prepared.log_gains[-1]), (2, 1, .05)))
        self.assertAlmostEqual(float(endpoint), float(limit), places=7)

    def test_large_adaptance_uses_fixed_compact_gains_and_exterior_normalization(self):
        settings = ColorSettings(adaptance=((-260.8694152832031, 0.), (0., 0.), (0., 0.), (4., -1.)))
        prepared = prepare(color=settings).color
        compact = prepared.adaptance_table
        self.assertFalse(hasattr(prepared, 'adaptance_interior_table'))
        self.assertEqual([table.name for table in prepared.tables], ['Adaptance parameters'])
        self.assertEqual(compact.mapping, 'response_compact')
        self.assertEqual(compact.cells, 3072)
        # Retain the frozen near-pole witness as a raw Compact diagnostic.
        # The fixed layout is admitted by full-grade HDR, not a local precision
        # assertion that would silently restore the removed representation.
        h = np.array((47.1189113567, 20.4547993876, 48.6231110572))
        logs, k = prepared.adaptation_parameters(h)
        exact = np.column_stack((logs, np.log(k)))
        actual = compact.evaluate(compact.coordinate(h, prepared.aw))[:, 0]
        error = float(np.max(abs(actual-exact)/(1+abs(exact))))
        print(json.dumps(dict(kind='compact_adaptance_strong_scalar', conditioned_error=error,
            error_limit=COLOR_TABLE_ERROR_LIMIT,
            scalar_precision=texture_admission_policy(compact.name)['scalar_precision'])), flush=True)
        self.assertTrue(np.isfinite(actual).all())
        self.assertTrue(np.isfinite(error))
        h = np.array((prepared.high, prepared.high*1000, 1e25))
        logs, k = prepared.adaptation_parameters(h)
        np.testing.assert_allclose(compact.field('log_gains', compact.coordinate(h, prepared.aw)), logs,
                                   rtol=2e-7, atol=2e-8)
        # The same Compact table supplies normalization throughout the tail.
        normalizer = compact.field('log_k', compact.coordinate(h, prepared.aw))
        error = float(np.max(abs(normalizer-np.log(k))/(1+abs(np.log(k)))))
        print(json.dumps(dict(kind='compact_adaptance_tail_scalar', conditioned_error=error,
            error_limit=COLOR_TABLE_ERROR_LIMIT,
            scalar_precision=texture_admission_policy(compact.name)['scalar_precision'])), flush=True)
        self.assertTrue(np.isfinite(normalizer).all())
        if texture_admission_policy(compact.name)['scalar_precision'] == 'required':
            self.assertLess(error, COLOR_TABLE_ERROR_LIMIT)
        self.assertGreater(abs(np.log(k[-1])-np.log(k[0])), 1e-5)

    def test_signed_coefficient_rounding_floor_has_explicit_conditioning(self):
        settings = ColorSettings(lightness=((30, -100, 20, -20), (-50, 200, -20, 20),
                                            (100, -400, 30, -30), (-200, 700, -50, 50)),
                                 lightness_fit=6)
        prepared = prepare(color=settings).color
        x = np.array([.6306918561458589])
        exact = prepared.terms(x*prepared.high)[0]
        rounded = prepared.terms(x.astype(np.float32).astype(float)*prepared.high)[0]
        floor = float(np.max(abs(exact-rounded)/(1+abs(exact))))
        self.assertGreater(floor, 1e-4)
        table = prepared.coefficient_table
        np.testing.assert_array_equal(table.scales[0], (201., 701., 51., 51.))
        self.check_field_audit(table, settings)
        self.assertGreater(table.max_pointwise_error, table.max_error)
        self.assertGreater(table.max_mapper_error, COLOR_TABLE_ERROR_LIMIT)
        self.assertEqual(table.field_errors.shape, table.scales.shape)

    def test_extreme_web_and_valid_near_pole_adaptance_remain_preparable(self):
        rows = np.array([[(-1.)**(i+j) for j in range(6)] for i in range(4)])
        cases = (ColorSettings(web=WebSettings(log_chroma=16*rows, log_scale=8*rows)),
                 ColorSettings(adaptance=((-260.8694152832031, 0.), (0., 0.), (0., 0.), (0., 0.))))
        for settings in cases:
            prepared = prepare(color=settings).color
            if prepared.web_table is not None:
                table = prepared.web_table
                limits = scalar_limits(table, settings)
                self.assertEqual(len(table.absolute_columns), 24)
                self.assertLessEqual(table.max_absolute_interpolation_error,
                                     limits['absolute_interpolation'])
                # Opposite 16/8-stop controls cross zero at this tonal midpoint;
                # retain the direct log check under the same explicit policy
                # as the complete scalar audit for this extreme control case.
                h = np.float32((prepared.anchors[0]+prepared.anchors[1])/2)
                parameters = prepared.web_parameters(float(h))
                sampled = table.field('log_scale_coefficients', table.coordinate(h))
                self.assertLessEqual(np.max(abs(sampled-np.log(parameters['scale_coefficients']))),
                                     limits['absolute_interpolation'])
            for table in prepared.tables:
                self.assertTrue(np.isfinite(table.pixels).all())
                if table.name == 'Web toes':
                    self.assertTrue(table.audit_complete)
                    self.assertTrue(np.isfinite(table.max_relative_interpolation_error))
                    table = legacy_toe(prepared)
                self.check_field_audit(table, settings)
                self.assertTrue(np.isfinite(table.pixels).all())
                if table.segments > 1:
                    packed = table.pixels.reshape(-1, table.segments, table.segment_cells+1, 4)
                    np.testing.assert_array_equal(packed[:, :-1, -1], packed[:, 1:, 0])
                    boundaries = np.arange(1, table.segments)/table.segments
                    np.testing.assert_allclose(table.evaluate(boundaries-np.finfo(np.float32).eps),
                                               table.evaluate(boundaries+np.finfo(np.float32).eps),
                                               atol=2e-3, rtol=2e-5)

    def test_invalid_schema_calibration_and_crossed_handles(self):
        invalid = (ColorSettings(lightness=((0.,),)*4), ColorSettings(chroma_fit=6.1),
                   ColorSettings(lightness_fit=-2.1), ColorSettings(global_gain=float('inf')),
                   ColorSettings(adaptance_half_saturation=.01),
                   ColorSettings(adaptance=((1e6, 0.),)*4),
                   ColorSettings(web=WebSettings(hue_degrees=((0., -180., 0., 0., 0., 0.),)*4)))
        for settings in invalid:
            with self.subTest(settings=settings), self.assertRaises(ValueError):
                prepare(color=settings)
        # The Color fit range does not alter the independently agreed Tone cap.
        with self.assertRaises(ValueError): prepare(tone=ToneSettings(fit=4), color=ColorSettings(chroma_fit=6))


if __name__ == '__main__':
    unittest.main()
