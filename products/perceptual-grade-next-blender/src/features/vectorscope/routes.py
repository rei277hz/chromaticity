"""Freeze the selected Grade scope and its render-domain identity."""

from collections.abc import Mapping
import hashlib

from ...runtime.capture_graph import (
    COMPOSITOR_OVERRIDES, GRADE_TYPES, PER_NODE_TYPES, RouteBlocked, Walker,
    digest, identity, instance_observations, owner_for_node, rna_state, same,
    semantic_identity,
)
from ...runtime.capture_images import datablock_key, route_datablock
from ...runtime.shader_scene import shader_scene_inventory


def _vectorscope_size(width, height):
    width, height = int(width), int(height)
    if min(width, height) < 1:
        raise RouteBlocked("dimensions", "Vectorscope capture has no pixel domain")
    scale = min(1.0, 512 / max(width, height))
    return max(1, int(round(width * scale))), max(1, int(round(height * scale)))


def _vectorscope_geometry_observation(obj):
    mesh = getattr(obj, "data", None)
    is_mesh = getattr(obj, "type", None) == "MESH" and mesh is not None
    layers = tuple((str(layer.name), len(layer.data), bool(layer.active_render))
                   for layer in getattr(mesh, "uv_layers", ())) if is_mesh else ()
    return (
        semantic_identity(obj), semantic_identity(mesh),
        bool(getattr(obj, "hide_render", False)),
        (len(mesh.vertices), len(mesh.loops), len(mesh.polygons), layers) if is_mesh else None,
        tuple(tuple(float(value) for value in row)
              for row in getattr(obj, "matrix_world", ())),
        tuple(rna_state(item) for item in getattr(obj, "modifiers", ())),
        tuple(semantic_identity(item.material) for item in getattr(obj, "material_slots", ())),
    )


def vectorscope_mesh_witness(mesh):
    """Hash mesh topology, positions, UVs and typed attributes on a mesh update."""
    from array import array

    digest = hashlib.sha256()
    digest.update(repr((len(mesh.vertices), len(mesh.edges), len(mesh.loops),
                        len(mesh.polygons))).encode("ascii"))

    def add_collection(collection, property_name, code, components):
        values = array(code, [0]) * (len(collection) * components)
        collection.foreach_get(property_name, values)
        digest.update(memoryview(values).cast("B"))

    add_collection(mesh.vertices, "co", "f", 3)
    add_collection(mesh.edges, "vertices", "i", 2)
    add_collection(mesh.loops, "vertex_index", "i", 1)
    add_collection(mesh.polygons, "loop_start", "i", 1)
    add_collection(mesh.polygons, "loop_total", "i", 1)
    add_collection(mesh.polygons, "material_index", "i", 1)

    for layer in mesh.uv_layers:
        digest.update(layer.name.encode("utf8"))
        add_collection(layer.data, "uv", "f", 2)

    properties = {
        "FLOAT": ("value", "f", 1),
        "INT": ("value", "i", 1),
        "FLOAT_VECTOR": ("vector", "f", 3),
        "FLOAT_COLOR": ("color", "f", 4),
        "BYTE_COLOR": ("color", "f", 4),
        "BOOLEAN": ("value", "b", 1),
        "FLOAT2": ("vector", "f", 2),
        "INT8": ("value", "b", 1),
        "INT32_2D": ("value", "i", 2),
        "QUATERNION": ("value", "f", 4),
    }
    for attribute in mesh.attributes:
        description = properties.get(attribute.data_type)
        if description is None:
            raise TypeError(f"Unsupported mesh attribute type {attribute.data_type}")
        property_name, code, components = description
        digest.update(repr((attribute.name, attribute.domain,
                            attribute.data_type, len(attribute.data))).encode("utf8"))
        add_collection(attribute.data, property_name, code, components)
    return digest.hexdigest()


def _vectorscope_structural_graph(graph, images):
    structure = []
    for item in graph:
        if len(item) == 6 and item[0] == "input":
            _kind, parents, node, socket, _default, links = item
            structure.append(("input", parents, node, socket, links))
        elif len(item) == 4 and item[2] == "muted":
            structure.append(item)
        elif len(item) == 3 and item[1] == "baked_sampling":
            structure.append(item)
        elif len(item) >= 4 and isinstance(item[0], tuple) and isinstance(item[2], str):
            parents, node, kind, output = item[:4]
            structure.append((parents, node, kind, output))
        else:
            structure.append(item[:2] if len(item) >= 2 else item)
    image_sources = tuple(
        (tuple(descriptor["image_key"]), descriptor.get("node_name"),
         descriptor.get("group_path"), bool(descriptor.get("dynamic")))
        for _state, descriptor in images
    )
    return tuple(structure), image_sources


def _vectorscope_coverage_invariant(owner, node):
    """Prove the selected Grade's color cannot change AOV coverage."""
    tree = getattr(owner, "node_tree", None)
    owner_kind = str(getattr(getattr(owner, "bl_rna", None), "identifier",
                             type(owner).__name__))
    if (owner_kind != "Material"
            or tree is None or not same(tree, getattr(node, "id_data", None))):
        return False
    color = node.outputs.get("Color")
    if color is None:
        return False
    color_links = tuple(getattr(color, "links", ()))
    if len(color_links) != 1:
        return False
    color_link = color_links[0]
    shader = getattr(color_link, "to_node", None)
    shader_input = getattr(color_link, "to_socket", None)
    kind = getattr(shader, "bl_idname", None)
    primary_input = {"ShaderNodeEmission": "Color", "ShaderNodeBsdfPrincipled": "Base Color"}.get(kind)
    if (primary_input is None or getattr(shader, "mute", False)
            or getattr(shader_input, "name", None) != primary_input):
        return False
    if kind == "ShaderNodeBsdfPrincipled":
        for name, expected in (("Alpha", 1.0), ("Transmission Weight", 0.0)):
            socket = shader.inputs.get(name)
            if socket is None or socket.links or socket.default_value != expected:
                return False
    if any(getattr(socket, "links", ()) for socket in node.outputs if not same(socket, color)):
        return False
    if len(shader.outputs) != 1:
        return False
    surface_links = tuple(getattr(shader.outputs[0], "links", ()))
    if len(surface_links) != 1:
        return False
    output_link = surface_links[0]
    output = getattr(output_link, "to_node", None)
    surface_socket = getattr(output_link, "to_socket", None)
    if (getattr(output, "bl_idname", None) != "ShaderNodeOutputMaterial"
            or not getattr(output, "is_active_output", True)
            or getattr(surface_socket, "name", None) != "Surface"):
        return False
    for endpoint in tree.nodes:
        if (getattr(endpoint, "bl_idname", None) == "ShaderNodeOutputMaterial"
                and getattr(endpoint, "is_active_output", True)):
            surface = endpoint.inputs.get("Surface")
            if (surface is None or len(getattr(surface, "links", ())) != 1
                    or not same(getattr(surface.links[0], "from_node", None), shader)
                    or not same(getattr(surface.links[0], "to_node", None), endpoint)
                    or getattr(endpoint.inputs.get("Volume"), "links", ())
                    or getattr(endpoint.inputs.get("Displacement"), "links", ())):
                return False
    return True


def describe_vectorscope(node, context=None, viewport=None, *, dependencies=None,
                         upstream_grades=None, watch=None, scope_capture="input"):
    """Freeze a Grade scope capture and its render-domain identity."""
    import bpy

    if scope_capture not in {"input", "appearance"}:
        raise ValueError("Vectorscope capture kind is not supported")
    tree_type = getattr(getattr(node, "id_data", None), "bl_idname", None)
    if getattr(node, "bl_idname", None) not in GRADE_TYPES | PER_NODE_TYPES:
        raise RouteBlocked("target", "Vectorscope requires a Grade node")
    if tree_type not in {"ShaderNodeTree", "CompositorNodeTree"}:
        raise RouteBlocked("target", "Vectorscope requires a Shader or Compositor Grade")
    color = node.inputs.get("Color")
    if color is None or color.type != "RGBA":
        raise RouteBlocked("input", "Grade has no Color input")

    context = context or bpy.context
    kind, owner, scene, parents, locator = owner_for_node(bpy, node, context)
    compositor = kind == "compositor"
    selected_view = None if viewport is None else dict(viewport)
    layer = (scene.view_layers.get(selected_view.get("view_layer", ""))
             if selected_view is not None else None)
    if layer is None:
        context_layer = getattr(context, "view_layer", None)
        layer = (scene.view_layers.get(getattr(context_layer, "name", ""))
                 or (scene.view_layers[0] if scene.view_layers else None))
    if layer is None:
        raise RouteBlocked("view_layer", "Vectorscope scene has no active view layer")

    if compositor:
        percentage = int(scene.render.resolution_percentage)
        requested = (
            max(1, int(scene.render.resolution_x * percentage / 100)),
            max(1, int(scene.render.resolution_y * percentage / 100)),
        )
        width, height = _vectorscope_size(*requested)
        view = dict(
            source="compositor", scene=str(scene.name), frame=int(scene.frame_current),
            frame_subframe=float(scene.frame_subframe), view_layer=str(layer.name),
            engine=str(scene.render.engine), width=width, height=height,
        )
    else:
        if selected_view is None or selected_view.get("source") != "viewport":
            raise RouteBlocked("viewport", "Shader vectorscope needs an active 3D viewport")
        if selected_view.get("scene") not in (None, str(scene.name)):
            raise RouteBlocked("scene", "Shader vectorscope viewport belongs to another scene")
        if not all(name in selected_view for name in (
                "view_matrix", "projection_matrix", "clip_start", "clip_end")):
            raise RouteBlocked("viewport", "Shader vectorscope viewport projection is incomplete")
        width, height = _vectorscope_size(selected_view.get("width", 0),
                                         selected_view.get("height", 0))
        view = dict(selected_view)
        view.update(viewport_width=int(selected_view["width"]),
                    viewport_height=int(selected_view["height"]))
        view.update(scene=str(scene.name), frame=int(scene.frame_current),
                    frame_subframe=float(scene.frame_subframe),
                    view_layer=str(layer.name), engine=str(scene.render.engine),
                    width=width, height=height)

    collected_dependencies = []
    walker = Walker(
        bpy, scene, owner_kind=kind, owner=owner, full=False,
        compositor=compositor, compositor_locator=locator,
        dependencies=collected_dependencies, allow_dynamic_images=True,
    )
    walker.input(color, parents)
    alpha = node.inputs.get("Alpha") if not compositor else None
    if alpha is not None:
        walker.input(alpha, parents)
    walker.add_dependency(node.id_data)
    tree_pointer = getattr(node.id_data, "as_pointer", None)
    if tree_pointer is not None:
        walker.input_tree_pointers.add(int(tree_pointer()))
    for parent in parents:
        walker.add_dependency(parent.id_data)
        parent_pointer = getattr(parent.id_data, "as_pointer", None)
        if parent_pointer is not None:
            walker.input_tree_pointers.add(int(parent_pointer()))
    input_graph = tuple(walker.graph)
    input_images = tuple((state, descriptor) for state, descriptor in walker.images.values())
    if not compositor:
        owner_tree = getattr(owner, "node_tree", None)
        walker.add_dependency(owner)
        walker.add_dependency(owner_tree)
        walker.add_dependency(scene)
        inventory = shader_scene_inventory(scene, view_layers=(layer,))
        visible_names = view.get("visible_objects")
        visible_names = None if visible_names is None else set(visible_names)
        objects = tuple(obj for obj in inventory.objects
                        if visible_names is None or obj.name in visible_names)
        for obj in objects:
            walker.add_dependency(obj)
            walker.add_dependency(getattr(obj, "data", None))
        for collection in inventory.collections:
            walker.add_dependency(collection)
        for _owner_kind, scene_owner in inventory.owners:
            walker.add_dependency(scene_owner)
            walker.add_dependency(getattr(scene_owner, "node_tree", None))
        scene_observation = (
            semantic_identity(scene),
            rna_state(scene.render, exclude=COMPOSITOR_OVERRIDES),
            rna_state(getattr(scene, "cycles", None)),
            rna_state(getattr(scene, "eevee", None)),
            instance_observations(inventory),
            tuple(_vectorscope_geometry_observation(obj) for obj in objects),
            tuple((layer.name, bool(layer.use),
                   semantic_identity(getattr(layer, "material_override", None)),
                   semantic_identity(getattr(layer, "world_override", None)))
                  for layer in inventory.view_layers),
            tuple((semantic_identity(scene_owner),
                   rna_state(scene_owner, exclude={"node_tree"}))
                  for _owner_kind, scene_owner in inventory.owners),
        )
    else:
        scene_observation = (
            semantic_identity(scene),
            rna_state(scene.render, exclude=COMPOSITOR_OVERRIDES),
            tuple(walker.render_observations),
        )

    still_images = tuple(
        descriptor for _state, descriptor in walker.images.values()
        if not descriptor.get("dynamic")
    )
    dynamic_images = tuple(
        descriptor for _state, descriptor in walker.images.values()
        if descriptor.get("dynamic")
    )
    object_value = None if compositor else getattr(context, "object", None)
    if (not compositor and isinstance(context, Mapping)
            and context.get("object_key") is not None):
        object_value = route_datablock(bpy, bpy.data.objects, context, "object")
    object_key = None
    if object_value is not None and any(same(object_value, item) for item in scene.objects):
        object_key = datablock_key(bpy, object_value)
        walker.add_dependency(object_value)
        walker.add_dependency(getattr(object_value, "data", None))

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
    input_graph_covered = bool(
        input_graph and input_graph[0][0] == "input"
        and input_graph[0][3] == "Color" and not walker.visiting
    )
    coverage_invariant = bool(
        not compositor and input_graph_covered
        and _vectorscope_coverage_invariant(owner, node)
    )
    if watch is not None:
        owner_pointer = getattr(owner, "as_pointer", None)
        owner_tree_pointer = getattr(getattr(owner, "node_tree", None), "as_pointer", None)
        watch.update(
            input_graph_covered=input_graph_covered,
            coverage_invariant=coverage_invariant,
            input_tree_pointers=tuple(sorted(walker.input_tree_pointers)),
            owner_pointer=None if owner_pointer is None else int(owner_pointer()),
            owner_tree_pointer=(None if owner_tree_pointer is None
                                else int(owner_tree_pointer())),
        )

    route = dict(
        schema=1, scene=str(scene.name), scene_key=datablock_key(bpy, scene),
        frame=int(scene.frame_current), subframe=float(scene.frame_subframe),
        owner_kind=kind, owner_name=str(owner.name), owner_key=datablock_key(bpy, owner),
        group_path=tuple(str(item.name) for item in parents), node_name=str(node.name),
        socket_name="Color", root_key=locator.get("root_key"),
        effect_name=locator.get("effect_name"), object_key=object_key,
        has_render_layers=bool(walker.render_layers),
        input_graph_covered=input_graph_covered,
        coverage_invariant=coverage_invariant,
        width=width, height=height, view=view, images=still_images,
        dynamic_images=dynamic_images,
    )
    if scope_capture == "appearance":
        route["scope_capture"] = scope_capture
    structural_graph, image_sources = _vectorscope_structural_graph(input_graph, input_images)
    source_observation = (
        "pg-vectorscope-source-v1", kind, route["owner_key"], route["root_key"],
        route["effect_name"], route["group_path"], semantic_identity(node),
        structural_graph, image_sources,
    )
    route["source_signature"] = digest(source_observation)
    route["capture_signature"] = digest((
        "pg-vectorscope-capture-v1", route["source_signature"],
        route.get("scope_capture", "input"),
        route["frame"], route["subframe"], view, scene_observation,
        coverage_invariant, input_graph, input_images,
    ))
    return route


