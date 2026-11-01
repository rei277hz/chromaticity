from color_tools.perceptual_grade_blender.model.bake_inverse_gpu import Program as ReferenceGPUProgram
"""Actual llvmpipe/Blender inverse compute against shared CPU and float64 math."""
from dataclasses import replace
import unittest
import numpy as np
from tests.support.gpu import initialize
from color_tools.perceptual_grade_reference.model import Settings
from color_tools.perceptual_grade_reference.grading import ToneSettings
from color_tools.perceptual_grade_reference.grading import ColorSettings
from color_tools.perceptual_grade_core.model.tonal_web import WebSettings
from color_tools.perceptual_grade_core.model.bake_inverse import features
from color_tools.perceptual_grade_core.model import bake, bake_inverse
from color_tools.perceptual_grade_blender.model import bake_gpu, boundary_gpu
from tests.reference.legacy_capacity import LegacyCapacityBakeStack
from tests.reference.test_legacy_inverse_baking import mixed,reachable_web_case


class InverseComputeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        initialize();cls.base=LegacyCapacityBakeStack([Settings()],['INVERSE'], program_factory=ReferenceGPUProgram);cls.program=cls.base.prepare_gpu()

    def stack(self,settings,directions):
        stack=LegacyCapacityBakeStack(settings,directions,self.base.table, program_factory=ReferenceGPUProgram);stack.program=self.program;return stack

    def assert_parity(self,cpu,gpu):
        expected=cpu[:,:3];actual=gpu[:,:3]
        difference=np.max(abs(actual-expected),axis=-1);limit=np.maximum(.001*np.max(abs(expected),axis=-1),1e-7)
        self.assertTrue(np.all(difference<=limit),(cpu,gpu,difference/limit))
        self.assertTrue(np.isfinite(gpu).all())

    def assert_reported_error(self,solver,target,result,appearance=False):
        actual=self.program.evaluate(result[:,:3],3 if appearance else 2)
        if appearance:
            wanted=features(target);difference=(features(actual)-wanted)/(1+abs(wanted))
        else:
            difference=solver.kernel.native(actual[:,:3]-target,solver.canonical)
            peak=np.maximum(np.max(abs(solver.kernel.native(target,solver.canonical)),axis=-1),1e-4)
            difference/=peak[:,None]
        np.testing.assert_allclose(result[:,3],np.max(abs(difference),axis=-1),rtol=2e-5,atol=1e-7)

    def test_lookup_coordinate_math_against_float64(self):
        def source(data,offsets,expanded):
            return bake_gpu.source(data,offsets,expanded).split('void main()',1)[0]+'''
void main() {
    int id=int(gl_GlobalInvocationID.x);if(id>=sample_count||operation<0)return;
    ivec2 address=ivec2(id%256,id/256);vec4 v=texelFetch(input_pixels,address,0);
    imageStore(output_pixels,address,vec4(pg_power(v.x,v.y),pg_atan2(v.z,v.w),0.0,0.0));
}
'''
        kernel=self.base.kernels[0]
        program=boundary_gpu.Program(kernel.data,source,True,kernel.table.expanded)
        program.parameters=self.program.parameters
        bases=np.r_[np.float32(0),np.geomspace(1e-12,1e4,513).astype('f4'),np.float32(1)]
        exponents=np.array([.42,bake.GAMMA,1/bake.GAMMA,50/21],dtype='f4')
        base,exponent=np.meshgrid(bases,exponents);base=base.ravel();exponent=exponent.ravel()
        angles=np.linspace(-np.pi,np.pi,len(base));y=np.sin(angles).astype('f4');x=np.cos(angles).astype('f4')
        # Include tiny opponent ratios, both axes, and signed zero on the seam.
        y[:8]=[0,-0.,1,-1,1e-20,-1e-20,1,-1]
        x[:8]=[-1,-1,0,0,1,1,-1e-20,-1e-20]
        actual=program.evaluate(np.column_stack((base,exponent,y,x)))
        expected_power=np.power(base.astype(float),exponent.astype(float)).astype('f4')
        expected_angle=np.arctan2(y.astype(float),x.astype(float)).astype('f4')
        np.testing.assert_array_max_ulp(actual[:,0],expected_power,maxulp=3)
        np.testing.assert_allclose(actual[:,1],expected_angle,rtol=2e-7,atol=2.4e-7)
        np.testing.assert_array_equal(actual[base==0,0],0)

    def test_cube_crease_prior_acceptance_matches_cpu(self):
        stack=self.stack([Settings(color=ColorSettings(global_gain=.25))],['INVERSE'])
        solver=stack.solvers[0];self.program.set_inverse(solver)
        target=np.array([[.04064936935901642,0,1024]],dtype='f4')
        cpu_prior=np.max(abs(solver.residual(target,target,False)),axis=-1)
        forward=self.program.evaluate(target,2)[:,:3]
        peak=np.max(abs(solver.kernel.native(target,solver.canonical)),axis=-1)
        gpu_prior=np.max(abs(solver.kernel.native(forward-target,solver.canonical)),axis=-1)/peak
        limit=solver.acceptance_limit(target)
        # Previously the driver's atan/pow error selected a different face and
        # accepted the prior only on GPU, producing a completely different root.
        self.assertTrue(np.all(cpu_prior>limit),(cpu_prior,limit))
        self.assertTrue(np.all(gpu_prior>limit),(gpu_prior,limit))
        cpu=solver.evaluate(target);gpu=self.program.evaluate(target)
        self.assert_parity(cpu,gpu);self.assert_reported_error(solver,target,gpu)

    def test_mixed_web_center_scale_raw_forward_matches_cpu(self):
        settings=Settings(tone=ToneSettings(input_nits=(0.,7.,42.,210.,1000.)),
            color=ColorSettings(global_gain=.1,adaptance=((1.,-2.),(-3.,2.),(2.,3.),(-1.,2.)),
                web=WebSettings(
                    log_chroma=((.2,-.1,.1,-.15,.25,-.2),(-.1,.2,-.1,.1,-.15,.2),(.15,)*6,(-.1,)*6),
                    hue_degrees=((8.,-4.,6.,-8.,4.,-6.),(-6.,8.,-4.,6.,-8.,4.),(5.,)*6,(-3.,)*6),
                    log_scale=((.15,-.1,.1,0.,-.15,.2),(-.1,.15,0.,-.1,.1,-.15),(.1,)*6,(-.05,)*6))))
        stack=self.stack([settings],['FORWARD']);k=stack.kernels[0];self.program.set_inverse(stack.solvers[0])
        axis=np.r_[0.,np.geomspace(1e-6,500,8)].astype('f4')
        source=np.stack(np.meshgrid(axis,axis,axis,indexing='ij'),-1).reshape(-1,3)
        expected=k.grade(k.tone_state(k.enter(source)));actual=self.program.evaluate(source,3)
        errors=abs(features(actual)-features(expected))/(1+abs(features(expected)))
        self.assertLess(float(np.max(errors[:,[0,2,3]])),2e-4)
        # Adaptance can move signed E through zero. Its square root is poorly
        # conditioned there, so check carried E and JA at the physical H²/height
        # scales, as in the independent CPU mixed-web accuracy contract.
        scale=1+abs(expected[:,3].astype(float))+66*np.hypot(expected[:,1].astype(float),expected[:,2].astype(float))
        self.assertLess(float(np.max(abs(actual[:,3]-expected[:,3])/scale)),2e-6)
        ja_error=abs(features(actual)[:,1]-features(expected)[:,1])/np.sqrt(scale)
        self.assertLess(float(np.max(ja_error)),5e-5)
        np.testing.assert_array_equal(actual[0],0.)
        self.assertFalse(stack.solvers[0].simple)

    def test_rgb_and_raw_inverse_computation(self):
        points=np.array([[.1,.2,.3],[.7,.2,.1],[.02,.08,.4],[0,0,0]],dtype='f4')
        for settings in (Settings(color=ColorSettings(global_gain=.25)),mixed(),
                         Settings(color=ColorSettings(web=WebSettings(hue_degrees=((3.,-4.,2.,-3.,4.,-2.),)*4),global_gain=.15)),
                         Settings(tone=ToneSettings(input_nits=(0.,7.,45.,203.,1000.)))):
            stack=self.stack([settings],['INVERSE']);k=stack.kernels[0];self.program.set_inverse(stack.solvers[0])
            raw=k.grade(k.tone_state(k.enter(points)));rgb=k.evaluate(points)
            with self.subTest(settings=settings):
                for target,appearance in ((rgb,False),(raw,True)):
                    self.assert_parity(stack.solvers[0].evaluate(target,appearance),self.program.evaluate(target,int(appearance)))

    def test_unequal_hue_handles_recover_raw_targets(self):
        settings=Settings(color=ColorSettings(web=WebSettings(hue_degrees=((3.,-4.,2.,-3.,4.,-2.),)*4),global_gain=.15))
        stack=self.stack([settings],['INVERSE']);solver=stack.solvers[0];k=solver.kernel
        points=np.array([[.1,.2,.3],[.7,.2,.1],[.02,.08,.4],[0,0,0]],dtype='f4')
        target=k.grade(k.enter(points));self.program.set_inverse(solver)
        cpu=solver.evaluate(target,True);gpu=self.program.evaluate(target,1)
        self.assert_parity(cpu,gpu)
        self.assert_reported_error(solver,target,gpu,True)
        self.assertTrue(np.all(gpu[:,3]<=bake_inverse.TOLERANCE),gpu)
        np.testing.assert_allclose(gpu[:,:3],points,rtol=.001,atol=1e-7)

    def test_full_web_raw_inverse_recovers_known_in_cube_sources(self):
        settings,source=reachable_web_case()
        stack=self.stack([settings],['INVERSE']);solver=stack.solvers[0];k=solver.kernel
        target=k.grade(k.tone_state(k.enter(source)));self.program.set_inverse(solver)
        cpu=solver.evaluate(target,True);actual=self.program.evaluate(target,1)
        self.assert_parity(cpu,actual)
        self.assert_reported_error(solver,target,actual,True)
        self.assertTrue(np.all(actual[:,3]<=bake_inverse.TOLERANCE),actual)
        np.testing.assert_allclose(actual[:,:3],source,rtol=.001,atol=1e-7)

    def test_directional_stage3_residual_matches_cpu(self):
        base=mixed();settings=replace(base,color=replace(base.color,
            lightness=((0.,0.,.03,-.02),(0.,.1,.02,0.),(0.,0.,0.,0.),(0.,0.,0.,0.)),
            chroma=((0.,0.,0.,0.),(0.,0.,.01,-.01),(0.,0.,0.,0.),(0.,0.,0.,0.))))
        stack=self.stack([settings],['INVERSE']);solver=stack.solvers[0];k=solver.kernel
        points=np.array([[.1,.2,.3],[.7,.2,.1],[.02,.08,.4],[0,0,0],[1e-8,2e-8,0]],dtype='f4')
        self.program.set_inverse(solver)
        for raw in (False,True):
            target=k.grade(k.tone_state(k.enter(points))) if raw else k.evaluate(points)
            self.assert_parity(solver.evaluate(target,raw),self.program.evaluate(target,int(raw)))

    def test_chroma_toe_scale_zero_seams_and_physical_upper_bound(self):
        maximum=np.finfo('f4').max
        targets=np.array([[0,0,0,0],[-1,0,0,-2],[0,.3,.4,-1],[0,0,0,-132],
            [maximum,maximum,-maximum,-maximum],[1e-12,0,0,1e-24],
            [-1e-12,1e-20,-1e-20,-1e-24]],dtype='f4')
        tau=bake_inverse.chroma_scale(targets)
        actual=self.program.evaluate(targets,7)
        np.testing.assert_allclose(actual[:,:2],np.column_stack((tau,np.log(tau))),rtol=2e-6,atol=0)
        self.assertTrue(np.all(actual[:,0]>0));self.assertTrue(np.isfinite(actual).all())
        rows=[]
        for tau in np.array([bake_inverse.CHROMA_TOE_MIN,1e-20,1e-6,2],dtype='f4'):
            values=np.array([0,tau,np.nextafter(tau,np.float32(0)),
                np.nextafter(tau,np.float32(np.inf)),1,np.exp(np.float32(20))],dtype='f4')
            logs=np.full_like(values,-np.inf);np.log(values,out=logs,where=values>0)
            coordinates=bake_inverse.chroma_encode(logs,np.log(tau))
            for gain in (-200.,0.,200.):
                rows.append(np.column_stack((values,np.full_like(values,tau),
                    np.full_like(values,gain),coordinates)))
        rows=np.concatenate(rows);logs=np.full(len(rows),-np.inf,dtype='f4')
        np.log(rows[:,0],out=logs,where=rows[:,0]>0);logscale=np.log(rows[:,1])
        encoded=bake_inverse.chroma_encode(logs,logscale)
        decoded=bake_inverse.chroma_decode(rows[:,3],logscale)
        predicted=bake_inverse.chroma_encode(logs+np.float32(np.log(2))*rows[:,2],logscale)
        expected=np.column_stack((encoded,decoded,predicted,encoded-predicted))
        actual=self.program.evaluate(rows,6)
        np.testing.assert_allclose(actual[:,:3],expected[:,:3],rtol=2e-5,atol=float(bake_inverse.CHROMA_TOE_MIN))
        np.testing.assert_allclose(actual[:,3],expected[:,3],rtol=2e-5,atol=2e-5)
        np.testing.assert_array_equal(actual[rows[:,0]==0],0)
        self.assertTrue(np.isfinite(actual).all())

    def test_mixed_tone_recovers_all_neutral_lut_vertices(self):
        settings=replace(mixed(),tone=ToneSettings(input_nits=(0.,7.,45.,203.,1000.)))
        stack=self.stack([settings],['INVERSE']);solver=stack.solvers[0];k=solver.kernel
        axis=.01*np.expm1(np.linspace(0,1,65)*np.log1p(1024/.01));axis[0],axis[-1]=0,1024
        source=np.repeat(axis.astype('f4')[:,None],3,axis=1)
        self.program.set_inverse(solver)
        # Direct raw calls deliberately bypass matching-Stack cancellation.
        # This includes the 29 neutral vertices that failed the former log-C search.
        targets=(k.grade(k.tone_state(k.enter(source))),self.program.evaluate(source,3))
        for target in targets:
            cpu=solver.evaluate(target,True);gpu=self.program.evaluate(target,1)
            self.assertTrue(np.all(cpu[:,3]<=bake_inverse.TOLERANCE),cpu)
            self.assertTrue(np.all(gpu[:,3]<=bake_inverse.TOLERANCE),gpu)
            self.assert_parity(cpu,gpu)
            np.testing.assert_allclose(gpu[:,:3],source,rtol=.001,atol=1e-7)
            self.assert_reported_error(solver,target,gpu,True)

    def test_chroma_toe_near_neutral_and_signed_raw_validation(self):
        settings=replace(mixed(),tone=ToneSettings(input_nits=(0.,7.,45.,203.,1000.)))
        stack=self.stack([settings],['INVERSE']);solver=stack.solvers[0];k=solver.kernel
        levels=np.array([1e-8,1e-6,1e-4,.01,.08,1,16],dtype='f4')
        directions=np.array([[1,1,1],[1.0001,1,.9999],[.999,1.001,1]],dtype='f4')
        source=(levels[:,None,None]*directions[None,:,:]).reshape(-1,3)
        self.program.set_inverse(solver);target=k.grade(k.tone_state(k.enter(source)))
        cpu=solver.evaluate(target,True);gpu=self.program.evaluate(target,1)
        self.assert_parity(cpu,gpu);self.assert_reported_error(solver,target,gpu,True)
        # Nonpositive H must not turn the raw target into black before validation.
        signed=np.array([[0,1,-1,-100],[-1,.2,-.1,-20]],dtype='f4')
        cpu=solver.evaluate(signed,True);gpu=self.program.evaluate(signed,1)
        self.assert_parity(cpu,gpu);self.assert_reported_error(solver,signed,gpu,True)
        self.assertTrue(np.isfinite(gpu).all())
        self.assertTrue(np.all(gpu[:,3]>bake_inverse.TOLERANCE))

    def test_rgb_prior_uses_adopted_absolute_and_relative_acceptance(self):
        levels=np.array([1e-7,1e-4,.01,.1,1,100,1024],dtype='f4')
        points=(levels[:,None,None]*np.array([[.1,.2,.3],[.7,.2,.1],[.02,.08,.4]],dtype='f4')).reshape(-1,3)
        absolute_cases=0;relative_cases=0;stricter_rejections=0
        for settings in (Settings(color=ColorSettings(global_gain=.00005)),
                         Settings(color=ColorSettings(global_gain=.001)),mixed(),
                         Settings(tone=ToneSettings(input_nits=(0.,7.,45.,203.,1000.)))):
            stack=self.stack([settings],['INVERSE']);solver=stack.solvers[0];k=solver.kernel
            self.program.set_inverse(solver)
            cpu=solver.evaluate(points);gpu=self.program.evaluate(points)
            peak=np.max(abs(k.native(points,solver.canonical)),axis=-1)
            limit=np.maximum(.0001*peak,.00003)
            cpu_prior=k.native(k.evaluate(points)-points,solver.canonical)
            gpu_prior=k.native(self.program.evaluate(points,2)[:,:3]-points,solver.canonical)
            # Leave a margin around the threshold for forward float32 rounding.
            cpu_error=np.max(abs(cpu_prior),axis=-1);gpu_error=np.max(abs(gpu_prior),axis=-1)
            error=np.maximum(cpu_error,gpu_error)
            accepted=error<.98*limit
            self.assertTrue(np.any(accepted))
            np.testing.assert_array_equal(cpu[accepted,:3],points[accepted])
            np.testing.assert_array_equal(gpu[accepted,:3],points[accepted])
            absolute_cases+=np.count_nonzero(accepted&(peak<.3)&(error>.0001*peak))
            relative_cases+=np.count_nonzero(accepted&(peak>.3))
            # These priors passed the former 10x looser rule. Require actual
            # CPU/GLSL examples which now reconstruct an acceptable candidate.
            rejected=(np.minimum(cpu_error,gpu_error)>1.02*limit)&(error<.98*np.maximum(.001*peak,.0003))
            corrected=rejected&(cpu[:,3]<=solver.acceptance_limit(points))&(gpu[:,3]<=solver.acceptance_limit(points))
            stricter_rejections+=np.count_nonzero(corrected)
            self.assertTrue(np.all(np.any(cpu[corrected,:3]!=points[corrected],axis=1)))
            self.assertTrue(np.all(np.any(gpu[corrected,:3]!=points[corrected],axis=1)))
        self.assertGreater(absolute_cases,0)
        self.assertGreater(relative_cases,0)
        self.assertGreater(stricter_rejections,0)

    def test_actual_stack_handoffs_and_reset(self):
        points=np.array([[.1,.2,.3],[.7,.2,.1],[.02,.08,.4],[0,0,0],[1024,1024,1024]],dtype='f4')
        a=Settings(color=ColorSettings(global_gain=.1));b=Settings(color=ColorSettings(global_gain=.2))
        for directions in (['FORWARD','INVERSE'],['INVERSE','FORWARD'],['INVERSE','INVERSE'],['FORWARD','FORWARD']):
            with self.subTest(directions=directions):
                stack=self.stack([a,b],directions)
                self.assert_parity(stack.bake_native(points),stack.bake_native(points,'GPU'))
        stack=self.stack([mixed(),mixed()],['FORWARD','INVERSE'])
        np.testing.assert_array_equal(stack.bake_native(points,'GPU')[:,:3],points)

    def test_tone_table_with_nonzero_black_and_extreme_fit(self):
        points=np.array([[.1,.2,.3],[.7,.2,.1],[1e-8,2e-8,0],[0,0,0]],dtype='f4')
        for tone in (ToneSettings(input_nits=(.01,1.,90.,400.,4000.),fit=-2),
                     ToneSettings(input_nits=(0.,.0001,.01,203.,10000.),fit=3)):
            stack=self.stack([Settings(tone=tone)],['INVERSE']);k=stack.kernels[0];solver=stack.solvers[0]
            raw=k.grade(k.tone_state(k.enter(points)));self.program.set_inverse(solver)
            self.assert_parity(solver.evaluate(raw,True),self.program.evaluate(raw,1))

    def test_direct_tone_table_lookup_at_knots_black_and_tail(self):
        ordinary=ToneSettings(input_nits=(0.,7.,45.,203.,1000.))
        for tone in (ordinary,ToneSettings(input_nits=(.01,1.,90.,400.,4000.),fit=-2),
                     ToneSettings(input_nits=(0.,.0001,.01,203.,10000.),fit=3),ordinary):
            stack=self.stack([Settings(tone=tone)],['INVERSE']);solver=stack.solvers[0];table=solver.tone_table
            knots=(float(table.scale)*np.expm1(table.nodes[:,0].astype(float))).astype('f4')
            heights=np.unique(np.r_[np.float32(0),np.geomspace(1e-12,1,21).astype('f4'),
                knots,np.nextafter(knots,np.float32(np.inf)),np.maximum(0,np.nextafter(knots,np.float32(-np.inf))),
                table.tail_h,np.nextafter(table.tail_h,np.float32(-np.inf)),
                np.nextafter(table.tail_h,np.float32(np.inf)),table.tail_h*np.float32(1e5)]).astype('f4')
            points=np.column_stack((heights,np.zeros((len(heights),2),dtype='f4'),heights*heights))
            self.program.set_inverse(solver)
            actual=self.program.evaluate(points,5);expected=solver.undo_tone(points)
            np.testing.assert_allclose(actual,expected,rtol=8e-6,atol=0)
            np.testing.assert_array_equal(actual[heights==0],0)
            self.assertEqual(self.program.tone_lookup_bytes,table.bytes)
            self.assertGreaterEqual(self.program.parameter_bytes,1024+table.nodes.nbytes)
        reset=self.stack([Settings()],['INVERSE']).solvers[0];self.program.set_inverse(reset)
        np.testing.assert_array_equal(self.program.evaluate(points,5),points)
        self.assertEqual(self.program.tone_lookup_bytes,0)
        self.assertEqual(self.program.parameter_bytes,1024)

    def test_forward_only_compute_does_not_require_inverse_tone_table(self):
        settings=Settings(tone=ToneSettings(input_nits=(0.,7.,45.,203.,1000.)))
        stack=self.stack([settings],['FORWARD']);solver=stack.solvers[0]
        self.assertIsNone(solver.tone_table);self.program.set_inverse(solver)
        points=np.array([[.1,.2,.3],[0,0,0]],dtype='f4')
        self.assert_parity(stack.bake_native(points),self.program.evaluate(points,2))
        with self.assertRaisesRegex(RuntimeError,'must be prepared'):
            self.program.evaluate(points,0)

    def test_black_forward_output_is_exact_for_inverse_reuse(self):
        black=np.zeros((1,3),dtype='f4');base=mixed()
        for tone in (ToneSettings(),ToneSettings(input_nits=(0.,7.,45.,203.,1000.)),
                     ToneSettings(input_nits=(.01,1.,90.,400.,4000.),fit=-2),
                     ToneSettings(input_nits=(0.,.0001,.01,203.,10000.),fit=3)):
            stack=self.stack([replace(base,tone=tone)],['INVERSE']);solver=stack.solvers[0]
            self.program.set_inverse(solver)
            np.testing.assert_array_equal(self.program.evaluate(black,2),0)
            raw=self.program.evaluate(black,3)
            np.testing.assert_array_equal(raw,0)
            for target,appearance in ((black,False),(raw,True)):
                np.testing.assert_array_equal(self.program.evaluate(target,int(appearance)),0)
                np.testing.assert_array_equal(solver.evaluate(target,appearance),0)

    def test_white_tip_direct_candidate_selection_matches_cpu(self):
        stack=self.stack([Settings(tone=ToneSettings(input_nits=(0.,7.,45.,203.,1000.)))],['INVERSE'])
        points=np.array([[1024,57.233760833740234,.7465960383415222],
            [1024,57.233760833740234,13.524435043334961],[0,1024,1024]],dtype='f4')
        self.assert_parity(stack.bake_native(points),stack.bake_native(points,'GPU'))

    def test_general_inverse_reports_recovered_and_exhausted_candidates(self):
        settings=replace(mixed(),tone=ToneSettings(input_nits=(0.,7.,45.,203.,1000.)))
        stack=self.stack([settings],['INVERSE']);solver=stack.solvers[0]
        target=np.array([[0,1024,1024],[2.662182331085205]*3],dtype='f4')
        cpu=stack.bake_native(target);gpu=stack.bake_native(target,'GPU')
        self.assert_parity(cpu,gpu)
        # The neutral witness is now recovered; the cube corner still exhausts
        # the finite search and must retain its actual failed residual.
        np.testing.assert_array_equal(gpu[:,3]<=solver.acceptance_limit(target),[False,True])
        self.assert_reported_error(solver,target,gpu)

    def test_signed_raw_handoff_with_extreme_chroma(self):
        stack=self.stack([Settings(color=ColorSettings(global_gain=10))],['INVERSE'])
        k=stack.kernels[0];points=np.array([[0,.2,0],[.2,0,0]],dtype='f4')
        raw=k.grade(k.enter(points));self.assertTrue(np.all(raw[:,3]<0))
        self.program.set_inverse(stack.solvers[0])
        np.testing.assert_allclose(self.program.evaluate(points,4),k.enter(points),rtol=2e-5,atol=2e-5)
        self.assert_parity(stack.solvers[0].evaluate(raw,True),self.program.evaluate(raw,1))

    def test_simple_inverse_selects_prior_black_or_direct_candidate(self):
        points=np.array([[0,0,0],[.1,.2,.3],[.04064936935901642,0,1024],
            [1024,57.233760833740234,.7465960383415222],[0,1024,1024]],dtype='f4')
        tone=ToneSettings(input_nits=(0.,7.,45.,203.,1000.))
        for settings in (Settings(color=ColorSettings(global_gain=.25)),
                         Settings(color=ColorSettings(global_gain=1.5)),Settings(tone=tone),
                         Settings(tone=tone,color=ColorSettings(global_gain=.25))):
            for hk_guard in (False,True):
                stack=LegacyCapacityBakeStack([settings],['INVERSE'],self.base.table,hk_guard=hk_guard, program_factory=ReferenceGPUProgram)
                solver=stack.solvers[0];k=solver.kernel
                self.program.set_inverse(solver)
                for appearance in (False,True):
                    with self.subTest(settings=settings,appearance=appearance,hk_guard=hk_guard):
                        target=k.enter(points) if appearance else points
                        prior=np.clip(k.export(target),0,1024) if appearance else target
                        raw=target if appearance else k.enter(prior)
                        direct=np.clip(k.export(solver.direct_state(raw)),0,1024)
                        candidates=np.stack((prior,np.zeros_like(prior),direct))
                        cpu=solver.evaluate(target,appearance);gpu=self.program.evaluate(target,int(appearance))
                        self.assert_parity(cpu,gpu)
                        # Both H-K modes return one of the raw inverse family's
                        # candidates, even when export guards prevent closure.
                        difference=np.max(abs(candidates-gpu[None,:,:3]),axis=-1)
                        limit=np.maximum(.001*np.max(abs(candidates),axis=-1),1e-7)
                        self.assertTrue(np.all(np.any(difference<=limit,axis=0)),(candidates,gpu))
                        self.assert_reported_error(solver,target,gpu,appearance)

    def test_hk_guard_knee_signed_energy_and_degenerate_limits(self):
        def source(data,offsets,expanded):
            return bake_gpu.source(data,offsets,expanded).split('void main()',1)[0]+'''
void main() {
    int id=int(gl_GlobalInvocationID.x);if(id>=sample_count||operation<0)return;
    ivec2 address=ivec2(id%256,id/256);vec4 v=texelFetch(input_pixels,address,0);
    imageStore(output_pixels,address,pg_hk_guard(vec4(v.x,v.y,0.0,v.z),v.w));
}
'''
        kernel=self.base.kernels[0]
        program=boundary_gpu.Program(kernel.data,source,True,kernel.table.expanded)
        self.program.set_inverse(self.base.solvers[0]);program.parameters=self.program.parameters
        h=np.array([20,20,20,20,20,20,0,-2,1e-8],dtype='f4')
        c=np.array([1,4,400/66,10,1000,10,0,10,1e-16],dtype='f4')
        b=np.sqrt(66*c);u=h-b;energy=u*(abs(u)+2*b)
        reference=np.array([100,100,100,100,100,0,0,100,1e-18],dtype='f4')
        points=np.column_stack((h,c,energy,reference))
        q=np.column_stack((h,c,np.zeros_like(h),energy));ref=np.zeros_like(q);ref[:,3]=reference
        expected=kernel._hk_export(q,ref);actual=program.evaluate(points)
        np.testing.assert_allclose(actual,expected,rtol=2e-6,atol=2e-6)
        np.testing.assert_array_equal(actual[[0,6,7]],q[[0,6,7]])
        self.assertTrue(np.all(actual[[1,2,3,4],3]>0))
        self.assertEqual(actual[5,3],0)

    def test_hk_export_rgb_inverse_and_raw_handoffs(self):
        settings=Settings(color=ColorSettings(global_gain=1.5))
        enabled=self.stack([settings],['INVERSE'])
        disabled=LegacyCapacityBakeStack([settings],['INVERSE'],self.base.table,hk_guard=False, program_factory=ReferenceGPUProgram)
        source=np.array([[.1,.2,.3],[.7,.2,.1],[.02,.08,.4],[0,.2,0],[0,0,0]],dtype='f4')
        solver=enabled.solvers[0];k=solver.kernel;toned=k.tone_state(k.enter(source));raw=k.grade(toned)
        repaired=k._hk_export(raw,toned)
        self.assertTrue(np.any(repaired[:,3]>raw[:,3]))
        target=k.evaluate(source)
        self.assertGreater(float(np.max(abs(target-disabled.kernels[0].evaluate(source)))),.001)
        self.program.set_inverse(solver)
        np.testing.assert_allclose(self.program.evaluate(source,2)[:,:3],target,rtol=3e-5,atol=2e-7)
        np.testing.assert_allclose(self.program.evaluate(source,3),raw,rtol=3e-5,atol=2e-5)
        gpu=self.program.evaluate(target);cpu=solver.evaluate(target)
        self.assert_parity(cpu,gpu);self.assert_reported_error(solver,target,gpu)
        # The raw inverse is validated against the guarded RGB map, without
        # an extra RGB solve to force repaired targets inside the tolerance.
        self.assertTrue(np.any(cpu[:,3]>solver.acceptance_limit(target)),cpu)
        self.assertTrue(np.any(gpu[:,3]>solver.acceptance_limit(target)),gpu)
        raw_inverse=self.program.evaluate(raw,1)
        self.assert_parity(solver.evaluate(raw,True),raw_inverse)
        self.assert_reported_error(solver,raw,raw_inverse,True)
        # Reusing a shader across reference/production modes updates the flag.
        self.program.set_inverse(disabled.solvers[0])
        np.testing.assert_allclose(self.program.evaluate(source,2)[:,:3],disabled.kernels[0].evaluate(source),rtol=3e-5,atol=2e-7)
        np.testing.assert_allclose(self.program.evaluate(source,3),raw,rtol=3e-5,atol=2e-5)
        np.testing.assert_array_equal(self.program.evaluate(raw,1),raw_inverse)

    def test_raw_pair_near_opponent_axis(self):
        stack=self.stack([Settings(color=ColorSettings(global_gain=.1)),Settings(color=ColorSettings(global_gain=.2))],['FORWARD','INVERSE'])
        points=np.array([[168.81788635253906,117.71593475341797,9.427742004394531]],dtype='f4')
        self.assert_parity(stack.bake_native(points),stack.bake_native(points,'GPU'))

