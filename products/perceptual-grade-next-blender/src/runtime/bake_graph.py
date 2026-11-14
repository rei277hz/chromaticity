"""Private native readers composed around shared, authoritative live kernels.

Callers consume bake/node policy effects before invoking any mutation here.
The live kernel is never copied or modified to store a node's bake selection.
"""

# pg-book: technical-report/en#next-policy.bake

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


def eligible(node):
    return getattr(node, "bl_idname", None) in {
        "PGShaderGrade", "PGCompositorGrade",
        "PGShaderGradeStack", "PGCompositorGradeStack",
    }


def marked(tree, key):
    if tree is None:
        return None
    return next((node for node in tree.nodes if node.get(key)), None)


def live_tree(tree):
    if tree is not None and tree.get(WRAPPER):
        live = marked(tree, LIVE)
        return None if live is None else live.node_tree
    return tree


def image_allowed(node, image):
    if image is None:
        return True
    try:
        return (image.library is None and image.get(SCHEMA) == 1
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


def structure_valid(tree):
    """Check the derived wrapper independently of its embedded live kernel."""
    try:
        if tree is None or tree.get(WRAPPER) != 1:
            return False
        shader = tree.bl_idname == "ShaderNodeTree"
        if not shader and tree.bl_idname != "CompositorNodeTree":
            return False
        def unique(predicate):
            matches = tuple(item for item in tree.nodes if predicate(item))
            if len(matches) != 1:
                raise ValueError("Bake wrapper node is not unique")
            return matches[0]
        source = unique(lambda item: item.bl_idname == "NodeGroupInput")
        output = unique(lambda item: item.bl_idname == "NodeGroupOutput")
        live = unique(lambda item: bool(item.get(LIVE)))
        reader = unique(lambda item: bool(item.get(READER)))
        if (not output.is_active_output or live.node_tree is None
                or live.bl_idname != ("ShaderNodeGroup" if shader else "CompositorNodeGroup")
                or reader.bl_idname != ("ShaderNodeTexImage" if shader else "CompositorNodeImage")
                or any(item.mute for item in tree.nodes)):
            return False
        expected_interface = [
            ("INPUT", "Color", "NodeSocketColor"),
            ("OUTPUT", "Color", "NodeSocketColor"),
        ]
        if shader:
            expected_interface.extend((("INPUT", "Alpha", "NodeSocketFloat"),
                                       ("INPUT", "Vector", "NodeSocketVector"),
                                       ("OUTPUT", "Alpha", "NodeSocketFloat")))
        interface = [(item.in_out, item.name, item.socket_type)
                     for item in tree.interface.items_tree if item.item_type == "SOCKET"]
        if sorted(interface) != sorted(expected_interface):
            return False
        expected = [(source.outputs["Color"], live.inputs["Color"])]
        if shader:
            uv = unique(lambda item: bool(item.get(UV)))
            if (uv.bl_idname != "ShaderNodeUVMap" or getattr(uv, "from_instancer", False)
                    or reader.projection != "FLAT"):
                return False
            expected.append((source.outputs["Alpha"], live.inputs["Alpha"]))
            links = tuple(reader.inputs["Vector"].links)
            if (len(links) != 1 or links[0].from_socket not in
                    (source.outputs["Vector"], uv.outputs["UV"])):
                return False
            expected.append((links[0].from_socket, reader.inputs["Vector"]))
            for name in ("Color", "Alpha"):
                selector = unique(lambda item: item.get(SELECTOR) == name)
                if (selector.bl_idname != "ShaderNodeMixRGB"
                        or selector.blend_type != "MIX" or selector.use_clamp
                        or selector.use_alpha):
                    return False
                expected.extend(((live.outputs[name], selector.inputs[1]),
                                 (reader.outputs[name], selector.inputs[2]),
                                 (selector.outputs[0], output.inputs[name])))
        else:
            selector = unique(lambda item: item.get(SELECTOR) == "Color")
            if selector.bl_idname != "CompositorNodeSwitch":
                return False
            expected.extend(((live.outputs["Color"], selector.inputs["Off"]),
                             (reader.outputs["Image"], selector.inputs["On"]),
                             (selector.outputs["Image"], output.inputs["Color"])))
        actual = {(link.from_socket.as_pointer(), link.to_socket.as_pointer())
                  for link in tree.links if link.is_valid and not link.is_muted}
        return (len(tree.nodes) == (7 if shader else 5)
                and len(tree.links) == len(expected)
                and actual == {(origin.as_pointer(), target.as_pointer())
                               for origin, target in expected})
    except (AttributeError, KeyError, ReferenceError, RuntimeError, TypeError, ValueError):
        return False


def build(node, kernel, *, retire=None):
    from ..kernel.node_templates import instantiate_wrapper

    return instantiate_wrapper(node.id_data.bl_idname, kernel, retire=retire)


def synchronize(node, *, use_bake):
    """Reconcile native reader/selector drift from one authorized output policy."""
    tree = node.node_tree
    if tree is None or tree.get(WRAPPER) != 1:
        if use_bake:
            raise RuntimeError("Baked output has no private wrapper")
        return
    reader = marked(tree, READER)
    live = marked(tree, LIVE)
    selectors = tuple(item for item in tree.nodes if item.get(SELECTOR))
    shader = tree.bl_idname == "ShaderNodeTree"
    if reader is None or live is None or live.node_tree is None or len(selectors) != (2 if shader else 1):
        raise RuntimeError("Bake wrapper is incomplete")
    image = node.pg_bake_image
    if reader.image != image:
        reader.image = image
    for selector in selectors:
        socket = selector.inputs[0] if shader else selector.inputs["Switch"]
        value = float(use_bake) if shader else bool(use_bake)
        if socket.default_value != value:
            socket.default_value = value
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
