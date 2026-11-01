"""Fallback status and actions remain independent of scope publication."""
from tests.support.session import component as _component, SessionTest, patch
from dataclasses import asdict
import json
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from color_tools.blender_runtime.execution.contracts import ExecutionDiagnostic
from color_tools.perceptual_grade_blender.integration.components import Component
gpu = _component('graph.gpu'); scheduler = _component('graph.scheduler')
jobs = _component('scopes.jobs')
color = _component('ui.color'); diagram = _component('ui.diagram')


class GPUStatusTests(SessionTest):
    def setUp(self):
        source_status=patch.dict(self.session.components,{'scopes.sampling':Component({'scope_input_status':lambda *_a,**_k:dict(native=False)})})
        source_status.start();self.addCleanup(source_status.stop)
        self.rect = (10., 20., 200., 160.)
        self.diagnostic = ExecutionDiagnostic('lut_bake', 'Compiler failure', 'complete traceback',
            'compiler output tail', 'METAL', 'Test GPU', 'fingerprint', 'session', 12, 3, 123,
            '/tmp/helper.log', '/tmp/diagnostic.json')
        self.fallback = dict(state='fallback', reason='Compiler failure', diagnostic=self.diagnostic)

    def test_fallback_is_visible_even_when_scope_is_current(self):
        with patch.object(jobs, 'status', return_value=dict(state='current')), \
             patch.object(gpu, 'status', return_value=self.fallback), \
             patch.object(diagram, 'rectangle'), patch.object(diagram, 'text') as text:
            color.draw_scope_status(object(), self.rect, 1.)
        self.assertEqual([call.args[0] for call in text.call_args_list],
                         ['gpu.status.fallback', 'gpu.details', 'gpu.retry'])

    def test_probing_hides_retry_but_keeps_failure_details(self):
        with patch.object(jobs, 'status', return_value=dict(state='current')), \
             patch.object(gpu, 'status', return_value=dict(self.fallback, state='probing')), \
             patch.object(diagram, 'rectangle'), patch.object(diagram, 'text') as text:
            color.draw_scope_status(object(), self.rect, 1.)
        self.assertEqual([call.args[0] for call in text.call_args_list],
                         ['gpu.status.probing', 'gpu.details'])

    def test_gpu_hit_actions_are_separate_from_scope_retry(self):
        buttons = color.gpu_status_rects(self.rect, 1.)
        with patch.object(diagram, 'scope_status_target', return_value=(self.rect, 'linear')), \
             patch.object(jobs, 'status', return_value=dict(state='error')), \
             patch.object(gpu, 'status', return_value=self.fallback):
            for action, (x, y, w, h) in buttons.items():
                self.assertEqual(diagram.scope_retry_hit(None, None, {'scale': 1.}, (x+w/2, y+h/2)), action)
            x, y, w, h = color.scope_retry_rect(self.rect, 1.)
            self.assertEqual(diagram.scope_retry_hit(None, None, {'scale': 1.}, (x+w/2, y+h/2)), 'linear')
        x, y, w, h = buttons['gpu_retry']
        with patch.object(diagram, 'scope_status_target', return_value=(self.rect, 'linear')), \
             patch.object(jobs, 'status', return_value=dict(state='current')), \
             patch.object(gpu, 'status', return_value=dict(self.fallback, state='probing')):
            self.assertIsNone(diagram.scope_retry_hit(None, None, {'scale': 1.}, (x+w/2, y+h/2)))

    def test_details_copies_complete_structured_record_without_starting_work(self):
        manager = SimpleNamespace(clipboard='', popup_menu=Mock())
        with patch.object(gpu, 'status', return_value=self.fallback), patch.object(gpu, 'retry') as retry:
            color.gpu_action(SimpleNamespace(window_manager=manager), 'gpu_details')
        self.assertEqual(json.loads(manager.clipboard), asdict(self.diagnostic))
        retry.assert_not_called()
        manager.popup_menu.assert_called_once()
        draw = manager.popup_menu.call_args.args[0]
        popup = SimpleNamespace(layout=SimpleNamespace(label=Mock()))
        draw(popup, None)
        displayed = [call.kwargs['text'] for call in popup.layout.label.call_args_list]
        self.assertTrue(any('clipboard' in line for line in displayed))
        self.assertIn('Compiler failure', displayed)

    def test_gpu_retry_action_only_requests_conformance(self):
        with patch.object(gpu, 'retry') as retry, patch.object(jobs, 'retry') as scope_retry:
            color.gpu_action(None, 'gpu_retry')
        retry.assert_called_once_with(role='gpu')
        scope_retry.assert_not_called()

    def test_scope_gpu_retry_action_targets_scope_helper(self):
        with patch.object(gpu,'retry') as retry:
            color.gpu_action(None,'gpu_retry',role='scope_gpu')
        retry.assert_called_once_with(role='scope_gpu')

    def test_status_timer_defers_all_callbacks_during_native_recovery(self):
        runtime = SimpleNamespace(closed=False, fenced=False, poll=Mock(), jobs={1: object()},
                                  gpu_status=Mock(return_value=self.fallback))
        with patch.object(gpu, 'current_runtime', return_value=runtime), \
             patch.object(scheduler, 'lifecycle_admits', return_value=False):
            self.assertEqual(gpu._status_tick(), .05)
        runtime.poll.assert_not_called()
        runtime.gpu_status.assert_not_called()


class GPURoleStatusTests(SessionTest):
    def test_status_and_details_query_the_requested_role(self):
        diagnostic=ExecutionDiagnostic('scope_update','Scope shader failure','trace','compiler',
            'METAL','GPU','fingerprint','session',8,2,123,'/tmp/helper.log',
            '/tmp/diagnostic.json',role='scope_gpu')
        expected=dict(state='fallback',reason='Scope shader failure',diagnostic=diagnostic)
        runtime=SimpleNamespace(closed=False,gpu_status=Mock(return_value=expected))
        with patch.object(gpu,'current_runtime',return_value=runtime):
            self.assertEqual(gpu.status(role='scope_gpu'),expected)
            self.assertEqual(json.loads(gpu.details(role='scope_gpu')),asdict(diagnostic))
        self.assertEqual(runtime.gpu_status.call_args_list,
            [unittest.mock.call(role='scope_gpu'),unittest.mock.call(role='scope_gpu')])

    def test_scope_retry_does_not_probe_the_lut_role(self):
        handle=object();runtime=SimpleNamespace(retry_gpu=Mock(return_value=handle))
        with patch.object(gpu,'get_runtime',return_value=runtime),patch.object(gpu,'_watch') as watch:
            self.assertIs(gpu.retry(role='scope_gpu'),handle)
        runtime.retry_gpu.assert_called_once_with(role='scope_gpu')
        watch.assert_called_once_with()

    def test_scope_health_transition_redraws_with_unchanged_lut_health(self):
        ready=dict(state='ready',reason='',diagnostic=None)
        failed=dict(state='fallback',reason='scope failure',diagnostic=None)
        states={'gpu':ready,'scope_gpu':ready}
        runtime=SimpleNamespace(closed=False,fenced=False,jobs={},poll=Mock(),
            gpu_status=Mock(side_effect=lambda role:states[role]))
        with patch.object(gpu,'current_runtime',return_value=runtime), \
             patch.object(gpu,'_last_status',None), \
             patch.object(scheduler,'lifecycle_admits',return_value=True), \
             patch('color_tools.perceptual_grade_blender.graph.lut.redraw') as redraw:
            self.assertIsNone(gpu._status_tick())
            self.assertEqual(redraw.call_count,1)
            gpu._status_tick()
            self.assertEqual(redraw.call_count,1)
            states['scope_gpu']=failed
            gpu._status_tick()
            self.assertEqual(redraw.call_count,2)
        self.assertEqual({call.kwargs['role'] for call in runtime.gpu_status.call_args_list},
                         {'gpu','scope_gpu'})

    def test_unknown_gpu_role_is_rejected_without_runtime(self):
        with patch.object(gpu,'current_runtime',return_value=None):
            with self.assertRaises(ValueError):gpu.status(role='unrecognized')


class ScopeInputStatusTests(SessionTest):
    def test_source_only_description_continues_while_native_output_is_busy(self):
        source=Mock(return_value={'_scope_channel':17})
        sampling=Component({'channel':lambda *_a,**_k:17,'describe':source,
                            'scope_input_status':lambda *_a,**_k:dict(native=False)})
        describe=dict(zip(jobs.request.__code__.co_freevars,
                          (cell.cell_contents for cell in jobs.request.__closure__)))['_describe']
        guard=_component('graph.output_guard')
        with patch.dict(self.session.components,{'scopes.sampling':sampling}), \
             patch.object(scheduler,'scope_result',return_value=None), \
             patch.object(guard,'reason',return_value='Output installation is waiting for Blender job SHADER_COMPILATION') as reason:
            self.assertEqual(describe(None,None)['_scope_channel'],17)
            source.assert_called_once()
            reason.assert_not_called()

    def test_native_waiting_description_does_not_leave_error_after_capture_adoption(self):
        source=dict(native=True,state='waiting',error='')
        def waiting(*_args,**_kwargs):raise ValueError('Automatic scope input is being prepared')
        sampling=Component({'channel':lambda *_a,**_k:17,'describe':waiting,
                            'scope_input_status':lambda *_a,**_k:source})
        describe=dict(zip(jobs.request.__code__.co_freevars,
                          (cell.cell_contents for cell in jobs.request.__closure__)))['_describe']
        with patch.dict(self.session.components,{'scopes.sampling':sampling}), \
             patch.object(scheduler,'scope_result',return_value=None):
            for phase in ('waiting','capturing','updating','paused'):
                source['state']=phase
                with self.assertRaises(ValueError):describe(None,None)
            source['state']='captured'
            self.assertEqual(jobs.status(None)['state'],'preparing')

    def test_automatic_status_is_passive_and_has_no_refresh_action(self):
        rect=(10.,20.,200.,160.)
        source=dict(native=True,pending=False,state='updating',error='')
        observe=Mock();acquire=Mock()
        guard=_component('graph.output_guard')
        self.assertFalse(hasattr(diagram,'scope_refresh_hit'))
        self.assertFalse(hasattr(_component('ui.geometry'),'scope_refresh_rect'))
        with patch.dict(self.session.components,{'scopes.sampling':Component({'scope_input_status':lambda *_a,**_k:source}),
                'scopes.automatic':Component({'observe':observe}),'scopes.capture':Component({'acquire':acquire})}), \
             patch.object(jobs,'status') as status, \
             patch.object(gpu,'status',return_value=dict(state='ready')), \
             patch.object(guard,'available',return_value=True), \
             patch.object(diagram,'rectangle') as rectangle,patch.object(diagram,'text') as text:
            for phase,label in (('updating','scope.status.updating'),('paused','scope.status.paused'),
                                ('capturing','scope.status.updating')):
                status.return_value=dict(state=phase,error='')
                text.reset_mock();rectangle.reset_mock()
                color.draw_scope_status(None,rect,1.)
                self.assertIn(label,[call.args[0] for call in text.call_args_list])
                self.assertNotIn('scope.refresh.label',[call.args[0] for call in text.call_args_list])
                rectangle.assert_not_called()
            observe.assert_not_called();acquire.assert_not_called()

    def test_native_evaluation_wait_is_visible_without_authorizing_work(self):
        guard=_component('graph.output_guard')
        with patch.dict(self.session.components,{'scopes.sampling':Component({'scope_input_status':lambda *_a,**_k:dict(native=True)})}), \
             patch.object(jobs,'status',return_value=dict(state='updating',error='')), \
             patch.object(guard,'available',return_value=False), \
             patch.object(gpu,'status',return_value=dict(state='ready')), \
             patch.object(diagram,'rectangle'),patch.object(diagram,'text') as text:
            color.draw_scope_status(None,(10.,20.,200.,160.),1.)
            self.assertIn('scope.status.waiting_native',[call.args[0] for call in text.call_args_list])

    def test_retained_animation_frame_is_identified_while_new_frame_is_pending(self):
        with patch.dict(self.session.components,{'scopes.sampling':Component({'scope_input_status':lambda *_a,**_k:dict(native=False)})}), \
             patch.object(jobs,'status',return_value=dict(state='updating',error='',frames=(12,12))), \
             patch.object(gpu,'status',return_value=dict(state='ready')), \
             patch.object(diagram,'rectangle'),patch.object(diagram,'text') as text:
            color.draw_scope_status(None,(10.,20.,200.,160.),1.)
            self.assertIn('Previous frame 12',str(text.call_args_list[0].args[0]))

