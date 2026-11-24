"""Exercise the installed vectorscope using the window's native event queue."""

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
    def __init__(self, nodes, ui, window, area, region):
        self.nodes, self.ui = nodes, ui
        self.window, self.area, self.region = window, area, region

    def event(self, kind, value, delta=(0, 0)):
        x, y, side = self.ui._plot_rect(self.area, self.region)
        self.event_at(kind, value, (x + side / 2 + delta[0], y + side / 2 + delta[1]))

    def event_at(self, kind, value, point):
        self.window.event_simulate(
            type=kind, value=value,
            x=self.region.x + round(point[0]),
            y=self.region.y + round(point[1]),
        )

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

    def press_at(self, point, control=None):
        window_key = self.window.as_pointer()
        deadline = time.monotonic() + 5
        while self.nodes._gesture_observer_token(window_key) is None:
            assert time.monotonic() < deadline, "The window gesture router did not register"
            yield .05
        self.event_at("MOUSEMOVE", "NOTHING", point)
        yield .05
        self.event_at("LEFTMOUSE", "PRESS", point)
        deadline = time.monotonic() + 5
        while (drag := self.ui._DRAGS.get(window_key)) is None:
            assert time.monotonic() < deadline, ("Gizmo did not receive press", control, point)
            yield .05
        if control is not None:
            assert drag.mode == control, ("Gizmo pressed a different control", control, drag.mode)

    def click_control(self, control, node):
        point = self.control_point(control, node)
        yield from self.press_at(point, control)
        self.event_at("LEFTMOUSE", "RELEASE", point)
        yield .05

    def drag_control(self, control, node, delta, *, cancel=False):
        start = self.control_point(control, node)
        end = tuple(value + change for value, change in zip(start, delta))
        before = self.settings(node)
        window_key = self.window.as_pointer()
        yield from self.press_at(start, control)
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
