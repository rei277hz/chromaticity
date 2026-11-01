"""Replace native Grade/Stack owners after static authored-control edits."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
import uuid


_PENDING = {}
_JOBS = {}
_LIVE = {}
_PUBLICATION_HOLDS = set()
_TIMER_REGISTERED = False
_EXECUTOR = None

PREPARATION_LEDGER_KEY = "perceptual_grade_next_preparation_ledger"
PREPARATION_LEDGER_SCHEMA = 1
CANDIDATE_OWNER_KEY = "perceptual_grade_next_candidate_owner"
CANDIDATE_REVISION_KEY = "perceptual_grade_next_candidate_revision"


def _read_ledger(node):
    raw = node.get(PREPARATION_LEDGER_KEY, "")
    if not raw:
        return None
    try:
        value = json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        return {"schema": PREPARATION_LEDGER_SCHEMA, "stage": "corrupt"}
    if not isinstance(value, dict) or value.get("schema") != PREPARATION_LEDGER_SCHEMA:
        return {"schema": PREPARATION_LEDGER_SCHEMA, "stage": "obsolete"}
    return value


def _write_ledger(node, *, kind, revision, stage, prior_revision=0,
                  prior_settings="", error="", backup_transaction="",
                  backup_slots=(), new_transaction=False, transaction_id="",
                  clear_backup=False):
    previous = _read_ledger(node) or {}
    transaction_id = (transaction_id or
                      ("%s" % uuid.uuid4().hex if new_transaction else
                       previous.get("transaction_id", "")) or uuid.uuid4().hex)
    # A fresh edit owns a new publication transaction. Never carry backup
    # references from a transaction resolved by recovery or a prior failure.
    if new_transaction:
        previous = {}
    node[PREPARATION_LEDGER_KEY] = json.dumps({
        "schema": PREPARATION_LEDGER_SCHEMA,
        "kind": kind,
        "revision": int(revision),
        "prior_revision": int(prior_revision),
        "prior_settings": prior_settings or "",
        "stage": stage,
        "error": str(error)[:512] if error else "",
        "transaction_id": transaction_id,
        "backup_transaction": ("" if clear_backup or new_transaction else
                               backup_transaction or previous.get("backup_transaction", "")),
        "backup_slots": ([] if clear_backup or new_transaction else
                         list(backup_slots or previous.get("backup_slots", ()))),
    }, sort_keys=True, separators=(",", ":"))


def _clear_ledger(node):
    if PREPARATION_LEDGER_KEY in node:
        del node[PREPARATION_LEDGER_KEY]


def _pointer(value):
    try:
        pointer = value.as_pointer()
        return pointer or None
    except (AttributeError, ReferenceError):
        return None


def _find_owner(group):
    import bpy
    from .scope_runtime import _project_node_trees

    wanted = _pointer(group)
    if wanted is None:
        return None
    for tree in _project_node_trees(bpy):
        for node in tree.nodes:
            backend = node.get("perceptual_grade_next_backend")
            try:
                if backend == "native_grade_graph":
                    if _pointer(node.perceptual_grade_next_controls) == wanted:
                        return tree, node, "grade"
                elif backend == "native_stack_lut":
                    for entry in node.perceptual_grade_next_stack_controls.entries:
                        if (_pointer(entry) == wanted
                                or _pointer(entry.settings) == wanted):
                            return tree, node, "stack"
                    if _pointer(node.perceptual_grade_next_stack_controls) == wanted:
                        return tree, node, "stack"
            except (AttributeError, ReferenceError, RuntimeError):
                continue
    return None


def _key(tree, node):
    return (_pointer(tree), _pointer(node))


def _schedule_timer():
    global _TIMER_REGISTERED
    import bpy

    if not _TIMER_REGISTERED:
        bpy.app.timers.register(_process_one, first_interval=0.2)
        _TIMER_REGISTERED = True


def _executor():
    global _EXECUTOR
    if _EXECUTOR is None:
        _EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="pgn-prepare")
    return _EXECUTOR


def register_native_owner(node, native, kind):
    if kind not in {"grade", "stack"}:
        raise ValueError("native owner kind must be grade or stack")
    _LIVE[_key(node.id_data, node)] = (kind, native, node.id_data, node)
    _refresh_project_readiness()


def _refresh_project_readiness():
    try:
        import bpy
        from .project_readiness import refresh_project_readiness
        from .scope_runtime import _project_node_trees
        refresh_project_readiness(tuple(_project_node_trees(bpy)))
    except (ImportError, ReferenceError, RuntimeError, TypeError, ValueError):
        # A stale or malformed owner remains unready; readiness refresh must
        # never turn an authored control callback into a UI exception.
        return


def _live_owner(key):
    for live_key, (kind, native, tree, node) in tuple(_LIVE.items()):
        if _pointer(tree) is None or _pointer(node) is None:
            del _LIVE[live_key]
    owner = _LIVE.get(key)
    return owner


def _prune_live_owners():
    for key in tuple(_LIVE):
        _live_owner(key)


def mark_node_dirty(node):
    """Queue a complete replacement for an authored node instance."""
    tree = getattr(node, "id_data", None)
    if tree is None:
        return False
    backend = node.get("perceptual_grade_next_backend")
    kind = {"native_grade_graph": "grade", "native_stack_lut": "stack"}.get(backend)
    if kind is None:
        return False
    try:
        from .preparation_ledger import retained_backing
        if retained_backing(node) is not None:
            node["perceptual_grade_next_preparation_state"] = "FAILED"
            node["perceptual_grade_next_preparation_error"] = (
                "Preparation recovery is pending; recover the retained resources before editing again"
            )
            _refresh_project_readiness()
            return False
        from . import controls
        animated = controls.unsupported_node_animation_paths(
            getattr(tree, "animation_data", None), node.path_from_id()
        )
        if animated:
            node["perceptual_grade_next_preparation_state"] = "UNAVAILABLE"
            node["perceptual_grade_next_preparation_error"] = (
                "Static Grade/Stack controls have animation: " + animated[0]
            )[:512]
            _refresh_project_readiness()
            return False
        snapshot = (controls.settings_from_controls(node.perceptual_grade_next_controls)
                    if kind == "grade" else controls.stack_settings_from_controls(node))
        revision = int(node.get("perceptual_grade_next_edit_revision", 0)) + 1
        _write_ledger(
            node, kind=kind, revision=revision, stage="queued",
            prior_revision=int(node.get("perceptual_grade_next_applied_revision", 0)),
            prior_settings=(node.get("perceptual_grade_next_settings", "")
                            if kind == "grade" else
                            node.get("perceptual_grade_next_stack_settings", "")),
            new_transaction=True,
        )
        node["perceptual_grade_next_edit_revision"] = revision
        node["perceptual_grade_next_preparation_state"] = "PENDING"
        node["perceptual_grade_next_preparation_error"] = ""
    except (AttributeError, ReferenceError, RuntimeError):
        _refresh_project_readiness()
        return False
    except (TypeError, ValueError) as error:
        try:
            node["perceptual_grade_next_preparation_state"] = "FAILED"
            node["perceptual_grade_next_preparation_error"] = str(error)[:512]
        except (ReferenceError, RuntimeError):
            pass
        _refresh_project_readiness()
        return False
    key = _key(tree, node)
    live = _live_owner(key)
    previous = None
    if live is not None and live[0] == kind:
        previous = (live[1].controller.prepared if kind == "grade"
                    else live[1].preparation)
    job = _JOBS.get(key)
    if job is not None and job[0].cancel():
        del _JOBS[key]
    _PENDING[key] = (tree, node, kind, revision, snapshot, previous)
    _schedule_timer()
    _refresh_project_readiness()
    return True


def control_changed(group, _context):
    """Blender RNA callback shared by Grade and Stack controls."""
    if not getattr(group, "perceptual_grade_next_ready", False):
        return
    owner = _find_owner(group)
    if owner is not None:
        mark_node_dirty(owner[1])


def _prepare(kind, settings, previous):
    if kind == "grade":
        from .native_grade import prepare_native_grade
        return prepare_native_grade(settings, previous=previous)
    from .stack import prepare_stack, refine_stack
    if previous is not None and previous.settings == settings:
        if previous.final_ready:
            return previous
        return refine_stack(previous)
    return refine_stack(prepare_stack(settings))


def _install(tree, node, kind, revision, settings, prepared):
    if _PUBLICATION_HOLDS:
        raise NativeAdmissionDeferred("Native publication is held by Save or Render")
    from .native_admission import acquire_writer, release

    lease = acquire_writer("preparation:%s:%s" % (_pointer(node), revision))
    if lease is None:
        raise NativeAdmissionDeferred("Native readers have not retired")
    try:
        return _install_admitted(tree, node, kind, revision, settings, prepared)
    finally:
        release(lease)


class NativeAdmissionDeferred(RuntimeError):
    """A prepared candidate is waiting for exclusive native publication."""


def _install_admitted(tree, node, kind, revision, settings, prepared):
    _write_ledger(
        node, kind=kind, revision=revision, stage="staging",
        prior_revision=int(node.get("perceptual_grade_next_applied_revision", 0)),
        prior_settings=(node.get("perceptual_grade_next_settings", "")
                        if kind == "grade" else
                        node.get("perceptual_grade_next_stack_settings", "")),
    )
    if kind == "grade":
        from .native_grade import apply_native_grade, install_native_grade
        grade_settings, prepared_grade = prepared
        if grade_settings != settings:
            raise RuntimeError("Prepared Grade settings changed during generation")
        live = _live_owner(_key(tree, node))
        if live is not None and live[0] == "grade" and live[1].controller.valid:
            previous_owner = live[1]
            previous_settings = previous_owner.settings
            previous_prepared = previous_owner.controller.prepared
            previous_node_settings = node.get("perceptual_grade_next_settings", "")
            manifest_key = "perceptual_grade_next_accepted_grade_manifest"
            previous_manifest_present = manifest_key in node
            previous_manifest = node.get(manifest_key, "")
            previous_applied_revision = node.get("perceptual_grade_next_applied_revision", 0)
            previous_node_state = node.get("perceptual_grade_next_preparation_state", "READY")
            previous_node_error = node.get("perceptual_grade_next_preparation_error", "")
            previous_controller_revision = previous_owner.controller.revision
            _write_ledger(
                node, kind=kind, revision=revision, stage="committing",
                prior_revision=previous_applied_revision,
                prior_settings=previous_node_settings,
            )
            from .preparation_ledger import (
                discard_grade_backing, stage_grade_backing,
            )
            ledger = _read_ledger(node) or {}
            transaction = ledger.get("transaction_id", "")
            backup_transaction, backup_slots = stage_grade_backing(
                tree, node, previous_owner, prepared_grade, transaction,
                ledger_data=ledger,
            )
            if backup_slots:
                _write_ledger(
                    node, kind=kind, revision=revision, stage="backed_up",
                    prior_revision=previous_applied_revision,
                    prior_settings=previous_node_settings,
                    backup_transaction=backup_transaction,
                    backup_slots=backup_slots,
                )
            _write_ledger(
                node, kind=kind, revision=revision, stage="committing",
                prior_revision=previous_applied_revision,
                prior_settings=previous_node_settings,
            )
            try:
                updated, receipt = apply_native_grade(
                    previous_owner, settings, prepared_grade,
                    expected_revision=previous_owner.controller.revision,
                )
            except BaseException as error:
                if backup_transaction:
                    if previous_owner.controller.valid:
                        _write_ledger(
                            node, kind=kind, revision=revision, stage="failed",
                            prior_revision=previous_applied_revision,
                            prior_settings=previous_node_settings, error=error,
                            clear_backup=True,
                        )
                        discard_grade_backing(node, backup_transaction)
                    else:
                        _write_ledger(
                            node, kind=kind, revision=revision, stage="failed",
                            prior_revision=previous_applied_revision,
                            prior_settings=previous_node_settings, error=error,
                            backup_transaction=backup_transaction,
                            backup_slots=backup_slots,
                        )
                        node["perceptual_grade_next_preparation_state"] = "FAILED"
                        node["perceptual_grade_next_preparation_error"] = (
                            "Grade update rollback failed; retained recovery backing"
                        )
                        _refresh_project_readiness()
                raise
            try:
                node["perceptual_grade_next_settings"] = updated.tree[
                    "perceptual_grade_next_settings"
                ]
                node["perceptual_grade_next_applied_revision"] = revision
                node["perceptual_grade_next_preparation_state"] = "READY"
                node["perceptual_grade_next_preparation_error"] = ""
                from .project_readiness import accept_grade_manifest
                accept_grade_manifest(node, updated)
            except BaseException as error:
                try:
                    apply_native_grade(
                        updated, previous_settings, previous_prepared,
                        expected_revision=receipt["revision"],
                    )
                    node["perceptual_grade_next_settings"] = previous_node_settings
                    if previous_manifest_present:
                        node[manifest_key] = previous_manifest
                    elif manifest_key in node:
                        del node[manifest_key]
                    if ((manifest_key in node) != previous_manifest_present
                            or (previous_manifest_present
                                and node.get(manifest_key) != previous_manifest)):
                        raise RuntimeError("Grade manifest compensation readback failed")
                    node["perceptual_grade_next_applied_revision"] = previous_applied_revision
                    node["perceptual_grade_next_preparation_state"] = previous_node_state
                    node["perceptual_grade_next_preparation_error"] = previous_node_error
                    previous_owner.controller.revision = previous_controller_revision
                    previous_owner.tree["perceptual_grade_nodes_revision"] = previous_controller_revision
                except BaseException as rollback_error:
                    live[1].controller.valid = False
                    _write_ledger(
                        node, kind=kind, revision=revision, stage="failed",
                        prior_revision=previous_applied_revision,
                        prior_settings=previous_node_settings,
                        error="Grade metadata commit and native rollback failed",
                        backup_transaction=backup_transaction,
                        backup_slots=backup_slots,
                    )
                    try:
                        node["perceptual_grade_next_preparation_state"] = "FAILED"
                        node["perceptual_grade_next_preparation_error"] = (
                            "Grade metadata commit and native rollback failed"
                        )
                    except (ReferenceError, RuntimeError):
                        pass
                    _refresh_project_readiness()
                    raise RuntimeError("Grade metadata commit and native rollback failed") from rollback_error
                if backup_transaction:
                    _write_ledger(
                        node, kind=kind, revision=revision, stage="failed",
                        prior_revision=previous_applied_revision,
                        prior_settings=previous_node_settings, clear_backup=True,
                    )
                    discard_grade_backing(node, backup_transaction)
                raise error
            register_native_owner(node, updated, "grade")
            _clear_ledger(node)
            if backup_transaction:
                discard_grade_backing(node, backup_transaction)
            _refresh_project_readiness()
            return
        candidate_owner = str(node.as_pointer())
        candidate_name = ".PG Next Candidate Grade %s %s %s" % (
            candidate_owner, revision, uuid.uuid4().hex,
        )
        candidate = install_native_grade(settings, prepared_grade,
            tree_type=node.node_tree.bl_idname,
            name=candidate_name, candidate_owner=candidate_owner,
            candidate_revision=revision)
        new_tree = candidate.tree
    else:
        from .stack import _settings_data
        from .stack_graph import build_native_stack
        if prepared.settings != settings:
            raise RuntimeError("Prepared Stack settings changed during generation")
        candidate = build_native_stack(
            settings, preparation=prepared, tree_type=node.node_tree.bl_idname,
            name=f"{node.node_tree.name} Prepared",
        )
        new_tree = candidate.tree

    # Mark replacement resources before they become visible through the owner
    # node. Recovery can then remove an unreferenced candidate if Blender exits
    # between candidate construction and the native pointer swap.
    new_tree[CANDIDATE_OWNER_KEY] = str(node.as_pointer())
    new_tree[CANDIDATE_REVISION_KEY] = revision

    previous = node.node_tree
    incoming = tuple(
        (link.from_socket, link.to_socket.name)
        for link in tree.links if link.to_node == node
    )
    outgoing = tuple(
        (link.from_socket.name, link.to_socket)
        for link in tree.links if link.from_node == node
    )
    defaults = {
        socket.name: _copy_socket_value(socket.default_value)
        for socket in node.inputs if hasattr(socket, "default_value")
    }
    property_keys = (
        "perceptual_grade_next_settings",
        "perceptual_grade_next_stack_settings",
        "perceptual_grade_next_stack_evaluator",
        "perceptual_grade_next_stack_quality_tier",
        "perceptual_grade_next_applied_revision",
        "perceptual_grade_next_preparation_state",
        "perceptual_grade_next_preparation_error",
        "perceptual_grade_next_accepted_grade_manifest",
    )
    properties_before = {key: node.get(key) for key in property_keys}
    properties_present = {key: key in node for key in property_keys}
    previous_live = _LIVE.get(_key(tree, node))
    from .preparation_ledger import (
        commit_tree_backing, discard_owner_ledger, restore_tree_backing,
        stage_tree_backing,
    )
    transaction = (_read_ledger(node) or {}).get("transaction_id", "")
    try:
        stage_tree_backing(
            tree, node, previous, new_tree, transaction,
            defaults=defaults,
            properties={key: (properties_present[key], properties_before[key])
                        for key in property_keys},
        )
    except BaseException:
        _dispose(candidate, kind)
        raise
    try:
        _write_ledger(
            node, kind=kind, revision=revision, stage="committing",
            prior_revision=int(node.get("perceptual_grade_next_applied_revision", 0)),
            prior_settings=(node.get("perceptual_grade_next_settings", "")
                            if kind == "grade" else
                            node.get("perceptual_grade_next_stack_settings", "")),
            backup_transaction=transaction,
        )
        node.node_tree = new_tree
        if node.node_tree != new_tree:
            raise RuntimeError("Blender did not install the candidate native tree")
        for socket_name, value in defaults.items():
            socket = node.inputs.get(socket_name)
            if socket is not None and hasattr(socket, "default_value"):
                socket.default_value = value
        _restore_links(tree, node, incoming, outgoing)
        if kind == "grade":
            node["perceptual_grade_next_settings"] = new_tree[
                "perceptual_grade_next_settings"
            ]
        else:
            node["perceptual_grade_next_stack_settings"] = json.dumps(
                _settings_data(settings), sort_keys=True, separators=(",", ":")
            )
            node["perceptual_grade_next_stack_evaluator"] = new_tree.get(
                "perceptual_grade_next_stack_bake_evaluator", ""
            )
            node["perceptual_grade_next_stack_quality_tier"] = new_tree.get(
                "perceptual_grade_next_stack_quality_tier", ""
            )
        node["perceptual_grade_next_applied_revision"] = revision
        node["perceptual_grade_next_preparation_state"] = "READY"
        node["perceptual_grade_next_preparation_error"] = ""
        if kind == "grade":
            from .project_readiness import accept_grade_manifest
            accept_grade_manifest(node, candidate)
        register_native_owner(node, candidate, kind)
        commit_tree_backing(node, transaction)
    except BaseException as install_error:
        try:
            restore_tree_backing(tree, node, _read_ledger(node))
            if previous_live is None:
                _LIVE.pop(_key(tree, node), None)
            else:
                _LIVE[_key(tree, node)] = previous_live
        except BaseException as rollback_error:
            # The real prior/candidate references remain rooted by the ledger.
            # Disposal here would destroy the only crash-recovery backing.
            _LIVE.pop(_key(tree, node), None)
            raise RuntimeError("Native replacement and rollback both failed") from rollback_error
        _dispose(candidate, kind)
        raise install_error
    if kind == "grade":
        from .preparation_ledger import clear_candidate_markers
        new_tree.name = previous.name + " Prepared"
        clear_candidate_markers(new_tree)
    else:
        for key in (CANDIDATE_OWNER_KEY, CANDIDATE_REVISION_KEY):
            if key in new_tree:
                del new_tree[key]
    discard_owner_ledger(node)
    _clear_ledger(node)
    _remove_unused(previous)
    _refresh_project_readiness()


def _copy_socket_value(value):
    try:
        return tuple(value)
    except TypeError:
        return value


def _restore_links(tree, node, incoming, outgoing):
    current = tuple(tree.links)
    for source, socket_name in incoming:
        target = node.inputs.get(socket_name)
        if target is None:
            raise RuntimeError(f"Replacement Grade lost input socket {socket_name}")
        if not any(link.from_socket == source and link.to_socket == target for link in current):
            tree.links.new(source, target)
    for socket_name, target in outgoing:
        source = node.outputs.get(socket_name)
        if source is None:
            raise RuntimeError(f"Replacement Grade lost output socket {socket_name}")
        if not any(link.from_socket == source and link.to_socket == target for link in current):
            tree.links.new(source, target)


def _dispose(candidate, kind):
    if kind == "grade":
        candidate.controller.dispose(unlink=True)
    else:
        images = candidate.images
        candidate.dispose(unlink=True)
        import bpy
        for image in images:
            if image.users == 0:
                bpy.data.images.remove(image, do_unlink=True)


def _remove_unused(tree):
    if tree is None or getattr(tree, "users", 1) != 0:
        return
    try:
        import bpy
        owned = []
        images = []

        def collect(group):
            pointer = _pointer(group)
            if pointer is None or pointer in {item[0] for item in owned}:
                return
            children = []
            for child in getattr(group, "nodes", ()):
                image = getattr(child, "image", None)
                if image is not None:
                    images.append(image)
                nested = getattr(child, "node_tree", None)
                if nested is not None:
                    children.append(nested)
            owned.append((pointer, group))
            for nested in children:
                collect(nested)

        collect(tree)
        bpy.data.node_groups.remove(tree, do_unlink=True)
        for _pointer_id, group in reversed(owned[1:]):
            if getattr(group, "users", 1) == 0:
                try:
                    bpy.data.node_groups.remove(group, do_unlink=True)
                except (ReferenceError, RuntimeError):
                    pass
        seen = set()
        for image in images:
            pointer = _pointer(image)
            if pointer is None or pointer in seen:
                continue
            seen.add(pointer)
            if getattr(image, "users", 1) == 0:
                try:
                    bpy.data.images.remove(image, do_unlink=True)
                except (ReferenceError, RuntimeError):
                    pass
    except (ReferenceError, RuntimeError):
        pass


def process_pending_updates():
    """Synchronously drain queued updates; useful for deterministic tests."""
    if _PUBLICATION_HOLDS:
        return ()
    failures = []
    while _PENDING or _JOBS:
        if _JOBS:
            key, (future, tree, node, kind, revision, settings, _previous) = next(iter(_JOBS.items()))
            try:
                prepared = future.result()
                if (key not in _PENDING
                        and int(node.get("perceptual_grade_next_edit_revision", -1)) == revision
                        and _pointer(tree) is not None and _pointer(node) is not None):
                    _install(tree, node, kind, revision, settings, prepared)
            except NativeAdmissionDeferred:
                break
            except BaseException as error:
                _JOBS.pop(key, None)
                _record_failure(node, error)
                failures.append(error)
            else:
                _JOBS.pop(key, None)
            continue
        key = next(iter(_PENDING))
        tree, node, kind, revision, settings, previous = _PENDING.pop(key)
        try:
            if (_pointer(tree) is None or _pointer(node) is None
                    or _key(tree, node) != key):
                continue
            if int(node.get("perceptual_grade_next_edit_revision", -1)) != revision:
                continue
            prepared = _prepare(kind, settings, previous)
            ledger = _read_ledger(node)
            if ledger is not None:
                _write_ledger(
                    node, kind=kind, revision=revision, stage="validated",
                    prior_revision=ledger.get("prior_revision", 0),
                    prior_settings=ledger.get("prior_settings", ""),
                )
            if int(node.get("perceptual_grade_next_edit_revision", -1)) == revision:
                _install(tree, node, kind, revision, settings, prepared)
        except NativeAdmissionDeferred:
            _PENDING[key] = (tree, node, kind, revision, settings, previous)
            break
        except BaseException as error:
            try:
                ledger = _read_ledger(node)
                if ledger is not None:
                    _write_ledger(
                        node, kind=ledger.get("kind", kind),
                        revision=ledger.get("revision", revision), stage="failed",
                        prior_revision=ledger.get("prior_revision", 0),
                        prior_settings=ledger.get("prior_settings", ""), error=error,
                    )
                node["perceptual_grade_next_preparation_state"] = "FAILED"
                node["perceptual_grade_next_preparation_error"] = str(error)[:512]
            except (ReferenceError, RuntimeError):
                pass
            failures.append(error)
    if _PENDING or _JOBS:
        return tuple(failures)
    global _TIMER_REGISTERED
    try:
        import bpy
        if bpy.app.timers.is_registered(_process_one):
            bpy.app.timers.unregister(_process_one)
    except (ImportError, ValueError, RuntimeError):
        pass
    _TIMER_REGISTERED = False
    if failures:
        return tuple(failures)
    return ()


def hold_publication(reason):
    if not reason:
        raise ValueError("publication hold requires an identity")
    _PUBLICATION_HOLDS.add(reason)


def release_publication(reason):
    _PUBLICATION_HOLDS.discard(reason)


def _record_failure(node, error):
    try:
        ledger = _read_ledger(node)
        if ledger is not None:
            _write_ledger(
                node, kind=ledger.get("kind", "unknown"),
                revision=ledger.get("revision", 0), stage="failed",
                prior_revision=ledger.get("prior_revision", 0),
                prior_settings=ledger.get("prior_settings", ""), error=error,
            )
        node["perceptual_grade_next_preparation_state"] = "FAILED"
        node["perceptual_grade_next_preparation_error"] = str(error)[:512]
    except (ReferenceError, RuntimeError):
        pass
    _refresh_project_readiness()


def _finish_job(key, job):
    future, tree, node, kind, revision, settings, _previous = job
    if not future.done():
        return False
    try:
        prepared = future.result()
        if (_pointer(tree) is not None and _pointer(node) is not None
                and _key(tree, node) == key
                and int(node.get("perceptual_grade_next_edit_revision", -1)) == revision):
            _install(tree, node, kind, revision, settings, prepared)
    except NativeAdmissionDeferred:
        return False
    except BaseException as error:
        if (_pointer(node) is not None
                and int(node.get("perceptual_grade_next_edit_revision", -1)) == revision):
            _record_failure(node, error)
    del _JOBS[key]
    return True


def _process_one():
    global _TIMER_REGISTERED
    _prune_live_owners()
    if _PUBLICATION_HOLDS:
        return 0.2
    for key, job in tuple(_JOBS.items()):
        _finish_job(key, job)
    for key, pending in tuple(_PENDING.items()):
        if key in _JOBS:
            continue
        tree, node, kind, revision, settings, previous = _PENDING.pop(key)
        if (_pointer(tree) is None or _pointer(node) is None
                or _key(tree, node) != key
                or int(node.get("perceptual_grade_next_edit_revision", -1)) != revision):
            continue
        future = _executor().submit(_prepare, kind, settings, previous)
        _JOBS[key] = (future, tree, node, kind, revision, settings, previous)
    if _PENDING or _JOBS:
        return 0.2
    _TIMER_REGISTERED = False
    return None


def cancel_pending_updates(*, clear_holds=True):
    """Forget queued Python callbacks during extension unregister."""
    global _TIMER_REGISTERED, _EXECUTOR
    _PENDING.clear()
    for future, *_rest in _JOBS.values():
        future.cancel()
    _JOBS.clear()
    _LIVE.clear()
    if clear_holds:
        _PUBLICATION_HOLDS.clear()
    try:
        import bpy
        if bpy.app.timers.is_registered(_process_one):
            bpy.app.timers.unregister(_process_one)
    except (ImportError, ValueError, RuntimeError):
        pass
    _TIMER_REGISTERED = False
    if _EXECUTOR is not None:
        _EXECUTOR.shutdown(wait=False, cancel_futures=True)
        _EXECUTOR = None


__all__ = ("cancel_pending_updates", "control_changed", "mark_node_dirty",
           "hold_publication", "process_pending_updates", "register_native_owner",
           "release_publication")
