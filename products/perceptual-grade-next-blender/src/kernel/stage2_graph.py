"""Complete fixed Linear/Tone graphs driven by one small parameter image."""

from types import SimpleNamespace

from .graph import Graph, BuiltGrade, TREE_TYPES, count_nodes
from .stage2_parameters import (
    MATRIX_RED_SLOT, MATRIX_BLUE_SLOT, MATRIX_NEUTRAL_SLOT,
    TONE_SCALARS_SLOT, TONE_DOMAIN_SLOT, PARAMETER_SCHEMA, PARAMETER_SHAPE,
    prepare_parameters,
)


PARAMETER_IMAGE = "_perceptual_grade_parameter_schema"
PARAMETER_BINDING = "_perceptual_grade_parameter_image"


class ParameterBindings:
    """Compose fixed texel reads with Graph; no update edits any socket."""

    def __init__(self, graph, parameters, image=None):
        self.graph = graph
        if image is None:
            image = graph._packed_image(
                parameters.pixels, key="stage2_parameters",
                label="Perceptual Grade tone and linear parameters",
            )
            image[PARAMETER_IMAGE] = PARAMETER_SCHEMA
        else:
            if (image.get(PARAMETER_IMAGE) != PARAMETER_SCHEMA
                    or tuple(image.size) != (PARAMETER_SHAPE[1], PARAMETER_SHAPE[0])):
                raise ValueError("Invalid shared Stage 2 parameter image")
            graph.images.append(image)
        self.image = image
        scalars, high = self.sample(TONE_SCALARS_SLOT)
        black, span, slope = graph.split(scalars)
        self.tone = SimpleNamespace(active=True, black=black, span=span,
                                    slope=slope, high=high)
        self.domain = graph.split(self.sample(TONE_DOMAIN_SLOT)[0])[0]

    def sample(self, slot):
        graph = self.graph
        uv = ((slot + .5) / PARAMETER_SHAPE[1], .5, 1.)
        if graph.tree.bl_idname == "ShaderNodeTree":
            return graph._sample_shader_uv(
                self.image, graph.vector(uv), "Closest", "Grade parameters"
            )
        key = ('coefficient_image', self.image.as_pointer())
        source = graph.cache.get(key)
        if source is None:
            source = graph.node("CompositorNodeImage", "Grade parameters")
            source.image = self.image
            graph.cache[key] = source
        sample = graph.node("CompositorNodeMapUV", "Grade parameter texel")
        sample.inputs["Interpolation"].default_value = "Nearest"
        sample.inputs["Extension X"].default_value = "Extend"
        sample.inputs["Extension Y"].default_value = "Extend"
        graph.connect(source.outputs["Image"], sample.inputs["Image"])
        graph.connect(uv, sample.inputs["UV"])
        separate = graph.node("CompositorNodeSeparateColor", "Grade parameter channels")
        separate.mode = "RGB"
        graph.connect(sample.outputs["Image"], separate.inputs["Image"])
        return sample.outputs["Image"], separate.outputs["Alpha"]

    def matrix(self, rgb):
        graph = self.graph
        red, green, blue = graph.split(rgb)
        red_delta = graph.vscale(self.sample(MATRIX_RED_SLOT)[0], graph.sub(red, green))
        blue_delta = graph.vscale(self.sample(MATRIX_BLUE_SLOT)[0], graph.sub(blue, green))
        neutral = graph.vscale(self.sample(MATRIX_NEUTRAL_SLOT)[0], green)
        return graph.vadd(graph.vadd(red_delta, blue_delta), neutral)


def build_stage2_group(prepared, tree_type="ShaderNodeTree", *,
                       name="Perceptual Grade", diagnostics=False, parameter_image=None):
    """Build every Tone and guard path, including an exact reset's paths."""
    if tree_type not in TREE_TYPES:
        raise ValueError("Grade nodes require a Shader or Compositor tree")
    if prepared.table is None or prepared.boundary is None:
        raise ValueError("Stage 2 requires a complete Tone table and boundary")
    if prepared.color.active:
        raise ValueError("Stage 2 does not support Color adjustments")
    parameters = prepared.parameters or prepare_parameters(prepared)
    import bpy

    tree = bpy.data.node_groups.new(name, tree_type)
    graph = Graph(tree, prepared)
    try:
        graph.parameters = ParameterBindings(graph, parameters, parameter_image)
        tree[PARAMETER_BINDING] = graph.parameters.image
        color_input = tree.interface.new_socket(
            name="Color", in_out="INPUT", socket_type="NodeSocketColor",
        )
        color_input.default_value = (0., 0., 0., 1.)
        if tree_type == "ShaderNodeTree":
            tree.interface.new_socket(
                name="Alpha", in_out="INPUT", socket_type="NodeSocketFloat",
            ).default_value = 1.
        tree.interface.new_socket(
            name="Color", in_out="OUTPUT", socket_type="NodeSocketColor",
        )
        if tree_type == "ShaderNodeTree" or diagnostics:
            tree.interface.new_socket(
                name="Alpha", in_out="OUTPUT", socket_type="NodeSocketFloat",
            )
        if diagnostics:
            for socket_name in ("Decode Valid", "Pole Margin", "Saturated"):
                tree.interface.new_socket(
                    name=socket_name, in_out="OUTPUT", socket_type="NodeSocketFloat",
                )

        source = tree.nodes.new("NodeGroupInput")
        output = tree.nodes.new("NodeGroupOutput")
        output.is_active_output = True
        appearance = graph.encode_cones(graph.parameters.matrix(source.outputs["Color"]))
        toned = graph.tone(appearance, force=True)
        decoded = graph.output_guard(graph.hk_guard(graph.guard_input(toned)))
        if tree_type == "ShaderNodeTree":
            color, alpha = decoded.color, source.outputs["Alpha"]
        else:
            separate = graph.node("CompositorNodeSeparateColor")
            separate.mode = "RGB"
            graph.connect(source.outputs["Color"], separate.inputs["Image"])
            alpha = separate.outputs["Alpha"]
            restore = graph.node("CompositorNodeSetAlpha")
            restore.inputs["Type"].default_value = "Replace Alpha"
            graph.connect(decoded.color, restore.inputs["Image"])
            graph.connect(alpha, restore.inputs["Alpha"])
            color = restore.outputs["Image"]
        graph.connect(color, output.inputs["Color"])
        if tree_type == "ShaderNodeTree" or diagnostics:
            graph.connect(alpha, output.inputs["Alpha"])
        if diagnostics:
            for value, socket_name in (
                (decoded.valid, "Decode Valid"),
                (decoded.pole_margin, "Pole Margin"),
                (decoded.saturated, "Saturated"),
            ):
                graph.connect(value, output.inputs[socket_name])
        tree["_perceptual_grade_stage2_complete"] = True
        return BuiltGrade(tree, tuple(graph.images), tuple(graph.helper_groups),
                          prepared, count_nodes(tree, graph.images))
    except BaseException:
        bpy.data.node_groups.remove(tree, do_unlink=True)
        for helper in graph.helper_groups:
            if helper.users == 0:
                bpy.data.node_groups.remove(helper)
        for image in graph.images:
            if image.users == 0:
                bpy.data.images.remove(image)
        raise
