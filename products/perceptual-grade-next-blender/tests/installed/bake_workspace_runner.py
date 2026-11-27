"""Smoke-test Grade preparation and Image Bake in non-default working spaces."""

import addon_utils
import importlib
import json
from pathlib import Path
import sys
import time
from types import SimpleNamespace

import bpy
import numpy as np


repository, report_path = map(Path, sys.argv[sys.argv.index("--") + 1:])
bpy.context.preferences.extensions.repos.new(
    name="Perceptual Grade working-space bake test", module="pg_workspace_bake",
    custom_directory=str(repository),
)
extension = importlib.import_module("bl_ext.pg_workspace_bake.perceptual_grade")
application = importlib.import_module("bl_ext.pg_workspace_bake.perceptual_grade.application")
nodes = importlib.import_module("bl_ext.pg_workspace_bake.perceptual_grade.features.grade.host")
errors = []
assert addon_utils.enable(extension.__name__, default_set=False,
                          handle_error=errors.append) is extension
assert not errors, errors


def wait_ready(node):
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        application._runtime._scheduler_tick()
        state = nodes._record_for(node)["state"]
        if (state.error is None and nodes.node_policy.output_allowed(state)
                and state.applied_quality == "full"
                and nodes._kernel_is_current(
                    node.node_tree, node.id_data.bl_idname,
                    state.desired_signature, "full")):
            return
        time.sleep(.01)
    raise TimeoutError("Grade kernel did not become ready")


def wait_bake(node):
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        application._runtime._scheduler_tick()
        manager = nodes._bake.manager
        if manager is None or manager._node_key(node) not in manager.jobs:
            return
        time.sleep(.01)
    raise TimeoutError("Image Bake did not retire")


def source_image(name):
    values = np.asarray((
        .1, .2, .3, .25, .3, .4, .5, .5,
        .5, .6, .7, .75, .7, .8, .9, 1.,
    ), dtype=np.float32)
    image = bpy.data.images.new(name, width=2, height=2, alpha=True,
                                float_buffer=True)
    image.colorspace_settings.name = "Non-Color"
    image.alpha_mode = "CHANNEL_PACKED"
    image.pixels.foreach_set(values)
    image.update()
    image.pack()
    return image, values.reshape(4, 4)


def bake_in_space(scene, space, index):
    result = bpy.ops.wm.set_working_color_space(working_space=space)
    assert result == {"FINISHED"}, result
    assert nodes._working_space() == space

    material = bpy.data.materials.new(f"Working-space Bake Material {index}")
    material.use_nodes = True
    tree = material.node_tree
    tree.nodes.clear()
    grade = nodes.create_node(tree)
    grade.pg_grade = nodes._make_grade()
    source = tree.nodes.new("ShaderNodeTexImage")
    source.image, expected = source_image(f"Working-space Bake Source {index}")
    tree.links.new(source.outputs["Color"], grade.inputs["Color"])
    tree.links.new(source.outputs["Alpha"], grade.inputs["Alpha"])
    context = SimpleNamespace(
        scene=scene, object=None, pg_bake_node=grade,
        space_data=SimpleNamespace(id=material, node_tree=tree, path=()),
    )
    wait_ready(grade)
    operator = SimpleNamespace(cancel=False, node_pointer="", tree_pointer="")
    assert nodes.PG_OT_bake.execute(operator, context) == {"FINISHED"}
    wait_bake(grade)
    image = grade.pg_bake_image
    assert image is not None, grade.get(nodes.bake_controller.BAKE_ERROR)
    assert image.is_float and image.packed_file is not None and not image.is_dirty
    pixels = np.asarray(image.pixels[:], dtype=np.float32)
    assert pixels.size and np.isfinite(pixels).all()
    np.testing.assert_allclose(pixels.reshape(-1, 4), expected,
                               rtol=0, atol=0.002)
    assert grade.pg_use_bake
    assert not grade.get(nodes.bake_controller.BAKE_ERROR)
    return {"space": space, "pixels": int(pixels.size)}


scene = bpy.context.scene
scene.render.resolution_percentage = 100
scene.render.resolution_x = 8
scene.render.resolution_y = 8
results = [bake_in_space(scene, space, index)
           for index, space in enumerate(("Linear Rec.2020", "ACEScg"))]
report_path.write_text(json.dumps({"passed": True, "bakes": results}) + "\n")
