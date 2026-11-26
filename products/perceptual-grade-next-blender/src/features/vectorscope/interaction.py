"""Pointer ownership, cursor feedback, and Grade control gestures."""

from collections.abc import Callable
from dataclasses import dataclass, replace
import math
import threading
from typing import TYPE_CHECKING

import bpy

from ...kernel.prepare import nits_to_j
from ...kernel.settings import D65, LinearSettings
from ...kernel.tone_ui import TONE_DEFAULTS, TONE_LEVEL_FIELDS, TONE_LIMITS, _j_to_nits
from . import editor, geometry
from .geometry import (
    AXIS_LABELS, SLIDER_RANGES, curve_point, tone_anchor_levels, tone_model, tone_peak_j,
)
from .white_drag import WhiteDrag

if TYPE_CHECKING:
    from .runtime import WhiteDragReceipt


_POINTER_BUTTONS = {"LEFTMOUSE", "MIDDLEMOUSE", "RIGHTMOUSE", "BUTTON4MOUSE",
                    "BUTTON5MOUSE", "BUTTON6MOUSE", "BUTTON7MOUSE", "PEN", "ERASER"}
_POINTER_MOVES = {"MOUSEMOVE", "INBETWEEN_MOUSEMOVE"}


@dataclass(frozen=True)
class GestureCallbacks:
    begin: Callable
    edit: Callable
    finish: Callable
    cancel: Callable
    linear_settings: Callable
    tone_settings: Callable
    peak_menu: Callable


@dataclass(frozen=True)
class _WhiteControl:
    receipt: "WhiteDragReceipt"
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
    panel_position: tuple | None = None
    panel_size: float | tuple | None = None


def _tone_hit(rect, point, model, selected, scale, peak_j):
    sources, targets = tone_anchor_levels(model)
    actual = model.remap(sources * 100.) / 100.
    choices = ((math.dist(point, curve_point(rect, source, target, peak_j)),
                index != selected, index)
               for index, source in enumerate(sources)
               for target in ((targets[index], actual[index])
                              if source <= peak_j and actual[index] <= peak_j
                              else (targets[index],)))
    distance, _, index = min(choices, default=(math.inf, False, None))
    return index if distance <= 7 * scale else None


def _control_cursor(stage, mode):
    if mode in {"close", "linear_tab", "tone_tab", "peak"}:
        return "HAND_POINT"
    if mode in {"header", "scope", "cr", "yb"}:
        return "SCROLL_XY"
    if mode.startswith("resize_"):
        handle = mode.removeprefix("resize_")
        return {"w": "MOVE_X", "e": "MOVE_X", "s": "MOVE_Y", "n": "MOVE_Y"}.get(
            handle, "SCROLL_XY")
    if mode in {"fit", "cr_balance"} or (mode == "exposure" and stage == "LINEAR"):
        return "SCROLL_Y"
    if mode in {"curve", "exposure", "yb_balance"}:
        return "SCROLL_X"
    return None


def _is_pointer_event(event):
    kind = event.type
    return (kind in _POINTER_MOVES or kind in _POINTER_BUTTONS
            or kind.startswith(("WHEEL", "TRACKPAD", "NDOF_")))


class Interaction:
    def __init__(self, runtime, callbacks, editors, close_editor, change_stage, observe):
        self.runtime = runtime
        self.callbacks = callbacks
        self.editors = editors
        self.close_editor = close_editor
        self.change_stage = change_stage
        self.observe = observe
        self.drags = {}
        self.hover_cursors = {}
        self.outside_buttons = {}

    def dragging(self, key):
        drag = self.drags.get(key[0])
        return drag is not None and drag.key == key and drag.token is not None

    def release(self, key):
        drag = self.drags.get(key[0])
        if drag is not None and drag.key == key:
            self._cancel_drag(key[0])
        self._restore_hover_cursor(key[0])

    def reconcile_windows(self, windows):
        for window_key in self.outside_buttons.keys() - windows:
            del self.outside_buttons[window_key]

    def reset(self):
        for window_key in tuple(self.drags):
            self._cancel_drag(window_key)
        for window_key in tuple(self.hover_cursors):
            self._restore_hover_cursor(window_key)
        self.outside_buttons.clear()

    def reconcile(self, key, window, node):
        drag = self.drags.get(key[0])
        if drag is not None and drag.key == key and not self._drag_is_current(drag, window, node):
            self._cancel_drag(key[0])

    def _restore_hover_cursor(self, window_key):
        previous = self.hover_cursors.pop(window_key, None)
        if previous is None:
            return
        window = previous[0]
        try:
            window.cursor_modal_restore()
        except (AttributeError, ReferenceError, RuntimeError):
            pass

    def _set_hover_cursor(self, window, cursor=None):
        if window is None:
            return
        try:
            window_key = int(window.as_pointer())
            previous = self.hover_cursors.get(window_key)
            if previous is not None and previous[1] == cursor:
                return
            if previous is not None:
                self._restore_hover_cursor(window_key)
            if cursor is not None:
                window.cursor_modal_set(cursor)
                self.hover_cursors[window_key] = (window, cursor)
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            pass

    def _cancel_drag(self, window_key, *, before_frame_change=False):
        drag = self.drags.pop(window_key, None)
        if drag is None:
            return
        self._restore_hover_cursor(window_key)
        manager = bpy.context.window_manager
        window = None if manager is None else next(
            (item for item in manager.windows if item.as_pointer() == window_key), None)
        if drag.panel_position is not None:
            self.editors[drag.key].position = drag.panel_position
            if drag.mode.startswith("resize_"):
                preferences = self.editors[drag.key]
                if drag.panel_size is None:
                    preferences.sizes.pop(preferences.stage, None)
                else:
                    preferences.sizes[preferences.stage] = drag.panel_size
            if window is not None and window.screen is not None:
                area = next((item for item in window.screen.areas
                             if item.as_pointer() == drag.key[1]), None)
                if area is not None:
                    area.tag_redraw()
        if drag.token is None:
            return
        restore = window is None or (editor.frame_key(window.scene) == drag.frame)
        if before_frame_change and window is not None:
            restore = window.scene.as_pointer() == drag.frame[0]
        self.callbacks.cancel(window_key, drag.token, restore)

    def _drag_is_current(self, drag, window, node):
        return (node is not None and editor.binding(node) == drag.binding
                and editor.frame_key(window.scene) == drag.frame
                and (drag.white is None
                     or self.runtime.white_drag_current(
                         drag.white.receipt, node, frame=drag.frame,
                         stage=self.editors[drag.key].stage)))

    def frame_change_pre(self, scene_pointer):
        """Cancel same-scene drags before animation evaluates the destination frame."""
        if threading.current_thread() is not threading.main_thread():
            return
        for window_key, drag in tuple(self.drags.items()):
            if drag.frame[0] == scene_pointer:
                self._cancel_drag(window_key, before_frame_change=True)

    def _control_values(self, mode, node, fields):
        if mode in ("fit", "curve"):
            tone = self.callbacks.tone_settings(node)
            return ((tone.fit,) if mode == "fit"
                    else (tone.input_nits[TONE_LEVEL_FIELDS.index(fields[0])],))
        linear = self.callbacks.linear_settings(node)
        if mode == "scope":
            return linear.source_xy
        if mode in AXIS_LABELS:
            index = int(mode == "yb")
            return linear.spread[index], linear.heading[index]
        if mode == "exposure":
            return (linear.exposure,)
        # LinearSettings uses the reference convention, opposite to the RNA controls.
        return (-linear.balance[int(mode == "yb_balance")],)

    def _control_at(self, key, node, box, point):
        for item in ("close", "linear_tab", "tone_tab"):
            if geometry.contains(box[item], point):
                return item, ()
        for handle, rect in box["resize_grips"].items():
            if geometry.contains(rect, point):
                return "resize_" + handle, ()
        if geometry.contains(box["header"], point):
            return "header", ()
        if "curve" in box:
            x, y, w, h = box["curve"]
            # Endpoint markers straddle the plot border and the edge sliders.
            pad = 3 * box["scale"]
            if geometry.contains((x - pad, y - pad, w + 2 * pad, h + 2 * pad), point):
                tone = self.callbacks.tone_settings(node)
                index = _tone_hit(box["curve"], point, tone_model(tone),
                                  self.editors[key].tone_anchor, box["scale"], tone_peak_j(tone))
                if index is not None:
                    return "curve", (TONE_LEVEL_FIELDS[index],)
        for item in SLIDER_RANGES:
            if item in box and geometry.contains(box[item], point):
                return item, (item,)
        if "scope" in box:
            positions = geometry.handle_positions(box["scope"], self.callbacks.linear_settings(node),
                                                  box["scale"])
            distance, axis = min((math.dist(point, pos), axis) for axis, pos in positions.items())
            if distance <= 7 * box["scale"]:
                return axis, (axis + "_spread", axis + "_heading")
            if geometry.contains(box["scope"], point):
                return "scope", ("source_x", "source_y")
        elif geometry.contains(box["peak"], point):
            return "peak", ()
        return "body", ()

    def _white_control(self, key, node, frame):
        inputs = self.runtime.begin_white_drag(key, node, frame=frame)
        if inputs is None:
            return None
        receipt, rgba, linear, space = inputs
        model = WhiteDrag.from_capture(rgba, linear, space)
        return None if model is None else _WhiteControl(receipt, model, linear)

    def _press_control(self, key, node, box, point, origin, frame):
        mode, fields = self._control_at(key, node, box, point)
        white = self._white_control(key, node, frame) if mode == "scope" else None
        if mode == "scope" and white is None:
            mode, fields = "body", ()
        elif mode == "curve":
            self.editors[key].tone_anchor = TONE_LEVEL_FIELDS.index(fields[0])
        if mode == "header":
            values = box["rect"][0] / box["scale"], box["rect"][1] / box["scale"]
        elif white is not None:
            values = white.linear.source_xy
        else:
            values = self._control_values(mode, node, fields) if fields else ()
        rect = box["scope"] if mode in AXIS_LABELS else box.get(mode, box["rect"])
        resizing = mode.startswith("resize_")
        return _Drag(key, editor.binding(node), frame, mode, rect, origin, box["scale"],
                     fields, values, white,
                     panel_position=self.editors[key].position if mode == "header" or resizing else None,
                     panel_size=self.editors[key].sizes.get(self.editors[key].stage) if resizing else None)

    def _plot_at(self, window, mouse):
        for area in window.screen.areas:
            key = editor.key(window, area)
            if key not in self.editors or area.type != "NODE_EDITOR":
                continue
            if not geometry.contains((area.x, area.y, area.width, area.height), mouse):
                continue
            region = next((item for item in editor.view_regions(area)
                           if geometry.contains((item.x, item.y, item.width, item.height), mouse)), None)
            node = editor.selected(area.spaces.active)
            if region is None or node is None:
                continue
            box = editor.layout(area, region, self.editors[key])
            if box is None:
                continue
            point = mouse[0] - region.x, mouse[1] - region.y
            if geometry.contains(box["rect"], point):
                return key, area, region, node, box, point
        return None

    def _press_plot(self, window, event):
        origin = event.mouse_x, event.mouse_y
        hit = self._plot_at(window, origin)
        if hit is None:
            return False
        key, area, region, node, box, point = hit
        with bpy.context.temp_override(window=window, area=area, region=region):
            drag = self._press_control(key, node, box, point, origin, editor.frame_key(window.scene))
        self.drags[key[0]] = drag
        self._set_hover_cursor(window, _control_cursor(self.editors[key].stage, drag.mode))
        area.tag_redraw()
        return True

    def _hover_plot(self, window, mouse):
        hit = self._plot_at(window, mouse)
        if hit is None:
            self._set_hover_cursor(window)
            return False
        key, area, region, node, box, point = hit
        with bpy.context.temp_override(window=window, area=area, region=region):
            mode, _ = self._control_at(key, node, box, point)
        self._set_hover_cursor(window, _control_cursor(self.editors[key].stage, mode))
        return True

    def _drag_values(self, drag, node, mouse):
        dx, dy = mouse[0] - drag.origin[0], mouse[1] - drag.origin[1]
        if drag.white is not None:
            white = drag.white
            return white.model.move(white.linear, dx, dy, drag.rect[2])
        if drag.mode in AXIS_LABELS:
            last = drag.origin if drag.last is None else drag.last
            start = self._control_values(drag.mode, node, drag.fields)
            drag.last = mouse
            return geometry.drag_handle(drag.rect, drag.mode, *start,
                                        mouse[0] - last[0], mouse[1] - last[1])
        if drag.mode == "curve":
            tone = self.callbacks.tone_settings(node)
            reference = tone.reference_nits
            if dx == 0:
                return drag.values
            delta = dx / drag.rect[2]
            level = float(nits_to_j(drag.values[0], reference)) + delta * .1 * tone_peak_j(tone)
            limits = TONE_LIMITS[TONE_LEVEL_FIELDS.index(drag.fields[0])]
            low, high = nits_to_j(limits, reference)
            return (_j_to_nits(float(min(high, max(low, level))), reference),)
        lo, hi = SLIDER_RANGES[drag.mode]
        vertical = (drag.mode in ("cr_balance", "fit")
                    or drag.mode == "exposure" and self.editors[drag.key].stage == "LINEAR")
        delta = dy / drag.rect[3] if vertical else dx / drag.rect[2]
        return (min(hi, max(lo, drag.values[0] + delta * (hi - lo))),)

    def _edit_drag(self, drag, node, values):
        if drag.token is None:
            if values == drag.values:
                return True
            if drag.white is not None:
                unchanged = self.callbacks.linear_settings(node) == drag.white.linear
            else:
                unchanged = self._control_values(drag.mode, node, drag.fields) == drag.values
            if unchanged:
                drag.token = self.callbacks.begin(drag.key[0], node, drag.fields)
            if drag.token is None:
                self._cancel_drag(drag.key[0])
                return False
        if not self.callbacks.edit(drag.key[0], drag.token, node, values):
            self._cancel_drag(drag.key[0])
            return False
        return True

    def _reset_drag(self, drag, node, mouse):
        if drag.mode == "header":
            self.editors[drag.key].position = drag.values = editor.HOME
        else:
            if drag.mode == "curve":
                tone = self.callbacks.tone_settings(node)
                index = TONE_LEVEL_FIELDS.index(drag.fields[0])
                target = tone_anchor_levels(tone_model(tone))[1][index]
                values = (_j_to_nits(float(target), tone.reference_nits),)
            elif drag.mode == "fit":
                values = (TONE_DEFAULTS["fit"],)
            elif drag.white is not None:
                values = D65
            else:
                values = (0.,) * len(drag.fields)
            if not self._edit_drag(drag, node, values):
                return
            drag.values = self._control_values(drag.mode, node, drag.fields)
            if drag.white is not None:
                drag.white = replace(drag.white, linear=self.callbacks.linear_settings(node))
        drag.origin = mouse
        drag.last = None

    def _release_button(self, drag, area, region, click, node):
        if drag.mode not in ("close", "linear_tab", "tone_tab", "peak"):
            return
        point = click[0] - region.x, click[1] - region.y
        if not geometry.contains(drag.rect, point):
            return
        if drag.mode == "close":
            self.close_editor(drag.key)
        elif drag.mode == "peak":
            self.callbacks.peak_menu(bpy.context, node)
        else:
            self.change_stage(drag.key, "LINEAR" if drag.mode == "linear_tab" else "TONE")
        area.tag_redraw()

    def _drag_event(self, window, event, drag):
        window_key = window.as_pointer()
        if event.type in {"ESC", "RIGHTMOUSE"} and event.value == "PRESS":
            self._cancel_drag(window_key)
            return True
        moving = event.type in _POINTER_MOVES
        releasing = event.type == "LEFTMOUSE" and event.value == "RELEASE"
        resetting = (event.type == "R" and (drag.fields or drag.mode == "header"))
        if resetting and (event.value != "PRESS" or getattr(event, "is_repeat", False)):
            return True
        if not (moving or releasing or resetting):
            return True
        mouse = event.mouse_x, event.mouse_y
        area = next((area for area in window.screen.areas
                     if area.as_pointer() == drag.key[1] and area.type == "NODE_EDITOR"), None)
        region = None if area is None else next(iter(editor.view_regions(area)), None)
        node = None if area is None else editor.selected(area.spaces.active)
        box = None if region is None else editor.layout(area, region, self.editors[drag.key])
        if node is None or box is None:
            self._cancel_drag(window_key)
            return True
        with bpy.context.temp_override(window=window, area=area, region=region):
            if drag.white is not None and (releasing or resetting or drag.token is None):
                # A link or viewport change can precede the next timer observation.
                self.observe(drag.key, window, area, region, node)
            if (self.drags.get(window_key) is not drag
                    or not self._drag_is_current(drag, window, node)):
                self._cancel_drag(window_key)
                return True
            if resetting:
                self._reset_drag(drag, node, mouse)
                area.tag_redraw()
            elif drag.mode == "header":
                self.editors[drag.key].position = tuple(
                    value + (end - start) / drag.scale
                    for value, end, start in zip(drag.values, mouse, drag.origin)
                )
                area.tag_redraw()
            elif drag.mode.startswith("resize_"):
                preferences = self.editors[drag.key]
                position, size = geometry.resize(
                    preferences.stage, drag.rect, box["bounds"], drag.mode.removeprefix("resize_"),
                    mouse[0] - drag.origin[0], mouse[1] - drag.origin[1], drag.scale,
                )
                preferences.position = position
                preferences.sizes[preferences.stage] = size
                area.tag_redraw()
            elif drag.fields and (drag.token is not None or math.dist(mouse, drag.origin) >= 3 * drag.scale):
                self._edit_drag(drag, node, self._drag_values(drag, node, mouse))
            if releasing and self.drags.pop(window_key, None) is drag:
                if drag.token is not None:
                    self.callbacks.finish(window_key, drag.token, node)
                else:
                    self._release_button(drag, area, region, mouse, node)
                self._hover_plot(window, mouse)
        return True

    def pointer_event(self, window, event):
        """Own pointer input over the overlay and update hover cursors."""
        if (window is None or window.screen is None
                or not callable(getattr(window, "as_pointer", None))):
            return False
        window_key = window.as_pointer()
        drag = self.drags.get(window_key)
        if event.type == "WINDOW_DEACTIVATE":
            self._cancel_drag(window_key)
            self._restore_hover_cursor(window_key)
            self.outside_buttons.pop(window_key, None)
            return False
        if drag is not None:
            return ((_is_pointer_event(event) or event.type in {"R", "ESC"})
                    and self._drag_event(window, event, drag))
        if not self.editors:
            self._restore_hover_cursor(window_key)
            return False
        if not _is_pointer_event(event):
            return False
        # Recover when Blender swallowed a native release before this router.
        if event.type in _POINTER_BUTTONS and event.value == "PRESS":
            self.outside_buttons.pop(window_key, None)
        outside = self.outside_buttons.get(window_key)
        if outside is not None:
            if event.type == outside and event.value == "RELEASE":
                self.outside_buttons.pop(window_key, None)
            return False
        mouse = event.mouse_x, event.mouse_y
        if event.type == "LEFTMOUSE" and event.value == "PRESS":
            if self._press_plot(window, event):
                return True
        elif self._hover_plot(window, mouse):
            return True
        self._restore_hover_cursor(window_key)
        if event.type in _POINTER_BUTTONS and event.value == "PRESS":
            self.outside_buttons[window_key] = event.type
        return False
