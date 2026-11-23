"""Transient Node Editor controls and display for the Linear vectorscope."""

from collections.abc import Callable
from dataclasses import dataclass
import math
import threading

import bpy
import numpy as np

from . import localization
from .kernel.settings import LinearSettings
from .vectorscope import CHROMA_LIMIT, WhiteDrag, color_bar_targets


_PER_NODE_TYPES = {"PGShaderGradePerNode", "PGCompositorGradePerNode"}
_SHARED_TYPES = {"PGShaderGrade", "PGCompositorGrade"}
_SMALL_SIDE = 112
_MAX_SIDE = 216
_INTERVAL = 1 / 60
_ENABLED = set()
_PLOTS = {}
_REVISIONS = {}
_REVISION_LOCK = threading.Lock()
_LAST_VIEW = {}
_TEXTURES = {}
_SHADERS = {}
_BATCHES = {}
_DRAGS = {}
_runtime = None
_draw_handle = None
_gesture = None


@dataclass(frozen=True)
class DisplayState:
    rgba: np.ndarray | None
    status: str
    error: str | None

    @property
    def brightness(self):
        return None if self.rgba is None else self.rgba[..., 3]


@dataclass(frozen=True)
class _GestureCallbacks:
    begin: Callable
    edit: Callable
    finish: Callable
    cancel: Callable


@dataclass
class _Drag:
    key: tuple[int, int]
    binding: tuple[int, int | None]
    frame: tuple[int, int, float]
    capture: tuple[str, int, str]
    model: WhiteDrag
    linear: LinearSettings
    x: int
    y: int
    side: int
    threshold: float
    token: int | None = None


def _key(window, area):
    return window.as_pointer(), area.as_pointer()


def _selected(space):
    tree = getattr(space, "edit_tree", None)
    node = getattr(getattr(tree, "nodes", None), "active", None)
    if node is None or not node.select:
        return None
    if (node.bl_idname in _PER_NODE_TYPES
            or node.bl_idname in _SHARED_TYPES and node.pg_grade is not None):
        return node
    return None


def _binding(node):
    grade = getattr(node, "pg_grade", None)
    return node.as_pointer(), None if grade is None else grade.as_pointer()


def _node_editor(context):
    area = context.area
    return context.window is not None and area is not None and area.type == "NODE_EDITOR"


class PG_OT_toggle_vectorscope(bpy.types.Operator):
    bl_idname = "perceptual_grade.toggle_vectorscope"
    bl_label = localization.native("label.vectorscope")
    bl_description = localization.native("tooltip.toggle_vectorscope")
    bl_translation_context = localization.CONTEXT
    bl_options = {"INTERNAL"}

    @classmethod
    def poll(cls, context):
        return _node_editor(context) and (
            _key(context.window, context.area) in _ENABLED
            or _selected(context.space_data) is not None)

    def execute(self, context):
        key = _key(context.window, context.area)
        if key in _ENABLED:
            _ENABLED.remove(key)
            _release(key)
        else:
            _ENABLED.add(key)
            _ensure_timer()
        context.area.tag_redraw()
        return {"FINISHED"}


def draw_toggle(layout, context, node):
    if _node_editor(context) and node == _selected(context.space_data):
        enabled = _key(context.window, context.area) in _ENABLED
        layout.operator(PG_OT_toggle_vectorscope.bl_idname, depress=enabled,
                        icon="HIDE_OFF" if enabled else "HIDE_ON")


def _view_regions(area):
    return tuple(region for region in area.regions
                 if region.type == "WINDOW" and region.width > 0 and region.height > 0)


def remember_viewport(window, x, y):
    if window is None or window.screen is None:
        return
    for area in window.screen.areas:
        if area.type != "VIEW_3D":
            continue
        for region in _view_regions(area):
            if (region.x <= x < region.x + region.width
                    and region.y <= y < region.y + region.height):
                _LAST_VIEW[window.as_pointer()] = area.as_pointer(), region.as_pointer()
                return


def _matrix(value):
    return tuple(tuple(float(item) for item in row) for row in value)


def _viewport_descriptor(window, context):
    views = tuple((area, region, index)
                  for area in window.screen.areas if area.type == "VIEW_3D"
                  for index, region in enumerate(_view_regions(area)))
    if not views:
        return None
    remembered = _LAST_VIEW.get(window.as_pointer())
    selected = next((item for item in views
                     if (item[0].as_pointer(), item[1].as_pointer()) == remembered), None)
    if selected is None:
        selected = max(views, key=lambda item: item[1].width * item[1].height)
    area, region, index = selected
    space = area.spaces.active
    quadviews = tuple(space.region_quadviews)
    view = quadviews[index] if index < len(quadviews) else space.region_3d
    if view is None:
        return None
    scene = context.scene
    layer = context.view_layer
    return {
        "source": "viewport",
        "scene": scene.name,
        "frame": scene.frame_current,
        "frame_subframe": scene.frame_subframe,
        "view_layer": layer.name,
        "engine": scene.render.engine,
        "width": region.width,
        "height": region.height,
        "view_matrix": _matrix(view.view_matrix),
        "projection_matrix": _matrix(view.window_matrix),
        "clip_start": space.clip_start,
        "clip_end": space.clip_end,
        "perspective": view.view_perspective,
        "visible_objects": tuple(sorted(obj.name for obj in layer.objects
                                        if obj.visible_get(view_layer=layer, viewport=space))),
        "viewport": (area.as_pointer(), region.as_pointer()),
    }


def _plot_rect(area, region):
    right = region.width
    if area.spaces.active.show_region_ui:
        right = min((panel.x - region.x for panel in area.regions
                     if panel.type == "UI" and panel.width > 1 and panel.x >= region.x),
                    default=right)
    side = min(_MAX_SIDE, right - 28, region.height - 62)
    if side < _SMALL_SIDE:
        return None
    return right - side - 14, region.height - side - 30, side


def _release(key):
    drag = _DRAGS.get(key[0])
    if drag is not None and drag.key == key:
        _cancel_drag(key[0])
    _PLOTS.pop(key, None)
    with _REVISION_LOCK:
        _REVISIONS.pop(key, None)
    _TEXTURES.pop(key, None)
    if _runtime is not None:
        _runtime.release(key)


def _frame_key(scene):
    return scene.as_pointer(), scene.frame_current, scene.frame_subframe


def _cancel_drag(window_key, *, before_frame_change=False):
    drag = _DRAGS.pop(window_key, None)
    if drag is None or drag.token is None:
        return
    manager = bpy.context.window_manager
    window = None if manager is None else next(
        (item for item in manager.windows if item.as_pointer() == window_key), None)
    restore = window is None or (_frame_key(window.scene) == drag.frame)
    if before_frame_change and window is not None:
        restore = window.scene.as_pointer() == drag.frame[0]
    _gesture.cancel(window_key, drag.token, restore)


def _drag_is_current(drag, window, node):
    return (node is not None and _binding(node) == drag.binding
            and _frame_key(window.scene) == drag.frame
            and _runtime.drag_capture(drag.key, node) == drag.capture)


def frame_change_pre(scene):
    """Cancel same-scene drags before animation evaluates the destination frame."""
    if threading.current_thread() is not threading.main_thread():
        return
    try:
        scene_pointer = int(scene.as_pointer())
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return
    for window_key, drag in tuple(_DRAGS.items()):
        if drag.frame[0] == scene_pointer:
            _cancel_drag(window_key, before_frame_change=True)


def _press_plot(window, event):
    for area in window.screen.areas:
        key = _key(window, area)
        if key not in _ENABLED or area.type != "NODE_EDITOR":
            continue
        region = next(iter(_view_regions(area)), None)
        node = _selected(area.spaces.active)
        if region is None or node is None:
            continue
        bounds = _plot_rect(area, region)
        if bounds is None:
            continue
        x, y, side = bounds
        mouse_x, mouse_y = event.mouse_x - region.x, event.mouse_y - region.y
        if not (x <= mouse_x < x + side and y <= mouse_y < y + side):
            continue
        with bpy.context.temp_override(window=window, area=area, region=region):
            state = display_state(bpy.context)
            if (state is None or state.status != "current" or state.brightness is None
                    or not state.brightness.any()):
                return True
            capture = _runtime.drag_capture(key, node)
            inputs = _runtime.drag_inputs(key, node)
            if capture is None or inputs is None:
                return True
            rgba, linear, space = inputs
            model = WhiteDrag.from_capture(rgba, linear, space)
            if model is not None:
                _DRAGS[key[0]] = _Drag(
                    key, _binding(node), _frame_key(window.scene), capture, model, linear,
                    event.mouse_x, event.mouse_y, side,
                    3.0 * bpy.context.preferences.system.ui_scale,
                )
        return True
    return False


def _move_drag(drag, node, dx, dy):
    values = drag.model.move(drag.linear, dx, dy, drag.side)
    if drag.token is None:
        if values == drag.linear.source_xy:
            return
        inputs = _runtime.drag_inputs(drag.key, node)
        if inputs is None or inputs[1] != drag.linear:
            _cancel_drag(drag.key[0])
            return
        drag.token = _gesture.begin(drag.key[0], node)
        if drag.token is None:
            _cancel_drag(drag.key[0])
            return
    if not _gesture.edit(drag.key[0], drag.token, node, values):
        _cancel_drag(drag.key[0])


def pointer_event(window, event):
    """Handle plot input through the window's existing Grade gesture router."""
    if window is None or window.screen is None or not _ENABLED:
        return False
    window_key = window.as_pointer()
    drag = _DRAGS.get(window_key)
    if drag is None:
        return (event.type == "LEFTMOUSE" and event.value == "PRESS"
                and _press_plot(window, event))
    if event.type == "WINDOW_DEACTIVATE":
        _cancel_drag(window_key)
        return False
    if event.type in {"ESC", "RIGHTMOUSE"} and event.value == "PRESS":
        _cancel_drag(window_key)
        return True
    moving = event.type in {"MOUSEMOVE", "INBETWEEN_MOUSEMOVE"}
    releasing = event.type == "LEFTMOUSE" and event.value == "RELEASE"
    if not (moving or releasing):
        return False
    dx, dy = event.mouse_x - drag.x, event.mouse_y - drag.y
    if drag.token is None and math.hypot(dx, dy) < drag.threshold:
        if releasing:
            _cancel_drag(window_key)
        return True
    area = next((area for area in window.screen.areas
                 if area.as_pointer() == drag.key[1] and area.type == "NODE_EDITOR"), None)
    region = None if area is None else next(iter(_view_regions(area)), None)
    node = None if area is None else _selected(area.spaces.active)
    if region is None or node is None or _plot_rect(area, region) is None:
        _cancel_drag(window_key)
        return True
    with bpy.context.temp_override(window=window, area=area, region=region):
        if releasing or drag.token is None:
            # A link or viewport change can precede the next timer observation.
            _observe(drag.key, window, area, region, node)
        if (_DRAGS.get(window_key) is not drag
                or not _drag_is_current(drag, window, node)):
            _cancel_drag(window_key)
            return True
        _move_drag(drag, node, dx, dy)
        if releasing and _DRAGS.pop(window_key, None) is drag and drag.token is not None:
            _gesture.finish(window_key, drag.token, node)
    return True


def _observe(key, window, area, region, node):
    previous = _PLOTS.get(key)
    binding = _binding(node)
    if previous is not None and previous[0] != binding:
        _release(key)
        previous = None
    with _REVISION_LOCK:
        revision = _REVISIONS.setdefault(key, 0)
    with bpy.context.temp_override(window=window, area=area, region=region):
        context = bpy.context
        frame = _frame_key(context.scene)
        try:
            viewport = (_viewport_descriptor(window, context)
                        if node.id_data.bl_idname == "ShaderNodeTree" else None)
            state = DisplayState(*_runtime.observe(key, context, node, viewport))
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError) as error:
            state = DisplayState(*_runtime.unavailable(key, error))
    _PLOTS[key] = binding, frame, state, revision
    drag = _DRAGS.get(key[0])
    if (drag is not None and drag.key == key
            and (state.status in {"error", "unavailable"}
                 or not _drag_is_current(drag, window, node))):
        _cancel_drag(key[0])
    if state.rgba is None:
        _TEXTURES.pop(key, None)
    if (previous is None or previous[3] != revision
            or previous[2].rgba is not state.rgba
            or previous[2].status != state.status or previous[2].error != state.error):
        area.tag_redraw()


def _tick():
    if _runtime is None:
        return None
    if _ENABLED:
        manager = bpy.context.window_manager
        windows = () if manager is None else tuple(manager.windows)
        editors = {_key(window, area): (window, area)
                   for window in windows if window.screen is not None
                   for area in window.screen.areas if area.type == "NODE_EDITOR"}
        for key in tuple(_ENABLED):
            editor = editors.get(key)
            if editor is None:
                _ENABLED.remove(key)
                _release(key)
                continue
            window, area = editor
            node = _selected(area.spaces.active)
            region = next(iter(_view_regions(area)), None)
            if node is not None and region is not None and _plot_rect(area, region) is not None:
                _observe(key, window, area, region, node)
            elif key in _PLOTS:
                _release(key)
                area.tag_redraw()
        live_windows = {window.as_pointer() for window in windows}
        for key in _LAST_VIEW.keys() - live_windows:
            del _LAST_VIEW[key]
    active = _runtime.poll()
    return _INTERVAL if _ENABLED or active else None


def _ensure_timer():
    if not bpy.app.background and not bpy.app.timers.is_registered(_tick):
        bpy.app.timers.register(_tick, first_interval=0.0, persistent=True)


def display_state(context):
    """Return the visible plot for the active node and editor."""
    if not _node_editor(context):
        return None
    node = _selected(context.space_data)
    key = _key(context.window, context.area)
    plot = _PLOTS.get(key)
    if node is None or plot is None or plot[0] != _binding(node):
        return None
    _, frame, state, revision = plot
    active_frame = _frame_key(context.scene)
    if frame[0] != active_frame[0]:
        return None
    with _REVISION_LOCK:
        invalidated = revision != _REVISIONS.get(key)
    if state.status == "current" and (frame != active_frame or invalidated):
        return DisplayState(state.rgba, "updating", None)
    return state


def _shader(name):
    import gpu
    if name not in _SHADERS:
        _SHADERS[name] = gpu.shader.from_builtin(name)
    return _SHADERS[name]


def _quad(x, y, width, height):
    return (x, y), (x + width, y), (x + width, y + height), (x, y + height)


def _fill(rect, color):
    from gpu_extras.batch import batch_for_shader
    shader = _shader("UNIFORM_COLOR")
    shader.bind()
    shader.uniform_float("color", color)
    key = ("fill", tuple(rect))
    batch = _BATCHES.get(key)
    if batch is None:
        batch = batch_for_shader(shader, "TRI_FAN", {"pos": _quad(*rect)})
        _remember_batch(key, batch)
    batch.draw(shader)


def _remember_batch(key, batch):
    _BATCHES[key] = batch
    while len(_BATCHES) > 32:
        _BATCHES.pop(next(iter(_BATCHES)))


def _draw_trace(rect, rgba, key):
    import gpu
    from gpu_extras.batch import batch_for_shader
    cached = _TEXTURES.get(key)
    if cached is None or cached[0] is not rgba:
        height, width, _ = rgba.shape
        texture = gpu.types.GPUTexture(
            (width, height), format="RGBA16F",
            data=gpu.types.Buffer("FLOAT", rgba.shape, rgba),
        )
        texture.filter_mode(False)
        cached = rgba, texture
        _TEXTURES[key] = cached
    shader = _shader("IMAGE")
    shader.bind()
    shader.uniform_sampler("image", cached[1])
    batch_key = ("density", tuple(rect))
    batch = _BATCHES.get(batch_key)
    if batch is None:
        batch = batch_for_shader(shader, "TRI_FAN", {
            "pos": _quad(*rect), "texCoord": _quad(0, 0, 1, 1),
        })
        _remember_batch(batch_key, batch)
    batch.draw(shader)


_CIRCLE = tuple((math.cos(i * math.tau / 96), math.sin(i * math.tau / 96))
                for i in range(97))
_TARGETS = color_bar_targets()
_SKIN_ANGLE = math.radians(123.0)


def _text(label, x, y, size, color, width):
    import blf
    blf.size(0, size)
    if blf.dimensions(0, label)[0] > width:
        suffix = "..."
        label = label[:128]
        while label and blf.dimensions(0, label + suffix)[0] > width:
            label = label[:-1]
        label += suffix
    blf.position(0, x, y, 0)
    blf.color(0, *color)
    blf.draw(0, label)


def _guides(rect):
    import gpu
    from gpu_extras.batch import batch_for_shader
    x, y, side, _ = rect
    radius = side * 0.5
    cx, cy = x + radius, y + radius
    scale = radius / CHROMA_LIMIT
    targets = [(label, cx + cb * scale, cy + cr * scale)
               for label, cb, cr in _TARGETS]
    half_box = max(3.0, radius * 0.055)
    shader = _shader("POLYLINE_UNIFORM_COLOR")
    shader.bind()
    shader.uniform_float("viewportSize", gpu.state.viewport_get()[2:])
    shader.uniform_float("lineWidth", 1.0)
    key = ("guides", tuple(rect))
    batch = _BATCHES.get(key)
    if batch is None:
        points = tuple((cx + radius * dx, cy + radius * dy, 0) for dx, dy in _CIRCLE)
        positions = [point for segment in zip(points, points[1:]) for point in segment]
        for _, px, py in targets:
            corners = _quad(px - half_box, py - half_box, 2 * half_box, 2 * half_box)
            positions.extend((*point, 0) for segment in zip(corners, (*corners[1:], corners[0]))
                             for point in segment)
        batch = batch_for_shader(shader, "LINES", {"pos": positions})
        _remember_batch(key, batch)
    shader.uniform_float("color", (0.68, 0.68, 0.68, 0.55))
    batch.draw(shader)
    key = ("skin guide", tuple(rect))
    batch = _BATCHES.get(key)
    if batch is None:
        dx, dy = radius * math.cos(_SKIN_ANGLE), radius * math.sin(_SKIN_ANGLE)
        batch = batch_for_shader(shader, "LINES", {
            "pos": [(cx, cy, 0), (cx + dx, cy + dy, 0)],
        })
        _remember_batch(key, batch)
    shader.uniform_float("color", (0.68, 0.68, 0.68, 0.32))
    batch.draw(shader)
    color = (0.72, 0.72, 0.72, 0.92)
    for label, px, py in targets:
        _text(label, px + half_box + 2, py + half_box, 9, color, 20)


def _draw():
    context = bpy.context
    if (not _node_editor(context) or context.region is None
            or context.region.type != "WINDOW"):
        return
    key = _key(context.window, context.area)
    if key not in _ENABLED or _selected(context.space_data) is None:
        return
    bounds = _plot_rect(context.area, context.region)
    if bounds is None:
        return
    import gpu
    x, y, side = bounds
    rect = x, y, side, side
    state = display_state(context)
    blend, depth = gpu.state.blend_get(), gpu.state.depth_test_get()
    try:
        gpu.state.blend_set("ALPHA")
        gpu.state.depth_test_set("NONE")
        _fill((x - 7, y - 28, side + 14, side + 53), (0.075, 0.075, 0.075, 0.97))
        _fill(rect, (0.023, 0.023, 0.023, 1.0))
        if state is not None and state.rgba is not None:
            _draw_trace(rect, state.rgba, key)
        _guides(rect)
        _text(localization.tr("label.vectorscope"), x, y + side + 8, 12,
              (0.94, 0.94, 0.94, 1.0), side)
        if state is None or state.status != "current":
            error = state is not None and state.status in {"error", "unavailable"}
            status = "scope.vectorscope.unavailable" if error else "scope.vectorscope.updating"
            color = (1.0, 0.63, 0.45, 1.0) if error else (0.76, 0.76, 0.76, 1.0)
            _text(localization.tr(status), x, y - 12, 10, color, side)
            if error and state.error:
                _text(state.error.splitlines()[0], x, y - 22, 8, color, side)
    finally:
        gpu.state.blend_set(blend)
        gpu.state.depth_test_set(depth)
    if (getattr(_runtime, "timing", None) is not None
            and state is not None and state.status == "current" and state.rgba is not None):
        _runtime.record_draw(key, state.rgba)


def invalidate(scene, changed_ids):
    if _runtime is not None and _ENABLED:
        affected = _runtime.invalidate(scene, changed_ids)
        _mark_updating(affected)


def linear_changed(node):
    if _runtime is not None and _ENABLED:
        callback = getattr(_runtime, "linear_changed", None)
        _mark_updating(callback(node) if callback is not None else tuple(_PLOTS))


def _mark_updating(affected):
    changed = set()
    with _REVISION_LOCK:
        for key in affected:
            if key in _REVISIONS:
                _REVISIONS[key] += 1
                changed.add(key)
    if not changed or threading.current_thread() is not threading.main_thread():
        return
    manager = bpy.context.window_manager
    if manager is None:
        return
    for window in manager.windows:
        if window.screen is not None:
            for area in window.screen.areas:
                if _key(window, area) in changed:
                    area.tag_redraw()


def _clear_display():
    for window_key in tuple(_DRAGS):
        _cancel_drag(window_key)
    _ENABLED.clear()
    _PLOTS.clear()
    with _REVISION_LOCK:
        _REVISIONS.clear()
    _LAST_VIEW.clear()
    _TEXTURES.clear()
    _BATCHES.clear()


def reset():
    _clear_display()
    if _runtime is not None:
        _runtime.reset()


def register(create_runtime, *, begin, edit, finish, cancel):
    global _runtime, _draw_handle, _gesture
    _gesture = _GestureCallbacks(begin, edit, finish, cancel)
    if _runtime is None:
        _runtime = create_runtime()
    if not PG_OT_toggle_vectorscope.is_registered:
        bpy.utils.register_class(PG_OT_toggle_vectorscope)
    if not bpy.app.background and _draw_handle is None:
        _draw_handle = bpy.types.SpaceNodeEditor.draw_handler_add(
            _draw, (), "WINDOW", "POST_PIXEL")


def unregister():
    global _runtime, _draw_handle, _gesture
    if bpy.app.timers.is_registered(_tick):
        bpy.app.timers.unregister(_tick)
    if _draw_handle is not None:
        bpy.types.SpaceNodeEditor.draw_handler_remove(_draw_handle, "WINDOW")
        _draw_handle = None
    if PG_OT_toggle_vectorscope.is_registered:
        bpy.utils.unregister_class(PG_OT_toggle_vectorscope)
    _clear_display()
    _gesture = None
    runtime = _runtime
    if runtime is not None:
        runtime.close()
        _runtime = None
    _SHADERS.clear()
