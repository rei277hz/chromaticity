"""Native premises for the opt-in scope diagnostic, without helper work."""
from tests.support.session import component as _component, SessionTest, patch
from importlib.machinery import SourceFileLoader
from importlib.resources import files
from importlib.util import module_from_spec, spec_from_loader
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
pass

import bpy
import numpy as np
grades = _component('graph.grades'); scheduler = _component('graph.scheduler')
jobs = _component('scopes.jobs'); sampling = _component('scopes.sampling')
from color_tools.perceptual_grade_core.jobs import codec
from tests.support.blender import BlenderTest


class ScopeTraceTests(BlenderTest):
    def setUp(self):
        super().setUp()
        path = str(files('tests.blender') / 'pg_scope_trace.py')
        loader = SourceFileLoader('_pg_scope_trace_test', path)
        self.trace = module_from_spec(spec_from_loader(loader.name, loader))
        loader.exec_module(self.trace)
        self.previous_state = sys.modules.get(self.trace._STATE_MODULE)
        self.previous_profile = sys.getprofile()
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        home = patch.object(self.trace.Path, 'home', return_value=Path(directory.name))
        home.start()
        self.addCleanup(home.stop)

    def tearDown(self):
        try:
            self.trace.stop()
            if self.previous_state is None:
                sys.modules.pop(self.trace._STATE_MODULE, None)
            else:
                sys.modules[self.trace._STATE_MODULE] = self.previous_state
            sys.setprofile(self.previous_profile)
        finally:
            super().tearDown()

    def node(self, grade=False):
        tree = bpy.data.node_groups.new('Scope trace premise', 'CompositorNodeTree')
        return tree.nodes.new(grades.KINDS['CompositorNodeTree'] if grade else 'CompositorNodeGroup')

    def records(self, path):
        return [json.loads(line) for line in path.read_text().splitlines()]

    def test_install_rerun_stop_restores_all_hooks_without_changing_profiler(self):
        def prior_profile(frame, event, arg):
            pass
        sys.setprofile(prior_profile)
        first_path = self.trace.install()
        first = sys.modules[self.trace._STATE_MODULE].trace
        originals = [(path, name, original) for path, name, original, wrapper in first.hooks]
        self.assertEqual(len(originals), 18)
        for path, name, original, wrapper in first.hooks:
            self.assertIs(getattr(first.target(path), name), wrapper)
        second_path = self.trace.install()
        second = sys.modules[self.trace._STATE_MODULE].trace
        self.assertTrue(first.closed)
        self.assertIsNone(first.fd)
        self.assertNotEqual(first_path, second_path)
        for (path, name, original), (_, _, current, _) in zip(originals, second.hooks):
            self.assertIs(current, original)
        self.trace.stop()
        self.trace.stop()
        for path, name, original in originals:
            self.assertIs(getattr(second.target(path), name), original)
        self.assertIsNone(second.fd)
        self.assertIs(sys.getprofile(), prior_profile)

    def test_independent_component_metadata_excludes_arrays_and_records_missing_draw(self):
        warp_samples = _component('ui.warp_samples')
        pass
        selected=dict(_warp_clouds=(dict(pixels=np.ones((1,1,2,2))),),
            neutral=dict(center=np.ones(2)),statistics_status='pending',
            _visual_request='new',_statistics_request='old',_visual_epoch=7,_statistics_epoch=4,
            _visual_analysis=9,_statistics_analysis=3,_display_current=False,
            _warp_tone=1,_scope_key=('latest',),_scope_part='visual')
        values=self.trace._display_components(selected)
        self.assertTrue(values['cloud_available'])
        self.assertTrue(values['statistics_available'])
        self.assertTrue(values['retained_statistics'])
        self.assertTrue(all(type(value) in self.trace._SCALARS for value in values.values()))
        plot=_component('ui.color_geometry').ABPlot((0,0,32,32),-1,1,-1,1)
        with patch.object(warp_samples,'draw'):
            path=self.trace.install()
            warp_samples.draw(plot,selected,None,1.)
            warp_samples.draw(plot,selected,None,1.)
            warp_samples.draw(plot,None,None,1.)
            self.trace.stop()
        events=[item for item in self.records(path) if item['event']=='warp_components']
        self.assertEqual(len(events),2)
        self.assertEqual(events[0]['visual_request'],'new')
        self.assertEqual(events[0]['statistics_request'],'old')
        self.assertFalse(events[1]['cloud_available'])
        self.assertFalse(events[1]['statistics_available'])

    def test_native_gesture_and_scope_request_keep_semantics_and_scalar_receipts(self):
        node = self.node()
        path = self.trace.install()
        token = scheduler.begin(node)
        self.assertTrue(scheduler.dragging(node))
        spec = dict(key=('trace', 1), context=('trace-context', 1))
        ticket = scheduler.scope_request(node, 'linear', spec)
        repeated = scheduler.scope_request(node, 'linear', spec)
        self.assertEqual(ticket.key, repeated.key)
        self.assertNotEqual(ticket.token, repeated.token)
        self.assertFalse(scheduler.scope_publish(ticket))
        self.assertIsNone(scheduler.end(token))
        self.assertFalse(scheduler.dragging(node))
        records = self.records(path)
        events = [record['event'] for record in records]
        self.assertEqual(events.count('scope_request'), 1)
        self.assertIn('gesture_begin', events)
        self.assertIn('gesture_release', events)
        self.assertIn('gesture_release_returned', events)
        publication = next(record for record in records if record['event'] == 'scope_publish')
        self.assertFalse(publication['accepted'])
        self.assertTrue(all(type(value) in (str, int, float, bool, type(None))
                            for record in records for value in record.values()))
        state = sys.modules[self.trace._STATE_MODULE].trace
        self.assertTrue(all(type(value) in (str, int, float, bool, type(None))
                            for key, values in state.requests.items() for value in (*key, *values)))

    def test_diagnostic_extraction_failure_preserves_actual_capture_exception(self):
        path = self.trace.install()
        # Capture rejects the retired native reference independently of its
        # request key. An unsupported diagnostic key must not replace that error.
        with self.assertRaisesRegex(ReferenceError, 'Retired scope capture'):
            sampling.capture(dict(node=None, key=(object(),)))
        records = self.records(path)
        events = [record['event'] for record in records]
        self.assertIn('diagnostic_fields_unavailable', events)
        error = next(record for record in records if record['event'] == 'capture_error')
        self.assertEqual(error['error_type'], 'ReferenceError')
        self.assertEqual(error['error'], 'Retired scope capture')
        self.assertNotIn('capture_end', events)

    def test_trace_write_failure_does_not_interrupt_native_gesture(self):
        node = self.node()
        self.trace.install()
        state = sys.modules[self.trace._STATE_MODULE].trace
        with patch.object(self.trace, '_write_all', side_effect=OSError('Diagnostic disk failure')):
            token = scheduler.begin(node)
            self.assertTrue(scheduler.dragging(node))
            self.assertIsNone(scheduler.end(token))
        self.assertFalse(scheduler.dragging(node))
        self.assertTrue(state.write_failed)
        self.trace.stop()
        self.assertIsNone(state.fd)

    def test_actual_scope_key_survives_submission_and_result_codec(self):
        node = self.node(grade=True)
        kernel = bpy.data.node_groups.new('Scope trace inputs', 'CompositorNodeTree')
        for name in ('Color', 'Color Reference'):
            kernel.interface.new_socket(name=name, in_out='INPUT', socket_type='NodeSocketColor')
        node.node_tree = kernel
        described = sampling.describe(node, 'Linear Rec.709')
        path = self.trace.install()
        scheduler.scope_request(node, 'full', described)
        runtime = SimpleNamespace(session=SimpleNamespace(identity='trace-codec-premise'))

        def submit(spec):
            captured = codec.thaw_scope_request(spec.inputs)
            base = dict(_scope_key=captured['key'])
            base['_color'] = dict(_base=base)
            payload = codec.freeze_scope_result(base)
            job = SimpleNamespace(order=1, state=SimpleNamespace(identity=7, generation=2),
                                  spec=spec, role=spec.lane, finished=True)
            return SimpleNamespace(runtime=runtime, _job=job, identity=9,
                                   result=lambda timeout=None: payload)

        runtime.submit = submit
        with patch('color_tools.perceptual_grade_blender.jobs.get_runtime', return_value=runtime):
            future = jobs._submit('scope_full', dict(key=described['key'], space=described['space']))
            result = future.result()
            self.assertIs(future.result(), result)
        records = self.records(path)
        keys = [record['scope_key'] for record in records
                if record['event'] in ('scope_request', 'scope_submit', 'scope_decode_end')]
        self.assertEqual(len(keys), 3)
        self.assertEqual(len(set(keys)), 1)
        self.assertEqual(self.trace._result_key(result['_color'])['scope_key'], keys[0])
        self.assertFalse(any(record['event'] == 'diagnostic_fields_unavailable' for record in records))
        self.assertEqual(sum(record['event'] == 'scope_decode_end' for record in records), 1)

    def test_texture_metadata_and_wire_payload_accounting_are_scalar_only(self):
        view=dict(key=('view',1),width=7,height=5,rect=(.25,.75,6.,4.),scale=1.5,
                  bounds=((-1.,-1.,1.,1.),)*4)
        pixels=np.zeros((2,4,5,7),dtype=np.uint8)
        result=dict(_scope_key=('scope',1),_warp_clouds=(dict(view=view,pixels=pixels,backend='gpu',
                    timings=dict(readback_seconds=.012,compute_submission_seconds=.003)),))
        values=self.trace._cloud_values(result)
        self.assertEqual(values['cloud_view_count'],1)
        self.assertEqual(values['cloud_tile_count'],8)
        self.assertEqual(values['cloud_pixel_bytes'],280)
        self.assertEqual(values['cloud_array_count'],1)
        self.assertEqual(values['cloud_backend'],'gpu')
        self.assertEqual(values['cloud_readback_seconds'],.012)
        self.assertTrue(all(type(value) in self.trace._SCALARS for value in values.values()))
        self.assertEqual(self.trace._cloud_values(dict(_base=result)),values)
        encoded={'$dict':[['cloud',{'$array':'array-example.npy','shape':[2,4,5,7],'dtype':'|u1','bytes':280}],
                          ['weights',{'$array':'array-other.npy','shape':[5],'dtype':'<f4','bytes':20}]]}
        self.assertEqual(self.trace._payload_values(encoded,'output_payload'),
                         dict(output_payload_arrays=2,output_payload_bytes=300))

    def test_preview_decode_is_traced_once_and_distinct_from_statistics(self):
        path=self.trace.install()
        visual=dict(_scope_key=('preview',),_scope_part='visual',_scope_request='exact')
        statistics=dict(_scope_key=('preview',),_scope_part='stats',_scope_request='exact')
        handle=SimpleNamespace(preview=codec.freeze_scope_result(visual),
            result=lambda timeout=None:codec.freeze_scope_result(statistics))
        future=jobs.ScopeResult(handle)
        self.assertEqual(future.preview()['_scope_part'],'visual')
        self.assertIsNone(future.preview())
        self.assertEqual(future.result()['_scope_part'],'stats')
        records=self.records(path)
        previews=[r for r in records if r['event']=='scope_preview_decode_end']
        finals=[r for r in records if r['event']=='scope_decode_end']
        self.assertEqual(len(previews),1);self.assertEqual(len(finals),1)
        self.assertEqual(previews[0]['scope_part'],'visual')
        self.assertEqual(finals[0]['scope_part'],'stats')

    def test_report_keeps_visual_and_statistics_latencies_and_excludes_late_draws(self):
        path=str(files('tests.blender')/'scope_trace_report.py')
        loader=SourceFileLoader('_pg_scope_report_test',path)
        report=module_from_spec(spec_from_loader(loader.name,loader));loader.exec_module(report)
        ticket={name:1 for name in report.TICKET_FIELDS}
        ticket.update(node_pointer=7,channel='full',scope_key='exact')
        def event(sequence,name,**fields):
            return dict(ticket,sequence=sequence,event=name,monotonic_ns=sequence*1000000,**fields)
        events=[event(1,'gesture_begin',gesture=1),event(2,'scope_request'),
            event(3,'gesture_release',gesture=1),
            event(4,'scope_publish',accepted=True,scope_part='visual'),
            event(5,'warp_draw',scope_part='visual'),
            event(6,'scope_publish',accepted=True,scope_part='stats'),
            event(7,'warp_draw',scope_part='stats'),event(8,'gesture_begin',gesture=2)]
        gesture=report.gesture_report(events)[0]
        self.assertEqual(gesture['release_to_visual_publication']['duration_ms'],1)
        self.assertEqual(gesture['release_to_visual_draw']['duration_ms'],2)
        self.assertEqual(gesture['release_to_p95_publication']['duration_ms'],3)
        self.assertEqual(gesture['release_to_p95_draw']['duration_ms'],4)
        late=events[:5]+[events[-1],event(9,'scope_publish',accepted=True,scope_part='stats'),
            event(10,'warp_draw',scope_part='stats')]
        gesture=report.gesture_report(late)[0]
        self.assertNotIn('release_to_p95_publication',gesture)
        self.assertNotIn('release_to_p95_draw',gesture)

        job=dict(job_order=11,attempt=1,generation=1,session='helper',operation='scope_update')
        records=[event(1,'scope_request'),event(2,'capture_end'),
            event(3,'scope_submit',**job),event(4,'run_send',**job),
            event(5,'job_message_begin',call=1,message_kind='preview',
                  output_payload_arrays=1,output_payload_bytes=1024,**job),
            event(6,'job_message_end',call=1,message_kind='preview',**job),
            event(7,'scope_preview_decode_begin',**job),
            event(8,'scope_preview_decode_end',scope_part='visual',cloud_backend='gpu',**job),
            event(9,'scope_publish',accepted=True,scope_part='visual'),
            event(10,'job_message_begin',call=2,message_kind='complete',
                  output_payload_arrays=4,output_payload_bytes=96,**job),
            event(11,'job_message_end',call=2,message_kind='complete',**job),
            event(12,'scope_decode_begin',**job),event(13,'scope_decode_end',scope_part='stats',**job),
            event(14,'scope_publish',accepted=True,scope_part='stats')]
        result=report.job_report(records)[0]
        self.assertEqual(result['visual_payload_bytes'],1024)
        self.assertEqual(result['output_payload_bytes'],96)
        self.assertEqual(result['cloud']['backend'],'gpu')
        self.assertEqual(result['submission_to_visual_publication']['duration_ms'],6)
        self.assertEqual(result['handling_to_publication']['duration_ms'],3)

    def test_report_counts_lagging_drag_publications_before_release(self):
        path=str(files('tests.blender')/'scope_trace_report.py')
        loader=SourceFileLoader('_pg_scope_cadence_test',path)
        report=module_from_spec(spec_from_loader(loader.name,loader));loader.exec_module(report)
        ticket={name:1 for name in report.TICKET_FIELDS}
        ticket.update(node_pointer=7,channel='full',scope_key='first')
        def event(sequence,name,**fields):
            return dict(ticket,sequence=sequence,event=name,monotonic_ns=sequence*1000000,**fields)
        events=[event(1,'gesture_begin',gesture=1),event(2,'scope_request'),
            event(3,'scope_request',key=2,epoch=2,scope_key='newer'),
            event(4,'scope_publish',accepted=True,scope_part='visual'),
            event(5,'scope_publish',accepted=True,scope_part='stats'),
            event(6,'warp_draw',scope_part='stats'),
            event(7,'scope_publish',accepted=False,scope_part='stats'),
            event(8,'scope_publish',accepted=True,scope_part='visual',key=2,epoch=2,scope_key='newer'),
            event(9,'scope_publish',accepted=True,scope_part='stats',key=2,epoch=2,scope_key='newer'),
            event(10,'warp_draw',scope_part='stats',key=2,epoch=2,scope_key='newer'),
            event(11,'gesture_release',gesture=1)]
        cadence=report.gesture_report(events)[0]['during_drag']['channels']['full']
        self.assertEqual(cadence['visual']['publications'],2)
        self.assertEqual(cadence['p95']['publications'],2)
        self.assertEqual(cadence['p95']['draws'],2)
        self.assertEqual(cadence['p95']['publication_gap']['median_ms'],4.)
        self.assertEqual(cadence['p95']['result_age']['median_ms'],4.5)

    def test_first_texture_draw_records_conversion_upload_and_native_view(self):
        warp_samples = _component('ui.warp_samples')
        pass
        plot=_component('ui.color_geometry').ABPlot((.25,.75,6.,4.),-1.,1.,-1.,1.)
        view=dict(key=('view',1),width=7,height=5,rect=(.25,.75,6.,4.),scale=1.,
                  bounds=((-1.,-1.,1.,1.),)*4)
        pixels=np.full((1,4,5,7),128,dtype=np.uint8)
        result=dict(_scope_key=('scope',1),_warp_tone=2,
                    _warp_clouds=(dict(view=view,pixels=pixels,backend='gpu',timings={}),))
        def draw(plot, selected, external, scale):
            warp_samples.texture_layer(pixels,selected['_warp_tone'],0)
        warp_samples.clear()
        with patch.object(warp_samples,'draw',side_effect=draw), \
                patch.object(warp_samples,'upload_coverage',return_value=object()):
            path=self.trace.install()
            warp_samples.draw(plot,result,None,1.)
            warp_samples.draw(plot,result,None,1.)
            self.trace.stop()
        records=self.records(path)
        for name in ('cloud_coverage_conversion','cloud_texture_upload','warp_draw'):
            events=[record for record in records if record['event']==name]
            self.assertEqual(len(events),1,name)
            self.assertEqual(events[0]['cloud_backend'],'gpu')
            self.assertGreaterEqual(events[0]['duration_ms'],0.)
        draw=next(record for record in records if record['event']=='warp_draw')
        self.assertEqual(draw['view_rect_width'],6.)
        self.assertEqual(draw['view_rect_x'],.25)
        self.assertEqual(draw['tone'],2)
        self.assertTrue(all(type(value) in self.trace._SCALARS for record in records for value in record.values()))
        warp_samples.clear()
