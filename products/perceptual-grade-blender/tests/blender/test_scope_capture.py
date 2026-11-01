"""Foreground capture identity, automatic acquisition and native-input lease lifetime."""
import gc
import hashlib
import sys
import tempfile
import time
from pathlib import Path
from types import MappingProxyType, SimpleNamespace

import bpy
import numpy as np

from tests.support.blender import BlenderTest, sequence
from tests.support.session import component, patch
from color_tools.perceptual_grade_blender.integration.components import Component


class FakeHandle:
    def __init__(self, spec):
        self.spec = spec
        self._retired = False
        self.cancel_requested = False
        self.value = None
        self.error = None

    def retired(self):
        return self._retired

    def cancel(self):
        self.cancel_requested = True

    def finish(self, value=None, error=None):
        self.value = value
        self.error = error
        self._retired = True

    def result(self):
        if self.error is not None:
            raise self.error
        if self.value is not None:
            return self.value
        return dict(identity=self.spec.inputs['identity'],
                    prepared_provenance=tuple(sorted({(item['cube_signature'],65) for item in self.spec.inputs.get('_pg_models',())})),
                    rgba=np.full((2, 3, 4), .25, dtype=np.float32), label='fake native graph')


class FakeRuntime:
    def __init__(self, directory):
        self.session = SimpleNamespace(path=Path(directory))
        self.closed = self.fenced = False
        self.specs = []
        self.handles = []
        self.polls = 0
        self.helpers = {}

    def poll(self, **_kwargs):
        self.polls += 1

    def submit(self, spec):
        self.specs.append(spec)
        handle = FakeHandle(spec)
        self.handles.append(handle)
        return handle


class ScopeCaptureTests(BlenderTest):
    def setUp(self):
        super().setUp()
        self.capture = component('scopes.capture')
        self.contexts = component('scopes.context')
        self.scheduler = component('graph.scheduler')
        self.guard = component('graph.output_guard')
        self._temp = tempfile.TemporaryDirectory(prefix='pg-scope-capture-test-')
        self.addCleanup(self._temp.cleanup)
        self.runtime = FakeRuntime(self._temp.name)
        self.runtime_context = patch.dict(self.session.components, services=Component({
            'get_runtime': lambda: self.runtime, 'current_runtime': lambda: self.runtime}))
        self.wake_context = patch.object(self.scheduler, 'wake', new=lambda *_args, **_kwargs: None)
        self.runtime_context.start(); self.wake_context.start()
        self.addCleanup(self.wake_context.stop)
        self.addCleanup(self.runtime_context.stop)

    def tearDown(self):
        try:
            # Test consumers can intentionally finish while their fake worker
            # remains live. Retire those physical leases before closing the App.
            for handle in self.runtime.handles:
                if not handle.retired():handle.finish()
            self.capture.clear()
            self.assertTrue(self.capture.collect_retired())
        finally:
            super().tearDown()

    def compositor_target(self):
        scene = bpy.context.scene
        scene.render.resolution_x = 16
        scene.render.resolution_y = 8
        scene.render.resolution_percentage = 100
        tree = bpy.data.node_groups.new('Scope capture compositor', 'CompositorNodeTree')
        scene.compositing_node_group = tree
        tree.interface.new_socket(name='Color', in_out='OUTPUT', socket_type='NodeSocketColor')
        source = tree.nodes.new('CompositorNodeRGB')
        source.outputs[0].default_value = (.2, .4, .8, .5)
        output = tree.nodes.new('NodeGroupOutput')
        tree.links.new(source.outputs[0], output.inputs['Color'])
        context = SimpleNamespace(scene=scene, view_layer=scene.view_layers[0], object=None,
            space_data=None, window=None, area=None, region=None)
        return scene, tree, source, output, context

    def descriptor(self, node, context, socket='Color'):
        return self.capture.describe(node, socket,
            context=self.contexts.describe(node, socket, context))

    def request(self, node, descriptor):
        previous=next((item for item in self.capture.states.values()
                       if item['request']['consumer']==descriptor['consumer']
                       and item['request']['node_name']==descriptor['node_name']),None)
        if previous is not None and previous['request']['identity']!=descriptor['identity']:
            self.capture.mark_stale(node,descriptor)
        self.capture.acquire(node,(('Color',descriptor,(16,8),False),))
        try:self.capture.sample(node,'Color',(16,8),descriptor=descriptor)
        except component('graph.lut').ScopePreparing:pass
        return next(item for item in self.capture.states.values() if item['request']['identity']==descriptor['identity'])

    def start_bake(self):
        _scene, tree, source, output, context = self.compositor_target()
        node = component('graph.nodes').create_grade(tree)
        tree.links.new(source.outputs[0], node.inputs['Color'])
        tree.links.new(node.outputs['Color'], output.inputs['Color'])
        token = self.capture.start_bake(node, context=context)
        state = self.capture.bakes[token]
        self.assertEqual(state['handle'].spec.operation, 'compositor_bake')
        self.assertIsNone(state['handle'].spec.key)
        return token, state, state['handle']

    @staticmethod
    def bake_artifact(state, **changes):
        # These tests exercise ownership and receipt validation; native EXR
        # decoding/evaluation is covered by the generated-scene bake target.
        path = state['directory'] / 'captured.exr'
        path.write_bytes(b'opaque helper artifact')
        artifact = dict(identity=state['request']['identity'], path=str(path),
                        sha256=hashlib.sha256(path.read_bytes()).hexdigest())
        artifact.update(changes)
        return artifact

    def test_immediate_native_snapshot_is_shared_across_scope_stages(self):
        scene, tree, source, output, context = self.compositor_target()
        descriptor = self.descriptor(output, context)
        state = self.request(output, descriptor)
        self.assertEqual(len(self.runtime.specs),1)
        self.assertEqual(state['due'],0)

        # Full, linear and repeated display requests use this one native source
        # request. Stage-specific analysis remains downstream of capture.
        self.request(output, descriptor)
        self.assertEqual(len(self.capture.states), 1)
        self.assertEqual(len(self.runtime.specs),1)
        state['due'] = 0
        self.capture.poll()
        self.assertEqual(len(self.runtime.specs), 1)

        handle = self.runtime.handles[0]
        handle.finish()
        self.capture.poll()
        rgba, identity, label = self.capture.sample(output, 'Color', (16, 8), descriptor=descriptor)
        self.assertEqual(identity, descriptor['identity'])
        self.assertEqual(label, 'fake native graph')
        self.assertEqual(rgba.shape, (2, 3, 4))
        self.assertFalse(rgba.flags.writeable)
        self.assertEqual(len(self.runtime.specs), 1)
        self.assertFalse(tuple(self.runtime.session.path.glob('capture-*')))

    def test_queries_and_numerical_retry_never_authorize_native_input(self):
        _scene,_tree,_source,target,context=self.compositor_target()
        descriptor=self.descriptor(target,context)
        for _ in range(3):
            with self.assertRaisesRegex(component('graph.lut').ScopePreparing,'Waiting for automatic'):
                self.capture.sample(target,descriptor=descriptor)
            self.capture.retry(target)
            self.capture.poll()
        self.assertFalse(self.runtime.specs)
        self.assertFalse(self.capture.states)
        self.assertEqual(self.capture.status(target,descriptor)['state'],'waiting')

    def test_one_request_is_consumed_once_and_duplicate_request_is_disabled(self):
        _scene,_tree,_source,target,context=self.compositor_target()
        descriptor=self.descriptor(target,context)
        inputs=(('Color',descriptor,(16,8),False),)
        self.assertTrue(self.capture.acquire(target,inputs))
        self.assertFalse(self.capture.acquire(target,inputs))
        self.assertTrue(self.capture.status(target,descriptor)['pending'])
        state=next(iter(self.capture.states.values()));state['due']=0
        self.capture.poll();self.capture.poll()
        self.assertEqual(len(self.runtime.specs),1)
        self.runtime.handles[0].finish(error=RuntimeError('Native read failed'))
        self.capture.poll()
        self.assertEqual(self.capture.status(target,descriptor)['state'],'error')
        self.capture.retry(target);self.capture.poll()
        self.assertEqual(len(self.runtime.specs),1)
        self.assertTrue(self.capture.acquire(target,inputs))

    def test_capture_prepares_frozen_models_privately_without_live_output_wait(self):
        _scene,tree,source,target,context=self.compositor_target()
        grade=component('graph.nodes').create_grade(tree)
        tree.links.new(source.outputs[0],grade.inputs['Color'])
        tree.links.new(grade.outputs['Color'],target.inputs['Color'])
        descriptor=self.descriptor(target,context)
        self.assertEqual(len(descriptor['_pg_models']),1)
        before=component('graph.lut').installed_signal(grade)
        before=(before[0],*(np.array(value,copy=True) for value in before[1:]))
        with patch.object(component('graph.lut'),'scope_signal',new=lambda *_a,**_k:self.fail('Live output preparation')):
            self.capture.acquire(target,(('Color',descriptor,(16,8),False),))
        self.assertEqual(len(self.runtime.specs),1)
        self.assertEqual(self.runtime.specs[0].inputs['_pg_models'],descriptor['_pg_models'])
        after=component('graph.lut').installed_signal(grade)
        self.assertEqual(after[0],before[0])
        for a,b in zip(after[1:],before[1:]):np.testing.assert_array_equal(a,b)
        self.runtime.handles[0].finish();self.capture.poll()
        self.assertEqual(self.capture.status(target,descriptor)['state'],'captured')

    def test_cancelled_automatic_capture_retains_snapshot_until_retirement(self):
        _scene,_tree,_source,target,context=self.compositor_target()
        descriptor=self.descriptor(target,context);completed=[]
        self.capture.acquire(target,(('Color',descriptor,(16,8),False),),complete=lambda ok:completed.append(ok) or ok)
        state=next(iter(self.capture.states.values()));directory=state['directory']
        self.capture.cancel_scope(target,descriptor)
        self.assertEqual(completed,[False])
        self.assertTrue(directory.exists())
        self.assertTrue(self.runtime.handles[0].cancel_requested)
        self.runtime.handles[0].finish();self.capture.poll()
        self.assertFalse(directory.exists())

    def test_primary_reference_are_adopted_as_one_authorized_batch(self):
        _scene,tree,source,target,context=self.compositor_target()
        tree.interface.new_socket(name='Reference',in_out='OUTPUT',socket_type='NodeSocketColor')
        tree.links.new(source.outputs[0],target.inputs['Reference'])
        primary=self.descriptor(target,context)
        reference=self.descriptor(target,context,'Reference')
        self.capture.acquire(target,(('Color',primary,(16,8),False),('Reference',reference,None,True)))
        for state in self.capture.states.values():state['due']=0
        self.capture.poll()
        self.assertEqual(len(self.runtime.specs),1)
        self.runtime.handles[0].finish();self.capture.poll()
        self.assertIsNone(self.capture.accepted_descriptor(target,context=primary))
        self.assertEqual(len(self.runtime.specs),2)
        self.assertEqual(tuple(self.runtime.specs[1].inputs['sample_size']),(3,2))
        self.assertEqual(tuple(self.runtime.specs[1].inputs['sample_grid']['key']),
                         ('scope-grid-v1',3,2,3,2))
        self.runtime.handles[1].finish();self.capture.poll()
        self.assertIsNotNone(self.capture.accepted_descriptor(target,context=primary))
        self.assertIsNotNone(self.capture.accepted_descriptor(target,'Reference',reference))
        self.assertEqual(self.capture.status(target,primary)['state'],'captured')
        self.assertFalse(self.capture.status(target,primary)['pending'])

    def test_snapshot_preserves_frozen_reference_grid_and_provenance(self):
        from color_tools.perceptual_grade_core.scopes.samples import ordinary_layout
        _scene,_tree,_source,target,context=self.compositor_target()
        descriptor=self.descriptor(target,context)
        layout=ordinary_layout(3,2)
        descriptor['_sample_grid']={name:getattr(layout,name)
            for name in ('mass','x','uv','tiles','ids','key')}
        state=self.request(target,descriptor);state['due']=0;self.capture.poll()
        self.assertEqual(state['request']['_scope_provenance'],descriptor['_scope_provenance'])
        grid=self.runtime.specs[0].inputs['sample_grid']
        np.testing.assert_array_equal(grid['uv'],layout.uv)
        self.runtime.handles[0].finish();self.capture.poll()
        accepted=self.capture.accepted_descriptor(target,context=descriptor)
        self.assertEqual(accepted['_scope_provenance'],descriptor['_scope_provenance'])
        np.testing.assert_array_equal(accepted['_sample_grid']['uv'],layout.uv)

    def test_native_reference_readback_uses_primary_tile_uv_instead_of_storage_grid(self):
        from color_tools.perceptual_grade_core.scopes.samples import tiled_layout,sample_rgba
        from color_tools.perceptual_grade_blender.jobs.handlers.native_capture import _sample_layout,_read_compositor
        layout=tiled_layout(((1001,2,2),(1002,3,2)),maximum=7)
        grid={name:getattr(layout,name) for name in ('mass','x','uv','tiles','ids','key')}
        frozen=_sample_layout(grid)
        pixels=np.arange(4*5*4,dtype=np.float32).reshape(4,5,4)/80
        image=bpy.data.images.new('Native reference grid',width=5,height=4,alpha=True,float_buffer=True)
        image.colorspace_settings.name='Non-Color';image.alpha_mode='CHANNEL_PACKED'
        image.pixels.foreach_set(pixels.ravel());image.update()
        path=Path(self._temp.name)/'reference.exr'
        image.filepath_raw=str(path);image.file_format='OPEN_EXR';image.save()
        actual,domain=_read_compositor(path,(7,1),True,frozen)
        self.assertEqual(domain,(5,4))
        np.testing.assert_allclose(actual,sample_rgba(pixels,layout),rtol=0,atol=1e-6)
        self.assertFalse(frozen.uv.flags.writeable)

    def test_native_watch_marks_source_stale_and_retains_accepted_pixels(self):
        _scene,_tree,source,target,context=self.compositor_target()
        descriptor=self.descriptor(target,context);state=self.request(target,descriptor)
        state['due']=0;self.capture.poll();self.runtime.handles[0].finish();self.capture.poll()
        before=self.capture.sample(target,descriptor=descriptor)[0]
        self.capture.invalidate()
        self.assertFalse(self.capture.check_stale(target,descriptor,force=True))
        source.outputs[0].default_value=(.9,.1,.3,1.)
        self.capture.invalidate()
        self.assertTrue(self.capture.check_stale(target,descriptor,force=True))
        self.assertEqual(self.capture.status(target,descriptor)['state'],'refresh_needed')
        self.assertIs(self.capture.sample(target,descriptor=descriptor)[0],before)
        self.capture.poll()
        self.assertEqual(len(self.runtime.specs),1)

    def test_scope_only_reset_preserves_running_bake_and_its_snapshot(self):
        token,state,handle=self.start_bake()
        directory=state['directory']
        self.capture.clear_scopes()
        self.assertIn(token,self.capture.bakes)
        self.assertFalse(handle.cancel_requested)
        self.assertTrue(directory.exists())

    def test_opt_in_diagnostics_report_snapshot_phases_and_helper_adoption(self):
        scene, tree, source, output, context = self.compositor_target()
        self.capture.enable_diagnostics(True)
        descriptor = self.descriptor(output, context)
        state = self.request(output, descriptor)
        state['due'] = 0
        self.capture.poll()
        self.assertEqual(len(self.runtime.handles), 1)
        spec = self.runtime.specs[0]
        self.assertTrue(spec.inputs['_capture_diagnostics'])
        timing_values = {'native_render_seconds':.5,
                         'nested':MappingProxyType({'sample_bytes':96})}
        self.runtime.handles[0].finish(dict(
            identity=spec.inputs['identity'], rgba=np.full((2,3,4),.25,np.float32),
            domain=(16,8), label='fake native graph',
            _capture_timings=MappingProxyType(timing_values)))
        self.capture.poll()
        timing_values['native_render_seconds'] = 9.
        records = self.capture.diagnostics()
        events = [item['event'] for item in records]
        self.assertIn('request_created', events)
        self.assertIn('submit', events)
        self.assertIn('capture_adopted', events)
        phases = {item.get('phase') for item in records if item['event']=='phase'}
        self.assertTrue({'context','graph_and_dependency_description','blend_serialization',
                         'snapshot_dependency_walk','resource_snapshot','snapshot_total'} <= phases)
        adopted = next(item for item in records if item['event']=='capture_adopted')
        self.assertEqual(adopted['owner_kind'],'compositor')
        self.assertEqual(adopted['helper_timings']['native_render_seconds'],.5)
        self.assertEqual(adopted['helper_timings']['nested'],{'sample_bytes':96})
        self.assertEqual(len(adopted['capture']),64)
        self.capture.enable_diagnostics(False)
        self.assertEqual(self.capture.diagnostics(),[])

    def test_diagnostic_helper_metadata_failure_keeps_submitted_snapshot_leased(self):
        class BrokenHelper:
            @property
            def ready(self):
                raise RuntimeError('diagnostic metadata unavailable')

            generation = 3

        _scene, tree, source, output, context = self.compositor_target()
        self.capture.enable_diagnostics(True)
        self.runtime.helpers['capture'] = BrokenHelper()
        descriptor = self.descriptor(output, context)
        state = self.request(output, descriptor)
        state['due'] = 0
        self.capture.poll()
        handle = state['handle']
        directory = state['directory']
        self.assertIsNotNone(handle)
        self.assertTrue(directory.is_dir())

        handle.finish(dict(identity=state['request']['identity'],
                           rgba=np.full((2,3,4),.25,np.float32), domain=(16,8)))
        self.capture.poll()
        self.assertFalse(state['error'])
        self.assertIsNotNone(state['result'])
        self.assertFalse(directory.exists())

    def test_native_fingerprint_skips_grade_ui_settings_but_keeps_math_semantics(self):
        _scene, tree, source, output, context = self.compositor_target()
        math = tree.nodes.new('ShaderNodeMath')
        source_link = tree.links.new(source.outputs[0], math.inputs[0])
        tree.links.new(math.outputs[0], output.inputs['Color'])
        nodes = component('graph.nodes')
        original_links = bpy.types.NodeSocket.links
        socket_scans = []

        def links(socket):
            socket_scans.append(socket.as_pointer())
            return original_links.__get__(socket, type(socket))

        with patch.object(nodes, 'owner', side_effect=AssertionError('Native nodes evaluated Grade UI settings')), \
                patch.object(bpy.types.NodeSocket, 'links', new=property(links)):
            initial = self.descriptor(output, context)['version']
            math.operation = 'MULTIPLY'
            operation = self.descriptor(output, context)['version']
            math.inputs[1].default_value = .75
            value = self.descriptor(output, context)['version']
            math.mute = True
            muted = self.descriptor(output, context)['version']
            math.inputs[1].default_value = .33
            self.assertEqual(self.descriptor(output, context)['version'], muted)
            tree.links.remove(source_link)
            disconnected = self.descriptor(output, context)['version']
        self.assertNotEqual(initial, operation)
        self.assertNotEqual(operation, value)
        self.assertNotEqual(muted, disconnected)
        self.assertFalse(socket_scans, 'Fingerprint rescanned all tree links for each socket')

    def test_grade_fingerprint_keeps_saved_controls_without_sidebar_getters(self):
        _scene, tree, source, output, context = self.compositor_target()
        nodes, lut = component('graph.nodes'), component('graph.lut')
        grade = nodes.create_grade(tree)
        tree.links.new(source.outputs[0], grade.inputs['Color'])
        tree.links.new(grade.outputs['Color'], output.inputs['Color'])
        lut.ensure(grade, nodes.bake_model(grade), force=True)
        panel = component('ui.panel')
        with patch.object(panel, 'warp_hue_value', side_effect=AssertionError('Fingerprint evaluated an unsaved sidebar alias')):
            initial = self.descriptor(output, context)['version']
        nodes.write_chromatic(grade, {'global_gain': .2})
        lut.ensure(grade, nodes.bake_model(grade), force=True)
        with patch.object(panel, 'warp_hue_value', side_effect=AssertionError('Fingerprint evaluated an unsaved sidebar alias')):
            changed = self.descriptor(output, context)['version']
        self.assertNotEqual(initial, changed)

    def test_cancelled_snapshot_lease_waits_for_physical_helper_retirement(self):
        scene, tree, source, output, context = self.compositor_target()
        descriptor = self.descriptor(output, context)
        state = self.request(output, descriptor)
        state['due'] = 0
        self.capture.poll()
        handle = self.runtime.handles[0]
        directory = state['directory']
        self.assertTrue((directory / 'scene.blend').is_file())
        protocol = state['protocol']
        self.assertEqual(protocol.state.phase, 'capturing')

        self.capture.clear()
        self.assertTrue(handle.cancel_requested)
        self.assertIn(state, self.capture.retiring)
        self.assertEqual(protocol.state.phase, 'retiring')
        self.assertTrue(directory.exists())
        self.capture.poll()
        self.assertTrue(directory.exists(), 'Cancellation acknowledgement is not worker retirement')

        handle.finish()
        self.capture.poll()
        self.assertFalse(directory.exists())
        self.assertNotIn(state, self.capture.retiring)
        self.assertNotIn('protocol', state)

    def test_closed_runtime_does_not_release_an_unretired_scope_snapshot(self):
        _scene, _tree, _source, output, context = self.compositor_target()
        state = self.request(output, self.descriptor(output, context))
        state['due'] = 0
        self.capture.poll()
        handle, directory = state['handle'], state['directory']
        self.capture.clear()
        self.runtime.closed = True
        self.capture.poll()
        self.assertTrue(directory.exists(), 'Closed runtime is not physical retirement')
        handle.finish()
        self.capture.poll()
        self.assertFalse(directory.exists())

    def test_completed_bake_keeps_artifact_without_idle_polling_until_release(self):
        token, state, handle = self.start_bake()
        directory, owner = state['directory'], state['node']
        artifact = self.bake_artifact(state)
        handle.finish(artifact)
        self.assertIsNone(self.capture.poll())
        self.assertIsNone(component('ownership').resolve(owner))
        self.assertTrue(directory.exists())
        self.assertEqual(self.capture.bake_status(token), artifact)
        self.assertEqual(self.capture.bake_status(token), artifact)
        # A ready result keeps its artifact lease, but another target can
        # already freeze/submit its own independent request.
        second, second_state, second_handle = self.start_bake()
        second_directory = second_state['directory']
        self.assertEqual(len(self.capture.bakes), 2)
        self.assertEqual(self.capture.bake_status(token), artifact)
        self.assertTrue(self.capture.release_bake(token))
        self.assertFalse(directory.exists())
        self.assertTrue(second_directory.exists())
        self.assertFalse(second_handle.cancel_requested)
        self.assertFalse(self.capture.release_bake(token))
        with self.assertRaisesRegex(KeyError, 'Unknown compositor bake'):
            self.capture.bake_status(token)
        self.capture.cancel_bake(second)
        self.capture.release_bake(second)
        second_handle.finish()
        self.capture.poll()
        self.assertFalse(second_directory.exists())

    def test_failed_upstream_preparation_admits_no_bake_and_restores_rendering_state(self):
        nodes = component('graph.nodes')
        _scene, tree, source, output, context = self.compositor_target()
        upstream, target = nodes.create_grade(tree), nodes.create_grade(tree)
        tree.links.new(source.outputs[0], upstream.inputs['Color'])
        tree.links.new(upstream.outputs['Color'], target.inputs['Color'])
        tree.links.new(target.outputs['Color'], output.inputs['Color'])
        rendering = nodes._rendering
        def fail(*_args, **_kwargs):
            raise RuntimeError('Current exact output is unavailable')
        with patch.object(component('graph.lut'), 'ensure', new=fail):
            with self.assertRaisesRegex(RuntimeError, 'Current exact output is unavailable'):
                self.capture.start_bake(target, context=context)
        self.assertEqual(nodes._rendering, rendering)
        self.assertFalse(self.capture.bakes)
        self.assertFalse(self.capture.bake_retiring)
        self.assertFalse(tuple(self.runtime.session.path.glob('bake-*')))
        self.assertFalse(any(spec.operation == 'compositor_bake' for spec in self.runtime.specs))

    def test_accepted_capture_returns_its_token_when_timer_scheduling_fails(self):
        # Build the scene before injecting failure: node construction itself
        # legitimately schedules automatic LUT work.
        _scene, tree, source, output, context = self.compositor_target()
        node = component('graph.nodes').create_grade(tree)
        tree.links.new(source.outputs[0], node.inputs['Color'])
        tree.links.new(node.outputs['Color'], output.inputs['Color'])
        with patch.object(self.scheduler, 'wake', side_effect=RuntimeError('timer unavailable')), \
                self.assertLogs(self.capture.__name__, level='ERROR') as logged:
            token = self.capture.start_bake(node, context=context)
        self.assertTrue(any('accepted compositor bake' in line for line in logged.output))
        state = self.capture.bakes[token]
        handle, directory = state['handle'], state['directory']
        self.assertFalse(handle.retired())
        self.capture.cancel_bake(token)
        self.capture.release_bake(token)
        self.assertTrue(directory.exists())
        handle.finish()
        self.capture.collect_retired()
        self.assertFalse(directory.exists())

    def test_selected_lut_is_not_required_and_analytic_settings_are_frozen(self):
        nodes, lut = component('graph.nodes'), component('graph.lut')
        _scene, tree, source, output, context = self.compositor_target()
        target = nodes.create_grade(tree)
        tree.links.new(source.outputs[0], target.inputs['Color'])
        tree.links.new(target.outputs['Color'], output.inputs['Color'])
        nodes.write_chromatic(target, {'global_gain': .2})
        with patch.object(lut, 'ensure', side_effect=AssertionError('Selected LUT must not be required')):
            token = self.capture.start_bake(target, context=context)
        state = self.capture.bakes[token]
        payload = state['handle'].spec.inputs
        before = repr(payload['analytic'])
        self.assertEqual(payload['analytic']['kind'], 'GRADE')
        self.assertEqual(payload['identity'][0], 'analytic-compositor-bake-v1')
        nodes.write_values(target, {'exposure': .5})
        nodes.write_chromatic(target, {'global_gain': .4})
        self.assertEqual(repr(payload['analytic']), before)

    def test_bake_identity_includes_endpoint_rows_omitted_from_lut_signature(self):
        nodes, lut = component('graph.nodes'), component('graph.lut')
        _scene, tree, source, output, context = self.compositor_target()
        target = nodes.create_grade(tree)
        tree.links.new(source.outputs[0], target.inputs['Color'])
        tree.links.new(target.outputs['Color'], output.inputs['Color'])
        first_token = self.capture.start_bake(target, context=context)
        first = self.capture.bakes[first_token]
        identity = first['request']['identity']
        model_key = lut.cm.signature(nodes.bake_model(target))
        self.capture.release_bake(first_token)
        first['handle'].finish()
        self.capture.collect_retired()
        nodes.write_values(target, {'exposure': .5})
        self.assertEqual(lut.cm.signature(nodes.bake_model(target)), model_key)
        second_token = self.capture.start_bake(target, context=context)
        self.assertNotEqual(self.capture.bakes[second_token]['request']['identity'], identity)

    def test_pg_output_identity_tracks_only_the_connected_color_branch(self):
        nodes, bake = component('graph.nodes'), component('graph.bake')
        _scene, tree, source, output, context = self.compositor_target()
        upstream = nodes.create_grade(tree)
        image = bpy.data.images.new('Bound analytic bake', width=2, height=2, alpha=True, float_buffer=True)
        image.pixels.foreach_set(np.tile(np.array((.2, .4, .8, .375), np.float32), 4));image.update()
        image['_pg_bake_schema']=2
        image['_pg_bake_storage']='FLOAT_RGBA'
        image['_pg_bake_kind']='COMPOSITOR'
        image['_pg_bake_width'],image['_pg_bake_height']=tuple(image.size)
        if not image.has_data:
            image.pixels.foreach_set(np.tile(np.array((0.,0.,0.,1.),np.float32),int(image.size[0])*int(image.size[1])));image.update()
        image.pack()
        bake.set_baked_image(upstream, image)
        tree.links.new(source.outputs[0], upstream.inputs['Color'])
        tree.links.new(upstream.outputs['Color'], output.inputs['Color'])
        first = self.descriptor(output, context)
        image.pixels.foreach_set(np.tile(np.array((.7, .1, .3, .75), np.float32), 4));image.update()
        self.capture.invalidate()
        self.assertEqual(self.descriptor(output, context)['identity'], first['identity'])
        tree.links.new(upstream.outputs['Baked Color'], output.inputs['Color'])
        baked = self.descriptor(output, context)
        source.outputs[0].default_value = (.9, .7, .3, 1.)
        nodes.write_values(upstream, {'exposure': .5})
        self.assertEqual(self.descriptor(output, context)['identity'], baked['identity'])
        image.pixels.foreach_set(np.tile(np.array((.1, .3, .2, .25), np.float32), 4));image.update()
        self.capture.invalidate()
        self.assertNotEqual(self.descriptor(output, context)['identity'], baked['identity'])

    def test_baked_input_does_not_prepare_upstream_live_grade(self):
        nodes, bake, lut = component('graph.nodes'), component('graph.bake'), component('graph.lut')
        _scene, tree, _source, output, context = self.compositor_target()
        upstream, target = nodes.create_grade(tree), nodes.create_grade(tree)
        image = bpy.data.images.new('Fixed baked input', width=2, height=2, alpha=True, float_buffer=True)
        image['_pg_bake_schema']=2
        image['_pg_bake_storage']='FLOAT_RGBA'
        image['_pg_bake_kind']='COMPOSITOR'
        image['_pg_bake_width'],image['_pg_bake_height']=tuple(image.size)
        image.pixels.foreach_set(np.tile(np.array((0.,0.,0.,1.),np.float32),int(image.size[0])*int(image.size[1])));image.update()
        image.pack()
        bake.set_baked_image(upstream, image)
        tree.links.new(upstream.outputs['Baked Color'], target.inputs['Color'])
        tree.links.new(target.outputs['Color'], output.inputs['Color'])
        with patch.object(lut, 'ensure', side_effect=AssertionError('Baked Color does not read the live Grade')):
            token = self.capture.start_bake(target, context=context)
        self.assertIn(token, self.capture.bakes)

    def test_scope_baked_grade_and_stack_inputs_ignore_live_models_but_track_image_pixels(self):
        nodes, bake, lut = component('graph.nodes'), component('graph.bake'), component('graph.lut')
        sampling = component('scopes.sampling')
        for kind in ('Grade', 'Stack'):
            with self.subTest(kind=kind):
                _scene, tree, source, output, context = self.compositor_target()
                grade = nodes.create_grade(tree)
                upstream = grade if kind == 'Grade' else sequence(tree, [grade.pg_grade])
                target = nodes.create_grade(tree)
                image = bpy.data.images.new('Static scope ' + kind, width=2, height=2,
                                            alpha=True, float_buffer=True)
                image.pixels.foreach_set(np.tile(np.array((.2, .4, .8, .375), np.float32), 4))
                image.update()
                image['_pg_bake_schema']=2
                image['_pg_bake_storage']='FLOAT_RGBA'
                image['_pg_bake_kind']='COMPOSITOR'
                image['_pg_bake_width'],image['_pg_bake_height']=tuple(image.size)
                if not image.has_data:
                    image.pixels.foreach_set(np.tile(np.array((0.,0.,0.,1.),np.float32),int(image.size[0])*int(image.size[1])));image.update()
                image.pack()
                bake.set_baked_image(upstream, image)
                tree.links.new(source.outputs[0], upstream.inputs['Color'])
                tree.links.new(upstream.outputs['Baked Color'], target.inputs['Color'])
                tree.links.new(target.outputs['Color'], output.inputs['Color'])
                location = self.contexts.describe(target, context=context)

                def describe():
                    with (patch.object(nodes, 'bake_model', side_effect=AssertionError('Unused live model')),
                         patch.object(lut, 'scope_signal', side_effect=AssertionError('Unused live LUT')),
                         patch.object(lut, 'validate_output', side_effect=AssertionError('Unused final output'))):
                        sampling.probe_sources(target,nodes.working_space(),force=True,capture_context=location)
                        full = sampling.describe(target, nodes.working_space(), capture_context=location)
                        linear = sampling.describe_linear(target, nodes.working_space(), capture_context=location)
                        self.assertEqual(full['_dependencies'], {})
                        self.assertEqual(linear['_dependencies'], {})
                        for action in (lambda: sampling.capture(full),
                                       lambda: sampling.capture_linear(linear, {})):
                            action()
                        self.assertFalse(self.capture.states,'Baked Image unnecessarily admitted native capture')
                        return full, linear

                first, first_linear = describe()
                nodes.write_chromatic(grade, {'global_gain': .5})
                source.outputs[0].default_value = (.7, .1, .3, 1.)
                unchanged, unchanged_linear = describe()
                self.assertEqual(first['key'], unchanged['key'])
                self.assertEqual(first_linear['key'], unchanged_linear['key'])
                image.pixels.foreach_set(np.tile(np.array((.7, .1, .3, .75), np.float32), 4))
                image.update(); self.capture.invalidate()
                changed, changed_linear = describe()
                self.assertNotEqual(first['key'], changed['key'])
                self.assertNotEqual(first_linear['key'], changed_linear['key'])
                # The live Color output still has its real grading dependency.
                tree.links.new(upstream.outputs['Color'], target.inputs['Color'])
                dependencies = {}
                sampling.native_dependencies(target, 'Color', dependencies, location)
                self.assertIn(upstream.as_pointer(), dependencies)
                sampling.release({'_dependencies': dependencies})

    def test_scope_dependencies_follow_alpha_and_muted_native_bypasses(self):
        nodes = component('graph.nodes')
        sampling = component('scopes.sampling')
        tree = bpy.data.node_groups.new('Shader dependency outputs', 'ShaderNodeTree')
        source = tree.nodes.new('ShaderNodeRGB')
        upstream, target = nodes.create_grade(tree), nodes.create_grade(tree)
        tree.links.new(source.outputs[0], upstream.inputs['Color'])

        def assert_no_live_dependency():
            with patch.object(nodes, 'bake_model', side_effect=AssertionError('Unused live model')):
                dependencies = {}
                sampling.native_dependencies(target, 'Color', dependencies)
                self.assertEqual(dependencies, {})

        tree.links.new(upstream.outputs['Alpha'], target.inputs['Color'])
        assert_no_live_dependency()
        upstream.mute = True
        self.assertTrue(any(link.to_socket == upstream.outputs['Color'] for link in upstream.internal_links))
        tree.links.new(upstream.outputs['Color'], target.inputs['Color'])
        assert_no_live_dependency()
        upstream.mute = False
        math = tree.nodes.new('ShaderNodeMath')
        math.operation = 'ADD'
        for socket in math.inputs[:2]:tree.links.new(source.outputs[0], socket)
        tree.links.new(math.outputs[0], target.inputs['Color'])
        math.mute = True
        bypass = tuple(link.from_socket for link in math.internal_links if link.to_socket == math.outputs[0])
        self.assertEqual(len(bypass), 1)
        unused = next(socket for socket in math.inputs[:2] if socket not in bypass)
        tree.links.new(upstream.outputs['Color'], unused)
        self.assertEqual(tuple(link.from_socket for link in math.internal_links
                               if link.to_socket == math.outputs[0]), bypass)
        assert_no_live_dependency()

        # Alpha passes through its own input, so a live Color signal connected
        # there must still contribute its grading dependency.
        alpha_source = nodes.create_grade(tree)
        tree.links.new(alpha_source.outputs['Color'], upstream.inputs['Alpha'])
        tree.links.new(upstream.outputs['Alpha'], target.inputs['Color'])
        dependencies = {}
        sampling.native_dependencies(target, 'Color', dependencies)
        self.assertEqual(set(dependencies), {alpha_source.as_pointer()})
        sampling.release({'_dependencies': dependencies})

    def test_baked_scope_dependencies_keep_the_exact_shared_group_occurrence(self):
        nodes, bake = component('graph.nodes'), component('graph.bake')
        sampling = component('scopes.sampling')
        _scene, tree, _source, output, context = self.compositor_target()
        upstream = nodes.create_grade(tree)
        image = bpy.data.images.new('Grouped baked scope', width=2, height=2, float_buffer=True)
        image['_pg_bake_schema']=2
        image['_pg_bake_storage']='FLOAT_RGBA'
        image['_pg_bake_kind']='COMPOSITOR'
        image['_pg_bake_width'],image['_pg_bake_height']=tuple(image.size)
        image.pixels.foreach_set(np.tile(np.array((0.,0.,0.,1.),np.float32),int(image.size[0])*int(image.size[1])));image.update()
        image.pack()
        bake.set_baked_image(upstream, image)
        group = bpy.data.node_groups.new('Shared scope occurrence', 'CompositorNodeTree')
        group.interface.new_socket(name='Color', in_out='INPUT', socket_type='NodeSocketColor')
        group.interface.new_socket(name='Color', in_out='OUTPUT', socket_type='NodeSocketColor')
        incoming, outgoing = group.nodes.new('NodeGroupInput'), group.nodes.new('NodeGroupOutput')
        target = nodes.create_grade(group)
        group.links.new(incoming.outputs['Color'], target.inputs['Color'])
        group.links.new(target.outputs['Color'], outgoing.inputs['Color'])
        first = tree.nodes.new('CompositorNodeGroup'); first.node_tree = group
        tree.links.new(upstream.outputs['Baked Color'], first.inputs['Color'])
        tree.links.new(first.outputs['Color'], output.inputs['Color'])
        location = self.contexts.describe(target, context=context)
        second = tree.nodes.new('CompositorNodeGroup'); second.node_tree = group
        tree.links.new(upstream.outputs['Color'], second.inputs['Color'])
        with patch.object(nodes, 'bake_model', side_effect=AssertionError('Wrong group occurrence')):
            spec = sampling.describe(target, nodes.working_space(), capture_context=location)
            self.assertEqual(spec['_dependencies'], {})
        dependencies = {}
        sampling.native_dependencies(target, 'Color', dependencies,
                                     dict(location, group_path=(second.name,)))
        self.assertEqual(set(dependencies), {upstream.as_pointer()})
        sampling.release({'_dependencies': dependencies})

    def test_graph_link_index_releases_native_wrappers_before_return_without_gc(self):
        _scene, _tree, _source, target, context = self.compositor_target()
        describe = self.capture.describe
        graph = dict(zip(describe.__code__.co_freevars, describe.__closure__))['_graph'].cell_contents
        properties = dict(zip(graph.__code__.co_freevars, graph.__closure__))['_properties']
        original = properties.cell_contents
        indices, populated = [], []
        previous_profile, enabled = sys.getprofile(), gc.isenabled()

        def observe(frame, event, _value):
            if event == 'return' and frame.f_code is graph.__code__:
                # Retain the dictionary to test its synchronous clearing; never
                # retain the frame or a native RNA object from its other locals.
                indices.append(frame.f_locals['incoming'])
            elif event == 'return' and frame.f_code.co_name == 'links':
                populated.append(bool(frame.f_locals.get('incoming')))

        def fail_properties(*_args, **_kwargs):
            raise ValueError('Fingerprint failure after link indexing')

        gc.disable()
        sys.setprofile(observe)
        try:
            self.descriptor(target, context)
            properties.cell_contents = fail_properties
            with self.assertRaisesRegex(ValueError, 'Fingerprint failure after link indexing'):
                self.descriptor(target, context)
            self.assertTrue(any(populated), 'The generated graph never populated its link index')
            self.assertEqual(len(indices), 2)
            self.assertTrue(all(not index for index in indices),
                            'A traversal closure retained native links until cyclic GC')
        finally:
            properties.cell_contents = original
            sys.setprofile(previous_profile)
            if enabled:gc.enable()

    def test_native_capture_worklists_release_temporary_rna_without_gc(self):
        nodes = component('graph.nodes')
        _scene, tree, source, _output, context = self.compositor_target()
        upstream, target = nodes.create_grade(tree), nodes.create_grade(tree)
        tree.links.new(source.outputs[0], upstream.inputs['Color'])
        tree.links.new(upstream.outputs['Color'], target.inputs['Color'])
        referenced = bpy.data.scenes.new('Referenced capture scene')
        layer = tree.nodes.new('CompositorNodeRLayers'); layer.scene = referenced
        location = self.contexts.describe(target, context=context)

        def closure(function, name):
            return dict(zip(function.__code__.co_freevars, function.__closure__))[name].cell_contents

        references = closure(self.capture.describe, '_graph')
        upstream_grades = closure(closure(self.capture.start_bake, '_prepare_bake_input'), '_upstream_grades')
        watched = {references.__code__, upstream_grades.__code__}
        observations = []
        previous_profile, enabled = sys.getprofile(), gc.isenabled()

        def observe(frame, event, _value):
            if event == 'return' and frame.f_code in watched:
                # Only booleans escape the callback, never frames or raw RNA.
                observations.append(all(not frame.f_locals.get(name)
                    for name in ('work', 'incoming', 'result', 'required', 'parents')))

        gc.disable()
        sys.setprofile(observe)
        try:
            self.assertTrue(references(target,'Color')[0])
            self.assertEqual(upstream_grades(target, location), (upstream,))
            with patch.object(nodes, 'is_grade', side_effect=ValueError('Interrupted native traversal')):
                with self.assertRaisesRegex(ValueError, 'Interrupted native traversal'):
                    upstream_grades(target, location)
            self.assertEqual(observations, [True] * 3)
        finally:
            sys.setprofile(previous_profile)
            if enabled:gc.enable()

    def test_iterative_fingerprint_matches_python_container_representation(self):
        fingerprint = dict(zip(self.capture.describe.__code__.co_freevars,
                               self.capture.describe.__closure__))['_fingerprint'].cell_contents
        repeated = ['unicode · 颜色', (True, None, -0.0)]
        cyclic = []; cyclic.append(cyclic)
        mapping = {}; mapping['cycle'] = mapping
        mutual = []; mutual.append((mutual,))
        cases = ((), (1,), [], {}, None, 'quotes \' and "', float('inf'),
                 (repeated, repeated), {'second': [1, 2], 'first': (3,)},
                 cyclic, mapping, mutual)
        for value in cases:
            with self.subTest(value=repr(value)):
                self.assertEqual(fingerprint(value), hashlib.sha256(repr(value).encode()).hexdigest())
        _scene, _tree, _source, target, context = self.compositor_target()
        graph = dict(zip(self.capture.describe.__code__.co_freevars,
                         self.capture.describe.__closure__))['_graph'].cell_contents
        value, names = graph(target)
        self.assertFalse(names)
        self.assertEqual(fingerprint(value), hashlib.sha256(repr(value).encode()).hexdigest())
        for _ in range(sys.getrecursionlimit() + 50):value = (value,)
        self.assertEqual(len(fingerprint(value)), 64)

    def test_deep_native_graph_describes_hashes_and_prepares_without_recursion(self):
        nodes, sampling = component('graph.nodes'), component('scopes.sampling')
        _scene, tree, source, output, context = self.compositor_target()
        previous = source.outputs[0]
        # Keep native topology construction small; lower Python's limit only
        # while walking a chain that is longer than that limit.
        for _ in range(256):
            reroute = tree.nodes.new('NodeReroute')
            tree.links.new(previous, reroute.inputs[0])
            previous = reroute.outputs[0]
        target = nodes.create_grade(tree)
        tree.links.new(previous, target.inputs['Color'])
        tree.links.new(target.outputs['Color'], output.inputs['Color'])
        location = self.contexts.describe(target, context=context)
        prepare = dict(zip(self.capture.start_bake.__code__.co_freevars,
                           self.capture.start_bake.__closure__))['_prepare_bake_input'].cell_contents
        upstream = dict(zip(prepare.__code__.co_freevars, prepare.__closure__))['_upstream_grades'].cell_contents
        previous_links = bpy.types.NodeSocket.links
        reads = []

        def links(socket):
            reads.append(socket.as_pointer())
            return previous_links.__get__(socket, bpy.types.NodeSocket)

        previous_limit = sys.getrecursionlimit()
        try:
            sys.setrecursionlimit(200)
            with patch.object(bpy.types.NodeSocket, 'links', new=property(links)):
                first = sampling.describe(target, nodes.working_space(), capture_context=location)
                self.assertEqual(first['_dependencies'], {})
                before_native=len(reads)
                self.assertEqual(upstream(target, location), ())
                self.assertEqual(len(reads),before_native,'Native dependency traversal rescanned a tree per socket')
                source.outputs[0].default_value = (.7, .1, .3, .75)
                changed = sampling.describe(target, nodes.working_space(), capture_context=location)
        finally:
            sys.setrecursionlimit(previous_limit)
        self.assertNotEqual(first['key'], changed['key'])
        self.assertLessEqual(len(reads),2,'Simple route repeatedly rescanned the native tree')

    def test_collect_retired_is_cleanup_only_and_waits_for_physical_exit(self):
        token, state, handle = self.start_bake()
        directory = state['directory']
        self.capture.release_bake(token)
        specs = len(self.runtime.specs)
        with patch.object(self.scheduler, 'wake', side_effect=AssertionError('Cleanup scheduled work')):
            self.capture.collect_retired()
            self.assertTrue(directory.exists())
            handle.finish()
            self.capture.collect_retired()
        self.assertFalse(directory.exists())
        self.assertEqual(len(self.runtime.specs), specs)

    def test_failed_bake_keeps_diagnostic_until_release(self):
        token, state, handle = self.start_bake()
        directory, owner = state['directory'], state['node']
        handle.finish(error=RuntimeError('Native helper failed'))
        for _ in range(2):
            with self.assertRaisesRegex(ValueError, '^Native helper failed$'):
                self.capture.bake_status(token)
        self.assertFalse(directory.exists())
        self.assertIsNone(component('ownership').resolve(owner))
        self.assertIsNone(self.capture.poll())
        self.assertTrue(self.capture.release_bake(token))

    def test_cancelled_bake_keeps_status_and_files_until_their_separate_releases(self):
        token, state, handle = self.start_bake()
        directory, owner = state['directory'], state['node']
        self.assertTrue(self.capture.cancel_bake(token))
        self.assertTrue(handle.cancel_requested)
        self.assertIsNone(component('ownership').resolve(owner))
        for _ in range(2):
            with self.assertRaisesRegex(ValueError, '^Compositor bake cancelled$'):
                self.capture.bake_status(token)
            self.assertTrue(directory.exists())
        self.runtime.closed = True
        self.capture.poll()
        self.assertTrue(directory.exists(), 'Failed helper shutdown must preserve its inputs')
        handle.finish(error=RuntimeError('Late helper receipt'))
        with self.assertRaisesRegex(ValueError, '^Compositor bake cancelled$'):
            self.capture.bake_status(token)
        self.assertFalse(directory.exists())
        self.assertIsNone(self.capture.poll())
        self.assertTrue(self.capture.release_bake(token))

    def test_release_running_bake_retires_files_without_retaining_public_status(self):
        token, state, handle = self.start_bake()
        directory, owner = state['directory'], state['node']
        self.assertTrue(self.capture.release_bake(token))
        self.assertTrue(handle.cancel_requested)
        self.assertIsNone(component('ownership').resolve(owner))
        self.assertIn(state, self.capture.bake_retiring)
        with self.assertRaisesRegex(KeyError, 'Unknown compositor bake'):
            self.capture.bake_status(token)
        self.capture.poll()
        self.assertTrue(directory.exists())
        handle.finish()
        self.assertIsNone(self.capture.poll())
        self.assertFalse(directory.exists())
        self.assertNotIn(state, self.capture.bake_retiring)

    def test_release_after_retirement_before_poll_releases_node_ownership(self):
        token, state, handle = self.start_bake()
        directory, owner = state['directory'], state['node']
        handle.finish(self.bake_artifact(state))
        self.assertTrue(self.capture.release_bake(token))
        self.assertIsNone(component('ownership').resolve(owner))
        self.assertFalse(directory.exists())
        self.assertIsNone(self.capture.poll())

    def test_repeated_cancel_and_release_after_retirement_are_idempotent(self):
        token, state, handle = self.start_bake()
        directory = state['directory']
        self.capture.cancel_bake(token)
        self.capture.cancel_bake(token)
        self.assertEqual(len(self.capture.bake_retiring), 1)
        handle.finish()
        self.capture.release_bake(token)
        self.assertIsNone(self.capture.poll())
        self.assertFalse(self.capture.bake_retiring)
        self.assertFalse(directory.exists())

    def test_closing_session_cancels_without_scheduling_new_work(self):
        for action in ('cancel', 'release', 'clear'):
            with self.subTest(action=action):
                token, state, handle = self.start_bake()
                directory = state['directory']
                self.session.closing = True
                try:
                    with patch.object(self.scheduler, 'wake', side_effect=AssertionError(
                            'Cleanup must not schedule new callbacks')):
                        if action == 'cancel':
                            self.capture.cancel_bake(token)
                            self.capture.release_bake(token)
                        elif action == 'release':
                            self.capture.release_bake(token)
                        else:
                            self.capture.clear()
                finally:
                    self.session.closing = False
                self.assertTrue(handle.cancel_requested)
                self.assertFalse(self.capture.bakes)
                self.assertTrue(directory.exists())
                handle.finish()
                self.capture.poll()
                self.assertFalse(directory.exists())

    def test_clear_fences_bake_without_deleting_live_helper_inputs(self):
        token, state, handle = self.start_bake()
        directory, owner = state['directory'], state['node']
        self.capture.clear()
        self.assertFalse(self.capture.bakes)
        self.assertTrue(handle.cancel_requested)
        self.assertIsNone(component('ownership').resolve(owner))
        self.capture.poll()
        self.assertTrue(directory.exists())
        handle.finish()
        self.capture.poll()
        self.assertFalse(directory.exists())
        self.assertFalse(self.capture.bake_retiring)

    def test_registered_bake_retirement_survives_clear_and_failed_cleanup_receipt(self):
        token, state, handle = self.start_bake()
        calls = []

        def retired():
            calls.append(handle.retired())
            if len(calls) == 1:
                raise RuntimeError('cleanup receipt unavailable')

        self.capture.on_bake_retired(token, retired)
        self.capture.clear()
        self.assertFalse(calls)
        self.assertFalse(self.capture.bakes)
        self.assertIn(state, self.capture.bake_retiring)
        self.assertFalse(self.capture.collect_retired())
        handle.finish()
        with self.assertRaisesRegex(RuntimeError, 'cleanup receipt unavailable'):
            self.capture.collect_retired()
        self.assertIn(state, self.capture.bake_retiring)
        self.assertIn('on_retired', state)
        self.assertTrue(self.capture.collect_retired())
        self.assertEqual(calls, [True, True])
        self.assertFalse(self.capture.bake_retiring)
        self.assertNotIn('on_retired', state)

    def test_invalid_bake_receipts_preserve_errors_and_clean_artifacts(self):
        for changes, diagnostic in (({'identity': ('foreign',)}, 'foreign source revision'),
                                    ({'path': 'relative.exr'}, 'invalid artifact'),
                                    ({'sha256': 'wrong'}, 'changed after capture')):
            with self.subTest(diagnostic=diagnostic):
                token, state, handle = self.start_bake()
                directory, owner = state['directory'], state['node']
                handle.finish(self.bake_artifact(state, **changes))
                for _ in range(2):
                    with self.assertRaisesRegex(ValueError, diagnostic):
                        self.capture.bake_status(token)
                self.assertFalse(directory.exists())
                self.assertIsNone(component('ownership').resolve(owner))
                self.capture.release_bake(token)

    def test_edit_burst_keeps_active_capture_and_only_latest_successor(self):
        scene,tree,source,output,context=self.compositor_target()
        grade=component('graph.nodes').create_grade(tree)
        native=tree.nodes.new('CompositorNodeExposure')
        tree.links.new(source.outputs[0],native.inputs['Image'])
        tree.links.new(native.outputs['Image'],grade.inputs['Color'])
        automatic=component('scopes.automatic')
        self.assertTrue(automatic.observe(grade,context))
        first=self.runtime.handles[0]
        for exposure in (.2,.4,.6):
            native.inputs['Exposure'].default_value=exposure
            automatic.observe(grade,context)
        self.assertEqual(len(self.runtime.specs),1)
        self.assertFalse(first.cancel_requested)
        first.finish();self.capture.poll()
        self.assertEqual(self.capture.status(grade)['state'],'captured')
        self.assertEqual(automatic.status(grade),'updating')
        self.assertTrue(automatic.observe(grade,context))
        self.assertEqual(len(self.runtime.specs),2)
        newest=self.capture.describe(grade,context=context)
        self.assertEqual(self.runtime.specs[1].inputs['identity'],newest['identity'])
        sampling=component('scopes.sampling');nodes=component('graph.nodes')
        cached=sampling.describe_linear(grade,nodes.grading_space(grade),capture_context=context)
        with patch.object(self.scheduler,'dragging',return_value=True):
            nodes.write_values(grade,{'exposure':.25})
            automatic.observe(grade,context)
            latest=sampling.describe_linear(grade,nodes.grading_space(grade),capture_context=context)
            self.assertNotEqual(latest['key'],cached['key'])
            self.assertEqual(len(self.runtime.specs),2)
            self.assertFalse(self.runtime.handles[1].cancel_requested)
            self.runtime.handles[1].finish();self.capture.poll()
            self.assertEqual(self.capture.accepted_descriptor(grade)['identity'],newest['identity'])
        self.assertEqual(automatic.status(grade),'ready')

    def test_automatic_playback_fences_late_capture_and_acquires_stopped_frame(self):
        scene,tree,source,output,context=self.compositor_target()
        grade=component('graph.nodes').create_grade(tree)
        native=tree.nodes.new('CompositorNodeExposure')
        tree.links.new(source.outputs[0],native.inputs['Image'])
        tree.links.new(native.outputs['Image'],grade.inputs['Color'])
        automatic=component('scopes.automatic')
        self.assertTrue(automatic.observe(grade,context))
        old=self.runtime.handles[0]
        pre=next(callback for name,callback in self.session.handlers if name=='animation_playback_pre' and callback.__name__=='playback_pre')
        post=next(callback for name,callback in self.session.handlers if name=='animation_playback_post' and callback.__name__=='playback_post')
        pre(scene)
        automatic.sync()
        self.assertTrue(old.cancel_requested)
        for frame in (3,7,9):
            scene.frame_set(frame);automatic.observe(grade,context)
        old.finish();self.capture.poll()
        self.assertIsNone(self.capture.accepted_descriptor(grade))
        self.assertEqual(len(self.runtime.specs),1)
        post(scene)
        with patch.object(self.guard,'available',return_value=False):
            automatic.observe(grade,context)
        self.assertEqual(len(self.runtime.specs),1)
        self.assertTrue(automatic.observe(grade,context))
        self.assertEqual(self.runtime.specs[-1].inputs['view']['frame'],9)
        self.runtime.handles[-1].finish();self.capture.poll()
        self.assertTrue(automatic.analysis_allowed(grade,context))
        self.assertEqual(automatic.status(grade),'ready')

    def test_scene_dependency_ignores_selection_and_display_but_tracks_geometry(self):
        scene,tree,source,output,context=self.compositor_target()
        native=tree.nodes.new('CompositorNodeRLayers')
        tree.links.new(native.outputs['Image'],output.inputs['Color'])
        mesh=bpy.data.meshes.new('Scope semantic mesh')
        mesh.from_pydata([(0.,0.,0.),(1.,0.,0.),(0.,1.,0.)],[],[(0,1,2)])
        obj=bpy.data.objects.new('Scope semantic object',mesh);scene.collection.objects.link(obj)
        baseline=self.descriptor(output,context)
        obj.show_name=True;obj.show_wire=True;obj.display_type='WIRE';obj.hide_select=True
        mesh.vertices[0].select=True;mesh.polygons[0].select=True
        update=SimpleNamespace(id=mesh,is_updated_geometry=True,is_updated_transform=False)
        self.capture.invalidate(depsgraph=SimpleNamespace(updates=(update,)))
        self.assertEqual(self.descriptor(output,context)['identity'],baseline['identity'])
        mesh.vertices[0].co.x=.25
        self.capture.invalidate(depsgraph=SimpleNamespace(updates=(update,)))
        self.assertNotEqual(self.descriptor(output,context)['identity'],baseline['identity'])

    def test_image_rename_rebases_companion_without_acquiring_a_new_source(self):
        _scene,tree,source,output,context=self.compositor_target()
        image=bpy.data.images.new('Scope source before rename',width=2,height=2,float_buffer=True)
        image.pixels.foreach_set(np.full(16,.25,dtype=np.float32));image.update()
        image_node=tree.nodes.new('CompositorNodeImage');image_node.image=image
        tree.links.new(image_node.outputs['Image'],output.inputs['Color'])
        frozen=self.contexts.source_context(output,context)
        descriptor=self.capture.describe_source(output,context=frozen)
        image.name='Scope source after rename'
        self.capture.invalidate(depsgraph=SimpleNamespace(updates=(SimpleNamespace(id=image),)))
        current=self.capture.describe_source(output,context=frozen)
        self.assertEqual(current['identity'],descriptor['identity'])
        self.assertTrue(self.capture.acquire(output,(('Color',descriptor,(16,8),False),)))
        self.assertEqual(self.runtime.specs[-1].inputs['_image_source']['name'],image.name)

    def test_snapshot_rebases_renamed_nodes_without_changing_semantic_source(self):
        _scene,tree,source,output,context=self.compositor_target()
        nodes=component('graph.nodes')
        grade=nodes.create_grade(tree)
        tree.links.new(source.outputs[0],grade.inputs['Color'])
        tree.links.new(grade.outputs['Color'],output.inputs['Color'])
        frozen=self.contexts.source_context(output,context)
        descriptor=self.capture.describe(output,context=frozen)
        grade.name='Renamed upstream Grade'
        self.assertEqual(self.capture.describe(output,context=frozen)['identity'],descriptor['identity'],'grade rename')
        source.name='Renamed source'
        self.assertEqual(self.capture.describe(output,context=frozen)['identity'],descriptor['identity'],'source rename')
        output.name='Renamed target'
        self.assertEqual(self.capture.describe(output,context=frozen)['identity'],descriptor['identity'],'target rename')
        source.label='Only an editor label';source.location=(77,88);source.select=True
        appearance=self.capture.describe(output,context=frozen)
        self.assertEqual(appearance['identity'],descriptor['identity'],'editor-only node appearance')
        disconnected=tree.nodes.new('CompositorNodeExposure')
        disconnected.inputs['Exposure'].default_value=3.
        current=self.capture.describe(output,context=frozen)
        self.assertEqual(current['identity'],descriptor['identity'])
        self.assertTrue(self.capture.acquire(output,(('Color',descriptor,(16,8),False),)))
        self.assertEqual(self.runtime.specs[-1].inputs['_pg_models'][0]['node_name'],grade.name)
        self.assertEqual(self.runtime.specs[-1].inputs['node_name'],output.name)

    def test_scene_rename_rebases_snapshot_root_without_changing_source(self):
        scene,tree,source,output,context=self.compositor_target()
        frozen=self.contexts.source_context(output,context)
        descriptor=self.capture.describe(output,context=frozen)
        scene.name='Renamed scope scene'
        self.assertEqual(self.capture.describe(output,context=frozen)['identity'],descriptor['identity'])
        self.assertTrue(self.capture.acquire(output,(('Color',descriptor,(16,8),False),)))
        self.assertEqual(self.runtime.specs[-1].inputs['scene'],scene.name)

    def test_reachable_group_socket_ignores_unused_inputs_and_rebases_model_path(self):
        _scene,tree,source,output,context=self.compositor_target()
        group=bpy.data.node_groups.new('Scope dependency group','CompositorNodeTree')
        for name in ('Used','Unused'):
            group.interface.new_socket(name=name,in_out='INPUT',socket_type='NodeSocketColor')
        group.interface.new_socket(name='Color',in_out='OUTPUT',socket_type='NodeSocketColor')
        incoming=group.nodes.new('NodeGroupInput');endpoint=group.nodes.new('NodeGroupOutput')
        upstream=component('graph.nodes').create_grade(group)
        group.links.new(incoming.outputs['Used'],upstream.inputs['Color'])
        group.links.new(upstream.outputs['Color'],endpoint.inputs['Color'])
        instance=tree.nodes.new('CompositorNodeGroup');instance.node_tree=group
        tree.links.new(source.outputs[0],instance.inputs['Used'])
        tree.links.new(instance.outputs['Color'],output.inputs['Color'])
        frozen=self.contexts.source_context(output,context)
        descriptor=self.capture.describe(output,context=frozen)
        instance.inputs['Unused'].default_value=(.7,.8,.9,1.)
        disconnected=group.nodes.new('CompositorNodeExposure')
        disconnected.inputs['Exposure'].default_value=5.
        instance.name='Renamed group occurrence';upstream.name='Renamed contained Grade'
        current=self.capture.describe(output,context=frozen)
        self.assertEqual(current['identity'],descriptor['identity'])
        self.assertTrue(self.capture.acquire(output,(('Color',descriptor,(16,8),False),)))
        record=self.runtime.specs[-1].inputs['_pg_models'][0]
        self.assertEqual(record['group_path'],(instance.name,))
        self.assertEqual(record['node_name'],upstream.name)
        source.outputs[0].default_value=(.9,.1,.2,1.)
        self.assertNotEqual(self.capture.describe(output,context=frozen)['identity'],descriptor['identity'])

    def test_replaced_source_cannot_retire_its_input_before_the_helper(self):
        scene, tree, source, output, context = self.compositor_target()
        first = self.descriptor(output, context)
        old = self.request(output, first)
        old['due'] = 0
        self.capture.poll()
        old_handle = self.runtime.handles[0]
        old_directory = old['directory']

        source.outputs[0].default_value = (.7, .5, .2, 1.)
        latest = self.descriptor(output, context)
        current = self.request(output, latest)
        self.assertTrue(old_handle.cancel_requested)
        self.assertTrue(old_directory.exists())
        self.assertIn(old, self.capture.retiring)
        current['due'] = 0
        self.capture.poll()
        self.assertEqual(len(self.runtime.specs), 2)

        old_handle.finish()
        self.capture.poll()
        self.assertFalse(old_directory.exists())
        self.assertIsNone(current['result'], 'Retired old result replaced the current request')
        self.runtime.handles[1].finish()
        self.capture.poll()
        rgba, identity, _label = self.capture.sample(output, 'Color', (16, 8), descriptor=latest)
        self.assertEqual(identity, latest['identity'])
        self.assertIsNotNone(rgba)

    def test_exact_consumers_have_separate_capture_authority_and_shared_source_version(self):
        _scene,_tree,_source,output,context=self.compositor_target()
        first=self.descriptor(output,context)
        first=dict(first,consumer=('editor',1))
        first['identity']=('native-scope-v1',first['consumer'],first['version'],'Color')
        first['_source_context']=dict(first['_source_context'],consumer=first['consumer'])
        second=dict(first,consumer=('editor',2))
        second['_source_context']=dict(second['_source_context'],consumer=second['consumer'])
        second['identity']=('native-scope-v1',second['consumer'],second['version'],'Color')
        self.assertEqual(first['version'],second['version'])
        self.assertNotEqual(first['identity'],second['identity'])
        self.request(output,first)
        second_state=self.request(output,second)
        self.assertEqual(len(self.capture.states),2)
        self.assertNotEqual(next(iter(self.capture.states))[0],list(self.capture.states)[1][0])
        self.assertIsNotNone(second_state['handle'])

    def test_immediate_capture_keeps_its_frozen_source_when_live_values_change(self):
        _scene,_tree,source,output,context=self.compositor_target()
        first=self.descriptor(output,context);state=self.request(output,first)
        source.outputs[0].default_value=(.8,.5,.2,1.)
        latest=self.descriptor(output,context)
        self.assertNotEqual(first['identity'],latest['identity'])
        self.assertEqual(self.runtime.specs[0].inputs['identity'],first['identity'])
        self.assertEqual(state['request']['identity'],first['identity'])
        self.runtime.handles[0].finish();self.capture.poll()
        self.assertEqual(self.capture.accepted_descriptor(output,context=first)['identity'],first['identity'])

    def test_unloaded_file_is_owned_while_dirty_file_keeps_edited_pixels(self):
        scene,tree,source,output,context=self.compositor_target()
        path=Path(self._temp.name)/'input.tga'
        image=bpy.data.images.new('Scope file seed',width=2,height=2,alpha=True,float_buffer=True)
        image.pixels.foreach_set(np.tile(np.asarray((.2,.4,.8,1.),dtype=np.float32),4))
        image.filepath_raw=str(path);image.file_format='TARGA';image.save()
        bpy.data.images.remove(image)
        image=bpy.data.images.load(str(path),check_existing=False)
        node=tree.nodes.new('CompositorNodeImage');node.image=image
        tree.links.new(node.outputs['Image'],output.inputs['Color'])
        image.buffers_free()
        self.assertFalse(image.has_data)
        descriptor=self.descriptor(output,context)
        state=self.request(output,descriptor);state['due']=0;self.capture.poll()
        records=self.runtime.specs[-1].inputs['images']
        record=next(record for record in records if record['name']==image.name)
        self.assertEqual(record['source'],'file')
        self.assertEqual(Path(record['path']).read_bytes(),path.read_bytes())
        self.assertNotEqual(Path(record['path']),path)
        self.runtime.handles[-1].finish();self.capture.poll()

        image.reload()
        image.pixels.foreach_set(np.tile(np.asarray((.7,.3,.1,1.),dtype=np.float32),4));image.update()
        self.capture.invalidate()
        latest=self.descriptor(output,context)
        self.assertNotEqual(descriptor['identity'],latest['identity'])
        state=self.request(output,latest);state['due']=0;self.capture.poll()
        record=next(record for record in self.runtime.specs[-1].inputs['images'] if record['name']==image.name)
        self.assertEqual(record['source'],'buffer',repr(state))
        np.testing.assert_allclose(np.load(record['path'],allow_pickle=False)[0,0],
                                   np.asarray(image.pixels[:4]),rtol=0,atol=0)

    def test_generated_pixel_edit_invalidates_without_depsgraph_image_update(self):
        scene,tree,source,output,context=self.compositor_target()
        image=bpy.data.images.new('Scope volatile image',width=2,height=2,alpha=True,float_buffer=True)
        node=tree.nodes.new('CompositorNodeImage');node.image=image
        tree.links.new(node.outputs['Image'],output.inputs['Color'])
        image.pixels.foreach_set(np.tile(np.asarray((.1,.2,.3,1.),dtype=np.float32),4));image.update()
        before=self.descriptor(output,context)
        image.pixels.foreach_set(np.tile(np.asarray((.8,.6,.4,1.),dtype=np.float32),4));image.update()
        self.capture.invalidate()
        after=self.descriptor(output,context)
        self.assertNotEqual(before['identity'],after['identity'])

    def test_snapshot_reprobes_silent_volatile_edit_inside_probe_interval(self):
        _scene,tree,_source,output,context=self.compositor_target()
        image=bpy.data.images.new('Silent volatile image',width=2,height=2,alpha=True,float_buffer=True)
        node=tree.nodes.new('CompositorNodeImage');node.image=image
        tree.links.new(node.outputs['Image'],output.inputs['Color'])
        image.pixels.foreach_set(np.tile(np.asarray((.1,.2,.3,1.),dtype=np.float32),4));image.update()
        first=self.descriptor(output,context)
        image.pixels.foreach_set(np.tile(np.asarray((.8,.6,.4,1.),dtype=np.float32),4));image.update()
        with self.assertRaisesRegex(ValueError,'changed before the snapshot'):
            self.request(output,first)
        self.assertFalse(self.runtime.specs)
        state=self.request(output,self.descriptor(output,context))
        self.assertEqual(len(self.runtime.specs),1,repr(state))
        record=next(item for item in self.runtime.specs[0].inputs['images'] if item['name']==image.name)
        np.testing.assert_array_equal(np.load(record['path'],allow_pickle=False)[0,0],np.asarray(image.pixels[:4],dtype=np.float32))

    def test_edited_complex_image_buffers_reject_before_flat_read_or_helper_submit(self):
        _scene,tree,_source,target,context=self.compositor_target()
        image=bpy.data.images.new('Edited complex source',width=2,height=2,alpha=True,float_buffer=True)
        image_node=tree.nodes.new('CompositorNodeImage');image_node.image=image
        tree.links.new(image_node.outputs['Image'],target.inputs['Color'])
        def closure(function,name):
            return dict(zip(function.__code__.co_freevars,function.__closure__))[name]
        image_state=closure(self.capture.describe,'_image_state').cell_contents
        bpy_cell=closure(image_state,'bpy');native_bpy=bpy_cell.cell_contents
        reads=[]
        class UnsupportedImage:
            is_dirty=True
            @property
            def size(self):reads.append('size');raise AssertionError('Unsafe flat size getter')
            @property
            def pixels(self):reads.append('pixels');raise AssertionError('Unsafe flat pixel getter')
        class Proxy:
            def __init__(self,base,**values):self.base=base;self.values=values
            def __getattr__(self,name):return self.values[name] if name in self.values else getattr(self.base,name)
        for source,multiview,image_type,dirty in (('TILED',False,'IMAGE',True),('GENERATED',True,'IMAGE',False),('FILE',False,'MULTILAYER',True)):
            with self.subTest(source=source,multiview=multiview,image_type=image_type):
                descriptor=self.descriptor(target,context)
                unsupported=UnsupportedImage();unsupported.source=source
                unsupported.use_multiview=multiview;unsupported.type=image_type;unsupported.is_dirty=dirty
                images=Proxy(native_bpy.data.images,get=lambda name:unsupported if name==image.name else native_bpy.data.images.get(name))
                bpy_cell.cell_contents=Proxy(native_bpy,data=Proxy(native_bpy.data,images=images))
                try:
                    with self.assertRaisesRegex(ValueError,'cannot snapshot edited'):self.request(target,descriptor)
                finally:bpy_cell.cell_contents=native_bpy
                self.assertFalse(self.runtime.specs);self.assertFalse(reads)
                self.assertFalse(tuple(self.runtime.session.path.glob('capture-*')))
                self.capture.clear_scopes()

    def test_external_render_scene_edits_change_explicit_source_immediately(self):
        scene,tree,source,output,context=self.compositor_target()
        external=bpy.data.scenes.new('Scope external render scene')
        external.world=bpy.data.worlds.new('Scope external world')
        external.world.use_nodes=True
        render=tree.nodes.new('CompositorNodeRLayers');render.scene=external
        tree.links.new(render.outputs['Image'],output.inputs['Color'])
        before=self.descriptor(output,context)
        external.world.node_tree.nodes['Background'].inputs['Color'].default_value=(.6,.2,.1,1.)
        pending=self.descriptor(output,context)
        self.assertFalse(pending['scene_pending'])
        self.assertNotEqual(before['identity'],pending['identity'])
        after=self.descriptor(output,context)
        self.assertNotEqual(before['identity'],after['identity'])

    def test_shader_selected_terminal_edits_preserve_native_input_identity(self):
        scene=bpy.context.scene
        camera=bpy.data.objects.new('Debounce camera',bpy.data.cameras.new('Debounce camera'))
        scene.collection.objects.link(camera);scene.camera=camera
        material=bpy.data.materials.new('Debounce material');material.use_nodes=True
        root=material.node_tree;root.nodes.clear()
        group=bpy.data.node_groups.new('Debounce output kernel','ShaderNodeTree')
        group.interface.new_socket(name='Color',in_out='INPUT',socket_type='NodeSocketColor')
        group.interface.new_socket(name='Color',in_out='OUTPUT',socket_type='NodeSocketColor')
        output_color=group.nodes.new('ShaderNodeRGB');endpoint=group.nodes.new('NodeGroupOutput')
        group.links.new(output_color.outputs[0],endpoint.inputs['Color'])
        target=root.nodes.new('ShaderNodeGroup');target.node_tree=group
        target.inputs['Color'].default_value=(.1,.2,.3,1.)
        emission=root.nodes.new('ShaderNodeEmission');endpoint=root.nodes.new('ShaderNodeOutputMaterial')
        root.links.new(target.outputs['Color'],emission.inputs['Color']);root.links.new(emission.outputs[0],endpoint.inputs['Surface'])
        mesh=bpy.data.meshes.new('Debounce mesh');mesh.materials.append(material)
        obj=bpy.data.objects.new('Debounce object',mesh);scene.collection.objects.link(obj)
        context=SimpleNamespace(scene=scene,view_layer=scene.view_layers[0],object=obj,
            space_data=None,window=None,area=None,region=None)
        before=self.descriptor(target,context)
        with patch.object(self.scheduler,'dragging',new=lambda _node:True):
            output_color.outputs[0].default_value=(.8,.5,.2,1.)
            pending=self.descriptor(target,context)
            self.assertFalse(pending['scene_pending'])
            self.assertEqual(before['identity'],pending['identity'])
            time.sleep(.31)
            held=self.descriptor(target,context)
            self.assertEqual(before['identity'],held['identity'])
        after=self.descriptor(target,context)
        self.assertFalse(after['scene_pending'])
        self.assertEqual(before['identity'],after['identity'])
        lighting=root.nodes.new('ShaderNodeShaderToRGB')
        root.links.new(lighting.outputs['Color'],target.inputs['Color'])
        feedback=self.descriptor(target,context)
        output_color.outputs[0].default_value=(.3,.2,.1,1.)
        self.assertNotEqual(feedback['identity'],self.descriptor(target,context)['identity'],
                            'Lighting feedback must retain selected terminal scene dependencies')

    def test_generic_nested_group_parent_and_color_ramp_edits_invalidate(self):
        scene = bpy.context.scene
        camera = bpy.data.objects.new('Fingerprint camera', bpy.data.cameras.new('Fingerprint camera'))
        scene.collection.objects.link(camera)
        scene.camera = camera
        material = bpy.data.materials.new('Scope nested fingerprint')
        material.use_nodes = True
        root = material.node_tree
        root.nodes.clear()
        parent_tree = bpy.data.node_groups.new('Scope parent group', 'ShaderNodeTree')
        parent_tree.interface.new_socket(name='Color', in_out='INPUT', socket_type='NodeSocketColor')
        parent_tree.interface.new_socket(name='Color', in_out='OUTPUT', socket_type='NodeSocketColor')
        parent_input = parent_tree.nodes.new('NodeGroupInput')
        parent_output = parent_tree.nodes.new('NodeGroupOutput')

        inner_tree = bpy.data.node_groups.new('Scope inner group', 'ShaderNodeTree')
        inner_tree.interface.new_socket(name='Color', in_out='INPUT', socket_type='NodeSocketColor')
        inner_tree.interface.new_socket(name='Color', in_out='OUTPUT', socket_type='NodeSocketColor')
        inner_input = inner_tree.nodes.new('NodeGroupInput')
        target = inner_tree.nodes.new('ShaderNodeEmission')
        inner_output = inner_tree.nodes.new('NodeGroupOutput')
        inner_tree.links.new(inner_input.outputs['Color'], target.inputs['Color'])
        inner_tree.links.new(inner_input.outputs['Color'], inner_output.inputs['Color'])

        inner_instance = parent_tree.nodes.new('ShaderNodeGroup')
        inner_instance.node_tree = inner_tree
        parent_tree.links.new(parent_input.outputs['Color'], inner_instance.inputs['Color'])
        parent_tree.links.new(inner_instance.outputs['Color'], parent_output.inputs['Color'])
        parent_instance = root.nodes.new('ShaderNodeGroup')
        parent_instance.node_tree = parent_tree
        ramp = root.nodes.new('ShaderNodeValToRGB')
        ramp.color_ramp.elements[0].position = .2
        ramp.color_ramp.elements[1].position = .8

        mesh = bpy.data.meshes.new('Scope fingerprint mesh')
        obj = bpy.data.objects.new('Scope fingerprint object', mesh)
        scene.collection.objects.link(obj)
        mesh.materials.append(material)
        context = SimpleNamespace(scene=scene, view_layer=scene.view_layers[0], object=obj,
            space_data=None, window=None, area=None, region=None)
        first = self.descriptor(target, context)
        parent_instance.inputs['Color'].default_value = (.1, .3, .5, 1.)
        parent_changed = self.descriptor(target, context)
        self.assertNotEqual(first['identity'], parent_changed['identity'])

        root.links.new(ramp.outputs['Color'], parent_instance.inputs['Color'])
        baseline = self.descriptor(target, context)
        ramp.color_ramp.elements[1].position = .83
        ramp_changed = self.descriptor(target, context)
        self.assertNotEqual(baseline['identity'], ramp_changed['identity'])
