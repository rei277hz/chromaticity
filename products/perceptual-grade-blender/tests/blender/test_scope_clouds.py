"""The optional Warp raster path captures only visible, value-only pad views."""
from tests.support.session import component as _component, SessionTest, patch
from unittest.mock import Mock
import bpy
nodes = _component('graph.nodes')
clouds = _component('scopes.clouds'); sampling = _component('scopes.sampling'); jobs = _component('scopes.jobs')
diagram = _component('ui.diagram'); warp = _component('ui.warp'); warp_view = _component('ui.warp_view'); warp_samples = _component('ui.warp_samples')
from tests.support.blender import BlenderTest


class ScopeCloudTests(BlenderTest):
    def setUp(self):
        super().setUp()
        clouds.clear()

    def tearDown(self):
        clouds.clear()
        super().tearDown()

    def node(self):
        tree=bpy.data.node_groups.new('Cloud views','CompositorNodeTree')
        node=nodes.create_grade(tree)
        node.pg_chromatic.family='WARP'
        return node

    def test_descriptor_tracks_native_resize_scale_and_subpixel_origin(self):
        bounds=((-1,-1,1,1),)*4
        first=clouds.descriptor((16.25,20.75,409,409),1.,bounds)
        self.assertEqual((first['width'],first['height']),(410,410))
        self.assertEqual(first['rect'],(.25,.75,409.,409.))
        moved=clouds.descriptor((116.25,120.75,409,409),1.,bounds)
        self.assertEqual(first['key'],moved['key'])
        resized=clouds.descriptor((16.25,20.75,410,410),1.,bounds)
        scaled=clouds.descriptor((16.25,20.75,409,409),2.,bounds)
        fractional=clouds.descriptor((16.5,20.75,409,409),1.,bounds)
        self.assertNotEqual(first['key'],resized['key'])
        self.assertNotEqual(first['key'],scaled['key'])
        self.assertNotEqual(first['key'],fractional['key'])
        self.assertEqual(scaled['scale'],2.)
        selected=clouds.descriptor((16.25,20.75,409,409),1.,bounds,tone=2)
        self.assertEqual(selected['tone'],2)
        self.assertNotEqual(selected['key'],first['key'])
        self.assertNotEqual(selected['key'],clouds.descriptor((16.25,20.75,409,409),1.,bounds,tone=1)['key'])
        with self.assertRaises(ValueError):clouds.descriptor((0,0,10,10),1.,bounds,tone=4)

    def test_capture_uses_only_active_tones_gesture_lock_for_active_bound(self):
        node=self.node();node.pg_chromatic.active_tone=2
        model=object();box=dict(ab=(16.25,20.75,409,409),scale=1.5,_warp_editor=(1,2,3))
        token=warp_view.begin(box['_warp_editor'],node,2,9.)
        with (patch.object(nodes,'color_model',side_effect=AssertionError('Locked view built a model')),
              patch.object(warp_view,'radius',wraps=warp_view.radius) as locked,
              patch.object(warp,'view_radius',side_effect=AssertionError('Locked view fitted contours'))):
            view=clouds.capture_view(node,box)
        locked.assert_called_once_with(box['_warp_editor'],node,2)
        self.assertEqual(view['bounds'],((-9.,-9.,9.,9.),)*4)
        self.assertEqual(view['tone'],2)
        self.assertNotIn(node,view.values())
        self.assertIs(warp_view._locks[box['_warp_editor']],token)
        self.assertEqual(warp_view.radius(box['_warp_editor'],node,2),9.)
        warp_view.end(token)
        with patch.object(nodes,'color_model',return_value=model), \
             patch.object(warp,'view_radius',return_value=6.) as fitted:
            settled=clouds.capture_view(node,box)
        fitted.assert_called_once_with(model,2)
        self.assertEqual(settled['bounds'],((-6.,-6.,6.,6.),)*4)
        self.assertNotEqual(view['key'],settled['key'])

    def test_same_geometry_keeps_distinct_tone_views_and_filters_active_raster(self):
        from color_tools.perceptual_grade_blender.model import scope_active
        bounds=((-1.,-1.,1.,1.),)*4
        first=clouds.descriptor((0,0,100,100),1.,bounds,tone=1)
        second=clouds.descriptor((0,0,100,100),1.,bounds,tone=2)
        node=self.node()
        clouds.replace_views({node.as_pointer():(first,second,dict(first))})
        captured=clouds.views(node)
        self.assertEqual(len(captured),2)
        self.assertEqual(tuple(scope_active._views({'_warp_views':captured},1)),(first,))
        self.assertEqual(tuple(scope_active._views({'_warp_views':captured},2)),(second,))
        self.assertEqual(tuple(scope_active._views({'_warp_views':captured},0)),())

    def test_view_cache_keeps_distinct_editor_views_and_deduplicates_equal_rasters(self):
        node=self.node();other=self.node();bounds=((-1,-1,1,1),)*4
        shared=clouds.descriptor((16.25,20.75,409,409),1.,bounds)
        duplicate=dict(shared)
        second=clouds.descriptor((16.5,20.75,409,409),1.,bounds)
        clouds.replace_views({node.as_pointer():(shared,duplicate,second),
                              other.as_pointer():(second,)})
        views=clouds.views(node)
        self.assertEqual(len(views),2)
        self.assertEqual([item['key'] for item in views],sorted((shared['key'],second['key'])))
        self.assertEqual(clouds.views(other),(second,))
        clouds.clear()
        self.assertEqual(clouds.views(node),())
        self.assertEqual(clouds.views(other),())

    def test_real_editor_scan_replaces_only_visible_warp_views_and_keeps_demands_shared(self):
        node=self.node();wm=bpy.context.window_manager
        wm.pg_diagram_enabled=True;wm.pg_stage='CHROMATIC'
        areas=list(bpy.context.screen.areas)[:2]
        self.assertEqual(len(areas),2)
        for area in areas:
            area.type='NODE_EDITOR';area.ui_type='CompositorNodeTree'
            area.spaces.active.pin=True;area.spaces.active.node_tree=node.id_data
        boxes={area.as_pointer():dict(ab=(16.25,20.75,409,409),scale=1.,
            _warp_editor=(bpy.context.window.as_pointer(),area.as_pointer(),index+1))
            for index,area in enumerate(areas)}
        with (patch.object(clouds,'_enabled',True),
              patch.object(diagram,'layout',side_effect=lambda context:boxes[context.area.as_pointer()])):
            self.assertEqual(set(diagram.scope_consumers()),{('full',node.as_pointer())})
            self.assertEqual(len(clouds.views(node)),1)
            boxes[areas[1].as_pointer()]['scale']=2.
            diagram.scope_consumers()
            self.assertEqual(len(clouds.views(node)),2)
            areas[1].type='VIEW_3D'
            self.assertEqual(set(diagram.scope_consumers()),{('full',node.as_pointer())})
            self.assertEqual(len(clouds.views(node)),1)
            node.pg_chromatic.family='J'
            self.assertEqual(diagram.scope_consumers()['full',node.as_pointer()][2],
                (node.pg_chromatic.active_tone,False))
            self.assertEqual(clouds.views(node),())
            node.pg_chromatic.family='WARP'
            diagram.scope_consumers();self.assertEqual(len(clouds.views(node)),1)
            wm.pg_stage='REMAP'
            self.assertEqual(diagram.scope_consumers()['full',node.as_pointer()][2],('tone',))
            self.assertEqual(clouds.views(node),())
            wm.pg_stage='CHROMATIC'
            diagram.scope_consumers();self.assertEqual(len(clouds.views(node)),1)
            wm.pg_diagram_enabled=False
            self.assertFalse(diagram.scope_consumers())
            self.assertEqual(clouds.views(node),())

    def test_native_view_changes_publication_identity_but_reuses_numerical_identity(self):
        node=self.node();space=nodes.grading_space(node)
        first=clouds.descriptor((16,20,409,409),1.,((-1,-1,1,1),)*4)
        resized=clouds.descriptor((16,20,510,510),1.,first['bounds'])
        specs=[]
        try:
            with patch.object(clouds,'_enabled',True):
                clouds.replace_views({node.as_pointer():(first,)})
                specs.append(sampling.describe(node,space,(2,True)))
                clouds.replace_views({node.as_pointer():(resized,)})
                specs.append(sampling.describe(node,space,(2,True)))
            self.assertNotEqual(specs[0]['key'],specs[1]['key'])
            self.assertEqual(specs[0]['_warp_analysis_key'],specs[1]['_warp_analysis_key'])
            self.assertEqual(specs[0]['_scope_evaluation'],specs[1]['_scope_evaluation'])
            self.assertEqual(specs[1]['_warp_views'],(resized,))
        finally:
            for spec in specs:sampling.release(spec)

    def test_recovery_scan_and_sampling_reset_clear_cached_views_and_textures(self):
        node=self.node();view=clouds.descriptor((0,0,100,100),1.,((-1,-1,1,1),)*4)
        clouds.replace_views({node.as_pointer():(view,)})
        with (patch.object(nodes,'recovery_pending',return_value=True),
              patch.object(nodes,'active_grade',side_effect=AssertionError('recovery scanned RNA'))):
            self.assertEqual(diagram.scope_consumers(),{})
            self.assertEqual(clouds.views(node),())
        clouds.replace_views({node.as_pointer():(view,)})
        warp_samples._textures['test']=warp_samples.Coverage(object(),object())
        sampling.clear()
        self.assertEqual(clouds.views(node),())
        self.assertFalse(warp_samples._textures)

    def test_experiment_switch_refreshes_worker_and_retains_view_and_texture_caches(self):
        node=self.node();view=clouds.descriptor((0,0,100,100),1.,((-1,-1,1,1),)*4)
        with patch.object(clouds,'_enabled',False),patch.object(jobs,'refresh_backend') as refresh:
            clouds.replace_views({node.as_pointer():(view,)})
            warp_samples._textures['test']=warp_samples.Coverage(object(),object())
            clouds.set_enabled(True)
            self.assertTrue(clouds.enabled())
            self.assertEqual(clouds.views(node),(view,))
            self.assertIn('test',warp_samples._textures)
            clouds.set_enabled(True)
            self.assertEqual(refresh.call_count,1)
            clouds.set_enabled(False)
            self.assertFalse(clouds.enabled())
            self.assertEqual(refresh.call_count,2)

    def test_decorate_captures_stage_three_demand_on_both_backends(self):
        node=self.node();view=clouds.descriptor((1,2,100,100),1.,((-1,-1,1,1),)*4)
        def spec(stage,selected):
            from color_tools.perceptual_grade_core.scopes.identity import ScopeIdentity
            key = ScopeIdentity(version=('scope',), reference_version=None, comparison=False,
                matrix=(), tone=None, request_params=None, stack_signature=None,
                generation=1, stage=stage)
            return dict(stage=stage,view=selected,key=key,_scope_evaluation=('eval',))
        cases=((True,2,(1,True)),(True,3,('tone',)))
        for enabled,stage,selected in cases:
            original=spec(stage,selected)
            with (self.subTest(enabled=enabled,stage=stage,view=selected),
                  patch.object(clouds,'_enabled',enabled),
                  patch.object(clouds,'views',side_effect=AssertionError('unneeded view lookup'))):
                self.assertIs(clouds.decorate(original,node),original)
                self.assertNotIn('_warp_views',original)
        original=spec(3,(1,True))
        with patch.object(clouds,'_enabled',True),patch.object(clouds,'views',return_value=(view,)):
            result=clouds.decorate(original,node)
        from color_tools.perceptual_grade_core.scopes.identity import ScopeIdentity
        self.assertIsInstance(result['_warp_analysis_key'], ScopeIdentity)
        self.assertIsNone(result['_warp_analysis_key'].presentation)
        self.assertEqual(result['_warp_views'],(view,))
        self.assertEqual(result['key'].presentation.schema, clouds.SCHEMA)
        self.assertEqual(result['key'].presentation.requested, ((1, True),))
        self.assertEqual(result['key'].presentation.views, (view['key'],))
        self.assertTrue(result['key'].presentation.enabled)
        self.assertEqual(result['_scope_evaluation'][-1],('active-scopes',clouds.SCHEMA))
        for enabled in (False,True):
            with patch.object(clouds,'_enabled',enabled):
                self.assertEqual(clouds.decorate(spec(3,(2,False)),node)['_scope_demands'],((2,False),))

    def test_scope_submit_routes_texture_requests_to_priority_gpu_lane_only(self):
        execution = _component('jobs')
        runtime=Mock()
        cases=(('scope_full',{},'scope_full','bulk',0),
               ('scope_full',{'_warp_views':()},'scope_warp','gpu',1),
               ('scope_linear',{'_warp_views':()},'scope_linear','linear',0))
        for operation,snapshot,wanted,lane,priority in cases:
            with self.subTest(operation=operation,texture='_warp_views' in snapshot):
                runtime.reset_mock()
                with patch.object(execution,'get_runtime',return_value=runtime):
                    result=jobs._submit(operation,snapshot)
                runtime.submit.assert_called_once()
                spec=runtime.submit.call_args.args[0]
                self.assertEqual(spec.operation,wanted)
                self.assertEqual(spec.lane,lane)
                self.assertEqual(spec.priority,priority)
                self.assertIsNone(spec.key)
                self.assertIs(result.handle,runtime.submit.return_value)

    def test_active_source_capture_is_array_free_when_warm_and_reuses_pixels(self):
        import numpy as np
        node=self.node();space=nodes.grading_space(node)
        initial=sampling.describe(node,space,(2,False))
        cold=sampling.capture(initial)
        nodes.write_chromatic(node,{'global_gain':.1})
        latest=sampling.describe(node,space,(2,False))
        self.assertEqual(sampling.cache_id(initial),sampling.cache_id(latest))
        with patch.object(sampling,'source_samples',side_effect=AssertionError('warm source scan')):
            warm=sampling.capture(latest,seed=cold)
        self.assertIs(warm['rgba'],cold['rgba'])
        request=jobs._update_snapshot(warm)
        def arrays(value):
            if isinstance(value,np.ndarray):return 1
            if isinstance(value,dict):return sum(arrays(v) for v in value.values())
            if isinstance(value,(tuple,list)):return sum(arrays(v) for v in value)
            return 0
        self.assertEqual(arrays(request),0)
        self.assertNotIn('rgba',request);self.assertNotIn('comparison',request)
        nodes.write_tone(node,{'input_midtones':45})
        tone=sampling.describe(node,space,(2,False))
        self.assertEqual(sampling.cache_id(initial),sampling.cache_id(tone))
        self.assertNotEqual(cold['base_key'],sampling.capture(tone,seed=cold)['base_key'])
        for spec in (initial,latest,tone):sampling.release(spec)

    def test_sparse_selection_never_shows_another_tone_and_stats_delta_is_exact(self):
        import numpy as np
        pixels=np.zeros((1,1,4,4),dtype=np.uint8)
        selected=dict(_active_tone=2,neutral=None,statistics_status='pending',_warp_clouds=(dict(pixels=pixels),))
        visual=dict(_scope_request='first',_active_colors={'2:warp':selected})
        self.assertIsNone(sampling.select_view(visual,(1,True)))
        self.assertIsNone(sampling.select_view({'_colors':({'weights':pixels},)*4},(2,True)))
        chosen=sampling.select_view(visual,(2,True))
        self.assertEqual(chosen['_color']['_active_tone'],2)
        self.assertIsNone(jobs._merge_statistics(visual,dict(_scope_request='stale')))
        stats=dict(neutral={'count':4},statistics_status='ready')
        final=jobs._merge_statistics(visual,dict(_scope_request='first',_active_statistics={'2':stats}))
        self.assertEqual(final['_active_colors']['2:warp']['neutral']['count'],4)
        self.assertIs(final['_active_colors']['2:warp']['_warp_clouds'][0]['pixels'],pixels)
        self.assertIsNone(visual['_active_colors']['2:warp']['neutral'])

    def test_preview_decodes_once_and_cancellation_waits_for_retirement(self):
        from color_tools.perceptual_grade_core.jobs.codec import freeze_scope_result
        handle=Mock();handle.preview=freeze_scope_result({'_scope_part':'visual'})
        handle.retired.return_value=False
        result=jobs.ScopeResult(handle)
        self.assertEqual(result.preview()['_scope_part'],'visual')
        self.assertIsNone(result.preview())
        result.cancel();handle.cancel.assert_called_once()
        self.assertFalse(result.retired())
        handle.retired.return_value=True;self.assertTrue(result.retired())

    def test_retirement_drain_adopts_preview_arriving_with_terminal_delta(self):
        from types import SimpleNamespace
        from color_tools.perceptual_grade_core.jobs.codec import freeze_scope_result
        handle=SimpleNamespace(preview=None)
        def retire():
            handle.preview=freeze_scope_result({'_scope_part':'visual'})
            return True
        handle.retired=retire
        result=jobs.ScopeResult(handle)
        preview,retired=jobs._drain_preview(result)
        self.assertTrue(retired)
        self.assertEqual(preview['_scope_part'],'visual')
        self.assertIsNone(result.preview())

    def test_active_requests_use_dedicated_gpu_or_texture_only_cpu_lane(self):
        execution = _component('jobs')
        runtime=Mock()
        for enabled,lane in ((False,'bulk'),(True,'scope_gpu')):
            for operation in ('scope_register','scope_update'):
                with patch.object(clouds,'_enabled',enabled),patch.object(execution,'get_runtime',return_value=runtime):
                    jobs._submit(operation,{'cache_id':'source'})
                spec=runtime.submit.call_args.args[0]
                self.assertEqual(spec.operation,operation);self.assertEqual(spec.lane,lane)
                self.assertEqual(spec.priority,1)

    def test_receipt_ticks_throttle_consumer_scan_but_ui_refresh_is_immediate(self):
        node=self.node();pointer=node.as_pointer();space=nodes.grading_space(node)
        consumers={('full',pointer):(node,space,(2,True))};now=[1.]
        with patch.object(jobs.time,'monotonic',side_effect=lambda:now[0]), \
             patch.object(jobs,'visible_consumers',side_effect=lambda:consumers) as scan:
            jobs._sync_consumers()
            self.assertIn(('full',pointer),jobs._consumers)
            consumers.clear()
            for _ in range(15):
                now[0]+=.001;jobs._sync_consumers(throttle=True)
            self.assertEqual(scan.call_count,1)
            self.assertIn(('full',pointer),jobs._consumers)
            now[0]+=.002;jobs._sync_consumers(throttle=True)
            self.assertNotIn(('full',pointer),jobs._consumers)
            consumers[('full',pointer)]=(node,space,(2,True))
            jobs.refresh_visible()
            self.assertIn(('full',pointer),jobs._consumers)
        jobs.clear()
        self.assertEqual(jobs._consumer_scan_due,0.)


if __name__=='__main__':
    import unittest
    unittest.main()
