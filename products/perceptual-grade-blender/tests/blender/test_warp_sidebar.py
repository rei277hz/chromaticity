"""All Warp controls are visible; absolute hue adapts existing stored deltas."""
from tests.support.session import component as _component, SessionTest, patch
import math
from types import SimpleNamespace
pass

import bpy

nodes = _component('graph.nodes'); editing = _component('graph.editing')
panel = _component('ui.panel')
from tests.support.blender import BlenderTest,sequence


class RecordingLayout:
    def __init__(self):
        self.properties=[]
        self.labels=[]
        self.operators=[]
        self.box_count=0

    def row(self,**_kwargs):return self
    def box(self):
        self.box_count+=1
        return self
    def prop(self,values,name,**kwargs):self.properties.append((values,name,kwargs))
    def label(self,**kwargs):self.labels.append(kwargs['text'])
    def operator(self,name,**_kwargs):self.operators.append(name)


class WarpSidebarTests(BlenderTest):
    def node(self):
        tree=bpy.data.node_groups.new('Warp sidebar','CompositorNodeTree')
        return nodes.create_grade(tree)

    def test_all_controls_are_always_visible_without_selectors(self):
        node=self.node();node.pg_chromatic.family='WARP'
        expected={'sidebar_'+name for name in panel.color_fields('WARP')}
        for active_tone,active_handle in ((0,-1),(3,5)):
            node.pg_chromatic.active_tone=active_tone
            node.pg_chromatic.active_handle=active_handle
            layout=RecordingLayout()
            with patch.object(nodes,'active_grade',return_value=node):
                panel.PG_PT_chromatic.draw(SimpleNamespace(layout=layout),bpy.context)
            shown=[name for _,name,_ in layout.properties if name.startswith('sidebar_')]
            self.assertEqual(set(shown),expected)
            self.assertEqual(len(shown),len(expected))
            self.assertEqual(layout.box_count,4)
            self.assertEqual(layout.operators,['perceptual_grade.reset_chromatic'])
            self.assertFalse(hasattr(panel,'PG_OT_warp_select'))
            for label in 'RYGCBM':self.assertEqual(layout.labels.count(label),4)

    def test_absolute_hue_is_pre_adaptance_and_tracks_raw_animation_values(self):
        node=self.node();values=nodes.grades.data_owner(node).pg_chromatic
        model=nodes.color_model(node)
        for tone in range(4):
            for handle in range(6):
                field=f'web_hue_{tone}_{handle}'
                origin=math.degrees(float(model.web.geometry.angles[tone,handle]))
                self.assertAlmostEqual(getattr(values,'sidebar_'+field),origin%360.,places=4)
        nodes.write_chromatic(node,dict(web_hue_1_0=3.,adaptance_a_1=5.,web_scale_1_0=.5))
        origin=panel.warp_hue_origin(node,1,0)
        self.assertAlmostEqual(values.sidebar_web_hue_1_0,(origin+3.)%360.,places=4)
        nodes.write_chromatic(node,dict(web_hue_1_0=-2.))
        self.assertAlmostEqual(values.sidebar_web_hue_1_0,(origin-2.)%360.,places=4)

    def test_hue_wrap_selects_nearest_stored_lift(self):
        node=self.node()
        for tone in range(4):
            for handle in range(6):
                origin=panel.warp_hue_origin(node,tone,handle)
                for current in (-359.,-12.,12.,359.):
                    # Exercise source-hue lookup even with an invalid saved
                    # web, without scheduling a bake of that invalid state.
                    with patch.object(nodes.grades,'changed'):
                        nodes.write_chromatic(node,{f'web_hue_{tone}_{handle}':current})
                    for hue in (0.,360.,.5,359.5):
                        delta=panel.warp_hue_delta(node,tone,handle,hue)
                        self.assertGreaterEqual(delta,-360.)
                        self.assertLessEqual(delta,360.)
                        error=((origin+delta-hue+180.)%360.)-180.
                        self.assertAlmostEqual(error,0.,places=10)
                        other=[delta+turn*360. for turn in (-1,1) if -360.<=delta+turn*360.<=360.]
                        for choice in other:self.assertLessEqual(abs(delta-current),abs(choice-current)+1e-10)
                    self.assertEqual(panel.warp_hue_delta(node,tone,handle,0.),
                                     panel.warp_hue_delta(node,tone,handle,360.))

    def test_unchanged_float32_hue_display_preserves_exact_raw_values(self):
        node=self.node();values=nodes.grades.data_owner(node).pg_chromatic
        for tone in range(4):
            for handle in range(6):
                field=f'web_hue_{tone}_{handle}'
                display=getattr(values,'sidebar_'+field)
                self.assertEqual(panel.warp_hue_delta(node,tone,handle,display),getattr(values,field))

    def test_inline_edits_validate_the_full_web_and_reject_hue_crossings(self):
        node=self.node();values=nodes.grades.data_owner(node).pg_chromatic
        before=nodes.read_chromatic(node)
        values.sidebar_web_hue_1_0=values.sidebar_web_hue_1_0
        values.sidebar_web_scale_1_0=0.
        self.assertEqual(nodes.read_chromatic(node),before)
        self.assertIsNone(node.pg_grade)
        # The red corner may move within its sector, but not past yellow.
        values.sidebar_web_hue_1_0=(panel.warp_hue_origin(node,1,1)+10.)%360.
        self.assertEqual(nodes.read_chromatic(node),before)
        values.sidebar_adaptance_a_1=1.e6
        self.assertEqual(nodes.read_chromatic(node),before)
        values.sidebar_web_hue_1_0=(panel.warp_hue_origin(node,1,0)+2.)%360.
        self.assertAlmostEqual(nodes.read_chromatic(node).web_hue_1_0,2.,places=4)
        self.assertIsNotNone(node.pg_grade)

    def test_inline_scale_uses_paired_compensation_and_keeps_later_darkening(self):
        warp_scale = _component('ui.warp_scale')
        node=self.node()
        nodes.write_chromatic(node,dict(web_chroma_1_0=3.))
        model=nodes.color_model(node)
        expected=warp_scale.edit(model,1,0,4.)
        self.assertTrue(expected)
        values=nodes.grades.data_owner(node).pg_chromatic
        values.sidebar_web_scale_1_0=4.
        self.assertEqual(values.web_scale_1_0,4.)
        self.assertLess(values.web_chroma_1_0,3.)
        self.assertAlmostEqual(values.web_chroma_1_0,expected['web_chroma_1_0'],places=6)
        reduced=values.web_chroma_1_0
        values.sidebar_web_scale_1_0=-8.
        self.assertEqual(values.web_chroma_1_0,reduced)
        self.assertEqual(values.web_scale_1_0,-8.)

    def test_native_scale_gesture_freezes_baseline_retraces_and_cancels_pair(self):
        warp_edit = _component('ui.warp_edit'); warp_scale = _component('ui.warp_scale')
        node=self.node();nodes.write_chromatic(node,dict(web_chroma_1_0=3.))
        before=nodes.read_chromatic(node)
        expected=warp_scale.edit(nodes.color_model(node),1,0,4.)
        transaction=warp_edit.begin(node)
        values=nodes.grades.data_owner(node).pg_chromatic
        values.sidebar_web_scale_1_0=2.
        values.sidebar_web_scale_1_0=4.
        self.assertAlmostEqual(values.web_chroma_1_0,expected['web_chroma_1_0'],places=6)
        values.sidebar_web_scale_1_0=0.
        self.assertEqual(nodes.read_chromatic(node),before)
        values.sidebar_web_scale_1_0=4.
        warp_edit.defer_finish(transaction,False)
        # Native RNA may attempt its own field-only restoration after Esc.
        # That must not re-enter compensation or lose the companion Chroma.
        values.sidebar_web_scale_1_0=0.
        warp_edit.flush()
        self.assertEqual(nodes.read_chromatic(node),before)
        self.assertNotIn(transaction.key,warp_edit._edits)

    def test_native_first_edit_follows_new_grade_owner_and_cancel_removes_it(self):
        warp_edit = _component('ui.warp_edit')
        node=self.node();self.assertIsNone(node.pg_grade)
        before=nodes.read_chromatic(node)
        transaction=warp_edit.begin(node)
        node.pg_chromatic.sidebar_web_chroma_1_0=.25
        grade=node.pg_grade
        self.assertIsNotNone(grade)
        grade.pg_chromatic.sidebar_web_chroma_1_0=.5
        self.assertEqual(transaction.field,'web_chroma_1_0')
        self.assertEqual(grade.pg_chromatic.web_chroma_1_0,.5)
        warp_edit.finish(transaction,False)
        self.assertIsNone(node.pg_grade)
        self.assertEqual(nodes.read_chromatic(node),before)

    def test_native_stack_shared_grade_edit_uses_one_pair_and_raw_autokeys(self):
        warp_edit = _component('ui.warp_edit')
        node=self.node();nodes.write_chromatic(node,dict(web_chroma_1_0=3.))
        shared=nodes.create_grade(node.id_data);shared.pg_grade=node.pg_grade
        stack=sequence(node.id_data,[node.pg_grade,node.pg_grade])
        stack.pg_stack_entries[1].direction='INVERSE'
        target=editing.Target(stack,stack.pg_stack_entries[1])
        context=SimpleNamespace(window_manager=SimpleNamespace(pg_diagram_enabled=False),
                                scene=bpy.context.scene,window=SimpleNamespace(as_pointer=lambda:4242))
        context.scene.tool_settings.use_keyframe_insert_auto=True
        transaction=warp_edit.begin(target,context)
        with patch.object(nodes,'keyframe_chromatic') as keyframe:
            node.pg_grade.pg_chromatic.sidebar_web_scale_1_0=4.
            keyframe.assert_not_called()
            warp_edit.finish(transaction)
        self.assertEqual({call.args[1] for call in keyframe.call_args_list},
                         {'web_scale_1_0','web_chroma_1_0'})
        self.assertTrue(all(call.args[0] is target for call in keyframe.call_args_list))
        self.assertEqual(nodes.read_chromatic(node),nodes.read_chromatic(shared))
        self.assertEqual(nodes.read_chromatic(target),nodes.read_chromatic(node))
        self.assertEqual(target.pg_chromatic.active_tone,1)
        self.assertEqual(target.pg_chromatic.active_handle,0)

    def test_release_finishes_after_native_callback_when_overlay_is_closed(self):
        warp_edit = _component('ui.warp_edit')
        node=self.node()
        context=SimpleNamespace(window=SimpleNamespace(as_pointer=lambda:4243),
                                window_manager=SimpleNamespace(pg_diagram_enabled=False),scene=bpy.context.scene)
        with patch.object(warp_edit,'sidebar_node',return_value=(node,context)):
            warp_edit.observe_event(context,SimpleNamespace(type='LEFTMOUSE',value='PRESS'))
            transaction=warp_edit._edits[4243]
            node.pg_chromatic.sidebar_web_chroma_1_0=.125
            warp_edit.observe_event(context,SimpleNamespace(type='LEFTMOUSE',value='RELEASE'))
            self.assertIn(4243,warp_edit._edits)
            node.pg_grade.pg_chromatic.sidebar_web_chroma_1_0=.25
            warp_edit.flush()
        self.assertNotIn(4243,warp_edit._edits)
        self.assertEqual(nodes.read_chromatic(node).web_chroma_1_0,.25)
        self.assertEqual(transaction.touched,{'web_chroma_1_0'})

    def test_text_entry_keeps_snapshot_after_click_release_until_enter_callback(self):
        warp_edit = _component('ui.warp_edit')
        node=self.node();nodes.write_chromatic(node,dict(web_chroma_1_0=3.))
        context=SimpleNamespace(window=SimpleNamespace(as_pointer=lambda:4244),
                                window_manager=SimpleNamespace(pg_diagram_enabled=False),scene=bpy.context.scene)
        context.scene.tool_settings.use_keyframe_insert_auto=True
        with patch.object(warp_edit,'sidebar_node',return_value=(node,context)):
            warp_edit.observe_event(context,SimpleNamespace(type='LEFTMOUSE',value='DOUBLE_CLICK'))
            edit=warp_edit._edits[4244]
            warp_edit.observe_event(context,SimpleNamespace(type='LEFTMOUSE',value='RELEASE'))
            warp_edit.flush()
            self.assertIs(warp_edit._edits[4244],edit)
            with patch.object(nodes,'keyframe_chromatic') as keyframe:
                warp_edit.observe_event(context,SimpleNamespace(type='RET',value='PRESS'))
                # Number text is applied by Blender after the observer sees Enter.
                node.pg_grade.pg_chromatic.sidebar_web_scale_1_0=4.
                self.assertEqual({call.args[1] for call in keyframe.call_args_list},
                                 {'web_scale_1_0','web_chroma_1_0'})
                warp_edit.flush()
            self.assertEqual(len(keyframe.call_args_list),2)
        self.assertNotIn(4244,warp_edit._edits)

    def test_clear_on_undo_discards_snapshot_without_replaying_values(self):
        warp_edit = _component('ui.warp_edit')
        node=self.node();nodes.write_chromatic(node,dict(web_chroma_1_0=3.))
        warp_edit.begin(node)
        node.pg_grade.pg_chromatic.sidebar_web_scale_1_0=4.
        # Simulate the undo system installing a different exact raw state.
        nodes.write_chromatic(node,dict(web_scale_1_0=-1.,web_chroma_1_0=2.))
        restored=nodes.read_chromatic(node)
        warp_edit.clear()
        self.assertEqual(nodes.read_chromatic(node),restored)
        self.assertFalse(warp_edit._edits)

    def test_real_undo_redo_restores_compensated_pair_and_raw_keyframes(self):
        warp_edit = _component('ui.warp_edit')
        node=self.node();node.id_data.use_fake_user=True
        tree_name=node.id_data.name;node_name=node.name
        def current():return bpy.data.node_groups[tree_name].nodes[node_name]
        def keyed_paths(node):
            animation=node.pg_grade.animation_data
            strip=animation.action.layers[0].strips[0]
            return {curve.data_path for curve in strip.channelbag(animation.action_slot).fcurves}
        nodes.write_chromatic(node,dict(web_chroma_1_0=3.))
        before=nodes.read_chromatic(node)
        bpy.ops.ed.undo_push(message='Before Warp Scale')
        context=SimpleNamespace(window_manager=SimpleNamespace(pg_diagram_enabled=False),
                                scene=bpy.context.scene,window=SimpleNamespace(as_pointer=lambda:4245))
        context.scene.tool_settings.use_keyframe_insert_auto=True
        transaction=warp_edit.begin(node,context)
        node.pg_grade.pg_chromatic.sidebar_web_scale_1_0=4.
        after=nodes.read_chromatic(node)
        self.assertNotEqual(after,before)
        warp_edit.defer_finish(transaction)
        action=node.pg_grade.animation_data.action
        self.assertIsNotNone(action)
        self.assertEqual(keyed_paths(node),{'pg_chromatic.web_scale_1_0','pg_chromatic.web_chroma_1_0'})
        # Native number buttons push undo after processing the release/Enter
        # callback; queued settlement must not add state after that snapshot.
        bpy.ops.ed.undo_push(message='Warp Scale')
        warp_edit.flush()
        bpy.ops.ed.undo()
        self.assertEqual(nodes.read_chromatic(current()),before)
        self.assertFalse(warp_edit._edits)
        bpy.ops.ed.redo()
        self.assertEqual(nodes.read_chromatic(current()),after)
        self.assertIsNotNone(current().pg_grade.animation_data.action)
        self.assertEqual(keyed_paths(current()),{'pg_chromatic.web_scale_1_0','pg_chromatic.web_chroma_1_0'})

    def test_adapters_delegate_raw_edits_and_preserve_storage_paths(self):
        warp_edit = _component('ui.warp_edit')
        node=self.node();values=nodes.grades.data_owner(node).pg_chromatic
        calls=[]
        def edit(owner,field,value):
            calls.append((owner,field,value))
            nodes.write_chromatic(owner,{field:value})
        with patch.object(warp_edit,'edit_sidebar',side_effect=edit):
            values.sidebar_web_chroma_1_0=.125
            values.sidebar_web_scale_1_0=.25
            values.sidebar_adaptance_a_1=.5
            values.sidebar_adaptance_half_saturation=.4
            expected=panel.warp_hue_value(node,1,0)+2.
            values.sidebar_web_hue_1_0=expected
        self.assertEqual([field for _,field,_ in calls],
                         ['web_chroma_1_0','web_scale_1_0','adaptance_a_1','adaptance_half_saturation','web_hue_1_0'])
        self.assertAlmostEqual(values.web_hue_1_0,2.,places=4)
        self.assertAlmostEqual(values.web_chroma_1_0,.125)
        self.assertAlmostEqual(values.web_scale_1_0,.25)
        self.assertTrue(all(not name.startswith('sidebar_') for name in values.keys()))
        for name in panel.color_fields('WARP'):
            prop=values.bl_rna.properties['sidebar_'+name]
            self.assertFalse(prop.is_animatable)
            self.assertTrue(prop.is_skip_save)
        for name in ('web_scale_1_0','sidebar_web_scale_1_0'):
            prop=values.bl_rna.properties[name]
            self.assertEqual((prop.hard_min,prop.hard_max),(-8.,8.))
            self.assertEqual((prop.soft_min,prop.soft_max),(-1.,1.))
            self.assertEqual(prop.precision,2)
