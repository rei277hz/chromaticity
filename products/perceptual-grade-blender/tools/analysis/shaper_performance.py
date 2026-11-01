"""Fresh-process baking and real Blender final-render comparison of two shapers."""
import argparse
import hashlib
import json
import os
from pathlib import Path
from statistics import median
import subprocess
import sys
import tempfile
import time
import numpy as np
from tools.analysis.lut_shapers import Shaper,tetrahedral

SHAPERS={'current':Shaper(),'candidate':Shaper('log_tanh',.01,2.,.25)}
CASES=('tone','chroma','hue','mixed','mixed_tone','strong_chroma')
# Blender later prepends its embedded script paths, where a bootstrap bpy
# package assumes _bpy is already loaded. Children need the original wheel path.
CHILD_IMPORT_PATH=tuple(sys.path)


def timed(function):
    start=time.perf_counter();result=function();return result,time.perf_counter()-start


def save(path,value):
    path.write_text(json.dumps(value,indent=2,allow_nan=False)+'\n')


def initialize(backend):
    import bpy
    gpu=None;renderer='CPU'
    if backend=='GPU':
        import gpu
        bpy.context.preferences.system.gpu_backend='OPENGL';gpu.init()
        renderer=gpu.platform.renderer_get()
        if 'llvmpipe' not in renderer.lower():raise RuntimeError('llvmpipe is required')
    return bpy,gpu,renderer


def bake_worker(output,variant,backend):
    (bpy,gpu,renderer),initialization=timed(lambda:initialize(backend))
    from color_tools.perceptual_grade_blender.model import baking,gpu as compute
    from tools.analysis.grade_shaper_error import CPU,GPU,resource_hashes
    from tools.analysis.photo_grade import extension_model
    from tools.analysis.photo_stack import cases
    shaper=SHAPERS[variant];_,context=timed(baking.resource);program=None
    program_seconds=0.
    if backend=='GPU':
        start=time.perf_counter();kernel=baking.kernel(extension_model(cases()['reset']))
        program=compute.Program(kernel);compute.validate_program(program,kernel)
        program_seconds=time.perf_counter()-start
    result=dict(kind='bake',variant=variant,shaper=shaper.to_dict(),backend=backend,
        renderer=renderer,blender=bpy.app.version_string,d65_sha256=resource_hashes(),
        initialize_seconds=initialization,d65_context_seconds=context,
        gpu_program_setup_seconds=program_seconds,cases={})
    for name in CASES:
        model,model_seconds=timed(lambda:extension_model(cases()[name]))
        start=time.perf_counter()
        baker=CPU(shaper,model,True,True) if backend=='CPU' else GPU(shaper,model,program,True,True,renderer)
        cube=baker.finish();seconds=time.perf_counter()-start
        result['cases'][name]=dict(model_seconds=model_seconds,bake_pack_seconds=seconds,
            cube_sha256=hashlib.sha256(cube.values.tobytes()).hexdigest(),**cube.diagnostics)
        if name=='mixed_tone':
            np.save(output/'cube.npy',cube.values)
            np.save(output/'packed.npy',cube.prepared_pixels)
        print(variant,backend,name,f'{seconds*1000:.3f} ms',flush=True)
    compute.clear();save(output/'result.json',result)


def scene_setup(bpy,width,height,backend):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.wm.set_working_color_space(working_space='ACEScg')
    scene=bpy.context.scene;scene.render.engine='CYCLES'
    scene.cycles.device='CPU';scene.cycles.samples=1;scene.cycles.use_denoising=False
    scene.render.resolution_x=width;scene.render.resolution_y=height
    scene.render.resolution_percentage=100;scene.render.use_border=False
    scene.render.use_persistent_data=False;scene.render.use_compositing=True
    scene.render.compositor_device=backend;scene.render.compositor_precision='AUTO'
    scene.render.image_settings.file_format='OPEN_EXR'
    scene.render.image_settings.color_mode='RGBA';scene.render.image_settings.color_depth='32'
    scene.render.image_settings.color_management='OVERRIDE'
    scene.render.image_settings.linear_colorspace_settings.name='scene_linear'
    camera=bpy.data.objects.new('Timing camera',bpy.data.cameras.new('Timing camera'))
    scene.collection.objects.link(camera);scene.camera=camera
    world=bpy.data.worlds.new('Timing world');world.use_nodes=True;scene.world=world
    return scene


def make_image(bpy,name,rgba,alpha):
    height,width=rgba.shape[:2]
    image=bpy.data.images.new(name,width=width,height=height,float_buffer=True,alpha=True)
    image.colorspace_settings.name='Non-Color';image.alpha_mode=alpha;image.use_half_precision=False
    image.pixels.foreach_set(np.asarray(rgba,dtype='f4').ravel());image.update()
    return image


def render_worker(output,variant,backend,input_path,cube_path,packed_path):
    (bpy,gpu,renderer),initialization=timed(lambda:initialize(backend))
    from color_tools.perceptual_grade_blender.machines import create_machines
    from color_tools.perceptual_grade_blender.session import Session
    application=Session(create_machines())
    try:
        lut=application.component('graph.lut')
        from tools.analysis.shaper_graph import shaper_graph
        rgb=np.load(input_path,allow_pickle=False);height,width=rgb.shape[:2]
        scene,scene_seconds=timed(lambda:scene_setup(bpy,width,height,backend))
        start=time.perf_counter()
        tree=bpy.data.node_groups.new('Shaper render study','CompositorNodeTree')
        tree.interface.new_socket(name='Image',in_out='OUTPUT',socket_type='NodeSocketColor')
        rgba=np.concatenate((rgb,np.ones((height,width,1),dtype='f4')),-1)
        source=tree.nodes.new('CompositorNodeImage');source.image=make_image(bpy,'Photographic samples',rgba,'PREMUL')
        target=tree.nodes.new('NodeGroupOutput');target.is_active_output=True
        if variant=='passthrough':value=source.outputs['Image']
        else:
            with shaper_graph(lut,SHAPERS[variant]):value=lut.compositor_lookup(tree,source.outputs['Image'])
            atlas=make_image(bpy,'Baked RGBE coefficients',np.load(packed_path,allow_pickle=False),'CHANNEL_PACKED')
            for node in tree.nodes:
                if node.get('_pg_cube_image'):node.image=atlas
        tree.links.new(value,target.inputs['Image']);scene.compositing_node_group=tree
        setup_seconds=time.perf_counter()-start
        reads=sum(n.bl_idname=='CompositorNodeMapUV' for n in tree.nodes)
        if reads!=(0 if variant=='passthrough' else 4):raise AssertionError('Unexpected LUT image-read count')
        address_nodes=sum(len(n.node_tree.nodes) for n in tree.nodes if n.get('_pg_cube_address'))
        events=[]
        def before(*_):events.append(('before',time.perf_counter()))
        def after(*_):events.append(('after',time.perf_counter()))
        bpy.app.handlers.composite_pre.append(before);bpy.app.handlers.composite_post.append(after)
        try:status,render_seconds=timed(lambda:bpy.ops.render.render())
        finally:
            bpy.app.handlers.composite_pre.remove(before);bpy.app.handlers.composite_post.remove(after)
        if 'FINISHED' not in status:raise ArithmeticError('Render failed: '+repr(status))
        # These job handlers need not fire during final rendering. A missing
        # interval is unavailable, never zero; validate the rendered pixels below.
        composite_seconds=(events[1][1]-events[0][1]
            if [kind for kind,_ in events]==['before','after'] else None)
        exr=output/'render.exr'
        _,save_seconds=timed(lambda:bpy.data.images['Render Result'].save_render(str(exr),scene=scene))
        start=time.perf_counter();image=bpy.data.images.load(str(exr),check_existing=False)
        image.colorspace_settings.name='Non-Color';image.alpha_mode='PREMUL'
        if tuple(image.size)!=(width,height):raise ArithmeticError('Rendered dimensions differ')
        actual=np.empty(width*height*4,dtype='f4');image.pixels.foreach_get(actual)
        actual=actual.reshape(height,width,4);bpy.data.images.remove(image)
        read_seconds=time.perf_counter()-start
        expected=rgb if variant=='passthrough' else tetrahedral(np.load(cube_path,allow_pickle=False),rgb,SHAPERS[variant])
        error=abs(actual[...,:3].astype(float)-expected)
        normalized=error/(1+abs(expected));maximum=float(normalized.max())
        if (not np.isfinite(actual).all() or maximum>=.002
                or not np.array_equal(actual[0,0,:3],np.zeros(3))
                or not np.all(actual[...,3]==1)):
            raise ArithmeticError(f'Render does not reproduce its LUT: normalized maximum {maximum}')
        changed=int(np.count_nonzero(np.max(abs(actual[...,:3]-rgb),-1)>1e-4))
        if variant!='passthrough' and changed==0:raise ArithmeticError('LUT render bypassed grading')
        result=dict(kind='render',variant=variant,backend=backend,width=width,height=height,
            renderer=renderer,blender=bpy.app.version_string,initialize_seconds=initialization,
            scene_setup_seconds=scene_seconds,graph_image_setup_seconds=setup_seconds,
            render_call_seconds=render_seconds,compositor_seconds=composite_seconds,
            compositor_callbacks=[kind for kind,_ in events],
            save_exr_seconds=save_seconds,readback_seconds=read_seconds,
            compositor_precision='AUTO (full precision for final rendering)',
            map_uv_reads=reads,address_nodes=address_nodes,changed_pixels=changed,
            maximum_native_error=float(error.max()),maximum_normalized_error=maximum,
            render_sha256=hashlib.sha256(actual.tobytes()).hexdigest())
        save(output/'result.json',result)
    finally:
        application.close()


def prepare_input(output,width,height):
    from tools.analysis.photo_io import load_fixtures,ocio_processors,apply_processor
    from tools.analysis.photo_grade import extension_model,prepare
    from tools.analysis.photo_stack import cases
    fixtures=load_fixtures();ocio=ocio_processors();model=extension_model(cases()['mixed_tone'])
    pixels=np.concatenate([prepare(model,apply_processor(ocio['convert'],f['rgb'])).reshape(-1,3) for f in fixtures])
    pixels=np.clip(pixels,0,1024)
    # Pointwise lookup: repeat the complete sample sequence to fill a frame,
    # without claiming to reconstruct the unavailable original photographs.
    rgb=np.resize(pixels,(height,width,3)).astype('f4')
    rgb[0,:4]=[[0,0,0],[1024,1024,1024],[0,.2,0],[2,.1,1]]
    path=output/'input.npy';np.save(path,rgb)
    return path,dict(ocio=ocio['metadata'],fixture_names=[f['name'] for f in fixtures],
        unique_photographic_samples=len(pixels),input_sha256=hashlib.sha256(rgb.tobytes()).hexdigest(),
        construction='Repeated complete photographic sample sequence, then four endpoint/color probes; no filtering.')


def child(output,kind,variant,backend,input_path=None,cube_path=None,packed_path=None):
    output.mkdir(parents=True,exist_ok=True)
    command=[sys.executable,'-m','tools.analysis.shaper_performance','--worker',kind,
        '--output-dir',str(output),'--variant',variant,'--backend',backend]
    for flag,path in (('--input',input_path),('--cube',cube_path),('--packed',packed_path)):
        if path is not None:command.extend((flag,str(path)))
    # Set before the child's first Blender import. Never delete or touch an
    # existing system/user driver cache; discard only this new temporary one.
    with tempfile.TemporaryDirectory(prefix='mesa-',dir=output) as cache:
        env=os.environ.copy();env['PYTHONPATH']=os.pathsep.join(CHILD_IMPORT_PATH)
        env['MESA_SHADER_CACHE_DIR']=str(Path(cache).resolve())
        start=time.perf_counter()
        with (output/'process.log').open('w') as stream:
            process=subprocess.run(command,env=env,stdout=stream,stderr=subprocess.STDOUT,timeout=300)
        if process.returncode:raise RuntimeError(f'{kind} child failed; see {output / "process.log"}')
        result=json.loads((output/'result.json').read_text());result['process_seconds']=time.perf_counter()-start
        result['fresh_process']=True;result['empty_mesa_cache']=True
    return result


def summary(output,report):
    rows=report['trials'];lines=['# Shaper bake and actual render performance','',
        f'{report["repeats"]} fresh-process trials per variant/backend; '
        f'{report["width"]}×{report["height"]} photographic-sample frame. '
        'Current: log κ=.01. Candidate: log κ=.01 then tanh strength2, center.25.','',
        'Every process starts with an empty isolated Mesa shader cache. Baking uses '
        'a six-grade sequence with a new empty row cache for each grade, progressive '
        '33³/65³ execution and actual RGBE packing. '
        'D65/context/program initialization and model construction are separate from bake time.','',
        '## Fresh 65³ bake and RGBE packing','',
        '| Backend | Grade | Current median ms | Candidate median ms | Change |',
        '| --- | --- | ---: | ---: | ---: |']
    for backend in ('CPU','GPU'):
        for name in CASES:
            med=[median(r['cases'][name]['bake_pack_seconds'] for r in rows
                if (r['kind'],r['backend'],r['variant'])==('bake',backend,v)) for v in SHAPERS]
            lines.append(f'| {backend} | {name} | {med[0]*1000:.3f} | {med[1]*1000:.3f} | {(med[1]/med[0]-1)*100:+.2f}% |')
    lines+=['','## Separate bake initialization','',
        'Each trial is a fresh process. Immutable resources and the GPU program are '
        'shared only within that trial\'s six-grade sequence. Program setup includes '
        'the validation dispatch/readback and CPU comparison, not just compilation.','',
        '| Backend | Variant | Blender/context import ms | D65 load ms | GPU program + validation ms |',
        '| --- | --- | ---: | ---: | ---: |']
    for backend in ('CPU','GPU'):
        for variant in SHAPERS:
            selected=[r for r in rows if (r['kind'],r['backend'],r['variant'])==('bake',backend,variant)]
            med=lambda key:median(r[key]*1000 for r in selected)
            lines.append(f'| {backend} | {variant} | {med("initialize_seconds"):.3f} | '
                f'{med("d65_context_seconds"):.3f} | {med("gpu_program_setup_seconds"):.3f} |')
    if any(r['kind']=='render' for r in rows):
        lines+=['','## First final render of the baked mixed-tone LUT','',
            'Actual Blender compositor, same four nearest RGBE reads and linear-RGB '
            'tetrahedral blend. The candidate changes only scalar addressing/endpoints. '
            'AUTO uses full precision for final renders; these are not half-precision '
            'interactive preview timings. The scene is empty one-sample CPU Cycles; '
            'the blocking render call includes Blender orchestration. Compositor callback intervals are reported only '
            'if both callbacks fire; otherwise unavailable. Readback and EXR writing are separate. '
            'This measures the LUT core on prepared input, excluding the full Grade wrapper\'s '
            'input repair and matrices. Graph/image setup is preparation; deferred uploads '
            'and shader compilation remain in the first render.','',
            '| Backend | Variant | First render median [min,max] ms | Graph/images setup ms | Blender/context import ms | EXR save + readback ms |',
            '| --- | --- | ---: | ---: | ---: | ---: |']
        for backend in ('CPU','GPU'):
            for variant in ('passthrough',*SHAPERS):
                selected=[r for r in rows if (r['kind'],r['backend'],r['variant'])==('render',backend,variant)]
                if not selected:continue
                values=[r['render_call_seconds']*1000 for r in selected]
                interval=f'{median(values):.3f} [{min(values):.3f}, {max(values):.3f}]'
                med=lambda key:median(r[key]*1000 for r in selected)
                lines.append(f'| {backend} | {variant} | {interval} | '
                    f'{med("graph_image_setup_seconds"):.3f} | {med("initialize_seconds"):.3f} | '
                    f'{median((r["save_exr_seconds"]+r["readback_seconds"])*1000 for r in selected):.3f} |')
        lines+=['','The pass-through control characterizes common overhead; subtracting its median '
            'does not establish an exact isolated LUT execution cost. JSON retains every '
            'trial, process startup, phase boundary, output check and native error.','',
            'Both render backends use the same CPU-baked vertices for each shaper. '
            'Verification checks the entire frame against its matching numerical lookup, '
            'exact black, alpha, dimensions and a non-bypassed grade. GPU means llvmpipe '
            'software rendering; no physical-GPU performance is inferred.']
        rendered=[r for r in rows if r['kind']=='render']
        lines+=['',f'Maximum normalized native render/lookup difference: '
            f'{max(r["maximum_normalized_error"] for r in rendered):.9g}. '
            'All output checks passed. Address graph: current 156 nodes, candidate 243 '
            '(+87); both use four Map UV image reads.']
    lines+=['','Production defaults, four-read rendering and D65 are unchanged.','',
        '```sh','buck2 run //products/perceptual-grade-blender:shaper_performance -- --output-dir buck-out/shaper-performance','```','']
    (output/'summary.md').write_text('\n'.join(lines))


def run(output,repeats,width,height):
    output=output.resolve();output.mkdir(parents=True,exist_ok=True)
    input_path,metadata=prepare_input(output,width,height)
    report=dict(repeats=repeats,width=width,height=height,metadata=metadata,trials=[])
    for trial in range(repeats):
        for backend in ('CPU','GPU'):
            for variant in (tuple(SHAPERS) if trial%2==0 else tuple(reversed(SHAPERS))):
                folder=output/f'bake-{trial}-{backend}-{variant}'
                result=child(folder,'bake',variant,backend);result['trial']=trial
                report['trials'].append(result);save(output/'report.json',report)
                print('Completed fresh bake',trial,backend,variant,flush=True)
    summary(output,report)
    for trial in range(repeats):
        for backend in ('CPU','GPU'):
            variants=('passthrough','current','candidate')
            variants=variants[trial%3:]+variants[:trial%3]
            for variant in variants:
                baked=output/f'bake-0-CPU-{variant}'
                result=child(output/f'render-{trial}-{backend}-{variant}','render',variant,backend,input_path,
                    None if variant=='passthrough' else baked/'cube.npy',
                    None if variant=='passthrough' else baked/'packed.npy')
                result['trial']=trial;report['trials'].append(result);save(output/'report.json',report)
                print('Completed first render',trial,backend,variant,
                    f'{result["render_call_seconds"]*1000:.3f} ms render call',flush=True)
    summary(output,report)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir',type=Path,default=Path('buck-out/shaper-performance'))
    parser.add_argument('--trials',type=int,default=5);parser.add_argument('--width',type=int,default=1920)
    parser.add_argument('--height',type=int,default=1080)
    parser.add_argument('--summarize-only',action='store_true',help='Reformat existing measurements without rerunning them')
    parser.add_argument('--worker',choices=('bake','render'));parser.add_argument('--variant',choices=(*SHAPERS,'passthrough'))
    parser.add_argument('--backend',choices=('CPU','GPU'))
    parser.add_argument('--input',type=Path);parser.add_argument('--cube',type=Path);parser.add_argument('--packed',type=Path)
    args=parser.parse_args()
    if args.summarize_only:summary(args.output_dir,json.loads((args.output_dir/'report.json').read_text()))
    elif args.worker=='bake':bake_worker(args.output_dir,args.variant,args.backend)
    elif args.worker=='render':render_worker(args.output_dir,args.variant,args.backend,args.input,args.cube,args.packed)
    else:
        if args.trials<1 or args.width<4 or args.height<1:parser.error('Positive trials/height and width≥4 required')
        run(args.output_dir,args.trials,args.width,args.height)


if __name__=='__main__':main()
