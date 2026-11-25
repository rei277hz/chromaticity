"""Exercise the installed bake implementation inside native Blender."""

import addon_utils
import importlib
import json
from pathlib import Path
import sys
import tempfile
import time
from types import SimpleNamespace
from unittest.mock import patch

import bpy
import numpy as np


repository, report_path = map(Path, sys.argv[sys.argv.index("--") + 1:])
bpy.context.preferences.extensions.repos.new(
    name="Perceptual Grade bake test", module="pg_bake",
    custom_directory=str(repository),
)
extension = importlib.import_module("bl_ext.pg_bake.perceptual_grade")
nodes = importlib.import_module("bl_ext.pg_bake.perceptual_grade.features.grade.host")
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
        manager = nodes._bake.manager
        if manager is None or manager._node_key(node) not in manager.jobs:
            return
        time.sleep(.01)
    raise TimeoutError("Bake did not retire")


def image(name, pixels, width, height, *, float_buffer=True):
    value = bpy.data.images.new(name, width=width, height=height,
                                alpha=True, float_buffer=float_buffer)
    value.colorspace_settings.name = "Non-Color"
    value.alpha_mode = "CHANNEL_PACKED"
    if hasattr(value, "use_half_precision"):
        value.use_half_precision = False
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


def assert_bake_controls(node, context, warning=None, *, can_bake=None, legacy=False):
    observed = {"labels": []}

    class Layout:
        def __init__(self):
            self.enabled = True

        def separator(self):
            pass

        def context_pointer_set(self, *_args):
            pass

        def box(self):
            return Layout()

        def row(self, **_kwargs):
            return Layout()

        def label(self, *, text, **_kwargs):
            observed["labels"].append(text)

        def prop(self, _node, name, **_kwargs):
            if name == "pg_use_bake":
                observed["enabled"] = self.enabled

        def operator(self, name, **_kwargs):
            if name == "perceptual_grade.bake":
                observed["can_bake"] = self.enabled
            return SimpleNamespace()

    nodes._draw_bake_controls(node, context, Layout())
    assert observed["enabled"], observed["labels"]
    if can_bake is not None:
        assert observed["can_bake"] == can_bake, observed["labels"]
    warning_texts = {
        nodes.localization.tr("status.bake_stale_" + reason)
        for reason in ("engine", "source", "route", "inputs", "canvas_size", "unverified")
    }
    expected = set() if warning is None else {nodes.localization.tr(warning)}
    assert warning_texts.intersection(observed["labels"]) == expected, observed["labels"]
    legacy_label = nodes.localization.tr("status.bake_legacy_source_unverified")
    assert (legacy_label in observed["labels"]) == legacy, observed["labels"]


def assert_shader_uses_image(node, image):
    reader = nodes.bake_graph.marked(node.node_tree, nodes.bake_graph.READER)
    selectors = tuple(item for item in node.node_tree.nodes if item.get(nodes.bake_graph.SELECTOR))
    assert node.pg_use_bake and node.pg_bake_image == image
    assert reader.image == image
    assert selectors and all(float(item.inputs[0].default_value) == 1.0 for item in selectors)


def foreground_cycles_settings(scene):
    addon = bpy.context.preferences.addons.get("cycles")
    preferences = None if addon is None else addon.preferences
    return (scene.cycles.device,
            None if preferences is None else preferences.compute_device_type,
            () if preferences is None else tuple(
                (device.id, device.type, device.use) for device in preferences.devices))


def foreground_render_settings(scene):
    return (scene.render.engine, scene.render.resolution_x, scene.render.resolution_y,
            scene.render.resolution_percentage, scene.render.use_compositing,
            scene.render.use_sequencer, scene.render.compositor_device,
            scene.render.compositor_precision)


def bake(node, context, *, on_queued=None):
    is_shader = node.id_data.bl_idname == nodes.SHADER_TREE
    original_cycles_settings = foreground_cycles_settings(context.scene) if is_shader else None
    original_render_settings = foreground_render_settings(context.scene)
    operator = SimpleNamespace(cancel=False, node_pointer="", tree_pointer="")
    assert nodes.PG_OT_bake.execute(operator, context) == {"FINISHED"}
    assert bpy.app.timers.is_registered(nodes._bake_tick), "Bake request did not wake its timer"
    request = nodes._bake.manager.jobs[nodes._bake.manager._node_key(node)]
    if on_queued is not None:
        on_queued()
    wait_bake(node)
    assert node.pg_bake_image is not None, node.get(nodes.bake_controller.BAKE_ERROR)
    assert node.pg_bake_image.packed_file is not None
    assert node.pg_bake_image.is_float
    assert node.pg_bake_image.get(nodes.bake_controller.BAKE_SOURCE_VERIFICATION) == 1
    assert not node.pg_bake_image.is_dirty
    assert node.pg_use_bake
    values = np.asarray(node.pg_bake_image.pixels[:], dtype=np.float32)
    assert values.size and np.isfinite(values).all()
    render_settings = foreground_render_settings(context.scene)
    assert original_render_settings == render_settings, (original_render_settings, render_settings)
    result = request["result"]
    if is_shader:
        cycles_settings = foreground_cycles_settings(context.scene)
        assert original_cycles_settings == cycles_settings, (original_cycles_settings, cycles_settings)
        assert request["route"]["shader_backend"] == "CYCLES_CPU", request["route"]
        assert (result["backend"], result["device"]) == ("CYCLES", "CPU"), result
    else:
        assert result["backend"] == "COMPOSITOR", result
    return values


def add_solid_effect(scene):
    tree = bpy.data.node_groups.new("Bake downstream color", nodes.COMPOSITOR_TREE)
    tree.interface.new_socket(name="Image", in_out="OUTPUT", socket_type="NodeSocketColor")
    output = tree.nodes.new("NodeGroupOutput")
    output.inputs["Image"].default_value = (1., 0., 1., 1.)
    effect = scene.compositor_effects.new("Downstream color")
    effect.node_group = tree
    scene.compositor_effects.active = effect
    return effect


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


def bake_linked_images(scene, mesh_object, material, directory):
    """Evaluate exact Image datablocks even when all three share one name."""
    name = "Bake Duplicate Image Name"
    float_rgba = np.array([
        [-.025, .20, .30, 1.], [1.35, .80, .90, 1.],
    ], dtype=np.float32)
    byte_rgba = np.array([
        [51, 102, 153, 64], [153, 102, 51, 192],
    ], dtype=np.float32) / 255
    linked = []
    library_paths = (directory / "bake-float.blend", directory / "bake-byte.blend")
    packed_rgba = np.full((2, 4), .5, dtype=np.float32)
    for path, is_float in zip(library_paths, (True, False)):
        test_image = image(name, packed_rgba, 2, 1, float_buffer=is_float)
        if not is_float:
            test_image.colorspace_settings.name = "sRGB"
            test_image.alpha_mode = "STRAIGHT"
        bpy.data.libraries.write(str(path), {test_image}, fake_user=True)
        bpy.data.images.remove(test_image)
    for path in library_paths:
        with bpy.data.libraries.load(str(path), link=True) as (available, imported):
            assert name in available.images
            imported.images = [name]
        linked.append(imported.images[0])
    decoy = image(name, ((.5, .5, .5, 1.),), 1, 1)
    assert len({source.as_pointer() for source in (*linked, decoy)}) == 3
    assert all(source.name == name for source in (*linked, decoy))
    assert tuple(source.is_float for source in linked) == (True, False)
    assert tuple(Path(bpy.path.abspath(source.library.filepath)).resolve()
                 for source in linked) == library_paths
    for source, values in zip(linked, (float_rgba, byte_rgba)):
        # The private snapshot must receive the live buffer. Loading the
        # linked library alone would produce the original gray pixels.
        source.pixels.foreach_set(values.ravel())
        source.update()
        np.testing.assert_allclose(np.asarray(source.pixels[:]).reshape(2, 4),
                                   values, rtol=0, atol=1e-6)

    shader_tree = material.node_tree
    float_texture, byte_texture, decoy_texture = (
        shader_tree.nodes.new("ShaderNodeTexImage") for _ in range(3))
    for texture, source in zip((float_texture, byte_texture, decoy_texture), (*linked, decoy)):
        texture.image = source
        texture.interpolation = "Closest"
    grade = nodes._make_grade()
    shader = nodes.create_node(shader_tree)
    shader.pg_grade = grade
    coordinates = shader_tree.nodes.new("ShaderNodeUVMap")
    for texture in (float_texture, byte_texture):
        shader_tree.links.new(coordinates.outputs["UV"], texture.inputs["Vector"])
    shader_tree.links.new(float_texture.outputs["Color"], shader.inputs["Color"])
    shader_tree.links.new(byte_texture.outputs["Alpha"], shader.inputs["Alpha"])
    shader.pg_bake_width = 8
    shader.pg_bake_height = 4
    wait_ready(shader)
    bpy.context.view_layer.update()
    shader_pixels = bake(shader, shader_context(material, scene, mesh_object, shader))
    assert shader.pg_bake_image.get(nodes.bake_controller.BAKE_DOMAIN) == "UV"
    expected_uv = float_rgba.copy()
    expected_uv[:, 3] = byte_rgba[:, 3]
    expected_uv = expected_uv.reshape(1, 2, 4).repeat(4, axis=0).repeat(4, axis=1)
    np.testing.assert_allclose(shader_pixels.reshape(4, 8, 4), expected_uv,
                               rtol=0, atol=0.002)

    compositor = bpy.data.node_groups.new("Linked Bake Compositor", nodes.COMPOSITOR_TREE)
    compositor.interface.new_socket(name="Image", in_out="OUTPUT", socket_type="NodeSocketColor")
    output = compositor.nodes.new("NodeGroupOutput")
    output.is_active_output = True
    source = compositor.nodes.new("CompositorNodeImage")
    source.image = linked[1]
    # Use opaque colors here so file output and alpha association are independent
    # of the exact Image and byte-storage behavior exercised by this capture.
    byte_rgba[:, 3] = 1.
    linked[1].pixels.foreach_set(byte_rgba.ravel())
    linked[1].update()
    nodes.invalidate_source(linked[1])
    compositor.nodes.new("CompositorNodeImage").image = decoy
    comp_grade = nodes.create_node(compositor)
    comp_grade.pg_grade = grade
    compositor.links.new(source.outputs["Image"], comp_grade.inputs["Color"])
    compositor.links.new(comp_grade.outputs["Color"], output.inputs["Image"])
    scene.compositing_node_group = compositor
    wait_ready(comp_grade)
    comp_pixels = bake(comp_grade, compositor_context(scene, compositor, comp_grade))
    assert tuple(comp_grade.pg_bake_image.size) == (2, 1)
    # All sampled sRGB channels are above the transfer function's linear segment.
    expected_linear = byte_rgba.copy()
    expected_linear[:, :3] = ((byte_rgba[:, :3] + 0.055) / 1.055) ** 2.4
    np.testing.assert_allclose(comp_pixels.reshape(2, 4), expected_linear, rtol=0, atol=0.002)
    assert float_texture.image == linked[0] and byte_texture.image == linked[1]
    assert source.image == linked[1]
    for source, values in zip(linked, (float_rgba, byte_rgba)):
        np.testing.assert_allclose(np.asarray(source.pixels[:]).reshape(2, 4),
                                   values, rtol=0, atol=1e-6)


def check_bake_upstream_grade_identity(scene, directory):
    group = bpy.data.node_groups.new("Bake Grade Identity Collision", nodes.SHADER_TREE)
    group.interface.new_socket(name="Color", in_out="OUTPUT", socket_type="NodeSocketColor")
    output = group.nodes.new("NodeGroupOutput")
    upstream = nodes.create_node(group)
    upstream.pg_grade = nodes._make_grade()
    group.links.new(upstream.outputs["Color"], output.inputs["Color"])
    wait_ready(upstream)

    library_path = directory / "bake-grade-decoy.blend"
    bpy.data.libraries.write(str(library_path), {group}, fake_user=True)
    with bpy.data.libraries.load(str(library_path), link=True) as (available, imported):
        assert group.name in available.node_groups
        imported.node_groups = [group.name]
    decoy_group = imported.node_groups[0]
    assert decoy_group.library is not None and decoy_group.name == group.name
    decoy = decoy_group.nodes[upstream.name]
    assert decoy.as_pointer() != upstream.as_pointer()
    assert any(node == decoy for node in nodes._all_grade_nodes())

    material = bpy.data.materials.new("Bake Grade Identity")
    material.use_nodes = True
    tree = material.node_tree
    occurrence = tree.nodes.new("ShaderNodeGroup")
    occurrence.node_tree = group
    target = nodes.create_node(tree)
    target.pg_grade = nodes._make_grade()
    tree.links.new(occurrence.outputs["Color"], target.inputs["Color"])
    wait_ready(target)

    context = shader_context(material, scene, node=target)
    original_refresh = nodes._refresh_nodes
    manager = nodes._bake.manager
    failure = RuntimeError("Injected Bake upstream preparation failure")
    failed_pointer = upstream.as_pointer()
    queued = []

    def refresh_with_failure(candidates, *args, **kwargs):
        candidates = tuple(candidates)
        for candidate in candidates:
            if candidate.as_pointer() == failed_pointer:
                return (((candidate,), failure),)
        return original_refresh(candidates, *args, **kwargs)

    try:
        nodes._refresh_nodes = refresh_with_failure
        manager.request = lambda node, *_args, **_kwargs: queued.append(node.as_pointer())
        try:
            nodes._bake.request(target, context)
        except RuntimeError as error:
            assert str(failure) in str(error)
        else:
            raise AssertionError("Bake accepted a failed upstream Grade")
        assert not queued

        failed_pointer = decoy.as_pointer()
        nodes._bake.request(target, context)
        assert queued == [target.as_pointer()]
    finally:
        nodes._refresh_nodes = original_refresh
        del manager.request
        nodes._bake.sources.forget(("request", target.as_pointer()))


def check_render_layers_indirect_sources(scene, target, context):
    layer = scene.view_layers[0]
    original_override = layer.material_override
    camera = scene.camera
    original_camera = (camera.location.copy(), camera.data.type, camera.data.ortho_scale)
    material = bpy.data.materials.new("Bake indirect source material")
    material.use_nodes = True
    tree = material.node_tree
    grade = nodes.create_node(tree)
    grade.pg_grade = nodes._make_grade()
    grade.inputs["Color"].default_value = (.22, .15, .09, 1.)
    emission = tree.nodes.new("ShaderNodeEmission")
    tree.links.new(grade.outputs["Color"], emission.inputs["Color"])
    tree.links.new(emission.outputs["Emission"], tree.nodes["Material Output"].inputs["Surface"])
    wait_ready(grade)
    replacement = bpy.data.materials.new("Bake replacement layer override")
    replacement.use_nodes = True
    replacement_tree = replacement.node_tree
    replacement_emission = replacement_tree.nodes.new("ShaderNodeEmission")
    replacement_emission.inputs["Color"].default_value = (.02, .45, .20, 1.)
    replacement_tree.links.new(replacement_emission.outputs["Emission"],
                               replacement_tree.nodes["Material Output"].inputs["Surface"])
    source = bpy.data.collections.new("Bake instance source")
    mesh = bpy.data.meshes.new("Bake indirect mesh")
    mesh.from_pydata(((-2, -2, 3), (2, -2, 3), (2, 2, 3), (-2, 2, 3)), (), ((0, 1, 2, 3),))
    obj = bpy.data.objects.new("Bake indirect object", mesh)
    source.objects.link(obj)
    mesh.materials.append(material)
    instance = bpy.data.objects.new("Bake collection instance", None)
    scene.collection.objects.link(instance)
    instance.instance_type = "COLLECTION"
    instance.instance_collection = source
    try:
        for binding in ("instance", "override"):
            if binding == "override":
                instance.instance_type = "NONE"
                layer.material_override = material
            bpy.context.view_layer.update()
            upstream = []
            nodes.bake_routes.describe(target, context, upstream_grades=upstream)
            assert upstream.count(grade) == 1, (binding, upstream)
            nodes._bake.request(target, context)
            key = target.as_pointer()
            pending = nodes._bake.manager.jobs[key]
            signature = pending["route"]["request_signature"]
            grade.pg_grade.pg_linear.exposure += .25
            assert nodes._bake.current_signature(target, pending["route"]) != signature, binding
            nodes._bake_tick()
            assert key not in nodes._bake.manager.jobs, binding
            assert target.pg_use_bake and target.pg_bake_image is not None

        # Give only the selected view layer's override control of these pixels.
        scene.collection.objects.link(obj)
        mesh.materials.clear()
        camera.location = (0., 0., 5.)
        camera.data.type = "ORTHO"
        camera.data.ortho_scale = 2.
        bpy.context.view_layer.update()
        before = bake(target, context)
        image = target.pg_bake_image
        assert_bake_controls(target, context, can_bake=True)
        layer.material_override = replacement
        bpy.context.view_layer.update()
        assert_bake_controls(target, context, "status.bake_stale_inputs", can_bake=True)
        assert target.pg_use_bake and target.pg_bake_image == image
        np.testing.assert_array_equal(np.asarray(image.pixels[:]), before)
        after = bake(target, context)
        assert_bake_controls(target, context, can_bake=True)
        width, height = tuple(image.size)
        old_rgb = before.reshape(height, width, 4)[height // 2, width // 2, :3]
        new_rgb = after.reshape(height, width, 4)[height // 2, width // 2, :3]
        assert np.max(np.abs(new_rgb - old_rgb)) > .03, (old_rgb, new_rgb)
    finally:
        camera.location, camera.data.type, camera.data.ortho_scale = original_camera
        layer.material_override = original_override
        scene.collection.objects.unlink(instance)
        scene.collection.objects.unlink(obj)


scene = bpy.context.scene
scene.frame_set(1)
scene.render.resolution_percentage = 100
scene.render.resolution_x = 32
scene.render.resolution_y = 32
scene.render.engine = "CYCLES"
scene.cycles.device = "CPU"

# Shader Image route, including the independent Alpha emission pass.
material = bpy.data.materials.new("Bake Material")
material.use_nodes = True
shader_tree = material.node_tree
shader_tree.nodes.clear()
grade_data = nodes._make_grade()
shader = nodes.create_node(shader_tree)
shader.pg_grade = grade_data
# In-gamut AP1 colors can have negative or above-one channels in Rec.709.
source_rgba = np.array([
    [-.025, .20, .30, .20], [.30, .40, .50, .40],
    [.50, .60, .70, .60], [1.35, .80, .90, .80],
], dtype=np.float32)
source_image = image("Bake Source", source_rgba, 2, 2)
source = shader_tree.nodes.new("ShaderNodeTexImage")
source.image = source_image
source.interpolation = "Closest"
link_source(shader_tree, shader, source)
wait_ready(shader)

# A first bake has no published receipt. Every reconciliation and helper
# completion must use cheap source revisions rather than reading source pixels.
assert shader.get(nodes.bake_controller.BAKE_NODE_SIGNATURE) is None
nodes._bake.request(shader, shader_context(material, scene, node=shader))
manager = nodes._bake.manager
node_key = manager._node_key(shader)
request = manager.jobs[node_key]
manager._start_next()
assert manager.active is request
original_describe = nodes.bake_routes.describe


def reject_pending_pixel_read(*_args, **_kwargs):
    raise AssertionError("Pending bake revalidation performed a full route scan")


nodes.bake_routes.describe = reject_pending_pixel_read
original_source_pixels = np.asarray(source_image.pixels[:], dtype=np.float32)
try:
    for _ in range(3):
        nodes._bake.reconcile((shader,))
        assert manager.active is request and manager.jobs[node_key] is request
        assert shader.get(nodes.bake_controller.BAKE_NODE_SIGNATURE) is None
    unrelated_image = image("Bake Unrelated Source", np.ones((1, 4), np.float32), 1, 1)
    nodes._depsgraph_update_post(scene, SimpleNamespace(
        updates=(SimpleNamespace(id=unrelated_image),)))
    assert nodes._bake.current_signature(shader, request["route"]) == request["route"]["request_signature"]
    nodes._bake.reconcile((shader,))
    assert manager.active is request and manager.jobs[node_key] is request

    # Python pixel writes have no dependable native change notification. A
    # script must explicitly invalidate the source after it changes the buffer.
    changed_source_pixels = original_source_pixels.copy()
    changed_source_pixels[0] += .05
    source_image.pixels.foreach_set(changed_source_pixels)
    nodes.invalidate_source(source_image)
    assert nodes._bake.current_signature(shader, request["route"]) is None
    nodes._bake.reconcile((shader,))
    deadline = time.monotonic() + 300
    while node_key in manager.jobs and time.monotonic() < deadline:
        manager.poll()
        time.sleep(.01)
    assert node_key not in manager.jobs, "Stale Bake helper did not retire"
    assert manager.active is None
    assert shader.pg_bake_image is None and not shader.pg_use_bake
    assert shader.get(nodes.bake_controller.BAKE_NODE_SIGNATURE) is None
finally:
    nodes.bake_routes.describe = original_describe
    source_image.pixels.foreach_set(original_source_pixels)
    source_image.update()
    source_image.pack()
    nodes.invalidate_source(source_image)

original_write_receipt = nodes._bake.write_receipt
transaction_receipt_clears = []


def observe_receipt_write(node, signature, *args, **kwargs):
    if node == shader and signature is None:
        transaction_receipt_clears.append(True)
    return original_write_receipt(node, signature, *args, **kwargs)


try:
    nodes._bake.write_receipt = observe_receipt_write
    shader_values = bake(shader, shader_context(material, scene, node=shader))
finally:
    nodes._bake.write_receipt = original_write_receipt
assert not transaction_receipt_clears, "Bake-owned Image assignment ran the user-binding callback"
assert nodes._bake.receipt_signature(shader) == nodes._bake.observed_signature(
    shader, nodes._bake.stored_context(shader)), ("post-rebake", shader.get(nodes.bake_controller.BAKE_ERROR))
assert shader.pg_bake_image.get(nodes.bake_controller.BAKE_DOMAIN) == "IMAGE"
assert np.unique(np.round(shader_values.reshape(-1, 4)[:, 3], 5)).size > 1
image_pixels = shader_values.reshape(-1, 4)
# The default anchors reproduce these in-gamut values and independent alpha.
np.testing.assert_allclose(image_pixels, source_rgba, rtol=0, atol=0.002)
identity_match = True

# Shader bakes use the same private Cycles CPU worker from an EEVEE scene.
scene.render.engine = "BLENDER_EEVEE"
scene.cycles.device = "GPU"
image_context = shader_context(material, scene, node=shader)
eevee_values = bake(shader, image_context)
np.testing.assert_allclose(eevee_values.reshape(-1, 4), source_rgba, rtol=0, atol=0.002)
assert tuple(shader.pg_bake_image.size) == (2, 2)

eevee_image = shader.pg_bake_image
eevee_receipt = nodes._bake.receipt_signature(shader)
assert eevee_receipt is not None
assert_bake_controls(shader, image_context)
scene.render.engine = "CYCLES"
bpy.context.view_layer.update()
nodes._bake.reconcile((shader,))
assert_shader_uses_image(shader, eevee_image)
assert nodes._bake.receipt_signature(shader) == eevee_receipt
assert_bake_controls(shader, image_context, can_bake=True)
scene.render.engine = "BLENDER_EEVEE"
bpy.context.view_layer.update()
nodes._bake.reconcile((shader,))
assert_shader_uses_image(shader, eevee_image)
assert nodes._bake.receipt_signature(shader) == eevee_receipt
assert_bake_controls(shader, image_context)

# A failed replacement restores the selected image, pixels, and receipt.
previous_image = shader.pg_bake_image
del previous_image[nodes.bake_controller.BAKE_SOURCE_VERIFICATION]
previous_receipt = nodes._bake.receipt_signature(shader)
previous_pixels = np.asarray(previous_image.pixels[:], dtype=np.float32).copy()
previous_gain = grade_data.pg_tone.vivid_gain
original_activate = nodes._bake._activate
activation_failures = []


def fail_after_bake_activation(entry, result):
    original_activate(entry, result)
    activation_failures.append("injected")
    raise RuntimeError("Injected Bake activation failure")


try:
    grade_data.pg_tone.vivid_gain = previous_gain + 0.125
    nodes._bake._activate = fail_after_bake_activation
    operator = SimpleNamespace(cancel=False, node_pointer="", tree_pointer="")
    assert nodes.PG_OT_bake.execute(operator, image_context) == {"FINISHED"}
    assert shader.pg_use_bake, "Replacement request disabled the selected bake"
    wait_bake(shader)
    assert activation_failures == ["injected"]
finally:
    nodes._bake._activate = original_activate
    grade_data.pg_tone.vivid_gain = previous_gain

assert_shader_uses_image(shader, previous_image)
np.testing.assert_array_equal(
    np.asarray(previous_image.pixels[:], dtype=np.float32), previous_pixels,
)
assert nodes._bake.receipt_signature(shader) == previous_receipt
assert previous_image.get(nodes.bake_controller.BAKE_SOURCE_VERIFICATION) is None
assert_bake_controls(shader, image_context, legacy=True)

scene.render.engine = "BLENDER_WORKBENCH"
scene.cycles.device = "GPU"
fallback_values = bake(shader, shader_context(material, scene, node=shader))
np.testing.assert_allclose(fallback_values.reshape(-1, 4), source_rgba, rtol=0, atol=0.002)

scene.render.engine = "CYCLES"
shader_values = bake(shader, image_context)
np.testing.assert_allclose(shader_values.reshape(-1, 4), source_rgba, rtol=0, atol=0.002)
scene.cycles.device = "CPU"
assert_bake_controls(shader, image_context)

# A valid managed Image remains available when its persisted receipt predates
# the current route fingerprint. The old receipt warns without disabling the
# selected baked output or the replacement Bake action.
old_fingerprint = "0" * 64
nodes._bake.write_receipt(shader, old_fingerprint,
                          nodes.bake_routes.backend_signature(
                              nodes.bake_routes.preview(shader, image_context)))
assert shader.pg_use_bake and nodes._bake.toggle_available(shader)
assert_bake_controls(shader, image_context, "status.bake_stale_inputs", can_bake=True)
current_shader_signature = nodes._bake.observed_signature(shader, image_context)
nodes._bake.write_receipt(
    shader, current_shader_signature,
    nodes.bake_routes.backend_signature(nodes.bake_routes.preview(shader, image_context)),
)

# Explicitly binding a valid Image establishes a reader baseline even when the
# node had no receipt. Unlinking it clears that baseline and leaves live output.
unverified = nodes.create_node(shader_tree)
unverified.pg_grade = grade_data
link_source(shader_tree, unverified, source)
wait_ready(unverified)
unverified.pg_bake_image = shader.pg_bake_image
if nodes.bake_controller.BAKE_NODE_SIGNATURE in unverified:
    del unverified[nodes.bake_controller.BAKE_NODE_SIGNATURE]
unverified.pg_use_bake = True
unverified_context = shader_context(material, scene, node=unverified)
assert unverified.pg_use_bake and nodes._bake.toggle_available(unverified)
assert_bake_controls(unverified, unverified_context,
                     "status.bake_stale_unverified", can_bake=True)
gate = nodes._grade_resources.gate
gate.evaluation_started("render", scene.as_pointer())
try:
    assert nodes.PG_OT_unlink_bake_image.execute(
        SimpleNamespace(), unverified_context) == {"FINISHED"}
    assert unverified.as_pointer() in nodes._bake.pending_reconciliations
finally:
    gate.evaluation_finished("render", scene.as_pointer())
nodes._bake_tick()
assert unverified.pg_bake_image is None and not unverified.pg_use_bake
assert nodes._bake.receipt_signature(unverified) is None
unverified_reader = nodes.bake_graph.marked(unverified.node_tree, nodes.bake_graph.READER)
unverified_selectors = tuple(
    item for item in unverified.node_tree.nodes if item.get(nodes.bake_graph.SELECTOR)
)
assert unverified_reader.image is None
assert unverified_selectors and all(float(item.inputs[0].default_value) == 0.0
                                    for item in unverified_selectors)

# Polling remains available when the passive node inventory is temporarily
# unavailable. The manager must advance before the inventory is inspected.
manager = nodes._bake.manager
original_nodes = nodes._bake.nodes
original_poll = manager.poll
polls = []


def unavailable_nodes():
    raise RuntimeError("Injected Bake inventory failure")


def tracked_poll():
    polls.append(True)
    return original_poll()


try:
    nodes._bake.nodes = unavailable_nodes
    manager.poll = tracked_poll
    assert nodes._bake_tick() == 0.02
finally:
    nodes._bake.nodes = original_nodes
    manager.poll = original_poll
assert polls

# Use Bake can be disabled and restored without unbinding the managed Image.
shader.pg_use_bake = False
assert not shader.pg_use_bake
assert nodes._bake.toggle_available(shader)
assert nodes._bake.receipt_signature(shader) == nodes._bake.observed_signature(
    shader, nodes._bake.stored_context(shader)), ("manual-off", shader.get(nodes.bake_controller.BAKE_ERROR))
assert_bake_controls(shader, image_context)
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
nodes._bake.reconcile((shader,))
assert shader.pg_use_bake and nodes.bake_graph.structure_valid(shader.node_tree)
assert nodes._bake.toggle_available(shader), ("first-wrapper-repair", shader.get(nodes.bake_controller.BAKE_ERROR))
broken_output = next(item for item in shader.node_tree.nodes
                     if item.bl_idname == "NodeGroupOutput")
shader.node_tree.links.remove(broken_output.inputs["Color"].links[0])
assert not nodes.bake_graph.structure_valid(shader.node_tree)
nodes._bake.reconcile((shader,))
assert shader.pg_use_bake and nodes.bake_graph.structure_valid(shader.node_tree)
assert nodes._bake.toggle_available(shader), ("second-wrapper-repair", shader.get(nodes.bake_controller.BAKE_ERROR))
# Without a recoverable live child the policy must install the packaged
# fail-closed magenta fallback while preserving the public Vector interface.
wrapper_snapshot = nodes._kernel_snapshot(shader)
shader.node_tree.nodes.remove(nodes.bake_graph.marked(shader.node_tree, nodes.bake_graph.LIVE))
nodes._bake.reconcile((shader,))
assert not shader.pg_use_bake and shader.get(nodes._NODE_ERROR)
assert nodes._bake.receipt_signature(shader) is not None, "wrapper failure revoked receipt"
assert not shader.node_tree.get(nodes.bake_graph.WRAPPER)
assert shader.node_tree.get(nodes._ERROR_KERNEL_KIND) == nodes._KERNEL_SCHEMA
assert shader.inputs.get("Vector") is not None
emergency_snapshot = nodes._kernel_snapshot(shader)
assert emergency_snapshot["values"] == wrapper_snapshot["values"]
assert emergency_snapshot["links"] == wrapper_snapshot["links"]
emergency_output = next(item for item in shader.node_tree.nodes
                        if item.bl_idname == "NodeGroupOutput")
magenta_link, = emergency_output.inputs["Color"].links
assert magenta_link.from_node.bl_idname == "ShaderNodeCombineColor"
assert tuple(magenta_link.from_node.inputs[name].default_value
             for name in ("Red", "Green", "Blue")) == (1.0, 0.0, 1.0)
alpha_link, = emergency_output.inputs["Alpha"].links
assert alpha_link.from_node.bl_idname == "NodeGroupInput"
assert alpha_link.from_socket.name == "Alpha"
# Background fixtures explicitly deliver the next host reconciliation.
assert not nodes._refresh_nodes((shader,))
assert nodes._bake.receipt_signature(shader) is not None, "refresh revoked receipt"
wait_ready(shader)
assert nodes._bake.receipt_signature(shader) is not None, "recovery revoked receipt"
recovered_snapshot = nodes._kernel_snapshot(shader)
assert recovered_snapshot["values"] == wrapper_snapshot["values"]
assert recovered_snapshot["links"] == wrapper_snapshot["links"]
shader.pg_use_bake = True
assert shader.pg_use_bake, (
    nodes._bake.receipt_signature(shader),
    nodes._bake.observed_signature(shader, nodes._bake.stored_context(shader)),
    nodes._node_stores[shader.as_pointer()]["state"],
    nodes._bake.image_valid(shader), shader.get(nodes.bake_controller.BAKE_ERROR),
)
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

# Unchanged baked outputs use a cheap observation, including unrelated native
# dependency updates. A relevant source event marks the Image as stale even
# when this test leaves its pixels unchanged.
class RemovedDependencyUpdate:
    @property
    def id(self):
        raise ReferenceError("Depsgraph ID was removed")


nodes._bake._remember_observation(shader)
source_receipt = nodes._bake.receipt_signature(shader)
source_bake = shader.pg_bake_image
original_describe = nodes.bake_routes.describe
def reject_full_idle_read(*_args, **_kwargs):
    raise AssertionError("Idle bake polling read full source pixels")
nodes.bake_routes.describe = reject_full_idle_read
try:
    nodes._depsgraph_update_post(scene, SimpleNamespace(
        updates=(SimpleNamespace(id=unrelated_image),)))
    nodes._bake.reconcile((shader,))
    assert_shader_uses_image(shader, source_bake)
    assert_bake_controls(shader, image_context)
    with patch.object(nodes.vectorscope_ui, "invalidate") as scope_invalidate:
        nodes._depsgraph_update_post(scene, SimpleNamespace(updates=(
            SimpleNamespace(id=unrelated_image),
            RemovedDependencyUpdate(),
            SimpleNamespace(id=source_image),
        )))
        scope_invalidate.assert_called_once_with(scene, [unrelated_image, source_image])
    nodes._bake.reconcile((shader,))
    assert_shader_uses_image(shader, source_bake)
    assert nodes._bake.receipt_signature(shader) == source_receipt
    assert_bake_controls(shader, image_context, "status.bake_stale_source")
    shader.pg_use_bake = False
    assert not shader.pg_use_bake
    assert_bake_controls(shader, image_context, "status.bake_stale_source")
    shader.pg_use_bake = True
    assert_shader_uses_image(shader, source_bake)
finally:
    nodes.bake_routes.describe = original_describe
shader_values = bake(shader, image_context)
assert_bake_controls(shader, image_context)

# Blender passes an initially shared node_tree to the copy callback.  Exercise
# that callback directly in the background fixture before changing the copy.
copied = nodes.create_node(shader_tree)
copied.pg_grade = grade_data
copied.node_tree = shader.node_tree
nodes.PGShaderGrade.copy(copied, shader)
link_source(shader_tree, copied, source)
copied.pg_bake_image = shader.pg_bake_image
copied.pg_use_bake = True
assert copied.pg_use_bake, copied.get(nodes.bake_controller.BAKE_ERROR)
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
assert copied.pg_use_bake, copied.get(nodes.bake_controller.BAKE_ERROR)
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
assert shared.pg_use_bake, shared.get(nodes.bake_controller.BAKE_ERROR)
# The request timer must be re-armed after its idle callback returned None.
if bpy.app.timers.is_registered(nodes._bake_tick):
    bpy.app.timers.unregister(nodes._bake_tick)
assert not bpy.app.timers.is_registered(nodes._bake_tick)
shared_context = shader_context(material, scene, node=shared)
shared_image = shader.pg_bake_image
original_reader_receipt = nodes._bake.receipt_signature(shader)
assert original_reader_receipt is not None
assert_bake_controls(shader, image_context)
shared_values = bake(shared, shared_context)
nodes._bake_tick()
assert_shader_uses_image(shader, shared_image)
assert_shader_uses_image(shared, shared_image)
assert nodes._bake.receipt_signature(shader) == original_reader_receipt
assert_bake_controls(shader, image_context, "status.bake_stale_source")
assert_bake_controls(shared, shared_context)
shared_rebake = shared_values.size == shader_values.size

# Editing the authoritative Grade leaves the bake selected while preparing
# the updated live child. The user can switch between the two outputs.
old_live = nodes.bake_graph.live_tree(shared.node_tree)
old_signature = old_live.get(nodes._KERNEL_SIGNATURE)
old_wrapper = shared.node_tree
old_receipt = nodes._bake.receipt_signature(shared)
grade_data.pg_tone.vivid_gain = 0.375
assert_shader_uses_image(shared, shared_image)
assert_bake_controls(shared, shared_context, "status.bake_stale_inputs")
wait_ready(shared)
nodes._bake_tick()
assert_shader_uses_image(shared, shared_image)
new_live = nodes.bake_graph.live_tree(shared.node_tree)
assert new_live is not None and new_live.get(nodes._KERNEL_SIGNATURE) != old_signature
assert shared.node_tree == old_wrapper
shared.pg_use_bake = False
assert not shared.pg_use_bake
assert_bake_controls(shared, shared_context, "status.bake_stale_inputs")
shared.pg_use_bake = True
assert_shader_uses_image(shared, shared_image)
assert nodes._bake.receipt_signature(shared) == old_receipt
assert_bake_controls(shared, shared_context, "status.bake_stale_inputs")

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
uv_node.pg_grade = nodes._make_grade()
link_source(shader_tree, uv_node, source, uv=True)
uv_node.pg_bake_width = 16
uv_node.pg_bake_height = 16
bpy.context.view_layer.update()
wait_ready(uv_node)
uv_values = bake(uv_node, shader_context(material, scene, obj, uv_node))
assert uv_node.pg_bake_image.get(nodes.bake_controller.BAKE_DOMAIN) == "UV"
assert uv_values.shape == (16 * 16 * 4,)
expected_uv_grade = source_rgba.reshape(2, 2, 4).repeat(8, axis=0).repeat(8, axis=1)
np.testing.assert_allclose(uv_values.reshape(16, 16, 4), expected_uv_grade, rtol=0, atol=0.002)
uv_context = shader_context(material, scene, obj, uv_node)
uv_image = uv_node.pg_bake_image
uv_receipt = nodes._bake.receipt_signature(uv_node)
# Engine and device switches preserve the published result and allow rebaking on the same mesh.
scene.render.engine = "BLENDER_EEVEE"
bpy.context.view_layer.update()
nodes._bake.reconcile((uv_node,))
assert_shader_uses_image(uv_node, uv_image)
assert nodes._bake.receipt_signature(uv_node) == uv_receipt
assert_bake_controls(uv_node, uv_context, can_bake=True)
scene.cycles.device = "GPU"
eevee_uv_values = bake(uv_node, uv_context)
np.testing.assert_allclose(eevee_uv_values, uv_values, rtol=0, atol=0.002)
assert tuple(uv_node.pg_bake_image.size) == (16, 16)
scene.cycles.device = "CPU"
scene.render.engine = "CYCLES"
bpy.context.view_layer.update()
nodes._bake.reconcile((uv_node,))
assert_shader_uses_image(uv_node, uv_image)
assert nodes._bake.receipt_signature(uv_node) == uv_receipt
assert_bake_controls(uv_node, uv_context)
# Material/node-tree edits can surface as Object geometry updates in Blender.
# They do not alter the UV source geometry or object transform.
nodes._depsgraph_update_post(scene, SimpleNamespace(updates=(
    SimpleNamespace(id=obj, is_updated_geometry=True,
                    is_updated_transform=False, is_updated_shading=True),
    SimpleNamespace(id=obj.data, is_updated_geometry=False,
                    is_updated_transform=False, is_updated_shading=True),
)))
nodes._bake.reconcile((uv_node,))
assert uv_node.pg_use_bake and nodes._bake.toggle_available(uv_node), (
    "Shading-only object update invalidated UV bake",
    nodes._bake.receipt_signature(uv_node),
)
assert_bake_controls(uv_node, uv_context)

# Blender evaluates named mesh data from the snapshot.
attribute_color = (.18, .35, .62, 1.)
attribute = mesh.color_attributes.new(name="Bake Tint", type="FLOAT_COLOR", domain="CORNER")
attribute.data.foreach_set("color", attribute_color * len(mesh.loops))
attribute_node = shader_tree.nodes.new("ShaderNodeAttribute")
attribute_node.attribute_name = attribute.name
attribute_grade = nodes.create_node(shader_tree)
attribute_grade.pg_grade = uv_node.pg_grade
shader_tree.links.new(attribute_node.outputs["Color"], attribute_grade.inputs["Color"])
attribute_grade.pg_bake_width = attribute_grade.pg_bake_height = 16
attribute_context = shader_context(material, scene, obj, attribute_grade)
mesh.update()
bpy.context.view_layer.update()
wait_ready(attribute_grade)
attribute_values = bake(attribute_grade, attribute_context)
np.testing.assert_allclose(
    attribute_values.reshape(-1, 4),
    np.broadcast_to(attribute_color, (16 * 16, 4)), rtol=0, atol=.002,
)
attribute_image = attribute_grade.pg_bake_image
assert attribute_image.get(nodes.bake_controller.BAKE_DOMAIN) == "UV"
attribute_receipt = nodes._bake.receipt_signature(attribute_grade)
attribute_operation = attribute_image.get(nodes.bake_controller.BAKE_OPERATION)
assert_bake_controls(attribute_grade, attribute_context)

nodes._bake.request(attribute_grade, attribute_context)
attribute_key = manager._node_key(attribute_grade)
assert manager.jobs[attribute_key]["state"].phase == "queued"
attribute.data[0].color = (.4, .25, .15, 1.)
mesh.update()
# Deliver a Mesh geometry notification at the same boundary as Blender.
nodes._depsgraph_update_post(scene, SimpleNamespace(updates=(
    SimpleNamespace(id=mesh, is_updated_geometry=True,
                    is_updated_transform=False, is_updated_shading=False),
)))
nodes._bake_tick()
assert attribute_key not in manager.jobs
assert_shader_uses_image(attribute_grade, attribute_image)
assert attribute_image.get(nodes.bake_controller.BAKE_OPERATION) == attribute_operation
assert nodes._bake.receipt_signature(attribute_grade) == attribute_receipt
np.testing.assert_array_equal(attribute_image.pixels[:], attribute_values)
assert_bake_controls(attribute_grade, attribute_context, "status.bake_stale_source")

# Compositor route uses the native compositor capture path.
scene.render.engine = "BLENDER_EEVEE"
scene.render.compositor_device = "GPU"
scene.render.compositor_precision = "AUTO"
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
effects = scene.compositor_effects
source_effect = effects.active
other_effect = add_solid_effect(scene)
comp_context = compositor_context(scene, compositor, comp_grade)
comp_values = bake(comp_grade, comp_context,
                   on_queued=lambda: setattr(effects, "active", source_effect))
effects.active = other_effect
assert nodes._bake.stored_context(comp_grade)["effect_name"] == source_effect.name
assert_bake_controls(comp_grade, comp_context, can_bake=True)
assert effects.active == other_effect
effects.active = source_effect
effects.remove(other_effect)
assert comp_grade.pg_bake_image.get(nodes.bake_controller.BAKE_DOMAIN) == "COMPOSITOR"
assert comp_values.size
comp_grade.pg_use_bake = False
comp_grade.pg_bake_image = shader.pg_bake_image
comp_grade.pg_use_bake = True
assert comp_grade.pg_use_bake, comp_grade.get(nodes.bake_controller.BAKE_ERROR)
comp_grade.pg_use_bake = False

# Render Layers still use the scene engine. This native Compositor Bake
# should preserve that dependency and the render canvas.
comp_grade.pg_bake_image = None
for link in tuple(comp_grade.inputs["Color"].links):
    compositor.links.remove(link)
comp_layers = compositor.nodes.new("CompositorNodeRLayers")
comp_layers.scene = scene
comp_layers.layer = scene.view_layers[0].name
compositor.links.new(comp_layers.outputs["Image"], comp_grade.inputs["Color"])
comp_context = compositor_context(scene, compositor, comp_grade)
comp_layer_values = bake(comp_grade, comp_context)
assert comp_layer_values.size == scene.render.resolution_x * scene.render.resolution_y * 4
assert_bake_controls(comp_grade, comp_context, can_bake=True)
scene.render.engine = "CYCLES"
assert_bake_controls(comp_grade, comp_context, "status.bake_stale_engine", can_bake=True)
scene.render.engine = "BLENDER_EEVEE"
assert_bake_controls(comp_grade, comp_context, can_bake=True)
check_render_layers_indirect_sources(scene, comp_grade, comp_context)

# A compositor constant has no source-image dimensions, so native capture
# should use the scene canvas while preserving its constant pixel value.
constant_tree = bpy.data.node_groups.new("Bake Constant Compositor", nodes.COMPOSITOR_TREE)
constant_tree.interface.new_socket(name="Image", in_out="OUTPUT", socket_type="NodeSocketColor")
constant_output = constant_tree.nodes.new("NodeGroupOutput")
constant_output.is_active_output = True
constant_grade = nodes.create_node(constant_tree)
constant_grade.pg_grade = nodes._make_grade()
constant_grade.inputs["Color"].default_value = (.2, .3, .4, .65)
constant_tree.links.new(constant_grade.outputs["Color"], constant_output.inputs["Image"])
scene.compositing_node_group = constant_tree
constant_context = compositor_context(scene, constant_tree, constant_grade)
wait_ready(constant_grade)
constant_effect = effects.active
other_effect = add_solid_effect(scene)
constant_values = bake(constant_grade, constant_context)
assert tuple(constant_grade.pg_bake_image.size) == (
    scene.render.resolution_x, scene.render.resolution_y,
)
np.testing.assert_allclose(constant_values.reshape(-1, 4),
                           np.broadcast_to((.2, .3, .4, .65),
                                           (constant_values.size // 4, 4)),
                           rtol=0, atol=0.002)
constant_image = constant_grade.pg_bake_image
constant_receipt = nodes._bake.receipt_signature(constant_grade)
constant_operation = constant_image.get(nodes.bake_controller.BAKE_OPERATION)
assert_bake_controls(constant_grade, constant_context, can_bake=True)
assert effects.active == other_effect
effects.active = constant_effect
effects.remove(other_effect)
scene.render.resolution_percentage = 50
assert_bake_controls(
    constant_grade, constant_context, "status.bake_stale_canvas_size", can_bake=True,
)
assert constant_grade.pg_use_bake and constant_grade.pg_bake_image == constant_image
nodes._bake.request(constant_grade, constant_context)
constant_key = manager._node_key(constant_grade)
assert manager.jobs[constant_key]["state"].phase == "queued"
scene.render.resolution_x = 48
nodes._bake_tick()
assert constant_key not in manager.jobs
assert constant_grade.pg_use_bake and constant_grade.pg_bake_image == constant_image
assert constant_image.get(nodes.bake_controller.BAKE_OPERATION) == constant_operation
assert nodes._bake.receipt_signature(constant_grade) == constant_receipt
np.testing.assert_array_equal(np.asarray(constant_image.pixels[:]), constant_values)
scene.render.resolution_x = 32
scene.render.resolution_percentage = 100
assert_bake_controls(constant_grade, constant_context, can_bake=True)
scene.render.resolution_percentage = 50
constant_grade.pg_use_bake = False
constant_image.alpha_mode = "STRAIGHT"
original_pixels = np.asarray(constant_image.pixels[:], dtype=np.float32)
try:
    nodes._bake._activate = fail_after_bake_activation
    nodes._bake.request(constant_grade, constant_context)
    wait_bake(constant_grade)
finally:
    nodes._bake._activate = original_activate
assert activation_failures == ["injected", "injected"]
assert not constant_grade.pg_use_bake and constant_grade.pg_bake_image == constant_image
assert tuple(constant_image.size) == (32, 32) and constant_image.alpha_mode == "STRAIGHT"
assert constant_image.get(nodes.bake_controller.BAKE_OPERATION) == constant_operation
np.testing.assert_array_equal(np.asarray(constant_image.pixels[:]), original_pixels)
constant_math = constant_tree.nodes.new("ShaderNodeMath")
constant_math.operation = "ADD"
constant_math.inputs[0].default_value = .25
constant_math.inputs[1].default_value = .25
constant_tree.links.new(constant_math.outputs[0], constant_grade.inputs["Color"])
math_values = bake(constant_grade, constant_context)
assert constant_grade.pg_bake_image == constant_image
assert tuple(constant_image.size) == (16, 16), constant_grade.get(nodes.bake_controller.BAKE_ERROR)
assert constant_image.packed_file is not None and not constant_image.is_dirty
np.testing.assert_allclose(math_values.reshape(-1, 4)[:, :3], .5, rtol=0, atol=.002)
assert_bake_controls(constant_grade, constant_context, can_bake=True)
scene.render.resolution_percentage = 100
assert_bake_controls(constant_grade, constant_context, "status.bake_stale_canvas_size")

# A signature change before the first poll invalidates the queued request.
scene.render.engine = "CYCLES"
stale = nodes.create_node(shader_tree)
stale_grade = nodes._make_grade(grade_data)
stale.pg_grade = stale_grade
link_source(shader_tree, stale, source, uv=True)
wait_ready(stale)
nodes._bake.request(stale, shader_context(material, scene, obj, stale))
stale_grade.pg_color.adaptance_a_1 = .75
nodes._bake_tick()
assert not stale.pg_use_bake and stale.pg_bake_image is None
assert nodes._bake.manager._node_key(stale) not in nodes._bake.manager.jobs
stale_discarded = True

# Change the foreground engine/device at both queue and execution boundaries.
pending = nodes.create_node(shader_tree)
pending.pg_grade = nodes._make_grade()
pending_source = shader_tree.nodes.new("ShaderNodeTexImage")
pending_source.image = source_image
link_source(shader_tree, pending, pending_source)
pending_context = shader_context(material, scene, node=pending)
wait_ready(pending)
nodes._bake.request(pending, pending_context)
pending_key = manager._node_key(pending)
pending_request = manager.jobs[pending_key]
scene.render.engine = "BLENDER_EEVEE"
scene.cycles.device = "GPU"
bpy.context.view_layer.update()
nodes._bake.reconcile((pending,))
assert manager.jobs[pending_key] is pending_request and pending_request["state"].phase == "queued"
manager._start_next()
assert manager.active is pending_request and pending_request["state"].phase == "running"
scene.render.engine = "CYCLES"
scene.cycles.device = "CPU"
bpy.context.view_layer.update()
nodes._bake.reconcile((pending,))
assert manager.active is pending_request and pending_request["state"].phase == "running"
wait_bake(pending)
assert pending.pg_use_bake and pending.pg_bake_image is not None, pending.get(nodes.bake_controller.BAKE_ERROR)
np.testing.assert_allclose(np.asarray(pending.pg_bake_image.pixels[:]).reshape(4, 4),
                           source_rgba, rtol=0, atol=0.002)
assert_bake_controls(pending, pending_context, can_bake=True)

# Both shader Bake routes capture the native full Stack, including Inverse.
inverse_grade = nodes._make_grade()
inverse_grade.pg_linear.exposure = -1.0
stack_source_image = image("Stack Bake Source", source_rgba, 2, 2)
expected_stack_rgba = source_rgba.copy()
expected_stack_rgba[:, :3] *= 2.0
image_stack = nodes.create_stack_node(shader_tree)
image_stack_context = shader_context(material, scene, node=image_stack)
inverse_entry = image_stack.pg_stack_entries.add()
inverse_entry.direction = "INVERSE"
inverse_entry.grade = inverse_grade
ignored_entry = image_stack.pg_stack_entries.add()
ignored_entry.enabled = False
ignored_entry.grade = inverse_grade
stack_source_node = shader_tree.nodes.new("ShaderNodeTexImage")
stack_source_node.image = stack_source_image
stack_source_node.interpolation = "Closest"
link_source(shader_tree, image_stack, stack_source_node)
bpy.context.view_layer.update()

# Editing an active entry withdraws even a first Bake before the next poll.
# An edit to a disabled row does not change the captured transform.
nodes._bake.request(image_stack, image_stack_context)
stack_key = manager._node_key(image_stack)
queued_stack_request = manager.jobs[stack_key]
assert queued_stack_request["state"].phase == "queued"
ignored_entry.direction = "INVERSE"
image_stack.pg_active_index = 1
assert manager.jobs[stack_key] is queued_stack_request
inverse_entry.direction = "FORWARD"
assert stack_key not in manager.jobs
assert image_stack.pg_bake_image is None and not image_stack.pg_use_bake

inverse_entry.direction = "INVERSE"
nodes._bake.request(image_stack, image_stack_context)
manager._start_next()
running_stack_request = manager.jobs[stack_key]
assert manager.active is running_stack_request
assert running_stack_request["state"].phase == "running"
inverse_entry.enabled = False
assert running_stack_request["state"].phase == "cancelling"
assert manager.active is running_stack_request
wait_bake(image_stack)
assert image_stack.pg_bake_image is None and not image_stack.pg_use_bake
assert nodes._bake.receipt_signature(image_stack) is None
inverse_entry.enabled = True

scene.render.engine = "BLENDER_EEVEE"
scene.cycles.device = "GPU"
bpy.context.view_layer.update()
stack_eevee_values = bake(image_stack, image_stack_context)
stack_image = image_stack.pg_bake_image
stack_receipt = nodes._bake.receipt_signature(image_stack)
assert stack_receipt is not None
assert stack_image.get(nodes.bake_controller.BAKE_DOMAIN) == "IMAGE"
assert tuple(stack_image.size) == (2, 2)
np.testing.assert_allclose(stack_eevee_values.reshape(4, 4), expected_stack_rgba,
                           rtol=0, atol=0.002)
assert_bake_controls(image_stack, image_stack_context)

inverse_entry.direction = "FORWARD"
assert_shader_uses_image(image_stack, stack_image)
assert nodes._bake.receipt_signature(image_stack) == stack_receipt
assert_bake_controls(image_stack, image_stack_context, "status.bake_stale_inputs")
inverse_entry.direction = "INVERSE"
assert_shader_uses_image(image_stack, stack_image)
assert_bake_controls(image_stack, image_stack_context)

for engine in ("CYCLES", "BLENDER_EEVEE"):
    scene.render.engine = engine
    bpy.context.view_layer.update()
    nodes._bake.reconcile((image_stack,))
    assert_shader_uses_image(image_stack, stack_image)
    assert nodes._bake.receipt_signature(image_stack) == stack_receipt
    assert_bake_controls(image_stack, image_stack_context, can_bake=True)

scene.render.engine = "CYCLES"
scene.cycles.device = "CPU"
bpy.context.view_layer.update()
stack_cycles_values = bake(image_stack, image_stack_context)
assert image_stack.pg_bake_image.get(nodes.bake_controller.BAKE_DOMAIN) == "IMAGE"
assert tuple(image_stack.pg_bake_image.size) == (2, 2)
np.testing.assert_allclose(stack_cycles_values.reshape(4, 4), expected_stack_rgba,
                           rtol=0, atol=0.002)
assert_bake_controls(image_stack, image_stack_context)

image_stack.pg_bake_image = None
stack_coordinates = shader_tree.nodes.new("ShaderNodeUVMap")
shader_tree.links.new(stack_coordinates.outputs["UV"], stack_source_node.inputs["Vector"])
image_stack.pg_bake_width = 16
image_stack.pg_bake_height = 8
uv_stack_context = shader_context(material, scene, obj, image_stack)
bpy.context.view_layer.update()
stack_uv_values = bake(image_stack, uv_stack_context)
stack_uv_image = image_stack.pg_bake_image
stack_uv_receipt = nodes._bake.receipt_signature(image_stack)
assert stack_uv_receipt is not None
assert stack_uv_image.get(nodes.bake_controller.BAKE_DOMAIN) == "UV"
assert tuple(stack_uv_image.size) == (16, 8)
expected_uv_rgba = expected_stack_rgba.reshape(2, 2, 4).repeat(4, axis=0).repeat(8, axis=1)
np.testing.assert_allclose(stack_uv_values.reshape(8, 16, 4), expected_uv_rgba,
                           rtol=0, atol=0.002)
assert_bake_controls(image_stack, uv_stack_context, can_bake=True)
scene.render.engine = "BLENDER_EEVEE"
bpy.context.view_layer.update()
nodes._bake.reconcile((image_stack,))
assert_shader_uses_image(image_stack, stack_uv_image)
assert nodes._bake.receipt_signature(image_stack) == stack_uv_receipt
assert_bake_controls(image_stack, uv_stack_context, can_bake=True)
scene.cycles.device = "GPU"
eevee_stack_uv = bake(image_stack, uv_stack_context)
np.testing.assert_allclose(eevee_stack_uv.reshape(8, 16, 4), expected_uv_rgba,
                           rtol=0, atol=0.002)
scene.cycles.device = "CPU"
scene.render.engine = "CYCLES"
bpy.context.view_layer.update()
nodes._bake.reconcile((image_stack,))
assert_shader_uses_image(image_stack, stack_uv_image)
assert nodes._bake.receipt_signature(image_stack) == stack_uv_receipt
assert_bake_controls(image_stack, uv_stack_context, can_bake=True)

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
stack.pg_stack_entries[0].grade.pg_color.web_scale_1_0 = .125
stack_tree.links.new(stack.outputs["Color"], stack_output.inputs["Image"])
try:
    wait_ready(stack, stack=True)
    stack_values = bake(stack, stack_context)
    assert tuple(stack.pg_bake_image.size) == (scene.render.resolution_x, scene.render.resolution_y)
    stack_ok = bool(stack_values.size and stack.pg_bake_image is not None)
except (AssertionError, RuntimeError, TimeoutError, ValueError) as error:
    raise AssertionError("Stack Bake acceptance failed: " + str(error)) from error

report = {
    "passed": True,
    "domains": ["IMAGE", "UV", "COMPOSITOR"],
    "stack": stack_ok,
    "stack_shader_bakes": ["IMAGE_EEVEE", "IMAGE_CYCLES", "UV_EEVEE", "UV_CYCLES"],
    "stack_entry_bake_invalidation": True,
    "packed_float": all(item.pg_bake_image is not None and item.pg_bake_image.is_float
                         and item.pg_bake_image.packed_file is not None
                         for item in (shader, shared, uv_node, comp_grade)),
    "live_restored": live_restored,
    "shared_rebake": shared_rebake,
    "stale_discarded": stale_discarded,
    "pending_engine_switch": True,
    "wrapper_independent": True,
    "wrapper_recovery": True,
    "baked_conversion": True,
    "grade_edit_stale_warning": True,
    "identity_match": identity_match,
    "cycles_cpu_shader_bakes": True,
    "compositor_render_layers": True,
    "compositor_constant": True,
    "engine_roundtrip": True,
    "render_admission": True,
    "source_edit_invalidation": True,
    "source_edit_stale_warning": True,
}

# Deliver fixture construction/engine updates as the interactive event loop
# would before clicking Bake. Then freeze the final scene for persistence.
bpy.context.view_layer.update()
uv_values = bake(uv_node, shader_context(material, scene, obj, uv_node))

# Preserve the latest active bake across a real save/load; resolve every RNA
# pointer again after open_mainfile, including the nested live kernel.
stack_tree_name, stack_name = stack_tree.name, stack.name
material_name, uv_name, source_image_name = material.name, uv_node.name, source_image.name
mesh_object_name = obj.name
packed_values = np.asarray(stack.pg_bake_image.pixels[:], dtype=np.float32)
other_effect_name = add_solid_effect(scene).name
assert uv_node.pg_use_bake and nodes._bake.toggle_available(uv_node)
with tempfile.TemporaryDirectory(prefix="pg-next-bake-save-") as directory:
    blend_path = str(Path(directory) / "bake.blend")
    assert "FINISHED" in bpy.ops.wm.save_as_mainfile(filepath=blend_path)
    assert uv_node.pg_use_bake and nodes._bake.toggle_available(uv_node)
    assert "FINISHED" in bpy.ops.wm.open_mainfile(filepath=blend_path)
    restored_uv = bpy.data.materials.get(material_name).node_tree.nodes.get(uv_name)
    assert restored_uv.pg_use_bake and nodes._bake.toggle_available(restored_uv)
    restored_tree = bpy.data.node_groups.get(stack_tree_name)
    assert restored_tree is not None
    restored_stack = restored_tree.nodes.get(stack_name)
    assert restored_stack is not None
    reopened_scene = bpy.context.scene
    assert reopened_scene.compositor_effects.active.name == other_effect_name
    stack_context = compositor_context(reopened_scene, restored_tree, restored_stack)
    assert_bake_controls(restored_stack, stack_context, can_bake=True)
    stored = nodes._bake.stored_context(restored_stack)
    duplicate = reopened_scene.compositor_effects.new("Second use of the baked Stack")
    duplicate.node_group = restored_tree
    legacy = {k: v for k, v in stored.items() if k not in {"root_key", "effect_name"}}
    restored_stack[nodes.bake_controller.BAKE_CONTEXT] = json.dumps(legacy)
    assert_bake_controls(restored_stack, stack_context, "status.bake_stale_route")
    assert restored_stack.pg_use_bake
    reopened_scene.compositor_effects.remove(duplicate)
    assert_bake_controls(restored_stack, stack_context)
    restored_stack[nodes.bake_controller.BAKE_CONTEXT] = json.dumps(stored)
    reopened_scene.compositor_effects.active = reopened_scene.compositor_effects[stored["effect_name"]]
    reopened_scene.compositor_effects.remove(reopened_scene.compositor_effects[other_effect_name])
    wait_ready(restored_stack, stack=True)
    nodes._bake_tick()
    assert restored_stack.pg_use_bake, restored_stack.get(nodes.bake_controller.BAKE_ERROR)
    assert nodes._bake.toggle_available(restored_stack)
    restored_image = restored_stack.pg_bake_image
    assert restored_image is not None and restored_image.is_float
    assert restored_image.packed_file is not None and not restored_image.is_dirty
    np.testing.assert_array_equal(np.asarray(restored_image.pixels[:], dtype=np.float32),
                                  packed_values)

    restored_material = bpy.data.materials.get(material_name)
    restored_uv = restored_material.node_tree.nodes.get(uv_name)
    restored_source = bpy.data.images.get(source_image_name)
    assert restored_uv is not None and restored_source is not None
    assert restored_uv.pg_use_bake and nodes._bake.toggle_available(restored_uv), (
        nodes._bake.receipt_signature(restored_uv),
        nodes._bake.observed_signature(restored_uv, nodes._bake.stored_context(restored_uv)),
    )
    assert_bake_controls(restored_uv, nodes._bake.stored_context(restored_uv))

    # Undo must recover the previously valid selector and receipt together.
    bpy.context.preferences.edit.use_global_undo = True
    assert bpy.ops.ed.undo_push(message="Valid baked stack baseline") == {"FINISHED"}
    restored_stack.pg_use_bake = False
    assert bpy.ops.ed.undo_push(message="Disable baked stack") == {"FINISHED"}
    del restored_stack, restored_uv, restored_source
    assert bpy.ops.ed.undo.poll()
    assert bpy.ops.ed.undo() == {"FINISHED"}
    if bpy.app.timers.is_registered(nodes._undo_redo_reconcile_tick):
        nodes._undo_redo_reconcile_tick()
    restored_tree = bpy.data.node_groups.get(stack_tree_name)
    restored_stack = restored_tree.nodes.get(stack_name)
    wait_ready(restored_stack, stack=True)
    nodes._bake_tick()
    assert restored_stack.pg_use_bake and nodes._bake.toggle_available(restored_stack)
    restored_material = bpy.data.materials.get(material_name)
    restored_uv = restored_material.node_tree.nodes.get(uv_name)
    restored_source = bpy.data.images.get(source_image_name)
    assert restored_uv.pg_use_bake and nodes._bake.toggle_available(restored_uv)

    # Source edits while Use Bake is off mark the receipt stale across file load.
    restored_uv.pg_use_bake = False
    assert not restored_uv.pg_use_bake
    original_receipt = nodes._bake.receipt_signature(restored_uv)
    before_source_edit = np.asarray(restored_source.pixels[:], dtype=np.float32)
    restored_source.pixels.foreach_set(before_source_edit + 0.01)
    nodes.invalidate_source(restored_source)
    assert not restored_uv.pg_use_bake
    assert_bake_controls(
        restored_uv, nodes._bake.stored_context(restored_uv), "status.bake_stale_source",
    )
    restored_uv.pg_use_bake = True
    assert restored_uv.pg_use_bake
    assert nodes._bake.receipt_signature(restored_uv) == original_receipt

    # Legacy verification is image metadata, independent of per-node freshness.
    del restored_uv.pg_bake_image[nodes.bake_controller.BAKE_SOURCE_VERIFICATION]
    assert_bake_controls(restored_uv, nodes._bake.stored_context(restored_uv),
                         "status.bake_stale_source", legacy=True)
    assert "FINISHED" in bpy.ops.wm.save_as_mainfile(filepath=blend_path)
    assert "FINISHED" in bpy.ops.wm.open_mainfile(filepath=blend_path)
    restored_scene = bpy.context.scene
    restored_material = bpy.data.materials.get(material_name)
    restored_uv = restored_material.node_tree.nodes.get(uv_name)
    restored_mesh_object = bpy.data.objects[mesh_object_name]
    restored_uv_context = shader_context(restored_material, restored_scene, restored_mesh_object,
                                         restored_uv)
    assert restored_uv.pg_use_bake
    assert nodes._bake.receipt_signature(restored_uv) == original_receipt
    assert_bake_controls(restored_uv, restored_uv_context, "status.bake_stale_source", legacy=True)

    legacy_image = restored_uv.pg_bake_image
    legacy_pixels = np.asarray(legacy_image.pixels[:], dtype=np.float32)
    legacy_operation = legacy_image.get(nodes.bake_controller.BAKE_OPERATION)
    restored_tree = restored_material.node_tree
    legacy_reader = nodes.create_node(restored_tree)
    legacy_reader.pg_grade = restored_uv.pg_grade
    texture = restored_uv.inputs["Color"].links[0].from_node
    link_source(restored_tree, legacy_reader, texture)
    legacy_reader_context = shader_context(restored_material, restored_scene, restored_mesh_object,
                                           legacy_reader)
    wait_ready(legacy_reader)
    bpy.context.view_layer.objects.active = restored_mesh_object
    bpy.context.view_layer.update()
    legacy_reader.pg_bake_image = legacy_image
    legacy_reader.pg_use_bake = True
    assert_shader_uses_image(legacy_reader, legacy_image)
    assert_bake_controls(legacy_reader, legacy_reader_context, legacy=True)

    # Reject a missing exact image before native bake and preserve the selected
    # artifact, receipt, and verification state.
    manager = nodes._bake.manager
    original_snapshot = manager.freeze_snapshot

    def snapshot_with_missing_source(route):
        root, snapshot, images = original_snapshot(route)
        images[0]["image_key"] = ("Missing Bake Image", None)
        return root, snapshot, images

    try:
        manager.freeze_snapshot = snapshot_with_missing_source
        nodes._bake.request(restored_uv, restored_uv_context)
        wait_bake(restored_uv)
        assert restored_uv.get(nodes.bake_controller.BAKE_ERROR)
    finally:
        manager.freeze_snapshot = original_snapshot
    assert_shader_uses_image(restored_uv, legacy_image)
    assert_shader_uses_image(legacy_reader, legacy_image)
    np.testing.assert_array_equal(legacy_image.pixels[:], legacy_pixels)
    assert legacy_image.get(nodes.bake_controller.BAKE_OPERATION) == legacy_operation
    assert legacy_image.get(nodes.bake_controller.BAKE_SOURCE_VERIFICATION) is None
    assert nodes._bake.receipt_signature(restored_uv) == original_receipt
    assert_bake_controls(restored_uv, restored_uv_context, "status.bake_stale_source", legacy=True)
    assert_bake_controls(legacy_reader, legacy_reader_context, legacy=True)

    bake(restored_uv, restored_uv_context)
    assert_shader_uses_image(restored_uv, legacy_image)
    assert_shader_uses_image(legacy_reader, legacy_image)
    assert legacy_image.get(nodes.bake_controller.BAKE_OPERATION) != legacy_operation
    assert_bake_controls(restored_uv, restored_uv_context)
    assert_bake_controls(legacy_reader, legacy_reader_context, "status.bake_stale_source")

    bake_linked_images(restored_scene, restored_mesh_object, restored_material, Path(directory))
    check_bake_upstream_grade_identity(restored_scene, Path(directory))
report["persistence"] = True
report["undo_valid_bake"] = True
report["source_edit_while_off"] = True
report["legacy_bake_source_verification"] = True
report["linked_bake_image_identity"] = True

# Exercise the add-on teardown after all native helper work has retired.
extension.unregister()
deadline = time.monotonic() + 30
while nodes._bake.manager is not None and time.monotonic() < deadline:
    # Background scripts do not yield Blender's timer loop. Honor the return
    # value just as the host does when invoking this timer callback.
    if nodes._bake_tick() is None and bpy.app.timers.is_registered(nodes._bake_tick):
        bpy.app.timers.unregister(nodes._bake_tick)
    time.sleep(.01)
assert nodes._bake.manager is None
assert not bpy.app.timers.is_registered(nodes._bake_tick)
report["teardown"] = True
report_path.write_text(json.dumps(report))

