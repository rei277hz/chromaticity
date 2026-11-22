"""Drive direct and evaluated compositor Color inputs through Blender's GUI."""

import addon_utils
import importlib
import json
import os
from pathlib import Path
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
vectorscope_ui = importlib.import_module(extension.__name__ + ".vectorscope_ui")
errors = []
assert addon_utils.enable(
    extension.__name__, default_set=False, handle_error=errors.append
) is extension, errors
assert not errors and not bpy.app.background, errors

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
    linear = np.asarray(color[:3]) * (2.0 ** exposure)
    code = np.where(linear < 0.018, 4.5 * linear,
                    1.099 * linear ** 0.45 - 0.099)
    luma = np.dot(code, (0.2126, 0.7152, 0.0722))
    cr = (code[0] - luma) / 1.5748
    cb = (code[2] - luma) / 1.8556
    return tuple(int((component + 0.65) * 144 / 1.3) for component in (cr, cb))


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

backend = vectorscope_ui._runtime.backend
create_job = backend.create_job


def track_helper_job(*args, **kwargs):
    report["helper_jobs"] = report.get("helper_jobs", 0) + 1
    return create_job(*args, **kwargs)


backend.create_job = track_helper_job

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


def snapshot():
    value = state()
    assert value is not None, "The selected Grade has no vectorscope display state"
    brightness = np.asarray(value.brightness)
    assert brightness.shape == (144, 144), brightness.shape
    assert np.isfinite(brightness).all(), "The vectorscope contains nonfinite density"
    assert value.status != "error", value.error
    return value, brightness.copy()


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


def scenario():
    checkpoint("enable vectorscope")
    with bpy.context.temp_override(window=window, area=area, region=region):
        assert bpy.ops.perceptual_grade.toggle_vectorscope() == {"FINISHED"}

    yield from wait_for(lambda: current(RED), "Direct Image input did not plot red")
    _, initial = snapshot()
    assert np.sum(initial) > 0.0, "The direct Image input produced an empty plot"
    report["initial_shape"] = list(initial.shape)
    report["direct_image_visible"] = True
    report["direct_sampling_avoids_helper"] = report.get("helper_jobs", 0) == 0
    assert report["direct_sampling_avoids_helper"], "Direct Image sampling started a helper job"

    grade.exposure = 1.0
    yield from wait_for(lambda: current(RED, 1.0), "Linear exposure did not move the red peak")
    _, exposed = snapshot()
    report["linear_edit_refreshed"] = not np.array_equal(initial, exposed)
    assert report["linear_edit_refreshed"]
    grade.exposure = 0.0
    yield from wait_for(lambda: current(RED), "Restoring exposure did not refresh the plot")

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
    report["stopped_frame"] = stopped_frame


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
        next(sequence)
        return 0.02
    except StopIteration:
        cleanup()
        report["passed"] = True
        checkpoint("passed")
        bpy.app.timers.register(request_quit, first_interval=0.1, persistent=True)
        return None
    except BaseException:
        report["error"] = traceback.format_exc()
        try:
            cleanup()
        except BaseException as error:
            report["cleanup_error"] = str(error)
        checkpoint("failed")
        print(report["error"], flush=True)
        os._exit(1)


bpy.app.timers.register(advance, first_interval=0.2, persistent=True)
