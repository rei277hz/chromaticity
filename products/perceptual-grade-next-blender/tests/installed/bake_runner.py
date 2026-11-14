"""Exercise the installed bake implementation inside native Blender."""

import addon_utils
import importlib
import json
from pathlib import Path
import sys
import tempfile
import time
from types import SimpleNamespace

import bpy
import numpy as np


repository, report_path = map(Path, sys.argv[sys.argv.index("--") + 1:])
bpy.context.preferences.extensions.repos.new(
    name="Perceptual Grade bake test", module="pg_bake",
    custom_directory=str(repository),
)
extension = importlib.import_module("bl_ext.pg_bake.perceptual_grade")
nodes = importlib.import_module("bl_ext.pg_bake.perceptual_grade.nodes")
errors = []
assert addon_utils.enable(extension.__name__, default_set=False, handle_error=errors.append) is extension
assert not errors, errors


def wait_ready(node, *, stack=False):
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        nodes._preparation_tick()
        state = nodes._record_for(node)["state"]
        if state.error is None and nodes.node_policy.output_allowed(state):
            assert state.applied_quality == "full"
            assert nodes._kernel_is_current(
                node.node_tree, node.id_data.bl_idname, state.desired_signature,
                "full", stack=stack,
            )
            return
        time.sleep(.01)
    raise TimeoutError("Grade kernel did not become ready")


def wait_bake(node):
    deadline = time.monotonic() + 300
    while time.monotonic() < deadline:
        nodes._bake_tick()
        manager = nodes._bake_manager
        if manager is None or manager._node_key(node) not in manager.jobs:
            return
        time.sleep(.01)
    raise TimeoutError("Bake did not retire")


def image(name, pixels, width, height):
    value = bpy.data.images.new(name, width=width, height=height,
                                alpha=True, float_buffer=True)
    value.colorspace_settings.name = "Non-Color"
    value.alpha_mode = "CHANNEL_PACKED"
    value.pixels.foreach_set(np.asarray(pixels, dtype=np.float32).reshape(-1))
    value.update()
    value.pack()
    return value


def shader_context(material, scene, obj=None, node=None):
    return SimpleNamespace(scene=scene, object=obj, pg_bake_node=node,
                           space_data=SimpleNamespace(id=material,
                                                      node_tree=material.node_tree,
                                                      path=()))


def compositor_context(scene, tree, node=None):
    return SimpleNamespace(scene=scene, object=None, pg_bake_node=node,
                           space_data=SimpleNamespace(id=scene,
                                                      node_tree=tree, path=()))


def bake(node, context):
    operator = SimpleNamespace(cancel=False, node_pointer="", tree_pointer="")
    assert nodes.PG_OT_bake.execute(operator, context) == {"FINISHED"}
    assert bpy.app.timers.is_registered(nodes._bake_tick), "Bake request did not wake its timer"
    wait_bake(node)
    assert node.pg_bake_image is not None, node.get(nodes._BAKE_ERROR)
    assert node.pg_bake_image.packed_file is not None
    assert node.pg_bake_image.is_float
    assert not node.pg_bake_image.is_dirty
    assert node.pg_use_bake
    values = np.asarray(node.pg_bake_image.pixels[:], dtype=np.float32)
    assert values.size and np.isfinite(values).all()
    return values


def assert_wrapper_independent(first, second):
    """A copied node must not share its selector/reader tree with its source."""
    assert first.node_tree is not None and second.node_tree is not None
    assert first.node_tree != second.node_tree
    first_selectors = tuple(item for item in first.node_tree.nodes
                            if item.get(nodes.bake_graph.SELECTOR))
    second_selectors = tuple(item for item in second.node_tree.nodes
                             if item.get(nodes.bake_graph.SELECTOR))
    assert first_selectors and second_selectors
    second.pg_use_bake = False
    assert all(float(item.inputs[0].default_value) == 1.0 for item in first_selectors)
    assert all(float(item.inputs[0].default_value) == 0.0 for item in second_selectors)


def link_source(tree, node, source, *, uv=False):
    if uv:
        coordinates = tree.nodes.new("ShaderNodeUVMap")
        tree.links.new(coordinates.outputs["UV"], source.inputs["Vector"])
    tree.links.new(source.outputs["Color"], node.inputs["Color"])
    tree.links.new(source.outputs["Alpha"], node.inputs["Alpha"])


scene = bpy.context.scene
scene.frame_set(1)
scene.render.resolution_percentage = 100
scene.render.resolution_x = 32
scene.render.resolution_y = 32

# Shader Image route, including the independent Alpha emission pass.
material = bpy.data.materials.new("Bake Material")
material.use_nodes = True
shader_tree = material.node_tree
shader_tree.nodes.clear()
grade_data = nodes._make_grade()
shader = nodes.create_node(shader_tree)
shader.pg_grade = grade_data
source_image = image("Bake Source", np.array([
    [.10, .20, .30, .20], [.30, .40, .50, .40],
    [.50, .60, .70, .60], [.70, .80, .90, .80],
], dtype=np.float32), 2, 2)
source = shader_tree.nodes.new("ShaderNodeTexImage")
source.image = source_image
link_source(shader_tree, shader, source)
wait_ready(shader)
shader_values = bake(shader, shader_context(material, scene, node=shader))
assert shader.pg_bake_image.get(nodes._BAKE_DOMAIN) == "IMAGE"
assert np.unique(np.round(shader_values.reshape(-1, 4)[:, 3], 5)).size > 1
source_rgba = np.array([
    [.10, .20, .30, .20], [.30, .40, .50, .40],
    [.50, .60, .70, .60], [.70, .80, .90, .80],
], dtype=np.float32)
image_pixels = shader_values.reshape(-1, 4)
# Default Linear/Tone anchors describe identity.  These source values are
# inside the Rec.709 domain, so the native Grade tree should return the same
# texels, including the independent Alpha pass, up to floating point error.
np.testing.assert_allclose(image_pixels, source_rgba, rtol=0, atol=0.002)
identity_match = True

# Use Bake can be disabled and restored without unbinding the managed Image.
shader.pg_use_bake = False
assert not shader.pg_use_bake
shader_wrapper = shader.node_tree
shader_selectors = tuple(item for item in shader_wrapper.nodes
                         if item.get(nodes.bake_graph.SELECTOR))
assert shader_selectors and all(float(item.inputs[0].default_value) == 0.0
                                for item in shader_selectors)
shader.pg_use_bake = True
assert shader.pg_use_bake and shader.pg_bake_image is not None
live_restored = all(float(item.inputs[0].default_value) == 1.0
                    for item in shader_selectors)

# Generated wrapper links and selector modes cannot silently change output.
assert nodes.bake_graph.structure_valid(shader.node_tree)
shader_selectors[0].blend_type = "MULTIPLY"
assert not nodes.bake_graph.structure_valid(shader.node_tree)
nodes._reconcile_bake_outputs((shader,))
assert shader.pg_use_bake and nodes.bake_graph.structure_valid(shader.node_tree)
broken_output = next(item for item in shader.node_tree.nodes
                     if item.bl_idname == "NodeGroupOutput")
shader.node_tree.links.remove(broken_output.inputs["Color"].links[0])
assert not nodes.bake_graph.structure_valid(shader.node_tree)
nodes._reconcile_bake_outputs((shader,))
assert shader.pg_use_bake and nodes.bake_graph.structure_valid(shader.node_tree)
# Without a recoverable live child the policy must install direct magenta
# output. Emergency output cannot depend on a functioning template asset.
wrapper_snapshot = nodes._kernel_snapshot(shader)
shader.node_tree.nodes.remove(nodes.bake_graph.marked(shader.node_tree, nodes.bake_graph.LIVE))
nodes._reconcile_bake_outputs((shader,))
assert not shader.pg_use_bake and shader.get(nodes._NODE_ERROR)
assert not shader.node_tree.get(nodes.bake_graph.WRAPPER)
assert shader.node_tree.get(nodes._ERROR_KERNEL_KIND) == nodes._KERNEL_SCHEMA
assert shader.inputs.get("Vector") is not None
emergency_snapshot = nodes._kernel_snapshot(shader)
assert emergency_snapshot["values"] == wrapper_snapshot["values"]
assert emergency_snapshot["links"] == wrapper_snapshot["links"]
emergency_output = next(item for item in shader.node_tree.nodes
                        if item.bl_idname == "NodeGroupOutput")
assert tuple(emergency_output.inputs["Color"].default_value) == (1.0, 0.0, 1.0, 1.0)
alpha_link, = emergency_output.inputs["Alpha"].links
assert alpha_link.from_node.bl_idname == "NodeGroupInput"
assert alpha_link.from_socket.name == "Alpha"
# Background fixtures explicitly deliver the next host reconciliation.
assert not nodes._refresh_nodes((shader,))
wait_ready(shader)
recovered_snapshot = nodes._kernel_snapshot(shader)
assert recovered_snapshot["values"] == wrapper_snapshot["values"]
assert recovered_snapshot["links"] == wrapper_snapshot["links"]
shader.pg_use_bake = True
assert shader.pg_use_bake
assert nodes.bake_graph.structure_valid(shader.node_tree)
# Wrapper repair retires the previous RNA nodes; reacquire their replacements.
shader_selectors = tuple(item for item in shader.node_tree.nodes
                         if item.get(nodes.bake_graph.SELECTOR))

# UI changes and timer reconciliation must not edit a graph held by a render.
gate = nodes._grade_resources.gate
gate.evaluation_started("render", scene.as_pointer())
try:
    shader.pg_use_bake = False
    nodes._bake_tick()
    assert all(float(item.inputs[0].default_value) == 1.0 for item in shader_selectors)
finally:
    gate.evaluation_finished("render", scene.as_pointer())
nodes._bake_tick()
assert all(float(item.inputs[0].default_value) == 0.0 for item in shader_selectors)
shader.pg_use_bake = True
assert shader.pg_use_bake

# Unchanged baked outputs use a cheap observation. A native image dependency
# update forces a full comparison and cannot leave modified pixels current.
nodes._remember_bake_observation(shader)
original_describe = nodes.bake_routes.describe
def reject_full_idle_read(*_args, **_kwargs):
    raise AssertionError("Idle bake polling read full source pixels")
nodes.bake_routes.describe = reject_full_idle_read
try:
    nodes._reconcile_bake_outputs((shader,), exact=False)
    assert shader.pg_use_bake
finally:
    nodes.bake_routes.describe = original_describe
original_pixels = np.asarray(source_image.pixels[:], dtype=np.float32)
changed_pixels = original_pixels.copy()
changed_pixels[0] += .05
source_image.pixels.foreach_set(changed_pixels)
source_image.update()
nodes._depsgraph_update_post(scene, SimpleNamespace(
    updates=(SimpleNamespace(id=source_image),)))
nodes._reconcile_bake_outputs((shader,), exact=False)
assert not shader.pg_use_bake
source_image.pixels.foreach_set(original_pixels)
source_image.update()
source_image.pack()
shader.pg_use_bake = True
assert shader.pg_use_bake

# Blender passes an initially shared node_tree to the copy callback.  Exercise
# that callback directly in the background fixture before changing the copy.
copied = nodes.create_node(shader_tree)
copied.pg_grade = grade_data
copied.node_tree = shader.node_tree
nodes.PGShaderGrade.copy(copied, shader)
link_source(shader_tree, copied, source)
copied.pg_bake_image = shader.pg_bake_image
copied.pg_use_bake = True
assert copied.pg_use_bake, copied.get(nodes._BAKE_ERROR)
assert_wrapper_independent(shader, copied)

# Converting a baked Shader Grade drops only its baked Vector input. A failed
# conversion must still restore that input and its link on the original node.
copied.inputs["Color"].default_value = (0.12, 0.23, 0.34, 0.45)
copied.inputs["Alpha"].default_value = 0.625
copied.inputs["Vector"].default_value = (0.1, 0.2, 0.3)
copied["user_conversion_marker"] = "keep"
coordinates = shader_tree.nodes.new("ShaderNodeUVMap")
shader_tree.links.new(coordinates.outputs["UV"], copied.inputs["Vector"])
color_reader = shader_tree.nodes.new("ShaderNodeSeparateColor")
alpha_reader = shader_tree.nodes.new("ShaderNodeMath")
shader_tree.links.new(copied.outputs["Color"], color_reader.inputs["Color"])
shader_tree.links.new(copied.outputs["Alpha"], alpha_reader.inputs[0])
copied.pg_bake_image = None
copied.pg_bake_image = shader.pg_bake_image
copied.pg_use_bake = True
assert copied.pg_use_bake, copied.get(nodes._BAKE_ERROR)
original_wrapper = copied.node_tree
original_image = copied.pg_bake_image
original_remove = nodes._remove_conversion_source


def reject_conversion_removal(_tree, _node):
    raise RuntimeError("Injected baked conversion rollback")


nodes._remove_conversion_source = reject_conversion_removal
try:
    try:
        nodes.convert_grade_node(copied, "NODE")
    except RuntimeError as error:
        assert str(error) == "Injected baked conversion rollback", error
    else:
        raise AssertionError("Injected baked conversion did not fail")
finally:
    nodes._remove_conversion_source = original_remove
assert copied.node_tree == original_wrapper
assert copied.pg_bake_image == original_image and copied.pg_use_bake
assert copied.inputs["Vector"].links[0].from_node == coordinates
np.testing.assert_allclose(copied.inputs["Vector"].default_value, (0.1, 0.2, 0.3))
converted = nodes.convert_grade_node(copied, "NODE")
wait_ready(converted)
assert nodes._is_per_node_grade_node(converted)
assert converted.inputs.get("Vector") is None
assert not hasattr(converted, "pg_bake_image")
assert not any(key.startswith("_pg_next_bake_") for key in converted.keys())
assert converted["user_conversion_marker"] == "keep"
np.testing.assert_allclose(converted.inputs["Color"].default_value, (0.12, 0.23, 0.34, 0.45))
assert converted.inputs["Alpha"].default_value == 0.625
assert converted.inputs["Color"].links[0].from_socket == source.outputs["Color"]
assert converted.inputs["Alpha"].links[0].from_socket == source.outputs["Alpha"]
assert color_reader.inputs["Color"].links[0].from_node == converted
assert alpha_reader.inputs[0].links[0].from_node == converted
assert shader.pg_bake_image == original_image and shader.pg_use_bake

# A second shared node can re-use and update the same managed Image.
shared = nodes.create_node(shader_tree)
shared.pg_grade = grade_data
link_source(shader_tree, shared, source)
wait_ready(shared)
shared.pg_bake_image = shader.pg_bake_image
shared.pg_use_bake = True
assert shared.pg_use_bake, shared.get(nodes._BAKE_ERROR)
# The request timer must be re-armed after its idle callback returned None.
if bpy.app.timers.is_registered(nodes._bake_tick):
    bpy.app.timers.unregister(nodes._bake_tick)
assert not bpy.app.timers.is_registered(nodes._bake_tick)
shared_values = bake(shared, shader_context(material, scene, node=shared))
nodes._bake_tick()
assert shader.pg_use_bake and shared.pg_use_bake
shared_rebake = shared.pg_bake_image == shader.pg_bake_image and shared_values.size == shader_values.size

# Editing the authoritative Grade leaves baked mode and restores the live
# child kernel after the replacement has become current.
old_live = nodes.bake_graph.live_tree(shader.node_tree)
old_signature = old_live.get(nodes._KERNEL_SIGNATURE)
old_wrapper = shader.node_tree
grade_data.pg_linear.exposure = 0.375
wait_ready(shader)
nodes._bake_tick()
assert not shader.pg_use_bake
new_live = nodes.bake_graph.live_tree(shader.node_tree)
assert new_live is not None and new_live.get(nodes._KERNEL_SIGNATURE) != old_signature
assert shader.node_tree == old_wrapper
shader.pg_use_bake = True
assert not shader.pg_use_bake, "A stale bake was relabeled current by the toggle"

# UV route through Cycles and a non-overlapping square mesh.
scene.render.engine = "CYCLES"
mesh = bpy.data.meshes.new("Bake Mesh")
mesh.from_pydata(((-1, -1, 0), (1, -1, 0), (1, 1, 0), (-1, 1, 0)), (), ((0, 1, 2, 3),))
uv = mesh.uv_layers.new(name="BakeUV")
for item, value in zip(uv.data, ((0, 0), (1, 0), (1, 1), (0, 1))):
    item.uv = value
uv.active_render = True
obj = bpy.data.objects.new("Bake Object", mesh)
scene.collection.objects.link(obj)
mesh.materials.append(material)
obj.active_material_index = 0
uv_node = nodes.create_node(shader_tree)
uv_node.pg_grade = grade_data
link_source(shader_tree, uv_node, source, uv=True)
uv_node.pg_bake_width = 16
uv_node.pg_bake_height = 16
wait_ready(uv_node)
uv_values = bake(uv_node, shader_context(material, scene, obj, uv_node))
assert uv_node.pg_bake_image.get(nodes._BAKE_DOMAIN) == "UV"
assert uv_values.shape == (16 * 16 * 4,)

# Compositor route uses the native compositor capture path.
scene.render.engine = "BLENDER_EEVEE"
camera_data = bpy.data.cameras.new("Bake Camera Data")
camera = bpy.data.objects.new("Bake Camera", camera_data)
scene.collection.objects.link(camera)
scene.camera = camera
compositor = bpy.data.node_groups.new("Bake Compositor", nodes.COMPOSITOR_TREE)
compositor.interface.new_socket(name="Image", in_out="OUTPUT", socket_type="NodeSocketColor")
comp_output = compositor.nodes.new("NodeGroupOutput")
comp_output.is_active_output = True
comp_source = compositor.nodes.new("CompositorNodeImage")
comp_source.image = source_image
comp_grade = nodes.create_node(compositor)
comp_grade.pg_grade = grade_data
compositor.links.new(comp_source.outputs["Image"], comp_grade.inputs["Color"])
compositor.links.new(comp_grade.outputs["Color"], comp_output.inputs["Image"])
scene.compositing_node_group = compositor
wait_ready(comp_grade)
comp_values = bake(comp_grade, compositor_context(scene, compositor, comp_grade))
assert comp_grade.pg_bake_image.get(nodes._BAKE_DOMAIN) == "COMPOSITOR"
assert comp_values.size
comp_grade.pg_use_bake = False
comp_grade.pg_bake_image = shader.pg_bake_image
comp_grade.pg_use_bake = True
assert comp_grade.pg_use_bake, comp_grade.get(nodes._BAKE_ERROR)
comp_grade.pg_use_bake = False

# A signature change before the first poll invalidates the queued request.
scene.render.engine = "CYCLES"
stale = nodes.create_node(shader_tree)
stale_grade = nodes._make_grade(grade_data)
stale.pg_grade = stale_grade
link_source(shader_tree, stale, source, uv=True)
wait_ready(stale)
nodes._bake_request(stale, shader_context(material, scene, obj, stale))
stale_grade.pg_linear.exposure = .75
nodes._bake_tick()
assert not stale.pg_use_bake and stale.pg_bake_image is None
assert nodes._bake_manager._node_key(stale) not in nodes._bake_manager.jobs
stale_discarded = True

# Stack route is evaluated through the populated 65^3 LUT when the helper is available.
stack_tree = bpy.data.node_groups.new("Bake Stack Compositor", nodes.COMPOSITOR_TREE)
stack_tree.interface.new_socket(name="Image", in_out="OUTPUT", socket_type="NodeSocketColor")
stack_output = stack_tree.nodes.new("NodeGroupOutput")
stack_output.is_active_output = True
stack = nodes.create_stack_node(stack_tree)
stack_context = compositor_context(scene, stack_tree, stack)
scene.compositing_node_group = stack_tree
entry_context = SimpleNamespace(pg_stack_node=stack)
assert nodes.PG_OT_stack_action.execute(SimpleNamespace(action="ADD"), entry_context) == {"FINISHED"}
assert nodes.PG_OT_new_stack_grade.execute(SimpleNamespace(index=0), entry_context) == {"FINISHED"}
stack_tree.links.new(stack.outputs["Color"], stack_output.inputs["Image"])
try:
    wait_ready(stack, stack=True)
    stack_values = bake(stack, stack_context)
    stack_ok = bool(stack_values.size and stack.pg_bake_image is not None)
except (AssertionError, RuntimeError, TimeoutError, ValueError) as error:
    raise AssertionError("Stack Bake acceptance failed: " + str(error)) from error

report = {
    "passed": True,
    "domains": ["IMAGE", "UV", "COMPOSITOR"],
    "stack": stack_ok,
    "packed_float": all(item.pg_bake_image is not None and item.pg_bake_image.is_float
                         and item.pg_bake_image.packed_file is not None
                         for item in (shader, shared, uv_node, comp_grade)),
    "live_restored": live_restored,
    "shared_rebake": shared_rebake,
    "stale_discarded": stale_discarded,
    "wrapper_independent": True,
    "wrapper_recovery": True,
    "baked_conversion": True,
    "grade_edit_live_fallback": True,
    "identity_match": identity_match,
    "render_admission": True,
    "source_edit_fallback": True,
}

# Preserve the latest active bake across a real save/load; resolve every RNA
# pointer again after open_mainfile, including the nested live kernel.
stack_tree_name, stack_name = stack_tree.name, stack.name
packed_values = np.asarray(stack.pg_bake_image.pixels[:], dtype=np.float32)
with tempfile.TemporaryDirectory(prefix="pg-next-bake-save-") as directory:
    blend_path = str(Path(directory) / "bake.blend")
    assert "FINISHED" in bpy.ops.wm.save_as_mainfile(filepath=blend_path)
    assert "FINISHED" in bpy.ops.wm.open_mainfile(filepath=blend_path)
    restored_tree = bpy.data.node_groups.get(stack_tree_name)
    assert restored_tree is not None
    restored_stack = restored_tree.nodes.get(stack_name)
    assert restored_stack is not None
    wait_ready(restored_stack, stack=True)
    nodes._bake_tick()
    assert restored_stack.pg_use_bake, restored_stack.get(nodes._BAKE_ERROR)
    restored_image = restored_stack.pg_bake_image
    assert restored_image is not None and restored_image.is_float
    assert restored_image.packed_file is not None and not restored_image.is_dirty
    np.testing.assert_array_equal(np.asarray(restored_image.pixels[:], dtype=np.float32),
                                  packed_values)
report["persistence"] = True

# Exercise the add-on teardown after all native helper work has retired.
extension.unregister()
deadline = time.monotonic() + 30
while nodes._bake_manager is not None and time.monotonic() < deadline:
    # Background scripts do not yield Blender's timer loop. Honor the return
    # value just as the host does when invoking this timer callback.
    if nodes._bake_tick() is None and bpy.app.timers.is_registered(nodes._bake_tick):
        bpy.app.timers.unregister(nodes._bake_tick)
    time.sleep(.01)
assert nodes._bake_manager is None
assert not bpy.app.timers.is_registered(nodes._bake_tick)
report["teardown"] = True
report_path.write_text(json.dumps(report))

