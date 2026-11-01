"""Warp geometry uses the export H–K guard without repairing scope samples twice."""
from tests.support.session import component as _component, SessionTest, patch
pass
import bpy
import numpy as np
nodes = _component('graph.nodes')
from color_tools.perceptual_grade_core.model.hk_guard import guard
diagram = _component('ui.diagram'); warp = _component('ui.warp')
from tests.support.blender import BlenderTest


class GuardedWarpTests(BlenderTest):
    def node(self):
        tree=bpy.data.node_groups.new('Guarded Warp','CompositorNodeTree')
        node=nodes.create_grade(tree)
        node.pg_chromatic.family='WARP';node.pg_chromatic.active_tone=1
        node.pg_chromatic.active_handle=0
        return node

    def test_display_guard_uses_each_source_energy_after_full_warp(self):
        node=self.node()
        nodes.write_chromatic(node,dict(adaptance_a_1=8.,adaptance_b_1=-5.,
            web_chroma_1_0=3.,web_scale_1_0=.4,web_hue_1_0=5.))
        model=nodes.color_model(node);g=warp.geometry(model,1)
        raw=model.warp_targets(1)
        expected,e=guard(raw.q,raw.energy,g['before'].energy)
        np.testing.assert_allclose(g['after'].q,expected,rtol=1e-13,atol=1e-13)
        np.testing.assert_allclose(g['after'].energy,e,rtol=1e-13,atol=1e-13)
        self.assertLess(raw.energy[1],0.)
        self.assertGreater(g['after'].energy[1],0.)
        self.assertFalse(np.array_equal(g['after'].q,raw.q))
        height=model.web.geometry.anchors[1]
        for before,after in (*g['contours'],*g['spokes']):
            raw=model.warp_state(before,height)
            expected,e=guard(raw.q,raw.energy,before.energy)
            np.testing.assert_allclose(after.q,expected,rtol=1e-13,atol=1e-13)
            np.testing.assert_allclose(after.energy,e,rtol=1e-13,atol=1e-13)
            self.assertTrue(np.all(after.energy>=0))
        np.testing.assert_allclose(g['before'].q[1:],model.web.geometry.q[1],atol=0.)

    def test_hit_and_selected_rail_use_guarded_final_handle(self):
        node=self.node();ui=node.pg_chromatic
        nodes.write_chromatic(node,dict(web_chroma_1_0=3.,web_scale_1_0=-1.))
        model=nodes.color_model(node);p=warp.plot((0,0,500,500),ui,model,1)
        guarded=model.guarded_saturation_targets(1)[1]
        self.assertGreater(np.linalg.norm(guarded-model.bounded_saturation_targets(1)[1]),.05)
        action=warp.hit(ui,model,p,p.screen(guarded),1.)
        self.assertEqual(action['handle'],0)
        np.testing.assert_array_equal(action['target'],guarded)
        rect=warp.scale_rects(model,1,p,1.,0)[0]
        self.assertTrue(np.isfinite(rect).all())

    def test_contextual_rim_requires_active_selected_crossing_in_same_editor(self):
        node=self.node();other=self.node();model=nodes.color_model(node)
        editor=(1,2,3);action=dict(tone=1,handle=0,rim_active=False)
        token=warp.begin_drag(editor,node,action)
        self.assertIsNone(warp.active_rim_radius(editor,node,model,1,0))
        action['rim_active']=True
        radius=warp.active_rim_radius(editor,node,model,1,0)
        self.assertAlmostEqual(radius,model.guard_rim_radius(1,0))
        self.assertGreater(radius,0.);self.assertLess(radius,1.)
        for owner,tone,handle,key in ((other,1,0,editor),(node,2,0,editor),
                (node,1,1,editor),(node,1,0,(1,4,5)),(node,1,-1,editor)):
            self.assertIsNone(warp.active_rim_radius(key,owner,model,tone,handle))
        replacement=warp.begin_drag(editor,node,dict(tone=1,handle=0,rim_active=True,rim_radius=.75))
        warp.end_drag(token)
        self.assertEqual(warp.active_rim_radius(editor,node,model,1,0),.75)
        warp.end_drag(replacement)
        self.assertIsNone(warp.active_rim_radius(editor,node,model,1,0))

    def test_rim_draw_is_temporary_and_samples_are_passed_through_once(self):
        node=self.node();ui=node.pg_chromatic;model=nodes.color_model(node)
        p=warp.plot((0,0,400,400),ui,model,1);editor=(1,2,3)
        samples=[];action=dict(tone=1,handle=0,rim_active=True,rim_radius=.75)
        token=warp.begin_drag(editor,node,action)
        with patch.object(diagram,'curve') as curve,patch.object(diagram,'rectangle'),\
                patch.object(diagram,'lines'),patch.object(diagram,'text'),patch.object(diagram,'triangles'):
            warp.draw(p,model,ui,1.,samples=samples.append,editor=editor,node=node)
            self.assertEqual(samples,[p])
            self.assertEqual(len(curve.call_args_list),11)
            points=np.asarray(curve.call_args_list[0].args[1])
            np.testing.assert_allclose(np.linalg.norm(points,axis=-1),.75,atol=3e-16)
            warp.end_drag(token);curve.reset_mock()
            warp.draw(p,model,ui,1.,editor=editor,node=node)
            self.assertEqual(len(curve.call_args_list),10)

    def test_contextual_rim_prunes_with_editor_and_target_lifecycle(self):
        first=self.node();second=self.node();action=dict(tone=1,handle=0,rim_active=True)
        warp.begin_drag((1,2,3),first,action)
        warp.begin_drag((1,4,5),second,action)
        warp.prune_rails({(1,2,3),(1,4,5)},lambda owner:owner is first)
        self.assertEqual(set(warp._dot_drags),{(1,2,3)})
        warp.prune_rails(set(),lambda owner:True)
        self.assertFalse(warp._dot_drags)
        warp.begin_drag((1,2,3),first,action)
        warp.clear();self.assertFalse(warp._dot_drags)
