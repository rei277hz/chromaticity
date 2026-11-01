"""Shader Bake route classification against real Blender node graphs."""
from types import SimpleNamespace

import bpy

from color_tools.perceptual_grade_blender.scopes.bake_routes import create
from tests.support.blender import BlenderTest
from tests.support.session import component


nodes = component('graph.nodes')
bake = component('graph.bake')


class ShaderBakeRouteTests(BlenderTest):
    def material(self, name='Shader Bake material'):
        material = bpy.data.materials.new(name)
        material.use_nodes = True
        return material

    def grade(self, material):
        return nodes.create_grade(material.node_tree)

    def context(self, material, obj=None):
        return SimpleNamespace(scene=bpy.context.scene, object=obj,
            view_layer=bpy.context.scene.view_layers[0],
            space_data=SimpleNamespace(type='NODE_EDITOR', id=material,
                                       node_tree=material.node_tree, path=()))

    def active_mesh(self, material, *, overlap=False):
        if overlap:
            vertices = ((0, 0, 0), (1, 0, 0), (0, 1, 0),
                        (2, 0, 0), (3, 0, 0), (2, 1, 0))
            faces = ((0, 1, 2), (3, 4, 5))
        else:
            vertices = ((0, 0, 0), (1, 0, 0), (0, 1, 0))
            faces = ((0, 1, 2),)
        mesh = bpy.data.meshes.new('Shader Bake mesh')
        mesh.from_pydata(vertices, (), faces)
        mesh.update()
        layer = mesh.uv_layers.new(name='BakeUV')
        layer.active_render = True
        uv = ((0, 0), (1, 0), (0, 1))
        layer.data.foreach_set('uv', tuple(value for _ in faces for point in uv for value in point))
        obj = bpy.data.objects.new('Shader Bake object', mesh)
        bpy.context.scene.collection.objects.link(obj)
        mesh.materials.append(material)
        bpy.context.view_layer.objects.active = obj
        obj.select_set(True)
        return obj

    @staticmethod
    def image(tree, name='Still source'):
        image = bpy.data.images.new(name, width=3, height=2, alpha=True, float_buffer=True)
        image.colorspace_settings.name = 'Non-Color'
        source = tree.nodes.new('ShaderNodeTexImage')
        source.image = image
        return source

    def test_still_image_route_is_full_resolution_value_only_and_engine_independent(self):
        scene = bpy.context.scene
        scene.render.engine = 'BLENDER_EEVEE'
        material = self.material()
        grade = self.grade(material)
        image = self.image(material.node_tree)
        material.node_tree.links.new(image.outputs['Color'], grade.inputs['Color'])

        route = component('scopes.bake_routes').describe(grade, self.context(material))

        self.assertEqual(route['operation'], 'shader_bake')
        self.assertEqual(route['owner_kind'], 'material')
        self.assertEqual(route['shader_bake']['domain'], 'IMAGE')
        self.assertEqual((route['shader_bake']['width'], route['shader_bake']['height']), (3, 2))
        self.assertEqual(route['shader_bake']['images'][0]['image_name'], image.image.name)
        self.assertEqual(route['shader_bake']['images'][0]['group_path'], ())
        self.assertNotIn('object', route['shader_bake'])
        self.assertIsInstance(route['identity'][1], str)
        self.assertEqual(scene.render.engine, 'BLENDER_EEVEE')
        self.assertFalse(self._contains_id(route))

    def test_image_preview_is_flat_without_content_fingerprinting_or_graph_changes(self):
        bpy.context.scene.render.engine = 'BLENDER_EEVEE'
        material = self.material()
        grade = self.grade(material)
        image = self.image(material.node_tree)
        material.node_tree.links.new(image.outputs['Color'], grade.inputs['Color'])
        material.node_tree.links.new(image.outputs['Alpha'], grade.inputs['Alpha'])
        links = tuple((link.from_socket.as_pointer(), link.to_socket.as_pointer())
                      for link in material.node_tree.links)
        images = tuple(item.as_pointer() for item in bpy.data.images)
        def no_content(*_args, **_kwargs):
            raise AssertionError('preview fingerprinted Image content')

        def resolve(name):
            if name == 'scopes.images':
                return SimpleNamespace(describe=no_content)
            return component(name)

        routes = create(SimpleNamespace(component=resolve))
        preview = routes.preview(grade, self.context(material))

        self.assertEqual(preview, dict(domain='IMAGE', show_dimensions=False,
                                      width=None, height=None, source='image', reasons=()))
        self.assertFalse(self._contains_id(preview))
        self.assertEqual(links, tuple((link.from_socket.as_pointer(), link.to_socket.as_pointer())
                                     for link in material.node_tree.links))
        self.assertEqual(images, tuple(item.as_pointer() for item in bpy.data.images))
        self.assertEqual(bpy.context.scene.render.engine, 'BLENDER_EEVEE')

    def test_explicit_source_uv_coordinates_explain_uv_route_before_cycles_admission(self):
        bpy.context.scene.render.engine = 'BLENDER_EEVEE'
        routes = component('scopes.bake_routes')
        for kind in ('ShaderNodeTexCoord', 'ShaderNodeUVMap'):
            with self.subTest(coordinates=kind):
                material = self.material(kind)
                grade = self.grade(material)
                source = self.image(material.node_tree)
                coordinates = material.node_tree.nodes.new(kind)
                material.node_tree.links.new(source.outputs['Color'], grade.inputs['Color'])
                material.node_tree.links.new(coordinates.outputs['UV'], source.inputs['Vector'])

                preview = routes.preview(grade, self.context(material))

                self.assertEqual(preview['domain'], 'UV')
                self.assertEqual(preview['reasons'], ('linked_coordinates',))
                self.assertTrue(preview['show_dimensions'])
                self.assertEqual((preview['width'], preview['height']), (2048, 2048))
                with self.assertRaisesRegex(ValueError, 'Cycles'):
                    routes.describe(grade, self.context(material))

    def test_baked_vector_changes_sampling_without_changing_image_route(self):
        material = self.material()
        grade = self.grade(material)
        source = self.image(material.node_tree)
        coordinates = material.node_tree.nodes.new('ShaderNodeTexCoord')
        material.node_tree.links.new(source.outputs['Color'], grade.inputs['Color'])
        material.node_tree.links.new(coordinates.outputs['UV'], grade.inputs['Vector'])

        preview = component('scopes.bake_routes').preview(grade, self.context(material))

        self.assertEqual(preview['domain'], 'IMAGE')
        self.assertEqual(preview['reasons'], ())
        self.assertFalse(preview['show_dimensions'])

    def test_preview_distinguishes_surface_dependencies_from_multiple_images(self):
        routes = component('scopes.bake_routes')
        material = self.material()
        grade = self.grade(material)
        tree = material.node_tree
        geometry = tree.nodes.new('ShaderNodeNewGeometry')
        tree.links.new(geometry.outputs['Position'], grade.inputs['Color'])

        preview = routes.preview(grade, self.context(material))

        self.assertEqual(preview['domain'], 'UV')
        self.assertEqual(preview['reasons'], ('surface_dependency',))
        first, second = self.image(tree, 'First source'), self.image(tree, 'Second source')
        mix = tree.nodes.new('ShaderNodeMixRGB')
        tree.links.new(first.outputs['Color'], mix.inputs[1])
        tree.links.new(second.outputs['Color'], mix.inputs[2])
        tree.links.new(mix.outputs['Color'], grade.inputs['Color'])

        preview = routes.preview(grade, self.context(material))

        self.assertEqual(preview['domain'], 'UV')
        self.assertEqual(preview['reasons'], ('multiple_images',))
        tree.links.new(geometry.outputs['Position'], grade.inputs['Alpha'])
        preview = routes.preview(grade, self.context(material))
        self.assertEqual(preview['reasons'], ('multiple_images', 'surface_dependency'))

    def test_constants_use_single_pixel_image_domain(self):
        material = self.material()
        grade = self.grade(material)
        grade.inputs['Color'].default_value = (.25, .5, .75, 1.)

        route = component('scopes.bake_routes').describe(grade, self.context(material))

        self.assertEqual(route['shader_bake']['domain'], 'IMAGE')
        self.assertEqual((route['shader_bake']['width'], route['shader_bake']['height']), (1, 1))
        self.assertEqual(route['shader_bake']['source'], 'constant')

    def test_constant_input_edits_change_frozen_identity(self):
        material = self.material()
        grade = self.grade(material)
        routes = component('scopes.bake_routes')
        first = routes.describe(grade, self.context(material))
        grade.inputs['Color'].default_value = (.4, .5, .6, 1.)
        second = routes.describe(grade, self.context(material))
        self.assertNotEqual(first['identity'], second['identity'])

    def test_image_alpha_and_nested_group_occurrence_are_frozen(self):
        material = self.material()
        grade = self.grade(material)
        child = bpy.data.node_groups.new('Bake image child', 'ShaderNodeTree')
        socket = child.interface.new_socket(name='Color', in_out='OUTPUT', socket_type='NodeSocketColor')
        alpha_socket = child.interface.new_socket(name='Alpha', in_out='OUTPUT', socket_type='NodeSocketFloat')
        texture = self.image(child, 'Nested still')
        output = child.nodes.new('NodeGroupOutput')
        output.is_active_output = True
        child.links.new(texture.outputs['Color'], output.inputs[socket.identifier])
        child.links.new(texture.outputs['Alpha'], output.inputs[alpha_socket.identifier])
        group = material.node_tree.nodes.new('ShaderNodeGroup')
        group.node_tree = child
        material.node_tree.links.new(group.outputs['Color'], grade.inputs['Color'])
        material.node_tree.links.new(group.outputs['Alpha'], grade.inputs['Alpha'])

        route = component('scopes.bake_routes').describe(grade, self.context(material))

        self.assertEqual(route['shader_bake']['domain'], 'IMAGE')
        self.assertEqual(route['shader_bake']['images'][0]['group_path'], (group.name,))
        self.assertEqual(route['shader_bake']['images'][0]['node_name'], texture.name)
        self.assertTrue(route['shader_bake']['images'][0]['alpha_linked'])

    def test_group_input_forwards_to_exact_parent_occurrence(self):
        material = self.material()
        grade = self.grade(material)
        child = bpy.data.node_groups.new('Bake pass-through child', 'ShaderNodeTree')
        input_socket = child.interface.new_socket(name='Color', in_out='INPUT', socket_type='NodeSocketColor')
        output_socket = child.interface.new_socket(name='Color', in_out='OUTPUT', socket_type='NodeSocketColor')
        group_input = child.nodes.new('NodeGroupInput')
        output = child.nodes.new('NodeGroupOutput')
        output.is_active_output = True
        child.links.new(group_input.outputs[input_socket.identifier], output.inputs[output_socket.identifier])
        group = material.node_tree.nodes.new('ShaderNodeGroup')
        group.node_tree = child
        constant = material.node_tree.nodes.new('ShaderNodeRGB')
        constant.outputs['Color'].default_value = (.2, .3, .4, 1.)
        material.node_tree.links.new(constant.outputs['Color'], group.inputs[input_socket.identifier])
        material.node_tree.links.new(group.outputs[output_socket.identifier], grade.inputs['Color'])

        route = component('scopes.bake_routes').describe(grade, self.context(material))

        self.assertEqual(route['shader_bake']['domain'], 'IMAGE')
        self.assertEqual(route['shader_bake']['source'], 'constant')

    def test_native_route_requires_cycles_mesh_material_and_valid_uv(self):
        scene = bpy.context.scene
        material = self.material()
        grade = self.grade(material)
        image = self.image(material.node_tree)
        coordinates = material.node_tree.nodes.new('ShaderNodeTexCoord')
        material.node_tree.links.new(image.outputs['Color'], grade.inputs['Color'])
        material.node_tree.links.new(coordinates.outputs['UV'], image.inputs['Vector'])
        scene.render.engine = 'BLENDER_EEVEE'
        with self.assertRaisesRegex(ValueError, 'Cycles'):
            component('scopes.bake_routes').describe(grade, self.context(material))

        scene.render.engine = 'CYCLES'
        obj = self.active_mesh(material)
        route = component('scopes.bake_routes').describe(grade, self.context(material, obj))
        self.assertEqual(route['shader_bake']['domain'], 'UV')
        self.assertEqual(route['shader_bake']['object_name'], obj.name)
        self.assertEqual(route['shader_bake']['material_slot'], 0)
        self.assertEqual(route['shader_bake']['uv_map'], 'BakeUV')

    def test_uv_binding_keeps_uv_route_and_uses_bound_image_dimensions(self):
        scene = bpy.context.scene
        scene.render.engine = 'CYCLES'
        material = self.material()
        grade = self.grade(material)
        image = self.image(material.node_tree)
        material.node_tree.links.new(image.outputs['Color'], grade.inputs['Color'])
        bound = bpy.data.images.new('Existing UV bake', width=7, height=5,
                                    alpha=True, float_buffer=True)
        bound['_pg_bake_kind'] = 'SHADER_UV'
        bound['_pg_bake_width'] = 7; bound['_pg_bake_height'] = 5
        bound['_pg_bake_schema'] = 2; bound['_pg_bake_storage'] = 'FLOAT_RGBA'
        bound.pixels.foreach_set((0.,) * (int(bound.size[0]) * int(bound.size[1]) * 4))
        bound.update(); bound.pack()
        bake.set_baked_image(grade, bound)
        obj = self.active_mesh(material)

        routes = component('scopes.bake_routes')
        preview = routes.preview(grade, self.context(material, obj))
        route = routes.describe(grade, self.context(material, obj))['shader_bake']

        self.assertEqual(preview['domain'], 'UV')
        self.assertEqual(preview['reasons'], ('existing_uv_binding',))
        self.assertEqual((preview['width'], preview['height']), (7, 5))
        self.assertEqual(route['domain'], 'UV')
        self.assertEqual((route['width'], route['height']), (7, 5))

        bake.set_baked_image(grade, None)
        preview = routes.preview(grade, self.context(material, obj))
        self.assertEqual(preview['domain'], 'IMAGE')
        self.assertEqual(preview['reasons'], ())
        self.assertFalse(preview['show_dimensions'])

    def test_image_binding_rejects_graph_that_now_requires_uv(self):
        scene = bpy.context.scene
        scene.render.engine = 'CYCLES'
        material = self.material()
        grade = self.grade(material)
        image = self.image(material.node_tree)
        material.node_tree.links.new(image.outputs['Color'], grade.inputs['Color'])
        bound = bpy.data.images.new('Existing Image bake', width=3, height=2,
                                    alpha=True, float_buffer=True)
        bound['_pg_bake_kind'] = 'SHADER_IMAGE'
        bound['_pg_bake_width'] = 3; bound['_pg_bake_height'] = 2
        bound['_pg_bake_schema'] = 2; bound['_pg_bake_storage'] = 'FLOAT_RGBA'
        bound.pixels.foreach_set((0.,) * (int(bound.size[0]) * int(bound.size[1]) * 4))
        bound.update(); bound.pack()
        bake.set_baked_image(grade, bound)
        coordinates = material.node_tree.nodes.new('ShaderNodeTexCoord')
        material.node_tree.links.new(coordinates.outputs['UV'], image.inputs['Vector'])

        routes = component('scopes.bake_routes')
        observation = routes.observe(grade, self.context(material))
        self.assertEqual(observation['code'], 'destination_domain')
        self.assertEqual(observation['route']['domain'], 'UV')
        with self.assertRaisesRegex(ValueError, 'clear or replace the binding'):
            routes.describe(grade, self.context(material))

    def test_overlapping_uvs_are_rejected(self):
        scene = bpy.context.scene
        scene.render.engine = 'CYCLES'
        material = self.material()
        grade = self.grade(material)
        image = self.image(material.node_tree)
        coordinates = material.node_tree.nodes.new('ShaderNodeTexCoord')
        material.node_tree.links.new(image.outputs['Color'], grade.inputs['Color'])
        material.node_tree.links.new(coordinates.outputs['UV'], image.inputs['Vector'])
        obj = self.active_mesh(material, overlap=True)

        with self.assertRaisesRegex(ValueError, 'overlapping'):
            component('scopes.bake_routes').describe(grade, self.context(material, obj))

    def test_shader_to_rgb_is_rejected(self):
        material = self.material()
        grade = self.grade(material)
        shader_to_rgb = material.node_tree.nodes.new('ShaderNodeShaderToRGB')
        surface = material.node_tree.nodes.new('ShaderNodeBsdfDiffuse')
        material.node_tree.links.new(surface.outputs['BSDF'], shader_to_rgb.inputs['Shader'])
        material.node_tree.links.new(shader_to_rgb.outputs['Color'], grade.inputs['Color'])

        with self.assertRaisesRegex(ValueError, 'Shader to RGB'):
            component('scopes.bake_routes').describe(grade, self.context(material))

    def test_frozen_identity_changes_with_source_parameters(self):
        material = self.material()
        grade = self.grade(material)
        image = self.image(material.node_tree)
        material.node_tree.links.new(image.outputs['Color'], grade.inputs['Color'])
        routes = component('scopes.bake_routes')
        first = routes.describe(grade, self.context(material))
        image.interpolation = 'Closest'
        second = routes.describe(grade, self.context(material))
        self.assertNotEqual(first['identity'], second['identity'])
        image.image.pixels[0] = .875
        image.image.update()
        third = routes.describe(grade, self.context(material))
        self.assertNotEqual(second['identity'], third['identity'])
        frozen = routes.freeze(grade, third)
        self.assertTrue(frozen['frozen'])
        self.assertEqual(frozen['identity'], third['identity'])
        self.assertFalse(self._contains_id(frozen))

    @classmethod
    def _contains_id(cls, value):
        if isinstance(value, bpy.types.ID):
            return True
        if isinstance(value, dict):
            return any(cls._contains_id(key) or cls._contains_id(item) for key, item in value.items())
        if isinstance(value, (tuple, list)):
            return any(cls._contains_id(item) for item in value)
        return False
