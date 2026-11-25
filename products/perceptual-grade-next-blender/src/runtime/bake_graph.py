"""Private native readers composed around shared, authoritative live kernels.

Callers consume bake/node policy effects before invoking any mutation here.
The live kernel is never copied or modified to store a node's bake selection.
"""

# pg-book: technical-report/en#next-policy.bake

from .effective_grade_graph import (
    DOMAIN, LIVE, OPERATION, READER, SCHEMA, SELECTOR, UV, WRAPPER, live_tree,
    marked, wrapper_structure_valid as structure_valid,
)

SIGNATURE = "_pg_next_bake_signature"
CONTEXT = "_pg_next_bake_context"


def eligible(node):
    return getattr(node, "bl_idname", None) in {
        "PGShaderGrade", "PGCompositorGrade",
        "PGShaderGradeStack", "PGCompositorGradeStack",
    }


def image_allowed(node, image):
    if image is None:
        return True
    try:
        return (image.library is None and image.get(SCHEMA) == 2
                and image.source in {"FILE", "GENERATED"} and image.is_float
                and image.packed_file is not None and not image.is_dirty
                and image.get(DOMAIN) in {"EMPTY", "IMAGE", "UV", "COMPOSITOR"}
                and (node.id_data.bl_idname == "ShaderNodeTree"
                     or image.get(DOMAIN) != "UV"))
    except (AttributeError, ReferenceError, RuntimeError):
        return False


def image_valid(node, image):
    try:
        return (image is not None and image_allowed(node, image)
                and image.colorspace_settings.name == "Non-Color"
                and image.alpha_mode == "CHANNEL_PACKED"
                and not getattr(image, "use_half_precision", False)
                and image.get(DOMAIN) != "EMPTY" and image.get(OPERATION) is not None
                and tuple(image.size) == (image.get("_pg_next_bake_width"),
                                          image.get("_pg_next_bake_height")))
    except (AttributeError, ReferenceError, RuntimeError, TypeError):
        return False


def build(node, kernel, *, retire=None):
    from ..kernel.node_templates import instantiate_wrapper

    return instantiate_wrapper(node.id_data.bl_idname, kernel, retire=retire)


def synchronize(node, *, use_bake):
    """Reconcile a reader and report whether its native output selection changed."""
    tree = node.node_tree
    if tree is None or tree.get(WRAPPER) != 1:
        if use_bake:
            raise RuntimeError("Baked output has no private wrapper")
        return False
    reader = marked(tree, READER)
    live = marked(tree, LIVE)
    selectors = tuple(item for item in tree.nodes if item.get(SELECTOR))
    shader = tree.bl_idname == "ShaderNodeTree"
    if reader is None or live is None or live.node_tree is None or len(selectors) != (2 if shader else 1):
        raise RuntimeError("Bake wrapper is incomplete")
    image = node.pg_bake_image
    if reader.image != image:
        reader.image = image
    selection_changed = False
    for selector in selectors:
        socket = selector.inputs[0] if shader else selector.inputs["Switch"]
        value = float(use_bake) if shader else bool(use_bake)
        if socket.default_value != value:
            socket.default_value = value
            selection_changed = True
    if shader:
        uv = marked(tree, UV)
        if uv is None:
            raise RuntimeError("Bake wrapper UV fallback is missing")
        uv_name = str(image.get("_pg_next_bake_uv_map", "")) if image is not None else ""
        if uv.uv_map != uv_name:
            uv.uv_map = uv_name
        source = next(item for item in tree.nodes if item.bl_idname == "NodeGroupInput")
        vector = node.inputs.get("Vector")
        target = source.outputs["Vector"] if vector is not None and vector.is_linked else uv.outputs["UV"]
        links = tuple(reader.inputs["Vector"].links)
        if len(links) != 1 or links[0].from_socket != target:
            tree.links.new(target, reader.inputs["Vector"])
        interpolation = str(image.get("_pg_next_bake_interpolation", "Linear")) if image else "Linear"
        extension = str(image.get("_pg_next_bake_extension", "REPEAT")) if image else "REPEAT"
        if reader.interpolation != interpolation:
            reader.interpolation = interpolation
        if reader.extension != extension:
            reader.extension = extension
    return selection_changed


def replace_live(node, kernel):
    """Keep the outer socket identities when publishing a new live kernel."""
    live = marked(node.node_tree, LIVE)
    if live is None:
        raise RuntimeError("Bake wrapper lost its live kernel")
    previous = live.node_tree
    if previous == kernel:
        return previous
    # Native group replacement can drop internal links, just as outer swaps do.
    tree = node.node_tree
    links = tuple((link.from_node, link.from_socket.name, link.to_node, link.to_socket.name)
                  for link in tree.links if link.from_node == live or link.to_node == live)
    def install(value):
        live.node_tree = value
        for origin, output, target, input_name in links:
            tree.links.new(origin.outputs[output], target.inputs[input_name])
    try:
        install(kernel)
    except BaseException:
        install(previous)
        raise
    return previous
