"""Measure actual CPU/GPU regular Grade installation; never regenerate D65."""
import argparse
from contextlib import ExitStack, contextmanager
from datetime import datetime
from functools import wraps
import hashlib
import importlib.util
import inspect
import json
import os
from pathlib import Path
import platform
from statistics import median
import sys
from threading import Lock, get_ident
import time

import bpy
import numpy as np
from color_tools import perceptual_grade_blender as addon
from color_tools.perceptual_grade_blender.integration.lifecycle import registered_session
from color_tools.perceptual_grade_blender.model import baking,gpu as compute
from color_tools.perceptual_grade_core.model import bake, bake_cache, boundary_polynomial, lut as cubes
from color_tools.perceptual_grade_blender.model import bake_gpu, boundary_gpu
from color_tools.perceptual_grade_core.model import cube_boundary


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


def product(application):
    """Resolve all measured adapters from the caller's original Session."""
    return tuple(application.component(name) for name in
                 ('graph.gpu', 'graph.grades', 'graph.lut', 'graph.nodes', 'scopes.sampling', 'scopes.jobs'))


class Recorder:
    """Measure foreground adapters; helper timings arrive with result receipts."""
    def __init__(self,application,coordination=False):self.application=application;self.active=False;self.lock=Lock();self.coordination=coordination

    def begin(self):
        self.stats={};self.events=[];self.start=time.perf_counter();self.active=True

    def record(self,name,start,end,event=False):
        with self.lock:
            item=self.stats.setdefault(name,{'calls':0,'sum_s':0.,'maximum_s':0.})
            item['calls']+=1;item['sum_s']+=end-start;item['maximum_s']=max(item['maximum_s'],end-start)
            if event:self.events.append(dict(name=name,start_s=start-self.start,end_s=end-self.start,thread=get_ident()))

    def wrap(self,function,label):
        @wraps(function)
        def measured(*args,**kwargs):
            if not self.active:return function(*args,**kwargs)
            name=label(*args,**kwargs) if callable(label) else label
            start=time.perf_counter();result=None
            try:
                result=function(*args,**kwargs);return result
            finally:
                end=time.perf_counter()
                with self.lock:
                    item=self.stats.setdefault(name,{'calls':0,'sum_s':0.,'maximum_s':0.})
                    item['calls']+=1;item['sum_s']+=end-start;item['maximum_s']=max(item['maximum_s'],end-start)
                    if (name.startswith(('ready.','packing.','scope.capture','scope.evaluate'))
                            or (name.startswith('publish.') and result is True)
                            or (self.coordination and (name.startswith('cpu.') or name in ('gpu.chunk','gpu.dispatch')))):
                        event={'name':name,'start_s':start-self.start,'end_s':end-self.start,'thread':get_ident()}
                        if name=='scope.capture' and result is not None:
                            event['lut_size']=result['signal'][0].size
                        if name=='scope.evaluate':event['lut_size']=args[0]['signal'][0].size
                        self.events.append(event)
        return measured

    def instrument(self,stack):
        gpu,grades,lut,nodes,sampling,jobs=product(self.application)
        targets=[(lut,'tick','timer'),(nodes,'bake_model','model_setup'),
            (lut,'compositor_helper','graph.helper_lookup'),
            (lut,'publish',lambda *a,**k:'publish.preview' if k.get('preview') else 'publish.final'),
            (jobs,'tick','scope.timer'),(sampling,'capture','scope.capture')]
        for owner,name,label in targets:
            stack.enter_context(replace_attribute(owner,name,self.wrap(getattr(owner,name),label)))


def elapsed(function):
    start=time.perf_counter();result=function();return result,time.perf_counter()-start


def cold_helpers(application):
    """A reproducible cold-helper boundary, using only owned child processes."""
    lut=application.component('graph.lut')
    runtime=application.app.execution.get_runtime()
    deadline=time.monotonic()+120
    while runtime.jobs:
        runtime.poll();time.sleep(.001)
        if time.monotonic()>deadline:raise TimeoutError('Cold helper reset could not settle numerical work')
    for helper in tuple(runtime.helpers.values()):
        helper.retiring_for_probe=True  # Deliberate cold boundary, not a GPU fault.
        helper.kill();helper.process.wait(timeout=10)
    runtime.poll()
    # A failed GPU needs a real conformance receipt. Settle the explicit probe
    # before measuring, then remove its helper so the timed workload stays cold.
    if runtime.gpu_status()['state']!='ready':
        runtime.retry_gpu().result(timeout=120)
        helper=runtime.helpers.get('gpu')
        if helper is not None:
            helper.retiring_for_probe=True
            helper.kill();helper.process.wait(timeout=10)
        runtime.poll()
    runtime.cache.clear();lut._ready.clear()


def reset(application,node):
    gpu,grades,lut,nodes,sampling,jobs=product(application)
    grades.assign_values(node.pg_grade,grades.defaults());grades.publish(node.pg_grade)
    lut.ensure(node,nodes.bake_model(node))


def settle_scope(application,node,view):
    gpu,grades,lut,nodes,sampling,jobs=product(application)
    deadline=time.perf_counter()+120
    while time.perf_counter()<deadline:
        sampling.get(node,nodes.grading_space(node),view);interval=jobs.tick()
        state=jobs._states[node.as_pointer()]
        if state['failed'] is not None:raise RuntimeError('Scope analysis failed')
        if state['completed']==state['spec']['key']:return
        time.sleep(interval or .016)
    raise TimeoutError('Scope warmup did not finish')


def trial(application,node,edit,recorder,view=None,uncached=False):
    gpu,grades,lut,nodes,sampling,jobs=product(application)
    reset(application,node)
    if view is not None:settle_scope(application,node,view)
    if uncached:
        cold_helpers(application)
    helpers={g.as_pointer() for g in bpy.data.node_groups if g.get('_pg_cube_op')}
    recorder.begin();edit();key=cubes.signature(nodes.bake_model(node))
    next_tick=recorder.start+lut.PREVIEW_DELAY;next_scope=recorder.start+.001
    next_draw=recorder.start;installed=None;scope_final=None
    previous=None if view is None else jobs._states[node.as_pointer()]['result']
    while time.perf_counter()<recorder.start+120:
        if view is not None and time.perf_counter()>=next_draw:
            sampling.get(node,nodes.grading_space(node),view);next_draw=time.perf_counter()+.016
            if next_scope==float('inf'):next_scope=time.perf_counter()+.001
        if time.perf_counter()>=next_tick:
            interval=lut.tick();next_tick=time.perf_counter()+(interval if interval is not None else .016)
        image=lut.image_for(node)
        if installed is None and image is not None and image.get('_pg_cube_signature')==key and image.get('_pg_cube_size')==cubes.SIZE:
            installed=time.perf_counter()-recorder.start
        if view is not None and time.perf_counter()>=next_scope:
            interval=jobs.tick();next_scope=time.perf_counter()+interval if interval is not None else float('inf')
            state=jobs._states[node.as_pointer()];result=state['result']
            if state['failed'] is not None:raise RuntimeError('Scope analysis failed')
            if result is not None and result is not previous:
                previous=result
                current_final=((key,cubes.SIZE) in result['_scope_provenance'] and
                    result['_scope_key']==state['spec']['key'] and
                    state['completed']==state['spec']['key'])
                now=time.perf_counter()-recorder.start
                recorder.events.append(dict(name='scope.publish',start_s=now,end_s=now,
                    provenance=result['_scope_provenance'],current_final=current_final))
                if current_final:scope_final=now
        if installed is not None and (view is None or scope_final is not None):break
        wake=min(next_tick,next_draw,next_scope) if view is not None else next_tick
        time.sleep(max(0.,wake-time.perf_counter()))
    else:raise TimeoutError(node.get('_pg_bake_error','') or 'LUT did not finish')
    recorder.active=False
    events={item['name']:item for item in recorder.events}
    diagnostics=dict(lut.installed_cube(node).diagnostics)
    return dict(installed_s=installed,preview_installed_s=events.get('publish.preview',events['publish.final'])['end_s'],
        calculated_s=max(0.,diagnostics['worker_calculated_at']-recorder.start),
        packed_s=max(0.,diagnostics['worker_packed_at']-recorder.start),
        final_publication_s=events['publish.final']['end_s']-events['publish.final']['start_s'],
        backend=node['_pg_cube_backend'],device=node.get('_pg_cube_device',''),
        scope_final_s=scope_final,math_cache_bytes=diagnostics['worker_cache_bytes'],
        worker_diagnostics=diagnostics,events=recorder.events,stats=recorder.stats,
        helpers_created=[g.get('_pg_cube_op') for g in bpy.data.node_groups
                         if g.get('_pg_cube_op') and g.as_pointer() not in helpers])


def scope_image(node):
    """Fixed HDR input at the existing scope resolution, without an image reload."""
    width,height=256,192;rng=np.random.default_rng(20261010)
    rgb=rng.random((height,width,3),dtype=np.float32)
    rgb*=np.exp2(np.linspace(-10,10,width,dtype=np.float32))[None,:,None]
    pixels=np.concatenate((rgb,np.ones((height,width,1),np.float32)),-1)
    image=bpy.data.images.new('Scope profile HDR',width=width,height=height,float_buffer=True,alpha=True)
    image.colorspace_settings.name='Non-Color';image.alpha_mode='CHANNEL_PACKED'
    image.pixels.foreach_set(pixels.ravel());image.update();image.pack()
    if image.is_dirty:raise RuntimeError('Profiling input must not invalidate itself while timers run')
    source=node.id_data.nodes.new('CompositorNodeImage');source.image=image
    node.id_data.links.new(source.outputs['Image'],node.inputs['Color'])


def publication(cube):
    """Separate reproduction, not additive to the concurrent installation timeline."""
    timings={}
    image,timings['allocate_s']=elapsed(lambda:bpy.data.images.new('Publication profile',
        width=cubes.ATLAS_WIDTH,height=cubes.atlas_height(cube.size,4),float_buffer=True,alpha=True))
    try:
        image.colorspace_settings.name='Non-Color';image.alpha_mode='CHANNEL_PACKED'
        image.use_half_precision=False;image.file_format='OPEN_EXR'
        pixels,timings['rgbe_s']=elapsed(cube.packed_pixels)
        _,timings['upload_s']=elapsed(lambda:image.pixels.foreach_set(pixels.ravel()))
        _,timings['update_s']=elapsed(image.update)
        _,timings['pack_s']=elapsed(image.pack)
        return timings
    finally:bpy.data.images.remove(image)


def line_sections(function,arguments,markers,keywords=None):
    """Time existing source blocks; do not copy production code."""
    source,first=inspect.getsourcelines(function);labels={};label='setup'
    for i,line in enumerate(source):
        label=next((name for text,name in markers if line.strip().startswith(text)),label)
        labels[first+i]=label
    parts={};state={};code=getattr(function,'__func__',function).__code__
    def trace(frame,event,arg):
        if frame.f_code is not code:return None
        now=time.perf_counter()
        if 'last' in state:
            name=state['label'];parts[name]=parts.get(name,0.)+now-state['last']
        state.update(last=now,label=labels.get(frame.f_lineno,'setup'))
        if event=='return':state['locals']=frame.f_locals.copy()
        return trace
    previous=sys.gettrace();sys.settrace(trace)
    try:result,total=elapsed(lambda:function(*arguments,**(keywords or {})))
    finally:sys.settrace(previous)
    return result,dict(total_s=total,sections_s=parts),state['locals']


def preview_graph_report(output,repeats):
    """Separate construction from binding; leave grading and LUT math untouched."""
    output.mkdir(parents=True,exist_ok=True);trials=[]
    markers=[('tag=','find_helper'),('tree=bpy.data.node_groups.new','create_group'),
        ('for direction,items','interface'),('source=tree.nodes.new','io_nodes'),
        ('g=Graph','address_math'),('for value,socket','wire_outputs'),('from .optimize','reductions')]
    bpy.ops.wm.read_factory_settings(use_empty=True);addon.register()
    application=registered_session()
    gpu,grades,lut,nodes,sampling,jobs=product(application)
    optimize=application.component('graph.optimize')
    try:
        tree=bpy.data.node_groups.new('Preview helper profile','CompositorNodeTree')
        node=nodes.create_grade(tree);lut.ensure(node,nodes.bake_model(node))
        address=next(n for n in node.node_tree.nodes if n.get('_pg_cube_address'))
        final=address.node_tree
        for _ in range(repeats):
            address.node_tree=final
            for helper in list(bpy.data.node_groups):
                if helper.get('_pg_cube_op')==f'{lut.SCHEMA}:Address:{cubes.PREVIEW_SIZE}':
                    bpy.data.node_groups.remove(helper,do_unlink=True)
            calls={}
            def measured(function,name):
                def wrapped(*args,**kwargs):
                    value,duration=elapsed(lambda:function(*args,**kwargs))
                    calls[name]=calls.get(name,0.)+duration
                    return value
                return wrapped
            with ExitStack() as stack:
                for owner,name in ((lut.Graph,'coordinates'),(lut.Graph,'uv'),
                        (optimize,'remove_dead_nodes'),(optimize,'fold_multiply_adds')):
                    stack.enter_context(replace_attribute(owner,name,measured(getattr(owner,name),name)))
                helper,parts,_=line_sections(lut.compositor_helper,('Address',cubes.PREVIEW_SIZE),markers)
            _,bind=elapsed(lambda:setattr(address,'node_tree',helper))
            cached,reuse=elapsed(lambda:lut.compositor_helper('Address',cubes.PREVIEW_SIZE))
            assert cached==helper
            trials.append(dict(**parts,inclusive_s=calls,bind_s=bind,reuse_s=reuse,
                nodes=len(helper.nodes),links=len(helper.links),fused_pairs=helper.get('_pg_fused_madd',0)))
    finally:
        addon.unregister();bpy.ops.wm.read_factory_settings(use_empty=True)
    data=dict(blender=bpy.app.version_string,trials=trials,
        limitations=['Isolated main-thread helper creation after Grade/identity setup, with no bake workers or scope activity.',
            'Construction is line-traced. Inclusive function timings overlap the construction sections.',
            'No compositor render, shader compilation or visible-frame latency is measured.'])
    (output/'report.json').write_text(json.dumps(data,indent=2)+'\n')
    lines=['# First-use 33³ preview address graph','',f'Blender {data["blender"]}; {repeats} fresh helper constructions.',
        '',f'{trials[0]["nodes"]} nodes, {trials[0]["links"]} links, {trials[0]["fused_pairs"]} multiply/add pairs folded.',
        '','| Section | Median ms |','| --- | ---: |']
    for key in trials[0]['sections_s']:
        lines.append(f'| {key} | {1000*median(t["sections_s"].get(key,0.) for t in trials):.3f} |')
    for key in ('total_s','bind_s','reuse_s'):
        lines.append(f'| {key} | {1000*median(t[key] for t in trials):.3f} |')
    lines+=['','Inclusive components (do not add to the sections above):','',
        '| Function | Median ms |','| --- | ---: |']
    for key in trials[0]['inclusive_s']:
        lines.append(f'| {key} | {1000*median(t["inclusive_s"][key] for t in trials):.3f} |')
    lines+=['',*(f'- {item}' for item in data['limitations']),'']
    (output/'summary.md').write_text('\n'.join(lines))
    print(f'Reports: {output}/summary.md and report.json',flush=True)


def component_report(application,node,repeats):
    gpu,grades,lut,nodes,sampling,jobs=product(application)
    """Separate replay: CPU sections are serial; GPU passes include readback."""
    import gpu as driver
    driver.init()
    reset(application,node);nodes.write_chromatic(node,{'c_high_2':1.})
    kernel=baking.kernel(nodes.bake_model(node));rgb=cubes.lattice().astype('f4')
    entry=kernel.enter(rgb);toned=kernel.tone_state(entry);graded=kernel.grade(toned)
    markers={
        'entry':[('rgb=np.','input_cast'),('cones=self.native','cone_encode'),
            ('p=np.power','response_encode'),('a=','opponent_coordinates'),
            ('ja=np.sign','signed_lightness'),('return np.stack','assemble_raw_appearance')],
        'export':[('q=np.','classify_energy'),('ids=np.flatnonzero','test_direct_rgb'),
            ('c=np.hypot','escape_ray'),('bound=np.where','cube_response_bracket'),
            ('saved,legal=candidate','neutral_ray'),('seed=self.capacity','fitted_capacity_seed'),
            ('for _ in range(24)','validated_bisection'),('out[ids]','assemble_tested_rgb')]}
    result=dict(samples=len(rgb),case='White Ch→C +1',cpu=[],gpu={},
        limitations=['CPU blocks replay the whole 65³ grid serially, without helper row caches or production chunk scheduling.',
            'Line tracing and wrappers add overhead; section timings are diagnostic, not additive to drag latency.',
            'GPU components are isolated production GLSL functions; each pass includes texture upload, dispatch and synchronous readback.',
            'GPU component times overlap in scope and each pays transport overhead; do not sum them.'])
    for _ in range(repeats):
        costs={};current=['entry']
        def measure(function,name):
            def wrapped(*args,**kwargs):
                value,duration=elapsed(lambda:function(*args,**kwargs))
                key=current[0]+'.'+name;costs[key]=costs.get(key,0.)+duration
                return value
            return wrapped
        with ExitStack() as stack:
            for owner,name in ((bake.Kernel,'capacity'),(bake.Kernel,'decode'),
                    (boundary_polynomial.PolynomialTable,'capacity'),
                    (boundary_polynomial.PolynomialTable,'field'),
                    (boundary_polynomial.PolynomialSelector,'select'),
                    (boundary_polynomial.PolynomialSelector,'edge_address'),
                    (boundary_polynomial.PolynomialSelector,'edge_value')):
                stack.enter_context(replace_attribute(owner,name,measure(getattr(owner,name),name)))
            entered,incoming,_=line_sections(kernel.enter,(rgb,),markers['entry'])
            tonal,tonal_seconds=elapsed(lambda:kernel.tonal(entered,kernel.color.chroma_fit))
            graded,grade_seconds=elapsed(lambda:kernel.grade(entered,{kernel.color.chroma_fit:tonal}))
            current[0]='export';output,outgoing,_=line_sections(kernel.export,(graded,),markers['export'])
        if not np.isfinite(output).all():raise ArithmeticError('Profile export is nonfinite')
        result['output_range']=dict(minimum=float(output.min()),maximum=float(output.max()),
            outside_cube_pixels=int(np.count_nonzero(np.any((output<0)|(output>1024),axis=-1))))
        result['cpu'].append(dict(entry=incoming,tonal_s=tonal_seconds,grade_s=grade_seconds,
            export=outgoing,inclusive_lookup_s=costs))
    physical_capacity=kernel.capacity(graded[:,3],graded[:,1:3])[:,None]
    main=r'''
void main() {
    int id=int(gl_GlobalInvocationID.x);if(id>=sample_count)return;
    ivec2 address=ivec2(id%256,id/256);vec4 p=texelFetch(input_pixels,address,0),result;
    if(operation==0)result=p;
    else if(operation==1)result=pg_enter(p.xyz);
    else if(operation==2)result=pg_grade(p);
    else if(operation==3)result=vec4(pg_export(p),1.0);
    else result=vec4(pg_physical_capacity(p.w,p.yz),0.0,0.0,0.0);
    imageStore(output_pixels,address,result);
}
'''
    def source(data,offsets,expanded):
        return bake_gpu.source(data,offsets,expanded).split('void main()',1)[0]+main
    program=boundary_gpu.Program(kernel.data,source,True,kernel.table.expanded)
    values=bake_gpu.parameters(kernel)
    program.parameters=program.gpu.types.GPUTexture((256,1),format='R32F',
        data=program.gpu.types.Buffer('FLOAT',(1,256),values))
    cases=(('transport',0,entry,entry),('entry',1,rgb,entry),('grade',2,toned,graded),
        ('export',3,graded,output),('physical_capacity',4,graded,physical_capacity))
    for name,operation,points,expected in cases:
        actual=program.evaluate(points,operation)
        # The isolated entry is sensitive near black; use the same mixed relative/absolute accounting.
        count=expected.shape[-1];error=np.max(abs(actual[:,:count].astype(float)-expected),axis=-1)
        limit=np.maximum(.001*np.max(abs(expected),axis=-1),1e-7)
        if np.any(error>limit):raise ArithmeticError('Isolated GPU '+name+' disagrees with CPU')
        times=[elapsed(lambda:program.evaluate(points,operation))[1] for _ in range(repeats)]
        result['gpu'][name]=dict(samples=len(points),seconds=times,max_tolerance_fraction=float(np.max(error/limit)))
    return result


def compare_selectors(output,baseline,repeats):
    """Compare installed helper package variants, including their cold startup."""
    import shutil
    import tempfile
    from color_tools.blender_runtime.execution.runtime import ExecutionRuntime
    output.mkdir(parents=True,exist_ok=True)
    required=('boundary_polynomial.py','boundary_gpu.py')
    for name in required:
        if not (baseline/name).is_file():raise ValueError('Missing selector baseline: '+name)
    data={'backends':{},'baseline_sha256':{name:hashlib.sha256((baseline/name).read_bytes()).hexdigest()
        for name in required},'limitations':[
        'Each variant executes in a separate installed-package helper with fresh process and numerical caches.',
        'Timings include helper startup, shader compilation, transfer and foreground installation.',
        'Software GPU/headless output; no visible-frame latency claim.']}
    bpy.ops.wm.read_factory_settings(use_empty=True);addon.register()
    application=registered_session()
    gpu,grades,lut,nodes,sampling,jobs=product(application)
    original=application.app.execution.get_runtime();runtimes={}
    try:
        with tempfile.TemporaryDirectory(prefix='pg-selector-packages-') as temporary:
            directory=Path(temporary)
            for name in ('current','previous'):
                package=directory/name
                shutil.copytree(Path(addon.__file__).absolute().parent.parent,package,
                    ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
                if name=='previous':
                    for filename in required:
                        component='perceptual_grade_core' if filename=='boundary_polynomial.py' else 'perceptual_grade_blender'
                        shutil.copyfile(baseline/filename,package/component/'model'/filename)
                runtimes[name]=ExecutionRuntime(directory/(name+'-sessions'), app=application.app,
                    machines=original.machines, package=package,
                    profile=original.profile, seal=original.seal, launcher=original.launcher,
                    worker_host=original.worker_host, host_settings=original.host_settings,
                    environment=original.environment)
            try:
                for backend in ('CPU','GPU'):
                    tree=bpy.data.node_groups.new(backend+' selector comparison','CompositorNodeTree')
                    node=nodes.create_grade(tree);grades.ensure(node)
                    with ExitStack() as stack:
                        if backend=='CPU':stack.enter_context(replace_attribute(gpu,'acquire',return_value=(None,None)))
                        recorder=Recorder(application);recorder.instrument(stack)
                        trials={'previous':[],'current':[]};identical=[]
                        for i in range(repeats):
                            values={}
                            for name in (('previous','current') if i%2==0 else ('current','previous')):
                                jobs.clear();lut.clear(release_gpu=True)
                                application.app.execution._runtime=runtimes[name]
                                item=trial(application,node,lambda:nodes.write_chromatic(node,{'c_high_2':1.+i*.01}),recorder,uncached=True)
                                if item['backend']!=backend:raise RuntimeError('Requested backend did not execute')
                                trials[name].append(item);values[name]=lut.installed_cube(node).values.copy()
                            np.testing.assert_array_equal(values['current'],values['previous']);identical.append(True)
                        data['backends'][backend]=dict(trials=trials,pair_outputs_identical=identical)
            finally:
                jobs.clear();lut.clear(release_gpu=True)
                application.app.execution._runtime=original
                for runtime in runtimes.values():runtime.shutdown()
    finally:
        application.app.execution._runtime=original
        addon.unregister();bpy.ops.wm.read_factory_settings(use_empty=True)
    (output/'report.json').write_text(json.dumps(data,indent=2)+'\n')
    lines=['# Selector helper-package comparison','',
        '| Backend / variant | 33³ installed ms | 65³ installed ms |','| --- | ---: | ---: |']
    for backend,entry in data['backends'].items():
        for name,trials in entry['trials'].items():
            lines.append('| '+backend+' / '+name+' | '+' | '.join(f'{1000*median(t[k] for t in trials):.2f}'
                for k in ('preview_installed_s','installed_s'))+' |')
    lines+=['','Paired outputs are array-identical.','',*data['limitations']]
    (output/'summary.md').write_text('\n'.join(lines)+'\n')


def report(output,repeats,scopes=False,details=False,details_only=False,uncached=False,coordination=False):
    output.mkdir(parents=True,exist_ok=True)
    cpu=platform.processor()
    if Path('/proc/cpuinfo').exists():
        cpu=next((line.split(':',1)[1].strip() for line in Path('/proc/cpuinfo').read_text().splitlines()
                  if line.startswith('model name')),cpu)
    data={'environment':dict(timestamp=datetime.now().astimezone().isoformat(),platform=platform.platform(),
        cpu=cpu,logical_cpus=os.cpu_count(),python=sys.version.split()[0],numpy=np.__version__,
        blender=bpy.app.version_string,cache_sha256=hashlib.sha256(Path(baking.__file__).with_name('d65_boundary.npz').read_bytes()).hexdigest()),
        'limitations':['Headless Blender; backend/device receipts identify the GPU used. Visible compositor frame timing is not measured.',
            'Clock starts at a committed control edit; raw mouse-event delivery and the nominal 60 Hz Stage-3 commit timer are excluded.',
            'Each edit settles before the next; this does not measure a continuous stream of cancellations.',
            ('Scopes active on a deterministic 256 x 192 HDR input; no comparison image.' if scopes else 'No scopes active.')+
                ' Timer callbacks run at production intervals; scheduling adds jitter.',
            'Foreground adapter timings and helper diagnostics are measured separately; process clocks use the same host monotonic clock.',
            ('Helpers restart before each timed edit; this includes process startup, lookup and shader initialization.'
             if uncached else 'Warm edits follow an unmeasured cache warmup for each control family.')],
        'backends':{}}
    if coordination:data['limitations'].append('Each backend prepares its own missing 33³ graph helper during node setup, before timed edits.')
    if details_only:data=json.loads((output/'report.json').read_text())
    bpy.ops.wm.read_factory_settings(use_empty=True);addon.register()
    application=registered_session()
    gpu,grades,lut,nodes,sampling,jobs=product(application)
    try:
        if details_only:
            tree=bpy.data.node_groups.new('Component profile','CompositorNodeTree')
            node=nodes.create_grade(tree);grades.ensure(node)
        for backend in (() if details_only else ('CPU','GPU')):
            jobs.clear();lut.clear(release_gpu=True)
            for handle in tuple(application.app.execution.get_runtime().handles.values()):handle.cancel()
            deadline=time.monotonic()+120
            while application.app.execution.get_runtime().jobs:
                application.app.execution.get_runtime().poll();time.sleep(.001)
                if time.monotonic()>deadline:raise TimeoutError('Backend reset could not retire jobs')
            cold_helpers(application)
            if coordination:
                # Both backends must pay for their own preview helper setup.
                for helper in list(bpy.data.node_groups):
                    if helper.get('_pg_cube_op')==f'{lut.SCHEMA}:Address:{cubes.PREVIEW_SIZE}':
                        bpy.data.node_groups.remove(helper,do_unlink=True)
            tree=bpy.data.node_groups.new(backend+' Grade profile','CompositorNodeTree')
            setup=[];helper=lut.compositor_helper
            def prepare(kind,size=cubes.SIZE,tree_type='CompositorNodeTree'):
                value,duration=elapsed(lambda:helper(kind,size,tree_type))
                if kind=='Address' and size==cubes.PREVIEW_SIZE:setup.append(duration)
                return value
            with replace_attribute(lut,'compositor_helper',prepare):
                node=nodes.create_grade(tree);grades.ensure(node)
            if scopes:scope_image(node)
            item={'cases':{},'empty_lattice_cache':uncached,'preview_helper_setup_s':sum(setup)}
            if not uncached:item['warmup']={}
            with ExitStack() as stack:
                if backend=='CPU':stack.enter_context(replace_attribute(gpu,'acquire',return_value=(None,None)))
                _,item['cold_identity_install_s']=elapsed(lambda:lut.ensure(node,nodes.bake_model(node)))
                if node['_pg_cube_backend']!=backend:raise RuntimeError('Requested backend did not execute')
                diagnostics=lut.installed_cube(node).diagnostics
                item['lookup_preparation_s']=diagnostics['worker_preparation_s']
                if backend=='GPU':item['shader_creation_s']=diagnostics['shader_creation_s']
                recorder=Recorder(application,coordination);recorder.instrument(stack)
                for name,writer,control,value in (('stage2_midtones',nodes.write_tone,'input_midtones',42.),
                        ('stage3_white_chroma',nodes.write_chromatic,'c_high_2',1.),
                        ('stage3_white_chroma_10',nodes.write_chromatic,'c_high_2',10.)):
                    view=(() if name=='stage2_midtones' else (3,False)) if scopes else None
                    if not uncached:item['warmup'][name]=trial(application,node,lambda:writer(node,{control:value-.01}),recorder,view)
                    trials=[]
                    for i in range(repeats):
                        trials.append(trial(application,node,lambda:writer(node,{control:value+i*.01}),recorder,view,uncached))
                        print(f'{backend} {name} {i+1}/{repeats}: {trials[-1]["installed_s"]:.3f} s installed 65³',flush=True)
                    item['cases'][name]=trials
                baker=lut._states[node.as_pointer()]['baker']
                item['publication']={str(c.size):[publication(c) for _ in range(repeats)]
                    for c in (baker.preview,baker.cube) if c is not None}
            data['backends'][backend]=item
            (output/'report.json').write_text(json.dumps(data,indent=2)+'\n')
        jobs.clear()
        if details or details_only:data['components']=component_report(application,node,repeats)
        (output/'report.json').write_text(json.dumps(data,indent=2)+'\n')
    finally:
        addon.unregister();bpy.ops.wm.read_factory_settings(use_empty=True)
    summarize(data,output)


def coordination_summary(data):
    lines=['','## Foreground and helper coordination','',
        'Actual median-total white-chroma +1 trial per backend. Helper durations include preparation and numerical packing; publication is measured in foreground Blender.',
        '', '| Backend | Helper preparation | Numerical loop through final samples | Final packing | Longest foreground timer |',
        '| --- | ---: | ---: | ---: | ---: |']
    for name,item in data['backends'].items():
        trials=item['cases']['stage3_white_chroma']
        trial=sorted(trials,key=lambda t:t['installed_s'])[len(trials)//2]
        diagnostics=trial['worker_diagnostics']
        preparation=diagnostics['worker_preparation_s']
        calculated=diagnostics['worker_calculated_at']-diagnostics['worker_started_at']-preparation
        values=(preparation,calculated,diagnostics['worker_packing_s'],trial['stats']['timer']['maximum_s'])
        lines.append('| '+name+' | '+' | '.join(f'{1000*value:.2f} ms' for value in values)+' |')
    lines+=['','The numerical loop includes preview packing and checkpoint/IPC work. These columns do not include process startup or payload transfer and are not an additive end-to-end decomposition.']
    return lines


def summarize(data,output):
    uncached=all(b.get('empty_lattice_cache') for b in data['backends'].values())
    lines=['# Regular Grade CPU/GPU installation profile','',json.dumps(data['environment'],indent=2),'',
        ('Median milliseconds with fresh helper processes.' if uncached else 'Median milliseconds for warm Stage 2/3 edits.')+
        ' Preview vertices are reused in the final 65³ LUT.','',
        '| Backend / control | Preview installed | All samples calculated | RGBE ready | Final publication | Final installed |',
        '| --- | ---: | ---: | ---: | ---: | ---: |']
    for backend,item in data['backends'].items():
        for name,trials in item['cases'].items():
            lines.append('| '+backend+' / '+name+' | '+' | '.join(f'{1000*median(t[k] for t in trials):.2f}'
                for k in ('preview_installed_s','calculated_s','packed_s','final_publication_s','installed_s'))+' |')
    if uncached:
        lines+=['','Setup is separate from edit timing:','',
            '| Backend | Preview helper preparation | Lookup preparation | First identity installation | Shader creation (included in installation) |',
            '| --- | ---: | ---: | ---: | ---: |']
        for backend,item in data['backends'].items():
            helper=f'{1000*item["preview_helper_setup_s"]:.2f} ms' if 'preview_helper_setup_s' in item else 'Not measured'
            lines.append(f'| {backend} | {helper} | {1000*item["lookup_preparation_s"]:.2f} ms | '+
                f'{1000*item["cold_identity_install_s"]:.2f} ms | {1000*item.get("shader_creation_s",0):.2f} ms |')
        if all('helpers_created' in t for b in data['backends'].values() for trials in b['cases'].values() for t in trials):
            count=sum(len(t['helpers_created']) for b in data['backends'].values() for trials in b['cases'].values() for t in trials)
            lines+=['',f'Helper groups created during timed edits: {count}.']
    if any(t.get('scope_final_s') is not None for b in data['backends'].values() for runs in b['cases'].values() for t in runs):
        lines+=['','| Backend / control | Final-matching scope published |','| --- | ---: |']
        for backend,item in data['backends'].items():
            for name,trials in item['cases'].items():
                lines.append(f'| {backend} / {name} | {1000*median(t["scope_final_s"] for t in trials):.2f} ms |')
    lines+=coordination_summary(data)
    if 'components' in data:
        detail=data['components'];lines+=['','## Isolated 65³ component replay','',
            'CPU milliseconds, one serial full-grid call, separate from process startup and production chunk scheduling.','',
            '| Path / section | Median ms |','| --- | ---: |']
        for name in ('entry','export'):
            lines.append(f'| {name}: total | {1000*median(t[name]["total_s"] for t in detail["cpu"]):.2f} |')
            for section in detail['cpu'][0][name]['sections_s']:
                lines.append(f'| {name}: {section} | {1000*median(t[name]["sections_s"].get(section,0) for t in detail["cpu"]):.2f} |')
        if 'tonal_s' in detail['cpu'][0]:
            lines+=['',f'White Ch→C +1 tonal weights: {1000*median(t["tonal_s"] for t in detail["cpu"]):.2f} ms; '+
                f'Stage 3 using those weights: {1000*median(t["grade_s"] for t in detail["cpu"]):.2f} ms. Stage 2 is inactive in this serial case.']
        if 'output_range' in detail:
            bounds=detail['output_range']
            lines+=['',f'Validated cube-export RGB range: [{bounds["minimum"]:.9g}, {bounds["maximum"]:.9g}]; '+
                f'{bounds["outside_cube_pixels"]:,} pixels have an out-of-cube channel.']
        lines+=['','| Lookup component (inclusive within CPU times above) | Median ms |','| --- | ---: |']
        for name in detail['cpu'][0]['inclusive_lookup_s']:
            lines.append(f'| {name} | {1000*median(t["inclusive_lookup_s"][name] for t in detail["cpu"]):.2f} |')
        lines+=['','Isolated GPU passes, including upload/dispatch/readback each time; not additive.','',
            '| Component | Median ms |','| --- | ---: |']
        for name,item in detail['gpu'].items():lines.append(f'| {name} | {1000*median(item["seconds"]):.2f} |')
        lines+=['',*(f'- {item}' for item in detail['limitations'])]
    lines+=['','Function timings, individual trials, cache bytes and separate publication operations are in report.json.',
        '',*(f'- {item}' for item in data['limitations']),'']
    (output/'summary.md').write_text('\n'.join(lines))
    print(f'Reports: {output}/summary.md and report.json',flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir',type=Path,required=True)
    parser.add_argument('--repeats',type=int,default=3)
    parser.add_argument('--scopes',action='store_true',help='Measure scopes concurrently at their current sampling size')
    parser.add_argument('--details',action='store_true',help='Replay mapping components separately from scheduler timing')
    parser.add_argument('--details-only',action='store_true',help='Refresh component replay in an existing report without repeating its timing trials')
    parser.add_argument('--uncached',action='store_true',help='Restart owned helpers before every edit, including startup and numerical preparation in timing')
    parser.add_argument('--coordination',action='store_true',help='Trace cache lock and publication sections; include first-use preview helpers for each backend')
    parser.add_argument('--summarize-only',action='store_true',help='Summarize saved report.json without running measurements')
    parser.add_argument('--preview-graph-only',action='store_true',help='Break down first-use 33³ helper creation without baking edits')
    parser.add_argument('--compare-selector',type=Path,help='Directory with previous boundary_polynomial.py and boundary_gpu.py; alternate complete empty-cache installations')
    args=parser.parse_args()
    if args.repeats<1:parser.error('--repeats must be positive')
    if args.compare_selector:compare_selectors(args.output_dir,args.compare_selector,args.repeats)
    elif args.preview_graph_only:preview_graph_report(args.output_dir,args.repeats)
    elif args.summarize_only:summarize(json.loads((args.output_dir/'report.json').read_text()),args.output_dir)
    else:report(args.output_dir,args.repeats,args.scopes,args.details,args.details_only,args.uncached,args.coordination)
