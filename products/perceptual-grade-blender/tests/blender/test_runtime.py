"""Interactive CPU bake scheduling, scope errors and portable BLAS execution."""
from tests.support.session import component as _component, SessionTest, patch
from concurrent.futures import Future
from collections import OrderedDict
from pathlib import Path
from types import SimpleNamespace
import os
import subprocess
import sys
import tempfile
import time
pass
import bpy
import numpy as np
gpu = _component('graph.gpu'); nodes = _component('graph.nodes'); lut = _component('graph.lut'); compositor = _component('graph.compositor'); scheduler = _component('graph.scheduler')
from color_tools.perceptual_grade_blender.model import baking
from color_tools.perceptual_grade_core.model import lut as cubes
from color_tools.perceptual_grade_core.jobs.codec import freeze_scope_request,thaw_scope_result
from color_tools.blender_runtime.execution.contracts import JobSpec,RuntimeLimits
from color_tools.blender_runtime.execution.runtime import ExecutionRuntime
from color_tools.perceptual_grade_blender.jobs.configuration import profile, seal
from color_tools import blender_runtime as execution_core
sampling = _component('scopes.sampling'); jobs = _component('scopes.jobs')
from tests.support.blender import BlenderTest,wait_for_scopes


class Layout:
    """Record native UI text and control availability without drawing a GPU frame."""
    def __init__(self,parent=None):
        self.enabled=True if parent is None else parent.enabled
        self.labels=[] if parent is None else parent.labels
        self.controls=[] if parent is None else parent.controls

    def row(self,**_kwargs):return Layout(self)
    def box(self):return Layout(self)
    def column(self,**_kwargs):return Layout(self)
    def separator(self):pass
    def context_pointer_set(self,*_args):pass
    def template_ID(self,*_args,**_kwargs):pass
    def label(self,*,text='',icon=None,**_kwargs):self.labels.append((str(text),icon))
    def prop(self,_value,name,**_kwargs):self.controls.append((name,self.enabled))
    def operator(self,name,**_kwargs):
        self.controls.append((name,self.enabled));return SimpleNamespace()


class RuntimeTests(BlenderTest):
    def test_staged_lut_retries_failed_publication_without_another_job(self):
        adapter=_component('jobs.baker')
        model=nodes.bake_model(self.node())
        baker=adapter.RemoteBaker(model)
        baker.cube=SimpleNamespace(size=cubes.SIZE,signature=baker.signature)
        try:
            with patch.object(adapter.RemoteBaker,'start',side_effect=AssertionError('Unexpected recomputation')):
                self.assertTrue(baker.prepare_publication())
                self.assertTrue(baker.authorize_publication())
                self.assertTrue(baker.publication_failed())
                self.assertTrue(baker.prepare_publication())
                self.assertTrue(baker.authorize_publication())
                self.assertTrue(baker.published())
                self.assertEqual(baker.protocol.state.phase,'ready')
                self.assertIsNone(baker.handle)
        finally:
            baker.cancel()
            baker.protocol.close()

    def analyze_full(self,node):
        spec=sampling.describe(node,nodes.grading_space(node))
        try:snapshot=sampling.capture(spec)
        finally:sampling.release(spec)
        return sampling.evaluate_snapshot(snapshot,OrderedDict())

    def setUp(self):
        super().setUp()
        cpu=patch.object(gpu,'acquire',return_value=(None,None));cpu.start();self.addCleanup(cpu.stop)

    def ui_snapshot(self,node):
        grades = _component('graph.grades'); stacks = _component('graph.stacks')
        panel = _component('ui.panel')
        draw_type=stacks.StackNode if stacks.is_stack(node) else grades.GradeNode
        node.id_data.nodes.active=node
        context=SimpleNamespace(space_data=SimpleNamespace(type='NODE_EDITOR',edit_tree=node.id_data),
            window_manager=bpy.context.window_manager,area=None)
        result={}
        for name,draw in (('node',lambda layout:draw_type.draw_buttons(node,context,layout)),
                          ('extended',lambda layout:draw_type.draw_buttons_ext(node,context,layout)),
                          ('sidebar',lambda layout:panel.PG_PT_main.draw(SimpleNamespace(layout=layout),context))):
            layout=Layout();draw(layout)
            result[name]=(layout.labels,layout.controls)
            self.assertTrue(layout.enabled)
        return result

    def test_node_sidebar_and_gizmo_stay_silent_through_normal_bake_states(self):
        editing = _component('graph.editing'); grades = _component('graph.grades'); stacks = _component('graph.stacks')
        diagram = _component('ui.diagram')
        from tests.support.blender import sequence
        grade=self.node();stack=sequence(grade.id_data,[grades.ensure(grade)])
        for node in (grade,stack):
            baseline=self.ui_snapshot(node)
            target=editing.Target(stack,stack.pg_stack_entries[0]) if stacks.is_stack(node) else node
            for phase,size in (('initial',None),('preview',33),('refining',33),('final',65)):
                with self.subTest(node=node.bl_idname,phase=phase):
                    # Old .blend files can retain these properties. Neither
                    # they nor installed resolution belong in normal UI text.
                    node['_pg_cube_status']='routine-status-'+phase
                    node['_pg_cube_backend']='GPU'
                    node['_pg_cube_device']='routine-device'
                    node['_pg_cube_backend_reason']='routine-fallback'
                    image=None if size is None else {'_pg_cube_schema':lut.SCHEMA,'_pg_cube_size':size}
                    with patch.object(lut,'image_for',return_value=image):
                        self.assertEqual(self.ui_snapshot(node),baseline)
                        self.assertEqual(diagram.reference_hint(target),'')
                        with patch.object(diagram,'text') as text:
                            diagram.draw_footer(target,{'scale':1.,'rect':(0.,0.,400.,120.)})
                        self.assertEqual([str(call.args[0]) for call in text.call_args_list],
                            [str(diagram.M('hint.drag_keys'))])
            self.assertFalse(node.get('_pg_bake_error'))

    def test_bake_errors_draw_only_on_node_and_sidebar_without_disabling_controls(self):
        editing = _component('graph.editing'); grades = _component('graph.grades'); stacks = _component('graph.stacks')
        diagram = _component('ui.diagram')
        from tests.support.blender import sequence
        grade=self.node();stack=sequence(grade.id_data,[grades.ensure(grade)])
        for state in lut._states.values():state['due']=float('inf')
        for node in (grade,stack):
            with self.subTest(node=node.bl_idname):
                normal=self.ui_snapshot(node)
                future=Future();future.set_exception(ValueError('Visible fixture failure'))
                lut._states[node.as_pointer()]['future']=future
                with self.assertLogs(lut.LOG,level='ERROR'):lut.tick()
                self.assertIn('Visible fixture failure',node['_pg_bake_error'])
                self.assertFalse(node.get('_pg_error'))
                failed=self.ui_snapshot(node)
                for surface,(labels,controls) in failed.items():
                    self.assertTrue(any('Visible fixture failure' in text and icon=='ERROR' for text,icon in labels))
                    self.assertEqual(controls,normal[surface][1])
                target=editing.Target(stack,stack.pg_stack_entries[0]) if stacks.is_stack(node) else node
                self.assertTrue(nodes.editable(target))
                self.assertEqual(diagram.reference_hint(target),'')
                with patch.object(diagram,'text') as text:
                    diagram.draw_footer(target,{'scale':1.,'rect':(0.,0.,400.,120.)})
                self.assertEqual([str(call.args[0]) for call in text.call_args_list],
                    [str(diagram.M('hint.drag_keys'))])

    def test_reference_and_drag_hints_remain_when_bake_error_is_present(self):
        reference = _component('scopes.reference')
        diagram = _component('ui.diagram')
        node=self.node();source=node.id_data.nodes.new('CompositorNodeRGB')
        node.id_data.links.new(source.outputs[0],node.inputs[reference.SOCKET])
        node['_pg_bake_error']='Not a gizmo message'
        self.assertEqual(diagram.reference_hint(node),diagram.tr('hint.reference_toggle'))
        with patch.object(diagram,'text') as text:
            diagram.draw_footer(node,{'scale':1.,'rect':(0.,0.,2000.,120.)})
        messages=[str(call.args[0]) for call in text.call_args_list]
        self.assertIn(diagram.tr('hint.reference_toggle'),messages)
        self.assertEqual(messages[-1],str(diagram.M('hint.drag_keys')))

    def ready_preview(self,node):
        state=lut._states[node.as_pointer()]
        state['due']=0.
        state['started']=True
        state['baker'].finish_preview()
        future=Future();future.set_result(None);state['future']=future
        return state

    def test_nonlinear_edits_do_not_invalidate_unchanged_installed_signal(self):
        node=self.node();lut.ensure(node,nodes.bake_model(node))
        signal=lut.signal_signature(node)
        with patch.object(compositor,'tag_output',wraps=compositor.tag_output) as tag:
            nodes.write_tone(node,{'input_midtones':42.})
            nodes.write_chromatic(node,{'global_gain':.2})
            tag.assert_not_called()
            self.assertEqual(lut.signal_signature(node),signal)
            nodes.write_values(node,{'exposure':.5})
            tag.assert_called_once_with(node)
            self.assertNotEqual(lut.signal_signature(node),signal)

    def test_active_drag_stack_preview_uses_its_own_endpoint_matrices(self):
        stacks = _component('graph.stacks'); spaces = _component('graph.spaces')
        from tests.support.blender import sequence
        tree=bpy.data.node_groups.new('Coherent snapshots','CompositorNodeTree')
        first=nodes.create_grade(tree);last=nodes.create_grade(tree)
        nodes.write_chromatic(first,{'global_gain':.1});nodes.write_chromatic(last,{'global_gain':.2})
        stack=sequence(tree,[first.pg_grade,last.pg_grade]);stack.pg_stack_entries[1].direction='INVERSE'
        lut.ensure(stack,stacks.model(stack))
        gesture=scheduler.begin(last);self.addCleanup(scheduler.end,gesture)
        nodes.write_values(first,{'exposure':.5});nodes.write_chromatic(last,{'global_gain':.3})
        state=self.ready_preview(stack);snapshot=state['baker'].model
        nodes.write_chromatic(last,{'global_gain':.4});nodes.write_values(last,{'exposure':.7})
        lut.tick()
        self.assertTrue(state['preview_published'])
        before,after=spaces.adapters(nodes.working_space())
        signal=lut.installed_signal(stack)
        np.testing.assert_array_equal(signal[1],(snapshot.input_matrix@cubes.TO_LUT@before).astype('f4'))
        np.testing.assert_array_equal(signal[2],(after@cubes.FROM_LUT@snapshot.output_matrix).astype('f4'))
        current=stacks.model(stack)
        self.assertFalse(np.array_equal(signal[2],(after@cubes.FROM_LUT@current.output_matrix).astype('f4')))
        scheduler.end(gesture)
        self.wait_for_cube(stack,65)
        np.testing.assert_array_equal(lut.installed_signal(stack)[2],(after@cubes.FROM_LUT@current.output_matrix).astype('f4'))

    def test_full_scopes_capture_final_cube_and_current_stack_endpoint_rows(self):
        editing = _component('graph.editing'); stacks = _component('graph.stacks')
        from tests.support.blender import sequence
        tree=bpy.data.node_groups.new('Stack scope endpoints','CompositorNodeTree')
        first=nodes.create_grade(tree);last=nodes.create_grade(tree)
        nodes.grades.ensure(first);nodes.grades.ensure(last)
        stack=sequence(tree,[first.pg_grade,last.pg_grade]);stack.pg_stack_entries[1].direction='INVERSE'
        target=editing.Target(stack,stack.pg_stack_entries[0])
        lut.ensure(stack,stacks.model(stack));cube=lut.installed_cube(stack)
        space=nodes.grading_space(target);old=lut.signal_signature(stack)
        spec=sampling.describe(target,space)
        spec['_schedule']=scheduler.scope_request(target,'full',spec)
        self.assertTrue(scheduler.scope_coherent(target,'full',spec))
        with patch.object(compositor,'preview_running',return_value=True):
            nodes.write_values(first,{'exposure':.5});nodes.write_values(last,{'exposure':.7})
            current=stacks.model(stack)
            self.assertEqual(cube.signature,cubes.signature(current))
            self.assertTrue(lut.installed_matches(stack,current))
            self.assertEqual(lut.signal_signature(stack),old)
            snapshot=sampling.capture(sampling.describe(target,space))
            self.assertEqual(snapshot['signal'][0].size,65)
            rgb=np.array([[.2,.3,.7],[.5,.1,.4]])
            np.testing.assert_allclose(lut.evaluate_signal(rgb,snapshot['signal']),
                current.apply_cube(cube,rgb),rtol=2e-6,atol=2e-7)
        compositor.flush_update(stack)
        self.assertIs(lut.installed_cube(stack),cube)
        rgb=np.array([[.2,.3,.7],[.5,.1,.4]])
        np.testing.assert_allclose(lut.evaluate_signal(rgb,lut.installed_signal(stack)),
            current.apply_cube(cube,rgb),rtol=2e-6,atol=2e-7)

    def test_final_publication_waits_for_preview_frame_before_commit(self):
        node=self.node();scene=bpy.context.scene;scene.compositing_node_group=node.id_data
        state=self.ready_preview(node);lut.tick();preview=lut.image_for(node)
        self.assertIsNotNone(state['future'])
        future=state['future']
        compositor.composite_pre(scene)
        rows=lut.installed_signal(node)[1].copy()
        lut.tick()
        nodes.write_values(node,{'exposure':1.})
        np.testing.assert_array_equal(lut.installed_signal(node)[1],rows)
        future.result(timeout=30)
        lut.tick()
        self.assertEqual(lut.image_for(node),preview)
        self.assertIsNotNone(state['baker'].cube)
        self.assertIs(lut._states[node.as_pointer()],state)
        self.assertNotEqual(scheduler._displayed.get(node.as_pointer()),lut.signal_signature(node))
        compositor.composite_post(scene)
        self.assertEqual(scheduler._displayed[node.as_pointer()],lut.signal_signature(node))
        compositor.update_tick();lut.tick()
        self.assertEqual(lut.installed_cube(node).size,65)
        self.assertFalse(np.array_equal(lut.installed_signal(node)[1],rows))
        # The completed frame still refers to the preceding preview even
        # though the newly installed data are final-resolution.
        self.assertNotEqual(scheduler._displayed[node.as_pointer()],lut.signal_signature(node))
        self.assertEqual(scheduler._displayed[node.as_pointer()][0][3],33)

    def test_refinement_runs_before_busy_preview_can_be_installed(self):
        node=self.node();state=self.ready_preview(node)
        with patch.object(compositor,'preview_running',return_value=True):
            lut.tick()
            # The helper may finish refinement before this foreground tick.
            # Either timing must keep publication behind the preview barrier.
            if state['future'] is not None:
                state['future'].result(timeout=10)
            lut.tick()
            self.assertIsNotNone(state['baker'].cube)
            self.assertFalse(state['preview_published'])
            self.assertIsNone(lut.image_for(node))
        self.assertEqual(lut.tick(),.016)
        self.assertEqual(lut.installed_cube(node).size,33)
        lut.tick()
        self.assertEqual(lut.installed_cube(node).size,65)

    def test_linear_edits_reuse_final_lut_and_version_committed_rows(self):
        from tests.support import reference as oracle
        node=self.node();lut.ensure(node,nodes.bake_model(node))
        image=lut.image_for(node);key=cubes.signature(nodes.bake_model(node));old=sampling.signal_signature(node)
        with patch.object(baking,'CPU',side_effect=AssertionError('Stage 1 rebaked its nonlinear LUT')):
            nodes.write_values(node,{'exposure':1.,'cr_balance':.1})
        self.assertEqual(lut.image_for(node),image)
        self.assertEqual(cubes.signature(nodes.bake_model(node)),key)
        self.assertNotEqual(sampling.signal_signature(node),old)
        self.assertIsNone(lut._states[node.as_pointer()]['future'])
        node.inputs['Color'].default_value=(-.1,.4,2.,1.)
        rgb=np.array([[-.1,.4,2.],[2000.,300.,1.],[.2,.3,.7]])
        expected=oracle.lut(rgb,nodes.settings(node))
        self.assertLess(float(oracle.error(lut.evaluate_signal(rgb,lut.installed_signal(node)),expected).max()),2e-6)
        base=wait_for_scopes(node)
        analysis=self.analyze_full(node)
        self.assertLess(analysis['stage1_rgb'].min(),0.)
        np.testing.assert_allclose(analysis['stage1_rgb'],analysis['source_rgb']@nodes.linear_matrix(node).T,rtol=0,atol=0)
        prepared=nodes.bake_model(node).grades[0].forward.prepare_input(analysis['stage1_rgb'])
        np.testing.assert_allclose(analysis['stage2_input_rgb'],prepared,rtol=0,atol=0)
        for stage in ('before','after'):
            for field in ('density','histogram'):
                np.testing.assert_array_equal(base[stage][field],analysis[stage][field])
        np.testing.assert_array_equal(base['linear_vectorscope']['density'],analysis['linear_vectorscope']['density'])
        self.assertEqual(lut.installed_cube(node).size,65)
        self.assertEqual(lut.installed_cube(node).signature,key)

    def test_cached_final_and_forced_render_progress_after_cancel(self):
        node=self.node();lut.ensure(node,nodes.bake_model(node));original=cubes.signature(nodes.bake_model(node))
        original_image=lut.image_for(node)
        node['_pg_bake_error']='Installed-cache fixture failure'
        lut.request(node,nodes.bake_model(node))
        self.assertFalse(node.get('_pg_bake_error'))
        nodes.write_tone(node,{'input_midtones':42.});lut.ensure(node,nodes.bake_model(node));previous=lut.image_for(node)
        state=lut._states[node.as_pointer()]
        previous_signature=state['baker'].signature;signal=lut.signal_signature(node)
        scene=bpy.context.scene;scene.compositing_node_group=node.id_data
        compositor.composite_pre(scene)
        try:
            node['_pg_bake_error']='Previous fixture failure'
            node['_pg_bake_render_error']=True
            nodes.write_tone(node,{'input_midtones':36.54})
            self.assertEqual(cubes.signature(nodes.bake_model(node)),original)
            # Both final banks already exist. Native evaluation must retain
            # the selected bank until its cancellation receipt arrives.
            self.assertIs(lut._states[node.as_pointer()],state)
            self.assertEqual(state['baker'].signature,previous_signature)
            lut.tick();self.assertEqual(lut.image_for(node),previous)
            self.assertEqual(lut.signal_signature(node),signal)
            self.assertEqual(node.get('_pg_bake_error'),'Previous fixture failure')
        finally:
            compositor.composite_cancel(scene)
        self.assertNotIn(node.as_pointer(),scheduler._displayed)
        with patch.object(lut,'cpu_baker',side_effect=AssertionError('Cached final started another bake')):
            compositor.update_tick()
            lut.tick()
        self.assertEqual(lut.image_for(node),original_image)
        self.assertEqual(lut.installed_cube(node).size,65)
        self.assertEqual(lut.installed_cube(node).signature,original)
        self.assertFalse(node.get('_pg_bake_error'))
        self.assertFalse(node.get('_pg_bake_render_error'))
        compositor.composite_pre(scene)
        try:
            nodes.write_chromatic(node,{'global_gain':.3})
            self.assertEqual(lut.image_for(node),original_image)
            self.assertEqual(lut.installed_cube(node).signature,original)
        finally:
            compositor.composite_cancel(scene)
        # Exact preparation may install the new final after native readers
        # have released the banks; force does not bypass that boundary.
        lut.ensure(node,nodes.bake_model(node),force=True)
        self.assertEqual(lut.installed_cube(node).signature,cubes.signature(nodes.bake_model(node)))

    def test_saved_previous_driver_signature_is_rebaked(self):
        node=self.node();nodes.write_chromatic(node,{'c_low_1':.3})
        model=nodes.bake_model(node)
        with patch.object(cubes,'SCHEMA',25), patch.object(lut,'cpu_baker',
                side_effect=lambda value,progressive,encoded,_stack:baking.CPU(value,progressive,encoded)):
            # Produce a coherent old payload, including its saved receipt
            # and detached bank authority, as an earlier extension would.
            # A local baker shares the fixture's patched schema; a spawned
            # current-version helper intentionally rejects that mismatch.
            lut.ensure(node,model)
            previous=cubes.signature(model)
        current=cubes.signature(model)
        self.assertNotEqual(previous,current)
        # A saved image keeps its old mathematical signature even though its
        # atlas encoding and graph schema remain readable in this version.
        lut.clear()
        self.assertEqual(lut.installed_cube(node).signature,previous)
        self.assertFalse(lut.installed_matches(node,model))
        lut.request(node,model)
        state=lut._states[node.as_pointer()]
        self.assertEqual(state['baker'].signature,current)
        if state['baker'].cube is not None:
            self.assertEqual(state['baker'].cube.signature,current)
        lut.ensure(node,model)
        self.assertTrue(lut.installed_matches(node,model))
        self.assertEqual(lut.installed_cube(node).signature,current)
        self.assertEqual(lut.installed_cube(node).size,65)

    def node(self):
        tree=bpy.data.node_groups.new('Interactive trial','CompositorNodeTree')
        node=nodes.create_grade(tree)
        node.inputs['Color'].default_value=(.2,.3,.7,1.)
        return node

    def wait_for_cube(self,node,size):
        deadline=time.monotonic()+120
        state=lut._states[node.as_pointer()]
        state['due']=0.
        expected=cubes.signature(nodes.bake_model(node),size)
        while time.monotonic()<deadline:
            lut.tick()
            cube=lut.installed_cube(node)
            if cube is not None and cube.signature==expected and cube.size==size:return cube
            self.assertIn(node.as_pointer(),lut._states,node.get('_pg_bake_error',''))
            time.sleep(.005)
        self.fail(f'Timed out waiting for {size}³ cube {expected}: '+node.get('_pg_bake_error',''))

    def test_scopes_and_timer_driven_stage_updates(self):
        node=self.node();rgb=np.array([[.2,.3,.7]])
        def check(cube):
            # The adopted fitted boundary reports range escapes. Keep those
            # diagnostics and exact black, without adding an output RGB clamp.
            self.assertTrue(np.isfinite(cube.values).all())
            np.testing.assert_array_equal(cube.values[0,0,0],0)
            self.assertEqual(cube.diagnostics['minimum_rgb'],float(cube.values.min()))
            self.assertEqual(cube.diagnostics['maximum_rgb'],float(cube.values.max()))
            self.assertEqual(cube.diagnostics['outside_cube_pixels'],
                int(np.count_nonzero(np.any((cube.values<0)|(cube.values>1024),axis=-1))))
        previous=None
        for index,edit in enumerate((lambda:None,
                     lambda:nodes.write_values(node,{'exposure':.5}),
                     lambda:nodes.write_tone(node,{'input_midtones':42.}),
                     lambda:nodes.write_chromatic(node,{'global_gain':1.}))):
            edit()
            # Stage 1 reuses the installed resolution; immediate refinement
            # can have finished while scopes for the preceding edit ran.
            cube=lut.installed_cube(node) if index==1 else self.wait_for_cube(node,33)
            check(cube)
            actual=lut.evaluate_signal(rgb,lut.installed_signal(node))
            if previous is not None:self.assertGreater(float(np.max(abs(actual-previous))),1e-4)
            previous=actual
            base=wait_for_scopes(node)
            cloud=base['linear_vectorscope']
            self.assertGreater(float(cloud['density'].sum()),0.)
            analysis=self.analyze_full(node)
            for stage in ('before','after'):
                self.assertTrue(np.isfinite(analysis[stage+'_j']).all())
                for field in ('density','histogram'):
                    np.testing.assert_array_equal(base[stage][field],analysis[stage][field])
            self.assertFalse(node.get('_pg_error'))
        final=self.wait_for_cube(node,65)
        check(final)
        self.assertFalse(node.get('_pg_bake_error'))

    def test_nehalem_process_updates_scopes_and_installed_luts(self):
        paths=[str(Path(__file__).parents[2]),*sys.path]
        env=dict(os.environ,OPENBLAS_CORETYPE='NEHALEM',PYTHONPATH=os.pathsep.join(paths))
        test='tests.blender.test_runtime.RuntimeTests.test_scopes_and_timer_driven_stage_updates'
        result=subprocess.run([sys.executable,'-B','-m','unittest',test],env=env,capture_output=True,text=True,timeout=180)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    def test_interactive_bake_failure_keeps_controls_editable_and_recovers(self):
        node=self.node();future=Future();future.set_exception(ValueError('Injected bake failure'))
        lut._states[node.as_pointer()]['future']=future
        with self.assertLogs(lut.LOG,level='ERROR') as logs:lut.tick()
        self.assertIn('Injected bake failure',node['_pg_bake_error'])
        self.assertFalse(node.get('_pg_error'))
        self.assertTrue(nodes.editable(node))
        self.assertNotIn(node.as_pointer(),lut._states)
        self.assertIsNone(logs.records[0].exc_info);self.assertIn('Traceback (most recent call last)',logs.records[0].getMessage())
        with self.assertNoLogs(lut.LOG,level='ERROR'):lut.tick()
        lut.request(node,nodes.bake_model(node))
        self.assertIn('Injected bake failure',node['_pg_bake_error'])
        self.assertNotIn(node.as_pointer(),lut._states)
        lut.scope_retry()
        lut.request(node,nodes.bake_model(node))
        baker=lut._states[node.as_pointer()]['baker'];baker.finish_preview()
        self.assertTrue(lut.publish(node,baker,force=True,preview=True))
        self.assertFalse(node.get('_pg_bake_error'))

    def test_failed_active_snapshot_does_not_drop_newer_pending_controls(self):
        node=self.node();gesture=scheduler.begin(node);self.addCleanup(scheduler.end,gesture)
        state=lut._states[node.as_pointer()];state['started']=True
        nodes.write_tone(node,{'input_midtones':42.})
        future=Future();future.set_exception(ValueError('Obsolete snapshot failure'));state['future']=future
        with self.assertLogs(lut.LOG,level='ERROR'):lut.tick()
        replacement=lut._states[node.as_pointer()]
        self.assertIsNot(replacement,state);self.assertIsNone(replacement['pending'])
        self.assertEqual(replacement['baker'].signature,cubes.signature(nodes.bake_model(node)))
        self.assertFalse(node.get('_pg_bake_error'))

    def test_numerical_scope_errors_are_logged_once_and_recover(self):
        node=self.node();lut.ensure(node,nodes.bake_model(node));space=nodes.grading_space(node)
        def failed_scope():
            future=Future();future.set_exception(ValueError('Injected helper scope failure'))
            future.retired=future.done
            return future
        def fail():
            self.assertIsNone(sampling.get(node,space))
            jobs.tick()
            deadline=time.monotonic()+10
            while jobs._running is not None and time.monotonic()<deadline:
                jobs.tick();time.sleep(.001)
            self.assertIsNone(jobs._running)
            state=jobs._states[node.as_pointer()]
            self.assertEqual(state['failed'],state['spec']['key'])
        with patch.object(jobs,'_submit',side_effect=lambda *_:failed_scope()):
            with self.assertLogs('color_tools.perceptual_grade_blender.scopes',level='ERROR') as logs:
                fail()
                for _ in range(2):sampling.get(node,space);jobs.tick()
            self.assertEqual(len(logs.records),1)
            self.assertIsNone(logs.records[0].exc_info);self.assertIn('Traceback (most recent call last)',logs.records[0].getMessage())
        nodes.write_values(node,{'exposure':.1})
        wait_for_scopes(node)
        self.assertIsNone(jobs._states[node.as_pointer()]['failed'])
        sampling.refresh()
        with patch.object(jobs,'_submit',side_effect=lambda *_:failed_scope()):
            with self.assertLogs('color_tools.perceptual_grade_blender.scopes',level='ERROR'):
                fail()

    def _scope_runtime_snapshot(self):
        """Small immutable request used to exercise the native worker path."""
        from color_tools.perceptual_grade_core.model import color, linear, tone
        space=linear.GradeSpace('D65')
        parameters=tone.Parameters(input_midtones=42.)
        chromatic=color.Parameters(global_gain=.2)
        rgba=np.array([[[.2,.3,.7,1.],[.6,.1,.4,.75],[-.01,.4,.7,1.]]],dtype=float)
        cube=cubes.Cube(cubes.lattice(),'captured-final',size=65)
        view=dict(key=('runtime-view',),width=33,height=35,rect=(.25,.75,32.,34.),
                  scale=1.,bounds=((-1.12,-1.12,1.12,1.12),)*4)
        return dict(base_key=('runtime-base',parameters,space),key=('runtime-request',chromatic),
            rgba=rgba,chain=(),label='Runtime input',signal=(cube,np.eye(3),np.eye(3)),
            comparison=(rgba.copy(),()),stack=False,space='Linear Rec.709',grading_space=space,
            params=chromatic,view=(2,True),tone=parameters,linear=linear.Parameters(),
            matrix=np.eye(3),to_grade=np.eye(3),_scope_provenance=(('captured-final',65),),
            _warp_analysis_key=('runtime-analysis',),_warp_views=(view,),
            _scope_evaluation=('analytic','runtime-cloud-v1'))

    def _scope_runtime(self,mode):
        directory=tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        fixture=Path(__file__).with_name('scope_helper_fixture.py')
        from color_tools.blender_runtime import App
        from color_tools.blender_runtime.execution.machines import ExecutionMachines
        owner = App(package=Path(execution_core.__file__).parent.parent, storage_name='scope_runtime_test')
        self.addCleanup(owner.close)
        machines = ExecutionMachines(*(self.session.machines[name] for name in ('attempt', 'gpu', 'retry', 'startup')))
        runtime=ExecutionRuntime(directory.name, app=owner, machines=machines,
            package=Path(execution_core.__file__).parent.parent, profile=profile, seal=seal,
            worker_host='blender_runtime.blender.worker',
            environment=dict(os.environ, PYTHONPATH=os.pathsep.join(
                path for path in sys.path if path and '/bpy/' not in path.replace('\\', '/'))),
            limits=RuntimeLimits(startup_seconds=5.,
            stalled_seconds=5.,shutdown_seconds=.5),
            launcher=lambda config:[sys.executable,str(fixture),config['config_path'],mode])
        self.addCleanup(runtime.shutdown)
        return runtime

    def test_scope_warp_publishes_texture_tiles_without_point_arrays(self):
        runtime=self._scope_runtime('normal')
        handle=runtime.submit(JobSpec('scope_warp',freeze_scope_request(self._scope_runtime_snapshot()),
            lane='gpu',priority=1))
        result=thaw_scope_result(handle.result(timeout=30))
        self.assertEqual(handle.backend,'gpu')
        self.assertEqual(result['_warp_clouds'][0]['backend'],'gpu')
        self.assertEqual(result['_warp_clouds'][0]['pixels'].dtype,np.uint8)
        self.assertEqual(result['_warp_clouds'][0]['pixels'].shape,(2,4,35,33))
        for selected in result['_colors']:
            self.assertTrue({'weights','after_energy','bounded_saturation','after',
                             'saturation','_input','sample_indices'}.isdisjoint(selected))

    def test_scope_warp_gpu_failure_retries_bulk_and_keeps_output(self):
        runtime=self._scope_runtime('fail_gpu')
        handle=runtime.submit(JobSpec('scope_warp',freeze_scope_request(self._scope_runtime_snapshot()),
            lane='gpu',priority=1))
        with self.assertLogs('color_tools.blender_runtime.execution.runtime',level='WARNING'):
            result=thaw_scope_result(handle.result(timeout=30))
        self.assertEqual(handle.backend,'bulk')
        self.assertIn('Forced Warp GPU helper failure',handle.fallback_reason)
        self.assertEqual(result['_warp_clouds'][0]['backend'],'cpu')
        self.assertEqual(result['_warp_clouds'][0]['pixels'].dtype,np.uint8)
        self.assertEqual(runtime.gpu_status()['state'],'fallback')
