"""Blender registration and editor lifetime for the Gizmo."""

import threading

import bpy

from ... import localization
from . import display, editor
from .interaction import GestureCallbacks, Interaction


_INTERVAL = 1 / 60
_editors = {}
_last_view = {}
_runtime = None
_interaction = None
_draw_handle = None
_shutting_down = False
_pending_redraws = set()
_redraw_lock = threading.Lock()


class PG_OT_toggle_vectorscope(bpy.types.Operator):
    bl_idname = "perceptual_grade.toggle_vectorscope"
    bl_label = localization.native("label.gizmo")
    bl_description = localization.native("tooltip.toggle_gizmo")
    bl_translation_context = localization.CONTEXT
    bl_options = {"INTERNAL"}

    @classmethod
    def poll(cls, context):
        return not _shutting_down and editor.is_node_editor(context) and (
            editor.key(context.window, context.area) in _editors
            or editor.selected(context.space_data) is not None)

    def execute(self, context):
        key = editor.key(context.window, context.area)
        if key in _editors:
            _close(key)
        else:
            _editors[key] = editor.Preferences()
            _ensure_timer()
        context.area.tag_redraw()
        return {"FINISHED"}


def draw_toggle(layout, context, node):
    if editor.is_node_editor(context) and node == editor.selected(context.space_data):
        enabled = editor.key(context.window, context.area) in _editors
        layout.operator(PG_OT_toggle_vectorscope.bl_idname, depress=enabled,
                        icon="HIDE_OFF" if enabled else "HIDE_ON")


def remember_viewport(window, x, y):
    if _shutting_down or window is None or window.screen is None:
        return
    for area in window.screen.areas:
        if area.type != "VIEW_3D":
            continue
        for region in editor.view_regions(area):
            if (region.x <= x < region.x + region.width
                    and region.y <= y < region.y + region.height):
                _last_view[window.as_pointer()] = area.as_pointer(), region.as_pointer()
                return


def _matrix(value):
    return tuple(tuple(float(item) for item in row) for row in value)


def _viewport_descriptor(window, context):
    views = tuple((area, region, index)
                  for area in window.screen.areas if area.type == "VIEW_3D"
                  for index, region in enumerate(editor.view_regions(area)))
    if not views:
        return None
    remembered = _last_view.get(window.as_pointer())
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


def _change_stage(key, stage):
    _editors[key].stage = stage
    if stage == "LINEAR":
        _runtime.release_appearance(key)
        display.release(key, appearance_only=True)


def _release(key):
    _interaction.release(key)
    _runtime.release(key)
    display.release(key)


def _close(key):
    _release(key)
    _editors.pop(key, None)


def _readout(key, node, scene):
    return _runtime.display_state(
        key, node, frame=editor.frame_key(scene), stage=_editors[key].stage,
        dragging=_interaction.dragging(key),
    )


def display_state(context):
    """Return the runtime's readout for the selected Grade."""
    if _shutting_down or _runtime is None or not editor.is_node_editor(context):
        return None
    key = editor.key(context.window, context.area)
    node = editor.selected(context.space_data)
    if key not in _editors or node is None:
        return None
    return _readout(key, node, context.scene)


def _observe(key, window, area, region, node):
    with bpy.context.temp_override(window=window, area=area, region=region):
        context = bpy.context
        stage = _editors[key].stage
        _runtime.observe_editor(
            key, context, node, frame=editor.frame_key(context.scene),
            stage=stage, dragging=_interaction.dragging(key),
            viewport_for=(lambda: _viewport_descriptor(window, context)
                          if node.id_data.bl_idname == "ShaderNodeTree" else None),
            tone_for=(lambda: _interaction.callbacks.tone_settings(node)
                      if stage == "TONE" else None),
        )
        _interaction.reconcile(key, window, node)


def _display_changed(before, after):
    if before is None or after is None:
        return before is not after
    return (
        before.rgba is not after.rgba
        or before.tone_histogram is not after.tone_histogram
        or before.appearance is not after.appearance
        or before.status != after.status or before.error != after.error
        or before.appearance_status != after.appearance_status
        or before.appearance_error != after.appearance_error
    )


def _tick():
    if _runtime is None or _shutting_down:
        return None
    _tag_redraw(())
    observed = []
    manager = bpy.context.window_manager
    windows = () if manager is None else tuple(manager.windows)
    areas = {editor.key(window, area): (window, area)
             for window in windows if window.screen is not None
             for area in window.screen.areas if area.type == "NODE_EDITOR"}
    for key, preferences in tuple(_editors.items()):
        area_context = areas.get(key)
        if area_context is None:
            _close(key)
            continue
        window, area = area_context
        region = next(iter(editor.view_regions(area)), None)
        node = editor.selected(area.spaces.active)
        if node is not None and region is not None and editor.layout(area, region, preferences):
            previous = _readout(key, node, window.scene)
            _observe(key, window, area, region, node)
            observed.append((key, window, area, node, previous))
        elif _runtime.has_editor(key):
            _release(key)
            area.tag_redraw()
    live_windows = {window.as_pointer() for window in windows}
    for key in _last_view.keys() - live_windows:
        del _last_view[key]
    _interaction.reconcile_windows(live_windows)
    active = _runtime.poll()
    for key, window, area, node, previous in observed:
        current = _readout(key, node, window.scene)
        if _display_changed(previous, current):
            area.tag_redraw()
    return _INTERVAL if _editors or active else None


def _ensure_timer():
    if not bpy.app.background and not bpy.app.timers.is_registered(_tick):
        bpy.app.timers.register(_tick, first_interval=0.0, persistent=True)


def _draw():
    context = bpy.context
    region = context.region
    if (_shutting_down or not editor.is_node_editor(context)
            or region is None or region.type != "WINDOW"):
        return
    key = editor.key(context.window, context.area)
    preferences = _editors.get(key)
    node = editor.selected(context.space_data)
    if preferences is None or node is None:
        return
    box = editor.layout(context.area, region, preferences)
    if box is None:
        return
    state = _readout(key, node, context.scene)
    callbacks = _interaction.callbacks
    linear = callbacks.linear_settings(node)
    tone = callbacks.tone_settings(node) if preferences.stage == "TONE" else None
    display.draw(region, box, state, key, preferences.stage, linear, tone,
                 preferences.tone_anchor)
    if (_runtime.timing is not None and state is not None
            and state.status == "current" and state.rgba is not None):
        _runtime.record_draw(key, state.rgba)


def pointer_event(window, event):
    return (not _shutting_down and _interaction is not None
            and _interaction.pointer_event(window, event))


def frame_change_pre(scene):
    if _runtime is not None and not _shutting_down:
        scene_pointer = scene.as_pointer()
        _interaction.frame_change_pre(scene_pointer)
        _tag_redraw(_runtime.frame_changed(scene_pointer))


def _tag_redraw(affected):
    affected = set(affected or ())
    if threading.current_thread() is not threading.main_thread():
        with _redraw_lock:
            _pending_redraws.update(affected)
        return
    with _redraw_lock:
        affected.update(_pending_redraws)
        _pending_redraws.clear()
    if not affected:
        return
    manager = bpy.context.window_manager
    if manager is None:
        return
    for window in manager.windows:
        if window.screen is not None:
            for area in window.screen.areas:
                if editor.key(window, area) in affected:
                    area.tag_redraw()


def invalidate(scene, changed_ids):
    if _runtime is not None and not _shutting_down:
        _tag_redraw(_runtime.invalidate(scene, changed_ids))


def linear_changed(owner):
    if _runtime is not None and not _shutting_down:
        _tag_redraw(_runtime.linear_changed(owner))


def tone_changed(owner):
    if _runtime is not None and not _shutting_down:
        _tag_redraw(_runtime.tone_changed(owner))


def appearance_changed(owner):
    if _runtime is not None and not _shutting_down:
        _tag_redraw(_runtime.appearance_changed(owner))


def _clear_ui(*, preserve_preferences=False):
    if _interaction is not None:
        _interaction.reset()
    if not preserve_preferences:
        _editors.clear()
    _last_view.clear()
    display.reset()
    with _redraw_lock:
        _pending_redraws.clear()


def reset(*, preserve_preferences=False):
    if _shutting_down:
        return
    _clear_ui(preserve_preferences=preserve_preferences)
    if _runtime is not None:
        _runtime.reset()


def register(create_runtime, *, begin, edit, finish, cancel,
             linear_settings, tone_settings, peak_menu):
    global _runtime, _interaction, _draw_handle, _shutting_down
    if _runtime is None:
        _runtime = create_runtime()
        callbacks = GestureCallbacks(begin, edit, finish, cancel, linear_settings,
                                     tone_settings, peak_menu)
        _interaction = Interaction(_runtime, callbacks, _editors, _close, _change_stage, _observe)
    _shutting_down = False
    if not PG_OT_toggle_vectorscope.is_registered:
        bpy.utils.register_class(PG_OT_toggle_vectorscope)
    if not bpy.app.background and _draw_handle is None:
        _draw_handle = bpy.types.SpaceNodeEditor.draw_handler_add(
            _draw, (), "WINDOW", "POST_PIXEL")


def begin_shutdown():
    global _shutting_down
    if not _shutting_down:
        _shutting_down = True
        _clear_ui()
    if _runtime is not None:
        _runtime.begin_shutdown()


def finish_shutdown():
    global _runtime
    if _runtime is not None:
        _runtime.finish_shutdown()
        _runtime = None


def unregister():
    global _interaction, _draw_handle
    if _runtime is not None:
        begin_shutdown()
        finish_shutdown()
    if bpy.app.timers.is_registered(_tick):
        bpy.app.timers.unregister(_tick)
    if _draw_handle is not None:
        bpy.types.SpaceNodeEditor.draw_handler_remove(_draw_handle, "WINDOW")
        _draw_handle = None
    if PG_OT_toggle_vectorscope.is_registered:
        bpy.utils.unregister_class(PG_OT_toggle_vectorscope)
    _interaction = None
    display.close()
