"""Public reference accelerated support and analytic crossover integration."""
from dataclasses import asdict, replace
import unittest
from unittest.mock import patch
import numpy as np
from color_tools.perceptual_grade_core.model import bake_inverse
from color_tools.perceptual_grade_reference.export import OutputCompressionSettings
from color_tools.perceptual_grade_reference.model import LinearSettings, Model, Settings
from color_tools.perceptual_grade_reference.grading import ColorSettings, ToneSettings
from color_tools.perceptual_grade_reference.stack import Stack
from color_tools.perceptual_grade_reference.stack_bake import BakeStack
from color_tools.perceptual_grade_reference.unified_chroma import UnifiedChromaSettings
from color_tools.perceptual_grade_core.model.tonal_web import WebSettings


class ReferenceBakeSupportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.table = BakeStack([Settings()]).table

    def test_unified_chroma_simple_inverse_with_and_without_tone_table(self):
        points = np.array([[.14, .18, .21], [.31, .27, .23], [.1, .1, .1], [0., 0., 0.]], dtype='f4')
        base = UnifiedChromaSettings(muted_gain=-.15, vivid_gain=.23, shadow_chroma=-.2)
        for controls in (base, replace(base, input_nits=(3., 40., 205., 1100.),
                                       black_compression_nits=.5, fit=2)):
            setting = Settings(tone_chroma=controls)
            model = Model(setting, hk_guard=False)
            stack = BakeStack([setting], ['INVERSE'], self.table, hk_guard=False)
            solver = stack.solvers[0]
            with self.subTest(controls=controls):
                self.assertFalse(solver.kernel.identity)
                self.assertTrue(solver.simple)
                self.assertEqual(solver.tone_table is not None, controls != base)
                entered = solver.kernel.enter(points)
                target = solver.kernel.grade(solver.kernel.tone_state(entered))
                np.testing.assert_allclose(target, np.concatenate((
                    model.grade_state(model.enter_native(points)).q,
                    model.grade_state(model.enter_native(points)).energy[:, None],
                ), axis=-1), rtol=2.e-4, atol=2.e-4)
                with patch.object(bake_inverse, 'minimize', side_effect=AssertionError('Unexpected raw fit')):
                    result = solver.evaluate(target, appearance=True)
                self.assertTrue(np.all(result[:, 3] <= solver.acceptance_limit(target, True)), result)
                np.testing.assert_allclose(result[:, :3], points, rtol=3.e-4, atol=1.e-6)

    def test_unified_chroma_stack_cancellation_uses_effective_settings(self):
        baseline = UnifiedChromaSettings(muted_gain=.3, vivid_gain=-.2)
        first = Settings(tone_chroma=baseline)
        second = Settings(tone_chroma=replace(baseline, muted_gain=.1))
        points = np.array([[.11, .18, .17], [.28, .22, .25]], dtype='f4')
        directions = ['FORWARD', 'INVERSE']
        analytic = Stack([first, second], directions, hk_guard=False).apply_native(points)
        baked = BakeStack([first, second], directions, self.table, hk_guard=False)
        self.assertFalse(baked.matching(0, 1))
        self.assertGreater(np.max(abs(analytic - points)), 1.e-4)
        np.testing.assert_allclose(baked.bake_native(points)[:, :3], analytic, atol=2.e-5, rtol=3.e-4)
        matching = BakeStack([first, first], directions, self.table, hk_guard=False)
        np.testing.assert_array_equal(matching.bake_native(points)[:, :3], points)

    def test_low_high_controls_match_analytic_for_every_row(self):
        points = np.array([[.1, .2, .3], [.7, .2, .1], [.02, .08, .4],
                           [.001, .0002, .0001], [0., 0., 0.]], dtype='f4')
        for name in ('lightness', 'chroma'):
            for row in range(4):
                for column, driver in enumerate(('low', 'high')):
                    controls = np.zeros((4, 4)); controls[row, column] = .1
                    settings = Settings(color=ColorSettings(**{name: tuple(map(tuple, controls))}))
                    with self.subTest(name=name, row=row, driver=driver):
                        stack = BakeStack([settings], table=self.table)
                        actual = stack.bake_native(points)[:, :3]
                        expected = Model(settings).forward_native(points.astype(float))
                        error = np.max(abs(actual-expected), axis=-1)
                        self.assertTrue(np.all(error <= np.maximum(.001*np.max(abs(expected), axis=-1), 1e-7)),
                                        (actual, expected))
                        self.assertEqual(len(BakeStack([settings], ['INVERSE'], self.table).solvers), 1)

    def test_later_low_high_grade_and_settings_iterables_work(self):
        affected = Settings(color=ColorSettings(chroma=((0., .1, 0., 0.),)*4))
        self.assertEqual(len(BakeStack(iter([Settings(), affected]), table=self.table).models), 2)
        self.assertEqual(len(BakeStack(iter([])).models), 0)
        with self.assertRaisesRegex(ValueError, 'finite with shape'):
            BakeStack([Settings(color=ColorSettings(lightness=((0.,),)))])

    def test_output_saturation_only_runs_at_the_final_rgb_export(self):
        points = np.array([[.6, .1, .2], [.03, .05, 1.], [.2, .2, .2]], dtype='f4')
        compressed = Settings(output_compression=OutputCompressionSettings(True, .1, .3))
        expected = Model(compressed).forward_native(points)
        self.assertGreater(np.max(abs(expected - points)), .01)
        baseline = Model().forward_native(points)
        np.testing.assert_allclose(expected[-1], baseline[-1], rtol=0., atol=2e-15)
        for settings, directions, target in (
            ([compressed], None, expected),
            ([compressed, Settings()], None, points),
            ([compressed, compressed], None, expected),
            ([compressed, compressed], ['FORWARD', 'INVERSE'], expected),
        ):
            with self.subTest(settings=settings, directions=directions):
                stack = BakeStack(settings, directions, table=self.table)
                result = stack.bake_native(points)
                np.testing.assert_allclose(result[..., :3], target, rtol=3e-4, atol=1e-6)
                np.testing.assert_array_equal(result[..., 3], 0.)
                np.testing.assert_array_equal(result[-1, :3], points[-1])

    def test_inverse_bake_folds_linear_matrix_before_final_export(self):
        points = np.array([[[.6, .1, .2], [.03, .05, 1.], [800., 2., 3.]]], dtype='f4')
        model = Model()
        native_to_xyz = model.cones_to_xyz @ np.linalg.inv(model.boundary.matrix)
        gains = np.array([.5, 1., 2.])
        matrix = native_to_xyz @ np.diag(gains) @ np.linalg.inv(native_to_xyz)
        linear = LinearSettings(matrix=tuple(map(tuple, matrix)))
        for enabled in (False, True):
            controls = OutputCompressionSettings(enabled, .1, .3)
            settings = Settings(linear=linear, output_compression=controls)
            stack = BakeStack([settings], ['INVERSE'], table=self.table)
            expected = Model(settings).release_native_output(points / gains)
            with self.subTest(enabled=enabled):
                actual = stack.bake_native(points)
                np.testing.assert_allclose(actual[..., :3], expected, rtol=3e-4, atol=1e-5)
                np.testing.assert_array_equal(actual[..., 3], 0.)
                np.testing.assert_array_equal(stack.output_matrix, np.eye(3))
                np.testing.assert_array_equal(stack.apply_native(points), actual[..., :3])

    def test_unchanged_controls_remain_accelerated_and_match_analytic(self):
        points = np.array([[.1, .2, .3], [.7, .2, .1], [.02, .08, .4], [0., 0., 0.]], dtype='f4')
        color = ColorSettings(global_gain=.1,
            lightness=((0., 0., .02, -.01),)*4,
            chroma=((0., 0., .03, -.02),)*4,
            adaptance=((.01, -.01),)*4,
            web=WebSettings(hue_degrees=((1.,)*6,)*4))
        cases = [Settings(), Settings(tone=ToneSettings(input_nits=(0., 7., 45., 203., 1000.))),
                 Settings(color=color)]
        table = self.table
        for settings in cases:
            with self.subTest(settings=asdict(settings)):
                stack = BakeStack(iter([settings]), table=table)
                actual = stack.bake_native(points)[:, :3]
                expected = Model(settings).forward_native(points.astype(float))
                error = np.max(abs(actual-expected), axis=-1)
                self.assertTrue(np.all(error <= np.maximum(.001*np.max(abs(expected), axis=-1), 1e-7)),
                                (actual, expected))
                self.assertEqual(len(BakeStack([settings], ['INVERSE'], table).solvers), 1)
                pair = BakeStack([settings, settings], ['FORWARD', 'INVERSE'], table)
                np.testing.assert_array_equal(pair.bake_native(points)[:, :3], points)

    def test_analytic_stack_executes_low_high_controls_and_inverse(self):
        settings = Settings(color=ColorSettings(
            lightness=((.1, -.1, 0., 0.),)*4,
            chroma=((.1, -.05, 0., 0.),)*4))
        source = np.array([[.1, .2, .3], [.6, .25, .1]])
        model = Model(settings)
        target = model.forward_native(source)
        stack = Stack([settings])
        np.testing.assert_allclose(stack.apply_native(source), target, rtol=2e-13, atol=2e-14)
        recovered = Stack([settings], ['INVERSE']).apply_native(target)
        np.testing.assert_allclose(model.forward_native(recovered), target, rtol=2e-8, atol=5e-10)
        np.testing.assert_allclose(Stack([settings, replace(settings, color=ColorSettings())]).apply_native(source),
                                   Model().forward_native(target), rtol=2e-13, atol=2e-14)
