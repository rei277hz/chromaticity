import importlib.util
import unittest
import numpy as np

from tools.perceptual_grade.reports.hdr_metrics import HDRDisplay, compare


class HdrMetricTests(unittest.TestCase):
    def test_movement_worsening_and_witness(self):
        reference = np.array([[10., 10., 10.], [0., 0., 0.], [2., 4., 1.]])
        baseline = np.array([[11., 10., 10.], [0., 0., 0.], [1., 4., 1.]])
        candidate = np.array([[12., 10., 10.], [1.5, 0., 0.], [2., 4., 1.]])
        result = compare(reference, baseline, candidate, inputs=reference)
        self.assertEqual(result['candidate']['worsening']['worsened'], 2)
        self.assertEqual(result['candidate']['worsening']['improved'], 1)
        self.assertAlmostEqual(result['candidate']['movement']['pixel_peak']['max'], 1.5)
        self.assertEqual(result['candidate']['error']['near_black_pixels'], 1)
        self.assertEqual(result['witnesses']['worsening']['index'], 1)
        self.assertEqual(result['witnesses']['worsening']['input_rgb'], [0., 0., 0.])
        self.assertLess(result['candidate']['worsening']['percentage']['min'], 0.)

    def test_near_black_percentage_is_separate(self):
        result = compare(np.array([[0., 0., 0.], [.5, 0., 0.]]),
                         np.array([[.1, 0., 0.], [.6, 0., 0.]]),
                         np.array([[.2, 0., 0.], [.7, 0., 0.]]))
        stats = result['candidate']['error']
        self.assertEqual(stats['percentage_eligible_pixels'], 0)
        self.assertEqual(stats['near_black_pixels'], 2)
        self.assertEqual(stats['pixel_peak']['max'], .2)
        self.assertEqual(stats['near_black']['max'], .2)
        self.assertEqual(stats['zero_reference_pixels'], 1)

    @unittest.skipUnless(importlib.util.find_spec('bpy'), 'requires the pinned Blender Python runtime')
    def test_pinned_ocio_display_processors(self):
        display = HDRDisplay()
        source = np.ones((1, 3), dtype=np.float64)
        for space in display.spaces:
            code = display.codes(source, space)
            self.assertEqual(code.shape, source.shape)
            self.assertTrue(np.isfinite(code).all())
            self.assertTrue(np.all((code > 0.) & (code < 1023.)))
        self.assertEqual(display.metadata['display'], 'Rec.2100-PQ')
        self.assertEqual(display.metadata['view'], 'ACES 2.0 - HDR 1000 nits')

    def test_shape_and_finite_validation(self):
        with self.assertRaises(ValueError):
            compare([[1., 2., 3.]], [[1., 2., 3.]], [[np.nan, 2., 3.]])
        with self.assertRaises(ValueError):
            compare([[1., 2., 3.]], [[1., 2.]])
        with self.assertRaisesRegex(ValueError, 'inputs shape mismatch'):
            compare([[1., 2., 3.]], [[1., 2., 3.]], inputs=[[1., 2.]])
        with self.assertRaisesRegex(ValueError, 'reference_rgb shape mismatch'):
            compare([[1., 2., 3.]], [[1., 2., 3.]], reference_rgb=[[1., 2., 3.], [4., 5., 6.]])

    def test_witness_has_matching_scene_and_code_values_and_no_full_arrays(self):
        reference = np.array([[[10., 8., 3.], [2., 3., 4.]]])
        baseline = reference + np.array([[[.2, 0., 0.], [0., 1., 0.]]])
        scene = reference/1023.
        result = compare(reference, baseline, baseline, inputs=np.ones((1, 2, 4)),
                         reference_rgb=scene, baseline_rgb=scene+.1, candidate_rgb=scene+.2)
        witness = result['witnesses']['current_error']
        self.assertEqual(witness['index'], 1)
        self.assertEqual(witness['reference_code_rgb'], reference[0, 1].tolist())
        self.assertEqual(witness['reference_rgb'], scene[0, 1].tolist())
        self.assertEqual(witness['input_rgb'], [1., 1., 1.])
        self.assertNotIn('reference_scene_rgb', result)


if __name__ == '__main__':
    unittest.main()
