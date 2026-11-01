"""Blender-owned source and native Bake adapters for Perceptual Grade Next.

This module is the host boundary for explicit Bakes.  It reads and writes
full-precision Blender Images, builds a temporary native shader evaluation
scene for Grade owners, and leaves lifecycle admission/publication to
``OutputGateway``.  No portable Grade model is used as a pixel evaluator.
"""

from dataclasses import dataclass

import numpy as np

from .bake import BakeRoute, BakeRouteFacts


MAX_PIXEL_BYTES = 512 * 1024 * 1024


def read_image_rgba(image):
    """Read a Blender Image as detached float32 RGBA rows."""
    width, height = (int(value) for value in image.size[:2])
    channels = int(getattr(image, "channels", 4))
    if min(width, height) < 1 or width * height * 16 > MAX_PIXEL_BYTES:
        raise ValueError("Bake Image has an invalid or oversized pixel domain")
    values = np.empty(width * height * channels, dtype=np.float32)
    image.pixels.foreach_get(values)
    values = values.reshape(height, width, channels)
    if channels == 4:
        rgba = values
    elif channels == 3:
        rgba = np.concatenate((values, np.ones((height, width, 1), np.float32)), axis=-1)
    elif channels == 2:
        rgba = np.concatenate((np.repeat(values[..., :1], 3, axis=-1), values[..., 1:2]), axis=-1)
    elif channels == 1:
        rgba = np.concatenate((np.repeat(values, 3, axis=-1), np.ones((height, width, 1), np.float32)), axis=-1)
    else:
        raise ValueError("Bake Image has an unsupported channel count")
    if not np.isfinite(rgba).all():
        raise ValueError("Bake Image contains non-finite pixels")
    return np.ascontiguousarray(rgba, dtype=np.float32)


def write_image_rgba(image, rgba):
    """Write a complete float32 RGBA result into a Blender Image."""
    values = np.asarray(rgba, dtype=np.float32)
    width, height = (int(value) for value in image.size[:2])
    if values.shape != (height, width, 4) or not np.isfinite(values).all():
        raise ValueError("Bake result does not match the destination Image")
    # Route admission checks ``is_float`` before this host write.  Some Blender
    # builds expose that RNA flag as false even for a writable float buffer;
    # half-precision buffers remain unconditionally rejected here.
    if getattr(image, "use_half_precision", False):
        raise RuntimeError("Bake destination must be a full-precision float Image")
    image.use_half_precision = False
    image.pixels.foreach_set(values.reshape(-1))
    image.update()
    return True


def image_source_from_owner(owner_node):
    """Resolve a direct still Image from the owner Color input."""
    return image_texture_from_owner(owner_node).image


def image_texture_from_owner(owner_node):
    """Resolve a direct still Image input for a native Grade/Stack owner."""
    sockets = getattr(owner_node, "inputs", ())
    try:
        socket = sockets.get("Color")
    except AttributeError:
        socket = next((item for item in sockets if getattr(item, "name", "") == "Color"), None)
    if socket is None or len(getattr(socket, "links", ())) != 1:
        raise RuntimeError("Bake requires one direct Color source Image")
    source = socket.links[0].from_node
    if getattr(source, "bl_idname", "") != "ShaderNodeTexImage":
        raise RuntimeError("Bake source must be a native Image Texture")
    inputs = getattr(source, "inputs", ())
    vector = inputs.get("Vector") if hasattr(inputs, "get") else None
    if vector is not None and getattr(vector, "is_linked", False):
        raise RuntimeError("Bake cannot reproduce a linked Image Texture coordinate input")
    if getattr(source, "projection", "FLAT") != "FLAT":
        raise RuntimeError("Bake supports flat Image Texture projection only")
    image = getattr(source, "image", None)
    if image is None:
        raise RuntimeError("Bake source Image is unavailable")
    if getattr(image, "source", "IMAGE") not in {"FILE", "GENERATED", "IMAGE"}:
        raise RuntimeError("Bake supports still Image sources only")
    if getattr(image, "use_multiview", False):
        raise RuntimeError("Bake does not support multiview Images")
    return source


def _rna_value(value):
    if isinstance(value, (str, bool, int, float)):
        return value
    try:
        return tuple(_rna_value(item) for item in value)
    except TypeError:
        return str(value)


def image_texture_sampling_identity(texture):
    """Capture settings that affect an unlinked-vector still Image Texture."""
    if texture is None:
        return ()
    settings = []
    for name in ("interpolation", "projection", "projection_blend", "extension"):
        if hasattr(texture, name):
            settings.append((name, _rna_value(getattr(texture, name))))
    for property_name in ("texture_mapping", "color_mapping", "image_user"):
        mapping = getattr(texture, property_name, None)
        if mapping is None:
            continue
        values = []
        property_names = (
            ("mapping", "vector_type", "translation", "rotation", "scale",
             "min", "max", "use_min", "use_max", "mapping_x",
             "mapping_y", "mapping_z")
            if property_name == "texture_mapping"
            else (("blend_color", "blend_factor", "blend_type", "brightness",
                   "contrast", "saturation", "use_color_ramp")
                  if property_name == "color_mapping"
                  else ("use_auto_refresh", "frame_current", "use_cyclic",
                        "frame_duration", "frame_offset", "frame_start"))
        )
        for name in property_names:
            if hasattr(mapping, name):
                values.append((name, _rna_value(getattr(mapping, name))))
        if property_name == "color_mapping" and getattr(mapping, "use_color_ramp", False):
            ramp = getattr(mapping, "color_ramp", None)
            if ramp is not None:
                values.append(("color_ramp", (
                    str(getattr(ramp, "color_mode", "")),
                    str(getattr(ramp, "interpolation", "")),
                    str(getattr(ramp, "hue_interpolation", "")),
                    tuple((float(element.position), _rna_value(element.color))
                          for element in ramp.elements),
                )))
        settings.append((property_name, tuple(values)))
    vector = getattr(getattr(texture, "inputs", None), "get", lambda *_: None)("Vector")
    if vector is not None:
        settings.append(("vector_linked", bool(getattr(vector, "is_linked", False))))
        settings.append(("vector_default", _rna_value(vector.default_value)))
    image = getattr(texture, "image", None)
    if image is not None:
        colorspace = getattr(image, "colorspace_settings", None)
        settings.append(("colorspace", str(getattr(colorspace, "name", ""))))
        settings.append(("alpha_mode", str(getattr(image, "alpha_mode", ""))))
        settings.append(("channels", int(getattr(image, "channels", 4))))
        settings.append(("size", tuple(int(value) for value in image.size[:2])))
        settings.append(("source", str(getattr(image, "source", ""))))
    return tuple(settings)


def _copy_texture_sampling(source, destination):
    if source is None:
        return
    for name in ("interpolation", "projection", "projection_blend", "extension"):
        if hasattr(source, name):
            try:
                setattr(destination, name, getattr(source, name))
            except (AttributeError, RuntimeError, TypeError, ValueError) as error:
                raise RuntimeError(f"Cannot preserve Image Texture {name}") from error
    source_vector = source.inputs.get("Vector")
    destination_vector = destination.inputs.get("Vector")
    if source_vector is not None and destination_vector is not None:
        try:
            destination_vector.default_value = source_vector.default_value
        except (AttributeError, RuntimeError, TypeError, ValueError) as error:
            raise RuntimeError("Cannot preserve Image Texture Vector default") from error
    for property_name in ("texture_mapping", "color_mapping", "image_user"):
        source_mapping = getattr(source, property_name, None)
        destination_mapping = getattr(destination, property_name, None)
        if source_mapping is None or destination_mapping is None:
            continue
        names = (
            ("mapping", "vector_type", "translation", "rotation", "scale",
             "min", "max", "use_min", "use_max", "mapping_x",
             "mapping_y", "mapping_z")
            if property_name == "texture_mapping"
            else (("blend_color", "blend_factor", "blend_type", "brightness",
                   "contrast", "saturation", "use_color_ramp")
                  if property_name == "color_mapping"
                  else ("use_auto_refresh", "frame_current", "use_cyclic",
                        "frame_duration", "frame_offset", "frame_start"))
        )
        for name in names:
            if hasattr(source_mapping, name):
                try:
                    setattr(destination_mapping, name, getattr(source_mapping, name))
                except (AttributeError, RuntimeError, TypeError, ValueError) as error:
                    raise RuntimeError(
                        f"Cannot preserve Image Texture {property_name}.{name}"
                    ) from error
        if property_name == "color_mapping":
            source_ramp = getattr(source_mapping, "color_ramp", None)
            destination_ramp = getattr(destination_mapping, "color_ramp", None)
            if (getattr(source_mapping, "use_color_ramp", False)
                    and source_ramp is not None and destination_ramp is not None):
                elements = tuple(
                    (float(element.position), tuple(element.color))
                    for element in source_ramp.elements
                )
                if len(elements) < 2:
                    raise RuntimeError("Image Texture color ramp has fewer than two stops")
                try:
                    destination_ramp.color_mode = source_ramp.color_mode
                    destination_ramp.interpolation = source_ramp.interpolation
                    destination_ramp.hue_interpolation = source_ramp.hue_interpolation
                    while len(destination_ramp.elements) > 2:
                        destination_ramp.elements.remove(destination_ramp.elements[-1])
                    first, last = elements[0], elements[-1]
                    destination_ramp.elements[0].position = 0.0
                    destination_ramp.elements[1].position = 1.0
                    destination_ramp.elements[0].position = first[0]
                    destination_ramp.elements[0].color = first[1]
                    destination_ramp.elements[1].position = last[0]
                    destination_ramp.elements[1].color = last[1]
                    for position, color in elements[1:-1]:
                        destination_ramp.elements.new(position).color = color
                except (AttributeError, IndexError, RuntimeError, TypeError, ValueError) as error:
                    raise RuntimeError("Cannot preserve Image Texture color ramp") from error
            elif property_name == "color_mapping" and source_ramp is not None:
                for name in ("interpolation", "hue_interpolation", "color_mode"):
                    if hasattr(source_ramp, name):
                        try:
                            setattr(destination_ramp, name, getattr(source_ramp, name))
                        except (AttributeError, RuntimeError, TypeError, ValueError) as error:
                            raise RuntimeError(
                                f"Cannot preserve Image Texture color ramp {name}"
                            ) from error


def _tree_has_shader_to_rgb(tree, seen=None):
    if tree is None:
        return False
    seen = set() if seen is None else seen
    if id(tree) in seen:
        return False
    seen.add(id(tree))
    for node in getattr(tree, "nodes", ()):
        if getattr(node, "bl_idname", "") == "ShaderNodeShaderToRGB":
            return True
        if _tree_has_shader_to_rgb(getattr(node, "node_tree", None), seen):
            return True
    return False


def _active_object_has_uv_layer(active_object):
    mesh = getattr(active_object, "data", None)
    uv_layers = getattr(mesh, "uv_layers", None)
    if uv_layers is None:
        return False
    try:
        return len(uv_layers) > 0 and getattr(uv_layers, "active", None) is not None
    except (AttributeError, ReferenceError, RuntimeError, TypeError):
        return False


def _explicit_image_uv_requirement(target_image):
    metadata = getattr(target_image, "get", None)
    if not callable(metadata):
        return False
    value = metadata("pg_requires_uv", None)
    return bool(value) if isinstance(value, (bool, int)) else False


def route_facts(scene, *, domain, target_image, native_output_available=True,
                context=None, node_tree=None):
    """Take fresh bounded Blender observations for poll/click admission."""
    render = getattr(scene, "render", None)
    engine = str(getattr(render, "engine", ""))
    bpy_module = None
    try:
        import bpy as bpy_module
    except ImportError:
        pass
    if context is None and bpy_module is not None:
        context = bpy_module.context
    try:
        from .native_admission import can_acquire_reader
        readers_idle = can_acquire_reader()
    except ImportError:
        readers_idle = True
    domain = str(domain).upper()
    if node_tree is None and context is not None:
        node_tree = getattr(getattr(context, "space_data", None), "edit_tree", None)
    active_object = None
    if context is not None:
        active_object = getattr(context, "active_object", None)
        if active_object is None:
            active_object = getattr(
                getattr(getattr(context, "view_layer", None), "objects", None),
                "active", None,
            )
    uv_layer_present = (
        _active_object_has_uv_layer(active_object) if domain == "UV" else False
    )
    # A missing tree cannot establish that Shader to RGB is absent. Treat the
    # shader route as blocked until its current graph can be observed.
    shader_to_rgb = (
        _tree_has_shader_to_rgb(node_tree)
        if node_tree is not None else True
    )
    return BakeRouteFacts(
        engine=engine,
        playback=bool(getattr(getattr(context, "screen", None), "is_animation_playing", False)),
        native_reader=not readers_idle,
        target_conflict=bool(getattr(target_image, "get", lambda *_: None)(
            "perceptual_grade_next_bake_active_backup"
        )),
        target_float32=bool(getattr(target_image, "is_float", False)
                            and not getattr(target_image, "use_half_precision", False)),
        image_requires_uv=(domain == "IMAGE"
                           and _explicit_image_uv_requirement(target_image)),
        shader_to_rgb=shader_to_rgb,
        uv_layer_present=uv_layer_present,
        native_output_available=native_output_available,
    )


def _readback(image):
    return read_image_rgba(image)


@dataclass
class NativeShaderEvaluator:
    """Evaluate an installed native group through Blender's Bake operator."""

    bpy: object
    scene: object
    owner_node: object
    source_image: object
    domain: str = "IMAGE"
    expected_evaluator: str = "native_grade_graph"
    source_texture: object = None

    def evaluate_native(self, source_pixels):
        values = np.asarray(source_pixels, dtype=np.float32)
        source = None
        destination = None
        material = None
        plane = None
        previous_active = None
        previous_selected = ()
        previous_engine = getattr(getattr(self.scene, "render", None), "engine", None)
        render = getattr(self.scene, "render", None)
        bake_settings = getattr(render, "bake", None)
        previous_target = getattr(bake_settings, "target", None)
        previous_clear = getattr(bake_settings, "use_clear", None)
        previous_margin = getattr(bake_settings, "margin", None)
        context = getattr(self.bpy, "context", None)
        try:
            if context is not None:
                if getattr(context, "mode", "OBJECT") != "OBJECT":
                    raise RuntimeError("Leave Edit Mode before baking")
                previous_active = getattr(context.view_layer.objects, "active", None)
                previous_selected = tuple(getattr(context, "selected_objects", ()))
            source = self._temporary_image(
                "PG Next Frozen Source", values, source_like=True,
            )
            destination = self._temporary_image(
                "PG Next Native Result", np.zeros_like(values),
            )
            material, plane = self._build_native_scene(source, destination)
            render = getattr(self.scene, "render", None)
            if render is not None:
                render.engine = "CYCLES"
                bake = getattr(render, "bake", None)
                if bake is not None:
                    bake.target = "IMAGE_TEXTURES"
                    bake.use_clear = True
                    if previous_margin is not None:
                        bake.margin = 0
            self._select(plane)
            self._bake(material, destination)
            color = _readback(destination)
            # Grade preserves alpha by contract. Keep its frozen plane exactly;
            # a second shader Bake samples the narrow texture domain at
            # different texel centers and can alter alpha independently of the
            # installed graph.
            color[..., 3] = values[..., 3]
            return color
        finally:
            if render is not None:
                if previous_engine is not None:
                    render.engine = previous_engine
                if bake_settings is not None:
                    if previous_target is not None:
                        bake_settings.target = previous_target
                    if previous_clear is not None:
                        bake_settings.use_clear = previous_clear
                    if previous_margin is not None:
                        bake_settings.margin = previous_margin
            self._remove_scene(material, plane, source, destination)
            if context is not None:
                for item in tuple(getattr(context, "selected_objects", ())):
                    item.select_set(False)
                for item in previous_selected:
                    try:
                        item.select_set(True)
                    except (ReferenceError, RuntimeError):
                        pass
                try:
                    context.view_layer.objects.active = previous_active
                except (ReferenceError, RuntimeError):
                    pass

    def _temporary_image(self, name, values, *, source_like=False):
        height, width, _ = values.shape
        image = None
        try:
            image = self.bpy.data.images.new(
                name, width=width, height=height, alpha=True, float_buffer=True,
            )
            image.use_half_precision = False
            if source_like:
                try:
                    image.colorspace_settings.name = self.source_image.colorspace_settings.name
                except (AttributeError, TypeError, RuntimeError):
                    pass
                try:
                    image.alpha_mode = self.source_image.alpha_mode
                except (AttributeError, TypeError, RuntimeError):
                    pass
            else:
                image.colorspace_settings.name = "Non-Color"
                image.alpha_mode = "CHANNEL_PACKED"
            image.pixels.foreach_set(np.asarray(values, dtype=np.float32).reshape(-1))
            image.update()
            return image
        except BaseException:
            if image is not None:
                self._remove_datablock(self.bpy.data.images, image)
            raise

    @staticmethod
    def _remove_datablock(collection, item):
        if collection is None or item is None:
            return
        try:
            collection.remove(item, do_unlink=True)
        except (TypeError, ReferenceError, RuntimeError):
            try:
                collection.remove(item)
            except (ReferenceError, RuntimeError):
                pass

    def _build_native_scene(self, source, destination):
        tree = self.bpy.data.materials.new("PG Next Native Bake Material")
        tree.use_nodes = True
        nodes = tree.node_tree.nodes
        nodes.clear()
        texture = nodes.new("ShaderNodeTexImage")
        texture.image = source
        _copy_texture_sampling(self.source_texture, texture)
        group = nodes.new("ShaderNodeGroup")
        group.node_tree = self.owner_node.node_tree
        emission = nodes.new("ShaderNodeEmission")
        output = nodes.new("ShaderNodeOutputMaterial")
        sink = nodes.new("ShaderNodeTexImage")
        sink.image = destination
        coordinates = nodes.new("ShaderNodeUVMap")
        tree.node_tree.links.new(coordinates.outputs["UV"], texture.inputs["Vector"])
        for name in ("Color", "Alpha"):
            if name in group.inputs and name in texture.outputs:
                tree.node_tree.links.new(texture.outputs[name], group.inputs[name])
        tree.node_tree.links.new(group.outputs.get("Color", group.outputs[0]), emission.inputs["Color"])
        tree.node_tree.links.new(emission.outputs[0], output.inputs["Surface"])
        nodes.active = sink
        mesh = self.bpy.data.meshes.new("PG Next Native Bake Plane")
        mesh.from_pydata(((-1, -1, 0), (1, -1, 0), (1, 1, 0), (-1, 1, 0)), (), ((0, 1, 2, 3),))
        uv = mesh.uv_layers.new(name="PG Next Bake UV")
        for item, value in zip(uv.data, ((0, 0), (1, 0), (1, 1), (0, 1))):
            item.uv = value
        obj = self.bpy.data.objects.new("PG Next Native Bake Plane", mesh)
        self.scene.collection.objects.link(obj)
        obj.data.materials.append(tree)
        coordinates.uv_map = obj.data.uv_layers.active.name
        return tree, obj

    def _bake(self, material, image, source_output=None):
        tree = material.node_tree
        emission = next(node for node in tree.nodes if node.bl_idname == "ShaderNodeEmission")
        if source_output is None:
            group = next(node for node in tree.nodes if node.bl_idname == "ShaderNodeGroup")
            source_output = group.outputs.get("Color", group.outputs[0])
        for link in tuple(emission.inputs["Color"].links):
            tree.links.remove(link)
        tree.links.new(source_output, emission.inputs["Color"])
        sink = next((node for node in tree.nodes
                     if node.bl_idname == "ShaderNodeTexImage" and node.image == image), None)
        if sink is None:
            sink = tree.nodes.new("ShaderNodeTexImage")
            sink.image = image
        for node in tree.nodes:
            node.select = node == sink
        tree.nodes.active = sink
        result = self.bpy.ops.object.bake(
            "EXEC_DEFAULT", type="EMIT", use_clear=True,
            use_selected_to_active=False,
        )
        if "FINISHED" not in result:
            raise RuntimeError("Native Grade Bake did not finish")

    def _select(self, obj):
        context = self.bpy.context
        for item in getattr(context, "selected_objects", ()):
            item.select_set(False)
        obj.select_set(True)
        context.view_layer.objects.active = obj

    def _remove_scene(self, material, plane, source, destination):
        mesh = getattr(plane, "data", None) if plane is not None else None
        for collection, item in (
                (getattr(self.bpy.data, "objects", None), plane),
                (getattr(self.bpy.data, "materials", None), material),
                (getattr(self.bpy.data, "images", None), source),
                (getattr(self.bpy.data, "images", None), destination)):
            if collection is not None and item is not None:
                try:
                    collection.remove(item, do_unlink=True)
                except (TypeError, ReferenceError, RuntimeError):
                    try:
                        collection.remove(item)
                    except (ReferenceError, RuntimeError):
                        pass
        meshes = getattr(self.bpy.data, "meshes", None)
        if meshes is not None and mesh is not None:
            try:
                if mesh.users == 0:
                    meshes.remove(mesh)
            except (ReferenceError, RuntimeError):
                pass


@dataclass
class NativeUVShaderEvaluator:
    """Bake the accepted shader output over a frozen copy of a mesh's UVs."""

    evaluator: NativeShaderEvaluator
    active_object: object
    uv_layer_name: str
    target_size: tuple
    owner_material_indices: tuple = ()

    def evaluate_native(self, source_pixels):
        values = np.asarray(source_pixels, dtype=np.float32)
        width, height = (int(value) for value in self.target_size)
        if (values.ndim != 3 or values.shape[-1] != 4
                or width < 1 or height < 1
                or width * height * 16 > MAX_PIXEL_BYTES):
            raise ValueError("UV Bake has an invalid source or destination domain")
        source = None
        destination = None
        material = None
        bake_object = None
        reference_object = None
        bake_mesh = None
        reference_mesh = None
        previous_active = None
        previous_selected = ()
        render = getattr(self.evaluator.scene, "render", None)
        previous_engine = getattr(render, "engine", None)
        bake_settings = getattr(render, "bake", None)
        previous_target = getattr(bake_settings, "target", None)
        previous_clear = getattr(bake_settings, "use_clear", None)
        previous_margin = getattr(bake_settings, "margin", None)
        context = getattr(self.evaluator.bpy, "context", None)
        try:
            if context is not None:
                if getattr(context, "mode", "OBJECT") != "OBJECT":
                    raise RuntimeError("Leave Edit Mode before UV baking")
                previous_active = getattr(context.view_layer.objects, "active", None)
                previous_selected = tuple(getattr(context, "selected_objects", ()))
            source = self.evaluator._temporary_image(
                "PG Next Frozen UV Source", values, source_like=True,
            )
            destination = self.evaluator._temporary_image(
                "PG Next UV Result",
                np.zeros((height, width, 4), dtype=np.float32),
            )
            (material, bake_object, bake_mesh, reference_object,
             reference_mesh, group) = self._build_uv_scene(source, destination)
            if render is not None:
                render.engine = "CYCLES"
                if bake_settings is not None:
                    bake_settings.target = "IMAGE_TEXTURES"
                    bake_settings.use_clear = True
                    if previous_margin is not None:
                        bake_settings.margin = 0
            self.evaluator._select(bake_object)
            color_socket = group.outputs.get("Color")
            alpha_socket = group.outputs.get("Alpha")
            if color_socket is None or alpha_socket is None:
                raise RuntimeError("Native UV Bake requires Grade Color and Alpha outputs")
            self.evaluator._bake(material, destination, color_socket)
            color = _readback(destination)
            self.evaluator._bake(material, destination, alpha_socket)
            alpha = _readback(destination)[..., 0]
            color[..., 3] = alpha
            return color
        finally:
            if render is not None:
                if previous_engine is not None:
                    render.engine = previous_engine
                if bake_settings is not None:
                    if previous_target is not None:
                        bake_settings.target = previous_target
                    if previous_clear is not None:
                        bake_settings.use_clear = previous_clear
                    if previous_margin is not None:
                        bake_settings.margin = previous_margin
            self._remove_uv_scene(
                material, bake_object, bake_mesh, reference_object,
                reference_mesh, source, destination,
            )
            if context is not None:
                for item in tuple(getattr(context, "selected_objects", ())):
                    item.select_set(False)
                for item in previous_selected:
                    try:
                        item.select_set(True)
                    except (ReferenceError, RuntimeError):
                        pass
                try:
                    context.view_layer.objects.active = previous_active
                except (ReferenceError, RuntimeError):
                    pass

    def _build_uv_scene(self, source, destination):
        bpy = self.evaluator.bpy
        context = bpy.context
        active = self.active_object
        if getattr(active, "type", "") != "MESH":
            raise RuntimeError("UV Bake requires an active mesh object")
        depsgraph = context.evaluated_depsgraph_get()
        evaluated = active.evaluated_get(depsgraph)
        evaluated_mesh = evaluated.to_mesh(
            preserve_all_data_layers=True, depsgraph=depsgraph,
        )
        bake_mesh = None
        reference_mesh = None
        material = None
        bake_object = None
        reference_object = None
        try:
            if evaluated_mesh.uv_layers.get(self.uv_layer_name) is None:
                raise RuntimeError("Evaluated mesh lost the selected UV map")
            if not evaluated_mesh.polygons:
                raise RuntimeError("UV Bake requires visible mesh faces")
            effective_material_slots = tuple(
                (str(getattr(slot, "link", "DATA")),
                 getattr(slot, "material", None))
                for slot in getattr(evaluated, "material_slots", ())
            )
            reference_mesh = evaluated_mesh.copy()
            reference_mesh.materials.clear()
            bake_mesh = evaluated_mesh.copy()
            if len(bake_mesh.materials) != len(effective_material_slots):
                raise RuntimeError("Evaluated UV Bake material slot count changed")
            for index, (link, effective_material) in enumerate(effective_material_slots):
                if link == "DATA":
                    bake_mesh.materials[index] = effective_material
            self._retain_owner_faces(bake_mesh)
            material = bpy.data.materials.new("PG Next Native UV Bake Material")
            material.use_nodes = True
            tree = material.node_tree
            nodes = tree.nodes
            nodes.clear()
            texture = nodes.new("ShaderNodeTexImage")
            texture.image = source
            _copy_texture_sampling(self.evaluator.source_texture, texture)
            group = nodes.new("ShaderNodeGroup")
            group.node_tree = self.evaluator.owner_node.node_tree
            emission = nodes.new("ShaderNodeEmission")
            output = nodes.new("ShaderNodeOutputMaterial")
            sink = nodes.new("ShaderNodeTexImage")
            sink.image = destination
            coordinates = nodes.new("ShaderNodeTexCoord")
            reference_object = bpy.data.objects.new(
                "PG Next UV Coordinate Reference", reference_mesh,
            )
            reference_object.matrix_world = evaluated.matrix_world
            self.evaluator.scene.collection.objects.link(reference_object)
            coordinates.object = reference_object
            tree.links.new(coordinates.outputs["Generated"], texture.inputs["Vector"])
            for name in ("Color", "Alpha"):
                if name in group.inputs and name in texture.outputs:
                    tree.links.new(texture.outputs[name], group.inputs[name])
            tree.links.new(group.outputs.get("Color", group.outputs[0]), emission.inputs["Color"])
            tree.links.new(emission.outputs[0], output.inputs["Surface"])
            nodes.active = sink

            bake_object = bpy.data.objects.new(
                "PG Next Native UV Bake Object", bake_mesh,
            )
            bake_object.matrix_world = evaluated.matrix_world
            for index, (link, effective_material) in enumerate(effective_material_slots):
                slot = bake_object.material_slots[index]
                slot.link = link
                if link == "OBJECT":
                    slot.material = effective_material
            self.evaluator.scene.collection.objects.link(bake_object)
            if not self.owner_material_indices:
                raise RuntimeError("UV Bake has no selected Grade material slots")
            for index in self.owner_material_indices:
                if index >= len(bake_mesh.materials):
                    raise RuntimeError("Evaluated UV Bake material slots changed")
                if bake_object.material_slots[index].link == "OBJECT":
                    bake_object.material_slots[index].material = material
                else:
                    bake_mesh.materials[index] = material
            return (
                material, bake_object, bake_mesh, reference_object,
                reference_mesh, group,
            )
        except BaseException:
            self._remove_uv_datablocks(
                material, bake_object, bake_mesh, reference_object, reference_mesh,
            )
            raise
        finally:
            try:
                evaluated.to_mesh_clear()
            except (AttributeError, ReferenceError, RuntimeError):
                pass

    def _remove_uv_scene(
            self, material, bake_object, bake_mesh, reference_object,
            reference_mesh, source, destination):
        self.evaluator._remove_scene(material, bake_object, source, destination)
        self.evaluator._remove_scene(None, reference_object, None, None)
        self._remove_uv_mesh(bake_mesh)
        self._remove_uv_mesh(reference_mesh)

    def _remove_uv_datablocks(
            self, material, bake_object, bake_mesh, reference_object,
            reference_mesh):
        self.evaluator._remove_scene(material, bake_object, None, None)
        self.evaluator._remove_scene(None, reference_object, None, None)
        self._remove_uv_mesh(bake_mesh)
        self._remove_uv_mesh(reference_mesh)

    def _remove_uv_mesh(self, bake_mesh):
        meshes = getattr(self.evaluator.bpy.data, "meshes", None)
        active_mesh = getattr(self.active_object, "data", None)
        if meshes is not None and bake_mesh is not None and bake_mesh is not active_mesh:
            try:
                if bake_mesh.users == 0:
                    meshes.remove(bake_mesh)
            except (ReferenceError, RuntimeError):
                pass

    def _retain_owner_faces(self, mesh):
        if not self.owner_material_indices:
            raise RuntimeError("UV Bake has no selected Grade material slots")
        import bmesh

        editable = bmesh.new()
        try:
            editable.from_mesh(mesh)
            excluded = [
                face for face in editable.faces
                if face.material_index not in self.owner_material_indices
            ]
            if len(excluded) == len(editable.faces):
                raise RuntimeError("Evaluated mesh has no faces using the selected Grade material")
            if excluded:
                bmesh.ops.delete(editable, geom=excluded, context="FACES_ONLY")
            editable.to_mesh(mesh)
        finally:
            editable.free()


@dataclass
class NativeStackShaderEvaluator:
    """Expose an accepted installed Stack Shader graph as a 65-LUT adapter."""

    evaluator: NativeShaderEvaluator
    evaluator_id: object
    manifest_id: object
    size: int = 65

    def apply(self, rgb):
        values = np.asarray(rgb, dtype=np.float32)
        if values.shape[-1:] != (3,):
            raise ValueError("Stack native capture requires RGB values")
        rgba = np.empty(values.shape[:-1] + (4,), dtype=np.float32)
        rgba[..., :3] = values
        rgba[..., 3] = 1.0
        return self.evaluator.evaluate_native(rgba)[..., :3]

    def apply_rgba(self, rgba):
        values = np.asarray(rgba, dtype=np.float32)
        if values.shape[-1:] != (4,):
            raise ValueError("Stack native capture requires RGBA values")
        return self.evaluator.evaluate_native(values)


__all__ = (
    "MAX_PIXEL_BYTES", "NativeShaderEvaluator", "NativeUVShaderEvaluator", "image_source_from_owner",
    "image_texture_from_owner", "image_texture_sampling_identity", "NativeStackShaderEvaluator",
    "read_image_rgba", "route_facts", "write_image_rgba",
)
