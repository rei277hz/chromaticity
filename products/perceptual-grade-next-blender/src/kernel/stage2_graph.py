"""Complete immutable Linear/Tone kernels with guarded scene-RGB output."""

from .graph import Graph, BuiltGrade, TREE_TYPES, count_nodes


def build_stage2_group(prepared, tree_type="ShaderNodeTree", *,
                       name="Perceptual Grade", diagnostics=False):
    """Build every Tone and guard path, including an exact reset's paths."""
    if tree_type not in TREE_TYPES:
        raise ValueError("Grade nodes require a Shader or Compositor tree")
    if prepared.table is None or prepared.boundary is None:
        raise ValueError("Stage 2 requires a complete Tone table and boundary")
    if prepared.color.active:
        raise ValueError("Stage 2 does not support Color adjustments")
    import bpy

    tree = bpy.data.node_groups.new(name, tree_type)
    graph = Graph(tree, prepared)
    try:
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
        appearance = graph.encode_cones(graph.matrix(
            source.outputs["Color"], prepared.linear_to_cones,
        ))
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
