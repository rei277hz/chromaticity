"""Discover a bake's native domain and freeze its effective input identity.

This module retains no Blender objects between calls. ``preview`` and
``observe`` inspect inexpensive RNA values and file metadata; ``describe`` also
fingerprints pixels, external image contents and UV geometry for a request.
Generated Grade kernels are deliberately absent from input fingerprints.
"""

# pg-book: technical-report/en#next-policy.bake

from array import array
from collections.abc import Mapping
import hashlib
import json
import math
from pathlib import Path


SCHEMA = 1
MAX_PIXEL_BYTES = 512 * 1024 * 1024
DEFAULT_UV_SIZE = 2048
MAX_UV_SIZE = 16384
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
    owner = getattr(value, "id_data", None)
    if owner is not None and owner is not value:
        return ("node", kind, str(getattr(value, "name", "")),
                _semantic_identity(owner, seen), library_path)
    return (kind, str(getattr(value, "name", "")),
            str(getattr(value, "filepath", "")), library_path)


def _same(left, right):
    return left is not None and right is not None and _identity(left) == _identity(right)


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


def _rna_state(value, seen=None, depth=0):
    """Snapshot writable semantic RNA, including ramps, curves and mappings."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return _plain(value)
    seen = set() if seen is None else seen
    key = _identity(value)
    if key in seen:
        return ("reference", _semantic_identity(value))
    if depth > 12:
        raise RouteBlocked("graph_complex", "Bake native inputs exceed the fingerprint depth limit")
    properties = getattr(getattr(value, "bl_rna", None), "properties", None)
    if properties is None:
        if hasattr(value, "__dict__"):
            return tuple(sorted((name, _rna_state(item, seen | {key}, depth + 1))
                                for name, item in vars(value).items()
                                if name not in _UI_PROPERTIES and not name.startswith("_")
                                and not callable(item)))
        return _plain(value)
    result = []
    for prop in properties:
        name = prop.identifier
        if name == "color" and hasattr(value, "inputs") and hasattr(value, "outputs"):
            continue
        if name in _UI_PROPERTIES or (prop.is_readonly and prop.type not in {"POINTER", "COLLECTION"}):
            continue
        item = getattr(value, name)
        if prop.type == "POINTER" and item is not None and hasattr(item, "session_uid"):
            frozen = (_semantic_identity(item), _dependency_state(item, seen | {key}, depth + 1))
        elif prop.type == "COLLECTION":
            frozen = tuple(_rna_state(entry, seen | {key}, depth + 1) for entry in item)
        else:
            frozen = _rna_state(item, seen | {key}, depth + 1)
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


def _owner(host, node, context):
    tree = node.id_data
    compositor = tree.bl_idname == "CompositorNodeTree"
    if isinstance(context, Mapping):
        kind = context.get("owner_kind")
        scene = host.data.scenes.get(context.get("scene"))
        values = {"material": host.data.materials, "world": host.data.worlds,
                  "compositor": host.data.scenes}.get(kind)
        owner = values.get(context.get("owner_name")) if values is not None else None
        root = (getattr(owner, "compositing_node_group", None) if kind == "compositor"
                else getattr(owner, "node_tree", None))
        path = tuple(context.get("group_path", ()))
        if scene is None or owner is None or root is None:
            raise RouteBlocked("owner", "The bake scene or graph owner is unavailable")
        selected, parents = _resolve_path(root, path)
        if not _same(selected, tree):
            raise RouteBlocked("occurrence", "The selected node-group occurrence changed")
        if kind == "world" and not _same(getattr(scene, "world", None), owner):
            raise RouteBlocked("world_scene", "The selected World is not used by this scene")
        return kind, owner, scene, root, parents
    context = context or host.context
    scene = getattr(context, "scene", None)
    space = getattr(context, "space_data", None)
    candidates = []
    collections = (("compositor", host.data.scenes),) if compositor else (
        ("material", host.data.materials), ("world", host.data.worlds))
    for kind, owners in collections:
        for owner in owners:
            root = (getattr(owner, "compositing_node_group", None) if compositor
                    else getattr(owner, "node_tree", None))
            if root is not None and _group_paths(root, tree):
                candidates.append((kind, owner, root))
    preferred = [item for item in candidates if _same(item[1], getattr(space, "id", None))]
    if not preferred:
        preferred = [item for item in candidates if _same(item[2], getattr(space, "node_tree", None))]
    if not preferred and compositor:
        preferred = [item for item in candidates if _same(item[1], scene)]
    if not preferred and not compositor:
        active = getattr(getattr(context, "object", None), "active_material", None)
        preferred = [item for item in candidates if _same(item[1], active)]
        if not preferred:
            preferred = [item for item in candidates if _same(item[1], getattr(scene, "world", None))]
    chosen = preferred or candidates
    if len(chosen) != 1:
        raise RouteBlocked("owner", "Choose the scene, material or World containing this node")
    kind, owner, root = chosen[0]
    if compositor:
        scene = owner
    if scene is None:
        raise RouteBlocked("scene", "Bake requires a scene context")
    if kind == "world" and not _same(getattr(scene, "world", None), owner):
        raise RouteBlocked("world_scene", "The selected World is not used by this scene")
    path = _editor_path(space, root, tree)
    if path is None:
        paths = _group_paths(root, tree)
        if len(paths) != 1:
            raise RouteBlocked("occurrence", "Choose the exact node-group occurrence to bake")
        path = paths[0]
    _tree, parents = _resolve_path(root, path)
    return kind, owner, scene, root, parents


def _grade_settings(node):
    kind = node.bl_idname
    if kind in STACK_TYPES:
        return tuple(_grade_values(entry.grade) for entry in node.pg_stack_entries
                     if entry.enabled and entry.grade is not None)
    owner = getattr(node, "pg_grade", None) if kind in GRADE_TYPES else node
    return _grade_values(owner if owner is not None else node)


def _grade_values(owner):
    linear = getattr(owner, "pg_linear", owner)
    tone = getattr(owner, "pg_tone", owner)
    return (tuple((name, _plain(getattr(linear, name))) for name in LINEAR_FIELDS),
            tuple((name, _plain(getattr(tone, name))) for name in TONE_FIELDS))


def _hash_file(path):
    digest = hashlib.sha256()
    try:
        with Path(path).open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as error:
        raise RouteBlocked("source_file", "Bake source Image file is unavailable: " + str(error)) from error
    return digest.hexdigest()


def _image_state(host, image, *, full):
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
    state = (_semantic_identity(image), source, str(getattr(image, "filepath", "")),
             str(image.colorspace_settings.name), str(image.alpha_mode),
             bool(getattr(image, "is_float", False)), image.get(BAKE_DOMAIN),
             image.get("_pg_next_bake_operation"))
    if not full:
        return state, None, None
    width, height = (int(item) for item in image.size)
    if min(width, height) < 1:
        raise RouteBlocked("source_empty", "Bake source Image has no pixels")
    if width * height * 16 > MAX_PIXEL_BYTES:
        raise RouteBlocked("dimensions", "Bake source Image exceeds the 512 MiB pixel budget")
    if bool(getattr(image, "is_dirty", False)) or source == "GENERATED":
        if not image.has_data:
            raise RouteBlocked("source_empty", "Bake source Image has no loaded pixels")
        count = width * height * int(image.channels)
        pixels = array("f", [0.]) * count
        image.pixels.foreach_get(pixels)
        payload = ("pixels", hashlib.sha256(memoryview(pixels).cast("B")).hexdigest())
    else:
        packed = getattr(image, "packed_file", None)
        if packed is not None:
            data = getattr(packed, "data", None)
            try:
                packed_digest = hashlib.sha256(bytes(data)).hexdigest() if data is not None else None
            except (TypeError, ValueError):
                packed_digest = None
            payload = ("packed", packed_digest, int(getattr(packed, "size", 0)))
        else:
            path = host.path.abspath(image.filepath, library=getattr(image, "library", None))
            payload = ("file", _hash_file(path),
                       tuple((str(candidate), _hash_file(candidate)) for candidate in _sidecars(path)))
        if getattr(image, "has_data", False):
            values = array("f", [0.]) * (width * height * int(image.channels))
            image.pixels.foreach_get(values)
            payload = (*payload, "pixels", hashlib.sha256(memoryview(values).cast("B")).hexdigest())
        else:
            raise RouteBlocked("source_empty", "Bake cannot fingerprint the effective loaded Image pixels")
    return (*state, width, height, int(image.channels), payload), width, height


def _sidecars(path):
    return tuple(item for item in _sidecar_candidates(path) if item.is_file())


def _file_observation(host, image):
    """Return cheap disk facts for passive source invalidation.

    This deliberately avoids opening or hashing files. Exact requests still
    use `_hash_file` and loaded pixel digests in `_image_state`.
    """
    if str(image.source) != "FILE" or getattr(image, "packed_file", None) is not None:
        return None
    try:
        path = Path(host.path.abspath(
            image.filepath, library=getattr(image, "library", None)))
        candidates = (path, *_sidecar_candidates(path))
        result = []
        for candidate in candidates:
            try:
                stat = candidate.stat()
            except OSError:
                result.append((str(candidate), None))
            else:
                result.append((str(candidate), int(stat.st_size), int(stat.st_mtime_ns)))
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
    pending = [getattr(node, "node_tree", None)]
    seen = set()
    while pending:
        tree = pending.pop()
        key = _identity(tree)
        if tree is None or key in seen:
            continue
        seen.add(key)
        for candidate in tree.nodes:
            if (candidate.bl_idname in {"ShaderNodeTexImage", "CompositorNodeImage"}
                    and _same(getattr(candidate, "image", None), image)):
                return candidate
            child = getattr(candidate, "node_tree", None)
            if child is not None:
                pending.append(child)
    return node


def _geometry_digest(label, values):
    """Hash a bounded semantic stream without retaining mesh-sized tuples."""
    digest = hashlib.sha256()
    digest.update(str(label).encode("utf8"))
    for value in values:
        try:
            encoded = json.dumps(_plain(value), separators=(",", ":"),
                                 sort_keys=True).encode("utf8")
        except (TypeError, ValueError, UnicodeError) as error:
            raise RouteBlocked(
                "geometry_attributes",
                "Bake cannot fingerprint mesh attribute data: " + str(error),
            ) from error
        digest.update(len(encoded).to_bytes(8, "little"))
        digest.update(encoded)
    return digest.hexdigest()


def _attribute_value(item, data_type):
    """Read one Blender Attribute/ColorAttribute element by declared type."""
    scalar_types = {"BOOLEAN", "BYTE", "INT", "INT8", "INT32", "INT64",
                    "FLOAT", "FLOAT2", "STRING"}
    vector_types = {"FLOAT_VECTOR", "FLOAT2", "FLOAT3", "FLOAT4",
                    "FLOAT_COLOR", "BYTE_COLOR", "QUATERNION", "FLOAT4X4",
                    "INT16_2D", "INT32_2D"}
    if data_type in scalar_types and hasattr(item, "value"):
        return getattr(item, "value")
    if data_type in vector_types:
        for name in ("vector", "color", "value", "normal"):
            if hasattr(item, name):
                value = getattr(item, name)
                try:
                    return tuple(value)
                except TypeError:
                    if isinstance(value, (bool, int, float, str)):
                        return value
                    raise RouteBlocked(
                        "geometry_attributes",
                        "Bake cannot fingerprint mesh attribute type " + str(data_type),
                    )
    raise RouteBlocked(
        "geometry_attributes",
        "Bake cannot fingerprint unsupported mesh attribute type " + str(data_type),
    )


def _mesh_attributes(mesh):
    """Return digests for generic and color mesh attributes."""
    attributes = []
    seen = set()
    for collection_name in ("attributes", "color_attributes"):
        collection = getattr(mesh, collection_name, ())
        for attribute in collection:
            identity = (str(getattr(attribute, "name", "")),
                        str(getattr(attribute, "domain", "")),
                        str(getattr(attribute, "data_type", "")))
            # Color attributes are also exposed through attributes in some
            # Blender versions; avoid hashing the same channel twice.
            if identity in seen:
                continue
            seen.add(identity)
            data_type = identity[2]
            data = getattr(attribute, "data", None)
            if data is None:
                raise RouteBlocked("geometry_attributes",
                                   "Bake mesh attribute has no readable data")
            values = (_attribute_value(item, data_type) for item in data)
            attributes.append((*identity, len(data), _geometry_digest(identity, values)))
    attributes.sort(key=lambda value: value[:3])
    colors = getattr(mesh, "color_attributes", None)
    selection = tuple((name, _plain(getattr(colors, name, None))) for name in (
        "active_color_name", "default_color_name", "render_color_index",
    ))
    return tuple(attributes), selection


def _vertex_group_state(obj, mesh):
    groups = tuple((int(getattr(group, "index", index)), str(getattr(group, "name", "")))
                   for index, group in enumerate(getattr(obj, "vertex_groups", ())))
    if not groups:
        return groups
    vertices = getattr(mesh, "vertices", None)
    if vertices is None:
        raise RouteBlocked("geometry_attributes", "Bake mesh has unreadable vertex groups")
    def values():
        for index, vertex in enumerate(vertices):
            assignments = getattr(vertex, "groups", None)
            if assignments is None:
                raise RouteBlocked("geometry_attributes", "Bake mesh has unreadable vertex weights")
            yield index, tuple((int(item.group), float(item.weight)) for item in assignments)
    return groups, _geometry_digest("vertex_groups", values())


def _corner_normal_state(mesh):
    has_custom = bool(getattr(mesh, "has_custom_normals", False))
    normals = getattr(mesh, "corner_normals", None)
    if normals is None:
        if has_custom:
            raise RouteBlocked("geometry_attributes", "Bake mesh custom normals are unreadable")
        return has_custom, None
    # RNA collections expose their owning datablock as .data. Iterate the
    # collection itself; wrappers may instead expose an element array there.
    try:
        iter(normals)
        data = normals
    except TypeError:
        data = getattr(normals, "data", None)
        if data is None or data is mesh:
            raise RouteBlocked("geometry_attributes", "Bake mesh corner normals are unreadable")
    if has_custom and len(data) != len(mesh.loops):
        raise RouteBlocked("geometry_attributes", "Bake mesh custom normals are incomplete")
    def values():
        for item in data:
            value = getattr(item, "vector", getattr(item, "normal", None))
            if value is None:
                raise RouteBlocked("geometry_attributes", "Bake mesh corner normal is unreadable")
            yield tuple(float(component) for component in value)
    return has_custom, _geometry_digest("corner_normals", values())


def _geometry_state(obj):
    _cache_geometry(obj)
    mesh = getattr(obj, "data", None)
    geometry = None
    if getattr(obj, "type", None) == "MESH" and mesh is not None:
        polygon_state = (
            (int(item.loop_start), int(item.loop_total), int(item.material_index),
             bool(getattr(item, "use_smooth", False)))
            for item in mesh.polygons
        )
        geometry = (
            _geometry_digest("vertices", (tuple(float(v) for v in item.co)
                                           for item in mesh.vertices)),
            _geometry_digest("polygons", polygon_state),
            _geometry_digest("loops", (int(item.vertex_index) for item in mesh.loops)),
            tuple((str(layer.name), bool(getattr(layer, "active_render", False)),
                   _geometry_digest("uv", (tuple(float(v) for v in item.uv)
                                            for item in layer.data)))
                  for layer in mesh.uv_layers),
            _geometry_digest("edges", (
                (tuple(int(index) for index in item.vertices),
                 bool(getattr(item, "use_edge_sharp", False)))
                for item in getattr(mesh, "edges", ()))),
            bool(getattr(mesh, "use_auto_smooth", False)),
            float(getattr(mesh, "auto_smooth_angle", 0.0)),
            _rna_state(getattr(mesh, "shape_keys", None)),
            _mesh_attributes(mesh),
            _vertex_group_state(obj, mesh),
            _corner_normal_state(mesh),
        )
    return (_semantic_identity(obj), _semantic_identity(mesh), geometry,
            _plain(getattr(obj, "matrix_world", ())), bool(getattr(obj, "hide_render", False)),
            tuple(_rna_state(item) for item in getattr(obj, "modifiers", ())),
            tuple(_rna_state(item) for item in getattr(obj, "constraints", ())),
            tuple(_semantic_identity(item.material) for item in getattr(obj, "material_slots", ())))


def _geometry_observation(obj):
    """Shallow invalidation facts; exact topology and UVs are checked by describe."""
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


class _Walker:
    def __init__(self, host, scene, *, full, compositor):
        self.host, self.scene, self.full = host, scene, full
        self.compositor = compositor
        self.graph = []
        self.images = {}
        self.image_observations = {}
        self.image_pointers = set()
        self.upstream = {}
        self.reasons = set()
        self.visiting = set()
        self.visited = set()
        self.rendered = set()
        self.render_states = []
        self.render_observations = []
        self.coordinate_depth = 0
        self.compositor_native = False

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
        state = _rna_state(node) if semantic is None else semantic
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
        state, width, height = _image_state(self.host, image, full=self.full)
        self.image_pointers.add(_identity(image))
        key = (tuple(_semantic_identity(item) for item in parents),
               _semantic_identity(node), _semantic_identity(image))
        previous = self.images.get(key)
        alpha = output.name in {"Alpha", "Baked Alpha"}
        sampler = _baked_sampler(node, image) if baked else node
        item = dict(group_path=tuple(str(item.name) for item in parents), node_name=str(node.name),
                    image_name=str(image.name), width=width, height=height,
                    alpha_linked=alpha or bool(previous and previous[1]["alpha_linked"]),
                    interpolation=str(getattr(sampler, "interpolation", "Linear")),
                    extension=str(getattr(sampler, "extension", "REPEAT")), baked=baked)
        self.images[key] = (state, item)
        self.image_observations[key] = (
            state[:-4] if self.full else state, bool(getattr(image, "is_dirty", False)),
            int(getattr(getattr(image, "packed_file", None), "size", 0)),
            _file_observation(self.host, image),
        )
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
        key = (_identity(node), _socket_name(output), tuple(_identity(item) for item in parents))
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
                self.upstream[key] = dict(
                    tree_name=str(getattr(getattr(node, "id_data", None), "name", "")),
                    tree_type=str(getattr(getattr(node, "id_data", None), "bl_idname", "")),
                    group_path=tuple(str(item.name) for item in parents),
                    node_name=str(node.name), kind="STACK" if kind in STACK_TYPES else "GRADE")
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
                self.compositor_native = True
                self._render_scene(getattr(node, "scene", None) or self.scene)
            elif kind.startswith("CompositorNode") and kind not in {"CompositorNodeRGB", "CompositorNodeValue"}:
                self.compositor_native = True
            elif kind not in POINTWISE and not self.coordinate_depth:
                self.reasons.add("surface_dependency")
            for socket in node.inputs:
                self.input(socket, parents)
        finally:
            self.visiting.remove(key)
            self.visited.add(key)

    def _render_scene(self, scene):
        key = _identity(scene)
        if key in self.rendered:
            return
        self.rendered.add(key)
        objects = tuple(scene.objects)
        camera = getattr(scene, "camera", None)
        summary = (_semantic_identity(scene), _rna_state(scene.render),
                   _rna_state(getattr(scene, "cycles", None)),
                   _semantic_identity(camera), _dependency_state(camera),
                   _rna_state(getattr(scene, "world", None)))
        self.render_observations.append((*summary, tuple(
            (_geometry_observation(obj),
             _rna_state(getattr(obj, "data", None)) if getattr(obj, "type", None) in {"LIGHT", "CAMERA"} else None)
            for obj in objects)))
        geometry = (tuple((_geometry_state(obj),
                           _rna_state(getattr(obj, "data", None))
                           if getattr(obj, "type", None) in {"LIGHT", "CAMERA"} else None)
                         for obj in objects) if self.full
                    else tuple(_geometry_observation(obj) for obj in objects))
        self.render_states.append((*summary, geometry))
        owners = [getattr(scene, "world", None)]
        for obj in objects:
            owners.extend(slot.material for slot in getattr(obj, "material_slots", ()))
            if getattr(obj, "type", None) == "LIGHT":
                owners.append(obj.data)
        owner_settings = tuple((_semantic_identity(owner), _rna_state(owner))
                               for owner in owners if owner is not None)
        self.render_states.append(("owner_settings", owner_settings))
        self.render_observations.append(("owner_settings", owner_settings))
        for owner in owners:
            tree = getattr(owner, "node_tree", None)
            if tree is None:
                continue
            for endpoint in tree.nodes:
                if (endpoint.bl_idname in {"ShaderNodeOutputMaterial", "ShaderNodeOutputWorld", "ShaderNodeOutputLight"}
                        and getattr(endpoint, "is_active_output", True)):
                    for socket in endpoint.inputs:
                        self.input(socket, ())


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


def _describe(node, context, *, full):
    import bpy
    if not is_bake_target(node):
        raise RouteBlocked("target", "Bake is available only for shared Grade and Grade Stack nodes")
    if getattr(getattr(node, "id_data", None), "bl_idname", None) not in {"ShaderNodeTree", "CompositorNodeTree"}:
        raise RouteBlocked("target", "Bake requires a Shader or Compositor graph")
    kind, owner, scene, root, parents = _owner(bpy, node, context)
    compositor = kind == "compositor"
    walker = _Walker(bpy, scene, full=full, compositor=compositor)
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
    if domain == "UV":
        if scene.render.engine != "CYCLES":
            raise RouteBlocked("cycles", "UV Bake requires the Cycles render engine")
        if kind != "material":
            raise RouteBlocked("world_uv", "World Bake supports only Image-domain inputs")
        if isinstance(context, Mapping):
            obj = bpy.data.objects.get(context.get("object_name")) if context.get("object_name") else None
        else:
            obj = getattr(context or bpy.context, "object", None)
        uv_map = _uv(obj, full=full)
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
    elif walker.compositor_native:
        width = height = None
    elif len(walker.images) == 1:
        first = next(iter(walker.images.values()))[1]
        width, height = first["width"], first["height"]
    elif not walker.images:
        scale = int(scene.render.resolution_percentage) / 100.
        width, height = max(1, int(scene.render.resolution_x * scale)), max(1, int(scene.render.resolution_y * scale))
    else:
        width = height = None
    if width is not None and height is not None:
        if min(width, height) < 1 or width * height * 16 > MAX_PIXEL_BYTES or (domain == "UV" and max(width, height) > MAX_UV_SIZE):
            raise RouteBlocked("dimensions", "Bake dimensions exceed the 512 MiB pixel budget")
    result = dict(schema=SCHEMA, domain=domain, width=width, height=height,
                  scene=str(scene.name), frame=int(scene.frame_current),
                  subframe=float(scene.frame_subframe), owner_kind=kind, owner_name=str(owner.name),
                  group_path=tuple(str(item.name) for item in parents), node_name=str(node.name),
                  object_name=str(obj.name) if obj is not None else None,
                  material_slot=material_slot, uv_map=uv_map,
                  reasons=tuple(sorted(walker.reasons)),
                  images=tuple(item[1] for item in walker.images.values()),
                  upstream=tuple(walker.upstream.values()), signature=None)
    colorspace = getattr(bpy.data, "colorspace", None)
    working_space = (getattr(colorspace, "working_space_interop_id", None),
                     getattr(colorspace, "working_space", None))
    observation = (SCHEMA, domain, width if domain == "UV" else None,
                   height if domain == "UV" else None, _semantic_identity(scene),
                   _semantic_identity(owner), _semantic_identity(node),
                   tuple(_semantic_identity(item) for item in parents),
                   result["frame"], result["subframe"], scene.render.engine, working_space,
                   _grade_settings(node), tuple(walker.graph),
                   tuple(walker.image_observations.items()),
                   _geometry_observation(obj) if obj is not None else None,
                   tuple(walker.render_observations),
                   material_slot, uv_map)
    result["observation_signature"] = _digest(observation)
    if full:
        terminal = tuple((_socket_name(socket), _plain(getattr(socket, "default_value", None)),
                          tuple((_semantic_identity(link.from_node), _socket_name(link.from_socket))
                                for link in _links(socket)))
                         for socket in node.inputs if socket.name in {"Color", "Alpha"})
        signature = (SCHEMA, domain, width, height, _semantic_identity(scene),
                     _semantic_identity(owner), _semantic_identity(node),
                     tuple(_semantic_identity(item) for item in parents),
                     result["frame"], result["subframe"], scene.render.engine, working_space,
                     _grade_settings(node), terminal, tuple(walker.graph),
                     tuple((key, item[0]) for key, item in walker.images.items()),
                     tuple(walker.render_states), _rna_state(scene.render) if compositor else None,
                     _geometry_state(obj) if obj is not None else None,
                     material_slot, uv_map)
        result["signature"] = _digest(signature)
    return result


def describe(node, context=None):
    """Return a value-only exact request, reading source pixels and UV geometry."""
    return _describe(node, context, full=True)


def preview(node, context=None):
    """Return route controls without pixel/file content reads or UV overlap work."""
    return _describe(node, context, full=False)


def observe(node, context=None):
    """Return a passive eligibility observation suitable for node UI drawing."""
    try:
        route = preview(node, context)
        return dict(state="ready", code=None, detail=None, signature=route["observation_signature"], route=route)
    except RouteBlocked as error:
        return dict(state="blocked", code=error.code, detail=str(error), signature=None, route=None)
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError) as error:
        return dict(state="blocked", code="unavailable", detail=str(error), signature=None, route=None)
