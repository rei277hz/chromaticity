"""Drive direct and evaluated compositor Color inputs through Blender's GUI."""

from dataclasses import replace
import addon_utils
import importlib
import json
import os
from pathlib import Path
import runpy
import sys
import time
import traceback

import bpy
import numpy as np


repository, report_path = sys.argv[sys.argv.index("--") + 1:]
bpy.context.preferences.view.show_splash = False
bpy.context.preferences.extensions.repos.new(
    name="Perceptual Grade vectorscope test", module="pg_vectorscope",
    custom_directory=repository,
)
extension = importlib.import_module("bl_ext.pg_vectorscope.perceptual_grade")
nodes = importlib.import_module(extension.__name__ + ".nodes")
vectorscope = importlib.import_module(extension.__name__ + ".scopes.vectorscope.analysis")
vectorscope_ui = importlib.import_module(extension.__name__ + ".scopes.vectorscope.ui")
drag_checks = runpy.run_path(str(Path(__file__).with_name("vectorscope_drag_checks.py")))
pointer = drag_checks["ScopePointer"](nodes, vectorscope_ui)
errors = []
assert addon_utils.enable(
    extension.__name__, default_set=False, handle_error=errors.append
) is extension, errors
assert not errors and not bpy.app.background, errors
bpy.context.preferences.edit.use_global_undo = True
# A saved preferences file suppresses the first-run Quick Setup popup.
bpy.ops.wm.save_userpref()
select = drag_checks["select"]
keyframes = drag_checks["keyframes"]
complete_tone_histogram = drag_checks["complete_tone_histogram"]
encoded_rgb = drag_checks["encoded_rgb"]
scope_tint = drag_checks["scope_tint"]
chroma_bin = drag_checks["chroma_bin"]
complete_trace = drag_checks["complete_trace"]
assert_solid_trace = drag_checks["assert_solid_trace"]

WIDTH, HEIGHT = 96, 64
TREE_NAME = "Vectorscope compositor fixture"
NODE_NAME = "Vectorscope Grade"
report = {"passed": False, "playback_frames": []}
scene = bpy.context.scene
scene.render.resolution_x = WIDTH
scene.render.resolution_y = HEIGHT
scene.render.resolution_percentage = 100
scene.render.use_compositing = True
scene.render.compositor_device = "CPU"
scene.render.compositor_precision = "FULL"
scene.render.image_settings.file_format = "PNG"
scene.view_settings.view_transform = "Standard"
engine_ids = {item.identifier for item in scene.render.bl_rna.properties["engine"].enum_items}
eevee = next((name for name in ("BLENDER_EEVEE_NEXT", "BLENDER_EEVEE")
              if name in engine_ids), None)
assert eevee is not None, ("EEVEE is unavailable", sorted(engine_ids))
scene.render.engine = eevee
scene.frame_start = 1
scene.frame_end = 120
scene.render.fps = 24


RED = (0.8, 0.04, 0.02, 1.0)
GREEN = (0.02, 0.7, 0.05, 1.0)
BLUE = (0.03, 0.08, 0.9, 1.0)


def paint(color):
    pixels = np.tile(np.asarray(color, dtype=np.float32), WIDTH * HEIGHT)
    image.pixels.foreach_set(pixels)
    image.update()
    image.update_tag()


def scope_bin(color, exposure=0.0):
    return chroma_bin(encoded_rgb(color, exposure))


def paint_grid():
    colors = np.asarray((RED, GREEN, BLUE, RED, GREEN, BLUE, RED, BLUE),
                        dtype=np.float32)
    rows = np.arange(HEIGHT)[:, None]
    columns = np.arange(WIDTH)[None, :]
    indices = ((columns // 12) + (rows // 8) * 2) % len(colors)
    image.pixels.foreach_set(np.ascontiguousarray(colors[indices].reshape(-1)))
    image.update()
    image.update_tag()


def peak_matches(brightness, color, exposure=0.0):
    if brightness is None or brightness.shape != (144, 144) or not np.any(brightness > 0):
        return False
    peak = np.unravel_index(np.argmax(brightness), brightness.shape)
    expected = scope_bin(color, exposure)
    return max(abs(actual - target) for actual, target in zip(peak, expected)) <= 1


image = bpy.data.images.new(
    "Vectorscope source", width=WIDTH, height=HEIGHT, alpha=True, float_buffer=True,
)
image.colorspace_settings.name = "Non-Color"
image.alpha_mode = "CHANNEL_PACKED"
paint(RED)

runtime = vectorscope_ui._runtime
create_job = runtime.create_job


def track_helper_job(inputs, **kwargs):
    field = ("appearance_jobs" if inputs["route"].get("scope_capture") == "appearance"
             else "helper_jobs")
    report[field] = report.get(field, 0) + 1
    job = create_job(inputs, **kwargs)
    if field == "appearance_jobs":
        advance = job.advance

        def record_samples():
            result = advance()
            if result is not None:
                appearance_samples[0] = result["rgba"]
            return result

        job.advance = record_samples
    return job


appearance_samples = [None]
runtime.create_job = track_helper_job

tree = bpy.data.node_groups.new(TREE_NAME, nodes.COMPOSITOR_TREE)
tree.interface.new_socket(name="Color", in_out="OUTPUT", socket_type="NodeSocketColor")
scene.compositing_node_group = tree
source = tree.nodes.new("CompositorNodeImage")
source.image = image
grade = nodes.create_per_node_node(tree)
grade.name = NODE_NAME
output = tree.nodes.new("NodeGroupOutput")
tree.links.new(source.outputs["Image"], grade.inputs["Color"])
tree.links.new(grade.outputs["Color"], output.inputs["Color"])
tree.nodes.active = grade
for node in tree.nodes:
    node.select = node == grade

camera_data = bpy.data.cameras.new("Vectorscope fixture camera")
camera_data.type = "ORTHO"
camera_data.ortho_scale = 4.0
camera = bpy.data.objects.new("Vectorscope fixture camera", camera_data)
scene.collection.objects.link(camera)
camera.location = (0.0, 0.0, 5.0)
scene.camera = camera

window = bpy.context.window
area = next(item for item in window.screen.areas if item.type == "VIEW_3D")
area.type = "NODE_EDITOR"
area.ui_type = "CompositorNodeTree"
space = area.spaces.active
space.pin = True
space.node_tree = tree
space.show_region_ui = True
region = next(item for item in area.regions if item.type == "WINDOW")
pointer.bind(window, area, region)
draw_tone = vectorscope_ui.display._draw_tone


def track_tone_draw(box, state, key, linear, tone, selected):
    draw_tone(box, state, key, linear, tone, selected)
    if state is not None and state.status == "current" and state.tone_histogram is not None:
        report["tone_gizmo_drawn"] = True


vectorscope_ui.display._draw_tone = track_tone_draw


def checkpoint(step):
    report["step"] = step
    path = Path(report_path)
    pending = path.with_suffix(".json.tmp")
    pending.write_text(json.dumps(report, indent=2))
    pending.replace(path)


def state():
    with bpy.context.temp_override(window=window, area=area, region=region):
        return vectorscope_ui.display_state(bpy.context)


def wait_for(predicate, step, timeout=90.0):
    checkpoint(step)
    deadline = time.monotonic() + timeout
    next_report = time.monotonic()
    while not predicate():
        value = state()
        now = time.monotonic()
        if now >= next_report:
            report["scope_status"] = None if value is None else value.status
            report["scope_error"] = None if value is None else value.error
            report["appearance_status"] = None if value is None else value.appearance_status
            report["appearance_error"] = None if value is None else value.appearance_error
            report["scope_bins"] = (
                None if value is None or value.brightness is None
                else int(np.count_nonzero(value.brightness))
            )
            if value is not None and value.brightness is not None:
                brightness = np.asarray(value.brightness)
                locations = np.argwhere(brightness > 0.0)
                report["scope_points"] = [
                    [int(y), int(x), float(brightness[y, x])]
                    for y, x in locations[:8]
                ]
            checkpoint(step)
            next_report = now + 2.0
        if value is not None:
            assert value.status not in {"error", "unavailable"}, (step, value.error)
        assert now < deadline, (step, value)
        yield 0.05


def appearance_current(previous=None):
    value = state()
    if value is None:
        return False
    assert value.appearance_status != "error", value.appearance_error
    return (value.appearance_status == "current" and value.appearance is not None
            and value.appearance.rgba[..., 3].any()
            and (previous is None or not np.array_equal(value.appearance.rgba, previous)))


def snapshot():
    value = state()
    assert value is not None, "The selected Grade has no vectorscope display state"
    trace = complete_trace(value)
    assert value.status != "error", value.error
    return value, trace[..., 3].copy()


def current(color, exposure=0.0):
    value = state()
    return (value is not None and value.status == "current"
            and peak_matches(value.brightness, color, exposure))


def changed(previous):
    value = state()
    return (value is not None and value.status == "current"
            and not np.array_equal(value.brightness, previous))


def image_frame(scene_value):
    if scene_value == scene:
        paint(GREEN if scene_value.frame_current % 2 else BLUE)


def playback(play):
    with bpy.context.temp_override(window=window, area=area, region=region):
        if play:
            bpy.ops.screen.animation_play()
        else:
            bpy.ops.screen.animation_cancel(restore_frame=False)


def cleanup():
    if window.screen is not None and window.screen.is_animation_playing:
        playback(False)
    if image_frame in bpy.app.handlers.frame_change_post:
        bpy.app.handlers.frame_change_post.remove(image_frame)


def exercise_mixed_trace(previous):
    # Add the same code value to every channel for the second color so both
    # colors contribute to the same chroma bin with unequal alpha.
    code = np.array(((0.43, 0.18, 0.27), (0.63, 0.38, 0.47)))
    linear = ((code + 0.099) / 1.099) ** (1 / 0.45)
    pixels = np.array(((*linear[0], 1.0), (*linear[1], 0.25), (*GREEN[:3], 0.0)),
                      dtype=np.float32)
    image.pixels.foreach_set(np.tile(pixels.reshape(-1), WIDTH * HEIGHT // len(pixels)))
    image.update()
    image.update_tag()
    yield from wait_for(lambda: changed(previous), "Mixed RGBA input did not refresh the scope")
    trace = complete_trace(state())
    active = trace[..., 3] > 0
    actual = trace[active, :3]
    expected = np.broadcast_to(scope_tint(np.average(code, axis=0, weights=(1.0, 0.25))),
                               actual.shape)
    assert np.count_nonzero(active) > 1, "Mixed trace is missing its Gaussian density"
    np.testing.assert_allclose(actual, expected, rtol=0, atol=1e-5)
    report["mixed_trace_rgb"] = True


def check_additive_trace_pixels():
    import gpu
    from mathutils import Matrix

    background = 0.023
    mass = np.array([[0.0, 1.0, 1.0, 1.0, 997.0]])
    measured_rgb = np.array([[0.0, 0.0, 0.0],
                             [0.3, 0.12, 0.06],
                             [0.6, 0.24, 0.12],
                             [0.0, 0.0, 0.0],
                             [0.95, 0.95, 0.95]])
    trace = vectorscope.trace_rgba(mass, mass[..., None] * measured_rgb)
    original = trace.copy()
    assert not trace.flags.writeable
    width, height = 40, 8
    saved_blend = gpu.state.blend_get()
    saved_depth = gpu.state.depth_test_get()
    saved_viewport = gpu.state.viewport_get()
    saved_scissor = gpu.state.scissor_get()
    key = object()
    offscreen = gpu.types.GPUOffScreen(width, height, format="RGBA32F")
    try:
        with offscreen.bind(), gpu.matrix.push_pop(), gpu.matrix.push_pop_projection():
            gpu.matrix.load_identity()
            gpu.matrix.load_projection_matrix(Matrix.Identity(4))
            gpu.state.viewport_set(0, 0, width, height)
            gpu.state.scissor_set(0, 0, width, height)
            gpu.state.depth_test_set("NONE")
            gpu.state.blend_set("ALPHA")
            framebuffer = gpu.state.active_framebuffer_get()
            framebuffer.clear(color=(background, background, background, 1.0))
            vectorscope_ui.display._draw_trace((-1, -1, 2, 2), trace, key)
            assert gpu.state.blend_get() == "ALPHA"
            pixels = np.asarray(framebuffer.read_color(0, 0, width, height, 4, 0, "FLOAT"))
            actual = pixels.reshape(height, width, 4)[height // 2, (4, 12, 20, 28, 36), :3]
    finally:
        gpu.state.blend_set(saved_blend)
        gpu.state.depth_test_set(saved_depth)
        gpu.state.viewport_set(*saved_viewport)
        gpu.state.scissor_set(*saved_scissor)
        vectorscope_ui.display._TEXTURES.pop(key, None)
        offscreen.free()

    log_density = np.log1p(65535 * mass[0] / mass.sum()) / np.log(65536)
    density = (1.0 - np.exp(-log_density)) / (1.0 - np.exp(-1.0))
    tint = np.array([scope_tint(color) for color in measured_rgb])
    expected = background + tint * density[:, None]
    np.testing.assert_allclose(actual, expected, rtol=0, atol=5e-4)
    previous = background + tint * log_density[:, None]
    assert np.all(actual[1:3] > previous[1:3] + 5e-4)
    np.testing.assert_allclose(actual[1], actual[2], rtol=0, atol=5e-4)
    np.testing.assert_array_equal(trace, original)
    report["additive_trace_pixels"] = True


def exercise_gizmo_controls():
    baseline = pointer.settings(grade)
    yield from pointer.hover_control("cr", grade)
    resized = yield from pointer.resize_control("resize_e", grade, (12, 0))
    assert resized > 300.
    report["gizmo_hover_and_resize"] = True

    original_simulate = pointer._simulate_event
    probe_calls = []

    def drop_target_moves(kind, value, x, y):
        entry = pointer._injected
        phase = entry.get("phase")
        probe_calls.append((kind, value, phase, entry.get("attempt")))
        if kind == "MOUSEMOVE" and phase == "target":
            return
        original_simulate(kind, value, x, y)

    pointer._simulate_event = drop_target_moves
    exhaustion = None
    try:
        yield from pointer.press_at(
            pointer.control_point("exposure", grade), "exposure", grade,
        )
    except AssertionError as error:
        exhaustion = error
    finally:
        pointer._simulate_event = original_simulate

    assert exhaustion is not None, "Dropped target moves unexpectedly reached the press"
    details = exhaustion.args[0]
    assert isinstance(details, tuple) and len(details) == 4, exhaustion.args
    message, control, _xy, target_attempts = details
    assert message.startswith("Gizmo router ") and "move" in message, details
    assert control == "exposure", details
    assert [(entry["phase"], entry["attempt"]) for entry in target_attempts] == [
        ("target", 1), ("target", 2), ("target", 3),
    ], target_attempts
    assert probe_calls == [
        ("MOUSEMOVE", "NOTHING", "away", 1), ("MOUSEMOVE", "NOTHING", "target", 1),
        ("MOUSEMOVE", "NOTHING", "away", 2), ("MOUSEMOVE", "NOTHING", "target", 2),
        ("MOUSEMOVE", "NOTHING", "away", 3), ("MOUSEMOVE", "NOTHING", "target", 3),
    ], probe_calls
    assert pointer.settings(grade) == baseline
    assert pointer.ui._interaction.drags.get(pointer.window.as_pointer()) is None
    assert pointer.nodes._gesture_token(pointer.window.as_pointer()) is None
    report["hover_exhaustion_before_press"] = True

    dropped_targets = []
    retried_targets = []

    def drop_first_target(kind, value, x, y):
        entry = pointer._injected
        if kind == "MOUSEMOVE" and entry.get("phase") == "target":
            if entry["attempt"] == 1:
                dropped_targets.append(entry)
                return
            retried_targets.append(entry)
        original_simulate(kind, value, x, y)

    pointer._simulate_event = drop_first_target
    try:
        exposed = yield from pointer.drag_control("exposure", grade, (0, 25), cancel=True)
    finally:
        pointer._simulate_event = original_simulate
    assert exposed.linear.exposure > baseline.linear.exposure
    assert len(dropped_targets) == 1, dropped_targets
    assert any(entry["phase"] == "target" and entry["attempt"] >= 2
               and entry.get("received_xy") == entry["xy"]
               and entry.get("admission") == "current"
               for entry in retried_targets), retried_targets
    assert pointer.settings(grade) == baseline
    report["hover_retry_acknowledged"] = True
    balanced = yield from pointer.drag_control("cr_balance", grade, (0, 25), cancel=True)
    assert balanced.linear.balance[0] < baseline.linear.balance[0]
    balanced = yield from pointer.drag_control("yb_balance", grade, (25, 0), cancel=True)
    assert balanced.linear.balance[1] < baseline.linear.balance[1]
    for axis, index in (("cr", 0), ("yb", 1)):
        directed = yield from pointer.drag_control(axis, grade, (13, 19), cancel=True)
        assert directed.linear.spread[index] != baseline.linear.spread[index]
        assert directed.linear.heading[index] != baseline.linear.heading[index]
        assert directed.linear.spread[1 - index] == baseline.linear.spread[1 - index]
        assert directed.linear.heading[1 - index] == baseline.linear.heading[1 - index]
    report["linear_gizmo_controls"] = True

    yield from pointer.click_control("tone_tab", grade)
    yield from wait_for(
        lambda: (value := state()) is not None and value.status == "current"
        and value.tone_histogram is not None,
        "Tone Gizmo did not publish its histogram",
    )
    histogram = complete_tone_histogram(state())
    yield from wait_for(lambda: report.get("tone_gizmo_drawn"), "Tone Gizmo failed to draw", 5.)
    yield from wait_for(appearance_current, "Tone Gizmo did not publish final appearance")
    original_appearance = state().appearance.rgba
    adjusted = yield from pointer.drag_control("exposure", grade, (25, 0), cancel=True)
    assert adjusted.linear.exposure > baseline.linear.exposure
    adjusted = yield from pointer.drag_control("curve", grade, (20, 0), cancel=True)
    assert adjusted.tone.input_nits[3] > baseline.tone.input_nits[3]
    assert adjusted.tone.input_nits[:3] == baseline.tone.input_nits[:3]
    adjusted = yield from pointer.drag_control("fit", grade, (0, 35), cancel=True)
    assert adjusted.tone.fit > baseline.tone.fit
    yield from exercise_fit_reset()
    with bpy.context.temp_override(window=window, area=area, region=region):
        assert bpy.ops.perceptual_grade.gizmo_set_peak(
            peak_nits="2000", node_pointer=str(grade.as_pointer()),
            owner_pointer=str(grade.as_pointer()),
        ) == {"FINISHED"}
    yield from wait_for(
        lambda: (value := state()) is not None and value.status == "current"
        and value.tone_histogram is not None and value.tone_histogram is not histogram,
        "Peak edit did not update the Tone histogram",
    )
    assert pointer.settings(grade).tone.peak_nits == 2000
    yield from wait_for(lambda: appearance_current(original_appearance),
                        "Peak edit did not update final appearance")
    tone_appearance = state().appearance.rgba
    tone_histogram = complete_tone_histogram(state())
    appearance_jobs = report.get("appearance_jobs", 0)
    grade.web_chroma_1_0 = -2.
    grade.web_chroma_2_0 = -2.
    yield from wait_for(lambda: appearance_current(tone_appearance),
                        "Warp edit did not update final appearance")
    assert report.get("appearance_jobs", 0) > appearance_jobs
    assert state().status == "current" and state().tone_histogram is tone_histogram
    grade.web_chroma_1_0 = 0.
    grade.web_chroma_2_0 = 0.

    # With a non-default peak, R resets Highlights to the current output target.
    before = pointer.settings(grade)
    point = pointer.control_point("curve", grade)
    yield from pointer.press_at(point, "curve", grade)
    yield from pointer.reset_drag_at(point)
    reset_settings = pointer.settings(grade)
    assert reset_settings.linear == before.linear
    assert reset_settings.tone.input_nits[:3] == before.tone.input_nits[:3]
    assert abs(reset_settings.tone.input_nits[3] - 2000.) < .05
    pointer.event_at("LEFTMOUSE", "RELEASE", point)
    yield from wait_for(lambda: nodes._gesture_token(window.as_pointer()) is None,
                        "Highlights reset gesture did not finish", 5.)
    assert pointer.settings(grade) == reset_settings
    report["highlight_reset_to_peak"] = True
    grade.input_highlights = before.tone.input_nits[3]
    grade.peak_nits = "1000"

    # Guarded black and white must be sampled at the returned endpoints.
    paint((-1., -1., -1., .25))
    yield from wait_for(
        lambda: (appearance_current()
                 and np.allclose(appearance_samples[0][..., :3], 0.)
                 and np.allclose(appearance_samples[0][..., 3], .25, atol=1e-6)),
        "Final appearance did not sample guarded black",
    )
    np.testing.assert_allclose(appearance_samples[0][..., 3], .25, atol=1e-6)
    black_appearance = state().appearance.rgba
    paint((2048., 2048., 2048., .75))
    yield from wait_for(
        lambda: (value := state()) is not None and value.appearance_status == "current"
        and value.appearance is not None and value.appearance.rgba is not black_appearance
        and value.appearance.overflow_fraction == 1.,
        "Final appearance did not report guarded white overflow",
    )
    white = appearance_samples[0]
    assert np.all(white[..., 0] > 100.)
    np.testing.assert_allclose(white[..., 1:3], 0., atol=.02)
    np.testing.assert_allclose(white[..., 3], .75, atol=1e-6)
    report["appearance_tone_warp_and_endpoints"] = True
    paint(RED)
    yield from pointer.click_control("linear_tab", grade)
    yield from wait_for(lambda: current(RED), "Linear trace did not return from Tone")
    assert report.get("helper_jobs", 0) == 0
    report["tone_gizmo_controls"] = True


def exercise_fit_reset():
    window_key = window.as_pointer()
    grade.fit = .75
    before = pointer.settings(grade)
    reset = replace(before, tone=replace(before.tone, fit=0.))
    start = pointer.control_point("fit", grade)
    yield from pointer.press_at(start, "fit", grade)
    assert nodes._gesture_token(window_key) is None
    yield from pointer.reset_drag_at(start)
    assert nodes._gesture_token(window_key) is not None
    assert pointer.settings(grade) == reset
    pointer.event_at("LEFTMOUSE", "RELEASE", start)
    yield from wait_for(lambda: nodes._gesture_token(window_key) is None,
                        "Fit reset gesture did not finish", 5.)
    assert pointer.settings(grade) == reset
    report["fit_reset_before_motion"] = True

    grade.fit = before.tone.fit
    yield from pointer.press_at(start, "fit", grade)
    end = start[0], start[1] + 35
    pointer.event_at("MOUSEMOVE", "NOTHING", end)
    yield from wait_for(lambda: grade.fit > before.tone.fit,
                        "Fit drag did not move before reset", 5.)
    yield from pointer.reset_drag_at(end)
    assert pointer.settings(grade) == reset
    continued = end[0], end[1] - 16
    pointer.event_at("MOUSEMOVE", "NOTHING", continued)
    yield from wait_for(lambda: grade.fit < 0., "Fit drag did not rebase on reset", 5.)
    pointer.event_at("ESC", "PRESS", continued)
    pointer.event_at("ESC", "RELEASE", continued)
    pointer.event_at("LEFTMOUSE", "RELEASE", continued)
    yield from wait_for(lambda: nodes._gesture_token(window_key) is None,
                        "Fit reset gesture did not cancel", 5.)
    assert pointer.settings(grade) == before
    report["fit_reset_continues_and_cancels"] = True
    grade.fit = reset.tone.fit


def exercise_drags():
    cleanup()
    tree.links.new(source.outputs["Image"], grade.inputs["Color"])
    paint(RED)
    yield from wait_for(lambda: current(RED), "Restore direct Image for gestures")

    baseline = pointer.settings(grade)
    yield from pointer.inert_drag()
    assert pointer.settings(grade) == baseline
    report["click_unchanged"] = True
    paint((*RED[:3], 0.0))
    yield from wait_for(
        lambda: (value := state()) is not None and value.status == "current"
        and value.brightness is not None and not np.any(value.brightness),
        "Transparent Image did not produce an empty vectorscope",
    )
    yield from pointer.inert_drag((25, 25))
    assert pointer.settings(grade) == baseline
    report["empty_plot_inert"] = True
    paint(RED)
    yield from wait_for(lambda: current(RED), "Restore opaque Image for gestures")

    shared = nodes._make_grade()
    first = nodes.create_node(tree)
    second = nodes.create_node(tree)
    first.pg_grade = second.pg_grade = shared
    tree.links.new(source.outputs["Image"], first.inputs["Color"])
    second_source = tree.nodes.new("CompositorNodeImage")
    second_image = bpy.data.images.new(
        "Second vectorscope source", width=WIDTH, height=HEIGHT, alpha=True, float_buffer=True,
    )
    second_image.colorspace_settings.name = "Non-Color"
    second_image.alpha_mode = "CHANNEL_PACKED"
    second_image.pixels.foreach_set(np.tile(np.asarray(BLUE, dtype=np.float32), WIDTH * HEIGHT))
    second_image.update()
    second_source.image = second_image
    tree.links.new(second_source.outputs["Image"], second.inputs["Color"])
    select(tree, second)
    yield from wait_for(lambda: current(BLUE), "Second shared Grade did not plot its blue input")
    _, peer_initial = snapshot()
    select(tree, first)
    yield from wait_for(lambda: current(RED), "First shared Grade did not plot its red input")
    yield from pointer.drag(first, (24, 20), cancel=lambda: select(tree, second))
    report["selection_cancelled"] = True
    yield from wait_for(lambda: current(BLUE), "Selection change did not restore the shared Grade")
    select(tree, first)
    yield from wait_for(lambda: current(RED), "First shared Grade did not restore its trace")
    jobs = report.get("helper_jobs", 0)
    xy = yield from pointer.drag(first, (24, 20))
    first_peak = pointer.peak()
    assert (shared.pg_linear.source_x, shared.pg_linear.source_y) == xy
    assert report.get("helper_jobs", 0) == jobs, "Shared Linear drag recaptured the direct Image"
    assert first.pg_grade == second.pg_grade
    select(tree, second)
    yield from wait_for(lambda: changed(peer_initial), "Second shared consumer did not receive the edit")
    assert pointer.peak() != first_peak, "Two shared consumers reused the same trace"
    report["shared_drag"] = True
    report["shared_consumer_input"] = True

    select(tree, grade)
    scene.frame_set(27, subframe=.25)
    scene.tool_settings.use_keyframe_insert_auto = True
    yield from wait_for(lambda: current(RED), "Per-node plot did not recover after shared edits")
    yield from pointer.drag(grade, (24, 20), cancel="ESC")
    report["escape_cancelled"] = True
    yield from wait_for(lambda: current(RED), "Escape did not restore the per-node trace")
    yield from pointer.drag(
        grade, (24, 20), cancel=lambda: scene.frame_set(scene.frame_current + 1),
    )
    assert not keyframes(tree), "Cancelled vectorscope gestures inserted keys"
    report["frame_change_cancelled"] = True
    scene.frame_set(27, subframe=.25)
    yield from wait_for(lambda: current(RED), "Per-node plot did not recover after frame change")
    pixel_cancel_before = pointer.settings(grade)
    yield from pointer.drag(
        grade, (24, 20), cancel=lambda: paint(GREEN),
    )
    yield from wait_for(
        lambda: current(GREEN),
        "Changing captured pixels did not cancel the drag and refresh the vectorscope",
    )
    assert pointer.settings(grade) == pixel_cancel_before
    assert not keyframes(tree), "A capture-change cancellation inserted Auto Key curves"
    report["capture_change_cancelled"] = True
    paint(RED)
    yield from wait_for(lambda: current(RED), "Per-node plot did not recover after pixel change")

    yield from exercise_animated_frame_cancel()
    tree.animation_data_clear()
    grade.property_unset("source_x")
    grade.property_unset("source_y")
    scene.frame_set(27, subframe=.25)
    yield from wait_for(lambda: current(RED), "Per-node plot did not recover after animation test")
    with bpy.context.temp_override(window=window, area=area, region=region):
        assert bpy.ops.ed.undo_push(message="Before vectorscope drag") == {"FINISHED"}
    scene.tool_settings.use_keyframe_insert_auto = True
    press_frame = scene.frame_current + scene.frame_subframe
    xy = yield from pointer.drag(grade, (24, 20))
    assert all(a != b for a, b in zip(xy, baseline.linear.source_xy)), xy
    assert keyframes(tree) == {
        grade.path_from_id("source_x"): ((press_frame, xy[0]),),
        grade.path_from_id("source_y"): ((press_frame, xy[1]),),
    }
    report["autokey_at_press_frame"] = True
    with bpy.context.temp_override(window=window, area=area, region=region):
        assert bpy.ops.ed.undo() == {"FINISHED"}
    restored_tree = bpy.data.node_groups[TREE_NAME]
    assert pointer.settings(restored_tree.nodes[NODE_NAME]) == baseline
    assert not keyframes(restored_tree), "Undo left Auto Key curves from the drag"
    gizmo_key = vectorscope_ui.editor.key(window, area)
    assert gizmo_key in vectorscope_ui._editors, "Undo hid the Gizmo"
    yield from wait_for(lambda: current(RED), "Undo did not restore the vectorscope")
    report["per_node_drag"] = True
    report["source_keys_undone"] = True
    report["undo_preserved_gizmo"] = True


def exercise_animated_frame_cancel():
    initial, destination = (0.30, 0.34), (0.32, 0.31)
    for frame, (source_x, source_y) in ((27, initial), (28, destination)):
        scene.frame_set(frame)
        grade.source_x, grade.source_y = source_x, source_y
        assert grade.keyframe_insert(data_path="source_x", frame=frame)
        assert grade.keyframe_insert(data_path="source_y", frame=frame)
    animated_keys = keyframes(tree)
    scene.frame_set(27)
    yield from wait_for(
        lambda: pointer.peak() is not None,
        "Animated frame 27 did not produce a current vectorscope",
    )
    window_key = window.as_pointer()
    animated_start = (grade.source_x, grade.source_y)
    assert np.allclose(animated_start, initial, rtol=0, atol=1e-6), animated_start
    pushed_undo = []
    push_undo = nodes._push_gesture_undo

    def record_undo(key):
        pushed_undo.append(key)
        return push_undo(key)

    nodes._push_gesture_undo = record_undo
    try:
        yield from pointer.press()
        pointer.event("MOUSEMOVE", "NOTHING", (24, 20))
        yield from wait_for(
            lambda: nodes._gesture_token(window_key) is not None
            and (grade.source_x, grade.source_y) != animated_start,
            "Animated source-white drag did not activate before the frame switch",
        )
        scene.frame_set(28)
        yield from wait_for(
            lambda: nodes._gesture_token(window_key) is None and pointer.peak() is not None,
            "Frame change did not cancel the drag and refresh the scope",
        )
        assert window_key not in vectorscope_ui._interaction.drags
        pointer.event("LEFTMOUSE", "RELEASE", (24, 20))
        yield .1
        animated_end = (grade.source_x, grade.source_y)
        assert np.allclose(animated_end, destination, rtol=0, atol=1e-6), animated_end
        assert keyframes(tree) == animated_keys, (
            "Frame-change cancellation changed existing Auto Key curves",
            animated_keys, keyframes(tree),
        )
        assert pushed_undo == [], pushed_undo
        report["animated_destination_preserved"] = True
    finally:
        nodes._push_gesture_undo = push_undo


def scenario():
    checkpoint("enable vectorscope")
    with bpy.context.temp_override(window=window, area=area, region=region):
        assert bpy.ops.perceptual_grade.toggle_vectorscope() == {"FINISHED"}

    yield from wait_for(lambda: current(RED), "Direct Image input did not plot red")
    initial_state, initial = snapshot()
    assert_solid_trace(initial_state, RED)
    checkpoint("draw additive trace into framebuffer")
    check_additive_trace_pixels()
    assert np.sum(initial) > 0.0, "The direct Image input produced an empty plot"
    report["initial_shape"] = list(initial.shape)
    report["direct_image_visible"] = True
    report["direct_sampling_avoids_helper"] = report.get("helper_jobs", 0) == 0
    assert report["direct_sampling_avoids_helper"], "Direct Image sampling started a helper job"

    checkpoint("native Linear and Tone Gizmo controls")
    yield from exercise_gizmo_controls()

    grade.exposure = -6.0
    yield from wait_for(lambda: current(RED, -6.0), "Linear exposure did not move the red peak")
    exposed_state, exposed = snapshot()
    assert_solid_trace(exposed_state, RED, -6.0)
    report["linear_edit_refreshed"] = not np.array_equal(initial, exposed)
    assert report["linear_edit_refreshed"]
    grade.exposure = 0.0
    yield from wait_for(lambda: current(RED), "Restoring exposure did not refresh the plot")
    yield from exercise_mixed_trace(initial)

    paint(GREEN)
    yield from wait_for(lambda: current(GREEN), "Image pixel edit did not move the peak to green")
    report["image_pixels_refreshed"] = True
    _, unprocessed = snapshot()
    checkpoint("spatial image pixel refresh")
    paint_grid()
    yield from wait_for(lambda: changed(unprocessed),
                        "Spatially varying Image edit did not refresh the plot")
    _, spatial = snapshot()

    tree.links.remove(next(link for link in tree.links
                           if link.to_socket == grade.inputs["Color"]))
    transform = tree.nodes.new("CompositorNodeTransform")
    transform.inputs["X"].default_value = 9.0
    transform.inputs["Scale"].default_value = 0.82
    tree.links.new(source.outputs["Image"], transform.inputs["Image"])
    tree.links.new(transform.outputs["Image"], grade.inputs["Color"])
    yield from wait_for(lambda: changed(spatial),
                        "Processed Compositor input did not produce a changed current plot")
    _, processed = snapshot()
    report["processed_input_visible"] = bool(np.count_nonzero(processed) > 1)
    assert report["processed_input_visible"], "Transform should interpolate the image edges"
    report["processed_input_uses_helper"] = report.get("helper_jobs", 0) > 0
    assert report["processed_input_uses_helper"], "Processed input skipped evaluation capture"
    helper_jobs = report["helper_jobs"]
    grade.exposure = 1.0
    yield from wait_for(lambda: changed(processed), "Processed input Linear edit did not refresh")
    assert report["helper_jobs"] == helper_jobs, "Processed input Linear edit started a capture"
    _, exposed = snapshot()
    transform.inputs["Scale"].default_value = 0.53
    yield from wait_for(lambda: changed(exposed), "Upstream Color edit did not refresh the plot")
    assert report["helper_jobs"] > helper_jobs, "Upstream Color edit reused stale samples"
    grade.exposure = 0.0

    bpy.app.handlers.frame_change_post.append(image_frame)
    checkpoint("playback refresh")
    playback(True)
    deadline = time.monotonic() + 1.25
    saw_updating = False
    while time.monotonic() < deadline:
        assert window.screen.is_animation_playing, "Timeline playback stopped unexpectedly"
        report["playback_frames"].append(int(scene.frame_current))
        displayed, density = snapshot()
        assert displayed.status in {"updating", "current"}, displayed
        assert np.any(density > 0.0), "Playback discarded the last complete plot"
        saw_updating |= displayed.status == "updating"
        yield 0.03
    playback(False)
    stopped_frame = int(scene.frame_current)
    report["retained_complete_during_updates"] = saw_updating

    expected = GREEN if stopped_frame % 2 else BLUE
    yield from wait_for(lambda: current(expected),
                        "Playback did not publish the latest stopped-frame plot")
    report["latest_frame_published"] = True
    assert_solid_trace(state(), expected)
    report["stopped_frame"] = stopped_frame
    checkpoint("native compositor gestures")
    yield from exercise_drags()


sequence = scenario()
started = time.monotonic()


def request_quit():
    with bpy.context.temp_override(window=window):
        assert bpy.ops.wm.quit_blender("EXEC_DEFAULT") == {"FINISHED"}
        # The isolated display receives no physical pointer events.
        window.event_simulate(type="MOUSEMOVE", value="NOTHING", x=640, y=480)
    return None


def advance():
    try:
        assert time.monotonic() - started < 285.0, "Vectorscope acceptance exceeded its budget"
        return next(sequence)
    except StopIteration:
        pointer.close()
        cleanup()
        report["passed"] = True
        checkpoint("passed")
        bpy.app.timers.register(request_quit, first_interval=0.1, persistent=True)
        return None
    except BaseException:
        report["error"] = traceback.format_exc()
        report["pointer_trace"] = pointer.diagnostics()
        try:
            pointer.close()
            cleanup()
        except BaseException as error:
            report["cleanup_error"] = str(error)
        checkpoint("failed")
        print(report["error"], flush=True)
        os._exit(1)


bpy.app.timers.register(advance, first_interval=0.2, persistent=True)
