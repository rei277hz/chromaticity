"""Exclusive input groups, compact receipts and demand-driven CPU fallback."""
from collections import OrderedDict
from dataclasses import replace
import unittest
from unittest.mock import patch,Mock
import numpy as np
from color_tools.perceptual_grade_core.model import color, tone, linear, scope_color, scope_analysis, statistics, lut, forward
from color_tools.perceptual_grade_blender.model import scope_active


def snapshot():
    space=linear.GradeSpace('D65');tp=tone.Parameters()
    # Exact neutrals span all four tone groups; duplicated rows expose image x.
    rgba=np.ones((3,8,4),float)
    rgba[...,:3]=np.array([.001,.01,.03,.1,.4,1.,3.,8.])[None,:,None]
    rgba[1,2,3]=.2;rgba[2,0,3]=0.
    return dict(base_key=('base',),key=('output',),rgba=rgba,chain=(),label='Input',
        signal=None,comparison=(rgba.copy(),()),stack=False,space='Linear Rec.709',
        grading_space=space,params=color.Parameters(global_gain=.3),view=(2,True),tone=tp,
        linear=linear.Parameters(),matrix=np.eye(3),to_grade=np.eye(3),
        _scope_provenance=(),_scope_evaluation=('analytic',),
        _scope_demands=((2,True),(2,False)),_scope_source_cache_id=('source',1),
        _warp_views=(dict(key=('native',),width=31,height=33,rect=(.25,.75,30.,32.),
            scale=1.,bounds=((-1.12,-1.12,1.12,1.12),)*4,tone=2),))


class ActiveScopeTests(unittest.TestCase):
    def test_neutral_membership_is_strict_linear_saturation_with_signed_black_rules(self):
        lower=np.nextafter(.1,0.);upper=np.nextafter(.1,np.inf)
        q=np.array([[1.,lower,0.],[1.,.1,0.],[1.,upper,0.],
                    [0.,0.,0.],[0.,.01,0.],[-1.,.05,0.],
                    [1.,0.,0.],[np.nan,0.,0.],[1.,np.inf,0.]])
        energy=np.array([1.,1.,1.,0.,0.,-1.,np.inf,1.,1.])
        np.testing.assert_array_equal(scope_color.near_neutral(q,energy),
                                      [True,False,False,True,False,True,False,False,False])
        # The same linear saturation at different tones has the same membership.
        scale=np.array([.01,1.,100.])
        for saturation,expected in ((.099,True),(.101,False)):
            states=np.column_stack([scale,saturation*scale,np.zeros(3)])
            np.testing.assert_array_equal(scope_color.near_neutral(states,scale**2),
                                          np.full(3,expected))

    def test_hash_selection_matches_full_grid_original_pixels_and_is_cached(self):
        s=snapshot();rng=np.random.default_rng(31)
        rgba=np.ones((50,80,4));rgba[...,:3]=np.tile([.005,.1,1.,8.],(50,20))[...,None]
        rgba[...,:3]*=rng.uniform(.99,1.01,rgba[...,:3].shape)
        rgba[...,3]=rng.uniform(.1,1.,rgba.shape[:2])
        s.update(rgba=rgba,comparison=None);cache=OrderedDict()
        base=scope_active.prepare(s,cache);model=color.model(s['tone'],s['params'],s['grading_space'])
        data=scope_color._input_analysis(base,model)
        for index in range(4):
            selected=scope_active.group(base,model,index)
            legacy=scope_color._selection(data,index)
            self.assertEqual(len(selected['sample_ids']),512)
            np.testing.assert_array_equal(selected['ids'][selected['sample_ids']],legacy['sample_indices'])
            self.assertEqual(len(np.unique(selected['sample_ids'])),512)
        edited=dict(s,params=replace(s['params'],global_gain=.9),view=(3,False))
        with patch.object(statistics,'hashed_sample',side_effect=AssertionError('selection recomputed')):
            self.assertIs(scope_active.prepare(edited,cache),base)
            for index in range(4):self.assertIs(scope_active.group(base,model,index),base['groups'][index])
        for changed in (dict(s,base_key=('new-stage2',)),dict(s,_scope_source_cache_id=('source',2))):
            self.assertIsNot(scope_active.prepare(changed,cache),base)

    def test_warp_selection_skips_capacity_and_cpu_histograms_cache_it(self):
        s=snapshot();base=scope_active.prepare(s,OrderedDict())
        model=color.model(s['tone'],s['params'],s['grading_space'])
        with patch.object(model,'capacity',wraps=model.capacity) as capacity:
            selected=scope_active.group(base,model,2)
            self.assertEqual(capacity.call_count,0);self.assertIsNone(selected['capacity'])
            first=scope_active._histograms(selected,model)
            second=scope_active._histograms(selected,model)
            self.assertEqual(capacity.call_count,1)
        for name in first:np.testing.assert_array_equal(first[name],second[name])

    def test_active_input_histograms_and_sectors_match_legacy_and_survive_codec(self):
        from color_tools.perceptual_grade_core.jobs import codec
        s=snapshot();s['_scope_demands']=tuple((index,False) for index in range(4))
        s['rgba'][...,:3]*=np.random.default_rng(9).uniform(.5,1.5,s['rgba'][...,:3].shape)
        base=scope_active.prepare(s,OrderedDict())
        result=scope_active.visual(base,s,False)
        legacy=scope_analysis.evaluate_snapshot(s,OrderedDict())['_colors']
        decoded=codec.thaw_scope_result(codec.freeze_scope_result(result))
        total=0
        for index in range(4):
            current=result['_active_colors'][f'{index}:jc']
            self.assertEqual(set(current['histograms']),{'low','high'})
            for name in ('low','high'):
                np.testing.assert_allclose(current['histograms'][name],legacy[index]['histograms'][name],rtol=1e-7,atol=1e-9)
            sectors=current['sectors'];total+=float(sectors.sum())
            self.assertEqual((sectors.shape,sectors.dtype,sectors.nbytes),((48,),np.dtype(np.float32),192))
            np.testing.assert_allclose(sectors,legacy[index]['sectors'],rtol=1e-7,atol=1e-9)
            np.testing.assert_array_equal(decoded['_active_colors'][f'{index}:jc']['sectors'],sectors)
            self.assertFalse(decoded['_active_colors'][f'{index}:jc']['sectors'].flags.writeable)
        self.assertGreater(total,0.)
        edited=dict(s,params=replace(s['params'],global_gain=.9))
        with patch.object(scope_active,'_histograms',side_effect=AssertionError('input diagnostics recomputed')):
            repeated=scope_active.visual(base,edited,False)
        for index in range(4):
            self.assertIs(repeated['_active_colors'][f'{index}:jc']['sectors'],
                          result['_active_colors'][f'{index}:jc']['sectors'])

    def test_exact_midpoints_partition_and_invalid_sentinel(self):
        model=color.model(tone.Parameters(),color.Parameters(),linear.GradeSpace('D65'))
        cuts=(model.anchors[:-1]+model.anchors[1:])*.5
        values=np.array([0.,np.nextafter(cuts[0],-np.inf),cuts[0],
            cuts[1],cuts[2],1e10,np.nan,np.inf])
        np.testing.assert_array_equal(scope_color.tone_groups(model,values),[0,0,1,2,3,3,255,255])
        weights=scope_color.analysis_weights(model,values)
        np.testing.assert_array_equal(weights.sum(axis=1),[1,1,1,1,1,1,0,0])

    def test_registration_has_one_uint8_group_and_prepared_identity_is_reused(self):
        s=dict(snapshot(),params=color.Parameters());base=scope_active.prepare(s,OrderedDict())
        self.assertEqual(base['tone_id'].dtype,np.uint8)
        with patch.object(scope_analysis,'evaluate_snapshot',side_effect=AssertionError('full analysis')):
            result=scope_active.visual(base,s,False)
        out=next(iter(base['outputs'].values()));selected=base['groups'][2]
        np.testing.assert_array_equal(out['rgb'],selected['rgb'])
        self.assertEqual(set(base['groups']),{2})
        self.assertEqual(set(result['_active_colors']),{'2:jc','2:warp'})

    def test_compact_receipt_matches_legacy_hard_group_jc_and_p95(self):
        s=snapshot();base=scope_active.prepare(s,OrderedDict())
        result=scope_active.visual(base,s,False)
        legacy=scope_analysis.evaluate_snapshot(s,OrderedDict())['_colors'][2]
        jc=result['_active_colors']['2:jc']
        np.testing.assert_array_equal(jc['waveform_levels'],scope_active.density_levels(legacy['waveform_selected']))
        np.testing.assert_array_equal(jc['vectorscope_levels'],scope_active.density_levels(legacy['vectorscope']['density']))
        stats=scope_active.statistics(base,s)['_active_statistics']['2']['neutral']
        for field in ('center','covariance','ellipse_covariance'):
            np.testing.assert_allclose(stats[field],legacy['neutral'][field],rtol=1e-12,atol=1e-12)
        self.assertEqual(stats['count'],legacy['neutral']['count'])
        record=result['_warp_clouds'][0]
        self.assertEqual(record['pixels'].shape,(2,1,33,31));self.assertEqual(record['tone'],2)
        def arrays(value):
            if isinstance(value,np.ndarray):yield value
            elif isinstance(value,dict):
                for child in value.values():yield from arrays(child)
            elif isinstance(value,(tuple,list)):
                for child in value:yield from arrays(child)
        self.assertTrue(all(a.shape not in ((24,3),(24,2),(3,8,4)) for a in arrays(result)))

    def test_controls_and_view_changes_reuse_membership_and_neutral_ids(self):
        s=snapshot();cache=OrderedDict();base=scope_active.prepare(s,cache)
        scope_active.visual(base,s,False);selected=base['groups'][2]
        edited=dict(s,params=replace(s['params'],global_gain=.9))
        with patch.object(scope_active,'group',wraps=scope_active.group) as group:
            same=scope_active.prepare(edited,cache)
            scope_active.visual(same,edited,False)
        self.assertIs(same,base);self.assertIs(base['groups'][2],selected)
        self.assertEqual(len(base['outputs']),2)
        changed=dict(s,_scope_source_cache_id=('source',2))
        self.assertIsNot(scope_active.prepare(changed,cache),base)

    def test_reference_uses_primary_group_and_product_alpha(self):
        s=snapshot();ref=s['comparison'][0].copy();ref[...,:3]=100.;ref[...,3]=.25
        s['comparison']=(ref,());base=scope_active.prepare(s,OrderedDict())
        model=color.model(s['tone'],s['params'],s['grading_space'])
        selected=scope_active.group(base,model,2)
        np.testing.assert_array_equal(selected['comparison']['alpha'],selected['alpha']*.25)
        self.assertEqual(len(selected['comparison']['q']),len(selected['q']))
        result=scope_active.visual(base,s,False)
        self.assertEqual(result['_active_colors']['2:warp']['_comparison'],dict(available=True))

    def test_invalid_samples_are_excluded_before_encoding_without_changing_primary_groups(self):
        s=snapshot();rgba=s['rgba'];ref=s['comparison'][0]
        rgba[0,0,0]=np.nan;rgba[0,1,1]=np.inf
        rgba[0,2,3]=np.nan;rgba[0,3,3]=np.inf;rgba[0,4,3]=-1.;rgba[0,5,3]=0.
        ref[1,4,0]=np.nan;ref[2,4,2]=-np.inf
        ref[1,5,3]=np.nan;ref[2,5,3]=np.inf
        original=rgba.copy();reference=ref.copy()
        with patch.object(scope_analysis,'apply_chain',wraps=scope_analysis.apply_chain) as chain:
            base=scope_active.prepare(s,OrderedDict())
        for args in chain.call_args_list:self.assertTrue(np.isfinite(args.args[0]).all())
        np.testing.assert_array_equal(base['tone_id'][0,:6],np.full(6,255,np.uint8))
        np.testing.assert_array_equal(base['alpha'][0,:6],np.zeros(6))
        np.testing.assert_array_equal(rgba,original);np.testing.assert_array_equal(ref,reference)
        result=scope_active.visual(base,s,False)
        group=base['groups'][2];reference_alpha=group['comparison']['alpha']
        expected_valid=np.isfinite(ref).all(axis=-1)&(ref[...,3]>0)
        expected_alpha=np.where(expected_valid,np.clip(ref[...,3],0,1),0.)
        np.testing.assert_array_equal(reference_alpha,
            group['alpha']*expected_alpha.reshape(-1)[group['ids']])
        self.assertTrue(np.isfinite(group['comparison']['q']).all())
        self.assertTrue(np.isfinite(result['_active_colors']['2:jc']['histograms']['low']).all())
        self.assertEqual(result['_warp_clouds'][0]['pixels'].shape,(2,1,33,31))

    def test_reference_shape_must_match_primary_grid(self):
        s=snapshot();s['comparison']=(s['rgba'][:1].copy(),())
        with self.assertRaisesRegex(ValueError,'reference RGBA shape must match'):
            scope_active.prepare(s,OrderedDict())
        for rgba in (np.ones((3,8,3)),np.ones((0,8,4)),np.ones((8,4))):
            with self.assertRaisesRegex(ValueError,'nonempty H x W x 4'):
                scope_active.prepare(dict(snapshot(),rgba=rgba),OrderedDict())

    def test_reference_and_final_provenance_changes_invalidate_registered_base(self):
        s=snapshot();cache=OrderedDict();old=scope_active.prepare(s,cache)
        edited=s['comparison'][0].copy();edited[...,:3]*=.3;edited[...,3]=.5
        next_source=dict(s,comparison=(edited,()),_scope_source_cache_id=('source',2))
        new=scope_active.prepare(next_source,cache)
        self.assertIsNot(new,old)
        np.testing.assert_array_equal(new['tone_id'],old['tone_id'])
        self.assertFalse(np.array_equal(new['comparison']['q'],old['comparison']['q']))
        np.testing.assert_array_equal(new['comparison']['alpha'],np.full((3,8),.5))
        final=dict(next_source,_scope_provenance=(('new-final',65),))
        self.assertIsNot(scope_active.prepare(final,cache),new)

    def test_grade_stack_samples_final_cube_and_matches_hard_scope_oracle(self):
        s=snapshot();cube=lut.Cube(lut.lattice()*.3,'final-stack',size=65)
        s.update(stack=True,signal=(cube,np.eye(3),np.eye(3)),
                 params=color.Parameters(global_gain=3.),_scope_provenance=(('final-stack',65),))
        base=scope_active.prepare(s,OrderedDict())
        expected=scope_analysis.evaluate_signal(s['rgba'][...,:3],s['signal'])
        # Invisible raw samples are deliberately zeroed before the LUT.
        expected=np.where((s['rgba'][...,3]>0)[...,None],expected,0.)
        np.testing.assert_allclose(base['stack_output_rgb'],expected,rtol=0,atol=0)
        with patch.object(forward.Model,'guarded_appearance',side_effect=AssertionError('Stack regrade')):
            result=scope_active.visual(base,s,False)
        legacy=scope_analysis.evaluate_snapshot(s,OrderedDict())['_colors'][2]
        jc=result['_active_colors']['2:jc']
        np.testing.assert_array_equal(jc['waveform_levels'],scope_active.density_levels(legacy['waveform_selected']))
        np.testing.assert_array_equal(jc['vectorscope_levels'],scope_active.density_levels(legacy['vectorscope']['density']))
        neutral=scope_active.statistics(base,s)['_active_statistics']['2']['neutral']
        self.assertEqual(neutral['count'],legacy['neutral']['count'])
        np.testing.assert_allclose(neutral['covariance'],legacy['neutral']['covariance'],rtol=1e-12,atol=1e-12)

    def test_extended_controls_use_authoritative_cpu_fallback_for_compact_group(self):
        s=snapshot();s['rgba']=np.array([[[.1,.12,.08,1.],[.4,.38,.42,1.]]])
        s.update(comparison=None,params=color.Parameters(global_gain=256.),
                 _scope_demands=((1,False),),_warp_views=())
        base=scope_active.prepare(s,OrderedDict())
        model,selected,out=scope_active.output(base,s,1,False)
        engine=forward.Model(model.tone,model)
        self.assertFalse(engine.vector_controls);self.assertGreater(len(selected['ids']),0)
        expected=engine.apply(base['stage1_rgb'].reshape(-1,3)[selected['ids']])
        np.testing.assert_allclose(out['rgb'],expected,rtol=2e-12,atol=2e-12)
        self.assertTrue(np.isfinite(out['q']).all())

    def test_statistics_cancellation_interrupts_fit(self):
        class Cancelled(Exception):pass
        calls=[]
        def checkpoint():
            calls.append(1)
            if len(calls)==4:raise Cancelled()
        with self.assertRaises(Cancelled):
            statistics.describe_sample(np.random.default_rng(1).normal(size=(512,2)),checkpoint=checkpoint)
        self.assertEqual(len(calls),4)

    def test_empty_demanded_group_keeps_small_finite_receipt(self):
        s=snapshot();s['rgba'][...,:3]=0.;s['comparison']=None
        base=scope_active.prepare(s,OrderedDict());result=scope_active.visual(base,s,False)
        jc=result['_active_colors']['2:jc'];self.assertFalse(jc['waveform_levels'].any())
        self.assertFalse(jc['sectors'].any());self.assertTrue(np.isfinite(jc['sectors']).all())
        neutral=scope_active.statistics(base,s)['_active_statistics']['2']['neutral']
        self.assertEqual(neutral['count'],0);self.assertTrue(neutral['reference'])

    def test_atlas_distribution_uses_population_and_source_x_not_storage_columns(self):
        grid=dict(mass=np.array([[.5,1.5,0.]]),x=np.array([[.9,.1,.5]]),key=('tiles',))
        values=scope_analysis.distribution(np.array([[.25,.25,.25]]),np.ones((1,3)),1.,grid)
        self.assertEqual(values['density'][40,172],.5)
        self.assertEqual(values['density'][40,19],1.5)
        self.assertEqual(values['density'].sum(),2.)
        self.assertEqual(values['histogram'].sum(),2.)
        self.assertEqual(values['count'],2.)

    def test_mass_stays_separate_from_alpha_and_reference_uses_primary_domain(self):
        s=snapshot();shape=s['rgba'].shape[:2]
        mass=np.linspace(.2,3.,np.prod(shape)).reshape(shape);mass[0,0]=0.
        x=np.broadcast_to((np.arange(shape[1])[::-1]+.5)/shape[1],shape)
        s['sample_grid']=dict(mass=mass,x=x,key=('atlas',1))
        cache=OrderedDict();base=scope_active.prepare(s,cache)
        model=color.model(s['tone'],s['params'],s['grading_space'])
        for index in range(4):
            selected=scope_active.group(base,model,index);ids=selected['ids']
            np.testing.assert_array_equal(selected['mass'],mass.ravel()[ids])
            np.testing.assert_allclose(selected['x'],x.ravel()[ids])
            np.testing.assert_array_equal(selected['alpha'],s['rgba'][...,3].ravel()[ids])
            np.testing.assert_array_equal(selected['comparison']['mass'],selected['mass'])
            np.testing.assert_array_equal(selected['comparison']['alpha'],selected['alpha']**2)
            self.assertEqual(selected['width'],1)
        changed=dict(s,sample_grid=dict(s['sample_grid'],key=('atlas',2)))
        self.assertIsNot(scope_active.prepare(changed,cache),base)
        current=scope_active.visual(base,s,False)
        legacy=scope_analysis.evaluate_snapshot(s,OrderedDict())['_colors'][2]
        np.testing.assert_array_equal(current['_active_colors']['2:jc']['waveform_levels'],
                                      scope_active.density_levels(legacy['waveform_selected']))
        for name in ('low','high'):
            np.testing.assert_allclose(current['_active_colors']['2:jc']['histograms'][name],
                                       legacy['histograms'][name],rtol=1e-7,atol=1e-9)

    def test_nonuniform_small_population_resamples_before_equal_weight_fit(self):
        from color_tools.perceptual_grade_core.model import scope_grid
        points=np.array([[0.,0.],[1.,0.],[0.,1.],[1.,1.]])
        selected,ids=scope_grid.sample(points,np.ones(4),np.array([100.,.1,.1,.1]))
        np.testing.assert_array_equal(ids,np.zeros(4,dtype=int))
        np.testing.assert_array_equal(selected,np.zeros((4,2)))
        _,ordinary=scope_grid.sample(points,np.ones(4),np.ones(4))
        np.testing.assert_array_equal(ordinary,np.arange(4))

    def test_linear_density_uses_grid_mass_and_retains_it_in_prepared_source(self):
        rgba=np.array([[[.2,.2,.2,1.],[.2,.2,.2,.5]]])
        grid=dict(mass=np.array([[.25,1.75]]),x=np.array([[.25,.75]]),key=('mass',))
        source=dict(key=('input',),rgba=rgba,chain=(),to_grade=np.eye(3),label='Input',
                    _scope_provenance=(),sample_grid=grid)
        s=dict(source=source,comparison=None,matrix=np.eye(3),scene_space='Linear Rec.709',
               space=linear.GradeSpace('D65'),key=('linear',),_scope_provenance=())
        result=scope_analysis.evaluate_linear(s)
        self.assertEqual(result['linear_vectorscope']['density'].sum(),1.125)
        self.assertIs(result['_source']['sample_grid'],grid)

    def test_malformed_population_cannot_enter_scope_analysis(self):
        s=snapshot();shape=s['rgba'].shape[:2]
        for mass,x in ((np.full(shape,-1.),np.zeros(shape)),
                       (np.full(shape,np.nan),np.zeros(shape)),
                       (np.ones(shape),np.full(shape,1.)),
                       (np.ones((1,1)),np.zeros(shape))):
            with self.subTest(mass=mass[0,0],x=x[0,0]):
                with self.assertRaises(ValueError):
                    scope_active.prepare(dict(s,sample_grid=dict(mass=mass,x=x,key=('bad',))),OrderedDict())


if __name__=='__main__':unittest.main()
