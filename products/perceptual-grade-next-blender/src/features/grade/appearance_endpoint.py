"""Resolve the guarded final-appearance outputs of a live Grade kernel."""

from ...kernel.node_templates import (
    KERNEL_QUALITY, SLOT_SCOPE_APPEARANCE, SLOT_SCOPE_APPEARANCE_ALPHA,
    TEMPLATE_SLOT,
)
from ...runtime import effective_grade_graph


def resolve(tree, target):
    """Copy the Grade-owned graph path and return its appearance output sockets.

    ``tree`` and ``target`` must belong to a private capture graph. The returned
    parent entries describe the additional copied group occurrences required
    to expose the sockets at the capture graph root.
    """
    parents = []
    kernel = target.node_tree
    if target.mute or kernel is None:
        raise ValueError("Vectorscope appearance capture requires a live full Grade node")
    if kernel.get(effective_grade_graph.WRAPPER):
        if not effective_grade_graph.wrapper_structure_valid(kernel):
            raise ValueError("Vectorscope Bake wrapper is incomplete")
        shader = kernel.bl_idname == "ShaderNodeTree"
        controls = (node.inputs[0 if shader else "Switch"] for node in kernel.nodes
                    if node.get(effective_grade_graph.SELECTOR))
        if any(control.is_linked or control.default_value for control in controls):
            raise ValueError("Vectorscope appearance capture cannot read an active Bake output")
        target.node_tree = kernel.copy()
        parents.append((tree, target))
        tree = target.node_tree
        target = effective_grade_graph.marked(tree, effective_grade_graph.LIVE)
        kernel = target.node_tree
    if (kernel.get("_perceptual_grade_stage2_complete") is not True
            or kernel.get(KERNEL_QUALITY) not in (None, "full")):
        raise ValueError("Vectorscope appearance capture requires a live full Grade node")

    target.node_tree = kernel.copy()
    kernel = target.node_tree
    parents.append((tree, target))

    packed = tuple(node for node in kernel.nodes
                   if node.get(TEMPLATE_SLOT) == SLOT_SCOPE_APPEARANCE)
    opacity = tuple(node for node in kernel.nodes
                    if node.get(TEMPLATE_SLOT) == SLOT_SCOPE_APPEARANCE_ALPHA)
    if len(packed) != 1 or len(opacity) != 1:
        raise ValueError("Vectorscope Grade has no unique final-appearance endpoint")

    outputs = (
        packed[0].outputs[0],
        _socket(opacity[0].outputs, "Value"),
    )
    return kernel, outputs, tuple(parents)


def _socket(sockets, name):
    result = next((item for item in sockets if item.identifier == name), None)
    if result is None:
        result = sockets.get(name)
    if result is None:
        raise ValueError("Vectorscope socket is absent: " + str(name))
    return result
