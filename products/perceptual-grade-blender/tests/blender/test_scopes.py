"""Real Blender interaction/publication while an independent scope worker runs."""
from tests.support.session import component as _component, SessionTest, patch
from collections import OrderedDict
from contextlib import contextmanager,ExitStack
from dataclasses import replace
from threading import Event,current_thread,main_thread
from types import MappingProxyType,SimpleNamespace
import time
import unittest
from unittest.mock import Mock
import bpy
import numpy as np
from color_tools import perceptual_grade_blender as addon
from color_tools.perceptual_grade_blender.integration.components import Component,component_items
nodes = _component('graph.nodes'); lut = _component('graph.lut'); editing = _component('graph.editing'); grades = _component('graph.grades'); scheduler = _component('graph.scheduler')
from color_tools.perceptual_grade_core.model import lut as cubes
from color_tools.perceptual_grade_core.model import linear as linear_model
sampling = _component('scopes.sampling'); jobs = _component('scopes.jobs'); reference = _component('scopes.reference'); color = _component('scopes.color')
diagram = _component('ui.diagram')
from color_tools.perceptual_grade_core.model import scope_analysis, scope_color as color_math, scope_reference as reference_math
from tests.support.scope import ScopeExecutor
from tests.support.blender import BlenderTest,wait_for_scopes,grade_data,sequence


class PhasedScopeResult:
    """Deliver a real helper's visual and terminal statistics independently."""
    def __init__(self,result,visual_gate,statistics_gate):
        self.result_handle=result
        self.visual_gate=visual_gate
        self.statistics_gate=statistics_gate
        self.cancel=Mock(wraps=result.cancel)

    def preview(self):
        return self.result_handle.preview() if self.visual_gate.is_set() else None

    def retired(self):
        return self.statistics_gate.is_set() and self.result_handle.retired()

    def done(self):
        return self.retired()

    def result(self,timeout=None):
        if not self.statistics_gate.is_set():
            raise AssertionError('Statistics read before their completion receipt')
        return self.result_handle.result(timeout=timeout)


class SaturationScopeTests(SessionTest):
    """Scopes measure the already-exported signal and retain the selected IDs."""


    def test_exported_rgb_paths_publish_saturation_without_reapplying_guards(self):
        from color_tools.perceptual_grade_core.model import statistics
        from color_tools.perceptual_grade_core.model.saturation import bounded_project
        q=np.array([[[20.,1.,2.],[30.,2.,4.],[10.,1.,1.],[-7.,-2.,1.]]])
        ja=np.array([[10.,20.,0.,-5.]])
        expected=np.array([[[.1,.2],[.1,.2],[np.nan,np.nan],[-.4,.2]]])
        ids=np.array([0,1,3]);weights=np.ones((1,4))
        for source in ('grade_output_rgb','stack_output_rgb'):
            with self.subTest(source=source):
                rgb=np.arange(12.).reshape(1,4,3)
                tone=SimpleNamespace(space='ACEScg',reference=203.,plot_max=1.,
                                     cones=Mock(return_value=rgb))
                model=SimpleNamespace(tone=tone)
                prepared=SimpleNamespace(apply=Mock(side_effect=AssertionError('RGB was evaluated twice')))
                selected=dict(weights=weights,sample_indices=ids,_input=dict(prepared=prepared))
                base={'model':SimpleNamespace(space='ACEScg'),source:rgb}
                with patch.object(color_math,'selection',return_value=selected), \
                     patch.object(color_math,'encode_cones',return_value=SimpleNamespace(q=q,ja=ja)), \
                     patch.object(color_math,'vectorscope',return_value=None):
                    result=color_math.evaluate(base,None,'ACEScg',0,selected_model=model)
                tone.cones.assert_called_once_with(rgb)
                np.testing.assert_allclose(result['saturation'],expected,equal_nan=True)
                np.testing.assert_allclose(result['bounded_saturation'],bounded_project(q,ja*np.abs(ja)))
                np.testing.assert_allclose(np.linalg.norm(result['bounded_saturation'][0,2]),1.)
                np.testing.assert_array_equal(result['after_energy'],ja*np.abs(ja))
                self.assertEqual(result['saturation_excluded'],1)
                self.assertIs(result['neutral']['sample_indices'],ids)
                direct=statistics.describe_sample(expected.reshape(-1,2)[ids],min_std=0.)
                for key in ('center','covariance','ellipse_covariance'):
                    np.testing.assert_array_equal(result['neutral'][key],direct[key])
                self.assertNotIn('prepared',result['_input'])

    def test_external_signal_has_bounded_zero_energy_and_signed_samples(self):
        from color_tools.perceptual_grade_core.model.saturation import bounded_project
        rgb=np.ones((1,3,3));rgba=np.concatenate((rgb,np.ones((1,3,1))),axis=-1)
        q=np.array([[[20.,1.,2.],[10.,1.,1.],[-7.,-2.,1.]]]);ja=np.array([[10.,0.,-5.]])
        model=SimpleNamespace(space='ACEScg',reference=203.,plot_max=1.,cones=Mock(return_value=rgb))
        with patch.object(reference_math.scopes,'apply_chain',return_value=rgb), \
             patch.object(reference_math,'encode_cones',return_value=SimpleNamespace(q=q,ja=ja)), \
             patch.object(reference_math.scopes,'distribution',return_value=None), \
             patch.object(reference_math.cs,'vectorscope',return_value=None):
            result=reference_math.evaluate(rgba,(),'ACEScg',dict(model=model),np.eye(3))
        np.testing.assert_allclose(result['bounded_saturation'],bounded_project(q,ja*np.abs(ja)))
        self.assertTrue(np.isnan(result['saturation'][0,1]).all())
        np.testing.assert_allclose(np.linalg.norm(result['bounded_saturation'][0,1]),1.)

    def test_neutral_overlay_compactifies_magnified_statistics_before_drawing(self):
        ui_color = _component('ui.color')
        pass
        from color_tools.perceptual_grade_core.model import statistics
        from color_tools.perceptual_grade_core.model.saturation import bounded_from_linear
        data=np.r_[np.random.default_rng(193).normal((.1,.05),.01,(80,2)),
                   np.tile((.7,-.4),(8,1))]
        stats=statistics.describe_sample(data,min_std=0.)
        self.assertGreater(np.linalg.norm(stats['center']-data.mean(axis=0)),.04)
        p=_component('ui.color_geometry').ABPlot((0,0,200,200),-1,1,-1,1)
        for scale in (1.,1.5):
            with self.subTest(scale=scale),patch.object(diagram,'curve') as curves, \
                 patch.object(diagram,'circle') as circles:
                ui_color.neutral_stats(p,stats,scale,False)
            expected=bounded_from_linear(5*statistics.ellipse(stats,min_radius=0.))
            np.testing.assert_allclose(curves.call_args_list[0].args[1],np.r_[expected,expected[:1]])
            circles.assert_not_called()
            self.assertEqual(curves.call_count,3)
            # Both cross strokes meet at the robust center and stay ten scaled
            # screen pixels wide after compactification.
            center=bounded_from_linear(5*stats['center'])
            for stroke in curves.call_args_list[1:]:
                ends=np.asarray(stroke.args[1])
                np.testing.assert_allclose(ends.mean(axis=0),center)
                np.testing.assert_allclose(np.linalg.norm(np.subtract(p.screen(ends[1]),p.screen(ends[0]))),10*scale)

    def test_degenerate_neutral_region_keeps_three_pixel_display_floor(self):
        ui_color = _component('ui.color')
        pass
        from color_tools.perceptual_grade_core.model import statistics
        data=np.zeros((8,2))
        stats=statistics.describe_sample(data,min_std=0.)
        plot=_component('ui.color_geometry').ABPlot((0,0,200,200),-1,1,-1,1)
        with patch.object(diagram,'curve') as curves,patch.object(diagram,'circle'):
            ui_color.neutral_stats(plot,stats,1.,False)
        points=np.asarray(curves.call_args_list[0].args[1])[:-1]
        screen=np.asarray([plot.screen(point) for point in points])
        np.testing.assert_allclose(np.linalg.norm(screen-plot.screen((0.,0.)),axis=-1),3.,atol=1e-8)

    def test_pending_fit_draws_latest_cloud_and_retained_ellipse(self):
        ui_color = _component('ui.color'); warp = _component('ui.warp'); warp_samples = _component('ui.warp_samples'); color_geometry = _component('ui.color_geometry')
        stats=object();pixels=np.zeros((1,1,2,2),dtype=np.uint8)
        selected=dict(neutral=stats,statistics_status='pending',_base={},
            _warp_clouds=(dict(pixels=pixels),),_visual_request='new-visual',
            _statistics_request='previous-fit')
        node=SimpleNamespace(pg_chromatic=SimpleNamespace(family='WARP',active_tone=0))
        box=color_geometry.layout(1000,750,1.,720,24,24,'WARP')
        plot=color_geometry.ABPlot(box['ab'],-1.2,1.2,-1.2,1.2)
        with ExitStack() as stack:
            stack.enter_context(patch.object(ui_color,'state',return_value=(None,None,None,plot,selected,'')))
            for name in ('draw_scopes','draw_scope_status','draw_slider'):
                stack.enter_context(patch.object(ui_color,name))
            for name in ('rectangle','text','draw_header','draw_footer'):
                stack.enter_context(patch.object(diagram,name))
            stack.enter_context(patch.object(reference,'selected',return_value=None))
            stack.enter_context(patch.object(warp,'draw',side_effect=lambda p,m,ui,s,**kw:kw['samples'](p)))
            stack.enter_context(patch.object(warp,'draw_scales'))
            draw_cloud=stack.enter_context(patch.object(warp_samples,'draw'))
            draw_fit=stack.enter_context(patch.object(ui_color,'neutral_stats'))
            ui_color.draw_board(None,node,None,None,box)
        draw_cloud.assert_called_once_with(plot,selected,None,1.)
        draw_fit.assert_called_once_with(plot,stats,1.,False)


class StackWhiteDragMathTests(BlenderTest):
    """The whole-Stack scope steers source white through ordered Stage-1 maps."""

    def test_composed_stage1_forward_inverse_and_mixed_directions(self):
        white_drag = _component('ui.white_drag')
        first=np.array([[1.1,.08,0.],[0.,.9,.04],[.02,0.,1.05]])
        second=np.array([[.95,0.,.06],[.03,1.2,0.],[0.,.02,.88]])
        third=np.array([[1.,.04,.01],[.02,1.,0.],[0.,.03,1.]])

        np.testing.assert_allclose(
            white_drag.compose_stage1([first,second],['FORWARD','FORWARD']),
            second@first,rtol=1e-13,atol=1e-13)
        np.testing.assert_allclose(
            white_drag.compose_stage1([first,second],['FORWARD','INVERSE']),
            np.linalg.inv(second)@first,rtol=1e-13,atol=1e-13)
        np.testing.assert_allclose(
            white_drag.compose_stage1([first,second,third],['INVERSE','FORWARD','INVERSE']),
            np.linalg.inv(third)@second@np.linalg.inv(first),rtol=1e-13,atol=1e-13)

    def test_repeated_grade_in_opposite_directions_cancels_in_stack_order(self):
        white_drag = _component('ui.white_drag')
        shared=np.array([[1.05,.03,0.],[0.,.97,.02],[.01,0.,1.1]])
        np.testing.assert_allclose(
            white_drag.compose_stage1([shared,shared],['FORWARD','INVERSE']),
            np.eye(3),rtol=1e-13,atol=1e-13)
        # The same shared Grade appears again after another transform. The
        # repeated occurrence must be composed at each position, not deduped.
        other=np.array([[.91,0.,.04],[.02,1.08,0.],[0.,.01,1.03]])
        expected=np.linalg.inv(shared)@other@shared
        np.testing.assert_allclose(
            white_drag.compose_stage1([shared,other,shared],['FORWARD','FORWARD','INVERSE']),
            expected,rtol=1e-13,atol=1e-13)

    def test_stack_vectorscope_has_no_predicted_orange_overlay(self):
        diagram = _component('ui.diagram')
        import inspect
        source=inspect.getsource(diagram.draw_board)
        self.assertNotIn('_visible_stack_scope_preview',source)
        self.assertFalse(hasattr(diagram,'_stack_scope_previews'))

    def _stack_drag(self,directions,edited_occurrences,matrices=None,rgb=None):
        white_drag = _component('ui.white_drag')
        tree=bpy.data.node_groups.new('Composed white drag','CompositorNodeTree')
        node=nodes.create_grade(tree);stack=sequence(tree,[grades.ensure(node)])
        space=nodes.grading_space(node);params=nodes.read_parameters(node)
        authoritative=np.asarray(nodes.grades.matrix(node),dtype=float)
        left=np.eye(3);right=np.eye(3)
        if matrices is None:matrices=[np.eye(3) for _ in directions]
        if rgb is None:rgb=np.random.default_rng(171).uniform(.03,.8,(256,3))
        drag=white_drag.StackWhiteDrag(rgb,np.ones(len(rgb)),params,space,matrices,
            directions,edited_occurrences,authoritative,left,right,np.eye(3),np.eye(3))
        return node,stack,drag,params,space

    def test_repeated_shared_grade_candidate_is_updated_at_every_entry(self):
        white_drag = _component('ui.white_drag')
        node,_,drag,params,space=self._stack_drag(
            ['FORWARD','FORWARD','INVERSE'],[True,False,True],
            [np.eye(3),np.array([[1.1,.02,0.],[0.,.94,.03],[.01,0.,1.02]]),np.eye(3)])
        changed=replace(params,source_x=params.source_x+.01)
        candidate=np.asarray(linear_model.edited_matrix(nodes.grades.matrix(node),space,
            {'source_x':changed.source_x,'source_y':changed.source_y}))
        expected=white_drag.compose_stage1(
            [candidate,drag._occurrence_matrices[1],candidate],drag._directions)
        actual=drag.composed_matrix(changed)
        np.testing.assert_allclose(actual,expected,rtol=1e-12,atol=1e-12)
        self.assertGreater(np.linalg.norm(actual-drag.composed_matrix(params)),1e-5)

    def test_empty_transparent_and_nonfinite_samples_use_finite_neutral_fallback(self):
        white_drag = _component('ui.white_drag')
        _,_,_,params,space=self._stack_drag(['INVERSE'],[True])
        cases=(
            (np.empty((0,3)),np.empty(0)),
            (np.full((4,3),.18),np.zeros(4)),
            (np.array([[np.nan,.2,.3],[.2,np.inf,.3]]),np.ones(2)),
            (np.full((2,3),.18),np.array([np.nan,np.inf])),
        )
        for rgb,alpha in cases:
            for stacked in (False,True):
                with self.subTest(count=len(rgb),alpha=alpha,stacked=stacked):
                    if stacked:
                        # Even with an evaluator available, unusable captures
                        # must take the finite neutral matrix fallback.
                        prepared=SimpleNamespace(apply_native=Mock(side_effect=
                            AssertionError('Invalid samples entered Stack evaluation')))
                        drag=white_drag.StackWhiteDrag(rgb,alpha,params,space,
                            [np.eye(3)],['INVERSE'],[True],np.eye(3),
                            np.eye(3),np.eye(3),np.eye(3),np.eye(3),
                            input_rgb=rgb,prepared=prepared)
                        self.assertFalse(drag._exact)
                        prepared.apply_native.assert_not_called()
                    else:drag=white_drag.WhiteDrag(rgb,alpha,params,space)
                    self.assertEqual(drag.sample_count,1)
                    np.testing.assert_array_equal(drag.selection_indices,[0])
                    np.testing.assert_array_equal(drag.weights,[1.])
                    np.testing.assert_array_equal(drag.rgb,[[.18,.18,.18]])
                    self.assertTrue(np.isfinite(drag.initial_center).all())
                    self.assertTrue(np.isfinite(drag.jacobian(params)).all())
                    moved=replace(params,**drag.move_pixels(params,(1.,-.5),.001))
                    self.assertTrue(np.isfinite(drag.position(moved)).all())

    def _nonlinear_stack_drag(self,directions,edited_occurrences):
        """Build an exact drag around the real prepared production evaluator."""
        from color_tools.perceptual_grade_core.model import transforms, lut as model_lut
        white_drag = _component('ui.white_drag')

        def active_grade(name,*,tone=False):
            grade=grade_data()
            grade.name=name
            with grades.guarded(grade):
                grade.pg_chromatic.global_gain=.35
                if tone:grade.pg_tone.input_midtones=60.
            return grade

        selected=active_grade('Stack drag nonlinear selected')
        intermediate=active_grade('Stack drag nonlinear intermediate',tone=True)
        selected_settings=nodes.settings(selected)
        intermediate_settings=nodes.settings(intermediate)
        entries=tuple(selected_settings if edited else intermediate_settings
                      for edited in edited_occurrences)
        space=nodes.grading_space(selected)
        stack_model=transforms.Stack(entries,'Linear Rec.709',directions)
        prepared=stack_model.prepare()
        params=nodes.read_parameters(selected)
        to_native,from_native=model_lut.basis(space)
        rng=np.random.default_rng(1907)
        input_rgb=rng.uniform(.035,.72,(12,3))
        native_input=(input_rgb@to_native.T).astype('f4')
        baseline_native=stack_model.apply_native(native_input)
        baseline_rgb=np.asarray(baseline_native,dtype=float)@from_native.T
        # Model a captured installed-LUT output with a small interpolation
        # residual. The drag prediction must retain that captured anchor.
        captured=baseline_rgb+np.linspace(-2e-4,2e-4,len(input_rgb))[:,None]*np.array([1.,-.5,.25])

        selected_index=next(i for i,value in enumerate(edited_occurrences) if value)
        forward=stack_model.grades[selected_index].forward
        boundary=np.asarray(forward.boundary.matrix,dtype=float)
        native_left=boundary@(np.asarray(linear_model.CAT16,dtype=float)/forward.white_cones[:,None])
        native_right=forward.cones_to_xyz@np.linalg.inv(boundary)
        matrices=tuple(np.asarray(grade.forward.matrix_native,dtype=float)
                       for grade in stack_model.grades)
        drag=white_drag.StackWhiteDrag(captured,np.ones(len(captured)),params,space,
            matrices,directions,edited_occurrences,nodes.grades.matrix(selected),
            native_left,native_right,to_native,from_native,stack_model,input_rgb,prepared)
        return (drag,stack_model,entries,selected,params,input_rgb,captured,
                to_native,from_native,prepared)

    def test_nonlinear_exact_preview_matches_production_stack_for_inverse_mixed_and_repeated(self):
        from color_tools.perceptual_grade_core.model import transforms
        white_drag = _component('ui.white_drag')

        cases=(
            (('INVERSE',),(True,)),
            (('FORWARD','INVERSE'),(True,False)),
            (('FORWARD','FORWARD','INVERSE'),(True,False,True)),
        )
        for directions,edited_occurrences in cases:
            with self.subTest(directions=directions,edited=edited_occurrences):
                (drag,stack_model,entries,selected,params,input_rgb,captured,
                 to_native,from_native,prepared)=self._nonlinear_stack_drag(
                    directions,edited_occurrences)
                before_matrices=tuple(value.copy() for value in prepared.matrices)
                before_inverses=tuple(None if value is None else value.copy()
                                      for value in prepared.inverses)
                before_input=prepared.input_matrix.copy()
                before_output=prepared.output_matrix.copy()

                candidate=replace(params,source_x=params.source_x+.002,
                                  source_y=params.source_y-.0015)
                edited_xyz=np.asarray(linear_model.edited_matrix(
                    nodes.grades.matrix(selected),drag.space,
                    {'source_x':candidate.source_x,'source_y':candidate.source_y}),dtype=float)
                candidate_entries=tuple(replace(value,matrix=edited_xyz)
                    if edited else value
                    for value,edited in zip(entries,edited_occurrences))
                # This is an independent production Stack, including its real
                # float32 forward kernels and inverse solver, with the edited
                # Grade's candidate Stage-1 matrix at every shared occurrence.
                direct_model=transforms.Stack(candidate_entries,'Linear Rec.709',directions)
                direct_native=direct_model.apply_native((input_rgb@to_native.T).astype('f4'))
                baseline_native=stack_model.apply_native((input_rgb@to_native.T).astype('f4'))
                direct_rgb=np.asarray(direct_native,dtype=float)@from_native.T
                baseline_rgb=np.asarray(baseline_native,dtype=float)@from_native.T
                selected_indices=drag.selection_indices
                expected=(captured[selected_indices]+direct_rgb[selected_indices]-
                          baseline_rgb[selected_indices])
                np.testing.assert_allclose(drag.preview_rgb(candidate),expected,
                                           rtol=3e-6,atol=3e-6)

                expected_center=drag.weights@white_drag.project(expected,drag.space)
                # position() is the exact local Jacobian model used to orient
                # pointer motion; near the baseline its finite-step error must
                # remain small. center() refreshes it from the full evaluator.
                np.testing.assert_allclose(drag.position(candidate),expected_center,
                                           rtol=2e-3,atol=2e-4)

                # Check the real nonlinear preview response in several scope
                # directions, rather than only checking the Jacobian's sign.
                # Small moves stay well inside the safe-white polygon, so
                # boundary projection cannot mask an orientation error.
                pointer_directions=((1.,0.),(-1.,0.),(0.,1.),(0.,-1.),
                                    (1.,1.),(-1.,1.),(1.,-1.),(-1.,-1.))
                if directions in (('INVERSE',),('FORWARD','INVERSE')):
                    baseline_coords=drag.preview_coordinates(params)
                    baseline_scope=drag.weights@baseline_coords
                    for pointer in pointer_directions:
                        moved=replace(params,**drag.move_pixels(params,pointer,.001))
                        moved_coords=drag.preview_coordinates(moved)
                        moved_scope=drag.weights@moved_coords
                        response=moved_scope-baseline_scope
                        self.assertGreater(float(np.dot(response,pointer)),1e-9,
                            msg=f'{directions}: pointer {pointer} produced {response}')
                else:
                    pointer=np.array([7.,3.])
                    moved=replace(params,**drag.move_pixels(params,pointer,.01))
                    baseline_scope=drag.weights@drag.preview_coordinates(params)
                    moved_scope=drag.weights@drag.preview_coordinates(moved)
                    self.assertGreater(float(np.dot(moved_scope-baseline_scope,pointer)),0.)

                np.testing.assert_allclose(drag.center(candidate),expected_center,
                                           rtol=2e-6,atol=2e-6)
                np.testing.assert_allclose(drag.position(candidate),expected_center,
                                           rtol=2e-6,atol=2e-6)

                for old,new in zip(before_matrices,prepared.matrices):
                    np.testing.assert_array_equal(new,old)
                for old,new in zip(before_inverses,prepared.inverses):
                    if old is None:self.assertIsNone(new)
                    else:np.testing.assert_array_equal(new,old)
                np.testing.assert_array_equal(prepared.input_matrix,before_input)
                np.testing.assert_array_equal(prepared.output_matrix,before_output)

    def test_final_inverse_endpoint_matches_full_float32_stack_under_matrix_stress(self):
        # A poorly conditioned, mixed-channel endpoint exposes differences in
        # inverse precision or matrix evaluation order. Compare the fast drag
        # endpoint against a freshly built production Stack, not another clone
        # of the drag's prepared evaluator.
        from color_tools.perceptual_grade_core.model import transforms
        stress=np.array([[1.,0.,0.],[.2,1e-5,0.],[-.1,.3,1.]])
        for directions,edited in ((('INVERSE',),(True,)),
                                  (('FORWARD','INVERSE'),(False,True))):
            with self.subTest(directions=directions):
                drag,_,entries,_,params,input_rgb,_,to_native,from_native,_=self._nonlinear_stack_drag(
                    directions,edited)
                self.assertTrue(drag._endpoint_only)
                original_right=drag._native_right.copy()
                drag._native_right=original_right@stress
                candidate=replace(params,source_x=params.source_x+.002,
                                  source_y=params.source_y-.0015)
                edited_xyz=np.asarray(linear_model.edited_matrix(
                    drag._authoritative_matrix,drag.space,
                    {'source_x':candidate.source_x,'source_y':candidate.source_y}),dtype=float)
                stressed_xyz=edited_xyz@original_right@stress@np.linalg.inv(original_right)
                candidate_entries=tuple(replace(value,matrix=stressed_xyz) if is_edited else value
                    for value,is_edited in zip(entries,edited))
                direct=transforms.Stack(candidate_entries,'Linear Rec.709',directions)
                native_matrix=direct.grades[-1].forward.matrix_native
                self.assertGreater(np.linalg.cond(native_matrix),1e4)
                expected_native=direct.apply_native((input_rgb@to_native.T).astype('f4'))
                expected=np.asarray(expected_native,dtype=float)@from_native.T
                actual=drag._evaluate_model(candidate)
                self.assertTrue(np.isfinite(actual).all())
                np.testing.assert_allclose(actual,expected,rtol=0.,atol=0.)

    def test_sequential_nonlinear_stack_drag_follows_pointer_through_reversals(self):
        # Steering updates a local Jacobian after each accepted move. Exercise
        # that update across turns instead of restarting every move at home.
        pointers=((8.,3.),(5.,8.),(-3.,8.),(-8.,2.),(-6.,-5.),
                  (2.,-8.),(8.,-3.),(7.,5.),(-7.,-5.),(6.,4.))
        cases=((('INVERSE',),(True,)),
               (('FORWARD','INVERSE'),(True,False)),
               (('INVERSE','FORWARD'),(True,False)))
        for directions,edited in cases:
            with self.subTest(directions=directions):
                drag,_,_,_,current,_,_,_,_,_=self._nonlinear_stack_drag(directions,edited)
                before=drag.weights@drag.preview_coordinates(current)
                for pointer in pointers:
                    moved=replace(current,**drag.move_pixels(current,pointer,.001))
                    after=drag.weights@drag.preview_coordinates(moved)
                    if moved!=current:
                        self.assertGreater(float(np.dot(after-before,pointer)),0.,
                            msg=f'{directions}: {pointer} from {current} moved against pointer')
                    drag.center(moved)
                    current,before=moved,after

    def test_stack_without_production_evaluator_has_no_approximate_drag_or_preview(self):
        _,_,drag,params,_=self._stack_drag(['INVERSE'],[True])
        self.assertFalse(drag.interactive)
        before=drag.center()
        candidate=replace(params,source_x=params.source_x+.01,
                          source_y=params.source_y-.005)

        # The composed Stage-1 matrix changes, but it cannot stand in for the
        # complete nonlinear/inverse Stack output. No estimated ghost or
        # source-white motion may be based on that matrix-only difference.
        self.assertGreater(np.linalg.norm(drag.composed_matrix(candidate)-
                                          drag.composed_matrix(params)),1e-5)
        updated=drag.move_pixels(params,(8.,-4.),.01)
        self.assertEqual(updated,dict(source_x=params.source_x,source_y=params.source_y))
        np.testing.assert_array_equal(drag.preview_rgb(candidate),drag.rgb)
        np.testing.assert_allclose(drag.center(candidate),before,rtol=0.,atol=0.)
        np.testing.assert_allclose(drag.position(candidate),before,rtol=0.,atol=0.)
        np.testing.assert_array_equal(drag.jacobian(candidate),np.zeros((2,2)))

    def test_cancelling_stage1_composition_is_not_used_as_whole_stack_prediction(self):
        _,_,drag,params,_=self._stack_drag(['FORWARD','INVERSE'],[True,True],
            [np.eye(3),np.eye(3)])
        self.assertFalse(drag.interactive)
        np.testing.assert_allclose(drag.composed_matrix(params),np.eye(3),atol=1e-13)
        candidate=replace(params,source_x=params.source_x+.01)
        self.assertTrue(np.isfinite(drag.preview_coordinates(candidate)).all())
        np.testing.assert_array_equal(drag.preview_rgb(candidate),drag.rgb)

    def test_stage1_scope_hit_enters_drag_for_a_stack_edit_target(self):
        tree=bpy.data.node_groups.new('Stage one drag target','CompositorNodeTree')
        grade=nodes.create_grade(tree)
        stack=sequence(tree,[grades.ensure(grade)])
        target=editing.Target(stack,stack.pg_stack_entries[0])
        wm=SimpleNamespace(pg_stage='LINEAR',pg_diagram_enabled=True,
            pg_diagram_x=24.,pg_diagram_y=24.,modal_handler_add=lambda _op:None)
        rect=(0.,0.,500.,500.)
        box={name:(450.,450.,20.,20.) for name in ('close','linear_tab','tone_tab','color_tab')}
        box.update(rect=rect,header=(0.,468.,500.,32.),vectorscope=(10.,10.,100.,100.))
        context=SimpleNamespace(window_manager=wm,window=None,area=SimpleNamespace(),
            preferences=SimpleNamespace(system=SimpleNamespace(ui_scale=1.)))
        event=SimpleNamespace(type='LEFTMOUSE',mouse_region_x=40.,mouse_region_y=40.,
            mouse_x=140.,mouse_y=140.)
        operator=SimpleNamespace(report=Mock())
        with patch.object(diagram,'layout',return_value=box),\
             patch.object(diagram.gizmo_help,'clear'),\
             patch.object(nodes,'active_grade',return_value=target),\
             patch.object(nodes,'read_chromatic',side_effect=AssertionError('Linear entry read chromatic model')):
            self.assertEqual(diagram.PG_OT_diagram_drag.invoke(operator,context,event),{'RUNNING_MODAL'})
        self.assertEqual(operator._mode,'scope_white')
        self.assertFalse(operator._scope_dragged)

    def test_vectorscope_click_keeps_reference_toggle(self):
        tree=bpy.data.node_groups.new('Stage one click target','CompositorNodeTree')
        grade=nodes.create_grade(tree);stack=sequence(tree,[grades.ensure(grade)])
        target=editing.Target(stack,stack.pg_stack_entries[0]);space=nodes.grading_space(target)
        op=SimpleNamespace(_node=target,_wm=SimpleNamespace(pg_diagram_enabled=True),
            _area=SimpleNamespace(tag_redraw=Mock()),_window=None,_space=space,
            _scene_space=nodes.working_space(),_mode='scope_white',_scope_dragged=False,
            _scope_acted=False,_white_scope_rect=(10.,10.,100.,100.),
            _pending_color=None,_drag_timer=None)
        context=SimpleNamespace(window=bpy.context.window,scene=bpy.context.scene)
        event=SimpleNamespace(type='LEFTMOUSE',value='RELEASE',mouse_region_x=40.,mouse_region_y=40.)
        with patch.object(diagram,'_registered',True),\
             patch('color_tools.perceptual_grade_blender.scopes.reference.connected',return_value=True),\
             patch('color_tools.perceptual_grade_blender.scopes.reference.toggle') as toggle:
            self.assertEqual(diagram.PG_OT_diagram_drag.modal(op,context,event),{'FINISHED'})
        toggle.assert_called_once_with(target)

    def test_stack_scope_drag_moves_resets_cancels_and_autokeys_source_white(self):
        tree=bpy.data.node_groups.new('Stage one drag lifecycle','CompositorNodeTree')
        grade=nodes.create_grade(tree)
        stack=sequence(tree,[grades.ensure(grade)])
        target=editing.Target(stack,stack.pg_stack_entries[0])
        initial=nodes.read_parameters(target)
        space=nodes.grading_space(target)
        wm=SimpleNamespace(pg_diagram_enabled=True)
        area=SimpleNamespace(tag_redraw=Mock())
        drag=SimpleNamespace(reset=Mock(),initial_center=(0.,0.),position=Mock(return_value=(.02,.03)))
        chart=SimpleNamespace(high=2.,low=-2.,size=200.)
        def gesture():
            return SimpleNamespace(_node=target,_wm=wm,_area=area,_window=None,_space=space,
                _scene_space=nodes.working_space(),_mode='scope_white',_last_mouse=(0.,0.),
                _press_mouse=(0.,0.),_scope_dragged=False,_scope_acted=False,_white_drag=drag,
                _box={'scale':1.,'chart':chart},_white_scope_rect=(0.,0.,100.,100.),
                _linear_start=nodes.grades.matrix(target),_grade_start=nodes.grades.selected(target),
                _start=nodes.read_parameters(target),_pending_color=None,_drag_timer=None)
        op=gesture()
        fake_white_drag=SimpleNamespace(
            move_pixels=Mock(return_value={'source_x':.31,'source_y':.34}),
            center=Mock(return_value=(.02,.03)),preview_available=True,
            initial_center=(.01,.02),reset=Mock(),position=Mock(return_value=(.01,.02)))
        move=SimpleNamespace(type='MOUSEMOVE',mouse_x=8.,mouse_y=-4.)
        with patch('color_tools.perceptual_grade_blender.ui.white_drag.from_node',return_value=fake_white_drag) as make_drag:
            self.assertEqual(diagram.PG_OT_diagram_drag.modal(op,bpy.context,move),{'RUNNING_MODAL'})
        make_drag.assert_called_once_with(target,space,initial)
        fake_white_drag.move_pixels.assert_called_once()
        self.assertTrue(op._scope_dragged)
        edited=nodes.read_parameters(target)
        self.assertAlmostEqual(edited.source_x,.31,places=6)
        self.assertAlmostEqual(edited.source_y,.34,places=6)

        diagram.PG_OT_diagram_drag.reset_dragged(op)
        wp=linear_model.white(space)
        reset=nodes.read_parameters(target)
        self.assertAlmostEqual(reset.source_x,wp[0],places=6)
        self.assertAlmostEqual(reset.source_y,wp[1],places=6)
        self.assertTrue(op._scope_acted)
        fake_white_drag.reset.assert_called_once()

        nodes.write_values(target,{'source_x':.31,'source_y':.34})
        op.restore=lambda:diagram.PG_OT_diagram_drag.restore(op)
        cancel=SimpleNamespace(type='ESC',value='PRESS')
        self.assertEqual(diagram.PG_OT_diagram_drag.modal(op,bpy.context,cancel),{'CANCELLED'})
        self.assertEqual(nodes.read_parameters(target),initial)

        # A fresh gesture inserts keyframes only for source-white fields that
        # changed, and cancellation above left the shared Grade untouched.
        auto=bpy.context.scene.tool_settings.use_keyframe_insert_auto
        try:
            bpy.context.scene.tool_settings.use_keyframe_insert_auto=True
            op=gesture()
            with patch('color_tools.perceptual_grade_blender.ui.white_drag.from_node',return_value=fake_white_drag):
                self.assertEqual(diagram.PG_OT_diagram_drag.modal(op,bpy.context,move),{'RUNNING_MODAL'})
            with patch.object(nodes,'keyframe_parameter') as keyframe:
                event=SimpleNamespace(type='LEFTMOUSE',value='RELEASE')
                self.assertEqual(diagram.PG_OT_diagram_drag.modal(op,bpy.context,event),{'FINISHED'})
            keyed={call.args[1] for call in keyframe.call_args_list}
            self.assertEqual(keyed,{'source_x','source_y'})
        finally:
            bpy.context.scene.tool_settings.use_keyframe_insert_auto=auto


class ScopeContextInteractionTests(BlenderTest):
    """Pointer routing uses native contexts without acquiring scope inputs."""

    def editors(self):
        tree=bpy.data.node_groups.new('Scope context interaction','CompositorNodeTree')
        node=nodes.create_grade(tree)
        source=tree.nodes.new('CompositorNodeExposure')
        tree.links.new(source.outputs['Image'],node.inputs['Color'])
        tree.nodes.active=node;node.select=True
        editors=[]
        for area in tuple(bpy.context.screen.areas)[:2]:
            area.type='NODE_EDITOR';area.ui_type='CompositorNodeTree'
            area.spaces.active.pin=True;area.spaces.active.node_tree=tree
            region=next(item for item in area.regions if item.type=='WINDOW')
            editors.append((area,region))
        self.assertEqual(len(editors),2)
        return node,editors

    @contextmanager
    def passive(self):
        with ExitStack() as stack:
            guards=[stack.enter_context(patch.object(component,name,
                side_effect=AssertionError('Passive interaction called '+name)))
                for component,name in ((sampling,'source_samples'),(sampling,'capture'))]
            replacements={}
            for name,methods in (('scopes.images',('read',)),('scopes.capture',('describe','acquire'))):
                exports=dict(component_items(self.session._component(name)))
                for method in methods:
                    guard=Mock(side_effect=AssertionError('Passive interaction called '+method))
                    guards.append(guard);exports[method]=guard
                replacements[name]=Component(exports)
            stack.enter_context(patch.dict(self.session.components,replacements))
            yield
            for guard in guards:guard.assert_not_called()

    def waiting(self,node):
        with self.assertRaisesRegex(lut.ScopePreparing,'Waiting for automatic'):
            sampling.describe_linear(node,nodes.grading_space(node),capture_context=bpy.context)

    def box(self):
        return dict(rect=(0.,0.,500.,500.),header=(0.,460.,500.,40.),
            close=(470.,470.,20.,20.),linear_tab=(350.,470.,30.,20.),
            tone_tab=(390.,470.,30.,20.),color_tab=(430.,470.,30.,20.),
            vectorscope=(10.,10.,200.,200.),before=(10.,10.,200.,200.),
            ab=(10.,10.,200.,200.),waveform=(10.,10.,200.,200.),scale=1.)

    def test_native_context_and_frozen_mapping_address_the_same_status(self):
        node,editors=self.editors();contexts=_component('scopes.context')
        channels=[]
        for area,region in editors:
            with bpy.context.temp_override(area=area,region=region),self.passive():
                frozen=contexts.source_context(node,bpy.context)
                channel=sampling.channel(node,bpy.context);channels.append(channel)
                self.assertEqual(channel,sampling.channel(node,frozen))
                self.assertEqual(channel,sampling.channel(node,MappingProxyType(frozen)))
                self.assertEqual(channel,sampling.channel(node))
                # An incomplete descriptor retains active-context discovery.
                self.assertEqual(channel,sampling.channel(node,MappingProxyType({})))
                self.waiting(node)
                self.assertEqual(sampling.scope_input_status(node,bpy.context),
                                 sampling.scope_input_status(node,frozen))
                self.assertEqual(sampling.scope_input_status(node,bpy.context)['state'],'waiting')
        self.assertNotEqual(*channels)
        self.assertEqual(sampling.channel(node,MappingProxyType({'consumer':None})),node.as_pointer())

    def test_supplied_editor_and_unresolved_fallback_do_not_use_ambient_editor(self):
        node,editors=self.editors();contexts=_component('scopes.context')
        supplied_area,supplied_region=editors[0]
        supplied=SimpleNamespace(window=bpy.context.window,area=supplied_area,
            region=supplied_region,space_data=supplied_area.spaces.active,scene=bpy.context.scene)
        with bpy.context.temp_override(area=editors[1][0],region=editors[1][1]),self.passive():
            expected=contexts.source_context(node,supplied)
            self.assertEqual(sampling.channel(node,supplied),sampling.channel(node,expected))
            self.assertNotEqual(sampling.channel(node,supplied),sampling.channel(node,bpy.context))
            exports=dict(component_items(self.session._component('scopes.context')))
            exports['consumer']=Mock(side_effect=ValueError('Ambiguous occurrence'))
            with patch.dict(self.session.components,{'scopes.context':Component(exports)}):
                self.assertEqual(sampling.channel(node,supplied),
                    (node.as_pointer(),('unresolved',supplied.window.as_pointer(),
                     supplied_area.as_pointer(),supplied_region.as_pointer())))
                self.assertNotEqual(sampling.channel(node,supplied),sampling.channel(node,bpy.context))

    def test_native_context_hover_reads_status_without_acquisition_on_each_page(self):
        node,editors=self.editors();area,region=editors[0]
        with bpy.context.temp_override(area=area,region=region):
            self.waiting(node)
            for stage in ('LINEAR','REMAP','CHROMATIC'):
                with self.subTest(stage=stage):
                    bpy.context.window_manager.pg_stage=stage
                    with self.passive(),\
                         patch.object(sampling,'scope_input_status',wraps=sampling.scope_input_status) as status,\
                         patch.object(_component('graph.gpu'),'status',return_value={'state':'ready'}):
                        # Inside the panel header, away from its early-return controls.
                        self.assertEqual(diagram.hover_cursor(bpy.context,node,self.box(),(30.,480.)),'SCROLL_XY')
                        self.assertGreaterEqual(status.call_count,2)
                        self.assertTrue(all(sampling.channel(node,call.args[1])==sampling.channel(node,bpy.context)
                                            for call in status.call_args_list))

class ScopeTests(BlenderTest):
    def analyze_full(self,node,view=()):
        spec=sampling.describe(node,nodes.grading_space(node),view)
        try:snapshot=sampling.capture(spec)
        finally:sampling.release(spec)
        return sampling.evaluate_snapshot(snapshot,OrderedDict())

    def analyze_active(self,node,view):
        from color_tools.perceptual_grade_blender.model import scope_active
        spec=sampling.describe(node,nodes.grading_space(node),view)
        try:snapshot=sampling.capture(spec)
        finally:sampling.release(spec)
        base=scope_active.prepare(snapshot,OrderedDict())
        result=scope_active.visual(base,snapshot,use_gpu=False)
        if any(warp for _,warp in snapshot['_scope_demands']):
            result=dict(result,_scope_request='oracle')
            delta=dict(scope_active.statistics(base,snapshot),_scope_request='oracle')
            result=jobs._merge_statistics(result,delta)
        return sampling.select_view(result,view)

    def assert_active_display(self,actual,expected):
        def equal(value,reference):
            if isinstance(value,np.ndarray):
                np.testing.assert_array_equal(value,reference)
                self.assertFalse(value.flags.writeable)
            elif hasattr(value,'items'):
                self.assertEqual(set(value),set(reference))
                for key,item in value.items():equal(item,reference[key])
            elif isinstance(value,(tuple,list)):
                self.assertEqual(len(value),len(reference))
                for item,wanted in zip(value,reference):equal(item,wanted)
            else:self.assertEqual(value,reference)
        self.assertEqual(set(actual['_active_colors']),set(expected['_active_colors']))
        for key,selected in actual['_active_colors'].items():
            wanted=expected['_active_colors'][key]
            for name in ('waveform_levels','vectorscope_levels','histograms','neutral','_comparison'):
                if name in selected:equal(selected[name],wanted[name])
            self.assertEqual(selected['_active_tone'],wanted['_active_tone'])
            self.assertEqual(selected['_active_page'],wanted['_active_page'])

    def assert_scope_display(self,actual,expected):
        """Compare published display fields with an independent rich analysis."""
        def equal(value,reference):
            if isinstance(value,np.ndarray):
                np.testing.assert_array_equal(value,reference)
                self.assertFalse(value.flags.writeable)
            elif hasattr(value,'items'):
                for key,item in value.items():equal(item,reference[key])
            else:self.assertEqual(value,reference)
        for name in ('before','after','linear_vectorscope'):
            equal(actual[name],expected[name])
        for selected,wanted in zip(actual['_colors'],expected['_colors'],strict=True):
            for name in ('after_energy','bounded_saturation','weights','histograms','sectors',
                         'waveform_selected','waveform_outside','vectorscope','neutral',
                         'saturation_excluded','label'):
                equal(selected[name],wanted[name])
        if expected['_comparison'] is None:
            self.assertIsNone(actual['_comparison'])
        else:
            for name in ('distribution','vectorscope','energy','bounded_saturation'):
                equal(actual['_comparison'][name],expected['_comparison'][name])
            for selected,wanted in zip(actual['_comparisons_selected'],expected['_comparisons_selected'],strict=True):
                for name in ('weights','waveform','vectorscope'):
                    equal(selected[name],wanted[name])
                self.assertIs(selected['signal'],actual['_comparison'])

    def node(self):
        tree=bpy.data.node_groups.new('Async scopes','CompositorNodeTree')
        node=nodes.create_grade(tree)
        node.inputs['Color'].default_value=(.2,.3,.7,1.)
        lut.ensure(node,nodes.bake_model(node))
        return node

    def image_source(self,node):
        image=bpy.data.images.new('Persistent dirty scope source',width=16,height=8,float_buffer=True,alpha=True)
        image.colorspace_settings.name='Non-Color';image.alpha_mode='CHANNEL_PACKED'
        rgba=np.random.default_rng(401).uniform(.02,.8,(8,16,4)).astype(np.float32)
        image.pixels.foreach_set(rgba.ravel());image.update()
        source=node.id_data.nodes.new('CompositorNodeImage');source.image=image
        node.id_data.links.new(source.outputs['Image'],node.inputs['Color'])
        return image,rgba

    def test_numeric_frames_publish_and_coalesce_while_compositor_guard_is_closed(self):
        """Immutable analytical work is independent of native output writes."""
        for kind in ('linear','full'):
            with self.subTest(kind=kind):
                sampling.refresh();bpy.context.scene.frame_set(1)
                node=self.node();pointer=node.as_pointer();space=nodes.grading_space(node)
                view=() if kind=='linear' else ('tone',)
                operation='scope_linear' if kind=='linear' else 'scope_full'
                first_gate,latest_gate=Event(),Event()
                executor=ScopeExecutor({operation:[first_gate,latest_gate]})
                tick=jobs.linear_tick if kind=='linear' else jobs.tick
                running=lambda:jobs._linear_running if kind=='linear' else jobs._running
                states=jobs._linear_states if kind=='linear' else jobs._states
                try:
                    with patch.object(jobs,'visible_consumers',return_value={(kind,pointer):(node,space,view)}),\
                         patch.object(jobs,'_submit',executor),\
                         patch.object(_component('graph.output_guard'),'available',return_value=False):
                        jobs.refresh_visible();tick();first=running()
                        self.assertIsNotNone(first)
                        self.assertFalse(scheduler.scope_dragging(node))
                        for frame in range(2,21):
                            bpy.context.scene.frame_set(frame)
                            nodes.write_values(node,{'exposure':frame/20})
                            jobs.refresh_visible();tick()
                            self.assertIs(running()[3],first[3])
                            self.assertEqual(len(executor.snapshots[operation]),1)
                        first_gate.set();tick()
                        state=states[pointer]
                        self.assertEqual(state['result']['_scope_key'],first[2]['key'])
                        self.assertEqual(state['_displayed_scene_frame'],1)
                        self.assertEqual(running()[2]['_scope_scene_frame'],20)
                        self.assertEqual(len(executor.snapshots[operation]),2)
                        latest_gate.set();tick()
                        self.assertEqual(state['completed'],state['spec']['key'])
                        self.assertEqual(state['_displayed_scene_frame'],20)
                        self.assertEqual(jobs.status(node,kind)['state'],'current')
                        self.assertIsNone(running())
                        jobs.refresh_visible();tick()
                        self.assertEqual(len(executor.snapshots[operation]),2)
                finally:first_gate.set();latest_gate.set()

    def completed_scope(self,node,view):
        """Allow retained components when a completed receipt lacks a replacement."""
        space=nodes.grading_space(node)
        for _ in range(8):
            result=sampling.get(node,space,view);jobs.tick()
            state=jobs._states[node.as_pointer()]
            if state['completed']==state['spec']['key']:
                return sampling.get(node,space,view)
        self.fail('Scope receipt did not complete')

    def test_only_demanded_tone_and_page_are_published_without_point_arrays(self):
        clouds = _component('scopes.clouds')
        node=self.node();space=nodes.grading_space(node);executor=ScopeExecutor()
        cloud=clouds.descriptor((0.,0.,32.,32.),1.,((-2.,-2.,2.,2.),)*4)
        clouds.replace_views({node.as_pointer():(cloud,)})
        with patch.object(jobs,'visible_consumers',return_value={}), \
             patch.object(jobs,'_submit',executor):
            for tone in range(4):
                for warp in (False,True):
                    view=(tone,warp)
                    current=wait_for_scopes(node,view)
                    self.assertEqual(set(current['_active_colors']),{f'{tone}:{"warp" if warp else "jc"}'})
                    selected=current['_color']
                    self.assertEqual(selected['_active_tone'],tone)
                    for name in ('sample_indices','weights','saturation','bounded_saturation','after_energy'):
                        self.assertNotIn(name,selected)
                    state=jobs._states[node.as_pointer()]
                    with patch.object(jobs,'_submit',side_effect=AssertionError('Unchanged focus caused work')):
                        cached=sampling.get(node,space,view)
                        self.assertIs(cached['_active_colors'],current['_active_colors'])
                        self.assertIsNone(jobs.tick())
                    self.assertEqual(state['completed'],state['spec']['key'])
        self.assertEqual(len(executor.snapshots['scope_register']),1)
        self.assertEqual(len(executor.snapshots['scope_update']),8)
        self.assertEqual(jobs.status(node)['state'],'current')

    def test_active_visual_then_statistics_and_restarted_helper_reseeds(self):
        clouds = _component('scopes.clouds')
        node=self.node();executor=ScopeExecutor()
        view=clouds.descriptor((0.,0.,32.,32.),1.,((-2.,-2.,2.,2.),)*4)
        clouds.replace_views({node.as_pointer():(view,)})
        with patch.object(jobs,'visible_consumers',return_value={}), \
             patch.object(jobs,'_submit',executor), \
             patch.object(scheduler,'scope_publish',wraps=scheduler.scope_publish) as publish:
            first=wait_for_scopes(node,(2,True))
            receipts=[call for call in publish.call_args_list if call.args[0].channel[0]=='full']
            self.assertEqual([call.args[0].quality for call in receipts],[1,2])
            visual,final=(call.args[1] for call in receipts)
            pixels=visual['_active_colors']['2:warp']['_warp_clouds'][0]['pixels']
            self.assertIs(pixels,final['_active_colors']['2:warp']['_warp_clouds'][0]['pixels'])
            self.assertIsNone(visual['_active_colors']['2:warp']['neutral'])
            self.assertEqual(first['_color']['statistics_status'],'ready')
            executor.session+='-restarted'
            nodes.write_chromatic(node,{'global_gain':.2})
            with patch.object(sampling,'source_samples',side_effect=AssertionError('Warm source was scanned')):
                second=wait_for_scopes(node,(2,True))
            self.assertNotEqual(first['_scope_key'],second['_scope_key'])
        self.assertEqual(len(executor.snapshots['scope_register']),2)
        self.assertEqual(len(executor.snapshots['scope_update']),3)
        def arrays(value):
            if isinstance(value,np.ndarray):return 1
            if hasattr(value,'values'):return sum(arrays(v) for v in value.values())
            if isinstance(value,(tuple,list)):return sum(arrays(v) for v in value)
            return 0
        self.assertTrue(all(arrays(snapshot)==0 for snapshot in executor.snapshots['scope_update']))

    def test_repeated_drag_edits_publish_each_regular_scope_before_release(self):
        """A worker slower than pointer events still publishes every completed capture."""
        cases=(('linear',(),'scope_linear'),('full',('tone',),'scope_full'),
               ('full',(2,False),'scope_update'))
        for kind,view,operation in cases:
            with self.subTest(kind=kind,view=view):
                sampling.refresh()
                node=self.node();space=nodes.grading_space(node);pointer=node.as_pointer()
                gates=[Event() for _ in range(4)]
                executor=ScopeExecutor({operation:gates})
                tick=jobs.linear_tick if kind=='linear' else jobs.tick
                running=lambda:jobs._linear_running if kind=='linear' else jobs._running
                states=jobs._linear_states if kind=='linear' else jobs._states
                def request():
                    result=(sampling.get_linear(node,space,ui=True) if kind=='linear'
                            else sampling.get(node,space,view,ui=True))
                    jobs.refresh_visible()  # Foreground timer follows passive drawing.
                    return result
                edit=(lambda value:nodes.write_values(node,{'exposure':value})) if kind=='linear' else (
                    (lambda value:nodes.write_tone(node,{'input_midtones':40.+value})) if view==('tone',) else
                    (lambda value:nodes.write_chromatic(node,{'global_gain':value})))
                visible={(kind,pointer):(node,space,view)}
                accepted=[];publish=scheduler.scope_publish
                def record_publication(ticket,payload):
                    admitted=publish(ticket,payload)
                    if admitted:accepted.append(payload['_scope_key'])
                    return admitted
                gesture=scheduler.begin(node)
                try:
                    with patch.object(jobs,'visible_consumers',return_value=visible), \
                         patch.object(jobs,'_submit',executor), \
                         patch.object(scheduler,'scope_publish',side_effect=record_publication):
                        request()
                        for _ in range(4):
                            tick()
                            if executor.snapshots[operation]:break
                        self.assertEqual(len(executor.snapshots[operation]),1)
                        published=[]
                        for cycle in range(3):
                            captured=running()[2]['key']
                            for step in range(4):
                                edit(.02*(cycle*4+step+1));request();tick()
                                self.assertEqual(running()[2]['key'],captured)
                            self.assertNotEqual(states[pointer]['spec']['key'],captured)
                            gates[cycle].set();tick()
                            displayed=states[pointer]['result']
                            self.assertIsNotNone(displayed)
                            self.assertEqual(displayed['_scope_key'],captured)
                            self.assertTrue(scheduler.dragging(node))
                            published.append(displayed['_scope_key'])
                            # Retirement must start the coalesced newest request
                            # in this tick, without needing another pointer event.
                            self.assertEqual(len(executor.snapshots[operation]),cycle+2)
                            self.assertEqual(running()[2]['key'],states[pointer]['spec']['key'])
                        self.assertEqual(len({repr(key) for key in published}),3)
                        old_capture=running()[2]['key']
                        edit(.4);request()
                        released=states[pointer]['spec']['key']
                        self.assertNotEqual(released,old_capture)
                        scheduler.end(gesture);gesture=None;jobs.finish_edit(node)
                        released_publications=len(accepted)
                        gates[3].set()
                        for _ in range(8):
                            tick()
                            if states[pointer]['completed']==released:break
                        self.assertEqual(states[pointer]['completed'],released)
                        self.assertEqual(states[pointer]['result']['_scope_key'],released)
                        self.assertEqual(jobs.status(node,kind)['state'],'current')
                        # Releasing a gesture retains compatible active work,
                        # just like playback; its newest successor finishes next.
                        self.assertEqual(accepted[released_publications:],[old_capture,released])
                finally:
                    for gate in gates:gate.set()
                    if gesture is not None:scheduler.end(gesture)

    def test_warp_drag_continuously_pairs_visual_and_statistics_before_release(self):
        clouds = _component('scopes.clouds')
        node=self.node();space=nodes.grading_space(node);pointer=node.as_pointer()
        view=(0,True);executor=ScopeExecutor();phases=[]
        cloud=clouds.descriptor((0.,0.,32.,32.),1.,((-2.,-2.,2.,2.),)*4)
        clouds.replace_views({pointer:(cloud,)})
        def submit(operation,snapshot):
            result=executor(operation,snapshot)
            if operation!='scope_update':return result
            phased=PhasedScopeResult(result,Event(),Event());phases.append(phased)
            return phased
        def request():
            result=sampling.get(node,space,view,ui=True)
            jobs.refresh_visible()
            return result
        visible={('full',pointer):(node,space,view)}
        accepted=[];publish=scheduler.scope_publish
        def record_publication(ticket,payload):
            admitted=publish(ticket,payload)
            if admitted:accepted.append((payload['_scope_key'],ticket.quality))
            return admitted
        gesture=scheduler.begin(node)
        try:
            with patch.object(jobs,'visible_consumers',return_value=visible), \
                 patch.object(jobs,'_submit',side_effect=submit), \
                 patch.object(scheduler,'scope_publish',side_effect=record_publication):
                request();jobs.tick();jobs.tick()
                self.assertEqual(len(phases),1)
                visual_ids=[];statistics_ids=[];previous_statistics=None
                for cycle in range(3):
                    phase=phases[cycle];captured=jobs._running[2]['key']
                    for step in range(3):
                        nodes.write_chromatic(node,{'global_gain':.02*(cycle*6+step+1)})
                        request();jobs.tick()
                    phase.cancel.assert_not_called()
                    phase.visual_gate.set();jobs.tick()
                    visual=request()
                    self.assertEqual(visual['_scope_key'],captured)
                    self.assertIs(visual['_color']['neutral'],previous_statistics)
                    self.assertEqual(visual['_color']['statistics_status'],'pending')
                    self.assertEqual(visual['_color']['_visual_request'],visual['_scope_request'])
                    if statistics_ids:
                        self.assertEqual(visual['_color']['_statistics_request'],statistics_ids[-1])
                        self.assertNotEqual(visual['_color']['_visual_request'],
                                            visual['_color']['_statistics_request'])
                    pixels=visual['_color']['_warp_clouds'][0]['pixels']
                    visual_ids.append(visual['_scope_request'])
                    for step in range(3):
                        nodes.write_chromatic(node,{'global_gain':.02*(cycle*6+step+4)})
                        request();jobs.tick()
                    phase.cancel.assert_not_called()
                    phase.statistics_gate.set();jobs.tick()
                    final=request()
                    self.assertEqual(final['_scope_request'],visual['_scope_request'])
                    # This capture is complete; newer pending controls still
                    # make its analysis stale relative to the requested edit.
                    self.assertEqual(final['_color']['statistics_status'],'pending')
                    self.assertEqual(final['_color']['_statistics_request'],final['_scope_request'])
                    self.assertIsNotNone(final['_color']['neutral'])
                    self.assertIs(final['_color']['_warp_clouds'][0]['pixels'],pixels)
                    previous_statistics=final['_color']['neutral']
                    statistics_ids.append(final['_scope_request'])
                    self.assertTrue(scheduler.dragging(node))
                    self.assertEqual(len(phases),cycle+2)
                    self.assertEqual(jobs._running[2]['key'],jobs._states[pointer]['spec']['key'])
                    # New input does not erase statistics belonging to the
                    # still-displayed raster while its replacement computes.
                    nodes.write_chromatic(node,{'global_gain':.02*(cycle*6+7)})
                    pending=request();jobs.tick()
                    self.assertIs(pending['_color']['neutral'],final['_color']['neutral'])
                    self.assertIs(pending['_color']['_warp_clouds'][0]['pixels'],pixels)
                self.assertEqual(visual_ids,statistics_ids)
                self.assertEqual(len(set(visual_ids)),3)
                obsolete=jobs._running[2]['key']
                nodes.write_chromatic(node,{'global_gain':.6});request()
                released=jobs._states[pointer]['spec']['key']
                self.assertNotEqual(obsolete,released)
                scheduler.end(gesture);gesture=None;jobs.finish_edit(node)
                self.assertIs(request()['_color']['neutral'],previous_statistics)
                released_publications=len(accepted)
                for _ in range(8):
                    for phase in phases:
                        phase.visual_gate.set();phase.statistics_gate.set()
                    jobs.tick()
                    if jobs._states[pointer]['completed']==released:break
                final=request()
                self.assertEqual(jobs._states[pointer]['completed'],released)
                self.assertEqual(final['_scope_key'],released)
                self.assertEqual(final['_color']['statistics_status'],'ready')
                self.assertEqual(len(executor.snapshots['scope_register']),1)
                self.assertEqual(accepted[released_publications:],
                                 [(obsolete,1),(obsolete,2),(released,1),(released,2)])
        finally:
            for phase in phases:
                phase.visual_gate.set();phase.statistics_gate.set()
            if gesture is not None:scheduler.end(gesture)

    def test_warp_committed_visual_keeps_previous_ellipse_until_matching_fit(self):
        clouds = _component('scopes.clouds')
        node=self.node();space=nodes.grading_space(node);executor=ScopeExecutor();phases=[]
        cloud=clouds.descriptor((0.,0.,32.,32.),1.,((-2.,-2.,2.,2.),)*4)
        clouds.replace_views({node.as_pointer():(cloud,)})
        with patch.object(jobs,'visible_consumers',return_value={}), \
             patch.object(jobs,'_submit',executor):old=wait_for_scopes(node,(0,True))
        old_color=old['_color'];old_pixels=old_color['_warp_clouds'][0]['pixels']
        def submit(operation,snapshot):
            result=executor(operation,snapshot)
            if operation!='scope_update':return result
            phase=PhasedScopeResult(result,Event(),Event());phases.append(phase)
            return phase
        try:
            with patch.object(jobs,'visible_consumers',return_value={}), \
                 patch.object(jobs,'_submit',side_effect=submit):
                nodes.write_chromatic(node,{'global_gain':.2})
                pending=sampling.get(node,space,(0,True))
                self.assertIs(pending['_color']['neutral'],old_color['neutral'])
                self.assertIs(pending['_color']['_warp_clouds'][0]['pixels'],old_pixels)
                jobs.tick();self.assertEqual(len(phases),1)
                phases[0].visual_gate.set();jobs.tick()
                visual=sampling.get(node,space,(0,True));selected=visual['_color']
                pixels=selected['_warp_clouds'][0]['pixels']
                self.assertIsNot(pixels,old_pixels)
                self.assertIs(selected['neutral'],old_color['neutral'])
                self.assertEqual(selected['_visual_request'],visual['_scope_request'])
                self.assertEqual(selected['_statistics_request'],old['_scope_request'])
                self.assertEqual(selected['statistics_status'],'pending')
                self.assertFalse(selected['_display_current'])
                self.assertNotEqual(selected['_visual_analysis'],selected['_statistics_analysis'])
                phases[0].statistics_gate.set();jobs.tick()
                final=sampling.get(node,space,(0,True))['_color']
                self.assertIs(final['_warp_clouds'][0]['pixels'],pixels)
                self.assertIsNot(final['neutral'],old_color['neutral'])
                self.assertEqual(final['_visual_request'],final['_statistics_request'])
                self.assertEqual(final['_visual_analysis'],final['_statistics_analysis'])
                self.assertEqual(final['_visual_epoch'],final['_statistics_epoch'])
                self.assertTrue(final['_display_current'])
        finally:
            for phase in phases:phase.visual_gate.set();phase.statistics_gate.set()

    def test_warp_retains_geometry_and_components_through_missing_views(self):
        clouds = _component('scopes.clouds')
        warp_samples = _component('ui.warp_samples')
        pass
        node=self.node();space=nodes.grading_space(node);pointer=node.as_pointer()
        first=clouds.descriptor((0.,0.,32.,32.),1.,((-2.,-2.,2.,2.),)*4)
        resized=clouds.descriptor((.25,.5,48.,48.),1.5,((-1.2,-1.2,1.2,1.2),)*4)
        gate=Event();executor=ScopeExecutor({'scope_update':[None,gate]})
        clouds.replace_views({pointer:(first,)})
        try:
            with patch.object(jobs,'visible_consumers',return_value={}), \
                 patch.object(jobs,'_submit',executor):
                old=wait_for_scopes(node,(0,True));selected=old['_color']
                pixels=selected['_warp_clouds'][0]['pixels'];stats=selected['neutral']
                clouds.replace_views({pointer:(resized,)})
                pending=sampling.get(node,space,(0,True))
                self.assertIs(pending['_color']['neutral'],stats)
                self.assertIs(pending['_color']['_warp_clouds'][0]['pixels'],pixels)
                plot=_component('ui.color_geometry').ABPlot((0.,0.,48.,48.),-1.2,1.2,-1.2,1.2)
                self.assertIs(warp_samples.choose_raster(plot,1.5,pending['_color']['_warp_clouds'],0),
                              selected['_warp_clouds'][0])
                jobs.tick();gate.set();current=wait_for_scopes(node,(0,True))
                current_pixels=current['_color']['_warp_clouds'][0]['pixels']
                self.assertIsNot(current_pixels,pixels)
                self.assertEqual(current['_color']['_warp_clouds'][0]['view']['width'],49)
                # Temporarily absent layout is not a newly empty distribution.
                clouds.replace_views({})
                missing=self.completed_scope(node,(0,True))
                self.assertIs(missing['_color']['_warp_clouds'][0]['pixels'],current_pixels)
                self.assertEqual(missing['_color']['_visual_request'],current['_color']['_visual_request'])
                self.assertIsNotNone(missing['_color']['neutral'])
                clouds.replace_views({pointer:(resized,)})
                restored=sampling.get(node,space,(0,True))
                self.assertIs(restored['_color']['_warp_clouds'][0]['pixels'],current_pixels)
        finally:gate.set()

    def test_cached_tone_and_page_are_restored_without_cross_tone_substitution(self):
        clouds = _component('scopes.clouds')
        node=self.node();space=nodes.grading_space(node);pointer=node.as_pointer();executor=ScopeExecutor()
        cloud=clouds.descriptor((0.,0.,32.,32.),1.,((-2.,-2.,2.,2.),)*4)
        clouds.replace_views({pointer:(cloud,)})
        with patch.object(jobs,'visible_consumers',return_value={}), \
             patch.object(jobs,'_submit',executor):
            first=wait_for_scopes(node,(0,True));first_color=first['_color']
            self.assertIsNone(sampling.get(node,space,(1,True)))
            second=wait_for_scopes(node,(1,True))
            restored=sampling.get(node,space,(0,True))
            self.assertIs(restored['_color']['neutral'],first_color['neutral'])
            self.assertIs(restored['_color']['_warp_clouds'][0]['pixels'],first_color['_warp_clouds'][0]['pixels'])
            self.assertEqual(restored['_color']['_active_tone'],0)
            self.assertNotEqual(restored['_color']['_visual_request'],second['_color']['_visual_request'])
            self.assertIsNone(sampling.get(node,space,(0,False)))
            jc=wait_for_scopes(node,(0,False))
            self.assertEqual(jc['_color']['_active_page'],'jc')
            restored=sampling.get(node,space,(0,True))
            self.assertIs(restored['_color']['neutral'],first_color['neutral'])
            # A second editor's demand must not erase the first editor's data.
            clouds.replace_demands({pointer:((0,True),(1,False))})
            expanded=sampling.get(node,space,(0,True))
            self.assertIs(expanded['_color']['neutral'],first_color['neutral'])
            union=wait_for_scopes(node,(0,True))
            self.assertEqual(set(union['_active_colors']),{'0:warp','1:jc'})
            clouds.replace_demands({pointer:((0,True),)})
            shrunk=sampling.get(node,space,(0,True))
            self.assertIs(shrunk['_color']['neutral'],union['_color']['neutral'])
            self.assertIsNone(sampling.get(node,space,(3,True)))
        requested={demand for snapshot in executor.snapshots['scope_update']
                   for demand in snapshot['_scope_demands']}
        self.assertEqual(requested,{(0,True),(1,True),(0,False),(1,False)})

    def test_warp_statistics_failure_retains_last_fit_and_source_change_clears_it(self):
        from color_tools.perceptual_grade_blender.model import scope_active
        clouds = _component('scopes.clouds')
        node=self.node();space=nodes.grading_space(node);executor=ScopeExecutor()
        cloud=clouds.descriptor((0.,0.,32.,32.),1.,((-2.,-2.,2.,2.),)*4)
        clouds.replace_views({node.as_pointer():(cloud,)})
        with patch.object(jobs,'visible_consumers',return_value={}), \
             patch.object(jobs,'_submit',executor):
            old=wait_for_scopes(node,(0,True))
            nodes.write_chromatic(node,{'global_gain':.2})
            with patch.object(scope_active,'statistics',side_effect=ValueError('Injected fit failure')):
                failed=self.completed_scope(node,(0,True))
            self.assertIs(failed['_color']['neutral'],old['_color']['neutral'])
            self.assertEqual(failed['_color']['_statistics_request'],old['_scope_request'])
            self.assertNotEqual(failed['_color']['_visual_request'],old['_scope_request'])
            self.assertFalse(failed['_color']['_display_current'])
            self.assertEqual(jobs.status(node)['state'],'error')
            jobs.retry(node)
            retried=sampling.get(node,space,(0,True))
            self.assertIs(retried['_color']['neutral'],old['_color']['neutral'])
            self.assertIs(retried['_color']['_warp_clouds'][0]['pixels'],failed['_color']['_warp_clouds'][0]['pixels'])
            recovered=wait_for_scopes(node,(0,True))
            self.assertEqual(recovered['_color']['_statistics_request'],recovered['_scope_request'])
            self.assertTrue(recovered['_color']['_display_current'])
            node.inputs['Color'].default_value=(.8,.1,.2,1.)
            self.assertIsNone(sampling.get(node,space,(0,True)))
            self.assertIsNone(sampling.get(node,space,(1,True)))

    def test_backend_switch_retains_components_and_valid_empty_raster_replaces_cloud(self):
        from color_tools.perceptual_grade_blender.model import scope_active
        clouds = _component('scopes.clouds')
        node=self.node();space=nodes.grading_space(node);pointer=node.as_pointer();executor=ScopeExecutor()
        cloud=clouds.descriptor((0.,0.,32.,32.),1.,((-2.,-2.,2.,2.),)*4)
        clouds.replace_views({pointer:(cloud,)})
        with patch.object(clouds,'_enabled',False), \
             patch.object(jobs,'visible_consumers',return_value={}), \
             patch.object(jobs,'_submit',executor):
            old=wait_for_scopes(node,(0,True));pixels=old['_color']['_warp_clouds'][0]['pixels']
            clouds.set_enabled(True)
            pending=sampling.get(node,space,(0,True))
            self.assertIs(pending['_color']['neutral'],old['_color']['neutral'])
            self.assertIs(pending['_color']['_warp_clouds'][0]['pixels'],pixels)
            self.assertEqual(clouds.views(node),(cloud,))
            changed=wait_for_scopes(node,(0,True))
            visual=scope_active.visual
            def empty_raster(*args,**kwargs):
                value=visual(*args,**kwargs);colors=dict(value['_active_colors'])
                records=tuple(dict(record,pixels=np.zeros_like(record['pixels']))
                              for record in colors['0:warp']['_warp_clouds'])
                colors['0:warp']=dict(colors['0:warp'],_warp_clouds=records)
                return dict(value,_active_colors=colors,_warp_clouds=records)
            nodes.write_chromatic(node,{'global_gain':.3})
            with patch.object(scope_active,'visual',side_effect=empty_raster):
                empty=wait_for_scopes(node,(0,True))
            replacement=empty['_color']['_warp_clouds'][0]['pixels']
            self.assertIsNot(replacement,changed['_color']['_warp_clouds'][0]['pixels'])
            self.assertEqual(np.count_nonzero(replacement),0)
            self.assertTrue(empty['_color']['_display_current'])

    def test_retained_display_cache_evicts_hidden_owners_before_visible_owner(self):
        first=self.node();second=nodes.create_grade(first.id_data);space=nodes.grading_space(first)
        visible={('full',first.as_pointer()):(first,space,(0,False))}
        with patch.object(jobs,'visible_consumers',return_value=visible), \
             patch.object(jobs,'_submit',ScopeExecutor()):
            first_result=wait_for_scopes(first,(0,False))
            sampling.get(first,space,(0,False),ui=True);jobs.refresh_visible()
            second_result=wait_for_scopes(second,(0,False))
            self.assertIsNotNone(second_result)
            for _ in range(8):
                hidden=nodes.create_grade(first.id_data)
                sampling.get(hidden,space,(0,False))
            self.assertEqual(len(jobs._states),8)
            self.assertIn(first.as_pointer(),jobs._states)
            self.assertNotIn(second.as_pointer(),jobs._states)
            self.assertNotIn(('full',second.as_pointer()),scheduler._records)
            retained=sampling.get(first,space,(0,False),ui=True)
            self.assertIs(retained['_color']['waveform_levels'],first_result['_color']['waveform_levels'])

    def test_stage_two_returns_while_warp_worker_waits_without_losing_cached_distribution(self):
        clouds = _component('scopes.clouds')
        node=self.node();space=nodes.grading_space(node);pointer=node.as_pointer();gate=Event()
        executor=ScopeExecutor({'scope_update':[gate]})
        cloud=clouds.descriptor((0.,0.,32.,32.),1.,((-2.,-2.,2.,2.),)*4)
        clouds.replace_views({pointer:(cloud,)})
        try:
            with patch.object(jobs,'visible_consumers',return_value={}), \
                 patch.object(jobs,'_submit',executor):
                tone=wait_for_scopes(node,('tone',))
                self.assertEqual(tone['_scope_evaluation'][0],'regular-grade-stage2')
                self.assertIsNone(sampling.get(node,space,(0,True)))
                for _ in range(4):
                    jobs.tick()
                    if executor.snapshots['scope_update']:break
                self.assertEqual(len(executor.snapshots['scope_update']),1)
                waiting=jobs._running[3]
                restored=sampling.get(node,space,('tone',))
                self.assertIs(restored,tone)
                self.assertIs(restored['after'],tone['after'])
                jobs.tick()
                self.assertIs(jobs._running[3],waiting)
                self.assertIs(sampling.get(node,space,('tone',)),tone)
                gate.set();current=wait_for_scopes(node,('tone',))
                self.assertEqual(current['_scope_evaluation'][0],'regular-grade-stage2')
                self.assertNotIn('_active_colors',current)
        finally:gate.set()

    def test_drag_cold_registration_advances_despite_continuing_control_edits(self):
        node=self.node();space=nodes.grading_space(node);pointer=node.as_pointer()
        register_gate=Event();update_gate=Event()
        executor=ScopeExecutor({'scope_register':[register_gate],'scope_update':[update_gate]})
        view=(2,False);visible={('full',pointer):(node,space,view)}
        gesture=scheduler.begin(node)
        try:
            with patch.object(jobs,'visible_consumers',return_value=visible), \
                 patch.object(jobs,'_submit',executor):
                sampling.get(node,space,view,ui=True);jobs.refresh_visible();jobs.tick()
                captured=jobs._running[2]['key']
                for index in range(4):
                    nodes.write_chromatic(node,{'global_gain':.03*(index+1)})
                    sampling.get(node,space,view,ui=True);jobs.refresh_visible();jobs.tick()
                self.assertEqual(len(executor.snapshots['scope_register']),1)
                self.assertFalse(executor.snapshots['scope_update'])
                register_gate.set();jobs.tick()
                self.assertEqual(len(executor.snapshots['scope_register']),1)
                self.assertEqual(len(executor.snapshots['scope_update']),1)
                nodes.write_chromatic(node,{'global_gain':.3})
                sampling.get(node,space,view,ui=True);jobs.refresh_visible();jobs.tick()
                update_gate.set();jobs.tick()
                displayed=sampling.get(node,space,view,ui=True)
                self.assertIsNotNone(displayed)
                self.assertEqual(displayed['_scope_key'],captured)
                self.assertTrue(scheduler.dragging(node))
                self.assertEqual(len(executor.snapshots['scope_update']),2)
                self.assertEqual(len(executor.snapshots['scope_register']),1)
        finally:
            register_gate.set();update_gate.set();scheduler.end(gesture)

    def test_scope_seed_acknowledgements_match_all_helper_identity_fields(self):
        runtime=SimpleNamespace(session=SimpleNamespace(identity='session-A'))
        handle=SimpleNamespace(backend='GPU',generation=7,runtime=runtime)
        future=SimpleNamespace(handle=handle)
        snapshot={'cache_id':'source-A'}
        valid=dict(cache_id='source-A',backend='GPU',session='session-A',generation=7)
        self.assertTrue(jobs._acknowledged(future,snapshot,valid))
        for field,value in (('cache_id','source-B'),('backend','CPU'),
                            ('session','session-B'),('generation',8)):
            with self.subTest(field=field):
                malformed=dict(valid,**{field:value})
                self.assertFalse(jobs._acknowledged(future,snapshot,malformed))

    def test_drag_service_rotates_despite_repeated_consumer_request_order(self):
        """Drawing A/B/C repeatedly cannot make A or C monopolize a worker."""
        for kind,operation in (('linear','scope_linear'),('full','scope_full')):
            with self.subTest(kind=kind):
                sampling.refresh()
                clouds = _component('scopes.clouds')
                clouds.clear()
                first=self.node();consumers=[first]
                for _ in range(2):
                    sibling=nodes.create_grade(first.id_data)
                    sibling.inputs['Color'].default_value=(.2,.3,.7,1.)
                    consumers.append(sibling)
                pointers=[node.as_pointer() for node in consumers]
                view=() if kind=='linear' else ('tone',)
                visible={(kind,node.as_pointer()):(node,nodes.grading_space(node),view)
                         for node in consumers}
                def request(node):
                    space=nodes.grading_space(node)
                    result=(sampling.get_linear(node,space,ui=True) if kind=='linear'
                            else sampling.get(node,space,view,ui=True))
                    jobs.refresh_visible()
                    return result
                tick=jobs.linear_tick if kind=='linear' else jobs.tick
                running=lambda:jobs._linear_running if kind=='linear' else jobs._running
                states=jobs._linear_states if kind=='linear' else jobs._states
                gates=[Event() for _ in range(7)]
                executor=ScopeExecutor({operation:gates})
                gestures=[scheduler.begin(node) for node in consumers]
                try:
                    with patch.object(jobs,'visible_consumers',return_value=visible), \
                         patch.object(jobs,'_submit',executor):
                        for node in consumers:request(node)
                        tick()
                        self.assertEqual(running()[0],pointers[0])
                        served=[]
                        for cycle in range(6):
                            pointer,_,spec,_=running();captured=spec['key']
                            self.assertEqual(pointer,pointers[cycle%3])
                            for step in range(3):
                                for index,node in enumerate(consumers):
                                    nodes.write_values(node,{'exposure':
                                        .02*(cycle*3+step+1)+index*.005})
                                for node in consumers:request(node)
                                tick()
                                self.assertEqual(running()[0],pointer)
                            gates[cycle].set();tick()
                            self.assertEqual(states[pointer]['result']['_scope_key'],captured)
                            served.append(pointer)
                            self.assertEqual(len(executor.snapshots[operation]),cycle+2)
                            self.assertEqual(running()[0],pointers[(cycle+1)%3],
                                f'cycle {cycle}: selected consumer {pointers.index(running()[0])}; '
                                f'order {[pointers.index(p) for p in jobs._service[kind]]}; '
                                f'cursor {jobs._service_start[kind]}')
                        self.assertEqual(served,pointers*2)
                finally:
                    for gate in gates:gate.set()
                    for gesture in gestures:scheduler.end(gesture)

    def test_incompatible_source_tone_or_page_still_fences_during_drag(self):
        cases=(('linear','source'),('full','source'),('full','tone'),('full','page'))
        for kind,change in cases:
            with self.subTest(kind=kind,change=change):
                sampling.refresh()
                clouds = _component('scopes.clouds')
                clouds.clear()
                node=self.node();space=nodes.grading_space(node);pointer=node.as_pointer()
                view=[() if kind=='linear' else (0,True)]
                visible={(kind,pointer):(node,space,view[0])}
                gate=Event();operation='scope_linear' if kind=='linear' else 'scope_update'
                executor=ScopeExecutor({operation:[None,gate]})
                tick=jobs.linear_tick if kind=='linear' else jobs.tick
                running=lambda:jobs._linear_running if kind=='linear' else jobs._running
                def request():
                    result=(sampling.get_linear(node,space,ui=True) if kind=='linear'
                            else sampling.get(node,space,view[0],ui=True))
                    jobs.refresh_visible()
                    return result
                gesture=None
                try:
                    with patch.object(jobs,'visible_consumers',return_value=visible), \
                         patch.object(jobs,'_submit',executor):
                        if kind=='linear':self.linear(node)
                        else:wait_for_scopes(node,view[0])
                        gesture=scheduler.begin(node)
                        if kind=='linear':nodes.write_values(node,{'exposure':.1})
                        else:nodes.write_chromatic(node,{'global_gain':.1})
                        request();tick()
                        old=running();future=old[3]
                        if change=='source':node.inputs['Color'].default_value=(.8,.1,.2,1.)
                        elif change=='tone':view[0]=(1,True)
                        else:view[0]=(0,False)
                        visible[kind,pointer]=(node,space,view[0])
                        request()
                        admitted=[];publish=scheduler.scope_publish
                        def record_publication(ticket,payload):
                            accepted=publish(ticket,payload)
                            if accepted:admitted.append(payload)
                            return accepted
                        with patch.object(scheduler,'scope_publish',side_effect=record_publication):
                            tick()
                            self.assertIs(running()[3],future)
                            gate.set();tick()
                            self.assertFalse(admitted)
                        settled=self.linear(node) if kind=='linear' else wait_for_scopes(node,view[0])
                        states=jobs._linear_states if kind=='linear' else jobs._states
                        self.assertNotEqual(settled['_scope_key'],old[2]['key'])
                        self.assertEqual(settled['_scope_key'],states[pointer]['spec']['key'])
                        self.assertTrue(scheduler.scope_dragging(node))
                finally:
                    gate.set()
                    if gesture is not None:scheduler.end(gesture)

    def test_obsolete_consumer_done_waits_for_physical_retirement(self):
        node=self.node();space=nodes.grading_space(node);executor=ScopeExecutor()
        with patch.object(jobs,'_submit',executor):wait_for_scopes(node,(2,False))
        handle=SimpleNamespace(preview=None,cancelled=False,physical=False)
        handle.done=lambda:handle.cancelled
        handle.retired=lambda:handle.physical
        def cancel():handle.cancelled=True;return True
        handle.cancel=cancel
        future=jobs.ScopeResult(handle)
        with patch.object(jobs,'_submit',return_value=future):
            nodes.write_chromatic(node,{'global_gain':.1})
            sampling.get(node,space,(2,False));jobs.tick()
        token=jobs._running[2]['_schedule']
        nodes.write_chromatic(node,{'global_gain':.2});sampling.get(node,space,(1,False))
        with patch.object(scheduler,'scope_complete',wraps=scheduler.scope_complete) as complete, \
             patch.object(jobs,'_submit',executor):
            jobs.tick()
            self.assertTrue(future.done());self.assertFalse(future.retired())
            self.assertIs(jobs._running[3],future)
            complete.assert_not_called()
            handle.physical=True;jobs.tick()
            self.assertTrue(any(call.args[0]==token for call in complete.call_args_list))
            settled=wait_for_scopes(node,(1,False))
        self.assertEqual(set(settled['_active_colors']),{'1:jc'})

    def test_clear_retains_scope_actor_and_snapshot_until_physical_retirement(self):
        node=self.node();space=nodes.grading_space(node);executor=ScopeExecutor()
        with patch.object(jobs,'_submit',executor):wait_for_scopes(node,(2,False))
        handle=SimpleNamespace(preview=None,cancelled=False,physical=False)
        handle.done=lambda:handle.cancelled
        handle.retired=lambda:handle.physical
        def cancel():handle.cancelled=True;return True
        handle.cancel=cancel
        future=jobs.ScopeResult(handle)
        with patch.object(jobs,'_submit',return_value=future):
            nodes.write_chromatic(node,{'global_gain':.1})
            sampling.get(node,space,(2,False));jobs.tick()
        spec=jobs._running[2];protocol=spec['_scope_protocol']
        try:
            with patch.object(sampling,'release',wraps=sampling.release) as release, \
                 patch.object(protocol,'close',wraps=protocol.close) as close:
                jobs.clear()
                self.assertTrue(handle.cancelled)
                self.assertEqual(protocol.state.phase,'retiring')
                self.assertFalse(jobs.drain_retired())
                close.assert_not_called();release.assert_not_called()
                self.assertTrue(any(item is spec for item,_ in jobs._retiring_cycles))
                handle.physical=True
                self.assertTrue(jobs.drain_retired())
                close.assert_called_once();release.assert_called_once_with(spec)
                self.assertNotIn('_scope_protocol',spec)
        finally:
            handle.physical=True
            jobs.drain_retired()

    def test_preview_decode_failure_holds_physical_slot_until_retirement(self):
        """A bad progressive receipt cannot release a still-running helper."""
        node=self.node();space=nodes.grading_space(node)
        old=wait_for_scopes(node,(0,False))
        previous=jobs._states[node.as_pointer()]['result']
        nodes.write_chromatic(node,{'global_gain':.1})

        class BadPreviewHandle:
            def __init__(self):self.physical=False;self.cancelled=False
            @property
            def preview(self):raise ValueError('malformed preview receipt')
            def done(self):return self.physical
            def retired(self):return self.physical
            def cancel(self):self.cancelled=True;return True
            def result(self,timeout=None):raise ValueError('malformed terminal receipt')

        handle=BadPreviewHandle();future=jobs.ScopeResult(handle)
        with patch.object(jobs,'_submit',return_value=future):
            sampling.get(node,space,(0,False));jobs.tick()
            self.assertIs(jobs._running[3],future)
            jobs.tick()
            self.assertIs(jobs._running[3],future)
            self.assertTrue(handle.cancelled)
            self.assertIsInstance(jobs._running[2].get('_scope_error'),str)
            self.assertEqual(jobs.status(node)['state'],'updating')
            # Retiring the physical helper makes the stored diagnostic
            # publish as an error and frees the scheduler ticket.
            handle.physical=True
            with self.assertLogs(jobs.LOG,level='ERROR'):
                jobs.tick()
            self.assertIsNone(jobs._running)
            self.assertIs(jobs._states[node.as_pointer()]['result'],previous)
            self.assertEqual(previous['_scope_key'],old['_scope_key'])
            self.assertEqual(jobs.status(node)['state'],'error')

    def test_regular_grade_branches_are_analytical_without_final_luts(self):
        node=self.node();upstream=nodes.create_grade(node.id_data)
        ref=nodes.create_grade(node.id_data)
        nodes.write_chromatic(upstream,{'global_gain':.12})
        nodes.write_chromatic(ref,{'global_gain':.23})
        node.id_data.links.new(upstream.outputs['Color'],node.inputs['Color'])
        node.id_data.links.new(ref.outputs['Color'],node.inputs[reference.SOCKET])
        space=nodes.grading_space(node)
        with patch.object(lut,'scope_signal',side_effect=AssertionError('Regular Grade requested a LUT')):
            result=wait_for_scopes(node)
            self.assertEqual(result['_scope_provenance'],())
            self.assertEqual(result['_scope_evaluation'][0],'regular-grade-appearance')
            self.assertIsNotNone(result['_comparison'])
            self.assertIsNotNone(self.linear(node))
            tone=wait_for_scopes(node,('tone',))
            self.assertEqual(tone['stage'],2)
            self.assertNotIn('_colors',tone)

    def test_stack_dependencies_reject_preview_cubes(self):
        node=self.node()
        upstream=sequence(node.id_data,[grade_data()])
        ref=sequence(node.id_data,[grade_data()])
        node.id_data.links.new(upstream.outputs['Color'],node.inputs['Color'])
        node.id_data.links.new(ref.outputs['Color'],node.inputs[reference.SOCKET])
        space=nodes.grading_space(node)
        for contaminated in (upstream,ref):
            real=lut.scope_signal
            def preview_signal(value,model=None,rows=None,owner=None):
                signal=real(value,model,rows,owner=owner)
                if value!=contaminated:return signal
                cube=signal[0]
                # The runtime guard must inspect the actual payload, even if
                # an adapter supplied an incorrect final-quality assertion.
                fake=cubes.Cube(cube.values[::2,::2,::2],cube.signature,cube.space,33)
                return fake,signal[1],signal[2]
            wait_for_scopes(node)
            sampling.refresh()
            with patch.object(lut,'scope_signal',side_effect=preview_signal):
                sampling.get(node,space);jobs.tick()
                future=jobs._running[3];future.result(timeout=10)
                with self.assertLogs(jobs.LOG,level='ERROR'):jobs.tick()
                self.assertIsNone(jobs._states[node.as_pointer()]['result'])
                self.assertEqual(jobs.status(node)['state'],'error')
                for _ in range(3):
                    sampling.get(node,space)
                    self.assertIsNone(jobs.tick())
            jobs.retry(node)
            self.assertEqual(jobs.status(node)['state'],'preparing')
        valid=wait_for_scopes(node)
        self.assertTrue(all(size==65 for _,size in valid['_scope_provenance']))
        self.assertTrue(valid['_scope_provenance'])

    def test_active_preview_cube_cannot_poison_seed_cache_or_retry(self):
        node=self.node();space=nodes.grading_space(node);view=(1,False)
        upstream=sequence(node.id_data,[grade_data()])
        ref=sequence(node.id_data,[grade_data()])
        node.id_data.links.new(upstream.outputs['Color'],node.inputs['Color'])
        node.id_data.links.new(ref.outputs['Color'],node.inputs[reference.SOCKET])
        for contaminated in (upstream,ref):
            with self.subTest(input=contaminated.name):
                executor=ScopeExecutor()
                with patch.object(jobs,'_submit',executor):
                    wait_for_scopes(node,view)
                    sampling.refresh()
                    registered=len(executor.snapshots['scope_register'])
                    real=lut.scope_signal
                    def preview_signal(value,model=None,rows=None,owner=None):
                        signal=real(value,model,rows,owner=owner)
                        if value!=contaminated:return signal
                        cube=signal[0]
                        fake=cubes.Cube(cube.values[::2,::2,::2],cube.signature,cube.space,33)
                        return fake,signal[1],signal[2]
                    with patch.object(lut,'scope_signal',side_effect=preview_signal):
                        sampling.get(node,space,view)
                        with self.assertLogs(jobs.LOG,level='ERROR'):jobs.tick()
                    state=jobs._states[node.as_pointer()]
                    cache_id=sampling.cache_id(state['spec'])
                    self.assertNotIn(cache_id,jobs._scope_sources)
                    self.assertNotIn(cache_id,jobs._scope_receipts)
                    self.assertEqual(len(executor.snapshots['scope_register']),registered)
                    self.assertIsNone(jobs._running)
                    self.assertEqual(jobs.status(node)['state'],'error')
                    jobs.retry(node)
                    valid=wait_for_scopes(node,view)
                    self.assertEqual(jobs.status(node)['state'],'current')
                    self.assertTrue(valid['_scope_provenance'])
                    self.assertTrue(all(size==65 for _,size in valid['_scope_provenance']))
                    self.assertIn(cache_id,jobs._scope_sources)
                    self.assertTrue(all(size==65 for _,size in jobs._scope_sources[cache_id]['_scope_provenance']))

    def test_failure_retains_coherent_scope_and_manual_retry_recovers(self):
        node=self.node();space=nodes.grading_space(node)
        old=wait_for_scopes(node);nodes.write_values(node,{'exposure':.1})
        self.assertIs(sampling.get(node,space),old)
        with patch.object(sampling,'capture',side_effect=TypeError('Injected capture failure')):
            with self.assertLogs(jobs.LOG,level='ERROR'):jobs.tick()
        state=jobs._states[node.as_pointer()]
        self.assertIs(state['result'],old)
        self.assertEqual(jobs.status(node)['state'],'error')
        with patch.object(sampling,'capture',side_effect=AssertionError('Automatic retry')):
            for _ in range(3):sampling.get(node,space);jobs.tick()
        jobs.retry(node)
        self.assertEqual(jobs.status(node)['state'],'updating')
        self.assertEqual(scheduler.scope_status(node),'stale')
        current=wait_for_scopes(node)
        self.assertNotEqual(current['_scope_key'],old['_scope_key'])
        self.assertEqual(jobs.status(node)['state'],'current')

        # A failed refresh can have the same semantic key as the last good
        # result. Retry must retain that result but run the capture again.
        state=jobs._states[node.as_pointer()]
        jobs._failure(state,state['spec'],RuntimeError('Same-key refresh failed'))
        self.assertEqual(jobs.status(node)['state'],'error')
        jobs.retry(node)
        self.assertIs(state['result'],current)
        self.assertIsNone(state['completed'])
        self.assertEqual(jobs.status(node)['state'],'updating')
        jobs.tick()
        self.assertIsNotNone(jobs._running)
        jobs._running[3].result(timeout=10);jobs.tick()
        self.assertEqual(state['completed'],state['spec']['key'])
        self.assertEqual(jobs.status(node)['state'],'current')

    def test_new_tone_discards_obsolete_update_and_retains_own_previous_statistics(self):
        node=self.node();space=nodes.grading_space(node)
        release=Event();executor=ScopeExecutor({'scope_update':[None,release]})
        with patch.object(jobs,'_submit',executor):
            old=wait_for_scopes(node,(0,True))
            self.assertIsNotNone(old['_color']['neutral'])
            nodes.write_chromatic(node,{'global_gain':.1})
            during=sampling.get(node,space,(0,True))
            self.assertEqual(during['_scope_key'],old['_scope_key'])
            self.assertIs(during['_color']['neutral'],old['_color']['neutral'])
            jobs.tick();future=jobs._running[3]
            nodes.write_chromatic(node,{'global_gain':.2})
            self.assertIsNone(sampling.get(node,space,(2,False)))
            jobs.tick()
            self.assertIs(jobs._running[3],future)
            release.set();future.result(timeout=10);jobs.tick()
            state=jobs._states[node.as_pointer()]
            self.assertEqual(state['result']['_scope_key'],old['_scope_key'])
            settled=wait_for_scopes(node,(2,False))
        self.assertEqual(settled['_scope_key'],sampling.describe(node,space,(2,False))['key'])
        self.assertEqual(set(settled['_active_colors']),{'2:jc'})

    def visible_result(self,node,kind,timeout=10):
        states=jobs._linear_states if kind=='linear' else jobs._states
        deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            lut.tick();jobs.refresh_visible();jobs.linear_tick();jobs.tick()
            state=states[node.as_pointer()]
            if state['result'] is not None and state['completed']==state['spec']['key'] and not state['requested']:
                return state['result']
            if state['failed']==state['spec']['key']:self.fail('Visible scope failed')
            time.sleep(.001)
        self.fail('Visible scope did not finish')

    def test_dirty_image_revisions_follow_samples_and_preserve_shared_cache(self):
        node=self.node();image,rgba=self.image_source(node);now=[1.]
        with patch.object(_component('scopes.images'),'time',SimpleNamespace(monotonic=lambda:now[0])):
            first=sampling.source_samples(node,nodes.working_space())[0]
            signature=sampling.source_signature(node)
            self.assertEqual(first.dtype,np.float32)
            # A different reference grid has its own revision; it must not
            # invalidate the already sampled primary image.
            sampling.source_samples(node,nodes.working_space(),size=(4,2))[0]
            self.assertEqual(sampling.source_signature(node),signature)
            now[0]+=.5
            self.assertIs(sampling.source_samples(node,nodes.working_space())[0],first)
            self.assertEqual(sampling.source_signature(node),signature)
            rgba[1,2,3]*=.5;image.pixels.foreach_set(rgba.ravel());image.update()
            now[0]+=.49
            self.assertIs(sampling.source_samples(node,nodes.working_space())[0],first)
            now[0]+=.02
            changed=sampling.source_samples(node,nodes.working_space())[0]
            self.assertIsNot(changed,first)
            self.assertNotEqual(sampling.source_signature(node),signature)
            np.testing.assert_array_equal(changed,rgba)
            # Nonfinite samples should not make an unchanged image perpetual work.
            rgba[0,0,0]=np.nan;image.pixels.foreach_set(rgba.ravel());image.update();now[0]+=.5
            invalid=sampling.source_samples(node,nodes.working_space())[0];now[0]+=.5
            self.assertIs(sampling.source_samples(node,nodes.working_space())[0],invalid)

    def test_visible_dirty_image_probes_do_not_reanalyze_or_redraw_unchanged_pixels(self):
        node=self.node();image,rgba=self.image_source(node);self.preview(node)
        now=[1.];consumers={}
        with (
            patch.object(jobs,'visible_consumers',return_value=consumers),
            patch.object(_component('scopes.images'),'time',SimpleNamespace(monotonic=lambda:now[0])),
        ):
            for kind in ('linear','full'):
                with self.subTest(kind=kind):
                    consumers.clear();consumers[kind,node.as_pointer()]=(node,nodes.grading_space(node),())
                    result=self.visible_result(node,kind)
                    revision=sampling.source_signature(node)
                    with (
                        patch.object(jobs,'_submit',side_effect=AssertionError('Unchanged scope analysis')),
                        patch.object(lut,'redraw') as redraw,
                    ):
                        for _ in range(3):
                            now[0]+=.5;jobs.refresh_visible();jobs.linear_tick();jobs.tick()
                            self.assertIsNone(jobs._linear_running);self.assertIsNone(jobs._running)
                        redraw.assert_not_called()
                    state=(jobs._linear_states if kind=='linear' else jobs._states)[node.as_pointer()]
                    self.assertIs(state['result'],result)
                    self.assertEqual(sampling.source_signature(node),revision)
                    self.assertEqual(state['completed'],state['spec']['key'])
            # Closing the last consumer stops even the lightweight probe timer.
            consumers.clear();jobs.refresh_visible()
            self.assertFalse(bpy.app.timers.is_registered(scheduler.timer_callback(jobs.probe_tick)))
            now[0]+=1.;rgba[0,0,0]=.95;image.pixels.foreach_set(rgba.ravel());image.update()
            with patch.object(sampling,'source_samples',side_effect=AssertionError('Hidden source capture')):
                jobs.refresh_linear(node);jobs.refresh_visible();jobs.linear_tick();jobs.tick()
            # Reopening validates the dirty source before publishing current scopes.
            consumers['linear',node.as_pointer()]=(node,nodes.grading_space(node),())
            reopened=self.visible_result(node,'linear')
            self.assertAlmostEqual(reopened['source_rgb'][0,0,0],.95,places=6)

    def test_closed_consumer_finishes_current_worker_without_successor_or_redraw(self):
        for kind in ('linear','full'):
            with self.subTest(kind=kind):
                node=self.node();pointer=node.as_pointer();space=nodes.grading_space(node)
                consumers={(kind,pointer):(node,space,())}
                block=self.blocked_linear if kind=='linear' else self.blocked_analysis
                request=sampling.get_linear if kind=='linear' else sampling.get
                tick=jobs.linear_tick if kind=='linear' else jobs.tick
                running=lambda:jobs._linear_running if kind=='linear' else jobs._running
                with patch.object(jobs,'visible_consumers',return_value=consumers),block() as (started,release,snapshots):
                    request(node,space,ui=True);jobs.refresh_visible();tick();self.assertTrue(started.wait(2))
                    future=running()[3]
                    consumers.clear();jobs.refresh_visible();nodes.write_values(node,{'exposure':.3})
                    release.set();future.result(timeout=10)
                    with patch.object(lut,'redraw') as redraw:
                        self.assertIsNone(tick());self.assertIsNone(tick())
                        redraw.assert_not_called()
                    self.assertIsNone(jobs._linear_pending);self.assertEqual(len(snapshots),1)
                    consumers[kind,pointer]=(node,space,())
                    current=self.visible_result(node,kind)
                    self.assertEqual(len(snapshots),2)
                    if kind=='linear':
                        np.testing.assert_allclose(current['stage1_rgb'],current['source_rgb']@nodes.linear_matrix(node).T)
                    else:
                        expected=scope_analysis.evaluate_snapshot(snapshots[-1],OrderedDict())
                        np.testing.assert_allclose(expected['stage1_rgb'],expected['source_rgb']@nodes.linear_matrix(node).T)
                        self.assert_scope_display(current,expected)

    def test_page_switch_cancels_queued_scope_and_explicit_requests_still_work(self):
        node=self.node();pointer=node.as_pointer();space=nodes.grading_space(node)
        consumers={('linear',pointer):(node,space,())}
        with patch.object(jobs,'visible_consumers',return_value=consumers):
            sampling.get_linear(node,space,ui=True)
            self.assertIsNone(jobs._linear_pending)  # Drawing records no work.
            jobs.refresh_visible()
            self.assertIsNotNone(jobs._linear_pending)
            consumers.clear();consumers['full',pointer]=(node,space,())
            jobs.refresh_visible()
            self.assertIsNone(jobs._linear_pending)
            submit=jobs._submit
            def active_only(operation,snapshot):
                self.assertNotEqual(operation,'scope_linear')
                return submit(operation,snapshot)
            with patch.object(jobs,'_submit',active_only):
                self.visible_result(node,'full')
            consumers.clear();jobs.refresh_visible()
            # A tool's explicit request works once without any editor, and
            # retained results do not subscribe it to subsequent grade edits.
            first=self.linear(node)
            nodes.write_values(node,{'exposure':.2})
            self.assertIsNone(jobs.linear_tick());self.assertIsNone(jobs._linear_pending)
            current=self.linear(node)
            self.assertNotEqual(current['_scope_key'],first['_scope_key'])

    def test_hidden_one_shot_does_not_follow_edits_while_worker_runs(self):
        for kind in ('linear','full'):
            with self.subTest(kind=kind):
                node=self.node();space=nodes.grading_space(node)
                block=self.blocked_linear if kind=='linear' else self.blocked_analysis
                request=sampling.get_linear if kind=='linear' else sampling.get
                tick=jobs.linear_tick if kind=='linear' else jobs.tick
                running=lambda:jobs._linear_running if kind=='linear' else jobs._running
                with block() as (started,release,snapshots):
                    request(node,space);tick();self.assertTrue(started.wait(2))
                    future=running()[3]
                    nodes.write_values(node,{'exposure':.4})
                    release.set();future.result(timeout=10)
                    self.assertIsNone(tick());self.assertIsNone(running())
                    self.assertEqual(len(snapshots),1)
                    current=self.linear(node) if kind=='linear' else wait_for_scopes(node)
                    self.assertEqual(len(snapshots),2)
                    self.assertIsNotNone(current)

    def test_queued_one_shot_captures_source_changed_before_worker_start(self):
        node=self.node();space=nodes.grading_space(node)
        previous=self.linear(node)
        nodes.write_values(node,{'exposure':.1})
        sampling.get_linear(node,space)
        # No second request: the previously cached source must not be relabeled
        # with the new source's revision when the queued capture finally runs.
        node.inputs['Color'].default_value=(.7,.1,.2,1.)
        jobs.linear_tick();self.assertIsNotNone(jobs._linear_running)
        jobs._linear_running[3].result(timeout=10)
        self.assertIsNone(jobs.linear_tick())
        current=jobs._linear_states[node.as_pointer()]['result']
        self.assertIsNot(current,previous)
        np.testing.assert_allclose(current['source_rgb'][0,0],[.7,.1,.2],rtol=0,atol=3e-8)

    def test_real_editors_keep_distinct_tickets_and_share_numeric_sources(self):
        node=self.node();self.image_source(node);tree=node.id_data
        sampling.source_samples(node,nodes.grading_space(node))
        wm=bpy.context.window_manager;wm.pg_diagram_enabled=True;wm.pg_stage='LINEAR'
        areas=list(bpy.context.screen.areas)[:2]
        self.assertEqual(len(areas),2)
        for area in areas:
            area.type='NODE_EDITOR';area.ui_type='CompositorNodeTree'
            area.spaces.active.pin=True;area.spaces.active.node_tree=tree
        consumers=diagram.scope_consumers();keys=set(consumers)
        self.assertEqual(len(keys),2)
        self.assertEqual({kind for kind,_ in keys},{'linear'})
        self.assertEqual({channel[0] for _,channel in keys},{node.as_pointer()})
        self.assertEqual(len({value[3]['consumer'] for value in consumers.values()}),2)
        with patch.object(jobs,'_submit',ScopeExecutor()):
            for _ in range(8):
                jobs.refresh_visible();jobs.linear_tick()
                states=[jobs._linear_states[channel] for _,channel in keys]
                if all(state['completed']==state['spec']['key'] for state in states):break
            self.assertTrue(all(state['completed']==state['spec']['key'] for state in states))
            self.assertIs(states[0]['result']['_source'],states[1]['result']['_source'])
            self.assertNotEqual(states[0]['spec']['_schedule'].channel,
                                states[1]['spec']['_schedule'].channel)
        nodes.write_values(node,{'exposure':.2})
        jobs.refresh_visible();self.assertIsNotNone(jobs._linear_pending)
        self.assertTrue(bpy.app.timers.is_registered(scheduler.timer_callback(jobs.probe_tick)))
        areas[0].type='VIEW_3D'
        remaining=set(diagram.scope_consumers())
        self.assertEqual(len(remaining),1);self.assertLess(remaining,keys)
        jobs.refresh_visible();self.assertIsNotNone(jobs._linear_pending)
        areas[1].type='VIEW_3D'
        self.assertFalse(diagram.scope_consumers())
        with patch.object(sampling,'source_samples',side_effect=AssertionError('Closed editor capture')):
            jobs.refresh_visible();self.assertIsNone(jobs.linear_tick())
        self.assertIsNone(jobs._linear_pending)
        self.assertFalse(bpy.app.timers.is_registered(scheduler.timer_callback(jobs.probe_tick)))
        area=areas[0];area.type='NODE_EDITOR';area.ui_type='CompositorNodeTree'
        area.spaces.active.pin=True;area.spaces.active.node_tree=tree
        wm.pg_stage='CHROMATIC'
        target=next(iter(diagram.scope_consumers().values()))
        self.assertEqual(target[2],(node.pg_chromatic.active_tone,False))
        node.pg_chromatic.family='WARP'
        self.assertEqual(next(iter(diagram.scope_consumers().values()))[2],(node.pg_chromatic.active_tone,True))
        wm.pg_stage='REMAP'
        self.assertEqual(next(iter(diagram.scope_consumers().values()))[2],('tone',))
        wm.pg_diagram_enabled=False
        self.assertFalse(diagram.scope_consumers())

    def sequence_source(self,node):
        """A real source sequence whose frames have distinct stored pixels."""
        import os,struct,tempfile,zlib
        directory=tempfile.TemporaryDirectory(prefix='pg-playback-test-')
        self.addCleanup(directory.cleanup)
        def chunk(kind,data):
            return struct.pack('>I',len(data))+kind+data+struct.pack('>I',zlib.crc32(kind+data)&0xffffffff)
        for frame in range(1,21):
            header=struct.pack('>2I5B',1,1,8,6,0,0,0)
            data=b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',header)
            data+=chunk(b'IDAT',zlib.compress(bytes((0,frame*10,100,200,255))))+chunk(b'IEND',b'')
            with open(os.path.join(directory.name,f'frame{frame:04}.png'),'wb') as stream:stream.write(data)
        image=bpy.data.images.load(os.path.join(directory.name,'frame0001.png'));image.source='SEQUENCE'
        source=node.id_data.nodes.new('CompositorNodeImage');source.image=image
        source.frame_start=1;source.frame_duration=20
        node.id_data.links.new(source.outputs['Image'],node.inputs['Color'])
        bpy.context.scene.frame_set(1)
        sampling.source_samples(node,nodes.grading_space(node))

    def test_cold_acquisition_freezes_first_frame_and_only_keeps_newest_successor(self):
        images=_component('scopes.images')
        for kind in ('linear','full'):
            with self.subTest(kind=kind):
                sampling.refresh();node=self.node();self.sequence_source(node);images.invalidate()
                pointer=node.as_pointer();space=nodes.grading_space(node)
                view=() if kind=='linear' else ('tone',)
                operation='scope_linear' if kind=='linear' else 'scope_full'
                first_gate,latest_gate,decode_gate=Event(),Event(),Event()
                executor=ScopeExecutor({operation:[first_gate,latest_gate]})
                tick=jobs.linear_tick if kind=='linear' else jobs.tick
                running=lambda:jobs._linear_running if kind=='linear' else jobs._running
                states=jobs._linear_states if kind=='linear' else jobs._states
                read=sampling.source_samples;attempts=[]
                def acquire(*args,**kwargs):
                    route=kwargs.get('frozen_route')
                    if route is not None and route.kind=='image' and kwargs.get('prepared') is None:
                        attempts.append(route.source.frame)
                        if not decode_gate.is_set():raise images.SourcePreparing('Gated source decode')
                    kwargs['asynchronous']=False
                    return read(*args,**kwargs)
                try:
                    with patch.object(jobs,'visible_consumers',return_value={(kind,pointer):(node,space,view)}),\
                         patch.object(jobs,'_submit',executor),patch.object(sampling,'source_samples',acquire):
                        jobs.refresh_visible();tick()
                        first=states[pointer]['capturing']
                        self.assertIsNotNone(first);self.assertIsNone(running())
                        for frame in range(2,21):
                            bpy.context.scene.frame_set(frame)
                            nodes.write_values(node,{'exposure':frame/100})
                            jobs.refresh_visible();tick()
                            self.assertIs(states[pointer]['capturing'],first)
                            self.assertIsNone(running())
                        self.assertEqual(set(attempts),{1})
                        decode_gate.set();tick()
                        self.assertEqual(running()[2]['_scope_frames'],(1,))
                        self.assertEqual(len(executor.snapshots[operation]),1)
                        first_gate.set();tick()
                        self.assertEqual(states[pointer]['_displayed_frames'],(1,))
                        self.assertEqual(running()[2]['_scope_frames'],(20,))
                        self.assertEqual(set(attempts),{1,20})
                        self.assertEqual(len(executor.snapshots[operation]),2)
                        latest_gate.set();tick()
                        self.assertEqual(states[pointer]['_displayed_frames'],(20,))
                        self.assertEqual(states[pointer]['completed'],states[pointer]['spec']['key'])
                finally:first_gate.set();latest_gate.set();decode_gate.set()

    def test_forced_primary_is_retained_while_reference_acquisition_waits(self):
        node=self.node();self.image_source(node)
        ref=node.id_data.nodes.new('CompositorNodeImage')
        ref.image=bpy.data.images.new('Scope reference',width=16,height=8,float_buffer=True)
        node.id_data.links.new(ref.outputs['Image'],node.inputs[reference.SOCKET])
        spec=sampling.describe_linear(node,nodes.grading_space(node))
        read=sampling.source_samples;calls=[];ready=Event()
        def acquire(*args,**kwargs):
            socket=args[2] if len(args)>2 else 'Color'
            if kwargs.get('prepared') is None:
                calls.append(socket)
                if socket==reference.SOCKET and not ready.is_set():
                    raise _component('scopes.images').SourcePreparing('Reference is still decoding')
            return read(*args,**kwargs)
        with patch.object(sampling,'source_samples',acquire):
            for _ in range(3):
                with self.assertRaises(_component('scopes.images').SourcePreparing):
                    sampling.prepare_sources(spec,force=True)
            self.assertEqual(calls.count('Color'),1)
            ready.set();prepared=sampling.prepare_sources(spec,force=True)
            captured=sampling.capture_linear(prepared,{})
            self.assertEqual(calls.count('Color'),1)
            self.assertEqual(calls.count(reference.SOCKET),4)
            self.assertIsNotNone(captured['comparison'])
            self.assertFalse(prepared['_scope_prepared_sources'][0][0].flags.writeable)
        sampling.release(prepared)

    def test_cancelled_acquisition_keeps_lease_until_source_physically_retires(self):
        from tests.support.session import current_session
        node=self.node();self.sequence_source(node)
        pointer=node.as_pointer();space=nodes.grading_space(node)
        visible={('linear',pointer):(node,space,())};retired=Event()
        application=current_session();application.component('scopes.images')
        images=application.components['scopes.images']
        application.components['scopes.images']=Component({'retired':lambda descriptor:retired.is_set()},
            readers={name:(lambda name=name:getattr(images,name))
                     for name,_ in component_items(images) if name!='retired'})
        read=sampling.source_samples
        def acquire(*args,**kwargs):
            if not retired.is_set():raise images.SourcePreparing('Gated source decode')
            kwargs['asynchronous']=False
            return read(*args,**kwargs)
        try:
            with patch.object(jobs,'visible_consumers',return_value=visible),\
                 patch.object(jobs,'_submit',ScopeExecutor()),patch.object(sampling,'source_samples',acquire):
                jobs.refresh_visible();jobs.linear_tick()
                spec=jobs._linear_states[pointer]['capturing'];protocol=spec['_scope_protocol']
                visible.clear();jobs.refresh_visible()
                self.assertEqual(protocol.state.phase,'retiring')
                self.assertEqual(jobs._retiring_captures,[spec])
                visible['linear',pointer]=(node,space,())
                jobs.refresh_visible();jobs.linear_tick()
                self.assertIsNone(jobs._linear_running)
                self.assertIsNone(jobs._linear_states[pointer]['capturing'])
                self.assertFalse(jobs.drain_retired())
                retired.set();jobs.linear_tick()
                self.assertFalse(jobs._retiring_captures)
                self.assertNotIn('_scope_protocol',spec)
                self.assertIsNotNone(jobs._linear_running)
                jobs.linear_tick()
        finally:
            retired.set();jobs.drain_retired()
            application.components['scopes.images']=images

    def test_partial_reference_acquisition_does_not_replace_frozen_request(self):
        for kind in ('linear','full'):
            with self.subTest(kind=kind):
                sampling.refresh();bpy.context.scene.frame_set(1)
                node=self.node();self.image_source(node)
                ref=node.id_data.nodes.new('CompositorNodeImage')
                ref.image=bpy.data.images.new('Delayed reference',width=16,height=8,float_buffer=True)
                node.id_data.links.new(ref.outputs['Image'],node.inputs[reference.SOCKET])
                pointer=node.as_pointer();space=nodes.grading_space(node)
                view=() if kind=='linear' else ('tone',)
                operation='scope_linear' if kind=='linear' else 'scope_full'
                tick=jobs.linear_tick if kind=='linear' else jobs.tick
                running=lambda:jobs._linear_running if kind=='linear' else jobs._running
                states=jobs._linear_states if kind=='linear' else jobs._states
                ready=Event();numerical=Event();executor=ScopeExecutor({operation:[numerical]})
                read=sampling.source_samples;reads=[]
                def acquire(*args,**kwargs):
                    socket=args[2] if len(args)>2 else 'Color'
                    if kwargs.get('prepared') is None:
                        reads.append(socket)
                        if socket==reference.SOCKET and not ready.is_set():
                            raise _component('scopes.images').SourcePreparing('Reference decode pending')
                    kwargs['asynchronous']=False
                    return read(*args,**kwargs)
                try:
                    with patch.object(jobs,'visible_consumers',return_value={(kind,pointer):(node,space,view)}),\
                         patch.object(jobs,'_submit',executor),patch.object(sampling,'source_samples',acquire):
                        jobs.refresh_visible();tick()
                        frozen=states[pointer]['capturing'];owner=frozen['_schedule'].owner
                        self.assertEqual(set(frozen['_scope_prepared_sources']),{0})
                        for frame in range(2,6):
                            bpy.context.scene.frame_set(frame);nodes.write_values(node,{'exposure':frame/10})
                            jobs.refresh_visible();tick()
                            self.assertIs(states[pointer]['capturing'],frozen)
                            self.assertEqual(states[pointer]['spec']['_schedule'].owner,owner)
                        self.assertEqual(reads.count('Color'),1)
                        ready.set();tick()
                        self.assertEqual(running()[2]['_scope_scene_frame'],1)
                        self.assertEqual(len(executor.snapshots[operation]),1)
                        self.assertEqual(reads.count('Color'),1)
                        numerical.set();tick()
                        self.assertEqual(states[pointer]['_displayed_scene_frame'],1)
                        tick()
                        self.assertEqual(states[pointer]['_displayed_scene_frame'],5)
                finally:ready.set();numerical.set()

    def test_animated_source_keeps_finished_frame_and_coalesces_newest_pending(self):
        for kind in ('linear','full'):
            with self.subTest(kind=kind):
                sampling.refresh()
                node=self.node();self.sequence_source(node)
                pointer=node.as_pointer();space=nodes.grading_space(node)
                view=() if kind=='linear' else ('tone',)
                visible={(kind,pointer):(node,space,view)}
                operation='scope_linear' if kind=='linear' else 'scope_full'
                first_gate,latest_gate=Event(),Event()
                executor=ScopeExecutor({operation:[first_gate,latest_gate]})
                tick=jobs.linear_tick if kind=='linear' else jobs.tick
                running=lambda:jobs._linear_running if kind=='linear' else jobs._running
                states=jobs._linear_states if kind=='linear' else jobs._states
                try:
                    with patch.object(jobs,'visible_consumers',return_value=visible),\
                         patch.object(jobs,'_submit',executor),self.completed_image_reads():
                        jobs.refresh_visible();tick()
                        first=running();first_key=first[2]['key']
                        self.assertTrue(first[2]['_scope_history'])
                        self.assertEqual(first[2]['_scope_frames'],(1,))
                        for frame in range(2,21):
                            bpy.context.scene.frame_set(frame)
                            jobs.refresh_visible();tick()
                            self.assertIs(running()[3],first[3])
                            self.assertEqual(len(executor.snapshots[operation]),1)
                            self.assertEqual(states[pointer]['spec']['_scope_frames'],(frame,))
                        first_gate.set();tick()
                        state=states[pointer]
                        newest=running()[2]['key']
                        self.assertEqual(state['spec']['key'],newest)
                        self.assertEqual(state['result']['_scope_key'],first_key)
                        self.assertEqual(state['_displayed_frames'],(1,))
                        self.assertNotEqual(state['completed'],newest)
                        self.assertEqual(running()[2]['_scope_frames'],(20,))
                        self.assertEqual(len(executor.snapshots[operation]),2)
                        latest_gate.set();tick()
                        self.assertEqual(state['completed'],newest)
                        self.assertEqual(state['result']['_scope_key'],newest)
                        self.assertEqual(state['_displayed_frames'],(20,))
                        self.assertIsNone(running())
                        self.assertFalse(scheduler.scope_dragging(node))
                finally:first_gate.set();latest_gate.set()

    def test_looped_animated_key_does_not_complete_or_clear_newer_failure(self):
        for kind in ('linear','full'):
            with self.subTest(kind=kind):
                sampling.refresh()
                node=self.node();self.sequence_source(node)
                pointer=node.as_pointer();space=nodes.grading_space(node)
                view=() if kind=='linear' else ('tone',)
                visible={(kind,pointer):(node,space,view)}
                operation='scope_linear' if kind=='linear' else 'scope_full'
                gate=Event();executor=ScopeExecutor({operation:[gate]})
                tick=jobs.linear_tick if kind=='linear' else jobs.tick
                running=lambda:jobs._linear_running if kind=='linear' else jobs._running
                states=jobs._linear_states if kind=='linear' else jobs._states
                try:
                    with patch.object(jobs,'visible_consumers',return_value=visible),\
                         patch.object(jobs,'_submit',executor),self.completed_image_reads():
                        jobs.refresh_visible();tick()
                        original=running()[2]
                        for frame in (2,1):
                            bpy.context.scene.frame_set(frame);jobs.refresh_visible();tick()
                        state=states[pointer];current=state['spec']
                        self.assertEqual(original['key'],current['key'])
                        self.assertLess(original['_schedule'].epoch,current['_schedule'].epoch)
                        jobs._failure(state,current,RuntimeError('new loop failed'))
                        gate.set();tick()
                        self.assertEqual(state['result']['_scope_key'],original['key'])
                        self.assertEqual(state['failed'],current['key'])
                        self.assertEqual(state['error'],'new loop failed')
                        self.assertNotEqual(state['completed'],current['key'])
                        self.assertEqual(jobs.status(node,kind)['state'],'error')
                        self.assertEqual(len(executor.snapshots[operation]),1)
                        self.assertIsNone(running())
                finally:gate.set()

    def test_animated_primary_history_does_not_cross_static_reference_change(self):
        for kind in ('linear','full'):
            with self.subTest(kind=kind):
                sampling.refresh()
                node=self.node();self.sequence_source(node)
                ref=node.id_data.nodes.new('CompositorNodeRGB')
                ref.outputs[0].default_value=(.6,.1,0.,1.)
                node.id_data.links.new(ref.outputs[0],node.inputs[reference.SOCKET])
                pointer=node.as_pointer();space=nodes.grading_space(node)
                view=() if kind=='linear' else ('tone',)
                visible={(kind,pointer):(node,space,view)}
                operation='scope_linear' if kind=='linear' else 'scope_full'
                old_gate,new_gate=Event(),Event()
                executor=ScopeExecutor({operation:[old_gate,new_gate]})
                tick=jobs.linear_tick if kind=='linear' else jobs.tick
                running=lambda:jobs._linear_running if kind=='linear' else jobs._running
                states=jobs._linear_states if kind=='linear' else jobs._states
                accepted=[];publish=scheduler.scope_publish
                def record(ticket,payload):
                    admitted=publish(ticket,payload)
                    if admitted:accepted.append(payload['_scope_key'])
                    return admitted
                try:
                    with patch.object(jobs,'visible_consumers',return_value=visible),\
                         patch.object(jobs,'_submit',executor),\
                         patch.object(scheduler,'scope_publish',side_effect=record),self.completed_image_reads():
                        jobs.refresh_visible();tick()
                        old=running();self.assertTrue(old[2]['_scope_history'])
                        bpy.context.scene.frame_set(2)
                        ref.outputs[0].default_value=(0.,.1,.6,1.)
                        jobs.refresh_visible();tick()
                        self.assertEqual(len(executor.snapshots[operation]),1)
                        self.assertIs(running()[3],old[3])
                        self.assertNotEqual(old[2]['context'],states[pointer]['spec']['context'])
                        old_gate.set();tick()
                        self.assertFalse(accepted)
                        self.assertIsNone(states[pointer]['result'])
                        current=running()[2]['key']
                        self.assertEqual(len(executor.snapshots[operation]),2)
                        new_gate.set();tick()
                        self.assertEqual(accepted,[current])
                        self.assertEqual(states[pointer]['completed'],current)
                        captured=executor.snapshots[operation][-1]['comparison']
                        rgba=captured['rgba'] if kind=='linear' else captured[0]
                        np.testing.assert_allclose(rgba[0,0],(0.,.1,.6,1.),atol=3e-8)
                finally:old_gate.set();new_gate.set()

    @contextmanager
    def completed_image_reads(self):
        """Numerical-cycle tests control computation; acquisition has its own gates."""
        read=sampling.source_samples
        def completed(*args,**kwargs):
            kwargs['asynchronous']=False
            return read(*args,**kwargs)
        with patch.object(sampling,'source_samples',completed):yield

    def pump(self,condition,timeout=10):
        deadline=time.monotonic()+timeout
        while not condition() and time.monotonic()<deadline:
            jobs.tick();time.sleep(.001)
        self.assertTrue(condition(),'Scope scheduler did not reach the required state')

    def native_replacement(self):
        nodes.undo_redo_pre_handler()
        nodes.reset_cache_handler()

    def finish_recovery(self):
        deadline=time.monotonic()+5
        while nodes.recovery_status()['state'] not in ('completed','failed') and time.monotonic()<deadline:
            nodes.recovery_tick();time.sleep(.001)
        self.assertEqual(nodes.recovery_status()['state'],'completed',nodes.recovery_status())

    def linear(self,node,timeout=10):
        deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            result=sampling.get_linear(node,nodes.grading_space(node));jobs.linear_tick()
            state=jobs._linear_states[node.as_pointer()]
            if result is not None and result['_scope_key']==state['spec']['key']:return result
            if state['failed']==state['spec']['key']:self.fail('Stage-1 scope failed')
            time.sleep(.001)
        self.fail('Stage-1 scope did not finish')

    @contextmanager
    def blocked_linear(self):
        release=Event(); executor=ScopeExecutor({'scope_linear':[release]})
        try:
            with patch.object(jobs,'_submit',executor):
                yield executor.started['scope_linear'],release,executor.snapshots['scope_linear']
        finally:release.set()

    @contextmanager
    def blocked_analysis(self):
        release=Event(); executor=ScopeExecutor({'scope_full':[release]})
        try:
            with patch.object(jobs,'_submit',executor):
                yield executor.started['scope_full'],release,executor.snapshots['scope_full']
        finally:release.set()

    def preview(self,node):
        cube=lut.installed_cube(node)
        if cube is not None and cube.signature==cubes.signature(nodes.bake_model(node)):return cube
        state=lut._states[node.as_pointer()];state['due']=0
        deadline=time.monotonic()+15
        while time.monotonic()<deadline:
            lut.tick()
            cube=lut.installed_cube(node)
            if cube is not None and cube.signature==cubes.signature(nodes.bake_model(node),33):return cube
            time.sleep(.001)
        self.fail('Preview publication did not finish')

    def test_handle_and_preview_progress_while_scope_worker_is_blocked(self):
        node=self.node();space=nodes.grading_space(node)
        with self.blocked_analysis() as (started,release,snapshots):
            self.assertIsNone(sampling.get(node,space));jobs.tick()
            self.assertTrue(started.wait(2));future=jobs._running[3]
            bpy.context.window_manager.pg_diagram_enabled=True
            area=SimpleNamespace(tag_redraw=Mock())
            drag=SimpleNamespace(_node=node,_wm=bpy.context.window_manager,_area=area,
                _window=None,_space=space,_scene_space=nodes.working_space(),_mode='exposure',
                _last_mouse=(0,0),_box={'exposure':(0,0,300,24)},_pending_color=None,_drag_timer=None)
            event=SimpleNamespace(type='MOUSEMOVE',value='NOTHING',mouse_x=30,mouse_y=0)
            self.assertEqual(diagram.PG_OT_diagram_drag.modal(drag,bpy.context,event),{'RUNNING_MODAL'})
            self.assertGreater(nodes.read_parameters(node).exposure,0)
            self.assertFalse(future.done())
            self.assertIsNone(sampling.get(node,space))
            cube=self.preview(node)
            self.assertIn(cube.size,(33,65))
            self.assertFalse(hasattr(jobs,'_executor'))
            self.assertFalse(future.done())
            event=SimpleNamespace(type='LEFTMOUSE',value='RELEASE')
            self.assertEqual(diagram.PG_OT_diagram_drag.modal(drag,bpy.context,event),{'FINISHED'})
            self.assertFalse(future.done())
            release.set();base=wait_for_scopes(node)
            self.assertEqual(len(snapshots),2)
            self.assertEqual(base['_scope_key'],jobs._states[node.as_pointer()]['spec']['key'])
            area.tag_redraw.assert_called()
            self.assertIsNone(drag._area)

    def test_stage_one_publishes_while_bulk_scope_response_is_blocked(self):
        node=self.node();lut.ensure(node,nodes.bake_model(node))
        space=nodes.grading_space(node)
        with self.blocked_analysis() as (started,release,_):
            sampling.get(node,space);jobs.tick();self.assertTrue(started.is_set())
            full_future=jobs._running[3]
            first=self.linear(node)
            nodes.write_values(node,{'source_x':.33,'source_y':.34})
            latest=self.linear(node)
            self.assertNotEqual(first['_scope_key'],latest['_scope_key'])
            self.assertFalse(full_future.done())
            self.assertFalse(hasattr(jobs,'_linear_executor'))
            release.set();full_future.result(timeout=15)

    def test_stage_one_matrix_numerics_source_reuse_and_comparison(self):
        spaces = _component('graph.spaces')
        from color_tools.perceptual_grade_core.model import tone
        self.enterContext(patch.object(sampling,'time',SimpleNamespace(monotonic=lambda:1.)))
        self.enterContext(patch.object(_component('scopes.images'),'time',SimpleNamespace(monotonic=lambda:1.)))
        node=self.node();nodes.write_values(node,{'exposure':.2})
        nodes.write_tone(node,{'input_midtones':45});nodes.write_chromatic(node,{'global_gain':.3})
        image=bpy.data.images.new('Linear scope samples',width=256,height=192,float_buffer=True,alpha=True)
        image.colorspace_settings.name='Non-Color';image.alpha_mode='CHANNEL_PACKED'
        rgba=np.random.default_rng(512).uniform(-.1,.8,(192,256,4)).astype('f4');rgba[0,0,3]=0
        image.pixels.foreach_set(rgba.ravel());image.update()
        source=node.id_data.nodes.new('CompositorNodeImage');source.image=image
        reference_node=node.id_data.nodes.new('CompositorNodeRGB');reference_node.outputs[0].default_value=(.3,.2,.6,.7)
        node.id_data.links.new(source.outputs['Image'],node.inputs['Color'])
        node.id_data.links.new(reference_node.outputs[0],node.inputs[reference.SOCKET])
        sample=sampling.source_samples
        def main_capture(*args,**kwargs):
            self.assertIs(current_thread(),main_thread());return sample(*args,**kwargs)
        with patch.object(sampling,'source_samples',side_effect=main_capture) as capture,\
             patch.object(tone,'model',side_effect=AssertionError('Stage 1 requested appearance math')),\
             patch.object(lut,'installed_signal',side_effect=AssertionError('Stage 1 copied its own LUT')),\
             patch.object(scope_analysis,'evaluate_samples',side_effect=AssertionError('Foreground analysis ran')):
            actual=self.linear(node)
        # The first read establishes image revisions; the second freezes their
        # coherent identity. Pixel readbacks themselves reuse sample_image.
        self.assertEqual(capture.call_count,4)
        to_grade=spaces.adapters(nodes.working_space())[0]
        expected_input=rgba[...,:3].astype(float)@to_grade.T
        expected=expected_input@nodes.linear_matrix(node).T
        np.testing.assert_array_equal(actual['source_rgb'],expected_input)
        np.testing.assert_array_equal(actual['stage1_rgb'],expected)
        np.testing.assert_array_equal(actual['alpha'],rgba[...,3])
        np.testing.assert_array_equal(actual['linear_vectorscope']['density'],
            color.vectorscope(expected,rgba[...,3],nodes.grading_space(node))['density'])
        self.assertEqual(actual['stage1_rgb'].shape,(192,256,3))
        self.assertTrue(np.any(actual['stage1_rgb']<0))
        self.assertFalse(actual['source_rgb'].flags.writeable);self.assertFalse(actual['stage1_rgb'].flags.writeable)
        comparison=np.broadcast_to(np.array([.3,.2,.6],dtype='f4'),(192,256,3)).astype(float)@to_grade.T
        np.testing.assert_array_equal(actual['_comparison']['vectorscope']['density'],
            color.vectorscope(comparison,np.full((192,256),np.float32(.7)),nodes.grading_space(node))['density'])
        with patch.object(sampling,'source_samples',side_effect=AssertionError('Unchanged source recaptured')):
            nodes.write_values(node,{'exposure':.4});latest=self.linear(node)
        self.assertIs(latest['_source'],actual['_source'])
        self.assertIs(latest['_comparison_source'],actual['_comparison_source'])
        key=latest['_scope_key']
        nodes.write_tone(node,{'input_midtones':46});nodes.write_chromatic(node,{'global_gain':.4})
        self.assertIs(sampling.get_linear(node,nodes.grading_space(node)),latest)
        self.assertEqual(jobs._linear_states[node.as_pointer()]['spec']['key'],key)
        self.assertFalse(jobs.linear_pending())

    def test_scope_adapters_retire_work_and_obey_policy_rejection(self):
        """The policy owns admission; both numerical adapters use its decision."""
        for kind in ('linear','full'):
            with self.subTest(kind=kind):
                node=self.node();space=nodes.grading_space(node)
                block=self.blocked_linear if kind=='linear' else self.blocked_analysis
                request=sampling.get_linear if kind=='linear' else sampling.get
                tick=jobs.linear_tick if kind=='linear' else jobs.tick
                states=jobs._linear_states if kind=='linear' else jobs._states
                with block() as (started,release,_):
                    request(node,space);tick();self.assertTrue(started.wait(2))
                    running=jobs._linear_running if kind=='linear' else jobs._running
                    token=running[2]['_schedule'];future=running[3]
                    release.set();future.result(timeout=10)
                    with patch.object(scheduler,'scope_complete',wraps=scheduler.scope_complete) as complete,\
                         patch.object(scheduler,'scope_publish',return_value=False) as publish,\
                         patch.object(jobs,'_redraw') as redraw:
                        tick()
                    complete.assert_called_once_with(token);publish.assert_called_once()
                    redraw.assert_not_called();self.assertIsNone(states[node.as_pointer()]['result'])

    def test_stage_one_rejects_old_source_and_reuses_no_stale_upstream_signal(self):
        node=self.node();space=nodes.grading_space(node)
        with self.blocked_linear() as (started,release,_):
            sampling.get_linear(node,space);jobs.linear_tick();self.assertTrue(started.wait(2))
            old_state=jobs._linear_states[node.as_pointer()]
            node.inputs['Color'].default_value=(.7,.1,.2,1)
            self.assertIsNone(sampling.get_linear(node,space));release.set()
            latest=self.linear(node);self.assertIsNone(old_state['result'])
            spaces = _component('graph.spaces')
            expected=np.array([.7,.1,.2],dtype='f4').astype(float)@spaces.adapters(nodes.working_space())[0].T
            np.testing.assert_array_equal(latest['source_rgb'][0,0],expected)
        upstream=self.node();downstream=nodes.create_grade(upstream.id_data)
        upstream.id_data.links.new(upstream.outputs['Color'],downstream.inputs['Color']);self.preview(upstream)
        old=self.linear(downstream);nodes.write_values(upstream,{'exposure':.5});latest=self.linear(downstream)
        self.assertNotEqual(old['_scope_key'],latest['_scope_key'])
        incoming=np.broadcast_to(tuple(upstream.inputs['Color'].default_value)[:3],(1,256,3))
        from color_tools.perceptual_grade_core.model import transforms
        to_grade,from_grade=spaces.adapters(nodes.working_space())
        expected=transforms.Grade(nodes.settings(upstream)).apply(incoming@to_grade.T)@from_grade.T@to_grade.T
        np.testing.assert_array_equal(latest['source_rgb'],expected)

    def test_stage_one_refresh_delete_and_unregister_discard_old_work(self):
        for action in (sampling.refresh,self.native_replacement,addon.unregister):
            with self.subTest(action=action):
                node=self.node()
                with self.blocked_linear() as (started,release,_):
                    sampling.get_linear(node,nodes.grading_space(node));jobs.linear_tick();self.assertTrue(started.wait(2))
                    future=jobs._linear_running[3];state=jobs._linear_states[node.as_pointer()]
                    action();self.assertFalse(future.done());self.assertFalse(jobs.linear_pending())
                    self.assertFalse(jobs._linear_states);self.assertFalse(jobs._linear_sources)
                    self.assertFalse(hasattr(jobs,'_linear_executor'))
                    self.assertFalse(bpy.app.timers.is_registered(scheduler.timer_callback(jobs.linear_tick)))
                    if action==self.native_replacement:
                        self.assertEqual(nodes.recovery_tick(),.02)
                        self.assertEqual(nodes.recovery_status()['state'],'retiring')
                        self.assertTrue(any(f is future for _,f in jobs._retiring_cycles))
                    release.set();future.result(timeout=10);self.assertIsNone(state['result'])
                    if action==self.native_replacement:self.finish_recovery()
                if action is addon.unregister:addon.register()
        node=self.node();pointer=node.as_pointer()
        with self.blocked_linear() as (started,release,_):
            sampling.get_linear(node,nodes.grading_space(node));jobs.linear_tick();self.assertTrue(started.wait(2))
            future=jobs._linear_running[3];node.id_data.nodes.remove(node);release.set();future.result(timeout=10)
            self.assertIsNone(jobs.linear_tick());self.assertNotIn(pointer,jobs._linear_states)

    def test_request_description_errors_are_visible_before_job_admission(self):
        node=self.node();space=nodes.grading_space(node)
        for kind,describe,request in (('linear','describe_linear',jobs.request_linear),
                                      ('full','describe',jobs.request)):
            with self.subTest(kind=kind):
                with patch.object(sampling,describe,side_effect=ValueError('Missing graph resource')):
                    with self.assertRaisesRegex(ValueError,'Missing graph resource'):
                        request(node,space)
                state=jobs.status(node,kind)
                self.assertEqual(state['state'],'error')
                self.assertEqual(state['error'],'Missing graph resource')
                self.assertFalse(state['available'])
                jobs.retry(node,kind)
                self.assertEqual(jobs.status(node,kind)['state'],'preparing')
                request(node,space)
                self.assertNotEqual(jobs.status(node,kind)['state'],'error')

    def test_stage_one_capture_failure_logs_once_and_refresh_recovers(self):
        node=self.node();space=nodes.grading_space(node)
        with patch.object(sampling,'describe_linear',side_effect=ValueError('Injected unsupported source')):
            with self.assertLogs(jobs.LOG,level='ERROR') as logs:
                with self.assertRaisesRegex(ValueError,'unsupported source'):sampling.get_linear(node,space)
            self.assertEqual(jobs.status(node,'linear')['state'],'error')
            self.assertIn('unsupported source',jobs.status(node,'linear')['error'])
            self.assertEqual(len(logs.records),1);self.assertIsNone(logs.records[0].exc_info)
            self.assertIn('Traceback (most recent call last)',logs.records[0].getMessage())
            with self.assertNoLogs(jobs.LOG,level='ERROR'):
                for _ in range(3):
                    with self.assertRaisesRegex(ValueError,'unsupported source'):sampling.get_linear(node,space)
        self.assertIsNone(sampling.get_linear(node,space));self.assertNotIn(node.as_pointer(),sampling._errors)
        with patch.object(sampling,'source_samples',side_effect=OSError('Injected linear readback error')):
            sampling.get_linear(node,space)
            with self.assertLogs(jobs.LOG,level='ERROR'):jobs.linear_tick()
            with self.assertNoLogs(jobs.LOG,level='ERROR'):
                for _ in range(3):sampling.get_linear(node,space);jobs.linear_tick()
        sampling.refresh();self.assertIsNotNone(self.linear(node))

    def test_full_scope_capture_runs_without_waiting_for_final_lut(self):
        node=self.node();space=nodes.grading_space(node)
        nodes.write_chromatic(node,{'global_gain':.2})
        with patch.object(lut,'scope_signal',side_effect=AssertionError('Requested final LUT')):
            self.assertIsNone(sampling.get(node,space,(1,False)))
            jobs.tick()
            self.assertIsNotNone(jobs._running)
            result=wait_for_scopes(node,(1,False))
        self.assertEqual(result['_scope_provenance'],())
        self.assertEqual(result['_scope_key'],sampling.describe(node,space,(1,False))['key'])

    def test_snapshot_parity_readonly_results_and_comparison(self):
        node=self.node();space=nodes.grading_space(node)
        nodes.write_values(node,{'exposure':.2})
        nodes.write_tone(node,{'input_midtones':42})
        nodes.write_chromatic(node,{'global_gain':.3})
        image=bpy.data.images.new('Scope parity',width=8,height=8,float_buffer=True,alpha=True)
        image.colorspace_settings.name='Non-Color';image.alpha_mode='CHANNEL_PACKED'
        rgba=np.random.default_rng(917).uniform(.01,1,(8,8,4)).astype('f4')
        rgba[0,0,3]=0;rgba[0,1,:3]=[-.01,.4,.7]
        image.pixels.foreach_set(rgba.ravel());image.update()
        source=node.id_data.nodes.new('CompositorNodeImage');source.image=image
        comparison=node.id_data.nodes.new('CompositorNodeRGB');comparison.outputs[0].default_value=(.3,.2,.6,.7)
        node.id_data.links.new(source.outputs['Image'],node.inputs['Color'])
        node.id_data.links.new(comparison.outputs[0],node.inputs[reference.SOCKET])
        wait_for_scopes(node)
        view=(2,True);expected=self.analyze_active(node,view)
        capture=sampling.capture
        def on_main(spec,*args,**kwargs):
            self.assertIs(current_thread(),main_thread());return capture(spec,*args,**kwargs)
        sampling.refresh()
        with patch.object(sampling,'capture',side_effect=on_main) as captured, \
             patch.object(scope_analysis,'evaluate_samples',side_effect=AssertionError('Foreground analysis ran')):
            actual=wait_for_scopes(node,view)
        self.assertGreater(captured.call_count,0)
        self.assert_active_display(actual,expected)
        result=actual['_color'];expected_color=expected['_color']
        np.testing.assert_array_equal(result['neutral']['center'],expected_color['neutral']['center'])
        self.assertNotIn('mean',result['neutral'])
        self.assertIs(result['_base'],actual)
        self.assertIsNotNone(actual['_comparison_selected'])
        self.assertIs(reference.get(node,actual),actual['_comparison'])
        self.assertIs(reference.selected(node,actual),actual['_comparison_selected'])
        with self.assertRaises(TypeError):actual['_color']=None
        with self.assertRaises(ValueError):result['neutral']['center'][0]=1
        reference.toggle(node)
        self.assertIsNone(reference.get(node,actual))

    def test_publication_reuses_stage_one_and_two_cache(self):
        node=self.node(); executor=ScopeExecutor()
        with patch.object(jobs,'_submit',executor):
            wait_for_scopes(node)
            nodes.write_chromatic(node,{'global_gain':.2});self.preview(node)
            with patch.object(scope_analysis,'evaluate_samples',side_effect=AssertionError('Unchanged base was recomputed')):
                result=wait_for_scopes(node)
        expected=scope_analysis.evaluate_snapshot(executor.snapshots['scope_full'][-1],OrderedDict())
        self.assert_scope_display(result,expected)
        self.assertNotIn('grade_output_rgb',result)

    def test_stage_two_skips_chromatic_work_and_promotes_cached_appearance(self):
        node=self.node();space=nodes.grading_space(node);executor=ScopeExecutor()
        nodes.write_tone(node,{'input_midtones':42})
        with patch.object(nodes,'read_chromatic',side_effect=AssertionError('Stage 2 read Stage 3 controls')):
            spec=sampling.describe(node,space,('tone',))
        sampling.release(spec)
        with patch.object(jobs,'_submit',executor):
            with patch.object(color_math,'evaluate_all',side_effect=AssertionError('Stage 2 ran Stage 3')), \
                 patch.object(color_math,'input_analysis_cache',side_effect=AssertionError('Stage 2 selected chromatic samples')):
                early=wait_for_scopes(node,('tone',))
            self.assertNotIn('_colors',early)
            nodes.write_chromatic(node,{'global_gain':.4})
            with patch.object(jobs,'_submit',side_effect=AssertionError('Stage 3 edit invalidated Stage 2')):
                self.assertIs(sampling.get_tone(node,space),early)
                self.assertIsNone(jobs.tick())
            with patch.object(scope_analysis,'evaluate_samples',side_effect=AssertionError('Stage 3 recomputed Stage 2')):
                late=wait_for_scopes(node)
            for stage in ('before','after'):
                for field in early[stage]:
                    np.testing.assert_array_equal(early[stage][field],late[stage][field])
        self.assertEqual(len(executor.snapshots['scope_full']),2)

    def test_upstream_matrix_only_edit_invalidates_analytical_snapshot(self):
        upstream=self.node();downstream=nodes.create_grade(upstream.id_data)
        upstream.id_data.links.new(upstream.outputs['Color'],downstream.inputs['Color'])
        self.preview(upstream);self.preview(downstream)
        old=wait_for_scopes(downstream);image=lut.image_for(upstream)
        old_analysis=self.analyze_full(downstream)
        nodes.write_values(upstream,{'exposure':.5})
        self.assertEqual(lut.image_for(upstream),image)
        latest=wait_for_scopes(downstream)
        self.assertNotEqual(old['_scope_key'],latest['_scope_key'])
        incoming=np.broadcast_to(tuple(upstream.inputs['Color'].default_value)[:3],(1,256,3))
        from color_tools.perceptual_grade_core.model import transforms
        spaces = _component('graph.spaces')
        to_grade,from_grade=spaces.adapters(nodes.working_space())
        expected=transforms.Grade(nodes.settings(upstream)).apply(incoming@to_grade.T)@from_grade.T
        analysis=self.analyze_full(downstream)
        np.testing.assert_array_equal(analysis['source_rgb'],expected)
        self.assertGreater(np.max(abs(analysis['source_rgb']-old_analysis['source_rgb'])),.01)
        self.assert_scope_display(latest,analysis)

    def test_source_and_view_changes_reject_old_result(self):
        node=self.node();space=nodes.grading_space(node)
        with self.blocked_analysis() as (started,release,snapshots):
            sampling.get(node,space);jobs.tick();self.assertTrue(started.wait(2))
            old_state=jobs._states[node.as_pointer()]
            source=node.id_data.nodes.new('CompositorNodeRGB');source.outputs[0].default_value=(.7,.1,.2,1)
            node.id_data.links.new(source.outputs[0],node.inputs['Color'])
            self.assertIsNone(sampling.get(node,space))
            release.set();base=wait_for_scopes(node)
            self.assertIsNone(old_state['result'])
            expected=scope_analysis.evaluate_snapshot(snapshots[-1],OrderedDict())
            np.testing.assert_allclose(expected['source_rgb'][0,0],[.7,.1,.2],atol=3e-8,rtol=0)
            self.assert_scope_display(base,expected)
        color_result=sampling.get(node,space,(1,False))
        self.assertIsNone(color_result)
        color_result=wait_for_scopes(node,(1,False))
        self.assertEqual(set(color_result['_active_colors']),{'1:jc'})
        self.assertNotIn('_colors',color_result)
        self.assertNotIn('weights',color_result['_color'])

    def test_deleted_node_and_stack_entry_discard_results(self):
        node=self.node();space=nodes.grading_space(node);pointer=node.as_pointer()
        with self.blocked_analysis() as (started,release,snapshots):
            sampling.get(node,space);jobs.tick();self.assertTrue(started.wait(2))
            node.id_data.nodes.remove(node);release.set()
            self.pump(lambda:jobs._running is None)
            self.assertNotIn(pointer,jobs._states)
        tree=bpy.data.node_groups.new('Stack scopes','CompositorNodeTree')
        stack=sequence(tree,[grade_data()]);stack.inputs['Color'].default_value=(.2,.3,.4,1.)
        self.preview(stack)
        target=editing.Target(stack,stack.pg_stack_entries[0])
        base=wait_for_scopes(target,(1,False))
        # Stack inspector values are in canonical grading RGB, not native AP1.
        spaces = _component('graph.spaces')
        to_grade=spaces.adapters(nodes.working_space())[0]
        incoming=np.broadcast_to(tuple(stack.inputs['Color'].default_value)[:3],(1,256,3))
        native=lut.evaluate_signal(incoming,lut.installed_signal(stack))@to_grade.T
        expected=self.analyze_full(target,(1,False))
        np.testing.assert_array_equal(expected['stack_output_rgb'],native)
        self.assert_active_display(base,self.analyze_active(target,(1,False)))
        self.assertNotIn('linear_vectorscope',base)
        nodes.write_values(target,{'exposure':.2})
        with self.blocked_analysis() as (started,release,snapshots):
            sampling.get(target,nodes.grading_space(target));jobs.tick();self.assertTrue(started.wait(2))
            pointer=target.as_pointer();stack.pg_stack_entries.remove(0);release.set()
            self.pump(lambda:jobs._running is None)
            self.assertNotIn(pointer,jobs._states)

    def test_refresh_reload_unregister_do_not_wait_or_publish_old_work(self):
        for action in (sampling.refresh,self.native_replacement,addon.unregister):
            with self.subTest(action=action):
                node=self.node();space=nodes.grading_space(node)
                with self.blocked_analysis() as (started,release,snapshots):
                    sampling.get(node,space);jobs.tick();self.assertTrue(started.wait(2))
                    future=jobs._running[3];old_state=jobs._states[node.as_pointer()]
                    action()
                    self.assertFalse(future.done());self.assertIsNone(jobs._running)
                    self.assertFalse(jobs._states)
                    self.assertFalse(bpy.app.timers.is_registered(scheduler.timer_callback(jobs.tick)))
                    if action==self.native_replacement:
                        self.assertEqual(nodes.recovery_tick(),.02)
                        self.assertEqual(nodes.recovery_status()['state'],'retiring')
                        self.assertTrue(any(f is future for _,f in jobs._retiring_cycles))
                    release.set();future.result(timeout=10)
                    self.assertIsNone(old_state['result'])
                    if action==self.native_replacement:self.finish_recovery()
                    self.assertIsNone(jobs.tick())
                if action is addon.unregister:addon.register()

    def test_capture_errors_log_once_and_refresh_recovers(self):
        node=self.node();space=nodes.grading_space(node)
        with patch.object(sampling,'source_samples',side_effect=OSError('Injected readback error')):
            self.assertIsNone(sampling.get(node,space))
            with self.assertLogs(jobs.LOG,level='ERROR') as logs:jobs.tick()
            self.assertEqual(len(logs.records),1);self.assertIsNone(logs.records[0].exc_info)
            self.assertIn('Traceback (most recent call last)',logs.records[0].getMessage())
            self.assertIsNone(jobs._running)
            with self.assertNoLogs(jobs.LOG,level='ERROR'):
                for _ in range(3):self.assertIsNone(sampling.get(node,space));jobs.tick()
        sampling.refresh();self.assertIsNotNone(wait_for_scopes(node))
