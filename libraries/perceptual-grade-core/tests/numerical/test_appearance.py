"""Blender CPU forward parity against the independent Colour/float64 oracle."""
from dataclasses import replace
import unittest
import numpy as np
from color_tools.perceptual_grade_core.model import color, forward, linear, tone, transforms
from color_tools.perceptual_grade_core.model.pipeline import Prepared
from tests.support import cases, reference as oracle


class AppearanceTests(unittest.TestCase):
    WHITES=('D65',)
    SPACES=('Linear Rec.709','Linear Rec.2020')
    TONE_CASES=((-2.,203.,500.),(.375,203.,1000.625),(6.,203.,4000.),(128.,203.,500.))
    STACK_WHITE='D65'

    def prepared(self,rgb,model):
        return Prepared({'stage1_rgb':rgb,'stage2_input_rgb':forward.Model(model.tone,model).prepare_input(rgb)},model)

    def assertParity(self,actual,expected,tolerance=3e-12):
        self.assertTrue(np.isfinite(actual).all())
        self.assertLessEqual(float(oracle.error(actual,expected).max(initial=0)),tolerance)

    def assertPortableParity(self,actual,expected):
        # Production Stack uses the adopted float32 bake contract. The
        # independently implemented inspection/oracle paths remain float64.
        self.assertTrue(np.isfinite(actual).all())
        error=np.max(abs(np.asarray(actual)-expected),axis=-1)
        limit=np.maximum(.001*np.max(abs(expected),axis=-1),1e-7)
        self.assertTrue(np.all(error<=limit),(error,limit))

    def test_reset_signed_hdr_and_final_black(self):
        x=cases.samples()
        for space in [*self.SPACES,*(linear.GradeSpace(p) for p in self.WHITES)]:
            with self.subTest(space=space):
                tp,cp=tone.Parameters(),color.Parameters()
                self.assertParity(color.model(tp,cp,space).apply(x),oracle.nonlinear(x,tp,cp,space))
                np.testing.assert_array_equal(color.model(tp,cp,space).apply([[-1,-1,-1],[0,0,0]]),0.)

    def test_driver_parity_across_crossover_hues_and_signed_ja(self):
        ja,chroma,angle=np.meshgrid([-1e150,-75.,0.,75.,1e150],
                                   [0.,1e-100,11.25,22.5,45.,1e150],
                                   np.linspace(-np.pi,np.pi,9),indexing='ij')
        q=np.stack((np.zeros_like(chroma),chroma*np.cos(angle),chroma*np.sin(angle)),axis=-1)
        actual=color.drivers(q,ja)
        expected=oracle.legacy_drivers(q,ja)
        self.assertTrue(np.isfinite(actual).all())
        np.testing.assert_allclose(actual,expected,rtol=2e-15,atol=0.)
        # Production must use the adopted response, even if both paths drift together.
        anchors=color.drivers([[100.,11.25,0.],[100.,22.5,0.],[100.,45.,0.]], [75.,75.,75.], [56.25]*3)
        visible=np.array([11.25,22.5,45.])**2/(np.array([11.25,22.5,45.])**2+4)
        np.testing.assert_allclose(anchors[:,:2]/visible[:,None],[[.8,.2],[.5,.5],[.2,.8]],rtol=2e-15)

    def test_scope_crossover_uses_hue_dependent_physical_capacity(self):
        from color_tools.perceptual_grade_core.model.cube_boundary import default_context
        ctx=default_context()
        ja=np.array([-75.,0.,1e-12,1.,75.,400.,ctx.white,ctx.white+1.])
        hue=np.linspace(-np.pi,np.pi,len(ja));capacity=ctx.capacity(ja,hue)
        chroma=color.chroma_crossover(capacity)
        np.testing.assert_allclose(chroma,.4*capacity,rtol=0,atol=0)
        magnitude=np.hypot(ja,np.sqrt(66*chroma))
        q=np.column_stack((magnitude,chroma*np.cos(hue),chroma*np.sin(hue)))
        low_high=color.drivers(q,ja,capacity)[:,:2]
        np.testing.assert_allclose(low_high[:,0],low_high[:,1],rtol=5e-15,atol=0.)
        np.testing.assert_array_equal(chroma[[0,1,6,7]],0.)

    def test_blender_export_guard_validates_actual_cube_and_preserves_inner_rays(self):
        from color_tools.perceptual_grade_core.model.cube_boundary import default_context
        context=default_context()
        ja,hue=np.meshgrid(context.white*np.array([.001,.02,.2,.5,.9,.999]),
                           np.linspace(-np.pi,np.pi,29),indexing='ij')
        c=context.capacity(ja,hue)
        inputs=[];energies=[]
        for factor in (.2,.9,1.1,4.,1000.):
            radius=(factor*c).ravel()
            inputs.append(np.column_stack((np.sqrt(ja.ravel()**2+66*radius),
                radius*np.cos(hue).ravel(),radius*np.sin(hue).ravel())))
            energies.append(ja.ravel()**2)
        q=np.concatenate(inputs);energy=np.concatenate(energies)
        actual,stored,rgb=context.guard(q,energy)
        self.assertTrue(np.isfinite(rgb).all())
        self.assertTrue(np.all((rgb>=0)&(rgb<=1024)))
        np.testing.assert_array_equal(stored,energy)
        response=context.responses(q,energy)
        safe=np.isfinite(response).all(axis=-1)&np.all(abs(response)<400,axis=-1)
        direct=np.full_like(q,np.nan)
        with np.errstate(divide='ignore',invalid='ignore',over='ignore'):
            direct[safe]=context.decode(q[safe],energy[safe])
        legal=np.isfinite(direct).all(axis=-1)&np.all((direct>=0)&(direct<=1024),axis=-1)
        np.testing.assert_array_equal(actual[legal],q[legal])
        np.testing.assert_array_equal(rgb[legal],direct[legal])
        np.testing.assert_allclose(np.arctan2(actual[:,2],actual[:,1]),
                                   np.arctan2(q[:,2],q[:,1]),atol=5e-15,rtol=0)
        sampled=np.arange(0,len(q),17)
        single=np.array([context.guard(q[i],energy[i])[2] for i in sampled])
        np.testing.assert_allclose(rgb[sampled],single,atol=1e-8,rtol=1e-10)

    def test_continuous_tone_narrow_intervals_fits_and_peaks(self):
        x=cases.samples()
        for fit,reference,peak in self.TONE_CASES:
            tp=tone.Parameters(input_black=.1,input_shadows=.11,input_midtones=42,input_white=260,input_highlights=1500,
                               fit=fit,reference_nits=reference,peak_nits=peak)
            for preset in self.WHITES:
                space=linear.GradeSpace(preset)
                with self.subTest(fit=fit,white=preset):
                    self.assertParity(tone.model(tp,space).apply(x),oracle.nonlinear(x,tp,color.Parameters(),space))
                    heights=np.linspace(0,300,61)
                    expected=oracle.grading.Tone(oracle.tone_settings(tp)).remap(heights)
                    self.assertParity((100*tone.model(tp,space).remap(heights/100))[:,None],expected[:,None])

    def test_every_control_and_combined_grade(self):
        x=cases.samples();tp=cases.parameters()[1]
        configs=[(name,replace(color.Parameters(),**{name:3. if name.startswith(('web_hue_','adaptance_a_','adaptance_b_')) else high*.27 if precision else .375}))
                 for name,_,_,_,high,precision,_ in color.CONTROLS]
        configs.append(('combined',cases.parameters()[2]))
        for preset in self.WHITES:
            space=linear.GradeSpace(preset)
            for name,cp in configs:
                with self.subTest(white=preset,control=name):
                    self.assertParity(color.model(tp,cp,space).apply(x),oracle.nonlinear(x,tp,cp,space))

    def test_complete_linear_tone_creative_grade(self):
        x=cases.samples()
        for preset in self.WHITES:
            space=linear.GradeSpace(preset);lp,tp,cp=cases.parameters(space)
            lp=replace(lp,exposure=.7,cr_balance=.1,yb_heading=-5,cr_spread=20)
            grade=transforms.Grade(transforms.Settings.from_parameters(lp,tp,cp,space))
            self.assertParity(grade.apply(x),oracle.grade(x,lp,tp,cp,space))

    def test_linear_first_reset_stack_and_nonlinear_composition(self):
        lp=linear.Parameters(exposure=1.3,cr_balance=.2,yb_spread=45)
        value=transforms.Settings.from_parameters(lp,tone.Parameters(),color.Parameters(),linear.GradeSpace('D65'))
        engine,_,_=oracle.evaluator(value.tone,value.color,value.space,value.matrix)
        native=np.array([[-.1,.4,2.],[4096.,30.,0.],[0.,0.,0.],[.2,.7,.3],[100.,1024.,3.]])
        expected=engine.input_native(native,engine.cones_to_xyz@np.linalg.inv(engine.boundary.matrix),True)
        self.assertPortableParity(transforms.Stack([value]).apply_native(native),expected)
        before=oracle.model.rgb_matrix('Linear Rec.709')
        to_xyz=engine.cones_to_xyz@np.linalg.inv(engine.boundary.matrix)
        rgb=native@to_xyz.T@np.linalg.inv(before).T
        grade=transforms.Grade(value)
        nonlinear=transforms.Grade(replace(value,matrix=linear.I3))
        linear_rgb=rgb@np.asarray(linear.rgb_matrix(value.matrix,value.space)).T
        self.assertParity(grade.apply(rgb),nonlinear.apply(linear_rgb))
        self.assertPortableParity(transforms.Stack([value]).apply(rgb),grade.apply(rgb))

    def test_signed_stage2_inspector_and_zero_crossings(self):
        x=np.array([[-.1,.3,2],[.1,-.03,.5],[-.1,-.1,-.1],[-1,.01,.1],[-.1,-.03,.01]])
        tp=tone.Parameters(input_white=235)
        for change in (-600.,600.):
            cp=replace(color.Parameters(),**{f'j_{driver}_{i}':change for driver in ('low','high') for i in range(4)})
            m=color.model(tp,cp)
            prepared=self.prepared(x,m)
            result=prepared.apply(m)
            self.assertParity(result,oracle.nonlinear(x,tp,cp))
            encoded=m.tone.stage2(prepared.rgb)
            np.testing.assert_allclose(prepared.stage2.q,encoded.q,rtol=0,atol=0)
        # Later Stack handoffs bypass entry and retain signed intermediate RGB.
        signed=Prepared({'stage2_input_rgb':x},m)
        self.assertLess(signed.stage2.ja[-1],0)
        self.assertParity(signed.apply(m),forward.Model(m.tone,m).apply(x,entry=False))

    def test_extreme_finite_inputs_and_controls(self):
        engine=forward.Model(tone.model(tone.Parameters()))
        integers=np.array([[2**63-1,-2**61,1]],dtype=np.int64)
        np.testing.assert_array_equal(engine.apply_native(integers),engine.apply_native(integers.astype(float)))
        x=np.array([[np.nextafter(0.,1),0,0],[1e-250,-1e-250,2e-250],[1e300,-1e299,2e299],[-1e300]*3])
        for cp in (color.Parameters(),color.Parameters(global_gain=10000),color.Parameters(global_gain=-10000),
                   color.Parameters(j_high_1=1e200,c_high_2=80,j_fit=10000)):
            self.assertParity(color.model(tone.Parameters(),cp).apply(x),oracle.nonlinear(x,tone.Parameters(),cp),2e-10)
        # Exact gray stays neutral in the vector and prepared inspector paths,
        # even when enormous chroma gain would amplify any matrix roundoff.
        cp=color.Parameters(global_gain=64);m=color.model(tone.Parameters(),cp)
        gray=np.array([[-.1]*3,[.18]*3])
        np.testing.assert_array_equal(m.apply(gray)[0],0.)
        self.assertParity(self.prepared(gray,m).apply(m),m.apply(gray))

    def test_hk_boundary_signed_outputs_and_prepared_parity(self):
        from color_tools.perceptual_grade_reference.appearance import decode
        from color_tools.perceptual_grade_reference.responses import hk_energy
        h = np.array([-1., 0., 1e-4, .5*np.sqrt(1320.), np.sqrt(1320.), 40.])
        q = np.column_stack((h, np.full(len(h), 20.), np.zeros(len(h))))
        for preset in self.WHITES:
            space = linear.GradeSpace(preset);tp, cp = tone.Parameters(), color.Parameters()
            engine, _, inverse = oracle.evaluator(tp, cp, space)
            xyz = decode(q, hk_energy(h, 20.), engine.white)
            rgb = xyz @ inverse.T
            model = color.model(tp, cp, space)
            expected = oracle.nonlinear(rgb, tp, cp, space)
            self.assertParity(model.apply(rgb), expected)
            self.assertParity(self.prepared(rgb,model).apply(model), expected)
            # This signed source has nonpositive native luminance at entry.
            np.testing.assert_array_equal(expected[3],0.)
            # Force the independently implemented scaled path as well.
            grade = transforms.Grade(transforms.Settings(tuple(map(tuple,np.eye(3))), tp, cp, space))
            grade.forward.vector_controls = False
            self.assertParity(grade.apply(rgb), expected)

    def test_forward_receivers_reenter_from_exported_rgb(self):
        tp,cp=tone.Parameters(),color.Parameters()
        first=transforms.Settings(tuple(map(tuple,np.eye(3))),tp,color.Parameters(global_gain=3.),linear.GradeSpace(self.STACK_WHITE))
        last=transforms.Settings(tuple(map(tuple,np.eye(3))),tp,color.Parameters(global_gain=-3.),linear.GradeSpace('D65'))
        x=np.array([[-.1,.3,2.],[.2,.3,.4],[-.1,-.1,-.1],[500.,100.,1.]])
        stack=transforms.Stack([first,last]);expected=oracle.stack(x,[first,last])
        self.assertPortableParity(stack.apply(x),expected)
        each=transforms.Grade(last).apply(transforms.Grade(first).apply(x))
        # Exact release/entry inverses cancel across standalone boundaries.
        self.assertParity(each,expected)

    def test_invalid_inputs_parameters_and_inverse_are_explicit_errors(self):
        for x in ([1,2],[np.nan,0,0],[0,np.inf,0]):
            with self.assertRaises(ValueError):color.model(tone.Parameters(),color.Parameters()).apply(x)
        with self.assertRaises(ValueError):tone.model(tone.Parameters(fit=float('nan')))
        with self.assertRaises(ValueError):color.model(tone.Parameters(),color.Parameters(global_gain=float('inf')))
        value=transforms.Settings.from_parameters(linear.Parameters(),tone.Parameters(),color.Parameters(),'Linear Rec.709')
        with self.assertRaises(TypeError):transforms.Grade(value,reverse=True)
