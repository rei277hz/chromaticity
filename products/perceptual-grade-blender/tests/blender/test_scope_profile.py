"""Profile reports preserve phased visual/statistics and byte accounting."""
from tests.support.session import component as _component, SessionTest, patch
from importlib.machinery import SourceFileLoader
from importlib.resources import files
from importlib.util import module_from_spec,spec_from_loader
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

import numpy as np
from color_tools.perceptual_grade_core.jobs import codec
jobs = _component('scopes.jobs')


loader=SourceFileLoader('_pg_scope_profile_test',str(files('tests.blender')/'scope_profile.py'))
profile=module_from_spec(spec_from_loader(loader.name,loader));loader.exec_module(profile)


class ScopeProfileTests(SessionTest):
    def test_continuous_summary_counts_old_results_before_release_and_keeps_gaps(self):
        events=[dict(event='publication',at=.1,part='visual',age_seconds=.09),
            dict(event='publication',at=.2,part='stats',age_seconds=.19),
            dict(event='submit',at=.205,retirement_gap_seconds=.005),
            dict(event='draw',at=.21,part='stats'),
            dict(event='publication',at=.3,part='visual',age_seconds=.08),
            dict(event='publication',at=.4,part='stats',age_seconds=.18),
            dict(event='draw',at=.41,part='stats'),
            dict(event='cancel',at=.51),dict(event='publication',at=.7,part='stats',age_seconds=.1),
            dict(event='input',at=.01,arrays=0,bytes=0),dict(event='output',at=.2,arrays=4,bytes=96)]
        result=profile.continuous_summary(events,.5)
        self.assertTrue(result['updates_before_release'])
        self.assertEqual(result['p95']['publications'],2)
        self.assertAlmostEqual(result['p95']['publication_gap']['median_ms'],200.)
        self.assertAlmostEqual(result['p95']['draw_gap']['median_ms'],200.)
        self.assertEqual(result['completion_to_next_dispatch']['count'],1)
        self.assertEqual(result['cancellations_during_drag'],0)
        self.assertEqual(result['cancellations_after_release'],1)
        self.assertEqual(result['transfers']['output'],dict(arrays=4,bytes=96))

    def test_continuous_wire_accounting_counts_descriptors_without_loading_arrays(self):
        wire={'$dict':[['visual',{'$array':'cloud.npy','bytes':64}],
                       ['stats',{'$tuple':[{'$array':'center.npy','bytes':16}]}]]}
        self.assertEqual(profile.wire_arrays(wire),dict(arrays=2,bytes=80))

    def test_component_continuity_counts_losses_after_availability_not_initial_wait(self):
        states=[(False,False,False),(True,False,False),(True,True,False),
                (True,True,True),(False,True,True),(True,False,False),(True,True,False)]
        events=[dict(event='display',at=index/10,cloud_available=cloud,
                     statistics_available=stats,retained_statistics=retained)
                for index,(cloud,stats,retained) in enumerate(states)]
        summary=profile.continuous_summary(events,1.)['display_continuity']
        self.assertEqual(summary,dict(observations=7,missing_cloud_after_first=1,
            missing_statistics_after_first=1,retained_statistics_observations=2))
        visual=self.visual();selected=visual['_active_colors']['1:warp']
        selected.update(neutral=dict(count=8),_visual_request='new',_statistics_request='old',
                        _display_current=False,statistics_status='pending')
        components=profile.display_components(visual)
        self.assertTrue(components['cloud_available'])
        self.assertTrue(components['statistics_available'])
        self.assertTrue(components['retained_statistics'])
        self.assertEqual(components['visual_request'],'new')
        self.assertEqual(components['statistics_request'],'old')
        self.assertFalse(profile.display_components(None)['cloud_available'])

    def visual(self):
        pixels=np.zeros((1,1,8,8),np.uint8)
        record=dict(pixels=pixels,backend='gpu',view={})
        return dict(_scope_request='request',_scope_part='visual',_warp_clouds=(record,),
            _active_colors={'1:warp':dict(_warp_clouds=(record,),neutral=None,statistics_status='pending')})

    def statistics(self,request='request'):
        return dict(_scope_request=request,_scope_part='stats',_scope_stats_status='ready',
            _active_statistics={'1':dict(neutral=dict(count=8,location=np.ones(2),scatter=np.eye(2)),
                                         statistics_status='ready')})

    def test_phased_protocol_merges_only_matching_statistics_without_raster_retransmission(self):
        visual=self.visual();delta=self.statistics()
        result,metadata=profile.phased_result(codec,jobs,codec.freeze_scope_result(delta),
            codec.freeze_scope_result(visual))
        self.assertEqual(result['_scope_part'],'stats')
        self.assertEqual(profile.neutral_samples(result),[8])
        self.assertEqual(metadata['visual_output']['bytes'],64)
        self.assertEqual(metadata['terminal_output']['bytes'],48)
        self.assertEqual(metadata['output']['bytes'],112)
        profile.assert_texture_only(result)
        with self.assertRaisesRegex(AssertionError,'did not match'):
            profile.phased_result(codec,jobs,codec.freeze_scope_result(self.statistics('obsolete')),
                codec.freeze_scope_result(visual))
        with self.assertRaisesRegex(AssertionError,'without their retained visual'):
            profile.phased_result(codec,jobs,codec.freeze_scope_result(delta))

    def test_statistics_delta_cannot_repeat_cloud_data(self):
        visual=self.visual();delta=dict(self.statistics(),_warp_clouds=visual['_warp_clouds'])
        with self.assertRaisesRegex(AssertionError,'retransmitted'):
            profile.phased_result(codec,jobs,codec.freeze_scope_result(delta),codec.freeze_scope_result(visual))

    def test_early_decoded_preview_is_reused_for_terminal_merge(self):
        visual=self.visual();preview=codec.freeze_scope_result(visual)
        decoded=codec.thaw_scope_result(preview)
        result,metadata=profile.phased_result(codec,jobs,codec.freeze_scope_result(self.statistics()),
                                             preview,decoded_preview=decoded)
        self.assertIs(result['_warp_clouds'][0]['pixels'],decoded['_warp_clouds'][0]['pixels'])
        self.assertEqual(metadata['preview_decode_seconds'],0.)

    def test_texture_boundary_rejects_points_and_identifies_cpu_fallback(self):
        visual=self.visual()
        with self.assertRaisesRegex(AssertionError,'leaked point data'):
            profile.assert_texture_only(dict(visual,nested={'weights':np.ones(100)}))
        cpu=dict(visual,_warp_clouds=(dict(visual['_warp_clouds'][0],backend='cpu'),))
        with self.assertRaisesRegex(AssertionError,'CPU fallback'):
            profile.assert_texture_only(cpu)
        profile.assert_texture_only(cpu,require_gpu=False)

    def test_compare_separates_visual_final_and_array_free_update_metrics(self):
        empty=dict(count=0,bytes=0,arrays=[])
        texture=dict(count=1,bytes=64,arrays=[])
        fitted=dict(count=2,bytes=48,arrays=[])
        report=dict(passed=True,direct=[dict(kind='cold',seconds=.2,functions={},output=texture)],
            remote=[dict(kind=kind,total_seconds=.1,jobs=[dict(decode_seconds=.001)])
                for kind in ('cold','warm','queued')],committed_edits=[dict(warmup=True)],
            input_payload=texture,seed_payload=texture,update_payload=empty,
            limitations=[],scope_protocol='active-phased',membership_schema=1)
        for index in range(1,101):
            report['direct'].append(dict(kind='warm',seconds=index/1000,visual_seconds=index/2000,
                functions={},output=texture,visual_output=texture,terminal_output=fitted))
            report['committed_edits'].append(dict(seconds=.2+index/1000,
                visual_seconds=index/1000,p95_publication_seconds=.1+index/1000,
                first_warp_draw_seconds=.01+index/1000,cloud=dict(backends=['gpu'])))
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);folders=[root/'baseline',root/'optimized']
            for folder in folders:
                folder.mkdir();profile.save(folder/'report.json',report)
                profile.save(folder/'source_hashes.json',{})
                profile.save(folder/'launch.json',dict(runner_sha256='runner',buck_command=[]))
            output=root/'comparison.json'
            self.assertEqual(profile.compare(SimpleNamespace(compare=folders,output=output)),0)
            comparison=json.loads(output.read_text())
        optimized=comparison['optimized']
        self.assertEqual(optimized['warm_update_input']['count'],0)
        self.assertEqual(optimized['terminal_output']['bytes'],48)
        self.assertAlmostEqual(optimized['committed_visual']['p95_ms'],95.)
        self.assertAlmostEqual(optimized['p95_publication']['p95_ms'],195.)
        self.assertTrue(comparison['performance_acceptance_sample_count_met'])
