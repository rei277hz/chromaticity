"""Actual Blender compute renderer for the legacy picker color equations.

The owning extension creates and retires this program on Blender's main thread.
No other extension namespace is consulted here.
"""
import threading

import numpy as np

from . import _glsl
from ..color_core import aces2
from ..hdr_color_picker_core import slice_source, render_slice as cpu_render_slice


class Program:
    """A device program with a mandatory CPU conformance check before use."""

    def __init__(self):
        if threading.current_thread() is not threading.main_thread():
            raise RuntimeError('Picker GPU programs require Blender\'s main thread')
        import gpu
        if not gpu.capabilities.compute_shader_support_get():
            raise RuntimeError('Compute shaders are unavailable')
        self.gpu = gpu
        table = np.concatenate((aces2.HDR_REACH_M, aces2.HDR_GAMUT_CUSP, aces2.HDR_GAMUT_HUES)).astype('f4')
        packed = np.zeros(((len(table)+255)//256, 256), dtype='f4')
        packed.flat[:len(table)] = table
        self.tables = gpu.types.GPUTexture((256, len(packed)), format='R32F',
            data=gpu.types.Buffer('FLOAT', packed.shape, packed))
        info = gpu.types.GPUShaderCreateInfo()
        info.local_group_size(8, 8, 1)
        info.sampler(0, 'FLOAT_2D', 'tables')
        info.image(0, 'RGBA32F', 'FLOAT_2D', 'output_pixels', qualifiers={'WRITE'})
        info.push_constant('IVEC2', 'dimensions')
        info.push_constant('FLOAT', 'j_value')
        info.push_constant('INT', 'full_rec2020')
        info.compute_source(_glsl.source())
        self.shader = gpu.shader.create_from_info(info)
        self.output = None
        self.dimensions = None
        self.conformance = self._check()

    def _render(self, j, width, height, full_rec2020=True):
        width, height = int(width), int(height)
        if width < 1 or height < 1 or width*height > 4096*4096:
            raise ValueError('Slice dimensions must be positive and at most 16M pixels')
        if self.dimensions != (width, height):
            self.output = self.gpu.types.GPUTexture((width, height), format='RGBA32F')
            self.dimensions = (width, height)
        self.shader.bind()
        self.shader.uniform_sampler('tables', self.tables)
        self.shader.uniform_int('dimensions', (width, height))
        self.shader.uniform_float('j_value', float(j))
        self.shader.uniform_int('full_rec2020', int(bool(full_rec2020)))
        self.shader.image('output_pixels', self.output)
        self.gpu.compute.dispatch(self.shader, (width+7)//8, (height+7)//8, 1)
        result = np.array(self.output.read(), dtype='f4').reshape(height, width, 4)
        # Source gamut membership is a double-precision authoring contract.
        # A float32 shader can round a peak or zero crossing to its other side;
        # retain the exact CPU mask and repair only rejected valid pixels.
        xyz, valid = slice_source(j, width, height, full_rec2020)
        missing = valid & (result[..., 3] == 0)
        if np.any(missing):
            result[missing, :3] = aces2.inverse_from_xyz_d65(xyz[missing])
        result[~valid] = 0
        result[..., 3] = valid
        return result

    def _check(self):
        worst = 0.0
        count = 0
        for j in (0, .01, .1, .25, .5, .75, .95, 1):
            for full in (True, False):
                actual = self._render(j, 31, 31, full)
                expected = cpu_render_slice(j, 31, 31, full)
                if not np.array_equal(actual[..., 3], expected[..., 3]):
                    raise RuntimeError('Picker GPU gamut validity differs from the CPU contract')
                if not np.isfinite(actual).all():
                    raise RuntimeError('Picker GPU produced a non-finite result')
                valid = expected[..., 3] > 0
                delta = np.abs(actual[valid, :3]-expected[valid, :3])
                tolerance = 3e-5+3e-4*np.abs(expected[valid, :3])
                if np.any(delta > tolerance):
                    raise RuntimeError('Picker GPU color differs from the CPU contract')
                worst = max(worst, float(np.max(delta, initial=0)))
                count += int(valid.sum())
        return {'samples': count, 'maximum_absolute_error': worst}

    def render_slice(self, j, width, height, full_rec2020=True):
        if threading.current_thread() is not threading.main_thread():
            raise RuntimeError('Picker GPU rendering requires Blender\'s main thread')
        return self._render(j, width, height, full_rec2020)



class Renderer:
    """One controller's lazy GPU program and device resource lifetime."""
    def __init__(self):
        self.program = None

    def render_slice(self, j, width, height, full_rec2020=True):
        if self.program is None:
            self.program = Program()
        return self.program.render_slice(j, width, height, full_rec2020)

    def reset(self):
        self.program = None
