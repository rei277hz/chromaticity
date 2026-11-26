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


def scope_tint(code):
    clipped = np.clip(code, 0.0, 1.0)
    peak = clipped.max()
    return clipped / peak if peak > 0 else np.ones(3)


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


def complete_tone_histogram(display):
    histogram = display.tone_histogram
    assert display.rgba is None
    assert histogram.shape == (128,) and histogram.dtype == np.float32
    assert not histogram.flags.writeable
    assert np.isfinite(histogram).all() and np.all(histogram >= 0) and histogram.any()
    return histogram


def assert_solid_trace(display, color, exposure=0.0, *, tolerance=1e-3):
    trace = complete_trace(display)
    peak = np.unravel_index(np.argmax(display.brightness), display.brightness.shape)
    assert np.count_nonzero(display.brightness) > 1, "Expected a smoothed trace"
    np.testing.assert_allclose(trace[peak][:3], scope_tint(encoded_rgb(color, exposure)),
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
    _EVENTS = _MOVES | {"LEFTMOUSE", "RIGHTMOUSE", "ESC", "R", "WINDOW_DEACTIVATE"}
    _HOVER_ATTEMPTS = 3
    _HOVER_RETRY_INTERVAL = 0.25
    _HOVER_OFFSET = 8

    def __init__(self, nodes, ui):
        self.nodes, self.ui = nodes, ui
        self.window = None
        self.trace = deque(maxlen=64)
        self._injected = None
        self._acknowledged = None
        self._started = time.monotonic()
        router_cls = nodes.PG_OT_gesture_router
        interaction_cls = ui.Interaction
        modal = router_cls.modal
        press_plot = interaction_cls._press_plot
        cancel_drag = interaction_cls._cancel_drag
        self._originals = [
            (router_cls, "modal", modal),
            (interaction_cls, "_press_plot", press_plot),
            (interaction_cls, "_cancel_drag", cancel_drag),
        ]

        def trace_modal(router, context, event):
            if (self.window is None or router.window_key != self.window.as_pointer()
                    or event.type not in self._EVENTS):
                return modal(router, context, event)
            before = ui._interaction.drags.get(router.window_key)
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
            if matches and injected.get("phase") is not None:
                entry["phase"] = injected["phase"]
                entry["attempt"] = injected["attempt"]
            if matches and self._acknowledged is None:
                injected["received_xy"] = entry["xy"]
                if entry["xy"] == injected["xy"]:
                    injected["admission"] = entry["admission"]
            result = modal(router, context, event)
            after = ui._interaction.drags.get(router.window_key)
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

        def trace_press_plot(interaction, window, event):
            result = press_plot(interaction, window, event)
            if window == self.window:
                key = ui.editor.key(window, self.area)
                tree = getattr(self.area.spaces.active, "edit_tree", None)
                active = None if tree is None else tree.nodes.active
                region = next(iter(ui.editor.view_regions(self.area)), None)
                preferences = ui._editors.get(key)
                box = None
                if not result and preferences is not None and region is not None:
                    box = ui.editor.layout(self.area, region, preferences)
                drag = interaction.drags.get(key[0])
                injected = self._injected
                if (injected is not None and injected["type"] == event.type
                        and injected["value"] == event.value
                        and injected["xy"] == (event.mouse_x, event.mouse_y)):
                    injected["hit"] = result
                self._record(
                    "hit_test", hit=result, xy=(event.mouse_x, event.mouse_y),
                    enabled=preferences is not None,
                    stage=None if preferences is None else preferences.stage,
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

        def trace_cancel_drag(interaction, window_key, *, before_frame_change=False):
            if self.window is not None and window_key == self.window.as_pointer():
                drag = interaction.drags.get(window_key)
                if drag is not None:
                    self._record("cancel_drag", control=drag.mode, token=drag.token,
                                 before_frame_change=before_frame_change)
            return cancel_drag(interaction, window_key, before_frame_change=before_frame_change)

        # Blender captures the Python callback when the operator is registered.
        router_cls.modal = trace_modal
        interaction_cls._press_plot = trace_press_plot
        interaction_cls._cancel_drag = trace_cancel_drag

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
        x, y, side = self.plot_rect()
        self.event_at(kind, value, (x + side / 2 + delta[0], y + side / 2 + delta[1]))

    def event_at(self, kind, value, point, *, phase=None, attempt=None):
        x = self.region.x + round(point[0])
        y = self.region.y + round(point[1])
        details = {
            "type": kind,
            "value": value,
            "xy": (x, y),
            "area": self.area.as_pointer(),
            "local_xy": point,
        }
        if attempt is not None:
            details["phase"] = phase
            details["attempt"] = attempt
        injected = self._record("inject", **details)
        self._injected = injected
        self._acknowledged = None
        self._simulate_event(kind, value, x, y)
        return injected

    def reset_drag_at(self, point):
        for value in ("PRESS", "RELEASE"):
            injected = self.event_at("R", value, point)
            deadline = time.monotonic() + 5
            while self._acknowledged is None:
                assert time.monotonic() < deadline, (
                    "Gizmo router did not acknowledge R " + value, self.diagnostics(),
                )
                yield .05
            receipt = self._acknowledged
            assert self._injected is injected and receipt["xy"] == injected["xy"], (
                "Gizmo router acknowledged a different R event", injected, receipt,
            )
            assert "RUNNING_MODAL" in receipt["result"], (
                "R was not consumed by the active Gizmo drag", receipt,
            )

    def _simulate_event(self, kind, value, x, y):
        self.window.event_simulate(type=kind, value=value, x=x, y=y)

    def _hover_away_point(self, point):
        x, y = map(round, point)
        away_x = x + self._HOVER_OFFSET
        if away_x >= self.region.width:
            away_x = x - self._HOVER_OFFSET
        assert 0 <= away_x < self.region.width and 0 <= y < self.region.height, point
        return away_x, y

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

    def box(self):
        editor = self.ui.editor
        preferences = self.ui._editors[editor.key(self.window, self.area)]
        box = editor.layout(self.area, self.region, preferences)
        assert box is not None
        return box

    def plot_rect(self):
        return tuple(map(round, self.box()["scope"][:3]))

    def control_point(self, control, node):
        box = self.box()
        geometry = self.ui.editor.geometry
        if control in ("cr", "yb"):
            linear = self.settings(node).linear
            return geometry.handle_positions(box["scope"], linear, box["scale"])[control]
        if control.startswith("resize_"):
            x, y, width, height = box["resize_grips"][control.removeprefix("resize_")]
            return x + width / 2, y + height / 2
        if control == "curve":
            settings = self.settings(node).tone
            tone = geometry.tone_model(settings)
            return geometry.curve_point(
                box["curve"], tone.source[-1], tone.target[-1],
                geometry.tone_peak_j(settings),
            )
        if control == "saturation_crossover":
            settings = self.settings(node).tone
            return geometry.saturation_crossover_point(
                box["appearance"], settings.saturation_crossover,
            )
        if control == "tone_crossover":
            settings = self.settings(node).tone
            point, _pinned = geometry.tone_crossover_point(
                box["appearance"], geometry.tone_model(settings),
                geometry.tone_peak_j(settings), settings.tone_crossover,
            )
            return point
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
        away = self._hover_away_point(point)
        target_moves = []
        delivery_deadline = time.monotonic() + 5
        for attempt in range(1, self._HOVER_ATTEMPTS + 1):
            if time.monotonic() >= delivery_deadline:
                break
            # Let Blender process the away move before queuing the target.
            self.event_at("MOUSEMOVE", "NOTHING", away,
                          phase="away", attempt=attempt)
            yield .05
            if time.monotonic() >= delivery_deadline:
                break
            move = self.event_at("MOUSEMOVE", "NOTHING", point,
                                 phase="target", attempt=attempt)
            target_moves.append(move)
            attempt_deadline = delivery_deadline
            if attempt < self._HOVER_ATTEMPTS:
                attempt_deadline = min(attempt_deadline,
                                       time.monotonic() + self._HOVER_RETRY_INTERVAL)
            while self._acknowledged is None and time.monotonic() < attempt_deadline:
                yield .05
            if self._acknowledged is not None:
                break
        assert target_moves, ("Gizmo hover expired before target move", control, point)
        move = target_moves[-1]
        assert self._injected is move and self._acknowledged is not None, (
            self._delivery_failure(move), control, move["xy"], target_moves)
        press = self.event_at("LEFTMOUSE", "PRESS", point)
        deadline = time.monotonic() + 5
        while ((drag := self.ui._interaction.drags.get(window_key)) is None
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

    def hover_control(self, control, node):
        point = self.control_point(control, node)
        injected = self.event_at("MOUSEMOVE", "NOTHING", point)
        deadline = time.monotonic() + 5
        while self._acknowledged is None:
            assert time.monotonic() < deadline, ("Gizmo hover was not acknowledged", control)
            yield .05
        assert self._injected is injected and "RUNNING_MODAL" in self._acknowledged["result"], (
            "Gizmo did not own its hovered handle", control, self._acknowledged,
        )
        window_key = self.window.as_pointer()
        assert self.ui._interaction.hover_cursors[window_key][1] == "SCROLL_XY"
        box = self.box()
        outside = (box["rect"][0] - 15, box["rect"][1] + box["rect"][3] / 2)
        injected = self.event_at("MOUSEMOVE", "NOTHING", outside)
        deadline = time.monotonic() + 5
        while self._acknowledged is None:
            assert time.monotonic() < deadline, "Gizmo did not restore the pointer outside its panel"
            yield .05
        assert self._injected is injected and window_key not in self.ui._interaction.hover_cursors

    def resize_control(self, control, node, delta):
        key = self.ui.editor.key(self.window, self.area)
        preferences = self.ui._editors[key]
        initial = preferences.sizes.get(preferences.stage)
        point = self.control_point(control, node)
        yield from self.press_at(point, control, node)
        self.event_at("MOUSEMOVE", "NOTHING",
                      tuple(value + change for value, change in zip(point, delta)))
        deadline = time.monotonic() + 5
        while preferences.sizes.get(preferences.stage) == initial:
            assert time.monotonic() < deadline, ("Gizmo resize did not change size", control)
            yield .05
        self.event_at("LEFTMOUSE", "RELEASE",
                      tuple(value + change for value, change in zip(point, delta)))
        yield .05
        return preferences.sizes[preferences.stage]

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
        x, y, side = self.plot_rect()
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
