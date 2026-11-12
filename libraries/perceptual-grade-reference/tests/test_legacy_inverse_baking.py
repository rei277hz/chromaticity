"""Legacy capacity-kernel inverse fidelity and raw handoffs.

These tests deliberately exercise the unchanged production .4*capacity kernel,
not the analytic reference crossover.
"""
from dataclasses import replace
from unittest.mock import patch
import unittest
import numpy as np
from color_tools.perceptual_grade_reference.model import Settings,LinearSettings
from tests.reference.legacy_capacity import LegacyCapacityModel, LegacyCapacityStack, LegacyCapacityBakeStack as BakeStack
from color_tools.perceptual_grade_reference.grading import ToneSettings
from color_tools.perceptual_grade_reference.grading import ColorSettings
from color_tools.perceptual_grade_core.model.tonal_web import WebSettings
from color_tools.perceptual_grade_reference.responses import GAMMA,INVERSE,eccentricity
from color_tools.perceptual_grade_reference.stack import nonlinear_inverse
from color_tools.perceptual_grade_core.model.bake_inverse import TOLERANCE
from color_tools.perceptual_grade_core.model import bake_inverse
from color_tools.perceptual_grade_core.model import tone_table


def mixed():
    return Settings(color=ColorSettings(global_gain=.15,web=WebSettings(
        hue_degrees=((0.,)*6,(3.,-2.,1.,-1.,2.,-3.),(1.,)*6,(0.,)*6),
        log_chroma=((0.,)*6,(.02,-.01,0.,.01,-.02,0.),(0.,)*6,(0.,)*6),
        log_scale=((0.,)*6,(.01,0.,-.01,0.,.01,0.),(0.,)*6,(0.,)*6)),
        adaptance=((0.,0.),(0.,0.),(0.,.01),(0.,0.)),
        lightness=((0.,0.,0.,0.),(0.,.1,0.,0.),(0.,0.,0.,0.),(0.,0.,0.,0.))))


def reachable_web_case():
    """Moderate in-cube sources spanning tones for a full seven-handle grade."""
    settings=Settings(tone=ToneSettings(input_nits=(0.,7.,45.,203.,1000.)),
        color=ColorSettings(global_gain=.1,adaptance=((.3,-.2),(-.2,.3),(.2,.1),(-.1,.2)),
            lightness=((.1,-.2,.02,-.01),)*4,chroma=((.03,-.02,.01,-.01),)*4,
            web=WebSettings(
                hue_degrees=((3.,-2.,1.,-1.,2.,-3.),(-2.,3.,-1.,2.,-3.,1.),(2.,)*6,(-1.,)*6),
                log_chroma=((.05,-.03,.02,-.04,.03,-.02),(-.03,.02,-.01,.03,-.02,.04),(.03,)*6,(-.02,)*6),
                log_scale=((.03,-.02,.01,0.,-.03,.02),(-.02,.03,0.,-.01,.02,-.03),(.02,)*6,(-.01,)*6))))
    directions=np.array([[.3,.5,.7],[.7,.4,.2],[.2,.7,.4],[.6,.3,.6],[.6,.6,.3],[.3,.6,.6]],dtype='f4')
    source=(np.array([.02,.2,2.,20.,200.,1000.],dtype='f4')[:,None,None]*directions).reshape(-1,3)
    return settings,source


class LegacyInverseBakingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base=BakeStack([Settings()],['INVERSE'],hk_guard=False);cls.table=cls.base.table
        cls.points=np.array([[.1,.2,.3],[.7,.2,.1],[.02,.08,.4],[0,0,0]],dtype='f4')

    def stack(self,settings,directions):return BakeStack(settings,directions,self.table,hk_guard=False)

    def test_raw_grade_exceeds_response_pole_without_an_extra_guard(self):
        model=LegacyCapacityModel(Settings(color=ColorSettings(global_gain=10)))
        original=model.enter_native(np.array([[0.,.2,0.],[.2,0.,0.]]))
        with patch('tests.reference.legacy_capacity.hk_guard',side_effect=AssertionError('Guarded during grade')):
            raw=model.grade_state(original)
        np.testing.assert_array_equal(raw.q[:,0],original.q[:,0])
        np.testing.assert_array_equal(raw.q[:,1:],original.q[:,1:]*1024)
        ja=raw.ja;neutral=model.aw*np.sign(ja)*(abs(ja)/100)**(1/GAMMA)/3.05
        angle=np.arctan2(raw.q[:,2],raw.q[:,1])
        responses=neutral[:,None]+(raw.q[:,1:]*(model.aw/(1204*eccentricity(angle)))[:,None])@INVERSE[:,1:].T
        self.assertGreater(float(np.max(abs(responses))),400)
        self.assertTrue(np.isfinite(model.release_state(raw,guard=True)).all())

    def test_legacy_context_repairs_only_at_export_in_both_representations(self):
        settings=Settings(color=ColorSettings(global_gain=3.,
            web=WebSettings(log_scale=((.3,)*6,)*4)))
        model=LegacyCapacityModel(settings)
        source=self.points.astype(float)
        entered=model.enter_native(source)
        raw=model.grade_state(entered)
        self.assertTrue(np.any(raw.energy<0))
        np.testing.assert_array_equal(raw.reference_energy,entered.energy)
        self.assertFalse(model.color.hk_guard)
        output=model.release_state(raw,guard=True)
        np.testing.assert_allclose(output,model.forward_native(source),rtol=3e-12,atol=3e-13)
        model.vector_controls=False
        scaled=model.grade_state(entered)
        np.testing.assert_allclose(np.asarray(scaled.q,float),raw.q,rtol=3e-13,atol=3e-12)
        np.testing.assert_allclose(np.asarray(scaled.energy,float),raw.energy,rtol=3e-13,atol=3e-10)
        np.testing.assert_allclose(model.release_state(scaled,guard=True),output,rtol=4e-12,atol=3e-13)
        np.testing.assert_allclose(model.forward_native(source),output,rtol=4e-12,atol=3e-13)

    def test_legacy_stack_constructs_legacy_models_and_display_order(self):
        settings=Settings(color=ColorSettings(web=WebSettings(
            log_chroma=((.8,)*6,)*4,log_scale=((.4,)*6,)*4)))
        stack=LegacyCapacityStack([settings])
        model=stack.models[0]
        self.assertIsInstance(model,LegacyCapacityModel)
        from color_tools.perceptual_grade_core.model.hk_guard import guard
        for row in range(4):
            color=model.color;raw=color.warp_targets(row)
            reference=np.r_[color.web.geometry.anchors[row]**2,color.web.geometry.energy[row]]
            q,e=guard(raw.q,raw.energy,reference)
            displayed=color.guarded_warp_targets(row)
            np.testing.assert_array_equal(displayed.q,q)
            np.testing.assert_array_equal(displayed.energy,e)
        np.testing.assert_allclose(stack.apply_native(self.points.astype(float)),
                                   model.forward_native(self.points.astype(float)),rtol=3e-12,atol=3e-13)

    def test_raw_inverse_against_independent_float64_oracle(self):
        for settings in (Settings(color=ColorSettings(global_gain=10)),mixed(),
                         Settings(tone=ToneSettings(input_nits=(0.,7.,45.,203.,1000.)),color=ColorSettings(global_gain=.2))):
            with self.subTest(settings=settings):
                stack=self.stack([settings],['INVERSE']);k=stack.kernels[0];solver=stack.solvers[0]
                source=self.points[:2];raw=k.grade(k.tone_state(k.enter(source)))
                actual=solver.evaluate(raw,True)
                model=stack.models[0];target=model.grade_state(model.enter_native(source.astype(float)))
                expected,error=nonlinear_inverse(model,target,True)
                self.assertLess(float(error.max()),2e-8)
                self.assertTrue(np.all(actual[:,3]<=TOLERANCE),actual)
                difference=np.max(abs(actual[:,:3]-expected),axis=-1)
                self.assertTrue(np.all(difference<=np.maximum(.001*np.max(abs(expected),axis=-1),1e-7)),(actual,expected))

    def test_full_web_raw_inverse_recovers_known_in_cube_sources(self):
        settings,source=reachable_web_case()
        stack=BakeStack([settings],['INVERSE'],self.table,hk_guard=True)
        solver=stack.solvers[0];k=solver.kernel
        target=k.grade(k.tone_state(k.enter(source)))
        # Calling the solver directly excludes matching-Stack cancellation.
        with patch.object(bake_inverse,'minimize',wraps=bake_inverse.minimize) as searched:
            result=solver.evaluate(target,True)
        self.assertEqual(searched.call_count,1)
        self.assertTrue(np.all(result[:,3]<=TOLERANCE),result)
        np.testing.assert_allclose(result[:,:3],source,rtol=.001,atol=1e-7)
        np.testing.assert_array_equal(result[:,3],np.max(abs(solver.residual(result[:,:3],target,True)),axis=1))

    def test_directional_controls_and_probe_batching_preserve_inverse_results(self):
        # Exercise the full orientation-dependent residual as well as the
        # optimized isotropic case, including black and both cube boundaries.
        base=mixed()
        directional=replace(base,color=replace(base.color,
            lightness=((0.,0.,.03,-.02),(0.,.1,.02,0.),(0.,0.,0.,0.),(0.,0.,0.,0.)),
            chroma=((0.,0.,0.,0.),(0.,0.,.01,-.01),(0.,0.,0.,0.),(0.,0.,0.,0.))))
        points=np.concatenate((self.points,np.array([[1e-8,2e-8,0],[0,1,0],[1024,0,1024]],dtype='f4')))
        for settings in (base,directional):
            solver=self.stack([settings],['INVERSE']).solvers[0];k=solver.kernel
            self.assertEqual(bool(k.directional_drivers),settings is directional)
            for raw in (False,True):
                target=k.grade(k.tone_state(k.enter(points))) if raw else k.evaluate(points)
                solver.probe_batch=False
                expected=solver.evaluate(target,raw)
                solver.probe_batch=True
                actual=solver.evaluate(target,raw)
                np.testing.assert_array_equal(actual,expected)
                validated=target if raw else solver.repair(target)
                np.testing.assert_array_equal(actual[:,3],np.max(abs(solver.residual(actual[:,:3],validated,raw)),axis=1))

    def test_black_forward_and_precomputed_validation_agree(self):
        settings=(Settings(),mixed(),replace(mixed(),
            tone=ToneSettings(input_nits=(.01,1.,90.,400.,4000.),fit=-2),
            color=ColorSettings(global_gain=10.,lightness=((20.,-15.,8.,-6.),)*4,
                chroma=((1.,-2.,.5,-.25),)*4,web=WebSettings(hue_degrees=((30.,)*6,(-40.,)*6,(50.,)*6,(-60.,)*6)),adaptance=((15.,-10.),)*4)))
        for setting in settings:
            solver=self.stack([setting],['INVERSE']).solvers[0];k=solver.kernel
            black=np.zeros_like(self.points)
            raw=k.grade(k.tone_state(k.enter(black)))
            np.testing.assert_array_equal(raw,0.)
            np.testing.assert_array_equal(k.export(raw),0.)
            for appearance in (False,True):
                target=k.grade(k.tone_state(k.enter(self.points))) if appearance else self.points
                expected=solver.residual(black,target,appearance)
                with (patch.object(k,'enter',side_effect=AssertionError('Repeated black forward')),
                      patch.object(k,'grade',side_effect=AssertionError('Repeated black forward')),
                      patch.object(k,'export',side_effect=AssertionError('Repeated black forward'))):
                    actual=solver.residual(black,target,appearance,output=np.zeros(target.shape[-1],dtype='f4'))
                np.testing.assert_array_equal(actual,expected)

    def test_prior_import_and_tone_are_reused_without_changing_raw_target(self):
        setting=replace(mixed(),tone=ToneSettings(input_nits=(0.,7.,45.,203.,1000.)))
        solver=self.stack([setting],['INVERSE']).solvers[0];k=solver.kernel
        for appearance in (False,True):
            target=k.grade(k.tone_state(k.enter(self.points)))
            if not appearance:target=k.export(target)
            prior=np.clip(k.export(target),0,1024) if appearance else solver.repair(target)
            active=np.max(abs(solver.residual(prior,target,appearance)),axis=1)>solver.acceptance_limit(target,appearance)
            self.assertTrue(np.any(active));seen=[];reduced=solver.reduced
            def record(x,wanted,output=False,scale=None):
                if appearance:
                    self.assertTrue(np.all(np.any(np.all(wanted[:,None,:]==target[None,:,:],axis=-1),axis=1)))
                seen.append(len(wanted))
                return reduced(x,wanted,output,scale)
            with (patch.object(k,'enter',wraps=k.enter) as entered,
                  patch.object(k,'tone_state',wraps=k.tone_state) as toned,
                  patch.object(solver,'reduced',side_effect=record)):
                actual=solver.evaluate(target,appearance)
            self.assertTrue(seen)
            # Only the prior and final searched candidate need a forward import/tone.
            self.assertEqual(entered.call_count,2);self.assertEqual(toned.call_count,2)
            self.assertEqual(sum(len(call.args[0]) for call in entered.call_args_list),len(target)+int(active.sum()))
            np.testing.assert_array_equal(entered.call_args_list[0].args[0],prior)
            np.testing.assert_array_equal(actual[:,3],np.max(abs(solver.residual(actual[:,:3],target,appearance)),axis=1))

    def test_minimize_preserves_original_lane_ids_and_stalled_lane_budget(self):
        # Lane0 already solves the residual; lane1 solves on its first trial;
        # lane2 is constant and must retain the full budget. The controlled
        # step isolates bookkeeping from the separately tested linear solve.
        seed=np.zeros((3,2),dtype='f4');calls=[]
        def residual(x,ids):
            calls.append(ids.copy());value=x.copy()
            value[ids==1,0]-=1;value[ids==2]=np.array([1.,0.],dtype='f4')
            return value
        with patch.object(bake_inverse,'normal_step',side_effect=lambda jac,r,damping:r.copy()) as step:
            actual=bake_inverse.minimize(residual,seed,np.full(2,-10,dtype='f4'),np.full(2,10,dtype='f4'),4)
        np.testing.assert_array_equal(actual,[[0,0],[1,0],[0,0]])
        self.assertEqual(step.call_count,4)
        self.assertEqual([len(call.args[1]) for call in step.call_args_list],[2,1,1,1])
        np.testing.assert_array_equal(calls[0],[0,1,2])
        np.testing.assert_array_equal(calls[1],np.tile([1,2],4))
        np.testing.assert_array_equal(calls[2],[1,2])
        self.assertTrue(all(np.array_equal(ids,[2]) for ids in calls[3:]))

    def test_chroma_toe_roundtrip_monotonicity_and_c2_join(self):
        ratios=np.array([0,.001,.125,.5,1,2,100],dtype='f4')
        scales=np.array([bake_inverse.CHROMA_TOE_MIN,1e-12,.01,2],dtype='f4')
        logs=np.log(ratios,out=np.full_like(ratios,-np.inf),where=ratios>0)
        logscale=np.log(scales)[:,None]
        encoded=bake_inverse.chroma_encode(logs+logscale,logscale)
        expected=np.array([0,.0019995,.2421875,.875,1.5,1.5+np.log(2),1.5+np.log(100)])
        np.testing.assert_allclose(encoded,np.broadcast_to(expected,encoded.shape),rtol=8e-6,atol=1e-7)
        self.assertTrue(np.all(np.diff(encoded,axis=1)>0))
        decoded=bake_inverse.chroma_decode(encoded,logscale)
        np.testing.assert_array_equal(decoded[:,0],0)
        np.testing.assert_allclose(decoded,scales[:,None]*ratios,rtol=1e-5,atol=np.finfo('f4').smallest_subnormal*2)
        # Finite differences on either side approach the same first and
        # second derivatives at normalized chroma1: ψ'=1 and ψ''=-1.
        h=.02;ratio=np.array([1-2*h,1-h,1,1+h,1+2*h],dtype='f4')
        values=bake_inverse.chroma_encode(np.log(ratio),np.float32(0)).astype(float)
        left=(3*values[2]-4*values[1]+values[0])/(2*h)
        right=(-3*values[2]+4*values[3]-values[4])/(2*h)
        np.testing.assert_allclose([left,right],1,rtol=0,atol=.001)
        np.testing.assert_allclose([(values[2]-2*values[1]+values[0])/h**2,
                                   (values[4]-2*values[3]+values[2])/h**2],-1,rtol=0,atol=.05)

    def test_chroma_scale_handles_signed_zero_height_and_extreme_targets(self):
        maximum=np.finfo('f4').max
        target=np.array([[0,0,0,0],[0,.03,.04,0],[0,0,0,-33],[-np.sqrt(66),0,0,0],
                         [maximum,maximum,-maximum,-maximum]],dtype='f4')
        with np.errstate(over='raise',invalid='raise',divide='raise'):
            scale=bake_inverse.chroma_scale(target)
            zero=bake_inverse.chroma_encode(np.full(len(target),-np.inf,dtype='f4'),np.log(scale))
            decoded=bake_inverse.chroma_decode(zero,np.log(scale))
        np.testing.assert_allclose(scale,[bake_inverse.CHROMA_TOE_MIN,.05,.5,1,2],rtol=2e-7,atol=0)
        np.testing.assert_array_equal(zero,0);np.testing.assert_array_equal(decoded,0)

    def test_chroma_decode_preserves_legacy_bits_at_join_and_extreme_scales(self):
        # Frozen from the pre-selective np.where decoder with pinned NumPy2.5.3.
        # Inputs are log(tiny), log(1e-12), log(2), and 0, join±1ULP, join, 3.
        logscale=np.array([0xc2aeac50,0xc1dd0c55,0x3f317218],dtype='u4').view('f4')[:,None]
        coordinate=np.array([0,0x3fbfffff,0x3fc00000,0x3fc00001,0x40400000],dtype='u4').view('f4')
        expected=np.array([[0,0x007fffe6,0x007fffe6,0x007fffe6,0x018f69e2],
                           [0,0x2b8cbcc8,0x2b8cbcc9,0x2b8cbcc9,0x2c9daf73],
                           [0,0x3fffffff,0x40000000,0x40000002,0x410f69ff]],dtype='u4')
        actual=bake_inverse.chroma_decode(coordinate,logscale)
        self.assertEqual(actual.dtype,np.dtype('f4'))
        np.testing.assert_array_equal(actual.view('u4'),expected)
        for row,scale in zip(expected,logscale[:,0]):
            for bits,value in zip(row,coordinate):
                scalar=bake_inverse.chroma_decode(value,scale)
                self.assertEqual(scalar.shape,())
                np.testing.assert_array_equal(scalar.view('u4'),bits)
        empty=bake_inverse.chroma_decode(np.empty((0,5),dtype='f4'),np.float32(0))
        self.assertEqual(empty.shape,(0,5));self.assertEqual(empty.dtype,np.dtype('f4'))

    def test_chroma_decode_preserves_legacy_scalar_promotions(self):
        # Same legacy capture: Python scalars and NumPy arrays deliberately have
        # different promotion rules; integer coordinates must not truncate C.
        cases=((0,0,0),(1,0,0x3f15f61a),(1,np.float32(.1),0x3f25bba0),
               (1.5000001,np.float32(.1),0x3f8d763f),(3.1,np.float32(.1),0x40af2a94),
               (np.array([0,1,2,3],dtype='i4'),np.float32(.1),[0,0x3f25bba0,0x3fe93b30,0x409e7f3e]),
               (np.array([0,1,2,3],dtype='f4'),np.float32(.1),[0,0x3f25bb9f,0x3fe93b31,0x409e7f3e]),
               (np.array([0,.25,1,1.5,1.5000001,2.4,3.1],dtype='f4'),.1,
                [0,0x3e122eba,0x3f25bb9f,0x3f8d763e,0x3f8d763f,0x402df855,0x40af2a92]),
               (2.4,np.array([-.7,.1,.8],dtype='f4'),[0x3f9c56ed,0x402df855,0x40af2a94]))
        for coordinate,logscale,expected in cases:
            with self.subTest(coordinate=coordinate,logscale=logscale):
                actual=bake_inverse.chroma_decode(coordinate,logscale)
                self.assertEqual(actual.dtype,np.dtype('f4'))
                np.testing.assert_array_equal(actual.view('u4'),np.asarray(expected,dtype='u4'))

    def test_minimize_keeps_per_target_bounds_after_lanes_finish(self):
        seed=np.zeros((3,2),dtype='f4');low=np.array([[-1,0],[-2,0],[-3,0]],dtype='f4')
        high=np.array([[1,.1],[2,.2],[3,.3]],dtype='f4')
        wanted=np.array([[0,0],[.1,.1],[8,4]],dtype='f4');calls=[]
        def residual(x,ids):
            self.assertTrue(np.all(x>=low[ids]));self.assertTrue(np.all(x<=high[ids]))
            calls.append(ids.copy());return x-wanted[ids]
        for batch in (False,True):
            calls.clear()
            with patch.object(bake_inverse,'normal_step',side_effect=lambda jac,r,damping:r.copy()):
                result=bake_inverse.minimize(residual,seed,low,high,4,batch)
            np.testing.assert_array_equal(result,np.array([[0,0],[.1,.1],[3,.3]],dtype='f4'))
            self.assertTrue(any(np.array_equal(ids,[2]) for ids in calls))

    def test_mixed_tone_inverse_recovers_all_neutral_lut_vertices_and_dark_neutrals(self):
        setting=replace(mixed(),tone=ToneSettings(input_nits=(0.,7.,45.,203.,1000.)))
        solver=self.stack([setting],['INVERSE']).solvers[0];k=solver.kernel
        levels=.01*np.expm1(np.linspace(0,np.log1p(1024/.01),65))
        levels=np.r_[levels,np.geomspace(1e-12,1e-2,21)].astype('f4')
        source=np.repeat(levels[:,None],3,axis=1)
        target=k.grade(k.tone_state(k.enter(source)))
        with patch.object(bake_inverse,'minimize',wraps=bake_inverse.minimize) as searched:
            actual=solver.evaluate(target,True)
        self.assertEqual(searched.call_count,1)
        self.assertEqual(searched.call_args.args[4],bake_inverse.ITERATIONS)
        self.assertTrue(np.all(actual[:,3]<=TOLERANCE),actual)
        np.testing.assert_array_equal(actual[0],0)
        np.testing.assert_allclose(actual[:,:3],source,rtol=.001,atol=1e-7)
        np.testing.assert_array_equal(actual[:,3],np.max(abs(solver.residual(actual[:,:3],target,True)),axis=1))

    def test_zero_chroma_is_an_exact_reduced_coordinate(self):
        solver=self.stack([mixed()],['INVERSE']).solvers[0]
        state=np.array([[1,0,0,1]],dtype='f4');target=solver.kernel.grade(state)
        x=np.array([[0,0,0]],dtype='f4')
        with np.errstate(over='raise',invalid='raise',divide='raise'):
            residual=solver.reduced(x,target)
        np.testing.assert_array_equal(residual,0)
        np.testing.assert_array_equal(solver.reduced(x,target,True),state)

    def test_cartesian_reduced_residual_matches_actual_candidate_grade(self):
        # Unequal web corners couple the forward field to all three unknowns.
        settings=Settings(color=ColorSettings(web=WebSettings(hue_degrees=((2.,-3.,4.,-2.,3.,-4.),)*4),global_gain=.25))
        solver=self.stack([settings],['INVERSE']).solvers[0];k=solver.kernel
        source=np.array([[.1,.2,.3],[.7,.2,.1],[.02,.08,.4]],dtype='f4')
        state=k.enter(source);target=k.grade(state);tau=bake_inverse.chroma_scale(target);logtau=np.log(tau)
        x=np.column_stack((np.log(np.sqrt(state[:,3])),bake_inverse.opponent_encode(state[:,1:3],logtau)))
        actual=solver.reduced(x,target)
        rebuilt=solver.reduced(x,target,True)
        predicted=k.grade(rebuilt)
        ja=np.sign(predicted[:,3])*np.sqrt(abs(predicted[:,3]));wanted=np.sign(target[:,3])*np.sqrt(abs(target[:,3]))
        expected=np.column_stack(((predicted[:,0]-target[:,0])/(1+abs(target[:,0])),(ja-wanted)/(1+abs(wanted)),
            bake_inverse.opponent_encode(predicted[:,1:3],logtau)-bake_inverse.opponent_encode(target[:,1:3],logtau)))
        np.testing.assert_array_equal(actual,expected)
        np.testing.assert_allclose(actual,0,rtol=0,atol=2e-6)

    def test_cartesian_opponent_toe_roundtrip_including_neutral(self):
        points=np.array([[0,0],[1e-12,-2e-12],[.02,.03],[-4.,6.],[200.,-400.]],dtype='f4')
        for tau in (1e-10,.01,2.):
            logtau=np.float32(np.log(tau));encoded=bake_inverse.opponent_encode(points,logtau)
            decoded=bake_inverse.opponent_decode(encoded,logtau)
            np.testing.assert_array_equal(encoded[0],0)
            np.testing.assert_array_equal(decoded[0],0)
            np.testing.assert_allclose(decoded,points,rtol=8e-6,atol=1e-18)

    def test_hue_dependent_capacity_inverse_recovers_unequal_hue_handles(self):
        settings=Settings(color=ColorSettings(web=WebSettings(hue_degrees=((3.,-4.,2.,-3.,4.,-2.),)*4),global_gain=.15))
        solver=self.stack([settings],['INVERSE']).solvers[0];k=solver.kernel
        source=np.array([[.1,.2,.3],[.7,.2,.1],[.02,.08,.4],[0,0,0]],dtype='f4')
        raw=k.grade(k.enter(source));actual=solver.evaluate(raw,True)
        self.assertTrue(np.all(actual[:,3]<=TOLERANCE),actual)
        np.testing.assert_allclose(actual[:,:3],source,rtol=.001,atol=1e-7)

    def test_rgb_inverse_reproduces_reachable_targets(self):
        for settings in (Settings(color=ColorSettings(global_gain=.25)),mixed(),
                         Settings(tone=ToneSettings(input_nits=(0.,7.,45.,203.,1000.)))):
            stack=self.stack([settings],['INVERSE']);k=stack.kernels[0]
            target=k.evaluate(self.points);actual=stack.bake_native(target)
            solver=stack.solvers[0];reproduced=k.evaluate(actual[:,:3])
            wanted=k.native(target,solver.canonical);difference=k.native(reproduced-target,solver.canonical)
            limit=np.maximum(.0001*np.max(abs(wanted),axis=-1),.00003)
            self.assertTrue(np.all(np.max(abs(difference),axis=-1)<=limit),(actual,target,reproduced))
            np.testing.assert_array_equal(actual[-1,:3],0)

    def test_rgb_acceptance_is_inclusive_with_absolute_and_relative_limits(self):
        # Neutral RGB is unchanged by the comparison-space matrix. Probe both
        # sides of the 0.3 absolute/relative tolerance threshold, black, and white.
        peak=np.array([0,1e-5,.01,.299,.3,.301,1,1024],dtype='f4')
        target=np.repeat(peak[:,None],3,axis=1)
        limit=np.maximum(np.float32(.0001)*peak,np.float32(.00003))/np.maximum(peak,np.float32(1e-4))
        for settings in (Settings(color=ColorSettings(global_gain=.25)),mixed()):
            solver=self.stack([settings],['INVERSE']).solvers[0]
            # The inclusive boundary must return the prior without entering
            # further candidate validation. One ULP above must continue.
            for error,accepted in ((np.nextafter(limit,np.float32(-np.inf)),True),
                                   (limit,True),(np.nextafter(limit,np.float32(np.inf)),False)):
                residual=np.column_stack((error,np.zeros((len(peak),3),dtype='f4')))
                with patch.object(solver,'residual',side_effect=[residual,AssertionError('Needs candidate validation')]) as counted:
                    if accepted:
                        actual=solver.evaluate(target)
                        np.testing.assert_array_equal(actual[:,:3],target)
                        np.testing.assert_array_equal(actual[:,3],error)
                        self.assertEqual(counted.call_count,1)
                    else:
                        with self.assertRaisesRegex(AssertionError,'Needs candidate validation'):solver.evaluate(target)

    def test_rgb_acceptance_ranks_valid_candidates_by_distance(self):
        solver=self.stack([Settings(color=ColorSettings(global_gain=.25))],['INVERSE']).solvers[0]
        target=np.ones((1,3),dtype='f4');candidate=target*.5
        residuals=[np.array([[e,0,0,0]],dtype='f4') for e in (.01,.00005,.00009)]
        # The prior fails. Black is more accurate, but the direct candidate is
        # closer to the prior and both pass the adopted tolerance.
        with patch.object(solver,'residual',side_effect=residuals) as counted,\
             patch.object(solver.kernel,'export',return_value=candidate):
            actual=solver.evaluate(target)
        self.assertEqual(counted.call_count,3)
        np.testing.assert_array_equal(actual[:,:3],candidate)
        self.assertEqual(actual[0,3],np.float32(.00009))

    def test_raw_acceptance_retains_signed_coordinate_threshold(self):
        solver=self.stack([Settings(color=ColorSettings(global_gain=.25))],['INVERSE']).solvers[0]
        raw=solver.kernel.enter(self.points)
        for error,accepted in ((TOLERANCE,True),(np.nextafter(TOLERANCE,np.float32(np.inf)),False)):
            residual=np.full((len(raw),4),error,dtype='f4')
            with patch.object(solver,'residual',side_effect=[residual,AssertionError('Needs candidate validation')]):
                if accepted:
                    actual=solver.evaluate(raw,True)
                    np.testing.assert_array_equal(actual[:,3],error)
                else:
                    with self.assertRaisesRegex(AssertionError,'Needs candidate validation'):solver.evaluate(raw,True)

    def test_feasible_direct_tone_inverse_reproduces_reachable_targets(self):
        stack=self.stack([Settings(tone=ToneSettings(input_nits=(0.,7.,45.,203.,1000.)))],['INVERSE'])
        k=stack.kernels[0];solver=stack.solvers[0];target=k.evaluate(self.points)
        direct=solver.direct_state(k.enter(target))
        self.assertTrue(solver.feasible(direct).all())
        with patch.object(solver,'residual',wraps=solver.residual) as counted:
            result=solver.evaluate(target)
        self.assertLessEqual(counted.call_count,3)
        self.assertTrue(np.all(result[:,3]<=TOLERANCE))
        np.testing.assert_allclose(result[:,:3],self.points,rtol=.001,atol=1e-7)
        outside=solver.direct_state(k.enter(np.array([[0,1024,1024]],dtype='f4')))
        self.assertFalse(bool(solver.feasible(outside)[0]))

    def test_tone_undo_preserves_small_carried_energy(self):
        stack=self.stack([Settings(tone=ToneSettings(input_nits=(0.,7.,45.,203.,1000.)))],['INVERSE'])
        k=stack.kernels[0];source=self.points[:3]*np.float32(1e-16);entered=k.enter(source)
        recovered=stack.solvers[0].direct_state(k.tone_state(entered))
        np.testing.assert_allclose(recovered[:,3],entered[:,3],rtol=1e-5,atol=0)
        np.testing.assert_allclose(recovered[:,1:3],entered[:,1:3],rtol=1e-5,atol=0)

    def test_prepared_tone_inverse_uses_lookup_and_reproduces_the_curve(self):
        levels=np.geomspace(1e-20,1024,41).astype('f4')
        source=np.column_stack((levels,levels*.5,levels*.25))
        source=np.concatenate((np.zeros((1,3),dtype='f4'),source))
        for tone in (ToneSettings(input_nits=(0.,7.,45.,203.,1000.)),
                     ToneSettings(input_nits=(.01,1.,90.,400.,4000.),fit=-2),
                     ToneSettings(input_nits=(0.,.0001,.01,203.,10000.),fit=3)):
            solver=self.stack([Settings(tone=tone)],['INVERSE']).solvers[0];k=solver.kernel
            target=k.tone_state(k.enter(source))
            self.assertIsInstance(solver.tone_table,tone_table.ToneTable)
            with (patch.object(tone_table._Curve,'inverse',side_effect=AssertionError('Pixel tone root search')),
                  patch.object(solver.tone_table,'evaluate',wraps=solver.tone_table.evaluate) as counted):
                recovered=solver.undo_tone(target)
            self.assertEqual(counted.call_count,1)
            self.assertEqual(len(counted.call_args.args[0]),len(source))
            np.testing.assert_array_equal(recovered[0],0)
            self.assertTrue(np.isfinite(recovered).all())
            np.testing.assert_allclose(k.tone_state(recovered),target,rtol=4e-5,atol=2e-8)

    def test_tone_tables_are_prepared_only_for_inverse_and_shared_by_tone(self):
        setting=replace(mixed(),tone=ToneSettings(input_nits=(0.,7.,45.,203.,1000.)))
        with patch.object(tone_table._Curve,'inverse',side_effect=AssertionError('Unneeded tone table')):
            inactive=self.stack([Settings()],['INVERSE'])
            forward=self.stack([setting],['FORWARD'])
        self.assertIsNone(inactive.solvers[0].tone_table)
        self.assertIsNone(forward.solvers[0].tone_table)
        changed=replace(setting,color=replace(setting.color,global_gain=.2))
        other_tone=replace(setting,tone=replace(setting.tone,input_nits=(0.,7.,42.,203.,1000.)))
        stack=self.stack([setting,setting,changed,other_tone],['FORWARD','INVERSE','INVERSE','INVERSE'])
        self.assertIsNone(stack.solvers[0].tone_table)
        self.assertIs(stack.solvers[1].tone_table,stack.solvers[2].tone_table)
        self.assertIsNot(stack.solvers[1].tone_table,stack.solvers[3].tone_table)
        with patch.object(tone_table._Curve,'inverse',side_effect=AssertionError('Tone table rebuilt during bake')):
            for solver in stack.solvers[1:]:
                actual=solver.evaluate(self.points)
                self.assertTrue(np.isfinite(actual).all())
                np.testing.assert_array_equal(actual[:,3],np.max(abs(solver.residual(actual[:,:3],self.points,False)),axis=1))

    def test_tone_curve_is_independent_of_validation_batch_size(self):
        setting=replace(mixed(),tone=ToneSettings(input_nits=(0.,7.,45.,203.,1000.)))
        k=self.stack([setting],['INVERSE']).kernels[0]
        # This reachable inverse candidate exposed a one-ULP matvec difference
        # when black was excluded from the three-row candidate validation.
        source=np.array([[.12998360395431519,.23579509556293488,.32324358820915222],
                         [.7185615301132202,.2535375952720642,.15163643658161163],
                         [.042891815304756165,.10976753383874893,.35914817452430725]],dtype='f4')
        entered=k.enter(source)
        expected=k.tone_state(entered)
        for count in (1,2,3,4,5,8):
            for row in range(len(entered)):
                batch=np.zeros((count,4),dtype='f4');batch[-1]=entered[row]
                np.testing.assert_array_equal(k.tone_state(batch)[-1],expected[row])

    def test_simple_rgb_and_raw_inverses_validate_at_most_three_candidates(self):
        tone=ToneSettings(input_nits=(0.,7.,45.,203.,1000.))
        for settings in (Settings(tone=tone),Settings(color=ColorSettings(global_gain=.25)),
                         Settings(color=ColorSettings(global_gain=-1.)),
                         Settings(tone=tone,color=ColorSettings(global_gain=.2))):
            solver=self.stack([settings],['INVERSE']).solvers[0];k=solver.kernel
            self.assertTrue(solver.simple)
            rgb=np.array([[0,1024,1024],[1024,57.23376,.746596],[.1,.2,.3],[0,0,0]],dtype='f4')
            raw=np.concatenate((k.grade(k.tone_state(k.enter(self.points))),
                                np.array([[1e6,1,0,1e12]],dtype='f4')))
            for target,appearance in ((rgb,False),(raw,True)):
                with (self.subTest(settings=settings,appearance=appearance),
                      patch.object(bake_inverse,'minimize',side_effect=AssertionError('Simple inverse entered a numerical search')),
                      patch.object(solver,'residual',wraps=solver.residual) as counted):
                    result=solver.evaluate(target,appearance)
                self.assertLessEqual(counted.call_count,3)
                self.assertLessEqual(sum(len(call.args[0]) for call in counted.call_args_list),3*len(target))
                self.assertTrue(np.isfinite(result).all())
                self.assertTrue(np.all((result[:,:3]>=0)&(result[:,:3]<=1024)))
                np.testing.assert_array_equal(result[:,3],np.max(abs(solver.residual(result[:,:3],target,appearance)),axis=1))

    def test_simple_unreachable_raw_request_returns_best_validated_candidate(self):
        tone=ToneSettings(input_nits=(0.,7.,45.,203.,1000.))
        target=np.array([[1e6,1,0,1e12]],dtype='f4')
        for settings in (Settings(tone=tone),Settings(color=ColorSettings(global_gain=.25)),
                         Settings(color=ColorSettings(global_gain=-1.)),
                         Settings(tone=tone,color=ColorSettings(global_gain=.2))):
            solver=self.stack([settings],['INVERSE']).solvers[0]
            candidates=[];errors=[];residual=solver.residual
            def record(rgb,target,appearance,prepared=None,output=None):
                value=residual(rgb,target,appearance,prepared,output)
                candidates.extend(rgb.copy());errors.extend(np.max(abs(value),axis=1))
                return value
            with self.subTest(settings=settings),patch.object(solver,'residual',side_effect=record):
                result=solver.evaluate(target,True)
            self.assertEqual(len(candidates),3)  # Prior, black, direct analytic candidate.
            self.assertGreater(result[0,3],solver.acceptance_limit(target,True)[0])
            self.assertEqual(result[0,3],min(errors))
            self.assertTrue(any(np.array_equal(result[0,:3],v) for v in candidates))
            np.testing.assert_array_equal(result[:,3],np.max(abs(residual(result[:,:3],target,True)),axis=1))

    def test_general_inverse_stops_at_best_validated_candidate(self):
        settings=replace(mixed(),tone=ToneSettings(input_nits=(0.,7.,45.,203.,1000.)))
        solver=self.stack([settings],['INVERSE']).solvers[0]
        # The cube corner and high raw request still exhaust the search. The
        # formerly failing neutral RGB witness now passes with the zero toe.
        for target,appearance,accepted in ((np.array([[0,1024,1024]],dtype='f4'),False,False),
                                           (np.full((1,3),2.662182331085205,dtype='f4'),False,True),
                                           (np.array([[1e6,1,0,1e12]],dtype='f4'),True,False)):
            candidates=[];errors=[];residual=solver.residual
            def record(rgb,target,appearance,prepared=None,output=None):
                value=residual(rgb,target,appearance,prepared,output)
                candidates.extend(rgb.copy());errors.extend(np.max(abs(value),axis=1))
                return value
            with self.subTest(appearance=appearance),patch.object(solver,'residual',side_effect=record):
                result=solver.evaluate(target,appearance)
            self.assertLessEqual(len(candidates),3)  # Prior, black, one central Stage 3 candidate.
            self.assertEqual(bool(result[0,3]<=solver.acceptance_limit(target,appearance)[0]),accepted)
            self.assertEqual(result[0,3],min(errors))
            self.assertTrue(any(np.array_equal(result[0,:3],v) for v in candidates))
            np.testing.assert_array_equal(result[:,3],np.max(abs(residual(result[:,:3],target,appearance)),axis=1))

    def test_raw_handoff_retains_direct_candidate_without_rgb_refinement(self):
        stack=self.stack([Settings(color=ColorSettings(global_gain=.1)),Settings(color=ColorSettings(global_gain=.2))],['FORWARD','INVERSE'])
        source=np.array([[168.81788635253906,117.71593475341797,9.427742004394531]],dtype='f4')
        k=stack.kernels[0];solver=stack.solvers[1];raw=k.grade(k.enter(source))
        direct=solver.direct_state(raw);self.assertTrue(solver.feasible(direct).all())
        seed=np.clip(solver.kernel.export(direct),0,1024)
        result=solver.evaluate(raw,True)
        np.testing.assert_array_equal(result[:,:3],seed)
        # A direct candidate may remain an approximation; report its actual error.
        residual=np.max(abs(solver.residual(result[:,:3],raw,True)),axis=1)
        np.testing.assert_array_equal(result[:,3],residual)

    def test_matching_pair_cancels_and_endpoint_matrices_stay_outside(self):
        a=mixed();b=replace(a,linear=LinearSettings(exposure=-10.))
        stack=self.stack([a,b],['FORWARD','INVERSE'])
        with patch.object(stack.kernels[0],'grade',side_effect=AssertionError('Matching pair must cancel')):
            np.testing.assert_array_equal(stack.bake_native(self.points)[:,:3],self.points)
        actual=stack.apply_native([[0.,2.,0.],[1024,0,1024]])
        self.assertGreater(actual.max(),1024)
        np.testing.assert_allclose(actual,np.array([[0,2,0],[1024,0,1024]])*1024,rtol=3e-6,atol=.001)

    def test_repaired_input_and_batch_order_independence(self):
        stack=self.stack([Settings(color=ColorSettings(global_gain=-1.))],['INVERSE'])
        target=np.array([[.2,.01,.1],[2.,-.1,1.],[2048,40,1.]],dtype='f4')
        actual=stack.bake_native(target)
        np.testing.assert_array_equal(stack.bake_native(target[::-1])[::-1],actual)
        self.assertTrue(np.isfinite(actual).all())
        self.assertTrue(np.all((actual[:,:3]>=0)&(actual[:,:3]<=1024)))
        with self.assertRaises(ValueError):stack.bake_native([[np.inf,0,0]])

    def test_export_white_tip_is_exact_for_every_chroma(self):
        k=self.base.kernels[0]
        radius=np.linspace(0,1,17,dtype='f4')
        chroma=radius*k.white*k.white/66;angle=radius*6
        appearance=np.column_stack((np.full_like(radius,k.white),chroma*np.cos(angle),
                                    chroma*np.sin(angle),np.full_like(radius,k.white*k.white)))
        np.testing.assert_array_equal(k.export(appearance),1024)

    def test_root_choice_does_not_depend_on_cpu_batch_shape(self):
        stack=self.stack([Settings(color=ColorSettings(global_gain=.25))],['INVERSE'])
        point=np.array([[.04064936935901642,0,1024]],dtype='f4')
        expected=stack.bake_native(point)[0]
        for count in (17,17000):
            samples=np.zeros((count,3),dtype='f4');samples[-1]=point[0]
            np.testing.assert_array_equal(stack.bake_native(samples)[-1],expected)

