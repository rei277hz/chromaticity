"""Native ownership and instance selection for general scope capture."""
from types import SimpleNamespace
import sys
import unittest

import bpy

from color_tools.perceptual_grade_blender.scopes.context import create


class ScopeContextTests(unittest.TestCase):
    def setUp(self):
        bpy.ops.wm.read_factory_settings(use_empty=True)
        self.capture = create(None)
        self.scene = bpy.context.scene
        self.context = SimpleNamespace(scene=self.scene, view_layer=self.scene.view_layers[0],
                                       object=None, space_data=None, window=None, area=None, region=None)

    def tearDown(self):
        self.capture.clear()
        bpy.ops.wm.read_factory_settings(use_empty=True)

    def camera(self):
        camera = bpy.data.objects.new('Scope camera', bpy.data.cameras.new('Scope camera'))
        self.scene.collection.objects.link(camera)
        self.scene.camera = camera
        return camera

    def material(self):
        material = bpy.data.materials.new('Scope material')
        material.use_nodes = True
        return material

    def test_detached_tree_has_no_native_context(self):
        tree = bpy.data.node_groups.new('Detached', 'ShaderNodeTree')
        node = tree.nodes.new('ShaderNodeEmission')
        self.assertIsNone(self.capture.describe(node, context=self.context))
        self.assertIsNone(self.capture.consumer(node, self.context))

    def test_compositor_uses_owning_scene_without_camera(self):
        tree = bpy.data.node_groups.new('Compositor', 'CompositorNodeTree')
        self.scene.compositing_node_group = tree
        node = tree.nodes.new('CompositorNodeExposure')
        self.scene.render.resolution_x = 640
        self.scene.render.resolution_y = 360
        self.scene.render.resolution_percentage = 50
        request = self.capture.describe(node, 'Image', self.context)
        self.assertEqual(request['scene'], self.scene.name)
        self.assertEqual(request['owner_kind'], 'compositor')
        self.assertEqual(request['group_path'], ())
        self.assertEqual((request['view']['width'], request['view']['height']), (320, 180))

    def test_shader_requires_real_view_and_consumer_does_not(self):
        material = self.material()
        node = material.node_tree.nodes.new('ShaderNodeEmission')
        identity = self.capture.consumer(node, self.context)
        with self.assertRaisesRegex(ValueError, '3D viewport or an active scene camera'):
            self.capture.describe(node, context=self.context)
        self.camera()
        request = self.capture.describe(node, context=self.context)
        self.assertEqual(request['consumer'], identity)
        self.assertEqual(request['view']['source'], 'camera')
        self.scene.frame_set(9)
        newer = self.capture.describe(node, context=self.context)
        self.assertEqual(newer['consumer'], identity)
        self.assertNotEqual(newer['view']['frame'], request['view']['frame'])

    def test_shared_nested_group_requires_selected_instance(self):
        self.camera()
        material = self.material()
        root = material.node_tree
        child = bpy.data.node_groups.new('Shared source', 'ShaderNodeTree')
        node = child.nodes.new('ShaderNodeEmission')
        first = root.nodes.new('ShaderNodeGroup'); first.node_tree = child
        second = root.nodes.new('ShaderNodeGroup'); second.node_tree = child
        self.assertEqual(len(self.capture.group_paths(root, child)), 2)
        with self.assertRaisesRegex(ValueError, 'node-group instance'):
            self.capture.describe(node, context=self.context)
        self.context.space_data = SimpleNamespace(type='NODE_EDITOR', id=material, node_tree=root,
            path=(SimpleNamespace(node_tree=root), SimpleNamespace(node_tree=child)))
        root.nodes.active = first
        first_request = self.capture.describe(node, context=self.context)
        root.nodes.active = second
        second_request = self.capture.describe(node, context=self.context)
        self.assertEqual(first_request['group_path'], (first.name,))
        self.assertEqual(second_request['group_path'], (second.name,))
        self.assertNotEqual(first_request['consumer'], second_request['consumer'])

    def test_group_paths_preserve_occurrences_and_cycles_beyond_recursion_limit(self):
        # Exercise discovery depth independently of Blender's native cost of
        # constructing thousands of nested datablocks. Native cases above check
        # the same node-tree interface and editor occurrence selection.
        class Tree:
            def __init__(self):
                self.nodes = []

            def as_pointer(self):
                return id(self)

        target = Tree()
        root = target
        names = []
        for index in range(sys.getrecursionlimit() + 10):
            parent = Tree()
            name = 'group-' + str(index)
            parent.nodes.append(SimpleNamespace(name=name, node_tree=root))
            names.append(name)
            root = parent
        root.nodes.insert(0, SimpleNamespace(name='cycle', node_tree=root))
        root.nodes.append(SimpleNamespace(name='direct', node_tree=target))
        self.assertEqual(self.capture.group_paths(root, target),
                         (tuple(reversed(names)), ('direct',)))
        self.assertEqual(self.capture.group_paths(root, root), ((),))

    def test_remembered_view_tracks_live_area_then_falls_back_to_camera(self):
        self.camera()
        material = self.material()
        node = material.node_tree.nodes.new('ShaderNodeEmission')
        window = bpy.context.window
        views = tuple(window.screen.areas)[:2]
        for area in views:
            area.type = 'VIEW_3D'
        self.context.window = window
        selected = views[-1]
        region = next(item for item in selected.regions if item.type == 'WINDOW')
        self.capture.remember(self.context, SimpleNamespace(
            mouse_x=region.x + region.width // 2, mouse_y=region.y + region.height // 2))
        request = self.capture.describe(node, context=self.context)
        self.assertEqual(request['view']['source'], 'viewport')
        self.assertEqual(request['view']['viewport'], (selected.as_pointer(), region.as_pointer()))
        self.assertIsInstance(request['view']['view_matrix'], tuple)
        selected.type = 'NODE_EDITOR'
        changed = self.capture.describe(node, context=self.context)
        self.assertNotEqual(changed['view']['viewport'], request['view']['viewport'])
        for area in window.screen.areas:
            if area.type == 'VIEW_3D':
                area.type = 'NODE_EDITOR'
        self.assertEqual(self.capture.describe(node, context=self.context)['view']['source'], 'camera')

    def test_world_owner_and_light_domain(self):
        self.camera()
        world = bpy.data.worlds.new('Scope world'); world.use_nodes = True
        self.scene.world = world
        node = world.node_tree.nodes.new('ShaderNodeEmission')
        self.assertEqual(self.capture.describe(node, context=self.context)['owner_kind'], 'world')
        light = bpy.data.lights.new('Scope light', 'POINT'); light.use_nodes = True
        node = light.node_tree.nodes.new('ShaderNodeEmission')
        with self.assertRaisesRegex(ValueError, 'Light shader scopes'):
            self.capture.describe(node, context=self.context)

    def test_frozen_context_can_describe_reference_without_rna_context(self):
        self.camera()
        material = self.material()
        node = material.node_tree.nodes.new('ShaderNodeMixRGB')
        primary = self.capture.describe(node, 'Color1', self.context)
        reference = self.capture.describe(node, 'Color2', primary)
        self.assertEqual(reference['consumer'], primary['consumer'])
        self.assertEqual(reference['view'], primary['view'])
        self.assertEqual(reference['socket_name'], 'Color2')
        self.assertEqual(primary['socket_name'], 'Color1')


if __name__ == '__main__':
    unittest.main()
