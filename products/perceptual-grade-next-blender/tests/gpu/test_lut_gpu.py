"""Actual GPU full Grade Stack evaluation and native lookup parity."""

import asyncio
from dataclasses import asdict, replace
from functools import partial
import unittest
from unittest.mock import patch

import bpy
import gpu
import numpy as np

from color_tools.kernel import lut
from color_tools.template_build.stage2_graph import build_stage2_group
from color_tools.kernel.settings import ColorSettings, LinearSettings, Settings, ToneSettings, WebSettings
from color_tools.lut_gpu import StackGPUBackend
from color_tools.perceptual_grade_reference import grading, model
from color_tools.perceptual_grade_reference.cube_guard import guard as cube_guard
from color_tools.features.grade.preparation import GradePreparer
from tools.perceptual_grade.reports.native import NativeFixture
from tools.perceptual_grade.reports import oracle
from tools.perceptual_grade.reports.full_cases import guard_before_scale_grade
from .gpu_support import initialize


def evaluate_stack_ap1(rgb, settings, space, *, skip_hk_at=None, project_output=True):
    """Compose reference Grades in AP1 and optionally project the final output."""
    value = np.asarray(rgb, dtype=np.float64)
    for index, item in enumerate(settings):
        linear, _ = oracle.parameters(item.linear, item.tone)
        color = grading.ColorSettings(**asdict(item.color))
        reference = model.Model(model.Settings(
            linear=linear, color=color,
            tone_chroma=oracle.reference_chroma(item.tone).settings,
        ),
                                space, hk_guard=index != skip_hk_at)
        boundary = oracle.exact_boundary(reference)
        to_scene = reference.xyz_to_rgb @ reference.cones_to_xyz @ np.linalg.inv(boundary.matrix)
        neutral = value[..., 1, None]
        scene_rgb = neutral + (value - neutral) @ to_scene.T
        toned = oracle.evaluate(scene_rgb, item.linear, item.tone, space)["tone"]
        graded = reference.color.apply_state(toned)
        if project_output and index == len(settings) - 1:
            value = cube_guard(boundary, graded.q, graded.energy)[2]
        else:
            value = boundary.decode(graded.q, graded.energy)
    return value


class LUTGPUComputeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.gpu = initialize()

    def prepare(self, settings):
        preparer = GradePreparer()
        try:
            async def run():
                return await asyncio.gather(*(preparer.prepare(item) for item in settings))
            return tuple(asyncio.run(run()))
        finally:
            preparer.close()

    def bake(self, settings=(), *, directions=None, space="ACEScg", progressive=False,
             interleave=False):
        settings = tuple(replace(item, space=space) for item in settings)
        prepared = self.prepare(settings)
        backend = StackGPUBackend()
        job = backend.create_prepared(prepared, space, progressive, settings=settings,
                                      directions=directions)
        receipts = {}
        unrelated = None
        try:
            while "full" not in receipts:
                receipt = job.advance()
                if interleave and unrelated is None:
                    pixels = np.tile(np.array((7., 11., 13., 17.), np.float32), (16, 16, 1))
                    unrelated = self.gpu.types.GPUTexture(
                        (16, 16), format="RGBA32F",
                        data=self.gpu.types.Buffer("FLOAT", pixels.shape, pixels),
                    )
                    np.testing.assert_array_equal(np.asarray(unrelated.read()).reshape(16, 16, 4), pixels)
                if receipt is not None:
                    quality, result = receipt
                    receipts[quality] = result
        finally:
            job.close()
            backend.close()
        return receipts, prepared

    def test_empty_stack_identity_and_atlas_packing(self):
        receipts, _ = self.bake(progressive=True, interleave=True)
        preview, full = receipts["preview"].cube, receipts["full"].cube
        axis = lut.axis()
        expected = np.stack(np.meshgrid(axis, axis, axis, indexing="ij"), axis=-1)
        np.testing.assert_allclose(full.values, expected, rtol=0, atol=1e-4)
        np.testing.assert_array_equal(preview.values, full.values[::2, ::2, ::2])
        self.assertEqual(full.shader_pixels().shape, (lut.ATLAS_HEIGHT, lut.ATLAS_WIDTH, 4))
        self.assertTrue(np.isfinite(full.compositor_pixels()).all())

    def test_ordered_tone_grades_match_independent_reference_and_actual_edges(self):
        settings = (
            Settings(linear=LinearSettings(exposure=.4, balance=(.1, -.1)),
                     tone=ToneSettings(input_nits=(6., 42., 235., 1150.), fit=.5,
                                       muted_gain=-.4, vivid_gain=.35, shadow_chroma=.25)),
            Settings(linear=LinearSettings(exposure=-.15),
                     tone=ToneSettings(input_nits=(4., 32., 190., 950.), fit=-.25,
                                       black_compression_nits=.4)),
        )
        receipts, _ = self.bake(settings, progressive=True)
        full, preview = receipts["full"].cube, receipts["preview"].cube
        ids = np.array(((0, 0, 0), (8, 13, 20), (20, 17, 28), (32, 30, 24),
                        (40, 45, 32), (64, 40, 20), (64, 64, 64)))
        points = lut.axis()[ids]
        expected = evaluate_stack_ap1(points, settings, "ACEScg")
        actual = full.values[tuple(ids.T)]
        normalized = np.max(abs(actual - expected), axis=-1) / (1 + np.max(abs(expected), axis=-1))
        self.assertLessEqual(float(np.max(normalized)), 1e-4)
        np.testing.assert_array_equal(preview.values, full.values[::2, ::2, ::2])
        for axis in range(3):
            selected = [slice(None)] * 4
            selected[axis] = slice(None, -1)
            np.testing.assert_array_equal(full.edge_values[axis][tuple(selected)],
                                          np.diff(full.values, axis=axis))

    def test_gpu_vertices_match_shader_and_compositor_grade_graphs_in_scene_basis(self):
        settings = (Settings(
            linear=LinearSettings(exposure=.25, source_xy=(.31, .34)),
            tone=ToneSettings(input_nits=(5., 38., 225., 1200.), fit=.25,
                              black_compression_nits=.65, muted_gain=-.5, vivid_gain=.7,
                              saturation_crossover=.36, shadow_chroma=.5, highlight_chroma=-.4),
            color=guard_before_scale_grade(),
        ),)
        receipts, prepared = self.bake(settings, space="Linear Rec.2020")
        cube = receipts["full"].cube
        ids = np.tile(np.array(((8, 13, 20), (20, 17, 28), (32, 30, 24),
                               (40, 45, 32))), (64, 1))
        ap1 = lut.axis()[ids]
        scene = ap1 @ cube.from_lut.T
        alpha = np.tile(np.array((.1, .3, .7, 1.)), 64)
        values = np.column_stack((scene, alpha))
        expected = cube.values[tuple(ids.T)] @ cube.from_lut.T
        for context in ("shader", "compositor"):
            fixture = NativeFixture(
                prepared[0], values, context,
                builder=partial(build_stage2_group, diagnostics=True),
            )
            try:
                actual = fixture.render()
            finally:
                fixture.close()
            error = np.max(abs(actual["rgb"] - expected), axis=-1) / (1 + np.max(abs(expected), axis=-1))
            index = int(np.argmax(error))
            self.assertLessEqual(float(error[index]), 1e-4, {
                "context": context, "index": index,
                "actual": actual["rgb"][index].tolist(),
                "expected": expected[index].tolist(),
            })
            np.testing.assert_allclose(actual["alpha"], values[:, 3], rtol=0, atol=1e-6)

    def test_ordered_color_grades_guard_before_scale_in_both_resolutions(self):
        warp = guard_before_scale_grade()
        warp = replace(warp, web=replace(warp.web, log_chroma=((2.,) * 6,) * 4,
                                         log_scale=((.5,) * 6,) * 4))
        settings = (
            Settings(linear=LinearSettings(exposure=-6.),
                     tone=ToneSettings(muted_gain=2., vivid_gain=2., shadow_chroma=2.),
                     color=warp),
            Settings(color=warp),
        )
        ids = np.array(((0, 0, 0), (40, 0, 0), (0, 40, 0), (0, 0, 40),
                        (16, 16, 16), (32, 32, 32), (64, 64, 64)))
        source = lut.axis()[ids]
        expected = evaluate_stack_ap1(source, settings, "ACEScg")
        for index in range(len(settings)):
            skipped = evaluate_stack_ap1(source, settings, "ACEScg", skip_hk_at=index)
            self.assertFalse(np.allclose(expected, skipped), f"H-K repair at entry {index + 1}")
        receipts, _ = self.bake(settings, progressive=True)
        for quality, indices in (("preview", ids//2), ("full", ids)):
            with self.subTest(quality=quality):
                actual = receipts[quality].cube.values[tuple(indices.T)]
                normalized = np.max(abs(actual-expected), axis=-1)/(1+np.max(abs(expected), axis=-1))
                self.assertLessEqual(float(np.max(normalized)),1e-4)
        np.testing.assert_array_equal(receipts["preview"].cube.values,
                                      receipts["full"].cube.values[::2,::2,::2])

    def test_stack_projects_only_after_final_grade(self):
        settings = (
            Settings(linear=LinearSettings(exposure=2.)),
            Settings(linear=LinearSettings(exposure=-1.)),
        )
        receipts, _ = self.bake(settings, progressive=True)
        full_ids = np.array(((60, 60, 60), (64, 64, 64)))
        preview_ids = full_ids // 2
        expected = evaluate_stack_ap1(lut.axis()[full_ids], settings, "ACEScg")
        np.testing.assert_allclose(expected[0], lut.axis()[60] * 2., rtol=0, atol=1e-2)
        np.testing.assert_allclose(expected[1], (1024., 1024., 1024.), rtol=0, atol=1e-2)
        for quality, indices in (("preview", preview_ids), ("full", full_ids)):
            with self.subTest(quality=quality):
                actual = receipts[quality].cube.values[tuple(indices.T)]
                np.testing.assert_allclose(actual, expected, rtol=1e-4, atol=1e-2)

    def test_stack_rejects_a_pole_invalid_intermediate_decode(self):
        settings = (
            Settings(color=ColorSettings(web=WebSettings(log_scale=((8.,)*6,)*4))),
            Settings(),
        )
        primary_vertices = np.identity(3) * lut.MAXIMUM
        with self.assertRaisesRegex(ValueError, "Response pole"):
            evaluate_stack_ap1(primary_vertices, settings, "ACEScg")
        with self.assertRaisesRegex(ArithmeticError, "intermediate Grade could not decode"):
            self.bake(settings)

    def test_inverse_to_forward_with_distinct_tone_curves_matches_neutral_oracle(self):
        first = Settings(tone=ToneSettings(
            input_nits=tuple(.5 * value for value in ToneSettings().input_nits), fit=.5,
        ))
        second = Settings(tone=ToneSettings(input_nits=(9., 60., 290., 1400.), fit=-.25,
                                             black_compression_nits=.65))
        ids = np.array((12, 24, 32, 40, 48, 56, 64))
        target = lut.axis()[ids]
        white = np.full((1, 3), lut.MAXIMUM)
        # The initial inverse candidate for white would reproduce projected
        # white exactly, even though its raw forward result is much brighter.
        raw_white = evaluate_stack_ap1(white, (first,), "ACEScg", project_output=False)
        self.assertGreater(float(raw_white.min()), 1.1 * lut.MAXIMUM)
        np.testing.assert_allclose(evaluate_stack_ap1(white, (first,), "ACEScg"), white)
        to_lut, from_lut = lut.basis("ACEScg")
        low, high = np.zeros_like(target), np.full_like(target, lut.MAXIMUM)
        # The independent Tone is monotonic along a neutral ray, so its preimage
        # is bracketed without using the shader's seeds or nonlinear solver.
        for _ in range(48):
            middle = (low + high) / 2
            gray_ap1 = np.broadcast_to(middle[:, None], (len(middle), 3))
            gray_scene = gray_ap1 @ from_lut.T
            actual_scene = oracle.evaluate(
                gray_scene, first.linear, first.tone, "ACEScg",
            )["rgb"]
            actual = (actual_scene @ to_lut.T)[:, 1]
            below = actual < target
            low, high = np.where(below, middle, low), np.where(below, high, middle)
        preimage = np.broadcast_to(((low + high) / 2)[:, None], (len(ids), 3))
        expected = evaluate_stack_ap1(preimage, (second,), "ACEScg")
        self.assertFalse(np.allclose(expected[:, 1], target))
        receipts, _ = self.bake((first, second), directions=("INVERSE", "FORWARD"),
                                progressive=True)
        actual = receipts["full"].cube.values[ids, ids, ids]
        np.testing.assert_allclose(actual, expected, rtol=2e-4, atol=3e-5)
        np.testing.assert_array_equal(receipts["preview"].cube.values,
                                      receipts["full"].cube.values[::2, ::2, ::2])

    def test_different_inverse_forward_matrices_preserve_signed_intermediate(self):
        # The input of the inverted Linear is negative on every nonzero sample.
        # The two different matrices compose to a positive half-exposure scale.
        inverse = Settings(linear=LinearSettings(matrix=tuple(map(tuple, -np.eye(3)))))
        forward = Settings(linear=LinearSettings(matrix=tuple(map(tuple, -.5 * np.eye(3)))))
        receipts, _ = self.bake((inverse, forward), directions=("INVERSE", "FORWARD"),
                                space="Linear Rec.2020")
        ids = np.array(((20, 18, 24), (36, 40, 34), (50, 53, 52)))
        np.testing.assert_allclose(receipts["full"].cube.values[tuple(ids.T)],
                                   .5 * lut.axis()[ids], rtol=2e-4, atol=3e-5)

    def test_forward_inverse_and_consecutive_inverse_recover_signed_values(self):
        flip = Settings(linear=LinearSettings(matrix=tuple(map(tuple, -np.eye(3)))))
        down = Settings(linear=LinearSettings(exposure=-1.))
        receipts, _ = self.bake((flip, Settings(), down),
                                directions=("FORWARD", "INVERSE", "INVERSE"))
        ids = np.array((10, 32, 48, 64))
        expected = np.broadcast_to((-2 * lut.axis()[ids])[:, None], (len(ids), 3))
        np.testing.assert_allclose(receipts["full"].cube.values[ids, ids, ids], expected,
                                   rtol=2e-4, atol=3e-5)

    def test_inverse_requires_invertible_linear(self):
        singular = Settings(linear=LinearSettings(matrix=((1., 0., 0.),) * 3))
        with self.assertRaisesRegex(ValueError, "singular Linear"):
            self.bake((singular,), directions=("INVERSE",))

    def test_tone_chroma_round_trip_recovers_signed_chromatic_intermediates(self):
        grade = Settings(
            linear=LinearSettings(matrix=tuple(map(tuple, -np.eye(3)))),
            tone=ToneSettings(input_nits=(5., 38., 225., 1200.), fit=1.5,
                              black_compression_nits=.8, muted_gain=-.6, vivid_gain=.4,
                              saturation_crossover=.35, shadow_chroma=.35,
                              highlight_chroma=-.2, tone_crossover=48.),
        )
        ids = np.array(((0, 0, 0), (24, 24, 26), (32, 34, 30),
                        (42, 40, 42), (50, 52, 52)))
        points = lut.axis()[ids]
        intermediate = evaluate_stack_ap1(points, (grade,), "ACEScg", project_output=False)
        self.assertTrue((intermediate[1:] < 0.).all())
        receipts, _ = self.bake((grade, grade), directions=("FORWARD", "INVERSE"))
        actual = receipts["full"].cube.values[tuple(ids.T)]
        np.testing.assert_allclose(actual, points, rtol=2e-4, atol=3e-5)

    def test_inverse_authored_color_reproduces_chromatic_rgb_targets(self):
        grade = Settings(linear=LinearSettings(exposure=-2.),
                         tone=ToneSettings(input_nits=(5., 38., 225., 1200.),
                                           black_compression_nits=.8, muted_gain=-.6, vivid_gain=.4,
                                           shadow_chroma=.35, highlight_chroma=-.2),
                         color=ColorSettings(
                             web=WebSettings(hue_degrees=((1., -2., 3., 1., -1., 2.),) * 4)))
        ids = np.array(((28, 31, 29), (40, 37, 41), (47, 50, 48), (54, 52, 50),
                        (64, 64, 64)))
        targets = lut.axis()[ids]
        receipts, _ = self.bake((grade,), directions=("INVERSE",))
        preimages = receipts["full"].cube.values[tuple(ids.T)]
        self.assertFalse(np.allclose(preimages, targets, rtol=.01, atol=.01))
        self.assertTrue((preimages[-1] > lut.MAXIMUM).all())
        reproduced = evaluate_stack_ap1(preimages, (grade,), "ACEScg", project_output=False)
        peak = np.max(abs(targets), axis=-1)
        error = np.max(abs(reproduced - targets), axis=-1)
        np.testing.assert_array_less(error, np.maximum(3e-5, 2e-4 * peak))

    def test_unreachable_inverse_targets_report_approximation_at_both_resolutions(self):
        # Strong compression leaves saturated AP1 targets outside the maximum
        # chroma reachable from finite cone responses.
        grade = Settings(color=ColorSettings(web=WebSettings(log_chroma=((-16.,)*6,)*4)))
        receipts, _ = self.bake((grade,), directions=("INVERSE",), progressive=True)
        for quality, result in receipts.items():
            with self.subTest(quality=quality):
                diagnostics = result.diagnostics
                self.assertGreater(diagnostics["inverse_approximate_vertices"], 0)
                self.assertLess(diagnostics["inverse_approximate_vertices"], result.cube.size**3)
                self.assertGreater(diagnostics["inverse_max_residual"], 1.)
                self.assertTrue(np.isfinite(diagnostics["inverse_max_residual"]))
                red_preimage = result.cube.values[-1, 0, 0]
                reproduced = evaluate_stack_ap1(
                    red_preimage[None, :], (grade,), "ACEScg", project_output=False,
                )
                target = np.array((lut.MAXIMUM, 0., 0.))
                residual = np.max(abs(reproduced - target)) / (1e-4 * lut.MAXIMUM)
                self.assertGreater(residual, 1.)
                self.assertGreaterEqual(diagnostics["inverse_max_residual"], .99 * residual)
        preview = receipts["preview"].diagnostics
        full = receipts["full"].diagnostics
        self.assertGreaterEqual(full["inverse_approximate_vertices"],
                                preview["inverse_approximate_vertices"])
        self.assertGreaterEqual(full["inverse_max_residual"], preview["inverse_max_residual"])

    def test_compute_unavailability_and_dispatch_failure_have_no_cpu_fallback(self):
        backend = StackGPUBackend()
        with patch.object(gpu.capabilities, "compute_shader_support_get", return_value=False):
            with self.assertRaisesRegex(RuntimeError, "requires GPU compute"):
                backend.create_prepared((), "ACEScg", False)
        job = backend.create_prepared((), "ACEScg", False)
        try:
            with patch.object(gpu.compute, "dispatch", side_effect=RuntimeError("synthetic dispatch failure")):
                with self.assertRaisesRegex(RuntimeError, "synthetic dispatch failure"):
                    job.advance()
        finally:
            job.close()
            backend.close()


if __name__ == "__main__":
    unittest.main()
