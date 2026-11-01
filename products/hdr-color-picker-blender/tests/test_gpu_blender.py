"""Actual GPU compute versus the canonical CPU picker, run inside Blender."""
import unittest

import bpy
import gpu
import numpy as np

from bl_ext.picker_tests.hdr_color_picker import hdr_color_picker_core as model
from bl_ext.picker_tests.hdr_color_picker.hdr_color_picker_blender import gpu as renderer


class PickerGPUConformanceTests(unittest.TestCase):
    def test_actual_compute_renderer_matches_legacy_cpu_contract(self):
        gpu.init()
        program = renderer.Program()
        self.assertGreater(program.conformance['samples'], 3000)
        for j in (0, model.REFERENCE_WHITE_J, 1):
            for full in (True, False):
                with self.subTest(j=j, full_rec2020=full):
                    actual = program.render_slice(j, 47, 41, full)
                    expected = model.render_slice(j, 47, 41, full)
                    np.testing.assert_array_equal(actual[..., 3], expected[..., 3])
                    self.assertTrue(np.isfinite(actual).all())
                    np.testing.assert_allclose(actual[..., :3], expected[..., :3], rtol=3e-4, atol=3e-5)

    def test_controller_owned_program_can_be_released_and_recreated(self):
        instance = renderer.Renderer()
        first = instance.render_slice(.5, 9, 9)
        instance.reset()
        second = instance.render_slice(.5, 9, 9)
        np.testing.assert_array_equal(first, second)
        instance.reset()


if __name__ == '__main__':
    unittest.main()
