"""Real Blender ID ownership across portable saves and node deletion."""
from tests.support.session import component as _component, SessionTest, patch
from pathlib import Path
import tempfile
pass

import bpy
from color_tools import perceptual_grade_blender as addon
grades = _component('graph.grades'); gpu = _component('graph.gpu'); nodes = _component('graph.nodes'); stacks = _component('graph.stacks')
from tests.support.blender import BlenderTest, sequence


class OwnershipFixture(BlenderTest):
    def setUp(self):
        super().setUp()
        cpu = patch.object(gpu, 'acquire', return_value=(None, None))
        cpu.start()
        self.addCleanup(cpu.stop)


    def graph(self, kind):
        tree = bpy.data.node_groups.new('Owned ' + kind, kind)
        tree.use_fake_user = True
        first = nodes.create_grade(tree)
        nodes.write_values(first, {'exposure': .2})
        grade = first.pg_grade
        second = nodes.create_grade(tree)
        second.pg_grade = grade
        stack = sequence(tree, [grade, grade])
        first.pg_chromatic.family = 'WARP'
        first.pg_chromatic.active_tone = 2
        first.pg_chromatic.active_handle = 4
        stack.pg_stack_entries[1].focus.active_tone = 3
        stack.pg_stack_entries[1].focus.active_handle = 2
        tree.links.new(first.outputs['Color'], second.inputs['Color'])
        tree.links.new(second.outputs['Color'], stack.inputs['Color'])
        first.inputs['Color'].keyframe_insert(data_path='default_value', frame=1)
        grade.keyframe_insert(data_path='["' + grades.MATRIX + '"]', frame=1)
        self.assertEqual(grade.users, 5)  # Fake user, two nodes, two entries.
        return tree, grade


    def graph_state(self, tree):
        return (
            sorted((link.from_node.name, link.from_socket.name,
                    link.to_node.name, link.to_socket.name) for link in tree.links),
            sorted((curve.data_path, curve.array_index)
                   for curve in grades.owner_curves(tree)),
            [(node.name, grades.snapshot(node),
              tuple(getattr(node.pg_chromatic, field) for field in grades.FOCUS_FIELDS),
              stacks.entries(node) if stacks.is_stack(node) else None)
             for node in tree.nodes],
        )


    def assert_dependencies(self, tree, grade):
        curves = tree.animation_data.drivers
        self.assertEqual(len(curves), 3)
        for curve in curves:
            self.assertFalse(curve.mute)
            self.assertEqual(len(curve.driver.variables), 1)
            self.assertEqual(curve.driver.variables[0].targets[0].id, grade)


