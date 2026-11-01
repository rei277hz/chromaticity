"""Bind verified Blender-owned native evaluators to a Bake request.

The binding functions perform a fresh readiness inspection at the moment a
Bake captures pixels.  They do not rebuild a Stack model or grade through an
analytic helper; the returned object is the packed, installed evaluator that
the owner node currently references.
"""

from .output_gateway import EvaluatorBinding, OutputRequest
from .project_readiness import GRADE_BACKEND, STACK_BACKEND, inspect_project_owners
from .stack import reopen_stack


def bind_stack_evaluator(owner_node, request: OutputRequest):
    """Return the current accepted 65³ Stack LUT for ``request``.

    ``owner_node`` must be the installed ``native_stack_lut`` group node.  A
    fresh inspection rejects stale revisions, preview-only resources, changed
    authored controls, missing packed payloads, and manifest/evaluator identity
    mismatches before a LUT is handed to the capture gateway.
    """
    if request.evaluator != "stack_65_lut" or request.final_ready is not True:
        raise TypeError("Stack native capture requires a final 65^3 request")
    tree = getattr(owner_node, "id_data", None)
    if tree is None or getattr(owner_node, "node_tree", None) is None:
        raise RuntimeError("Stack owner has no installed native tree")
    snapshot = inspect_project_owners((tree,), generation=0)
    identity = None
    try:
        identity = f"{tree.as_pointer()}:{owner_node.as_pointer()}"
    except (AttributeError, ReferenceError, RuntimeError):
        pass
    if identity is None:
        raise RuntimeError("Stack owner has no stable Blender identity")
    matches = tuple(item for item in snapshot.owners if item.identity == identity)
    if len(matches) != 1:
        raise RuntimeError("Stack owner is not present in the current project")
    readiness = matches[0]
    if request.owner != readiness.identity:
        raise RuntimeError("Bake request belongs to a different Stack owner")
    if readiness.backend != STACK_BACKEND or not readiness.ready:
        raise RuntimeError(readiness.reason or "Stack final evaluator is not ready")
    if (readiness.evaluator != request.evaluator
            or readiness.evaluator_id != request.evaluator_id
            or readiness.manifest_id != request.manifest_id):
        raise RuntimeError("Stack evaluator receipt does not match the current owner")
    restored = reopen_stack(owner_node.node_tree, rebuild=False)
    if not restored.final_ready or not restored.validate_persistent():
        raise RuntimeError("Installed Stack final resources are not valid")
    lut = restored.bake_evaluator
    if getattr(lut, "size", None) != 65:
        raise RuntimeError("Installed Stack evaluator is not a 65^3 LUT")
    return EvaluatorBinding(lut, readiness.evaluator_id, readiness.manifest_id)


def bind_grade_evaluator(owner_node, request: OutputRequest, evaluate_native):
    """Bind Blender's installed Grade node-tree output for one Bake.

    ``evaluate_native`` is supplied by the host's native graph capture path;
    this adapter never substitutes a portable model or a custom GPU grader.
    The fresh inspection makes the callback usable only for the current
    installed tree and manifest.
    """
    if request.evaluator != "native_grade_graph" or request.final_ready is not True:
        raise TypeError("Grade native capture requires a final native graph request")
    if not callable(evaluate_native):
        raise TypeError("Grade native capture requires a callable Blender evaluator")
    tree = getattr(owner_node, "id_data", None)
    if tree is None or getattr(owner_node, "node_tree", None) is None:
        raise RuntimeError("Grade owner has no installed native tree")
    snapshot = inspect_project_owners((tree,), generation=0)
    try:
        identity = f"{tree.as_pointer()}:{owner_node.as_pointer()}"
    except (AttributeError, ReferenceError, RuntimeError) as error:
        raise RuntimeError("Grade owner has no stable Blender identity") from error
    matches = tuple(item for item in snapshot.owners if item.identity == identity)
    if len(matches) != 1:
        raise RuntimeError("Grade owner is not present in the current project")
    readiness = matches[0]
    if request.owner != readiness.identity:
        raise RuntimeError("Bake request belongs to a different Grade owner")
    if readiness.backend != GRADE_BACKEND or not readiness.ready:
        raise RuntimeError(readiness.reason or "Native Grade evaluator is not ready")
    if (readiness.evaluator != request.evaluator
            or readiness.evaluator_id != request.evaluator_id
            or readiness.manifest_id != request.manifest_id):
        raise RuntimeError("Grade evaluator receipt does not match the current owner")
    return EvaluatorBinding(evaluate_native, readiness.evaluator_id, readiness.manifest_id)


__all__ = ("bind_grade_evaluator", "bind_stack_evaluator")
