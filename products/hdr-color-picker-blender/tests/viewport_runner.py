"""Compare the real POST_PIXEL and final window paths to the display processor."""
import importlib
import json
import os
from pathlib import Path
import sys
import time
import traceback

import bpy
import gpu
import numpy as np


repository, report_path = map(Path, sys.argv[sys.argv.index('--') + 1:])
bpy.context.preferences.extensions.repos.new(
    name='Component package acceptance', module='picker_tests', custom_directory=str(repository))
display = importlib.import_module('bl_ext.picker_tests.hdr_color_picker.hdr_color_picker_blender.display')
report = {'passed': False, 'cases': []}
started = time.monotonic()
window = bpy.context.window_manager.windows[0]
area = next(area for area in window.screen.areas if area.type == 'VIEW_3D')
region = next(region for region in area.regions if region.type == 'WINDOW')
scene = window.scene
scene.display_settings.display_device = 'sRGB'
scene.view_settings.use_curve_mapping = False
scene.view_settings.use_white_balance = False
origin = (80, 100)
cell_width, height = 32, 24
samples = np.array([[[0, 0, 0, 1], [.001, .001, .001, 1], [.18, .18, .18, 1],
                     [1, 0, 0, 1], [0, 1, 0, 1], [0, 0, 1, 1],
                     [4, 4, 4, 1], [32, 1, .01, 1]]], dtype=np.float32)
cases = (
    ('AgX', 'None', 0., 1.),
    ('AgX', 'AgX - Punchy', 1.25, .8),
    ('Standard', 'None', -.5, 1.3),
    ('ACES 2.0', 'None', 0., 1.),
    ('Filmic', 'High Contrast', 0., 1.),
    ('Raw', 'None', 0., 1.),
)
texture = None
transform = None
frames = 0
framebuffer_result = None
draw_error = None


def draw():
    global texture, frames, framebuffer_result, draw_error
    if bpy.context.area != area or transform is None:
        return
    try:
        if texture is None:
            texture = gpu.types.GPUTexture((8, 1), format='RGBA32F',
                                          data=gpu.types.Buffer('FLOAT', samples.shape, samples))
            texture.filter_mode(False)
        previous = gpu.state.blend_get()
        try:
            gpu.state.blend_set('NONE')
            transform.gpu().draw(texture, origin, (cell_width * 8, height), viewport_overlay=True)
            pixels = np.array(gpu.state.active_framebuffer_get().read_color(
                origin[0], origin[1], cell_width * 8, height, 4, 0, 'FLOAT'))
            framebuffer_result = pixels[height // 2, cell_width // 2::cell_width, :3]
            frames += 1
        finally:
            gpu.state.blend_set(previous)
    except BaseException:
        draw_error = traceback.format_exc()


handler = bpy.types.SpaceView3D.draw_handler_add(draw, (), 'WINDOW', 'POST_PIXEL')


def screenshot_pixels(path):
    if sys.platform == 'linux':
        # Read the actual X11 window surface. Blender's screenshot operator can
        # read an unbound/cleared back buffer when invoked from a timer.
        import ctypes
        x11 = ctypes.CDLL('libX11.so.6')
        pointer = ctypes.c_void_p
        x11.XOpenDisplay.argtypes, x11.XOpenDisplay.restype = [ctypes.c_char_p], pointer
        x11.XDefaultRootWindow.argtypes, x11.XDefaultRootWindow.restype = [pointer], ctypes.c_ulong
        x11.XGetImage.argtypes = [pointer, ctypes.c_ulong, ctypes.c_int, ctypes.c_int,
                                 ctypes.c_uint, ctypes.c_uint, ctypes.c_ulong, ctypes.c_int]
        x11.XGetImage.restype = pointer
        x11.XGetPixel.argtypes, x11.XGetPixel.restype = [pointer, ctypes.c_int, ctypes.c_int], ctypes.c_ulong
        x11.XDestroyImage.argtypes = [pointer]
        x11.XCloseDisplay.argtypes = [pointer]
        connection = x11.XOpenDisplay(None)
        if not connection:
            raise RuntimeError('Cannot inspect native X11 window')
        image = None
        try:
            root = x11.XDefaultRootWindow(connection)
            image = x11.XGetImage(connection, root, 0, 0, window.width, window.height,
                                 ctypes.c_ulong(-1).value, 2)
            if not image:
                raise RuntimeError('Cannot read native X11 window')
            y = window.height - (region.y + origin[1] + height // 2) - 1
            xs = region.x + origin[0] + np.arange(8) * cell_width + cell_width // 2
            colors = [x11.XGetPixel(image, int(x), y) for x in xs]
            pixels = [[(pixel >> shift & 255) / 255 for shift in (16, 8, 0)] for pixel in colors]
            return np.array(pixels), (window.width, window.height)
        finally:
            if image:
                x11.XDestroyImage(image)
            x11.XCloseDisplay(connection)
    with bpy.context.temp_override(window=window, area=area, region=region):
        bpy.ops.screen.screenshot(filepath=str(path))
    image = bpy.data.images.load(str(path), check_existing=False)
    try:
        image.colorspace_settings.name = 'Non-Color'
        pixels = np.array(image.pixels[:], dtype=np.float32).reshape(image.size[1], image.size[0], 4)
        y = region.y + origin[1] + height // 2
        xs = region.x + origin[0] + np.arange(8) * cell_width + cell_width // 2
        return pixels[y, xs, :3], tuple(image.size)
    finally:
        bpy.data.images.remove(image)


def scenario():
    global transform, frames
    for working in ('ACEScg', 'Linear Rec.709'):
        with bpy.context.temp_override(window=window, area=area, region=region):
            bpy.ops.wm.set_working_color_space(working_space=working)
        for view, look, exposure, gamma in cases:
            scene.view_settings.view_transform = view
            scene.view_settings.look = look
            scene.view_settings.exposure = exposure
            scene.view_settings.gamma = gamma
            if transform is not None:
                transform.close()
            transform = display.processor(scene)
            expected = transform.apply(samples)[0, :, :3]
            frames = 0
            # Force complete native region redraws and wait for the draw handler,
            # rather than assuming a particular timer/frame scheduling order.
            while frames < 4:
                if draw_error:
                    raise RuntimeError(draw_error)
                area.tag_redraw()
                yield
            # The native region target is itself an 8-bit sRGB surface; the
            # separate float-offscreen test checks shader precision tightly.
            linearized = np.clip(expected, 0, 1) ** 2.2
            overlay_encoded = np.where(linearized < .0031308, 12.92 * linearized,
                                       1.055 * linearized ** (1 / 2.4) - .055)
            np.testing.assert_allclose(framebuffer_result, overlay_encoded, atol=2 / 255, rtol=0)
            screenshot, dimensions = screenshot_pixels(report_path.parent / 'viewport.png')
            report['diagnostics'] = {'window_size': dimensions, 'region': (region.x, region.y, region.width, region.height),
                                     'screenshot': screenshot.tolist(), 'framebuffer': framebuffer_result.tolist()}
            # Window compositing quantizes the SDR output to an 8-bit surface.
            target = np.clip(expected, 0, 1)
            # Account explicitly for the intermediate 8-bit sRGB overlay
            # attachment. Gamma-2.2 merge space loses extra precision in very
            # dark colors; this is Blender's buffer format, not OCIO error.
            stored = np.rint(overlay_encoded * 255) / 255
            merged = np.where(stored < .04045, stored / 12.92,
                              ((stored + .055) / 1.055) ** 2.4) ** (1 / 2.2)
            np.testing.assert_allclose(screenshot, merged, atol=2 / 255, rtol=0)
            report['cases'].append({
                'working_space': working, 'view': view, 'look': look,
                'exposure': exposure, 'gamma': gamma,
                'framebuffer_max_error': float(np.max(np.abs(framebuffer_result - overlay_encoded))),
                'window_max_error': float(np.max(np.abs(screenshot - target))),
                'window_quantized_max_error': float(np.max(np.abs(screenshot - merged))),
                'window_size': dimensions,
            })
            report_path.write_text(json.dumps(report, indent=2))
            yield


sequence = scenario()


def advance():
    try:
        if time.monotonic() - started > 120:
            raise TimeoutError('Viewport display acceptance exceeded two minutes')
        next(sequence)
        return .04
    except StopIteration:
        bpy.types.SpaceView3D.draw_handler_remove(handler, 'WINDOW')
        transform.close()
        report['passed'] = True
        report.pop('diagnostics', None)
        report_path.write_text(json.dumps(report, indent=2))
        print('Viewport display acceptance:', json.dumps(report), flush=True)
        bpy.ops.wm.quit_blender('EXEC_DEFAULT')
        return None
    except BaseException:
        report['error'] = traceback.format_exc()
        report_path.write_text(json.dumps(report, indent=2))
        print(json.dumps(report), file=sys.stderr, flush=True)
        os._exit(1)


bpy.app.timers.register(advance, first_interval=.5)
