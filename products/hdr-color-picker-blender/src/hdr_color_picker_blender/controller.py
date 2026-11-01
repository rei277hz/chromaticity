"""Private value state, asynchronous slice requests, and owned GPU resources."""
from dataclasses import dataclass
import logging
import numpy as np
from . import display
from ..blender_runtime.execution.contracts import JobSpec


@dataclass(frozen=True)
class SliceIdentity:
    lightness: float
    full_rec2020: bool
    width: int = 160
    height: int = 160

    def inputs(self):
        return dict(j=self.lightness, width=self.width, height=self.height,
                    full_rec2020=self.full_rec2020)


class Controller:
    def __init__(self, app):
        from .gpu import Renderer
        self.app = app
        self.arena = app.ownership.arena()
        self.renderer = Renderer()
        self.closed = False
        self.texture_ref = None
        self.view = None
        self.identity = None
        self.pending = None
        self.message = ''
        self.gpu_failed = False
        self.failure = None
        self.view_failure = None

    def reset(self):
        if self.closed:
            return
        self.renderer.reset()
        if self.pending is not None:
            self.pending.cancel()
            self.pending = None
        if self.view is not None:
            self.view.close()
        self.view = None
        self.identity = None
        self.texture_ref = None
        self.arena.begin()
        self.arena.native_replaced()
        self.arena.recovered(self.arena.state.token)
        self.gpu_failed = False
        self.failure = None
        self.view_failure = None
        self.message = ''

    def require_view(self, scene):
        """Prepare the real presentation before admitting interaction or writes."""
        self.app.require_open()
        if self.app.lifecycle is not None and self.app.lifecycle.state.phase != 'active':
            raise display.DisplayUnavailable('Picker resources require recovery')
        key = display.signature(scene)
        if self.view_failure is not None and self.view_failure[0] == key:
            raise display.DisplayUnavailable(self.view_failure[1])
        if self.view is not None and self.view.identity == key:
            return self.view
        if self.view is not None:
            self.view.close()
        self.view = None
        view = None
        try:
            view = display.processor(scene)
            view.gpu()
        except Exception as exc:
            if view is not None:
                view.close()
            self.message = 'Picker preview unavailable: ' + str(exc)
            self.view_failure = key, self.message
            raise display.DisplayUnavailable(self.message) from exc
        self.view = view
        self.view_failure = None
        return view

    def update(self, scene, settings):
        self.app.drain_finalizers()
        view_key = display.signature(scene)
        identity = SliceIdentity(float(settings.lightness), bool(settings.full_rec2020))
        if self.failure == (view_key, identity):
            return False
        self.require_view(scene)
        if identity != self.identity:
            if self.pending is not None:
                self.pending.cancel()
            self.pending = None
            self.identity = identity
            self.texture_ref = None
            if not self.gpu_failed:
                try:
                    self._upload(self.renderer.render_slice(**identity.inputs()))
                    self.message = ''
                    return True
                except Exception:
                    logging.getLogger(__name__).exception('Picker GPU slice failed; using CPU helper')
                    self.gpu_failed = True
            # Named fields at the boundary; no positional cross-module contract.
            self.pending = self.app.execution.get_runtime().submit(JobSpec('picker_slice', identity.inputs(),
                                                       key=identity.inputs()))
            self.message = 'Preparing color slice…'
        if self.pending is not None:
            self.app.execution.get_runtime().poll()
            if self.pending.done():
                handle, self.pending = self.pending, None
                self._upload(handle.result())
                self.message = ''
        return True

    def _upload(self, rgba):
        import gpu
        # Model rows run top to bottom; GPU texture origin runs bottom to top.
        rgba = np.ascontiguousarray(rgba[::-1], dtype=np.float32)
        texture = gpu.types.GPUTexture((rgba.shape[1], rgba.shape[0]), format='RGBA32F',
                                      data=gpu.types.Buffer('FLOAT', rgba.shape, rgba))
        self.texture_ref = self.arena.retain(texture, 'picker.slice')

    def draw(self, scene, settings, origin, size):
        try:
            if not self.update(scene, settings):
                return False
            texture = self.arena.resolve(self.texture_ref)
            if texture is not None:
                import gpu
                previous = gpu.state.blend_get()
                try:
                    gpu.state.blend_set('ALPHA')
                    self.view.gpu().draw(texture, origin, size, viewport_overlay=True)
                finally:
                    gpu.state.blend_set(previous)
                return True
        except Exception as exc:
            self.message = str(exc)
            try:
                self.failure = (display.signature(scene),
                                SliceIdentity(float(settings.lightness), bool(settings.full_rec2020)))
            except Exception:
                self.failure = None
            if self.pending is not None:
                self.pending.cancel()
                self.pending = None
            self.texture_ref = None
            self.identity = None
        return False

    def close(self):
        if self.closed:
            return
        try:
            self.reset()
        finally:
            # A failed display teardown cannot retain device resources or
            # abandon the exact arena needed for terminal App cleanup.
            self.renderer.reset()
            self.view = self.texture_ref = self.pending = None
            self.arena.close()
            self.closed = True
