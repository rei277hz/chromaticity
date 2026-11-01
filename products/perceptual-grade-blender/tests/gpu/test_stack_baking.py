"""Actual production Stack dispatch, raw handoffs and progressive publication."""
from tests.support.session import component as _component, SessionTest, patch
pass
import time
import os
import bpy
import numpy as np
acceleration = _component('graph.gpu'); nodes = _component('graph.nodes'); stacks = _component('graph.stacks'); lut = _component('graph.lut')
from color_tools.perceptual_grade_blender.model import baking, gpu as compute, stack_baking
from color_tools.perceptual_grade_core.model import transforms, linear, tone, color, lut as cubes
from tests.support.blender import BlenderTest,sequence
from tests.support.gpu import initialize


def settings(gain):
    return transforms.Settings(linear.I3,tone.Parameters(input_midtones=45),
        color.Parameters(global_gain=gain,web_hue_1_0=3.,web_chroma_1_2=.02,web_scale_2_4=.01,j_high_1=.1),linear.GradeSpace('D65'))


class StackBakingTests(BlenderTest):
    def setUp(self):
        super().setUp();initialize()

    def pump(self,condition):
        deadline=time.monotonic()+30
        while not condition() and time.monotonic()<deadline:
            lut.tick();time.sleep(.001)
        self.assertTrue(condition(),'Stack bake did not finish')

    def test_actual_gpu_all_handoffs_and_immutable_parameter_bindings(self):
        points=np.array([[0,0,0],[.1,.2,.3],[.7,.2,.1],[.02,.08,.4],[1024]*3],dtype='f4')
        rows=np.arange(len(points))
        program=None
        for directions in (('FORWARD','FORWARD'),('FORWARD','INVERSE'),
                           ('INVERSE','FORWARD'),('INVERSE','INVERSE')):
            model=transforms.Stack([settings(.15),settings(.2)],directions=directions)
            execution=model.prepare()
            if program is None:
                program=stack_baking.Program(execution.solvers[0])
                stack_baking.validate_program(program,execution)
            cpu=stack_baking.CPU(model);gpu=stack_baking.GPU(model,program,True,False,'test GPU')
            with patch.object(cubes,'lattice',return_value=points):
                expected=cpu.evaluate_rows(rows)
                with patch.object(program,'set_inverse',side_effect=AssertionError('Repeated parameter upload')):
                    actual=gpu.evaluate_rows(rows)
            self.assertIsNone(execution.program,'Worker-shared prepared model must remain NumPy-only')
            limit=np.maximum(.001*np.max(abs(expected),axis=-1),1e-7)
            self.assertTrue(np.all(np.max(abs(actual-expected),axis=-1)<=limit),(directions,expected,actual))
            if directions==('FORWARD','INVERSE'):
                with patch.object(cubes,'lattice',return_value=points),patch.object(program,'evaluate',wraps=program.evaluate) as calls:
                    gpu.evaluate_rows(rows)
                self.assertEqual([c.args[1] for c in calls.call_args_list],[3,1])
                self.assertEqual(calls.call_args_list[1].args[0].shape[-1],4)

    def test_single_forward_stack_matches_regular_grade_on_the_same_lattice(self):
        from dataclasses import replace
        axis=np.array([0,1,8,24,40,56,64])
        indices=np.stack(np.meshgrid(axis,axis,axis,indexing='ij'),-1).reshape(-1,3)
        rows=(indices[:,0]*cubes.SIZE+indices[:,1])*cubes.SIZE+indices[:,2]
        mixed=settings(.15)
        for entry in (replace(mixed,color=color.Parameters()),mixed):
            model=transforms.Stack([entry]);regular=baking.CPU(model);stack=stack_baking.CPU(model)
            expected=regular.evaluate_rows(rows)
            np.testing.assert_array_equal(stack.evaluate_rows(rows),expected)
            regular_program=compute.Program(regular.kernel)
            regular_gpu=compute.Baker(model,regular_program,True,False,'test GPU')
            stack_program=stack_baking.Program(model.prepare().solvers[0])
            stack_gpu=stack_baking.GPU(model,stack_program,True,False,'test GPU')
            regular_result=regular_gpu.evaluate_rows(rows);stack_result=stack_gpu.evaluate_rows(rows)
            for actual in (regular_result,stack_result):
                limit=np.maximum(.001*np.max(abs(expected),axis=-1),1e-7)
                self.assertTrue(np.all(np.max(abs(actual-expected),axis=-1)<=limit))
            limit=np.maximum(.001*np.max(abs(regular_result),axis=-1),1e-7)
            self.assertTrue(np.all(np.max(abs(stack_result-regular_result),axis=-1)<=limit))

    def test_progressive_stack_gpu_helper_preserves_nested_values_and_packs_rgbe(self):
        tree=bpy.data.node_groups.new('Current Stack GPU','CompositorNodeTree')
        first=nodes.create_grade(tree);nodes.write_chromatic(first,{'global_gain':.15})
        last=nodes.create_grade(tree);nodes.write_chromatic(last,{'global_gain':.2})
        stack=sequence(tree,[first.pg_grade,last.pg_grade]);stack.pg_stack_entries[1].direction='INVERSE'
        state=lut._states[stack.as_pointer()];state['due']=0
        with patch.object(stack_baking.GPU,'evaluate_rows',side_effect=AssertionError('Foreground GPU dispatch')):
            self.pump(lambda:state['preview_published'])
            preview=lut.installed_cube(stack).values.copy()
            self.pump(lambda:state['final_published'])
        self.assertEqual(stack['_pg_cube_backend'],'GPU')
        self.assertNotEqual(lut.installed_cube(stack).diagnostics['worker_pid'],os.getpid())
        np.testing.assert_array_equal(lut.installed_cube(stack).values[::2,::2,::2],preview)
        self.assertEqual(lut.image_for(stack)['_pg_cube_encoding'],'RGBE_DIFFERENCES')
        self.assertFalse(hasattr(first,'pg_direction'))

    def test_stack_gpu_failure_restarts_correct_cpu_baker_in_tick_and_render(self):
        pass
        pass
        tree=bpy.data.node_groups.new('Stack GPU failure','ShaderNodeTree')
        first=nodes.create_grade(tree);nodes.write_chromatic(first,{'global_gain':.1})
        stack=sequence(tree,[first.pg_grade]);stack.pg_stack_entries[0].direction='INVERSE'
        lut.ensure(stack,stacks.model(stack))
        old=lut.image_for(stack)
        nodes.write_chromatic(first,{'global_gain':.2})
        state=lut._states[stack.as_pointer()];state['due']=0
        runtime=_component('services').get_runtime()
        def running():
            current=lut._states[stack.as_pointer()]
            return (current['baker'].handle is not None and runtime.helpers.get('gpu') is not None
                and runtime.helpers['gpu'].active is current['baker'].handle._job)
        self.pump(running)
        state=lut._states[stack.as_pointer()]
        runtime.helpers['gpu'].kill()
        self.pump(lambda:state['baker'].backend=='CPU')
        self.assertIsInstance(state['baker'],_component('jobs.baker').RemoteBaker)
        self.assertEqual(state['baker'].backend,'CPU');self.assertEqual(lut.image_for(stack),old)
        self.assertIsInstance(state['baker'].fallback_reason,str)
        self.assertTrue(state['baker'].fallback_reason)
        self.assertFalse(stack.get('_pg_bake_error'))
        self.pump(lambda:state['final_published'])
        # Scope Retry only clears failed scope requests. A killed GPU helper
        # requires its own successful conformance probe before new GPU work.
        self.assertEqual(runtime.gpu_status(role='gpu')['state'],'fallback')
        probe=acceleration.retry(role='gpu')
        result=probe.result(timeout=30)
        self.assertEqual(probe.backend,'gpu')
        self.assertTrue(result['conformance'])
        self.assertEqual(runtime.gpu_status(role='gpu')['state'],'ready')
        nodes.write_chromatic(first,{'global_gain':.3})
        state=lut._states[stack.as_pointer()];state['due']=0
        self.pump(running)
        runtime.helpers['gpu'].kill()
        lut.ensure(stack,stacks.model(stack))
        self.assertEqual(stack['_pg_cube_backend'],'CPU')
        self.assertFalse(stack.get('_pg_bake_error'))
        self.assertIsInstance(lut._states[stack.as_pointer()]['baker'],_component('jobs.baker').RemoteBaker)
        self.assertEqual(lut.installed_cube(stack).signature,cubes.signature(stacks.model(stack)))
