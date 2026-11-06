"""Drive a live Viewer: final renders silently promote AUTO to full precision.

After setup, only authoritative Grade settings and the requested backend change.
No render, image tag, node rebind, mute toggle, or manual reconciliation may make
an edit visible. A composite completion and changed Viewer pixels are required.
"""

import addon_utils
import importlib
import json
from pathlib import Path
import sys
import time
import traceback

import bpy
from bpy.app.handlers import persistent
import gpu
import numpy as np


repository, report_path = map(Path, sys.argv[sys.argv.index("--") + 1:-1])
phase = sys.argv[-1]
bpy.context.preferences.view.show_splash = False
bpy.context.preferences.extensions.repos.new(
    name="Perceptual Grade compositor test", module="pg_compositor",
    custom_directory=str(repository),
)
extension = importlib.import_module("bl_ext.pg_compositor.perceptual_grade")
nodes = importlib.import_module(extension.__name__ + ".nodes")
errors = []
assert addon_utils.enable(
    extension.__name__, default_set=False, handle_error=errors.append
) is extension
assert not errors and not bpy.app.background, errors

# A spatially varying image is essential: constant results use float32 even in
# AUTO and would conceal the half-precision intermediate overflow regression.
PALETTE = np.asarray([
    (0, 0, 0, 0), (1e-8, 1e-8, 1e-8, .1), (1e-6, 1e-6, 1e-6, .25),
    (.0001, .0001, .0001, .5), (.01, .01, .01, .37), (.18, .18, .18, .5),
    (1, 1, 1, .75), (16, 16, 16, 1), (64, 64, 64, .2), (256, 256, 256, .6),
    (900, 900, 900, .3), (918, 918, 918, .4), (920, 920, 920, .7),
    (922, 922, 922, .8), (1024, 1024, 1024, 1), (2048, 2048, 2048, .5),
    (-.01, -.01, -.01, .5), (-1, -1, -1, .75), (-.1, .2, .3, .25),
    (1, -.2, .1, .6), (-4, 2, .5, 1), (1, 0, 0, 0), (0, 1, 0, .33),
    (0, 0, 1, .66), (4, 0, 0, 1), (0, 16, 1, .4), (32, .1, 4, .8),
    (.01, .5, 1, .9), (1, 1, 0, .3), (.5, .5, 1, .7),
    (.125, .25, .5, 1), (-1e-8, 1e-8, 0, .5),
], dtype=np.float32)
CONFIGS = ("reset", "exposure", "tone", "anchors")
SCENE_TREE = "Interactive Grade Root"
NESTED_TREE = "Nested Grade Consumer"
MATERIAL = "Shared Shader Consumer"
GRADE = "Interactive Shared Grade"
BLEND = report_path.parent / "stale-kernel.blend"
rows = []
events = []
pending_frame = {}
result = {"passed": False, "rows": rows}
started = time.monotonic()


def consumers():
    return (
        bpy.data.node_groups[NESTED_TREE].nodes["Nested Grade"],
        bpy.data.node_groups[SCENE_TREE].nodes["Shared Grade"],
        bpy.data.materials[MATERIAL].node_tree.nodes["Shader Grade"],
    )


def grade_settings():
    return nodes._snapshot_values(nodes._grade_settings(
        bpy.data.node_groups[GRADE], nodes._working_space(),
    ))


def identity():
    users = consumers()
    parameters = [node.node_tree[nodes.PARAMETER_BINDING] for node in users]
    assert all(image == parameters[0] for image in parameters), "Shared parameter image split"
    trees = (bpy.data.node_groups[SCENE_TREE], bpy.data.node_groups[NESTED_TREE],
             bpy.data.materials[MATERIAL].node_tree)
    return {
        "kernels": [node.node_tree.as_pointer() for node in users],
        "links": [[(link.from_socket.as_pointer(), link.to_socket.as_pointer())
                   for link in tree.links] for tree in trees],
        "node_counts": [len(node.node_tree.nodes) for node in users],
    }


def configure(name):
    grade = bpy.data.node_groups[GRADE]
    for field, value in nodes._LINEAR_DEFAULTS.items():
        setattr(grade.pg_linear, field, value)
    for field, value in nodes.TONE_DEFAULTS.items():
        setattr(grade.pg_tone, field, value)
    if name != "reset":
        grade.pg_linear.exposure = .5 if name == "exposure" else 1.
    if name == "tone":
        grade.pg_tone.fit = .5
    elif name == "anchors":
        for field, value in zip(nodes.TONE_LEVEL_FIELDS, (.2, 8., 40., 235., 1150.)):
            setattr(grade.pg_tone, field, value)
        grade.pg_tone.fit = 2.


def setup():
    scene = bpy.context.scene
    scene.render.compositor_device = "GPU"
    scene.render.compositor_precision = "AUTO"
    scene.render.resolution_x = len(PALETTE)
    scene.render.resolution_y = 8
    scene.render.resolution_percentage = 100
    image = bpy.data.images.new("Compositor palette", width=len(PALETTE), height=8,
                                alpha=True, float_buffer=True)
    image.colorspace_settings.name = "Non-Color"
    image.alpha_mode = "CHANNEL_PACKED"
    image.use_half_precision = False
    image.pixels.foreach_set(np.tile(PALETTE, (8, 1)).ravel())
    image.update()
    image.pack()
    root = bpy.data.node_groups.new(SCENE_TREE, nodes.COMPOSITOR_TREE)
    root.interface.new_socket(name="Image", in_out="OUTPUT", socket_type="NodeSocketColor")
    output = root.nodes.new("NodeGroupOutput")
    source = root.nodes.new("CompositorNodeImage")
    source.image = image
    nested = bpy.data.node_groups.new(NESTED_TREE, nodes.COMPOSITOR_TREE)
    for direction in ("INPUT", "OUTPUT"):
        nested.interface.new_socket(name="Color", in_out=direction,
                                    socket_type="NodeSocketColor")
    incoming = nested.nodes.new("NodeGroupInput")
    outgoing = nested.nodes.new("NodeGroupOutput")
    grade = nodes._make_grade()
    grade.name = GRADE
    node = nodes.create_node(nested)
    node.name = "Nested Grade"
    node.pg_grade = grade
    nested.links.new(incoming.outputs["Color"], node.inputs["Color"])
    nested.links.new(node.outputs["Color"], outgoing.inputs["Color"])
    wrapper = root.nodes.new("CompositorNodeGroup")
    wrapper.node_tree = nested
    shared = nodes.create_node(root)
    shared.name = "Shared Grade"
    shared.pg_grade = grade
    root.links.new(source.outputs["Image"], shared.inputs["Color"])
    root.links.new(source.outputs["Image"], wrapper.inputs["Color"])
    viewer = root.nodes.new("CompositorNodeViewer")
    root.links.new(wrapper.outputs["Color"], viewer.inputs["Image"])
    root.links.new(wrapper.outputs["Color"], output.inputs["Image"])
    root.nodes.active = viewer
    material = bpy.data.materials.new(MATERIAL)
    material.use_nodes = True
    material.use_fake_user = True
    shader = nodes.create_node(material.node_tree)
    shader.name = "Shader Grade"
    shader.pg_grade = grade
    shader_source = material.node_tree.nodes.new("ShaderNodeRGB")
    material.node_tree.links.new(shader_source.outputs[0], shader.inputs["Color"])
    scene.compositing_node_group = root
    area = next(area for area in bpy.context.screen.areas if area.type == "VIEW_3D")
    area.type = "NODE_EDITOR"
    area.ui_type = "CompositorNodeTree"
    area.spaces.active.show_backdrop = True


@persistent
def observe_started(*_args):
    global pending_frame
    try:
        states = [nodes._node_stores.get(node.as_pointer(), {}).get("state")
                  for node in consumers()]
        pending_frame = {
            "current": all(state is not None and nodes.node_policy.output_allowed(state)
                           for state in states),
            "settings": grade_settings(),
            "device": bpy.context.scene.render.compositor_device,
            "precision": bpy.context.scene.render.compositor_precision,
        }
    except (KeyError, ReferenceError):
        pending_frame = {"current": False}


@persistent
def observe(*_args):
    events.append(dict(pending_frame, finished=time.monotonic()))


@persistent
def observe_loaded_schema(*_args):
    result["loaded_schema"] = [node.node_tree.get(nodes._KERNEL_KIND) for node in consumers()]


bpy.app.handlers.composite_pre.append(observe_started)
bpy.app.handlers.composite_post.append(observe)
if phase == "exercise":
    setup()
    tasks = [(name, device, precision) for device, precision in (
        ("GPU", "AUTO"), ("CPU", "FULL"), ("GPU", "FULL"),
    ) for name in CONFIGS]
    tasks.append(("anchors", "GPU", "AUTO"))
    reference_rows = None
else:
    reference_rows = json.loads((report_path.parent / "exercise.json").read_text())
    bpy.app.handlers.load_post.insert(0, observe_loaded_schema)
    bpy.ops.wm.open_mainfile(filepath=str(BLEND))
    tasks = [("anchors", "GPU", "AUTO"), ("reset", "GPU", "AUTO")]
    result["settings_preserved"] = list(grade_settings()) == reference_rows["saved_settings"]
    assert result["settings_preserved"]
    assert result["loaded_schema"] == [3, 3, 3], result
    np.testing.assert_array_equal(
        np.asarray(bpy.data.images["Compositor palette"].pixels[:len(PALETTE) * 4],
                   dtype=np.float32).reshape(-1, 4), PALETTE,
    )

index = 0
stage = "apply"
wait_started = started
floor = 0
previous_pixels = None
fixed_identity = None
expected_settings = None
automatic_updates = 0


def pixel_error(actual, expected):
    error = np.max(np.abs(actual[:, :3] - expected[:, :3]), axis=1)
    return float(np.max(error / (1 + np.max(np.abs(expected[:, :3]), axis=1))))


def check_pixels(pixels, device, precision):
    assert np.isfinite(pixels).all(), pixels.tolist()
    if device == "GPU" and precision == "AUTO":
        # One binary16 ULP at the source alpha, including zero/subnormals.
        half = PALETTE[:, 3].astype(np.float16)
        ulp = (np.nextafter(half, np.float16(np.inf)) - half).astype(np.float32)
        assert np.all(np.abs(pixels[:, 3] - PALETTE[:, 3]) <= ulp), pixels[:, 3]
    else:
        np.testing.assert_array_equal(pixels[:, 3], PALETTE[:, 3])


def check_truth(pixels, name, device, precision):
    if name not in ("reset", "exposure"):
        return
    # These in-gamut neutrals do not invoke boundary repair. They independently
    # anchor the CPU references and catch the old AUTO near-white collapse.
    expected = PALETTE[3:9].copy()
    expected[:, :3] *= 2.**(.5 if name == "exposure" else 0.)
    error = pixel_error(pixels[3:9], expected)
    limit = .01 if (device, precision) == ("GPU", "AUTO") else 1e-4
    assert error <= limit, ("neutral exposure", name, device, precision, error)


def finish(error=None):
    result.update(passed=error is None, error=error, seconds=time.monotonic() - started,
                  events=len(events), gpu={"backend": gpu.platform.backend_type_get(),
                                           "renderer": gpu.platform.renderer_get()})
    report_path.write_text(json.dumps(result, indent=2))
    bpy.ops.wm.quit_blender()


def complete():
    baseline = reference_rows["rows"] if reference_rows else rows
    references = {row["config"]: np.asarray(row["pixels"], dtype=np.float32)
                  for row in baseline if (row["device"], row["precision"]) == ("CPU", "FULL")}
    for row in rows:
        error = pixel_error(np.asarray(row["pixels"], dtype=np.float32), references[row["config"]])
        limit = .01 if (row["device"], row["precision"]) == ("GPU", "AUTO") else 1e-4
        row["normalized_rgb_error"] = error
        assert error <= limit, (row["config"], row["device"], row["precision"], error)
    if phase == "exercise":
        result["automatic_updates"] = automatic_updates
        result["saved_settings"] = list(grade_settings())
        for node in consumers():
            node.node_tree[nodes._KERNEL_KIND] = 3
        result["saved_schema"] = [node.node_tree[nodes._KERNEL_KIND] for node in consumers()]
        assert bpy.ops.wm.save_as_mainfile(filepath=str(BLEND)) == {"FINISHED"}
    else:
        result["repaired_schema"] = [node.node_tree[nodes._KERNEL_KIND] for node in consumers()]
        assert result["repaired_schema"] == [5, 5, 5]
    finish()


def tick():
    global index, stage, wait_started, floor, previous_pixels, fixed_identity
    global expected_settings, automatic_updates
    try:
        now = time.monotonic()
        assert now - wait_started < 40, ("Viewer did not automatically update", phase,
                                        tasks[index], stage, len(events), floor)
        name, device, precision = tasks[index]
        scene = bpy.context.scene
        if stage == "apply":
            floor = len(events) if index else 0
            if not (phase == "reload" and index == 0):
                if scene.render.compositor_device != device:
                    scene.render.compositor_device = device
                if scene.render.compositor_precision != precision:
                    scene.render.compositor_precision = precision
                configure(name)
            expected_settings = grade_settings()
            wait_started = now
            stage = "observe"
            return .1
        users = consumers()
        current = all(nodes.node_policy.output_allowed(nodes._record_for(node)["state"])
                      for node in users)
        if not current or len(events) <= floor:
            return .1
        frame = events[-1]
        if (not frame.get("current") or frame.get("settings") != expected_settings
                or (frame.get("device"), frame.get("precision")) != (device, precision)
                or now - frame["finished"] < .3):
            return .1
        viewers = [image for image in bpy.data.images if image.type == "COMPOSITING"]
        if not viewers or tuple(viewers[0].size) != (len(PALETTE), 8):
            return .1
        pixels = np.asarray(viewers[0].pixels[:len(PALETTE) * 4], dtype=np.float32).reshape(-1, 4)
        same_backend_edit = index > 0 and tasks[index - 1][1:] == (device, precision)
        if same_backend_edit and np.array_equal(pixels, previous_pixels):
            return .1
        assert grade_settings() == expected_settings
        assert (scene.render.compositor_device, scene.render.compositor_precision) == (device, precision)
        current_identity = identity()
        if fixed_identity is None:
            fixed_identity = current_identity
        else:
            assert current_identity == fixed_identity, ("Grade topology changed", current_identity, fixed_identity)
        check_pixels(pixels, device, precision)
        check_truth(pixels, name, device, precision)
        if same_backend_edit:
            automatic_updates += 1
        rows.append({"config": name, "device": device, "precision": precision,
                     "pixels": pixels.tolist(), "events": len(events), "identity": current_identity,
                     "parameter": users[0].node_tree[nodes.PARAMETER_BINDING].as_pointer()})
        print("COMPOSITOR", name, device, precision, "completed", len(events), flush=True)
        previous_pixels = pixels
        index += 1
        if index == len(tasks):
            complete()
            return None
        stage = "apply"
        wait_started = now
        return .1
    except Exception:
        traceback.print_exc()
        finish(traceback.format_exc())
        return None


bpy.app.timers.register(tick, first_interval=.1)
