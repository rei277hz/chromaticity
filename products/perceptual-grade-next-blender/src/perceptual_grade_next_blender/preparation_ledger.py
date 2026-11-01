"""Persistent per-owner backing for interrupted native publication."""

import hashlib
import json
import math
import uuid

import numpy as np


OWNER_ID_KEY = "perceptual_grade_next_preparation_owner"
LEDGER_OWNER_KEY = "perceptual_grade_next_preparation_ledger_owner"
LEDGER_TX_KEY = "perceptual_grade_next_preparation_ledger_transaction"
LEDGER_SLOT_KEY = "perceptual_grade_next_preparation_ledger_slot"
LEDGER_ROLE_KEY = "perceptual_grade_next_preparation_ledger_role"
LEDGER_DIGEST_KEY = "perceptual_grade_next_preparation_ledger_digest"
LEDGER_SCHEMA = 1
LEDGER_PREFIX = ".PG Next Preparation Recovery "
CANDIDATE_OWNER_KEY = "perceptual_grade_next_candidate_owner"
CANDIDATE_REVISION_KEY = "perceptual_grade_next_candidate_revision"
LEDGER_MODE_KEY = "perceptual_grade_next_preparation_ledger_mode"
LEDGER_SNAPSHOT_KEY = "perceptual_grade_next_preparation_ledger_snapshot"
LEDGER_COMMITTED_KEY = "perceptual_grade_next_preparation_ledger_committed"
LEDGER_DATA_KEY = "perceptual_grade_next_preparation_ledger_data"
LEDGER_SLOTS_KEY = "perceptual_grade_next_preparation_ledger_slots"
TREE_REPLACEMENT = "tree_replacement"
GRADE_UPDATE = "grade_update"
CANDIDATE_IMAGE_PREFIX = ".PG Next Candidate Image "


def _controls(owner_node):
    return (owner_node.perceptual_grade_next_controls
            if owner_node.get("perceptual_grade_next_backend") == "native_grade_graph"
            else owner_node.perceptual_grade_next_stack_controls)


def _socket_key(sockets, socket):
    return {"name": socket.name, "identifier": socket.identifier,
            "index": next(index for index, item in enumerate(sockets) if item == socket)}


def _socket(sockets, descriptor):
    identifier = descriptor.get("identifier", "")
    for socket in sockets:
        if identifier and socket.identifier == identifier:
            return socket
    index = descriptor.get("index", -1)
    if 0 <= index < len(sockets) and sockets[index].name == descriptor.get("name"):
        return sockets[index]
    socket = sockets.get(descriptor.get("name", ""))
    if socket is None:
        raise RuntimeError("Preparation recovery socket is missing")
    return socket


def _link_snapshot(host_tree, owner_node):
    links = []
    for link in host_tree.links:
        if link.from_node != owner_node and link.to_node != owner_node:
            continue
        links.append({
            "from_node": None if link.from_node == owner_node else link.from_node.name,
            "from_socket": _socket_key(link.from_node.outputs, link.from_socket),
            "to_node": None if link.to_node == owner_node else link.to_node.name,
            "to_socket": _socket_key(link.to_node.inputs, link.to_socket),
        })
    return links


def tree_backing(owner_node):
    """Return the real retained replacement ledger, including without JSON marker."""
    ledger = _controls(owner_node).preparation_ledger
    if ledger is not None and ledger.get(LEDGER_MODE_KEY) == TREE_REPLACEMENT:
        return ledger
    return None


def retained_backing(owner_node):
    """Return any persistent recovery ledger still owned by this control set."""
    return _controls(owner_node).preparation_ledger


def field_backing(owner_node):
    """Return a retained packed-field ledger even when its JSON marker is gone."""
    ledger = _controls(owner_node).preparation_ledger
    if ledger is None or ledger.get(LEDGER_MODE_KEY) == TREE_REPLACEMENT:
        return None
    if ledger.get(LEDGER_MODE_KEY) == GRADE_UPDATE:
        return ledger
    roles = {node.get(LEDGER_ROLE_KEY, "") for node in ledger.nodes}
    if "backup" not in roles or "target" not in roles:
        return None
    return ledger


def field_backing_data(owner_node):
    ledger = field_backing(owner_node)
    if ledger is None:
        return None
    try:
        slots = tuple(json.loads(ledger.get(LEDGER_SLOTS_KEY, "[]")))
    except (TypeError, ValueError, json.JSONDecodeError):
        slots = tuple(node.get(LEDGER_SLOT_KEY, "") for node in ledger.nodes
                      if node.get(LEDGER_ROLE_KEY, "") == "backup")
    transaction = ledger.get(LEDGER_TX_KEY, "")
    try:
        data = json.loads(ledger.get(LEDGER_DATA_KEY, "{}"))
    except (TypeError, ValueError, json.JSONDecodeError):
        data = {}
    data.update({
        "backup_transaction": transaction,
        "backup_slots": slots,
        "transaction_id": data.get("transaction_id") or transaction,
        "kind": "grade",
    })
    return data


def stage_tree_backing(host_tree, owner_node, prior_tree, candidate_tree,
                       transaction, *, defaults, properties):
    """Retain both real tree IDs and a serialized owner snapshot before a swap."""
    import bpy

    controls = _controls(owner_node)
    if controls.preparation_ledger is not None:
        raise RuntimeError("Owner already retains a preparation recovery ledger")
    if prior_tree is None or candidate_tree is None or prior_tree == candidate_tree:
        raise RuntimeError("Replacement recovery needs distinct prior and candidate trees")
    owner = owner_id(owner_node)
    ledger = bpy.data.node_groups.new(LEDGER_PREFIX + owner[:12], host_tree.bl_idname)
    try:
        ledger["perceptual_grade_next_preparation_ledger_schema"] = LEDGER_SCHEMA
        ledger[LEDGER_OWNER_KEY] = owner
        ledger[LEDGER_TX_KEY] = transaction
        ledger[LEDGER_MODE_KEY] = TREE_REPLACEMENT
        ledger[LEDGER_COMMITTED_KEY] = False
        ledger[LEDGER_SNAPSHOT_KEY] = json.dumps({
            "defaults": defaults, "properties": properties,
            "links": _link_snapshot(host_tree, owner_node),
        }, sort_keys=True, separators=(",", ":"))
        node_type = ("ShaderNodeGroup" if host_tree.bl_idname == "ShaderNodeTree"
                     else "CompositorNodeGroup")
        for role, group in (("prior_tree", prior_tree), ("candidate_tree", candidate_tree)):
            reference = ledger.nodes.new(node_type)
            reference.hide = True
            reference[LEDGER_ROLE_KEY] = role
            reference.node_tree = group
            if reference.node_tree != group:
                raise RuntimeError("Replacement recovery tree reference was rejected")
        # This serialized PointerProperty is the lifetime root for both trees.
        controls.preparation_ledger = ledger
        if controls.preparation_ledger != ledger:
            raise RuntimeError("Replacement recovery ledger was not retained")
        return transaction
    except BaseException:
        if controls.preparation_ledger == ledger:
            controls.preparation_ledger = None
        bpy.data.node_groups.remove(ledger, do_unlink=True)
        raise


def _tree_references(ledger):
    references = {}
    for node in ledger.nodes:
        role = node.get(LEDGER_ROLE_KEY, "")
        if role in {"prior_tree", "candidate_tree"}:
            if role in references or getattr(node, "node_tree", None) is None:
                raise RuntimeError("Replacement recovery tree references are incomplete")
            references[role] = node.node_tree
    if set(references) != {"prior_tree", "candidate_tree"}:
        raise RuntimeError("Replacement recovery tree references are incomplete")
    return references


def _validate_tree_interface(tree, direction, descriptor):
    items = tuple(
        item for item in getattr(getattr(tree, "interface", None), "items_tree", ())
        if getattr(item, "item_type", "SOCKET") == "SOCKET"
        and getattr(item, "in_out", "") == direction
    )
    identifier = descriptor.get("identifier", "")
    matches = ([item for item in items if getattr(item, "identifier", "") == identifier]
               if identifier else [])
    if not matches:
        index = descriptor.get("index", -1)
        if 0 <= index < len(items) and items[index].name == descriptor.get("name"):
            matches = [items[index]]
    if len(matches) != 1 or matches[0].name != descriptor.get("name"):
        raise RuntimeError("Preparation recovery prior tree interface is incompatible")


def _validate_tree_snapshot(host_tree, owner_node, prior_tree, snapshot):
    if (not isinstance(snapshot, dict)
            or set(snapshot) != {"defaults", "properties", "links"}):
        raise RuntimeError("Preparation recovery snapshot is incomplete")
    defaults = snapshot["defaults"]
    properties = snapshot["properties"]
    links = snapshot["links"]
    if not isinstance(defaults, dict) or not isinstance(properties, dict):
        raise RuntimeError("Preparation recovery snapshot is malformed")
    defaults_plan = []
    for name, value in defaults.items():
        if (not isinstance(name, str) or not name or not _valid_json_value(value)):
            raise RuntimeError("Preparation recovery input default is malformed")
        socket = owner_node.inputs.get(name)
        if socket is None or not hasattr(socket, "default_value"):
            raise RuntimeError("Preparation recovery input default is missing")
        descriptor = _socket_key(owner_node.inputs, socket)
        _validate_tree_interface(prior_tree, "INPUT", descriptor)
        current = socket.default_value
        if (not isinstance(current, (str, bytes)) and hasattr(current, "__len__")
                and len(current)):
            if not isinstance(value, (list, tuple)) or len(value) != len(current):
                raise RuntimeError("Preparation recovery input default has the wrong arity")
            value = tuple(value)
        elif isinstance(value, (list, tuple)):
            raise RuntimeError("Preparation recovery scalar default has the wrong shape")
        defaults_plan.append((name, descriptor, value))

    properties_plan = []
    for key, entry in properties.items():
        if (not isinstance(key, str) or not key
                or not isinstance(entry, (tuple, list)) or len(entry) != 2
                or type(entry[0]) is not bool or not _valid_json_value(entry[1])):
            raise RuntimeError("Preparation recovery property snapshot is malformed")
        properties_plan.append((key, entry[0], entry[1]))

    if not isinstance(links, list):
        raise RuntimeError("Preparation recovery links are malformed")
    links_plan = []
    seen = set()
    for link in links:
        if (not isinstance(link, dict)
                or set(link) != {"from_node", "from_socket", "to_node", "to_socket"}
                or (link["from_node"] is not None
                    and (not isinstance(link["from_node"], str) or not link["from_node"]))
                or (link["to_node"] is not None
                    and (not isinstance(link["to_node"], str) or not link["to_node"]))):
            raise RuntimeError("Preparation recovery link snapshot is malformed")
        source_node = (owner_node if link["from_node"] is None
                       else host_tree.nodes.get(link["from_node"]))
        target_node = (owner_node if link["to_node"] is None
                       else host_tree.nodes.get(link["to_node"]))
        if source_node is None or target_node is None:
            raise RuntimeError("Preparation recovery link endpoint is missing")
        source = _validated_socket(source_node.outputs, link["from_socket"])
        target = _validated_socket(target_node.inputs, link["to_socket"])
        if source_node == owner_node:
            _validate_tree_interface(prior_tree, "OUTPUT", link["from_socket"])
        if target_node == owner_node:
            _validate_tree_interface(prior_tree, "INPUT", link["to_socket"])
        identity = (
            link["from_node"], link["from_socket"]["identifier"],
            link["from_socket"]["index"], link["to_node"],
            link["to_socket"]["identifier"], link["to_socket"]["index"],
        )
        if identity in seen:
            raise RuntimeError("Preparation recovery link snapshot is duplicated")
        seen.add(identity)
        links_plan.append((source_node, link["from_socket"], source,
                           target_node, link["to_socket"], target))
    return defaults_plan, properties_plan, links_plan


def _validate_replacement_candidate(owner_node, candidate):
    if owner_node.node_tree != candidate:
        raise RuntimeError("Replacement recovery candidate is not installed")
    edit = owner_node.get("perceptual_grade_next_edit_revision", -1)
    applied = owner_node.get("perceptual_grade_next_applied_revision", -1)
    if (type(edit) is not int or edit < 0 or applied != edit
            or owner_node.get("perceptual_grade_next_preparation_state") != "READY"):
        raise RuntimeError("Replacement candidate publication metadata is not ready")
    backend = owner_node.get("perceptual_grade_next_backend")
    if backend == "native_grade_graph":
        from .project_readiness import _validate_grade
        group, _manifest = _validate_grade(owner_node, check_ledger=False)
    elif backend == "native_stack_lut":
        from .project_readiness import _validate_stack
        group, _manifest, _preview, final_ready, _content = _validate_stack(
            owner_node, check_ledger=False,
        )
        if not final_ready:
            raise RuntimeError("Replacement Stack candidate has no accepted final LUT")
    else:
        raise RuntimeError("Replacement candidate backend is unsupported")
    if group != candidate:
        raise RuntimeError("Replacement candidate manifest describes another tree")


def commit_tree_backing(owner_node, transaction):
    """Record acceptance only after the full native binding has committed."""
    _controls_value, ledger = _ledger_for(owner_node, owner_node.get(OWNER_ID_KEY, ""), transaction)
    if ledger is None or ledger.get(LEDGER_MODE_KEY) != TREE_REPLACEMENT:
        raise RuntimeError("Replacement recovery ledger is missing")
    _validate_replacement_candidate(
        owner_node, _tree_references(ledger)["candidate_tree"],
    )
    ledger[LEDGER_COMMITTED_KEY] = True
    if ledger.get(LEDGER_COMMITTED_KEY) is not True:
        ledger[LEDGER_COMMITTED_KEY] = False
        raise RuntimeError("Replacement recovery commit marker did not persist")


def restore_tree_backing(host_tree, owner_node, ledger_data=None):
    """Restore an uncommitted swap; a failed repair retains every real reference."""
    retained = tree_backing(owner_node)
    if retained is None:
        return False
    transaction = retained.get(LEDGER_TX_KEY, "")
    _controls_value, ledger = _ledger_for(owner_node, owner_node.get(OWNER_ID_KEY, ""), transaction)
    references = _tree_references(ledger)
    if ledger.get(LEDGER_COMMITTED_KEY, False):
        if owner_node.node_tree != references["candidate_tree"]:
            raise RuntimeError("Committed replacement binding does not match its ledger")
        _validate_replacement_candidate(owner_node, references["candidate_tree"])
    else:
        try:
            snapshot = json.loads(ledger[LEDGER_SNAPSHOT_KEY])
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise RuntimeError("Preparation recovery snapshot is malformed") from error
        defaults_plan, properties_plan, links_plan = _validate_tree_snapshot(
            host_tree, owner_node, references["prior_tree"], snapshot,
        )
        owner_node.node_tree = references["prior_tree"]
        if owner_node.node_tree != references["prior_tree"]:
            raise RuntimeError("Preparation recovery did not restore the prior tree")
        for name, descriptor, value in defaults_plan:
            socket = _validated_socket(owner_node.inputs, descriptor)
            socket.default_value = value
        for link in tuple(host_tree.links):
            if link.from_node == owner_node or link.to_node == owner_node:
                host_tree.links.remove(link)
        restored_links = []
        for source_node, source_descriptor, _source, target_node, target_descriptor, _target in links_plan:
            source = _validated_socket(source_node.outputs, source_descriptor)
            target = _validated_socket(target_node.inputs, target_descriptor)
            host_tree.links.new(source, target)
            restored_links.append((source, target))
        for key, present, value in properties_plan:
            if present:
                owner_node[key] = value
            elif key in owner_node:
                del owner_node[key]
        if (len(restored_links) != sum(
                link.from_node == owner_node or link.to_node == owner_node
                for link in host_tree.links)
                or not all(any(link.from_socket == source and link.to_socket == target
                               for link in host_tree.links)
                           for source, target in restored_links)):
            raise RuntimeError("Preparation recovery links did not restore")
        for key, present, value in properties_plan:
            if (key in owner_node) != present or (present and owner_node.get(key) != value):
                raise RuntimeError("Preparation recovery property did not restore")
        for name, descriptor, value in defaults_plan:
            if _json_value(_validated_socket(owner_node.inputs, descriptor).default_value) != _json_value(value):
                raise RuntimeError("Preparation recovery input default did not restore")
    # Nothing above releases the ledger: exceptions retain repair debt.
    discard_owner_ledger(owner_node)
    return True


def owner_id(node):
    value = node.get(OWNER_ID_KEY, "")
    if value:
        return value
    value = uuid.uuid4().hex
    node[OWNER_ID_KEY] = value
    return value


def digest(values):
    array = np.asarray(values, dtype=np.float32)
    return hashlib.sha256(array.tobytes(order="C")).hexdigest()


def _json_value(value):
    try:
        value = tuple(value)
    except TypeError:
        pass
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    raise TypeError("Native Grade recovery snapshot contains an unsupported value")


def _native_grade_snapshot(host_tree, owner_node, native):
    graph = native.controller._graph
    bindings = []
    native_tree = getattr(native, "tree", None) or getattr(owner_node, "node_tree", None)
    for _value, target, _previous in getattr(graph, "bindings", ()):
        target_node = target.node
        incoming = ([link for link in native_tree.links if link.to_socket == target]
                    if native_tree is not None else [])
        if len(incoming) > 1:
            raise RuntimeError("Native Grade binding has multiple incoming links")
        bindings.append({
            "target_node": target_node.name,
            "target_socket": _socket_key(target_node.inputs, target),
            "default": _json_value(target.default_value),
            "sources": ([{
                "node": incoming[0].from_node.name,
                "socket": _socket_key(incoming[0].from_node.outputs,
                                      incoming[0].from_socket),
            }] if incoming else []),
        })
    owner_keys = (
        "perceptual_grade_next_settings",
        "perceptual_grade_next_applied_revision",
        "perceptual_grade_next_edit_revision",
        "perceptual_grade_next_preparation_state",
        "perceptual_grade_next_preparation_error",
        "perceptual_grade_next_accepted_grade_manifest",
    )
    return {
        "tree_properties": {
            key: (key in native_tree, native_tree.get(key))
            for key in ("perceptual_grade_next_settings",
                        "perceptual_grade_nodes_revision")
        } if native_tree is not None else {},
        "owner_properties": {
            key: (key in owner_node, owner_node.get(key)) for key in owner_keys
        },
        "bindings": bindings,
        "host_defaults": {
            socket.name: _json_value(socket.default_value)
            for socket in owner_node.inputs if hasattr(socket, "default_value")
        },
        "host_links": _link_snapshot(host_tree, owner_node),
    }


_TREE_PROPERTY_KEYS = frozenset((
    "perceptual_grade_next_settings", "perceptual_grade_nodes_revision",
))
_OWNER_PROPERTY_KEYS = frozenset((
    "perceptual_grade_next_settings",
    "perceptual_grade_next_applied_revision",
    "perceptual_grade_next_edit_revision",
    "perceptual_grade_next_preparation_state",
    "perceptual_grade_next_preparation_error",
    "perceptual_grade_next_accepted_grade_manifest",
))


def _valid_json_value(value):
    if value is None or type(value) in (bool, int, str):
        return True
    if type(value) is float:
        return math.isfinite(value)
    if isinstance(value, list):
        return all(_valid_json_value(item) for item in value)
    if isinstance(value, dict):
        return all(type(key) is str and _valid_json_value(item)
                   for key, item in value.items())
    return False


def _validated_socket(sockets, descriptor):
    if (not isinstance(descriptor, dict)
            or set(descriptor) != {"name", "identifier", "index"}
            or not isinstance(descriptor["name"], str)
            or not isinstance(descriptor["identifier"], str)
            or type(descriptor["index"]) is not int
            or descriptor["index"] < 0):
        raise RuntimeError("Grade recovery snapshot has an invalid socket descriptor")
    return _socket(sockets, descriptor)


def _validate_grade_snapshot(native_tree, owner_node, snapshot):
    """Validate and resolve every snapshot field before recovery mutates RNA."""
    required = {"tree_properties", "owner_properties", "bindings",
                "host_defaults", "host_links"}
    if not isinstance(snapshot, dict) or set(snapshot) != required:
        raise RuntimeError("Grade preparation recovery snapshot is incomplete")

    tree_properties = snapshot["tree_properties"]
    owner_properties = snapshot["owner_properties"]
    if (not isinstance(tree_properties, dict)
            or set(tree_properties) != _TREE_PROPERTY_KEYS
            or not isinstance(owner_properties, dict)
            or set(owner_properties) != _OWNER_PROPERTY_KEYS):
        raise RuntimeError("Grade preparation recovery properties are incomplete")
    for properties in (tree_properties, owner_properties):
        for entry in properties.values():
            if not isinstance(entry, (list, tuple)) or len(entry) != 2:
                raise RuntimeError("Grade preparation recovery property is malformed")
            present, value = entry
            if type(present) is not bool or not _valid_json_value(value):
                raise RuntimeError("Grade preparation recovery property is malformed")

    bindings = snapshot["bindings"]
    if not isinstance(bindings, list) or not bindings:
        raise RuntimeError("Grade preparation recovery bindings are incomplete")
    binding_plan = []
    seen_targets = set()
    for binding in bindings:
        if (not isinstance(binding, dict)
                or set(binding) != {"target_node", "target_socket", "default", "sources"}
                or not isinstance(binding["target_node"], str)
                or not binding["target_node"]
                or not _valid_json_value(binding["default"])
                or not isinstance(binding["sources"], list)
                or len(binding["sources"]) > 1):
            raise RuntimeError("Grade preparation recovery binding is malformed")
        target_node = native_tree.nodes.get(binding["target_node"])
        if target_node is None:
            raise RuntimeError("Native Grade recovery target node is missing")
        target = _validated_socket(target_node.inputs, binding["target_socket"])
        target_key = (target_node.name, target.identifier, target.name)
        if target_key in seen_targets:
            raise RuntimeError("Grade preparation recovery binding is duplicated")
        seen_targets.add(target_key)
        sources = []
        for source in binding["sources"]:
            if (not isinstance(source, dict)
                    or set(source) != {"node", "socket"}
                    or not isinstance(source["node"], str) or not source["node"]):
                raise RuntimeError("Grade preparation recovery source is malformed")
            source_node = native_tree.nodes.get(source["node"])
            if source_node is None:
                raise RuntimeError("Native Grade recovery source node is missing")
            sources.append(_validated_socket(source_node.outputs, source["socket"]))
        current = target.default_value
        try:
            if not isinstance(current, (str, bytes)) and len(current):
                default = tuple(binding["default"])
                if len(current) != len(default):
                    raise RuntimeError("Grade recovery default has the wrong arity")
            else:
                default = binding["default"]
        except TypeError:
            default = binding["default"]
        binding_plan.append((target, default, tuple(sources)))

    host_defaults = snapshot["host_defaults"]
    if (not isinstance(host_defaults, dict)
            or any(not isinstance(name, str) or not name
                   or not _valid_json_value(value)
                   for name, value in host_defaults.items())):
        raise RuntimeError("Grade owner recovery defaults are malformed")
    defaults_plan = []
    for name, value in host_defaults.items():
        socket = owner_node.inputs.get(name)
        if socket is None or not hasattr(socket, "default_value"):
            raise RuntimeError("Grade owner input default is missing during recovery")
        current = socket.default_value
        try:
            if not isinstance(current, (str, bytes)) and len(current):
                value = tuple(value)
                if len(current) != len(value):
                    raise RuntimeError("Grade owner recovery default has the wrong arity")
        except TypeError:
            pass
        defaults_plan.append((socket, value))

    host_tree = owner_node.id_data
    host_links = snapshot["host_links"]
    if not isinstance(host_links, list):
        raise RuntimeError("Grade owner recovery links are malformed")
    host_link_plan = []
    for link in host_links:
        if (not isinstance(link, dict)
                or set(link) != {"from_node", "from_socket", "to_node", "to_socket"}
                or (link["from_node"] is not None
                    and (not isinstance(link["from_node"], str) or not link["from_node"]))
                or (link["to_node"] is not None
                    and (not isinstance(link["to_node"], str) or not link["to_node"]))):
            raise RuntimeError("Grade owner recovery link is malformed")
        source_node = (owner_node if link["from_node"] is None
                       else host_tree.nodes.get(link["from_node"]))
        target_node = (owner_node if link["to_node"] is None
                       else host_tree.nodes.get(link["to_node"]))
        if source_node is None or target_node is None:
            raise RuntimeError("Grade owner host link endpoint is missing")
        host_link_plan.append((
            _validated_socket(source_node.outputs, link["from_socket"]),
            _validated_socket(target_node.inputs, link["to_socket"]),
        ))
    return tree_properties, owner_properties, binding_plan, defaults_plan, host_link_plan


def _restore_native_grade_snapshot(native_tree, owner_node, snapshot, plan=None):
    tree_properties, owner_properties, bindings, host_defaults, host_links = (
        _validate_grade_snapshot(native_tree, owner_node, snapshot)
        if plan is None else plan
    )

    for key, (present, value) in tree_properties.items():
        if present:
            native_tree[key] = value
        elif key in native_tree:
            del native_tree[key]
    for key, (present, value) in owner_properties.items():
        if present:
            owner_node[key] = value
        elif key in owner_node:
            del owner_node[key]

    for target, default, sources in bindings:
        for link in tuple(native_tree.links):
            if link.to_socket == target:
                native_tree.links.remove(link)
        target.default_value = default
        for source in sources:
            native_tree.links.new(source, target)

    for target, default, sources in bindings:
        actual = [link for link in native_tree.links if link.to_socket == target]
        if len(actual) != len(sources):
            raise RuntimeError("Native Grade binding recovery readback failed")
        for link, source in zip(actual, sources):
            if link.from_socket != source:
                raise RuntimeError("Native Grade link recovery readback failed")
        if _json_value(target.default_value) != _json_value(default):
            raise RuntimeError("Native Grade default recovery readback failed")

    for socket, value in host_defaults:
        socket.default_value = value

    host_tree = owner_node.id_data
    for link in tuple(host_tree.links):
        if link.from_node == owner_node or link.to_node == owner_node:
            host_tree.links.remove(link)
    for source, target in host_links:
        host_tree.links.new(source, target)
    if not all(any(link.from_socket == source and link.to_socket == target
                   for link in host_tree.links) for source, target in host_links):
        raise RuntimeError("Grade owner host links did not restore")
    for socket, value in host_defaults:
        if _json_value(socket.default_value) != _json_value(value):
            raise RuntimeError("Grade owner input default recovery readback failed")


def stage_grade_backing(host_tree, owner_node, native, prepared, transaction,
                        ledger_data=None):
    """Persist all prior Grade state before an in-place native publication."""
    slots = []
    for name, (_initial_table, image) in native.controller._graph.image_slots.items():
        old_table = (native.controller.prepared.table if name == "tone"
                     else getattr(native.controller.prepared.color, name))
        new_table = prepared.table if name == "tone" else getattr(prepared.color, name)
        if new_table is not old_table:
            slots.append((name, image))
    import bpy

    owner = owner_id(owner_node)
    ledger = bpy.data.node_groups.new(
        LEDGER_PREFIX + owner[:12], host_tree.bl_idname,
    )
    created = []
    try:
        ledger["perceptual_grade_next_preparation_ledger_schema"] = LEDGER_SCHEMA
        ledger["perceptual_grade_next_preparation_ledger_owner"] = owner
        ledger["perceptual_grade_next_preparation_ledger_transaction"] = transaction
        ledger[LEDGER_MODE_KEY] = GRADE_UPDATE
        ledger[LEDGER_SLOTS_KEY] = json.dumps(
            [name for name, _image in slots], separators=(",", ":"),
        )
        backing_data = dict(ledger_data or {})
        backing_data["grade_snapshot"] = _native_grade_snapshot(
            host_tree, owner_node, native,
        )
        ledger[LEDGER_DATA_KEY] = json.dumps(
            backing_data, sort_keys=True, separators=(",", ":"),
        )
        for name, source in slots:
            width, height = map(int, source.size)
            backup = bpy.data.images.new(
                LEDGER_PREFIX + "Image " + owner[:12] + " "
                + transaction[:8] + " " + name,
                width=width, height=height,
                alpha=True, float_buffer=True,
            )
            created.append(backup)
            backup[LEDGER_OWNER_KEY] = owner
            backup[LEDGER_TX_KEY] = transaction
            backup[LEDGER_SLOT_KEY] = name
            backup[LEDGER_ROLE_KEY] = "backup"
            backup.colorspace_settings.name = "Non-Color"
            backup.alpha_mode = "CHANNEL_PACKED"
            backup.use_half_precision = False
            pixels = np.empty(len(source.pixels), dtype=np.float32)
            source.pixels.foreach_get(pixels)
            expected = digest(pixels)
            backup.pixels.foreach_set(pixels)
            backup.update()
            backup.pack()
            readback = np.empty(len(backup.pixels), dtype=np.float32)
            backup.pixels.foreach_get(readback)
            if (not backup.packed_file or backup.use_half_precision
                    or digest(readback) != expected):
                raise RuntimeError(f"Grade recovery backing failed readback: {name}")
            backup[LEDGER_DIGEST_KEY] = expected
            node_type = ("ShaderNodeTexImage" if host_tree.bl_idname == "ShaderNodeTree"
                         else "CompositorNodeImage")
            backup_node = ledger.nodes.new(node_type)
            backup_node.hide = True
            backup_node.image = backup
            backup_node[LEDGER_SLOT_KEY] = name
            backup_node[LEDGER_ROLE_KEY] = "backup"
            target_node = ledger.nodes.new(node_type)
            target_node.hide = True
            target_node.image = source
            target_node[LEDGER_SLOT_KEY] = name
            target_node[LEDGER_ROLE_KEY] = "target"

        controls = (owner_node.perceptual_grade_next_controls
                    if owner_node.get("perceptual_grade_next_backend") == "native_grade_graph"
                    else owner_node.perceptual_grade_next_stack_controls)
        if controls.preparation_ledger is not None:
            raise RuntimeError("Owner already retains a preparation recovery ledger")
        controls.preparation_ledger = ledger
        ledger.name = LEDGER_PREFIX + owner[:12] + " " + transaction[:8]
        return transaction, tuple(name for name, _image in slots)
    except BaseException:
        try:
            controls = (owner_node.perceptual_grade_next_controls
                        if owner_node.get("perceptual_grade_next_backend") == "native_grade_graph"
                        else owner_node.perceptual_grade_next_stack_controls)
            if controls.preparation_ledger == ledger:
                controls.preparation_ledger = None
        except (AttributeError, ReferenceError, RuntimeError):
            pass
        try:
            bpy.data.node_groups.remove(ledger, do_unlink=True)
        except (ReferenceError, RuntimeError):
            pass
        for image in created:
            if image.users == 0:
                try:
                    bpy.data.images.remove(image, do_unlink=True)
                except (ReferenceError, RuntimeError):
                    pass
        raise


def _ledger_for(owner_node, owner, transaction):
    controls = (owner_node.perceptual_grade_next_controls
                if owner_node.get("perceptual_grade_next_backend") == "native_grade_graph"
                else owner_node.perceptual_grade_next_stack_controls)
    ledger = controls.preparation_ledger
    if ledger is None:
        return controls, None
    ledger_owner = ledger.get(LEDGER_OWNER_KEY)
    if not owner and ledger_owner:
        owner = ledger_owner
        owner_node[OWNER_ID_KEY] = owner
    if (ledger.get("perceptual_grade_next_preparation_ledger_schema") != LEDGER_SCHEMA
            or ledger_owner != owner
            or ledger.get(LEDGER_TX_KEY) != transaction):
        raise RuntimeError("Grade preparation recovery ledger identity mismatch")
    return controls, ledger


def _ledger_images(ledger):
    images = {}
    for node in ledger.nodes:
        image = getattr(node, "image", None)
        if image is None:
            continue
        try:
            pointer = image.as_pointer()
        except (AttributeError, ReferenceError, RuntimeError) as error:
            raise RuntimeError("Preparation ledger contains an invalid Image reference") from error
        if not pointer:
            raise RuntimeError("Preparation ledger Image has no stable identity")
        entry = images.setdefault(pointer, [image, set(), 0])
        entry[1].add(node.get(LEDGER_ROLE_KEY, ""))
        entry[2] += 1
    return tuple((image, frozenset(roles), references)
                 for image, roles, references in images.values())


def _discard_backup_images(ledger):
    import bpy

    for image, roles, references in _ledger_images(ledger):
        if "backup" not in roles or "target" in roles:
            continue
        if image.users > references + int(bool(image.use_fake_user)):
            continue
        pointer = image.as_pointer()
        bpy.data.images.remove(image, do_unlink=True)
        if any(getattr(node, "image", None) is not None
               and node.image.as_pointer() == pointer for node in ledger.nodes):
            raise RuntimeError("Preparation ledger Image unlink did not complete")
        if any(item.as_pointer() == pointer for item in bpy.data.images):
            raise RuntimeError("Preparation ledger Image removal did not complete")


def _retire_owner_ledger(owner_node, controls, ledger):
    import bpy
    ledger_pointer = ledger.as_pointer()

    controls.preparation_ledger = None
    if controls.preparation_ledger is not None:
        raise RuntimeError("Preparation ledger pointer did not clear")
    if ledger.users == 0:
        try:
            bpy.data.node_groups.remove(ledger, do_unlink=True)
        except BaseException as error:
            try:
                controls.preparation_ledger = ledger
            except BaseException as retain_error:
                owner_node["perceptual_grade_next_preparation_state"] = "FAILED"
                owner_node["perceptual_grade_next_preparation_error"] = (
                    "Preparation cleanup failed and its ledger could not be retained"
                )
                raise RuntimeError("Preparation cleanup debt could not be retained") from retain_error
            if controls.preparation_ledger != ledger:
                raise RuntimeError("Preparation cleanup ledger readback failed") from error
            raise RuntimeError("Preparation ledger removal failed; retry is required") from error
        if any(item.as_pointer() == ledger_pointer for item in bpy.data.node_groups):
            try:
                controls.preparation_ledger = ledger
            except BaseException:
                owner_node["perceptual_grade_next_preparation_state"] = "FAILED"
                owner_node["perceptual_grade_next_preparation_error"] = (
                    "Preparation cleanup readback failed"
                )
            raise RuntimeError("Preparation ledger removal readback failed")


def discard_grade_backing(owner_node, transaction):
    if not transaction:
        return False
    import bpy

    owner = owner_node.get(OWNER_ID_KEY, "")
    controls, ledger = _ledger_for(owner_node, owner, transaction)
    if ledger is None:
        return False
    _discard_backup_images(ledger)
    _retire_owner_ledger(owner_node, controls, ledger)
    return True


def discard_owner_ledger(owner_node):
    """Drop a staged ledger when no live field mutation was authorized."""
    backend = owner_node.get("perceptual_grade_next_backend")
    try:
        controls = (owner_node.perceptual_grade_next_controls
                    if backend == "native_grade_graph"
                    else owner_node.perceptual_grade_next_stack_controls)
        ledger = controls.preparation_ledger
    except (AttributeError, ReferenceError, RuntimeError):
        return False
    if ledger is None:
        return False
    import bpy

    _discard_backup_images(ledger)
    _retire_owner_ledger(owner_node, controls, ledger)
    return True


def restore_grade_backing(host_tree, owner_node, ledger_data):
    """Restore packed fields and binding metadata from an interrupted Grade edit."""
    import bpy

    retained = field_backing_data(owner_node)
    if retained is not None:
        # The real retained NodeTree and its packed images are the durable
        # authority. JSON is only a progress hint and may be absent or stale.
        merged = dict(ledger_data or {})
        merged.update(retained)
        ledger_data = merged
    if not isinstance(ledger_data, dict):
        raise RuntimeError("Grade preparation recovery metadata is malformed")
    owner = owner_node.get(OWNER_ID_KEY, "")
    transaction = ledger_data.get("backup_transaction", "")
    if not isinstance(transaction, str) or not transaction:
        raise RuntimeError("Grade preparation recovery transaction is missing")
    controls = _controls(owner_node)
    ledger = controls.preparation_ledger
    if ledger is None:
        raise RuntimeError("Grade preparation recovery backing is missing")
    ledger_owner = ledger.get(LEDGER_OWNER_KEY, "")
    if (ledger.get("perceptual_grade_next_preparation_ledger_schema") != LEDGER_SCHEMA
            or not ledger_owner or (owner and owner != ledger_owner)
            or ledger.get(LEDGER_TX_KEY) != transaction
            or ledger.get(LEDGER_MODE_KEY) == TREE_REPLACEMENT):
        raise RuntimeError("Grade preparation recovery ledger identity mismatch")
    owner = ledger_owner

    # Both the redundant marker and the durable ledger must describe the same
    # complete slot inventory. Never infer a damaged inventory and then restore
    # only the subset that happens to remain.
    try:
        slots = json.loads(ledger.get(LEDGER_SLOTS_KEY, ""))
    except (TypeError, ValueError, json.JSONDecodeError) as error:
        raise RuntimeError("Grade preparation recovery slot inventory is malformed") from error
    if (not isinstance(slots, list)
            or any(not isinstance(slot, str) or not slot for slot in slots)
            or len(set(slots)) != len(slots)
            or not isinstance(ledger_data.get("backup_slots"), (list, tuple))
            or tuple(ledger_data["backup_slots"]) != tuple(slots)):
        raise RuntimeError("Grade preparation recovery slot inventory is incomplete")

    backups, targets = {}, {}
    for node in ledger.nodes:
        image = getattr(node, "image", None)
        slot = node.get(LEDGER_SLOT_KEY, "")
        role = node.get(LEDGER_ROLE_KEY, "")
        if (image is None or not slot or slot not in slots
                or role not in {"target", "backup"}):
            raise RuntimeError("Grade preparation recovery field has no role")
        if role == "target":
            if slot in targets:
                raise RuntimeError(f"Duplicate Grade recovery target field: {slot}")
            targets[slot] = image
        else:
            if slot in backups:
                raise RuntimeError(f"Duplicate Grade recovery backup field: {slot}")
            if (image.get(LEDGER_OWNER_KEY) != owner
                    or image.get(LEDGER_TX_KEY) != transaction
                    or image.get(LEDGER_SLOT_KEY) != slot
                    or image.get(LEDGER_ROLE_KEY) != "backup"
                    or not image.packed_file or image.use_half_precision
                    or image.colorspace_settings.name != "Non-Color"):
                raise RuntimeError("Grade preparation recovery backing is invalid")
            pixels = np.empty(len(image.pixels), dtype=np.float32)
            image.pixels.foreach_get(pixels)
            if digest(pixels) != image.get(LEDGER_DIGEST_KEY, ""):
                raise RuntimeError(f"Grade recovery backing digest failed: {slot}")
            backups[slot] = (image, pixels)

    if set(slots) != set(backups) or set(slots) != set(targets):
        raise RuntimeError("Grade preparation recovery backing is incomplete")
    for slot in slots:
        backup_image, pixels = backups[slot]
        target = targets[slot]
        if (tuple(target.size) != tuple(backup_image.size)
                or len(target.pixels) != len(pixels)):
            raise RuntimeError(f"Grade preparation field layout changed: {slot}")

    snapshot = ledger_data.get("grade_snapshot")
    native_tree = owner_node.node_tree
    if snapshot is None or native_tree is None:
        raise RuntimeError("Grade preparation recovery snapshot is missing")
    snapshot_plan = _validate_grade_snapshot(native_tree, owner_node, snapshot)

    # Adopt a serialized owner ID only after every descriptor and payload has
    # passed validation, so malformed backing has no effects at all.
    if not owner_node.get(OWNER_ID_KEY, ""):
        owner_node[OWNER_ID_KEY] = owner

    for slot in slots:
        backup_image, pixels = backups[slot]
        target = targets[slot]
        target.use_half_precision = False
        target.pixels.foreach_set(pixels)
        target.update()
        target.pack()
        readback = np.empty(len(target.pixels), dtype=np.float32)
        target.pixels.foreach_get(readback)
        if not target.packed_file or digest(readback) != digest(pixels):
            raise RuntimeError(f"Grade preparation field restore failed: {slot}")
    _restore_native_grade_snapshot(native_tree, owner_node, snapshot, snapshot_plan)
    from .updates import _write_ledger
    _write_ledger(
        owner_node,
        kind=ledger_data.get("kind", "grade"),
        revision=ledger_data.get("revision", 0),
        stage="restored",
        prior_revision=ledger_data.get("prior_revision", 0),
        prior_settings=ledger_data.get("prior_settings", ""),
        transaction_id=ledger_data.get("transaction_id", ""),
        clear_backup=True,
    )
    _discard_backup_images(ledger)
    _retire_owner_ledger(owner_node, controls, ledger)
    return True


def discard_orphan_ledgers(node_groups):
    """Remove staged ledger groups whose owner or transaction marker is gone."""
    import bpy

    owners = []
    for tree in node_groups:
        for node in getattr(tree, "nodes", ()):
            if node.get("perceptual_grade_next_backend") not in {
                    "native_grade_graph", "native_stack_lut"}:
                continue
            try:
                controls = (node.perceptual_grade_next_controls
                            if node.get("perceptual_grade_next_backend") == "native_grade_graph"
                            else node.perceptual_grade_next_stack_controls)
                ledger = controls.preparation_ledger
            except (AttributeError, ReferenceError, RuntimeError):
                continue
            if ledger is not None:
                try:
                    owners.append((node, ledger))
                except (ReferenceError, RuntimeError):
                    continue
    live = {ledger.as_pointer() for _node, ledger in owners}
    removed = []
    for ledger in tuple(bpy.data.node_groups):
        if (not ledger.name.startswith(LEDGER_PREFIX)
                or ledger.as_pointer() in live or ledger.users != 0):
            continue
        name = ledger.name
        try:
            _discard_backup_images(ledger)
            bpy.data.node_groups.remove(ledger, do_unlink=True)
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            continue
        removed.append(name)
    for image in tuple(bpy.data.images):
        if (image.users == 0
                and image.name.startswith(LEDGER_PREFIX + "Image ")):
            try:
                bpy.data.images.remove(image, do_unlink=True)
            except (ReferenceError, RuntimeError):
                continue
    return tuple(removed)


def discard_orphan_candidates(node_groups):
    """Remove replacement trees left unreferenced by a crashed installation."""
    import bpy

    removed = []
    for tree in tuple(bpy.data.node_groups):
        if (not tree.get(CANDIDATE_OWNER_KEY)
                and not tree.name.startswith(".PG Next Candidate Grade ")):
            continue
        if getattr(tree, "users", 1) != 0:
            continue
        name = tree.name
        images = _candidate_images(tree)
        bpy.data.node_groups.remove(tree, do_unlink=True)
        for image in images:
            if image.users == 0:
                bpy.data.images.remove(image, do_unlink=True)
        removed.append(name)
    discard_orphan_candidate_images()
    return tuple(removed)


def _candidate_images(tree, seen=None):
    seen = set() if seen is None else seen
    pointer = tree.as_pointer()
    if pointer in seen:
        return ()
    seen.add(pointer)
    images = []
    image_pointers = set()
    for node in getattr(tree, "nodes", ()):
        image = getattr(node, "image", None)
        if image is not None:
            image_pointer = image.as_pointer()
            if image_pointer not in image_pointers:
                image_pointers.add(image_pointer)
                images.append(image)
        nested = getattr(node, "node_tree", None)
        if nested is not None:
            for nested_image in _candidate_images(nested, seen):
                nested_pointer = nested_image.as_pointer()
                if nested_pointer not in image_pointers:
                    image_pointers.add(nested_pointer)
                    images.append(nested_image)
    return tuple(images)


def clear_candidate_markers(tree):
    """Remove construction markers after an owner has committed its tree."""
    images = _candidate_images(tree)
    for image in images:
        for key in (CANDIDATE_OWNER_KEY, CANDIDATE_REVISION_KEY):
            if key in image:
                del image[key]
    for key in (CANDIDATE_OWNER_KEY, CANDIDATE_REVISION_KEY):
        if key in tree:
            del tree[key]
    return len(images)


def discard_orphan_candidate_images():
    """Remove candidate images created before a tree could reference them."""
    import bpy

    removed = []
    for image in tuple(bpy.data.images):
        marked = bool(image.get(CANDIDATE_OWNER_KEY))
        named = image.name.startswith(CANDIDATE_IMAGE_PREFIX)
        if image.users != 0 or not (marked or named):
            continue
        name = image.name
        bpy.data.images.remove(image, do_unlink=True)
        removed.append(name)
    return tuple(removed)


__all__ = (
    "commit_tree_backing", "clear_candidate_markers", "discard_orphan_candidate_images",
    "field_backing", "field_backing_data",
    "retained_backing", "restore_tree_backing", "stage_tree_backing", "tree_backing",
    "OWNER_ID_KEY", "discard_grade_backing", "discard_orphan_candidates",
    "discard_orphan_ledgers",
    "discard_owner_ledger", "owner_id", "restore_grade_backing",
    "stage_grade_backing",
)
