"""Build-only Stack graph emitter used by the Buck template generator."""

from .graph import Graph
from .lut_graph import append_lut_lookup


def build_stack_group(prepared, tree_type, *, name="Perceptual Grade Stack"):
    """Emit one Stack topology; runtime uses the generated template instead."""
    import bpy

    if tree_type not in ("ShaderNodeTree", "CompositorNodeTree"):
        raise ValueError("Grade Stack nodes require a Shader or Compositor tree")
    tree = bpy.data.node_groups.new(name, tree_type)
    graph = Graph(tree, None)
    try:
        color_input = tree.interface.new_socket(
            name="Color", in_out="INPUT", socket_type="NodeSocketColor")
        color_output = tree.interface.new_socket(
            name="Color", in_out="OUTPUT", socket_type="NodeSocketColor")
        alpha_input = alpha_output = None
        if tree_type == "ShaderNodeTree":
            alpha_input = tree.interface.new_socket(
                name="Alpha", in_out="INPUT", socket_type="NodeSocketFloat")
            alpha_input.default_value = 1.0
            alpha_output = tree.interface.new_socket(
                name="Alpha", in_out="OUTPUT", socket_type="NodeSocketFloat")
        source = tree.nodes.new("NodeGroupInput")
        output = tree.nodes.new("NodeGroupOutput")
        output.is_active_output = True
        transformed = append_lut_lookup(
            graph, prepared.cube, source.outputs[color_input.name])
        if tree_type == "ShaderNodeTree":
            graph.connect(transformed, output.inputs[color_output.name])
            graph.connect(source.outputs[alpha_input.name], output.inputs[alpha_output.name])
        else:
            separate = graph.node("CompositorNodeSeparateColor")
            separate.mode = "RGB"
            graph.connect(source.outputs[color_input.name], separate.inputs["Image"])
            restore = graph.node("CompositorNodeSetAlpha")
            restore.inputs["Type"].default_value = "Replace Alpha"
            graph.connect(transformed, restore.inputs["Image"])
            graph.connect(separate.outputs["Alpha"], restore.inputs["Alpha"])
            graph.connect(restore.outputs["Image"], output.inputs[color_output.name])
        return tree, tuple(graph.images)
    except BaseException:
        bpy.data.node_groups.remove(tree, do_unlink=True)
        for image in graph.images:
            if image.users == 0:
                bpy.data.images.remove(image)
        raise


__all__ = ("build_stack_group",)

