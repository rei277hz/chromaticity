from color_tools.perceptual_grade_reference import responses as response_math
from color_tools.perceptual_grade_reference.appearance import encode_cones
"""Independent physical, differential, signed and integration checks."""
from dataclasses import replace
import unittest
from unittest.mock import patch
import numpy as np
from color_tools.perceptual_grade_core.model.selective_adaptance import (
    SelectiveAdaptance, response_transform, response_transform_scaled,
    reach_weight, from_responses, to_responses,
)
from color_tools.perceptual_grade_reference.grading import Tone, ToneSettings, Color, ColorSettings
from color_tools.perceptual_grade_reference.appearance import response_constants
from color_tools.perceptual_grade_reference.responses import State, signed_hk
from color_tools.color_core.scaled import Scalar as S
from color_tools.perceptual_grade_core.model.tonal_web import TonalWeb, WebSettings
from color_tools.perceptual_grade_core.model.saturation import (project, valid, bounded_project,
    bounded_from_linear, bounded_unproject)


class SelectiveAdaptanceTests(unittest.TestCase):
    def setUp(self):
        self.tone=Tone(ToneSettings())
        self.anchors=100*np.asarray(self.tone.target[1:])
        self.aw=response_constants(self.tone.reference)[1]
        self.targets=np.array([[2.,-1.],[-3.,2.],[1.,3.],[-2.,-1.]])
        self.adapt=SelectiveAdaptance(self.targets,self.anchors,self.aw, response_math=response_math)

    def test_exact_physical_cone_gain(self):
        cones=np.geomspace(1e-20,1e20,301)
        def compress(x):
            p=abs(x)**.42
            return np.sign(x)*400*p/(27.13+p)
        for gain in (.05,.5,1.,2.,20.):
            for sign in (-1,1):
                actual=response_transform(compress(sign*cones),gain**.42)
                np.testing.assert_allclose(actual,compress(sign*cones*gain),rtol=8e-15,atol=2e-13)

    def test_total_group_inverse_and_monotonicity(self):
        r=np.unique(np.r_[-np.geomspace(1e-12,1e9,1000),[-400.,0.,400.],np.geomspace(1e-12,1e9,1000)])
        for m in (.01,.3,1.,3.,100.):
            out=response_transform(r,m)
            self.assertTrue(np.all(np.diff(out)>0))
            np.testing.assert_allclose(response_transform(out,1/m),r,rtol=1e-11,atol=3e-10)
            np.testing.assert_allclose(response_transform(out,.7),response_transform(r,.7*m),rtol=2e-13,atol=4e-12)
            for x in (-1e6,-400.0001,-400.,-2.,0.,2.,400.,400.0001,1e6):
                self.assertAlmostEqual(float(response_transform_scaled(S(x),m))/max(1,abs(x)),float(response_transform(x,m))/max(1,abs(x)),places=12)

    def test_boundary_value_slope_and_curvature(self):
        for m in (.25,2.,10.):
            for sign in (-1,1):
                b=sign*400.;d=.005
                f=lambda x:float(response_transform(x,m))
                self.assertEqual(f(b),b)
                left=(3*f(b)-4*f(b-d)+f(b-2*d))/(2*d)
                right=(-3*f(b)+4*f(b+d)-f(b+2*d))/(2*d)
                self.assertAlmostEqual(left,1/m,places=7)
                self.assertAlmostEqual(right,1/m,places=7)
                dl=(2*f(b)-5*f(b-d)+4*f(b-2*d)-f(b-3*d))/d**2
                dr=(2*f(b)-5*f(b+d)+4*f(b+2*d)-f(b+3*d))/d**2
                wanted=sign*2*(1-m)/(400*m*m)
                self.assertAlmostEqual(dl,wanted,places=5)
                self.assertAlmostEqual(dr,wanted,places=5)

    def test_source_saturation_mask(self):
        c=np.array([0.,.1,.25,.5,1.])*100
        v=reach_weight(c,10000.,.25)
        np.testing.assert_allclose(v,1/(1+(c/25)**4),rtol=3e-15)
        self.assertTrue(np.all(reach_weight(c,10000.,.05)<=v))
        self.assertTrue(np.all(v<=reach_weight(c,10000.,1)))
        self.assertEqual(float(reach_weight(1.,0.,.5)),0.)
        self.assertEqual(float(reach_weight(0.,0.,.5)),1.)
        self.assertEqual(float(reach_weight(1e300,1e300,.5)),0.)

    def test_direct_centers_reach_independence_and_all_tone_ja(self):
        h=np.unique(np.r_[np.geomspace(1e-100,1e5,97),self.anchors])
        for sign in (-1,1):
            ja=sign*h;e=ja*abs(ja)
            q=np.column_stack((ja,np.zeros((len(h),2))))
            for reach in (.05,.25,1.):
                adapt=SelectiveAdaptance(self.targets,self.anchors,self.aw,reach, response_math=response_math)
                out,eo=adapt.apply(q,e,h,np.zeros_like(h),e)
                np.testing.assert_array_equal(eo,e)
                self.assertTrue(np.isfinite(out).all())
        for reach in (.05,.25,1.):
            adapt=SelectiveAdaptance(self.targets,self.anchors,self.aw,reach, response_math=response_math)
            q=np.column_stack((self.anchors,np.zeros((4,2))))
            out,e=adapt.apply(q,self.anchors**2,self.anchors,np.zeros(4),self.anchors**2)
            np.testing.assert_allclose(out[:,1:],self.targets,rtol=2e-13,atol=3e-12)

    def test_response_encoding_and_fixed_selector_inverse(self):
        r=np.array([[20.,15.,10.],[-10.,-20.,-30.],[450.,100.,-550.]])
        q,e=from_responses(r,self.aw, response_math=response_math)
        np.testing.assert_allclose(to_responses(q,e,self.aw, response_math=response_math),r,rtol=2e-14,atol=2e-12)
        h=np.array([50.,100.,200.]);c=np.array([1.,10.,30.]);e0=np.array([2000.,6000.,15000.])
        out,eo=self.adapt.apply(q,e,h,c,e0)
        back,be=self.adapt.inverse(out,eo,h,c,e0)
        np.testing.assert_allclose(back,q,rtol=2e-12,atol=2e-10)
        np.testing.assert_allclose(be,e,rtol=3e-12)

    def test_extended_responses_export_only_through_physical_cube(self):
        from unittest.mock import patch
        from color_tools.perceptual_grade_reference.model import Model
        model=Model()
        q,e=from_responses(np.array([[450.,-880.,20.],[-450.,920.,-20.]]),self.aw, response_math=response_math)
        c=np.hypot(q[:,1],q[:,2]);h=np.sqrt(abs(e)+66*c)
        out,stored=self.adapt.apply(q,e,h,c,e)
        self.assertTrue(np.any(abs(to_responses(out,stored,self.aw, response_math=response_math))>=400))
        context=model.boundary
        decoder=type(context).decode
        calls=[]
        def physical_only(ctx,values,energy):
            responses=ctx.responses(values,energy)
            self.assertTrue(np.all(abs(responses)<400))
            calls.append(len(np.atleast_2d(values)))
            return decoder(ctx,values,energy)
        with patch.object(type(context),'decode',physical_only):
            from color_tools.perceptual_grade_core.model.hk_guard import guard
            repaired,energy=guard(out,stored,abs(e))
            rgb=model.release_state(State(repaired,energy),guard=True)
        self.assertTrue(calls)
        self.assertTrue(np.isfinite(rgb).all())
        self.assertTrue(np.all((rgb>=0)&(rgb<=1024)))

    def test_scaled_extremes_and_black(self):
        for exponent in (-1800,-20,0,20,1800):
            ja=S(.7,exponent);c=S(.2,exponent)
            q=[signed_hk(ja,c),c,S()];e=ja*abs(ja)
            h=(ja*ja+66*c)**.5
            out,eo=self.adapt.scaled_apply(q,e,h,c,e)
            self.assertTrue(all(np.isfinite(v.m) for v in [*out,eo]))
        out,e=self.adapt.apply(np.zeros(3),np.asarray(0.),0.,0.,0.)
        np.testing.assert_array_equal(out,0.);self.assertEqual(e,0.)
        for h,c in ((50.,1.),(100.,30.),(10.,3.)):
            ja=np.sqrt(abs(h*h-66*c));e=ja*ja;q=np.array([signed_hk(ja,c),c,0.])
            out,eout=self.adapt.apply(q,np.asarray(e),h,c,e)
            scaled,stored=self.adapt.scaled_apply(q,e,h,c,e)
            np.testing.assert_allclose(list(map(float,scaled)),out,rtol=3e-13,atol=2e-12)
            self.assertAlmostEqual(float(stored)/eout,1.,places=12)

    def test_invalid_center_and_reach(self):
        for target in (np.full((4,2),1e6),np.full((4,2),np.nan)):
            with self.assertRaises(ValueError):SelectiveAdaptance(target,self.anchors,self.aw, response_math=response_math)
        for reach in (0.,.049,1.001,2.,np.inf):
            with self.assertRaises(ValueError):SelectiveAdaptance(self.targets,self.anchors,self.aw,reach, response_math=response_math)
        color=Color(ColorSettings(adaptance=tuple(map(tuple,self.targets))),self.tone,hk_guard=False)
        for row in range(4):
            target=color.warp_targets(row).q[1,1:]+[.1,-.1]
            changed=color.target_settings(row,0,target)
            np.testing.assert_allclose(Color(changed,self.tone,hk_guard=False).warp_targets(row).q[1,1:],target,rtol=2e-12,atol=2e-12)

    def test_exact_folded_corner_target_is_rejected(self):
        # A physically valid cone calibration can still fold its fixed-H a/b
        # projection. An already-matching target must pass the local check too.
        targets=((-47.16643957888335,-29.12423070533272),
                 (42.26228064848024,36.50967340537377),
                 (5.813213485543778,51.183095814575374),
                 (55.10410325750891,-13.3427987554869))
        web=TonalWeb(WebSettings(),self.tone, encoder=encode_cones)
        settings=web.settings_for_target(0,3,[-5.550044051892587,-1.6012204525629576])
        color=Color(ColorSettings(adaptance=targets,adaptance_half_saturation=2**(4*.7612082038878359-4),web=settings),self.tone,hk_guard=False)
        target=color.warp_targets(0).q[4,1:]
        with self.assertRaisesRegex(ValueError,'folded or singular'):
            color.target_settings(0,3,target)

    def test_corner_solve_rejects_nonfinite_intermediates(self):
        web=TonalWeb(WebSettings(),self.tone, encoder=encode_cones)
        with patch.object(self.adapt,'apply',return_value=(np.array([1.,np.nan,0.]),0.)):
            with self.assertRaisesRegex(ValueError,'finite solve domain'):
                self.adapt.target(web,0,0,[1.,0.])

    def test_linear_saturation_projection_signed_zero_and_scaled(self):
        q=np.array([[20.,3.,4.],[-20.,3.,4.],[0.,0.,0.],[-1.,0.,0.],[1.,2.,0.]])
        e=np.array([144.,-144.,0.,-1.,0.])
        points=project(q,e)
        np.testing.assert_allclose(points[:2],[[.25,1/3],[.25,1/3]])
        np.testing.assert_array_equal(points[2:4],0.)
        np.testing.assert_array_equal(valid(q,e),[True,True,True,True,False])
        for scale in (2.**-100,2.**100):
            scaled=q.copy();scaled[:,1:]*=scale
            np.testing.assert_allclose(project(scaled,e*scale*scale),points,equal_nan=True)
        for exponent in (-1800,1800):
            scale=S(1.,exponent)
            actual=project([S(20.),3*scale,4*scale],-144*scale*scale)
            np.testing.assert_allclose(actual,[.25,1/3],rtol=2e-15)

    def test_saturation_centers_and_scale_independent_corner_targets(self):
        settings=ColorSettings(adaptance=tuple(map(tuple,self.targets)))
        for row in range(4):
            color=Color(settings,self.tone,hk_guard=False)
            center=np.array([.03,-.02])
            changed=color.target_saturation_settings(row,-1,center)
            np.testing.assert_allclose(np.asarray(changed.adaptance)[row],self.anchors[row]*center)
            np.testing.assert_allclose(Color(changed,self.tone,hk_guard=False).saturation_targets(row)[0],center,atol=2e-14)
        base=Color(settings,self.tone,hk_guard=False)
        target=base.saturation_targets(1)[1]*1.02+[.001,-.001]
        outcomes=[]
        for stops in (-8.,0.,8.):
            scales=np.zeros((4,6));scales[1,0]=stops
            color=Color(replace(settings,web=WebSettings(log_scale=tuple(map(tuple,scales)))),self.tone,hk_guard=False)
            np.testing.assert_allclose(color.saturation_targets(1),base.saturation_targets(1),rtol=2e-13,atol=2e-14)
            changed=color.target_saturation_settings(1,0,target)
            result=Color(changed,self.tone,hk_guard=False)
            np.testing.assert_allclose(result.saturation_targets(1)[1],target,rtol=2e-12,atol=2e-13)
            self.assertEqual(changed.web.log_scale[1][0],stops)
            outcomes.append(changed.web.log_chroma[1][0])
        np.testing.assert_allclose(outcomes,outcomes[1],rtol=2e-12,atol=2e-13)

    def test_saturation_projection_excludes_nonfinite_energy(self):
        for stored in (np.inf,-np.inf,np.nan):
            for q in ([20.,3.,4.],[0.,0.,0.],[S(20.),S(3.),S(4.)],[S(),S(),S()]):
                self.assertTrue(np.isnan(project(q,stored)).all())
                self.assertFalse(valid(q,stored))
        q=np.array([[20.,3.,4.],[0.,0.,0.],[20.,3.,4.],[20.,3.,4.]])
        energy=np.array([np.inf,-np.inf,np.nan,144.])
        np.testing.assert_array_equal(valid(q,energy),[False,False,False,True])
        # A finite Scalar may represent a point outside float64 display range.
        self.assertFalse(valid([S(20.),S(1.,1800),S()],S(1.)))

    def test_negative_saturation_targets_preserve_local_radial_branch(self):
        # At fixed H, negative-energy C/sqrt(|E|) folds at C=2H²/66.
        # Both sides remain independently usable; dragging never swaps them.
        base=TonalWeb(WebSettings(),self.tone, encoder=encode_cones);row=1;handle=0
        h=base.geometry.anchors[row];angle=base.geometry.angles[row,handle]
        for factor in (1.2,3.):
            c=factor*h*h/66
            web=base.settings_for_target(row,handle,c*np.array([np.cos(angle),np.sin(angle)]))
            color=Color(ColorSettings(web=web),self.tone,hk_guard=False)
            source=color.warp_targets(row);self.assertLess(source.energy[handle+1],0.)
            target=color.saturation_targets(row)[handle+1]*1.005
            changed=color.target_saturation_settings(row,handle,target)
            result=Color(changed,self.tone,hk_guard=False)
            self.assertLess(result.warp_targets(row).energy[handle+1],0.)
            np.testing.assert_allclose(result.saturation_targets(row)[handle+1],target,rtol=2e-12,atol=2e-13)
            radius=result.web.parameters(h)['target_radii'][handle]
            self.assertEqual(radius<2*h*h/66,factor<2)
            bounded=bounded_from_linear(target)
            bounded_settings=color.target_bounded_saturation_settings(row,handle,bounded)
            bounded_result=Color(bounded_settings,self.tone,hk_guard=False)
            self.assertLess(bounded_result.warp_targets(row).energy[handle+1],0.)
            np.testing.assert_allclose(bounded_result.bounded_saturation_targets(row)[handle+1],bounded,rtol=3e-12,atol=3e-13)
            self.assertEqual(bounded_result.web.parameters(h)['target_radii'][handle]<2*h*h/66,factor<2)

    def test_saturation_target_checks_singularity_even_at_exact_residual(self):
        web=TonalWeb(WebSettings(),self.tone, encoder=encode_cones)
        def singular(q,e,*selectors):
            return np.array([q[0],q[1],0.]),np.asarray(1.)
        seed=web.geometry.q[0,0]
        with patch.object(self.adapt,'apply',side_effect=singular):
            with self.assertRaisesRegex(ValueError,'folded or singular'):
                self.adapt.saturation_target(web,0,0,[seed[1],0.])

    def test_bounded_projection_disk_branches_hue_and_extreme_ranges(self):
        q=np.array([[20.,3.,4.],[-20.,3.,4.],[0.,0.,0.],[-1.,0.,0.],[1.,3.,4.]])
        e=np.array([144.,-144.,0.,-1.,0.])
        points=bounded_project(q,e)
        np.testing.assert_allclose(points[:2],[[3/13,4/13],[3/13,4/13]])
        np.testing.assert_array_equal(points[2:4],0.)
        np.testing.assert_allclose(points[4],[.6,.8])
        self.assertTrue(np.all(np.hypot(*points.T)<=1.))
        np.testing.assert_allclose(points[:,0]*q[:,2],points[:,1]*q[:,1])
        for exponent in (-1800,1800):
            scale=S(1.,exponent)
            actual=bounded_project([S(20.),3*scale,4*scale],-144*scale*scale)
            np.testing.assert_allclose(actual,points[0],rtol=3e-15)
        huge=np.finfo(float).max
        np.testing.assert_allclose(bounded_project([1.,huge,huge],1.),[2**-.5]*2)
        np.testing.assert_allclose(bounded_project([1.,1e-300,1e-300],0.),[2**-.5]*2)
        for stored in (np.inf,-np.inf,np.nan):
            self.assertTrue(np.isnan(bounded_project([1.,0.,0.],stored)).all())
            self.assertTrue(np.isnan(bounded_project([S(1.),S(3.),S(4.)],stored)).all())

    def test_bounded_projection_open_disk_inverse(self):
        for radius in (0.,.01,.5,.9,.9999):
            for theta in np.linspace(0,2*np.pi,17):
                target=radius*np.array([np.cos(theta),np.sin(theta)])
                linear=bounded_unproject(target)
                np.testing.assert_allclose(bounded_from_linear(linear),target,atol=3e-16)
        for target in ([1.,0.],[1.,1.],[np.nan,0.],[np.inf,0.],[0.]):
            with self.assertRaises(ValueError):bounded_unproject(target)
        for target in ([.01,-.02],[3.,4.],[1e300,-1e300]):
            self.assertTrue(np.isfinite(bounded_from_linear(target)).all())

    def test_bounded_targets_reuse_branch_inverse_and_preserve_scale(self):
        settings=ColorSettings(adaptance=tuple(map(tuple,self.targets)))
        base=Color(settings,self.tone,hk_guard=False)
        for row in range(4):
            target=np.array([.03,-.02])
            changed=base.target_bounded_saturation_settings(row,-1,target)
            np.testing.assert_allclose(Color(changed,self.tone,hk_guard=False).bounded_saturation_targets(row)[0],target,atol=2e-14)
        target=base.bounded_saturation_targets(1)[1]*1.02+[.001,-.001]
        for stops in (-8.,0.,8.):
            scales=np.zeros((4,6));scales[1,0]=stops
            color=Color(replace(settings,web=WebSettings(log_scale=tuple(map(tuple,scales)))),self.tone,hk_guard=False)
            np.testing.assert_allclose(color.bounded_saturation_targets(1),base.bounded_saturation_targets(1),rtol=3e-13,atol=2e-14)
            changed=color.target_bounded_saturation_settings(1,0,target)
            np.testing.assert_allclose(Color(changed,self.tone,hk_guard=False).bounded_saturation_targets(1)[1],target,rtol=3e-12,atol=3e-13)
            self.assertEqual(changed.web.log_scale[1][0],stops)

if __name__=='__main__':unittest.main()
