"""Profile real-project scope capture, helper analysis and Warp rendering.

Run through Buck: buck2 run //products/perceptual-grade-blender:scope_profile -- --blend ../rei-rgb.blend
    --output-dir /tmp/pg-scope-profile --material Material.001 --node Grade
Compare saved runs: buck2 run //products/perceptual-grade-blender:scope_profile -- --compare BASELINE OPTIMIZED
    --output /tmp/scope-comparison.json
Use --cloud-mode gpu --repeats 100 for the texture-only experiment; repeat with
--cloud-mode baseline and the same pad size, UI scale and reference mode.
Add --drag-seconds 30 --edit-hz 60 to measure continuous visuals and p95,
their age/cadence, physical retirement handoff, transfers and released final.
"""
import argparse
from collections import OrderedDict
from collections.abc import Mapping
from contextlib import ExitStack, contextmanager
from dataclasses import replace
from datetime import datetime, timezone
import functools
import hashlib
import importlib
from importlib.resources import files
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
import zipfile


@contextmanager
def replace_attribute(owner, name, replacement=..., **mock_options):
    """Replace one explicit component export and restore its lexical binding."""
    from unittest.mock import Mock
    original = getattr(owner, name)
    replacement = Mock(**mock_options) if replacement is ... else replacement
    setattr(owner, name, replacement)
    try:
        yield replacement
    finally:
        setattr(owner, name, original)


def save(path, value):
    temporary=path.with_suffix('.writing')
    temporary.write_text(json.dumps(value,indent=2,allow_nan=False)+'\n')
    temporary.replace(path)


def elapsed(function):
    started=time.perf_counter();result=function()
    return result,time.perf_counter()-started


class Timings:
    def __init__(self):self.values={}

    @contextmanager
    def instrument(self, targets):
        originals=[]
        def wrapper(original,label):
            @functools.wraps(original)
            def measured(*args,**kwargs):
                start=time.perf_counter()
                try:return original(*args,**kwargs)
                finally:
                    seconds=time.perf_counter()-start
                    record=self.values.setdefault(label,dict(calls=0,seconds=0.,maximum_seconds=0.))
                    record['calls']+=1;record['seconds']+=seconds
                    record['maximum_seconds']=max(record['maximum_seconds'],seconds)
            return measured
        try:
            for module,names in targets:
                for name in names:
                    original=getattr(module,name);originals.append((module,name,original))
                    setattr(module,name,wrapper(original,module.__name__.rsplit('.',1)[-1]+'.'+name))
            yield self
        finally:
            for module,name,original in reversed(originals):setattr(module,name,original)


def arrays(value):
    import numpy as np
    from collections.abc import Mapping
    seen=set();result=[]
    def visit(item):
        if id(item) in seen:return
        seen.add(id(item))
        if isinstance(item,np.ndarray):
            result.append(dict(shape=list(item.shape),dtype=str(item.dtype),bytes=int(item.nbytes)))
        elif isinstance(item,Mapping):
            for entry in item.values():visit(entry)
        elif isinstance(item,(tuple,list)):
            for entry in item:visit(entry)
    visit(value)
    return dict(count=len(result),bytes=sum(item['bytes'] for item in result),arrays=result)


def cloud_metadata(value):
    """Return only shapes/backend/timings, never cloud pixel or point arrays."""
    if not isinstance(value,Mapping):return {}
    records=value.get('_warp_clouds',())
    result=dict(views=len(records),pixel_bytes=0,backends=[],timings={},shapes=[])
    for name in ('_warp_cpu_seconds','_warp_cpu_reused'):
        if name in value:result[name.removeprefix('_warp_')]=value[name]
    for record in records:
        pixels=record['pixels']
        result['shapes'].append(list(pixels.shape));result['pixel_bytes']+=int(pixels.nbytes)
        result['backends'].append(str(record['backend']))
        for name,number in record.get('timings',{}).items():
            if type(number) in (int,float) and number>=0:
                result['timings'][name]=result['timings'].get(name,0.)+float(number)
    result['backends']=sorted(set(result['backends']))
    return result


def assert_texture_only(value,require_gpu=True):
    """Reject foreground point/energy arrays on the experimental result."""
    forbidden={'bounded_saturation','weights','after_energy','energy','rgba','stage2_appearance','tone_id'}
    seen=set()
    def visit(item,path='result'):
        if id(item) in seen:return
        seen.add(id(item))
        if isinstance(item,Mapping):
            for key,child in item.items():
                if key in forbidden:
                    raise AssertionError('GPU cloud publication leaked point data at '+path+'.'+str(key))
                visit(child,path+'.'+str(key))
        elif isinstance(item,(tuple,list)):
            for index,child in enumerate(item):visit(child,path+'['+str(index)+']')
    visit(value)
    if not value.get('_warp_clouds'):
        raise AssertionError('GPU cloud publication had no raster textures')
    if require_gpu and any(record.get('backend')!='gpu' for record in value['_warp_clouds']):
        raise AssertionError('GPU cloud publication used a CPU fallback raster')


def neutral_samples(result):
    colors=result.get('_active_colors',{}).values()
    return [item['neutral']['count'] for item in colors if item.get('neutral') is not None]


def display_components(result,tone=1):
    """Describe independent display freshness without copying numerical data."""
    selected={} if result is None else result.get('_active_colors',{}).get(f'{tone}:warp',result)
    visual=selected.get('_visual_request')
    statistics=selected.get('_statistics_request')
    return dict(cloud_available=bool(selected.get('_warp_clouds')),
        statistics_available=selected.get('neutral') is not None,
        visual_request=visual,statistics_request=statistics,
        retained_statistics=statistics is not None and statistics!=visual,
        display_current=bool(selected.get('_display_current',False)))


def timing_summary(values):
    from math import ceil
    from statistics import median
    values=sorted(values)
    return (dict(count=len(values),minimum_ms=1000*values[0],median_ms=1000*median(values),
        p95_ms=1000*values[ceil(.95*len(values))-1],maximum_ms=1000*values[-1],
        p95_at_least_100_samples=len(values)>=100) if values else dict(count=0))


def continuous_summary(events,release_at):
    """Summarize observed publications independently of the newest control key."""
    result=dict(duration_seconds=release_at)
    before=[event for event in events if event['at']<release_at]
    for part in ('visual','stats'):
        records=[event for event in before if event['event']=='publication' and event['part']==part]
        draws=[event for event in before if event['event']=='draw' and event['part']==part]
        label='p95' if part=='stats' else part
        result[label]=dict(publications=len(records),draws=len(draws),
            publications_per_second=len(records)/release_at if release_at else 0.,
            publication_gap=timing_summary(b['at']-a['at'] for a,b in zip(records,records[1:])),
            draw_gap=timing_summary(b['at']-a['at'] for a,b in zip(draws,draws[1:])),
            result_age=timing_summary(event['age_seconds'] for event in records
                                     if event.get('age_seconds') is not None))
    result['completion_to_next_dispatch']=timing_summary(event['retirement_gap_seconds']
        for event in before if event['event']=='submit' and event.get('retirement_gap_seconds') is not None)
    result['cancellations_during_drag']=sum(event['event']=='cancel' for event in before)
    result['cancellations_after_release']=sum(event['event']=='cancel' and event['at']>=release_at for event in events)
    result['transfers']={phase:dict(arrays=sum(event['arrays'] for event in events if event['event']==phase),
        bytes=sum(event['bytes'] for event in events if event['event']==phase)) for phase in ('input','output')}
    result['updates_before_release']=result['visual']['publications']>1 and result['p95']['publications']>1
    observations=[event for event in events if event['event']=='display']
    seen={'cloud':False,'statistics':False};missing={key:0 for key in seen}
    for event in observations:
        for key in seen:
            available=bool(event[key+'_available'])
            missing[key]+=int(seen[key] and not available)
            seen[key]|=available
    result['display_continuity']=dict(observations=len(observations),
        missing_cloud_after_first=missing['cloud'],missing_statistics_after_first=missing['statistics'],
        retained_statistics_observations=sum(bool(event.get('retained_statistics')) for event in observations))
    return result


def wire_arrays(value):
    """Count native wire descriptors without reading array files or pixels."""
    count=total=0
    def visit(item):
        nonlocal count,total
        if isinstance(item,Mapping):
            if '$array' in item:count+=1;total+=int(item.get('bytes',0))
            else:
                for child in item.values():visit(child)
        elif isinstance(item,(tuple,list)):
            for child in item:visit(child)
    visit(value)
    return dict(arrays=count,bytes=total)


def continuous_profile(module,node,seconds,edit_hz,pad_size,ui_scale,require_gpu):
    """Drive production gesture, capture, helper, publication and draw adapters."""
    import math
    nodes=module('perceptual_grade_blender.graph.nodes');scheduler=module('perceptual_grade_blender.graph.scheduler');lut=module('perceptual_grade_blender.graph.lut')
    sampling=module('perceptual_grade_blender.scopes.sampling');jobs=module('perceptual_grade_blender.scopes.jobs')
    runtime=module('perceptual_grade_blender.services').get_runtime();runtime_type=type(runtime)
    initial_a=nodes.read_chromatic(node).adaptance_a_1
    events=[];pending_draw=[];requests={};cancelled=set();last_retirement=None;last_components=None
    started=time.perf_counter();released=None;edit_count=0;token=None
    originals={name:getattr(owner,name) for owner,names in (
        (scheduler,('scope_request','scope_publish','scope_complete')),
        (jobs,('_submit',)),(jobs.ScopeResult,('cancel',)),(runtime_type,('_message',))) for name in names}
    def now():return time.perf_counter()-started
    def request(owner,kind,spec):
        ticket=originals['scope_request'](owner,kind,spec)
        if owner==node and kind=='full':requests.setdefault((ticket.key,ticket.epoch),now())
        return ticket
    def publish(ticket,payload=None,provenance=None):
        accepted=originals['scope_publish'](ticket,payload,provenance)
        if accepted and ticket.channel==('full',node.as_pointer()):
            at=now();display=scheduler.scope_result(node,'full') or payload
            part=display.get('_scope_part','full');requested=requests.get((ticket.key,ticket.epoch))
            events.append(dict(event='publication',at=at,part=part,key=ticket.key,epoch=ticket.epoch,
                               age_seconds=None if requested is None else at-requested))
            pending_draw.append((display,part,ticket.key,ticket.epoch))
        return accepted
    def complete(ticket):
        nonlocal last_retirement
        result=originals['scope_complete'](ticket)
        if ticket.channel==('full',node.as_pointer()):
            last_retirement=now();events.append(dict(event='retired',at=last_retirement,key=ticket.key))
        return result
    def submit(operation,snapshot,*args,**kwargs):
        nonlocal last_retirement
        result=originals['_submit'](operation,snapshot,*args,**kwargs)
        at=now();payload=arrays(result.handle._job.spec.inputs)
        events.append(dict(event='input',at=at,operation=operation,arrays=payload['count'],bytes=payload['bytes']))
        events.append(dict(event='submit',at=at,operation=operation,
            retirement_gap_seconds=None if last_retirement is None else at-last_retirement))
        last_retirement=None
        return result
    def cancel(future):
        identity=future.handle.identity
        if identity not in cancelled:
            cancelled.add(identity);events.append(dict(event='cancel',at=now(),handle=identity))
        return originals['cancel'](future)
    def message(owner,helper,receipt):
        job=helper.active
        if job is not None and job.spec.operation.startswith('scope_') and receipt.get('kind') in ('preview','complete'):
            events.append(dict(event='output',at=now(),operation=job.spec.operation,
                part=receipt['kind'],**wire_arrays(receipt.get('value'))))
        return originals['_message'](owner,helper,receipt)
    with ExitStack() as hooks:
        for owner,name,replacement in ((scheduler,'scope_request',request),(scheduler,'scope_publish',publish),
            (scheduler,'scope_complete',complete),(jobs,'_submit',submit),(jobs.ScopeResult,'cancel',cancel),
            (runtime_type,'_message',message)):
            hooks.enter_context(replace_attribute(owner,name,replacement))
        token=scheduler.begin(node);events.append(dict(event='begin',at=now(),gesture=token))
        next_edit=0.;next_lut=0.;deadline=time.monotonic()+seconds+180
        try:
            while True:
                at=now()
                if released is None and at>=seconds:
                    released=at;events.append(dict(event='release',at=at,gesture=token))
                    scheduler.end(token);token=None;jobs.finish_edit(node)
                if released is None and at>=next_edit:
                    # Coalesce missed mouse intervals instead of bursting delayed edits.
                    nodes.write_chromatic(node,{'adaptance_a_1':initial_a+.05*math.sin(at*2*math.pi/1.7)})
                    edit_count+=1;next_edit=at+1./edit_hz
                    events.append(dict(event='edit',at=now()))
                    space=nodes.grading_space(node)
                    sampling.get(node,space,(1,True))
                if at>=next_lut:
                    sampling.get(node,nodes.grading_space(node),(1,True));lut.tick();next_lut=at+1./60
                jobs.tick()
                components=display_components(scheduler.scope_result(node,'full'))
                if components!=last_components:
                    events.append(dict(event='display',at=now(),**components));last_components=components
                if pending_draw:
                    # As in a redraw, display the newest admitted envelope when
                    # visual and statistics were both drained in the same tick.
                    payload,part,key,epoch=pending_draw[-1];pending_draw.clear()
                    assert_texture_only(payload,require_gpu=require_gpu)
                    ui=draw_cloud(module,payload,pad_size,ui_scale,statistics=True)
                    events.append(dict(event='draw',at=ui['callback_finished_at']-started,
                                       part=part,key=key,epoch=epoch,ui=ui))
                state=jobs._states.get(node.as_pointer())
                if state is not None:
                    if state['failed']==state['spec']['key']:raise RuntimeError(state['error'])
                    if released is not None and state['completed']==state['spec']['key']:break
                if time.monotonic()>deadline:raise TimeoutError('Continuous gesture did not settle')
                time.sleep(.001)
        finally:
            if token is not None:scheduler.end(token)
    result=dict(events=events,requested_duration_seconds=seconds,edit_hz=edit_hz,edits=edit_count,
        observed_edit_hz=edit_count/released,release_at=released,release_to_final_seconds=now()-released,
        summary=continuous_summary(events,released))
    for part,label in (('visual','visual'),('stats','p95')):
        for event_name,suffix in (('publication','publication'),('draw','draw')):
            matches=[event for event in events if event['event']==event_name and event.get('part')==part
                     and event['at']>=released]
            if matches:result['release_to_'+label+'_'+suffix+'_seconds']=matches[-1]['at']-released
    continuity=result['summary']['display_continuity']
    result['passed']=(result['summary']['updates_before_release'] and
        continuity['missing_cloud_after_first']==continuity['missing_statistics_after_first']==0)
    return result


def phased_result(codec,jobs,result,preview=None,decoded_preview=None):
    """Decode the real visual/statistics protocol, including coalesced receipts."""
    decoded,decode_seconds=elapsed(lambda:codec.thaw_scope_result(result))
    visual=decoded_preview;preview_decode_seconds=0.
    if preview is not None and visual is None:
        visual,preview_decode_seconds=elapsed(lambda:codec.thaw_scope_result(preview))
    if decoded.get('_scope_part')=='stats':
        if visual is None:raise AssertionError('Statistics arrived without their retained visual preview')
        if decoded.get('_warp_clouds') or decoded.get('_active_colors'):
            raise AssertionError('Statistics delta retransmitted display data')
        decoded=jobs._merge_statistics(visual,decoded)
        if decoded is None:raise AssertionError('Statistics request did not match the visual preview')
    elif decoded.get('_scope_control'):
        raise AssertionError('Scope update needs registration: '+decoded['_scope_control'])
    return decoded,dict(decode_seconds=decode_seconds+preview_decode_seconds,
        terminal_decode_seconds=decode_seconds,preview_decode_seconds=preview_decode_seconds,
        output=arrays((preview,result)),visual_output=arrays(preview),terminal_output=arrays(result))


def draw_cloud(module, result, pad_size, ui_scale, statistics=False):
    """Time the production UI upload/draw; fence separately for offscreen tests."""
    import gpu
    from mathutils import Matrix
    began=time.perf_counter()
    samples=module('perceptual_grade_blender.ui.warp_samples');warp=module('perceptual_grade_blender.ui.warp')
    plot_type=module('perceptual_grade_blender.ui.color_geometry').ABPlot
    tone=1
    selected=result['_active_colors'][f'{tone}:warp']
    external={} if any(record['pixels'].shape[0]>1 for record in selected.get('_warp_clouds',())) else None
    radius=warp.view_radius(selected['model'],tone)
    plot=plot_type((0.,0.,float(pad_size),float(pad_size)),-radius,radius,-radius,radius)
    surface=gpu.types.GPUOffScreen(pad_size,pad_size)
    targets=[(samples,('layer','normalize_coverage','upload_coverage'))]
    timing=Timings()
    try:
        with surface.bind(),gpu.matrix.push_pop(),gpu.matrix.push_pop_projection():
            gpu.state.viewport_set(0,0,pad_size,pad_size)
            frame=gpu.state.active_framebuffer_get();frame.clear(color=(0,0,0,1))
            gpu.matrix.load_matrix(Matrix.Identity(4))
            gpu.matrix.load_projection_matrix(Matrix(((2/pad_size,0,0,-1),(0,2/pad_size,0,-1),
                                                       (0,0,-1,0),(0,0,0,1))))
            setup_seconds=time.perf_counter()-began
            with timing.instrument(targets):
                def draw():
                    samples.draw(plot,selected,external,ui_scale)
                    if statistics and selected.get('neutral') is not None:
                        module('perceptual_grade_blender.ui.color').neutral_stats(plot,selected['neutral'],ui_scale,False)
                _,seconds=elapsed(draw)
            callback_finished_at=time.perf_counter()
            # A readback forces completion for the benchmark, and is excluded
            # from production callback timing because the UI does not do this.
            _,fence_seconds=elapsed(lambda:frame.read_color(0,0,1,1,4,0,'UBYTE'))
    finally:surface.free()
    return dict(callback_seconds=seconds,callback_finished_at=callback_finished_at,
                benchmark_surface_setup_seconds=setup_seconds,
                benchmark_fence_seconds=fence_seconds,functions=timing.values,
                **display_components(result,tone))


class Context:
    def __init__(self,role='gpu'):
        self.role=self.lane=role
        self.generation=0;self.session='scope-profile-direct'
        self.visual=None;self.visual_at=None
    def preview(self,value):
        self.visual=value;self.visual_at=time.perf_counter()
    def checkpoint(self):pass


def native_profile(repository, report_path, blend, material_name, node_name, repeats,
                   cold_repeats=5, require_analytical=False,cloud_mode='baseline',
                   pad_size=409,ui_scale=1.,reference_mode='captured',lut_mode='concurrent',
                   drag_seconds=0.,edit_hz=60.):
    import addon_utils
    import bpy
    import numpy as np
    report_path=Path(report_path)
    report=dict(passed=False,started_at=datetime.now(timezone.utc).isoformat(),
                blender=bpy.app.version_string,platform=platform.platform(),numpy=np.__version__,
                material=material_name,node=node_name,phases=[],direct=[],remote=[],
                cloud_mode=cloud_mode,pad_size=pad_size,ui_scale=ui_scale,reference_mode=reference_mode,
                lut_mode=lut_mode,drag_seconds=drag_seconds,edit_hz=edit_hz,
                warm_repeats=repeats,p95_at_least_100_samples=repeats>=100)
    module_name='bl_ext.pg_scope_profile.perceptual_grade'
    application=None

    def phase(name,**values):
        item=dict(name=name,perf_counter=time.perf_counter(),**values)
        report['phases'].append(item);save(report_path,report)
        print('PG scope profile:',json.dumps(item),flush=True)

    def module(path):
        if path.startswith('perceptual_grade_blender.'):
            name = path.removeprefix('perceptual_grade_blender.')
            if name in importlib.import_module(module_name+'.perceptual_grade_blender.integration.registry').COMPONENTS:
                if application is None:
                    raise RuntimeError('Profiling requires its original registered product Session')
                return application.component(name)
        return importlib.import_module(module_name+'.'+path)

    bpy.context.preferences.view.show_splash=False
    bpy.context.preferences.filepaths.use_scripts_auto_execute=False
    bpy.context.preferences.extensions.repos.new(name='Scope profile',module='pg_scope_profile',
                                                custom_directory=repository)
    phase('extension.enable.begin')
    addon=addon_utils.enable(module_name,default_set=False)
    if addon is None:raise RuntimeError('Cannot enable profiling extension')
    application=importlib.import_module(module_name+'.perceptual_grade_blender.integration.lifecycle').registered_session()
    if application is None:raise RuntimeError('Profiling extension did not retain its Session')
    phase('project.open.begin')
    bpy.ops.wm.open_mainfile(filepath=blend,use_scripts=False,load_ui=True)
    phase('project.open.complete')

    def execute_profile():
        checks=ExitStack()
        try:
            nodes=module('perceptual_grade_blender.graph.nodes');lut=module('perceptual_grade_blender.graph.lut');sampling=module('perceptual_grade_blender.scopes.sampling')
            jobs=module('perceptual_grade_blender.scopes.jobs');codec=module('perceptual_grade_core.jobs.codec');handler=module('perceptual_grade_blender.jobs.handlers.scopes')
            analysis=module('perceptual_grade_core.model.scope_analysis');color=module('perceptual_grade_core.model.scope_color')
            robust=module('perceptual_grade_core.model.statistics');reference=module('perceptual_grade_core.model.scope_reference')
            pipeline=module('perceptual_grade_core.model.pipeline');chromatic=module('perceptual_grade_core.model.color')
            values=module('perceptual_grade_core.jobs.values');contracts=module('blender_runtime.execution.contracts')
            runtime=module('perceptual_grade_blender.services').get_runtime()
            report['scope_protocol']='active-phased'
            report['membership_schema']=color.MEMBERSHIP_SCHEMA
            cloud_settings=module('perceptual_grade_blender.scopes.clouds')
            cloud_settings.set_enabled(cloud_mode=='gpu')
            material=bpy.data.materials.get(material_name)
            if material is None or material.node_tree is None:raise ValueError('Missing material '+material_name)
            node=material.node_tree.nodes.get(node_name)
            if node is None or not nodes.is_grade(node):raise ValueError('Missing current-schema regular Grade '+node_name)
            warp=module('perceptual_grade_blender.ui.warp')
            def profile_views(owner):
                model=chromatic.model(nodes.read_tone(owner),nodes.read_chromatic(owner),nodes.grading_space(owner))
                radius=warp.view_radius(model,1)
                bound=(-radius,-radius,radius,radius)
                return (cloud_settings.descriptor((0.,0.,float(pad_size),float(pad_size)),
                                                  ui_scale,(bound,)*4,tone=1),)
            checks.enter_context(replace_attribute(cloud_settings,'views',side_effect=profile_views))
            checks.enter_context(replace_attribute(cloud_settings,'demands',return_value=((1,True),)))
            if reference_mode in ('off','primary'):
                socket=node.inputs.get('Color Reference')
                if socket is not None:
                    for link in tuple(socket.links):material.node_tree.links.remove(link)
                    if reference_mode=='primary':
                        source=node.inputs.get('Color')
                        if source is None or not source.is_linked:
                            raise ValueError('Primary reference mode requires a linked Color source')
                        material.node_tree.links.new(source.links[0].from_socket,socket)
            report['require_analytical']=require_analytical
            if require_analytical:
                original_signal=lut.scope_signal
                def dependency_signal(owner,*args,**kwargs):
                    if nodes.is_grade(owner):
                        raise AssertionError('Analytical scope requested a regular Grade final LUT')
                    return original_signal(owner,*args,**kwargs)
                checks.enter_context(replace_attribute(lut,'scope_signal',dependency_signal))
            report['scene_space']=nodes.working_space()
            report['source_links']=[dict(socket=socket.name,node=socket.links[0].from_node.name,
                image=getattr(getattr(socket.links[0].from_node,'image',None),'name',None))
                for socket in node.inputs if socket.is_linked]
            if not require_analytical:
                phase('final.ensure.begin')
                _,report['ensure_seconds']=elapsed(lambda:lut.ensure(node,nodes.bake_model(node)))
                report['lut_diagnostics']=dict(lut.installed_cube(node).diagnostics)
                phase('final.ensure.complete',seconds=report['ensure_seconds'])
            jobs.clear()
            report['preexisting_jobs']=[dict(operation=job.spec.operation,role=job.role)
                                        for job in runtime.jobs.values()]
            deadline=time.monotonic()+180
            while runtime.jobs:
                runtime.poll(budget_ms=4);time.sleep(.001)
                if time.monotonic()>deadline:raise TimeoutError('Existing work did not settle before profiling')
            if lut_mode=='disabled':
                checks.enter_context(replace_attribute(lut,'tick',return_value=None))
            # Profile the actual Warp consumer. This keeps baseline and the
            # texture experiment on the same Stage-3 request shape; GPU mode
            # additionally decorates that request with native raster views.
            spec=sampling.describe(node,nodes.grading_space(node),(1,True))
            phase('capture.begin')
            capture_timing=Timings()
            try:
                with capture_timing.instrument([(sampling,('source_samples','scope_signal')),
                                                (lut,('read_cube',))]):
                    snapshot,report['capture_seconds']=elapsed(lambda:sampling.capture(spec))
            finally:sampling.release(spec)
            report['capture_functions']=capture_timing.values
            if not snapshot.get('_warp_views'):
                snapshot['_warp_analysis_key']=snapshot['key']
                snapshot['_warp_views']=profile_views(node)
            report['sample_shape']=list(snapshot['rgba'].shape)
            report['comparison']=snapshot['comparison'] is not None
            report['chain_steps']=len(snapshot['chain'])
            if require_analytical and snapshot['signal'] is not None:
                raise AssertionError('Analytical capture transported an own signal')
            report['initial_color_parameters']=codec._parameters(snapshot['params'])
            payload,report['request_encode_seconds']=elapsed(lambda:codec.freeze_scope_request(snapshot))
            report['input_payload']=arrays(payload)
            update_payload=codec.freeze_scope_request(jobs._update_snapshot(snapshot))
            report['seed_payload']=arrays(payload)
            report['update_payload']=arrays(update_payload)
            if report['update_payload']['count']:
                raise AssertionError('Warm scope update still transports numerical arrays')
            phase('capture.complete',seconds=report['capture_seconds'],shape=report['sample_shape'])
            targets=[(analysis,('evaluate_snapshot','evaluate_samples','evaluate_signal','apply_chain','distribution')),
                (color,('evaluate_all','input_analysis','evaluate','selection','vectorscope','output_waveform')),
                (robust,('describe_sample','detmcd','qn','concentrate','weighted_sample')),
                (reference,('evaluate','select')),
                (pipeline.Prepared,('__init__',)),(chromatic.Model,('drivers','capacity')),
                (codec,('thaw_scope_request','freeze_full_scope_result'))]
            # starts() is a generator: timing its construction misses its body.
            targets.append((robust,('hashed_sample','ranks','corrected_start')))
            # Handler aliases are imported symbols, so wrap their actual bindings too.
            targets.append((handler,('thaw_scope_request','freeze_full_scope_result')))
            operation='scope_update'
            lane='scope_gpu' if cloud_mode=='gpu' else 'bulk'
            process=handler.update
            active=module('perceptual_grade_blender.model.scope_active');active_gpu=module('perceptual_grade_blender.model.scope_active_gpu')
            targets.extend([(active,('prepare','group','output','visual','statistics')),
                (handler,('register','update','freeze_scope_result'))])
            if cloud_mode=='gpu':targets.append((active_gpu,('evaluate','warp','jc','histograms','gather')))

            def trial_request(label,index):
                # Change real controls so retained output and p95 caches cannot
                # turn a measured release into a view-only reraster cache hit.
                identity=snapshot['key']
                if not hasattr(identity, 'version'):
                    raise TypeError('Scope profile requires the named ScopeIdentity contract')
                trial=dict(snapshot,
                           key=replace(identity, version=(identity.version,label,index)))
                trial['_warp_analysis_key']=trial['key'].analysis()
                trial['params']=replace(snapshot['params'],adaptance_a_1=
                    snapshot['params'].adaptance_a_1+.05*(2*((index*37)%101)/100-1))
                trial=jobs._update_snapshot(trial)
                return codec.freeze_scope_request(trial)

            handler._cache.clear()
            handler._warp_results.clear()
            cloud_engine=module('perceptual_grade_blender.model.scope_active_gpu') if cloud_mode=='gpu' else None
            handler._active_bases.clear();handler._sources.clear()
            for index in range(cold_repeats+repeats):
                kind='cold' if index<cold_repeats else 'warm'
                if kind=='cold':
                    handler._cache.clear()
                    handler._warp_results.clear()
                    handler._active_bases.clear();handler._sources.clear()
                    if cloud_engine is not None:cloud_engine.clear()
                trial_payload=trial_request('profile-direct',index)
                context=Context(lane)
                registration_seconds=0.
                if kind == 'cold' or index == 0:
                    acknowledgement,registration_seconds=elapsed(lambda:handler.register(payload,context))
                    if codec.thaw_scope_result(acknowledgement).get('_scope_control')!='ready':
                        raise AssertionError('Direct source registration was not acknowledged')
                phase('direct.begin',index=index)
                timing=Timings()
                began=time.perf_counter()
                with timing.instrument(targets):result,seconds=elapsed(lambda:process(trial_payload,context))
                sealed,seal_seconds=elapsed(lambda:values.seal(result))
                preview=None;preview_seal_seconds=0.
                if context.visual is not None:
                    preview,preview_seal_seconds=elapsed(lambda:values.seal(context.visual))
                decoded,protocol=phased_result(codec,jobs,sealed,preview)
                assert_texture_only(decoded,require_gpu=cloud_mode=='gpu')
                item=dict(kind=kind,seconds=seconds,functions=timing.values,
                          seal_seconds=seal_seconds+preview_seal_seconds,
                          registration_seconds=registration_seconds,
                          visual_seconds=context.visual_at-began if context.visual_at is not None else seconds,
                          neutral_samples=neutral_samples(decoded),
                          base_cache_entries=len(handler._active_bases),**protocol)
                item['scope_timings']=dict(decoded.get('_scope_timings',{}))
                if 'tone_population' not in report:
                    base=next(reversed(handler._active_bases.values()))
                    report['tone_population']={str(tone):int(np.count_nonzero(base['tone_id']==tone))
                                               for tone in (0,1,2,3,255)}
                    report['detmcd_sampling']={}
                    for tone,selected in base['groups'].items():
                        near=color.near_neutral(selected['q'],selected['energy'])
                        basis='linear appearance saturation < 0.1'
                        report['detmcd_sampling'][str(tone)]=dict(
                            tone_pixels=len(selected['ids']),
                            eligible_pixels=int(np.count_nonzero(near&(selected['alpha']>0))),
                            selected_pixels=len(selected['sample_ids']),basis=basis,
                            selection='SplitMix64 original raster IDs, distinct alpha-biased priorities',
                            gpu_readback_bytes=len(selected['sample_ids'])*2*4)
                item['cloud']=cloud_metadata(decoded)
                item['ui']=draw_cloud(module,decoded,pad_size,ui_scale)
                report['direct'].append(item)
                phase('direct.complete',index=index,seconds=seconds,seal_seconds=item['seal_seconds'],decode_seconds=item['decode_seconds'])
                del result,sealed,decoded
            # Real helpers give process/transport totals. Their computation cache
            # starts cold independently of the foreground diagnostic handler.
            phase('remote.register.begin')
            registered=time.perf_counter()
            handle=runtime.submit(contracts.JobSpec('scope_register',payload,lane=lane))
            deadline=time.monotonic()+180
            while not handle._job.finished:
                runtime.poll(budget_ms=4)
                if time.monotonic()>deadline:raise TimeoutError('Scope registration exceeded deadline')
                time.sleep(.001)
            acknowledgement=codec.thaw_scope_result(handle.result(timeout=1))
            if acknowledgement.get('_scope_control')!='ready':
                raise AssertionError('Remote source registration was not acknowledged')
            report['remote_registration']=dict(seconds=time.perf_counter()-registered,
                input=arrays(payload),output=arrays(handle.result(timeout=1)),backend=handle.backend,
                generation=handle.generation)
            phase('remote.register.complete',seconds=report['remote_registration']['seconds'])
            for trial,batch in enumerate((1,1,2)+(1,)*(repeats-1)):
                phase('remote.begin',batch=batch)
                began=time.perf_counter();handles=[];started={};completed={};previews={}
                for job_index in range(batch):
                    trial_payload=payload
                    trial_payload=trial_request('profile-remote',trial*2+job_index)
                    handles.append(runtime.submit(contracts.JobSpec(operation,trial_payload,lane=lane)))
                submit_seconds=time.perf_counter()-began
                deadline=time.monotonic()+180
                foreground=Timings()
                with foreground.instrument([(type(runtime),('_message',))]):
                    while len(completed)<len(handles):
                        runtime.poll(budget_ms=4)
                        now=time.perf_counter()
                        for index,handle in enumerate(handles):
                            if handle.running() and index not in started:started[index]=now-began
                            if handle.preview is not None and index not in previews:
                                visual,decode_seconds=elapsed(lambda:codec.thaw_scope_result(handle.preview))
                                assert_texture_only(visual,require_gpu=cloud_mode=='gpu')
                                first_visual_seconds=time.perf_counter()-began
                                ui=draw_cloud(module,visual,pad_size,ui_scale)
                                previews[index]=dict(decoded=visual,decode_seconds=decode_seconds,ui=ui,
                                    visual_seconds=first_visual_seconds,
                                    first_warp_draw_seconds=ui['callback_finished_at']-began)
                            if handle._job.finished and index not in completed:
                                result=handle.result(timeout=1)
                                preview=previews.get(index)
                                decoded,protocol=phased_result(codec,jobs,result,handle.preview,
                                    None if preview is None else preview['decoded'])
                                assert_texture_only(decoded,require_gpu=cloud_mode=='gpu')
                                done_seconds=time.perf_counter()-began
                                if preview is not None:
                                    protocol['preview_decode_seconds']+=preview['decode_seconds']
                                    protocol['decode_seconds']+=preview['decode_seconds']
                                    ui=preview['ui']
                                else:ui=draw_cloud(module,decoded,pad_size,ui_scale)
                                completed[index]=dict(done_seconds=done_seconds,
                                    started_seconds=started.get(index),backend=handle.backend,
                                    cloud=cloud_metadata(decoded),ui=ui,**protocol,
                                    visual_seconds=preview['visual_seconds'] if preview else done_seconds,
                                    first_warp_draw_seconds=ui['callback_finished_at']-began,
                                    p95_publication_seconds=done_seconds,
                                    scope_timings=dict(decoded.get('_scope_timings',{})))
                        if time.monotonic()>deadline:raise TimeoutError('Scope helper profile exceeded deadline')
                        time.sleep(.001)
                report['remote'].append(dict(batch=batch,kind='cold' if trial==0 else 'queued' if batch==2 else 'warm',
                    submit_seconds=submit_seconds,
                    total_seconds=time.perf_counter()-began,jobs=[completed[i] for i in range(batch)],
                    foreground_functions=foreground.values))
                phase('remote.complete',batch=batch,seconds=report['remote'][-1]['total_seconds'])
                del handles,result
            # Drive the same foreground request/capture/publication adapters at
            # their regular polling cadence after real in-memory Warp edits.
            # No synthetic replacement pixels or alternate numerical model.
            report['committed_edits']=[]
            jobs.clear()
            initial_a=float(getattr(nodes.read_chromatic(node),'adaptance_a_1'))
            for index in range(repeats+1):
                phase('committed.begin',index=index)
                began=time.perf_counter();events=[];last_image=None;scope_attempt=None;last_gpu={}
                visual_seconds=None;first_ui=None;scope_jobs=[]
                if index:nodes.write_chromatic(node,{'adaptance_a_1':initial_a+.05*(2*((index*37)%101)/100-1)})
                edited=time.perf_counter()-began
                timing=Timings();deadline=time.monotonic()+180
                with timing.instrument([(sampling,('capture','describe')),
                                        (jobs,('tick',)),(lut,('tick','publish','read_cube'))]):
                    while True:
                        sampling.get(node,nodes.grading_space(node),(1,True))
                        lut.tick();jobs.tick()
                        now=time.perf_counter()-began
                        for role in ('gpu','scope_gpu','bulk'):
                            helper=runtime.helpers.get(role)
                            active_job=None if helper is None else helper.active
                            active_key=None if active_job is None else (active_job.spec.operation,active_job.order,active_job.state.identity)
                            if active_key!=last_gpu.get(role):
                                events.append(dict(event='helper_lane',role=role,at=now,
                                    operation=active_key[0] if active_key else None,
                                    job_order=active_key[1] if active_key else None))
                                last_gpu[role]=active_key
                        image=lut.image_for(node)
                        image_key=None if image is None else (image.get('_pg_cube_size'),image.get('_pg_cube_signature'))
                        if image_key!=last_image:
                            events.append(dict(event='installed_image',at=now,size=image_key[0] if image_key else None))
                            last_image=image_key
                        if jobs._running is not None:
                            handle=jobs._running[3].handle
                            if scope_attempt!=handle.identity:
                                scope_attempt=handle.identity
                                events.append(dict(event='scope_submitted',at=now,handle=scope_attempt,
                                    operation=handle._job.spec.operation,role=handle.backend))
                                scope_jobs.append(dict(operation=handle._job.spec.operation,
                                    role=handle.backend,input=arrays(handle._job.spec.inputs)))
                        state=jobs._states.get(node.as_pointer())
                        if state is not None:
                            if state['failed']==state['spec']['key']:raise RuntimeError(state['error'])
                            current=state.get('result')
                            if visual_seconds is None and current is not None and current.get('_scope_key')==state['spec']['key']:
                                assert_texture_only(current,require_gpu=cloud_mode=='gpu')
                                visual_seconds=time.perf_counter()-began
                                events.append(dict(event='scope_visual',at=visual_seconds,
                                    part=current.get('_scope_part','full')))
                                first_ui=draw_cloud(module,current,pad_size,ui_scale)
                            if state['completed']==state['spec']['key']:
                                events.append(dict(event='scope_current',at=time.perf_counter()-began));break
                        if time.monotonic()>deadline:raise TimeoutError('Committed scope edit did not become current')
                        time.sleep(.016)
                installed=lut.installed_cube(node)
                assert_texture_only(state['result'],require_gpu=cloud_mode=='gpu')
                report['committed_edits'].append(dict(index=index,warmup=index==0,
                    seconds=time.perf_counter()-began,edit_seconds=edited,events=events,functions=timing.values,
                    visual_seconds=visual_seconds,p95_publication_seconds=time.perf_counter()-began,
                    scope_jobs=scope_jobs,output=arrays(state['result']),
                    scope_timings=dict(state['result'].get('_scope_timings',{})),
                    backend=node.get('_pg_cube_backend'),diagnostics=dict(installed.diagnostics) if installed else None))
                ui=first_ui or draw_cloud(module,state['result'],pad_size,ui_scale)
                report['committed_edits'][-1].update(cloud=cloud_metadata(state['result']),ui=ui,
                    first_warp_draw_seconds=ui['callback_finished_at']-began)
                phase('committed.complete',index=index,seconds=report['committed_edits'][-1]['seconds'])
            if drag_seconds:
                phase('continuous.begin',seconds=drag_seconds,edit_hz=edit_hz)
                report['continuous']=continuous_profile(module,node,drag_seconds,edit_hz,pad_size,ui_scale,cloud_mode=='gpu')
                if not report['continuous']['passed']:
                    raise AssertionError('Sustained drag did not publish multiple visuals and p95 results before release')
                phase('continuous.complete',summary=report['continuous']['summary'])
            report['limitations']=[
                'Native Blender and the reported graphics backend determine these measurements; results on Linux do not establish Metal performance.',
                'Direct handler phases are inclusive timings; nested functions must not be added together.',
                'Cold direct trials clear the analysis cache, but reuse the loaded process and sampled input; they do not measure process startup.',
                'Warm runs retain registered sources and Stage-2 inputs, send array-free updates and change real Stage-3 settings within a bounded range.',
                'Remote jobs use the selected production helper lane and protocol; simultaneous pair quantifies queue waiting, not the user\'s particular gesture queue.',
                'Committed-edit trials include foreground publication, timer cadence and a production Warp draw into an offscreen native-size pad. They exclude mouse delivery and screen presentation.',
                'Continuous trials invoke real scheduler gestures and control writes with coalesced target-rate edits, poll production jobs, and draw the latest cloud plus available p95 ellipse offscreen. They simulate input delivery inside a native timer and do not measure OS mouse delivery or event-loop fairness. Observed edit rate and offscreen setup/fence costs are reported.',
                'First offscreen Warp draw latency includes benchmark surface setup; its cost is reported separately. GPU fence time is excluded from that first-draw latency.',
                'Visual and final p95 publication are recorded separately. Offscreen visual drawing occurs between production polling iterations and can delay the observed final statistics receipt; helper phase timings exclude this foreground draw.',
                'GPU compute/raster phase timings are CPU submissions, not GPU execution durations. Readback includes outstanding helper GPU work. UI benchmark fencing is reported separately from the production callback.',
                'CPU fallback is reported separately and is never evidence for healthy GPU performance. Latency p95 uses nearest rank and fewer than 100 warm samples are flagged.',
                'lut_mode=disabled suppresses LUT timer dispatch after preexisting work settles to isolate scopes. It does not represent concurrent Grade interaction; lut_mode=concurrent retains that contention.',
                'Original project is never saved.']
            report['passed']=True
            phase('complete')
        except BaseException as error:
            report['error']=dict(type=type(error).__name__,message=str(error),traceback=traceback.format_exc())
            phase('failed');traceback.print_exc()
        finally:
            checks.close()
            addon_utils.disable(module_name,default_set=False)
            bpy.ops.wm.quit_blender()
        return None

    def run():
        if not bpy.context.window_manager.windows:return .1
        with bpy.context.temp_override(window=bpy.context.window_manager.windows[0]):
            return execute_profile()

    bpy.app.timers.register(run,first_interval=.5)


def launch(args):
    from tools.diagnostics.project_probe import display_adapter,preserve_logs,sha256,stop_group
    resources=files('tools.diagnostics');output=args.output_dir.resolve()
    output.mkdir(parents=True,exist_ok=False)
    report=output/'report.json';project=args.blend.resolve()
    archive=(args.extension_zip or Path(str(resources/'extension.zip'))).resolve()
    native=Path(str(resources/'blender')).resolve()
    executable=next(p for p in (native/'blender',native/'Blender.app/Contents/MacOS/Blender') if p.is_file())
    receipt=dict(blend=str(project),blend_sha256=sha256(project),extension_zip_sha256=sha256(archive),
                 runner_sha256=sha256(__file__),blender_binary_sha256=sha256(executable),
                 display_adapter_sha256=sha256(Path(str(resources/'gui_display.py'))),
                 started_at=datetime.now(timezone.utc).isoformat(),
                 buck_command=['buck2','run','//products/perceptual-grade-blender:scope_profile','--','--blend',str(project),
                               '--output-dir',str(output),'--material',args.material,'--node',args.node,
                               '--repeats',str(args.repeats),'--cold-repeats',str(args.cold_repeats),
                               '--cloud-mode',args.cloud_mode,'--pad-size',str(args.pad_size),
                               '--ui-scale',str(args.ui_scale),'--reference-mode',args.reference_mode,
                               '--lut-mode',args.lut_mode,'--drag-seconds',str(args.drag_seconds),'--edit-hz',str(args.edit_hz),
                               '--timeout',str(args.timeout)])
    if args.extension_zip:receipt['buck_command']+=['--extension-zip',str(archive)]
    if args.require_analytical:receipt['buck_command'].append('--require-analytical')
    with zipfile.ZipFile(archive) as source:
        manifest={item.filename:hashlib.sha256(source.read(item)).hexdigest()
                  for item in source.infolist() if not item.is_dir()}
    save(output/'source_hashes.json',manifest)
    shutil.copyfile(archive,output/'extension.zip')
    shutil.copyfile(__file__,output/'scope_profile.py')
    save(output/'launch.json',receipt)
    with tempfile.TemporaryDirectory(prefix='pg-scope-profile-') as directory:
        work=Path(directory);package=work/'repository/perceptual_grade';package.mkdir(parents=True)
        with zipfile.ZipFile(archive) as source:source.extractall(package)
        env={k:v for k,v in os.environ.items() if k not in ('PYTHONPATH','PYTHONHOME') and not k.startswith('BLENDER_')}
        for key,folder in [('BLENDER_USER_CONFIG','config'),('BLENDER_USER_SCRIPTS','scripts'),
                ('BLENDER_USER_EXTENSIONS','extensions'),('BLENDER_USER_DATAFILES','datafiles')]:env[key]=str(work/folder)
        temp=work/'native-temp';temp.mkdir()
        env.update(TMPDIR=str(temp),TMP=str(temp),TEMP=str(temp),OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1')
        command=[str(executable),'--factory-startup','--disable-autoexec','--threads','1',
                 '--window-geometry','0','0','1280','960','--python-exit-code','1','--python',str(output/'scope_profile.py'),
                 '--','--native',str(package.parent),str(report),str(project),args.material,args.node,
                 str(args.repeats),str(args.cold_repeats),str(int(args.require_analytical)),
                 args.cloud_mode,str(args.pad_size),str(args.ui_scale),args.reference_mode,args.lut_mode,
                 str(args.drag_seconds),str(args.edit_hz)]
        receipt['native_command']=command
        save(output/'launch.json',receipt)
        process=None
        try:
            with display_adapter(resources)(resources,work,env):
                with (output/'native.log').open('w') as log:
                    process=subprocess.Popen(command,cwd=work,env=env,stdin=subprocess.DEVNULL,
                        stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
                    receipt['native_returncode']=process.wait(timeout=args.timeout)
        finally:
            if process is not None:stop_group(process)
            preserve_logs(work,output)
            receipt['original_unchanged']=sha256(project)==receipt['blend_sha256']
            save(output/'launch.json',receipt)
    result=json.loads(report.read_text()) if report.is_file() else {}
    passed=result.get('passed') is True and receipt.get('native_returncode')==0 and receipt['original_unchanged']
    print(json.dumps(dict(passed=passed,output=str(output)),indent=2))
    return 0 if passed else 1


def compare(args):
    """Derive a repeatable summary from stored reports without importing Blender."""
    import shlex
    from statistics import median
    from math import ceil

    def read(directory,name):return json.loads((directory/name).read_text())

    def summarize(report):
        if report.get('passed') is not True:raise ValueError('Cannot compare an incomplete benchmark')
        warm=[item for item in report['direct'] if item['kind']=='warm']
        cold=[item for item in report['direct'] if item['kind']=='cold']
        edits=report['committed_edits'][1:]
        remote=[item['total_seconds'] for item in report['remote'] if item.get('kind')=='warm']
        if not remote:remote=[report['remote'][1]['total_seconds']]
        def p95(values):
            values=sorted(values)
            return 1000*values[ceil(.95*len(values))-1]
        def timing(item,name,field='seconds'):return item['functions'].get(name,{}).get(field,0)
        result=dict(
            cold_handler_ms=[1000*item['seconds'] for item in cold],
            warm_handler_ms=[1000*item['seconds'] for item in warm],
            warm_handler_median_ms=1000*median(item['seconds'] for item in warm),
            warm_handler_p95_ms=p95(item['seconds'] for item in warm),
            input_analysis_median_ms=1000*median(timing(item,'scope_color.input_analysis') for item in warm),
            capacity_median_ms=1000*median(timing(item,'Model.capacity') for item in warm),
            capacity_calls=[timing(item,'Model.capacity','calls') for item in warm],
            prepared_calls=[item['functions'].get('Prepared.__init__',{}).get('calls',0) for item in warm],
            cold_remote_ms=1000*report['remote'][0]['total_seconds'],
            warm_remote_ms=1000*median(remote),warm_remote_p95_ms=p95(remote),
            queued_pair_ms=1000*report['remote'][2]['total_seconds'],
            committed_ms=[1000*item['seconds'] for item in edits],
            committed_median_ms=1000*median(item['seconds'] for item in edits),
            committed_p95_ms=p95(item['seconds'] for item in edits),
            input_bytes=report['input_payload']['bytes'],input_arrays=report['input_payload']['count'],
            payload_bytes=warm[-1]['output']['bytes'],payload_arrays=warm[-1]['output']['count'])
        def stats(values):
            values=list(values)
            return dict(count=len(values),median_ms=1000*median(values),p95_ms=p95(values),
                        p95_at_least_100_samples=len(values)>=100) if values else dict(count=0)
        result['configuration']={name:report.get(name) for name in
                                 ('cloud_mode','scope_protocol','membership_schema','pad_size','ui_scale',
                                  'reference_mode','comparison','platform','lut_mode')}
        result['seed_input']=report.get('seed_payload',report['input_payload'])
        result['tone_population']=report.get('tone_population')
        result['detmcd_sampling']=report.get('detmcd_sampling')
        result['warm_update_input']=report.get('update_payload',report['input_payload'])
        result['visual_output']=warm[-1].get('visual_output',warm[-1]['output'])
        result['terminal_output']=warm[-1].get('terminal_output',warm[-1]['output'])
        result['handler_visual']=stats(item['visual_seconds'] for item in warm if 'visual_seconds' in item)
        result['committed_visual']=stats(item['visual_seconds'] for item in edits
                                          if item.get('visual_seconds') is not None)
        result['p95_publication']=stats(item['p95_publication_seconds'] for item in edits
                                         if 'p95_publication_seconds' in item)
        result['visual_to_p95']=stats(item['p95_publication_seconds']-item['visual_seconds'] for item in edits
            if item.get('visual_seconds') is not None and 'p95_publication_seconds' in item)
        result['handler_scope_phases']={name:stats(item.get('scope_timings',{}).get(name,0.) for item in warm)
            for name in ('prepare_seconds','visual_seconds','statistics_seconds')}
        result['first_warp_draw']=stats(item['first_warp_draw_seconds'] for item in edits
                                        if 'first_warp_draw_seconds' in item)
        result['ui_callback']=stats(item['ui']['callback_seconds'] for item in edits if 'ui' in item)
        result['healthy_gpu_warm_count']=sum(item.get('cloud',{}).get('backends')==['gpu'] for item in warm)
        result['cpu_fallback_warm_count']=sum('cpu' in item.get('cloud',{}).get('backends',()) for item in warm)
        result['cloud_phases']={name:stats(item.get('cloud',{}).get('timings',{}).get(name,0.) for item in warm
                                         if item.get('cloud',{}).get('backends')==['gpu'])
                                for name in ('preparation_seconds','compute_submission_seconds',
                                             'raster_submission_seconds','readback_seconds')}
        result['foreground_message']=stats(item.get('foreground_functions',{}).get('ExecutionRuntime._message',{}).get('seconds',0.)
                                            for item in report['remote'] if item.get('kind')=='warm')
        result['foreground_decode']=stats(job.get('decode_seconds',0.) for item in report['remote']
                                           if item.get('kind')=='warm' for job in item['jobs'])
        result['continuous']=report.get('continuous',{}).get('summary')
        return result

    baseline,optimized=(path.resolve() for path in args.compare)
    before=read(baseline,'report.json');after=read(optimized,'report.json')
    before_sources=read(baseline,'source_hashes.json');after_sources=read(optimized,'source_hashes.json')
    output=args.output.resolve()
    result=dict(baseline=summarize(before),optimized=summarize(after),
        changed_packaged_files=[name for name in sorted(set(before_sources)|set(after_sources))
                                if before_sources.get(name)!=after_sources.get(name)],
        limitations=after['limitations'],command=shlex.join(read(optimized,'launch.json')['buck_command']),
        comparison_command=shlex.join(['buck2','run','//products/perceptual-grade-blender:scope_profile','--','--compare',
                                      str(baseline),str(optimized),'--output',str(output)]),
        generator_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        inputs={label:{name:hashlib.sha256((directory/name).read_bytes()).hexdigest()
                       for name in ('report.json','launch.json','source_hashes.json')}
                for label,directory in (('baseline',baseline),('optimized',optimized))})
    comparable=('pad_size','ui_scale','reference_mode','sample_shape','comparison','platform','lut_mode',
                'scope_protocol','membership_schema')
    result['configuration_differences']={name:[before.get(name),after.get(name)] for name in comparable
                                         if before.get(name)!=after.get(name)}
    result['performance_acceptance_sample_count_met']=bool(len(before['committed_edits'])>=101
        and len(after['committed_edits'])>=101 and not result['configuration_differences']
        and all(item.get('cloud',{}).get('backends')==['gpu'] for item in after['committed_edits'][1:]))
    result['runner_sha256']={label:read(directory,'launch.json').get('runner_sha256')
                            for label,directory in (('baseline',baseline),('optimized',optimized))}
    result['same_runner']=len(set(result['runner_sha256'].values()))==1
    output.parent.mkdir(parents=True,exist_ok=True);save(output,result)
    print(json.dumps(dict(output=str(output),changed_packaged_files=result['changed_packaged_files']),indent=2))
    return 0


def main():
    if '--native' in sys.argv:
        values=sys.argv[sys.argv.index('--native')+1:]
        native_profile(*values[:5],int(values[5]),int(values[6]),bool(int(values[7])),
                       values[8],int(values[9]),float(values[10]),values[11],values[12],
                       float(values[13]) if len(values)>13 else 0.,float(values[14]) if len(values)>14 else 60.);return 0
    parser=argparse.ArgumentParser(description=__doc__)
    mode=parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--blend',type=Path)
    mode.add_argument('--compare',nargs=2,type=Path,metavar=('BASELINE_DIR','OPTIMIZED_DIR'))
    parser.add_argument('--output-dir',type=Path)
    parser.add_argument('--output',type=Path)
    parser.add_argument('--material',default='Material.001')
    parser.add_argument('--node',default='Grade')
    parser.add_argument('--repeats',type=int,default=100)
    parser.add_argument('--cold-repeats',type=int,default=5)
    parser.add_argument('--extension-zip',type=Path,help='Use a retained baseline package with the same runner')
    parser.add_argument('--require-analytical',action='store_true',help='Forbid regular Grade final-LUT scope requests')
    parser.add_argument('--cloud-mode',choices=('baseline','gpu'),default='baseline',
                        help='Use compact active CPU or scope GPU rendering')
    parser.add_argument('--pad-size',type=int,default=409,help='Warp pad size in native pixels')
    parser.add_argument('--ui-scale',type=float,default=1.,help='Native UI scale; use a proportionately larger pad for high-DPI trials')
    parser.add_argument('--reference-mode',choices=('captured','off','primary'),default='captured',
                        help='Use the project reference, disconnect it, or link the primary source as reference in memory')
    parser.add_argument('--lut-mode',choices=('concurrent','disabled'),default='concurrent',
                        help='Retain normal LUT work, or suppress LUT timer dispatch to isolate scope latency')
    parser.add_argument('--timeout',type=float,default=900)
    parser.add_argument('--drag-seconds',type=float,default=0.,help='Append a sustained real scheduler gesture before final release')
    parser.add_argument('--edit-hz',type=float,default=60.,help='Target continuous control edit frequency; delayed events coalesce')
    args=parser.parse_args()
    if args.repeats<1 or args.cold_repeats<1:parser.error('Repeat counts must be positive')
    if args.pad_size<1 or args.ui_scale<=0:parser.error('Pad size and UI scale must be positive')
    if args.drag_seconds<0 or args.edit_hz<=0:parser.error('Drag duration must be nonnegative and edit frequency positive')
    if args.compare:
        if args.output is None:parser.error('--compare requires --output')
        return compare(args)
    if args.output_dir is None:parser.error('--blend requires --output-dir')
    return launch(args)


if __name__=='__main__':
    if '--native' in sys.argv:main()
    else:sys.exit(main())
