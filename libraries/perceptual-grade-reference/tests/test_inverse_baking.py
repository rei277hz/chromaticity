"""Public reference accelerated support and analytic crossover integration."""
from dataclasses import asdict, replace
from unittest.mock import patch
import unittest
import numpy as np
from color_tools.perceptual_grade_reference.model import Model, Settings
from color_tools.perceptual_grade_reference.grading import ColorSettings, ToneSettings
from color_tools.perceptual_grade_reference.stack import Stack
from color_tools.perceptual_grade_reference.stack_bake import BakeStack
from color_tools.perceptual_grade_core.model.tonal_web import WebSettings


class ReferenceBakeSupportTests(unittest.TestCase):
    def test_low_high_controls_reject_before_kernel_preparation(self):
        for name in ('lightness', 'chroma'):
            for row in range(4):
                for column, driver in enumerate(('low', 'high')):
                    controls = np.zeros((4, 4)); controls[row, column] = .1
                    settings = Settings(color=ColorSettings(**{name: tuple(map(tuple, controls))}))
                    for directions in (['FORWARD'], ['INVERSE'], ['FORWARD', 'INVERSE']):
                        values = [settings]*len(directions)
                        with self.subTest(name=name, row=row, driver=driver, directions=directions):
                            with patch('color_tools.perceptual_grade_reference.stack_bake.Stack.__init__',
                                       side_effect=AssertionError('Prepared unsupported models')):
                                with self.assertRaisesRegex(NotImplementedError,
                                        rf'Grade 0: {name}\[{row}\].{driver}.*analytic'):
                                    BakeStack(values, directions, program_factory=lambda _: self.fail('GPU invoked'))

    def test_later_grade_is_checked_and_settings_iterables_work(self):
        affected = Settings(color=ColorSettings(chroma=((0., .1, 0., 0.),)*4))
        with self.assertRaisesRegex(NotImplementedError, 'Grade 1: chroma'):
            BakeStack(iter([Settings(), affected]))
        self.assertEqual(len(BakeStack(iter([])).models), 0)
        with self.assertRaisesRegex(ValueError, 'finite with shape'):
            BakeStack([Settings(color=ColorSettings(lightness=((0.,),)))])

    def test_unchanged_controls_remain_accelerated_and_match_analytic(self):
        points = np.array([[.1, .2, .3], [.7, .2, .1], [.02, .08, .4], [0., 0., 0.]], dtype='f4')
        color = ColorSettings(global_gain=.1,
            lightness=((0., 0., .02, -.01),)*4,
            chroma=((0., 0., .03, -.02),)*4,
            adaptance=((.01, -.01),)*4,
            web=WebSettings(hue_degrees=((1.,)*6,)*4))
        cases = [Settings(), Settings(tone=ToneSettings(input_nits=(0., 7., 45., 203., 1000.))),
                 Settings(color=color)]
        table = BakeStack([Settings()]).table
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
