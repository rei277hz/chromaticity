"""Native, isolated Blender evaluation for Grade and Grade Stack bakes.

The foreground bake coordinator owns request correlation and publication.  This
module only consumes an immutable scene snapshot and evaluates the selected
node's installed Blender tree.  In particular, it deliberately does not call
the numerical Grade implementation or sample a Stack cube in Python: Grade
helper images and the 65^3 Stack LUT are evaluated by Blender's node graph.
"""

# pg-book: technical-report/en#next-policy.bake

from pathlib import Path
import hashlib
import tempfile

import numpy as np


MAX_PIXEL_BYTES = 512 * 1024 * 1024
_GRADE_NODES = frozenset({
    "PGShaderGrade", "PGCompositorGrade",
    "PGShaderGradeStack", "PGCompositorGradeStack",
})


def _minimal_node_types():
    """Register only persisted node ABI classes needed while opening a snapshot."""
    import bpy

    for base, identifier in (
        ("NodeTree", "PGGradeData"),
        ("ShaderNodeCustomGroup", "PGShaderGrade"),
        ("CompositorNodeCustomGroup", "PGCompositorGrade"),
        ("ShaderNodeCustomGroup", "PGShaderGradeStack"),
        ("CompositorNodeCustomGroup", "PGCompositorGradeStack"),
        ("ShaderNodeCustomGroup", "PGShaderGradePerNode"),
        ("CompositorNodeCustomGroup", "PGCompositorGradePerNode"),
    ):
        registry = bpy.types.NodeTree if base == "NodeTree" else bpy.types.Node
        if registry.bl_rna_get_subclass_py(identifier, None) is not None:
            continue
        cls = type(identifier, (getattr(bpy.types, base),), {
            "__module__": __name__, "bl_idname": identifier,
            "bl_label": identifier, "bl_icon": "COLOR",
        })
        bpy.utils.register_class(cls)


def _open_snapshot(inputs):
    """Open and verify the immutable per-request Blender snapshot."""
    import bpy

    value = inputs.get("snapshot_path", inputs.get("snapshot"))
    if not isinstance(value, str):
        return
    path = Path(value)
    if not path.is_absolute() or path.is_symlink() or not path.is_file():
        raise ValueError("Invalid bake snapshot path")
    expected = inputs.get("snapshot_sha256")
    if expected:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != expected:
            raise ValueError("Bake snapshot changed after capture")
    _minimal_node_types()
    result = bpy.ops.wm.open_mainfile(filepath=str(path), use_scripts=False, load_ui=False)
    if "FINISHED" not in result:
        raise RuntimeError("Bake snapshot could not be opened")
    _restore_images(inputs.get("images", ()))


def _restore_images(records):
    import bpy

    for record in tuple(records or ()):
        if not isinstance(record, dict):
            raise TypeError("Bake image records must be mappings")
        name = str(record.get("name", ""))
        path_value = record.get("pixels_path") or record.get("path")
        if not name or not isinstance(path_value, str):
            raise ValueError("Bake image record is incomplete")
        path = Path(path_value)
        if not path.is_absolute() or path.is_symlink() or not path.is_file():
            raise ValueError("Invalid bake image payload")
        expected = record.get("sha256")
        if expected and hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError("Bake image payload changed after capture")
        values = np.load(path, allow_pickle=False)
        if values.dtype.kind != "f" or values.ndim != 3 or values.shape[-1] not in (1, 2, 3, 4):
            raise ValueError("Bake image payload is not a float image")
        height, width, channels = values.shape
        if min(width, height) < 1 or width * height * 16 > MAX_PIXEL_BYTES:
            raise ValueError("Bake source image exceeds the pixel budget")
        image = bpy.data.images.get(name)
        if image is None:
            image = bpy.data.images.new(name, width=width, height=height,
                                        alpha=True, float_buffer=True)
        if tuple(image.size) != (width, height):
            raise ValueError("Bake source dimensions changed after the scene snapshot")
        if channels == 1:
            values = np.concatenate((np.repeat(values, 3, axis=-1),
                                     np.ones((height, width, 1), np.float32)), axis=-1)
        elif channels == 2:
            values = np.concatenate((np.repeat(values[..., :1], 3, axis=-1),
                                     values[..., 1:2]), axis=-1)
        elif channels == 3:
            values = np.concatenate((values, np.ones((height, width, 1), np.float32)), axis=-1)
        image.pixels.foreach_set(np.asarray(values, dtype=np.float32).ravel())
        image.update()
        try:
            image.colorspace_settings.name = str(record.get("colorspace", "Non-Color"))
            image.alpha_mode = str(record.get("alpha_mode", "CHANNEL_PACKED"))
        except (AttributeError, RuntimeError, ValueError):
            pass


def _checkpoint(context):
    context.checkpoint()


def _socket(sockets, name):
    result = next((item for item in sockets if item.identifier == name), None)
    if result is None:
        result = sockets.get(name)
    if result is None:
        raise ValueError("Bake socket is absent: " + str(name))
    return result


def _links(socket):
    return tuple(link for link in socket.links
                 if getattr(link, "is_valid", True) and not getattr(link, "is_muted", False))


def _read_image(image):
    width, height = (int(value) for value in image.size)
    channels = int(getattr(image, "channels", 4))
    if min(width, height) < 1 or width * height * 16 > MAX_PIXEL_BYTES:
        raise ValueError("Bake image exceeds the pixel budget")
    values = np.empty(width * height * channels, dtype=np.float32)
    image.pixels.foreach_get(values)
    values = values.reshape(height, width, channels)
    if channels == 1:
        values = np.concatenate((np.repeat(values, 3, axis=-1),
                                 np.ones((height, width, 1), np.float32)), axis=-1)
    elif channels == 2:
        values = np.concatenate((np.repeat(values[..., :1], 3, axis=-1),
                                 values[..., 1:2]), axis=-1)
    elif channels == 3:
        values = np.concatenate((values, np.ones((height, width, 1), np.float32)), axis=-1)
    if values.shape[-1] != 4:
        raise ValueError("Bake image is not RGBA")
    return np.ascontiguousarray(values)


def _new_image(name, width, height):
    import bpy

    image = bpy.data.images.new(name, width=width, height=height,
                                alpha=True, float_buffer=True)
    image.colorspace_settings.name = "Non-Color"
    image.alpha_mode = "CHANNEL_PACKED"
    if hasattr(image, "use_half_precision"):
        image.use_half_precision = False
    return image


def _copy_path(root, path):
    """Copy group instances on an occurrence path in a private root tree."""
    tree = root
    for name in tuple(path):
        group = tree.nodes.get(str(name))
        if group is None or group.node_tree is None:
            raise ValueError("Bake group occurrence is absent: " + str(name))
        group.node_tree = group.node_tree.copy()
        tree = group.node_tree
    return tree


def _live_target(target):
    """Tap only the initiating node's live branch, leaving upstream modes alone."""
    tree = target.node_tree
    if tree is None:
        raise ValueError("Bake target has no generated node tree")
    if tree.get("_pg_next_bake_wrapper"):
        target.node_tree = tree.copy()
        tree = target.node_tree
        readers = tuple(node for node in tree.nodes if node.get("_pg_next_bake_live"))
        outputs = tuple(node for node in tree.nodes
                        if node.bl_idname == "NodeGroupOutput" and node.is_active_output)
        if len(readers) != 1 or len(outputs) != 1:
            raise ValueError("Bake target wrapper has no unique live branch")
        reader, output = readers[0], outputs[0]
        kernel = reader.node_tree
        for name in ("Color", "Alpha"):
            source = reader.outputs.get(name)
            destination = output.inputs.get(name)
            if source is not None and destination is not None:
                for link in tuple(destination.links):
                    tree.links.remove(link)
                tree.links.new(source, destination)
    else:
        kernel = tree
    if kernel is None or kernel.get("_perceptual_grade_quality") != "full":
        raise ValueError("Bake requires the current full-quality Grade kernel")
    if target.bl_idname.endswith("GradeStack"):
        if not kernel.get("_perceptual_grade_stack_kernel"):
            raise ValueError("Stack Bake requires its full 65^3 LUT node tree")


def _prepare_shader_sources(root, descriptor):
    """Preserve source alpha interpretation across independent emission passes."""
    for occurrence in descriptor.get("images", ()):
        path = tuple(occurrence.get("group_path", ()))
        tree = _copy_path(root, path)
        source = tree.nodes.get(str(occurrence["node_name"]))
        if source is None:
            raise ValueError("Bake source image occurrence is absent")
        if occurrence.get("baked"):
            # A managed upstream wrapper owns its sampler and coordinates.
            # Its native effective graph is already frozen in the snapshot.
            continue
        if source.bl_idname != "ShaderNodeTexImage" or source.image is None:
            raise ValueError("Bake source occurrence is not an Image Texture")
        image = source.image
        if (image.source not in {"FILE", "GENERATED"}
                or image.type not in {"IMAGE", "UV_TEST"} or image.use_multiview):
            raise ValueError("Bake supports only ordinary still Image Textures")
        if descriptor["domain"] == "IMAGE":
            # Evaluate one pixel per source texel, independent of filtering.
            # Explicit vector inputs were already rejected by route discovery.
            if _links(source.inputs["Vector"]):
                raise ValueError("Image Bake source acquired linked coordinates")
            source.projection = "FLAT"
            source.interpolation = "Closest"
            source.extension = "EXTEND"
            mapping = source.texture_mapping
            mapping.translation = (0.0, 0.0, 0.0)
            mapping.rotation = (0.0, 0.0, 0.0)
            mapping.scale = (1.0, 1.0, 1.0)
            mapping.use_min = False
            mapping.use_max = False
            mapping.vector_type = "POINT"
            mapping.mapping_x = "X"
            mapping.mapping_y = "Y"
            mapping.mapping_z = "Z"
            mapping.mapping = "FLAT"
        if not occurrence.get("alpha_linked"):
            continue
        color_links = tuple(source.outputs["Color"].links)
        if not color_links:
            continue
        # Cycles' native Image Texture conversion depends on whether Alpha is
        # live. Keep that dependency during the independent RGB bake pass.
        absolute = tree.nodes.new("ShaderNodeMath")
        absolute.operation = "ABSOLUTE"
        tree.links.new(source.outputs["Alpha"], absolute.inputs[0])
        positive = tree.nodes.new("ShaderNodeMath")
        positive.operation = "GREATER_THAN"
        positive.inputs[1].default_value = -1.0
        tree.links.new(absolute.outputs[0], positive.inputs[0])
        scale = tree.nodes.new("ShaderNodeVectorMath")
        scale.operation = "SCALE"
        tree.links.new(source.outputs["Color"], scale.inputs[0])
        tree.links.new(positive.outputs[0], scale.inputs["Scale"])
        for link in color_links:
            destination = link.to_socket
            tree.links.remove(link)
            tree.links.new(scale.outputs["Vector"], destination)


def _target_outputs(root, path, node_name):
    """Expose nested Color and Alpha outputs at the private root tree.

    Group interfaces are changed only in the helper's private file.  This
    keeps a reused group occurrence isolated while preserving all authored
    links and the generated Grade/Stack kernel itself.
    """
    tree = root
    groups = []
    for name in tuple(path):
        group = tree.nodes.get(str(name))
        if group is None or group.node_tree is None:
            raise ValueError("Bake group occurrence is absent: " + str(name))
        group.node_tree = group.node_tree.copy()
        groups.append((tree, group))
        tree = group.node_tree
    target = tree.nodes.get(str(node_name))
    if target is None or target.bl_idname not in _GRADE_NODES:
        raise ValueError("Bake target is not a Grade or Grade Stack node")
    _live_target(target)
    outputs = []
    for output_name in ("Color", "Alpha"):
        try:
            outputs.append(_socket(target.outputs, output_name))
        except ValueError:
            outputs.append(None)
    for parent, group in reversed(groups):
        endpoint = next((item for item in tree.nodes
                         if item.bl_idname == "NodeGroupOutput" and item.is_active_output), None)
        if endpoint is None:
            endpoint = tree.nodes.new("NodeGroupOutput")
            endpoint.is_active_output = True
        outer_outputs = []
        for name, socket, socket_type in zip(
                ("PG Next Bake Color", "PG Next Bake Alpha"), outputs,
                ("NodeSocketColor", "NodeSocketFloat")):
            field = tree.interface.new_socket(name=name, in_out="OUTPUT",
                                               socket_type=socket_type)
            if socket is not None:
                tree.links.new(socket, _socket(endpoint.inputs, field.identifier))
                outer_outputs.append(_socket(group.outputs, field.identifier))
            else:
                outer_outputs.append(None)
        outputs = outer_outputs
        tree = parent
    return outputs[0], outputs[1], tree


def _configure_linear(scene):
    """Configure a helper render for untransformed float pixels."""
    settings = scene.render.image_settings
    settings.file_format = "OPEN_EXR"
    settings.color_mode = "RGBA"
    settings.color_depth = "32"
    settings.exr_codec = "ZIPS"
    if hasattr(settings, "color_management"):
        settings.color_management = "OVERRIDE"
    try:
        settings.linear_colorspace_settings.name = "scene_linear"
    except (AttributeError, RuntimeError, ValueError):
        pass
    try:
        scene.view_settings.view_transform = "Standard"
        scene.view_settings.look = "None"
        scene.view_settings.exposure = 0.0
        scene.view_settings.gamma = 1.0
    except (AttributeError, RuntimeError, ValueError):
        pass


def _plane(scene):
    import bpy

    mesh = bpy.data.meshes.new("PG Next Bake Plane")
    mesh.from_pydata(((-1., -1., 0.), (1., -1., 0.),
                     (1., 1., 0.), (-1., 1., 0.)), (), ((0, 1, 2, 3),))
    uv = mesh.uv_layers.new(name="PG Next Bake UV")
    for item, value in zip(uv.data, ((0., 0.), (1., 0.), (1., 1.), (0., 1.))):
        item.uv = value
    mesh.uv_layers.active = uv
    uv.active_render = True
    obj = bpy.data.objects.new("PG Next Bake Plane", mesh)
    scene.collection.objects.link(obj)
    return obj, uv.name


def _material(root, color, alpha):
    import bpy

    material = bpy.data.materials.new("PG Next Bake Material")
    material.use_nodes = True
    tree = material.node_tree
    tree.nodes.clear()
    color_field = root.interface.new_socket(name="PG Next Bake Color", in_out="OUTPUT",
                                            socket_type="NodeSocketColor")
    endpoint = next((item for item in root.nodes
                     if item.bl_idname == "NodeGroupOutput" and item.is_active_output), None)
    if endpoint is None:
        endpoint = root.nodes.new("NodeGroupOutput")
        endpoint.is_active_output = True
    root.links.new(color, _socket(endpoint.inputs, color_field.identifier))
    alpha_field = None
    if alpha is not None:
        alpha_field = root.interface.new_socket(name="PG Next Bake Alpha", in_out="OUTPUT",
                                                socket_type="NodeSocketFloat")
        root.links.new(alpha, _socket(endpoint.inputs, alpha_field.identifier))
    group = tree.nodes.new("ShaderNodeGroup")
    group.node_tree = root
    emission = tree.nodes.new("ShaderNodeEmission")
    output = tree.nodes.new("ShaderNodeOutputMaterial")
    output.is_active_output = True
    tree.links.new(_socket(group.outputs, color_field.identifier), emission.inputs["Color"])
    tree.links.new(emission.outputs[0], output.inputs["Surface"])
    sink = tree.nodes.new("ShaderNodeTexImage")
    sink.image = None
    tree.nodes.active = sink
    return material, tree, group, emission, sink, alpha_field.identifier if alpha_field else None


def _set_alpha_output(tree, group, emission, alpha_name):
    # A scalar Alpha output is expanded to RGB for a second emission bake.
    for link in tuple(emission.inputs["Color"].links):
        tree.links.remove(link)
    tree.links.new(_socket(group.outputs, alpha_name), emission.inputs["Color"])


def _select(scene, obj, uv_name):
    import bpy

    if bpy.context.window is not None:
        bpy.context.window.scene = scene
    layer = bpy.context.view_layer
    if obj.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    layer.material_override = None
    for item in layer.objects:
        item.select_set(False)
    obj.hide_render = False
    obj.hide_viewport = False
    obj.hide_set(False)
    obj.select_set(True)
    layer.objects.active = obj
    uv = obj.data.uv_layers.get(uv_name)
    if uv is None:
        raise ValueError("Bake UV map is absent: " + str(uv_name))
    obj.data.uv_layers.active = uv
    uv.active_render = True
    layer.update()


def _bake_pass(scene, obj, material, tree, sink, emission, image, context, margin=0):
    import bpy

    sink.image = image
    tree.nodes.active = sink
    scene.render.bake.margin = int(margin)
    scene.render.bake.margin_type = "EXTEND"
    scene.render.bake.use_clear = True
    scene.render.bake.use_selected_to_active = False
    scene.render.bake.target = "IMAGE_TEXTURES"
    _checkpoint(context)
    result = bpy.ops.object.bake(type="EMIT", margin=int(margin),
                                 use_clear=True, use_selected_to_active=False)
    _checkpoint(context)
    if "FINISHED" not in result:
        raise RuntimeError("Native Shader Bake did not finish")
    return _read_image(image)


def _shader(inputs, context):
    import bpy

    descriptor = dict(inputs.get("shader_bake") or inputs.get("descriptor") or {})
    target = dict(inputs.get("target") or {})
    scene = bpy.data.scenes.get(str(target.get("scene", descriptor.get("scene", ""))))
    if scene is None:
        raise ValueError("Bake scene is absent")
    _set_frame(scene, descriptor)
    owner_kind = str(target.get("owner_kind", descriptor.get("owner_kind", "material"))).lower()
    owner_name = str(target.get("owner_name", descriptor.get("owner_name", "")))
    owner = ((bpy.data.materials if owner_kind == "material" else bpy.data.worlds).get(owner_name))
    if owner is None or owner.node_tree is None:
        raise ValueError("Bake shader owner is absent")
    width, height = int(descriptor["width"]), int(descriptor["height"])
    if min(width, height) < 1 or width * height * 16 > MAX_PIXEL_BYTES:
        raise ValueError("Shader Bake dimensions exceed the pixel budget")
    root = owner.node_tree.copy()
    _prepare_shader_sources(root, descriptor)
    path = tuple(target.get("group_path", descriptor.get("group_path", ())))
    color, alpha, root = _target_outputs(
        root, path, str(target.get("node_name", descriptor.get("node_name", ""))))
    if color is None:
        raise ValueError("Bake target has no Color output")
    material, tree, group, emission, sink, alpha_name = _material(root, color, alpha)
    obj = None
    if str(descriptor.get("domain", "IMAGE")) == "UV":
        from .bake_routes import _uv

        if owner_kind != "material" or scene.render.engine != "CYCLES":
            raise ValueError("UV Bake requires a Cycles material")
        obj = bpy.data.objects.get(str(descriptor.get("object_name", "")))
        if obj is None or obj.type != "MESH" or obj.name not in scene.objects:
            raise ValueError("UV Shader Bake requires the frozen active mesh")
        if any(modifier.type in {"MESH_SEQUENCE_CACHE", "MESH_CACHE"}
               or getattr(modifier, "cache_file", None) is not None for modifier in obj.modifiers):
            raise ValueError("UV Bake does not support Alembic or cache geometry")
        # Recheck the exact saved surface before invoking native render-mode
        # baking. In particular, do not let an enabled render-only modifier
        # introduce overlap after the foreground checked the base mesh.
        if _uv(obj, full=True) != descriptor.get("uv_map"):
            raise ValueError("UV Bake active render map changed in the snapshot")
        index = int(descriptor.get("material_slot", -1))
        if index < 0 or index >= len(obj.material_slots):
            raise ValueError("UV Shader Bake material slot is absent")
        scratch = _new_image("PG Next Bake Other Materials", width, height)
        for slot_index, slot in enumerate(obj.material_slots):
            slot.link = "OBJECT"
            if slot_index == index:
                slot.material = material
            else:
                other = bpy.data.materials.new("PG Next Bake Excluded Material")
                other.use_nodes = True
                scratch_node = other.node_tree.nodes.new("ShaderNodeTexImage")
                scratch_node.image = scratch
                other.node_tree.nodes.active = scratch_node
                slot.material = other
        uv_name = str(descriptor.get("uv_map", ""))
        margin = int(descriptor.get("margin", 16))
    else:
        obj, uv_name = _plane(scene)
        obj.data.materials.append(material)
        margin = 0
    scene.render.engine = "CYCLES"
    scene.cycles.samples = 1
    scene.cycles.use_denoising = False
    scene.cycles.device = "CPU"
    scene.render.resolution_x = width
    scene.render.resolution_y = height
    scene.render.resolution_percentage = 100
    scene.render.use_sequencer = False
    scene.compositing_node_group = None
    _configure_linear(scene)
    _select(scene, obj, uv_name)
    image = _new_image("PG Next Bake Result", width, height)
    rgb = _bake_pass(scene, obj, material, tree, sink, emission, image, context, margin)
    if alpha_name is not None:
        _set_alpha_output(tree, group, emission, alpha_name)
        alpha_pixels = _bake_pass(scene, obj, material, tree, sink, emission, image, context, margin)
        rgb[..., 3] = alpha_pixels[..., 0]
    else:
        rgb[..., 3] = 1.0
    if descriptor.get("domain") == "UV":
        # Bake a coverage mask separately; black graded pixels are valid texels.
        value = tree.nodes.new("ShaderNodeValue")
        value.outputs[0].default_value = 1.0
        for link in tuple(emission.inputs["Color"].links):
            tree.links.remove(link)
        tree.links.new(value.outputs[0], emission.inputs["Color"])
        coverage_image = _new_image("PG Next Bake Coverage", width, height)
        coverage = _bake_pass(scene, obj, material, tree, sink, emission,
                              coverage_image, context, margin)
        rgb[np.max(coverage[..., :3], axis=-1) <= 0.0] = 0.0
    _checkpoint(context)
    return _result(rgb, inputs, target, descriptor, backend="CYCLES")


def _compositor(inputs, context):
    import bpy

    target = dict(inputs.get("target") or {})
    scene = bpy.data.scenes.get(str(target.get("scene", "")))
    if scene is None:
        raise ValueError("Compositor Bake scene is absent")
    _set_frame(scene, target)
    tree = getattr(scene, "compositing_node_group", None)
    if tree is None:
        tree = getattr(scene, "node_tree", None)
    if tree is None:
        raise ValueError("Scene has no compositor graph")
    tree = tree.copy()
    path = tuple(target.get("group_path", ()))
    output, _alpha, tree = _target_outputs(tree, path, str(target.get("node_name", "")))
    with tempfile.TemporaryDirectory(prefix="pg-next-compositor-bake-") as directory:
        for node in tuple(tree.nodes):
            if node.bl_idname in {"CompositorNodeOutputFile", "CompositorNodeViewer", "NodeGroupOutput"}:
                tree.nodes.remove(node)
        field = next((item for item in tree.interface.items_tree
                      if item.item_type == "SOCKET" and item.in_out == "OUTPUT"
                      and item.socket_type == "NodeSocketColor"), None)
        if field is None:
            field = tree.interface.new_socket(name="Image", in_out="OUTPUT",
                                               socket_type="NodeSocketColor")
        root_output = tree.nodes.new("NodeGroupOutput")
        root_output.is_active_output = True
        tree.links.new(output, _socket(root_output.inputs, field.identifier))
        endpoint = tree.nodes.new("CompositorNodeOutputFile")
        endpoint.name = "PG Next Bake Output"
        endpoint.directory = directory
        endpoint.file_name = "bake_"
        item = endpoint.file_output_items.new("RGBA", "bake")
        endpoint.format.media_type = "IMAGE"
        endpoint.format.file_format = "OPEN_EXR"
        endpoint.format.color_mode = "RGBA"
        endpoint.format.color_depth = "32"
        endpoint.format.exr_codec = "ZIPS"
        endpoint.save_as_render = False
        try:
            endpoint.format.color_management = "OVERRIDE"
            endpoint.format.linear_colorspace_settings.name = "scene_linear"
        except (AttributeError, RuntimeError, ValueError):
            pass
        tree.links.new(output, endpoint.inputs[item.name])
        previous = scene.compositing_node_group
        scene.compositing_node_group = tree
        try:
            scene.render.use_compositing = True
            scene.render.use_sequencer = False
            scene.render.compositor_device = "CPU"
            scene.render.compositor_precision = "FULL"
            _configure_linear(scene)
            _checkpoint(context)
            result = bpy.ops.render.render(write_still=False, scene=scene.name)
            _checkpoint(context)
            if "FINISHED" not in result:
                raise RuntimeError("Native Compositor Bake did not finish")
            files = tuple(Path(directory).glob("bake_*.exr"))
            if not files:
                # Constant images lack an intrinsic file-output domain. The
                # root output supplies the finite scene-canvas fallback.
                rendered = bpy.data.images.get("Render Result")
                if rendered is None:
                    raise RuntimeError("Native Compositor Bake produced no pixels")
                fallback = Path(directory) / "bake_constant.exr"
                rendered.save_render(str(fallback), scene=scene)
                files = (fallback,)
            if len(files) != 1:
                raise RuntimeError("Native Compositor Bake produced multiple RGBA images")
            image = bpy.data.images.load(str(files[0]), check_existing=False)
            try:
                image.colorspace_settings.name = "Non-Color"
                image.alpha_mode = "CHANNEL_PACKED"
                if hasattr(image, "use_half_precision"):
                    image.use_half_precision = False
                pixels = _read_image(image)
            finally:
                bpy.data.images.remove(image)
        finally:
            scene.compositing_node_group = previous
    _checkpoint(context)
    return _result(pixels, inputs, target, target, backend="COMPOSITOR")


def _set_frame(scene, values):
    frame = values.get("frame")
    subframe = values.get("frame_subframe", values.get("subframe", 0.0))
    if frame is not None:
        scene.frame_set(int(frame), subframe=float(subframe))


def _result(pixels, inputs, target, descriptor, *, backend):
    import bpy

    pixels = np.asarray(pixels, dtype=np.float32)
    if pixels.ndim != 3 or pixels.shape[-1] != 4 or not np.isfinite(pixels).all():
        raise ArithmeticError("Native Bake produced nonfinite RGBA pixels")
    directory = Path(inputs["artifact_dir"])
    if not directory.is_absolute() or directory.is_symlink() or not directory.is_dir():
        raise ValueError("Invalid bake artifact directory")
    generation = inputs.get("generation", inputs.get("request_generation"))
    if type(generation) is not int or generation < 1:
        raise ValueError("Bake artifact requires a positive request generation")
    path = directory / ("pg_next_bake_" + str(generation) + ".exr")
    if path.is_symlink() or path.exists():
        raise ValueError("Bake artifact path must not be a symbolic link")
    if pixels.shape[1] * pixels.shape[0] * 16 > MAX_PIXEL_BYTES:
        raise MemoryError("Native Bake output exceeds the pixel budget")
    image = _new_image("PG Next Bake Completed", int(pixels.shape[1]), int(pixels.shape[0]))
    scene = bpy.data.scenes.get(str(target.get("scene", "")))
    if scene is None:
        raise ValueError("Bake output scene is absent")
    try:
        _configure_linear(scene)
        image.pixels.foreach_set(pixels.reshape(-1))
        image.update()
        image.save_render(str(path), scene=scene)
    finally:
        bpy.data.images.remove(image)
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return {
        "path": str(path),
        "sha256": digest.hexdigest(),
        "width": int(pixels.shape[1]),
        "height": int(pixels.shape[0]),
        "identity": inputs.get("identity", target.get("identity")),
        "signature": inputs.get("signature", target.get("signature")),
        "artifact_signature": target.get(
            "artifact_signature", target.get("source_signature", target.get("signature"))),
        "generation": generation,
        "scene": target.get("scene"),
        "frame": int(target.get("frame", 0)),
        "frame_subframe": float(target.get("frame_subframe", target.get("subframe", 0.0))),
        "node": target.get("node_name"),
        "backend": backend,
        "evaluation": "NODE_TREE",
        "domain": descriptor.get("domain", "COMPOSITOR"),
        "uv_map": descriptor.get("uv_map"),
        "interpolation": descriptor.get("interpolation", "Linear"),
        "extension": descriptor.get("extension", "REPEAT"),
    }


class BakeWorker:
    """Process-owned dispatch object used by :class:`HelperRuntime`."""

    def dispatch(self, operation, inputs, context):
        if operation == "gpu_probe":
            import bpy

            context.checkpoint()
            _minimal_node_types()
            return {"conformance": True, "backend": "NODE_TREE", "blender": tuple(bpy.app.version)}
        if operation in {"native_bake", "bake", "shader_bake"}:
            context.checkpoint()
            _open_snapshot(inputs)
            import bpy

            # Saved output nodes must never write to a user's file paths.
            for tree in tuple(bpy.data.node_groups):
                if tree.bl_idname == "CompositorNodeTree":
                    for node in tuple(tree.nodes):
                        if node.bl_idname == "CompositorNodeOutputFile":
                            tree.nodes.remove(node)
            route = inputs.get("route")
            if route is not None:
                if not isinstance(route, dict):
                    raise TypeError("Bake route must be a frozen mapping")
                inputs = dict(inputs, target=route, descriptor=route)
                kind = "compositor" if route.get("domain") == "COMPOSITOR" else "shader"
            else:
                kind = str(inputs.get("kind", "shader")).lower()
            target = inputs.get("target", {})
            scene = bpy.data.scenes.get(str(target.get("scene", "")))
            if scene is not None and bpy.context.window is not None:
                bpy.context.window.scene = scene
                if scene.view_layers:
                    bpy.context.window.view_layer = scene.view_layers[0]
            context.checkpoint()
            if kind in {"shader", "material", "world"}:
                return _shader(inputs, context)
            if kind in {"compositor", "composite"}:
                return _compositor(inputs, context)
            raise ValueError("Unknown native Bake kind: " + kind)
        if operation == "compositor_bake":
            return self.dispatch("bake", dict(inputs, kind="compositor"), context)
        raise ValueError("Unknown Bake helper operation: " + str(operation))


def create():
    return BakeWorker()


__all__ = ("BakeWorker", "create")
