"""Isolated capture of a Grade's input or guarded final appearance."""

from pathlib import Path
import tempfile
from uuid import uuid4

import numpy as np

from ...runtime.capture_host import (
    compositor_root, configure_linear, disable_file_outputs, open_snapshot,
)
from ...runtime.capture_images import route_datablock


MAX_CAPTURE_EDGE = 512
MAX_CAPTURE_PIXELS = MAX_CAPTURE_EDGE * MAX_CAPTURE_EDGE
MAX_CAPTURE_BYTES = MAX_CAPTURE_PIXELS * 16
MAX_SOURCE_BYTES = 512 * 1024 * 1024


def _bounded_size(width, height):
    width, height = int(width), int(height)
    if min(width, height) < 1:
        raise ValueError("Vectorscope capture dimensions must be positive")
    scale = min(1.0, MAX_CAPTURE_EDGE / max(width, height))
    return max(1, round(width * scale)), max(1, round(height * scale))


def _sources(root, group_path, node_name, *socket_names):
    """Copy the selected occurrence once and expose its input sources."""
    tree, parents, target = _occurrence(root, group_path, node_name)
    return tuple(_expose_input(tree, parents, target.inputs.get(name)) for name in socket_names)


def _occurrence(root, group_path, node_name):
    tree = root
    parents = []
    for name in tuple(group_path):
        group = tree.nodes.get(str(name))
        if group is None or group.node_tree is None:
            raise ValueError("Vectorscope node-group occurrence is absent: " + str(name))
        group.node_tree = group.node_tree.copy()
        parents.append((tree, group))
        tree = group.node_tree

    target = tree.nodes.get(str(node_name))
    if target is None:
        raise ValueError("Vectorscope Grade node is absent: " + str(node_name))
    return tree, parents, target


def _expose_input(tree, parents, incoming):
    if incoming is None or incoming.type not in {"RGBA", "VALUE"}:
        raise ValueError("Vectorscope target input has an unsupported socket type")

    links = tuple(link for link in incoming.links
                  if getattr(link, "is_valid", True) and not getattr(link, "is_muted", False))
    if len(links) > 1:
        raise ValueError("Vectorscope Color input has multiple active sources")
    if links:
        output = links[0].from_socket
        if output.type == "SHADER":
            raise ValueError("Shader closures cannot be sampled as a Color input")
    else:
        color_socket = incoming.type == "RGBA"
        if tree.bl_idname == "ShaderNodeTree":
            kind = "ShaderNodeRGB" if color_socket else "ShaderNodeValue"
        else:
            kind = "CompositorNodeRGB" if color_socket else "CompositorNodeValue"
        constant = tree.nodes.new(kind)
        constant.outputs[0].default_value = (
            tuple(incoming.default_value) if color_socket else float(incoming.default_value)
        )
        output = constant.outputs[0]

    socket_type = "NodeSocketColor" if incoming.type == "RGBA" else "NodeSocketFloat"
    return _expose_output(tree, parents, output, socket_type, "PG Vectorscope Input ")


def _group_output(tree):
    endpoint = next((node for node in tree.nodes
                     if node.bl_idname == "NodeGroupOutput" and node.is_active_output), None)
    if endpoint is None:
        endpoint = tree.nodes.new("NodeGroupOutput")
        endpoint.is_active_output = True
    return endpoint


def _expose_output(tree, parents, source, socket_type, prefix):
    for parent, group in reversed(parents):
        field = tree.interface.new_socket(
            name=prefix + uuid4().hex,
            in_out="OUTPUT",
            socket_type=socket_type,
        )
        endpoint = _group_output(tree)
        tree.links.new(source, _socket(endpoint.inputs, field.identifier))
        source = _socket(group.outputs, field.identifier)
        tree = parent
    return source


def _appearance_outputs(root, group_path, node_name):
    """Expose Grade's guarded final-appearance tap through private copies."""
    from ..grade import appearance_endpoint

    tree, parents, target = _occurrence(root, group_path, node_name)
    kernel, outputs, grade_parents = appearance_endpoint.resolve(tree, target)
    parents.extend(grade_parents)
    fields = (
        (outputs[0], "NodeSocketColor", "Appearance "),
        (outputs[1], "NodeSocketFloat", "Appearance Alpha "),
    )
    return tuple(_expose_output(kernel, parents, source, socket_type, prefix)
                 for source, socket_type, prefix in fields)


def _socket(sockets, name):
    result = next((item for item in sockets if item.identifier == name), None)
    if result is None:
        result = sockets.get(name)
    if result is None:
        raise ValueError("Vectorscope socket is absent: " + str(name))
    return result


def _output_node(tree, directory, prefix):
    endpoint = tree.nodes.new("CompositorNodeOutputFile")
    endpoint.name = "PG Vectorscope Capture"
    endpoint.directory = str(directory)
    endpoint.file_name = prefix
    item = endpoint.file_output_items.new("RGBA", "scope")
    endpoint.format.media_type = "IMAGE"
    endpoint.format.file_format = "OPEN_EXR"
    endpoint.format.color_mode = "RGBA"
    endpoint.format.color_depth = "32"
    endpoint.format.exr_codec = "ZIPS"
    endpoint.format.color_management = "OVERRIDE"
    endpoint.format.linear_colorspace_settings.name = "scene_linear"
    endpoint.save_as_render = False
    return endpoint, item


def _root_output(tree, source):
    interface = tree.interface
    output = interface.new_socket(
        name="PG Vectorscope", in_out="OUTPUT", socket_type="NodeSocketColor",
    )
    interface.move(output, 0)
    endpoint = tree.nodes.new("NodeGroupOutput")
    endpoint.is_active_output = True
    tree.links.new(source, _socket(endpoint.inputs, output.identifier))


def _install_tree(scene, tree):
    effects = getattr(scene, "compositor_effects", None)
    if effects is None:
        scene.compositing_node_group = tree
    else:
        effects.clear()
        effect = effects.new("PG Vectorscope Capture")
        effect.node_group = tree
        effect.enable_for_render = True
    scene.render.use_compositing = True
    scene.render.use_sequencer = False
    scene.render.compositor_device = "CPU"
    scene.render.compositor_precision = "FULL"


def _exr_dimensions(path):
    import struct

    def read(stream, size):
        data = stream.read(size)
        if len(data) != size:
            raise ValueError("Vectorscope EXR header is incomplete")
        return data

    def string(stream):
        result = bytearray()
        while True:
            value = read(stream, 1)
            if value == b"\0":
                return result.decode("utf8")
            result.extend(value)
            if len(result) > 1024:
                raise ValueError("Vectorscope EXR header contains an oversized name")

    with Path(path).open("rb") as stream:
        magic, version = struct.unpack("<II", read(stream, 8))
        if magic != 20000630 or version & 0x1A00:
            raise ValueError("Vectorscope capture requires a single-part EXR")
        bounds = None
        size = 0
        while True:
            name = string(stream)
            if not name:
                break
            kind = string(stream)
            length = struct.unpack("<I", read(stream, 4))[0]
            if length > 16 * 1024 * 1024:
                raise ValueError("Vectorscope EXR attribute is oversized")
            data = read(stream, length)
            size += length
            if size > 64 * 1024 * 1024:
                raise ValueError("Vectorscope EXR header is oversized")
            if name == "dataWindow" and kind == "box2i" and length == 16:
                bounds = struct.unpack("<4i", data)
    if bounds is None:
        raise ValueError("Vectorscope EXR has no data window")
    width, height = bounds[2] - bounds[0] + 1, bounds[3] - bounds[1] + 1
    if min(width, height) < 1 or width * height * 16 > MAX_SOURCE_BYTES:
        raise MemoryError("Vectorscope native capture exceeds its 512 MiB pixel budget")
    return width, height


def _rgba_buffer(pixels, dtype, *, copy=False):
    if pixels.shape[-1] == 3:
        rgba = np.empty((*pixels.shape[:2], 4), dtype=dtype)
        rgba[..., :3] = pixels
        rgba[..., 3] = 1.0
    else:
        rgba = (np.array(pixels, dtype=dtype, order="C", copy=True) if copy
                else np.ascontiguousarray(pixels, dtype=dtype))
    invalid = ~np.isfinite(rgba).all(axis=-1)
    if np.any(invalid):
        if rgba is pixels:
            rgba = rgba.copy()
        rgba[invalid] = 0.0
    return rgba


def _sample_pixels(pixels):
    height, width = pixels.shape[:2]
    sample_width, sample_height = _bounded_size(width, height)
    if (sample_width, sample_height) == (width, height):
        return _rgba_buffer(pixels, np.float32)

    # Reduce along the longer axis first to bound temporary storage per row.
    transposed = width > height
    if transposed:
        pixels = pixels.swapaxes(0, 1)
        height, width = width, height
        sample_height, sample_width = sample_width, sample_height

    # Integer edges retain exact overlap at fractional source-pixel boundaries.
    left = np.arange(sample_width) * width
    right = left + width
    first = left // sample_width
    last = (right - 1) // sample_width
    columns = first[:, None] + np.arange(np.max(last - first) + 1)
    column_weights = np.maximum(
        0, np.minimum(right[:, None], (columns + 1) * sample_width)
        - np.maximum(left[:, None], columns * sample_width),
    ) / width
    np.minimum(columns, width - 1, out=columns)

    reduced = np.empty((sample_height, sample_width, 4), dtype=np.float32)
    for row in range(sample_height):
        bottom, top = row * height, (row + 1) * height
        start = bottom // sample_height
        stop = (top - 1) // sample_height + 1
        rows = np.arange(start, stop)
        row_weights = (
            np.minimum(top, (rows + 1) * sample_height)
            - np.maximum(bottom, rows * sample_height)
        ) / height
        band = _rgba_buffer(pixels[start:stop], np.float64, copy=True)
        alpha = band[..., 3]
        np.clip(alpha, 0.0, 1.0, out=alpha)
        alpha *= row_weights[:, None]
        band[..., :3] *= alpha[..., None]
        integrated = np.sum(band, axis=0)
        cells = np.sum(integrated[columns] * column_weights[..., None], axis=1)
        alpha = cells[:, 3:4]
        np.divide(cells[:, :3], alpha, out=cells[:, :3], where=alpha > 0.0)
        reduced[row] = cells
    return np.ascontiguousarray(reduced.swapaxes(0, 1) if transposed else reduced)


def _read_buffer(image):
    width, height = (int(value) for value in image.size)
    channels = int(image.channels)
    if (min(width, height) < 1 or channels not in (3, 4)
            or width * height * channels * 4 > MAX_SOURCE_BYTES):
        raise MemoryError("Vectorscope source readback exceeds its 512 MiB budget")
    pixels = np.empty((height, width, channels), dtype=np.float32)
    image.pixels.foreach_get(pixels.reshape(-1))
    return _sample_pixels(pixels)


def _raw_compositor_image(route, scene):
    """Resolve the connected Image when Blender uses its raw channels."""
    import bpy
    if route.get("scope_capture") == "appearance":
        return None
    tree = compositor_root(bpy, scene, route)
    for name in tuple(route.get("group_path", ())):
        group = tree.nodes.get(str(name))
        if group is None or group.node_tree is None or group.mute:
            return None
        tree = group.node_tree
    target = tree.nodes.get(str(route["node_name"]))
    incoming = target.inputs.get(str(route.get("socket_name", "Color"))) if target else None
    if incoming is None:
        return None
    links = tuple(link for link in incoming.links
                  if getattr(link, "is_valid", True) and not getattr(link, "is_muted", False))
    if len(links) != 1:
        return None
    link = links[0]
    source = link.from_node
    if (source.bl_idname != "CompositorNodeImage" or source.mute
            or link.from_socket.name != "Image"):
        return None
    image = source.image
    if (image is None or image.source not in {"FILE", "GENERATED"}
            or image.type not in {"IMAGE", "UV_TEST"} or image.use_multiview
            or not image.is_float or int(image.channels) not in (3, 4)
            or image.colorspace_settings.name != "Non-Color"
            or image.alpha_mode != "CHANNEL_PACKED"):
        return None
    return image


def capture_loaded_image(route):
    """Read a bounded, already loaded input without freezing a scene snapshot."""
    import bpy

    if route["owner_kind"] != "compositor" or route.get("scope_capture") == "appearance":
        return None
    scene = route_datablock(bpy, bpy.data.scenes, route, "scene")
    if scene is None:
        return None
    image = _raw_compositor_image(route, scene)
    if image is None or not image.has_data:
        return None
    width, height = image.size
    if not (0 < width <= MAX_CAPTURE_EDGE and 0 < height <= MAX_CAPTURE_EDGE):
        return None
    return _read_buffer(image)


def _read_image(path, expected_size=None):
    import bpy

    image = bpy.data.images.load(str(path), check_existing=False)
    try:
        image.colorspace_settings.name = "Non-Color"
        image.alpha_mode = "CHANNEL_PACKED"
        width, height = (int(value) for value in image.size)
        channels = int(image.channels)
        if (min(width, height) < 1 or channels not in (3, 4)
                or width * height * channels * 4 > MAX_SOURCE_BYTES):
            raise MemoryError("Vectorscope source readback exceeds its 512 MiB budget")
        if expected_size is not None and (width, height) != tuple(expected_size):
            raise ValueError("Vectorscope capture output has unexpected dimensions")
        return _read_buffer(image)
    finally:
        bpy.data.images.remove(image)


def _render(scene, route, context):
    import bpy

    context.checkpoint()
    result = bpy.ops.render.render(write_still=False, scene=scene.name,
                                   layer=("" if route["owner_kind"] == "compositor"
                                          else str(route["view"]["view_layer"])))
    context.checkpoint()
    if "FINISHED" not in result:
        raise RuntimeError("Vectorscope native capture did not finish")


def _compositor_capture(route, scene, context):
    import bpy
    started = context.start_timing()
    root = compositor_root(bpy, scene, route)
    tree = root.copy()
    path, target = route.get("group_path", ()), route["node_name"]
    if route.get("scope_capture") == "appearance":
        packed, opacity = _appearance_outputs(tree, path, target)
        restore = tree.nodes.new("CompositorNodeSetAlpha")
        restore.inputs["Type"].default_value = "Replace Alpha"
        tree.links.new(packed, restore.inputs["Image"])
        tree.links.new(opacity, restore.inputs["Alpha"])
        output = restore.outputs["Image"]
    else:
        output, = _sources(tree, path, target, route.get("socket_name", "Color"))
    for node in tuple(tree.nodes):
        if node.bl_idname in {"NodeGroupOutput", "CompositorNodeViewer", "CompositorNodeOutputFile"}:
            tree.nodes.remove(node)

    _root_output(tree, output)
    with tempfile.TemporaryDirectory(prefix="pg-next-vectorscope-") as directory:
        token = uuid4().hex
        endpoint, item = _output_node(tree, directory, "scope_" + token + "_")
        tree.links.new(output, endpoint.inputs[item.name])
        _install_tree(scene, tree)
        configure_linear(scene)
        context.finish_timing("capture_setup", started)
        with context.measure("capture_render"):
            _render(scene, route, context)
        with context.measure("capture_readback"):
            files = tuple(Path(directory).glob("scope_" + token + "_*.exr"))
            if len(files) > 1:
                raise RuntimeError("Compositor vectorscope capture did not produce one image")
            if files:
                path = files[0]
            else:
                # A constant has no native image domain. Its root output is evaluated
                # across the scene canvas and returned through Render Result.
                rendered = bpy.data.images.get("Render Result")
                if rendered is None:
                    raise RuntimeError("Compositor vectorscope capture produced no pixels")
                path = Path(directory) / "constant.exr"
                rendered.save_render(str(path), scene=scene)
            return _read_image(path, _exr_dimensions(path))


def _camera(scene, view, render_size):
    import bpy
    from mathutils import Matrix

    if "view_matrix" not in view or "projection_matrix" not in view:
        raise ValueError("Shader vectorscope capture requires an active 3D viewport")
    matrix = Matrix(view["view_matrix"])
    projection = Matrix(view["projection_matrix"])
    projection_values = np.asarray(projection, dtype=np.float64)
    matrix_scale = float(np.max(np.abs(projection_values)))
    if not np.isfinite(matrix_scale) or matrix_scale == 0:
        raise ValueError("Shader vectorscope viewport projection is invalid")

    orthographic = abs(projection[3][3]) > matrix_scale * 1e-6
    if orthographic:
        projection_values = projection_values / projection[3][3]
        allowed = {(0, 0), (1, 1), (2, 2), (0, 3), (1, 3), (2, 3), (3, 3)}
        if (projection_values[0, 0] <= 0 or projection_values[1, 1] <= 0
                or any(abs(projection_values[row, column]) > 1e-7
                       for row in range(4) for column in range(4)
                       if (row, column) not in allowed)):
            raise ValueError("Shader vectorscope viewport projection cannot be reproduced")
        scale, offset = projection_values[2, 2], projection_values[2, 3]
        near_z, far_z = (-1.0 - offset) / scale, (1.0 - offset) / scale
        near = max(0.001, float(view.get("clip_start", 0.01)))
        far = near + near_z - far_z
        displacement = near_z + near
        if not np.isfinite((near, far, displacement)).all() or not 0 < near < far:
            raise ValueError("Shader vectorscope orthographic viewport clipping is invalid")
        kind = "ORTHO"
    else:
        near = max(0.001, float(view.get("clip_start", 0.01)))
        far = max(near + 0.001, float(view.get("clip_end", 1000.0)))
        displacement = 0.0
        kind = "PERSP"

    camera_data = bpy.data.cameras.new("PG Vectorscope Camera")
    camera = bpy.data.objects.new("PG Vectorscope Camera", camera_data)
    scene.collection.objects.link(camera)
    depth_origin = Matrix.Translation((0.0, 0.0, displacement))
    camera.matrix_world = matrix.inverted() @ depth_origin
    scene.camera = camera
    camera_data.sensor_fit = "HORIZONTAL"
    camera_data.sensor_width = 36.0
    camera_data.clip_start = near
    camera_data.clip_end = far
    camera_data.type = kind
    if kind == "PERSP":
        camera_data.lens = 18.0 * projection[0][0]
        camera_data.shift_x = projection[0][2] / 2.0
        camera_data.shift_y = projection[1][2] * projection[0][0] / (2.0 * projection[1][1])
    else:
        camera_data.ortho_scale = 2.0 / projection[0][0]
        camera_data.shift_x = -projection[0][3] / 2.0
        camera_data.shift_y = -projection[1][3] * projection[0][0] / (2.0 * projection[1][1])
    viewport_width = int(view.get("viewport_width", view["width"]))
    viewport_height = int(view.get("viewport_height", view["height"]))
    pixel_aspect = render_size[0] * viewport_height / (render_size[1] * viewport_width)
    scene.render.pixel_aspect_x = max(1.0, 1.0 / pixel_aspect)
    scene.render.pixel_aspect_y = max(1.0, pixel_aspect)

    depsgraph = bpy.context.evaluated_depsgraph_get()
    bpy.context.view_layer.update()
    actual = camera.calc_matrix_camera(
        depsgraph, x=render_size[0], y=render_size[1],
        scale_x=scene.render.pixel_aspect_x, scale_y=scene.render.pixel_aspect_y,
    )
    actual_values = np.asarray(actual, dtype=np.float64)
    expected = projection_values
    if orthographic:
        effective = actual_values @ np.asarray(depth_origin.inverted(), dtype=np.float64)
    else:
        effective, expected = actual_values[:2], expected[:2]
    if not np.allclose(effective, expected, rtol=2e-5, atol=2e-5):
        raise ValueError("Shader vectorscope render camera differs from the active viewport")

    visible = view.get("visible_objects")
    if visible is not None:
        names = set(visible)
        for collection in bpy.data.collections:
            collection.hide_render = False
        for obj in scene.objects:
            if obj != camera:
                obj.hide_render = obj.name not in names


def _aov(view_layer, tree, name, output=None, *, value=False):
    entry = view_layer.aovs.add()
    entry.name = name
    entry.type = "VALUE" if value else "COLOR"
    tap = tree.nodes.new("ShaderNodeOutputAOV")
    tap.aov_name = name
    destination = tap.inputs["Value" if value else "Color"]
    if output is None:
        destination.default_value = 1.0
    else:
        tree.links.new(output, destination)


def _resolve_shader_aovs(rgba, alpha, mask, *, appearance):
    coverage = np.clip(mask, 0.0, 1.0)
    opacity = np.clip(alpha, 0.0, coverage)
    weight = opacity if appearance else coverage
    visible = weight > 1e-8
    np.divide(rgba[..., :3], weight[..., None], out=rgba[..., :3],
              where=visible[..., None])
    rgba[..., :3][~visible] = 0.0
    rgba[..., 3] = opacity
    return rgba


def _shader_owner(route):
    import bpy
    collections = {"material": bpy.data.materials, "world": bpy.data.worlds}
    collection = collections.get(str(route["owner_kind"]).lower())
    if collection is None:
        raise ValueError("Shader vectorscope capture supports Materials and Worlds")
    return route_datablock(bpy, collection, route, "owner")


def _shader_capture(route, scene, view_layer, context):
    import bpy
    started = context.start_timing()
    owner = _shader_owner(route)
    if owner is None or owner.node_tree is None:
        raise ValueError("Shader vectorscope owner has no node tree")
    if str(route["owner_kind"]).lower() == "world" and scene.world != owner:
        raise ValueError("Shader vectorscope World is not used by the selected scene")
    view = route["view"]
    if scene.render.engine not in {"CYCLES", "BLENDER_EEVEE", "BLENDER_EEVEE_NEXT"}:
        raise ValueError("The active render engine does not provide Shader AOV capture")
    width, height = _bounded_size(view["width"], view["height"])
    scene.render.resolution_percentage = 100
    scene.render.resolution_x, scene.render.resolution_y = width, height
    scene.render.use_border = False
    scene.render.use_multiview = False
    configure_linear(scene)

    token = uuid4().hex
    color_name, mask_name = "PGVectorscopeColor_" + token, "PGVectorscopeMask_" + token
    path, target = route.get("group_path", ()), route["node_name"]
    appearance = route.get("scope_capture") == "appearance"
    if appearance:
        output, alpha_output = _appearance_outputs(owner.node_tree, path, target)
    else:
        output, alpha_output = _sources(owner.node_tree, path, target,
                                        route.get("socket_name", "Color"), "Alpha")
    _aov(view_layer, owner.node_tree, color_name, output)
    alpha_name = "PGVectorscopeAlpha_" + token
    _aov(view_layer, owner.node_tree, alpha_name, alpha_output, value=True)
    _aov(view_layer, owner.node_tree, mask_name, value=True)
    view_layer.update_render_passes()
    _camera(scene, view, (width, height))

    tree = bpy.data.node_groups.new("PG Vectorscope AOV Output", "CompositorNodeTree")
    render_layers = tree.nodes.new("CompositorNodeRLayers")
    render_layers.scene = scene
    render_layers.layer = view_layer.name
    color_output = render_layers.outputs.get(color_name)
    alpha_aov = render_layers.outputs.get(alpha_name)
    mask_output = render_layers.outputs.get(mask_name)
    if color_output is None or alpha_aov is None or mask_output is None:
        raise RuntimeError("Shader vectorscope AOV outputs are unavailable")

    with tempfile.TemporaryDirectory(prefix="pg-next-vectorscope-") as directory:
        _root_output(tree, color_output)
        color_endpoint, color_item = _output_node(tree, directory, "scope_color_" + token + "_")
        alpha_endpoint, alpha_item = _output_node(tree, directory, "scope_alpha_" + token + "_")
        mask_endpoint, mask_item = _output_node(tree, directory, "scope_mask_" + token + "_")
        tree.links.new(color_output, color_endpoint.inputs[color_item.name])
        tree.links.new(alpha_aov, alpha_endpoint.inputs[alpha_item.name])
        tree.links.new(mask_output, mask_endpoint.inputs[mask_item.name])
        _install_tree(scene, tree)
        context.finish_timing("capture_setup", started)
        with context.measure("capture_render"):
            _render(scene, route, context)
        color_files = tuple(Path(directory).glob("scope_color_" + token + "_*.exr"))
        alpha_files = tuple(Path(directory).glob("scope_alpha_" + token + "_*.exr"))
        mask_files = tuple(Path(directory).glob("scope_mask_" + token + "_*.exr"))
        if len(color_files) != 1 or len(alpha_files) != 1 or len(mask_files) != 1:
            raise RuntimeError("Shader vectorscope capture did not produce its AOV images")
        with context.measure("capture_readback"):
            rgba = _read_image(color_files[0], (width, height))
            alpha = _read_image(alpha_files[0], (width, height))[..., 0]
            mask = _read_image(mask_files[0], (width, height))[..., 0]
        return _resolve_shader_aovs(rgba, alpha, mask, appearance=appearance)


def capture(inputs, context):
    """Capture and return a bounded `{rgba: float32[height,width,4]}` sample."""
    import bpy
    expected = {"snapshot_path", "images", "route"}
    if (not isinstance(inputs, dict)
            or set(inputs) not in (expected, expected | {"artifact_dir"})):
        raise ValueError("Vectorscope capture inputs do not match the canonical request")
    route = inputs["route"]
    if not isinstance(route, dict) or not isinstance(route.get("view"), dict):
        raise TypeError("Vectorscope capture requires a frozen route and view")
    if route.get("scope_capture", "input") not in {"input", "appearance"}:
        raise ValueError("Vectorscope capture kind is not supported")
    with context.measure("capture_snapshot_open"):
        open_snapshot(inputs)
    scene = route_datablock(bpy, bpy.data.scenes, route, "scene")
    if scene is None:
        raise ValueError("Vectorscope capture scene is absent")
    with context.measure("capture_scene_setup"):
        if bpy.context.window is not None:
            bpy.context.window.scene = scene
        view_layer = scene.view_layers.get(str(route["view"].get("view_layer", "")))
        if view_layer is None:
            raise ValueError("Vectorscope capture view layer is absent")
        if bpy.context.window is not None:
            bpy.context.window.view_layer = view_layer
        scene.frame_set(int(route["frame"]), subframe=float(route.get("subframe", 0.0)))
        disable_file_outputs()
    context.checkpoint()

    kind = str(route.get("owner_kind", "")).lower()
    if kind == "compositor":
        image = _raw_compositor_image(route, scene)
        if image is None:
            rgba = _compositor_capture(route, scene, context)
        else:
            with context.measure("capture_readback"):
                rgba = _read_buffer(image)
    elif kind in {"material", "world"}:
        rgba = _shader_capture(route, scene, view_layer, context)
    else:
        raise ValueError("Vectorscope capture supports Compositor, Material, and World inputs")

    if (rgba.ndim != 3 or rgba.shape[-1] != 4
            or rgba.shape[0] * rgba.shape[1] > MAX_CAPTURE_PIXELS
            or rgba.nbytes > MAX_CAPTURE_BYTES):
        raise ArithmeticError("Vectorscope capture returned invalid or unbounded RGBA pixels")
    context.checkpoint()
    return {"rgba": np.ascontiguousarray(rgba)}


__all__ = ("capture", "MAX_CAPTURE_BYTES", "MAX_CAPTURE_EDGE", "MAX_CAPTURE_PIXELS")
