"""Actual helper GPU Stage 3 projection and native raster conformance."""
import unittest
import tempfile
from unittest.mock import patch
import numpy as np
from color_tools.perceptual_grade_core.jobs.codec import freeze_scope_request,thaw_scope_result
from color_tools.blender_runtime.execution.contracts import JobSpec
from color_tools import perceptual_grade_blender
from color_tools.perceptual_grade_blender.jobs.configuration import profile, seal
from color_tools.blender_runtime.blender.execution import create_runtime
from color_tools.blender_runtime.execution.machines import ExecutionMachines
from tests.support.session import SessionTest
from pathlib import Path
import bpy
from color_tools.perceptual_grade_blender.model import scope_cloud_gpu as cloud, bake_gpu, boundary_gpu
from color_tools.perceptual_grade_core.model import scope_analysis, scope_color, color, tone, linear, forward, saturation, lut
from tests.support.gpu import initialize


def descriptor(size=137,scale=1.):
    return dict(key=('native',size,scale),width=size+1,height=size+1,
        rect=(.25,.75,float(size),float(size)),scale=scale,
        bounds=tuple((-r,-r,r,r) for r in (1.12,1.2,1.4,1.6)))


def fixture(chromatic=None,rgba=None,tone_parameters=None):
    space=linear.GradeSpace('D65');tp=tone_parameters or tone.Parameters(input_midtones=43.)
    chromatic=chromatic or color.Parameters(global_gain=.3,web_hue_1_0=8.,web_scale_2_4=.1)
    if rgba is None:
        rng=np.random.default_rng(173)
        rgba=rng.uniform(.01,1.,(12,16,4));rgba[...,3]=rng.uniform(0.,1.,(12,16))
    base=scope_analysis.evaluate_samples(rgba,linear.Parameters(),tp,space)
    base['_colors']=scope_color.evaluate_all(base,chromatic,space)
    return base


def runtime_snapshot():
    space=linear.GradeSpace('D65');tp=tone.Parameters(input_midtones=43.)
    chromatic=color.Parameters(global_gain=.3,web_hue_1_0=8.,web_scale_2_4=.1)
    rgba=np.array([[[0.,0.,0.,1.],[1.,1.,1.,1.],[-.01,.4,.7,1.],[4.,.5,.1,1.]]])
    cube=lut.Cube(lut.lattice(),'runtime-captured-final',size=65)
    view=descriptor(65)
    return dict(base_key=('runtime-base',tp,space),key=('runtime-scope',chromatic),rgba=rgba,
        chain=(),label='GPU helper input',signal=(cube,np.eye(3),np.eye(3)),comparison=None,
        stack=False,space='Linear Rec.709',grading_space=space,params=chromatic,view=(2,True),
        tone=tp,linear=linear.Parameters(),matrix=np.eye(3),to_grade=np.eye(3),
        _scope_provenance=(('captured-final',65),),_scope_evaluation=('analytic','cloud-runtime-v1'),
        _warp_analysis_key=('runtime-analysis',),_warp_views=(view,))


class CloudGPUTests(SessionTest):
    @classmethod
    def setUpClass(cls):cls.gpu=initialize()

    def tearDown(self):cloud.clear()

    def test_full_cloud_population_survives_gpu_preparation_and_codec_fallback(self):
        from color_tools.perceptual_grade_core.jobs.codec import freeze_full_scope_result
        from collections import OrderedDict
        s=runtime_snapshot();shape=s['rgba'].shape[:2]
        s['sample_grid']=dict(mass=np.array([[.2,.4,1.1,2.3]]),
                              x=np.array([[.875,.625,.375,.125]]),key=('atlas-cloud',))
        result=scope_analysis.evaluate_snapshot(s,OrderedDict())
        wanted=cloud.render(result,[descriptor(191,2.)],False)[0]['pixels']
        actual=cloud.render(result,[descriptor(191,2.)],True)[0]
        self.assertEqual(actual['backend'],'gpu')
        error=abs(actual['pixels'].astype(int)-wanted.astype(int))
        self.assertLess(np.count_nonzero(error>1)/error.size,.002)
        decoded=thaw_scope_result(freeze_full_scope_result(result))
        for selected in decoded['_colors']:
            np.testing.assert_array_equal(selected['sample_mass'],s['sample_grid']['mass'])
            self.assertFalse(selected['sample_mass'].flags.writeable)
        np.testing.assert_array_equal(cloud.render(decoded,[descriptor(191,2.)],False)[0]['pixels'],wanted)

    def test_post_tone_compute_matches_analytic_projection_without_double_tone(self):
        result=fixture();model=result['_colors'][0]['model'];kernel=cloud._parameters(model)
        program=boundary_gpu.Program(kernel.data,cloud.source,True,kernel.table.expanded)
        bake_gpu.Program.set_kernel(program,kernel)
        appearance=result['stage2_appearance']
        source=cloud._state(appearance.q,appearance.ja*abs(appearance.ja))
        actual=program.evaluate(source,1)
        q,energy,_=forward.Model(model.tone,model).guarded_appearance(appearance)
        expected=saturation.bounded_project(q,energy).reshape(-1,2)
        np.testing.assert_allclose(actual[:,:2],expected,rtol=3e-4,atol=2e-5)
        np.testing.assert_array_equal(actual[:,2],energy.reshape(-1)<0)
        np.testing.assert_array_equal(actual[:,3],1)
        twice=model.tone.apply_appearance(appearance)
        tq,te,_=forward.Model(model.tone,model).guarded_appearance(twice)
        self.assertGreater(np.max(abs(saturation.bounded_project(tq,te).reshape(-1,2)-expected)),.005)

    def test_projection_retains_signed_zero_energy_and_neutral_branches(self):
        result=fixture();kernel=cloud._parameters(result['_colors'][0]['model'])
        program=boundary_gpu.Program(kernel.data,cloud.source,True,kernel.table.expanded)
        bake_gpu.Program.set_kernel(program,kernel)
        values=np.array([[1,3,4,0],[1,3,4,-9],[1,0,0,-9],[0,0,0,0],[10,-8,2,4]],dtype='f4')
        actual=program.evaluate(values,0)
        np.testing.assert_allclose(actual[:,:2],saturation.bounded_project(values[:,:3],values[:,3]),atol=2e-7)
        np.testing.assert_array_equal(actual[:,2],values[:,3]<0)

    def test_cloud_compute_matches_signed_hdr_neutral_reset_and_stack_rgb_inputs(self):
        rgba=np.array([[[0.,0.,0.,1.],[1.,1.,1.,1.],[-.01,.4,.7,1.],[4.,.5,.1,1.]]])
        stack=fixture(rgba=rgba);model=stack['_colors'][0]['model']
        stack['stack_output_rgb']=forward.Model(model.tone,model).apply(rgba[...,:3])
        stack['_colors']=scope_color.evaluate_all(stack,model.params,model.tone.space)
        cases=(
            ('regular-grade',fixture(rgba=rgba)),
            ('regular-grade-reset',fixture(color.Parameters(),rgba,tone.Parameters())),
            ('high-controls',fixture(color.Parameters(global_gain=16.,j_a_1=1.e6,
                c_high_1=16.,adaptance_a_2=32.,web_chroma_1_0=16.,web_scale_2_4=16.),rgba)),
            ('stack-after-rgb',stack),
        )
        view=descriptor(191,1.)
        for name,result in cases:
            with self.subTest(case=name):
                cloud.clear()
                actual=cloud.render(result,[view],True)[0]
                expected=cloud.render(result,[view],False)[0]
                self.assertEqual(actual['backend'],'gpu')
                self.assertEqual(actual['pixels'].dtype,np.uint8)
                # Test-only readback checks every projected sample, including
                # black; a nonfinite shader state must not silently disappear.
                layer=cloud._cache[id(result)].layers[0]
                points=np.array(layer.points.read(),dtype=np.float32).reshape(-1,4)[:layer.count]
                selection=result['_colors'][0]
                np.testing.assert_allclose(points[:,:2],selection['bounded_saturation'].reshape(-1,2),
                    rtol=3e-4,atol=2e-5)
                np.testing.assert_array_equal(points[:,2],selection['after_energy'].reshape(-1)<0)
                np.testing.assert_array_equal(points[:,3],1.)
                error=np.abs(actual['pixels'].astype(int)-expected['pixels'].astype(int))
                self.assertLess(np.count_nonzero(error>1)/error.size,.002)

    def test_cold_gpu_scope_helper_publishes_only_texture_tiles(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(bpy.utils, 'user_resource', return_value=directory):
                runtime=create_runtime(self.session.app,
                    machines=ExecutionMachines(*(self.session.machines[name] for name in ('attempt','gpu','retry','startup'))),
                    package=Path(perceptual_grade_blender.__file__).absolute().parent.parent,
                    profile=profile, seal=seal)
            try:
                handle=runtime.submit(JobSpec('scope_warp',
                    freeze_scope_request(runtime_snapshot()),lane='gpu',priority=1))
                result=thaw_scope_result(handle.result(timeout=120))
                self.assertEqual(handle.backend,'gpu')
                self.assertEqual(result['_warp_clouds'][0]['backend'],'gpu')
                pixels=result['_warp_clouds'][0]['pixels']
                self.assertEqual(pixels.dtype,np.uint8)
                self.assertEqual(pixels.shape,(1,4,66,66))
                for selected in result['_colors']:
                    self.assertTrue({'weights','after_energy','bounded_saturation','after',
                                     'saturation','_input','sample_indices'}.isdisjoint(selected))
            finally:
                report=runtime.shutdown()
                self.assertTrue(report.clean,report.errors)

    def test_raster_is_compact_and_reuses_gpu_points_on_resize(self):
        result=fixture();view=descriptor()
        actual=cloud.render(result,[view],True)[0]
        self.assertEqual(actual['backend'],'gpu');self.assertEqual(actual['pixels'].dtype,np.uint8)
        self.assertEqual(actual['pixels'].shape,(1,4,138,138))
        self.assertGreater(np.count_nonzero(actual['pixels']),100)
        expected=cloud.render(result,[view],False)[0]['pixels']
        error=np.abs(actual['pixels'].astype(int)-expected.astype(int))
        self.assertLess(np.count_nonzero(error>1)/error.size,.002)
        with patch.object(cloud,'_parameters',side_effect=AssertionError('recomputed Stage 3')):
            resized=cloud.render(result,[descriptor(183,1.5)],True)[0]
        self.assertEqual(resized['timings']['point_cache_hit'],1)
        self.assertEqual(resized['timings']['compute_submission_seconds'],0.)

    def test_raster_ignores_and_restores_dirty_depth_scissor_and_viewport(self):
        result=fixture();view=descriptor()
        expected=cloud.render(result,[view],True)[0]['pixels']
        state=self.gpu.state
        previous=(state.blend_get(),state.viewport_get(),state.depth_test_get(),state.scissor_get())
        try:
            state.blend_set('ADDITIVE');state.viewport_set(4,7,21,23)
            state.depth_test_set('GREATER');state.scissor_set(8,9,11,13)
            actual=cloud.render(result,[view],True)[0]['pixels']
            np.testing.assert_array_equal(actual,expected)
            self.assertEqual(state.blend_get(),'ADDITIVE')
            self.assertEqual(tuple(state.viewport_get()),(4,7,21,23))
            self.assertEqual(state.depth_test_get(),'GREATER')
            self.assertEqual(tuple(state.scissor_get()),(8,9,11,13))
        finally:
            state.blend_set(previous[0]);state.viewport_set(*previous[1])
            state.depth_test_set(previous[2]);state.scissor_set(*previous[3])

    def test_raster_preserves_reference_hollow_marks_and_tone_weights(self):
        result=fixture(color.Parameters())
        q=np.array([[10,3,2],[5,-2,3],[0,0,0],[1,2,-1]],float)
        energy=np.array([16,-9,0,0],float)
        signal=dict(appearance=q,energy=energy,bounded_saturation=saturation.bounded_project(q,energy))
        result['_comparisons_selected']=tuple(dict(signal=signal,weights=np.full(4,(t+1)/4)) for t in range(4))
        actual=cloud.render(result,[descriptor(191,2.)],True)[0]['pixels']
        expected=cloud.render(result,[descriptor(191,2.)],False)[0]['pixels']
        self.assertEqual(actual.shape,(2,4,192,192))
        error=np.abs(actual[1].astype(int)-expected[1].astype(int))
        self.assertLess(np.count_nonzero(error>1)/error.size,.0001)
        self.assertTrue(all(actual[1,t].sum()<actual[1,t+1].sum() for t in range(3)))

    def test_unsupported_ranges_require_explicit_cpu_fallback(self):
        result=fixture(color.Parameters(global_gain=100.))
        actual=cloud.render(result,[descriptor()],True)[0]
        self.assertEqual(actual['backend'],'cpu')
        self.assertIn('extended-range',actual['fallback_reason'])
        fallback=cloud.render(result,[descriptor()],False)[0]
        self.assertEqual(fallback['backend'],'cpu')
        np.testing.assert_array_equal(actual['pixels'],fallback['pixels'])

    def test_dense_cloud_crosses_compute_chunk_without_rounding_each_sample(self):
        result=fixture();count=70001
        q=np.broadcast_to([10.,0.,0.],(count,3));energy=np.full(count,100.)
        weights=np.full(count,.0001)
        result['_colors']=tuple(dict(value,after=q,after_energy=energy,weights=weights,
                                    opacity_weights=weights,sample_mass=np.ones(count))
                                for value in result['_colors'])
        result['stack_output_rgb']=True
        view=dict(key=('dense',),width=65,height=65,rect=(0.,0.,65.,65.),scale=1.,
                  bounds=((-1.,-1.,1.,1.),)*4)
        actual=cloud.render(result,[view],True)[0]['pixels']
        expected=round(255*(1-(1-.35*.0001)**count))
        self.assertEqual(actual.shape,(1,4,65,65))
        np.testing.assert_allclose(actual[0,:,32,32],expected,atol=1)
        self.assertEqual(np.count_nonzero(actual),4)
        self.assertEqual(len(cloud._cache[id(result)].layers),2)



if __name__=='__main__':unittest.main()
