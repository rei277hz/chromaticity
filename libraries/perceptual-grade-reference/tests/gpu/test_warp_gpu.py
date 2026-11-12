"""Actual reference GLSL forward, guarded Warp and inverse conformance."""

from dataclasses import replace
import unittest
from unittest.mock import patch

import numpy as np

from color_tools.perceptual_grade_core.model.tonal_web import WebSettings
from color_tools.perceptual_grade_reference.blender_gpu import ForwardProgram
from color_tools.perceptual_grade_reference.grading import ColorSettings, ToneSettings
from color_tools.perceptual_grade_reference.model import Model, Settings
from color_tools.perceptual_grade_reference.responses import hk_energy
from color_tools.perceptual_grade_reference.stack_bake import BakeStack
from .gpu_support import initialize


class WarpGPUComputeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.gpu = initialize()
        cls.base = BakeStack([Settings()])
        cls.table = cls.base.table
        cls.points = np.array([
            [.1, .2, .3], [.7, .2, .1], [.02, .08, .4], [.2, .01, .1],
            [1., 1., 1.], [20., 50., 100.], [0., 0., 0.],
        ], dtype="f4")
        cls.program = cls.base.prepare_gpu()

    def stack(self, settings, directions=None, **kwargs):
        return BakeStack(settings, directions, self.table, **kwargs)

    def assert_normalized_close(self, actual, expected, tolerance=2e-4):
        error = np.max(abs(actual - expected), axis=-1)
        limit = tolerance * (1 + np.max(abs(expected), axis=-1))
        self.assertTrue(np.all(error <= limit), (actual, expected, error, limit))

    def test_forward_kernels_match_cpu_and_independent_reference(self):
        settings = [
            Settings(),
            Settings(tone=ToneSettings(input_nits=(0., 7., 45., 203., 1000.))),
            Settings(color=ColorSettings(
                lightness=((.1, -.1, .02, -.01),) * 4,
                chroma=((.1, -.05, .03, -.02),) * 4,
                adaptance=((.02, -.01),) * 4,
                web=WebSettings(hue_degrees=((1.,) * 6,) * 4))),
            Settings(color=ColorSettings(global_gain=3.,
                adaptance=((.02, -.01),) * 4,
                web=WebSettings(log_scale=((2.,) * 6,) * 4))),
        ]
        forward = ForwardProgram(self.base.kernels[0])
        for setting in settings:
            with self.subTest(setting=setting):
                stack = self.stack([setting])
                kernel = stack.kernels[0]
                self.program.set_inverse(stack.solvers[0])
                actual = self.program.evaluate(self.points, 2)[:, :3]
                self.assert_normalized_close(actual, kernel.evaluate(self.points))
                expected = Model(setting).forward_native(self.points.astype(float))
                self.assert_normalized_close(actual, expected, 1e-3)
                forward.set_kernel(kernel)
                self.assert_normalized_close(forward.evaluate(self.points, 2)[:, :3], actual)
                self.assertTrue(np.all((actual >= 0) & (actual <= 1024)))

    def test_active_guard_precedes_scale_and_preserves_saturation_rays(self):
        radii = []
        saturations = []
        for scale in (-2., 0., 2., 4.):
            setting = Settings(color=ColorSettings(global_gain=3.,
                web=WebSettings(log_scale=((scale,) * 6,) * 4)))
            stack = self.stack([setting])
            kernel = stack.kernels[0]
            self.program.set_inverse(stack.solvers[0])
            actual = self.program.evaluate(self.points, 3)
            expected = kernel.grade(kernel.tone_state(kernel.enter(self.points)))
            self.assert_normalized_close(actual, expected)
            self.assertTrue(np.all(actual[:, 3] >= 0), actual)
            radii.append(np.hypot(actual[:, 1], actual[:, 2]))
            active = actual[:, 3] > 0
            saturations.append(
                np.hypot(actual[active, 1], actual[active, 2]) / np.sqrt(actual[active, 3])
            )
        self.assertTrue(np.all(np.diff(radii, axis=0) >= 0), radii)
        for actual in saturations[1:]:
            np.testing.assert_allclose(actual, saturations[0], rtol=3e-5, atol=3e-6)

    def test_signed_height_policy_and_disabled_guard_match_cpu(self):
        setting = Settings(color=ColorSettings(global_gain=2.,
            web=WebSettings(log_scale=((1.,) * 6,) * 4)))
        states = np.array([
            [-10., 20., 0., hk_energy(-10., 20.)], [0., 0., 0., 0.],
            [50., 20., 0., 1180.], [100., 0., 0., 10000.],
        ], dtype="f4")
        for guarded in (False, True):
            stack = self.stack([setting], hk_guard=guarded)
            self.program.set_inverse(stack.solvers[0])
            actual = self.program.evaluate(states, 8)
            expected = stack.kernels[0].grade(states)
            self.assert_normalized_close(actual, expected)
            self.assertLess(actual[0, 3], 0)
            np.testing.assert_array_equal(actual[1], 0.)

    def test_inverse_rgb_and_appearance_report_complete_forward_residual(self):
        setting = Settings(color=ColorSettings(
            lightness=((.1, -.1, 0., 0.),) * 4,
            chroma=((.1, -.05, 0., 0.),) * 4,
            web=WebSettings(log_scale=((.1,) * 6,) * 4)))
        stack = self.stack([setting], ["INVERSE"])
        solver = stack.solvers[0]
        self.program.set_inverse(solver)
        targets = [solver.kernel.evaluate(self.points),
                   solver.kernel.grade(solver.kernel.tone_state(solver.kernel.enter(self.points)))]
        for appearance, target in enumerate(targets):
            with self.subTest(appearance=appearance):
                actual = self.program.evaluate(target, appearance)
                expected = solver.evaluate(target, bool(appearance))
                self.assert_normalized_close(actual[:, :3], expected[:, :3], 2e-3)
                measured = np.max(abs(solver.residual(actual[:, :3], target, bool(appearance))), axis=-1)
                np.testing.assert_allclose(actual[:, 3], measured, rtol=2e-2, atol=3e-5)
                self.assertTrue(np.all(np.isfinite(actual)))

    def test_nonmatching_stack_handoff_uses_the_guarded_grade(self):
        first = Settings(color=ColorSettings(global_gain=2.,
            web=WebSettings(log_scale=((.5,) * 6,) * 4)))
        second = replace(first, color=replace(first.color, global_gain=1.8))
        stack = self.stack([first, second], ["FORWARD", "INVERSE"])
        expected = stack.bake_native(self.points)
        actual = stack.bake_native(self.points, "GPU", program=self.program)
        self.assert_normalized_close(actual, expected, 3e-3)

    def test_default_adapter_and_factory_failures_are_visible(self):
        stack = self.stack([Settings()])
        stack.program_factory = lambda _: self.program
        self.assertIs(stack.prepare_gpu(), self.program)
        broken = self.stack([Settings()], program_factory=lambda _: (_ for _ in ()).throw(
            RuntimeError("synthetic GPU construction failure")))
        with self.assertRaisesRegex(RuntimeError, "synthetic GPU"):
            broken.bake_native(self.points, "GPU")
        self.program.set_inverse(self.base.solvers[0])
        with patch.object(self.gpu.compute, "dispatch", side_effect=RuntimeError("synthetic dispatch failure")):
            with self.assertRaisesRegex(RuntimeError, "synthetic dispatch"):
                self.program.evaluate(self.points, 2)


if __name__ == "__main__":
    unittest.main()
