import unittest
from types import SimpleNamespace

import numpy as np

import bpy

from color_tools.perceptual_grade_next_blender.native_bake import (
    NativeShaderEvaluator, NativeUVShaderEvaluator, _copy_texture_sampling,
    image_texture_sampling_identity,
    image_source_from_owner, read_image_rgba, route_facts, write_image_rgba,
)
from color_tools.perceptual_grade_next_blender.bake import BakeRoute, inspect_bake_route


class _LinkedSocket:
    def __init__(self, node):
        self.links = (type("Link", (), {"from_node": node})(),)


class _SocketCollection:
    def __init__(self, socket):
        self.socket = socket

    def get(self, name):
        return self.socket if name == "Color" else None


class NativeBakeAdapterTests(unittest.TestCase):
    def test_bake_operator_registers_native_image_search_and_image_domain(self):
        from color_tools.perceptual_grade_next_blender import bake_operators

        classes = bake_operators.register()
        try:
            self.assertEqual(len(classes), 1)
            properties = bpy.ops.node.pg_next_bake.get_rna_type().properties
            self.assertEqual(properties["target_image"].type, "STRING")
            self.assertEqual(properties["domain"].type, "ENUM")
            self.assertEqual(properties["domain"].default, "IMAGE")
        finally:
            bake_operators.unregister()

    def test_empty_bake_target_creates_image_and_name_selects_existing_image(self):
        from color_tools.perceptual_grade_next_blender.bake_operators import _target_image

        source = bpy.data.images.new(
            "PG Next Source Picker Test", 2, 1, alpha=True, float_buffer=True,
        )
        target = bpy.data.images.new(
            "PG Next Chosen Target Test", 3, 2, alpha=True, float_buffer=True,
        )
        created = None
        try:
            self.assertIs(_target_image(bpy, source, target.name), target)
            created = _target_image(bpy, source, "")
            self.assertEqual(tuple(created.size), (2, 1))
            self.assertTrue(created.is_float)
        finally:
            for image in (created, target, source):
                if image is not None and bpy.data.images.get(image.name) is image:
                    bpy.data.images.remove(image, do_unlink=True)

    def test_blender_image_rgba_transport_is_float32_and_shape_checked(self):
        image = bpy.data.images.new(
            "PG Next Bake Adapter Test", width=2, height=1,
            alpha=True, float_buffer=True,
        )
        try:
            image.use_half_precision = False
            expected = np.asarray(
                (((-0.25, 0.5, 1.25, 0.0), (2.0, 3.0, 4.0, 0.75)),),
                dtype=np.float32,
            )
            image.pixels.foreach_set(expected.reshape(-1))
            image.update()
            actual = read_image_rgba(image)
            self.assertEqual(actual.dtype, np.float32)
            np.testing.assert_array_equal(actual, expected)
            write_image_rgba(image, expected * 0.5)
            np.testing.assert_array_equal(read_image_rgba(image), expected * 0.5)
            with self.assertRaisesRegex(ValueError, "does not match"):
                write_image_rgba(image, np.zeros((1, 1, 4), dtype=np.float32))
        finally:
            bpy.data.images.remove(image)

    def test_image_source_requires_direct_still_shader_image_node(self):
        image = bpy.data.images.new(
            "PG Next Bake Source Test", width=1, height=1,
            alpha=True, float_buffer=True,
        )
        try:
            node = type("ImageNode", (), {"bl_idname": "ShaderNodeTexImage", "image": image})()
            owner = type("Owner", (), {
                "inputs": _SocketCollection(_LinkedSocket(node)),
            })()
            self.assertIs(image_source_from_owner(owner), image)
            node.bl_idname = "CompositorNodeImage"
            with self.assertRaisesRegex(RuntimeError, "native Image Texture"):
                image_source_from_owner(owner)
            node.bl_idname = "ShaderNodeTexImage"
            node.projection = "BOX"
            with self.assertRaisesRegex(RuntimeError, "flat Image Texture"):
                image_source_from_owner(owner)
        finally:
            bpy.data.images.remove(image)

    def test_uv_source_sampling_preserves_implicit_vector_and_node_mapping(self):
        material = bpy.data.materials.new("PG Next UV Sampling Material")
        material.use_nodes = True
        source = material.node_tree.nodes.new("ShaderNodeTexImage")
        target_material = bpy.data.materials.new("PG Next UV Sampling Target")
        target_material.use_nodes = True
        target = target_material.node_tree.nodes.new("ShaderNodeTexImage")
        try:
            source.interpolation = "Closest"
            source.extension = "CLIP"
            source.texture_mapping.translation = (0.1, 0.2, 0.3)
            source.color_mapping.brightness = 1.25
            source.color_mapping.use_color_ramp = True
            source.color_mapping.color_ramp.elements.new(0.4).color = (0.2, 0.3, 0.4, 1.0)
            source.inputs["Vector"].default_value = (0.2, 0.3, 0.4)
            before = image_texture_sampling_identity(source)
            self.assertFalse(source.inputs["Vector"].is_linked)
            _copy_texture_sampling(source, target)
            self.assertFalse(target.inputs["Vector"].is_linked)
            self.assertEqual(image_texture_sampling_identity(target), before)
            target.texture_mapping.translation = (0.2, 0.2, 0.3)
            self.assertNotEqual(image_texture_sampling_identity(target), before)
        finally:
            bpy.data.materials.remove(target_material, do_unlink=True)
            bpy.data.materials.remove(material, do_unlink=True)

    def test_route_facts_reject_non_float_bake_destinations(self):
        image = bpy.data.images.new("PG Next Bake Target Test", 1, 1, float_buffer=False)
        try:
            facts = route_facts(type("Scene", (), {
                "render": type("Render", (), {"engine": "CYCLES"})(),
            })(), domain="IMAGE", target_image=image)
            self.assertFalse(facts.target_float32)
        finally:
            bpy.data.images.remove(image)

    def test_uv_and_shader_route_facts_are_observed_and_fail_closed(self):
        image = bpy.data.images.new("PG Next Route Facts Image", 1, 1, float_buffer=True)
        image.use_half_precision = False
        tree = bpy.data.node_groups.new("PG Next Route Facts Tree", "ShaderNodeTree")
        mesh = bpy.data.meshes.new("PG Next Route Facts Mesh")
        obj = bpy.data.objects.new("PG Next Route Facts Object", mesh)
        try:
            scene = SimpleNamespace(
                render=SimpleNamespace(engine="CYCLES"),
            )
            unknown = route_facts(
                scene, domain="UV", target_image=image,
                context=SimpleNamespace(active_object=None, space_data=None),
            )
            self.assertFalse(unknown.uv_layer_present)
            self.assertTrue(unknown.shader_to_rgb)
            route = BakeRoute("uv:unknown", "uv", "shader", "native_grade_graph", 1, "source")
            verdict = inspect_bake_route(route, unknown)
            self.assertFalse(verdict.ready)
            self.assertIn("no UV map", verdict.reason)

            mesh.uv_layers.new(name="Bake UV")
            context = SimpleNamespace(
                active_object=obj,
                screen=SimpleNamespace(is_animation_playing=False),
                space_data=SimpleNamespace(edit_tree=tree),
            )
            observed = route_facts(
                scene, domain="UV", target_image=image,
                context=context, node_tree=tree,
            )
            self.assertTrue(observed.uv_layer_present)
            self.assertFalse(observed.shader_to_rgb)

            tree.nodes.new("ShaderNodeShaderToRGB")
            observed = route_facts(
                scene, domain="UV", target_image=image,
                context=context, node_tree=tree,
            )
            self.assertTrue(observed.shader_to_rgb)
            self.assertTrue(observed.uv_layer_present)
        finally:
            bpy.data.objects.remove(obj, do_unlink=True)
            bpy.data.meshes.remove(mesh)
            bpy.data.node_groups.remove(tree)
            bpy.data.images.remove(image)

    def test_image_uv_requirement_uses_only_explicit_supported_metadata(self):
        image = bpy.data.images.new("PG Next Explicit UV Image", 1, 1, float_buffer=True)
        image.use_half_precision = False
        tree = bpy.data.node_groups.new("PG Next Explicit Image Tree", "ShaderNodeTree")
        scene = SimpleNamespace(render=SimpleNamespace(engine="CYCLES"))
        try:
            facts = route_facts(
                scene, domain="IMAGE", target_image=image, node_tree=tree,
            )
            self.assertFalse(facts.image_requires_uv)
            image["pg_requires_uv"] = True
            facts = route_facts(
                scene, domain="IMAGE", target_image=image, node_tree=tree,
            )
            self.assertTrue(facts.image_requires_uv)
            image["pg_requires_uv"] = "false"
            facts = route_facts(
                scene, domain="IMAGE", target_image=image, node_tree=tree,
            )
            self.assertFalse(facts.image_requires_uv)
        finally:
            bpy.data.node_groups.remove(tree)
            bpy.data.images.remove(image)

    def test_uv_evaluator_bakes_real_mesh_uv_coverage_without_mutating_source(self):
        scene = bpy.context.scene
        previous_engine = scene.render.engine
        previous_active = bpy.context.view_layer.objects.active
        previous_selected = tuple(bpy.context.selected_objects)
        scene.render.engine = "CYCLES"
        source = bpy.data.images.new(
            "PG Next UV Evaluator Source", 2, 2, alpha=True, float_buffer=True,
        )
        source.use_half_precision = False
        source.colorspace_settings.name = "Non-Color"
        source_values = np.asarray((
            ((0.1, 0.2, 0.3, 0.25), (0.8, 0.5, 0.6, 0.5)),
            ((0.2, 0.8, 0.9, 0.75), (0.9, 0.9, 0.8, 1.0)),
        ), dtype=np.float32)
        source.pixels.foreach_set(source_values.reshape(-1))
        source.update()
        group_tree = bpy.data.node_groups.new(
            "PG Next UV Evaluator Group", "ShaderNodeTree",
        )
        for name, direction, socket_type in (
                ("Color", "INPUT", "NodeSocketColor"),
                ("Alpha", "INPUT", "NodeSocketFloat"),
                ("Color", "OUTPUT", "NodeSocketColor"),
                ("Alpha", "OUTPUT", "NodeSocketFloat")):
            group_tree.interface.new_socket(
                name=name, in_out=direction, socket_type=socket_type,
            )
        group_input = group_tree.nodes.new("NodeGroupInput")
        group_output = group_tree.nodes.new("NodeGroupOutput")
        group_tree.links.new(group_input.outputs["Color"], group_output.inputs["Color"])
        group_tree.links.new(group_input.outputs["Alpha"], group_output.inputs["Alpha"])
        owner_tree = bpy.data.node_groups.new(
            "PG Next UV Evaluator Owner", "ShaderNodeTree",
        )
        owner = owner_tree.nodes.new("ShaderNodeGroup")
        owner.node_tree = group_tree
        owner_tree.interface.new_socket(
            name="Color", in_out="OUTPUT", socket_type="NodeSocketColor",
        )
        owner_tree.interface.new_socket(
            name="Alpha", in_out="OUTPUT", socket_type="NodeSocketFloat",
        )
        material = bpy.data.materials.new("PG Next UV Evaluator Original Material")
        material.use_nodes = True
        source_texture = owner_tree.nodes.new("ShaderNodeTexImage")
        source_texture.image = source
        source_texture.interpolation = "Closest"
        owner_tree.links.new(source_texture.outputs["Color"], owner.inputs["Color"])
        owner_tree.links.new(source_texture.outputs["Alpha"], owner.inputs["Alpha"])
        group_output = owner_tree.nodes.new("NodeGroupOutput")
        owner_tree.links.new(owner.outputs["Color"], group_output.inputs["Color"])
        owner_tree.links.new(owner.outputs["Alpha"], group_output.inputs["Alpha"])
        material_owner = material.node_tree.nodes.new("ShaderNodeGroup")
        material_owner.node_tree = owner_tree
        other_material = bpy.data.materials.new("PG Next UV Evaluator Other Material")
        other_material.use_nodes = True
        other_material.node_tree.nodes.new("ShaderNodeEmission")
        data_material = bpy.data.materials.new("PG Next UV Evaluator Data Material")
        data_material.use_nodes = True
        data_material.node_tree.nodes.new("ShaderNodeEmission")
        mesh = bpy.data.meshes.new("PG Next UV Evaluator Mesh")
        mesh.from_pydata(
            ((-1, -1, 0), (0, -1, 0), (0, 1, 0), (-1, 1, 0),
             (0, -1, 0), (1, -1, 0), (1, 1, 0), (0, 1, 0)), (),
            ((0, 1, 2, 3), (4, 5, 6, 7)),
        )
        uv = mesh.uv_layers.new(name="Bake UV")
        for item, value in zip(uv.data, (
                (0.5, 0.0), (1.0, 0.0), (1.0, 1.0), (0.5, 1.0),
                (0.0, 0.0), (0.5, 0.0), (0.5, 1.0), (0.0, 1.0))):
            item.uv = value
        mesh.polygons[0].material_index = 1
        obj = bpy.data.objects.new("PG Next UV Evaluator Object", mesh)
        scene.collection.objects.link(obj)
        obj.data.materials.append(data_material)
        obj.data.materials.append(material)
        obj.material_slots[0].link = "OBJECT"
        obj.material_slots[0].material = other_material
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
        original_tree = owner.node_tree
        original_mesh = obj.data
        evaluator = NativeShaderEvaluator(
            bpy, scene, owner, source, "UV", source_texture=source_texture,
        )
        uv_evaluator = NativeUVShaderEvaluator(
            evaluator, obj, "Bake UV", (8, 8), (1,),
        )
        original_mesh_pointer = int(mesh.as_pointer())
        def temporary_uv_datablocks():
            return (
                tuple(item.name for item in bpy.data.images
                      if item.name.startswith(("PG Next Frozen UV Source", "PG Next UV Result"))),
                tuple(item.name for item in bpy.data.materials
                      if item.name.startswith("PG Next Native UV Bake Material")),
                tuple(item.name for item in bpy.data.meshes
                      if int(item.as_pointer()) != original_mesh_pointer
                      and (item.name.startswith("PG Next UV Evaluator Mesh")
                           or item.name.startswith("PG Next Native UV"))),
            )
        try:
            from color_tools.perceptual_grade_next_blender.bake_operators import _uv_source_identity
            identity = _uv_source_identity(obj, owner_tree, bpy.context, source_texture)
            self.assertEqual(identity[4], (1,))
            self.assertEqual(len(identity[5]), 2)
            self.assertEqual(identity[2], "Bake UV")
            self.assertEqual(len(identity), 9)
            original_identity = identity
            obj.material_slots[0].link = "DATA"
            changed_link = _uv_source_identity(obj, owner_tree, bpy.context, source_texture)
            self.assertNotEqual(changed_link[3], original_identity[3])
            obj.material_slots[0].link = "OBJECT"
            obj.material_slots[0].material = other_material
            mesh.materials[0] = other_material
            changed_slot = _uv_source_identity(obj, owner_tree, bpy.context, source_texture)
            self.assertNotEqual(changed_slot[3], original_identity[3])
            mesh.materials[0] = data_material
            mesh.polygons[1].material_index = 1
            changed_assignment = _uv_source_identity(
                obj, owner_tree, bpy.context, source_texture,
            )
            self.assertNotEqual(changed_assignment[3], original_identity[3])
            mesh.polygons[1].material_index = 0
            source_texture.texture_mapping.translation = (0.15, 0.0, 0.0)
            changed_sampling = _uv_source_identity(
                obj, owner_tree, bpy.context, source_texture,
            )
            self.assertNotEqual(changed_sampling[3], original_identity[3])
            source_texture.texture_mapping.translation = (0.0, 0.0, 0.0)
            result = uv_evaluator.evaluate_native(source_values)
            self.assertEqual(result.shape, (8, 8, 4))
            self.assertEqual(result.dtype, np.float32)
            self.assertTrue(np.isfinite(result).all())
            self.assertGreater(float(result[..., 3].max()), 0.0)
            self.assertEqual(float(result[..., 3].min()), 0.0)
            self.assertTrue(np.any(result[:, 4:, 3] > 0.0))
            self.assertFalse(np.any(result[:, :2, 3] > 0.0))
            covered_pixels = result[..., 3] > 0.0
            self.assertLess(float(result[..., 0][covered_pixels].max()), 0.3)
            self.assertIs(owner.node_tree, original_tree)
            self.assertIs(obj.data, original_mesh)
            self.assertEqual(obj.data.uv_layers.active.name, "Bake UV")
            self.assertEqual(scene.render.engine, "CYCLES")
            self.assertIs(bpy.context.view_layer.objects.active, obj)
            self.assertEqual(temporary_uv_datablocks(), ((), (), ()))
            with self.subTest("retained material slots and indices"):
                frozen_source = evaluator._temporary_image(
                    "PG Next UV Structure Source", source_values, source_like=True,
                )
                frozen_target = evaluator._temporary_image(
                    "PG Next UV Structure Target", np.zeros((8, 8, 4), np.float32),
                )
                structure = None
                try:
                    structure = uv_evaluator._build_uv_scene(frozen_source, frozen_target)
                    (_temporary_material, bake_obj, bake_mesh, reference_obj,
                     reference_mesh, _group) = structure
                    self.assertEqual(len(bake_obj.material_slots), 2)
                    self.assertEqual(bake_obj.material_slots[0].link, "OBJECT")
                    self.assertIs(
                        bake_obj.material_slots[0].material.original, other_material,
                    )
                    self.assertIs(bake_mesh.materials[0].original, data_material)
                    self.assertEqual(tuple(polygon.material_index for polygon in bake_mesh.polygons), (1,))
                    self.assertIs(bake_obj.material_slots[1].material, structure[0])
                    texture_node = next(
                        node for node in structure[0].node_tree.nodes
                        if node.bl_idname == "ShaderNodeTexImage" and node.image is frozen_source
                    )
                    self.assertTrue(texture_node.inputs["Vector"].is_linked)
                    self.assertEqual(texture_node.interpolation, "Closest")
                    self.assertEqual(
                        texture_node.inputs["Vector"].links[0].from_node.outputs[0].name,
                        "Generated",
                    )
                    coordinate_node = texture_node.inputs["Vector"].links[0].from_node
                    self.assertIs(coordinate_node.object, reference_obj)
                    self.assertEqual(len(reference_mesh.polygons), 2)
                finally:
                    if structure is not None:
                        uv_evaluator._remove_uv_scene(
                            structure[0], structure[1], structure[2],
                            structure[3], structure[4], frozen_source, frozen_target,
                        )
                    else:
                        bpy.data.images.remove(frozen_source, do_unlink=True)
                        bpy.data.images.remove(frozen_target, do_unlink=True)
            with self.assertRaisesRegex(RuntimeError, "lost the selected UV map"):
                NativeUVShaderEvaluator(
                    evaluator, obj, "Missing Bake UV", (8, 8),
                ).evaluate_native(source_values)
            self.assertEqual(temporary_uv_datablocks(), ((), (), ()))
        finally:
            scene.render.engine = previous_engine
            for item in tuple(bpy.context.selected_objects):
                item.select_set(False)
            for item in previous_selected:
                try:
                    item.select_set(True)
                except (ReferenceError, RuntimeError):
                    pass
            bpy.context.view_layer.objects.active = previous_active
            bpy.data.objects.remove(obj, do_unlink=True)
            bpy.data.meshes.remove(mesh)
            bpy.data.materials.remove(material, do_unlink=True)
            bpy.data.materials.remove(other_material, do_unlink=True)
            bpy.data.materials.remove(data_material, do_unlink=True)
            bpy.data.node_groups.remove(owner_tree, do_unlink=True)
            bpy.data.node_groups.remove(group_tree, do_unlink=True)
            bpy.data.images.remove(source)


if __name__ == "__main__":
    unittest.main()
