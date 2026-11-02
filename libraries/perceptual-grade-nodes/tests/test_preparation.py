"""Independent stage/preparation comparisons and coefficient data obligations."""
from dataclasses import replace
from contextlib import ExitStack
from unittest.mock import patch
import sys
import unittest
import numpy as np

from color_tools.perceptual_grade_nodes import (
    LinearSettings, ToneSettings, ColorSettings, WebSettings, Settings, prepare, prepare_linear,
    prepare_tone as runtime_prepare_tone, prepare_update)
from color_tools.perceptual_grade_nodes.prepare import linear_matrix, project_source_white
from color_tools.perceptual_grade_nodes import project_source_white_component
from color_tools.perceptual_grade_nodes.settings import D65
from color_tools.perceptual_grade_nodes.tables import (
    TABLE_ERROR_LIMIT, build_diagnostic_table, build_runtime_table, build_table, coefficients, derivative_bernstein,
    kernel, readonly, select_table, audit_tone)
from color_tools.perceptual_grade_reference import model as reference
from color_tools.perceptual_grade_reference.grading import Tone, ToneSettings as ReferenceTone


def prepare_tone(*args, **kwargs):
    """These development numerical tests explicitly request dense receipts."""
    return audit_tone(runtime_prepare_tone(*args, **kwargs))


class PreparationTests(unittest.TestCase):
    def test_import_is_host_free(self):
        self.assertNotIn('bpy', sys.modules)

    def test_linear_controls_match_independent_matrix(self):
        cases = [LinearSettings(), LinearSettings(exposure=2.),
                 LinearSettings(source_xy=project_source_white((.8, 0.))),
                 LinearSettings(exposure=.7, source_xy=(.34567, .3585),
                                balance=(.4, -.2), spread=(45., -50.), heading=(-38., 72.))]
        for field, values in [('balance', (-2., 2.)), ('spread', (-100., 150.)),
                              ('heading', (-180., 180.))]:
            for axis in range(2):
                for value in values:
                    pair = [0., 0.]; pair[axis] = value
                    cases.append(replace(LinearSettings(), **{field: tuple(pair)}))
        white = reference.xyz_from_xy(reference.WHITES['D65'])
        for settings in cases:
            with self.subTest(settings=settings):
                expected = reference.linear_matrix(reference.LinearSettings(**vars(settings)), white)
                np.testing.assert_allclose(linear_matrix(settings), expected, rtol=2e-12, atol=2e-12)

    def test_white_projection_matches_reference(self):
        for point in ((0., 0.), (.9, .9), (.1, .7), (.3127, .329), (1., -1.)):
            np.testing.assert_allclose(project_source_white(point), reference.source_white(point), atol=1e-14)

    def test_white_component_projection_keeps_the_other_coordinate(self):
        for axis in (0, 1):
            for value in (0.0, 0.9):
                point = [D65[0], D65[1]]
                point[axis] = value
                point = tuple(point)
                result = project_source_white_component(point, axis)
                projected = list(point)
                projected[axis] = result
                with self.subTest(point=point, axis=axis):
                    self.assertEqual(projected[1-axis], D65[1-axis])
                    np.testing.assert_allclose(
                        project_source_white(projected), projected, atol=1e-12
                    )
        with self.assertRaises(ValueError):
            project_source_white_component((.3127, .329), 2)

    def test_matrix_override_is_authoritative_even_when_singular(self):
        # API robustness; this is not a UI-authored accuracy case.
        matrix = ((1., .2, 0.), (0., 0., 0.), (0., -.1, 1.))
        settings = LinearSettings(exposure=6., balance=(2., -2.), matrix=matrix)
        np.testing.assert_array_equal(linear_matrix(settings), matrix)
        self.assertEqual(np.linalg.matrix_rank(prepare_linear(settings).rgb_matrix), 2)

    def test_scene_adapters_and_scalar_identity(self):
        for space in reference.RGB_SPACES:
            actual = prepare_linear(LinearSettings(exposure=2.), space)
            expected = reference.rgb_matrix(space)
            rgb_white = reference.xyz_from_xy(
                reference.colour.RGB_COLOURSPACES[reference.RGB_SPACES[space]].whitepoint)
            white = reference.xyz_from_xy(reference.WHITES['D65'])
            expected = reference.adaptation(rgb_white, white, 'Bradford') @ expected
            np.testing.assert_allclose(actual.rgb_to_xyz, expected, rtol=2e-13, atol=2e-14)
            np.testing.assert_array_equal(actual.rgb_matrix, 4*np.eye(3))
            np.testing.assert_allclose(actual.from_cones @ actual.to_cones, np.eye(3), atol=2e-15)
            np.testing.assert_allclose(actual.linear_to_cones, actual.to_cones*4, atol=3e-15)
            self.assertFalse(actual.rgb_matrix.flags.writeable)

    def test_analytic_tone_and_quintic_256(self):
        cases = [ToneSettings(),
                 ToneSettings(input_nits=(0., 8., 40., 235., 1150.)),
                 ToneSettings(input_nits=(.2, .21, 42., 250., 1300.), fit=2.),
                 ToneSettings(input_nits=(.01, 1., 90., 400., 4000.), fit=-2.),
                 ToneSettings(input_nits=(0., .01, .1, 203., 10000.), fit=2.),
                 ToneSettings(input_nits=(0., .01, .1, 10., 100.), fit=2., peak_nits=4000.)]
        sizes = []
        for settings in cases:
            with self.subTest(settings=settings):
                prepared = prepare_tone(settings)
                oracle = Tone(ReferenceTone(**vars(settings)))
                probes = np.r_[np.linspace(0., 600., 12001), np.geomspace(1e-10, 1e7, 4097),
                               100*oracle.source]
                expected = oracle.remap(probes)
                actual = prepared.remap(probes)
                error = np.max(abs(actual-expected)/np.maximum(1., abs(expected)))
                self.assertLess(error, 2e-12)
                if not prepared.active:
                    self.assertIsNone(prepared.table)
                    continue
                self.assertLessEqual(prepared.table.max_error, TABLE_ERROR_LIMIT)
                self.assertTrue(prepared.table.monotone)
                self.assertFalse(prepared.table.jets.flags.writeable)
                np.testing.assert_array_equal(prepared.table.pixels.reshape(-1, 4)[:prepared.table.cells+1, :3],
                                              prepared.table.jets)
                self.assertGreater(prepared.table.probe_count, prepared.table.cells*16)
                sizes.append(prepared.table.cells)
        self.assertIn(256, sizes)
        self.assertEqual(set(sizes), {256})

    def test_quantized_monotonicity_and_shared_joins(self):
        tone = prepare_tone(ToneSettings(input_nits=(.2, .21, 42., 250., 1300.), fit=2.))
        for cells in (256, 2048):
            table = build_table(tone, cells)
            poly = coefficients(table.jets)
            self.assertGreaterEqual(float(np.min(derivative_bernstein(poly))), -2e-13)
            # Adjacent intervals recover the same stored value/derivatives.
            np.testing.assert_allclose(np.sum(poly, axis=-1), table.jets[1:, 0], atol=2e-15)
            np.testing.assert_allclose(np.sum(poly[:, 1:]*np.arange(1, 6), axis=-1),
                                       table.jets[1:, 1], atol=5e-15)
            np.testing.assert_allclose(np.sum(poly[:, 2:]*np.arange(2, 6)*np.arange(1, 5), axis=-1),
                                       table.jets[1:, 2], atol=2e-14)
        self.assertEqual(tone.table.cells, 256)

    def test_diagnostic_tone_sizes_shrink_storage_without_changing_runtime_layout(self):
        tone = prepare_tone(ToneSettings(input_nits=(.2, .21, 42., 250., 1300.), fit=2.))
        canonical = build_runtime_table(tone, 256)
        self.assertEqual(canonical.pixels.shape, (1, 512, 4))
        for cells in (256, 128, 64, 32):
            with self.subTest(cells=cells):
                table = build_diagnostic_table(tone, cells)
                self.assertEqual(table.pixels.shape, (1, cells+1, 4))
                self.assertLess(table.memory_bytes, canonical.memory_bytes)
                self.assertTrue(table.monotone)
                self.assertTrue(np.isfinite(table.max_error))
                self.assertGreater(table.probe_count, cells*16)
        with self.assertRaisesRegex(ValueError, '256 or 2048'):
            build_runtime_table(tone, 512)
        for cells in (0, 31, 33):
            with self.subTest(invalid_cells=cells), self.assertRaises(ValueError):
                build_diagnostic_table(tone, cells)

    def test_two_hundred_ui_valid_curves_select_a_passing_table(self):
        rng = np.random.default_rng(20261027)
        lower = np.array((0., .01, .1, 10., 100.))
        upper = np.array((2., 50., 250., 1000., 10000.))
        conversion = Tone(ReferenceTone())
        selected = set()
        checked = 0
        for _ in range(1000):
            anchors = tuple(lower+(upper-lower)*rng.random(5))
            # The UI clamps an edit against both neighbors in neutral J.
            # Filter with the independent oracle before preparation so its
            # minimum-spacing regularization cannot admit crossed anchors.
            if np.any(np.diff(conversion.nits_to_j(anchors)) < .001):
                continue
            settings = ToneSettings(anchors, int(rng.integers(-2, 3)), 203.,
                                    float(rng.choice((500, 1000, 2000, 4000))))
            prepared = prepare_tone(settings)
            oracle = Tone(ReferenceTone(**vars(settings)))
            t = np.linspace(0., 8., 4097, dtype=np.float32)
            h = 100*(prepared.black+prepared.span*t.astype(float))
            expected = oracle.remap(h)
            z = np.minimum(t/np.float32(prepared.table.domain), np.float32(1))
            actual = np.float32(100)*(np.float32(prepared.slope)*t+prepared.table.evaluate(z))
            error = float(np.max(abs(actual-expected)/np.maximum(1., abs(expected))))
            self.assertLessEqual(error, TABLE_ERROR_LIMIT, settings)
            selected.add(prepared.table.cells)
            checked += 1
            if checked == 200:
                break
        self.assertEqual(checked, 200)
        self.assertEqual(selected, {256})

    def test_invalid_preparation_is_explicit(self):
        for value in (LinearSettings(exposure=float('inf')), LinearSettings(exposure=1000.),
                      LinearSettings(matrix=((1., 2.), (3., 4.))),
                      LinearSettings(balance=(0.,))):
            with self.assertRaises(ValueError): prepare_linear(value)
        for value in (ToneSettings(fit=3), ToneSettings(fit=4), ToneSettings(fit=6), ToneSettings(fit=7),
                      ToneSettings(reference_nits=100.),
                      ToneSettings(input_nits=(0., 1., 2.)), ToneSettings(peak_nits=float('nan'))):
            with self.assertRaises(ValueError): prepare_tone(value)
        with self.assertRaises(ValueError): prepare(space='display-sRGB')

    def test_crossed_anchor_robustness_does_not_relax_quality_gate(self):
        # This cannot be authored through the UI's neighbor-J constraints.
        # The reference regularizes it, but that does not excuse shipping a
        # table that misses the agreed scalar error bound.
        value = ToneSettings(input_nits=(1.68, 46.64, 58.98, 920.94, 669.76),
                             fit=2, peak_nits=500.)
        prepared = prepare_tone(value)
        oracle = Tone(ReferenceTone(**vars(value)))
        np.testing.assert_allclose(prepared.source, oracle.source, atol=1e-14)
        self.assertEqual(prepared.table.cells, 256)
        self.assertLessEqual(prepared.table.max_error, TABLE_ERROR_LIMIT)

    def test_rounding_bin_probes_reject_a_false_sparse_pass(self):
        # Fit 4 is outside the public contract. Construct its table directly
        # to retain the regression that motivated rounding-bin-edge probes:
        # 16-per-cell probes at 512 cells reported 7.86e-6, but bin edges
        # exceed 1e-5. The current 256-cell selector must reject it too.
        settings = ToneSettings(input_nits=(0., 5., 20., 100., 100.33905282838904),
                                fit=2., peak_nits=4000.)
        prepared = prepare_tone(settings)
        width = prepared.width/4
        norms = readonly([kernel(1., left, right, width)
                          for left, right in zip(prepared.knots[:-1], prepared.knots[1:])])
        sharp = replace(prepared, settings=replace(settings, fit=4.),
                        width=width, norms=norms, table=None)
        self.assertGreater(build_diagnostic_table(sharp, 512).max_error, TABLE_ERROR_LIMIT)
        self.assertGreater(build_table(sharp, 256).max_error, TABLE_ERROR_LIMIT)
        with self.assertRaisesRegex(ValueError, 'Quintic 256 does not meet'):
            select_table(sharp)


class FixedRuntimePreparationTests(unittest.TestCase):
    def test_prior_cached_tone_does_not_bypass_fit_domain(self):
        current = prepare(full_fields=True)
        obsolete_settings = replace(current.tone.settings, fit=3.)
        prior = replace(current, tone=replace(current.tone, settings=obsolete_settings))
        with self.assertRaisesRegex(ValueError, r'Tone fit domain is \[-2, 2\]'):
            prepare_update(Settings(tone=obsolete_settings), prior)

    def test_same_settings_replace_prior_tone_512_and_preserve_current_reuse(self):
        for settings in (Settings(), Settings(tone=ToneSettings(
                input_nits=(0., 8., 40., 235., 1150.), fit=2.))):
            with self.subTest(tone=settings.tone):
                current = prepare(settings.linear, settings.tone, settings.space,
                                  color=settings.color, full_fields=True)
                self.assertEqual(current.table.cells, 256)
                self.assertEqual(current.table.pixels.shape, (1, 512, 4))
                self.assertEqual(current.table.memory_bytes, 8192)
                self.assertIs(prepare_update(settings, current).tone, current.tone)
                old_table = build_diagnostic_table(current.tone, 512)
                old_tone = replace(current.tone, table=old_table)
                prior = replace(current, tone=old_tone)
                refreshed = prepare_update(settings, prior)
                self.assertIsNot(refreshed.tone, old_tone)
                self.assertEqual(refreshed.table.cells, 256)
                np.testing.assert_array_equal(refreshed.table.pixels, current.table.pixels)
                self.assertIs(refreshed.color, current.color)

    def test_same_settings_reject_obsolete_fields_and_preserve_current_layout_reuse(self):
        from color_tools.perceptual_grade_nodes.layouts import FIELD_CELLS
        baseline = prepare(full_fields=True)
        self.assertIs(prepare_update(Settings(), baseline).color, baseline.color)
        old_cells = {'coefficient_table': 131072, 'adaptance_table': 16384,
                     'web_table': 32768, 'web_toe_table': 1280}
        for attribute, cells in old_cells.items():
            with self.subTest(attribute=attribute):
                expected = getattr(baseline.color, attribute)
                segment = min(cells, 8192)
                segments = cells // segment
                rows = expected.semantic_rows * segments
                height = 1 << (rows - 1).bit_length()
                pixels = np.full((height, segment+1, 4), -123., np.float32)
                obsolete = replace(expected, cells=cells, segments=segments,
                                   segment_cells=segment, pixels=pixels)
                prior = replace(baseline, color=replace(baseline.color, **{attribute: obsolete}))
                refreshed = prepare_update(Settings(), prior)
                actual = getattr(refreshed.color, attribute)
                self.assertEqual(actual.cells, FIELD_CELLS[expected.name])
                self.assertIsNot(actual, obsolete)
                np.testing.assert_array_equal(actual.pixels, expected.pixels)
                for other in ('coefficient_table', 'adaptance_table', 'web_table', 'web_toe_table'):
                    if other != attribute:
                        self.assertIs(getattr(refreshed.color, other), getattr(baseline.color, other))

    def test_same_size_prior_schema_fields_are_regenerated(self):
        from color_tools.perceptual_grade_nodes.layouts import LAYOUT_SCHEMA
        baseline = prepare(full_fields=True)
        self.assertEqual(LAYOUT_SCHEMA, 5)
        for attribute in ('coefficient_table', 'adaptance_table', 'web_table', 'web_toe_table'):
            with self.subTest(attribute=attribute):
                expected = getattr(baseline.color, attribute)
                obsolete = replace(expected, schema=3)
                prior = replace(baseline, color=replace(baseline.color, **{attribute: obsolete}))
                refreshed = prepare_update(Settings(), prior)
                actual = getattr(refreshed.color, attribute)
                self.assertIsNot(actual, obsolete)
                self.assertEqual(actual.schema, LAYOUT_SCHEMA)
                np.testing.assert_array_equal(actual.pixels, expected.pixels)

    def test_prior_dual_table_color_schema_is_replaced_even_at_reset(self):
        baseline = prepare(full_fields=True)
        obsolete_schema = replace(baseline.color, layout_schema=3)
        obsolete_field = replace(baseline.color)
        object.__setattr__(obsolete_field, 'adaptance_interior_table', None)
        for old_color in (obsolete_schema, obsolete_field):
            with self.subTest(layout_schema=old_color.layout_schema,
                              legacy_field=hasattr(old_color, 'adaptance_interior_table')):
                prior = replace(baseline, color=old_color)
                refreshed = prepare_update(Settings(), prior)
                self.assertIsNot(refreshed.color, old_color)
                self.assertEqual(refreshed.color.layout_schema, 5)
                self.assertFalse(hasattr(refreshed.color, 'adaptance_interior_table'))

    def test_strong_controls_keep_one_fixed_adaptance_field(self):
        neutral = prepare(full_fields=True)
        for tail in ((0., 0.), (4., -1.)):
            settings = ColorSettings(adaptance=((-260.8694152832031, 0.),
                (0., 0.), (0., 0.), tail))
            current = prepare_update(Settings(color=settings), neutral)
            self.assertGreater(float(np.max(abs(current.color.log_gains))), 1.)
            self.assertFalse(hasattr(current.color, 'adaptance_interior_table'))
            self.assertEqual(len(current.color.tables), 4)
            self.assertEqual(current.color.adaptance_table.cells, 3072)
            self.assertEqual(current.color.adaptance_table.mapping, 'response_compact')
            self.assertIs(current.color.coefficient_table, neutral.color.coefficient_table)
            self.assertIs(current.color.web_table, neutral.color.web_table)
            self.assertIs(current.color.web_toe_table, neutral.color.web_toe_table)

    def test_runtime_never_searches_or_runs_dense_gates(self):
        import importlib
        color_module = importlib.import_module('color_tools.perceptual_grade_nodes.color_prepare')
        tone_module = importlib.import_module('color_tools.perceptual_grade_nodes.tables')
        with ExitStack() as stack:
            for module, names in ((color_module, ('_build_field', '_audit_field', '_table_probes')),
                                  (tone_module, ('audit_table', '_probes', 'select_table', 'build_table'))):
                for name in names:
                    stack.enter_context(patch.object(module, name, side_effect=AssertionError('runtime audit: '+name)))
            neutral = prepare(full_fields=True)
            self.assertFalse(neutral.tone.active)
            self.assertFalse(neutral.color.active)
            self.assertIsNotNone(neutral.table)
            self.assertEqual(len(neutral.color.tables), 4)
            changed = prepare_update(Settings(tone=ToneSettings(input_nits=(0., 8., 40., 235., 1150.)),
                color=ColorSettings(global_gain=.2, web=WebSettings(hue_degrees=((1.,)*6,)*4))), neutral)
        self.assertIsNone(changed.table.max_error)
        self.assertIsNone(changed.table.probe_count)
        for table in changed.color.tables:
            self.assertIsNone(table.max_error)
            self.assertIsNone(table.probe_count)
            self.assertIsNone(table.field_errors)
            self.assertFalse(table.pixels.flags.writeable)
        self.assertEqual([t.pixels.shape for t in neutral.color.tables],
                         [t.pixels.shape for t in changed.color.tables])

    def test_update_reuses_only_dependency_compatible_fields(self):
        neutral = prepare(full_fields=True)
        exposure = prepare_update(Settings(linear=LinearSettings(exposure=.2)), neutral)
        self.assertIs(exposure.tone, neutral.tone)
        self.assertIsNot(exposure.linear, neutral.linear)
        self.assertTrue(all(a is b for a, b in zip(exposure.color.tables, neutral.color.tables)))
        gain = prepare_update(Settings(color=ColorSettings(global_gain=.3)), neutral)
        self.assertTrue(all(a is b for a, b in zip(gain.color.tables, neutral.color.tables)))
        hue = prepare_update(Settings(color=ColorSettings(web=WebSettings(hue_degrees=((1.,)*6,)*4))), neutral)
        self.assertIsNot(hue.color.web_table, neutral.color.web_table)
        self.assertIs(hue.color.web_toe_table, neutral.color.web_toe_table)
        self.assertIs(hue.color.coefficient_table, neutral.color.coefficient_table)
        adapted = prepare_update(Settings(color=ColorSettings(adaptance=((1., 0.),)*4)), neutral)
        self.assertIsNot(adapted.color.adaptance_table, neutral.color.adaptance_table)
        self.assertIs(adapted.color.web_table, neutral.color.web_table)
        peak = prepare_update(Settings(tone=ToneSettings(peak_nits=2000.)), neutral)
        self.assertTrue(all(a is not b for a, b in zip(peak.color.tables, neutral.color.tables)))
        self.assertEqual([t.pixels.shape for t in peak.color.tables], [t.pixels.shape for t in neutral.color.tables])


if __name__ == '__main__':
    unittest.main()
