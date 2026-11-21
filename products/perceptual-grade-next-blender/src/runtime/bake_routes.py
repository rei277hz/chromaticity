"""Discover a bake's native domain and freeze its effective input identity.

This module retains no Blender objects between calls. Image freshness uses
inexpensive RNA values and file metadata. ``describe`` also validates UV
triangles before accepting a request. The caller tracks pixel and mesh edits
through dependency invalidation.
Generated Grade kernels are deliberately absent from input fingerprints.
"""

# pg-book: technical-report/en#next-policy.bake

from collections.abc import Mapping
import hashlib
import json
import math
from pathlib import Path

from ..kernel.color_ui import COLOR_FIELDS
from ..kernel.lut import STACK_COMPOSITION_SCHEMA, STACK_INVERSE_SCHEMA
from . import bake_graph
from .bake_images import datablock_key, route_datablock
from .compositor_effects import compositor_occurrences, matching_compositor_occurrences
from .shader_scene import shader_scene_inventory


SCHEMA = 1
MAX_PIXEL_BYTES = 512 * 1024 * 1024
DEFAULT_UV_SIZE = 2048
MAX_UV_SIZE = 16384
_COMPOSITOR_OVERRIDES = frozenset(("compositor_device", "compositor_precision"))
_COMPOSITOR_POINTWISE = frozenset((
    "CompositorNodeRGB", "CompositorNodeValue", "CompositorNodeMath", "CompositorNodeMixRGB",
))
# These modifiers preserve loop topology and UV coordinates. Blender exposes
# a viewport evaluated mesh to Python, which cannot certify render-only
# topology/UV changes, so other enabled render modifiers require application
# before this initial UV bake route can validate its final surface.
UV_PRESERVING_MODIFIERS = frozenset((
    "CAST", "CORRECTIVE_SMOOTH", "LAPLACIANSMOOTH", "NORMAL_EDIT",
    "SIMPLE_DEFORM", "SMOOTH", "WARP", "WAVE", "WEIGHTED_NORMAL",
))
BAKE_DOMAIN = "_pg_next_bake_domain"
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
TONE_FIELDS = ("input_black", "input_shadows", "input_midtones", "input_white",
               "input_highlights", "fit", "peak_nits")
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


def is_bake_target(node):
    return getattr(node, "bl_idname", None) in GRADE_TYPES | STACK_TYPES


def _identity(value):
    if value is None:
        return None
    uid = getattr(value, "session_uid", None)
    if uid is not None:
        return (type(value).__name__, int(uid))
    pointer = getattr(value, "as_pointer", None)
    return (type(value).__name__, int(pointer()) if pointer else id(value))


def _semantic_identity(value, seen=None):
    """Stable save/reload identity used only in persisted signatures."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    seen = set() if seen is None else seen
    runtime_key = _identity(value)
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
                _semantic_identity(owner, seen), library_path)
    return (kind, str(getattr(value, "name", "")), filepath, library_path)


def _same(left, right):
    return left is not None and right is not None and _identity(left) == _identity(right)


def backend_signature(route):
    """Fingerprint the evaluator used for the bake."""
    return _digest((route["render_engine"], route.get("cycles_device"),
                    route.get("render_layers_backends")))


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
    key = _identity(value)
    if key not in dependency_seen:
        dependency_seen.add(key)
        dependencies.append(value)
        if hasattr(value, "matrix_world"):
            _collect_dependency(getattr(value, "data", None), dependencies,
                                dependency_seen)


def _rna_state(value, seen=None, depth=0, dependencies=None, dependency_seen=None,
               *, exclude=()):
    """Snapshot writable semantic RNA, including ramps, curves and mappings."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return _plain(value)
    seen = set() if seen is None else seen
    dependency_seen = set() if dependency_seen is None else dependency_seen
    key = _identity(value)
    if key in seen:
        return ("reference", _semantic_identity(value))
    if depth > 12:
        raise RouteBlocked("graph_complex", "Bake native inputs exceed the fingerprint depth limit")
    properties = getattr(getattr(value, "bl_rna", None), "properties", None)
    if properties is None:
        if hasattr(value, "__dict__"):
            return tuple(sorted((name, _rna_state(
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
            frozen = (_semantic_identity(item), _dependency_state(item, seen | {key}, depth + 1))
        elif prop.type == "COLLECTION":
            frozen = tuple(_rna_state(
                entry, seen | {key}, depth + 1, dependencies, dependency_seen,
            ) for entry in item)
        else:
            frozen = _rna_state(item, seen | {key}, depth + 1,
                                dependencies, dependency_seen)
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
    key = _identity(value)
    if key in seen:
        return ("reference", _semantic_identity(value))
    if depth > 12:
        raise RouteBlocked("graph_complex", "Bake referenced data exceeds its fingerprint depth limit")
    kind = str(getattr(value, "type", ""))
    if kind and hasattr(value, "matrix_world"):
        data = getattr(value, "data", None)
        return (
            "object", kind, _plain(getattr(value, "matrix_world", ())),
            _rna_state(data, seen | {key}, depth + 1)
            if data is not None and kind in {"CAMERA", "LIGHT"} else None,
        )
    name = str(getattr(getattr(value, "bl_rna", None), "identifier", type(value).__name__))
    if name in {"Camera", "World"} or name.endswith("Light"):
        return (name, _rna_state(value, seen, depth + 1))
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
    if _same(root, target):
        return ((),)
    key = _identity(root)
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
    if not path or not _same(path[0], root) or not _same(path[-1], target):
        return None
    names = []
    for parent, child in zip(path, path[1:]):
        choices = [node for node in parent.nodes if _same(getattr(node, "node_tree", None), child)]
        active = getattr(parent.nodes, "active", None)
        if active is not None and any(_same(active, item) for item in choices):
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
        if not _same(scene, owner) or context.get("owner_kind") != "compositor":
            raise RouteBlocked("owner", "The bake scene or graph owner is unavailable")
        path = tuple(context.get("group_path", ()))
        matches = []
        for effect, root in matching_compositor_occurrences(host, scene, context):
            try:
                selected, parents = _resolve_path(root, path)
            except RouteBlocked:
                continue
            if _same(selected, tree):
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
            matches = [item for item in candidates if _same(item[index], preferred)]
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


def _owner(host, node, context):
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
        if not _same(selected, tree):
            raise RouteBlocked("occurrence", "The selected node-group occurrence changed")
        if kind == "world" and not _same(getattr(scene, "world", None), owner):
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
    preferred = [item for item in candidates if _same(item[1], getattr(space, "id", None))]
    if not preferred:
        preferred = [item for item in candidates if _same(item[2], getattr(space, "node_tree", None))]
    if not preferred:
        active = getattr(getattr(context, "object", None), "active_material", None)
        preferred = [item for item in candidates if _same(item[1], active)]
        if not preferred:
            preferred = [item for item in candidates if _same(item[1], getattr(scene, "world", None))]
    chosen = preferred or candidates
    if len(chosen) != 1:
        raise RouteBlocked("owner", "Choose the scene, material or World containing this node")
    kind, owner, root = chosen[0]
    if scene is None:
        raise RouteBlocked("scene", "Bake requires a scene context")
    if kind == "world" and not _same(getattr(scene, "world", None), owner):
        raise RouteBlocked("world_scene", "The selected World is not used by this scene")
    return kind, owner, scene, _occurrence_parents(space, root, tree), {}


def _grade_settings(node):
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
        _semantic_identity(image),
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


def _digest(value):
    return hashlib.sha256(json.dumps(value, separators=(",", ":"), sort_keys=True).encode("utf8")).hexdigest()


def _cache_geometry(obj):
    for item in (*tuple(getattr(obj, "modifiers", ())), *tuple(getattr(obj, "constraints", ()))):
        if (getattr(item, "type", None) in {"MESH_SEQUENCE_CACHE", "MESH_CACHE", "TRANSFORM_CACHE"}
                or getattr(item, "cache_file", None) is not None):
            raise RouteBlocked("mesh_cache", "Bake does not support Alembic or CacheFile geometry")


def _baked_sampler(node, image):
    """Find only the native sampler bound to the authoritative baked Image."""
    tree = getattr(node, "node_tree", None)
    if tree is not None and tree.get(bake_graph.WRAPPER):
        reader = bake_graph.marked(tree, bake_graph.READER)
        if reader is None or not _same(getattr(reader, "image", None), image):
            raise RouteBlocked("baked_sampler", "Bake source wrapper has no matching Image reader")
        return reader, (str(reader.name),)
    pending = [(tree, ())]
    seen = set()
    while pending:
        tree, path = pending.pop()
        key = _identity(tree)
        if tree is None or key in seen:
            continue
        seen.add(key)
        for candidate in tree.nodes:
            if (candidate.bl_idname in {"ShaderNodeTexImage", "CompositorNodeImage"}
                    and _same(getattr(candidate, "image", None), image)):
                return candidate, (*path, str(candidate.name))
            child = getattr(candidate, "node_tree", None)
            if child is not None:
                pending.append((child, (*path, str(candidate.name))))
    return node, None


def _geometry_observation(obj):
    """Stable mesh metadata for saved receipts. Mesh edits also emit dependency updates."""
    _cache_geometry(obj)
    mesh = getattr(obj, "data", None)
    is_mesh = getattr(obj, "type", None) == "MESH" and mesh is not None
    layers = tuple((str(layer.name), len(layer.data), bool(layer.active_render))
                   for layer in getattr(mesh, "uv_layers", ())) if is_mesh else ()
    return (_semantic_identity(obj), _semantic_identity(mesh),
            bool(getattr(obj, "hide_render", False)),
            (len(mesh.vertices), len(mesh.loops), len(mesh.polygons), layers) if is_mesh else None,
            tuple(tuple(float(value) for value in row) for row in getattr(obj, "matrix_world", ())),
            tuple(_rna_state(item) for item in getattr(obj, "modifiers", ())),
            tuple(_semantic_identity(item.material) for item in getattr(obj, "material_slots", ())))


def _instance_observations(inventory):
    bindings = tuple((_semantic_identity(obj), _semantic_identity(obj.instance_collection))
                     for obj in inventory.objects
                     if getattr(obj, "instance_type", None) == "COLLECTION")
    collections = tuple(
        (_semantic_identity(collection), bool(getattr(collection, "hide_render", False)),
         _plain(getattr(collection, "instance_offset", ())),
         tuple(_semantic_identity(obj) for obj in collection.objects),
         tuple(_semantic_identity(child) for child in collection.children))
        for collection in inventory.collections
    )
    return bindings, collections


class _Walker:
    def __init__(self, host, scene, *, owner_kind, owner, full, compositor,
                 compositor_locator, dependencies=None):
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
        self.coordinate_depth = 0
        self.unknown_compositor_extent = False

    def input(self, socket, parents):
        links = _links(socket)
        if len(links) > 1 and not getattr(socket, "is_multi_input", False):
            raise RouteBlocked("input_links", "Bake input has multiple effective sources")
        self.graph.append(("input", tuple(_semantic_identity(item) for item in parents),
                           _semantic_identity(socket.node), _socket_name(socket),
                           None if links else _plain(getattr(socket, "default_value", None)),
                           tuple((_semantic_identity(link.from_node), _socket_name(link.from_socket)) for link in links)))
        if links:
            for link in links:
                self.output(link.from_node, link.from_socket, parents)

    def _observe(self, node, output, parents, semantic=None):
        state = (_rna_state(node, dependencies=self.dependencies,
                            dependency_seen=self.dependency_pointers)
                 if semantic is None else semantic)
        inputs = tuple(item for item in node.inputs
                       if semantic is None or item.name in {"Color", "Alpha"})
        sockets = tuple((_socket_name(item), _plain(getattr(item, "default_value", None)),
                         tuple((_semantic_identity(link.from_node), _socket_name(link.from_socket))
                               for link in _links(item))) for item in inputs)
        defaults = tuple((_socket_name(item), _plain(getattr(item, "default_value", None)))
                         for item in node.outputs if hasattr(item, "default_value"))
        self.graph.append((tuple(_semantic_identity(item) for item in parents), _semantic_identity(node),
                           node.bl_idname, _socket_name(output), state, sockets, defaults))

    def _image(self, node, image, output, parents, *, baked=False):
        if image is None:
            raise RouteBlocked("baked_unbound" if baked else "source_unbound",
                               "Bake source Image is unbound")
        image_identity = _identity(image)
        if image_identity not in self.image_states:
            self.image_states[image_identity] = _image_state(
                self.host, image, full=self.full,
            )
            self._add_dependency(image)
        state, width, height = self.image_states[image_identity]
        self.image_pointers.add(_identity(image))
        key = (tuple(_semantic_identity(item) for item in parents),
               _semantic_identity(node), _semantic_identity(image))
        previous = self.images.get(key)
        alpha = output.name in {"Alpha", "Baked Alpha"}
        sampler, reader_path = _baked_sampler(node, image) if baked else (node, ())
        item = dict(group_path=tuple(str(item.name) for item in parents), node_name=str(node.name),
                    owner=self.owner, reader_path=reader_path,
                    image_key=datablock_key(self.host, image), width=width, height=height,
                    alpha_linked=alpha or bool(previous and previous[1]["alpha_linked"]),
                    interpolation=str(getattr(sampler, "interpolation", "Linear")),
                    extension=str(getattr(sampler, "extension", "REPEAT")), baked=baked)
        if self.owner[0] == "compositor":
            item.update(self.compositor_locator)
        self.images[key] = (state, item)
        if (baked and not self.compositor
                and image.get(BAKE_DOMAIN) == "UV"):
            self.reasons.add("upstream_uv_bake")
        vector = next((item for item in node.inputs if item.name == "Vector"), None)
        if baked:
            self.graph.append((key, "baked_sampling", item["interpolation"], item["extension"],
                               None if vector is None else _plain(getattr(vector, "default_value", None)),
                               () if vector is None else tuple((_semantic_identity(link.from_node), _socket_name(link.from_socket))
                                                               for link in _links(vector))))
        if vector is not None and _links(vector):
            self.reasons.add("linked_coordinates")
            self.coordinate_depth += 1
            try:
                self.input(vector, parents)
            finally:
                self.coordinate_depth -= 1

    def output(self, node, output, parents):
        node_key = _identity(node)
        key = (node_key, _socket_name(output), tuple(_identity(item) for item in parents))
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
                bypass = tuple(link.from_socket for link in node.internal_links if _same(link.to_socket, output))
                if len(bypass) != 1:
                    raise RouteBlocked("muted_output", "Bake cannot resolve this muted node output")
                self.graph.append((_semantic_identity(node), _socket_name(output),
                                   "muted", _socket_name(bypass[0])))
                self.input(bypass[0], parents)
                return
            if kind == "ShaderNodeShaderToRGB":
                raise RouteBlocked("shader_to_rgb", "Bake does not support Shader to RGB")
            if kind in GRADE_TYPES | STACK_TYPES | PER_NODE_TYPES:
                if (output.name in {"Baked Color", "Baked Alpha"}
                        or bool(getattr(node, "pg_use_bake", False))):
                    self.graph.append((_semantic_identity(node), _socket_name(output), "baked"))
                    self._image(node, getattr(node, "pg_bake_image", None), output, parents, baked=True)
                    return
                if output.name == "Alpha":
                    alpha = next((item for item in node.inputs if item.name == "Alpha"), None)
                    if alpha is not None:
                        self.graph.append((_semantic_identity(node), "Alpha", "alpha",
                                           _plain(getattr(alpha, "default_value", None)),
                                           tuple((_semantic_identity(link.from_node), _socket_name(link.from_socket))
                                                 for link in _links(alpha))))
                        self.input(alpha, parents)
                    return
                self._observe(node, output, parents, _grade_settings(node))
                self.upstream_grades.setdefault(node_key, node)
                for socket in node.inputs:
                    if socket.name in {"Color", "Alpha"}:
                        self.input(socket, parents)
                return
            if kind in READER_TYPES:
                self.graph.append((_semantic_identity(node), _socket_name(output), "baked_reader"))
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
        scene_key = _identity(scene)
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
             _semantic_identity(getattr(layer, "material_override", None)),
             _semantic_identity(getattr(layer, "world_override", None)))
            for layer in inventory.view_layers
        )
        objects = inventory.objects
        camera = getattr(scene, "camera", None)
        self._add_dependency(camera)
        summary = (_semantic_identity(scene), layer_name, layer_overrides,
                   _instance_observations(inventory),
                   _rna_state(scene.render, exclude=_COMPOSITOR_OVERRIDES),
                   _rna_state(engine_settings),
                   _semantic_identity(camera), _dependency_state(camera),
                   _rna_state(getattr(scene, "world", None),
                              dependencies=self.dependencies,
                              dependency_seen=self.dependency_pointers))
        self.render_observations.append((*summary, tuple(
            (_geometry_observation(obj),
             _rna_state(getattr(obj, "data", None)) if getattr(obj, "type", None) in {"LIGHT", "CAMERA"} else None)
            for obj in objects)))
        for obj in objects:
            self._add_dependency(obj)
            self._add_dependency(getattr(obj, "data", None))
        for collection in inventory.collections:
            self._add_dependency(collection)
        owners = inventory.owners
        for _kind, owner in owners:
            self._add_dependency(owner)
        owner_settings = tuple((_semantic_identity(owner), _rna_state(
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

    def _add_dependency(self, value):
        _collect_dependency(value, self.dependencies, self.dependency_pointers)


def _intersection_area(subject, clip):
    orientation = sum(clip[i][0] * clip[(i + 1) % 3][1] - clip[(i + 1) % 3][0] * clip[i][1]
                      for i in range(3))
    sign = 1. if orientation >= 0. else -1.
    polygon = list(subject)
    for index in range(3):
        ax, ay = clip[index]
        bx, by = clip[(index + 1) % 3]
        previous, polygon = polygon, []
        if not previous:
            return 0.
        prior = previous[-1]
        prior_side = sign * ((bx - ax) * (prior[1] - ay) - (by - ay) * (prior[0] - ax))
        for current in previous:
            side = sign * ((bx - ax) * (current[1] - ay) - (by - ay) * (current[0] - ax))
            if (side >= -1e-12) != (prior_side >= -1e-12):
                dx, dy = current[0] - prior[0], current[1] - prior[1]
                edge_x, edge_y = bx - ax, by - ay
                denominator = edge_x * dy - edge_y * dx
                if abs(denominator) > 1e-20:
                    t = (edge_x * (ay - prior[1]) - edge_y * (ax - prior[0])) / denominator
                    polygon.append((prior[0] + t * dx, prior[1] + t * dy))
            if side >= -1e-12:
                polygon.append(current)
            prior, prior_side = current, side
    return abs(sum(polygon[i][0] * polygon[(i + 1) % len(polygon)][1]
                   - polygon[(i + 1) % len(polygon)][0] * polygon[i][1]
                   for i in range(len(polygon)))) * .5 if len(polygon) >= 3 else 0.


def _validate_nonoverlap(triangles):
    bins = {}
    comparisons = 0
    for index, points in enumerate(triangles):
        xs, ys = tuple(p[0] for p in points), tuple(p[1] for p in points)
        cells = {(x, y) for x in range(max(0, int(min(xs) * 32)), min(31, int(max(xs) * 32)) + 1)
                 for y in range(max(0, int(min(ys) * 32)), min(31, int(max(ys) * 32)) + 1)}
        candidates = set()
        for cell in cells:
            candidates.update(bins.get(cell, ()))
        comparisons += len(candidates)
        if comparisons > 250000:
            raise RouteBlocked("uv_complex", "UV overlap check exceeded its bounded work limit")
        for other in candidates:
            prior = triangles[other]
            if (max(p[0] for p in prior) <= min(xs) + 1e-12
                    or max(xs) <= min(p[0] for p in prior) + 1e-12
                    or max(p[1] for p in prior) <= min(ys) + 1e-12
                    or max(ys) <= min(p[1] for p in prior) + 1e-12):
                continue
            if _intersection_area(points, prior) > 1e-10:
                raise RouteBlocked("uv_overlap", "UV Bake does not support overlapping faces")
        for cell in cells:
            bins.setdefault(cell, []).append(index)


def _uv(obj, *, full):
    if obj is None or getattr(obj, "type", None) != "MESH" or obj.data is None:
        raise RouteBlocked("mesh", "UV Bake requires an active mesh object")
    _cache_geometry(obj)
    for modifier in getattr(obj, "modifiers", ()):
        if (getattr(modifier, "show_render", True)
                and getattr(modifier, "type", None) not in UV_PRESERVING_MODIFIERS):
            raise RouteBlocked(
                "uv_modifier",
                "Apply unsupported topology, UV or deformation modifiers before UV Bake: "
                + str(getattr(modifier, "name", getattr(modifier, "type", "unknown"))),
            )
    mesh = obj.data
    layer = next((item for item in mesh.uv_layers if item.active_render), None)
    if layer is None:
        raise RouteBlocked("uv_missing", "UV Bake requires an active render UV map")
    if not layer.data or len(layer.data) != len(mesh.loops):
        raise RouteBlocked("uv_incomplete", "UV Bake active render UV map is incomplete")
    if full:
        coordinates = tuple(tuple(float(v) for v in item.uv) for item in layer.data)
        if any(not math.isfinite(v) or not -1e-7 <= v <= 1.0000001 for point in coordinates for v in point):
            raise RouteBlocked("uv_tile", "UV Bake supports only finite UVs in the 0-1 tile")
        mesh.calc_loop_triangles()
        triangles = tuple(tuple(coordinates[index] for index in item.loops) for item in mesh.loop_triangles)
        if not triangles:
            raise RouteBlocked("uv_empty", "UV Bake mesh has no UV-mapped faces")
        for points in triangles:
            area = abs(sum(points[i][0] * points[(i + 1) % 3][1]
                           - points[(i + 1) % 3][0] * points[i][1] for i in range(3))) * .5
            if area <= 1e-12:
                raise RouteBlocked("uv_degenerate", "UV Bake map contains a degenerate face")
        _validate_nonoverlap(triangles)
    return str(layer.name)


def _dimension(node, key):
    value = getattr(node, "pg_bake_" + key, None)
    if value is None:
        getter = getattr(node, "get", None)
        value = getter("_pg_next_bake_" + key, DEFAULT_UV_SIZE) if getter else DEFAULT_UV_SIZE
    return int(value)


def _describe(node, context, *, full, dependencies=None, upstream_grades=None):
    import bpy
    if not is_bake_target(node):
        raise RouteBlocked("target", "Bake is available only for shared Grade and Grade Stack nodes")
    if getattr(getattr(node, "id_data", None), "bl_idname", None) not in {"ShaderNodeTree", "CompositorNodeTree"}:
        raise RouteBlocked("target", "Bake requires a Shader or Compositor graph")
    kind, owner, scene, parents, locator = _owner(bpy, node, context)
    compositor = kind == "compositor"
    collected_dependencies = [] if dependencies is not None else None
    walker = _Walker(bpy, scene, owner_kind=kind, owner=owner, full=full, compositor=compositor,
                     compositor_locator=locator, dependencies=collected_dependencies)
    for socket in node.inputs:
        if socket.name in {"Color", "Alpha"}:
            walker.input(socket, parents)
    destination = getattr(node, "pg_bake_image", None)
    bound_domain = destination.get(BAKE_DOMAIN) if destination is not None else None
    domain = "COMPOSITOR" if compositor else ("UV" if walker.reasons or len(walker.images) > 1 else "IMAGE")
    if not compositor and bound_domain == "UV":
        domain = "UV"
        walker.reasons.add("existing_uv_binding")
    if len(walker.images) > 1:
        walker.reasons.add("multiple_images")
    if destination is not None and _identity(destination) in walker.image_pointers:
        raise RouteBlocked("destination_feedback",
                           "Bake destination is also an effective input and would create a feedback loop")
    if domain == "UV" and bound_domain in {"IMAGE", "COMPOSITOR"}:
        raise RouteBlocked("destination_domain", "Clear the Image-domain destination before starting a UV Bake")
    if compositor and bound_domain == "UV":
        raise RouteBlocked("destination_domain", "Compositor Bake cannot write a UV-domain destination")
    obj = None
    uv_map = material_slot = None
    canvas_size = None
    if domain == "UV":
        if kind != "material":
            raise RouteBlocked("world_uv", "World Bake supports only Image-domain inputs")
        if isinstance(context, Mapping):
            obj = route_datablock(bpy, bpy.data.objects, context, "object")
        else:
            obj = getattr(context or bpy.context, "object", None)
        uv_map = _uv(obj, full=full)
        walker._add_dependency(obj)
        walker._add_dependency(getattr(obj, "data", None))
        if not any(_same(obj, item) for item in scene.objects):
            raise RouteBlocked("mesh_scene", "UV Bake active mesh is not in the selected scene")
        if obj.hide_render:
            raise RouteBlocked("mesh_hidden", "UV Bake active mesh is disabled for rendering")
        slots = tuple(index for index, slot in enumerate(obj.material_slots) if _same(slot.material, owner))
        if not slots:
            raise RouteBlocked("material_slot", "UV Bake active mesh does not use the selected material")
        active = int(getattr(obj, "active_material_index", slots[0]))
        material_slot = active if active in slots else slots[0]
        if destination is not None and bound_domain == "UV":
            width, height = (int(v) for v in destination.size) if full else (
                destination.get("_pg_next_bake_width"), destination.get("_pg_next_bake_height"))
        else:
            width, height = _dimension(node, "width"), _dimension(node, "height")
    elif domain == "IMAGE":
        first = next(iter(walker.images.values()), None)
        width, height = (first[1]["width"], first[1]["height"]) if first else (1, 1)
    elif walker.unknown_compositor_extent:
        width = height = None
    elif len(walker.images) == 1:
        first = next(iter(walker.images.values()))[1]
        width, height = first["width"], first["height"]
    elif not walker.images:
        percentage = int(scene.render.resolution_percentage)
        width = max(1, scene.render.resolution_x * percentage // 100)
        height = max(1, scene.render.resolution_y * percentage // 100)
        canvas_size = (width, height)
    else:
        width = height = None
    if width is not None and height is not None:
        if min(width, height) < 1 or width * height * 16 > MAX_PIXEL_BYTES or (domain == "UV" and max(width, height) > MAX_UV_SIZE):
            raise RouteBlocked("dimensions", "Bake dimensions exceed the 512 MiB pixel budget")
    render_engine = None if compositor else "CYCLES"
    evaluator = ({"render_layers_backends": tuple(walker.rendered.values())} if compositor
                 else {"shader_backend": "CYCLES_CPU", "cycles_device": "CPU"})
    result = dict(schema=SCHEMA, domain=domain, width=width, height=height,
                  scene=str(scene.name), scene_key=datablock_key(bpy, scene),
                  frame=int(scene.frame_current),
                  subframe=float(scene.frame_subframe), render_engine=render_engine,
                  owner_kind=kind, owner_name=str(owner.name), owner_key=datablock_key(bpy, owner),
                  group_path=tuple(str(item.name) for item in parents), node_name=str(node.name),
                  object_name=str(obj.name) if obj is not None else None,
                  object_key=datablock_key(bpy, obj) if obj is not None else None,
                  material_slot=material_slot, uv_map=uv_map,
                  reasons=tuple(sorted(walker.reasons)),
                  images=tuple(item[1] for item in walker.images.values()),
                  canvas_size=canvas_size,
                  **evaluator, **locator)
    colorspace = getattr(bpy.data, "colorspace", None)
    working_space = (getattr(colorspace, "working_space_interop_id", None),
                     getattr(colorspace, "working_space", None))
    receipt_observation = (
        SCHEMA, domain, width if domain == "UV" else None,
        height if domain == "UV" else None, _semantic_identity(scene),
        _semantic_identity(owner), _semantic_identity(node),
        tuple(_semantic_identity(item) for item in parents),
        result["frame"], result["subframe"], render_engine, working_space,
        evaluator.get("cycles_device"),
        _grade_settings(node), tuple(walker.graph),
        tuple((key, state) for key, (state, _sampler) in walker.images.items()),
        _geometry_observation(obj) if obj is not None else None,
        tuple(walker.render_observations),
        material_slot, uv_map,
    )
    result["receipt_signature"] = _digest(receipt_observation)
    # The managed image supplies its actual dimensions for persisted receipts.
    # Pending requests have no image yet and must carry the expected canvas.
    result["request_signature"] = (
        _digest((result["receipt_signature"], "scene_canvas", canvas_size))
        if canvas_size is not None else result["receipt_signature"]
    )
    if dependencies is not None:
        existing = {_identity(item) for item in dependencies}
        for item in collected_dependencies:
            key = _identity(item)
            if key not in existing:
                existing.add(key)
                dependencies.append(item)
    if upstream_grades is not None:
        existing = {_identity(item) for item in upstream_grades}
        upstream_grades.extend(grade for key, grade in walker.upstream_grades.items()
                               if key not in existing)
    return result


def describe(node, context=None, *, dependencies=None, upstream_grades=None):
    """Return a value-only request after validating UVs and source Images.

    When provided, ``dependencies`` receives each effective source Image and
    referenced Object/Mesh once. It is a caller-owned transient list; the
    returned route never contains Blender IDs.

    ``upstream_grades`` is another transient list. It receives each live Grade
    or Grade Stack node whose kernel will be used by this route, once.

    ``request_signature`` augments the durable receipt with the expected size
    for canvas-sized outputs. Both are available from ``preview`` and omit
    transient dirty state. Only an explicit Bake request checks that UV
    triangles are nondegenerate, inside the 0-1 tile, and nonoverlapping.
    """
    return _describe(node, context, full=True, dependencies=dependencies,
                     upstream_grades=upstream_grades)


def preview(node, context=None, *, dependencies=None):
    """Return route controls without pixel/file content reads or UV overlap work."""
    return _describe(node, context, full=False, dependencies=dependencies)


def observe(node, context=None, *, dependencies=None):
    """Return a passive eligibility observation suitable for node UI drawing."""
    try:
        route = preview(node, context, dependencies=dependencies)
        return dict(state="ready", code=None, detail=None, route=route)
    except RouteBlocked as error:
        return dict(state="blocked", code=error.code, detail=str(error), route=None)
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError) as error:
        return dict(state="blocked", code="unavailable", detail=str(error), route=None)
