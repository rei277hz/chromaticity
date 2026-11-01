"""Validate current authored Grade/Stack owners for project admission.

This adapter reads Blender datablocks on the foreground thread. Its snapshot
is a fresh observation of installed resources; node ID properties alone never
grant readiness.
"""

from dataclasses import dataclass, replace
from dataclasses import asdict
import hashlib
import json
import struct

from .lifecycle import ProjectWorkflow


GRADE_BACKEND = "native_grade_graph"
STACK_BACKEND = "native_stack_lut"
GRADE_SCHEMA = 1
STACK_SCHEMA = 1
GRADE_MANIFEST_KEY = "perceptual_grade_next_accepted_grade_manifest"
STACK_GRAPH_MANIFEST_KEY = "perceptual_grade_next_stack_accepted_graph_manifest"
_SUPPORTED_BACKENDS = frozenset((GRADE_BACKEND, STACK_BACKEND))
_GRADE_FIELD_ROLES = frozenset((
    "tone", "coefficient_table", "web_table", "web_toe_table",
    "adaptance_table", "boundary_seed",
))


def _pointer(value):
    try:
        pointer = value.as_pointer()
        return pointer or None
    except (AttributeError, ReferenceError):
        return None


def _identity(tree, node):
    tree_pointer, node_pointer = _pointer(tree), _pointer(node)
    if tree_pointer is None or node_pointer is None:
        return None
    return f"{tree_pointer}:{node_pointer}"


def _revision(node, key):
    value = node.get(key, -1)
    return value if type(value) is int and value >= 0 else -1


def _manifest_id(backend, owner_id, evaluator_id, data):
    payload = json.dumps(
        (backend, owner_id, evaluator_id, data), sort_keys=True,
        separators=(",", ":"), default=str,
    ).encode("utf8")
    return hashlib.sha256(payload).hexdigest()


def _same_control_snapshot(authored, installed):
    """Compare RNA values at Blender FloatProperty's float32 precision."""
    if isinstance(authored, dict) and isinstance(installed, dict):
        return (authored.keys() == installed.keys()
                and all(_same_control_snapshot(authored[key], installed[key])
                        for key in authored))
    if isinstance(authored, (tuple, list)) and isinstance(installed, (tuple, list)):
        return (len(authored) == len(installed)
                and all(_same_control_snapshot(left, right)
                        for left, right in zip(authored, installed)))
    if (isinstance(authored, (int, float)) and not isinstance(authored, bool)
            and isinstance(installed, (int, float)) and not isinstance(installed, bool)):
        return struct.pack("!f", float(authored)) == struct.pack("!f", float(installed))
    return authored == installed


def _plain(value):
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if hasattr(value, "to_list"):
        return _plain(value.to_list())
    try:
        return tuple(_plain(item) for item in value)
    except TypeError:
        return str(value)


def _socket_data(sockets, *, defaults=False):
    result = []
    for index, socket in enumerate(sockets):
        item = (index, socket.name, getattr(socket, "identifier", ""),
                getattr(socket, "bl_idname", ""))
        if defaults and hasattr(socket, "default_value"):
            item += (_plain(socket.default_value),)
        result.append(item)
    return tuple(result)


def _graph_digest(root):
    pending = [(root, "root")]
    seen = set()
    groups = []
    properties = (
        "operation", "blend_type", "data_type", "mode", "interpolation",
        "extension", "projection", "axis", "use_clamp", "mute",
    )
    while pending:
        group, path = pending.pop()
        pointer = _pointer(group)
        if pointer is None or pointer in seen:
            continue
        seen.add(pointer)
        nodes = []
        for node in group.nodes:
            child = getattr(node, "node_tree", None)
            image = getattr(node, "image", None)
            if child is not None:
                pending.append((child, path + "/" + node.name))
            nodes.append((
                node.name, node.bl_idname,
                tuple((name, _plain(getattr(node, name))) for name in properties
                      if hasattr(node, name)),
                tuple(sorted((key, _plain(node.get(key))) for key in node.keys())),
                _socket_data(node.inputs, defaults=True),
                _socket_data(node.outputs),
                None if image is None else image.name_full,
                None if child is None else child.name_full,
                bool(getattr(node, "is_active_output", False)),
            ))
        links = tuple(sorted((
            link.from_node.name, link.from_socket.name,
            link.to_node.name, link.to_socket.name,
        ) for link in group.links))
        interface = tuple((
            getattr(item, "item_type", ""), getattr(item, "name", ""),
            getattr(item, "in_out", ""), getattr(item, "socket_type", ""),
            _plain(getattr(item, "default_value", None)),
        ) for item in getattr(getattr(group, "interface", None), "items_tree", ()))
        groups.append((path, tuple(sorted(nodes)), links, interface))
    payload = json.dumps(tuple(sorted(groups)), sort_keys=True, separators=(",", ":"),
                         allow_nan=False, default=str).encode("utf8")
    return hashlib.sha256(payload).hexdigest()


def _image_records(root):
    import numpy as np

    records = {}
    pending = [(root, "root")]
    seen = set()
    while pending:
        group, path = pending.pop()
        pointer = _pointer(group)
        if pointer is None or pointer in seen:
            continue
        seen.add(pointer)
        for node in group.nodes:
            image = getattr(node, "image", None)
            if image is not None:
                image_pointer = _pointer(image)
                if image_pointer is None:
                    raise RuntimeError("Native graph image has no stable identity")
                record = records.setdefault(image_pointer, {
                    "image": image,
                    "name": image.name_full,
                    "role": str(image.get(
                        "perceptual_grade_nodes_field_role",
                        image.get("perceptual_grade_next_stack_role", ""),
                    )),
                    "role_schema": image.get(
                        "perceptual_grade_nodes_field_schema",
                        image.get("perceptual_grade_next_stack_size", -1),
                    ),
                    "size": tuple(int(value) for value in image.size),
                    "float": bool(getattr(image, "is_float", False)),
                    "half": bool(image.use_half_precision),
                    "packed": bool(image.packed_file),
                    "colorspace": image.colorspace_settings.name,
                    "alpha_mode": str(image.alpha_mode),
                    "assignments": [],
                    "pixels": "",
                })
                record["assignments"].append(path + "/" + node.name)
            child = getattr(node, "node_tree", None)
            if child is not None:
                pending.append((child, path + "/" + node.name))
    for record in records.values():
        pixels = np.empty(len(record["image"].pixels), dtype=np.float32)
        record["image"].pixels.foreach_get(pixels)
        record["pixels"] = hashlib.sha256(pixels.tobytes()).hexdigest()
        del record["image"]
    return tuple(sorted((
        record["name"], record["role"], record["role_schema"], record["size"],
        record["float"], record["half"], record["packed"], record["colorspace"],
        record["alpha_mode"], record["pixels"], tuple(sorted(record["assignments"])),
    ) for record in records.values()))


def _reject_transaction_debt(node):
    from .updates import _read_ledger
    from .preparation_ledger import retained_backing

    if _read_ledger(node) is not None or retained_backing(node) is not None:
        raise RuntimeError("Owner has unfinished preparation recovery debt")


def _images_by_role(root):
    pending = [root]
    seen = set()
    images = {}
    while pending:
        group = pending.pop()
        pointer = _pointer(group)
        if pointer is None or pointer in seen:
            continue
        seen.add(pointer)
        for node in group.nodes:
            image = getattr(node, "image", None)
            if image is not None:
                role = image.get("perceptual_grade_nodes_field_role", "")
                if role:
                    if role in images and images[role] != image:
                        raise RuntimeError("Native field role has multiple images: " + role)
                    images[role] = image
            child = getattr(node, "node_tree", None)
            if child is not None:
                pending.append(child)
    return images


def _grade_content_record(node, native=None):
    group = getattr(node, "node_tree", None)
    if group is None:
        raise RuntimeError("Grade node has no installed native tree")
    if native is not None:
        controller = getattr(native, "controller", None)
        if (getattr(native, "tree", None) != group or controller is None
                or not controller.valid):
            raise RuntimeError("Accepted Grade controller does not own the installed tree")
        controller._validate(controller.prepared)
        controller._assert_current_bindings()
        import numpy as np

        role_images = _images_by_role(group)
        slots = controller._graph.image_slots
        for role, (original, image) in slots.items():
            table = controller.prepared.table if role == "tone" else getattr(
                controller.prepared.color, role,
            )
            if (role_images.get(role) != image or table is None
                    or tuple(image.size) != (table.pixels.shape[1], table.pixels.shape[0])):
                raise RuntimeError("Accepted Grade field assignment changed: " + role)
            actual = np.empty(table.pixels.size, dtype=np.float32)
            image.pixels.foreach_get(actual)
            if not np.array_equal(actual.reshape(table.pixels.shape), table.pixels):
                raise RuntimeError("Accepted Grade field differs from prepared content: " + role)
        boundary = role_images.get("boundary_seed")
        boundary_data = controller._graph.cache.get("prepared_boundary")
        if boundary_data is None:
            boundary_data = controller.prepared.boundary
        if boundary_data is None:
            from ..perceptual_grade_nodes.boundary import prepare_boundary
            boundary_data = prepare_boundary(
                controller.prepared.fl, controller.prepared.aw,
                controller.prepared.gamma,
            )
        expected_boundary = boundary_data.pixels
        actual_boundary = np.empty(expected_boundary.size, dtype=np.float32)
        if boundary is None:
            raise RuntimeError("Accepted Grade boundary seed image is missing")
        boundary.pixels.foreach_get(actual_boundary)
        if not np.array_equal(actual_boundary.reshape(expected_boundary.shape), expected_boundary):
            raise RuntimeError("Accepted Grade boundary seed differs from prepared content")
    image_records = _image_records(group)
    field_records = tuple(record for record in image_records if record[1])
    roles = tuple(record[1] for record in field_records)
    if (len(roles) != len(_GRADE_FIELD_ROLES)
            or frozenset(roles) != _GRADE_FIELD_ROLES
            or any(record[2] != group.get("perceptual_grade_nodes_schema", -1)
                   or not record[4] or record[5] or not record[6]
                   or record[7] != "Non-Color" or record[8] != "CHANNEL_PACKED"
                   for record in field_records)):
        raise RuntimeError("Grade field roles or packed float32 interpretation is invalid")
    return {
        "schema": GRADE_SCHEMA,
        "layout_schema": group.get("perceptual_grade_nodes_schema", -1),
        "edit_revision": _revision(node, "perceptual_grade_next_edit_revision"),
        "applied_revision": _revision(node, "perceptual_grade_next_applied_revision"),
        "native_revision": group.get("perceptual_grade_nodes_revision", -1),
        "settings": node.get("perceptual_grade_next_settings", ""),
        "graph": _graph_digest(group),
        "images": image_records,
    }


def _stack_content_id(group):
    images = _image_records(group)
    roles = {record[1]: record for record in images if record[1]}
    expected = {"preview"}
    if group.get("perceptual_grade_next_stack_final_ready") is True:
        expected.add("final")
    if (set(roles) != expected
            or roles["preview"][2] != 33
            or roles["preview"][3] != (33 * 33, 33)
            or not roles["preview"][4] or roles["preview"][5]
            or not roles["preview"][6] or roles["preview"][7] != "Non-Color"
            or roles["preview"][8] != "CHANNEL_PACKED"):
        raise RuntimeError("Stack image roles or preview interpretation are invalid")
    if "final" in roles and (
            roles["final"][2] != 65
            or roles["final"][3] != (65 * 65, 65)
            or not roles["final"][4] or roles["final"][5]
            or not roles["final"][6] or roles["final"][7] != "Non-Color"
            or roles["final"][8] != "CHANNEL_PACKED"):
        raise RuntimeError("Stack final image is not the accepted packed float32 LUT")
    record = {
        "schema": group.get("perceptual_grade_next_stack_schema", -1),
        "recipe": group.get("perceptual_grade_next_stack_recipe", ""),
        "quality": group.get("perceptual_grade_next_stack_quality_tier", ""),
        "evaluator": group.get("perceptual_grade_next_stack_bake_evaluator", ""),
        "graph": _graph_digest(group),
        "images": images,
    }
    return _manifest_id(STACK_BACKEND, "stack", "stack-content", record)


def accept_grade_manifest(node, native):
    """Record verified installed content after a successful Grade publication."""
    if (node.get("perceptual_grade_next_backend") != GRADE_BACKEND
            or _revision(node, "perceptual_grade_next_edit_revision") < 0
            or _revision(node, "perceptual_grade_next_applied_revision")
            != _revision(node, "perceptual_grade_next_edit_revision")
            or node.get("perceptual_grade_next_preparation_state") != "READY"):
        raise RuntimeError("Grade publication metadata is not ready for acceptance")
    _group, _manifest_id_value, record = _validate_grade(
        node, check_ledger=False, require_manifest=False, native=native,
    )
    encoded = json.dumps(record, sort_keys=True, separators=(",", ":"), allow_nan=False)
    node[GRADE_MANIFEST_KEY] = encoded
    if node.get(GRADE_MANIFEST_KEY) != encoded:
        raise RuntimeError("Accepted Grade content manifest did not persist")
    return _manifest_id(GRADE_BACKEND, _pointer(node), _pointer(node.node_tree), record)


def _nested_images(tree):
    pending = [tree]
    seen = set()
    images = set()
    while pending:
        group = pending.pop()
        pointer = _pointer(group)
        if pointer is None or pointer in seen:
            continue
        seen.add(pointer)
        for item in getattr(group, "nodes", ()):
            image = getattr(item, "image", None)
            if image is not None:
                image_pointer = _pointer(image)
                if image_pointer is not None:
                    images.add(image_pointer)
                    if not image.packed_file or image.use_half_precision:
                        raise RuntimeError("Grade field image is unpacked or not float32")
            nested = getattr(item, "node_tree", None)
            if nested is not None:
                pending.append(nested)
    return seen, images


def _validate_grade(node, *, check_ledger=True, require_manifest=True, native=None):
    if check_ledger:
        _reject_transaction_debt(node)
    group = getattr(node, "node_tree", None)
    if group is None:
        raise RuntimeError("Grade node has no installed native tree")
    if node.get("perceptual_grade_next_schema") != GRADE_SCHEMA:
        raise RuntimeError("Grade owner schema is obsolete")
    if group.get("perceptual_grade_next_backend") != GRADE_BACKEND:
        raise RuntimeError("Installed tree is not the native Grade backend")
    if group.get("perceptual_grade_next_schema") != GRADE_SCHEMA:
        raise RuntimeError("Installed Grade tree schema is obsolete")
    if group.get("perceptual_grade_next_quality_tier") != "native_graph":
        raise RuntimeError("Installed Grade tree is not the final native graph")
    if group.get("perceptual_grade_next_has_preview_transform") is not False:
        raise RuntimeError("Grade must use one native graph without a preview transform")
    from ..perceptual_grade_nodes.layouts import LAYOUT_SCHEMA
    if (group.get("perceptual_grade_nodes_persistent") is not True
            or group.get("perceptual_grade_nodes_schema") != LAYOUT_SCHEMA):
        raise RuntimeError("Grade native field layout is not current and persistent")
    if not node.get("perceptual_grade_next_settings") or (
            node.get("perceptual_grade_next_settings")
            != group.get("perceptual_grade_next_settings")):
        raise RuntimeError("Grade owner settings do not match the installed tree")
    try:
        from . import controls
    except ImportError:
        from perceptual_grade_next_blender import controls
    animated = controls.unsupported_node_animation_paths(
        getattr(node.id_data, "animation_data", None), node.path_from_id()
    )
    if animated:
        raise RuntimeError("Static Grade controls have animation")
    authored = asdict(controls.settings_from_controls(node.perceptual_grade_next_controls))
    if not _same_control_snapshot(
            authored, json.loads(node.get("perceptual_grade_next_settings", "{}"))):
        raise RuntimeError("Grade controls do not match the installed settings")
    groups, images = _nested_images(group)
    if len(images) < 6:
        raise RuntimeError("Grade tree is missing packed preparation fields")
    record = _grade_content_record(node, native=native)
    encoded = json.dumps(record, sort_keys=True, separators=(",", ":"), allow_nan=False)
    accepted = node.get(GRADE_MANIFEST_KEY, "")
    if require_manifest and (not accepted or accepted != encoded):
        raise RuntimeError("Grade installed content differs from its accepted manifest")
    result = (group, _manifest_id(GRADE_BACKEND, _pointer(node), _pointer(group), record))
    return result + (record,) if native is not None else result


def _validate_stack(node, *, check_ledger=True):
    if check_ledger:
        _reject_transaction_debt(node)
    group = getattr(node, "node_tree", None)
    if group is None:
        raise RuntimeError("Stack node has no installed LUT tree")
    if node.get("perceptual_grade_next_schema") != STACK_SCHEMA:
        raise RuntimeError("Stack owner schema is obsolete")
    if (group.get("perceptual_grade_next_backend") != STACK_BACKEND
            or group.get("perceptual_grade_next_stack_schema") != STACK_SCHEMA):
        raise RuntimeError("Installed tree is not the current Stack backend")
    owner_settings = node.get("perceptual_grade_next_stack_settings", "")
    installed_settings = group.get("perceptual_grade_next_stack_settings", "")
    if not owner_settings or not installed_settings:
        raise RuntimeError("Stack owner has no authored settings")
    try:
        from . import controls
        from .stack import _settings_data
    except ImportError:
        from perceptual_grade_next_blender import controls
        from perceptual_grade_next_blender.stack import _settings_data
    animated = controls.unsupported_node_animation_paths(
        getattr(node.id_data, "animation_data", None), node.path_from_id()
    )
    if animated:
        raise RuntimeError("Static Stack controls have animation")
    authored = _settings_data(controls.stack_settings_from_controls(node))
    authored_matches_owner = _same_control_snapshot(authored, json.loads(owner_settings))
    authored_matches_tree = _same_control_snapshot(authored, json.loads(installed_settings))
    try:
        from .stack import reopen_stack
    except ImportError:
        from perceptual_grade_next_blender.stack import reopen_stack
    restored = reopen_stack(group, rebuild=False)
    if not restored.validate_persistent():
        raise RuntimeError("Persistent Stack resources are not valid")
    preview_name = group.get("perceptual_grade_next_stack_preview_resource", "")
    preview_image = None
    try:
        import bpy
        preview_image = bpy.data.images.get(preview_name)
    except ImportError:
        pass
    preview_ready = (
        authored_matches_owner and authored_matches_tree and preview_image is not None
        and group.get("perceptual_grade_next_stack_preview_size") == 33
    )
    preview_id = str(_pointer(group)) if preview_ready else ""
    if preview_ready and not restored.final_ready:
        lookups = [item for item in getattr(group, "nodes", ())
                   if item.get("perceptual_grade_next_stack_preview_lookup")]
        if (len(lookups) != 4
                or any(getattr(item, "image", None) != preview_image for item in lookups)):
            raise RuntimeError("Stack graph is not bound to its accepted 33^3 preview")

    final_image = None
    if restored.final_ready:
        final_name = group.get("perceptual_grade_next_stack_final_resource", "")
        try:
            import bpy
            final_image = bpy.data.images.get(final_name)
        except ImportError:
            pass
    final_ready = (
        restored.final_ready and authored_matches_owner and authored_matches_tree
        and node.get("perceptual_grade_next_stack_quality_tier") == "65^3"
        and node.get("perceptual_grade_next_stack_evaluator") == "stack_65_lut"
        and group.get("perceptual_grade_next_stack_quality_tier") == "65^3"
        and group.get("perceptual_grade_next_stack_bake_evaluator") == "stack_65_lut"
        and final_image is not None
    )
    if final_ready:
        lookups = [item for item in getattr(group, "nodes", ())
                   if item.get("perceptual_grade_next_stack_final_lookup")]
        if (len(lookups) != 4
                or any(getattr(item, "image", None) != final_image for item in lookups)):
            raise RuntimeError("Stack graph is not bound to its accepted final LUT")
    content_id = _stack_content_id(group)
    accepted_content_id = group.get(STACK_GRAPH_MANIFEST_KEY, "")
    if not accepted_content_id or accepted_content_id != content_id:
        raise RuntimeError("Stack evaluator graph differs from its accepted final content")
    manifest_id = _manifest_id(
        STACK_BACKEND, _pointer(node), "stack-recipe",
        (group.get("perceptual_grade_next_stack_recipe", ""), installed_settings),
    )
    return group, manifest_id, preview_id, final_ready, content_id


@dataclass(frozen=True)
class OwnerReadiness:
    identity: str
    backend: str
    edit_revision: int
    applied_revision: int
    state: str
    ready: bool
    evaluator: str
    evaluator_id: str
    manifest_id: str
    reason: str = ""
    preview_ready: bool = False
    preview_id: str = ""
    final_ready: bool = False


@dataclass(frozen=True)
class ReadinessSnapshot:
    generation: int
    owners: tuple[OwnerReadiness, ...]

    @property
    def owner_ids(self):
        return tuple(owner.identity for owner in self.owners)

    @property
    def ready_owner_ids(self):
        return tuple(owner.identity for owner in self.owners if owner.ready)

    @property
    def ready(self):
        identities = tuple(owner.identity for owner in self.owners)
        return (all(identities) and len(set(identities)) == len(identities)
                and all(owner.ready for owner in self.owners))


def inspect_project_owners(node_groups, *, generation=0):
    """Return an exact readiness snapshot from the current Blender data."""
    owners = []
    for tree in node_groups:
        for node in getattr(tree, "nodes", ()):
            declared_backend = node.get("perceptual_grade_next_backend")
            installed_tree = getattr(node, "node_tree", None)
            tree_backend = (installed_tree.get("perceptual_grade_next_backend")
                            if installed_tree is not None else None)
            backend = (declared_backend if declared_backend in _SUPPORTED_BACKENDS
                       else tree_backend)
            if backend not in _SUPPORTED_BACKENDS:
                continue
            identity = _identity(tree, node)
            identity_valid = identity is not None
            if identity is None:
                identity = f"invalid-owner-{len(owners)}"
            edit = _revision(node, "perceptual_grade_next_edit_revision")
            applied = _revision(node, "perceptual_grade_next_applied_revision")
            state = str(node.get("perceptual_grade_next_preparation_state", "MISSING"))
            evaluator = "native_grade_graph" if backend == GRADE_BACKEND else "stack_65_lut"
            evaluator_id = ""
            reason = ""
            preview_ready = False
            preview_id = ""
            final_ready = False
            evaluator_content_id = ""
            try:
                if not identity_valid:
                    raise RuntimeError("Native owner has no stable datablock identity")
                if declared_backend != backend:
                    raise RuntimeError("Owner backend metadata is missing or mismatched")
                if backend == GRADE_BACKEND:
                    if edit < 0 or applied != edit:
                        raise RuntimeError("Prepared revision does not match the current edit")
                    if state != "READY":
                        raise RuntimeError(f"Preparation state is {state}")
                    group, manifest_id = _validate_grade(node)
                    final_ready = True
                else:
                    (group, manifest_id, preview_id, final_ready,
                     evaluator_content_id) = _validate_stack(node)
                    final_ready = (final_ready and edit >= 0 and applied == edit
                                   and state == "READY")
                    preview_ready = bool(preview_id)
                    if not final_ready:
                        reason = ("Stack preview is ready; final 65^3 LUT is pending"
                                  if preview_ready else "Stack output does not match authored controls")
                group_pointer = _pointer(group)
                if group_pointer is None:
                    raise RuntimeError("Installed evaluator has no stable datablock identity")
                if final_ready:
                    evaluator_id = (evaluator_content_id if backend == STACK_BACKEND
                                    else str(group_pointer))
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError) as error:
                reason = str(error)
                manifest_id = ""
                preview_ready = False
                preview_id = ""
                final_ready = False
            owners.append(OwnerReadiness(
                identity=identity, backend=backend, edit_revision=edit,
                applied_revision=applied, state=state,
                ready=final_ready, evaluator=evaluator, evaluator_id=evaluator_id,
                manifest_id=manifest_id,
                reason=reason,
                preview_ready=preview_ready, preview_id=preview_id,
                final_ready=final_ready,
            ))
    counts = {}
    for owner in owners:
        counts[owner.identity] = counts.get(owner.identity, 0) + 1
    owners = [
        replace(owner, ready=False, reason="Duplicate native owner identity",
                evaluator_id="", manifest_id="", final_ready=False)
        if counts[owner.identity] > 1 else owner
        for owner in owners
    ]
    return ReadinessSnapshot(generation, tuple(owners))


class ProjectReadiness:
    """Translate fresh owner snapshots into checked project readiness events."""

    def __init__(self):
        self.workflow = ProjectWorkflow()
        self.generation = 0
        self.revision = 0
        self.attempt = 0
        self.signature = None
        self.snapshot = ReadinessSnapshot(0, ())
        self._ready_owners = set()

    def begin_document(self):
        self.generation += 1
        self.workflow.reset()
        self.revision = 0
        self.attempt = 0
        self.signature = None
        self._ready_owners.clear()
        return self.generation

    def refresh(self, node_groups):
        snapshot = inspect_project_owners(node_groups, generation=self.generation)
        identities = snapshot.owner_ids
        if self.workflow.state.phase in {"saving", "rendering"}:
            state = self.workflow.state
            signature = tuple((owner.identity, owner.edit_revision, owner.backend)
                              for owner in snapshot.owners)
            changed = (identities != state.required_owners or signature != self.signature)
            started = (state.save_started if state.phase == "saving"
                       else state.render_started)
            if changed and not started:
                if state.phase == "saving":
                    self.workflow.dispatch("save_cancel", operation=state.save_operation)
                else:
                    self.workflow.dispatch(
                        "render_cancel_before_start", operation=state.render_operation,
                    )
            elif changed:
                # The native operation already owns its frozen admission. Keep
                # its gate intact; the next active refresh will observe changes.
                self.snapshot = snapshot
                return snapshot
            else:
                attempt = state.preparation_attempt
                for owner in snapshot.owners:
                    if not owner.ready:
                        self.workflow.dispatch(
                            "output_owner_failed", generation=self.generation,
                            revision=self.revision, attempt=attempt, owner=owner.identity,
                        )
                        continue
                    if owner.identity in self.workflow.state.repair_owners:
                        self.attempt = max(
                            self.attempt, self.workflow.state.preparation_attempt,
                        ) + 1
                        self.workflow.dispatch(
                            "retry_owner", generation=self.generation,
                            revision=self.revision, attempt=self.attempt,
                            owner=owner.identity,
                        )
                    attempt = self.workflow.state.preparation_attempt
                    self.workflow.dispatch(
                        "owner_ready", generation=self.generation,
                        revision=self.revision, attempt=attempt, owner=owner.identity,
                        evaluator=owner.evaluator, evaluator_id=owner.evaluator_id,
                        manifest_id=owner.manifest_id, final_ready=True,
                    )
                self._ready_owners = {
                    owner.identity for owner in snapshot.owners if owner.ready
                }
                self.snapshot = snapshot
                return snapshot
        if not identities:
            if (self.workflow.state.generation > 0
                    and self.workflow.state.required_owners):
                self.begin_document()
                snapshot = inspect_project_owners(node_groups, generation=self.generation)
            if self.workflow.state.generation == 0:
                self.generation = max(1, self.generation)
                self.workflow.dispatch(
                    "open", generation=self.generation, owners=(), owner_evaluators=(),
                )
            self.snapshot = snapshot
            self.signature = (self.generation, ())
            return snapshot

        state = self.workflow.state
        if state.generation == 0:
            self.generation = max(1, self.generation)
            snapshot = inspect_project_owners(node_groups, generation=self.generation)
            identities = snapshot.owner_ids
            owner_evaluators = tuple((owner.identity, owner.evaluator)
                                     for owner in snapshot.owners)
            if not self.workflow.dispatch(
                    "open", generation=self.generation, owners=identities,
                    owner_evaluators=owner_evaluators):
                self.snapshot = snapshot
                return snapshot
        elif identities != state.required_owners:
            # Owner membership changes define a new static preparation epoch.
            # This adapter is not an operation queue; active native operations
            # must be fenced by their own exact receipts before this is used.
            self.begin_document()
            snapshot = inspect_project_owners(node_groups, generation=self.generation)
            identities = snapshot.owner_ids
            owner_evaluators = tuple((owner.identity, owner.evaluator)
                                     for owner in snapshot.owners)
            if not self.workflow.dispatch(
                    "open", generation=self.generation, owners=identities,
                    owner_evaluators=owner_evaluators):
                self.snapshot = snapshot
                return snapshot

        # Preview/final receipts refine one authored intent. In particular, a
        # Stack final LUT must not cancel a Bake waiting on its matching preview.
        signature = tuple((owner.identity, owner.edit_revision, owner.backend)
                          for owner in snapshot.owners)
        if signature != self.signature:
            self.revision += 1
            self.attempt += 1
            if not self.workflow.dispatch("intent", revision=self.revision):
                self.snapshot = snapshot
                return snapshot
            if not self.workflow.dispatch(
                    "prepare_begin", revision=self.revision, attempt=self.attempt):
                self.snapshot = snapshot
                return snapshot
            self.signature = signature

        current_ready = {owner.identity for owner in snapshot.owners if owner.ready}
        for owner_id in self._ready_owners - current_ready:
            self.workflow.dispatch(
                "owner_failed", revision=self.revision,
                attempt=self.workflow.state.preparation_attempt, owner=owner_id,
            )
        for owner in snapshot.owners:
            if not owner.ready and not owner.preview_ready:
                self.workflow.dispatch(
                    "owner_failed", revision=self.revision,
                    attempt=self.workflow.state.preparation_attempt,
                    owner=owner.identity,
                )
        for owner_id in tuple(owner.identity for owner in snapshot.owners
                              if owner.ready and owner.identity in self.workflow.state.repair_owners):
            self.attempt = max(self.attempt, self.workflow.state.preparation_attempt) + 1
            self.workflow.dispatch(
                "retry_owner", revision=self.revision, attempt=self.attempt,
                owner=owner_id,
            )
        attempt = self.workflow.state.preparation_attempt
        for owner in snapshot.owners:
            if owner.preview_ready:
                self.workflow.dispatch(
                    "owner_preview", revision=self.revision, attempt=attempt,
                    owner=owner.identity, evaluator="stack_33_lut",
                    evaluator_id=owner.preview_id, manifest_id=owner.manifest_id,
                )
            if owner.ready:
                self.workflow.dispatch(
                    "owner_ready", revision=self.revision, attempt=attempt,
                    owner=owner.identity, evaluator=owner.evaluator,
                    evaluator_id=owner.evaluator_id,
                    manifest_id=owner.manifest_id, final_ready=True,
                )
        self._ready_owners = current_ready
        self.snapshot = snapshot
        return snapshot


_PROJECT_READINESS = ProjectReadiness()


def begin_document():
    """Fence prior file owners and begin observations for the loaded document."""
    return _PROJECT_READINESS.begin_document()


def refresh_project_readiness(node_groups):
    return _PROJECT_READINESS.refresh(node_groups)


def project_readiness_runtime():
    return _PROJECT_READINESS


__all__ = (
    "OwnerReadiness", "ProjectReadiness", "ReadinessSnapshot",
    "accept_grade_manifest", "begin_document",
    "inspect_project_owners", "project_readiness_runtime", "refresh_project_readiness",
)
