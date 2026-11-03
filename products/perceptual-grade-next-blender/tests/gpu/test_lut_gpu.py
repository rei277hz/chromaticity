"""Actual Blender compute output for forward Stage 1 LUT baking."""

import unittest
from unittest.mock import patch

import bpy
import gpu
import numpy as np

from color_tools.kernel import lut
from color_tools.lut_gpu import StackGPUBackend
from .gpu_support import initialize


def expected_cube(matrices, size):
    matrix, to_lut, from_lut, signature = lut._stack_matrix(matrices, "ACEScg")
    coordinates = lut.axis(lut.SIZE)
    if size == lut.PREVIEW_SIZE:
        coordinates = coordinates[::2]
    lattice = np.stack(np.meshgrid(coordinates, coordinates, coordinates,
                                   indexing="ij"), axis=-1)
    values = (lattice @ matrix.T).astype(np.float32)
    edges = np.zeros((3, size, size, size, 3), dtype=np.float32)
    for direction in range(3):
        delta = np.zeros(size, dtype=np.float64)
        delta[:-1] = np.diff(coordinates)
        shape = [1, 1, 1, 1]
        shape[direction] = size
        edges[direction] = (
            delta.reshape(shape) * matrix[:, direction].reshape(1, 1, 1, 3)
        ).astype(np.float32)
    return values, edges, signature, to_lut, from_lut


class LUTGPUComputeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.gpu = initialize()

    def bake_progressive(self, matrices, *, interleave=False):
        backend = StackGPUBackend()
        job = backend.create_matrices(matrices, "ACEScg", True)
        preview = full = None
        unrelated = None
        try:
            while full is None:
                receipt = job.advance()
                if interleave and unrelated is None and job.cursor:
                    pixels = np.tile(
                        np.array((7.0, 11.0, 13.0, 17.0), np.float32),
                        (16, 16, 1),
                    )
                    unrelated = self.gpu.types.GPUTexture(
                        (16, 16), format="RGBA32F",
                        data=self.gpu.types.Buffer("FLOAT", pixels.shape, pixels),
                    )
                    values = np.asarray(unrelated.read(), dtype=np.float32)
                    np.testing.assert_array_equal(
                        values.reshape(-1, 4),
                        np.tile(np.array((7.0, 11.0, 13.0, 17.0), np.float32),
                                (16 * 16, 1)),
                    )
                if receipt is not None:
                    quality, prepared = receipt
                    if quality == "preview":
                        preview = prepared.cube
                    else:
                        full = prepared.cube
        finally:
            job.close()
            backend.close()
        self.assertIsNotNone(preview)
        self.assertIsNotNone(full)
        return preview, full

    def test_gpu_values_and_edge_planes_match_independent_reference(self):
        matrices = (
            np.array(((1.0, .25, 0.0), (0.0, .9, .1), (.2, 0.0, 1.1))),
            np.array(((.8, 0.0, .1), (.1, 1.0, 0.0), (0.0, .2, 1.1))),
        )
        preview, full = self.bake_progressive(matrices, interleave=True)

        expected_preview = expected_cube(matrices, lut.PREVIEW_SIZE)
        expected_full = expected_cube(matrices, lut.SIZE)
        self.assertEqual(preview.signature, expected_preview[2])
        self.assertEqual(full.signature, expected_full[2])
        np.testing.assert_allclose(preview.values, expected_preview[0], rtol=2e-6,
                                   atol=1e-5)
        np.testing.assert_allclose(preview.edge_values, expected_preview[1],
                                   rtol=2e-6, atol=1e-5)
        np.testing.assert_allclose(full.values, expected_full[0], rtol=2e-6,
                                   atol=1e-5)
        np.testing.assert_allclose(full.edge_values, expected_full[1],
                                   rtol=2e-6, atol=1e-5)
        np.testing.assert_array_equal(preview.values, full.values[::2, ::2, ::2])

    def test_identity_gpu_cube_and_atlas_packing(self):
        preview, full = self.bake_progressive((np.eye(3),))
        axis = lut.axis()
        expected = np.stack(np.meshgrid(axis, axis, axis, indexing="ij"), axis=-1)
        np.testing.assert_allclose(full.values, expected, rtol=0, atol=1e-4)
        self.assertEqual(full.shader_pixels().shape,
                         (lut.ATLAS_HEIGHT, lut.ATLAS_WIDTH, 4))
        self.assertEqual(full.compositor_pixels().shape, full.shader_pixels().shape)
        self.assertTrue(np.isfinite(full.shader_pixels()).all())
        self.assertTrue(np.isfinite(full.compositor_pixels()).all())
        points = np.array(((-.01, .2, 1.0), (lut.MAXIMUM + 20, 100, 3.0)))
        np.testing.assert_allclose(preview.apply(points), points, rtol=2e-5,
                                   atol=2e-4)

    def test_tiny_edge_slope_survives_at_a_large_vertex(self):
        matrix = np.eye(3)
        matrix[0, 1] = 1e-5
        _preview, full = self.bake_progressive((matrix,))
        expected = 1e-5 * (lut.axis()[1] - lut.axis()[0])
        actual = full.edge_values[1, lut.SIZE - 1, 0, 0, 0]
        self.assertGreater(float(actual), 0.0)
        self.assertAlmostEqual(float(actual), float(expected), delta=1e-8)

    def test_compute_unavailability_fails_without_cpu_fallback(self):
        backend = StackGPUBackend()
        original = gpu.capabilities.compute_shader_support_get
        gpu.capabilities.compute_shader_support_get = lambda: False
        try:
            with self.assertRaisesRegex(RuntimeError, "requires GPU compute"):
                backend.create_matrices((np.eye(3),), "ACEScg", False)
        finally:
            gpu.capabilities.compute_shader_support_get = original
            backend.close()

    def test_direct_request_bakes_only_full_quality_and_dispatch_failure_propagates(self):
        backend = StackGPUBackend()
        direct = backend.create_matrices((np.eye(3),), "ACEScg", False)
        try:
            qualities = []
            prepared = None
            while prepared is None:
                receipt = direct.advance()
                if receipt is not None:
                    quality, prepared = receipt
                    qualities.append(quality)
            self.assertEqual(qualities, ["full"])
            self.assertEqual(prepared.cube.size, lut.SIZE)
        finally:
            direct.close()

        failed = backend.create_matrices((np.eye(3),), "ACEScg", False)
        try:
            with patch.object(gpu.compute, "dispatch",
                              side_effect=RuntimeError("synthetic dispatch failure")):
                with self.assertRaisesRegex(RuntimeError, "synthetic dispatch failure"):
                    failed.advance()
        finally:
            failed.close()
            backend.close()


if __name__ == "__main__":
    unittest.main()
