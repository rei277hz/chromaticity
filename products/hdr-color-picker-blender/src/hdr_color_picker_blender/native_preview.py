"""Present a transient float image through Blender's native Image Editor."""
from pathlib import Path
from tempfile import TemporaryDirectory

import bpy
import numpy as np
from mathutils import Color

from .display import DisplayUnavailable


def _scene_pixels(rgba, working_space):
    if working_space not in ('ACEScg', 'Linear Rec.709'):
        raise ValueError('Unsupported native preview working space')
    if rgba.ndim != 3 or rgba.shape[2] != 4 or not rgba.size or not np.isfinite(rgba).all():
        raise ValueError('The native preview needs a finite RGBA color slice')
    # Picker rows start at the top. Blender exposes float image pixels bottom-up
    # in the current scene-linear space, including values outside [0, 1].
    pixels = np.array(rgba[::-1], dtype=np.float32, order='C', copy=True)
    if working_space != 'ACEScg':
        matrix = np.array([tuple(Color(rgb).from_acescg_to_scene_linear())
                           for rgb in np.eye(3)], dtype=np.float32)
        pixels[..., :3] = pixels[..., :3] @ matrix
    return pixels


def _create_file_image(path, pixels, working_space):
    # Blender skips the full scene view for GENERATED images. Use an isolated
    # writer to create the first float EXR, then keep only its FILE image.
    height, width, _ = pixels.shape
    scene = bpy.data.scenes.new('HDR Picker EXR Writer')
    try:
        settings = scene.render.image_settings
        settings.file_format = 'OPEN_EXR'
        settings.color_mode = 'RGBA'
        settings.color_depth = '32'
        settings.exr_codec = 'ZIP'
        settings.color_management = 'OVERRIDE'
        settings.linear_colorspace_settings.name = working_space
        writer = bpy.data.images.new('HDR Picker EXR Source', width, height,
                                     alpha=True, float_buffer=True)
        try:
            writer.pixels.foreach_set(pixels.ravel())
            writer.save_render(str(path), scene=scene)
        finally:
            bpy.data.images.remove(writer)
    finally:
        bpy.data.scenes.remove(scene)

    image = bpy.data.images.load(str(path), check_existing=False)
    try:
        image.name = 'HDR Picker Preview'
        image.colorspace_settings.name = working_space
        image.use_view_as_render = True
        image.use_half_precision = False
        return image
    except Exception:
        bpy.data.images.remove(image)
        raise


def _close_window(manager, window):
    if len(manager.windows) > 1:
        with bpy.context.temp_override(window=window):
            bpy.ops.wm.window_close()


class NativePreview:
    def __init__(self):
        self._origin = None
        self._window = None
        self._area = None
        self._screen_uid = None
        self._scene_uid = None
        self._image_uid = None
        self._directory = None
        self._space = None
        self._slice = None
        self._error = None

    def _image(self):
        if self._image_uid is None:
            return None
        return next((image for image in bpy.data.images if image.session_uid == self._image_uid), None)

    def _window_and_area(self, manager):
        if self._window is None or manager is None:
            return None
        window = next((win for win in manager.windows if win.as_pointer() == self._window), None)
        if window is None or window.screen.session_uid != self._screen_uid:
            return None
        area = next((area for area in window.screen.areas if area.as_pointer() == self._area), None)
        if area is None:
            return None
        return window, area

    def _owned_area(self, manager):
        pair = self._window_and_area(manager)
        if pair is None:
            return None
        window, area = pair
        if (len(window.screen.areas) != 1 or area.type != 'IMAGE_EDITOR' or
                area.spaces.active.mode != 'VIEW'):
            return None
        image = area.spaces.active.image
        image_uid = image.session_uid if image is not None else None
        expected = self._image_uid if self._slice is not None else None
        if image_uid != expected:
            return None
        return window, area

    def target(self, manager):
        pair = self._owned_area(manager)
        if pair is None:
            return None
        origin = next((win for win in manager.windows if win.as_pointer() == self._origin), None)
        if origin is None or origin.scene.session_uid != self._scene_uid:
            return None
        return pair if pair[0].scene.session_uid == self._scene_uid else None

    def open(self, context):
        manager = context.window_manager
        if self.target(manager) is not None and self._origin == context.window.as_pointer():
            return
        self.close()
        self._origin = context.window.as_pointer()
        self._scene_uid = context.scene.session_uid
        previous = {window.as_pointer() for window in manager.windows}
        try:
            with bpy.context.temp_override(window=context.window, area=context.area):
                result = bpy.ops.screen.area_dupli('INVOKE_DEFAULT')
            windows = [window for window in manager.windows if window.as_pointer() not in previous]
            if len(windows) == 1 and len(windows[0].screen.areas) == 1:
                self._window = windows[0].as_pointer()
                self._screen_uid = windows[0].screen.session_uid
                self._area = windows[0].screen.areas[0].as_pointer()
            if 'FINISHED' not in result or len(windows) != 1 or self._area is None:
                raise DisplayUnavailable('Blender could not open the native preview window')
            window = windows[0]
            area = window.screen.areas[0]
            with bpy.context.temp_override(window=window, area=area):
                area.type = 'IMAGE_EDITOR'
                area.spaces.active.mode = 'VIEW'
                area.spaces.active.image = None
                area.spaces.active.show_region_ui = False
            self._directory = TemporaryDirectory(prefix='hdr-picker-preview-')
            area.tag_redraw()
        except Exception as exc:
            try:
                pair = self._window_and_area(manager)
                if pair is not None:
                    _close_window(manager, pair[0])
            finally:
                self.close()
            raise DisplayUnavailable(f'Could not open native preview: {exc}') from exc

    def update(self, manager, working_space, rgba, error):
        if self._window is None:
            return
        pair = self.target(manager)
        if pair is None:
            self.close()
            return
        window, area = pair
        if self._error == error and self._slice is rgba and self._space == working_space:
            return
        space = area.spaces.active
        space.image = None
        self._slice = None
        self._space = working_space
        if rgba is None:
            self._error = error
            area.tag_redraw()
            return
        try:
            with bpy.context.temp_override(window=window, area=area):
                pixels = _scene_pixels(np.asarray(rgba, dtype=np.float32), working_space)
            image = self._image()
            first = image is None
            if first:
                path = Path(self._directory.name) / 'preview.exr'
                image = _create_file_image(path, pixels, working_space)
                self._image_uid = image.session_uid
            else:
                height, width, _ = pixels.shape
                if image.colorspace_settings.name != working_space:
                    image.colorspace_settings.name = working_space
                if tuple(image.size) != (width, height):
                    image.scale(width, height)
                image.pixels.foreach_set(pixels.ravel())
                image.update()
                image.save()
            space.image = image
            if first:
                if image.channels == 4:
                    space.display_channels = 'COLOR_ALPHA'
                region = next((region for region in area.regions if region.type == 'WINDOW'), None)
                if region is not None:
                    with bpy.context.temp_override(window=window, area=area, region=region):
                        if bpy.ops.image.view_all.poll():
                            bpy.ops.image.view_all(fit_view=True)
            self._slice = rgba
            self._error = None
        except Exception as exc:
            space.image = None
            image = self._image()
            if image is not None:
                bpy.data.images.remove(image)
            self._image_uid = None
            self._error = f'Native preview unavailable: {exc}'
        area.tag_redraw()

    def status(self, manager):
        pair = self.target(manager)
        if pair is None:
            return None
        if self._error is not None:
            return self._error
        window, area = pair
        if area.spaces.active.image is None:
            return 'Preparing native preview...'
        if window.support_hdr_color and window.scene.view_settings.is_hdr:
            return 'Native HDR preview'
        if window.support_hdr_color:
            return 'Native SDR view on an HDR window'
        return 'Native preview on an SDR window'

    def close(self):
        manager = bpy.context.window_manager
        pair = self._window_and_area(manager)
        try:
            if pair is not None:
                window, area = pair
                still_owned = self._owned_area(manager) is not None
                for space in area.spaces:
                    if (space.type == 'IMAGE_EDITOR' and space.image is not None and
                            space.image.session_uid == self._image_uid):
                        space.image = None
                if still_owned:
                    _close_window(manager, window)
        finally:
            try:
                image = self._image()
                if image is not None:
                    bpy.data.images.remove(image, do_unlink=True)
            finally:
                try:
                    if self._directory is not None:
                        self._directory.cleanup()
                finally:
                    self.__init__()
