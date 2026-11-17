"""Compare live Auto carrier cuts with Full; final renders cannot test Auto."""

from dataclasses import replace
import json
from pathlib import Path
import sys
import time
import traceback

import bpy
import numpy as np


configuration = json.loads(Path(sys.argv[sys.argv.index("--") + 1]).read_text())
sys.path.extend(configuration["python_paths"])

from color_tools.kernel import LinearSettings, prepare
from color_tools.kernel.boundary import prepare_boundary
from color_tools.kernel.stage2_parameters import prepare_parameters
from color_tools.template_build.guard_graph import compositor_stage2_output_guard
from color_tools.template_build.stage2_graph import ParameterBindings, ParameterGraph


report = Path(configuration["report"])
palette = np.repeat(np.asarray((.0001, .01, .18, 1., 16., 64.), np.float32)[:, None],
                    4, axis=1)
palette[:, 3] = 1.
scene = bpy.context.scene
assert not bpy.app.background
scene.render.resolution_x = len(palette)
scene.render.resolution_y = 8
scene.render.resolution_percentage = 100
bpy.context.preferences.view.show_splash = False
image = bpy.data.images.new("Spatial carrier palette", width=len(palette), height=8,
                            alpha=True, float_buffer=True)
image.colorspace_settings.name = "Non-Color"
image.alpha_mode = "CHANNEL_PACKED"
image.use_half_precision = False
image.pixels.foreach_set(np.tile(palette, (8, 1)).ravel())
image.update()
prepared = prepare(LinearSettings(exposure=.5), full_fields=True)
prepared = replace(prepared, boundary=prepare_boundary(prepared.fl, prepared.aw, prepared.gamma))
tree = bpy.data.node_groups.new("Live carrier probe", "CompositorNodeTree")
tree.interface.new_socket(name="Image", in_out="OUTPUT", socket_type="NodeSocketColor")
graph = ParameterGraph(tree, prepared)
graph.parameters = ParameterBindings(graph, prepare_parameters(prepared))
source = tree.nodes.new("CompositorNodeImage")
source.image = image
cones = graph.parameters.matrix(source.outputs["Image"])
encoded = graph.encode_cones(cones)
toned = graph.tone(encoded, force=True)
colored = graph.color_and_guard(toned)
variants = {
    "production": compositor_stage2_output_guard(graph, colored,
        source=source.outputs["Image"], retained_tone=toned).color,
    "retained_tone": graph.decode(toned).color,
    "tone_coordinates": graph.decode_coordinates(toned.J_A, toned.a, toned.b).color,
    "color_coordinates": graph.decode_coordinates(colored.J_A, colored.a, colored.b).color,
    "carriers": graph.vector((toned.J_A, colored.J_A, toned.achromatic)),
    "cones": cones,
}
viewer = tree.nodes.new("CompositorNodeViewer")
output = tree.nodes.new("NodeGroupOutput")
tree.nodes.active = viewer
scene.compositing_node_group = tree
area = next(item for item in bpy.context.screen.areas if item.type == "VIEW_3D")
area.type = "NODE_EDITOR"
area.ui_type = "CompositorNodeTree"
area.spaces.active.show_backdrop = True
tasks = [(name, device, precision) for device, precision in (
    ("GPU", "AUTO"), ("GPU", "FULL"), ("CPU", "FULL"),
) for name in variants]
rows, events = [], []
index, stage, floor = 0, "apply", 0
wait_started = time.monotonic()


def observed(*_args):
    events.append(time.monotonic())


bpy.app.handlers.composite_post.append(observed)


def finish(error=None):
    report.write_text(json.dumps({"rows": rows, "error": error}, indent=2))
    bpy.ops.wm.quit_blender()


def tick():
    global index, stage, floor, wait_started
    try:
        now = time.monotonic()
        assert now - wait_started < 40, (tasks[index], stage, len(events), floor)
        name, device, precision = tasks[index]
        if stage == "apply":
            floor = len(events)
            for target in (viewer.inputs["Image"], output.inputs["Image"]):
                for link in tuple(target.links):
                    tree.links.remove(link)
                tree.links.new(variants[name], target)
            scene.render.compositor_device = device
            scene.render.compositor_precision = precision
            scene.compositing_node_group = tree
            stage, wait_started = "observe", now
            return .1
        if len(events) <= floor or now - events[-1] < .3:
            return .1
        images = [item for item in bpy.data.images if item.type == "COMPOSITING"]
        if not images or tuple(images[0].size) != (len(palette), 8):
            return .1
        assert (scene.render.compositor_device, scene.render.compositor_precision) == (device, precision)
        pixels = np.asarray(images[0].pixels[:len(palette) * 4],
                            dtype=np.float32).reshape(-1, 4)
        assert np.isfinite(pixels).all(), (tasks[index], pixels)
        rows.append({"variant": name, "device": device, "precision": precision,
                     "pixels": pixels.tolist()})
        print("LIVE CARRIER", name, device, precision, pixels[:, :3].tolist(), flush=True)
        index += 1
        if index == len(tasks):
            finish()
            return None
        stage, wait_started = "apply", now
        return .1
    except Exception:
        finish(traceback.format_exc())
        return None


bpy.app.timers.register(tick, first_interval=.1)
