import unittest

import numpy as np

from color_tools.perceptual_grade_next_core.model.lut import (
    FINAL_SIZE,
    PREVIEW_SIZE,
    FinalLattice,
    StackLUT,
    axis,
    input_repair,
    lattice,
    make_recipe,
    pack_rgbe,
    refine_final,
    sample_preview,
    tetrahedral,
    unpack_rgbe,
)


IDENTITY = np.eye(3)


def recipe(*, input_matrix=IDENTITY, output_matrix=IDENTITY, directions=("FORWARD",), model_key="test"):
    return make_recipe(
        working_space="ACEScg",
        directions=directions,
        input_matrix=input_matrix,
        output_matrix=output_matrix,
        model_key=model_key,
    )


class LatticeTests(unittest.TestCase):
    def test_preview_points_are_exact_even_final_vertices(self):
        final = lattice(FINAL_SIZE)
        preview = lattice(PREVIEW_SIZE)
        np.testing.assert_array_equal(preview, final[::2, ::2, ::2])
        np.testing.assert_array_equal(axis()[::2], lattice(PREVIEW_SIZE)[:, 0, 0, 0])

    def test_refinement_evaluates_each_final_vertex_once(self):
        seen = set()

        def evaluate(points):
            output = np.stack((points[:, 0] + points[:, 1],
                               points[:, 1] * points[:, 2],
                               points[:, 2] - points[:, 0]), axis=-1)
            for point in points:
                key = tuple(point)
                if key in seen:
                    raise AssertionError(f"shared vertex reevaluated: {key}")
                seen.add(key)
            return output

        selected = recipe()
        preview = sample_preview(evaluate, selected, block_size=5000)
        self.assertEqual(len(seen), PREVIEW_SIZE**3)
        final = refine_final(preview, evaluate, selected, block_size=17000)
        self.assertEqual(len(seen), FINAL_SIZE**3)
        self.assertEqual(final.size, 65)
        self.assertTrue(final.final_ready)
        np.testing.assert_array_equal(final.values[::2, ::2, ::2], preview.values)

    def test_refinement_rejects_a_different_recipe(self):
        selected = recipe(model_key="settings-a")
        preview = sample_preview(lambda points: points, selected)
        with self.assertRaisesRegex(ValueError, "same StackRecipe"):
            refine_final(preview, lambda points: points, recipe(model_key="settings-b"))

    def test_final_constructor_checks_actual_even_vertex_payload(self):
        selected = recipe()
        preview = sample_preview(lambda points: points, selected)
        final = refine_final(preview, lambda points: points, selected)
        corrupted = final.values.copy()
        corrupted[0, 0, 0, 0] = 1.0
        with self.assertRaisesRegex(ValueError, "exactly reuse all preview vertices"):
            FinalLattice(corrupted, selected, preview)

    def test_stack_bake_object_cannot_be_created_from_preview(self):
        selected = recipe()
        preview = sample_preview(lambda points: points, selected)
        with self.assertRaisesRegex(TypeError, r"65\^3 FinalLattice"):
            StackLUT(preview)

    def test_tetrahedral_lookup_is_exact_for_affine_fields(self):
        grid = lattice(FINAL_SIZE)
        values = np.empty_like(grid, dtype=np.float32)
        values[..., 0] = 2.0 * grid[..., 0] - grid[..., 1] + 0.5 * grid[..., 2]
        values[..., 1] = grid[..., 0] + 3.0 * grid[..., 1] - 2.0 * grid[..., 2]
        values[..., 2] = -0.25 * grid[..., 0] + grid[..., 1] + 4.0 * grid[..., 2]
        samples = np.asarray(((0.03, 0.1, 2.0), (3.5, 6.0, 10.0),
                              (120.0, 180.0, 200.0), (1024.0, 700.0, 33.0)))
        expected = np.stack((
            2.0 * samples[:, 0] - samples[:, 1] + 0.5 * samples[:, 2],
            samples[:, 0] + 3.0 * samples[:, 1] - 2.0 * samples[:, 2],
            -0.25 * samples[:, 0] + samples[:, 1] + 4.0 * samples[:, 2],
        ), axis=-1)
        np.testing.assert_allclose(tetrahedral(values, samples), expected, rtol=2e-6, atol=2e-4)

    def test_lut_applies_endpoint_matrices_outside_the_sampled_core(self):
        input_matrix = np.asarray(((1.0, 0.15, 0.0), (0.0, 1.0, 0.1), (0.05, 0.0, 1.0)))
        output_matrix = np.asarray(((1.0, 0.0, 0.1), (0.2, 1.0, 0.0), (0.0, 0.1, 1.0)))
        selected = recipe(input_matrix=input_matrix, output_matrix=output_matrix)
        preview = sample_preview(lambda points: points, selected)
        final = refine_final(preview, lambda points: points, selected)
        lut = StackLUT(final)
        samples = np.asarray(((0.5, 1.0, 2.0), (6.0, 4.0, 3.0), (30.0, 12.0, 5.0)))
        expected = samples @ input_matrix.T @ output_matrix.T
        np.testing.assert_allclose(lut.apply(samples), expected, rtol=2e-6, atol=2e-5)


class BoundaryAndTransportTests(unittest.TestCase):
    def test_ap1_repair_is_identity_in_cube_and_bounds_outside_inputs(self):
        inside = np.asarray(((0.0, 0.0, 0.0), (1.0, 0.25, 4.0), (1024.0, 10.0, 0.0)))
        np.testing.assert_array_equal(input_repair(inside), inside)
        outside = np.asarray(((-4.0, 2.0, 1.0), (2048.0, 100.0, 50.0),
                              (10.0, -100.0, 10.0)))
        repaired = input_repair(outside)
        self.assertTrue(np.isfinite(repaired).all())
        self.assertGreaterEqual(float(repaired.min()), 0.0)
        self.assertLessEqual(float(repaired.max()), 1024.0)

    def test_rgbe_transport_roundtrips_float32_vertices(self):
        values = np.asarray(((0.0, 0.0, 0.0), (1.5, -2.25, 8.0),
                             (1e10, -1.2e10, 2e10)), dtype=np.float32)
        np.testing.assert_array_equal(unpack_rgbe(pack_rgbe(values)), values)

    def test_recipe_identity_binds_direction_endpoints_and_core_key(self):
        base = recipe()
        different_direction = recipe(directions=("INVERSE",))
        different_key = recipe(model_key="other")
        different_input = recipe(input_matrix=np.diag((2.0, 1.0, 1.0)))
        self.assertEqual(base.digest, recipe().digest)
        self.assertNotEqual(base.digest, different_direction.digest)
        self.assertNotEqual(base.digest, different_key.digest)
        self.assertNotEqual(base.digest, different_input.digest)


if __name__ == "__main__":
    unittest.main()
