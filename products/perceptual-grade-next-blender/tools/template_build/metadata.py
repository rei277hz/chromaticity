"""Build-only metadata tagging for generated native node templates."""

from ..kernel.node_templates import (
    BAKE_LIVE,
    BAKE_READER,
    PARAMETER_BANK_BINDINGS,
    PARAMETER_IMAGE,
    PARAMETER_SCHEMA,
    SLOT_BOUNDARY,
    SLOT_LIVE,
    SLOT_LUT,
    SLOT_BAKE,
    TEMPLATE_KIND,
    TEMPLATE_SCHEMA,
    TEMPLATE_SIZE,
    TEMPLATE_SOURCE,
    TEMPLATE_SLOT,
    TEMPLATE_SPACE,
    TEMPLATE_VARIANT,
    STACK_IMAGE,
    TemplateAssetError,
    TemplateVariant,
    _slots,
    structure_digest,
)
from ..kernel.stage2_bindings import TEMPLATE_SCHEMA as TEMPLATE_MARKER_SCHEMA


def _tag_node(node, role):
    node[TEMPLATE_SLOT] = role


def _discover_slots(tree, kind):
    result = {}
    for node in tree.nodes:
        image = getattr(node, "image", None)
        role = node.get(TEMPLATE_SLOT)
        if role is None and image is not None:
            if image.get(PARAMETER_IMAGE) == PARAMETER_SCHEMA:
                for bank, key in enumerate(PARAMETER_BANK_BINDINGS):
                    if image == tree.get(key):
                        role = f"parameter:{bank}"
                        break
            if role is None and (
                    image.get("perceptual_grade_nodes_field_role") == "boundary_seed"
                    or node.label == "AP1 boundary root seed"):
                role = SLOT_BOUNDARY
            if role is None and (image.get(STACK_IMAGE) or kind == "stack"):
                role = SLOT_LUT
        if role is None and node.get(BAKE_LIVE):
            role = SLOT_LIVE
        if role is None and node.get(BAKE_READER):
            role = SLOT_BAKE
        if role is not None:
            _tag_node(node, role)
            result.setdefault(str(role), []).append(node.name)
    return {role: tuple(names) for role, names in result.items()}


def tag_template(tree, key, kind, space=None, size=None, *, slots=None):
    """Mark an emitted tree as a source template and return its record."""
    variant = TemplateVariant(kind, tree.bl_idname, space, size)
    if variant.key != key:
        raise TemplateAssetError(f"Template key does not match identity: {key}")
    tree[TEMPLATE_SCHEMA] = TEMPLATE_MARKER_SCHEMA
    tree[TEMPLATE_VARIANT] = key
    tree[TEMPLATE_KIND] = kind
    tree[TEMPLATE_SOURCE] = True
    if space is not None:
        tree[TEMPLATE_SPACE] = space
    if size is not None:
        tree[TEMPLATE_SIZE] = size
    discovered = _discover_slots(tree, kind)
    if slots is not None:
        for role, names in _slots(slots).items():
            for name in names:
                node = tree.nodes.get(name)
                if node is None:
                    raise TemplateAssetError(f"Template slot is absent: {name}")
                _tag_node(node, role)
            discovered[role] = tuple(names)
    return describe_template(tree, key, kind, space=space, size=size, slots=discovered)


def describe_template(tree, key, kind, space=None, size=None, *, slots=None):
    variant = TemplateVariant(kind, tree.bl_idname, space, size)
    if variant.key != key:
        raise TemplateAssetError(f"Template key does not match identity: {key}")
    slots = _slots(slots) if slots is not None else _discover_slots(tree, kind)
    return {
        "name": tree.name,
        "kind": kind,
        "tree_type": tree.bl_idname,
        "space": space,
        "size": size,
        "node_count": len(tree.nodes),
        "link_count": len(tree.links),
        "structure_sha256": structure_digest(tree),
        "slots": {role: list(names) for role, names in slots.items()},
    }


__all__ = ("describe_template", "tag_template")
