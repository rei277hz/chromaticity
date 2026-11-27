"""Exercise Shader viewport capture and native vectorscope drags."""

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
    name="Perceptual Grade shader vectorscope test", module="pg_vectorscope_shader",
    custom_directory=repository,
)
extension = importlib.import_module("bl_ext.pg_vectorscope_shader.perceptual_grade")
nodes = importlib.import_module(extension.__name__ + ".features.grade.host")
vectorscope_ui = importlib.import_module(extension.__name__ + ".features.vectorscope.ui")
drag_checks = runpy.run_path(str(Path(__file__).with_name("vectorscope_drag_checks.py")))
pointer = drag_checks["ScopePointer"](nodes, vectorscope_ui)
errors = []
assert addon_utils.enable(extension.__name__, default_set=False,
                          handle_error=errors.append) is extension, errors
assert not errors and not bpy.app.background, errors
bpy.ops.wm.save_userpref()
select = drag_checks["select"]
encoded_rgb = drag_checks["encoded_rgb"]
scope_tint = drag_checks["scope_tint"]
chroma_bin = drag_checks["chroma_bin"]
complete_trace = drag_checks["complete_trace"]
complete_tone_histogram = drag_checks["complete_tone_histogram"]
assert_solid_trace = drag_checks["assert_solid_trace"]

report = {"passed": False}
scene = bpy.context.scene
engine_ids = {item.identifier for item in scene.render.bl_rna.properties["engine"].enum_items}
eevee = next((name for name in ("BLENDER_EEVEE_NEXT", "BLENDER_EEVEE")
              if name in engine_ids), None)
assert eevee is not None, ("EEVEE is unavailable", sorted(engine_ids))
scene.render.engine = eevee
scene.render.resolution_x, scene.render.resolution_y = 96, 64
scene.render.resolution_percentage = 100
scene.render.use_compositing = False
scene.render.film_transparent = False

mesh = bpy.data.meshes.new("Vectorscope shader mesh")
mesh.from_pydata(((-2, -2, 0), (2, -2, 0), (2, 2, 0), (-2, 2, 0)), (), ((0, 1, 2, 3),))
uv = mesh.uv_layers.new(name="Vectorscope UV")
for item in uv.uv:
    item.vector = (0.25, 0.5)
mesh.update()
obj = bpy.data.objects.new("Vectorscope shader plane", mesh)
scene.collection.objects.link(obj)
material = bpy.data.materials.new("Vectorscope shader material")
material.use_nodes = True
tree = material.node_tree
for node in tuple(tree.nodes):
    tree.nodes.remove(node)
red, blue = (0.72, 0.05, 0.28, 1.0), (0.02, 0.08, 0.84, 1.0)
image = bpy.data.images.new("Vectorscope UV texture", 2, 1, alpha=True, float_buffer=True)
image.colorspace_settings.name = "Non-Color"
image.alpha_mode = "CHANNEL_PACKED"
image.pixels.foreach_set(np.asarray((*red, *blue), dtype=np.float32))
image.update()
coordinates = tree.nodes.new("ShaderNodeUVMap")
coordinates.uv_map = uv.name
color = tree.nodes.new("ShaderNodeTexImage")
color.image = image
color.interpolation = "Closest"
grade = nodes.create_per_node_node(tree)
grade.name = "Vectorscope Shader Grade"
shader = tree.nodes.new("ShaderNodeBsdfPrincipled")
output = tree.nodes.new("ShaderNodeOutputMaterial")
tree.links.new(coordinates.outputs["UV"], color.inputs["Vector"])
tree.links.new(color.outputs["Color"], grade.inputs["Color"])
tree.links.new(grade.outputs["Color"], shader.inputs["Base Color"])
tree.links.new(shader.outputs[0], output.inputs["Surface"])
obj.data.materials.append(material)

runtime = vectorscope_ui._runtime
create_job = runtime.create_job
capture_jobs = []


def track_capture(inputs, **kwargs):
    capture_jobs.append(inputs["route"].get("scope_capture", "input"))
    return create_job(inputs, **kwargs)


runtime.create_job = track_capture

camera_data = bpy.data.cameras.new("Vectorscope shader camera")
camera_data.type = "ORTHO"
camera_data.ortho_scale = 5.0
camera = bpy.data.objects.new("Vectorscope shader camera", camera_data)
scene.collection.objects.link(camera)
camera.location = (0.0, 0.0, 5.0)
scene.camera = camera

window = bpy.context.window
node_area = next(item for item in window.screen.areas if item.type == "VIEW_3D")
node_area.type = "NODE_EDITOR"
node_area.ui_type = "ShaderNodeTree"
for item in scene.objects:
    item.select_set(item == obj)
bpy.context.view_layer.objects.active = obj
node_area.spaces.active.pin = True
node_area.spaces.active.shader_type = "OBJECT"
node_area.spaces.active.node_tree = tree
tree.nodes.active = grade
for item in tree.nodes:
    item.select = item == grade
node_region = next(item for item in node_area.regions if item.type == "WINDOW")
pointer.bind(window, node_area, node_region)
view_area = next(item for item in window.screen.areas if item.type == "OUTLINER")
view_area.type = "VIEW_3D"
view_area.spaces.active.region_3d.view_perspective = "CAMERA"


def checkpoint(step):
    report["step"] = step
    path = Path(report_path)
    pending = path.with_suffix(".json.tmp")
    pending.write_text(json.dumps(report, indent=2))
    pending.replace(path)


def state():
    with bpy.context.temp_override(window=window, area=node_area, region=node_region):
        return vectorscope_ui.display_state(bpy.context)


def wait_for(predicate, message, timeout=120.0):
    checkpoint(message)
    deadline = time.monotonic() + timeout
    while not predicate():
        value = state()
        assert value is None or value.status not in {"error", "unavailable"}, (
            f"{message}: {value.error}"
        )
        assert time.monotonic() < deadline, (message, value)
        yield 0.05


def current(previous=None):
    value = state()
    if value is None or value.status != "current" or value.brightness is None:
        return False
    brightness = np.asarray(value.brightness)
    return previous is None or not np.array_equal(brightness, previous)


def matches(color, exposure=0.0):
    if not current():
        return False
    brightness = state().brightness
    if not np.any(brightness > 0):
        return False
    expected = chroma_bin(encoded_rgb(color, exposure))
    peak = np.unravel_index(np.argmax(brightness), brightness.shape)
    return max(abs(actual - target) for actual, target in zip(peak, expected)) <= 1


def mixed_peaks(display):
    if display is None or display.status != "current" or display.rgba is None:
        return None
    trace = complete_trace(display)
    peaks = []
    for sample in (red, blue):
        code = encoded_rgb(sample)
        row, column = chroma_bin(code)
        neighborhood = trace[row - 1:row + 2, column - 1:column + 2]
        index = np.unravel_index(np.argmax(neighborhood[..., 3]), (3, 3))
        rgba = neighborhood[index]
        if rgba[3] <= 0 or not np.allclose(rgba[:3], scope_tint(code), rtol=0, atol=1e-3):
            return None
        peaks.append(float(rgba[3]))
    return peaks


def appearance_current(previous=None):
    value = state()
    if value is None:
        return False
    assert value.appearance_status not in {"error", "unavailable", "bake"}, value.appearance_error
    if value.appearance_status != "current" or value.appearance is None:
        return False
    trace = value.appearance.rgba
    assert trace.shape == (144, 288, 4) and not trace.flags.writeable
    return trace[..., 3].any() and (previous is None or not np.array_equal(trace, previous))


def scenario():
    checkpoint("enable vectorscope")
    with bpy.context.temp_override(window=window, area=node_area, region=node_region):
        assert bpy.ops.perceptual_grade.toggle_vectorscope() == {"FINISHED"}
    yield from wait_for(lambda: matches(red), "Shader AOV capture did not plot the first UV sample")
    first = np.asarray(state().brightness).copy()
    assert first.shape == (144, 144) and np.sum(first) > 0
    assert_solid_trace(state(), red)
    report["initial_shape"] = list(first.shape)
    report["shader_aov_visible"] = True
    previous_captures = len(capture_jobs)
    grade.exposure = 1.0
    yield from wait_for(lambda: matches(red, 1.0), "Shader Linear edit did not refresh")
    assert_solid_trace(state(), red, 1.0)
    assert len(capture_jobs) == previous_captures, "Shader Linear edit recaptured unchanged inputs"
    report["linear_edit_refreshed"] = True
    for item in uv.uv:
        item.vector = (0.75, 0.5)
    mesh.update()
    mesh.update_tag()
    yield from wait_for(lambda: matches(blue, 1.0), "Shader UV edit did not move the vectorscope peak")
    assert len(capture_jobs) > previous_captures, "Shader UV edit reused stale samples"
    report["uv_edit_refreshed"] = True
    grade.exposure = 0.0
    yield from wait_for(lambda: matches(blue), "Shader plot did not restore its exposure")
    captures = len(capture_jobs)
    checkpoint("native per-node Shader drag")
    yield from pointer.drag(grade, (-24, 20), cancel="RIGHTMOUSE")
    report["right_click_cancelled"] = True
    yield from wait_for(lambda: matches(blue), "Right-click did not restore the Shader trace")
    yield from pointer.drag(grade, (-24, 20))
    assert len(capture_jobs) == captures, "Per-node Shader drag recaptured unchanged inputs"
    report["per_node_drag"] = True

    shared = nodes.create_node(tree)
    shared.pg_grade = nodes._make_grade()
    tree.links.new(color.outputs["Color"], shared.inputs["Color"])
    tree.links.new(shared.outputs["Color"], shader.inputs["Base Color"])
    select(tree, shared)
    yield from wait_for(lambda: matches(blue), "Shared Shader Grade did not plot its UV input")
    captures = len(capture_jobs)
    baseline = pointer.settings(grade)
    checkpoint("native shared Shader drag")
    xy = yield from pointer.drag(shared, (-24, 20))
    assert (shared.pg_grade.pg_linear.source_x, shared.pg_grade.pg_linear.source_y) == xy
    assert pointer.settings(grade) == baseline
    assert len(capture_jobs) == captures, "Shared Shader drag recaptured unchanged inputs"
    report["shared_drag"] = True

    # Sample both sides of the texture in one opaque surface capture, with
    # separate Grade input alpha and surface coverage.
    shared.pg_grade.pg_linear.source_x = 0.3127
    shared.pg_grade.pg_linear.source_y = 0.329
    image.pixels.foreach_set(np.asarray((*red, *blue[:3], 0.125), dtype=np.float32))
    image.update()
    image.update_tag()
    tree.links.new(color.outputs["Alpha"], shared.inputs["Alpha"])
    for loop, item in zip(mesh.loops, uv.uv):
        item.vector = (0.25 if mesh.vertices[loop.vertex_index].co.x < 0 else 0.75, 0.5)
    mesh.update()
    mesh.update_tag()
    yield from wait_for(
        lambda: mixed_peaks(state()) is not None,
        "Shader UV capture did not plot both encoded source colors",
    )
    red_density, blue_density = mixed_peaks(state())
    assert red_density > blue_density, (red_density, blue_density)
    report["mixed_trace_rgb"] = True

    # Fit changes the mapping only when the source and target anchors differ.
    shared.pg_grade.pg_tone.input_white = 450.
    input_captures = capture_jobs.count("input")
    yield from pointer.click_control("tone_tab", shared)
    yield from wait_for(
        lambda: (value := state()) is not None and value.status == "current"
        and value.tone_histogram is not None,
        "Shared Shader Grade did not publish the Tone histogram",
    )
    histogram = complete_tone_histogram(state())
    yield from wait_for(appearance_current, "Shared Shader Tone did not plot final appearance")
    original_appearance = state().appearance.rgba
    appearance_captures = capture_jobs.count("appearance")
    assert appearance_captures > 0

    shared.pg_grade.pg_tone.input_highlights = 600.0
    with bpy.context.temp_override(window=window, area=node_area, region=node_region):
        assert bpy.ops.perceptual_grade.gizmo_set_peak(peak_nits="1000") == {"FINISHED"}
    assert shared.pg_grade.pg_tone.input_highlights == 1000.0
    yield from wait_for(
        lambda: (value := state()) is not None and value.appearance_status == "current"
        and value.appearance is not None and value.appearance.rgba is not original_appearance,
        "Same-value peak selection did not set shared Grade Highlights",
    )
    previous_appearance = state().appearance
    panel_edit_started = time.monotonic()
    shared.pg_grade.pg_tone.fit += 0.1
    yield from wait_for(
        lambda: (value := state()) is not None
        and value.appearance_status in {"retained", "updating"}
        and value.appearance is not None,
        "Tone panel edit did not retain the previous appearance while updating",
    )
    yield from wait_for(
        lambda: (value := state()) is not None and value.appearance_status == "preview"
        and value.appearance is not None and value.appearance is not previous_appearance,
        "Tone panel edit did not publish its bounded GPU preview",
    )
    panel_to_preview_seconds = time.monotonic() - panel_edit_started
    yield from wait_for(
        lambda: appearance_current() and state().appearance.rgba is not previous_appearance.rgba,
        "Tone panel edit did not publish its exact appearance",
    )
    panel_to_exact_seconds = time.monotonic() - panel_edit_started
    original_appearance = state().appearance.rgba
    appearance_captures = capture_jobs.count("appearance")

    before = pointer.settings(shared)
    start = pointer.control_point("fit", shared)
    yield from pointer.press_at(start, "fit", shared)
    drag_started = time.monotonic()
    previous_trace = state().appearance
    preview_resources = None
    drag_preview_seconds = []
    for delta in (18, 35):
        end = start[0], start[1] + delta
        moved = time.monotonic()
        pointer.event_at("MOUSEMOVE", "NOTHING", end)
        yield from wait_for(
            lambda: (value := state()) is not None and value.appearance_status == "preview"
            and value.appearance is not None and value.appearance is not previous_trace,
            "Tone drag did not publish its bounded GPU preview",
        )
        drag_preview_seconds.append(time.monotonic() - moved)
        previous_trace = state().appearance
        assert previous_trace.rgba[..., 3].any()
        preview = runtime.preview_backend
        resources = (preview._input_texture, *(preview._role_textures[role][2]
                     for role in ("web", "web_toe", "adaptance")))
        if preview_resources is not None:
            assert all(current is previous for current, previous in zip(resources, preview_resources))
        preview_resources = resources
    yield from wait_for(
        lambda: pointer.settings(shared).tone.fit > before.tone.fit,
        "Tone drag did not change Fit",
    )
    yield from wait_for(
        lambda: appearance_current(original_appearance),
        "Tone drag did not publish an exact appearance before release",
    )
    drag_to_exact_seconds = time.monotonic() - drag_started
    pointer.event_at("LEFTMOUSE", "RELEASE", end)
    edited = pointer.settings(shared)
    assert edited.tone.fit > before.tone.fit
    assert shared.pg_grade.pg_tone.fit == edited.tone.fit
    assert pointer.settings(grade) == baseline
    yield from wait_for(
        lambda: (value := state()) is not None and value.status == "current"
        and value.tone_histogram is not None and value.tone_histogram is not histogram,
        "Shared Shader Tone Fit did not refresh the histogram",
    )
    yield from wait_for(lambda: appearance_current(original_appearance),
                        "Shared Shader Tone Fit did not refresh final appearance")
    assert capture_jobs.count("input") == input_captures
    assert capture_jobs.count("appearance") > appearance_captures
    report["appearance_timing_seconds"] = {
        "panel_to_exact": panel_to_exact_seconds,
        "panel_to_preview": panel_to_preview_seconds,
        "drag_to_exact": drag_to_exact_seconds,
        "first_drag_preview": drag_preview_seconds[0],
        "warm_drag_preview": drag_preview_seconds[1],
    }
    report["appearance_retained_during_update"] = True
    report["appearance_preview_reused_inputs_and_roles"] = True
    report["appearance_exact_during_drag"] = True
    report["shared_tone_gizmo"] = True

    tone_appearance = state().appearance.rgba
    tone_histogram = complete_tone_histogram(state())
    appearance_captures = capture_jobs.count("appearance")
    shared.pg_grade.pg_color.web_chroma_2_5 = -1.0
    yield from wait_for(lambda: appearance_current(tone_appearance),
                        "Shared Shader Warp did not refresh final appearance")
    assert capture_jobs.count("input") == input_captures
    assert capture_jobs.count("appearance") > appearance_captures
    assert state().status == "current" and state().tone_histogram is tone_histogram
    report["appearance_tone_and_warp"] = True

    tone = shared.pg_grade.pg_tone
    before_chroma = state().appearance.rgba
    tone.muted_gain = -2.0
    tone.shadow_chroma = -2.0
    tone.tone_crossover = .50
    yield from wait_for(lambda: appearance_current(before_chroma),
                        "Shared Shader chroma controls did not refresh final appearance")
    for field, delta in (("saturation_crossover", (32, 0)), ("tone_crossover", (0, 18))):
        before_crossover = state().appearance.rgba
        appearance_captures = capture_jobs.count("appearance")
        crossover = getattr(tone, field)
        start = pointer.control_point(field, shared)
        yield from pointer.press_at(start, field, shared)
        end = start[0] + delta[0], start[1] + delta[1]
        pointer.event_at("MOUSEMOVE", "NOTHING", end)
        yield from wait_for(lambda: getattr(tone, field) > crossover,
                            f"{field} drag did not change its control")
        assert getattr(tone, field) > crossover
        pointer.event_at("LEFTMOUSE", "RELEASE", end)
        yield from wait_for(lambda: appearance_current(before_crossover),
                            f"{field} did not publish its exact appearance")
        assert capture_jobs.count("appearance") > appearance_captures
        assert capture_jobs.count("input") == input_captures
        report[field + "_exact_capture"] = True

    previous_appearance = state().appearance.rgba
    tone.tone_crossover = .20
    yield from wait_for(
        lambda: appearance_current(previous_appearance),
        "Lower tone crossover did not publish its exact appearance",
    )
    pointer.appearance_gain_point("highlight_chroma", shared)

    gain_fields = ("muted_gain", "vivid_gain", "shadow_chroma", "highlight_chroma")
    for field in gain_fields:
        before_gain = pointer.settings(shared).tone
        before_appearance = state().appearance.rgba
        appearance_captures = capture_jobs.count("appearance")
        start = pointer.control_point(field, shared)
        yield from pointer.press_at(start, field, shared)
        end = start[0] + 12, start[1]
        pointer.event_at("MOUSEMOVE", "NOTHING", end)
        yield from wait_for(
            lambda: getattr(pointer.settings(shared).tone, field) > getattr(before_gain, field),
            f"{field} drag did not change its control",
        )
        assert getattr(pointer.settings(shared).tone, field) > getattr(before_gain, field)
        assert all(getattr(pointer.settings(shared).tone, other) == getattr(before_gain, other)
                   for other in gain_fields if other != field)
        pointer.event_at("LEFTMOUSE", "RELEASE", end)
        # A gain can leave the sampled colors in the same density bins.
        yield from wait_for(
            lambda: appearance_current() and state().appearance.rgba is not before_appearance,
            f"{field} did not publish its exact appearance",
        )
        assert capture_jobs.count("appearance") > appearance_captures
        assert capture_jobs.count("input") == input_captures
        report[field + "_exact_capture"] = True


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
        assert time.monotonic() - started < 285.0
        return next(sequence)
    except StopIteration:
        pointer.close()
        report["passed"] = True
        checkpoint("passed")
        bpy.app.timers.register(request_quit, first_interval=0.1, persistent=True)
        return None
    except BaseException:
        report["error"] = traceback.format_exc()
        report["pointer_trace"] = pointer.diagnostics()
        try:
            pointer.close()
        except BaseException as error:
            report["cleanup_error"] = str(error)
        checkpoint("failed")
        print(report["error"], flush=True)
        os._exit(1)


bpy.app.timers.register(advance, first_interval=0.2, persistent=True)
