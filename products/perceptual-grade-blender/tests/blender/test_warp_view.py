"""Warp fit stays fixed for the entire pointer gesture, including pauses."""
from tests.support.session import component as _component, SessionTest, patch
from types import SimpleNamespace, MethodType
from threading import Event
pass
import bpy
import time
import numpy as np
nodes = _component('graph.nodes'); editing = _component('graph.editing'); lut = _component('graph.lut'); scheduler = _component('graph.scheduler')
sampling = _component('scopes.sampling'); jobs = _component('scopes.jobs'); clouds = _component('scopes.clouds')
color = _component('ui.color'); geo = _component('ui.color_geometry'); diagram = _component('ui.diagram'); warp = _component('ui.warp'); warp_view = _component('ui.warp_view')
from tests.support.blender import BlenderTest, grade_data, sequence,wait_for_scopes
from tests.support.scope import ScopeExecutor


class WarpViewTests(BlenderTest):
    def finish_recovery(self):
        deadline=time.monotonic()+10
        while nodes.recovery_status()['state'] not in ('completed','failed','superseded'):
            self.assertLess(time.monotonic(),deadline,nodes.recovery_status())
            nodes.recovery_tick();time.sleep(.001)
        self.assertEqual(nodes.recovery_status()['state'],'completed',nodes.recovery_status())
        self.assertFalse(nodes.recovery_pending())

    def node(self):
        tree=bpy.data.node_groups.new('Warp view','CompositorNodeTree')
        node=nodes.create_grade(tree)
        node.pg_chromatic.family='WARP';node.pg_chromatic.active_tone=1
        return node

    def gesture(self,node,point=None,field=None,editor=(10,20,30),handle=-1,region=(1000,750)):
        box=geo.layout(*region,1.,720,24,24,'WARP')
        box['_warp_editor']=editor
        p=color.control_state(node,nodes.grading_space(node),box)[3]
        if field:
            rect=warp.scale_rects(nodes.color_model(node),1,p,box['scale'],node.pg_chromatic.active_handle)[int(field.rsplit('_',1)[1])] if field.startswith('web_') else box['global1']
            point=(rect[0]+rect[2]*.6,rect[1]+5)
        elif point is None:point=p.screen(nodes.color_model(node).guarded_saturation_targets(1)[handle+1])
        wm=SimpleNamespace(pg_stage='CHROMATIC',pg_diagram_enabled=True,
            pg_diagram_x=24.,pg_diagram_y=24.,modal_handler_add=lambda op:None)
        context=SimpleNamespace(window_manager=wm,window=None,
            area=SimpleNamespace(tag_redraw=lambda:None),scene=bpy.context.scene)
        op=SimpleNamespace()
        for name in ('absolute_fit','restore','reset_dragged'):
            setattr(op,name,MethodType(getattr(diagram.PG_OT_diagram_drag,name),op))
        event=SimpleNamespace(type='LEFTMOUSE',mouse_region_x=point[0],mouse_region_y=point[1],
            mouse_x=point[0],mouse_y=point[1])
        with patch.object(diagram,'layout',return_value=box),patch.object(nodes,'active_grade',return_value=node):
            self.assertEqual(diagram.PG_OT_diagram_drag.invoke(op,context,event),{'RUNNING_MODAL'})
        self.assertIsNotNone(op._warp_fit_token)
        return op,context,box,p

    def move(self,op,context,dx=0,dy=0):
        event=SimpleNamespace(type='MOUSEMOVE',value='NOTHING',
            mouse_x=op._last_mouse[0]+dx,mouse_y=op._last_mouse[1]+dy,
            mouse_region_x=op._last_mouse[0]+dx)
        self.assertEqual(diagram.PG_OT_diagram_drag.modal(op,context,event),{'RUNNING_MODAL'})

    def move_target(self,op,context,target):
        """Move through the real modal conversion at the frozen display scale."""
        action=op._color_action;p=action['plot']
        delta=np.asarray(target)-action['target'];gain=.2 if action['handle']<0 else .5
        self.move(op,context,dx=-delta[1]*p.rect[2]/(gain*(p.xmax-p.xmin)),
                  dy=delta[0]*p.rect[3]/(gain*(p.ymax-p.ymin)))
        actual=nodes.color_model(op._node).guarded_saturation_targets(action['tone'])[action['handle']+1]
        np.testing.assert_allclose(actual,action['target'],atol=2e-7)
        if action['mode']=='position':np.testing.assert_allclose(actual,target,atol=2e-7)

    def test_material_blue_corner_real_undo_redo_recovers_latest_final_output(self):
        # Exercise the reported Shading sequence with real material RNA and
        # Blender undo, using the existing modal-event harness for the drag.
        # Native macOS event dispatch/deallocation still needs GUI acceptance.
        for finished in (False,True):
            with self.subTest(final_lut_before_undo=finished):
                material=bpy.data.materials.new('Blue Warp undo '+str(finished))
                material.use_nodes=True;material.use_fake_user=True
                node=nodes.create_grade(material.node_tree)
                node.pg_chromatic.family='WARP';node.pg_chromatic.active_tone=1
                material_name=material.name;node_name=node.name
                def current():return bpy.data.materials[material_name].node_tree.nodes[node_name]
                before=nodes.read_chromatic(node)
                self.assertIsNone(node.pg_grade)
                bpy.ops.ed.undo_push(message='Before blue Warp drag')
                op,context,_,_=self.gesture(node,handle=4)
                self.assertEqual(op._color_action['handle'],4)
                self.move(op,context,dx=4,dy=3)
                release=SimpleNamespace(type='LEFTMOUSE',value='RELEASE')
                self.assertEqual(diagram.PG_OT_diagram_drag.modal(op,context,release),{'FINISHED'})
                after=nodes.read_chromatic(node)
                self.assertNotEqual(after,before)
                if finished:
                    lut.ensure(node,nodes.bake_model(node),force=True)
                    self.assertEqual(lut.validate_output(node,final=True)['size'],65)
                else:
                    self.assertFalse(lut._states[node.as_pointer()]['final_published'])
                stale=scheduler.lut_candidate(node,nodes.bake_model(node),False)
                scheduler.ready(stale,True)
                # A pending result is admissible now; a completed duplicate
                # may already be rejected by the normal publication policy.
                if not finished:self.assertTrue(scheduler.publication(stale,commit=False))
                bpy.ops.ed.undo_push(message='Blue Warp drag')
                # Blender restores settings; the coordinator adopts native output.
                for action,expected in ((bpy.ops.ed.undo,before),(bpy.ops.ed.redo,after),
                                        (bpy.ops.ed.undo,before)):
                    self.assertEqual(action(),{'FINISHED'})
                    self.finish_recovery()
                    self.assertEqual(nodes.read_chromatic(current()),expected)
                    self.assertNotEqual(stale.session,scheduler.session())
                    self.assertFalse(scheduler.publication(stale))
                self.assertFalse(nodes.recovery_pending())
                self.assertIsNone(current().pg_grade)
                self.assertTrue(lut.is_adopted(current()))
                with patch.object(lut,'ensure',side_effect=AssertionError('Undo silently rebaked output')):
                    nodes.refresh_node(current(),force=True)
                    self.assertEqual(bpy.ops.ed.redo(),{'FINISHED'})
                    self.finish_recovery()
                    self.assertEqual(nodes.read_chromatic(current()),after)
                    self.assertTrue(lut.is_adopted(current()))

    def test_lock_ownership_by_editor_target_tone_and_token(self):
        first=self.node();second=self.node();editor=(1,2,3);other=(1,4,5)
        token=warp_view.begin(editor,first,1,42.)
        warp_view.begin(other,second,2,70.)
        self.assertEqual(warp_view.radius(editor,first,1),42.)
        self.assertEqual(warp_view.radius(other,second,2),70.)
        replacement=warp_view.begin(editor,first,1,60.)
        warp_view.end(token)
        self.assertEqual(warp_view.radius(editor,first,1),60.)
        self.assertIsNone(warp_view.radius(editor,first,2))
        self.assertEqual(warp_view.radius(other,second,2),70.)
        warp_view.begin(editor,first,1,42.)
        self.assertIsNone(warp_view.radius(editor,second,1))
        warp_view.end(replacement)

    def test_handle_fit_frozen_through_timer_reset_and_final_pending_commit(self):
        node=self.node();op,context,box,initial=self.gesture(node,handle=0)
        # Red moves upward on the positive-energy branch. Its captured mouse
        # passes the pad edge, while the bounded handle enters the top controls.
        self.move_target(op,context,(.95,.1))
        self.assertGreater(op._last_mouse[1],initial.rect[1]+initial.rect[3])
        self.assertFalse(warp.handle_visible(initial,op._color_action['target'],box['scale']))
        self.assertGreater(warp.view_radius(nodes.color_model(node),1),initial.xmax)
        self.assertEqual(color.control_state(node,op._space,box)[3].xmax,initial.xmax)
        event=SimpleNamespace(type='TIMER',value='NOTHING',timer=None)
        self.assertEqual(diagram.PG_OT_diagram_drag.modal(op,context,event),{'RUNNING_MODAL'})
        self.assertEqual(color.control_state(node,op._space,box)[3].xmax,initial.xmax)
        event=SimpleNamespace(type='R',value='PRESS')
        self.assertEqual(diagram.PG_OT_diagram_drag.modal(op,context,event),{'RUNNING_MODAL'})
        self.assertEqual(color.control_state(node,op._space,box)[3].xmax,initial.xmax)
        op._pending_color={'web_chroma_1_0':.4}
        with patch.object(diagram.warp_view,'end',wraps=warp_view.end) as end:
            event=SimpleNamespace(type='LEFTMOUSE',value='RELEASE')
            self.assertEqual(diagram.PG_OT_diagram_drag.modal(op,context,event),{'FINISHED'})
            end.assert_called_once()
        self.assertAlmostEqual(nodes.read_chromatic(node).web_chroma_1_0,.4)
        self.assertIsNone(warp_view.radius(box['_warp_editor'],node,1))
        settled=color.control_state(node,op._space,box)[3]
        self.assertGreater(settled.xmax,initial.xmax)
        self.assertTrue(warp.handle_visible(settled,nodes.color_model(node).guarded_saturation_targets(1)[1],box['scale']))

    def test_center_drag_can_move_secondary_vertex_under_header_until_release_refit(self):
        node=self.node()
        # The widest allowed Adaptance reach makes moving the center move the
        # red corner too. In a small real editor, the center stays below the
        # control strip while the secondary corner crosses under it.
        nodes.write_chromatic(node,dict(adaptance_half_saturation=1.))
        op,context,box,initial=self.gesture(node,handle=-1,region=(1000,470))
        self.assertGreater(initial.xmax,1.)
        center_target=(.7,0.)
        self.move_target(op,context,center_target)
        current=color.control_state(node,op._space,box)[3]
        positions=nodes.color_model(node).guarded_saturation_targets(1)
        center_screen=initial.screen(positions[0]);red_screen=initial.screen(positions[1])
        top_limit=initial.rect[1]+initial.rect[3]-(warp.HEADER+9)*box['scale']
        self.assertLess(center_screen[1],top_limit)
        self.assertGreater(red_screen[1],top_limit)
        self.assertEqual(current.xmax,initial.xmax)
        self.assertEqual(current.ymax,initial.ymax)
        # A timer/pause must not fit around the moved secondary point mid-drag.
        event=SimpleNamespace(type='TIMER',value='NOTHING',timer=None)
        self.assertEqual(diagram.PG_OT_diagram_drag.modal(op,context,event),{'RUNNING_MODAL'})
        current=color.control_state(node,op._space,box)[3]
        self.assertEqual(current.xmax,initial.xmax)
        self.assertGreater(initial.screen(nodes.color_model(node).guarded_saturation_targets(1)[1])[1],top_limit)
        event=SimpleNamespace(type='LEFTMOUSE',value='RELEASE')
        self.assertEqual(diagram.PG_OT_diagram_drag.modal(op,context,event),{'FINISHED'})
        settled=color.control_state(node,op._space,box)[3]
        self.assertGreater(settled.xmax,initial.xmax)
        final=nodes.color_model(node).guarded_saturation_targets(1)
        self.assertTrue(warp.handle_visible(settled,final[1],box['scale']))
        self.assertIsNone(warp_view.radius(box['_warp_editor'],node,1))

    def test_center_reset_retains_scope_components_through_release_refit_and_escape(self):
        warp_samples = _component('ui.warp_samples')
        for finish in ('release','escape'):
            with self.subTest(finish=finish):
                sampling.refresh();node=self.node();space=nodes.grading_space(node)
                node.inputs['Color'].default_value=(.2,.3,.7,1.)
                nodes.write_chromatic(node,dict(adaptance_a_1=60.))
                box=geo.layout(1000,750,1.,720,24,24,'WARP');box['_warp_editor']=(10,20,30)
                gate=Event();executor=ScopeExecutor({'scope_update':[None,gate]})
                def visible():
                    clouds.replace_views({node.as_pointer():(clouds.capture_view(node,box),)})
                    return {('full',node.as_pointer()):(node,space,(1,True))}
                visible()
                op=None
                try:
                    with patch.object(jobs,'visible_consumers',side_effect=visible), \
                         patch.object(jobs,'_submit',executor):
                        old=wait_for_scopes(node,(1,True));selected=old['_color']
                        old_pixels=selected['_warp_clouds'][0]['pixels'];old_stats=selected['neutral']
                        op,context,box,initial=self.gesture(node,handle=-1)
                        self.assertEqual(op._color_action['handle'],-1)
                        event=SimpleNamespace(type='R',value='PRESS')
                        self.assertEqual(diagram.PG_OT_diagram_drag.modal(op,context,event),{'RUNNING_MODAL'})
                        self.assertEqual(nodes.read_chromatic(node).adaptance_a_1,0.)
                        pending=sampling.get(node,space,(1,True),ui=True)
                        self.assertIs(pending['_color']['_warp_clouds'][0]['pixels'],old_pixels)
                        self.assertIs(pending['_color']['neutral'],old_stats)
                        self.assertEqual(color.control_state(node,space,box)[3].xmax,initial.xmax)
                        deadline=time.monotonic()+10
                        while jobs._running is None:
                            self.assertLess(time.monotonic(),deadline,'Pending scope analysis did not start')
                            jobs.probe_tick()
                            sampling.get(node,space,(1,True),ui=True)
                            jobs.tick();time.sleep(.001)
                        event=SimpleNamespace(type='LEFTMOUSE' if finish=='release' else 'ESC',
                                              value='RELEASE' if finish=='release' else 'PRESS')
                        self.assertEqual(diagram.PG_OT_diagram_drag.modal(op,context,event),
                                         {'FINISHED'} if finish=='release' else {'CANCELLED'})
                        op=None
                        self.assertIsNone(warp_view.radius(box['_warp_editor'],node,1))
                        current_plot=color.control_state(node,space,box)[3]
                        if finish=='release':self.assertLess(current_plot.xmax,initial.xmax)
                        else:self.assertEqual(current_plot.xmax,initial.xmax)
                        # Draw/request/receipt turns after the radius lock is
                        # released may reproject, but must never lose a cloud.
                        for _ in range(3):
                            retained=sampling.get(node,space,(1,True),ui=True)
                            self.assertIs(retained['_color']['neutral'],old_stats)
                            self.assertIs(retained['_color']['_warp_clouds'][0]['pixels'],old_pixels)
                            self.assertIsNotNone(warp_samples.choose_raster(
                                current_plot,box['scale'],retained['_color']['_warp_clouds'],1))
                            jobs.tick()
                        gate.set();final=wait_for_scopes(node,(1,True))
                        self.assertTrue(final['_color']['_display_current'])
                        self.assertEqual(final['_color']['_visual_analysis'],final['_color']['_statistics_analysis'])
                finally:
                    gate.set()
                    if op is not None:diagram.end_color_drag(op,commit=False)

    def test_cancel_restores_fit_and_parameters_after_expansion(self):
        node=self.node();nodes.write_chromatic(node,dict(adaptance_a_1=60.))
        original=nodes.read_chromatic(node)
        op,context,box,initial=self.gesture(node,handle=0)
        self.move_target(op,context,(.9,.1))
        self.assertGreater(warp.view_radius(nodes.color_model(node),1),initial.xmax)
        event=SimpleNamespace(type='ESC',value='PRESS')
        self.assertEqual(diagram.PG_OT_diagram_drag.modal(op,context,event),{'CANCELLED'})
        self.assertEqual(nodes.read_chromatic(node),original)
        self.assertEqual(color.control_state(node,op._space,box)[3].xmax,initial.xmax)
        self.assertIsNone(op._warp_fit_token)

    def test_both_slider_fits_freeze_before_mouse_down_edit_and_shrink_on_release(self):
        for field in ('adaptance_half_saturation','web_scale_1_0'):
            node=self.node();node.pg_chromatic.active_handle=0
            nodes.write_chromatic(node,dict(adaptance_a_1=60.,web_scale_1_0=1.))
            before=warp.view_radius(nodes.color_model(node),1)
            op,context,box,initial=self.gesture(node,field=field)
            self.assertEqual(op._color_action['fields'],(field,))
            self.assertEqual(op._warp_fit_token.radius,before)
            # Explicitly queue a final smaller edit, as a release between timer ticks does.
            op._pending_color={'adaptance_a_1':0.,'web_scale_1_0':0.}
            self.assertEqual(color.control_state(node,op._space,box)[3].xmax,initial.xmax)
            event=SimpleNamespace(type='LEFTMOUSE',value='RELEASE')
            self.assertEqual(diagram.PG_OT_diagram_drag.modal(op,context,event),{'FINISHED'})
            self.assertLess(color.control_state(node,op._space,box)[3].xmax,initial.xmax)

    def test_scale_gesture_compensates_as_one_pair_reverses_resets_and_cancels(self):
        node=self.node();node.pg_chromatic.active_handle=0
        nodes.write_chromatic(node,dict(web_chroma_1_0=3.))
        initial=nodes.read_chromatic(node)
        op,context,box,plot=self.gesture(node,field='web_scale_1_0')
        height=op._color_action['rect'][3]
        self.move(op,context,dy=height*4)
        adjusted=nodes.read_chromatic(node)
        self.assertAlmostEqual(adjusted.web_scale_1_0,4.)
        self.assertLess(adjusted.web_chroma_1_0,3.)
        self.assertGreater(nodes.color_model(node).warp_targets(1).q[1,0],0.)
        self.move(op,context,dy=-height*4)
        self.assertEqual(nodes.read_chromatic(node),initial)
        self.move(op,context,dy=height*4)
        reduced=nodes.read_chromatic(node).web_chroma_1_0
        event=SimpleNamespace(type='R',value='PRESS')
        self.assertEqual(diagram.PG_OT_diagram_drag.modal(op,context,event),{'RUNNING_MODAL'})
        self.assertEqual(nodes.read_chromatic(node).web_scale_1_0,0.)
        self.assertEqual(nodes.read_chromatic(node).web_chroma_1_0,reduced)
        event=SimpleNamespace(type='ESC',value='PRESS')
        self.assertEqual(diagram.PG_OT_diagram_drag.modal(op,context,event),{'CANCELLED'})
        self.assertEqual(nodes.read_chromatic(node),initial)
        op,context,box,plot=self.gesture(node,field='web_scale_1_0')
        self.move(op,context,dy=op._color_action['rect'][3]*4)
        old=bpy.context.scene.tool_settings.use_keyframe_insert_auto
        try:
            bpy.context.scene.tool_settings.use_keyframe_insert_auto=True
            with patch.object(nodes,'keyframe_chromatic') as keyframe:
                event=SimpleNamespace(type='LEFTMOUSE',value='RELEASE')
                self.assertEqual(diagram.PG_OT_diagram_drag.modal(op,context,event),{'FINISHED'})
                self.assertEqual({call.args[1] for call in keyframe.call_args_list},{'web_scale_1_0','web_chroma_1_0'})
        finally:bpy.context.scene.tool_settings.use_keyframe_insert_auto=old

    def test_editor_close_and_deleted_stack_target_prune_locks(self):
        node=self.node();data=grade_data();stack=sequence(node.id_data,[data])
        target=editing.Target(stack,stack.pg_stack_entries[0]);editor=(1,2,3)
        warp_view.begin(editor,target,1,40.)
        warp_view.begin((1,4,5),node,1,50.)
        stack.pg_stack_entries.clear()
        warp_view.prune({editor},lambda owner:editing.valid(owner) if editing.is_target(owner) else nodes.is_grade(owner))
        self.assertIsNone(warp_view.radius(editor,target,1))
        self.assertIsNone(warp_view.radius((1,4,5),node,1))

    def test_stack_gesture_freezes_fit_and_cleans_up_on_entry_removal(self):
        node=self.node();stack=sequence(node.id_data,[grade_data()])
        target=editing.Target(stack,stack.pg_stack_entries[0])
        target.pg_chromatic.family='WARP';target.pg_chromatic.active_tone=1
        op,context,box,initial=self.gesture(target,handle=0)
        self.move_target(op,context,(.95,.1))
        self.assertGreater(warp.view_radius(nodes.color_model(target),1),initial.xmax)
        self.assertEqual(color.control_state(target,op._space,box)[3].xmax,initial.xmax)
        stack.pg_stack_entries.clear()
        event=SimpleNamespace(type='TIMER',value='NOTHING',timer=None)
        self.assertEqual(diagram.PG_OT_diagram_drag.modal(op,context,event),{'CANCELLED'})
        self.assertIsNone(warp_view.radius(box['_warp_editor'],target,1))

    def test_flush_error_and_lifecycle_cleanup_release_locks(self):
        node=self.node();editor=(1,2,3)
        op=SimpleNamespace(_node=node,_pending_color={'adaptance_a_1':3.},
            _warp_fit_token=warp_view.begin(editor,node,1,42.))
        with patch.object(nodes,'write_chromatic',side_effect=RuntimeError('deleted target')):
            with self.assertRaises(RuntimeError):diagram.end_color_drag(op)
        self.assertIsNone(warp_view.radius(editor,node,1))
        self.assertIsNone(op._pending_color)
        for cleanup in (diagram.cleanup_drag_timers,diagram.cleanup_hover_cursors,
                        sampling.clear,nodes.undo_redo_pre_handler):
            warp_view.begin(editor,node,1,42.)
            cleanup()
            self.assertIsNone(warp_view.radius(editor,node,1))
        nodes.reset_cache_handler()
        for _ in range(100):
            nodes.recovery_tick()
            if nodes.recovery_status()['state'] in ('completed','failed'):break
        self.assertEqual(nodes.recovery_status()['state'],'completed',nodes.recovery_status())

    def test_save_settles_latest_pair_and_late_modal_events_cannot_restore_it(self):
        node = self.node()
        op, context, box, plot = self.gesture(node, handle=0)
        op._pending_color = {'web_chroma_1_0': .4, 'web_scale_1_0': .5}
        old = bpy.context.scene.tool_settings.use_keyframe_insert_auto
        try:
            bpy.context.scene.tool_settings.use_keyframe_insert_auto = True
            with patch.object(nodes, 'keyframe_chromatic') as keyed:
                diagram.settle_drags(commit=True)
                self.assertEqual({call.args[1] for call in keyed.call_args_list},
                                 {'web_chroma_1_0', 'web_scale_1_0'})
        finally:
            bpy.context.scene.tool_settings.use_keyframe_insert_auto = old
        accepted = nodes.read_chromatic(node)
        self.assertAlmostEqual(accepted.web_chroma_1_0, .4)
        self.assertAlmostEqual(accepted.web_scale_1_0, .5)
        self.assertFalse(diagram._active_drags)
        self.assertIsNone(warp_view.radius(box['_warp_editor'], node, 1))
        for event in (SimpleNamespace(type='ESC', value='PRESS'),
                      SimpleNamespace(type='LEFTMOUSE', value='RELEASE')):
            self.assertEqual(diagram.PG_OT_diagram_drag.modal(op, context, event), {'CANCELLED'})
            self.assertEqual(nodes.read_chromatic(node), accepted)

    def test_every_terminal_modal_path_detaches_rna_after_keyframing(self):
        for terminal in ('release', 'escape', 'failure', 'suspend'):
            with self.subTest(terminal=terminal):
                node = self.node()
                op, context, _box, _plot = self.gesture(node, handle=4)
                original = op._chromatic_start
                if terminal == 'release':
                    event = SimpleNamespace(type='LEFTMOUSE', value='RELEASE')
                    def keyframe(live, current_context):
                        self.assertIs(live._node, node)
                        self.assertIs(live._context, context)
                    with patch.object(diagram, 'keyframe_drag', side_effect=keyframe) as keyed:
                        self.assertEqual(diagram.PG_OT_diagram_drag.modal(op, context, event), {'FINISHED'})
                        keyed.assert_called_once()
                elif terminal == 'escape':
                    self.assertEqual(diagram.PG_OT_diagram_drag.modal(op, context,
                        SimpleNamespace(type='ESC', value='PRESS')), {'CANCELLED'})
                elif terminal == 'failure':
                    with self.assertLogs(diagram.LOG, level='ERROR'), \
                         patch.object(nodes, 'is_grade', side_effect=RuntimeError('Interrupted modal')):
                        self.assertEqual(diagram.PG_OT_diagram_drag.modal(op, context,
                            SimpleNamespace(type='TIMER', value='NOTHING')), {'CANCELLED'})
                else:
                    diagram.settle_drags()
                for name in ('_node', '_grade_start', '_context', '_area', '_wm', '_window', '_drag_timer'):
                    self.assertIsNone(getattr(op, name))
                self.assertIs(op._chromatic_start, original)
                self.assertNotIn(id(op), diagram._active_drags)
                self.assertNotIn(id(op), diagram._drag_timers)

    def test_failed_invoke_releases_operator_references_and_gesture_tokens(self):
        node = self.node()
        with patch.object(color, 'apply_click', side_effect=RuntimeError('Interrupted invoke')), \
             patch.object(diagram, 'release_drag_references', wraps=diagram.release_drag_references) as released:
            with self.assertRaisesRegex(RuntimeError, 'Interrupted invoke'):
                self.gesture(node, handle=4)
        released.assert_called_once()
        op = released.call_args.args[0]
        for name in ('_node', '_grade_start', '_context', '_area', '_wm', '_window'):
            self.assertIsNone(getattr(op, name))
        self.assertFalse(diagram._active_drags or diagram._drag_timers)

    def test_lifecycle_suspend_discards_pending_and_never_replays_snapshot(self):
        node = self.node()
        op, context, box, plot = self.gesture(node, handle=0)
        nodes.write_chromatic(node, {'web_chroma_1_0': .2})
        op._pending_color = {'web_chroma_1_0': .7}
        nodes.suspend_handler()
        # Simulate the settings restored by undo/load before the old operator
        # receives its next callback. Neither buffered nor start values apply.
        nodes.write_chromatic(node, {'web_chroma_1_0': .3})
        event = SimpleNamespace(type='ESC', value='PRESS')
        self.assertEqual(diagram.PG_OT_diagram_drag.modal(op, context, event), {'CANCELLED'})
        self.assertAlmostEqual(nodes.read_chromatic(node).web_chroma_1_0, .3)
        self.assertIsNone(op._pending_color)
        self.assertFalse(diagram._active_drags)
        self.assertIsNone(warp_view.radius(box['_warp_editor'], node, 1))

    def test_stops_modal_pending_reset_cancel_and_release_rim_lifetime(self):
        node=self.node();initial=nodes.read_chromatic(node)
        op,context,box,plot=self.gesture(node,handle=0)
        editor=box['_warp_editor'];action=op._color_action
        # A single captured drag can go past the compact display disk.
        direction=action['target']/np.linalg.norm(action['target'])
        delta=direction*.6
        self.move(op,context,dx=-delta[1]*plot.rect[2]/(.5*(plot.xmax-plot.xmin)),
                  dy=delta[0]*plot.rect[3]/(.5*(plot.ymax-plot.ymin)))
        self.assertEqual(action['mode'],'stops')
        self.assertIsNotNone(warp.active_rim_radius(editor,node,nodes.color_model(node),1,0))
        held=warp_view.radius(editor,node,1)
        # The event timer publishes pending values, but does not end or refit.
        event=SimpleNamespace(type='TIMER',value='NOTHING',timer=None)
        diagram.PG_OT_diagram_drag.modal(op,context,event)
        self.assertEqual(warp_view.radius(editor,node,1),held)
        self.assertEqual(action['mode'],'stops')
        event=SimpleNamespace(type='R',value='PRESS')
        diagram.PG_OT_diagram_drag.modal(op,context,event)
        self.assertEqual(action['mode'],'position')
        self.assertIsNone(warp.active_rim_radius(editor,node,nodes.color_model(node),1,0))
        np.testing.assert_allclose(action['cursor'],action['target'])
        self.move(op,context,dy=3)
        event=SimpleNamespace(type='ESC',value='PRESS')
        self.assertEqual(diagram.PG_OT_diagram_drag.modal(op,context,event),{'CANCELLED'})
        self.assertEqual(nodes.read_chromatic(node),initial)
        self.assertIsNone(op._warp_dot_token)
        self.assertIsNone(warp.active_rim_radius(editor,node,nodes.color_model(node),1,0))
        self.assertIsNone(warp_view.radius(editor,node,1))
