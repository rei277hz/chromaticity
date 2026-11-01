"""Physical Warp handles, centered automatic views and Blender RNA plumbing."""
from tests.support.session import component as _component, SessionTest, patch
from dataclasses import replace
from types import SimpleNamespace
pass
import numpy as np
import bpy
nodes = _component('graph.nodes'); grades = _component('graph.grades'); stacks = _component('graph.stacks')
from color_tools.perceptual_grade_core.model import color as cm
color = _component('ui.color'); geo = _component('ui.color_geometry'); warp = _component('ui.warp'); panel = _component('ui.panel'); diagram = _component('ui.diagram')
from tests.support.blender import BlenderTest,grade_data,sequence


class WarpTests(BlenderTest):
    def node(self):
        tree=bpy.data.node_groups.new('Warp UI','CompositorNodeTree')
        return nodes.create_grade(tree)

    def test_schema_hue_removal_and_page_reset_fields(self):
        node=self.node();ui=node.pg_chromatic
        self.assertEqual({item.identifier for item in ui.bl_rna.properties['family'].enum_items},{'J','C','WARP'})
        for name in ('hue_0','hue_fit','concentration_a_0','global_low_hue','adaptance_fit','adaptance_strength'):
            self.assertNotIn(name,ui.bl_rna.properties)
            self.assertNotIn(name,cm.PARAM_NAMES)
        self.assertEqual(len([n for n in cm.PARAM_NAMES if n.startswith('web_')]),72)
        fields=panel.color_fields('WARP')
        self.assertIn('adaptance_half_saturation',fields)
        self.assertNotIn('adaptance_reach',fields)
        self.assertTrue(all(n in fields for n in warp.fields(2,4)))
        self.assertNotIn('global_gain',fields)
        self.assertEqual(ui.adaptance_half_saturation,.25)

    def test_center_is_direct_destination_at_every_half_saturation_and_preserves_neutral_ja(self):
        node=self.node();tone=nodes.read_tone(node)
        for row in range(4):
            for half in (.05,.25,1.):
                model=cm.model(tone,replace(cm.Parameters(),adaptance_half_saturation=half))
                target=np.array([3.,-2.])
                values=model.target_values(row,-1,target)
                self.assertEqual(values,{f'adaptance_a_{row}':3.,f'adaptance_b_{row}':-2.})
                edited=cm.model(tone,replace(model.params,**values))
                actual=edited.warp_targets(row)
                np.testing.assert_allclose(actual.q[0,1:],target,atol=2e-12)
                self.assertEqual(actual.energy[0],edited.web.geometry.anchors[row]**2)

    def test_unphysical_center_drag_retains_last_valid_target(self):
        node=self.node();ui=node.pg_chromatic;ui.active_tone=1
        model=nodes.color_model(node);p=warp.plot((0,0,300,300),ui,model,1)
        action=warp.hit(ui,model,p,p.screen((0.,0.)),1.)
        values=warp.drag(model,action,2.,3.)
        self.assertTrue(values)
        accepted=action['target'].copy()
        edited=cm.model(nodes.read_tone(node),replace(model.params,**values))
        self.assertEqual(warp.drag(edited,action,1.e6,1.e6),{})
        np.testing.assert_array_equal(action['target'],accepted)
        with self.assertRaisesRegex(ValueError,'positive cone responses'):
            edited.target_values(1,-1,[1.e6,-1.e6])

    def test_orientation_inverse_clipping_and_equal_aspect(self):
        p=geo.ABPlot((10,20,400,200),-20,20,-10,10)
        np.testing.assert_allclose(p.screen((1,0)),(210,130))
        np.testing.assert_allclose(p.screen((0,-1)),(220,120))
        np.testing.assert_allclose(p.unscreen(p.screen((3,-7))),(3,-7))
        self.assertTrue(p.inside((9,19)));self.assertFalse(p.inside((11,0)))
        node=self.node();ui=node.pg_chromatic;model=nodes.color_model(node)
        p=warp.plot((0,0,300,220),ui,model,1)
        self.assertEqual(p.rect,(40.,0.,220.,220.))
        self.assertAlmostEqual(p.rect[2]/(p.xmax-p.xmin),p.rect[3]/(p.ymax-p.ymin))
        self.assertEqual(p.screen((0.,0.)),(150.,110.))
        self.assertEqual(p.xmin,-p.xmax);self.assertEqual(p.ymin,-p.ymax)
        self.assertAlmostEqual(p.xmax,p.ymax)

    def test_layout_warp_pad_is_one_centered_square_with_inset_control(self):
        for width,height,scale,requested in ((1000,700,1,720),(1600,800,1,1200),(1000,600,1,720),(1600,1000,1.5,900),(384,438,1,360)):
            box=geo.layout(width,height,scale,requested,24,24,'WARP')
            x,y,w,h=box['ab'];self.assertAlmostEqual(w,h)
            self.assertAlmostEqual(w,min(box['rect'][3]-119*scale,box['rect'][2]-38*scale))
            for key in ('vectorscope','waveform','readout','warp_scale'):self.assertNotIn(key,box)
            sx,sy,sw,sh=box['global1']
            self.assertGreaterEqual(sx,x);self.assertGreaterEqual(sy,y)
            self.assertLessEqual(sx+sw,x+w);self.assertLessEqual(sy+sh,y+h)
            for tx,ty,tw,th in box['tone_buttons'].values():
                self.assertGreaterEqual(tx,x);self.assertGreaterEqual(ty,y)
                self.assertLessEqual(tx+tw,x+w);self.assertLessEqual(ty+th,y+h)
        box=geo.layout(1000,700,1,390,24,24,'WARP')
        self.assertEqual(box['ab'][2],box['rect'][3]-119.)
        self.assertEqual(box['rect'][2],box['ab'][2]+38.)

    def test_derived_view_auto_expands_and_contracts_without_persisted_state(self):
        node=self.node();ui=node.pg_chromatic;model=nodes.color_model(node)
        snapshot=nodes.read_chromatic(node)
        initial=warp.view_radius(model,1)
        pad=(11.,17.,300.,300.)
        initial_plot=warp.plot(pad,ui,model,1)
        nodes.write_chromatic(node,{f'web_hue_1_{i}':90. for i in range(6)})
        expanded_model=nodes.color_model(node)
        expanded=warp.view_radius(expanded_model,1)
        expanded_plot=warp.plot(pad,ui,expanded_model,1)
        self.assertGreater(expanded,initial)
        self.assertEqual(expanded_plot.rect,initial_plot.rect)
        self.assertAlmostEqual(expanded_plot.screen((0.,0.))[0],pad[0]+pad[2]/2)
        self.assertAlmostEqual(expanded_plot.screen((0.,0.))[1],pad[1]+pad[3]/2)
        nodes.write_chromatic(node,{f'web_hue_1_{i}':0. for i in range(6)})
        contracted=warp.view_radius(nodes.color_model(node),1)
        self.assertLess(contracted,expanded)
        self.assertEqual(snapshot,nodes.read_chromatic(node))
        scaled=cm.model(nodes.read_tone(node),replace(model.params,web_scale_1_0=1.))
        self.assertTrue(np.isfinite(warp.view_radius(scaled,1)))
        self.assertEqual(warp.plot(pad,ui,scaled,1).rect,initial_plot.rect)
        for tone in range(4):
            self.assertFalse(hasattr(ui,f'warp_view_ready_{tone}'))
            for bound in ('a_min','a_max','b_min','b_max'):
                self.assertFalse(hasattr(ui,f'warp_{bound}_{tone}'))

    def test_combined_geometry_changes_with_adaptance_but_not_jc(self):
        node=self.node();model=nodes.color_model(node);base=warp.geometry(model,1)
        np.testing.assert_array_equal(base['before'].q,base['after'].q)
        nodes.write_chromatic(node,dict(adaptance_a_1=10.,web_hue_1_0=5.,web_scale_1_3=.1))
        model=nodes.color_model(node);edited=warp.geometry(model,1)
        self.assertGreater(np.max(abs(edited['contours'][-1][1].q-base['contours'][-1][1].q)),1.)
        nodes.write_chromatic(node,dict(j_high_1=12.,c_low_1=.2,global_gain=.1))
        other=warp.geometry(nodes.color_model(node),1)
        np.testing.assert_array_equal(other['after'].q,edited['after'].q)
        for (source,target),(source2,target2) in zip(edited['contours'],other['contours']):
            np.testing.assert_array_equal(source.q,source2.q)
            np.testing.assert_array_equal(target.q,target2.q)

    def test_actual_saturation_drag_offset_and_speed_by_handle(self):
        node=self.node();node.pg_chromatic.family='WARP';node.pg_chromatic.active_tone=1
        nodes.write_chromatic(node,dict(adaptance_a_1=5.,web_scale_1_0=.2))
        model=nodes.color_model(node);p=warp.plot((0,0,300,300),node.pg_chromatic,model,1)
        target=model.guarded_saturation_targets(1)[1]
        action=warp.hit(node.pg_chromatic,model,p,p.screen(target),1.)
        self.assertEqual(action['handle'],0)
        start=action['target'].copy()
        gain=.5
        expected=start+gain*np.array([3.*(p.ymax-p.ymin)/p.rect[3],-2.*(p.xmax-p.xmin)/p.rect[2]])
        values=warp.drag(model,action,2.,3.)
        edited=cm.model(nodes.read_tone(node),replace(model.params,**values))
        np.testing.assert_allclose(edited.guarded_saturation_targets(1)[1],expected,rtol=2e-6,atol=2e-8)
        np.testing.assert_allclose(edited.guarded_saturation_targets(1)[1],action['target'],rtol=2e-6,atol=2e-8)
        self.assertEqual(edited.params.web_scale_1_0,model.params.web_scale_1_0)
        nodes.write_chromatic(node,dict(adaptance_half_saturation=.05))
        model=nodes.color_model(node);target=model.guarded_saturation_targets(1)[0]
        action=warp.hit(node.pg_chromatic,model,p,p.screen(target),1.)
        self.assertFalse(action['disabled'])
        values=warp.drag(model,action,2.,3.)
        self.assertTrue(values)
        edited=cm.model(nodes.read_tone(node),replace(model.params,**values))
        np.testing.assert_allclose(edited.guarded_saturation_targets(1)[0],action['target'],rtol=2e-6,atol=2e-8)

        # Center Adaptance movement is 0.2×, while corners remain at 0.5×.
        nodes.write_chromatic(node,dict(adaptance_half_saturation=1.))
        model=nodes.color_model(node);p=warp.plot((0,0,300,300),node.pg_chromatic,model,1)
        center=model.guarded_saturation_targets(1)[0]
        action=warp.hit(node.pg_chromatic,model,p,p.screen(center),1.)
        self.assertEqual(action['handle'],-1)
        start=action['target'].copy()
        expected=start+.2*np.array([3.*(p.ymax-p.ymin)/p.rect[3],-2.*(p.xmax-p.xmin)/p.rect[2]])
        values=warp.drag(model,action,2.,3.)
        edited=cm.model(nodes.read_tone(node),replace(model.params,**values))
        np.testing.assert_allclose(edited.guarded_saturation_targets(1)[0],expected,rtol=2e-6,atol=2e-8)

    def test_drag_conversion_keeps_mouse_down_range_during_auto_fit(self):
        node=self.node();ui=node.pg_chromatic;ui.active_tone=1
        model=nodes.color_model(node);p=warp.plot((0,0,300,300),ui,model,1)
        corner=model.guarded_saturation_targets(1)[5]
        action=warp.hit(ui,model,p,p.screen(corner),1.)
        dy=corner[0]*p.rect[3]/(p.ymax-p.ymin)*.04
        dx=-corner[1]*p.rect[2]/(p.xmax-p.xmin)*.04
        values=warp.drag(model,action,dx,dy)
        edited=cm.model(nodes.read_tone(node),replace(model.params,**values))
        increment=.02*corner
        np.testing.assert_allclose(action['target'],corner+increment,rtol=2e-6,atol=2e-8)
        start=action['target'].copy()
        fitted=warp.plot(p.rect,ui,edited,1)
        self.assertGreaterEqual(fitted.xmax,1.)
        second=warp.drag(edited,action,dx,dy)
        self.assertTrue(second)
        np.testing.assert_allclose(action['target']-start,increment,rtol=2e-6,atol=2e-8)
        self.assertIs(action['plot'],p)

    def test_stack_focus_preserves_selected_handle_without_view_state(self):
        data=grade_data();tree=bpy.data.node_groups.new('Warp stack','CompositorNodeTree')
        node=sequence(tree,[data]);focus=node.pg_stack_entries[0].focus
        focus.family='WARP';focus.active_handle=4
        saved=stacks.entries(node);stacks.assign(node,saved)
        focus=node.pg_stack_entries[0].focus
        self.assertEqual(focus.active_handle,4)
        self.assertFalse(hasattr(focus,'warp_view_ready_2'))

    def test_warp_has_no_manual_view_controls_or_separate_scope_hits(self):
        node=self.node();ui=node.pg_chromatic;ui.family='WARP'
        model=nodes.color_model(node);box=geo.layout(900,680,1,720,24,24,'WARP')
        self.assertNotIn('warp_fit',box);self.assertNotIn('warp_reset',box)
        self.assertFalse(hasattr(panel,'PG_OT_warp_fit_view'))
        self.assertFalse(hasattr(panel,'PG_OT_warp_reset_handle'))
        point=(0.,0.)
        with patch.object(geo,'waveform_tone',side_effect=AssertionError('Warp has no waveform hit')):
            self.assertEqual(color.hit(node,nodes.grading_space(node),box,point)['kind'],'consume')
        with patch.object(diagram,'rectangle') as rectangle,patch.object(diagram,'text'),patch.object(diagram,'lines'),patch.object(color,'draw_vectorscope') as vectorscope:
            color.draw_scopes(box,model,ui.active_tone,None,warp=True)
        rectangle.assert_not_called();vectorscope.assert_not_called()
        for family in ('J','C'):
            ui.family=family;box=geo.layout(900,680,1,720,24,24,family)
            with patch.object(geo,'waveform_tone',return_value=2) as waveform:
                self.assertEqual(color.hit(node,nodes.grading_space(node),box,(0.,0.)),dict(kind='tone',value=2,source='waveform'))
            waveform.assert_called_once()
            with patch.object(diagram,'rectangle') as rectangle,patch.object(diagram,'text'),patch.object(diagram,'lines'),patch.object(color,'draw_vectorscope') as vectorscope:
                color.draw_scopes(box,model,ui.active_tone,None)
            rectangle.assert_called_once_with(box['waveform'],color.theme.PLOT)
            vectorscope.assert_called_once()

    def test_warp_contours_show_modified_only_with_dim_inner_lines(self):
        node=self.node();ui=node.pg_chromatic;ui.active_tone=1
        model=nodes.color_model(node);p=warp.plot((0,0,300,300),ui,model,1)
        with patch.object(diagram,'curve') as curve,patch.object(diagram,'rectangle'),patch.object(diagram,'lines'),patch.object(diagram,'text'),patch.object(diagram,'triangles'):
            warp.draw(p,model,ui,1.)
        closed=[call for call in curve.call_args_list if np.array_equal(np.asarray(call.args[1])[0],np.asarray(call.args[1])[-1])]
        self.assertEqual(len(closed),4)
        self.assertEqual([call.args[2] for call in closed],[(*color.theme.ORANGE[:3],opacity) for opacity in (.4,.4,.4,.8)])
        self.assertTrue(all(call.args[3]==1. for call in closed))
        self.assertEqual(len(curve.call_args_list),10)  # Four contours and six modified spokes; no permanent rim.
        self.assertTrue(all(len(call.args)<5 or not call.args[4] for call in curve.call_args_list))

    def test_fixed_targets_align_with_reset_handles_and_keep_control_precedence(self):
        reference = _component('scopes.reference')
        node=self.node();ui=node.pg_chromatic;ui.family='WARP';ui.active_tone=1
        box=geo.layout(1000,700,1,390,24,24,'WARP')
        model=nodes.color_model(node);p=warp.plot(box['ab'],ui,model,1)
        g=warp.geometry(model,1)
        np.testing.assert_array_equal(g['before'].q[1:],g['after'].q[1:])
        context=SimpleNamespace(window_manager=SimpleNamespace(pg_stage='CHROMATIC'))
        with patch.object(reference,'connected',return_value=True),patch.object(color.cs,'get',side_effect=AssertionError('Hit must not sample')):
            for index,rect in box['tone_buttons'].items():
                x,y,w,h=rect;point=(x+w/2,y+h/2)
                self.assertEqual(color.hit(node,nodes.grading_space(node),box,point)['value'],index)
                self.assertFalse(diagram.comparison_hit(context,node,box,point))
            for q in model.guarded_saturation_targets(1):
                point=p.screen(q)
                self.assertEqual(color.hit(node,nodes.grading_space(node),box,point)['kind'],'warp_dot')
                self.assertFalse(diagram.comparison_hit(context,node,box,point))
            x,y,w,h=box['ab'];point=(x+w*.9,y+h*.1)
            self.assertEqual(color.hit(node,nodes.grading_space(node),box,point)['kind'],'consume')
            self.assertTrue(diagram.comparison_hit(context,node,box,point))

    def test_statistics_tooltip_follows_caption_position(self):
        gizmo_help = _component('ui.help')
        node=self.node();ui=node.pg_chromatic;ui.family='WARP'
        box=geo.layout(1000,700,1,390,24,24,'WARP')
        context=SimpleNamespace(window_manager=SimpleNamespace(pg_stage='CHROMATIC'))
        sx,sy=box['warp_statistics']
        with patch.object(diagram,'comparison_hit',return_value=False):
            actual=gizmo_help.at(context,node,box,(sx+10.,sy+2.))
            self.assertEqual(actual.title,'diagram.adaptance.statistics')
            x,y,w,h=geo.square(box['ab'])
            previous=gizmo_help.at(context,node,box,(x+10.,y-30.))
            self.assertIsNone(previous)

    def test_modal_drag_ignores_shift_for_corner_and_center(self):
        for handle in (-1,0):
            node=self.node();ui=node.pg_chromatic;ui.family='WARP';ui.active_tone=1
            model=nodes.color_model(node);p=warp.plot((0,0,300,300),ui,model,1)
            target=model.guarded_saturation_targets(1)[handle+1]
            results=[]
            for shift in (False,True):
                action=warp.hit(ui,model,p,p.screen(target),1.)
                op=SimpleNamespace(_node=node,_wm=SimpleNamespace(pg_diagram_enabled=True),_area=SimpleNamespace(tag_redraw=lambda:None),
                    _space=nodes.grading_space(node),_scene_space=nodes.working_space(),_window=None,
                    _mode='chromatic',_last_mouse=(0.,0.),_color_action=action,_pending_color=None,_drag_timer=None,_last_commit=0.)
                event=SimpleNamespace(type='MOUSEMOVE',value='NOTHING',mouse_x=2.,mouse_y=3.,shift=shift)
                with patch.object(diagram,'flush_color'):
                    self.assertEqual(diagram.PG_OT_diagram_drag.modal(op,bpy.context,event),{'RUNNING_MODAL'})
                results.append(op._pending_color)
            self.assertIsNotNone(results[0]);self.assertEqual(results[0],results[1])

    def test_atomic_modal_drag_autokey_reset_and_cancel(self):
        node=self.node();ui=node.pg_chromatic;ui.family='WARP';ui.active_tone=1
        nodes.write_chromatic(node,dict(adaptance_a_1=3.,web_scale_1_0=.1))
        initial=nodes.read_chromatic(node);model=nodes.color_model(node)
        p=warp.plot((0,0,300,300),ui,model,1)
        action=warp.hit(ui,model,p,p.screen(model.guarded_saturation_targets(1)[1]),1.)
        ui.active_handle=0
        wm=bpy.context.window_manager;wm.pg_diagram_enabled=True
        op=SimpleNamespace(_node=node,_wm=wm,_area=SimpleNamespace(tag_redraw=lambda:None),
            _window=None,_space=nodes.grading_space(node),_scene_space=nodes.working_space(),
            _mode='chromatic',_last_mouse=(0,0),_color_action=action,_box={'scale':1},
            _pending_color=None,_drag_timer=None,_last_commit=0.,_chromatic_start=initial,
            _focus_start=('WARP',1,'low',0),_grade_start=grades.selected(node),
            _color_accumulator={name:getattr(initial,name) for name in action['fields']})
        event=SimpleNamespace(type='MOUSEMOVE',value='NOTHING',mouse_x=2.,mouse_y=3.,shift=False)
        self.assertEqual(diagram.PG_OT_diagram_drag.modal(op,bpy.context,event),{'RUNNING_MODAL'})
        edited=nodes.read_chromatic(node)
        changed={name for name in cm.PARAM_NAMES if getattr(initial,name)!=getattr(edited,name)}
        self.assertTrue(changed);self.assertLessEqual(changed,set(warp.fields(1,0,False)))
        reset_op=SimpleNamespace(**vars(op))
        auto=bpy.context.scene.tool_settings.use_keyframe_insert_auto
        try:
            bpy.context.scene.tool_settings.use_keyframe_insert_auto=True
            with patch.object(nodes,'keyframe_chromatic') as keyframe:
                event=SimpleNamespace(type='LEFTMOUSE',value='RELEASE')
                self.assertEqual(diagram.PG_OT_diagram_drag.modal(op,bpy.context,event),{'FINISHED'})
                self.assertEqual({call.args[1] for call in keyframe.call_args_list},changed)
        finally:bpy.context.scene.tool_settings.use_keyframe_insert_auto=auto
        self.assertIsNone(op._node)
        self.assertIsNone(op._color_action)
        diagram.PG_OT_diagram_drag.reset_dragged(reset_op)
        self.assertTrue(all(getattr(nodes.read_chromatic(node),name)==0 for name in warp.fields(1,0)))
        self.assertEqual(nodes.read_chromatic(node).adaptance_a_1,initial.adaptance_a_1)
        diagram.PG_OT_diagram_drag.restore(reset_op)
        self.assertEqual(nodes.read_chromatic(node),initial)

    def test_invalid_crossing_keeps_last_valid_drag_target(self):
        node=self.node();model=nodes.color_model(node);ui=node.pg_chromatic;ui.active_tone=1
        p=warp.plot((0,0,300,300),ui,model,1)
        positions=model.guarded_saturation_targets(1)
        action=warp.hit(ui,model,p,p.screen(positions[1]),1.)
        saved=action['target'].copy()
        delta=np.asarray(p.screen(positions[3]))-p.screen(positions[1])
        self.assertEqual(warp.drag(model,action,*(delta*2)),{})
        np.testing.assert_array_equal(action['target'],saved)

    def test_native_gpu_draws_warp_contours_handles_and_both_sample_clouds(self):
        import sys
        import gpu
        from mathutils import Matrix
        reference = _component('scopes.reference')
        warp_samples = _component('ui.warp_samples')
        bpy.context.preferences.system.gpu_backend='METAL' if sys.platform=='darwin' else 'OPENGL'
        gpu.init()
        node=self.node();ui=node.pg_chromatic;ui.family='WARP';ui.active_tone=1;ui.active_handle=0
        nodes.write_chromatic(node,dict(adaptance_a_1=15.,adaptance_b_1=-9.,web_hue_1_0=12.,web_chroma_1_0=.2,web_scale_1_0=.1))
        model=nodes.color_model(node);box=geo.layout(900,680,1,720,24,24,'WARP')
        p=warp.plot(box['ab'],ui,model,1)
        before=nodes.read_chromatic(node)
        rng=np.random.default_rng(571)
        q=np.column_stack((np.full(1000,50.),rng.uniform(-.5,.5,(1000,2))*p.xmax))
        result=dict(after=q,saturation=q[:,1:],bounded_saturation=q[:,1:],after_energy=np.ones(1000),weights=np.ones(1000),_base={})
        external=dict(signal=dict(appearance=q*.8,saturation=q[:,1:]*.8,bounded_saturation=q[:,1:]*.8,energy=np.ones(1000)),weights=np.full(1000,.6))
        width,height=800,600;surface=gpu.types.GPUOffScreen(width,height)
        try:
            with surface.bind():
                gpu.state.viewport_set(0,0,width,height)
                frame=gpu.state.active_framebuffer_get();frame.clear(color=(.13,.13,.13,1.))
                with gpu.matrix.push_pop(),gpu.matrix.push_pop_projection():
                    gpu.matrix.load_matrix(Matrix.Identity(4))
                    gpu.matrix.load_projection_matrix(Matrix(((2/width,0,0,-1),(0,2/height,0,-1),(0,0,-1,0),(0,0,0,1))))
                    gpu.state.blend_set('ALPHA')
                    with patch.object(color.cs,'get',return_value=result),patch.object(reference,'selected',return_value=external),patch.object(grades,'changed',side_effect=AssertionError('Draw must not write RNA')):
                        color.draw_board(None,node,nodes.grading_space(node),model.params,box)
                    self.assertEqual(nodes.read_chromatic(node),before)
                    gpu.state.blend_set('NONE')
                    pixels=frame.read_color(0,0,width,height,4,0,'UBYTE');pixels.dimensions=width*height*4
                    values=np.asarray(pixels).reshape(height,width,4)
                    self.assertGreater(len(np.unique(values.reshape(-1,4),axis=0)),100)
                    # Orange curve pixels prove the opponent geometry reached the GPU canvas.
                    self.assertGreater(np.sum((values[...,0]>180)&(values[...,1]>80)&(values[...,1]<170)&(values[...,2]<40)),300)
        finally:warp_samples.clear();surface.free()

    def test_native_gpu_clips_boundary_markers_and_keeps_narrow_axis_below_tones(self):
        import sys
        import gpu
        from mathutils import Matrix
        pass
        bpy.context.preferences.system.gpu_backend='METAL' if sys.platform=='darwin' else 'OPENGL'
        gpu.init()
        p=geo.ABPlot((20.,20.,118.,118.),-1,1,-1,1)
        node=self.node();ui=node.pg_chromatic;ui.family='WARP';model=nodes.color_model(node)
        with patch.object(diagram,'text') as text,patch.object(diagram,'rectangle'),patch.object(diagram,'lines'),patch.object(diagram,'curve'),patch.object(diagram,'triangles'):
            warp.draw(p,model,ui,1.)
        label=next(call for call in text.call_args_list if call.args[0]==_component('localization.i18n').M('symbol.a_plus'))
        self.assertLess(label.args[2]+8.,p.rect[1]+p.rect[3]-28.)
        surface=gpu.types.GPUOffScreen(180,180)
        try:
            with surface.bind():
                gpu.state.viewport_set(0,0,180,180)
                frame=gpu.state.active_framebuffer_get();frame.clear(color=(.13,.13,.13,1.))
                with gpu.matrix.push_pop(),gpu.matrix.push_pop_projection():
                    gpu.matrix.load_matrix(Matrix.Identity(4))
                    gpu.matrix.load_projection_matrix(Matrix(((2/180,0,0,-1),(0,2/180,0,-1),(0,0,-1,0),(0,0,0,1))))
                    gpu.state.blend_set('ALPHA')
                    for screen in ((20.2,79.),(137.8,79.),(79.,20.2),(79.,137.8)):
                        warp.target(p,p.unscreen(screen),warp.COLORS[1],1.)
                        warp._circle(p,screen,4.,warp.COLORS[1])
                        warp._circle(p,screen,6.,color.theme.TEXT,True,.8)
                        warp._text(p,'M',(screen[0]+5.,screen[1]+4.),7.,warp.COLORS[1])
                    gpu.state.blend_set('NONE')
                    pixels=frame.read_color(0,0,180,180,4,0,'UBYTE');pixels.dimensions=180*180*4
                    values=np.asarray(pixels).reshape(180,180,4)
                    changed=np.any(values!=values[0,0],axis=-1)
                    outside=np.ones((180,180),bool);outside[20:138,20:138]=False
                    self.assertGreater(np.count_nonzero(changed),100)
                    self.assertFalse(np.any(changed[outside]))
        finally:surface.free()

    def test_focus_and_refresh_leave_view_derived_from_current_grade(self):
        node=self.node();ui=node.pg_chromatic
        ui.family='WARP';ui.active_tone=0
        radius=warp.view_radius(nodes.color_model(node),0)
        nodes.refresh_node(node)
        self.assertEqual(radius,warp.view_radius(nodes.color_model(node),0))
        data=grade_data();stack=sequence(node.id_data,[data]);focus=stack.pg_stack_entries[0].focus
        focus.family='WARP';focus.active_tone=2
        before=warp.view_radius(nodes.color_model(data),2)
        stacks.refresh(stack)
        self.assertEqual(before,warp.view_radius(nodes.color_model(data),2))
        self.assertFalse(hasattr(focus,'warp_view_ready_2'))

    def test_auto_fit_contains_interior_curves_and_marks(self):
        node=self.node();ui=node.pg_chromatic
        nodes.write_chromatic(node,dict(adaptance_a_1=5.,adaptance_b_1=-4.,web_chroma_1_0=-1.,web_scale_1_1=1.))
        model=nodes.color_model(node)
        p=warp.plot((0,0,300,300),ui,model,1);g=warp.geometry(model,1)
        self.assertTrue(all(p.inside(point) for point in warp.bounded_project(g['before'].q,g['before'].energy)[1:]))
        for before,after in (*g['contours'],*g['spokes']):
            self.assertTrue(all(p.inside(point) for point in warp.bounded_project(after.q,after.energy) if np.isfinite(point).all()))

    def test_selected_scale_rail_drag_range_speed_and_guarded_position(self):
        node=self.node();ui=node.pg_chromatic;ui.family='WARP';ui.active_tone=1
        model=nodes.color_model(node);box=geo.layout(1000,700,1,720,24,24,'WARP')
        p=warp.plot(box['ab'],ui,model,1);x,y,w,h=p.rect
        self.assertEqual(warp.scale_rects(model,1,p,1.,-1),{})
        for handle in range(6):
            ui.active_handle=handle
            rects=warp.scale_rects(model,1,p,1.,handle)
            self.assertEqual(set(rects),{handle})
            rect=rects[handle];rx,ry,rw,rh=rect
            self.assertGreaterEqual(rx,x);self.assertLessEqual(rx+rw,x+w)
            self.assertGreaterEqual(ry,y);self.assertLessEqual(ry+rh,y+h-49)
            action=color.hit(node,nodes.grading_space(node),box,(rx+rw/2,ry+rh*.25))
            field=f'web_scale_1_{handle}'
            self.assertEqual(action['fields'],(field,));self.assertTrue(action['vertical'])
            value=geo.drag_values(model.params,action['fields'],100,0,None,rect,True)
            self.assertEqual(value[field],0.)
            accumulator={field:0.}
            for delta,expected in ((rh/2,.5),(rh,1.5),(-rh/4,1.25),(-3*rh,-1.75)):
                value=geo.drag_values(model.params,action['fields'],0,delta,None,rect,True,accumulator)
                self.assertEqual(value[field],expected)
            edited=cm.model(nodes.read_tone(node),replace(model.params,**value))
            # Raw Scale preserves saturation, but its H–K guard may move the
            # displayed handle because source reference energy stays fixed.
            np.testing.assert_allclose(edited.bounded_saturation_targets(1),model.bounded_saturation_targets(1),atol=1e-12)
            edited_rect=warp.scale_rects(edited,1,p,1.,handle)[handle]
            self.assertTrue(np.isfinite(edited_rect).all())
            ui.active_handle=-1
            self.assertIsNone(warp.hit_scale(ui,model,p,(rx+rw/2,ry+rh/2),1.))

    def test_selected_scale_readout_is_signed_neutral_and_unlabeled(self):
        node=self.node();ui=node.pg_chromatic;ui.active_tone=1;ui.active_handle=3
        nodes.write_chromatic(node,dict(web_scale_1_3=-.125))
        model=nodes.color_model(node);p=warp.plot((0,0,400,400),ui,model,1)
        with patch.object(diagram,'colored_triangles'),patch.object(diagram,'lines'),patch.object(diagram,'rectangle'),patch.object(diagram,'text') as text:
            warp.draw_scales(p,model,ui,1.)
        text.assert_called_once()
        self.assertEqual(text.call_args.args[0],'-0.12')
        self.assertEqual(text.call_args.args[-1],color.theme.TEXT)

    def test_saturation_paths_break_at_singularities_and_signed_branches(self):
        from color_tools.color_core.modcam16 import State
        q=np.array([[10.,1.,0.],[10.,2.,0.],[10.,3.,0.],[10.,4.,0.],[10.,5.,0.],[10.,6.,0.],[10.,7.,0.]])
        state=State(q,np.array([4.,4.,0.,-4.,-4.,4.,4.]))
        paths=list(warp.paths(state))
        self.assertEqual([negative for _,negative in paths],[False,True,False])
        self.assertEqual([len(points) for points,_ in paths],[3,2,2])
        self.assertTrue(all(np.isfinite(points).all() for points,_ in paths))

    def test_top_controls_never_overlap_vertices_or_scale_rails(self):
        node=self.node();ui=node.pg_chromatic;ui.family='WARP'
        def intersects(a,b):
            return a[0]<b[0]+b[2] and b[0]<a[0]+a[2] and a[1]<b[1]+b[3] and b[1]<a[1]+a[3]
        for scale,width,height in ((1.,384,438),(1.,1000,700),(1.5,1600,1000)):
            box=geo.layout(width,height,scale,720,24,24,'WARP')
            for tone in range(4):
                ui.active_tone=tone
                nodes.write_chromatic(node,{f'web_hue_{tone}_{i}':90. for i in range(6)})
                model=nodes.color_model(node);p=warp.plot(box['ab'],ui,model,tone)
                controls=[box['global1'],*box['tone_buttons'].values()]
                for position in model.guarded_saturation_targets(tone):
                    px,py=p.screen(position);marker=(px-8*scale,py-8*scale,16*scale,16*scale)
                    self.assertTrue(warp.handle_visible(p,position,scale))
                    self.assertFalse(any(intersects(marker,rect) for rect in controls))
                for handle in range(6):
                    rect=warp.scale_rects(model,tone,p,scale,handle)[handle]
                    self.assertFalse(any(intersects(rect,control) for control in controls))
