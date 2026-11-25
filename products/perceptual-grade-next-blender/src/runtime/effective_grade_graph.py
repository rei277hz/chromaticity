"""Read-only Grade graph ABI shared by Bake and scope capture."""

WRAPPER = "_pg_next_bake_wrapper"
LIVE = "_pg_next_bake_live"
READER = "_pg_next_bake_reader"
SELECTOR = "_pg_next_bake_selector"
UV = "_pg_next_bake_uv"
SCHEMA = "_pg_next_bake_schema"
DOMAIN = "_pg_next_bake_domain"
OPERATION = "_pg_next_bake_operation"


def marked(tree, key):
    if tree is None:
        return None
    return next((node for node in tree.nodes if node.get(key)), None)


def live_tree(tree):
    if tree is not None and tree.get(WRAPPER):
        live = marked(tree, LIVE)
        return None if live is None else live.node_tree
    return tree


def wrapper_structure_valid(tree):
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


