"""Build-only bake wrapper topology with a placeholder live interface."""

WRAPPER = "_pg_next_bake_wrapper"
LIVE = "_pg_next_bake_live"
READER = "_pg_next_bake_reader"
SELECTOR = "_pg_next_bake_selector"
UV = "_pg_next_bake_uv"
SCHEMA = "_pg_next_bake_schema"
DOMAIN = "_pg_next_bake_domain"
SIGNATURE = "_pg_next_bake_signature"
OPERATION = "_pg_next_bake_operation"
CONTEXT = "_pg_next_bake_context"


def build_wrapper_group(tree_type):
    import bpy

    if tree_type not in ("ShaderNodeTree", "CompositorNodeTree"):
        raise ValueError("Bake wrapper requires a Shader or Compositor tree")
    kernel = bpy.data.node_groups.new("Perceptual Grade Template Live", tree_type)
    for direction in ("INPUT", "OUTPUT"):
        kernel.interface.new_socket(name="Color", in_out=direction, socket_type="NodeSocketColor")
        if tree_type == "ShaderNodeTree":
            kernel.interface.new_socket(name="Alpha", in_out=direction, socket_type="NodeSocketFloat")
    shader = tree_type == "ShaderNodeTree"
    tree = bpy.data.node_groups.new("Perceptual Grade Bake Wrapper", tree_type)
    try:
        tree[WRAPPER] = 1
        tree.interface.new_socket(name="Color", in_out="INPUT", socket_type="NodeSocketColor")
        if shader:
            tree.interface.new_socket(name="Alpha", in_out="INPUT", socket_type="NodeSocketFloat").default_value = 1.0
            tree.interface.new_socket(name="Vector", in_out="INPUT", socket_type="NodeSocketVector")
        tree.interface.new_socket(name="Color", in_out="OUTPUT", socket_type="NodeSocketColor")
        if shader:
            tree.interface.new_socket(name="Alpha", in_out="OUTPUT", socket_type="NodeSocketFloat")
        source = tree.nodes.new("NodeGroupInput")
        output = tree.nodes.new("NodeGroupOutput")
        output.is_active_output = True
        live = tree.nodes.new("ShaderNodeGroup" if shader else "CompositorNodeGroup")
        live[LIVE] = True
        live.node_tree = kernel
        tree.links.new(source.outputs["Color"], live.inputs["Color"])
        reader = tree.nodes.new("ShaderNodeTexImage" if shader else "CompositorNodeImage")
        reader[READER] = True
        if shader:
            tree.links.new(source.outputs["Alpha"], live.inputs["Alpha"])
            uv = tree.nodes.new("ShaderNodeUVMap")
            uv[UV] = True
            tree.links.new(uv.outputs["UV"], reader.inputs["Vector"])
            for name in ("Color", "Alpha"):
                selector = tree.nodes.new("ShaderNodeMixRGB")
                selector.blend_type = "MIX"
                selector.use_clamp = False
                selector[SELECTOR] = name
                selector.inputs[0].default_value = 0.0
                tree.links.new(live.outputs[name], selector.inputs[1])
                tree.links.new(reader.outputs[name], selector.inputs[2])
                tree.links.new(selector.outputs[0], output.inputs[name])
        else:
            selector = tree.nodes.new("CompositorNodeSwitch")
            selector[SELECTOR] = "Color"
            selector.inputs["Switch"].default_value = False
            tree.links.new(live.outputs["Color"], selector.inputs["Off"])
            tree.links.new(reader.outputs["Image"], selector.inputs["On"])
            tree.links.new(selector.outputs["Image"], output.inputs["Color"])
        return tree
    except BaseException:
        bpy.data.node_groups.remove(tree, do_unlink=True)
        bpy.data.node_groups.remove(kernel, do_unlink=True)
        raise


