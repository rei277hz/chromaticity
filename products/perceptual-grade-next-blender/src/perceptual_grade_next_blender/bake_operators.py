"""User-facing native Bake operators for the Next extension.

The operators intentionally keep Blender RNA and operator invocation here. All
identity checks, route admission, evaluator selection and Image publication
continue through the checked adapters.
"""

from itertools import count
import hashlib

import numpy as np

from .bake import BakeRoute
from .image_publication import publish_blender_image
from .native_bake import (
    NativeShaderEvaluator, NativeStackShaderEvaluator, NativeUVShaderEvaluator,
    image_source_from_owner, image_texture_from_owner,
    image_texture_sampling_identity, read_image_rgba, route_facts,
)
from .native_capture import bind_grade_evaluator, bind_stack_evaluator
from .native_compositor_bake import (
    NativeCompositorGradeEvaluator, NativeCompositorStackEvaluator,
    capture_compositor_signal, unique_compositor_group_path,
)
from .output_gateway import OutputGateway, OutputRequest
from .project_readiness import (
    inspect_project_owners, project_readiness_runtime, refresh_project_readiness,
)


_OPERATIONS = count(1)
_CLASSES = ()
_MENUS = []
_GATEWAY = None
_BAKE_READER_LEASES = {}


def _owner_identity(tree, node):
    try:
        return f"{tree.as_pointer()}:{node.as_pointer()}"
    except (AttributeError, ReferenceError, RuntimeError) as error:
        raise RuntimeError("Bake owner has no stable Blender identity") from error


def _owner_readiness(tree, node):
    identity = _owner_identity(tree, node)
    snapshot = inspect_project_owners((tree,), generation=0)
    matches = tuple(owner for owner in snapshot.owners if owner.identity == identity)
    if len(matches) != 1 or not matches[0].ready:
        reason = matches[0].reason if matches else "Bake owner is not installed"
        raise RuntimeError(reason or "Bake owner is not ready")
    return matches[0]


def _active_object(context):
    active = getattr(context, "active_object", None)
    if active is None:
        active = getattr(
            getattr(getattr(context, "view_layer", None), "objects", None),
            "active", None,
        )
    return active


def _tree_contains(root, target, seen=None):
    if root is None or target is None:
        return False
    seen = set() if seen is None else seen
    target_pointer = _tree_identity(target)
    pointer = _tree_identity(root)
    if pointer and pointer == target_pointer:
        return True
    if not pointer:
        return False
    if pointer in seen:
        return False
    seen.add(pointer)
    return any(
        _tree_contains(getattr(node, "node_tree", None), target, seen)
        for node in getattr(root, "nodes", ())
    )


def _tree_identity(tree):
    original = getattr(tree, "original", None)
    if original is not None:
        tree = original
    try:
        return int(tree.as_pointer())
    except (AttributeError, ReferenceError, RuntimeError):
        return 0


def _owner_material_ids(active_object, owner_tree):
    if getattr(active_object, "type", "") != "MESH":
        raise RuntimeError("UV Bake requires an active mesh object")
    matches = []
    for slot in getattr(active_object, "material_slots", ()):
        material = getattr(slot, "material", None)
        if (material is not None
                and _tree_contains(
                    getattr(getattr(material, "original", None), "node_tree", None)
                    or getattr(material, "node_tree", None), owner_tree)):
            matches.append(int(material.as_pointer()))
    if not matches:
        raise RuntimeError("The selected Grade node is not used by an active-object material")
    return tuple(sorted(set(matches)))


def _material_pointer(material):
    if material is None:
        return 0
    material = getattr(material, "original", None) or material
    try:
        return int(material.as_pointer())
    except (AttributeError, ReferenceError, RuntimeError):
        raise RuntimeError("UV Bake material assignment has no stable identity")


def _uv_source_identity(active_object, owner_tree, context, source_texture):
    """Digest the evaluated mesh domain that the UV Bake will consume."""
    if getattr(active_object, "type", "") != "MESH":
        raise RuntimeError("UV Bake requires an active mesh object")
    if getattr(active_object, "mode", "OBJECT") != "OBJECT":
        raise RuntimeError("Leave Edit Mode before UV baking")
    data = getattr(active_object, "data", None)
    uv_layers = getattr(data, "uv_layers", None)
    active_uv = getattr(uv_layers, "active", None) if uv_layers is not None else None
    if active_uv is None:
        raise RuntimeError("The active object has no UV map")
    uv_name = str(active_uv.name)
    object_material_slots = tuple(
        (str(getattr(slot, "link", "DATA")),
         _material_pointer(getattr(slot, "material", None)))
        for slot in getattr(active_object, "material_slots", ())
    )
    _owner_material_ids(active_object, owner_tree)
    depsgraph = context.evaluated_depsgraph_get()
    evaluated = active_object.evaluated_get(depsgraph)
    mesh = evaluated.to_mesh(preserve_all_data_layers=True, depsgraph=depsgraph)
    try:
        layer = mesh.uv_layers.get(uv_name)
        if layer is None:
            raise RuntimeError("Evaluated mesh lost the active UV map")
        if not mesh.polygons:
            raise RuntimeError("UV Bake requires visible mesh faces")
        evaluated_slots = tuple(getattr(evaluated, "material_slots", ()))
        mesh_materials = tuple(getattr(mesh, "materials", ()))
        material_ids = tuple(
            _material_pointer(getattr(slot, "material", None))
            for slot in evaluated_slots
        )
        slot_links = tuple(str(getattr(slot, "link", "DATA")) for slot in evaluated_slots)
        mesh_material_ids = tuple(_material_pointer(item) for item in mesh_materials)
        owner_material_indices = tuple(
            index for index, slot in enumerate(evaluated_slots)
            for material in (getattr(slot, "material", None),)
            if material is not None
            and _tree_contains(
                getattr(getattr(material, "original", None), "node_tree", None)
                or getattr(material, "node_tree", None), owner_tree)
        )
        if not owner_material_indices:
            raise RuntimeError("Evaluated mesh has no faces using the selected Grade material")
        polygon_material_indices = np.empty(len(mesh.polygons), dtype=np.int32)
        mesh.polygons.foreach_get("material_index", polygon_material_indices)
        if not any(int(index) in owner_material_indices for index in polygon_material_indices):
            raise RuntimeError("Evaluated mesh has no faces using the selected Grade material")
        coordinates = np.empty(len(layer.data) * 2, dtype=np.float32)
        layer.data.foreach_get("uv", coordinates)
        vertices = np.empty(len(mesh.vertices) * 3, dtype=np.float32)
        mesh.vertices.foreach_get("co", vertices)
        loops = np.empty(len(mesh.loops), dtype=np.int32)
        mesh.loops.foreach_get("vertex_index", loops)
        polygon_values = np.empty(len(mesh.polygons) * 2, dtype=np.int32)
        mesh.polygons.foreach_get("loop_start", polygon_values[0::2])
        mesh.polygons.foreach_get("loop_total", polygon_values[1::2])
        matrix = np.asarray(
            [[float(value) for value in row] for row in evaluated.matrix_world],
            dtype=np.float64,
        )
        digest = hashlib.sha256()
        digest.update(repr((
            material_ids, slot_links, mesh_material_ids,
            owner_material_indices, image_texture_sampling_identity(source_texture),
        )).encode("utf8"))
        object_slot_values = np.asarray(
            [(0 if link == "DATA" else 1, pointer)
             for link, pointer in object_material_slots],
            dtype=np.uint64,
        ).reshape((-1, 2))
        for values in (
                coordinates, vertices, loops, polygon_values,
                polygon_material_indices, object_slot_values, matrix):
            digest.update(values.tobytes(order="C"))
        return (
            int(active_object.as_pointer()), int(data.as_pointer()), uv_name,
            digest.hexdigest(), owner_material_indices, material_ids,
            object_material_slots, slot_links, mesh_material_ids,
        )
    finally:
        evaluated.to_mesh_clear()


def _target_image(bpy, source, requested):
    return _target_image_size(bpy, tuple(source.size[:2]), requested)


def _target_image_size(bpy, size, requested):
    if requested:
        target = requested if not isinstance(requested, str) else bpy.data.images.get(requested)
        if target is None:
            raise RuntimeError("Selected Bake Image does not exist")
        return target
    width, height = (int(value) for value in size[:2])
    image = bpy.data.images.new(
        "PG Next Bake Result", width=width, height=height,
        alpha=True, float_buffer=True,
    )
    image.use_half_precision = False
    return image


def _run_bake_transaction(context, operator):
    from .native_admission import acquire_reader, release

    operation = next(_OPERATIONS)
    reader_lease = acquire_reader("bake:%s" % operation)
    if reader_lease is None:
        raise RuntimeError("Native evaluation is busy with another reader or publisher")
    _BAKE_READER_LEASES[operation] = reader_lease
    try:
        return _run_bake_transaction_admitted(context, operator, operation)
    finally:
        if _BAKE_READER_LEASES.get(operation) == reader_lease:
            active = bool(
                _GATEWAY is not None
                and _GATEWAY.state.bake_operation == operation
                and _GATEWAY.state.bake_physical in ("live", "retiring")
            )
            if not active:
                _BAKE_READER_LEASES.pop(operation, None)
                release(reader_lease)


def _run_bake_transaction_admitted(context, operator, operation):
    import bpy
    from .project_readiness import project_readiness_runtime, refresh_project_readiness
    from .scope_runtime import _project_node_trees
    from .native_admission import release

    space = getattr(context, "space_data", None)
    tree = getattr(space, "edit_tree", None)
    owner = getattr(context, "active_node", None)
    if owner is None:
        owner = getattr(space, "edit_node", None)
    if tree is None or owner is None:
        raise RuntimeError("Select a Perceptual Grade or Grade Stack node first")
    backend = owner.get("perceptual_grade_next_backend")
    if backend not in {"native_grade_graph", "native_stack_lut"}:
        raise RuntimeError("Selected node is not a Perceptual Grade Next owner")
    if tree.bl_idname not in {"ShaderNodeTree", "CompositorNodeTree"}:
        raise RuntimeError("Bake requires an editable Shader or Compositor node tree")
    graph = "shader" if tree.bl_idname == "ShaderNodeTree" else "compositor"
    # Polling is advisory; build the readiness receipt from the current file.
    refresh_project_readiness(tuple(_project_node_trees(bpy)))
    readiness = _owner_readiness(tree, owner)
    source_texture = None
    source = None
    compositor_root = None
    compositor_path = ()
    if graph == "shader":
        source_texture = image_texture_from_owner(owner)
        source = source_texture.image
        pixels = read_image_rgba(source)
    else:
        domain = str(getattr(operator, "domain", "IMAGE")).upper()
        if domain != "IMAGE":
            raise RuntimeError("Compositor Bake supports the Image domain only")
        compositor_root = getattr(context.scene, "compositing_node_group", None)
        if compositor_root is None:
            raise RuntimeError("The active scene has no Compositor node tree")
        compositor_path = unique_compositor_group_path(compositor_root, tree)
        pixels = capture_compositor_signal(
            context.scene, compositor_root, tree, owner, compositor_path,
            stage="input",
        )
    digest = hashlib.sha256(pixels.tobytes(order="C")).hexdigest()
    domain = str(getattr(operator, "domain", "IMAGE")).upper()
    active_object = None
    uv_identity = None
    source_id = (f"{source.as_pointer()}:{digest}" if graph == "shader" else
                 f"{compositor_root.as_pointer()}:{owner.as_pointer()}:{compositor_path}:{digest}")
    if domain == "UV":
        if graph != "shader":
            raise RuntimeError("Compositor Bake supports the Image domain only")
        active_object = _active_object(context)
        if active_object is None:
            raise RuntimeError("UV Bake requires an active mesh object")
        uv_identity = _uv_source_identity(active_object, tree, context, source_texture)
        source_id += ":uv:" + hashlib.sha256(repr(uv_identity).encode("utf8")).hexdigest()
    elif domain != "IMAGE":
        raise RuntimeError("Unsupported Shader Bake domain")
    source_revision = int(hashlib.sha256(source_id.encode("utf8")).hexdigest()[:15], 16) + 1
    target = (_target_image(bpy, source, operator.target_image)
              if graph == "shader" else
              _target_image_size(bpy, pixels.shape[1::-1], operator.target_image))
    facts = route_facts(
        context.scene, domain=domain, target_image=target,
        context=context, node_tree=tree,
    )
    evaluator = "native_grade_graph" if backend == "native_grade_graph" else "stack_65_lut"
    request = OutputRequest(
        operation=operation, owner=readiness.identity, source_revision=source_revision,
        source_id=source_id, evaluator=evaluator,
        evaluator_id=readiness.evaluator_id, manifest_id=readiness.manifest_id,
        final_ready=True, route_id=f"{readiness.identity}:{domain}:{operation}",
    )
    route = BakeRoute(
        request.route_id, domain.lower(), graph,
        evaluator, request.source_revision, request.source_id,
    )
    # Refresh the shared project authority at click time. A cached poll result
    # never grants a Bake, and an isolated workflow would lose owner receipts.
    runtime = project_readiness_runtime()
    gateway = OutputGateway(runtime.workflow)
    global _GATEWAY
    _GATEWAY = gateway
    try:
        gateway.request_bake(request)
        frozen = gateway.freeze_bake_source(request, route, facts, pixels)
        # Freeze the source while no native reader is live. The native
        # evaluator is admitted only after this exact source snapshot exists.
        gateway.start_bake(operation)
        if graph == "compositor":
            input_check, output = capture_compositor_signal(
                context.scene, compositor_root, tree, owner, compositor_path,
                stage="output",
            )
            if not np.array_equal(input_check, frozen.rgba):
                raise RuntimeError("Compositor source changed during Bake")
            if output.shape != frozen.rgba.shape:
                raise RuntimeError("Compositor Grade changed the frozen pixel domain")
            current_owner = _owner_readiness(tree, owner)
            if (current_owner.evaluator_id != readiness.evaluator_id
                    or current_owner.manifest_id != readiness.manifest_id
                    or context.scene.compositing_node_group is not compositor_root
                    or unique_compositor_group_path(compositor_root, tree) != compositor_path):
                raise RuntimeError("Compositor Grade owner or scene route changed during Bake")
            if backend == "native_grade_graph":
                native = NativeCompositorGradeEvaluator(
                    readiness.evaluator_id, readiness.manifest_id,
                    frozen.rgba, output,
                )
                binding = bind_grade_evaluator(owner, request, native.evaluate_native)
                result = gateway.capture_grade(
                    native_evaluator=binding, request=request,
                    result_id=f"{request.route_id}:result", frozen_input=frozen,
                )
            else:
                accepted_lut = bind_stack_evaluator(owner, request)
                if not np.array_equal(output[..., 3], frozen.rgba[..., 3]):
                    raise RuntimeError("Native Compositor Stack changed alpha during Bake")
                native = NativeCompositorStackEvaluator(
                    readiness.evaluator_id, readiness.manifest_id,
                    frozen.rgba, output, accepted_lut.value,
                )
                result = gateway.capture_stack(
                    lut=native, request=request,
                    result_id=f"{request.route_id}:result", frozen_input=frozen,
                )
        elif backend == "native_grade_graph":
            image_evaluator = NativeShaderEvaluator(
                bpy, context.scene, owner, source, operator.domain,
                expected_evaluator=evaluator, source_texture=source_texture,
            )
            native = (NativeUVShaderEvaluator(
                image_evaluator, active_object, uv_identity[2], tuple(target.size[:2]),
                uv_identity[4],
            ) if domain == "UV" else image_evaluator)
            binding = bind_grade_evaluator(owner, request, native.evaluate_native)
            result = gateway.capture_grade(
                native_evaluator=binding, request=request,
                result_id=f"{request.route_id}:result", frozen_input=frozen,
            )
        else:
            # Evaluate the installed 65^3 lookup graph in Blender so source
            # Image sampling, color-space conversion, shaper and interpolation
            # match the actual Shader route.
            bind_stack_evaluator(owner, request)
            image_evaluator = NativeShaderEvaluator(
                bpy, context.scene, owner, source, operator.domain,
                expected_evaluator=evaluator, source_texture=source_texture,
            )
            native = (NativeUVShaderEvaluator(
                image_evaluator, active_object, uv_identity[2], tuple(target.size[:2]),
                uv_identity[4],
            ) if domain == "UV" else image_evaluator)
            binding = NativeStackShaderEvaluator(
                native, readiness.evaluator_id, readiness.manifest_id,
            )
            result = gateway.capture_stack(
                lut=binding, request=request,
                result_id=f"{request.route_id}:result", frozen_input=frozen,
            )
        if domain == "UV":
            if _uv_source_identity(
                    active_object, tree, context, current_source_texture := image_texture_from_owner(owner)
            ) != uv_identity:
                raise RuntimeError("Active object UV source changed during Bake")
            current_source = current_source_texture
            current_pixels = read_image_rgba(current_source.image)
            if (current_source.as_pointer() != source_texture.as_pointer()
                    or hashlib.sha256(current_pixels.tobytes(order="C")).hexdigest() != digest):
                raise RuntimeError("UV Bake source Image changed during Bake")
            current_owner = _owner_readiness(tree, owner)
            if (current_owner.evaluator_id != readiness.evaluator_id
                    or current_owner.manifest_id != readiness.manifest_id):
                raise RuntimeError("UV Bake Grade owner changed during Bake")
        gateway.retire_bake_reader(operation)
        lease = _BAKE_READER_LEASES.pop(operation, None)
        if lease is not None:
            release(lease)
        gateway.stage_bake(operation, result)
        gateway.publish_bake(operation)
        publication = publish_blender_image(
            target, result.rgba, operation=operation, bpy_module=bpy,
        )
        gateway.publish_bake_image(operation, result, publication)
        gateway.complete_bake(request, result.result_id)
    except BaseException:
        try:
            if gateway.state.bake_physical in ("live", "retiring"):
                gateway.retire_bake_reader(operation)
        except RuntimeError:
            pass
        if gateway.state.bake_physical == "none":
            lease = _BAKE_READER_LEASES.pop(operation, None)
            if lease is not None:
                release(lease)
        try:
            gateway.cancel_bake(operation)
        except RuntimeError:
            pass
        raise
    return target


def _run_bake(context, operator):
    if getattr(operator, "target_image", ""):
        return _run_bake_transaction(context, operator)

    import bpy

    existing_images = {
        int(image.as_pointer()) for image in bpy.data.images
    }
    try:
        return _run_bake_transaction(context, operator)
    except BaseException:
        # An implicit target is created before route preflight. Remove only that
        # unpublished, unused datablock; committed recovery backing owns its Image.
        for image in tuple(bpy.data.images):
            try:
                pointer = int(image.as_pointer())
                is_new_target = (
                    pointer not in existing_images
                    and image.name.startswith("PG Next Bake Result")
                )
                has_recovery_backing = bool(
                    image.get("perceptual_grade_next_bake_active_backup")
                )
                if is_new_target and image.users == 0 and not has_recovery_backing:
                    bpy.data.images.remove(image, do_unlink=True)
            except (ReferenceError, RuntimeError, TypeError, ValueError):
                continue
        raise


def register():
    global _CLASSES, _MENUS
    if _CLASSES:
        return _CLASSES
    import bpy

    class PGNEXT_OT_bake(bpy.types.Operator):
        bl_idname = "node.pg_next_bake"
        bl_label = "Bake Perceptual Grade Next"
        bl_description = "Bake the selected native Grade or accepted 65^3 Stack evaluator"
        bl_options = {"REGISTER", "UNDO"}

        target_image: bpy.props.StringProperty(
            name="Bake Image",
            description="Choose an existing Image or leave empty to create one",
            default="",
        )
        domain: bpy.props.EnumProperty(
            name="Bake Domain", items=(("IMAGE", "Image", ""), ("UV", "UV", "")),
            default="IMAGE",
        )

        def draw(self, context):
            tree = getattr(getattr(context, "space_data", None), "edit_tree", None)
            if getattr(tree, "bl_idname", None) == "ShaderNodeTree":
                self.layout.prop(self, "domain")
            self.layout.prop_search(
                self, "target_image", bpy.data, "images", text="Bake Image",
            )

        def invoke(self, context, _event):
            return context.window_manager.invoke_props_dialog(self)

        @classmethod
        def poll(cls, context):
            space = getattr(context, "space_data", None)
            node = getattr(context, "active_node", None)
            return bool(
                getattr(getattr(space, "edit_tree", None), "bl_idname", None)
                in {"ShaderNodeTree", "CompositorNodeTree"}
                and getattr(node, "get", lambda *_: None)("perceptual_grade_next_backend")
                in {"native_grade_graph", "native_stack_lut"}
            )

        def execute(self, context):
            try:
                _run_bake(context, self)
            except (RuntimeError, TypeError, ValueError) as error:
                self.report({"ERROR"}, str(error))
                return {"CANCELLED"}
            return {"FINISHED"}

    _CLASSES = (PGNEXT_OT_bake,)
    for cls in _CLASSES:
        bpy.utils.register_class(cls)
    for name in ("NODE_MT_category_shader_color", "NODE_MT_category_compositor_color"):
        menu = getattr(bpy.types, name, None)
        if menu is not None:
            menu.append(_bake_menu)
            _MENUS.append(menu)
    return _CLASSES


def _bake_menu(menu, context):
    space = getattr(context, "space_data", None)
    node = getattr(context, "active_node", None)
    if (getattr(space, "edit_tree", None) is None
            or getattr(getattr(space, "edit_tree", None), "bl_idname", None)
            not in {"ShaderNodeTree", "CompositorNodeTree"}
            or node is None):
        return
    backend = getattr(node, "get", lambda *_: None)("perceptual_grade_next_backend")
    if backend not in {"native_grade_graph", "native_stack_lut"}:
        return
    menu.layout.separator()
    menu.layout.operator("node.pg_next_bake", icon="RENDER_STILL")


def unregister():
    global _CLASSES, _MENUS, _GATEWAY
    import bpy
    while _MENUS:
        menu = _MENUS.pop()
        try:
            menu.remove(_bake_menu)
        except (ValueError, ReferenceError):
            pass
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
    _CLASSES = ()
    _GATEWAY = None


__all__ = ("register", "unregister")
