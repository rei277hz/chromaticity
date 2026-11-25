"""Shared graph occurrence lookup and effective input traversal for captures."""

from collections.abc import Mapping
import hashlib
import json
import math
from pathlib import Path

from ..kernel.color_ui import COLOR_FIELDS
from ..kernel.lut import STACK_COMPOSITION_SCHEMA, STACK_INVERSE_SCHEMA
from ..kernel.tone_ui import TONE_FIELDS
from . import effective_grade_graph
from .capture_images import datablock_key, route_datablock
from .compositor_effects import compositor_occurrences, matching_compositor_occurrences
from .shader_scene import shader_scene_inventory


MAX_PIXEL_BYTES = 512 * 1024 * 1024
COMPOSITOR_OVERRIDES = frozenset(("compositor_device", "compositor_precision"))
_IMAGE_LAYER_VIEW = frozenset(("layer", "view"))
_COMPOSITOR_POINTWISE = frozenset((
    "CompositorNodeRGB", "CompositorNodeValue", "CompositorNodeMath", "CompositorNodeMixRGB",
))
BAKE_DOMAIN = effective_grade_graph.DOMAIN
GRADE_TYPES = frozenset(("PGShaderGrade", "PGCompositorGrade"))
STACK_TYPES = frozenset(("PGShaderGradeStack", "PGCompositorGradeStack"))
PER_NODE_TYPES = frozenset(("PGShaderGradePerNode", "PGCompositorGradePerNode"))
READER_TYPES = frozenset(("PGShaderBake", "PGCompositorBake",
                          "PGShaderBakeReader", "PGCompositorBakeReader"))
POINTWISE = frozenset((
    "ShaderNodeRGB", "ShaderNodeValue", "ShaderNodeRGBToBW", "ShaderNodeMath",
    "ShaderNodeVectorMath", "ShaderNodeMix", "ShaderNodeMixRGB",
    "ShaderNodeHueSaturation", "ShaderNodeBrightContrast", "ShaderNodeGamma",
    "ShaderNodeInvert", "ShaderNodeValToRGB", "ShaderNodeRGBCurve",
    "ShaderNodeCombineColor", "ShaderNodeSeparateColor", "ShaderNodeCombineRGB",
    "ShaderNodeSeparateRGB", "ShaderNodeCombineXYZ", "ShaderNodeSeparateXYZ",
    "ShaderNodeClamp", "ShaderNodeMapRange", "ShaderNodeMapValue",
))
LINEAR_FIELDS = ("exposure", "source_x", "source_y", "cr_balance", "yb_balance",
                 "cr_spread", "yb_spread", "cr_heading", "yb_heading")
_UI_PROPERTIES = frozenset((
    "rna_type", "id_data", "original", "name", "name_full", "label", "location",
    "width", "width_hidden", "height", "dimensions", "select", "hide",
    "show_options", "show_preview", "show_texture", "use_custom_color",
    "parent", "inputs", "outputs", "internal_links", "node_tree", "links",
    "preview", "asset_data", "animation_data", "library", "override_library",
    "session_uid", "users", "use_fake_user", "is_updated", "is_updated_data",
))


class RouteBlocked(ValueError):
    """An expected, actionable unsupported input condition."""

    def __init__(self, code, detail):
        super().__init__(detail)
        self.code = code


def identity(value):
    if value is None:
        return None
    uid = getattr(value, "session_uid", None)
    if uid is not None:
        return (type(value).__name__, int(uid))
    pointer = getattr(value, "as_pointer", None)
    return (type(value).__name__, int(pointer()) if pointer else id(value))


def semantic_identity(value, seen=None):
    """Stable save/reload identity used only in persisted signatures."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    seen = set() if seen is None else seen
    runtime_key = identity(value)
    if runtime_key in seen:
        return ("reference", type(value).__name__)
    seen = seen | {runtime_key}
    kind = str(getattr(value, "bl_idname", type(value).__name__))
    library = getattr(value, "library", None)
    library_path = str(getattr(library, "filepath", "")) if library is not None else ""
    filepath = str(getattr(value, "filepath", ""))
    if kind == "Image" or library_path:
        import bpy
        library_path = _absolute_path(bpy, library_path)
        if kind == "Image":
            filepath = _absolute_path(bpy, filepath, library=library)
    owner = getattr(value, "id_data", None)
    if owner is not None and owner is not value:
        return ("node", kind, str(getattr(value, "name", "")),
                semantic_identity(owner, seen), library_path)
    return (kind, str(getattr(value, "name", "")), filepath, library_path)


def same(left, right):
    return left is not None and right is not None and identity(left) == identity(right)


def _plain(value):
    if value is None or type(value) in (bool, int, str):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else value.hex()
    if isinstance(value, Mapping):
        return tuple(sorted((str(key), _plain(item)) for key, item in value.items()))
    try:
        return tuple(_plain(item) for item in value)
    except TypeError:
        raise RouteBlocked("unsupported_value", "Bake cannot fingerprint a native input value") from None


def _collect_dependency(value, dependencies, dependency_seen):
    if dependencies is None or not hasattr(value, "session_uid"):
        return
    key = identity(value)
    if key not in dependency_seen:
        dependency_seen.add(key)
        dependencies.append(value)
        if hasattr(value, "matrix_world"):
            _collect_dependency(getattr(value, "data", None), dependencies,
                                dependency_seen)


def rna_state(value, seen=None, depth=0, dependencies=None, dependency_seen=None,
               *, exclude=()):
    """Snapshot writable semantic RNA, including ramps, curves and mappings."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return _plain(value)
    seen = set() if seen is None else seen
    dependency_seen = set() if dependency_seen is None else dependency_seen
    key = identity(value)
    if key in seen:
        return ("reference", semantic_identity(value))
    if depth > 12:
        raise RouteBlocked("graph_complex", "Bake native inputs exceed the fingerprint depth limit")
    properties = getattr(getattr(value, "bl_rna", None), "properties", None)
    if properties is None:
        if hasattr(value, "__dict__"):
            return tuple(sorted((name, rna_state(
                item, seen | {key}, depth + 1, dependencies, dependency_seen,
            ))
                                for name, item in vars(value).items()
                                if name not in exclude
                                if name not in _UI_PROPERTIES and not name.startswith("_")
                                and not callable(item)))
        return _plain(value)
    result = []
    for prop in properties:
        name = prop.identifier
        if name == "color" and hasattr(value, "inputs") and hasattr(value, "outputs"):
            continue
        if (name in exclude or name in _UI_PROPERTIES
                or (prop.is_readonly and prop.type not in {"POINTER", "COLLECTION"})):
            continue
        item = getattr(value, name)
        if prop.type == "POINTER" and item is not None and hasattr(item, "session_uid"):
            _collect_dependency(item, dependencies, dependency_seen)
            frozen = (semantic_identity(item), _dependency_state(item, seen | {key}, depth + 1))
        elif prop.type == "COLLECTION":
            frozen = tuple(rna_state(
                entry, seen | {key}, depth + 1, dependencies, dependency_seen,
            ) for entry in item)
        else:
            nested_exclude = (_IMAGE_LAYER_VIEW if name == "image_user"
                              and prop.type == "POINTER" and exclude == _IMAGE_LAYER_VIEW
                              else ())
            frozen = rna_state(item, seen | {key}, depth + 1,
                                dependencies, dependency_seen, exclude=nested_exclude)
        result.append((name, frozen))
    return tuple(result)


def _dependency_state(value, seen=None, depth=0):
    """Capture render-visible state of IDs referenced by native nodes.

    Pointer identity alone is insufficient: coordinate objects, cameras and
    lights can move or change their data while retaining the same Blender ID.
    Keep this deliberately bounded and avoid image payloads, which have their
    own source fingerprint path.
    """
    if value is None:
        return None
    seen = set() if seen is None else seen
    key = identity(value)
    if key in seen:
        return ("reference", semantic_identity(value))
    if depth > 12:
        raise RouteBlocked("graph_complex", "Bake referenced data exceeds its fingerprint depth limit")
    kind = str(getattr(value, "type", ""))
    if kind and hasattr(value, "matrix_world"):
        data = getattr(value, "data", None)
        return (
            "object", kind, _plain(getattr(value, "matrix_world", ())),
            rna_state(data, seen | {key}, depth + 1)
            if data is not None and kind in {"CAMERA", "LIGHT"} else None,
        )
    name = str(getattr(getattr(value, "bl_rna", None), "identifier", type(value).__name__))
    if name in {"Camera", "World"} or name.endswith("Light"):
        return (name, rna_state(value, seen, depth + 1))
    return None


def _links(socket):
    return tuple(link for link in getattr(socket, "links", ())
                 if not getattr(link, "is_muted", False) and getattr(link, "is_valid", True))


def _socket(collection, identifier):
    return next((item for item in collection
                 if getattr(item, "identifier", item.name) == identifier or item.name == identifier), None)


def _socket_name(socket):
    # Grade's public interface survives swapping derived live, wrapper and
    # fallback groups, whose generated Socket_N identifiers can differ.
    if getattr(getattr(socket, "node", None), "bl_idname", None) in (
            GRADE_TYPES | STACK_TYPES | PER_NODE_TYPES | READER_TYPES):
        return str(socket.name)
    return str(getattr(socket, "identifier", socket.name))


def _group_paths(root, target, ancestors=()):
    if same(root, target):
        return ((),)
    key = identity(root)
    if root is None or key in ancestors:
        return ()
    result = []
    for node in root.nodes:
        if getattr(node, "bl_idname", None) in GRADE_TYPES | STACK_TYPES | PER_NODE_TYPES | READER_TYPES:
            continue
        child = getattr(node, "node_tree", None)
        if child is not None:
            result.extend((str(node.name), *path)
                          for path in _group_paths(child, target, (*ancestors, key)))
    return tuple(result)


def _resolve_path(root, path):
    parents = []
    tree = root
    for name in path:
        node = tree.nodes.get(name)
        child = getattr(node, "node_tree", None)
        if child is None:
            raise RouteBlocked("occurrence", "The selected node-group occurrence is unavailable")
        parents.append(node)
        tree = child
    return tree, tuple(parents)


def _editor_path(space, root, target):
    path = tuple(getattr(item, "node_tree", None) for item in getattr(space, "path", ()))
    if not path or not same(path[0], root) or not same(path[-1], target):
        return None
    names = []
    for parent, child in zip(path, path[1:]):
        choices = [node for node in parent.nodes if same(getattr(node, "node_tree", None), child)]
        active = getattr(parent.nodes, "active", None)
        if active is not None and any(same(active, item) for item in choices):
            chosen = active
        elif len(choices) == 1:
            chosen = choices[0]
        else:
            raise RouteBlocked("occurrence", "Choose the exact node-group occurrence to bake")
        names.append(str(chosen.name))
    return tuple(names)


def _compositor_owner(host, tree, context):
    if isinstance(context, Mapping):
        scene = route_datablock(host, host.data.scenes, context, "scene")
        owner = route_datablock(host, host.data.scenes, context, "owner")
        if not same(scene, owner) or context.get("owner_kind") != "compositor":
            raise RouteBlocked("owner", "The bake scene or graph owner is unavailable")
        path = tuple(context.get("group_path", ()))
        matches = []
        for effect, root in matching_compositor_occurrences(host, scene, context):
            try:
                selected, parents = _resolve_path(root, path)
            except RouteBlocked:
                continue
            if same(selected, tree):
                matches.append((effect, root, parents))
        if len(matches) != 1:
            raise RouteBlocked("occurrence", "The saved compositor effect occurrence cannot be resolved uniquely")
        effect, root, parents = matches[0]
    else:
        context = context or host.context
        space = getattr(context, "space_data", None)
        candidates = [(scene, effect, root) for scene in host.data.scenes
                      for effect, root in compositor_occurrences(scene) if _group_paths(root, tree)]
        editor_path = getattr(space, "path", ())
        editor_root = (editor_path[0].node_tree if editor_path else getattr(space, "node_tree", None))
        for index, preferred in ((0, getattr(space, "id", None)), (2, editor_root),
                                 (0, getattr(context, "scene", None))):
            matches = [item for item in candidates if same(item[index], preferred)]
            if matches:
                candidates = matches
        if len(candidates) > 1:
            candidates = [item for item in candidates if getattr(item[1], "is_active", False)]
        if len(candidates) != 1:
            raise RouteBlocked("occurrence", "Choose the compositor effect containing this node")
        scene, effect, root = candidates[0]
        parents = _occurrence_parents(space, root, tree)
    locator = {"root_key": datablock_key(host, root)}
    if effect is not None:
        locator["effect_name"] = effect.name
    return "compositor", scene, scene, parents, locator


def _occurrence_parents(space, root, tree):
    path = _editor_path(space, root, tree)
    if path is None:
        paths = _group_paths(root, tree)
        if len(paths) != 1:
            raise RouteBlocked("occurrence", "Choose the exact node-group occurrence to bake")
        path = paths[0]
    _tree, parents = _resolve_path(root, path)
    return parents


def owner_for_node(host, node, context):
    tree = node.id_data
    if tree.bl_idname == "CompositorNodeTree":
        return _compositor_owner(host, tree, context)
    if isinstance(context, Mapping):
        kind = context.get("owner_kind")
        scene = route_datablock(host, host.data.scenes, context, "scene")
        values = {"material": host.data.materials, "world": host.data.worlds}.get(kind)
        owner = route_datablock(host, values, context, "owner") if values is not None else None
        root = getattr(owner, "node_tree", None)
        path = tuple(context.get("group_path", ()))
        if scene is None or owner is None or root is None:
            raise RouteBlocked("owner", "The bake scene or graph owner is unavailable")
        selected, parents = _resolve_path(root, path)
        if not same(selected, tree):
            raise RouteBlocked("occurrence", "The selected node-group occurrence changed")
        if kind == "world" and not same(getattr(scene, "world", None), owner):
            raise RouteBlocked("world_scene", "The selected World is not used by this scene")
        return kind, owner, scene, parents, {}
    context = context or host.context
    scene = getattr(context, "scene", None)
    space = getattr(context, "space_data", None)
    candidates = []
    collections = (("material", host.data.materials), ("world", host.data.worlds))
    for kind, owners in collections:
        for owner in owners:
            root = getattr(owner, "node_tree", None)
            if root is not None and _group_paths(root, tree):
                candidates.append((kind, owner, root))
    preferred = [item for item in candidates if same(item[1], getattr(space, "id", None))]
    if not preferred:
        preferred = [item for item in candidates if same(item[2], getattr(space, "node_tree", None))]
    if not preferred:
        active = getattr(getattr(context, "object", None), "active_material", None)
        preferred = [item for item in candidates if same(item[1], active)]
        if not preferred:
            preferred = [item for item in candidates if same(item[1], getattr(scene, "world", None))]
    chosen = preferred or candidates
    if len(chosen) != 1:
        raise RouteBlocked("owner", "Choose the scene, material or World containing this node")
    kind, owner, root = chosen[0]
    if scene is None:
        raise RouteBlocked("scene", "Bake requires a scene context")
    if kind == "world" and not same(getattr(scene, "world", None), owner):
        raise RouteBlocked("world_scene", "The selected World is not used by this scene")
    return kind, owner, scene, _occurrence_parents(space, root, tree), {}


def grade_settings(node):
    kind = node.bl_idname
    if kind in STACK_TYPES:
        active = tuple(entry for entry in node.pg_stack_entries
                       if entry.enabled and entry.grade is not None)
        entries = tuple(_grade_values(entry.grade) for entry in active)
        directions = tuple(getattr(entry, "direction", "FORWARD") for entry in active)
        if "INVERSE" in directions:
            return ("stack_composition", STACK_COMPOSITION_SCHEMA, entries, STACK_INVERSE_SCHEMA, directions)
        if len(entries) > 1:
            return ("stack_composition", STACK_COMPOSITION_SCHEMA, entries)
        return entries
    owner = getattr(node, "pg_grade", None) if kind in GRADE_TYPES else node
    return _grade_values(owner if owner is not None else node)


def _grade_values(owner):
    linear = getattr(owner, "pg_linear", owner)
    tone = getattr(owner, "pg_tone", owner)
    color = getattr(owner, "pg_color", owner)
    return (tuple((name, _plain(getattr(linear, name))) for name in LINEAR_FIELDS),
            tuple((name, _plain(getattr(tone, name))) for name in TONE_FIELDS),
            tuple((name, _plain(getattr(color, name))) for name in COLOR_FIELDS))


def _absolute_path(host, path, library=None):
    raw = str(path or "")
    if not raw:
        return ""
    try:
        resolved = host.path.abspath(raw, library=library)
    except (AttributeError, OSError, RuntimeError, TypeError, ValueError):
        resolved = raw
    try:
        return str(Path(resolved).expanduser().resolve(strict=False))
    except (OSError, RuntimeError, TypeError, ValueError):
        return str(Path(resolved).expanduser())


def _image_state(host, image, *, full):
    """Return stable Image metadata without reading or hashing pixel payloads."""
    source = str(image.source)
    if source in {"MOVIE", "SEQUENCE"}:
        raise RouteBlocked("source_sequence", "Bake does not support movie or image-sequence sources")
    if source == "TILED" or getattr(image, "is_tiled", False):
        raise RouteBlocked("source_udim", "Bake does not support UDIM sources")
    if source not in {"FILE", "GENERATED"}:
        raise RouteBlocked("source_type", "Bake requires stored still Image sources")
    if getattr(image, "use_multiview", False):
        raise RouteBlocked("source_multiview", "Bake does not support multiview Image sources")
    if getattr(image, "type", "IMAGE") not in {"IMAGE", "UV_TEST"}:
        raise RouteBlocked("source_multilayer", "Bake does not support multilayer Image sources")
    width, height = (int(item) for item in image.size)
    if min(width, height) < 1:
        raise RouteBlocked("source_empty", "Bake source Image has no pixels")
    channels = int(image.channels)
    if channels < 1 or (full and not getattr(image, "has_data", False)):
        raise RouteBlocked("source_empty", "Bake source Image has no loaded pixels")
    if full and width * height * 16 > MAX_PIXEL_BYTES:
        raise RouteBlocked("dimensions", "Bake source Image exceeds the 512 MiB pixel budget")
    packed = getattr(image, "packed_file", None)
    state = (
        semantic_identity(image),
        source, width, height, channels,
        bool(getattr(image, "is_float", False)),
        str(image.colorspace_settings.name), str(image.alpha_mode),
        packed is not None, int(getattr(packed, "size", 0)) if packed is not None else None,
        _file_observation(host, image),
        image.get(BAKE_DOMAIN), image.get("_pg_next_bake_operation"),
    )
    return state, width, height


def _file_observation(host, image):
    """Return bounded file metadata for an external still Image and sidecars."""
    if str(image.source) != "FILE" or getattr(image, "packed_file", None) is not None:
        return None
    try:
        raw_path = getattr(image, "filepath", "")
        if not raw_path:
            return ((str(raw_path), None),)
        path = Path(_absolute_path(host, raw_path, library=getattr(image, "library", None)))
        candidates = (path, *_sidecar_candidates(path))
        result = []
        for candidate in candidates:
            try:
                stat = candidate.stat()
            except OSError:
                result.append((str(candidate), None))
            else:
                result.append((
                    str(candidate), int(stat.st_dev), int(stat.st_ino),
                    int(stat.st_size), int(stat.st_mtime_ns), int(stat.st_ctime_ns),
                ))
        return tuple(result)
    except (AttributeError, OSError, TypeError, ValueError):
        return ((str(getattr(image, "filepath", "")), None),)


def _sidecar_candidates(path):
    base = Path(path)
    return tuple(dict.fromkeys((
        Path(str(base) + ".json"), Path(str(base) + ".sidecar"),
        Path(str(base) + ".tx"), base.with_suffix(".json"),
        base.with_suffix(".ocio"),
    )))


def digest(value):
    return hashlib.sha256(json.dumps(value, separators=(",", ":"), sort_keys=True).encode("utf8")).hexdigest()


def cache_geometry(obj):
    for item in (*tuple(getattr(obj, "modifiers", ())), *tuple(getattr(obj, "constraints", ()))):
        if (getattr(item, "type", None) in {"MESH_SEQUENCE_CACHE", "MESH_CACHE", "TRANSFORM_CACHE"}
                or getattr(item, "cache_file", None) is not None):
            raise RouteBlocked("mesh_cache", "Bake does not support Alembic or CacheFile geometry")


def _baked_sampler(node, image):
    """Find only the native sampler bound to the authoritative baked Image."""
    tree = getattr(node, "node_tree", None)
    if tree is not None and tree.get(effective_grade_graph.WRAPPER):
        reader = effective_grade_graph.marked(tree, effective_grade_graph.READER)
        if reader is None or not same(getattr(reader, "image", None), image):
            raise RouteBlocked("baked_sampler", "Bake source wrapper has no matching Image reader")
        return reader, (str(reader.name),)
    pending = [(tree, ())]
    seen = set()
    while pending:
        tree, path = pending.pop()
        key = identity(tree)
        if tree is None or key in seen:
            continue
        seen.add(key)
        for candidate in tree.nodes:
            if (candidate.bl_idname in {"ShaderNodeTexImage", "CompositorNodeImage"}
                    and same(getattr(candidate, "image", None), image)):
                return candidate, (*path, str(candidate.name))
            child = getattr(candidate, "node_tree", None)
            if child is not None:
                pending.append((child, (*path, str(candidate.name))))
    return node, None


def geometry_observation(obj):
    """Stable mesh metadata for saved receipts. Mesh edits also emit dependency updates."""
    cache_geometry(obj)
    mesh = getattr(obj, "data", None)
    is_mesh = getattr(obj, "type", None) == "MESH" and mesh is not None
    layers = tuple((str(layer.name), len(layer.data), bool(layer.active_render))
                   for layer in getattr(mesh, "uv_layers", ())) if is_mesh else ()
    return (semantic_identity(obj), semantic_identity(mesh),
            bool(getattr(obj, "hide_render", False)),
            (len(mesh.vertices), len(mesh.loops), len(mesh.polygons), layers) if is_mesh else None,
            tuple(tuple(float(value) for value in row) for row in getattr(obj, "matrix_world", ())),
            tuple(rna_state(item) for item in getattr(obj, "modifiers", ())),
            tuple(semantic_identity(item.material) for item in getattr(obj, "material_slots", ())))


def instance_observations(inventory):
    bindings = tuple((semantic_identity(obj), semantic_identity(obj.instance_collection))
                     for obj in inventory.objects
                     if getattr(obj, "instance_type", None) == "COLLECTION")
    collections = tuple(
        (semantic_identity(collection), bool(getattr(collection, "hide_render", False)),
         _plain(getattr(collection, "instance_offset", ())),
         tuple(semantic_identity(obj) for obj in collection.objects),
         tuple(semantic_identity(child) for child in collection.children))
        for collection in inventory.collections
    )
    return bindings, collections


class Walker:
    def __init__(self, host, scene, *, owner_kind, owner, full, compositor,
                 compositor_locator, dependencies=None, allow_dynamic_images=False):
        self.host, self.scene, self.full = host, scene, full
        self.owner = (owner_kind, datablock_key(host, owner))
        self.compositor = compositor
        self.compositor_locator = compositor_locator
        self.dependencies = dependencies
        self.graph = []
        self.images = {}
        self.image_pointers = set()
        self.image_states = {}
        self.dependency_pointers = set()
        self.upstream_grades = {}
        self.reasons = set()
        self.visiting = set()
        self.visited = set()
        self.rendered = {}
        self.render_layers = set()
        self.render_observations = []
        self.input_tree_pointers = set()
        self.coordinate_depth = 0
        self.unknown_compositor_extent = False
        self.allow_dynamic_images = allow_dynamic_images

    def input(self, socket, parents, *, links=None):
        if links is None:
            links = _links(socket)
        if len(links) > 1 and not getattr(socket, "is_multi_input", False):
            raise RouteBlocked("input_links", "Bake input has multiple effective sources")
        self.graph.append(("input", tuple(semantic_identity(item) for item in parents),
                           semantic_identity(socket.node), _socket_name(socket),
                           None if links else _plain(getattr(socket, "default_value", None)),
                           tuple((semantic_identity(link.from_node), _socket_name(link.from_socket))
                                 for link in links)))
        for link in links:
            self.output(link.from_node, link.from_socket, parents)

    def _observe(self, node, output, parents, semantic=None):
        tree = getattr(node, "id_data", None)
        pointer = getattr(tree, "as_pointer", None)
        if pointer is not None:
            self.input_tree_pointers.add(int(pointer()))
        # The enums have no valid item on ordinary single-layer, single-view images.
        exclude = (_IMAGE_LAYER_VIEW if self.allow_dynamic_images
                   and node.bl_idname == "CompositorNodeImage" else ())
        state = (rna_state(node, dependencies=self.dependencies,
                            dependency_seen=self.dependency_pointers, exclude=exclude)
                 if semantic is None else semantic)
        self.graph.append((tuple(semantic_identity(item) for item in parents), semantic_identity(node),
                           node.bl_idname, _socket_name(output), state,
                           _plain(getattr(output, "default_value", None))))

    def _image(self, node, image, output, parents, *, baked=False):
        if image is None:
            raise RouteBlocked("baked_unbound" if baked else "source_unbound",
                               "Bake source Image is unbound")
        image_identity = identity(image)
        if image_identity not in self.image_states:
            if self.allow_dynamic_images and str(image.source) in {"MOVIE", "SEQUENCE"}:
                if getattr(image, "use_multiview", False):
                    raise RouteBlocked("source_multiview", "Vectorscope cannot capture multiview Images")
                if getattr(image, "type", "IMAGE") != "IMAGE":
                    raise RouteBlocked("source_multilayer", "Vectorscope cannot capture multilayer Images")
                width, height = (int(value) for value in image.size)
                if min(width, height) < 1:
                    raise RouteBlocked("source_empty", "Vectorscope source Image has no dimensions")
                state = (
                    semantic_identity(image), str(image.source),
                    _absolute_path(self.host, getattr(image, "filepath", ""),
                                   library=getattr(image, "library", None)),
                    width, height, int(getattr(image, "frame_duration", 0)),
                    int(getattr(image, "frame_start", 0)),
                    int(getattr(image, "frame_offset", 0)),
                    bool(getattr(image, "use_cyclic", False)),
                    bool(getattr(image, "use_auto_refresh", False)),
                    str(image.colorspace_settings.name), str(image.alpha_mode),
                )
                self.image_states[image_identity] = state, width, height
            else:
                self.image_states[image_identity] = _image_state(
                    self.host, image, full=self.full,
                )
            self.add_dependency(image)
        state, width, height = self.image_states[image_identity]
        self.image_pointers.add(identity(image))
        key = (tuple(semantic_identity(item) for item in parents),
               semantic_identity(node), semantic_identity(image))
        previous = self.images.get(key)
        alpha = output.name in {"Alpha", "Baked Alpha"}
        sampler, reader_path = _baked_sampler(node, image) if baked else (node, ())
        item = dict(group_path=tuple(str(item.name) for item in parents), node_name=str(node.name),
                    owner=self.owner, reader_path=reader_path,
                    image_key=datablock_key(self.host, image), width=width, height=height,
                    alpha_linked=alpha or bool(previous and previous[1]["alpha_linked"]),
                    interpolation=str(getattr(sampler, "interpolation", "Linear")),
                    extension=str(getattr(sampler, "extension", "REPEAT")), baked=baked,
                    dynamic=str(image.source) in {"MOVIE", "SEQUENCE"})
        if self.owner[0] == "compositor":
            item.update(self.compositor_locator)
        self.images[key] = (state, item)
        if (baked and not self.compositor
                and image.get(BAKE_DOMAIN) == "UV"):
            self.reasons.add("upstream_uv_bake")
        if baked:
            self.graph.append((key, "baked_sampling", item["interpolation"], item["extension"]))
        for socket in node.inputs:
            if socket.name != "Vector":
                if not baked:
                    self.input(socket, parents)
                continue
            links = _links(socket)
            if not links:
                self.input(socket, parents, links=links)
                continue
            self.reasons.add("linked_coordinates")
            self.coordinate_depth += 1
            try:
                self.input(socket, parents, links=links)
            finally:
                self.coordinate_depth -= 1

    def output(self, node, output, parents):
        node_key = identity(node)
        key = (node_key, _socket_name(output), tuple(identity(item) for item in parents))
        if key in self.visiting:
            raise RouteBlocked("cycle", "Bake input contains a node cycle")
        if key in self.visited:
            return
        if len(self.visited) > 100000:
            raise RouteBlocked("graph_complex", "Bake input graph exceeds its bounded traversal limit")
        self.visiting.add(key)
        try:
            kind = node.bl_idname
            if getattr(node, "mute", False):
                bypass = tuple(link.from_socket for link in node.internal_links if same(link.to_socket, output))
                if len(bypass) != 1:
                    raise RouteBlocked("muted_output", "Bake cannot resolve this muted node output")
                self.graph.append((semantic_identity(node), _socket_name(output),
                                   "muted", _socket_name(bypass[0])))
                self.input(bypass[0], parents)
                return
            if kind == "ShaderNodeShaderToRGB":
                raise RouteBlocked("shader_to_rgb", "Bake does not support Shader to RGB")
            if kind in GRADE_TYPES | STACK_TYPES | PER_NODE_TYPES:
                if (output.name in {"Baked Color", "Baked Alpha"}
                        or bool(getattr(node, "pg_use_bake", False))):
                    self.graph.append((semantic_identity(node), _socket_name(output), "baked"))
                    self._image(node, getattr(node, "pg_bake_image", None), output, parents, baked=True)
                    return
                if output.name == "Alpha":
                    alpha = next((item for item in node.inputs if item.name == "Alpha"), None)
                    if alpha is not None:
                        self.graph.append((semantic_identity(node), "Alpha", "alpha"))
                        self.input(alpha, parents)
                    return
                self._observe(node, output, parents, grade_settings(node))
                self.upstream_grades.setdefault(node_key, node)
                for socket in node.inputs:
                    if socket.name in {"Color", "Alpha"}:
                        self.input(socket, parents)
                return
            if kind in READER_TYPES:
                self.graph.append((semantic_identity(node), _socket_name(output), "baked_reader"))
                self._image(node, getattr(node, "pg_bake_image", None), output, parents, baked=True)
                return
            self._observe(node, output, parents)
            if kind in {"ShaderNodeTexImage", "CompositorNodeImage"}:
                self._image(node, getattr(node, "image", None), output, parents)
                return
            if getattr(node, "image", None) is not None:
                raise RouteBlocked("source_node", "Bake supports Image Texture and compositor Image sources only")
            if kind in {"CompositorNodeMovieClip", "CompositorNodeMask"}:
                raise RouteBlocked("source_node", "Bake does not support movie-clip or mask data sources")
            if kind == "NodeGroupInput":
                if not parents:
                    raise RouteBlocked("group_input", "Bake cannot resolve an unbound root group input")
                socket = _socket(parents[-1].inputs, _socket_name(output))
                if socket is None:
                    raise RouteBlocked("group_input", "Bake group input is unavailable")
                self.input(socket, parents[:-1])
                return
            if kind == "NodeReroute":
                if node.inputs:
                    self.input(node.inputs[0], parents)
                return
            child = getattr(node, "node_tree", None)
            if kind in {"ShaderNodeGroup", "CompositorNodeGroup"}:
                if child is None:
                    raise RouteBlocked("group_tree", "Bake input group has no node tree")
                endpoint = next((item for item in child.nodes if item.bl_idname == "NodeGroupOutput"
                                 and getattr(item, "is_active_output", True)), None)
                socket = _socket(endpoint.inputs, _socket_name(output)) if endpoint is not None else None
                if socket is None:
                    raise RouteBlocked("group_output", "Bake group has no matching active output")
                self.input(socket, (*parents, node))
                return
            if kind == "CompositorNodeRLayers":
                self.unknown_compositor_extent = True
                render_scene = getattr(node, "scene", None)
                self._render_scene(self.scene if render_scene is None else render_scene,
                                   getattr(node, "layer", None))
            elif self.compositor:
                if kind not in _COMPOSITOR_POINTWISE and kind not in POINTWISE:
                    self.unknown_compositor_extent = True
            elif kind not in POINTWISE and not self.coordinate_depth:
                self.reasons.add("surface_dependency")
            for socket in node.inputs:
                self.input(socket, parents)
        finally:
            self.visiting.remove(key)
            self.visited.add(key)

    def _render_scene(self, scene, layer_name):
        scene_key = identity(scene)
        key = scene_key, layer_name
        if key in self.render_layers:
            return
        self.render_layers.add(key)
        engine = scene.render.engine
        if engine == "CYCLES":
            engine_settings = getattr(scene, "cycles", None)
        elif engine in {"BLENDER_EEVEE", "BLENDER_EEVEE_NEXT"}:
            engine_settings = getattr(scene, "eevee", None)
        else:
            engine_settings = None
        self.rendered[scene_key] = (
            engine, getattr(engine_settings, "device", None) if engine == "CYCLES" else None,
        )
        selected = (None if not layer_name else tuple(
            layer for layer in getattr(scene, "view_layers", ()) if layer.name == layer_name))
        inventory = shader_scene_inventory(scene, view_layers=selected)
        layer_overrides = tuple(
            (layer.name, bool(getattr(layer, "use", True)),
             semantic_identity(getattr(layer, "material_override", None)),
             semantic_identity(getattr(layer, "world_override", None)))
            for layer in inventory.view_layers
        )
        objects = inventory.objects
        camera = getattr(scene, "camera", None)
        self.add_dependency(camera)
        summary = (semantic_identity(scene), layer_name, layer_overrides,
                   instance_observations(inventory),
                   rna_state(scene.render, exclude=COMPOSITOR_OVERRIDES),
                   rna_state(engine_settings),
                   semantic_identity(camera), _dependency_state(camera),
                   rna_state(getattr(scene, "world", None),
                              dependencies=self.dependencies,
                              dependency_seen=self.dependency_pointers))
        self.render_observations.append((*summary, tuple(
            (geometry_observation(obj),
             rna_state(getattr(obj, "data", None)) if getattr(obj, "type", None) in {"LIGHT", "CAMERA"} else None)
            for obj in objects)))
        for obj in objects:
            self.add_dependency(obj)
            self.add_dependency(getattr(obj, "data", None))
        for collection in inventory.collections:
            self.add_dependency(collection)
        owners = inventory.owners
        for _kind, owner in owners:
            self.add_dependency(owner)
        owner_settings = tuple((semantic_identity(owner), rna_state(
            owner, dependencies=self.dependencies,
            dependency_seen=self.dependency_pointers,
        ))
                               for _kind, owner in owners)
        self.render_observations.append(("owner_settings", owner_settings))
        previous_owner = self.owner
        try:
            for kind, owner in owners:
                tree = getattr(owner, "node_tree", None)
                if tree is None or not getattr(owner, "use_nodes", True):
                    continue
                self.owner = (kind, datablock_key(self.host, owner))
                for endpoint in tree.nodes:
                    if (endpoint.bl_idname in {"ShaderNodeOutputMaterial", "ShaderNodeOutputWorld", "ShaderNodeOutputLight"}
                            and getattr(endpoint, "is_active_output", True)):
                        for socket in endpoint.inputs:
                            self.input(socket, ())
        finally:
            self.owner = previous_owner

    def add_dependency(self, value):
        _collect_dependency(value, self.dependencies, self.dependency_pointers)


