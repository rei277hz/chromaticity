"""Compare the picker overlay and a native file-backed Image Editor in one window."""
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
import PyOpenColorIO as ocio


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
scene.view_settings.use_curve_mapping = False
scene.view_settings.use_white_balance = False
scene.render.dither_intensity = 0
origin = (80, 100)
cell_width, height = 32, 24
samples = np.array([[[0, 0, 0, 1], [.001, .001, .001, 1], [.18, .18, .18, 1],
                     [1, 0, 0, 1], [0, 1, 0, 1], [0, 0, 1, 1],
                     [4, 4, 4, 1], [32, 1, .01, 1]]], dtype=np.float32)
swatch_count = samples.shape[1]
texture = None
transform = None
frames = 0
reference_frames = 0
framebuffer_result = None
draw_error = None
reference_area = next(a for a in window.screen.areas if a.type == 'PROPERTIES')
reference_area.type = 'IMAGE_EDITOR'
reference_space = reference_area.spaces.active
reference_space.show_region_ui = False
reference_space.show_region_toolbar = False
reference_space.overlay.show_overlays = False
reference_region = next(r for r in reference_area.regions if r.type == 'WINDOW')
report['blender'] = list(bpy.app.version)
report['hdr_window'] = window.support_hdr_color


def reference_file():
    """Write 32-bit ACEScg swatches, with no display transform baked in."""
    width = swatch_count * cell_width
    path = report_path.parent / 'acescg-swatches.exr'
    image = bpy.data.images.new('Reference swatches', width=width, height=height,
                                alpha=True, float_buffer=True)
    try:
        image.colorspace_settings.name = 'ACEScg'
        image.pixels.foreach_set(np.tile(samples.repeat(cell_width, axis=1), (height, 1, 1)).ravel())
        fmt = scene.render.image_settings
        fmt.file_format = 'OPEN_EXR'
        fmt.color_mode = 'RGBA'
        fmt.color_depth = '32'
        fmt.color_management = 'OVERRIDE'
        fmt.linear_colorspace_settings.name = 'ACEScg'
        image.save_render(str(path), scene=scene)
    finally:
        bpy.data.images.remove(image)
    return path


def mark_reference_draw():
    global reference_frames
    if bpy.context.area == reference_area:
        reference_frames += 1


def draw():
    global texture, frames, framebuffer_result, draw_error
    if bpy.context.area != area or transform is None:
        return
    try:
        if texture is None:
            texture = gpu.types.GPUTexture((swatch_count, 1), format='RGBA32F',
                                          data=gpu.types.Buffer('FLOAT', samples.shape, samples))
            texture.filter_mode(False)
        previous = gpu.state.blend_get()
        try:
            gpu.state.blend_set('NONE')
            transform.gpu(viewport_overlay=True).draw(texture, origin, (cell_width * swatch_count, height))
            pixels = np.array(gpu.state.active_framebuffer_get().read_color(
                origin[0], origin[1], cell_width * swatch_count, height, 4, 0, 'FLOAT'))
            framebuffer_result = pixels[height // 2, cell_width // 2::cell_width, :3]
            frames += 1
        finally:
            gpu.state.blend_set(previous)
    except BaseException:
        draw_error = traceback.format_exc()


handler = bpy.types.SpaceView3D.draw_handler_add(draw, (), 'WINDOW', 'POST_PIXEL')
reference_handler = bpy.types.SpaceImageEditor.draw_handler_add(
    mark_reference_draw, (), 'WINDOW', 'POST_PIXEL')


def screenshot_pixels(path, points):
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
            colors = [x11.XGetPixel(image, x, window.height - 1 - y) for x, y in points]
            pixels = [[(pixel >> shift & 255) / 255 for shift in (16, 8, 0)] for pixel in colors]
            return np.array(pixels)
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
        return np.array([pixels[y, x, :3] for x, y in points])
    finally:
        bpy.data.images.remove(image)


def sample_points():
    picker = [(region.x + origin[0] + (index * cell_width) + cell_width // 2,
               region.y + origin[1] + height // 2) for index in range(swatch_count)]
    reference = []
    for index in range(swatch_count):
        x, y = reference_region.view2d.view_to_region((index + .5) / swatch_count, .5, clip=False)
        if not (0 <= x < reference_region.width and 0 <= y < reference_region.height):
            raise RuntimeError(f'Image Editor swatch {index} lies outside its region')
        reference.append((reference_region.x + x, reference_region.y + y))
    return picker + reference


def storage_from_screen(value):
    """8-bit sRGB overlay before Blender composites it in gamma-2.2 space."""
    linear = np.clip(value, 0, 1) ** 2.2
    return np.where(linear < .0031308, 12.92 * linear, 1.055 * linear ** (1 / 2.4) - .055)


def screen_from_storage(value):
    linear = np.where(value < .04045, value / 12.92, ((value + .055) / 1.055) ** 2.4)
    return linear ** (1 / 2.2)


def compare_window():
    screenshot = screenshot_pixels(report_path.parent / 'viewport.png', sample_points())
    picker, native = np.split(screenshot, 2)
    if np.ptp(native) < .15:
        raise AssertionError(f'Native Image Editor swatches are indistinguishable: {native}')
    # A native screenshot already rounded each channel to 8 bits. Its one-code
    # neighborhood bounds the expected independently quantized overlay texture.
    lower = np.rint(255 * storage_from_screen(native - 1 / 255)) / 255
    upper = np.rint(255 * storage_from_screen(native + 1 / 255)) / 255
    error = np.maximum(lower - framebuffer_result, framebuffer_result - upper)
    if np.max(error) > 2 / 255:
        raise AssertionError(f'Picker overlay {framebuffer_result} differs from native colors {native}')
    # The readback above is the storage encoding, before the viewport merge.
    np.testing.assert_allclose(picker, screen_from_storage(framebuffer_result), atol=2 / 255, rtol=0)
    return float(np.max(np.abs(picker - native)))


def view_cases(working):
    config = ocio.GetCurrentConfig()
    devices = config.getDisplays() if bpy.app.version >= (5, 3, 0) else ('sRGB',)
    for device in devices:
        for view in config.getViews(device):
            for emulation in ('OFF', 'AUTO'):
                look, exposure, gamma = 'None', 0., 1.
                if working == 'Linear Rec.709' and emulation == 'AUTO':
                    if view.startswith('AgX'):
                        look, exposure, gamma = 'AgX - Punchy', 1.25, .8
                    elif view == 'Filmic':
                        look = 'High Contrast'
                    elif view == 'False Color':
                        look = 'False Color - Punchy'
                    elif view.startswith('ACES'):
                        look = view.split(' - ')[0] + ' - Reference Gamut Compression'
                    elif view == 'Standard':
                        exposure, gamma = -.5, 1.3
                yield device, view, emulation, look, exposure, gamma


def scenario():
    global transform, frames, reference_frames
    with bpy.context.temp_override(window=window, area=area, region=region):
        bpy.ops.wm.set_working_color_space(working_space='ACEScg')
    path = reference_file()
    for working in ('ACEScg', 'Linear Rec.709'):
        with bpy.context.temp_override(window=window, area=area, region=region):
            bpy.ops.wm.set_working_color_space(working_space=working)
        image = bpy.data.images.load(str(path), check_existing=False)
        image.colorspace_settings.name = 'ACEScg'
        if working == 'ACEScg':
            values = np.asarray(image.pixels[:]).reshape(height, -1, 4)
            np.testing.assert_allclose(values[height // 2, cell_width // 2::cell_width], samples[0],
                                       rtol=0, atol=1e-5)
        image.use_view_as_render = True
        reference_space.image = image
        reference_space.display_channels = 'COLOR'
        with bpy.context.temp_override(window=window, area=reference_area, region=reference_region):
            bpy.ops.image.view_all(fit_view=True)
        for device, view, emulation, look, exposure, gamma in view_cases(working):
            scene.display_settings.display_device = device
            scene.view_settings.view_transform = view
            scene.view_settings.look = look
            scene.view_settings.exposure = exposure
            scene.view_settings.gamma = gamma
            scene.display_settings.emulation = emulation
            case = dict(working_space=working, device=device, view=view, look=look,
                        emulation=emulation, exposure=exposure, gamma=gamma)
            report['current_case'] = case
            if transform is not None:
                transform.close()
            transform = display.processor(scene, window)
            frames = reference_frames = 0
            while min(frames, reference_frames) < 2:
                if draw_error:
                    raise RuntimeError(draw_error)
                area.tag_redraw()
                reference_area.tag_redraw()
                yield
            case['max_window_difference'] = compare_window()
            report['cases'].append(case)
            yield
        reference_space.image = None
        bpy.data.images.remove(image)


sequence = scenario()


def advance():
    try:
        if time.monotonic() - started > 900:
            raise TimeoutError(f'Viewport display acceptance timed out after {len(report["cases"])} cases')
        next(sequence)
        return .04
    except StopIteration:
        bpy.types.SpaceView3D.draw_handler_remove(handler, 'WINDOW')
        bpy.types.SpaceImageEditor.draw_handler_remove(reference_handler, 'WINDOW')
        transform.close()
        report['passed'] = True
        report.pop('current_case', None)
        report_path.write_text(json.dumps(report, indent=2))
        print(f'Compared {len(report["cases"])} picker and native Image Editor cases', flush=True)
        bpy.ops.wm.quit_blender('EXEC_DEFAULT')
        return None
    except BaseException:
        report['error'] = traceback.format_exc()
        report_path.write_text(json.dumps(report, indent=2))
        print(json.dumps(report), file=sys.stderr, flush=True)
        os._exit(1)


bpy.app.timers.register(advance, first_interval=.5)
