"""Discover a Bake domain and freeze the input identity for its receipt."""

# pg-book: technical-report/en#next-policy.bake

from collections.abc import Mapping
import math

from .capture_graph import (
    BAKE_DOMAIN, GRADE_TYPES, MAX_PIXEL_BYTES,
    STACK_TYPES, RouteBlocked, Walker, cache_geometry, digest,
    geometry_observation, grade_settings, identity, owner_for_node,
    same, semantic_identity,
)
from .capture_images import datablock_key, route_datablock

SCHEMA = 1
# Version the persisted digest independently of the worker route payload.
FINGERPRINT_SCHEMA = 3
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


def is_bake_target(node):
    return getattr(node, "bl_idname", None) in GRADE_TYPES | STACK_TYPES


def backend_signature(route):
    """Fingerprint the evaluator used for the bake."""
    return digest((route["render_engine"], route.get("cycles_device"),
                    route.get("render_layers_backends")))


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
    cache_geometry(obj)
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
    kind, owner, scene, parents, locator = owner_for_node(bpy, node, context)
    compositor = kind == "compositor"
    collected_dependencies = [] if dependencies is not None else None
    walker = Walker(bpy, scene, owner_kind=kind, owner=owner, full=full, compositor=compositor,
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
    if destination is not None and identity(destination) in walker.image_pointers:
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
        walker.add_dependency(obj)
        walker.add_dependency(getattr(obj, "data", None))
        if not any(same(obj, item) for item in scene.objects):
            raise RouteBlocked("mesh_scene", "UV Bake active mesh is not in the selected scene")
        if obj.hide_render:
            raise RouteBlocked("mesh_hidden", "UV Bake active mesh is disabled for rendering")
        slots = tuple(index for index, slot in enumerate(obj.material_slots) if same(slot.material, owner))
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
        FINGERPRINT_SCHEMA, domain, width if domain == "UV" else None,
        height if domain == "UV" else None, semantic_identity(scene),
        semantic_identity(owner), semantic_identity(node),
        tuple(semantic_identity(item) for item in parents),
        result["frame"], result["subframe"], render_engine, working_space,
        evaluator.get("cycles_device"),
        grade_settings(node), tuple(walker.graph),
        tuple((key, state) for key, (state, _sampler) in walker.images.items()),
        geometry_observation(obj) if obj is not None else None,
        tuple(walker.render_observations),
        material_slot, uv_map,
    )
    result["receipt_signature"] = digest(receipt_observation)
    # The managed image supplies its actual dimensions for persisted receipts.
    # Pending requests have no image yet and must carry the expected canvas.
    result["request_signature"] = (
        digest((result["receipt_signature"], "scene_canvas", canvas_size))
        if canvas_size is not None else result["receipt_signature"]
    )
    if dependencies is not None:
        existing = {identity(item) for item in dependencies}
        for item in collected_dependencies:
            key = identity(item)
            if key not in existing:
                existing.add(key)
                dependencies.append(item)
    if upstream_grades is not None:
        existing = {identity(item) for item in upstream_grades}
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
