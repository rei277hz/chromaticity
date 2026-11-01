"""Real GPU compact Stage 3 evaluation, histogram reduction and p95 gather."""
from collections import OrderedDict
from dataclasses import replace
import unittest
from unittest.mock import patch
import numpy as np
from color_tools.perceptual_grade_blender.model import scope_active as active,scope_active_gpu as active_gpu
from color_tools.perceptual_grade_core.model import color, tone, linear, scope_color, scope_analysis, saturation, lut
from color_tools.perceptual_grade_blender.model import scope_cloud_gpu
from tests.support.gpu import initialize


def fixture(identity=False):
    rng=np.random.default_rng(173);rgba=rng.uniform(.01,5.,(12,16,4))
    rgba[...,3]=rng.uniform(0.,1.,rgba.shape[:2])
    rgba[0,:4,:3]=[[0,0,0],[1,1,1],[-.01,.4,.7],[4.,.5,.1]]
    space=linear.GradeSpace('D65');tp=tone.Parameters() if identity else tone.Parameters(input_midtones=43.)
    cp=color.Parameters() if identity else color.Parameters(global_gain=.3,web_hue_1_0=8.,web_scale_2_4=.1)
    return dict(base_key=('test',identity),key=('test-output',identity),rgba=rgba,chain=(),label='Input',
        signal=None,comparison=(rgba.copy(),()),stack=False,space='Linear Rec.709',grading_space=space,
        tone=tp,params=cp,linear=linear.Parameters(),matrix=np.eye(3),to_grade=np.eye(3),
        _scope_provenance=(),_scope_evaluation=('analytic',),view=(2,True),
        _scope_demands=tuple((t,w) for t in range(4) for w in (False,True)),
        _warp_views=(dict(key=('native',),width=66,height=68,rect=(.25,.75,65.,67.),
            scale=1.,bounds=((-1.12,-1.12,1.12,1.12),)*4),))


class ActiveGPUTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.gpu=initialize()

    def tearDown(self):active_gpu.clear()

    def test_weighted_atlas_cpu_gpu_density_coordinates_and_opacity_agree(self):
        s=fixture(identity=True);shape=s['rgba'].shape[:2]
        mass=np.linspace(.15,3.,np.prod(shape)).reshape(shape);mass[0,0]=0.
        # Reverse source x to prove the GPU uses coordinates rather than packed columns.
        x=np.broadcast_to((np.arange(shape[1])[::-1]+.5)/shape[1],shape)
        s['sample_grid']=dict(mass=mass,x=x,key=('udim-weighted',))
        actual=active.visual(active.prepare(s,OrderedDict()),s,True)
        expected=active.visual(active.prepare(s,OrderedDict()),s,False)
        self.assertEqual(actual['_active_backend'],'gpu')
        for index in range(4):
            a=actual['_active_colors'][f'{index}:jc'];b=expected['_active_colors'][f'{index}:jc']
            for field in ('waveform_levels','vectorscope_levels'):
                error=abs(a[field].astype(int)-b[field].astype(int))
                self.assertLess(np.count_nonzero(error>1)/error.size,.005)
            for name in ('low','high'):
                np.testing.assert_allclose(a['histograms'][name],b['histograms'][name],rtol=8e-4,atol=5e-5)
        for a,b in zip(actual['_warp_clouds'],expected['_warp_clouds']):
            error=abs(a['pixels'].astype(int)-b['pixels'].astype(int))
            self.assertLess(np.count_nonzero(error>1)/error.size,.005)

    def test_selected_gpu_grade_render_reduction_and_gather_match_cpu(self):
        for identity in (False,True):
            s=fixture(identity);base=active.prepare(s,OrderedDict())
            with (patch.object(scope_analysis,'evaluate_snapshot',side_effect=AssertionError('full CPU analysis')),
                  patch.object(active,'_cpu_output',side_effect=AssertionError('CPU output fallback')),
                  patch.object(color.Model,'capacity',side_effect=AssertionError('CPU capacity work'))):
                actual=active.visual(base,s,True)
            self.assertTrue(all(selected['capacity'] is None for selected in base['groups'].values()))
            expected=active.visual(active.prepare(s,OrderedDict()),s,False)
            self.assertEqual(actual['_active_backend'],'gpu')
            for index in range(4):
                _,selected,out=active.output(base,s,index,True)
                model,_,cpu=active.output(base,s,index,False)
                count=len(selected['ids'])
                state=np.array(out['state'].read(),np.float32).reshape(-1,4)[:count]
                np.testing.assert_allclose(state[:,:3],cpu['q'],rtol=3e-4,atol=4e-4)
                np.testing.assert_allclose(state[:,3],cpu['energy'],rtol=3e-4,atol=2e-3)
                points=active_gpu.gather(out,selected['sample_ids'])
                expected_points=saturation.project(cpu['q'][selected['sample_ids']],cpu['energy'][selected['sample_ids']])
                np.testing.assert_allclose(points,expected_points,rtol=5e-4,atol=2e-5)
                self.assertLessEqual(points.nbytes,4096)
                gpu_jc=actual['_active_colors'][f'{index}:jc'];cpu_jc=expected['_active_colors'][f'{index}:jc']
                for field in ('waveform_levels','vectorscope_levels'):
                    error=abs(gpu_jc[field].astype(int)-cpu_jc[field].astype(int))
                    self.assertLess(np.count_nonzero(error>1)/error.size,.005)
                for driver in ('low','high'):
                    np.testing.assert_allclose(gpu_jc['histograms'][driver],cpu_jc['histograms'][driver],rtol=8e-4,atol=5e-5)
                np.testing.assert_allclose(gpu_jc['sectors'],cpu_jc['sectors'],rtol=8e-4,atol=5e-5)
                self.assertEqual(gpu_jc['sectors'].nbytes,192)
            for a,b in zip(actual['_warp_clouds'],expected['_warp_clouds']):
                self.assertEqual(a['pixels'].shape,(2,1,68,66))
                error=abs(a['pixels'].astype(int)-b['pixels'].astype(int))
                self.assertLess(np.count_nonzero(error>1)/error.size,.005)

    def test_linear_gather_preserves_zero_energy_policy_and_duplicate_ids(self):
        s=fixture();base=active.prepare(s,OrderedDict());model,selected,out=active.output(base,s,2,True)
        from color_tools.perceptual_grade_blender.model.scope_cloud_gpu import _texture
        q=np.array([[1,3,4,0],[1,3,4,-9],[1,0,0,-9],[0,0,0,0],[10,-8,2,4]],np.float32)
        out=dict(state=_texture(q))
        ids=np.array([0,1,1,2,3,4],np.int32)
        actual=active_gpu.gather(out,ids)
        expected=saturation.project(q[ids,:3],q[ids,3])
        np.testing.assert_allclose(actual,expected,rtol=1e-6,atol=0,equal_nan=True)
        self.assertNotIn('_gather_cache',out)

    def test_gather_resources_are_group_owned_and_reused_across_stage3_edits(self):
        s=fixture();rng=np.random.default_rng(71)
        rgba=np.ones((32,32,4),float)
        rgba[...,:3]=.2+rng.normal(0,.001,rgba[...,:3].shape)
        s.update(rgba=rgba,comparison=(rgba.copy(),()),_scope_demands=((1,True),))
        bases=OrderedDict();base=active.prepare(s,bases)
        _,selected,out=active.output(base,s,1,True)
        ids=selected['sample_ids']
        self.assertEqual(len(ids),512)
        first=active_gpu.gather(out,ids)
        cache=selected['gpu']['gather_cache']
        self.assertIs(out['_gather_cache'],cache)
        self.assertEqual(set(cache),{'ids','indices','points'})
        self.assertFalse(cache['ids'].flags.writeable)
        self.assertFalse(np.shares_memory(cache['ids'],ids))
        indices,points=cache['indices'],cache['points']
        edited=dict(s,params=replace(s['params'],global_gain=.8))
        self.assertIs(active.prepare(edited,bases),base)
        _,same,next_out=active.output(base,edited,1,True)
        self.assertIs(same,selected)
        self.assertIs(next_out['_gather_cache'],cache)
        updated=active_gpu.gather(next_out,ids)
        self.assertIs(cache['indices'],indices)
        self.assertIs(cache['points'],points)
        self.assertFalse(np.array_equal(first,updated))
        _,_,cpu=active.output(base,edited,1,False)
        expected=saturation.project(cpu['q'][ids],cpu['energy'][ids])
        np.testing.assert_allclose(updated,expected,rtol=5e-4,atol=2e-5)
        other=active.prepare(dict(edited,_scope_source_cache_id='other-source'),bases)
        _,other_selected,other_out=active.output(other,edited,1,True)
        active_gpu.gather(other_out,other_selected['sample_ids'])
        self.assertIsNot(other_selected['gpu']['gather_cache'],cache)
        self.assertIsNot(other_selected['gpu']['gather_cache']['indices'],indices)
        self.assertIsNot(other_selected['gpu']['gather_cache']['points'],points)

    def test_gather_cache_tracks_arbitrary_ids_without_mutating_callers(self):
        from color_tools.perceptual_grade_blender.model.scope_cloud_gpu import _texture
        state=np.array([[1,3,4,-9],[1,1,2,4],[1,-2,1,9]],np.float32)
        cache={};out=dict(state=_texture(state),_gather_cache=cache)
        ids=np.array([0,1,1,2],np.int32)
        actual=active_gpu.gather(out,ids)
        np.testing.assert_allclose(actual,saturation.project(state[ids,:3],state[ids,3]),
                                   rtol=1e-6,atol=0)
        self.assertTrue(ids.flags.writeable)
        indices,points=cache['indices'],cache['points']
        np.testing.assert_array_equal(cache['ids'],ids)
        empty=active_gpu.gather(out,np.array([],np.int32))
        self.assertEqual((empty.shape,empty.dtype),((0,2),np.dtype(np.float32)))
        with self.assertRaisesRegex(ValueError,'512'):
            active_gpu.gather(out,np.zeros(513,np.int32))
        self.assertIs(cache['indices'],indices)
        self.assertIs(cache['points'],points)
        ids[:]=[2,1,0,0]
        np.testing.assert_array_equal(cache['ids'],[0,1,1,2])
        actual=active_gpu.gather(out,ids)
        np.testing.assert_allclose(actual,saturation.project(state[ids,:3],state[ids,3]),
                                   rtol=1e-6,atol=0)
        self.assertIsNot(cache['indices'],indices)
        self.assertIsNot(cache['points'],points)
        np.testing.assert_array_equal(cache['ids'],ids)

    def test_gpu_quantization_matches_round_even_reference_and_maximum_floor(self):
        values=np.zeros((160,336),np.float32)
        values[0,:144]=np.linspace(0,.9,144);values[1,144:]=np.arange(192)%17
        tex=self.gpu.types.GPUTexture((336,160),format='R32F',data=self.gpu.types.Buffer('FLOAT',values.shape,values))
        actual=active_gpu._levels(tex)
        np.testing.assert_array_equal(actual['vectorscope_levels'],active.density_levels(values[:144,:144]))
        np.testing.assert_array_equal(actual['waveform_levels'],active.density_levels(values[:,144:]))

    def test_grade_stack_final_lut_and_invalid_samples_match_cpu_without_regrading(self):
        s=fixture();cube=lut.Cube(lut.lattice()*.3,'gpu-stack',size=65)
        s.update(stack=True,signal=(cube,np.eye(3),np.eye(3)),params=color.Parameters(global_gain=3.),
                 _scope_provenance=(('gpu-stack',65),))
        s['rgba'][0,4,0]=np.nan;s['rgba'][0,5,3]=np.inf
        s['comparison'][0][0,6,1]=np.inf;s['comparison'][0][0,7,3]=np.nan
        base=active.prepare(s,OrderedDict())
        with patch.object(active,'_cpu_output',side_effect=AssertionError('Stack GPU fallback')):
            actual=active.visual(base,s,True)
        expected=active.visual(active.prepare(s,OrderedDict()),s,False)
        self.assertEqual(actual['_active_backend'],'gpu')
        np.testing.assert_array_equal(base['tone_id'][0,4:6],[255,255])
        for index in range(4):
            model,selected,out=active.output(base,s,index,True)
            state=np.array(out['state'].read(),np.float32).reshape(-1,4)[:len(selected['ids'])]
            np.testing.assert_allclose(state[:,:3],selected['q'],rtol=1e-6,atol=1e-6)
            np.testing.assert_allclose(state[:,3],selected['energy'],rtol=1e-6,atol=1e-6)
            gpu_jc=actual['_active_colors'][f'{index}:jc'];cpu_jc=expected['_active_colors'][f'{index}:jc']
            for layer,reference in ((gpu_jc,cpu_jc),(gpu_jc['_comparison'],cpu_jc['_comparison'])):
                for field in ('waveform_levels','vectorscope_levels'):
                    error=np.abs(layer[field].astype(int)-reference[field].astype(int))
                    self.assertLess(np.count_nonzero(error>1)/error.size,.005)
            self.assertEqual(actual['_active_colors'][f'{index}:warp']['_comparison'],dict(available=True))

    def test_extended_controls_and_raster_limits_fall_back_to_texture_only_cpu(self):
        for high_controls in (True,False):
            with self.subTest(high_controls=high_controls):
                s=fixture();s['_scope_demands']=((2,True),(2,False))
                if high_controls:s['params']=color.Parameters(global_gain=128.)
                base=active.prepare(s,OrderedDict())
                if high_controls:actual=active.visual(base,s,True)
                else:
                    with patch.object(active_gpu,'warp',side_effect=scope_cloud_gpu.UnsupportedGPUCloud('test target limit')):
                        actual=active.visual(base,s,True)
                    self.assertEqual(actual['_active_fallback_reason'],'test target limit')
                expected=active.visual(active.prepare(s,OrderedDict()),s,False)
                self.assertEqual(actual['_active_backend'],'cpu')
                self.assertEqual(actual['_warp_clouds'][0]['backend'],'cpu')
                np.testing.assert_array_equal(actual['_warp_clouds'][0]['pixels'],expected['_warp_clouds'][0]['pixels'])
                for field in ('waveform_levels','vectorscope_levels'):
                    np.testing.assert_array_equal(actual['_active_colors']['2:jc'][field],
                                                  expected['_active_colors']['2:jc'][field])
                statistics=active.statistics(base,s)['_active_statistics']['2']['neutral']
                self.assertTrue(np.isfinite(statistics['covariance']).all())

    def test_scope_probe_compares_actual_products_and_rejects_blank_nonempty_density(self):
        from color_tools.perceptual_grade_blender.jobs.handlers import scopes
        class Context:
            role='scope_gpu'
            def checkpoint(self):pass
        result=scopes.probe(None,Context())
        self.assertTrue(result['conformance'])
        self.assertIn('linear_gather',result['checks']);self.assertIn('empty_group',result['checks'])
        self.assertIn('hue_sectors',result['checks'])
        render=active_gpu.jc
        def blank(*args,**kwargs):
            result=render(*args,**kwargs)
            result['waveform_levels']=np.zeros((160,192),np.uint8)
            return result
        with patch.object(active_gpu,'jc',side_effect=blank):
            with self.assertRaisesRegex(ArithmeticError,'nonempty density is blank'):
                scopes.probe(None,Context())
        histogram=active_gpu.histograms
        def blank_sectors(*args,**kwargs):
            result=histogram(*args,**kwargs);result['sectors']=np.zeros(48,np.float32)
            return result
        with patch.object(active_gpu,'histograms',side_effect=blank_sectors):
            with self.assertRaises(AssertionError):scopes.probe(None,Context())


if __name__=='__main__':unittest.main()
