"""Exercise active-viewport Shader Color capture for a per-node Grade."""

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
    name="Perceptual Grade shader vectorscope test", module="pg_vectorscope_shader",
    custom_directory=repository,
)
extension = importlib.import_module("bl_ext.pg_vectorscope_shader.perceptual_grade")
nodes = importlib.import_module(extension.__name__ + ".nodes")
vectorscope_ui = importlib.import_module(extension.__name__ + ".vectorscope_ui")
errors = []
assert addon_utils.enable(extension.__name__, default_set=False,
                          handle_error=errors.append) is extension, errors
assert not errors and not bpy.app.background, errors

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
shader = tree.nodes.new("ShaderNodeEmission")
output = tree.nodes.new("ShaderNodeOutputMaterial")
tree.links.new(coordinates.outputs["UV"], color.inputs["Vector"])
tree.links.new(color.outputs["Color"], grade.inputs["Color"])
tree.links.new(grade.outputs["Color"], shader.inputs["Color"])
tree.links.new(shader.outputs[0], output.inputs["Surface"])
obj.data.materials.append(material)

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
    linear = np.asarray(color[:3]) * 2.0 ** exposure
    code = np.where(linear < 0.018, 4.5 * linear, 1.099 * linear ** 0.45 - 0.099)
    luma = np.dot(code, (0.2126, 0.7152, 0.0722))
    cr, cb = (code[0] - luma) / 1.5748, (code[2] - luma) / 1.8556
    expected = tuple(int((value + 0.65) * 144 / 1.3) for value in (cr, cb))
    peak = np.unravel_index(np.argmax(brightness), brightness.shape)
    return max(abs(actual - target) for actual, target in zip(peak, expected)) <= 1


def scenario():
    checkpoint("enable vectorscope")
    with bpy.context.temp_override(window=window, area=node_area, region=node_region):
        assert bpy.ops.perceptual_grade.toggle_vectorscope() == {"FINISHED"}
    yield from wait_for(lambda: matches(red), "Shader AOV capture did not plot the first UV sample")
    first = np.asarray(state().brightness).copy()
    assert first.shape == (144, 144) and np.sum(first) > 0
    report["initial_shape"] = list(first.shape)
    report["shader_aov_visible"] = True
    grade.exposure = 1.0
    yield from wait_for(lambda: matches(red, 1.0), "Shader Linear edit did not refresh")
    report["linear_edit_refreshed"] = True
    for item in uv.uv:
        item.vector = (0.75, 0.5)
    mesh.update()
    mesh.update_tag()
    yield from wait_for(lambda: matches(blue, 1.0), "Shader UV edit did not move the vectorscope peak")
    report["uv_edit_refreshed"] = True


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
        next(sequence)
        return 0.02
    except StopIteration:
        report["passed"] = True
        checkpoint("passed")
        bpy.app.timers.register(request_quit, first_interval=0.1, persistent=True)
        return None
    except BaseException:
        report["error"] = traceback.format_exc()
        checkpoint("failed")
        print(report["error"], flush=True)
        os._exit(1)


bpy.app.timers.register(advance, first_interval=0.2, persistent=True)
