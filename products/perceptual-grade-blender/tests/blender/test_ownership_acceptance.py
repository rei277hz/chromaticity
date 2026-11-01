"""Real Blender ID ownership across portable saves and node deletion."""
from tests.support.session import component as _component, SessionTest, patch
from pathlib import Path
import tempfile
pass

import bpy
from color_tools import perceptual_grade_blender as addon
grades = _component('graph.grades'); gpu = _component('graph.gpu'); nodes = _component('graph.nodes'); stacks = _component('graph.stacks')
from tests.support.blender import BlenderTest, sequence


from tests.blender.ownership_support import OwnershipFixture


class OwnershipAcceptanceTests(OwnershipFixture):
    def test_repeated_real_saves_preserve_users_links_settings_and_animation(self):
        graphs = [self.graph(kind) for kind in ('ShaderNodeTree', 'CompositorNodeTree')]
        expected = {tree.name: self.graph_state(tree) for tree, _ in graphs}
        names = [(tree.name, grade.name) for tree, grade in graphs]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'owned.blend'
            for _ in range(3):
                bpy.ops.wm.save_as_mainfile(filepath=str(path), check_existing=False)
                self.assertFalse(grades._saving)
                for tree, grade in graphs:
                    self.assertEqual(grade.users, 5)
                    self.assertEqual(self.graph_state(tree), expected[tree.name])
                    self.assert_dependencies(tree, grade)
            bpy.ops.wm.open_mainfile(filepath=str(path))
            for tree_name, grade_name in names:
                tree, grade = bpy.data.node_groups[tree_name], bpy.data.node_groups[grade_name]
                self.assertEqual(grade.users, 5)
                self.assert_dependencies(tree, grade)
                self.assertEqual(len(list(grades.owner_curves(grade))), 9)
                self.assertEqual(len(stacks.entries(next(n for n in tree.nodes if stacks.is_stack(n)))), 2)
            bpy.ops.wm.save_as_mainfile(filepath=str(path), check_existing=False)
            for _, grade_name in names:
                self.assertEqual(bpy.data.node_groups[grade_name].users, 5)


    def test_save_failure_restores_custom_nodes_without_adding_users(self):
        graphs = [self.graph(kind) for kind in ('ShaderNodeTree', 'CompositorNodeTree')]
        self.assertIn(nodes.save_finished_handler, bpy.app.handlers.save_post_fail)
        for _ in range(3):
            nodes.save_handler()
            self.assertTrue(grades._saving)
            for tree, grade in graphs:
                self.assertEqual(grade.users, 5)
                self.assertTrue(all(node.bl_idname in ('ShaderNodeGroup', 'CompositorNodeGroup')
                                    for node in tree.nodes))
            nodes.save_finished_handler()
            self.assertFalse(grades._saving)
            for tree, grade in graphs:
                self.assertEqual(grade.users, 5)
                self.assertTrue(all(node.bl_idname in (*grades.KINDS.values(), *stacks.KINDS.values())
                                    for node in tree.nodes))
                self.assert_dependencies(tree, grade)


    def test_repeated_disable_enable_retains_portable_references(self):
        graphs = [self.graph(kind) for kind in ('ShaderNodeTree', 'CompositorNodeTree')]
        names = [(tree.name, grade.name) for tree, grade in graphs]
        for _ in range(2):
            addon.unregister()
            # Unregistering the custom NodeTree type invalidates its Python RNA
            # wrapper; reacquire the preserved ID through the generic registry.
            for tree_name, grade_name in names:
                tree, grade = bpy.data.node_groups[tree_name], bpy.data.node_groups[grade_name]
                self.assertEqual(grade.users, 5)
                self.assertTrue(all(node.bl_idname in ('ShaderNodeGroup', 'CompositorNodeGroup')
                                    for node in tree.nodes))
            addon.register()
            nodes.refresh_all()
            for tree_name, grade_name in names:
                tree, grade = bpy.data.node_groups[tree_name], bpy.data.node_groups[grade_name]
                self.assertEqual(grade.users, 5)
                self.assert_dependencies(tree, grade)


