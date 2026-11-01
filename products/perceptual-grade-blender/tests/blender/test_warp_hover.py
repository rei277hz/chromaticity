"""Scale hover/readout state is editor-local and never changes the Grade."""
from tests.support.session import component as _component, SessionTest, patch
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

color = _component('ui.color'); diagram = _component('ui.diagram'); warp = _component('ui.warp'); warp_view = _component('ui.warp_view'); hover_help = _component('ui.help')
pass
pass


def node(pointer):
    return SimpleNamespace(as_pointer=lambda:pointer,
        pg_chromatic=SimpleNamespace(active_tone=1,active_handle=0,family='WARP'))


class WarpHoverTests(SessionTest):
    def tearDown(self):
        warp.clear();warp_view.clear();hover_help.clear()

    def test_retired_tokens_discard_hover_view_and_help_without_native_access(self):
        owner=node(11);editor=(1,2,3)
        warp.set_rail_hover(editor,owner,1,4)
        _component('ownership').release(warp._rail_hovers[editor][0])
        valid=Mock(side_effect=AssertionError('Retired owner reached native validation'))
        warp.prune_rails({editor},valid)
        self.assertNotIn(editor,warp._rail_hovers)
        token=warp_view.begin(editor,owner,1,2.)
        _component('ownership').release(token.node_ref)
        self.assertIsNone(warp_view.radius(editor,owner,1))
        token=warp_view.begin(editor,owner,1,2.)
        _component('ownership').release(token.node_ref)
        warp_view.prune({editor},valid)
        self.assertNotIn(editor,warp_view._locks)
        region=SimpleNamespace(tag_redraw=Mock())
        window=SimpleNamespace(as_pointer=lambda:1)
        hover_help.update(window,region,(),(0,0),1.,hover_help.Help('Title',()),now=0.)
        _component('ownership').release(hover_help._states[1].region_ref)
        hover_help.poll(now=1.)
        self.assertNotIn(1,hover_help._states)
        region.tag_redraw.assert_not_called()
        valid.assert_not_called()

    def test_hover_is_local_to_editor_target_and_tone(self):
        first,second=node(11),node(12)
        self.assertTrue(warp.set_rail_hover((1,2,3),first,1,4))
        self.assertFalse(warp.set_rail_hover((1,2,3),first,1,4))
        self.assertEqual(warp.readout_handle((1,2,3),first,1,0),4)
        self.assertEqual(warp.readout_handle((1,2,3),second,1,0),0)
        self.assertEqual(warp.readout_handle((1,2,3),first,2,0),0)
        warp.set_rail_hover((2,2,3),second,1,3)
        warp.set_rail_hover((1,4,5),first,1,2)
        self.assertNotIn((1,2,3),warp._rail_hovers)
        self.assertEqual(warp.readout_handle((2,2,3),second,1,0),3)
        self.assertEqual(first.pg_chromatic.active_handle,0)

    def test_drag_priority_and_token_ownership(self):
        owner=node(11);editor=(1,2,3)
        warp.set_rail_hover(editor,owner,1,4)
        token=warp.begin_scale_drag(editor,owner,1,2)
        self.assertEqual(warp.readout_handle(editor,owner,1,0),2)
        replacement=warp.begin_scale_drag(editor,owner,1,3)
        warp.end_scale_drag(token)
        self.assertEqual(warp.readout_handle(editor,owner,1,0),3)
        warp.end_scale_drag(replacement)
        self.assertEqual(warp.readout_handle(editor,owner,1,0),4)
        warp.clear_rail_hovers(SimpleNamespace(as_pointer=lambda:1))
        self.assertEqual(warp.readout_handle(editor,owner,1,0),0)

    def test_cursor_hover_updates_readout_without_selection_or_grade_writes(self):
        owner=node(11);redraw=Mock()
        window=SimpleNamespace(as_pointer=lambda:1,
            screen=SimpleNamespace(areas=[SimpleNamespace(type='NODE_EDITOR',tag_redraw=redraw)]))
        context=SimpleNamespace(window=window,window_manager=SimpleNamespace(pg_stage='CHROMATIC'))
        box={key:(0,0,10,10) for key in ('close','linear_tab','tone_tab','color_tab','header')}
        box.update(ab=(10,10,400,400),scale=1.)
        box['_warp_editor']=(1,2,3)
        action=dict(kind='slider',handle=5,vertical=True)
        with patch.object(diagram.nodes,'editable',return_value=True),\
                patch.object(diagram.nodes,'grading_space',return_value='Linear Rec.709'),\
                patch('color_tools.perceptual_grade_blender.scopes.sampling.scope_input_status',return_value={'native':False}),\
                patch('color_tools.perceptual_grade_blender.scopes.jobs.status',return_value={'state':'ready'}),\
                patch.object(diagram,'comparison_hit',return_value=False),\
                patch.object(color,'hit',return_value=action),\
                patch.object(diagram.nodes,'write_chromatic',side_effect=AssertionError('Hover wrote Grade')):
            self.assertEqual(diagram.hover_cursor(context,owner,box,(20,20)),'SCROLL_Y')
            self.assertEqual(warp.readout_handle((1,2,3),owner,1,0),5)
            self.assertEqual(owner.pg_chromatic.active_handle,0)
            redraw.assert_called_once()
            diagram.hover_cursor(context,owner,box,(20,20))
            redraw.assert_called_once()
            diagram.hover_cursor(context,owner,box,(1,1))
            self.assertEqual(warp.readout_handle((1,2,3),owner,1,0),0)
            self.assertEqual(redraw.call_count,2)

    def test_selected_readout_and_thumb_pin_without_ramps_or_borders(self):
        owner=node(11);editor=(1,2,3)
        model=SimpleNamespace(params=SimpleNamespace(web_scale_1_0=0.))
        plot=_component('ui.color_geometry').ABPlot((0,0,400,400),-1,1,-1,1)
        positions=[]
        for value,expected_y in ((-5.,200.),(-1.,200.),(0.,240.),(1.,280.),(5.,280.)):
            model.params.web_scale_1_0=value
            with patch.object(warp,'scale_rects',return_value={0:(40,200,3,80)}),\
                    patch.object(diagram,'colored_triangles') as ramp,patch.object(diagram,'lines') as lines,\
                    patch.object(diagram,'rectangle') as rectangle,patch.object(diagram,'text') as text:
                warp.draw_scales(plot,model,owner.pg_chromatic,1.,editor=editor,node=owner)
                text.assert_called_once();ramp.assert_not_called();rectangle.assert_not_called()
                self.assertEqual(text.call_args.args[0],f'{value:+.2f}')
                self.assertEqual(text.call_args.args[-1],color.theme.TEXT)
                self.assertEqual([point[1] for point in lines.call_args.args[0]],[expected_y]*2)
                positions.append(text.call_args.args[1:3])
        self.assertTrue(all(position==positions[0] for position in positions))

    def test_scale_drag_holds_rail_placement_until_release(self):
        owner=node(11);editor=(1,2,3)
        model=SimpleNamespace(params=SimpleNamespace(web_scale_1_0=3.))
        plot=_component('ui.color_geometry').ABPlot((0,0,400,400),-1,1,-1,1)
        token=warp.begin_scale_drag(editor,owner,1,0,(40,200,3,80))
        with patch.object(warp,'scale_rects',return_value={0:(240,200,3,80)}),\
                patch.object(diagram,'lines') as lines,patch.object(diagram,'text'):
            warp.draw_scales(plot,model,owner.pg_chromatic,1.,editor=editor,node=owner)
            self.assertEqual(lines.call_args_list[0].args[0][0][0],41.5)
            warp.end_scale_drag(token)
            warp.draw_scales(plot,model,owner.pg_chromatic,1.,editor=editor,node=owner)
            self.assertEqual(lines.call_args_list[3].args[0][0][0],241.5)

    def test_prune_and_lifecycle_cleanup_release_hover_and_drag(self):
        first,second=node(11),node(12)
        warp.set_rail_hover((1,2,3),first,1,2)
        warp.begin_scale_drag((2,2,3),second,1,3)
        warp.prune_rails({(1,2,3),(2,2,3)},lambda owner:owner is first)
        self.assertFalse(warp._rail_drags)
        self.assertTrue(warp._rail_hovers)
        diagram.cleanup_hover_cursors()
        self.assertFalse(warp._rail_hovers);self.assertFalse(warp._rail_drags)

    def test_dashes_follow_continuous_screen_distance_for_dense_clipped_paths(self):
        source=tuple((x,50.) for x in [i*.5-10 for i in range(241)])
        for rect,expected_count,expected_end in (
            ((0.,0.,100.,100.),10,95.),
            ((0.,0.,200.,100.),20,195.),
        ):
            chart=_component('ui.color_geometry').Plot(rect,0.,100.,0.,100.)
            with self.subTest(rect=rect),patch.object(diagram,'lines') as lines:
                diagram.curve(chart,source,(1.,1.,1.,1.),2.,dashed=True)
                coords=lines.call_args.args[0]
                spans=[]
                for a,b in zip(coords[::2],coords[1::2]):
                    self.assertEqual((a[1],b[1]),(50.,50.))
                    if spans and abs(spans[-1][1]-a[0])<1e-8:
                        spans[-1]=(spans[-1][0],b[0])
                    else:spans.append((a[0],b[0]))
                self.assertEqual(len(spans),expected_count)
                self.assertEqual(spans[0],(0.,5.))
                self.assertEqual(spans[-1],(expected_end-5.,expected_end))
                for start,end in spans:
                    self.assertAlmostEqual(end-start,5.)
                for (_,end),(start,_) in zip(spans,spans[1:]):
                    self.assertAlmostEqual(start-end,5.)
                self.assertEqual(lines.call_args.args[2],2.)

        # Clipping advances the existing phase rather than starting a fresh
        # dash at the canvas edge; a degenerate clip must not divide by zero.
        chart=_component('ui.color_geometry').Plot((0.,0.,100.,100.),0.,100.,0.,100.)
        with patch.object(diagram,'lines') as lines:
            diagram.curve(chart,((-7.,50.),(107.,50.)),(1.,1.,1.,1.),dashed=True)
            coords=lines.call_args.args[0]
            for actual,expected in zip(coords[:2]+coords[-2:],[(3.,50.),(8.,50.),(93.,50.),(98.,50.)]):
                for value,target in zip(actual,expected):self.assertAlmostEqual(value,target)
            diagram.curve(chart,((-1.,1.),(1.,-1.)),(1.,1.,1.,1.),dashed=True)
            self.assertEqual(lines.call_args.args[0],[])
            diagram.curve(chart,((50.,50.),(50.,50.)),(1.,1.,1.,1.),dashed=True)
            self.assertEqual(lines.call_args.args[0],[])


if __name__=='__main__':unittest.main()
