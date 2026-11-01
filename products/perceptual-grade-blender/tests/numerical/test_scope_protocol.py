"""Seed recovery and phased scope publication across the real domain codec."""
from concurrent.futures import CancelledError
from types import SimpleNamespace
from unittest.mock import patch
import unittest
import numpy as np

from color_tools.perceptual_grade_core.jobs import codec
from color_tools.perceptual_grade_blender.jobs.handlers import scopes


class ScopeProtocolTests(unittest.TestCase):
    def setUp(self):
        scopes._sources.clear();scopes._active_bases.clear()
        self.addCleanup(scopes._sources.clear)
        self.addCleanup(scopes._active_bases.clear)
        self.previews=[]
        self.context=SimpleNamespace(role='bulk',generation=7,session='test-session',
            checkpoint=lambda:None,preview=lambda value:self.previews.append(codec.thaw_scope_result(value)))
        self.seed=dict(cache_id='source-id',rgba=np.ones((3,4,4),dtype=np.float32),
            base_key=('base',),key=('release',),_scope_provenance=(),
            _scope_evaluation=('analytic',),_scope_demands=((2,True),),_warp_views=())

    def call(self,method,value):
        return codec.thaw_scope_result(method(codec.freeze_scope_request(value),self.context))

    def test_missing_or_wrong_generation_seed_is_control_result(self):
        self.assertEqual(self.call(scopes.update,{'cache_id':'source-id'})['_scope_control'],'needs_seed')
        ready=self.call(scopes.register,self.seed)
        self.assertEqual((ready['_scope_control'],ready['backend'],ready['generation']),('ready','bulk',7))
        self.context.generation+=1
        self.assertEqual(self.call(scopes.update,{'cache_id':'source-id'})['_scope_control'],'needs_seed')
        self.context.generation=7;self.context.role='scope_gpu'
        self.assertEqual(self.call(scopes.update,{'cache_id':'source-id'})['_scope_control'],'needs_seed')

    def test_register_owns_seed_and_eviction_requires_reseed(self):
        self.call(scopes.register,self.seed)
        retained=scopes._sources['source-id'][0]['rgba']
        self.seed['rgba'][:]=0
        self.assertTrue(np.all(retained==1));self.assertFalse(retained.flags.writeable)
        with patch.object(scopes,'_SOURCE_LIMIT',1):
            self.call(scopes.register,dict(self.seed,cache_id='replacement'))
        self.assertEqual(self.call(scopes.update,{'cache_id':'source-id'})['_scope_control'],'needs_seed')

    def test_seed_bound_includes_owned_cube_samples(self):
        from color_tools.perceptual_grade_core.model.lut import Cube
        values=np.ones((33,33,33,3),np.float32)
        cube=Cube(values,'seed-cube',size=33)
        seed=dict(self.seed,chain=(cube,))
        self.assertEqual(scopes._source_bytes(seed),self.seed['rgba'].nbytes+values.nbytes)
        with patch.object(scopes,'_SOURCE_BYTES',values.nbytes):
            with self.assertRaisesRegex(ValueError,'bounded seed cache'):self.call(scopes.register,seed)
        self.call(scopes.register,seed)
        retained=scopes._sources['source-id'][0]['chain'][0]
        values[:]=0
        self.assertTrue(np.all(retained.values==1))
        self.assertFalse(retained.values.flags.writeable)

    def test_visual_precedes_statistics_and_final_does_not_retransmit_pixels(self):
        from color_tools.perceptual_grade_blender.model import scope_active
        self.call(scopes.register,self.seed)
        raster=np.zeros((1,1,32,32),np.uint8)
        visual={'_active_colors':{},'_warp_clouds':({'pixels':raster},)}
        def fit(*args,**kwargs):
            self.assertEqual(len(self.previews),1)
            return {'_active_statistics':{'2':{'count':12}}}
        with (patch.object(scope_active,'prepare',return_value=object()),
              patch.object(scope_active,'visual',return_value=visual),
              patch.object(scope_active,'statistics',side_effect=fit)):
            result=self.call(scopes.update,{'cache_id':'source-id','key':('new-release',)})
        self.assertEqual(result['_scope_part'],'stats')
        self.assertEqual(result['_scope_request'],self.previews[0]['_scope_request'])
        self.assertNotIn('_warp_clouds',result)
        self.assertEqual(self.previews[0]['_scope_key'],('new-release',))
        self.assertEqual(self.previews[0]['_warp_clouds'][0]['pixels'].nbytes,1024)

    def test_jc_finishes_without_preview_and_stats_failure_preserves_visual(self):
        from color_tools.perceptual_grade_blender.model import scope_active
        self.call(scopes.register,self.seed)
        with (patch.object(scope_active,'prepare',return_value=object()),
              patch.object(scope_active,'visual',return_value={'_active_colors':{}}),
              patch.object(scope_active,'statistics',side_effect=ValueError('singular fit')) as stats):
            result=self.call(scopes.update,{'cache_id':'source-id','_scope_demands':((2,False),)})
            self.assertEqual(result['_scope_part'],'visual');self.assertFalse(self.previews)
            stats.assert_not_called()
            result=self.call(scopes.update,{'cache_id':'source-id'})
            self.assertEqual(result['_scope_stats_status'],'unavailable')
            self.assertEqual(len(self.previews),1)

    def test_cancellation_after_visual_is_not_converted_to_stats_failure(self):
        from color_tools.perceptual_grade_blender.model import scope_active
        self.call(scopes.register,self.seed)
        with (patch.object(scope_active,'prepare',return_value=object()),
              patch.object(scope_active,'visual',return_value={'_active_colors':{}}),
              patch.object(scope_active,'statistics',side_effect=CancelledError)):
            with self.assertRaises(CancelledError):self.call(scopes.update,{'cache_id':'source-id'})
        self.assertEqual(len(self.previews),1)

    def test_request_identity_fences_views_controls_and_backend(self):
        first=scopes._request_identity(self.seed,self.context)
        for field,value in (('key',('changed',)),('_scope_demands',((1,True),)),
                            ('_warp_views',({'width':64},)),('_scope_evaluation',('new-schema',))):
            self.assertNotEqual(first,scopes._request_identity(dict(self.seed,**{field:value}),self.context))
        self.context.generation+=1
        self.assertNotEqual(first,scopes._request_identity(self.seed,self.context))
