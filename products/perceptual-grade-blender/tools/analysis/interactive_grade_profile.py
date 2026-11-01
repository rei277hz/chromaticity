"""Fresh-process timings for coalesced Grade previews and priority Stage-1 scopes."""
import argparse
from contextlib import ExitStack
from functools import wraps
import hashlib
import json
import os
from pathlib import Path
from statistics import median
import subprocess
import sys
import tempfile
import time

CHILD_IMPORT_PATH=tuple(sys.path)
SCENARIOS=('stage1','stage3','continuous')


def timed(function):
    start=time.perf_counter();result=function();return result,time.perf_counter()-start


def save(path,value):
    path.write_text(json.dumps(value,indent=2,allow_nan=False)+'\n')


def key_id(key):
    return hashlib.sha256(repr(key).encode()).hexdigest()[:16]


def latency_summary(values):
    values=sorted(values)
    if not values:return None
    return dict(count=len(values),median_s=median(values),
        p95_s=values[max(0,(95*len(values)+99)//100-1)],maximum_s=values[-1])


def annotate(result):
    for event in result['events']:
        field='linear_key' if event['kind']=='stage1_scope' else 'signature'
        value=event.get('key' if field=='linear_key' else 'signature')
        matches=[edit for edit in result['edits'] if edit.get(field)==value and edit['at_s']<=event['at_s']]
        if matches:
            event['request_index']=matches[-1]['index']
            event['request_age_s']=event['at_s']-matches[-1]['at_s']
    result['latency']={kind:latency_summary([event['request_age_s'] for event in result['events']
        if event['kind']==kind and 'request_age_s' in event]) for kind in ('stage1_scope','preview','final')}
    result['actual_edit_gaps']=latency_summary([b['at_s']-a['at_s'] for a,b in zip(result['edits'],result['edits'][1:])])
    result['source_reads']={phase:sum(event['kind']=='read_image' and event['phase']==phase
        for event in result['captures']) for phase in ('setup','edit')}


def worker(output,backend,scenario,duration,period):
    start=time.perf_counter()
    import bpy
    from color_tools import perceptual_grade_blender as addon
    from color_tools.perceptual_grade_blender.integration.lifecycle import registered_session
    from color_tools.perceptual_grade_core.model import bake_cache, lut as cubes
    from tools.analysis.grade_bake_profile import scope_image, replace_attribute, product
    imported=time.perf_counter()-start
    bpy.ops.wm.read_factory_settings(use_empty=True)
    addon.register()
    application=registered_session()
    gpu,grades,lut,nodes,sampling,jobs=product(application)
    scheduler=application.component('graph.scheduler')
    images=application.component('scopes.images')
    result=dict(backend=backend,scenario=scenario,blender=bpy.app.version_string,scheduler_gesture=True,
        source_size=[256,192],source_seed=20261010,requested_edit_period_s=period,drag_duration_s=duration,
        controls={'stage1':'source white xy=(0.32,0.34)',
            'stage3':'White Ch→C=1.01',
            'continuous':'exposure=0.25+0.01i; White Ch→C=1+0.01i'}[scenario],
        setup={'imports_s':imported},events=[],edits=[],captures=[],max_pending=0,
        max_linear_pending=0,max_main_thread_call_s=0.)
    clock=None
    def stamp():return None if clock is None else time.perf_counter()-clock
    def capture(function,name):
        @wraps(function)
        def measured(*args,**kwargs):
            began=time.perf_counter()
            value=function(*args,**kwargs)
            result['captures'].append(dict(kind=name,phase='setup' if clock is None else 'edit',
                start_s=None if clock is None else began-clock,duration_s=time.perf_counter()-began,
                prepared_source_reused='rgb' in value['source'] if name=='capture_linear' else None))
            return value
        return measured
    original_publish=lut.publish;original_linear_tick=jobs.linear_tick
    def linear_tick():
        value=original_linear_tick()
        if clock is not None:observe()
        return value
    def publish(node,baker,force=False,preview=False):
        began=time.perf_counter();value=original_publish(node,baker,force=force,preview=preview)
        if value and clock is not None:
            result['events'].append(dict(kind='preview' if preview else 'final',at_s=stamp(),
                duration_s=time.perf_counter()-began,signature=baker.signature,
                current_signature=cubes.signature(nodes.bake_model(node))))
        return value
    with ExitStack() as stack:
        if backend=='CPU':stack.enter_context(replace_attribute(gpu,'acquire',return_value=(None,None)))
        stack.enter_context(replace_attribute(lut,'publish',publish))
        stack.enter_context(replace_attribute(jobs,'linear_tick',linear_tick))
        stack.enter_context(replace_attribute(images,'read',capture(images.read,'read_image')))
        for name in ('source_samples','capture_linear','capture'):
            stack.enter_context(replace_attribute(sampling,name,capture(getattr(sampling,name),name)))
        def setup():
            tree=bpy.data.node_groups.new('Interactive timing','CompositorNodeTree')
            node=nodes.create_grade(tree);grades.ensure(node)
            return node
        node,result['setup']['node_and_helpers_s']=timed(setup)
        _,result['setup']['source_image_s']=timed(lambda:scope_image(node))
        _,result['setup']['identity_install_s']=timed(lambda:lut.ensure(node,nodes.bake_model(node)))
        if node.get('_pg_cube_backend')!=backend:raise RuntimeError('Requested backend did not execute')
        # The real installed cube identifies the actual backend, not the request.
        cube=lut.installed_signal(node)[0]
        result['identity_diagnostics']=dict(cube.diagnostics) if cube is not None else {}
        if backend=='GPU':
            renderer=cube.diagnostics['device'];result['renderer']=renderer
            if 'llvmpipe' not in renderer.lower():raise RuntimeError('Software llvmpipe GPU required')
            if application.app.execution.get_runtime().gpu_failure:raise RuntimeError(application.app.execution.get_runtime().gpu_failure)
        else:result['renderer']='CPU'
        pointer=node.as_pointer();space=nodes.grading_space(node);full_scopes=scenario!='stage1'
        result['full_scopes_concurrent']=full_scopes
        def request_scopes():
            sampling.get_linear(node,space)
            if full_scopes:sampling.get(node,space,(3,False))
        seen_linear=None;seen_full=None
        next_lut=next_linear=next_full=0.
        def observe():
            nonlocal seen_linear,seen_full
            state=lut._states.get(pointer)
            result['max_pending']=max(result['max_pending'],int(state is not None and state.get('pending') is not None))
            result['max_linear_pending']=max(result['max_linear_pending'],int(bool(jobs._linear_pending)))
            for label,states in (('stage1_scope',jobs._linear_states),('full_scope',jobs._states)):
                item=states.get(pointer)
                if item is None:continue
                if item['failed']==item['spec']['key']:raise RuntimeError(label+' failed')
                complete=item['completed']
                seen=seen_linear if label=='stage1_scope' else seen_full
                if complete is not None and complete!=seen:
                    if clock is not None:
                        result['events'].append(dict(kind=label,at_s=stamp(),key=key_id(complete),
                            latest=complete==item['spec']['key']))
                    if label=='stage1_scope':seen_linear=complete
                    else:seen_full=complete
        def pump():
            nonlocal next_lut,next_linear,next_full
            # Match the timer intervals; priority work runs before preview work.
            now=time.perf_counter()
            for name,function in (('linear',jobs.linear_tick),('lut',lut.tick),('full',jobs.tick)):
                if name=='full' and not full_scopes:continue
                due={'linear':next_linear,'lut':next_lut,'full':next_full}[name]
                if now<due:continue
                began=time.perf_counter();interval=function();ended=time.perf_counter()
                if clock is not None:result['max_main_thread_call_s']=max(result['max_main_thread_call_s'],ended-began)
                due=ended+(.016 if interval is None else interval)
                if name=='linear':next_linear=due
                elif name=='lut':next_lut=due
                else:next_full=due
            observe()
        def full_current():
            if not full_scopes:return True
            state=jobs._states[pointer]
            return state['completed']==sampling.describe(node,space,(3,False))['key']
        def linear_current():
            state=jobs._linear_states[pointer]
            return state['completed']==state['spec']['key']
        began=time.perf_counter()
        request_scopes()
        while not (linear_current() and full_current()):
            pump()
            if time.perf_counter()-began>120:raise TimeoutError('Initial scopes')
            time.sleep(.001)
        result['setup']['initial_source_and_scopes_s']=time.perf_counter()-began
        initial_image=lut.image_for(node).as_pointer()
        # Helpers retain immutable lookups and numerical caches from setup.
        # Startup is measured separately by the identity installation above.
        result['empty_lattice_cache_at_first_edit']=False
        result['prepared_source_reused']=True
        clock=time.perf_counter();last_request=None;released=None;edit_index=0
        gesture=scheduler.begin(node)
        stack.callback(scheduler.end,gesture)
        next_edit=clock;deadline=clock+120
        while time.perf_counter()<deadline:
            now=time.perf_counter()
            if edit_index==0 or (scenario=='continuous' and now-clock<duration and now>=next_edit):
                began=time.perf_counter();edit_index+=1
                if scenario=='stage1':nodes.write_values(node,{'source_x':.32,'source_y':.34})
                elif scenario=='continuous':nodes.write_values(node,{'exposure':.25+.01*edit_index})
                if scenario in ('stage3','continuous'):
                    nodes.write_chromatic(node,{'c_high_2':1.+.01*edit_index})
                request_scopes()
                last_request=cubes.signature(nodes.bake_model(node))
                result['edits'].append(dict(index=edit_index,at_s=began-clock,
                    duration_s=time.perf_counter()-began,signature=last_request,
                    linear_key=key_id(jobs._linear_states[pointer]['spec']['key'])))
                next_edit=time.perf_counter()+period
                # request() schedules these timers promptly when they were idle.
                next_linear=min(next_linear,time.perf_counter()+.001)
                next_full=min(next_full,time.perf_counter()+.001)
                next_lut=min(next_lut,time.perf_counter()+lut.PREVIEW_DELAY)
            pump()
            now=time.perf_counter()
            if released is None and (scenario!='continuous' or now-clock>=duration):
                released=now-clock;scheduler.end(gesture);jobs.finish_edit(node)
                result['released_s']=released
            image=lut.image_for(node)
            current=image is not None and image.get('_pg_cube_signature')==last_request and image.get('_pg_cube_size')==65
            if released is not None and current and linear_current() and full_current():break
            time.sleep(.001)
        else:raise TimeoutError('Interactive preview/scopes did not settle')
        result['settled_s']=stamp();result['final_signature']=last_request
        result['final_backend']=node.get('_pg_cube_backend')
        if result['final_backend']!=backend or (backend=='GPU' and application.app.execution.get_runtime().gpu_failure):
            raise RuntimeError('Requested backend did not finish the edited LUT')
        result['stage1_did_not_replace_lut']=scenario!='stage1' or lut.image_for(node).as_pointer()==initial_image
        if not result['stage1_did_not_replace_lut']:raise AssertionError('Stage 1 rebaked its LUT')
        installs=[event for event in result['events'] if event['kind'] in ('preview','final')]
        if scenario!='stage1' and not any(event['kind']=='preview' for event in installs):
            raise AssertionError('No 33-cube was installed')
        result['previews_during_drag']=sum(event['kind']=='preview' and event['at_s']<=released for event in installs)
        result['stage1_scopes_during_drag']=sum(event['kind']=='stage1_scope' and event['at_s']<=released for event in result['events'])
        result['setup_total_s']=sum(result['setup'].values())
        annotate(result)
        save(output/'result.json',result)
        addon.unregister()
    print(backend,scenario,'edits',edit_index,'settled',result['settled_s'],flush=True)


def summarize(report,output):
    lines=['# Interactive Grade timing','',
        'Fresh processes and empty Mesa shader caches; no discarded warm-up edits. Times below are milliseconds from the first edit. '+
        'The existing 256 × 192 source is prepared once before editing; immutable source data are then reused. '+
        'Initial installation and source preparation are reported separately.','',
        '| Backend / scenario | First Stage-1 scope | First 33³ installed | Latest 65³ installed | All scopes settled |',
        '| --- | ---: | ---: | ---: | ---: |']
    def event_time(trial,kind,latest=False):
        values=[event['at_s'] for event in trial['events'] if event['kind']==kind and
            (not latest or event.get('signature')==trial['final_signature'])]
        return min(values) if values else None
    def cell(values):
        values=[value for value in values if value is not None]
        return '—' if not values else f'{1000*median(values):.2f}'
    for name,trials in report['trials'].items():
        lines.append('| '+name+' | '+' | '.join((cell([event_time(t,'stage1_scope') for t in trials]),
            cell([event_time(t,'preview') for t in trials]),cell([event_time(t,'final',True) for t in trials]),
            cell([t['settled_s'] for t in trials])))+' |')
    lines+=['','| Backend / scenario | Import | Node/helpers | Source image | Identity/shader install | Initial source/scopes | Process total |',
        '| --- | ---: | ---: | ---: | ---: | ---: | ---: |']
    for name,trials in report['trials'].items():
        lines.append('| '+name+' | '+' | '.join(cell([t['setup'][key] for t in trials]) for key in
            ('imports_s','node_and_helpers_s','source_image_s','identity_install_s','initial_source_and_scopes_s'))+
            ' | '+cell([t['process_seconds'] for t in trials])+' |')
    lines+=['','Continuous dragging uses a requested 16 ms gap after each submitted edit; the recorded cadence includes actual main-thread delays.','',
        '| Backend | Edits | 33³ installs during drag | Stage-1 scopes during drag | Maximum queued previews | Final 65³ after release |',
        '| --- | ---: | ---: | ---: | ---: | ---: |']
    for name,trials in report['trials'].items():
        if not name.endswith('/continuous'):continue
        lines.append('| '+name.split('/')[0]+' | '+' | '.join(str(median([len(t['edits']) for t in trials])) if key=='edits'
            else str(median([t[key] for t in trials])) for key in ('edits','previews_during_drag','stage1_scopes_during_drag','max_pending'))+
            ' | '+cell([event_time(t,'final',True)-t['released_s'] for t in trials])+' |')
    lines+=['','| Continuous backend / publication | Median snapshot age | p95 | Maximum |',
        '| --- | ---: | ---: | ---: |']
    for name,trials in report['trials'].items():
        if not name.endswith('/continuous'):continue
        for kind in ('stage1_scope','preview'):
            values=[event['request_age_s'] for t in trials for event in t['events']
                if event['kind']==kind and 'request_age_s' in event]
            stats=latency_summary(values)
            if stats:lines.append('| '+name.split('/')[0]+' / '+kind+' | '+
                ' | '.join(f'{1000*stats[key]:.2f}' for key in ('median_s','p95_s','maximum_s'))+' |')
    lines+=['','Stage-1-only changes the source-white point to (0.32, 0.34) and requests only the priority scope. '+
        'Stage-3 changes White Ch→C; continuous stress changes exposure and White Ch→C together. '+
        'The latter two also request the full White color scope. '+
        'These are image-installation and scope-result-publication measurements. Headless timers do not measure visible frames, '+
        'mouse event delivery, or compositor rendering. CPU and software-GPU runs include real concurrent scope workers. '+
        'Setup contains the first shader/context work, rather than hiding it in a warm-up. '+
        'Per-edit timestamps, request signatures, source captures, and full trials are in report.json.','']
    (output/'summary.md').write_text('\n'.join(lines))


def run(args):
    args.output_dir.mkdir(parents=True,exist_ok=True)
    if args.worker:
        worker(args.output_dir,args.backend,args.scenario,args.duration,args.period);return
    if args.summarize_only:
        summarize(json.loads((args.output_dir/'report.json').read_text()),args.output_dir);return
    report=dict(trials={},limitations=['Headless manual timer pumping; no visible-frame or hardware-GPU claim.',
        'Persistent helpers retain setup caches; cold process/lookup preparation is measured in identity installation.',
        'Persistent operating-system file caches are not cleared.'])
    for backend in ([args.backend] if args.backend else ('CPU','GPU')):
        for scenario in ([args.scenario] if args.scenario else SCENARIOS):
            trials=report['trials'].setdefault(backend+'/'+scenario,[])
            for index in range(args.repeats):
                output=args.output_dir/f'{backend}-{scenario}-{index}';output.mkdir(parents=True,exist_ok=True)
                command=[sys.executable,'-m','tools.analysis.interactive_grade_profile','--worker',
                    '--output-dir',str(output.resolve()),'--backend',backend,'--scenario',scenario,
                    '--duration',str(args.duration),'--period',str(args.period)]
                with tempfile.TemporaryDirectory(prefix='mesa-',dir=output) as cache:
                    env=os.environ.copy();env['PYTHONPATH']=os.pathsep.join(CHILD_IMPORT_PATH)
                    env['MESA_SHADER_CACHE_DIR']=str(Path(cache).resolve())
                    began=time.perf_counter()
                    with (output/'process.log').open('w') as stream:
                        subprocess.run(command,env=env,stdout=stream,stderr=subprocess.STDOUT,check=True,timeout=180)
                    trial=json.loads((output/'result.json').read_text())
                    trial['process_seconds']=time.perf_counter()-began
                    trial['artifact_directory']=str(output)
                    trial['fresh_process']=True;trial['empty_mesa_cache']=True
                trials.append(trial);save(args.output_dir/'report.json',report)
                print(backend,scenario,index,'complete',flush=True)
    summarize(report,args.output_dir)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir',type=Path,required=True)
    parser.add_argument('--repeats',type=int,default=3)
    parser.add_argument('--backend',choices=('CPU','GPU'))
    parser.add_argument('--scenario',choices=SCENARIOS)
    parser.add_argument('--duration',type=float,default=1.)
    parser.add_argument('--period',type=float,default=.016)
    parser.add_argument('--worker',action='store_true')
    parser.add_argument('--summarize-only',action='store_true')
    args=parser.parse_args()
    if args.repeats<1 or args.duration<=0 or args.period<=0:parser.error('Positive repeats, duration and period required')
    if args.worker and (not args.backend or not args.scenario):parser.error('Worker requires backend and scenario')
    run(args)
