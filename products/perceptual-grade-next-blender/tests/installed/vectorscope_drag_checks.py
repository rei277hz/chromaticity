"""Exercise the installed vectorscope using the window's native event queue."""

from collections import deque
from dataclasses import replace
import time

import bpy
import numpy as np


def encoded_rgb(color, exposure=0.0):
    linear = np.asarray(color[:3]) * 2.0 ** exposure
    magnitude = np.abs(linear)
    return np.sign(linear) * np.where(
        magnitude < 0.018, 4.5 * magnitude, 1.099 * magnitude ** 0.45 - 0.099,
    )


def chroma_bin(code):
    luma = np.dot(code, (0.2126, 0.7152, 0.0722))
    cr, cb = (code[0] - luma) / 1.5748, (code[2] - luma) / 1.8556
    return tuple(int((value + 0.65) * 144 / 1.3) for value in (cr, cb))


def complete_trace(display):
    trace = display.rgba
    assert trace.shape == (144, 144, 4) and trace.dtype == np.float32
    assert not trace.flags.writeable
    assert np.isfinite(trace).all() and np.all((0 <= trace) & (trace <= 1))
    assert np.shares_memory(display.brightness, trace)
    np.testing.assert_array_equal(display.brightness, trace[..., 3])
    return trace


def assert_solid_trace(display, color, exposure=0.0, *, tolerance=1e-3):
    trace = complete_trace(display)
    peak = np.unravel_index(np.argmax(display.brightness), display.brightness.shape)
    assert np.count_nonzero(display.brightness) > 1, "Expected a smoothed trace"
    np.testing.assert_allclose(trace[peak][:3], np.clip(encoded_rgb(color, exposure), 0, 1),
                               rtol=0, atol=tolerance)
    assert 0 < display.brightness[peak] < 1
    return trace


def select(tree, grade):
    tree.nodes.active = grade
    for node in tree.nodes:
        node.select = node == grade


def keyframes(tree):
    animation = tree.animation_data
    if animation is None or animation.action is None:
        return {}
    return {
        curve.data_path: tuple((point.co.x, point.co.y) for point in curve.keyframe_points)
        for layer in animation.action.layers for strip in layer.strips
        if (bag := strip.channelbag(animation.action_slot)) is not None
        for curve in bag.fcurves
    }


class ScopePointer:
    _MOVES = {"MOUSEMOVE", "INBETWEEN_MOUSEMOVE"}
    _EVENTS = _MOVES | {"LEFTMOUSE", "RIGHTMOUSE", "ESC", "WINDOW_DEACTIVATE"}

    def __init__(self, nodes, ui):
        self.nodes, self.ui = nodes, ui
        self.window = None
        self.trace = deque(maxlen=64)
        self._injected = None
        self._acknowledged = None
        self._started = time.monotonic()
        router_cls = nodes.PG_OT_gesture_router
        modal, press_plot, cancel_drag = router_cls.modal, ui._press_plot, ui._cancel_drag
        self._originals = [
            (router_cls, "modal", modal),
            (ui, "_press_plot", press_plot),
            (ui, "_cancel_drag", cancel_drag),
        ]

        def trace_modal(router, context, event):
            if (self.window is None or router.window_key != self.window.as_pointer()
                    or event.type not in self._EVENTS):
                return modal(router, context, event)
            before = ui._DRAGS.get(router.window_key)
            area, region = context.area, context.region
            entry = self._record(
                "router", type=event.type, value=event.value, xy=(event.mouse_x, event.mouse_y),
                window=router.window_key,
                area=None if area is None else (area.type, area.as_pointer()),
                region=None if region is None else region.type,
                observer=router.token,
                admission=nodes.gesture_policy.observer_status(
                    nodes._gesture_state, router.window_key, router.token),
            )
            injected = self._injected
            matches = (injected is not None and event.value == injected["value"]
                       and (event.type == injected["type"]
                            or injected["type"] == "MOUSEMOVE" and event.type in self._MOVES))
            if matches and self._acknowledged is None:
                injected["received_xy"] = entry["xy"]
                if entry["xy"] == injected["xy"]:
                    injected["admission"] = entry["admission"]
            result = modal(router, context, event)
            after = ui._DRAGS.get(router.window_key)
            entry["result"] = sorted(result)
            if after is not before:
                if after is not None:
                    entry["created_drag"] = after.mode
                if before is not None:
                    entry["removed_drag"] = before.mode
            # Keep the receipt for the current injection even if the trace rolls over.
            if (matches and self._acknowledged is None and entry["xy"] == injected["xy"]
                    and entry["admission"] == "current"):
                self._acknowledged = entry
            return result

        def trace_press_plot(window, event):
            result = press_plot(window, event)
            if window == self.window:
                key = ui._key(window, self.area)
                tree = getattr(self.area.spaces.active, "edit_tree", None)
                active = None if tree is None else tree.nodes.active
                region = next(iter(ui._view_regions(self.area)), None)
                enabled = key in ui._ENABLED
                box = None
                if not result and enabled and region is not None:
                    box = ui._gizmo_layout(self.area, region, key)
                drag = ui._DRAGS.get(key[0])
                injected = self._injected
                if (injected is not None and injected["type"] == event.type
                        and injected["value"] == event.value
                        and injected["xy"] == (event.mouse_x, event.mouse_y)):
                    injected["hit"] = result
                self._record(
                    "hit_test", hit=result, xy=(event.mouse_x, event.mouse_y),
                    enabled=enabled, stage=ui._stage(key),
                    fixture_active_node=None if active is None else active.name,
                    fixture_active_node_selected=None if active is None else active.select,
                    local_xy=(event.mouse_x - region.x, event.mouse_y - region.y)
                    if region is not None else None,
                    region=None if region is None else (region.x, region.y, region.width, region.height),
                    gizmo_rect=None if box is None else box["rect"],
                    control=None if drag is None else drag.mode,
                    hit_area=None if drag is None else drag.key[1],
                )
            return result

        def trace_cancel_drag(window_key, *, before_frame_change=False):
            if self.window is not None and window_key == self.window.as_pointer():
                drag = ui._DRAGS.get(window_key)
                if drag is not None:
                    self._record("cancel_drag", control=drag.mode, token=drag.token,
                                 before_frame_change=before_frame_change)
            return cancel_drag(window_key, before_frame_change=before_frame_change)

        # Blender captures the Python callback when the operator is registered.
        router_cls.modal = trace_modal
        ui._press_plot = trace_press_plot
        ui._cancel_drag = trace_cancel_drag

    def bind(self, window, area, region):
        self.window, self.area, self.region = window, area, region

    def close(self):
        self.window = None
        for owner, name, original in self._originals:
            setattr(owner, name, original)
        self._originals.clear()

    def diagnostics(self):
        return {
            "events": list(self.trace),
            "last_injection": None if self._injected is None else dict(self._injected),
            "last_receipt": None if self._acknowledged is None else dict(self._acknowledged),
        }

    def _record(self, step, **details):
        entry = {"step": step, "seconds": time.monotonic() - self._started, **details}
        self.trace.append(entry)
        return entry

    def event(self, kind, value, delta=(0, 0)):
        x, y, side = self.ui._plot_rect(self.area, self.region)
        self.event_at(kind, value, (x + side / 2 + delta[0], y + side / 2 + delta[1]))

    def event_at(self, kind, value, point):
        x = self.region.x + round(point[0])
        y = self.region.y + round(point[1])
        injected = self._record("inject", type=kind, value=value, xy=(x, y),
                                area=self.area.as_pointer(), local_xy=point)
        self._injected = injected
        self._acknowledged = None
        self.window.event_simulate(type=kind, value=value, x=x, y=y)
        return injected

    def _delivery_failure(self, injected):
        event = "press" if injected["type"] == "LEFTMOUSE" else "move"
        if "received_xy" not in injected:
            return f"Gizmo router did not receive {event}"
        if "admission" not in injected:
            return f"Gizmo router received {event} at different coordinates"
        if injected["admission"] != "current":
            return f"Gizmo router rejected {event} at observer admission"
        if self._acknowledged is not None and "created_drag" in self._acknowledged:
            return "Gizmo drag was created and lost before polling"
        if injected.get("hit") is False:
            return "Gizmo hit test rejected press"
        if self._acknowledged is None:
            return f"Gizmo router did not finish handling {event}"
        return "Gizmo router handled press without creating a drag"

    def control_point(self, control, node):
        with bpy.context.temp_override(window=self.window, area=self.area, region=self.region):
            box = self.ui._gizmo_layout(self.area, self.region)
        assert box is not None
        if control in ("cr", "yb"):
            linear = self.settings(node).linear
            return self.ui.geometry.handle_positions(box["scope"], linear, box["scale"])[control]
        if control == "curve":
            tone = self.ui._tone_model(self.settings(node).tone)
            return self.ui._curve_point(box["curve"], tone.source[-1], tone.target[-1])
        x, y, width, height = box[control]
        return x + width / 2, y + height / 2

    def press_at(self, point, control=None, node=None):
        window_key = self.window.as_pointer()
        self._record("prepare_press", control=control, node=None if node is None else node.name,
                     window=window_key, area=self.area.as_pointer(), local_xy=point)
        deadline = time.monotonic() + 5
        while self.nodes._gesture_observer_token(window_key) is None:
            assert time.monotonic() < deadline, "The window gesture router did not register"
            yield .05
        move = self.event_at("MOUSEMOVE", "NOTHING", point)
        deadline = time.monotonic() + 5
        while self._acknowledged is None:
            assert time.monotonic() < deadline, (
                self._delivery_failure(move), control, move["xy"])
            yield .05
        press = self.event_at("LEFTMOUSE", "PRESS", point)
        deadline = time.monotonic() + 5
        while ((drag := self.ui._DRAGS.get(window_key)) is None
               or self._acknowledged is None or "created_drag" not in self._acknowledged):
            assert time.monotonic() < deadline, (self._delivery_failure(press), control, press["xy"])
            yield .05
        if control is not None:
            assert drag.mode == control, ("Gizmo pressed a different control", control, drag.mode)

    def click_control(self, control, node):
        point = self.control_point(control, node)
        yield from self.press_at(point, control, node)
        self.event_at("LEFTMOUSE", "RELEASE", point)
        yield .05

    def drag_control(self, control, node, delta, *, cancel=False):
        start = self.control_point(control, node)
        end = tuple(value + change for value, change in zip(start, delta))
        before = self.settings(node)
        window_key = self.window.as_pointer()
        yield from self.press_at(start, control, node)
        self.event_at("MOUSEMOVE", "NOTHING", end)
        deadline = time.monotonic() + 5
        while self.nodes._gesture_token(window_key) is None:
            assert time.monotonic() < deadline, ("Gizmo control did not begin", control)
            yield .05
        after = self.settings(node)
        assert before != after, ("Gizmo control did not edit settings", control)
        if cancel:
            self.event_at("ESC", "PRESS", end)
            self.event_at("ESC", "RELEASE", end)
        self.event_at("LEFTMOUSE", "RELEASE", end)
        yield .05
        while self.nodes._gesture_token(window_key) is not None:
            assert time.monotonic() < deadline, ("Gizmo control did not finish", control)
            yield .05
        assert self.settings(node) == (before if cancel else after), control
        return after

    def settings(self, node):
        grade = getattr(node, "pg_grade", None)
        owner = grade if grade is not None else node
        return self.nodes._raw_grade_settings(owner, self.nodes._working_space())

    def peak(self):
        with bpy.context.temp_override(window=self.window, area=self.area, region=self.region):
            scope = self.ui.display_state(bpy.context)
        if scope is None or scope.status != "current" or scope.brightness is None:
            return None
        pixels = scope.brightness
        if not np.any(pixels > 0):
            return None
        cr, cb = np.unravel_index(np.argmax(pixels), pixels.shape)
        return int(cb), int(cr)

    def press(self):
        x, y, side = self.ui._plot_rect(self.area, self.region)
        yield from self.press_at((x + side / 2, y + side / 2))

    def inert_drag(self, delta=(0, 0)):
        yield from self.press()
        if delta != (0, 0):
            self.event("MOUSEMOVE", "NOTHING", delta)
            yield .05
        self.event("LEFTMOUSE", "RELEASE", delta)
        yield .05

    def drag(self, node, delta, *, cancel=None):
        before = self.settings(node)
        start = self.peak()
        assert start is not None
        yield from self.press()
        self.event("MOUSEMOVE", "NOTHING", delta)
        deadline = time.monotonic() + 20.0
        while True:
            peak = self.peak()
            if (peak is not None and all(
                    d == 0 or (end - initial) * d > 0
                    for initial, end, d in zip(start, peak, delta))):
                break
            assert time.monotonic() < deadline, (node.name, "trace direction", start, peak,
                                                  delta, before.linear,
                                                  self.settings(node).linear)
            yield .05
        assert self.nodes._gesture_token(self.window.as_pointer()) is not None, (
            "A vectorscope pointer drag did not activate the native Grade gesture"
        )
        edited = self.settings(node)
        assert edited.linear.source_xy != before.linear.source_xy
        assert edited == replace(before, linear=replace(
            before.linear, source_xy=edited.linear.source_xy)), "Drag edited unrelated Grade fields"
        if callable(cancel):
            cancel()
            yield .1
        elif cancel is not None:
            self.event(cancel, "PRESS", delta)
            self.event(cancel, "RELEASE", delta)
        self.event("LEFTMOUSE", "RELEASE", delta)
        deadline = time.monotonic() + 5
        yield .05
        while self.nodes._gesture_token(self.window.as_pointer()) is not None:
            assert time.monotonic() < deadline, "Vectorscope did not finish its gesture"
            yield .05
        expected = edited if cancel is None else before
        assert self.settings(node) == expected, (cancel, expected, self.settings(node))
        return edited.linear.source_xy
