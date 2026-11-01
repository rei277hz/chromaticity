"""Settled Grade graphs must not retrigger scene evaluation during idle polls."""
from tests.support.session import component as _component, SessionTest, patch
pass

import bpy
import time
import numpy as np

gpu = _component('graph.gpu'); grades = _component('graph.grades'); lut = _component('graph.lut'); nodes = _component('graph.nodes')
from tests.support.blender import BlenderTest, sequence


class IdleTests(BlenderTest):
    def setUp(self):
        super().setUp()
        cpu = patch.object(gpu, 'acquire', return_value=(None, None))
        cpu.start()
        self.addCleanup(cpu.stop)
        # Real GUI startup completes this bounded recovery on its timer before
        # idle polling. Blocking bpy tests must drive that foreground phase.
        nodes.retry_recovery()
        deadline=time.monotonic()+10
        while nodes.recovery_pending():
            self.assertLess(time.monotonic(),deadline,nodes.recovery_status())
            nodes.recovery_tick()

    def shader_graph(self):
        # A live material on a scene object is essential: an unused NodeTree
        # does not expose the viewport feedback caused by redundant RNA writes.
        bpy.ops.mesh.primitive_cube_add()
        material = bpy.data.materials.new('Idle material')
        material.use_nodes = True
        bpy.context.object.data.materials.append(material)
        tree = material.node_tree
        grade = nodes.create_grade(tree)
        nodes.write_chromatic(grade, {'global_gain': .1})
        stack = sequence(tree, [grade.pg_grade])
        tree.links.new(grade.outputs['Color'], stack.inputs['Color'])
        tree.links.new(stack.outputs['Color'], tree.nodes['Principled BSDF'].inputs['Base Color'])
        return grade, stack

    def compositor_graph(self):
        tree = bpy.data.node_groups.new('Idle compositor', 'CompositorNodeTree')
        tree.interface.new_socket(name='Image', in_out='OUTPUT', socket_type='NodeSocketColor')
        grade = nodes.create_grade(tree)
        nodes.write_chromatic(grade, {'global_gain': .1})
        stack = sequence(tree, [grade.pg_grade])
        output = tree.nodes.new('NodeGroupOutput')
        tree.links.new(grade.outputs['Color'], stack.inputs['Color'])
        tree.links.new(stack.outputs['Color'], output.inputs['Image'])
        bpy.context.scene.compositing_node_group = tree
        return grade, stack

    def settle(self, *targets):
        for node in targets:
            lut.ensure(node, nodes.bake_model(node))
            self.assertEqual(lut.installed_cube(node).size, 65)
        for _ in range(3):
            nodes.refresh_all()
            lut.tick()
            bpy.context.view_layer.update()

    def test_settled_material_and_compositor_refreshes_are_read_only(self):
        targets = (*self.shader_graph(), *self.compositor_graph())
        self.settle(*targets)
        images = tuple(lut.image_for(node).as_pointer() for node in targets)
        signatures = tuple(lut.signal_signature(node) for node in targets)
        updates = []

        def record(_scene, depsgraph):
            updates.extend((update.id.bl_rna.identifier, update.id.name)
                           for update in depsgraph.updates)

        bpy.app.handlers.depsgraph_update_post.append(record)
        try:
            # Prove the observer is attached to a live dependency graph before
            # using silence as the regression criterion.
            source = targets[0].inputs['Color']
            original = tuple(source.default_value)
            source.default_value = (.2, .3, .4, 1.)
            bpy.context.view_layer.update()
            self.assertTrue(any(kind == 'Material' and name == 'Idle material'
                                for kind, name in updates), updates)
            source.default_value = original
            bpy.context.view_layer.update()
            updates.clear()
            # Invoke both timer entry and direct edit/animation refresh paths.
            # Observe actual Blender dependency updates, not just setter calls.
            with patch.object(lut, 'cpu_baker', wraps=lut.cpu_baker) as bake:
                for _ in range(12):
                    nodes.poll_working_space()
                    nodes.refresh_all()
                    self.assertIsNone(lut.tick())
                    bpy.context.view_layer.update()
                bake.assert_not_called()
            self.assertEqual(updates, [])
            self.assertEqual(tuple(lut.image_for(node).as_pointer() for node in targets), images)
            self.assertEqual(tuple(lut.signal_signature(node) for node in targets), signatures)
            self.assertTrue(all(state['future'] is None for state in lut._states.values()))
        finally:
            bpy.app.handlers.depsgraph_update_post.remove(record)

    def test_real_edits_and_grade_animation_still_update_the_material(self):
        grade, stack = self.shader_graph()
        self.settle(grade, stack)
        old_signature = lut.installed_cube(grade).signature
        nodes.write_chromatic(grade, {'global_gain': .2})
        pending = lut._states[grade.as_pointer()]
        self.assertNotEqual(pending['baker'].signature, old_signature)
        self.settle(grade, stack)
        self.assertEqual(lut.installed_cube(grade).signature, pending['baker'].signature)
        images = tuple(lut.image_for(node).as_pointer() for node in (grade, stack))

        # Grade animation is a real datablock Action, evaluated by Blender's
        # existing driver dependency and frame handler, not manually sampled.
        data = grade.pg_grade
        for frame, exposure in ((1, 0.), (2, 1.)):
            nodes.write_values(grade, {'exposure': exposure})
            data.keyframe_insert(data_path='["' + grades.MATRIX + '"]', frame=frame)
        bpy.context.scene.frame_set(1)
        bpy.context.view_layer.update()
        nodes.poll_working_space()
        bpy.context.view_layer.update()
        before = tuple(lut.signal_signature(node) for node in (grade, stack))
        np.testing.assert_allclose(nodes.linear_matrix(grade), np.eye(3), rtol=0, atol=1e-12)
        bpy.context.scene.frame_set(2)
        bpy.context.view_layer.update()
        np.testing.assert_allclose(nodes.linear_matrix(grade), 2 * np.eye(3), rtol=0, atol=1e-12)
        # Native frame evaluation updates the Grade data, while only the
        # main-thread poll may publish its derived endpoint rows.
        self.assertEqual(tuple(lut.signal_signature(node) for node in (grade, stack)), before)
        nodes.poll_working_space()
        bpy.context.view_layer.update()
        self.assertNotEqual(tuple(lut.signal_signature(node) for node in (grade, stack)), before)
        self.assertEqual(tuple(lut.image_for(node).as_pointer() for node in (grade, stack)), images)
