"""Effective Bake inputs against real RNA, independent of helper execution."""
import bpy

from tests.support.blender import BlenderTest, grade_data
from tests.support.session import component, patch


nodes = component('graph.nodes')
grades = component('graph.grades')
bake = component('graph.bake')
capture = component('scopes.capture')
contexts = component('scopes.context')
gpu = component('graph.gpu')


class BakeInputTests(BlenderTest):
    def setUp(self):
        super().setUp()
        cpu = patch.object(gpu, 'acquire', return_value=(None, None))
        cpu.start()
        self.addCleanup(cpu.stop)

    def graph(self, kind='ShaderNodeTree'):
        tree = bpy.data.node_groups.new('Bake input graph', kind)
        target = nodes.create_grade(tree)
        source = tree.nodes.new('ShaderNodeRGB' if kind == 'ShaderNodeTree' else 'CompositorNodeRGB')
        source.outputs[0].default_value = (.2, .4, .6, 1.)
        tree.links.new(source.outputs[0], target.inputs['Color'])
        return tree, target, source

    def observe(self, node, context=None):
        return capture.bake_input_observation(node, context or contexts.source_context(node))

    def image(self):
        image = bpy.data.images.new('Baked input', width=2, height=1, alpha=True, float_buffer=True)
        image['_pg_bake_schema'] = 2
        image['_pg_bake_storage'] = 'FLOAT_RGBA'
        image['_pg_bake_kind'] = 'COMPOSITOR'
        image['_pg_bake_width'] = 2
        image['_pg_bake_height'] = 1
        image.pixels.foreach_set((.2, .4, .6, 1.) * 2)
        image.update()
        image.pack()
        return image

    def bind(self, node, image):
        with bake.binding_suppressed(node):
            node.pg_bake_image = image
        bake.materialize_binding(node)

    def test_presentation_and_unrelated_nodes_do_not_change_inputs(self):
        for kind in ('ShaderNodeTree', 'CompositorNodeTree'):
            with self.subTest(kind=kind):
                tree, target, source = self.graph(kind)
                before = self.observe(target)
                target.name = 'Renamed target'
                source.name = 'Renamed source'
                source.location = (123., 456.)
                source.width = 290
                source.select = True
                source.label = 'Presentation only'
                source.hide = True
                unrelated = tree.nodes.new(source.bl_idname)
                unrelated.outputs[0].default_value = (.9, .8, .7, 1.)
                tree.nodes.active = unrelated
                self.assertEqual(before, self.observe(target))

    def test_native_values_and_effective_links_change_inputs(self):
        for kind in ('ShaderNodeTree', 'CompositorNodeTree'):
            with self.subTest(kind=kind):
                tree, target, first = self.graph(kind)
                second = tree.nodes.new(first.bl_idname)
                second.outputs[0].default_value = first.outputs[0].default_value
                before = self.observe(target)
                tree.links.new(second.outputs[0], target.inputs['Color'])
                rewired = self.observe(target)
                self.assertNotEqual(before, rewired)
                second.outputs[0].default_value = (.1, .2, .3, 1.)
                self.assertNotEqual(rewired, self.observe(target))

    def test_equal_grade_selection_and_revert_are_semantic_changes(self):
        _tree, target, _source = self.graph()
        first, second = grade_data(), grade_data()
        target.pg_grade = first
        before = self.observe(target)
        target.pg_grade = second
        self.assertNotEqual(before, self.observe(target))
        target.pg_grade = first
        self.assertNotEqual(before, self.observe(target))

    def test_upstream_grade_changes_are_observed_by_its_consumer(self):
        tree, target, source = self.graph()
        upstream = nodes.create_grade(tree)
        tree.links.new(source.outputs[0], upstream.inputs['Color'])
        tree.links.new(upstream.outputs['Color'], target.inputs['Color'])
        before = self.observe(target)
        nodes.write_values(upstream, {'exposure': .5})
        self.assertNotEqual(before, self.observe(target))
        nodes.write_values(upstream, {'exposure': 0.})
        self.assertNotEqual(before, self.observe(target))

    def test_baked_output_ignores_live_grade_but_observes_its_image(self):
        for kind in ('ShaderNodeTree', 'CompositorNodeTree'):
            with self.subTest(kind=kind):
                tree, target, _source = self.graph(kind)
                upstream = nodes.create_grade(tree)
                image = self.image()
                self.bind(upstream, image)
                tree.links.new(upstream.outputs['Baked Color'], target.inputs['Color'])
                before = self.observe(target)
                nodes.write_values(upstream, {'exposure': .5})
                image.name = 'Renamed baked input'
                self.assertEqual(before, self.observe(target))
                self.bind(upstream, self.image())
                self.assertNotEqual(before, self.observe(target))

    def test_upstream_baked_vector_and_sampling_settings_are_inputs(self):
        tree, target, _source = self.graph()
        upstream = nodes.create_grade(tree)
        self.bind(upstream, self.image())
        tree.links.new(upstream.outputs['Baked Color'], target.inputs['Color'])
        vector = tree.nodes.new('ShaderNodeCombineXYZ')
        tree.links.new(vector.outputs['Vector'], upstream.inputs['Vector'])
        bake.sync_coordinates()
        before = self.observe(target)
        vector.inputs['X'].default_value = .7
        moved = self.observe(target)
        self.assertNotEqual(before, moved)
        sampler = next(item for item in upstream.node_tree.nodes if item.get('_pg_baked_image'))
        sampler.interpolation = 'Closest' if sampler.interpolation != 'Closest' else 'Linear'
        self.assertNotEqual(moved, self.observe(target))

    def test_target_baked_vector_does_not_affect_its_live_bake(self):
        tree, target, _source = self.graph()
        before = self.observe(target)
        vector = tree.nodes.new('ShaderNodeCombineXYZ')
        tree.links.new(vector.outputs['Vector'], target.inputs['Vector'])
        bake.sync_coordinates()
        vector.inputs['X'].default_value = .75
        self.assertEqual(before, self.observe(target))

    def test_uv_route_observes_mesh_and_uv_edits_without_scope_revision_poll(self):
        _tree, target, _source = self.graph()
        mesh = bpy.data.meshes.new('Bake input mesh')
        mesh.from_pydata(((0., 0., 0.), (1., 0., 0.), (0., 1., 0.)), (), ((0, 1, 2),))
        layer = mesh.uv_layers.new(name='Bake UV')
        layer.active_render = True
        layer.data.foreach_set('uv', (0., 0., 1., 0., 0., 1.))
        obj = bpy.data.objects.new('Bake input surface', mesh)
        bpy.context.scene.collection.objects.link(obj)
        context = dict(contexts.source_context(target), object_uid=int(obj.session_uid), domain='UV')
        before = self.observe(target, context)
        # These direct edits deliberately do not call invalidate() or request
        # an evaluated depsgraph. Bake must observe current mesh data itself.
        mesh.vertices[0].co.x = .2
        geometry_changed = self.observe(target, context)
        self.assertNotEqual(before, geometry_changed)
        layer.data[0].uv.x = .15
        uv_changed = self.observe(target, context)
        self.assertNotEqual(geometry_changed, uv_changed)
        obj.name = 'Renamed surface'; mesh.name = 'Renamed mesh'
        mesh.vertices[0].select = not mesh.vertices[0].select
        self.assertEqual(uv_changed, self.observe(target, context))

    def test_nested_occurrence_uses_only_its_own_parent_inputs(self):
        root = bpy.data.node_groups.new('Bake occurrence root', 'ShaderNodeTree')
        inner = bpy.data.node_groups.new('Bake occurrence inner', 'ShaderNodeTree')
        inner.interface.new_socket(name='Color', in_out='INPUT', socket_type='NodeSocketColor')
        input_node = inner.nodes.new('NodeGroupInput')
        target = nodes.create_grade(inner)
        inner.links.new(input_node.outputs['Color'], target.inputs['Color'])
        first, other = root.nodes.new('ShaderNodeGroup'), root.nodes.new('ShaderNodeGroup')
        first.node_tree = other.node_tree = inner
        first.inputs['Color'].default_value = (.1, .2, .3, 1.)
        other.inputs['Color'].default_value = (.8, .7, .6, 1.)
        context = dict(_lightweight=True, root_pointer=root.as_pointer(), tree_pointer=inner.as_pointer(),
                       group_path=(first.name,), group_pointers=(first.as_pointer(),),
                       scene_uid=bpy.context.scene.session_uid, scene=bpy.context.scene.name)
        before = self.observe(target, context)
        first.name = 'Renamed exact occurrence'
        other.inputs['Color'].default_value = (.9, .9, .9, 1.)
        self.assertEqual(before, self.observe(target, context))
        first.inputs['Color'].default_value = (.5, .4, .3, 1.)
        self.assertNotEqual(before, self.observe(target, context))
