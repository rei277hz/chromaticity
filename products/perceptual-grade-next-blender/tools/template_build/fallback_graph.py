"""Build-only pending and fail-closed fallback node groups."""

from ..kernel.node_templates import TREE_TYPES


def build_fallback_group(mode, tree_type, *, vector=False, name=None):
    """Emit one fixed fallback topology for the requested public interface."""
    import bpy

    if mode not in {"pending", "error"} or tree_type not in TREE_TYPES:
        raise ValueError("Unsupported fallback template context")
    if tree_type == "CompositorNodeTree" and vector:
        raise ValueError("Compositor fallback cannot expose Vector")

    tree = bpy.data.node_groups.new(
        name or f"PG Template {mode.title()} {tree_type.removesuffix('NodeTree')}",
        tree_type,
    )
    color_input = tree.interface.new_socket(
        name="Color", in_out="INPUT", socket_type="NodeSocketColor",
    )
    color_output = tree.interface.new_socket(
        name="Color", in_out="OUTPUT", socket_type="NodeSocketColor",
    )
    alpha_input = alpha_output = None
    if tree_type == "ShaderNodeTree":
        alpha_input = tree.interface.new_socket(
            name="Alpha", in_out="INPUT", socket_type="NodeSocketFloat",
        )
        alpha_input.default_value = 1.0
        alpha_output = tree.interface.new_socket(
            name="Alpha", in_out="OUTPUT", socket_type="NodeSocketFloat",
        )
        if vector:
            tree.interface.new_socket(
                name="Vector", in_out="INPUT", socket_type="NodeSocketVector",
            )

    source = tree.nodes.new("NodeGroupInput")
    output = tree.nodes.new("NodeGroupOutput")
    output.is_active_output = True
    if mode == "pending":
        tree.links.new(source.outputs[color_input.name], output.inputs[color_output.name])
    elif tree_type == "ShaderNodeTree":
        magenta = tree.nodes.new("ShaderNodeCombineColor")
        magenta.mode = "RGB"
        magenta.inputs["Red"].default_value = 1.0
        magenta.inputs["Green"].default_value = 0.0
        magenta.inputs["Blue"].default_value = 1.0
        tree.links.new(magenta.outputs["Color"], output.inputs[color_output.name])
        tree.links.new(source.outputs[alpha_input.name], output.inputs[alpha_output.name])
    else:
        separate = tree.nodes.new("CompositorNodeSeparateColor")
        separate.mode = "RGB"
        tree.links.new(source.outputs[color_input.name], separate.inputs["Image"])
        magenta = tree.nodes.new("CompositorNodeCombineColor")
        magenta.mode = "RGB"
        magenta.inputs["Red"].default_value = 1.0
        magenta.inputs["Green"].default_value = 0.0
        magenta.inputs["Blue"].default_value = 1.0
        restore = tree.nodes.new("CompositorNodeSetAlpha")
        restore.inputs["Type"].default_value = "Replace Alpha"
        tree.links.new(magenta.outputs["Image"], restore.inputs["Image"])
        tree.links.new(separate.outputs["Alpha"], restore.inputs["Alpha"])
        tree.links.new(restore.outputs["Image"], output.inputs[color_output.name])
    if mode == "pending" and tree_type == "ShaderNodeTree":
        tree.links.new(source.outputs[alpha_input.name], output.inputs[alpha_output.name])
    tree["_pg_template_mode"] = mode
    tree["_pg_template_vector"] = bool(vector)
    return tree


__all__ = ("build_fallback_group",)
