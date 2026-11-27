"""Pinned native Blender view transform and generated-GPU fidelity gate."""
import os
import copy
from dataclasses import replace
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import bpy
import gpu
from mathutils import Matrix
import numpy as np

from bl_ext.picker_tests.hdr_color_picker.hdr_color_picker_blender import display


CASES = (
    ('AgX', 'None', 0., 1.),
    ('AgX', 'AgX - Punchy', 1.25, .8),
    ('Standard', 'None', -.5, 1.3),
    ('ACES 2.0', 'None', 0., 1.),
    ('Filmic', 'High Contrast', 0., 1.),
    ('Raw', 'None', 0., 1.),
)
DISPLAYS = ('sRGB', 'Display P3', 'Rec.1886', 'Rec.2020', 'Rec.2100-PQ', 'Rec.2100-HLG')
GPU_CASES = (
    *(('sRGB', *case) for case in CASES),
    ('Display P3', 'AgX', 'None', 0., 1.),
    ('Rec.1886', 'Standard', 'None', 0., 1.),
    ('Rec.2020', 'False Color', 'False Color - Punchy', 0., 1.),
    ('Rec.2100-PQ', 'ACES 2.0 - HDR 1000 nits', 'None', 0., 1.),
    ('Rec.2100-HLG', 'AgX - HDR 1000 nits', 'None', 0., 1.),
)
SAMPLES = np.array([[[0, 0, 0, 1], [.001, .001, .001, 1], [.18, .18, .18, 1],
                     [1, 0, 0, 1], [0, 1, 0, 1], [0, 0, 1, 1],
                     [4, 4, 4, 1], [32, 1, .01, 1]]], dtype=np.float32)


class DisplayTests(unittest.TestCase):
    def setUp(self):
        # Isolate display data without resetting the extension repository/preferences.
        previous = bpy.context.window.scene
        self.scene = bpy.data.scenes.new('Picker display acceptance')
        bpy.context.window.scene = self.scene
        def restore():
            bpy.context.window.scene = previous
            bpy.data.scenes.remove(self.scene)
        self.addCleanup(restore)
        self.scene.display_settings.display_device = 'sRGB'
        self.scene.render.image_settings.file_format = 'PNG'
        self.scene.render.image_settings.color_mode = 'RGBA'
        self.scene.render.image_settings.color_depth = '16'
        self.scene.render.dither_intensity = 0

    def test_matches_native_image_save_view_transform(self):
        """Check raw selected-device values against Blender's PNG export."""
        config = display._ocio().GetCurrentConfig()
        self.assertEqual(set(config.getDisplays()), set(DISPLAYS))
        self.scene.display_settings.emulation = 'OFF'
        for working_space in ('ACEScg', 'Linear Rec.709'):
            bpy.ops.wm.set_working_color_space(working_space=working_space)
            image = bpy.data.images.new('Native picker reference', width=8, height=1,
                                        float_buffer=True)
            # Image data lives in Blender's working space, unlike our ACEScg input.
            from mathutils import Color
            samples = SAMPLES.copy()
            for index, rgb in enumerate(samples[0, :, :3]):
                color = Color(rgb).from_acescg_to_scene_linear()
                samples[0, index, :3] = color
            image.pixels.foreach_set(samples.ravel())
            try:
                cases = list(('sRGB', *case) for case in CASES)
                cases.extend((device, view, 'None', 0., 1.)
                             for device in DISPLAYS for view in config.getViews(device)
                             if (device, view, 'None', 0., 1.) not in cases)
                for device, view, look, exposure, gamma in cases:
                    with self.subTest(working_space=working_space, device=device, view=view, look=look):
                        self.scene.display_settings.display_device = device
                        settings = self.scene.view_settings
                        settings.view_transform = view
                        settings.look = look
                        settings.exposure = exposure
                        settings.gamma = gamma
                        transform = display.processor(self.scene)
                        with tempfile.TemporaryDirectory() as directory:
                            path = str(Path(directory) / 'native.png')
                            image.save_render(path, scene=self.scene)
                            result = bpy.data.images.load(path)
                            result.colorspace_settings.name = 'Non-Color'
                            native = np.array(result.pixels[:]).reshape(1, 8, 4)
                            bpy.data.images.remove(result)
                        expected = transform.apply(SAMPLES)
                        # Blender exports PQ/HLG still images with 203-nit
                        # reference white. The display view itself uses 100 nits.
                        selected = config.getDisplayViewColorSpaceName(device, view)
                        hdr_files = {
                            'Rec.2100-PQ': 'blender:pq_rec2020_display_203nits',
                            'Rec.2100-HLG': 'blender:hlg_rec2020_display_203nits',
                        }
                        if selected in hdr_files:
                            file_cpu = config.getProcessor(
                                selected, hdr_files[selected]).getDefaultCPUProcessor()
                            file_cpu.applyRGBA(expected.reshape(-1, 4))
                        np.testing.assert_allclose(native[..., :3], np.clip(expected[..., :3], 0, 1),
                                                   atol=2 / 65535, rtol=0)
            finally:
                bpy.data.images.remove(image)

    def test_generated_gpu_matches_cpu_processor(self):
        gpu.init()
        texture = gpu.types.GPUTexture((8, 1), format='RGBA32F',
                                      data=gpu.types.Buffer('FLOAT', SAMPLES.shape, SAMPLES))
        texture.filter_mode(False)
        offscreen = gpu.types.GPUOffScreen(8, 1, format='RGBA32F')
        try:
            for device, view, look, exposure, gamma in GPU_CASES:
                with self.subTest(device=device, view=view, look=look):
                    self.scene.display_settings.display_device = device
                    settings = self.scene.view_settings
                    settings.view_transform = view
                    settings.look = look
                    settings.exposure = exposure
                    settings.gamma = gamma
                    transform = display.processor(self.scene)
                    with offscreen.bind(), gpu.matrix.push_pop(), gpu.matrix.push_pop_projection():
                        gpu.state.viewport_set(0, 0, 8, 1)
                        gpu.state.blend_set('NONE')
                        gpu.matrix.load_matrix(Matrix.Identity(4))
                        gpu.matrix.load_projection_matrix(Matrix((
                            (.25, 0, 0, -1), (0, 2, 0, -1),
                            (0, 0, -1, 0), (0, 0, 0, 1))))
                        transform.gpu().draw(texture, (0, 0), (8, 1))
                        actual = np.array(gpu.state.active_framebuffer_get().read_color(
                            0, 0, 8, 1, 4, 0, 'FLOAT'))
                    np.testing.assert_allclose(actual[..., :3],
                                               transform.apply(SAMPLES)[..., :3],
                                               atol=1e-4, rtol=0)
        finally:
            offscreen.free()

    def test_unsupported_display_settings_hold_preview(self):
        for property_name in ('use_curve_mapping', 'use_white_balance'):
            setattr(self.scene.view_settings, property_name, True)
            with self.assertRaises(display.DisplayUnavailable):
                display.processor(self.scene)
            setattr(self.scene.view_settings, property_name, False)
        identity = replace(display.signature(self.scene), display='Unknown Display')
        with self.assertRaises(display.DisplayUnavailable):
            display._processor(identity)
        identity = replace(display.signature(self.scene), display='Rec.2100-HLG', view='Filmic')
        with self.assertRaises(display.DisplayUnavailable):
            display._processor(identity)
        with patch.dict(os.environ, {'OCIO': '/not-validated/config.ocio'}):
            with self.assertRaises(display.DisplayUnavailable):
                display.processor(self.scene)
        identity = replace(display.signature(self.scene), working_space='Linear Rec.2020')
        with self.assertRaises(display.DisplayUnavailable):
            display._processor(identity)

    def test_identity_and_alpha_are_value_contracts(self):
        identity = display.signature(self.scene)
        self.scene.view_settings.exposure = 1
        self.assertNotEqual(identity, display.signature(self.scene))
        sdr = display.signature(self.scene, SimpleNamespace(support_hdr_color=False))
        hdr = display.signature(self.scene, SimpleNamespace(support_hdr_color=True))
        self.assertNotEqual(sdr, hdr)
        pixels = SAMPLES.copy()
        pixels[..., 3] = np.linspace(0, 1, 8)
        output = display.processor(self.scene).apply(pixels)
        np.testing.assert_array_equal(output[..., 3], pixels[..., 3])

    def test_auto_emulation_preserves_extended_gamut_and_hdr(self):
        self.scene.display_settings.display_device = 'Display P3'
        self.scene.view_settings.view_transform = 'Standard'
        self.scene.display_settings.emulation = 'AUTO'
        pixels = np.array([[[1., 0., 0., .25], [4., 4., 4., .5]]], dtype=np.float32)
        transform = display.processor(self.scene)
        raw = transform.apply(pixels)
        auto = transform.apply(pixels, viewport_overlay=True)
        self.assertLess(float(auto[0, 0, :3].min()), 0.)
        self.assertGreater(float(auto[0, 0, :3].max()), 1.)
        np.testing.assert_allclose(auto[0, 1, :3], np.ones(3), atol=2e-5)
        np.testing.assert_array_equal(auto[..., 3], pixels[..., 3])
        self.scene.display_settings.emulation = 'OFF'
        off = display.processor(self.scene)
        np.testing.assert_allclose(off.apply(pixels, viewport_overlay=True), raw, atol=1e-6)
        self.scene.display_settings.emulation = 'AUTO'
        for device in ('Rec.2100-PQ', 'Rec.2100-HLG'):
            self.scene.display_settings.display_device = device
            self.scene.view_settings.view_transform = 'Standard'
            hdr = display.processor(self.scene).apply(pixels, viewport_overlay=True)
            self.assertGreater(float(hdr[0, 1, :3].min()), 1.)

    def test_runtime_custom_config_without_environment_is_rejected(self):
        ocio = display._ocio()
        original = ocio.GetCurrentConfig()
        custom = copy.deepcopy(original)
        custom.addColorSpace(ocio.ColorSpace(name='Unvalidated runtime color space'))
        with patch.dict(os.environ):
            os.environ.pop('OCIO', None)
            try:
                ocio.SetCurrentConfig(custom)
                with self.assertRaises(display.DisplayUnavailable):
                    display.processor(self.scene)
            finally:
                ocio.SetCurrentConfig(original)
        # Restoring Blender's configuration must also restore picker admission.
        display.processor(self.scene)
