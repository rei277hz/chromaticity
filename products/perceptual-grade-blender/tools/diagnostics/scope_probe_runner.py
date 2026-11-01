"""Measure installed native scopes without saving the supplied project.

The diagnostic observes scalar capture/execution timings. GUI measurements use
normal registered timers and the production draw callbacks; headless probes
pump the same production callbacks explicitly and report current-state timing.
"""
from contextlib import nullcontext
import hashlib
import importlib
import importlib.util
import json
from pathlib import Path
import sys
import time
import traceback

import addon_utils
import bpy
import numpy as np

_SUMMARY_PATH = Path(__file__).with_name('scope_probe_report.py')
_SUMMARY_SPEC = importlib.util.spec_from_file_location('_pg_scope_probe_report', _SUMMARY_PATH)
_SUMMARY_MODULE = importlib.util.module_from_spec(_SUMMARY_SPEC)
_SUMMARY_SPEC.loader.exec_module(_SUMMARY_MODULE)
summarize = _SUMMARY_MODULE.summarize


def digest(value):
    return hashlib.sha256(repr(value).encode('utf8')).hexdigest()


class ExecutionTrace:
    """Observe dispatch/receipt without retaining messages, handles, or RNA."""
    def __init__(self, name, events):
        self.events = events
        self.hooks = []
        runtime_type = importlib.import_module(name + '.blender_runtime.execution.runtime').ExecutionRuntime
        for method, event in (('_send', 'execution_send'), ('_message', 'execution_message')):
            original = getattr(runtime_type, method)
            def measured(runtime, helper, message, original=original, event=event):
                job = helper.active
                values = dict(event=event, at=time.perf_counter(), role=str(helper.role),
                              generation=int(helper.generation), message=str(message.get('kind', '')),
                              ready=bool(helper.ready))
                if job is not None:
                    values.update(operation=str(job.spec.operation), attempt=int(job.state.identity),
                                  order=int(job.order))
                began = time.perf_counter()
                try:
                    return original(runtime, helper, message)
                finally:
                    values['seconds'] = time.perf_counter() - began
                    self.events.append(values)
            self.hooks.append((runtime_type, method, original, measured))
            setattr(runtime_type, method, measured)

    def close(self):
        for owner, method, original, measured in reversed(self.hooks):
            if getattr(owner, method) is measured:
                setattr(owner, method, original)
        self.hooks.clear()


class DrawTrace:
    """Match the sample consumed by a completed native board draw to its key."""
    def __init__(self, application, module, events):
        self.events, self.hooks, self.active = events, [], None
        jobs = application.component('scopes.jobs')
        sampling = application.component('scopes.sampling')
        for method, kind in (('get_linear', 'linear'), ('get_tone', 'full'), ('get', 'full')):
            owner = application.component('scopes.sampling')
            original = getattr(owner, method)
            def sampled(node, *args, original=original, kind=kind, **kwargs):
                result = original(node, *args, **kwargs)
                if self.active is not None and result is not None:
                    base = result.get('_base', result)
                    states = jobs._linear_states if kind == 'linear' else jobs._states
                    state = states.get(node.as_pointer()) or states.get(sampling.channel(node))
                    key = base.get('_scope_key')
                    if state is not None and key == state['spec']['key']:
                        self.active.append(dict(kind=kind, key=digest(key),
                            part=str(base.get('_scope_part', 'complete')),
                            node=str(node.name), request=str(base.get('_scope_request', ''))))
                return result
            self.patch(owner, method, sampled)
        for path in ('ui.diagram', 'ui.tone', 'ui.color'):
            owner = application.component(path)
            original = owner.draw_board
            def drawn(*args, original=original, **kwargs):
                previous = self.active
                records = self.active = []
                began = time.perf_counter()
                try:
                    result = original(*args, **kwargs)
                    ended = time.perf_counter()
                    seen = set()
                    for record in records:
                        key = tuple(record.items())
                        if key not in seen:
                            seen.add(key)
                            self.events.append(dict(event='scope_draw', at=ended,
                                seconds=ended-began, **record))
                    return result
                finally:
                    self.active = previous
            self.patch(owner, 'draw_board', drawn)

    def patch(self, owner, method, value):
        original = getattr(owner, method)
        self.hooks.append((owner, method, original, value))
        setattr(owner, method, value)

    def close(self):
        for owner, method, original, measured in reversed(self.hooks):
            if getattr(owner, method) is measured:
                setattr(owner, method, original)
        self.hooks.clear()


def main(repository, report_path, blend_path, node_name='Grade', options_json='{}'):
    repository, report_path, blend_path = map(Path, (repository, report_path, blend_path))
    options = dict(owner='compositor', material='', workspace='', gui=False, diagnostics=False,
                   page_order='forward',complex_native=False)
    options.update(json.loads(options_json))
    name = 'bl_ext.pg_scope_probe.perceptual_grade'
    started = time.perf_counter()
    report = dict(schema=2, passed=False, blender=list(bpy.app.version), node=node_name,
                  source_before=hashlib.sha256(blend_path.read_bytes()).hexdigest(), stages={},
                  options=options, events=[], execution_events=[], capture_events=[], draw_events=[],
                  clock_origin=started, measurement='gui_draw' if options['gui'] else 'headless_current')
    hooks = []
    application = capture = None
    enabled = False

    def phase(value, **fields):
        report.update(phase=value, **fields)
        event = dict(event=value, at=time.perf_counter(), **fields)
        report['events'].append(event)
        with report_path.with_suffix('.phases.jsonl').open('a', encoding='utf8') as stream:
            stream.write(json.dumps(event) + '\n')
        report_path.write_text(json.dumps(report, indent=2), encoding='utf8')
        print('PG_SCOPE_PROBE', value, json.dumps(fields), flush=True)

    def module(path):
        return importlib.import_module(name + '.perceptual_grade_blender.' + path)

    def workflow():
        nonlocal application, capture, enabled
        phase('enable.begin')
        bpy.context.preferences.extensions.repos.new(name='PG scope probe', module='pg_scope_probe',
            custom_directory=str(repository))
        addon = addon_utils.enable(name, default_set=False)
        assert addon is not None
        enabled = True
        phase('load.begin')
        bpy.ops.wm.open_mainfile(filepath=str(blend_path), use_scripts=False,
                                load_ui=bool(options['workspace'] or options['gui']))
        phase('load.complete')
        application = module('integration.lifecycle').registered_session()
        # No overlay request may start during the saved-workspace transition.
        # The initial measurement starts when measured() enables that overlay.
        bpy.context.window_manager.pg_diagram_enabled = False
        nodes, lut, sampling, jobs, capture = (application.component(component) for component in
            ('graph.nodes', 'graph.lut', 'scopes.sampling', 'scopes.jobs', 'scopes.capture'))
        images=application.component('scopes.images')
        if options['diagnostics']:
            capture.enable_diagnostics(True)
            images.enable_diagnostics(True)
            hooks.append(ExecutionTrace(name, report['execution_events']))
        scene = bpy.context.scene
        if options['owner'] == 'compositor':
            owner = scene
            tree = scene.compositing_node_group
            wanted = 'PGCompositorGrade'
        else:
            collection = bpy.data.materials if options['owner'] == 'material' else bpy.data.worlds
            candidates = [item for item in collection if item.node_tree and node_name in item.node_tree.nodes]
            owner = collection.get(options['material']) if options['material'] else candidates[0] if len(candidates) == 1 else None
            if owner is None:
                raise ValueError('Select an unambiguous shader owner with --material')
            tree = owner.node_tree
            wanted = 'PGShaderGrade'
        node = tree.nodes.get(node_name) if tree else None
        assert node is not None and node.bl_idname == wanted, 'Select a matching Grade node'
        original_links = tuple(sorted((link.from_node.name, link.from_socket.identifier,
                               link.to_node.name, link.to_socket.identifier) for link in tree.links))
        window = bpy.context.window
        if options['workspace']:
            if window is None:
                windows = tuple(bpy.context.window_manager.windows)
                window = windows[0] if windows else None
            workspace = next((item for item in bpy.data.workspaces
                              if item.name == options['workspace']), None)
            if window is None or workspace is None:
                raise ValueError('The requested saved workspace is unavailable: requested=' +
                    repr(options['workspace']) + ', window=' + repr(window is not None) +
                    ', workspaces=' + repr(tuple(item.name for item in bpy.data.workspaces)))
            window.workspace = workspace
            switched = time.perf_counter()
            while not any(area.type == 'NODE_EDITOR' and area.spaces.active.tree_type == tree.bl_idname
                          for area in window.screen.areas):
                if time.perf_counter()-switched > 10:
                    raise TimeoutError('The saved workspace did not activate its matching node editor')
                yield .05
            yield .1
        override = {}
        if window is not None:
            candidates = [area for area in window.screen.areas if area.type == 'NODE_EDITOR'
                          and area.spaces.active.tree_type == tree.bl_idname]
            if candidates:
                area = max(candidates, key=lambda item: item.width*item.height)
                region = next(item for item in area.regions if item.type == 'WINDOW')
                override = dict(window=window, area=area, region=region)
                tree.nodes.active = node
                for item in tree.nodes:
                    item.select = item == node
                if options['owner'] == 'material':
                    users = [obj for obj in scene.objects if any(slot.material == owner for slot in obj.material_slots)]
                    if users:
                        bpy.context.view_layer.objects.active = users[0]
                        users[0].select_set(True)
                area.tag_redraw()
        if options['gui'] and not override:
            raise ValueError('GUI scope timing requires a matching saved node editor: ' +
                repr(tuple((area.type, getattr(area.spaces.active,'tree_type',''))
                           for area in window.screen.areas) if window is not None else ()))
        context_scope = lambda: bpy.context.temp_override(**override) if override else nullcontext()
        if options['gui']:
            hooks.append(DrawTrace(application, module, report['draw_events']))
            bpy.context.window_manager.pg_diagram_enabled = False
        recovery_started = time.perf_counter()
        while nodes.recovery_pending():
            if time.perf_counter()-recovery_started > 120:
                raise TimeoutError('Native recovery did not finish')
            if not options['gui']:
                nodes.poll_working_space(); lut.tick()
            yield .01
        with context_scope():
            context = application.component('scopes.context').source_context(node)
        phase('capture.begin', upstream=node.inputs['Color'].links[0].from_node.bl_idname
              if node.inputs['Color'].is_linked else 'constant', context=context,
              recovery_seconds=time.perf_counter()-recovery_started,
              workspace=window.workspace.name if window is not None else '')

        def measured(label, kind, view=(), previous_key=None, expected_key=None, started_at=None):
            began = time.perf_counter() if started_at is None else started_at
            image_before=images.diagnostics()
            first_current = None
            draw_at = None
            event_start = len(report['draw_events'])
            with context_scope():
                if options['gui']:
                    wm = bpy.context.window_manager
                    wm.pg_stage = 'LINEAR' if kind == 'linear' else 'REMAP' if view == ('tone',) else 'CHROMATIC'
                    if wm.pg_stage == 'CHROMATIC':
                        node.pg_chromatic.family = 'J'; node.pg_chromatic.active_tone = 1
                    wm.pg_diagram_enabled = True
                    application.component('ui.panel').redraw(bpy.context)
            phase('stage.begin', stage=label)
            while time.perf_counter()-began < 180:
                with context_scope():
                    if not options['gui']:
                        nodes.poll_working_space(); lut.tick()
                    if options['gui']:
                        # Production draw callbacks own demand. Polling must
                        # not add another expensive source-description loop.
                        channel = sampling.channel(node)
                        value = application.component('graph.scheduler').scope_result(node, kind, channel=channel)
                        if kind != 'linear':
                            value = sampling.select_view(value, view)
                    else:
                        application.component('scopes.automatic').observe(node,bpy.context)
                        capture.poll()
                        try:
                            value = (jobs.request_linear(node, nodes.grading_space(node)) if kind == 'linear' else
                                     jobs.request(node, nodes.grading_space(node), view))
                        except lut.ScopePreparing:value=None
                        jobs.linear_tick() if kind == 'linear' else jobs.tick()
                    status = jobs.status(node, kind)
                    if status['state'] == 'error':raise RuntimeError(status['error'])
                if value is not None:
                    base = value.get('_base', value)
                    key = digest(base['_scope_key'])
                    candidates = [event for event in report['draw_events'][event_start:]
                                  if event['kind'] == kind and event['key'] == key and event['node'] == node_name]
                    if candidates:
                        draw_at = candidates[0]['at']
                    if (status['state'] == 'current' and key != previous_key
                            and (expected_key is None or key==expected_key)):
                        first_current = first_current or time.perf_counter()
                        if not options['gui'] or draw_at is not None:
                            info = dict(status=status, seconds=first_current-began, started_at=began,
                                current_at=first_current, scope_key=key,
                                scope_timings=dict(base.get('_scope_timings', {})))
                            image_after=images.diagnostics()
                            info['image_reads']={field:image_after[field]-image_before[field]
                                for field in ('reads','decodes','decode_seconds')}
                            if draw_at is not None:
                                info.update(first_draw_at=draw_at, first_draw_seconds=draw_at-began)
                            phase('stage.complete', stage=label, seconds=info['seconds'],
                                  first_draw_seconds=info.get('first_draw_seconds'))
                            return value, info
                yield .02
            raise TimeoutError('Scope did not become current and drawn: ' + label)

        results={}
        stages=[('linear','linear',()),('tone','full',('tone',)),('color','full',(1,False))]
        for label,kind,view in reversed(stages) if options['page_order']=='reverse' else stages:
            value,info=yield from measured(label,kind,view)
            results[label]=value;report['stages'][label]=info
        linear=results['linear'];tone=results['tone'];color=results['color']
        rgb = linear['source_rgb']
        assert np.isfinite(rgb).all() and rgb.ndim == 3 and rgb.shape[0] > 1
        assert float(rgb.std()) > 0, 'Project probe requires a nonuniform source image'
        report['stages']['linear'].update(shape=rgb.shape, minimum=float(rgb.min()), maximum=float(rgb.max()))
        assert tone['before']['count'] > 0 and tone['after']['count'] > 0
        assert color.get('_active_colors'), 'Color scope has no active measurement'
        assert not capture.states,'Automatic Image route admitted native capture'
        phase('stages.current')
        before_capture = tuple(state['result']['identity'] for state in capture.states.values()
                               if state.get('result') is not None)
        exposure = nodes.read_parameters(node).exposure
        before_matrix = nodes.grades.matrix(node)
        nodes.write_values(node, {'exposure': exposure+.25})
        assert nodes.grades.matrix(node) != before_matrix, 'The requested Grade edit did not commit'
        edited, info = yield from measured('grade_edit', 'linear', previous_key=report['stages']['linear']['scope_key'])
        after_capture = tuple(state['result']['identity'] for state in capture.states.values()
                              if state.get('result') is not None)
        report['grade_only_reused_capture'] = after_capture == before_capture
        report['grade_edit'] = info
        np.testing.assert_array_equal(edited['source_rgb'], rgb)
        assert report['grade_only_reused_capture'], 'Grade-only edit unnecessarily recaptured input'
        source = node.inputs['Color'].links[0].from_node if node.inputs['Color'].is_linked else None
        if source is not None and source.bl_idname == 'CompositorNodeTransform':
            source.inputs['X'].default_value += 37
            fresh, info = yield from measured('transform_bypass', 'linear',expected_key=report['grade_edit']['scope_key'])
            assert fresh['source_rgb'].shape == rgb.shape
            np.testing.assert_array_equal(fresh['source_rgb'],rgb)
            report['transform_bypass'] = info
        _, info = yield from measured('page_return', 'linear',expected_key=report['grade_edit']['scope_key'])
        report['page_return'] = info

        original_input=node.inputs['Color'].links[0].from_socket
        upstream=nodes.create_grade(tree)
        tree.nodes.active=node;upstream.select=False;node.select=True
        tree.links.new(original_input,upstream.inputs['Color'])
        tree.links.new(upstream.outputs['Color'],node.inputs['Color'])
        _,upstream_before=yield from measured('upstream_grade','linear',previous_key=report['grade_edit']['scope_key'])
        nodes.write_values(upstream,{'exposure':.25})
        changed,info=yield from measured('upstream_edit','linear',previous_key=upstream_before['scope_key'])
        assert not np.allclose(changed['source_rgb'],rgb),'Upstream Grade edit did not change sampled input'
        report['upstream_edit']=info
        tree.links.new(original_input,node.inputs['Color']);tree.nodes.remove(upstream)
        _,restored=yield from measured('upstream_restore','linear',expected_key=report['grade_edit']['scope_key'])
        report['upstream_restore']=restored

        with context_scope():route=sampling.source_route(node)
        image_node=next((item for item in tree.nodes if getattr(item,'image',None) is not None
                         and item.image.name==route.source.name),None) if route.kind=='image' else None
        if image_node is not None:
            original_image=image_node.image
            changed_image=bpy.data.images.new('Scope diagnostic changed image',width=32,height=16,alpha=True,float_buffer=True)
            changed_image.colorspace_settings.name='Non-Color'
            pixels=np.ones((16,32,4),np.float32)
            pixels[...,:3]=np.linspace(.1,.9,32)[None,:,None]
            changed_image.pixels.foreach_set(pixels.ravel());changed_image.update()
            image_node.image=changed_image
            changed,info=yield from measured('image_change','linear',previous_key=restored['scope_key'])
            assert changed['source_rgb'].shape==(16,32,3)
            report['image_change']=info
            image_node.image=original_image
            _,info=yield from measured('image_restore','linear',expected_key=restored['scope_key'])
            report['image_restore']=info
            bpy.data.images.remove(changed_image)
        automatic_events=capture.diagnostics()
        assert not any(event['event'] in {'request_created','snapshot_begin','submit'} for event in automatic_events)
        assert not capture.states,'Automatic page/edit/Transform workflow admitted native capture'
        report['automatic_zero_native_requests']=True
        report['automatic_zero_scene_fingerprints']=not any(event.get('phase')=='describe_total' for event in automatic_events)
        assert report['automatic_zero_scene_fingerprints'],'Automatic draw described a native scene'

        if options['complex_native']:
            original_input=node.inputs['Color'].links[0].from_socket
            temporary=tree.nodes.new('ShaderNodeMixRGB')
            tree.nodes.active=node;temporary.select=False;node.select=True
            temporary.name='Scope diagnostic complex source'
            temporary.inputs[0].default_value=0.
            tree.links.new(original_input,temporary.inputs[1])
            tree.links.new(temporary.outputs['Color'],node.inputs['Color'])
            began=time.perf_counter()
            with context_scope():application.component('ui.panel').redraw(bpy.context)
            native,info=yield from measured('complex_native','linear',previous_key=report['grade_edit']['scope_key'],started_at=began)
            report['complex_native']=info
            accepted=tuple(item['result']['identity'] for item in capture.states.values() if item.get('result') is not None)
            assert accepted,'Automatic native input produced no accepted capture'
            temporary.inputs[0].default_value=.25
            with context_scope():application.component('ui.panel').redraw(bpy.context)
            _,info=yield from measured('complex_native_change','linear',previous_key=info['scope_key'])
            report['complex_native_change']=info
            updated=tuple(item['result']['identity'] for item in capture.states.values() if item.get('result') is not None)
            assert updated!=accepted,'Changed native input did not acquire a new revision'
            request_count=sum(event['event']=='request_created' for event in capture.diagnostics())
            assert request_count>=2,'Source edit did not automatically reacquire'
            tree.links.new(original_input,node.inputs['Color'])
            tree.nodes.remove(temporary)
        current_links = tuple(sorted((link.from_node.name, link.from_socket.identifier,
                               link.to_node.name, link.to_socket.identifier) for link in tree.links))
        assert original_links == current_links, 'Capture changed the live graph'
        report['live_links_unchanged'] = True
        report['native'] = [dict(domain=state['result']['domain'], shape=state['result']['rgba'].shape)
                            for state in capture.states.values() if state.get('result') is not None]
        if options['diagnostics']:
            report['image_diagnostics']=images.diagnostics()
            report['capture_events'] = capture.diagnostics()
            report['capture_summary'] = summarize(report['capture_events'])
            first = min(info['started_at'] for info in report['stages'].values())
            report['capture_requests_before_initial_measurement'] = sum(
                event['event'] == 'request_created' and event['at'] < first
                for event in report['capture_events'])
            assert report['capture_requests_before_initial_measurement'] == 0, 'Cold scope began before its measurement'
            for info in (*report['stages'].values(), report['grade_edit'],report['upstream_edit'],report['upstream_restore'],
                         report.get('transform_bypass', {}), report.get('image_change',{}),report.get('image_restore',{}),
                         report['page_return'],report.get('complex_native',{}),report.get('complex_native_change',{})):
                if not info:continue
                info['capture_summary'] = summarize(event for event in report['capture_events']
                    if info['started_at'] <= event['at'] <= info['current_at'])
                info['execution_events'] = [event for event in report['execution_events']
                    if info['started_at'] <= event['at'] <= info['current_at']]
        report['limitations'] = [
            'No project file is saved; grading and Transform edits are restricted to the isolated process.',
            'Fresh processes do not clear the operating-system disk cache.',
            'GUI draw means the production board callback returned with a matching current key, not physical scanout.',
            'GUI observation reads published scheduler results; only production draws and registered timers request scopes.',
            'Headless mode explicitly pumps production callbacks and does not measure event-loop fairness or drawing.',
            'Native capture and execution phase times are inclusive; overlapping intervals must not be summed.',
            'Diagnostic hooks add overhead; each report records whether they were enabled.',
            'Image decode counts include periodic silent-pixel/reload probes; selected control edits do not themselves force those probes.',
            'Linux software-rendering results do not establish macOS/Metal latency.']
        phase('cleanup')
        for hook in reversed(hooks):
            hook.close()
        hooks.clear()
        addon_utils.disable(name, default_set=False)
        enabled = False
        assert application.closed
        report['source_after'] = hashlib.sha256(blend_path.read_bytes()).hexdigest()
        assert report['source_before'] == report['source_after'], 'Source blend changed'
        phase('complete', passed=True)

    runner = workflow()
    def step():
        nonlocal enabled
        try:
            return next(runner)
        except StopIteration:
            if options['gui']:
                bpy.ops.wm.quit_blender()
            return None
        except BaseException:
            if capture is not None and options['diagnostics']:
                report['capture_events'] = capture.diagnostics()
                report['capture_summary'] = summarize(report['capture_events'])
            phase('failed', error=traceback.format_exc())
            for hook in reversed(hooks):
                hook.close()
            hooks.clear()
            if enabled:
                addon_utils.disable(name, default_set=False)
                enabled = False
            if options['gui']:
                bpy.ops.wm.quit_blender()
                return None
            raise
    if options['gui']:
        # Opening a .blend clears nonpersistent timers. Complete that first
        # workflow segment before registering the timer that drives later steps.
        delay = step()
        if delay is not None:
            bpy.app.timers.register(step, first_interval=delay)
    else:
        while True:
            delay = step()
            if delay is None:
                break
            time.sleep(delay)


if __name__ == '__main__':
    main(*sys.argv[sys.argv.index('--')+1:])
