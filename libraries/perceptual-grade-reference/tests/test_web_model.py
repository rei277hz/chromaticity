"""Reference integration, carried energy, inverse, and adoption boundaries."""
from dataclasses import replace
import unittest
import numpy as np
from color_tools.perceptual_grade_reference.grading import ColorSettings, ToneSettings
from color_tools.perceptual_grade_reference.model import Model, Settings
from color_tools.perceptual_grade_core.model.tonal_web import WebSettings
from color_tools.perceptual_grade_reference.responses import State, signed_hk
from color_tools.color_core.scaled import Scalar as S
from color_tools.perceptual_grade_reference.bake import Kernel
from color_tools.perceptual_grade_core.model.hk_guard import guard
from color_tools.perceptual_grade_reference.stack import Stack
from color_tools.perceptual_grade_reference.stack_bake import BakeStack


def edits(scale=1.):
    row=np.array([.06, -.03, .04, 0., -.02, .03])*scale
    hue=np.array([3., -2., 1., 0., -3., 2.])*scale
    light=np.array([.025, 0., -.02, .015, 0., -.01])*scale
    return WebSettings(log_chroma=tuple(map(tuple,np.tile(row,(4,1)))),
                       hue_degrees=tuple(map(tuple,np.tile(hue,(4,1)))),
                       log_scale=tuple(map(tuple,np.tile(light,(4,1)))))


class WebModelTests(unittest.TestCase):
    def test_schema_has_only_current_controls(self):
        for kw in ({'hue':(1.,)*4},{'global_hues':(1.,2.)},{'adaptance_fit':0.}):
            with self.assertRaises(TypeError):ColorSettings(**kw)
        with self.assertRaises(ValueError):Model(Settings(color=ColorSettings(web={'log_chroma':[[0.]]})))
        model=Model(Settings(color=ColorSettings(global_gain=.1)))
        self.assertIsNone(model.color.web._geometry)

    def test_reset_web_preserves_carried_state_and_neutrals(self):
        q=np.array([[float(signed_hk(1e-100,80.)),80.,0.],[75.,0.,0.],[0.,0.,0.]])
        energy=np.array([1e-200,75.**2,0.])
        reset=Model().grade_state(State(q,energy))
        np.testing.assert_array_equal(reset.q,q)
        np.testing.assert_array_equal(reset.energy,energy)
        active=Model(Settings(color=ColorSettings(web=edits())))
        result=active.grade_state(State(q[1:],energy[1:]))
        np.testing.assert_array_equal(result.q,q[1:])
        np.testing.assert_array_equal(result.energy,energy[1:])

    def test_scaled_raw_handoff_preserves_authoritative_energy(self):
        # These energies are not recovered bit-for-bit by sqrt followed by square.
        candidates = [S(v) for v in (.1, .2, .3, .7, np.pi, 1.e-200)]
        energy = next(v for v in candidates if (abs(v)**.5)**2 != v)
        chroma = S(1.)
        ja = energy**.5
        q = [signed_hk(ja, chroma), chroma, S()]
        state = State(np.array([q], dtype=object), np.array([energy], dtype=object))
        rows = np.zeros((4, 6)); rows[-1, 0] = .2
        for settings in (ColorSettings(),
                         ColorSettings(web=WebSettings(log_chroma=rows))):
            model = Model(Settings(color=settings), hk_guard=False)
            result = model.grade_state(state)
            self.assertEqual(result.energy[0], energy)
            self.assertTrue(all(a == b for a, b in zip(result.q[0], q)))
        # A nontrivial hue edit changes q but must still carry this exact energy.
        hue = np.full((4, 6), 5.)
        web = Model(Settings(color=ColorSettings(web=WebSettings(hue_degrees=hue))), hk_guard=False)
        result = web.grade_state(state)
        self.assertEqual(result.energy[0], energy)
        self.assertNotEqual(result.q[0, 2], q[2])

    def test_scaled_retained_changes_and_web_scale_update_energy(self):
        base = Model(Settings(color=ColorSettings(global_gain=.2)))
        scaled = Model(Settings(color=ColorSettings(global_gain=.2,
            web=WebSettings(log_scale=((.25,)*6,)*4))))
        state = base.enter_native(np.array([[.08, .12, .25]]))
        normal = scaled.grade_state(state)
        base.vector_controls = scaled.vector_controls = False
        actual = scaled.grade_state(state)
        self.assertGreater(actual.energy[0], S())
        self.assertNotEqual(actual.energy[0], S(state.energy[0]))
        np.testing.assert_allclose(np.asarray(actual.q, float), normal.q, rtol=1e-13)
        np.testing.assert_allclose(np.asarray(actual.energy, float), normal.energy, rtol=1e-13)

    def test_order_and_posttone_selector_match_explicit_composition(self):
        settings=Settings(tone=ToneSettings(input_nits=(0.,8.,42.,203.,1100.)),
            color=ColorSettings(global_gain=.2,lightness=((.2,0.,0.,0.),)*4,
                                adaptance=((.1,-.05),)*4,web=edits()))
        model=Model(settings)
        state=model.enter_native(np.array([[.1,.2,.35],[.6,.15,.02],[1.,2.,.3]]))
        tone=model.tone.apply(state)
        retained_model=Model(replace(settings,color=replace(settings.color,adaptance=((0.,0.),)*4,web=WebSettings())),hk_guard=False)
        retained=retained_model.color.apply_state(tone)
        source_c=np.hypot(tone.q[:,1],tone.q[:,2])
        height=np.hypot(tone.ja,np.sqrt(66*source_c))
        reference=tone.ja*abs(tone.ja)
        def transform(q,e):
            q,e=model.color.adaptation.apply(q,e,height,source_c,reference)
            return guard(q,e,reference)
        q,e=model.color.web.apply(retained.q,retained.energy,height,transform=transform)
        actual=model.grade_state(state)
        np.testing.assert_array_equal(actual.q,q)
        np.testing.assert_array_equal(actual.energy,e)
        rgb=model.release_state(actual,guard=True)
        self.assertTrue(np.isfinite(rgb).all())
        self.assertTrue(((rgb>=0)&(rgb<=1024)).all())

    def test_repaired_scale_preserves_saturation_and_scaled_path(self):
        chroma=np.full((4,6),.35);scale=np.full((4,6),.3)
        base=WebSettings(log_chroma=tuple(map(tuple,chroma)))
        changed=replace(base,log_scale=tuple(map(tuple,scale)))
        first=Model(Settings(color=ColorSettings(web=base)))
        second=Model(Settings(color=ColorSettings(web=changed)))
        q=first.color.web.geometry.q[0].copy();e=first.color.web.geometry.energy[0].copy()
        state=State(q,e)
        a,b=first.grade_state(state),second.grade_state(state)
        raw=Model(Settings(color=ColorSettings(web=base)),hk_guard=False).grade_state(state)
        self.assertTrue(np.any(raw.energy<0))
        self.assertTrue(np.all(a.energy>0))
        self.assertTrue(np.all(b.energy>0))
        ca=np.hypot(a.q[:,1],a.q[:,2]);cb=np.hypot(b.q[:,1],b.q[:,2])
        np.testing.assert_allclose(ca/abs(a.ja),cb/abs(b.ja),rtol=4e-14)
        for source,energy,wanted,stored in zip(q,e,b.q,b.energy):
            out,energy_out=second.color.scaled_apply_state(list(map(S,source)),S(np.sqrt(energy)))
            np.testing.assert_allclose(list(map(float,out)),wanted,rtol=3e-13,atol=1e-12)
            self.assertAlmostEqual(float(energy_out)/stored,1.,places=12)

    def test_portable_paths_accept_active_web(self):
        settings=Settings(color=ColorSettings(web=edits()))
        model=Model(settings)
        kernel=Kernel(model.boundary.cache,model.tone,model.color)
        self.assertTrue(kernel.web_active)
        self.assertIsNotNone(BakeStack([settings]))
        reset=Model()
        self.assertTrue(Kernel(reset.boundary.cache,reset.tone,reset.color).identity)

    def test_combined_center_and_corner_targets(self):
        settings=ColorSettings(web=edits(),adaptance=((3.,-2.),)*4)
        model=Model(Settings(color=settings))
        for row in range(4):
            source=model.color.warp_targets(row)
            center=source.q[0,1:]+np.array([2.,1.])
            moved=model.color.target_settings(row,-1,center)
            candidate=Model(Settings(color=moved))
            np.testing.assert_allclose(candidate.color.warp_targets(row).q[0,1:],center,atol=2e-14)
            self.assertEqual(moved.web,settings.web)
            target=candidate.color.warp_targets(row).q[1,1:]+np.array([.1,.1])
            changed=candidate.color.target_settings(row,0,target)
            final=Model(Settings(color=changed)).color.warp_targets(row)
            np.testing.assert_allclose(final.q[1,1:],target,rtol=2e-12,atol=2e-12)
            self.assertEqual(changed.web.log_scale,moved.web.log_scale)
        minimum=Model(Settings(color=replace(settings,adaptance_half_saturation=.05)))
        moved=minimum.color.target_settings(0,-1,[1.,0.])
        np.testing.assert_allclose(Model(Settings(color=moved)).color.warp_targets(0).q[0,1:],[1.,0.],atol=2e-12)

    def test_selective_cone_neutral_preservation_and_final_saturation(self):
        settings=ColorSettings(web=edits(),adaptance=((5.,-3.),)*4)
        model=Model(Settings(color=settings))
        h=np.linspace(1.,250.,61)
        q=np.column_stack((h,np.zeros((len(h),2))))
        output=model.color.warp_state(State(q,h*h),h)
        np.testing.assert_array_equal(output.energy,h*h)
        self.assertTrue(np.isfinite(output.q).all())
        no_scale=Model(Settings(color=replace(settings,web=replace(settings.web,log_scale=WebSettings().log_scale))))
        a=no_scale.color.warp_targets(0);b=model.color.warp_targets(0)
        np.testing.assert_allclose(np.hypot(a.q[:,1],a.q[:,2])/abs(a.ja),
                                   np.hypot(b.q[:,1],b.q[:,2])/abs(b.ja),rtol=3e-14)
        model.vector_controls=False
        state=model.enter_native(np.array([[.1,.2,.3],[1.,.05,.2]]))
        out=model.grade_state(state)
        model.vector_controls=True;vector=model.grade_state(state)
        np.testing.assert_allclose(np.asarray(out.q,float),vector.q,rtol=1e-13)
        np.testing.assert_allclose(np.asarray(out.energy,float),vector.energy,rtol=1e-13)

    def test_rgb_inverse_reports_real_forward_residual(self):
        model=Model(Settings(color=ColorSettings(web=edits(.5),adaptance=((1.,-.5),)*4)))
        source=np.array([[.3,.15,.09],[.08,.25,.22]])
        target=model.forward(source)
        result=model.inverse(target)
        actual=model.forward(result.value)
        residual=np.max(abs(actual-target),axis=-1)/(1+np.max(abs(target),axis=-1))
        np.testing.assert_allclose(result.residual,residual,atol=2e-15,rtol=2e-4)
        self.assertTrue((result.status=='root').all())
        self.assertLess(float(residual.max()),2e-10)

    def test_repaired_stack_handoff_and_inverse_with_web(self):
        first=Settings(color=ColorSettings(web=edits(.5),adaptance=((1.,-.5),)*4))
        second=Settings(color=ColorSettings(web=edits(.3),adaptance=((-.5,.25),)*4))
        source=np.array([[.3,.15,.09]])
        stack=Stack([first,second],['FORWARD','INVERSE'])
        actual=stack.apply(source)
        self.assertTrue(np.isfinite(actual).all())
        target=stack.models[0].grade_state(stack.models[0].enter_native(source))
        self.assertTrue(np.all(target.energy>=0))
        from color_tools.perceptual_grade_reference.stack import nonlinear_inverse
        native,residual=nonlinear_inverse(stack.models[1],target,True)
        self.assertLess(float(np.max(residual)),2e-10)
        reproduced=stack.models[1].grade_state(stack.models[1].enter_native(native))
        np.testing.assert_allclose(reproduced.q,target.q,rtol=2e-9,atol=2e-9)


if __name__=='__main__':unittest.main()
