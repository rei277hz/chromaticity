"""Direct full-raster production kernels, endpoint routing and alpha fidelity."""
from concurrent.futures import CancelledError
from dataclasses import replace
import unittest
from unittest.mock import patch

import numpy as np

from color_tools.perceptual_grade_core.model import baking, color, linear, lut, raster, tone, transforms
from color_tools.perceptual_grade_core.model.export import input_repair


def settings(gain=.15, exposure=0.):
    return transforms.Settings.from_parameters(linear.Parameters(exposure=exposure),
        tone.Parameters(input_midtones=45), color.Parameters(global_gain=gain), linear.GradeSpace('D65'))


def pixels():
    native = np.array(((.0217, .131, .427), (5.31, .213, .047),
                       (.31, 2.17, .163), (0., 0., 0.)), dtype=np.float32)
    return np.column_stack((native @ lut.FROM_LUT.T, np.array((.375, .75, -0., 1.2)))).astype(np.float32)


class RasterTests(unittest.TestCase):
    def test_grade_evaluates_off_lattice_pixels_without_tetrahedral_interpolation(self):
        model = transforms.Stack((settings(.35),))
        source = pixels()
        rows = (lut.TO_LUT, lut.FROM_LUT)
        native = input_repair(source[:, :3].astype(float) @ rows[0].T, lut.AP1_Y).astype(np.float32)
        kernel = baking.kernel(model)
        expected = (kernel.evaluate(native).astype(float) @ rows[1].T).astype(np.float32)
        cube = kernel.evaluate(lut.lattice(lut.PREVIEW_SIZE))
        approximated = lut.tetrahedral(cube, native) @ rows[1].T
        self.assertGreater(float(np.max(abs(approximated - expected))), 1e-4)
        actual = source.copy()
        with patch.object(lut, 'tetrahedral', side_effect=AssertionError('No LUT lookup')):
            raster.grade_rgba(actual, model, rows)
        np.testing.assert_array_equal(actual[:, :3], expected)
        np.testing.assert_array_equal(actual[:, 3].view(np.uint32), source[:, 3].view(np.uint32))

    def test_stack_directions_and_endpoint_matrices_match_complete_production_model(self):
        source = pixels()
        a, b = settings(.1, .2), settings(.05, -.1)
        for directions in (('FORWARD', 'FORWARD'), ('FORWARD', 'INVERSE'),
                           ('INVERSE', 'FORWARD'), ('INVERSE', 'INVERSE'), ()):
            with self.subTest(directions=directions):
                model = transforms.Stack((a, b) if directions else (), directions=directions)
                rows = (model.input_matrix @ lut.TO_LUT, lut.FROM_LUT @ model.output_matrix)
                actual = source.copy()
                diagnostics = raster.grade_rgba(actual, model, rows, stack=True, block=2)
                expected = model.apply(source[:, :3])
                np.testing.assert_allclose(actual[:, :3], expected, rtol=2e-5, atol=3e-6)
                np.testing.assert_array_equal(actual[:, 3].view(np.uint32), source[:, 3].view(np.uint32))
                self.assertTrue(np.isfinite(diagnostics['max_inverse_residual']))

    def test_chunking_preserves_pixels_alpha_and_monotone_progress(self):
        model = transforms.Stack((settings(),))
        source = np.tile(pixels(), (19, 1))
        first, second = source.copy(), source.copy()
        progress = []
        raster.grade_rgba(first, model, (lut.TO_LUT, lut.FROM_LUT))
        result = raster.grade_rgba(second, model, (lut.TO_LUT, lut.FROM_LUT),
                                   block=7, progress=progress.append)
        np.testing.assert_array_equal(first, second)
        np.testing.assert_array_equal(second[:, 3].view(np.uint32), source[:, 3].view(np.uint32))
        self.assertEqual(result['pixels'], len(source))
        self.assertEqual(progress, sorted(progress))
        self.assertEqual(progress[-1], 1.)

    def test_cancellation_stops_between_chunks_without_touching_alpha(self):
        model = transforms.Stack((settings(),))
        source = np.tile(pixels(), (4, 1))
        actual = source.copy()
        completed = []
        def checkpoint():
            if completed:raise CancelledError('Stopped raster')
        with self.assertRaisesRegex(CancelledError, 'Stopped raster'):
            raster.grade_rgba(actual, model, (lut.TO_LUT, lut.FROM_LUT), block=4,
                              checkpoint=checkpoint, progress=completed.append)
        self.assertEqual(len(completed), 1)
        np.testing.assert_array_equal(actual[4:], source[4:])
        np.testing.assert_array_equal(actual[:, 3].view(np.uint32), source[:, 3].view(np.uint32))

    def test_signed_extreme_inputs_reach_projection_without_float32_matrix_overflow(self):
        model = transforms.Stack((replace(settings(0.), tone=tone.Parameters()),))
        actual = np.array(((3e38, -1e38, 2e38, .375), (0, 0, 0, .75)), dtype=np.float32)
        raster.grade_rgba(actual, model, (64 * lut.TO_LUT, lut.FROM_LUT))
        self.assertTrue(np.isfinite(actual).all())
        np.testing.assert_array_equal(actual[:, 3], np.array((.375, .75), dtype=np.float32))

    def test_invalid_storage_nonfinite_pixels_and_endpoints_are_rejected(self):
        model = transforms.Stack((settings(),))
        for source in (pixels().astype(float), pixels()[:, ::-1], np.zeros((3, 3), np.float32)):
            with self.assertRaisesRegex(ValueError, 'float32 RGBA'):
                raster.grade_rgba(source, model, (lut.TO_LUT, lut.FROM_LUT))
        source = pixels();source[0, 3] = np.nan
        with self.assertRaisesRegex(ValueError, 'nonfinite RGBA'):
            raster.grade_rgba(source, model, (lut.TO_LUT, lut.FROM_LUT))
        with self.assertRaisesRegex(ValueError, 'endpoint'):
            raster.grade_rgba(pixels(), model, (np.eye(3), np.full((3, 3), np.inf)))
        with self.assertRaisesRegex(ValueError, 'bounded pixel chunk'):
            raster.grade_rgba(pixels(), model, (lut.TO_LUT, lut.FROM_LUT), block=raster.BLOCK + 1)
