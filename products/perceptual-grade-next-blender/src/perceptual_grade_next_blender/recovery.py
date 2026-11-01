"""Rebuild static derived Grade/Stack data after load and Undo/Redo.

Only authored Blender data survives reopening.  Runtime workers, Bake handles
and native output continuations are deliberately fenced and discarded; fresh
preparation requests are the only work recovery may create.
"""

from dataclasses import dataclass

_HANDLERS = {}
_LAST_RECOVERY = None


@dataclass(frozen=True)
class RecoveryResult:
    """Fresh observation produced by one load/Undo recovery pass."""

    generation: int
    queued: tuple = ()
    reused: tuple = ()
    invalid: tuple = ()
    discarded_operations: tuple = ()

    @property
    def complete(self):
        """Whether every owner is settled after this recovery pass.

        Queued owners still need a fresh preparation receipt, so a recovery
        observation with queued work is intentionally incomplete even when no
        owner was permanently invalid.
        """
        return not self.invalid and not self.queued

    @property
    def pending(self):
        """Whether recovery created work that has not reached a receipt."""
        return bool(self.queued)


def last_recovery():
    """Return the latest recovery observation, if a Blender document loaded."""
    return _LAST_RECOVERY


def _owner_key(tree, node):
    try:
        tree_id = tree.as_pointer()
        node_id = node.as_pointer()
    except (AttributeError, ReferenceError, RuntimeError):
        return None
    if not tree_id or not node_id:
        return None
    return f"{tree_id}:{node_id}"


def _node_identity(node):
    try:
        return node.as_pointer() or id(node)
    except (AttributeError, ReferenceError, RuntimeError):
        return None


def _is_complete_project_tree_collection(node_groups, bpy):
    """Guard document-wide orphan cleanup from callers that pass a subset."""
    try:
        from .scope_runtime import _project_node_trees
        return ({tree.as_pointer() for tree in node_groups}
                == {tree.as_pointer() for tree in _project_node_trees(bpy)})
    except (AttributeError, ReferenceError, RuntimeError, TypeError):
        return False


def _has_current_derived_data(node):
    """Check only persisted data; ID properties never certify readiness."""
    try:
        from .updates import _read_ledger
        if _read_ledger(node) is not None:
            return False
    except (ImportError, AttributeError, TypeError, ValueError, RuntimeError):
        return False
    backend = node.get("perceptual_grade_next_backend")
    try:
        if backend == "native_grade_graph":
            from .project_readiness import _validate_grade
            _validate_grade(node)
            return True
        if backend == "native_stack_lut":
            from .project_readiness import _validate_stack
            _validate_stack(node)
            return True
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return False
    return False


def requeue_prepared_nodes(node_groups, *, mark_dirty=None, reuse_valid=False):
    """Queue owners whose authored settings are recoverable from saved RNA.

    This reconstructs from node controls and does not treat readiness ID
    properties or old worker state as authority. A valid packed Stack LUT can
    be adopted after readback; Grade graphs are requeued to rebuild their live
    persistent controller. Explicit Bake recovery is handled separately from
    preparation and never resumes the old request.
    """
    if mark_dirty is None:
        from .updates import mark_node_dirty as mark_dirty
    queued = []
    for tree in tuple(node_groups):
        try:
            nodes = tuple(getattr(tree, "nodes", ()))
        except (ReferenceError, RuntimeError):
            # Another owner in this pass may have released this ledger tree.
            continue
        for node in nodes:
            if node.get("perceptual_grade_next_backend") not in {
                "native_grade_graph", "native_stack_lut",
            }:
                continue
            try:
                if node.get("perceptual_grade_next_backend") == "native_grade_graph":
                    controls = node.perceptual_grade_next_controls
                else:
                    controls = node.perceptual_grade_next_stack_controls
            except (AttributeError, ReferenceError, RuntimeError):
                continue
            retained_tree_ledger = None
            retained_field_ledger = None
            retained_backing_id = None
            restore_attempted = False
            restore_completed = False
            try:
                from .updates import _clear_ledger, _read_ledger
                from .preparation_ledger import (
                    field_backing_data, retained_backing, tree_backing,
                )
                ledger = _read_ledger(node)
                retained_tree_ledger = tree_backing(node)
                retained_backing_id = retained_backing(node)
                retained_field_ledger = field_backing_data(node)
                if retained_tree_ledger is not None:
                    from .preparation_ledger import restore_tree_backing
                    restore_attempted = True
                    restore_tree_backing(tree, node, ledger)
                    restore_completed = True
                elif retained_field_ledger is not None:
                    from .preparation_ledger import restore_grade_backing
                    restore_data = dict(ledger or {})
                    restore_data.update(retained_field_ledger)
                    restore_attempted = True
                    restore_grade_backing(tree, node, restore_data)
                    restore_completed = True
                elif ledger is not None and ledger.get("backup_transaction"):
                    if node.get("perceptual_grade_next_backend") == "native_grade_graph":
                        from .preparation_ledger import restore_grade_backing
                        restore_attempted = True
                        restore_grade_backing(
                            tree, node, ledger,
                        )
                        restore_completed = True
                    else:
                        from .preparation_ledger import discard_owner_ledger
                        discard_owner_ledger(node)
                elif ledger is not None:
                    from .preparation_ledger import discard_owner_ledger
                    discard_owner_ledger(node)
                else:
                    from .preparation_ledger import discard_owner_ledger
                    discard_owner_ledger(node)
                _clear_ledger(node)
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                retained_native_ledger = (
                    retained_tree_ledger is not None
                    or retained_field_ledger is not None
                    or (retained_backing_id is not None
                        and hasattr(retained_backing_id, "nodes"))
                )
                if not restore_completed and (retained_native_ledger or restore_attempted):
                    # A failed compensation must retain its real ID references
                    # and exact snapshot. A fresh transaction could overwrite
                    # the only recoverable prior state.
                    try:
                        from . import updates
                        updates._LIVE.pop(updates._key(tree, node), None)
                        node["perceptual_grade_next_preparation_state"] = "FAILED"
                        node["perceptual_grade_next_preparation_error"] = (
                            "Preparation recovery is incomplete; retained native resources need repair"
                        )
                    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                        pass
                    continue
                # A damaged or incomplete transaction must not strand this
                # owner in FAILED forever.  Remove its persisted transaction
                # and any staged backing first; the next preparation is a
                # fresh request reconstructed from authored controls.  In
                # particular, never let a failed restore be treated as a
                # usable prior candidate.
                try:
                    from .preparation_ledger import discard_owner_ledger
                    discard_owner_ledger(node)
                except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                    pass
                try:
                    _clear_ledger(node)
                except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                    pass
                try:
                    from . import updates
                    updates._LIVE.pop(updates._key(tree, node), None)
                except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                    pass
                try:
                    node["perceptual_grade_next_preparation_state"] = "FAILED"
                    node["perceptual_grade_next_preparation_error"] = (
                        "Preparation recovery backing could not be restored"
                    )
                except (ReferenceError, RuntimeError):
                    pass
                # Queue a fresh full preparation even when the persisted
                # transaction was malformed.  A failed callback must not
                # turn a recoverable owner into a permanent unavailable
                # state.
                try:
                    if mark_dirty(node):
                        queued.append(node)
                except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                    pass
                continue
            if (reuse_valid
                    and node.get("perceptual_grade_next_backend") == "native_stack_lut"
                    and _has_current_derived_data(node)):
                continue
            if mark_dirty(node):
                queued.append(node)
    return tuple(queued)


def recover_document(node_groups, *, generation=0, mark_dirty=None):
    """Fence runtime state and derive fresh preparation demand from the file.

    The returned identities are stable only for this observation.  Explicit
    Bakes and output operations are represented as discarded because recovery
    never resumes them automatically.
    """
    global _LAST_RECOVERY
    _invalidate_runtime_state()
    try:
        import bpy
    except ImportError:
        bpy = None
    complete_project = (
        bpy is not None and _is_complete_project_tree_collection(node_groups, bpy)
    )
    if bpy is not None and hasattr(getattr(bpy, "data", None), "images"):
        from .image_publication import BlenderImageBackupStore
        image_recovery = BlenderImageBackupStore(bpy).recover_pending()
        if complete_project:
            try:
                from .preparation_ledger import (
                    discard_orphan_candidates, discard_orphan_ledgers,
                )
                discard_orphan_ledgers(node_groups)
                discard_orphan_candidates(node_groups)
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                # A malformed owner must not prevent the rest of document recovery.
                pass
        if complete_project:
            from .scope_runtime import _project_node_trees
            node_groups = tuple(_project_node_trees(bpy))
    else:
        # Host-independent workflow tests have no Blender datablock store.
        image_recovery = ()
    from .project_readiness import begin_document, refresh_project_readiness

    current_generation = begin_document()
    if generation > current_generation:
        current_generation = generation
    queued = requeue_prepared_nodes(
        node_groups, mark_dirty=mark_dirty, reuse_valid=True,
    )
    if complete_project:
        from .scope_runtime import _project_node_trees
        node_groups = tuple(_project_node_trees(bpy))
    queued_node_ids = {_node_identity(node) for node in queued}
    queued_ids = set()
    invalid_ids = set()
    reused_ids = set()
    for tree in node_groups:
        for node in getattr(tree, "nodes", ()):
            backend = node.get("perceptual_grade_next_backend")
            if backend not in {"native_grade_graph", "native_stack_lut"}:
                continue
            identity = _owner_key(tree, node)
            if identity is None:
                continue
            if _node_identity(node) in queued_node_ids:
                queued_ids.add(identity)
            elif (backend == "native_stack_lut"
                  and _has_current_derived_data(node)):
                reused_ids.add(identity)
            else:
                invalid_ids.add(identity)
    refresh_project_readiness(node_groups)
    _LAST_RECOVERY = RecoveryResult(
        generation=current_generation,
        queued=tuple(sorted(queued_ids)),
        reused=tuple(sorted(reused_ids)),
        invalid=tuple(sorted(invalid_ids)),
        discarded_operations=("bake", "save", "render") + tuple(
            "bake_image:" + token + ":" + outcome
            for token, outcome in image_recovery
        ),
    )
    return _LAST_RECOVERY


def _invalidate_runtime_state():
    from .updates import cancel_pending_updates
    cancel_pending_updates(clear_holds=False)


def _after_load(_unused):
    import bpy
    from .scope_runtime import _project_node_trees
    recover_document(tuple(_project_node_trees(bpy)))


def _after_undo(_unused):
    import bpy
    from .scope_runtime import _project_node_trees
    recover_document(tuple(_project_node_trees(bpy)))


def _render_started(_unused):
    from .updates import hold_publication
    hold_publication("native_render")


def _render_finished(scene):
    from .updates import release_publication
    release_publication("native_render")
    from .output_operators import native_render_terminal
    native_render_terminal(committed=True, scene=scene)


def _render_cancelled(scene):
    from .updates import release_publication
    release_publication("native_render")
    from .output_operators import native_render_terminal
    native_render_terminal(committed=False, scene=scene)


def _save_started(_unused):
    from .updates import hold_publication
    hold_publication("native_save")


def _save_finished(_unused):
    from .updates import release_publication
    release_publication("native_save")


def register():
    """Register persistent handlers without importing Blender at package load."""
    import bpy

    if "load_post" not in _HANDLERS:
        _HANDLERS["load_post"] = bpy.app.handlers.persistent(_after_load)
    if "undo_post" not in _HANDLERS:
        _HANDLERS["undo_post"] = bpy.app.handlers.persistent(_after_undo)
    if hasattr(bpy.app.handlers, "redo_post"):
        if "redo_post" not in _HANDLERS:
            _HANDLERS["redo_post"] = bpy.app.handlers.persistent(_after_undo)
    for name, callback in (("render_pre", _render_started),
                           ("render_complete", _render_finished),
                           ("render_cancel", _render_cancelled),
                           ("save_pre", _save_started),
                           ("save_post", _save_finished)):
        if hasattr(bpy.app.handlers, name) and name not in _HANDLERS:
            _HANDLERS[name] = bpy.app.handlers.persistent(callback)
    for name, callback in _HANDLERS.items():
        handlers = getattr(bpy.app.handlers, name)
        while callback in handlers:
            handlers.remove(callback)
        handlers.append(callback)


def unregister():
    """Remove only the handlers owned by this package."""
    try:
        import bpy
    except ImportError:
        _HANDLERS.clear()
        return
    for name, callback in tuple(_HANDLERS.items()):
        handlers = getattr(bpy.app.handlers, name, ())
        while callback in handlers:
            handlers.remove(callback)
    _HANDLERS.clear()


__all__ = (
    "RecoveryResult", "last_recovery", "recover_document", "register",
    "requeue_prepared_nodes", "unregister",
)
