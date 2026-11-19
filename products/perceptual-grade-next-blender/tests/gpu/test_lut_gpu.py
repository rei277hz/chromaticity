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
from color_tools.runtime.grade_preparation import GradePreparer
from tools.perceptual_grade.reports.native import NativeFixture
from tools.perceptual_grade.reports import oracle
from tools.perceptual_grade.reports.full_cases import guard_before_scale_grade
from .gpu_support import initialize


def evaluate_stack_ap1(rgb, settings, space, *, skip_hk_at=None):
    """Compose raw Grades in AP1, with one guarded final decode."""
    value = np.asarray(rgb, dtype=np.float64)
    for index, item in enumerate(settings):
        linear, tone = oracle.parameters(item.linear, item.tone)
        color = grading.ColorSettings(**asdict(item.color))
        reference = model.Model(model.Settings(linear=linear, tone=tone, color=color),
                                space, hk_guard=index != skip_hk_at)
        boundary = oracle.exact_boundary(reference)
        to_scene = reference.xyz_to_rgb @ reference.cones_to_xyz @ np.linalg.inv(boundary.matrix)
        neutral = value[..., 1, None]
        scene_rgb = neutral + (value - neutral) @ to_scene.T
        toned = oracle.evaluate(scene_rgb, item.linear, item.tone, space)["tone"]
        graded = reference.color.apply_state(toned)
        if index == len(settings) - 1:
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

    def bake(self, settings=(), *, space="ACEScg", progressive=False, interleave=False):
        settings = tuple(replace(item, space=space) for item in settings)
        prepared = self.prepare(settings)
        backend = StackGPUBackend()
        job = backend.create_prepared(prepared, space, progressive, settings=settings)
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
                    receipts[quality] = result.cube
        finally:
            job.close()
            backend.close()
        return receipts, prepared

    def test_empty_stack_identity_and_atlas_packing(self):
        receipts, _ = self.bake(progressive=True, interleave=True)
        preview, full = receipts["preview"], receipts["full"]
        axis = lut.axis()
        expected = np.stack(np.meshgrid(axis, axis, axis, indexing="ij"), axis=-1)
        np.testing.assert_allclose(full.values, expected, rtol=0, atol=1e-4)
        np.testing.assert_array_equal(preview.values, full.values[::2, ::2, ::2])
        self.assertEqual(full.shader_pixels().shape, (lut.ATLAS_HEIGHT, lut.ATLAS_WIDTH, 4))
        self.assertTrue(np.isfinite(full.compositor_pixels()).all())

    def test_ordered_tone_grades_match_independent_reference_and_actual_edges(self):
        settings = (
            Settings(linear=LinearSettings(exposure=.4, balance=(.1, -.1)),
                     tone=ToneSettings(input_nits=(0., 6., 42., 235., 1150.), fit=.5)),
            Settings(linear=LinearSettings(exposure=-.15),
                     tone=ToneSettings(input_nits=(0., 4., 32., 190., 950.), fit=-.25)),
        )
        receipts, _ = self.bake(settings, progressive=True)
        full, preview = receipts["full"], receipts["preview"]
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
            tone=ToneSettings(input_nits=(0., 5., 38., 225., 1200.), fit=.25),
            color=guard_before_scale_grade(),
        ),)
        receipts, prepared = self.bake(settings, space="Linear Rec.2020")
        cube = receipts["full"]
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
        settings = (
            Settings(linear=LinearSettings(exposure=-6.),
                     color=ColorSettings(global_gain=3.)),
            Settings(color=guard_before_scale_grade()),
        )
        receipts, _ = self.bake(settings, progressive=True)
        ids = np.array(((0, 0, 0), (40, 0, 0), (0, 40, 0), (0, 0, 40),
                        (16, 16, 16), (32, 32, 32), (64, 64, 64)))
        source = lut.axis()[ids]
        expected = evaluate_stack_ap1(source, settings, "ACEScg")
        for index in range(len(settings)):
            skipped = evaluate_stack_ap1(source, settings, "ACEScg", skip_hk_at=index)
            self.assertFalse(np.allclose(expected, skipped), f"H-K repair at entry {index + 1}")
        for quality, indices in (("preview", ids//2), ("full", ids)):
            with self.subTest(quality=quality):
                actual = receipts[quality].values[tuple(indices.T)]
                normalized = np.max(abs(actual-expected), axis=-1)/(1+np.max(abs(expected), axis=-1))
                self.assertLessEqual(float(np.max(normalized)),1e-4)
        np.testing.assert_array_equal(receipts["preview"].values,
                                      receipts["full"].values[::2,::2,::2])

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
                actual = receipts[quality].values[tuple(indices.T)]
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
