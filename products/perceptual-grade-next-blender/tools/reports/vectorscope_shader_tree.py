"""Temporary Shader Editor mapping pass for vectorscope reducer comparisons."""

import os
from pathlib import Path
import tempfile
import time

import numpy as np


def _math(tree, operation, *values):
    node = tree.nodes.new("ShaderNodeMath")
    node.operation = operation
    for socket, value in zip(node.inputs, values):
        if hasattr(value, "node"):
            tree.links.new(value, socket)
        else:
            socket.default_value = float(value)
    return node.outputs[0]


def _map_shader_tree(tree, image, matrix, limit, size):
    coordinates = tree.nodes.new("ShaderNodeTexCoord")
    source = tree.nodes.new("ShaderNodeTexImage")
    source.image = image
    source.interpolation = "Closest"
    tree.links.new(coordinates.outputs["UV"], source.inputs["Vector"])

    separate = tree.nodes.new("ShaderNodeSeparateXYZ")
    tree.links.new(source.outputs["Color"], separate.inputs[0])
    rows = tuple(tuple(float(value) for value in row) for row in matrix)
    corrected = []
    for row in range(3):
        value = _math(tree, "MULTIPLY", separate.outputs[0], rows[row][0])
        value = _math(tree, "ADD", value,
                      _math(tree, "MULTIPLY", separate.outputs[1], rows[row][1]))
        value = _math(tree, "ADD", value,
                      _math(tree, "MULTIPLY", separate.outputs[2], rows[row][2]))
        corrected.append(value)

    code = []
    for channel in corrected:
        magnitude = _math(tree, "ABSOLUTE", channel)
        toe = _math(tree, "MULTIPLY", magnitude, 4.5)
        shoulder = _math(
            tree,
            "SUBTRACT",
            _math(tree, "MULTIPLY", _math(tree, "POWER", magnitude, 0.45), 1.099),
            0.099,
        )
        linear = _math(tree, "LESS_THAN", magnitude, 0.018)
        encoded = _math(tree, "ADD",
                        _math(tree, "MULTIPLY", toe, linear),
                        _math(tree, "MULTIPLY", shoulder,
                              _math(tree, "SUBTRACT", 1.0, linear)))
        positive = _math(tree, "GREATER_THAN", channel, 0.0)
        negative = _math(tree, "LESS_THAN", channel, 0.0)
        sign = _math(tree, "SUBTRACT", positive, negative)
        code.append(_math(tree, "MULTIPLY", encoded, sign))

    luma = _math(tree, "ADD",
                 _math(tree, "MULTIPLY", code[0], 0.2126),
                 _math(tree, "MULTIPLY", code[1], 0.7152))
    luma = _math(tree, "ADD", luma, _math(tree, "MULTIPLY", code[2], 0.0722))
    cb = _math(tree, "DIVIDE", _math(tree, "SUBTRACT", code[2], luma), 1.8556)
    cr = _math(tree, "DIVIDE", _math(tree, "SUBTRACT", code[0], luma), 1.5748)

    alpha_value = _math(tree, "MAXIMUM", 0.0,
                        _math(tree, "MINIMUM", 1.0, source.outputs["Alpha"]))
    valid_cb = _math(tree, "SUBTRACT", 1.0,
                     _math(tree, "GREATER_THAN", _math(tree, "ABSOLUTE", cb), limit))
    valid_cr = _math(tree, "SUBTRACT", 1.0,
                     _math(tree, "GREATER_THAN", _math(tree, "ABSOLUTE", cr), limit))
    valid = _math(tree, "MULTIPLY", _math(tree, "MULTIPLY", valid_cb, valid_cr),
                  _math(tree, "GREATER_THAN", alpha_value, 0.0))

    bin_cb = _math(tree, "FLOOR", _math(tree, "MULTIPLY",
                                        _math(tree, "DIVIDE", _math(tree, "ADD", cb, limit),
                                              2.0 * limit), size))
    bin_cr = _math(tree, "FLOOR", _math(tree, "MULTIPLY",
                                        _math(tree, "DIVIDE", _math(tree, "ADD", cr, limit),
                                              2.0 * limit), size))
    bin_cb = _math(tree, "MINIMUM", size - 1.0, _math(tree, "MAXIMUM", 0.0, bin_cb))
    bin_cr = _math(tree, "MINIMUM", size - 1.0, _math(tree, "MAXIMUM", 0.0, bin_cr))
    bin_cb = _math(tree, "MULTIPLY", bin_cb, valid)
    bin_cr = _math(tree, "MULTIPLY", bin_cr, valid)

    # Eevee's half-float AOVs can represent each of these integers exactly.
    scaled_alpha = _math(tree, "MULTIPLY", alpha_value, 1024.0)
    alpha_high = _math(tree, "FLOOR", scaled_alpha)
    alpha_low = _math(tree, "FLOOR", _math(tree, "MULTIPLY",
                                            _math(tree, "SUBTRACT", scaled_alpha, alpha_high),
                                            1024.0))
    alpha_high = _math(tree, "MULTIPLY", alpha_high, valid)
    alpha_low = _math(tree, "MULTIPLY", alpha_low, valid)

    packed = tree.nodes.new("ShaderNodeCombineColor")
    packed.mode = "RGB"
    for channel, value in zip(("Red", "Green", "Blue"), (bin_cb, bin_cr, alpha_high)):
        tree.links.new(value, packed.inputs[channel])
    return packed.outputs[0], alpha_low


def _render_scene(bpy, scene):
    return bpy.ops.render.render(write_still=False, scene=scene.name)


def _temporary_id_snapshot(bpy):
    names = ("scenes", "objects", "meshes", "cameras", "images", "materials", "node_groups")
    return {
        name: frozenset(
            int(item.as_pointer()) for item in getattr(bpy.data, name)
            if name != "images" or item.type != "RENDER_RESULT"
        )
        for name in names
    }


def _render_mapped_pixels(bpy, capture, rgba, matrix, limit, size):
    height, width = rgba.shape[:2]
    engine = bpy.context.scene.render.engine
    scene = bpy.data.scenes.new("PG Vectorscope Mapping Scene")
    created = [scene]
    try:
        scene.render.engine = engine
        scene.render.resolution_x = width
        scene.render.resolution_y = height
        scene.render.resolution_percentage = 100
        scene.render.film_transparent = False
        scene.render.filter_size = 0.01
        scene.render.threads_mode = "FIXED"
        scene.render.threads = min(8, max(1, os.cpu_count() or 1))
        scene.eevee.taa_samples = 1
        scene.eevee.taa_render_samples = 1
        scene.eevee.use_taa_reprojection = False
        scene.view_settings.view_transform = "Standard"
        scene.view_settings.look = "None"
        scene.view_settings.exposure = 0.0
        scene.view_settings.gamma = 1.0

        camera_data = bpy.data.cameras.new("PG Vectorscope Mapping Camera")
        created.append(camera_data)
        camera_data.type = "ORTHO"
        camera_data.ortho_scale = 2.0
        camera = bpy.data.objects.new(camera_data.name, camera_data)
        created.append(camera)
        scene.collection.objects.link(camera)
        camera.location = (0.0, 0.0, 2.0)
        scene.camera = camera

        mesh = bpy.data.meshes.new("PG Vectorscope Mapping Plane")
        created.append(mesh)
        aspect = height / width
        mesh.from_pydata(((-1.0, -aspect, 0.0), (1.0, -aspect, 0.0),
                          (1.0, aspect, 0.0), (-1.0, aspect, 0.0)), (), ((0, 1, 2, 3),))
        uv = mesh.uv_layers.new(name="PG Vectorscope UV")
        for item, value in zip(uv.data, ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0))):
            item.uv = value
        obj = bpy.data.objects.new("PG Vectorscope Mapping Plane", mesh)
        created.append(obj)
        scene.collection.objects.link(obj)

        source = bpy.data.images.new("PG Vectorscope Mapping Source", width=width,
                                     height=height, alpha=True, float_buffer=True)
        created.append(source)
        source.colorspace_settings.name = "Non-Color"
        source.alpha_mode = "CHANNEL_PACKED"
        source.use_half_precision = False
        source.pixels.foreach_set(rgba.reshape(-1))
        source.update()

        material = bpy.data.materials.new("PG Vectorscope Mapping Material")
        created.append(material)
        material.use_nodes = True
        tree = material.node_tree
        tree.nodes.clear()
        mapped_output, alpha_low = _map_shader_tree(tree, source, matrix, limit, size)
        emission = tree.nodes.new("ShaderNodeEmission")
        material_output = tree.nodes.new("ShaderNodeOutputMaterial")
        tree.links.new(mapped_output, emission.inputs["Color"])
        tree.links.new(emission.outputs[0], material_output.inputs["Surface"])
        obj.data.materials.append(material)

        view_layer = scene.view_layers[0]
        color_aov, alpha_aov = "PGVectorscopeBins", "PGVectorscopeAlphaLow"
        capture._aov(view_layer, tree, color_aov, mapped_output)
        capture._aov(view_layer, tree, alpha_aov, alpha_low, value=True)
        view_layer.update_render_passes()

        compositor = bpy.data.node_groups.new("PG Vectorscope Mapping Output", "CompositorNodeTree")
        created.append(compositor)
        render_layers = compositor.nodes.new("CompositorNodeRLayers")
        render_layers.scene = scene
        render_layers.layer = view_layer.name
        color_pass = render_layers.outputs.get(color_aov)
        alpha_pass = render_layers.outputs.get(alpha_aov)
        if color_pass is None or alpha_pass is None:
            raise RuntimeError("Shader-tree vectorscope mapping AOVs are unavailable")
        capture._root_output(compositor, color_pass)
        capture._install_tree(scene, compositor)

        with tempfile.TemporaryDirectory(prefix="pg-vectorscope-map-") as directory:
            for prefix, socket in (("bins_", color_pass), ("alpha_", alpha_pass)):
                output, item = capture._output_node(compositor, directory, prefix)
                compositor.links.new(socket, output.inputs[item.name])

            result = _render_scene(bpy, scene)
            if "FINISHED" not in result:
                raise RuntimeError("Shader-tree vectorscope mapping render did not finish")
            color_files = tuple(Path(directory).glob("bins_*.exr"))
            alpha_files = tuple(Path(directory).glob("alpha_*.exr"))
            if len(color_files) != 1 or len(alpha_files) != 1:
                raise RuntimeError("Shader-tree vectorscope mapping did not write both AOVs")
            mapped = capture._read_image(color_files[0], (width, height))
            alpha_low = capture._read_image(alpha_files[0], (width, height))[..., 0]
        mapped[..., 2] = (mapped[..., 2] + alpha_low / 1024.0) / 1024.0
        mapped[..., 3] = 0.0
        return mapped
    finally:
        bpy.data.batch_remove(ids=created)


def _mapping_input(rgba, rec709_matrix, size, limit):
    values = np.asarray(rgba, dtype=np.float32)
    if values.ndim != 3 or values.shape[-1] != 4 or min(values.shape[:2]) < 1:
        raise ValueError("Shader-tree vectorscope reducer requires nonempty RGBA pixels")
    matrix = np.asarray(rec709_matrix, dtype=np.float64)
    if matrix.shape != (3, 3) or not np.isfinite(matrix).all():
        raise ValueError("Shader-tree vectorscope reducer matrix must be finite and 3 by 3")
    if type(size) is not int or size < 1 or not np.isfinite(limit) or limit <= 0.0:
        raise ValueError("Shader-tree vectorscope reducer has invalid histogram bounds")

    values = values.copy(order="C")
    values[~np.isfinite(values).all(axis=-1)] = 0.0
    return values, matrix


def shader_reducer(rgba, rec709_matrix, *, capture, size=144, limit=0.65):
    """Map samples through a temporary Shader Node Tree and add their bins on GPU."""
    import bpy
    from .vectorscope_gpu import GPUHistogram

    before = _temporary_id_snapshot(bpy)
    started = time.perf_counter_ns()
    values, matrix = _mapping_input(rgba, rec709_matrix, size, limit)
    mapped = _render_mapped_pixels(bpy, capture, values, matrix, limit, size)
    mapping_ms = (time.perf_counter_ns() - started) / 1e6
    clean = _temporary_id_snapshot(bpy) == before
    gpu = GPUHistogram(size=size, limit=limit)
    histogram, timing = gpu.accumulate_timed(mapped)
    timing = {**timing, "mapping_ms": mapping_ms, "temporary_ids_clean": clean}
    return histogram, timing


def verify_failure_cleanup(rgba, rec709_matrix, *, capture, size=144, limit=0.65):
    """Inject a failure immediately before rendering and verify temporary IDs are removed."""
    from unittest.mock import patch

    import bpy

    values, matrix = _mapping_input(rgba, rec709_matrix, size, limit)
    before = _temporary_id_snapshot(bpy)
    failure = RuntimeError("injected vectorscope render failure")
    with patch(__name__ + "._render_scene", side_effect=failure):
        try:
            _render_mapped_pixels(bpy, capture, values, matrix, limit, size)
        except RuntimeError as error:
            if error is not failure:
                raise
        else:
            raise AssertionError("Shader-tree mapping did not observe the injected render failure")
    return {"failure_injected": True, "temporary_ids_clean": _temporary_id_snapshot(bpy) == before}


__all__ = ("shader_reducer", "verify_failure_cleanup")
