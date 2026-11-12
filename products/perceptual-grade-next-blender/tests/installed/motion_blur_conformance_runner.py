"""Verify center-frame Grade semantics with native scene motion blur."""

import addon_utils
import importlib
import json
from pathlib import Path
import sys

import bpy
import numpy as np


repository, report_path = map(Path, sys.argv[sys.argv.index("--") + 1:])
bpy.context.preferences.extensions.repos.new(
    name="Perceptual Grade motion blur test", module="pg_grade_motion_blur",
    custom_directory=str(repository),
)
extension = importlib.import_module("bl_ext.pg_grade_motion_blur.perceptual_grade")
nodes = importlib.import_module(extension.__name__ + ".nodes")
addon_utils.enable(extension.__name__, default_set=False)


def set_if_present(owner, name, value):
    if owner is not None and name in owner.bl_rna.properties:
        setattr(owner, name, value)
        return True
    return False


def motion_blur_owner(scene, engine):
    if engine == "CYCLES":
        return getattr(scene, "cycles", None)
    render = getattr(scene, "render", None)
    if engine in {"BLENDER_EEVEE", "BLENDER_EEVEE_NEXT"}:
        if render is not None and "use_motion_blur" in render.bl_rna.properties:
            return render
        return getattr(scene, "eevee", None)
    return render


def enable_motion_blur(scene, engine):
    owner = motion_blur_owner(scene, engine)
    set_if_present(owner, "motion_blur_shutter", 1.0)
    set_if_present(owner, "motion_blur_position", "CENTER")
    return set_if_present(owner, "use_motion_blur", True)


def disable_motion_blur(scene):
    for owner in (getattr(scene, "render", None), getattr(scene, "eevee", None),
                  getattr(scene, "cycles", None)):
        set_if_present(owner, "use_motion_blur", False)


def render_pixels(scene, time):
    frame = int(time)
    scene.frame_set(frame, subframe=time - frame)
    output_path = report_path.parent / "motion_blur_probe.exr"
    output_path.unlink(missing_ok=True)
    scene.render.filepath = str(output_path.with_suffix(""))
    scene.render.image_settings.file_format = "OPEN_EXR"
    result = bpy.ops.render.render("EXEC_DEFAULT", write_still=True)
    if result != {"FINISHED"} or not output_path.is_file():
        raise AssertionError(("Render produced no pixels", time, result,
                              scene.render.engine, output_path.exists()))
    image = bpy.data.images.load(str(output_path), check_existing=False)
    pixels = np.asarray(image.pixels[:], dtype=np.float32).reshape(
        (image.size[1], image.size[0], 4),
    )[2:-2, 2:-2, :3].copy()
    if image.users == 0:
        bpy.data.images.remove(image)
    return pixels


def prepare_grade(node, grade, time):
    frame = int(time)
    scene.frame_set(frame, subframe=time - frame)
    if nodes._is_shared_grade_node(node):
        node.pg_grade = grade
    failures = nodes._refresh_nodes((node,))
    assert not failures, (scene.render.engine, time, failures)
    failures = nodes._drain_preparations()
    assert not failures, (scene.render.engine, time, failures)
    assert not node.get(nodes._NODE_ERROR), (scene.render.engine, time, "Grade error")


def grade_error_present(grade_nodes):
    return any(node.get(nodes._NODE_ERROR) for node in grade_nodes)


def contains_error_magenta(pixels):
    return bool(np.any(
        (pixels[:, :, 0] > 0.99)
        & (pixels[:, :, 1] < 0.01)
        & (pixels[:, :, 2] > 0.99)
    ))


def link_shader_path(tree, source, grade_node, emission, *, use_grade):
    for link in tuple(tree.links):
        if (link.to_socket == emission.inputs["Color"]
                or (nodes._is_grade_node(link.to_node)
                    and link.to_socket == link.to_node.inputs["Color"])):
            tree.links.remove(link)
    if use_grade:
        tree.links.new(source.outputs["Color"], grade_node.inputs["Color"])
        tree.links.new(grade_node.outputs["Color"], emission.inputs["Color"])
    else:
        for link in tuple(tree.links):
            if link.to_socket == grade_node.inputs["Color"]:
                tree.links.remove(link)
        tree.links.new(source.outputs["Color"], emission.inputs["Color"])


def set_linear_interpolation(action):
    for layer in tuple(getattr(action, "layers", ())):
        for strip in tuple(layer.strips):
            for slot in tuple(action.slots):
                try:
                    bag = strip.channelbag(slot)
                except (AttributeError, RuntimeError, TypeError):
                    continue
                for curve in bag.fcurves:
                    for point in curve.keyframe_points:
                        point.interpolation = "LINEAR"
    for curve in tuple(getattr(action, "fcurves", ())):
        for point in curve.keyframe_points:
            point.interpolation = "LINEAR"


scene = bpy.context.scene
scene.render.use_compositing = False
scene.render.resolution_x = 32
scene.render.resolution_y = 32
scene.render.resolution_percentage = 100
scene.render.film_transparent = False
scene.view_settings.view_transform = "Standard"
scene.view_settings.look = "None"
scene.view_settings.exposure = 0.0
scene.view_settings.gamma = 1.0
for obj in tuple(bpy.data.objects):
    bpy.data.objects.remove(obj, do_unlink=True)

mesh = bpy.data.meshes.new("Temporal probe mesh")
mesh.from_pydata(((-0.45, -0.45, 0), (0.45, -0.45, 0),
                  (0.45, 0.45, 0), (-0.45, 0.45, 0)), (), ((0, 1, 2, 3),))
mesh.update()
obj = bpy.data.objects.new("Temporal probe", mesh)
scene.collection.objects.link(obj)
for frame, x in ((1, -0.6), (2, 0.0), (3, 0.6)):
    obj.location.x = x
    obj.keyframe_insert(data_path="location", frame=frame)
camera_data = bpy.data.cameras.new("Temporal probe camera")
camera_data.type = "ORTHO"
camera_data.ortho_scale = 2.4
camera = bpy.data.objects.new("Temporal probe camera", camera_data)
scene.collection.objects.link(camera)
camera.location = (0.0, 0.0, 5.0)
scene.camera = camera

material = bpy.data.materials.new("Temporal probe material")
material.use_nodes = True
tree = material.node_tree
tree.nodes.clear()
color_node = tree.nodes.new("ShaderNodeRGB")
color_node.outputs["Color"].default_value = (0.04, 0.08, 0.12, 1.0)
shader_grade_node = nodes.create_node(tree)
emission = tree.nodes.new("ShaderNodeEmission")
output = tree.nodes.new("ShaderNodeOutputMaterial")
link_shader_path(tree, color_node, shader_grade_node, emission, use_grade=True)
tree.links.new(emission.outputs["Emission"], output.inputs["Surface"])
obj.data.materials.append(material)
animated_shader_grade_node = nodes.create_per_node_node(tree)
static_grade = bpy.data.node_groups.new(
    "Static motion blur Grade", nodes.PGGradeData.bl_idname,
)
shader_grade_node.pg_grade = static_grade
for frame, exposure in ((1, 0.0), (3, 4.0)):
    scene.frame_set(frame)
    animated_shader_grade_node.exposure = exposure
    path = animated_shader_grade_node.path_from_id() + ".exposure"
    assert tree.keyframe_insert(data_path=path, frame=frame)
set_linear_interpolation(tree.animation_data.action)

compositor_tree = bpy.data.node_groups.new(
    "Motion blur Grade compositor", nodes.COMPOSITOR_TREE,
)
compositor_tree.interface.new_socket(
    name="Image", in_out="OUTPUT", socket_type="NodeSocketColor",
)
compositor_output = compositor_tree.nodes.new("NodeGroupOutput")
compositor_source = compositor_tree.nodes.new("CompositorNodeRLayers")
compositor_source.scene = scene
compositor_source.layer = scene.view_layers[0].name
compositor_grade_node = nodes.create_node(compositor_tree)
compositor_grade_node.pg_grade = static_grade
animated_compositor_grade_node = nodes.create_per_node_node(compositor_tree)
for frame, exposure in ((1, 0.0), (3, 4.0)):
    scene.frame_set(frame)
    animated_compositor_grade_node.exposure = exposure
    path = animated_compositor_grade_node.path_from_id() + ".exposure"
    assert compositor_tree.keyframe_insert(data_path=path, frame=frame)
set_linear_interpolation(compositor_tree.animation_data.action)
compositor_tree.links.new(
    compositor_source.outputs["Image"], compositor_grade_node.inputs["Color"],
)
compositor_tree.links.new(
    compositor_grade_node.outputs["Color"], compositor_output.inputs["Image"],
)
scene.compositing_node_group = compositor_tree
set_if_present(scene.render, "compositor_device", "CPU")

grade_nodes = (shader_grade_node, animated_shader_grade_node,
               compositor_grade_node, animated_compositor_grade_node)
failures = nodes._refresh_nodes(grade_nodes)
assert not failures, failures
failures = nodes._drain_preparations()
assert not failures, failures

cycles_activation_error = None
try:
    addon_utils.enable("cycles", default_set=False)
except Exception as error:
    cycles_activation_error = repr(error)

engine_items = scene.render.bl_rna.properties["engine"].enum_items
engine_ids = {item.identifier for item in engine_items}
eevee = next((name for name in ("BLENDER_EEVEE_NEXT", "BLENDER_EEVEE")
              if name in engine_ids), None)
if eevee is None:
    raise AssertionError(("EEVEE is unavailable", sorted(engine_ids)))
engines = (eevee, "CYCLES") if "CYCLES" in engine_ids else (eevee,)
for engine in engines:
    scene.render.engine = engine
    set_if_present(getattr(scene, "cycles", None), "samples", 4)
    set_if_present(getattr(scene, "eevee", None), "taa_render_samples", 1)
    set_if_present(scene.render, "threads_mode", "FIXED")
    set_if_present(scene.render, "threads", 1)
    if not enable_motion_blur(scene, engine):
        raise AssertionError((engine, "motion blur could not be enabled"))

report = {
    "blender": list(bpy.app.version[:3]),
    "engines": list(engines),
    "cycles_activation_error": cycles_activation_error,
    "times": [1.5, 2.5],
    "shader_grade": {"engines": {}},
    "compositor_grade": {"engines": {}},
}
old_engine = scene.render.engine
old_frame = scene.frame_current
old_subframe = float(scene.frame_subframe)
old_range = (scene.frame_start, scene.frame_end, scene.frame_step)
try:
    scene.frame_start, scene.frame_end, scene.frame_step = (1, 3, 1)
    for engine in engines:
        scene.render.engine = engine
        set_if_present(getattr(scene, "cycles", None), "samples", 4)
        set_if_present(getattr(scene, "eevee", None), "taa_render_samples", 1)
        for mode, target_node, static_node, use_compositing in (
                ("shader_grade", animated_shader_grade_node,
                 shader_grade_node, False),
                ("compositor_grade", animated_compositor_grade_node,
                 compositor_grade_node, True)):
            scene.render.use_compositing = use_compositing
            link_shader_path(tree, color_node, static_node, emission,
                             use_grade=not use_compositing)
            mode_results = {}
            for time in report["times"]:
                frame = int(time)
                scene.frame_set(frame, subframe=time - frame)
                exposure = float(target_node.exposure)
                expected_exposure = 2.0 * (time - 1.0)
                assert abs(exposure - expected_exposure) <= 1e-6, (
                    engine, mode, time, exposure, expected_exposure,
                )
                static_copy = nodes._make_grade(target_node)
                assert abs(float(static_copy.pg_linear.exposure) - exposure) <= 1e-6

                if use_compositing:
                    for link in tuple(compositor_tree.links):
                        if link.to_socket in (compositor_grade_node.inputs["Color"],
                                              animated_compositor_grade_node.inputs["Color"],
                                              compositor_output.inputs["Image"]):
                            compositor_tree.links.remove(link)
                    compositor_tree.links.new(compositor_source.outputs["Image"],
                                              static_node.inputs["Color"])
                    compositor_tree.links.new(static_node.outputs["Color"],
                                              compositor_output.inputs["Image"])
                else:
                    link_shader_path(tree, color_node, static_node, emission, use_grade=True)
                prepare_grade(static_node, static_copy, time)
                static_blur = render_pixels(scene, time)
                if use_compositing:
                    for link in tuple(compositor_tree.links):
                        if link.to_socket in (compositor_grade_node.inputs["Color"],
                                              animated_compositor_grade_node.inputs["Color"],
                                              compositor_output.inputs["Image"]):
                            compositor_tree.links.remove(link)
                    compositor_tree.links.new(compositor_source.outputs["Image"],
                                              target_node.inputs["Color"])
                    compositor_tree.links.new(target_node.outputs["Color"],
                                              compositor_output.inputs["Image"])
                else:
                    link_shader_path(tree, color_node, target_node, emission, use_grade=True)
                prepare_grade(target_node, None, time)
                animated_blur = render_pixels(scene, time)
                frame_error = float(np.max(np.abs(animated_blur - static_blur)))
                assert frame_error <= 0.005, (engine, mode, time, frame_error)
                assert not grade_error_present(grade_nodes), (engine, mode, time)
                assert not contains_error_magenta(animated_blur), (engine, mode, time)

                blur_still_delta = None
                if time == 1.5:
                    disable_motion_blur(scene)
                    if use_compositing:
                        for link in tuple(compositor_tree.links):
                            if link.to_socket in (compositor_grade_node.inputs["Color"],
                                                  animated_compositor_grade_node.inputs["Color"],
                                                  compositor_output.inputs["Image"]):
                                compositor_tree.links.remove(link)
                        compositor_tree.links.new(compositor_source.outputs["Image"],
                                                  static_node.inputs["Color"])
                        compositor_tree.links.new(static_node.outputs["Color"],
                                                  compositor_output.inputs["Image"])
                    else:
                        link_shader_path(tree, color_node, static_node, emission,
                                         use_grade=True)
                    prepare_grade(static_node, static_copy, time)
                    still = render_pixels(scene, time)
                    blur_still_delta = float(np.max(np.abs(static_blur - still)))
                    assert blur_still_delta > 0.02, (
                        engine, mode, "scene motion did not change rendered pixels",
                        blur_still_delta,
                    )
                    assert enable_motion_blur(scene, engine)

                mode_results[str(time)] = {
                    "exposure": exposure,
                    "mean_rgb": np.mean(animated_blur, axis=(0, 1)).tolist(),
                    "max_animated_vs_static_error": frame_error,
                    "motion_blur_vs_still_delta": blur_still_delta,
                }
            first_rgb = np.asarray(mode_results["1.5"]["mean_rgb"])
            last_rgb = np.asarray(mode_results["2.5"]["mean_rgb"])
            animated_output_delta = float(np.max(np.abs(last_rgb - first_rgb)))
            assert animated_output_delta > 0.02, (
                engine, mode, "animated Grade did not change output between times",
                animated_output_delta,
            )
            report[mode]["engines"][engine] = {
                "samples": mode_results,
                "max_time_output_delta": animated_output_delta,
            }
finally:
    scene.render.engine = old_engine
    scene.frame_start, scene.frame_end, scene.frame_step = old_range
    scene.frame_set(old_frame, subframe=old_subframe)

report_path.parent.mkdir(parents=True, exist_ok=True)
report_path.write_text(json.dumps(report, indent=2))
