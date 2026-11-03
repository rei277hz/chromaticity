import unittest

import numpy as np

from color_tools.kernel.lut import (
    ATLAS_HEIGHT,
    ATLAS_WIDTH,
    MAXIMUM,
    PREVIEW_SIZE,
    SIZE,
    LinearCube,
    axis,
    atlas_height,
    pack_rgbe,
    unpack_rgbe,
    _stack_matrix,
)


def reference_cube(matrices, space="ACEScg", size=SIZE):
    """Independent CPU reference for validating the production GPU baker."""
    matrix, to_lut, from_lut, signature = _stack_matrix(matrices, space)
    coordinates = axis(SIZE)
    if size == PREVIEW_SIZE:
        coordinates = coordinates[::2]
    elif size != SIZE:
        coordinates = axis(size)
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
    values.flags.writeable = False
    edges.flags.writeable = False
    to_lut.flags.writeable = False
    from_lut.flags.writeable = False
    return LinearCube(values, edges, signature, space, to_lut, from_lut, size)


class LinearStackLUTTests(unittest.TestCase):
    def test_empty_and_ordered_stacks_preserve_the_linear_transform(self):
        first = np.array(((1.0, .2, 0.0), (0.0, .9, .1), (.1, 0.0, 1.0)))
        second = np.array(((.8, 0.0, .1), (.1, 1.0, 0.0), (0.0, .2, 1.1)))
        points = np.array((
            (0.0, 0.0, 0.0),
            (.2, .7, 3.0),
            (MAXIMUM, 128.0, 12.0),
            (-.1, .4, 100.0),
            (1400.0, 2000.0, 2048.0),
        ))

        identity = reference_cube((), space="ACEScg")
        np.testing.assert_allclose(identity.apply(points), points, atol=2e-4, rtol=2e-6)

        cube = reference_cube((first, second), space="ACEScg")
        expected = points @ (second @ first).T
        np.testing.assert_allclose(cube.apply(points), expected, atol=2e-4, rtol=2e-6)
        self.assertNotEqual(cube.signature,
                            reference_cube((second, first), space="ACEScg").signature)

    def test_edge_slopes_are_differenced_before_float32_storage(self):
        matrix = np.eye(3)
        matrix[0, 1] = 1e-5
        cube = reference_cube((matrix,), space="ACEScg")
        expected = 1e-5 * (axis()[1] - axis()[0])
        stored = cube.edge_values[1, SIZE - 1, 0, 0, 0]
        self.assertGreater(stored, 0.0)
        self.assertAlmostEqual(float(stored), float(expected), delta=1e-12)

    def test_cpu_lookup_extrapolates_both_boundary_cells(self):
        matrix = np.array(((1.0, .25, 0.0), (0.0, 1.0, .1), (.2, 0.0, 1.0)))
        cube = reference_cube((matrix,), space="ACEScg")
        points = np.array(((-.01, .2, 1.0), (MAXIMUM + 20.0, 100.0, 3.0)))
        np.testing.assert_allclose(cube.apply(points), points @ matrix.T,
                                   atol=2e-4, rtol=2e-6)

    def test_rgbe_round_trip_and_atlas_layout(self):
        values = np.array(((-3.5, 2.0, .125), (1e-20, -2e-20, 3e-20),
                           (0.0, 0.0, 0.0)), dtype=np.float32)
        np.testing.assert_array_equal(unpack_rgbe(pack_rgbe(values)), values)

        cube = reference_cube((np.eye(3),), space="ACEScg")
        shader = cube.shader_pixels()
        compositor = cube.compositor_pixels()
        self.assertEqual(shader.shape, (ATLAS_HEIGHT, ATLAS_WIDTH, 4))
        self.assertEqual(compositor.shape, shader.shape)
        self.assertTrue(np.isfinite(shader).all())
        self.assertTrue(np.isfinite(compositor).all())
        self.assertTrue(np.array_equal(shader.reshape(-1, 4)[:SIZE**3, 3],
                                       np.ones(SIZE**3, dtype=np.float32)))

    def test_matrix_validation(self):
        with self.assertRaises(ValueError):
            _stack_matrix((np.ones((3, 2)),), "ACEScg")
        with self.assertRaises(ValueError):
            _stack_matrix((np.full((3, 3), np.inf),), "ACEScg")

    def test_progressive_bake_emits_exact_nested_preview_before_returning_full_cube(self):
        matrix = np.array(((1.0, .25, 0.0), (0.0, .9, .1), (.2, 0.0, 1.1)))
        preview = reference_cube((matrix,), space="ACEScg", size=PREVIEW_SIZE)
        full = reference_cube((matrix,), space="ACEScg")
        self.assertEqual(preview.size, PREVIEW_SIZE)
        self.assertEqual(full.size, SIZE)
        self.assertEqual(preview.signature, full.signature)
        np.testing.assert_array_equal(preview.values, full.values[::2, ::2, ::2])
        self.assertFalse(preview.values.flags.writeable)
        self.assertFalse(full.values.flags.writeable)

        direct = reference_cube((matrix,), space="ACEScg")
        np.testing.assert_array_equal(full.values, direct.values)
        np.testing.assert_array_equal(full.edge_values, direct.edge_values)

    def test_preview_lookup_extrapolates_and_uses_its_own_atlas_dimensions(self):
        matrix = np.array(((1.0, .25, 0.0), (0.0, 1.0, .1), (.2, 0.0, 1.0)))
        preview = reference_cube((matrix,), space="ACEScg", size=PREVIEW_SIZE)
        points = np.array(((-.01, .2, 1.0), (MAXIMUM + 20.0, 100.0, 3.0)))
        np.testing.assert_allclose(preview.apply(points), points @ matrix.T,
                                   atol=2e-4, rtol=2e-6)

        shader = preview.shader_pixels()
        compositor = preview.compositor_pixels()
        self.assertEqual(shader.shape, (atlas_height(PREVIEW_SIZE), ATLAS_WIDTH, 4))
        self.assertEqual(compositor.shape, shader.shape)
        self.assertEqual(atlas_height(SIZE), ATLAS_HEIGHT)
        self.assertTrue(np.isfinite(shader).all())
        self.assertTrue(np.isfinite(compositor).all())
        self.assertTrue(np.array_equal(shader.reshape(-1, 4)[:PREVIEW_SIZE**3, 3],
                                       np.ones(PREVIEW_SIZE**3, dtype=np.float32)))

if __name__ == "__main__":
    unittest.main()
