"""Blender installation adapter for the static Next Stack LUT.

The graph owns the accepted packed resources, while the portable ``StackLUT``
is the only bake evaluator.  The 33^3 image is retained for interactive
quality/progress metadata and is never connected as final or bake output.
"""

from dataclasses import dataclass
import json

import numpy as np

from .stack import (
    FINAL_EVALUATOR,
    StackDatablock,
    StackPreparation,
    prepare_stack,
    refine_stack,
)
from ..perceptual_grade_next_core.model.lut import KAPPA, LOG_RANGE, MAXIMUM, MINIMUM, basis


STACK_BACKEND = "native_stack_lut"
STACK_SCHEMA = 1


@dataclass(frozen=True)
class NativeStack:
    tree: object
    datablock: StackDatablock
    preparation: StackPreparation
    tree_type: str

    @property
    def images(self):
        import bpy

        names = {
            self.tree.get("perceptual_grade_next_stack_preview_resource", ""),
            self.tree.get("perceptual_grade_next_stack_final_resource", ""),
        }
        return tuple(image for image in bpy.data.images if image.name in names)

    @property
    def final_ready(self):
        return self.datablock.final_ready

    @property
    def bake_evaluator(self):
        return self.datablock.bake_evaluator

    def dispose(self, *, unlink=True):
        import bpy

        if self.tree is not None and unlink and self.tree.users == 0:
            images = self.images
            bpy.data.node_groups.remove(self.tree, do_unlink=True)
            for image in images:
                if image.users == 0:
                    bpy.data.images.remove(image, do_unlink=True)


def _interface(tree, name, in_out, socket_type):
    socket = tree.interface.new_socket(name=name, in_out=in_out, socket_type=socket_type)
    if socket_type == "NodeSocketFloat":
        socket.default_value = 1.0
    return socket


def _make_group_tree(tree_type, name):
    import bpy

    tree = bpy.data.node_groups.new(name, tree_type)
    _interface(tree, "Color", "INPUT", "NodeSocketColor")
    _interface(tree, "Color", "OUTPUT", "NodeSocketColor")
    if tree_type == "ShaderNodeTree":
        _interface(tree, "Alpha", "INPUT", "NodeSocketFloat")
        _interface(tree, "Alpha", "OUTPUT", "NodeSocketFloat")
    return tree


def _connect_final_image(tree, image, recipe, *, size=65, role="final"):
    """Install tetrahedral sampling with the same shaper and endpoint matrices."""
    to_lut, from_lut = basis(recipe.working_space)
    input_matrix = np.asarray(recipe.input_matrix) @ to_lut
    output_matrix = from_lut @ np.asarray(recipe.output_matrix)
    shader = tree.bl_idname == "ShaderNodeTree"

    class Graph:
        def __init__(self):
            self.nodes = tree.nodes
            self.links = tree.links
            self.cache = {}

        def math(self, operation, a, b=None):
            key = (operation, self.key(a), self.key(b))
            if key in self.cache:
                return self.cache[key]
            # Blender 5.2's new compositor tree removed CompositorNodeMath;
            # ShaderNodeMath is accepted by both trees and shares these ops.
            node = self.nodes.new("ShaderNodeMath")
            node.operation = operation
            node.use_clamp = False
            node.hide = True
            for index, value in enumerate((a, b)):
                if index == 1 and b is None:
                    continue
                socket = node.inputs[index]
                if hasattr(value, "node"):
                    self.links.new(value, socket)
                else:
                    socket.default_value = float(value)
            self.cache[key] = node.outputs[0]
            return node.outputs[0]

        @staticmethod
        def key(value):
            if value is None:
                return None
            return value.as_pointer() if hasattr(value, "as_pointer") else float(value)

        def vec(self, values):
            node = self.nodes.new("ShaderNodeCombineXYZ" if shader else "CompositorNodeCombineColor")
            if not shader:
                node.mode = "RGB"
            names = ("X", "Y", "Z") if shader else ("Red", "Green", "Blue")
            for value, name in zip(values, names):
                socket = node.inputs[name]
                if hasattr(value, "node"):
                    self.links.new(value, socket)
                else:
                    socket.default_value = float(value)
            node.hide = True
            return node.outputs[0] if shader else node.outputs["Image"]

        def split(self, value):
            node = self.nodes.new("ShaderNodeSeparateXYZ" if shader else "CompositorNodeSeparateColor")
            if not shader:
                node.mode = "RGB"
                self.links.new(value, node.inputs["Image"])
                return tuple(node.outputs[name] for name in ("Red", "Green", "Blue"))
            self.links.new(value, node.inputs[0])
            return tuple(node.outputs)

        def matrix(self, value, matrix):
            parts = self.split(value)
            rows = []
            for row in matrix:
                terms = [self.math("MULTIPLY", channel, coefficient)
                         for channel, coefficient in zip(parts, row)]
                rows.append(self.math("ADD", self.math("ADD", terms[0], terms[1]), terms[2]))
            return self.vec(rows)

        def clamp(self, value, low, high):
            return self.math("MINIMUM", self.math("MAXIMUM", value, low), high)

        def add(self, a, b): return self.math("ADD", a, b)
        def sub(self, a, b): return self.math("SUBTRACT", a, b)
        def mul(self, a, b): return self.math("MULTIPLY", a, b)
        def div(self, a, b): return self.math("DIVIDE", a, b)
        def maximum(self, a, b): return self.math("MAXIMUM", a, b)
        def minimum(self, a, b): return self.math("MINIMUM", a, b)
        def lt(self, a, b): return self.math("LESS_THAN", a, b)
        def gt(self, a, b): return self.math("GREATER_THAN", a, b)

    source = tree.nodes.new("NodeGroupInput")
    output = tree.nodes.new("NodeGroupOutput")
    output.is_active_output = True
    g = Graph()
    rgb = g.matrix(source.outputs["Color"], input_matrix)
    r, green, blue = g.split(rgb)
    magnitude = g.maximum(g.math("ABSOLUTE", r),
                          g.maximum(g.math("ABSOLUTE", green), g.math("ABSOLUTE", blue)))
    safe_magnitude = g.maximum(magnitude, 1e-30)
    unit = tuple(g.div(channel, safe_magnitude) for channel in (r, green, blue))
    weights = (0.2722287168, 0.6740817658, 0.0536895174)
    luminance = g.maximum(0.0, g.add(g.add(g.mul(unit[0], weights[0]),
                                           g.mul(unit[1], weights[1])),
                                     g.mul(unit[2], weights[2])))
    offset = g.maximum(0.0, g.math("SUBTRACT", 0.0,
                                  g.minimum(unit[0], g.minimum(unit[1], unit[2]))))
    repair_scale = g.div(luminance, g.maximum(g.add(luminance, offset), 1e-30))
    lifted = tuple(g.mul(g.add(value, offset), repair_scale) for value in unit)
    peak = g.maximum(lifted[0], g.maximum(lifted[1], lifted[2]))
    factor = g.minimum(magnitude, g.div(MAXIMUM, g.maximum(peak, 1e-30)))
    candidate = tuple(g.mul(value, factor) for value in lifted)
    outside = g.maximum(
        g.maximum(g.math("SUBTRACT", 0.0, r), 0.0),
        g.maximum(g.maximum(g.math("SUBTRACT", 0.0, green), 0.0),
                  g.maximum(g.math("SUBTRACT", 0.0, blue), 0.0)),
    )
    for channel in (r, green, blue):
        outside = g.maximum(outside, g.maximum(g.math("SUBTRACT", channel, MAXIMUM), 0.0))
    repair = g.gt(outside, 0.0)
    repaired_parts = tuple(
        g.add(g.mul(candidate_value, repair), g.mul(original, g.sub(1.0, repair)))
        for candidate_value, original in zip(candidate, (r, green, blue))
    )

    # Address each channel on the fixed 65-point log1p axis.
    cell, fractions = [], []
    for channel in repaired_parts:
        bounded = g.clamp(channel, MINIMUM, MAXIMUM)
        encoded = g.div(g.math("LOGARITHM", g.add(1.0, g.div(bounded, KAPPA)), 2.718281828459045), LOG_RANGE)
        position = g.mul(size - 1, encoded)
        lower = g.clamp(g.math("FLOOR", position), 0.0, size - 2)
        exponential = g.math("POWER", 2.718281828459045, g.mul(lower, LOG_RANGE / (size - 1)))
        lo = g.mul(KAPPA, g.sub(exponential, 1.0))
        hi = g.mul(KAPPA, g.sub(g.mul(exponential, 2.718281828459045 ** (LOG_RANGE / (size - 1))), 1.0))
        fraction = g.clamp(g.div(g.sub(channel, lo), g.maximum(g.sub(hi, lo), 1e-30)), 0.0, 1.0)
        cell.append(lower)
        fractions.append(fraction)
    x, y, z = fractions
    ge = lambda a, b: g.sub(1.0, g.lt(a, b))
    high = (g.mul(ge(x, y), ge(x, z)), g.mul(g.lt(x, y), ge(y, z)), g.mul(g.lt(x, z), g.lt(y, z)))
    low = (g.mul(g.lt(x, y), g.lt(x, z)), g.mul(ge(x, y), g.lt(y, z)), g.mul(ge(x, z), ge(y, z)))
    strides = (size * size, size, 1)
    base = g.add(g.add(g.mul(cell[0], strides[0]), g.mul(cell[1], strides[1])), cell[2])
    first = g.add(g.add(g.mul(high[0], strides[0]), g.mul(high[1], strides[1])), g.mul(high[2], strides[2]))
    last = g.add(g.add(g.mul(low[0], strides[0]), g.mul(low[1], strides[1])), g.mul(low[2], strides[2]))
    diagonal = size * size + size + 1
    indices = (base, g.add(base, first), g.sub(g.add(base, diagonal), last), g.add(base, diagonal))
    maximum = g.maximum(x, g.maximum(y, z))
    minimum = g.minimum(x, g.minimum(y, z))
    middle = g.minimum(g.maximum(x, y), g.maximum(g.minimum(x, y), z))
    interpolation = (maximum, g.sub(maximum, middle), g.sub(middle, minimum), minimum)
    samples = []
    for index in indices:
        row = g.math("FLOOR", g.div(index, size * size))
        column = g.sub(index, g.mul(row, size * size))
        uv = g.vec((g.div(g.add(column, 0.5), size * size), g.div(g.add(row, 0.5), size), 0.0))
        if shader:
            texture = tree.nodes.new("ShaderNodeTexImage")
            texture.interpolation = "Closest"
            texture.extension = "EXTEND"
            texture.image = image
            texture.hide = True
            tree.links.new(uv, texture.inputs["Vector"])
            samples.append(g.split(texture.outputs["Color"]))
        else:
            texture = tree.nodes.new("CompositorNodeImage")
            texture.image = image
            texture.hide = True
            sample = tree.nodes.new("CompositorNodeMapUV")
            sample.inputs["Interpolation"].default_value = "Nearest"
            sample.inputs["Extension X"].default_value = "Extend"
            sample.inputs["Extension Y"].default_value = "Extend"
            tree.links.new(texture.outputs["Image"], sample.inputs["Image"])
            tree.links.new(uv, sample.inputs["UV"])
            samples.append(g.split(sample.outputs["Image"]))
        texture[f"perceptual_grade_next_stack_{role}_lookup"] = True
    output_parts = []
    for channel in range(3):
        result = g.add(g.add(g.add(g.mul(samples[0][channel], g.sub(1.0, interpolation[0])),
                                   g.mul(samples[1][channel], interpolation[1])),
                             g.mul(samples[2][channel], interpolation[2])),
                       g.mul(samples[3][channel], interpolation[3]))
        output_parts.append(result)
    looked_up = g.matrix(g.vec(output_parts), output_matrix)
    if shader:
        tree.links.new(looked_up, output.inputs["Color"])
        tree.links.new(source.outputs["Alpha"], output.inputs["Alpha"])
    else:
        source_channels = tree.nodes.new("CompositorNodeSeparateColor")
        source_channels.mode = "RGB"
        tree.links.new(source.outputs["Color"], source_channels.inputs["Image"])
        output_channels = tree.nodes.new("CompositorNodeSeparateColor")
        output_channels.mode = "RGB"
        tree.links.new(looked_up, output_channels.inputs["Image"])
        combined = tree.nodes.new("CompositorNodeCombineColor")
        combined.mode = "RGB"
        for name, value in zip(("Red", "Green", "Blue"), output_channels.outputs):
            tree.links.new(value, combined.inputs[name])
        tree.links.new(source_channels.outputs["Alpha"], combined.inputs["Alpha"])
        tree.links.new(combined.outputs["Image"], output.inputs["Color"])
    return texture


def build_native_stack(settings=None, *, preparation=None, final=True, tree_type="ShaderNodeTree", name="Perceptual Grade Stack Next", block_size=4096, checkpoint=None):
    """Install a 33^3 preview or complete 65^3 Stack owner."""
    if tree_type not in {"ShaderNodeTree", "CompositorNodeTree"}:
        raise ValueError("Next Stack requires a ShaderNodeTree or CompositorNodeTree")
    if preparation is None:
        preparation = prepare_stack(settings, block_size=block_size, checkpoint=checkpoint)
        if final:
            preparation = refine_stack(preparation, block_size=block_size, checkpoint=checkpoint)
    elif settings is not None and preparation.settings != settings:
        raise ValueError("Prepared Stack candidate does not match authored settings")
    if final and not preparation.final_ready:
        raise ValueError("Final Stack installation requires the accepted 65^3 LUT")
    import bpy

    tree = _make_group_tree(tree_type, name)
    try:
        datablock = StackDatablock(tree, preparation)
        if preparation.final_ready:
            role, size = "final", 65
            image_name = tree.get("perceptual_grade_next_stack_final_resource", "")
        else:
            role, size = "preview", 33
            image_name = tree.get("perceptual_grade_next_stack_preview_resource", "")
        image = bpy.data.images.get(image_name)
        if image is None:
            raise RuntimeError(f"Persistent Stack {role} image is missing")
        _connect_final_image(tree, image, preparation.recipe, size=size, role=role)
        tree["perceptual_grade_next_backend"] = STACK_BACKEND
        tree["perceptual_grade_next_stack_schema"] = STACK_SCHEMA
        tree["perceptual_grade_next_stack_quality_tier"] = (
            "65^3" if preparation.final_ready else "33^3-preview"
        )
        tree["perceptual_grade_next_stack_has_preview_transform"] = True
        tree["perceptual_grade_next_stack_bake_evaluator"] = (
            FINAL_EVALUATOR if preparation.final_ready else ""
        )
        tree["perceptual_grade_next_stack_manifest"] = json.dumps(
            preparation.metadata(), sort_keys=True, separators=(",", ":")
        )
        datablock.validate_persistent()
        from .project_readiness import STACK_GRAPH_MANIFEST_KEY, _stack_content_id
        content_id = _stack_content_id(tree)
        tree[STACK_GRAPH_MANIFEST_KEY] = content_id
        if tree.get(STACK_GRAPH_MANIFEST_KEY) != content_id:
            raise RuntimeError("Stack evaluator content manifest did not persist")
        return NativeStack(tree, datablock, preparation, tree_type)
    except BaseException:
        if tree.users == 0:
            bpy.data.node_groups.remove(tree, do_unlink=True)
        raise


__all__ = ("NativeStack", "STACK_BACKEND", "STACK_SCHEMA", "build_native_stack")
