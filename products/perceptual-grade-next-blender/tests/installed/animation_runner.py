"""Verify continuous native animation rendering with per-frame Grade preflight."""

import addon_utils
import importlib
import json
from pathlib import Path
import sys
import time

import bpy
import numpy as np


repository, report_path, mode = sys.argv[sys.argv.index("--") + 1:]
repository, report_path = Path(repository), Path(report_path)
bpy.context.preferences.extensions.repos.new(
    name="Perceptual Grade animation test", module="pg_grade_animation",
    custom_directory=str(repository),
)
extension = importlib.import_module("bl_ext.pg_grade_animation.perceptual_grade")
nodes = importlib.import_module(extension.__name__ + ".nodes")
addon_utils.enable(extension.__name__, default_set=False)

scene = bpy.context.scene
scene.render.engine = "BLENDER_EEVEE"
scene.render.use_compositing = True
scene.render.compositor_device = "CPU"
scene.render.compositor_precision = "FULL"
scene.render.resolution_x = 16
scene.render.resolution_y = 16
scene.render.resolution_percentage = 100
scene.render.film_transparent = False
scene.view_settings.view_transform = "Standard"
scene.view_settings.look = "None"
scene.view_settings.exposure = 0.0
scene.view_settings.gamma = 1.0

old_auto_key = scene.tool_settings.use_keyframe_insert_auto
old_compositing_group = scene.compositing_node_group
old_frame = scene.frame_current
old_subframe = float(scene.frame_subframe)
old_range = (scene.frame_start, scene.frame_end, scene.frame_step)
for obj in tuple(bpy.data.objects):
    bpy.data.objects.remove(obj, do_unlink=True)

material = bpy.data.materials.new("Animated Grade test material")
material.use_nodes = True
shader_node = nodes.create_per_node_node(material.node_tree)
rgb = material.node_tree.nodes.new("ShaderNodeRGB")
rgb.outputs["Color"].default_value = (0.04, 0.08, 0.12, 1.0)
emission = material.node_tree.nodes.new("ShaderNodeEmission")
material_output = material.node_tree.nodes.get("Material Output")
material.node_tree.links.new(rgb.outputs["Color"], shader_node.inputs["Color"])
material.node_tree.links.new(shader_node.outputs["Color"], emission.inputs["Color"])
material.node_tree.links.new(emission.outputs["Emission"], material_output.inputs["Surface"])

mesh = bpy.data.meshes.new("Animated Grade test mesh")
mesh.from_pydata(((-1, -1, 0), (1, -1, 0), (1, 1, 0), (-1, 1, 0)), (), ((0, 1, 2, 3),))
mesh.update()
obj = bpy.data.objects.new("Animated Grade test object", mesh)
scene.collection.objects.link(obj)
obj.data.materials.append(material)
camera_data = bpy.data.cameras.new("Animated Grade test camera")
camera_data.type = "ORTHO"
camera_data.ortho_scale = 2.8
camera = bpy.data.objects.new("Animated Grade test camera", camera_data)
scene.collection.objects.link(camera)
camera.location = (0.0, 0.0, 5.0)
scene.camera = camera

compositor_tree = bpy.data.node_groups.new(
    "Animated Grade test compositor", nodes.COMPOSITOR_TREE,
)
compositor_tree.interface.new_socket(
    name="Image", in_out="OUTPUT", socket_type="NodeSocketColor",
)
compositor_output = compositor_tree.nodes.new("NodeGroupOutput")
compositor_source = compositor_tree.nodes.new("CompositorNodeRLayers")
compositor_source.scene = scene
compositor_source.layer = scene.view_layers[0].name
compositor_node = nodes.create_per_node_node(compositor_tree)
compositor_tree.links.new(compositor_source.outputs["Image"], compositor_node.inputs["Color"])
compositor_tree.links.new(compositor_node.outputs["Color"], compositor_output.inputs["Image"])
scene.compositing_node_group = compositor_tree

failures = nodes._refresh_nodes((shader_node, compositor_node))
assert not failures, failures
failures = nodes._drain_preparations()
assert not failures, failures

# Auto Key is captured at gesture press and inserted at the captured frame.
scene.frame_set(6)
scene.tool_settings.use_keyframe_insert_auto = True
window_key = 744
gesture_token = nodes._begin_gesture(window_key, shader_node)
gesture_targets = nodes._live_gesture_targets(nodes._gesture_related_nodes(shader_node))
nodes._gesture_keyframe_baselines[gesture_token] = nodes._capture_gesture_keyframe_baseline(
    tuple(nodes.gesture_policy.Target(nodes._gesture_identity(target), None)
          for target in gesture_targets)
)
shader_node.exposure = 1.25
scene.frame_set(8)
scene.tool_settings.use_keyframe_insert_auto = False
nodes._end_gesture(window_key, gesture_token)
animation_data = material.node_tree.animation_data
assert animation_data is not None and animation_data.action is not None
strip = animation_data.action.layers[0].strips[0]
exposure_path = shader_node.path_from_id() + ".exposure"
curve = next(item for item in strip.channelbag(animation_data.action_slot).fcurves
             if item.data_path == exposure_path)
assert any(abs(point.co.x - 6) < 1e-6 and abs(point.co.y - 1.25) < 1e-6
           for point in curve.keyframe_points)

scene.tool_settings.use_keyframe_insert_auto = old_auto_key
failures = nodes._refresh_nodes((shader_node, compositor_node))
assert not failures, failures
failures = nodes._drain_preparations()
assert not failures, failures

for frame, exposure in ((1, 0.0), (3, 2.0)):
    scene.frame_set(frame)
    shader_node.exposure = exposure
    compositor_node.exposure = exposure
    shader_node.fit = -0.5 if frame == 1 else 0.5
    assert material.node_tree.keyframe_insert(data_path=exposure_path, frame=frame)
    fit_path = shader_node.path_from_id() + ".fit"
    assert material.node_tree.keyframe_insert(data_path=fit_path, frame=frame)
    compositor_path = compositor_node.path_from_id() + ".exposure"
    assert compositor_tree.keyframe_insert(data_path=compositor_path, frame=frame)


def action_curve(owner, data_path):
    animation_data = owner.animation_data
    strip = animation_data.action.layers[0].strips[0]
    return next(item for item in strip.channelbag(animation_data.action_slot).fcurves
                if item.data_path == data_path)


for curve in (action_curve(material.node_tree, exposure_path),
              action_curve(material.node_tree, fit_path),
              action_curve(compositor_tree, compositor_path)):
    for point in curve.keyframe_points:
        point.interpolation = "LINEAR"
for frame, expected in ((1, 0.0), (2, 1.0), (3, 2.0)):
    scene.frame_set(frame)
    assert abs(shader_node.exposure - expected) < 1e-6, (
        frame, shader_node.exposure, expected,
    )
    assert abs(shader_node.fit - (expected / 2.0 - 0.5)) < 1e-6, (
        frame, shader_node.fit, expected,
    )
    assert abs(compositor_node.exposure - expected) < 1e-6, (
        frame, compositor_node.exposure, expected,
    )
animated_nodes, _, _ = nodes._animation_snapshot(scene)
assert shader_node in animated_nodes and compositor_node in animated_nodes

# Blender should keep node property paths attached to a renamed node.
shader_node.name = "Animated Shader Grade Renamed"
exposure_path = shader_node.path_from_id() + ".exposure"
fit_path = shader_node.path_from_id() + ".fit"
assert len(action_curve(material.node_tree, exposure_path).keyframe_points) == 3
assert len(action_curve(material.node_tree, fit_path).keyframe_points) == 2

# Exercise the actual .blend persistence boundary for both tree Actions.
scene.frame_start, scene.frame_end, scene.frame_step = (1, 3, 1)
scene.frame_set(2, subframe=0.25)
tree_names = material.name, compositor_tree.name
node_names = shader_node.name, compositor_node.name
saved_file = report_path.parent / "animated-grade-roundtrip.blend"
assert bpy.ops.wm.save_as_mainfile(filepath=str(saved_file)) == {"FINISHED"}
assert bpy.ops.wm.open_mainfile(filepath=str(saved_file)) == {"FINISHED"}

scene = bpy.context.scene
material = bpy.data.materials[tree_names[0]]
compositor_tree = bpy.data.node_groups[tree_names[1]]
obj = scene.objects["Animated Grade test object"]
shader_node = material.node_tree.nodes[node_names[0]]
compositor_node = compositor_tree.nodes[node_names[1]]
exposure_path = shader_node.path_from_id() + ".exposure"
fit_path = shader_node.path_from_id() + ".fit"
compositor_path = compositor_node.path_from_id() + ".exposure"
assert len(action_curve(material.node_tree, exposure_path).keyframe_points) == 3
assert len(action_curve(material.node_tree, fit_path).keyframe_points) == 2
assert len(action_curve(compositor_tree, compositor_path).keyframe_points) == 2

scene.frame_set(2, subframe=0.25)
assert abs(shader_node.exposure - 1.25) < 1e-6
assert abs(shader_node.fit - 0.125) < 1e-6
assert abs(compositor_node.exposure - 1.25) < 1e-6
failures = nodes._refresh_nodes((shader_node, compositor_node))
assert not failures, failures
failures = nodes._drain_preparations()
assert not failures, failures
reopened_nodes, reopened_signatures, _ = nodes._animation_snapshot(scene)
assert shader_node in reopened_nodes and compositor_node in reopened_nodes
assert nodes._animation_outputs_current(reopened_nodes, reopened_signatures) == (True, None)

# Key insertion failures must be visible on the affected node, then clear after
# a later successful Auto Key operation.
gesture_identity = nodes._gesture_identity(shader_node)
gesture_token = 991
current_exposure = float(shader_node.exposure)
original_insert_node_keyframes = nodes._insert_node_keyframes


def fail_keyframe_insertion(*_args):
    raise RuntimeError("simulated keyframe insertion failure")


try:
    nodes._insert_node_keyframes = fail_keyframe_insertion
    nodes._gesture_keyframe_baselines[gesture_token] = {
        gesture_identity: {"exposure": current_exposure - 1.0},
    }
    nodes._keyframe_gesture(gesture_token, 2.25)
    assert shader_node.get(nodes._NODE_ANIMATION_ERROR)

    nodes._insert_node_keyframes = lambda *_args: None
    nodes._gesture_keyframe_baselines[gesture_token] = {
        gesture_identity: {"exposure": current_exposure - 1.0},
    }
    nodes._keyframe_gesture(gesture_token, 2.25)
    assert not shader_node.get(nodes._NODE_ANIMATION_ERROR)
finally:
    nodes._insert_node_keyframes = original_insert_node_keyframes

saved_time = (scene.frame_current, float(scene.frame_subframe))
saved_range = (scene.frame_start, scene.frame_end, scene.frame_step)
receipts = []
render_starts = []
render_completions = []
render_cancellations = []
render_writes = []


def on_render_pre(current_scene, *_args):
    frame = int(current_scene.frame_current)
    receipt = {"frame": frame}
    if bpy.app.background:
        try:
            frame_nodes, signatures, signature = nodes._animation_snapshot(current_scene)
            ready, error = nodes._animation_outputs_current(frame_nodes, signatures)
            receipt.update(
                exposure=float(shader_node.exposure),
                compositor_exposure=float(compositor_node.exposure),
                signature=signature,
                ready=ready, error=error,
            )
        except Exception as error:
            receipt["error"] = str(error)
    receipts.append(receipt)


def on_render_init(current_scene, *_args):
    render_starts.append(int(current_scene.as_pointer()))


def on_render_complete(current_scene, *_args):
    render_completions.append(int(current_scene.as_pointer()))


def on_render_cancel(current_scene, *_args):
    render_cancellations.append(int(current_scene.as_pointer()))


def on_render_write(current_scene, *_args):
    render_writes.append(int(current_scene.frame_current))


bpy.app.handlers.render_pre.append(on_render_pre)
bpy.app.handlers.render_init.append(on_render_init)
bpy.app.handlers.render_complete.append(on_render_complete)
bpy.app.handlers.render_cancel.append(on_render_cancel)
bpy.app.handlers.render_write.append(on_render_write)

sequence_prefix = report_path.parent / "grade_sequence_"
movie_prefix = report_path.parent / "grade_movie"
repeat_prefix = report_path.parent / "grade_repeat_"
file_formats = scene.render.image_settings.bl_rna.properties["file_format"].enum_items
movie_supported = any(item.identifier == "FFMPEG" for item in file_formats)
state = {"phase": "sequence", "result": None, "error": None, "run": None}


def finish_test():
    try:
        assert state["error"] is None, state["error"]
        assert len(render_starts) == 2, render_starts
        assert len(render_completions) == 2, render_completions
        assert [item["frame"] for item in receipts] == [1, 2, 3, 1, 2, 3], receipts
        assert render_writes == [1, 2, 3, 1, 2, 3], render_writes
        assert (scene.frame_current, float(scene.frame_subframe)) == saved_time
        assert (scene.frame_start, scene.frame_end, scene.frame_step) == saved_range
        if bpy.app.background:
            assert all(item.get("ready") for item in receipts), receipts
            assert all(item.get("error") is None for item in receipts), receipts
            assert [round(item["exposure"], 4) for item in receipts[:3]] == [
                0.0, 1.0, 2.0,
            ], receipts
            assert [round(item["compositor_exposure"], 4) for item in receipts[:3]] == [
                0.0, 1.0, 2.0,
            ], receipts
            assert len({item["signature"] for item in receipts[:3]}) == 3, receipts

        sequence_files = sorted(report_path.parent.glob("grade_sequence_*.png"))
        assert len(sequence_files) == 3, sequence_files
        repeat_files = tuple(sorted(report_path.parent.glob("grade_repeat_*.png")))
        levels = []
        for path in sequence_files:
            image = bpy.data.images.load(str(path), check_existing=False)
            pixels = np.asarray(image.pixels[:], dtype=np.float32).reshape((-1, 4))
            levels.append(float(pixels[:, :3].mean()))
            bpy.data.images.remove(image)
        assert len({round(level, 5) for level in levels}) == 3, levels
        if not movie_supported:
            repeated_levels = []
            for path in sorted(repeat_files):
                image = bpy.data.images.load(str(path), check_existing=False)
                pixels = np.asarray(image.pixels[:], dtype=np.float32).reshape((-1, 4))
                repeated_levels.append(float(pixels[:, :3].mean()))
                bpy.data.images.remove(image)
            assert len({round(level, 5) for level in repeated_levels}) == 3, (
                repeated_levels,
            )
        movie_files = tuple(path for path in report_path.parent.glob("grade_movie*")
                            if path.is_file())
        movie_bytes = 0
        if movie_supported:
            assert len(movie_files) == 1 and movie_files[0].stat().st_size > 0, movie_files
            movie_bytes = movie_files[0].stat().st_size
        else:
            assert not movie_files, movie_files
            assert len(repeat_files) == 3, repeat_files
        report_path.write_text(json.dumps({
            "animation": "continuous-native-verified",
            "blender": list(bpy.app.version[:3]), "mode": mode,
            "frames": [item["frame"] for item in receipts],
            "render_starts": len(render_starts), "render_writes": render_writes,
            "sequence_levels": levels, "movie_supported": movie_supported,
            "movie_bytes": movie_bytes,
        }))
    except Exception as error:
        state["error"] = str(error)
        report_path.write_text(json.dumps({"error": state["error"], "receipts": receipts}))
    finally:
        for callback, collection in (
            (on_render_pre, bpy.app.handlers.render_pre),
            (on_render_init, bpy.app.handlers.render_init),
            (on_render_complete, bpy.app.handlers.render_complete),
            (on_render_cancel, bpy.app.handlers.render_cancel),
            (on_render_write, bpy.app.handlers.render_write),
        ):
            if callback in collection:
                collection.remove(callback)
        scene.tool_settings.use_keyframe_insert_auto = old_auto_key
        scene.frame_start, scene.frame_end, scene.frame_step = old_range
        scene.frame_set(old_frame, subframe=old_subframe)
        scene.compositing_node_group = old_compositing_group
        if not bpy.app.background:
            bpy.app.timers.register(_quit_when_idle, first_interval=0.1)


def _quit_when_idle():
    if any(bpy.app.is_job_running(name) for name in
           ("RENDER", "RENDER_PREVIEW", "COMPOSITE")):
        return 0.1
    addon_utils.disable(extension.__name__, default_set=False)
    bpy.ops.wm.quit_blender()
    return None


def begin_render():
    global movie_supported
    if state["phase"] == "sequence":
        scene.render.image_settings.file_format = "PNG"
        scene.render.filepath = str(sequence_prefix)
    elif state["phase"] == "movie":
        if movie_supported:
            try:
                scene.render.image_settings.file_format = "FFMPEG"
                scene.render.ffmpeg.format = "MPEG4"
                scene.render.ffmpeg.codec = "H264"
                scene.render.filepath = str(movie_prefix)
            except (TypeError, ValueError):
                movie_supported = False
        if not movie_supported:
            scene.render.image_settings.file_format = "PNG"
            scene.render.filepath = str(repeat_prefix)
    else:
        return None
    state["run"] = {
        "phase": state["phase"],
        "starts_before": len(render_starts),
        "completions_before": len(render_completions),
        "cancellations_before": len(render_cancellations),
        "deadline": time.monotonic() + 270.0,
    }
    try:
        if bpy.app.background:
            state["result"] = bpy.ops.render.render("EXEC_DEFAULT", animation=True)
            if state["phase"] == "sequence":
                state["phase"], state["result"] = "movie", None
                state["run"] = None
                return begin_render()
            finish_test()
            return None
        state["result"] = bpy.ops.render.render(
            "INVOKE_DEFAULT", scene=scene.name, animation=True,
        )
        return None
    except Exception as error:
        state["error"] = str(error)
        finish_test()
        return None


def monitor_gui():
    run = state["run"]
    if run is None:
        return 0.05
    if len(render_cancellations) > run["cancellations_before"]:
        state["error"] = "Native animation render was cancelled"
        finish_test()
        return None
    if len(render_starts) == run["starts_before"]:
        if time.monotonic() >= run["deadline"]:
            state["error"] = "Native animation render did not initialize"
            finish_test()
            return None
        return 0.05
    if len(render_completions) == run["completions_before"]:
        if time.monotonic() >= run["deadline"]:
            state["error"] = "Native animation render did not complete"
            finish_test()
            return None
        return 0.05
    if run["phase"] == "sequence":
        state["phase"], state["result"] = "movie", None
        state["run"] = None
        begin_render()
        return 0.05
    finish_test()
    return None


if bpy.app.background:
    begin_render()
else:
    bpy.app.timers.register(begin_render, first_interval=0.5)
    bpy.app.timers.register(monitor_gui, first_interval=0.1, persistent=True)
