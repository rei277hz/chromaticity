"""Actual GPU Stage 1/2 Stack evaluation and native lookup parity."""

import asyncio
from dataclasses import replace
from functools import partial
import unittest
from unittest.mock import patch

import bpy
import gpu
import numpy as np

from color_tools.kernel import lut
from color_tools.kernel.stage2_graph import build_stage2_group
from color_tools.kernel.settings import LinearSettings, Settings, ToneSettings
from color_tools.lut_gpu import StackGPUBackend
from color_tools.runtime.grade_preparation import GradePreparer
from tools.perceptual_grade.reports.native import NativeFixture
from tools.perceptual_grade.reports.oracle import evaluate_full
from .gpu_support import initialize


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
        expected = points
        for item in settings:
            expected = evaluate_full(expected, item.linear, item.tone, item.color, "ACEScg")["rgb"]
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
