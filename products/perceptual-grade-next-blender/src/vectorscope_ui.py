"""PERCEPTUAL GRADE Gizmo overlay and live scope display for the Node Editor."""

from collections.abc import Callable
from dataclasses import dataclass, replace
from functools import lru_cache
import math
import threading

import bpy
import numpy as np

from . import appearance_scope, gizmo_geometry as geometry, localization
from .kernel.prepare import nits_to_j, prepare_tone
from .kernel.settings import LinearSettings
from .kernel.tone_ui import TONE_LEVEL_FIELDS, TONE_LIMITS, _j_to_nits
from .tone_scope import PLOT_MAX, ToneWaveforms
from .vectorscope import WhiteDrag


_PER_NODE_TYPES = {"PGShaderGradePerNode", "PGCompositorGradePerNode"}
_SHARED_TYPES = {"PGShaderGrade", "PGCompositorGrade"}
_HOME = (24, 24)
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
_STAGE = {}
_POSITIONS = {}
_TONE_ANCHORS = {}
_DEFAULT_TONE_ANCHOR = TONE_LEVEL_FIELDS.index("input_white")
_PALETTE = {
    name: tuple(int(rgb[index:index + 2], 16) / 255 for index in (0, 2, 4)) + (1.,)
    for name, rgb in {
        "panel": "3d3d3d", "header": "303030", "plot": "282828",
        "outline": "575757", "grid": "404040", "text": "e6e6e6",
        "muted": "aaaaaa", "blue": "265787", "orange": "e87d0d",
        "reference": "9b9b9b", "waveform": "87a3bd",
        "R": "ff3352", "C": "4bc9cc", "B": "2890ff", "Y": "f0cf5a",
    }.items()
}
_AXIS_LABELS = {"cr": "R", "yb": "B"}
_SLIDER_RANGES = {"exposure": (-6., 6.), "cr_balance": (-2., 2.),
                  "yb_balance": (-2., 2.), "fit": (-2., 2.)}


@dataclass(frozen=True)
class DisplayState:
    rgba: np.ndarray | None
    status: str
    error: str | None
    waveforms: ToneWaveforms | None = None
    appearance: appearance_scope.AppearanceScope | None = None
    appearance_status: str | None = None
    appearance_error: str | None = None

    @property
    def brightness(self):
        return None if self.rgba is None else self.rgba[..., 3]


@dataclass(frozen=True)
class _GestureCallbacks:
    begin: Callable
    edit: Callable
    finish: Callable
    cancel: Callable
    linear_settings: Callable
    tone_settings: Callable
    peak_menu: Callable


@dataclass(frozen=True)
class _WhiteControl:
    capture: tuple[str, int, str]
    model: WhiteDrag
    linear: LinearSettings


@dataclass
class _Drag:
    key: tuple[int, int]
    binding: tuple[int, int | None]
    frame: tuple[int, int, float]
    mode: str
    rect: tuple
    origin: tuple
    scale: float
    fields: tuple[str, ...] = ()
    values: tuple[float, ...] = ()
    white: _WhiteControl | None = None
    last: tuple | None = None
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
    bl_label = localization.native("label.gizmo")
    bl_description = localization.native("tooltip.toggle_gizmo")
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
            _close(key)
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


def _stage(key):
    return _STAGE.get(key, "LINEAR")


def _gizmo_layout(area, region, key=None):
    if key is None:
        key = _key(bpy.context.window, area)
    right = region.width
    if area.spaces.active.show_region_ui:
        right = min((panel.x - region.x for panel in area.regions
                     if panel.type == "UI" and panel.width > 1 and panel.x >= region.x),
                    default=right)
    return geometry.layout(_stage(key), right, region.height,
                           bpy.context.preferences.system.ui_scale, _POSITIONS.get(key, _HOME))


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
    box = _gizmo_layout(area, region)
    return None if box is None or "scope" not in box else tuple(map(round, box["scope"][:3]))


def _close(key):
    _ENABLED.discard(key)
    _release(key)
    _STAGE.pop(key, None)
    _POSITIONS.pop(key, None)
    _TONE_ANCHORS.pop(key, None)


def _release(key):
    drag = _DRAGS.get(key[0])
    if drag is not None and drag.key == key:
        _cancel_drag(key[0])
    _PLOTS.pop(key, None)
    with _REVISION_LOCK:
        _REVISIONS.pop(key, None)
    _TEXTURES.pop(key, None)
    _TEXTURES.pop((key, "before"), None)
    _TEXTURES.pop((key, "after"), None)
    _TEXTURES.pop((key, "appearance"), None)
    if _runtime is not None:
        _runtime.release(key)


def _frame_key(scene):
    return scene.as_pointer(), scene.frame_current, scene.frame_subframe


def _cancel_drag(window_key, *, before_frame_change=False):
    drag = _DRAGS.pop(window_key, None)
    if drag is not None and drag.mode == "header":
        _POSITIONS[drag.key] = drag.values
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
            and (drag.white is None
                 or _runtime.drag_capture(drag.key, node) == drag.white.capture))


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


@lru_cache(maxsize=4)
def _tone_model(tone):
    return prepare_tone(tone)


def _level_y(rect, level):
    return rect[1] + min(1., max(0., level / PLOT_MAX)) * rect[3]


def _curve_point(rect, source, target):
    return rect[0] + source / PLOT_MAX * rect[2], _level_y(rect, target)


def _tone_anchor_levels(model):
    # The first curve knot is the fixed origin; the four following knots are editable.
    return model.source[1:], model.target[1:]


def _tone_hit(mode, rect, point, model, selected, scale):
    sources, targets = _tone_anchor_levels(model)
    if mode == "curve":
        actual = model.remap(sources * 100.) / 100.
        choices = ((math.dist(point, _curve_point(rect, source, target)), index != selected, index)
                   for index, source in enumerate(sources) if source <= PLOT_MAX
                   for target in (targets[index], actual[index]) if target <= PLOT_MAX)
    else:
        levels = sources if mode == "before" else targets
        choices = ((abs(point[1] - _level_y(rect, level)), index != selected, index)
                   for index, level in enumerate(levels))
    distance, _, index = min(choices, default=(math.inf, False, None))
    return index if distance <= 7 * scale else None


def _control_values(mode, node, fields):
    if mode in ("fit", "before", "curve"):
        tone = _gesture.tone_settings(node)
        return ((tone.fit,) if mode == "fit"
                else (tone.input_nits[TONE_LEVEL_FIELDS.index(fields[0])],))
    linear = _gesture.linear_settings(node)
    if mode in _AXIS_LABELS:
        index = int(mode == "yb")
        return linear.spread[index], linear.heading[index]
    if mode == "exposure":
        return (linear.exposure,)
    # LinearSettings uses the reference convention, opposite to the RNA controls.
    return (-linear.balance[int(mode == "yb_balance")],)


def _press_control(key, node, box, point, origin, frame):
    mode, fields, white = "body", (), None
    for item in ("close", "linear_tab", "tone_tab", "header"):
        if geometry.contains(box[item], point):
            mode = item
            break
    else:
        for item in _SLIDER_RANGES:
            if item in box and geometry.contains(box[item], point):
                mode, fields = item, (item,)
                break
        else:
            if "scope" in box:
                positions = geometry.handle_positions(box["scope"],
                                                      _gesture.linear_settings(node), box["scale"])
                distance, axis = min((math.dist(point, pos), axis)
                                     for axis, pos in positions.items())
                if distance <= 7 * box["scale"]:
                    mode, fields = axis, (axis + "_spread", axis + "_heading")
                elif geometry.contains(box["scope"], point):
                    state = display_state(bpy.context)
                    if (state is not None and state.status == "current"
                            and state.brightness is not None and state.brightness.any()):
                        capture = _runtime.drag_capture(key, node)
                        inputs = _runtime.drag_inputs(key, node)
                        if capture is not None and inputs is not None:
                            rgba, linear, space = inputs
                            model = WhiteDrag.from_capture(rgba, linear, space)
                            if model is not None:
                                mode, fields = "scope", ("source_x", "source_y")
                                white = _WhiteControl(capture, model, linear)
            elif geometry.contains(box["peak"], point):
                mode = "peak"
            else:
                for side in ("before", "after", "curve"):
                    if not geometry.contains(box[side], point):
                        continue
                    model = _tone_model(_gesture.tone_settings(node))
                    index = _tone_hit(side, box[side], point, model,
                                      _TONE_ANCHORS.get(key, _DEFAULT_TONE_ANCHOR), box["scale"])
                    if index is not None:
                        _TONE_ANCHORS[key] = index
                        if side != "after":
                            mode, fields = side, (TONE_LEVEL_FIELDS[index],)
                    break
    if mode == "header":
        values = box["rect"][0] / box["scale"], box["rect"][1] / box["scale"]
    elif white is not None:
        values = white.linear.source_xy
    else:
        values = _control_values(mode, node, fields) if fields else ()
    rect = box["scope"] if mode in _AXIS_LABELS else box.get(mode, box["rect"])
    return _Drag(key, _binding(node), frame, mode, rect, origin, box["scale"],
                 fields, values, white)


def _press_plot(window, event):
    for area in window.screen.areas:
        key = _key(window, area)
        if key not in _ENABLED or area.type != "NODE_EDITOR":
            continue
        region = next(iter(_view_regions(area)), None)
        node = _selected(area.spaces.active)
        if region is None or node is None:
            continue
        box = _gizmo_layout(area, region, key)
        if box is None:
            continue
        origin = event.mouse_x, event.mouse_y
        point = origin[0] - region.x, origin[1] - region.y
        if not geometry.contains(box["rect"], point):
            continue
        with bpy.context.temp_override(window=window, area=area, region=region):
            _DRAGS[key[0]] = _press_control(key, node, box, point, origin, _frame_key(window.scene))
        area.tag_redraw()
        return True
    return False


def _drag_values(drag, node, mouse):
    dx, dy = mouse[0] - drag.origin[0], mouse[1] - drag.origin[1]
    if drag.white is not None:
        white = drag.white
        return white.model.move(white.linear, dx, dy, drag.rect[2])
    if drag.mode in _AXIS_LABELS:
        last = drag.origin if drag.last is None else drag.last
        start = _control_values(drag.mode, node, drag.fields)
        drag.last = mouse
        return geometry.drag_handle(drag.rect, drag.mode, *start,
                                    mouse[0] - last[0], mouse[1] - last[1])
    if drag.mode in ("before", "curve"):
        reference = _gesture.tone_settings(node).reference_nits
        delta = dy / drag.rect[3] if drag.mode == "before" else dx / drag.rect[2]
        level = float(nits_to_j(drag.values[0], reference)) + delta * .1 * PLOT_MAX
        limits = TONE_LIMITS[TONE_LEVEL_FIELDS.index(drag.fields[0])]
        low, high = nits_to_j(limits, reference)
        return (_j_to_nits(float(min(high, max(low, level))), reference),)
    lo, hi = _SLIDER_RANGES[drag.mode]
    vertical = drag.mode == "cr_balance" or drag.mode == "exposure" and _stage(drag.key) == "LINEAR"
    delta = dy / drag.rect[3] if vertical else dx / drag.rect[2]
    return (min(hi, max(lo, drag.values[0] + delta * (hi - lo))),)


def _move_drag(drag, node, mouse):
    values = _drag_values(drag, node, mouse)
    if drag.token is None:
        if values == drag.values:
            return
        if drag.white is not None:
            inputs = _runtime.drag_inputs(drag.key, node)
            unchanged = inputs is not None and inputs[1] == drag.white.linear
        else:
            unchanged = _control_values(drag.mode, node, drag.fields) == drag.values
        if not unchanged:
            _cancel_drag(drag.key[0])
            return
        drag.token = _gesture.begin(drag.key[0], node, drag.fields)
        if drag.token is None:
            _cancel_drag(drag.key[0])
            return
    if not _gesture.edit(drag.key[0], drag.token, node, values):
        _cancel_drag(drag.key[0])


def _release_button(drag, area, region, click, node):
    if drag.mode not in ("close", "linear_tab", "tone_tab", "peak"):
        return
    point = click[0] - region.x, click[1] - region.y
    if not geometry.contains(drag.rect, point):
        return
    if drag.mode == "close":
        _close(drag.key)
    elif drag.mode == "peak":
        _gesture.peak_menu(bpy.context, node)
    else:
        _STAGE[drag.key] = "LINEAR" if drag.mode == "linear_tab" else "TONE"
        if _STAGE[drag.key] == "LINEAR":
            _runtime.release_appearance(drag.key)
            _TEXTURES.pop((drag.key, "appearance"), None)
    area.tag_redraw()


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
    mouse = event.mouse_x, event.mouse_y
    area = next((area for area in window.screen.areas
                 if area.as_pointer() == drag.key[1] and area.type == "NODE_EDITOR"), None)
    region = None if area is None else next(iter(_view_regions(area)), None)
    node = None if area is None else _selected(area.spaces.active)
    if region is None or node is None or _gizmo_layout(area, region, drag.key) is None:
        _cancel_drag(window_key)
        return True
    with bpy.context.temp_override(window=window, area=area, region=region):
        if drag.white is not None and (releasing or drag.token is None):
            # A link or viewport change can precede the next timer observation.
            _observe(drag.key, window, area, region, node)
        if (_DRAGS.get(window_key) is not drag
                or not _drag_is_current(drag, window, node)):
            _cancel_drag(window_key)
            return True
        if drag.mode == "header":
            _POSITIONS[drag.key] = tuple(value + (end - start) / drag.scale
                                         for value, end, start in zip(drag.values, mouse, drag.origin))
            area.tag_redraw()
        elif drag.fields and (drag.token is not None or math.dist(mouse, drag.origin) >= 3 * drag.scale):
            _move_drag(drag, node, mouse)
        if releasing and _DRAGS.pop(window_key, None) is drag:
            if drag.token is not None:
                _gesture.finish(window_key, drag.token, node)
            else:
                _release_button(drag, area, region, mouse, node)
    return True


def _observe(key, window, area, region, node):
    previous = _PLOTS.get(key)
    binding = _binding(node)
    if previous is not None and previous[0] != binding:
        _release(key)
        previous = None
    with _REVISION_LOCK:
        revision = _REVISIONS.setdefault(key, (0, 0))
    with bpy.context.temp_override(window=window, area=area, region=region):
        context = bpy.context
        frame = _frame_key(context.scene)
        stage = _stage(key)
        viewport = None
        try:
            viewport = (_viewport_descriptor(window, context)
                        if node.id_data.bl_idname == "ShaderNodeTree" else None)
            tone = _gesture.tone_settings(node) if stage == "TONE" else None
            plot, status, error = _runtime.observe(key, context, node, viewport, tone=tone)
            state = (DisplayState(None, status, error, plot) if stage == "TONE"
                     else DisplayState(plot, status, error))
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError) as error:
            state = DisplayState(*_runtime.unavailable(key, error))
        if stage == "TONE":
            try:
                appearance, appearance_status, appearance_error = _runtime.observe_appearance(
                    key, context, node, viewport,
                )
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError) as error:
                appearance, appearance_status, appearance_error = None, "unavailable", str(error)
            state = replace(state, appearance=appearance, appearance_status=appearance_status,
                            appearance_error=appearance_error)
    if state.appearance is None:
        _TEXTURES.pop((key, "appearance"), None)
    _PLOTS[key] = binding, frame, state, revision, stage
    drag = _DRAGS.get(key[0])
    if (drag is not None and drag.key == key
            and (drag.white is not None and state.status in {"error", "unavailable"}
                 or not _drag_is_current(drag, window, node))):
        _cancel_drag(key[0])
    if (previous is None or previous[3:] != (revision, stage)
            or previous[2].rgba is not state.rgba
            or previous[2].waveforms is not state.waveforms
            or previous[2].status != state.status or previous[2].error != state.error
            or previous[2].appearance is not state.appearance
            or previous[2].appearance_status != state.appearance_status
            or previous[2].appearance_error != state.appearance_error):
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
                _close(key)
                continue
            window, area = editor
            node = _selected(area.spaces.active)
            region = next(iter(_view_regions(area)), None)
            if node is not None and region is not None and _gizmo_layout(area, region, key) is not None:
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
    _, frame, state, revision, stage = plot
    active_frame = _frame_key(context.scene)
    if frame[0] != active_frame[0] or stage != _stage(key):
        return None
    with _REVISION_LOCK:
        plot_revision, appearance_revision = _REVISIONS.get(key, revision)
    frame_changed = frame != active_frame
    if state.status == "current" and (frame_changed or plot_revision != revision[0]):
        state = replace(state, status="updating", error=None)
    if stage == "TONE" and getattr(node, "pg_use_bake", False):
        state = replace(state, appearance=None, appearance_status="bake", appearance_error=None)
    elif (state.appearance_status == "current"
            and (frame_changed or appearance_revision != revision[1])):
        state = replace(state, appearance_status="updating", appearance_error=None)
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


def _draw_trace(rect, data, key, *, color=None, additive=True):
    import gpu
    from gpu_extras.batch import batch_for_shader
    cached = _TEXTURES.get(key)
    if cached is None or cached[0] is not data:
        if color is None:
            rgba = data
        else:
            rgba = np.empty((*data.shape, 4), dtype=np.float32)
            rgba[..., :3] = color[:3]
            rgba[..., 3] = data
        height, width, _ = rgba.shape
        texture = gpu.types.GPUTexture(
            (width, height), format="RGBA16F",
            data=gpu.types.Buffer("FLOAT", rgba.shape, rgba),
        )
        texture.filter_mode(False)
        cached = data, texture
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
    blend = gpu.state.blend_get()
    try:
        # Additive blending applies the trace density once to measured RGB.
        gpu.state.blend_set("ADDITIVE" if additive and color is None else "ALPHA")
        batch.draw(shader)
    finally:
        gpu.state.blend_set(blend)


_CIRCLE = tuple((math.cos(i * math.tau / 96), math.sin(i * math.tau / 96))
                for i in range(97))
_SKIN_ANGLE = math.radians(123.0)


def _text(label, x, y, size, color, width, *, align=0.):
    import blf
    blf.size(0, max(1, round(size)))
    if blf.dimensions(0, label)[0] > width:
        suffix = "..."
        label = label[:128]
        while label and blf.dimensions(0, label + suffix)[0] > width:
            label = label[:-1]
        label += suffix
    if align:
        x -= align * blf.dimensions(0, label)[0]
    blf.position(0, x, y, 0)
    blf.color(0, *color)
    blf.draw(0, label)


def _lines(points, color, width=1., *, cache=None):
    import gpu
    from gpu_extras.batch import batch_for_shader
    shader = _shader("POLYLINE_UNIFORM_COLOR")
    shader.bind()
    shader.uniform_float("viewportSize", gpu.state.viewport_get()[2:])
    shader.uniform_float("lineWidth", width)
    shader.uniform_float("color", color)
    batch = _BATCHES.get(cache) if cache is not None else None
    if batch is None:
        batch = batch_for_shader(shader, "LINES", {"pos": [(*point, 0.) for point in points]})
        if cache is not None:
            _remember_batch(cache, batch)
    batch.draw(shader)


def _circle(center, radius, color, width=1., *, cache=None):
    cx, cy = center
    step = 4 if radius <= 8 else 1
    points = [(cx + radius * dx, cy + radius * dy) for dx, dy in _CIRCLE[::step]]
    _lines([p for segment in zip(points, points[1:]) for p in segment], color, width, cache=cache)


def _target_corners(point, half, arm):
    x, y = point
    for sx, sy in ((-1, -1), (-1, 1), (1, -1), (1, 1)):
        corner = x + sx * half, y + sy * half
        yield from (corner, (corner[0] - sx * arm, corner[1]),
                    corner, (corner[0], corner[1] - sy * arm))


def _guides(rect, scale, linear):
    x, y, side, _ = rect
    radius = side * .5
    center = x + radius, y + radius
    targets = geometry.scope_targets(rect)
    reference = _PALETTE["reference"][:3]
    _circle(center, radius, (*reference, .55), scale, cache=("graticule", rect))
    skin = (center[0] + radius * math.cos(_SKIN_ANGLE),
            center[1] + radius * math.sin(_SKIN_ANGLE))
    _lines((center, skin), (*reference, .32), scale, cache=("skin", rect))
    for label, point in targets.items():
        px, py = point
        color = _PALETTE.get(label, _PALETTE["reference"])
        if label in _AXIS_LABELS.values():
            _lines((center, point), (*color[:3], .28), scale, cache=("axis", rect, label))
        _lines(_target_corners(point, 7 * scale, 3 * scale), color, scale,
               cache=("target", rect, scale, label))
        _text(label, px + 9 * scale, py + 5 * scale, 9 * scale, color, 16 * scale)
    for axis, point in geometry.handle_positions(rect, linear, scale).items():
        label = _AXIS_LABELS[axis]
        color = _PALETTE[label]
        if math.dist(point, targets[label]) > scale:
            _lines((center, point), (*color[:3], .35), scale)
        _circle(point, 4.5 * scale, color, 1.6 * scale)


def _slider(rect, field, value, scale, *, vertical=False):
    lo, hi = _SLIDER_RANGES[field]
    x, y, width, height = rect
    amounts = (value - lo) / (hi - lo)
    label = localization.tr("property." + field)
    if vertical:
        _text(label, x + scale, y + height - 10 * scale, 9 * scale, _PALETTE["text"], width)
        _text(f"{value:+.2f}", x + scale, y + 4 * scale, 9 * scale, _PALETTE["orange"], width)
        start = x + width / 2, y + 21 * scale
        end = start[0], y + height - 20 * scale
    else:
        _text(label, x, y + height - 10 * scale, 9 * scale, _PALETTE["text"], width - 42 * scale)
        _text(f"{value:+.2f}", x + width - 35 * scale, y + height - 10 * scale, 9 * scale,
              _PALETTE["orange"], 35 * scale)
        start, end = (x, y + 8 * scale), (x + width, y + 8 * scale)
    middle = tuple((a + b) / 2 for a, b in zip(start, end))
    knob = tuple(a + amounts * (b - a) for a, b in zip(start, end))
    colors = {"cr_balance": ("R", "C"), "yb_balance": ("B", "Y")}
    if field in colors:
        negative, positive = colors[field]
        _lines((start, middle), _PALETTE[negative], scale)
        _lines((middle, end), _PALETTE[positive], scale)
        tint = _PALETTE[positive if value >= 0 else negative]
    else:
        _lines((start, end), _PALETTE["outline"], 3 * scale)
        tint = _PALETTE["orange"]
    _lines((middle, knob), tint, 3 * scale)
    _fill((knob[0] - 3 * scale, knob[1] - 3 * scale, 6 * scale, 6 * scale), tint)


def _draw_header(box, stage):
    x, y, _, _ = box["header"]
    scale = box["scale"]
    _fill(box["rect"], _PALETTE["panel"])
    _fill(box["header"], _PALETTE["header"])
    _text(localization.tr("gizmo.wordmark"), x + 12 * scale, y + 10 * scale,
          10 * scale, _PALETTE["text"], 119 * scale)
    for value, name in (("LINEAR", "linear"), ("TONE", "tone")):
        rect = box[name + "_tab"]
        active = stage == value
        if active:
            _fill(rect, _PALETTE["blue"])
        _text(localization.tr("panel." + name), rect[0] + 4 * scale, rect[1] + 6 * scale,
              9 * scale, _PALETTE["text" if active else "muted"], rect[2] - 8 * scale)
    x, y, _, _ = box["close"]
    _lines(((x + 7 * scale, y + 7 * scale), (x + 15 * scale, y + 15 * scale),
            (x + 15 * scale, y + 7 * scale), (x + 7 * scale, y + 15 * scale)),
           _PALETTE["muted"], scale)


def _draw_linear(box, state, key, linear):
    rect, scale = box["scope"], box["scale"]
    _fill(rect, _PALETTE["plot"])
    if state is not None and state.rgba is not None:
        _draw_trace(rect, state.rgba, key)
    _guides(rect, scale, linear)
    _slider(box["exposure"], "exposure", linear.exposure, scale, vertical=True)
    _slider(box["cr_balance"], "cr_balance", -linear.balance[0], scale, vertical=True)
    _slider(box["yb_balance"], "yb_balance", -linear.balance[1], scale)


def _tone_connector(a, b, color, scale):
    # Smooth connectors join matched landmarks without resembling waveform data.
    points = []
    for i in range(24):
        t = i / 23
        ease = t * t * (3 - 2 * t)
        points.append((a[0] + t * (b[0] - a[0]), a[1] + ease * (b[1] - a[1])))
    _lines([point for i in range(0, 22, 2) for point in points[i:i + 2]], color, scale)


def _draw_tone_curve(rect, model, histogram, selected, scale):
    from gpu_extras.batch import batch_for_shader

    x, y, width, height = rect
    _fill(rect, _PALETTE["plot"])
    if histogram is not None and (maximum := histogram.max()) > 0:
        bin_width = width / histogram.size
        points = []
        for index in np.flatnonzero(histogram):
            a, b, c, d = _quad(x + index * bin_width, y, bin_width,
                                height * .72 * histogram[index] / maximum)
            points.extend((a, b, c, a, c, d))
        shader = _shader("UNIFORM_COLOR")
        shader.bind()
        shader.uniform_float("color", (*_PALETTE["muted"][:3], .24))
        batch_for_shader(shader, "TRIS", {"pos": points}).draw(shader)

    grid = []
    for tick in np.arange(0., PLOT_MAX, .5):
        px, py = _curve_point(rect, tick, tick)
        grid.extend(((px, y), (px, y + height), (x, py), (x + width, py)))
    _lines(grid, _PALETTE["grid"], scale, cache=("curve grid", rect))
    identity = []
    for index in range(0, 36, 2):
        for tick in (index, index + 1):
            level = PLOT_MAX * tick / 36
            identity.append(_curve_point(rect, level, level))
    _lines(identity, _PALETTE["reference"], scale, cache=("curve identity", rect))
    source = np.linspace(0., PLOT_MAX, 192)
    target = model.remap(source * 100.) / 100.
    visible = target <= PLOT_MAX
    curve = [_curve_point(rect, a, b) for a, b in zip(source[visible], target[visible])]
    if curve and not visible.all():
        position = float(np.interp(PLOT_MAX, target, source))
        curve.append(_curve_point(rect, position, PLOT_MAX))
    if len(curve) > 1:
        _lines([point for segment in zip(curve, curve[1:]) for point in segment],
               _PALETTE["orange"], 1.6 * scale)
    sources, targets = _tone_anchor_levels(model)
    actual = model.remap(sources * 100.) / 100.
    for index, source_j in enumerate(sources):
        if source_j > PLOT_MAX:
            continue
        color = _PALETTE["orange" if index == selected else "reference"]
        _circle(_curve_point(rect, source_j, targets[index]), 3 * scale, color, scale)
        if actual[index] <= PLOT_MAX:
            _circle(_curve_point(rect, source_j, actual[index]), 1.5 * scale, color, 2 * scale)
    _text(localization.tr("gizmo.tone_curve"), x, y + height + 23 * scale,
          10 * scale, _PALETTE["text"], width)
    _text(localization.tr("gizmo.output_j"), x, y + height + 9 * scale,
          8 * scale, _PALETTE["muted"], width)
    _text(localization.tr("gizmo.input_j"), x + width * .38, y - 14 * scale,
          8 * scale, _PALETTE["muted"], width * .6)


def _draw_appearance(box, state, key):
    rect, scale = box["appearance"], box["scale"]
    x, y, width, height = rect
    top, right = y + height, x + width
    left = box["before"][0]
    column_width = box["after"][0] + box["after"][2] - left
    compact = box["compact_waveforms"] or height < 55 * scale
    appearance = None if state is None else state.appearance
    status = None if state is None else state.appearance_status
    _fill(rect, _PALETTE["plot"])
    guide = []
    saturation_ticks = ((0., "0"), (.5, "0.5"), (1., "1"), (2., "2"), (math.inf, "\u221e"))
    for value, label in saturation_ticks:
        px = x + appearance_scope.saturation_position(value) * width
        if 0. < value < math.inf:
            guide.extend(((px, y), (px, top)))
        if not compact or value in (0., 1., math.inf):
            alignment = 1. if value == math.inf else .5
            _text(label, px, y - 11 * scale, 8 * scale, _PALETTE["muted"],
                  20 * scale, align=alignment)
    if not compact:
        middle = y + appearance_scope.lightness_position(50.) * height
        guide.extend(((x, middle), (right, middle)))
    _lines(guide, _PALETTE["grid"], scale, cache=("appearance grid", rect))
    if appearance is not None:
        _draw_trace(rect, appearance.rgba, (key, "appearance"), additive=False)

    knee = y + appearance_scope.lightness_position(appearance_scope.LIGHTNESS_KNEE) * height
    dash = 5 * scale
    segments = [point for start in np.arange(x, right, 2 * dash)
                for point in ((start, knee), (min(start + dash, right), knee))]
    _lines(segments, (*_PALETTE["orange"][:3], .65), scale, cache=("appearance knee", rect))
    _lines(((x, y), (x, top), (x, y), (right, y), (x, top), (right, top),
            (right, top), (right, y)), _PALETTE["outline"], scale,
           cache=("appearance outline", rect))

    lightness_ticks = [(y, "0"), (knee - 2 * scale, "100"),
                       (top + 2 * scale, localization.tr("scope.appearance.upper"))]
    if not compact:
        lightness_ticks.insert(1, (middle, "50"))
    for py, label in lightness_ticks:
        _text(label, x - 3 * scale, py - 3 * scale, 8 * scale,
              _PALETTE["orange" if label == "100" else "muted"], 31 * scale, align=1.)
    _text("J_HK", x - 3 * scale, top + 10 * scale, 8 * scale,
          _PALETTE["muted"], 28 * scale, align=1.)
    _text("s" if compact else localization.tr("scope.appearance.axis_saturation"),
          x - 11 * scale if compact else x + width * .5,
          y - (11 if compact else 22) * scale, 8 * scale, _PALETTE["muted"],
          width, align=.5)
    _text(localization.tr("scope.appearance.title"), x, top + 10 * scale, 9 * scale,
          _PALETTE["text"], column_width - (x - left))
    if appearance is not None:
        _text(localization.tr("scope.appearance.overflow", fraction=appearance.overflow_fraction),
              left + column_width, top + 22 * scale, 8 * scale,
              _PALETTE["orange" if appearance.overflow_fraction else "muted"],
              column_width, align=1.)
    if status != "current":
        status_id = status if status in {"bake", "unavailable"} else (
            "unavailable" if status == "error" else "updating")
        _text(localization.tr("scope.appearance." + status_id), x + width * .5,
              y + height * .5 - 3 * scale, 8 * scale,
              _PALETTE["orange" if status_id == "unavailable" else "text"],
              width - 4 * scale, align=.5)
        if status_id == "unavailable" and state.appearance_error:
            _text(state.appearance_error.splitlines()[0], x + width * .5,
                  y + height * .5 - 15 * scale, 8 * scale,
                  _PALETTE["muted"], width - 4 * scale, align=.5)


def _draw_tone(box, state, key, linear, tone):
    scale = box["scale"]
    model = _tone_model(tone)
    source, target = _tone_anchor_levels(model)
    selected = _TONE_ANCHORS.get(key, _DEFAULT_TONE_ANCHOR)
    waves = None if state is None else state.waveforms
    _slider(box["exposure"], "exposure", linear.exposure, scale)
    _slider(box["fit"], "fit", tone.fit, scale)
    _draw_appearance(box, state, key)
    peak = box["peak"]
    _fill(peak, _PALETTE["header"])
    px, py, pw, _ = peak
    peak_value = localization.tr(f"tone.peak.{int(tone.peak_nits)}")
    _text(localization.tr("gizmo.peak", value=peak_value), px + 6 * scale, py + 9 * scale,
          9 * scale, _PALETTE["text"], pw - 23 * scale)
    _lines(((px + pw - 15 * scale, py + 15 * scale), (px + pw - 11 * scale, py + 11 * scale),
            (px + pw - 11 * scale, py + 11 * scale), (px + pw - 7 * scale, py + 15 * scale)),
           _PALETTE["muted"], scale)
    for side, levels in (("before", source), ("after", target)):
        rect = box[side]
        x, y, width, height = rect
        _fill(rect, _PALETTE["plot"])
        if waves is not None:
            _draw_trace(rect, getattr(waves, side), (key, side), color=_PALETTE["waveform"])
        grid = [(px, _level_y(rect, tick)) for tick in np.arange(0., PLOT_MAX, .5)
                for px in (x, x + width)]
        _lines(grid, _PALETTE["grid"], scale, cache=("wave grid", rect))
        compact = box["compact_waveforms"]
        _text(localization.tr("gizmo." + side), x, y + height + (8 if compact else 23) * scale,
              10 * scale, _PALETTE["text"], width)
        if not compact:
            anchor = localization.tr("property." + TONE_LEVEL_FIELDS[selected])
            _text(f"{anchor}  {float(levels[selected]):.2f} J", x,
                  y + height + 9 * scale, 9 * scale, _PALETTE["orange"], width)
        for index, value in enumerate(levels):
            level_y = _level_y(rect, value)
            color = _PALETTE["orange" if index == selected else "reference"]
            if value <= PLOT_MAX:
                _lines(((x, level_y), (x + width, level_y)), color, scale)
            mark = x + width if side == "before" else x
            _circle((mark, level_y), 2.5 * scale, color, scale)
    before, after = box["before"], box["after"]
    for index in (*[i for i in range(len(source)) if i != selected], selected):
        color = _PALETTE["orange" if index == selected else "reference"]
        a, b = _level_y(before, source[index]), _level_y(after, target[index])
        _tone_connector((before[0] + before[2] + 3 * scale, a),
                        (after[0] - 3 * scale, b), color, scale)
    _draw_tone_curve(box["curve"], model, None if waves is None else waves.histogram,
                     selected, scale)


def _draw_status(box, state):
    if state is not None and state.status == "current":
        return
    failed = state is not None and state.status in {"error", "unavailable"}
    title = localization.tr("scope.vectorscope.unavailable" if failed
                            else "scope.vectorscope.updating")
    if failed and state.error:
        title += "  " + state.error.splitlines()[0]
    x, y, width, _ = box["status"]
    scale = box["scale"]
    _text(title, x, y + 3 * scale, 9 * scale,
          _PALETTE["orange" if failed else "muted"], width)


def _draw():
    context = bpy.context
    if (not _node_editor(context) or context.region is None
            or context.region.type != "WINDOW"):
        return
    key = _key(context.window, context.area)
    node = _selected(context.space_data)
    if key not in _ENABLED or node is None:
        return
    box = _gizmo_layout(context.area, context.region, key)
    if box is None:
        return
    import gpu
    from mathutils import Matrix

    stage = _stage(key)
    state = display_state(context)
    blend, depth = gpu.state.blend_get(), gpu.state.depth_test_get()
    try:
        gpu.state.blend_set("ALPHA")
        gpu.state.depth_test_set("NONE")
        with gpu.matrix.push_pop(), gpu.matrix.push_pop_projection():
            gpu.matrix.load_identity()
            gpu.matrix.load_projection_matrix(Matrix((
                (2 / context.region.width, 0, 0, -1),
                (0, 2 / context.region.height, 0, -1),
                (0, 0, -1, 0), (0, 0, 0, 1),
            )))
            _draw_header(box, stage)
            linear = _gesture.linear_settings(node)
            if stage == "LINEAR":
                _draw_linear(box, state, key, linear)
            else:
                _draw_tone(box, state, key, linear, _gesture.tone_settings(node))
            _draw_status(box, state)
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


def tone_changed(node):
    if _runtime is not None and _ENABLED:
        _mark_updating(_runtime.tone_changed(node))


def appearance_changed(owner):
    if _runtime is not None and _ENABLED:
        _mark_updating(_runtime.appearance_changed(owner), appearance_only=True)


def _mark_updating(affected, *, appearance_only=False):
    changed = set()
    with _REVISION_LOCK:
        for key in affected:
            if key in _REVISIONS:
                plot, appearance = _REVISIONS[key]
                _REVISIONS[key] = plot + int(not appearance_only), appearance + 1
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
    _tone_model.cache_clear()
    _STAGE.clear()
    _POSITIONS.clear()
    _TONE_ANCHORS.clear()


def reset():
    _clear_display()
    if _runtime is not None:
        _runtime.reset()


def register(create_runtime, *, begin, edit, finish, cancel,
             linear_settings, tone_settings, peak_menu):
    global _runtime, _draw_handle, _gesture
    _gesture = _GestureCallbacks(begin, edit, finish, cancel, linear_settings,
                                 tone_settings, peak_menu)
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
