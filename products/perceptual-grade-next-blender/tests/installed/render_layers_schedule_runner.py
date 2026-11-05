"""Verify Grade changes reschedule Render Layers compositor output while dragging."""

import addon_utils
import hashlib
import importlib
import json
import sys
import time
import traceback
from array import array
from pathlib import Path

import bpy


repository, report_path = map(Path, sys.argv[sys.argv.index("--") + 1:])
bpy.context.preferences.view.show_splash = False
bpy.context.preferences.extensions.repos.new(
    name="Perceptual Grade Render Layers test", module="pg_render_layers",
    custom_directory=str(repository),
)
extension = importlib.import_module("bl_ext.pg_render_layers.perceptual_grade")
nodes = importlib.import_module(extension.__name__ + ".nodes")
errors = []
assert addon_utils.enable(
    extension.__name__, default_set=False, handle_error=errors.append
) is extension
assert not errors and not bpy.app.background, errors

SCENE_TREE = "Render Layers Grade Root"
GRADE_NAME = "Rendered Grade"
events = []
render_count = 0
report = {
    "passed": False,
    "accepted_exposure": [],
    "evaluations": [],
    "render_count": 0,
}


def exposure():
    return float(bpy.data.node_groups[GRADE_NAME].pg_linear.exposure)


def on_composite_pre(scene, *_args):
    events.append({
        "scene": scene.as_pointer(),
        "exposure_at_start": exposure(),
        "started": time.monotonic(),
        "finished": None,
    })


def on_composite_post(scene, *_args):
    pointer = scene.as_pointer()
    index = next((i for i, item in enumerate(events)
                  if item["scene"] == pointer and item["finished"] is None), None)
    if index is None:
        return
    events[index]["finished"] = time.monotonic()


def on_render_init(*_args):
    global render_count
    render_count += 1


bpy.app.handlers.composite_pre.append(on_composite_pre)
bpy.app.handlers.composite_post.append(on_composite_post)
bpy.app.handlers.render_init.append(on_render_init)


def setup_scene():
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_EEVEE"
    scene.render.use_compositing = True
    scene.render.compositor_device = "CPU"
    scene.render.compositor_precision = "FULL"
    scene.render.resolution_x = 200
    scene.render.resolution_y = 150
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.film_transparent = False
    scene.view_settings.view_transform = "Standard"
    scene.view_settings.look = "None"
    scene.view_settings.exposure = 0.0
    scene.view_settings.gamma = 1.0

    for obj in tuple(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)

    mesh = bpy.data.meshes.new("Render Layers source mesh")
    mesh.from_pydata(((-2, -2, 0), (2, -2, 0), (2, 2, 0), (-2, 2, 0)), (), ((0, 1, 2, 3),))
    surface = bpy.data.objects.new("Render Layers source", mesh)
    scene.collection.objects.link(surface)
    material = bpy.data.materials.new("Render Layers emission")
    material.use_nodes = True
    emission = material.node_tree.nodes.new("ShaderNodeEmission")
    emission.inputs["Color"].default_value = (0.18, 0.08, 0.03, 1.0)
    output = material.node_tree.nodes.get("Material Output")
    material.node_tree.links.new(emission.outputs["Emission"], output.inputs["Surface"])
    surface.data.materials.append(material)

    camera_data = bpy.data.cameras.new("Render Layers camera")
    camera_data.type = "ORTHO"
    camera_data.ortho_scale = 5.0
    camera = bpy.data.objects.new("Render Layers camera", camera_data)
    scene.collection.objects.link(camera)
    camera.location = (0.0, 0.0, 5.0)
    scene.camera = camera

    world = bpy.data.worlds.new("Render Layers world")
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs["Color"].default_value = (0.01, 0.01, 0.01, 1.0)
    world.node_tree.nodes["Background"].inputs["Strength"].default_value = 1.0
    scene.world = world

    root = bpy.data.node_groups.new(SCENE_TREE, nodes.COMPOSITOR_TREE)
    root.interface.new_socket(name="Image", in_out="OUTPUT", socket_type="NodeSocketColor")
    output_node = root.nodes.new("NodeGroupOutput")
    source = root.nodes.new("CompositorNodeRLayers")
    source.scene = scene
    source.layer = scene.view_layers[0].name
    grade_data = nodes._make_grade()
    grade_data.name = GRADE_NAME
    grade = nodes.create_node(root)
    grade.name = "Rendered Grade Node"
    grade.pg_grade = grade_data
    viewer = root.nodes.new("CompositorNodeViewer")
    root.links.new(source.outputs["Image"], grade.inputs["Color"])
    root.links.new(grade.outputs["Color"], viewer.inputs["Image"])
    root.links.new(grade.outputs["Color"], output_node.inputs["Image"])
    root.nodes.active = grade
    scene.compositing_node_group = root

    area = next(area for area in bpy.context.window.screen.areas if area.type == "VIEW_3D")
    area.type = "NODE_EDITOR"
    area.ui_type = "CompositorNodeTree"
    area.spaces.active.show_region_ui = True
    area.spaces.active.show_backdrop = True
    area.spaces.active.edit_tree.nodes.active = grade
    return area, grade


area, _grade_node = setup_scene()
bpy.ops.render.render("EXEC_DEFAULT", write_still=False)
baseline_render_count = render_count
report["initial_render_count"] = baseline_render_count
events.clear()


def current_area():
    return next(item for item in bpy.context.window.screen.areas
                if item.as_pointer() == area.as_pointer())


def viewer_image():
    image = bpy.data.images.get("Viewer Node")
    if image is None or image.type != "COMPOSITING" or not image.has_data:
        return None
    return image


def viewer_hash():
    image = viewer_image()
    if image is None or tuple(image.size) != (200, 150):
        return None
    return hashlib.sha256(array("f", image.pixels[:]).tobytes()).hexdigest()


def viewer_range():
    image = viewer_image()
    if image is None:
        return None
    pixels = array("f", image.pixels[:])
    return [min(pixels), max(pixels)]


def find_exposure_slider():
    region = next(region for region in current_area().regions if region.type == "UI")
    region.active_panel_category = "Perceptual Grade"
    current_area().tag_redraw()
    yield 0.3
    x = region.x + region.width // 2
    manager = bpy.context.window_manager
    previous_clipboard = manager.clipboard
    try:
        for y in range(region.y + region.height - 5,
                       max(region.y, region.y + region.height - 300), -3):
            bpy.context.window.event_simulate(type="MOUSEMOVE", value="NOTHING", x=x, y=y)
            yield 0.02
            with bpy.context.temp_override(window=bpy.context.window, area=current_area(),
                                           region=region):
                if not bpy.ops.ui.copy_data_path_button.poll():
                    continue
                bpy.ops.ui.copy_data_path_button()
                if manager.clipboard.endswith("pg_linear.exposure"):
                    return x, y - 4
    finally:
        manager.clipboard = previous_clipboard
    raise AssertionError("The real Compositor Grade Exposure slider was not found")


def wait_for(predicate, message, timeout=15.0):
    deadline = time.monotonic() + timeout
    while not predicate():
        assert time.monotonic() < deadline, message
        yield 0.05


def send(kind, value, position):
    bpy.context.window.event_simulate(
        type=kind, value=value, x=int(position[0]), y=int(position[1]),
    )


def run():
    window = bpy.context.window
    yield from wait_for(lambda: viewer_hash() is not None,
                        "Initial render did not populate the Compositor Viewer")
    initial_hash = viewer_hash()
    report["initial_viewer_range"] = viewer_range()
    render_result = bpy.data.images.get("Render Result")
    if render_result is not None and render_result.has_data:
        render_pixels = array("f", render_result.pixels[:])
        report["render_result_range"] = [min(render_pixels), max(render_pixels)]
    slider = yield from find_exposure_slider()
    tree = bpy.data.node_groups[SCENE_TREE]
    tree.nodes.active = tree.nodes["Rendered Grade Node"]
    send("MOUSEMOVE", "NOTHING", slider)
    yield 0.05
    send("LEFTMOUSE", "PRESS", slider)
    yield from wait_for(lambda: nodes._gesture_phase(window.as_pointer()) == "armed",
                        "Native Compositor slider press did not arm the Grade gesture")
    send("MOUSEMOVE", "NOTHING", (slider[0] + 8, slider[1]))
    yield from wait_for(lambda: nodes._record_for(tree.nodes["Rendered Grade Node"])["state"].gesture_active,
                        "Native Compositor slider movement did not start the gesture")

    last_hash = initial_hash
    for offset in (12, 16, 12, 8, 12, 16, 20, 16, 12, 8, 4, 8, 12, 16, 20, 16,
                   12, 8, 4, 8, 12, 16, 20, 16):
        before = sum(item["finished"] is not None for item in events)
        send("MOUSEMOVE", "NOTHING", (slider[0] + offset, slider[1]))
        yield 0.5
        report["accepted_exposure"].append(exposure())
        completed = sum(item["finished"] is not None for item in events)
        if completed > before:
            yield from wait_for(lambda: not bpy.app.is_job_running("COMPOSITE"),
                                "Live Compositor evaluation did not finish", timeout=3.0)
            yield 0.3
            digest = viewer_hash()
            sample = {
                "completed_events": completed,
                "exposure": exposure(),
                "viewer_hash": digest,
                "viewer_range": viewer_range(),
                "sampled": time.monotonic(),
            }
            report["evaluations"].append(sample)
            if digest is not None:
                last_hash = digest

    final_exposure = exposure()
    send("LEFTMOUSE", "RELEASE", (slider[0] - 30, slider[1]))
    yield from wait_for(lambda: not nodes._record_for(tree.nodes["Rendered Grade Node"])["state"].gesture_active,
                        "Native Compositor slider release did not finish the gesture")

    yield from wait_for(lambda: not bpy.app.is_job_running("COMPOSITE"),
                        "Final compositor evaluation did not finish", timeout=12.0)
    yield 0.3
    final_hash = viewer_hash()
    final_sample = {
        "completed_events": sum(item["finished"] is not None for item in events),
        "exposure": exposure(),
        "viewer_hash": final_hash,
        "viewer_range": viewer_range(),
        "sampled": time.monotonic(),
        "after_release": True,
    }
    report["evaluations"].append(final_sample)
    if final_hash is not None:
        last_hash = final_hash

    report["final_exposure"] = final_exposure
    report["final_viewer_hash"] = last_hash
    report["render_count"] = render_count
    report["passed"] = (
        len({round(value, 4) for value in report["accepted_exposure"]}) >= 4
        and len(report["evaluations"]) >= 3
        and len({round(item["exposure"], 4) for item in report["evaluations"]}) >= 3
        and len({item["viewer_hash"] for item in report["evaluations"]
                 if item["viewer_hash"] is not None}) >= 2
        and final_hash != initial_hash
        and abs(final_sample["exposure"] - final_exposure) < 1e-5
        and any(abs(item["exposure"] - final_exposure) < 1e-5
                and item["viewer_hash"] == final_hash
                for item in report["evaluations"])
        and render_count == baseline_render_count == 1
    )
    assert report["passed"], report


steps = run()


def finish(error=None):
    if error is not None:
        report["failure"] = error
    report["render_count"] = render_count
    report_path.write_text(json.dumps(report, indent=2))
    bpy.ops.wm.quit_blender("EXEC_DEFAULT")
    return None


def tick():
    try:
        return next(steps)
    except StopIteration:
        return finish()
    except BaseException:
        detail = traceback.format_exc()
        print(detail, flush=True)
        return finish(detail)


bpy.app.timers.register(tick, first_interval=0.2)
