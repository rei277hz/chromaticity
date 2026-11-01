"""Shared Grade ownership, ordered stacks, invalidation and persistence."""
from tests.support.session import component as _component, SessionTest, patch
from pathlib import Path
import tempfile
pass
import numpy as np
import bpy
grades = _component('graph.grades'); nodes = _component('graph.nodes'); stacks = _component('graph.stacks'); lut = _component('graph.lut')
from color_tools.perceptual_grade_core.model import linear, lut as cubes, tone
panel = _component('ui.panel')
from tests.support import cases, reference as oracle
from tests.support.blender import BlenderTest, sequence


class StackTests(BlenderTest):
    def test_shadow_anchor_defaults_and_tone_resets_remain_exact_identity_after_rna(self):
        tree=bpy.data.node_groups.new('Neutral tone defaults','CompositorNodeTree')
        node=nodes.create_grade(tree)
        defaults=tone.Parameters()

        def assert_neutral():
            self.assertEqual(node.pg_tone.input_shadows,float(np.float32(defaults.input_shadows)))
            self.assertEqual(nodes.read_tone(node),defaults)
            model=tone.model(nodes.read_tone(node),nodes.grading_space(node))
            self.assertFalse(model.active)
            np.testing.assert_array_equal(model.source,model.target)
            samples=np.r_[0.,100*model.target,200.]
            np.testing.assert_array_equal(model.remap_h(samples),samples)

        assert_neutral()
        bpy.context.window_manager.pg_stage='REMAP'
        for operator in (panel.PG_OT_reset_tone,panel.PG_OT_reset_stage):
            with self.subTest(reset=operator.bl_idname):
                nodes.write_tone(node,{'input_shadows':2*defaults.input_shadows,'fit':2})
                self.assertTrue(tone.model(nodes.read_tone(node),nodes.grading_space(node)).active)
                with patch.object(nodes,'active_grade',return_value=node),patch.object(panel,'redraw'):
                    self.assertEqual(operator.execute(None,bpy.context),{'FINISHED'})
                assert_neutral()

    def test_inverse_occurrences_native_endpoints_and_matrix_only_reuse(self):
        tree=bpy.data.node_groups.new('Paired stack','CompositorNodeTree')
        node=nodes.create_grade(tree);nodes.write_chromatic(node,{'global_gain':10.,'c_high_2':-16.})
        stack=sequence(tree,[node.pg_grade,node.pg_grade])
        stack.pg_stack_entries[1].direction='INVERSE'
        model=stacks.model(stack);lut.ensure(stack,model);image=lut.image_for(stack)
        self.assertEqual(lut.installed_cube(stack).size,65)
        np.testing.assert_array_equal(lut.installed_cube(stack).values.reshape(-1,3),cubes.lattice().astype('f4'))
        signature=lut.signal_signature(stack)
        with patch.object(lut,'cpu_baker',side_effect=AssertionError('Endpoint matrix edit rebaked')):
            nodes.write_values(node,{'exposure':-.1,'cr_balance':.03})
        self.assertEqual(image,lut.image_for(stack));self.assertNotEqual(signature,lut.signal_signature(stack))
        self.assertEqual(model.bake_key,stacks.model(stack).bake_key)
        x=np.array([[.1,.2,.3],[-.1,.4,2.],[1024,0,1.]])@cubes.FROM_LUT.T
        np.testing.assert_allclose(lut.evaluate_signal(x,lut.installed_signal(stack)),stacks.model(stack).apply(x),rtol=3e-6,atol=2e-6)
        self.assertFalse(hasattr(node,'pg_direction'))
        self.assertEqual(stack.pg_stack_entries[0].direction,'FORWARD')
        self.assertFalse(any('approximate' in key for key in image.keys()))
        copied=tree.copy();nodes.refresh_all();clone=copied.nodes[stack.name]
        self.assertEqual(clone.node_tree,stack.node_tree)
        nodes.prepare_output_resources(clone)
        self.assertEqual(stacks.entries(clone),stacks.entries(stack))
        clone.pg_stack_entries[1].enabled=False
        self.assertTrue(stack.pg_stack_entries[1].enabled)
        bpy.data.node_groups.remove(copied)
        tree.use_fake_user=True;name=stack.name
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'inverse.blend';bpy.ops.wm.save_as_mainfile(filepath=str(path),check_existing=False)
            bpy.ops.wm.open_mainfile(filepath=str(path));restored=bpy.data.node_groups['Paired stack'].nodes[name]
            self.assertEqual([e.direction for e in restored.pg_stack_entries],['FORWARD','INVERSE'])

    def test_singular_inverse_rejects_baking_and_render_preflight(self):
        tree=bpy.data.node_groups.new('Singular inverse','CompositorNodeTree')
        bpy.context.scene.compositing_node_group=tree
        node=nodes.create_grade(tree);nodes.write_values(node,{'exposure':.1})
        stack=sequence(tree,[node.pg_grade]);stack.pg_stack_entries[0].direction='INVERSE'
        model=stacks.model(stack)
        self.assertFalse(model.grades[0].forward.tone.active)
        self.assertFalse(model.grades[0].forward.color.active)
        lut.ensure(stack,model)
        grades.write_matrix(node.pg_grade,((1.,0.,0.),(0.,0.,0.),(0.,0.,1.)))
        grades.publish(node.pg_grade)
        self.assertIn('singular',stack['_pg_error'])
        self.assertNotIn(stack.as_pointer(),lut._states)
        with self.assertRaisesRegex(ValueError,'singular'):nodes.bake_model(stack)
        try:
            output = _component('graph.output')
            with self.assertRaisesRegex(ValueError,'singular'):output.prepare_render(bpy.context.scene)
        finally:
            grades.write_matrix(node.pg_grade,linear.I3);grades.publish(node.pg_grade);nodes.render_end_handler()

    def test_shared_edits_independent_copies_and_white_ownership(self):
        shader = bpy.data.node_groups.new('Shared shader', 'ShaderNodeTree')
        comp = bpy.data.node_groups.new('Shared compositor', 'CompositorNodeTree')
        a, b = nodes.create_grade(shader), nodes.create_grade(comp)
        self.assertIsNone(a.pg_grade)
        nodes.write_values(a, {'exposure': .3})
        b.pg_grade = a.pg_grade
        self.assertEqual(a.pg_grade, b.pg_grade)
        nodes.write_values(b, {'exposure': .5})
        self.assertEqual(a.pg_linear.exposure, .5)
        fixed = nodes.linear_matrix(a).copy()
        self.assertEqual(a.pg_grade.pg_working_white,'D65')
        np.testing.assert_allclose(nodes.linear_matrix(a),fixed,atol=2e-12,rtol=0)
        shared = a.pg_grade
        grades.new(b)
        nodes.write_values(b, {'exposure': -.5})
        self.assertEqual(a.pg_grade, shared)
        self.assertNotEqual(a.pg_grade, b.pg_grade)
        grades.unlink(b)
        self.assertIsNone(b.pg_grade)
        self.assertEqual(b.pg_linear.exposure, 0)

    def test_stack_order_invalidation_stale_results_and_persistence(self):
        tree = bpy.data.node_groups.new('Persisted stack', 'CompositorNodeTree')
        tree.use_fake_user = True
        first = nodes.create_grade(tree)
        nodes.write_values(first, {'exposure': .2})
        a = first.pg_grade
        last = nodes.create_grade(tree)
        nodes.write_values(last, {'exposure': -.1})
        b = last.pg_grade
        stack = sequence(tree, [a,b,a])
        model = stacks.model(stack)
        x = cases.samples()[:8]
        expected = x
        model=stacks.model(stack)
        expected=oracle.stack(x,[nodes.settings(node)for node in (first,last,first)])
        # Production Stack now uses the shared float32 execution profile.
        self.assertLess(oracle.error(model.apply(x), expected).max(), 2e-6)
        lut.ensure(stack, model)
        old_image = lut.image_for(stack)
        a.pg_linear.exposure = .25
        self.assertEqual(lut.image_for(stack), old_image)
        obsolete = lut._states[stack.as_pointer()]['baker']
        obsolete.finish()
        a.pg_linear.exposure = .3
        self.assertFalse(lut.publish(stack, obsolete))
        lut.ensure(stack, stacks.model(stack))
        tree_copy = tree.copy()
        nodes.refresh_all()
        copied = tree_copy.nodes[stack.name]
        self.assertEqual(copied.node_tree, stack.node_tree)
        nodes.prepare_output_resources(copied)
        self.assertNotEqual(copied.node_tree, stack.node_tree)
        self.assertEqual(stacks.entries(copied), stacks.entries(stack))
        copied.pg_stack_entries[0].enabled = False
        self.assertTrue(stack.pg_stack_entries[0].enabled)
        bpy.data.node_groups.remove(tree_copy)
        name = stack.name
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'stack.blend'
            bpy.ops.wm.save_as_mainfile(filepath=str(path), check_existing=False)
            bpy.ops.wm.open_mainfile(filepath=str(path))
            restored = bpy.data.node_groups['Persisted stack'].nodes[name]
            self.assertEqual(len(restored.pg_stack_entries),3)
            self.assertEqual(restored.pg_stack_entries[0].direction,'FORWARD')
            self.assertEqual(restored.pg_stack_entries[0].grade, restored.pg_stack_entries[2].grade)
            self.assertTrue(stacks.is_stack(restored))

    def test_real_undo_redo_restores_lazy_and_shared_grades(self):
        for name, kind in (('Undo shader', 'ShaderNodeTree'), ('Undo compositor', 'CompositorNodeTree')):
            tree = bpy.data.node_groups.new(name, kind)
            tree.use_fake_user = True
            node = nodes.create_grade(tree)
        def current():
            return tuple(bpy.data.node_groups[name].nodes['Grade'] for name in ('Undo shader', 'Undo compositor'))
        bpy.ops.ed.undo_push(message='Empty nodes')
        a, b = current()
        nodes.write_values(a, {'exposure': 1})
        bpy.ops.ed.undo_push(message='First edit')
        bpy.ops.ed.undo()
        a, b = current()
        self.assertIsNone(a.pg_grade)
        bpy.ops.ed.redo()
        a, b = current()
        self.assertEqual(a.pg_linear.exposure, 1)
        b.pg_grade = a.pg_grade
        bpy.ops.ed.undo_push(message='Shared Grade')
        nodes.write_values(b, {'exposure': 2})
        bpy.ops.ed.undo_push(message='Shared edit')
        bpy.ops.ed.undo()
        a, b = current()
        self.assertEqual(a.pg_grade, b.pg_grade)
        self.assertEqual(a.pg_linear.exposure, 1)
        np.testing.assert_array_equal(nodes.linear_matrix(a),2*np.eye(3))
        bpy.ops.ed.redo()
        a, b = current()
        self.assertEqual(a.pg_linear.exposure, 2)
