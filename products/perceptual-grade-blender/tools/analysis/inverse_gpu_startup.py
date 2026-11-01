from color_tools.perceptual_grade_blender.model.bake_inverse_gpu import Program as ReferenceGPUProgram
"""Trace a cold llvmpipe inverse shader and two complete fresh-grade GPU bakes."""
import argparse
from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from unittest.mock import patch
import numpy as np
from color_tools.perceptual_grade_core.model import bake_inverse
from color_tools.perceptual_grade_blender.model import bake_inverse_gpu
from tests.reference.legacy_capacity import LegacyCapacityModel
from color_tools.perceptual_grade_core.model.boundary_polynomial import PolynomialTable
from tests.reference.legacy_capacity import LegacyCapacityBakeStack
from tools.analysis.inverse_bake_profile import cases,lattice


def unwrap(value):
    return value.raw if isinstance(value,(Texture,Shader)) else value


class Texture:
    def __init__(self,raw,trace):self.raw=raw;self.trace=trace
    def read(self,*args,**kwargs):
        return self.trace.call('texture.read',self.raw.read,args,kwargs)
    def __getattr__(self,name):return getattr(self.raw,name)


class Shader:
    def __init__(self,raw,trace):self.raw=raw;self.trace=trace
    def __getattr__(self,name):
        method=getattr(self.raw,name)
        if name not in ('bind','uniform_sampler','uniform_int','image'):return method
        def measured(*args,**kwargs):
            return self.trace.call('shader.'+name,method,tuple(map(unwrap,args)),
                {k:unwrap(v) for k,v in kwargs.items()})
        return measured


class Trace:
    def __init__(self):
        self.origin=time.perf_counter();self.events=[];self.frames=[];self.trial=None;self.source={}

    def call(self,name,function,args=(),kwargs=None,details=None):
        event=dict(name=name,trial=self.trial,start_seconds=time.perf_counter()-self.origin,
            parent=self.frames[-1][0] if self.frames else None)
        if details:event.update(details)
        index=len(self.events);self.events.append(event);frame=[index,0.];self.frames.append(frame)
        try:return function(*args,**(kwargs or {}))
        finally:
            duration=time.perf_counter()-self.origin-event['start_seconds'];self.frames.pop()
            event.update(seconds=duration,exclusive_seconds=duration-frame[1])
            if self.frames:self.frames[-1][1]+=duration

    def install(self,gpu,patches):
        buffer,texture=gpu.types.Buffer,gpu.types.GPUTexture
        create,dispatch=gpu.shader.create_from_info,gpu.compute.dispatch
        source=bake_inverse_gpu.source
        def make_buffer(*args,**kwargs):return self.call('buffer.create',buffer,args,kwargs)
        def make_texture(*args,**kwargs):
            raw=self.call('texture.create_upload',texture,args,kwargs,
                dict(dimensions=list(args[0]),format=kwargs.get('format'),has_data='data' in kwargs))
            return Texture(raw,self)
        def make_shader(*args,**kwargs):return Shader(self.call('shader.create_from_info',create,args,kwargs),self)
        def submit(*args,**kwargs):return self.call('compute.dispatch',dispatch,tuple(map(unwrap,args)),kwargs)
        def make_source(*args,**kwargs):
            text=self.call('shader.source',source,args,kwargs);encoded=text.encode()
            self.source=dict(utf8_bytes=len(encoded),lines=len(text.splitlines()),sha256=hashlib.sha256(encoded).hexdigest())
            return text
        for owner,name,replacement in ((gpu.types,'Buffer',make_buffer),(gpu.types,'GPUTexture',make_texture),
            (gpu.shader,'create_from_info',make_shader),(gpu.compute,'dispatch',submit),(bake_inverse_gpu,'source',make_source)):
            patches.enter_context(patch.object(owner,name,replacement))

    def totals(self,trial):
        result={}
        for event in self.events:
            if event['trial']!=trial:continue
            row=result.setdefault(event['name'],dict(calls=0,seconds=0.,exclusive_seconds=0.,durations=[]))
            row['calls']+=1;row['seconds']+=event['seconds'];row['exclusive_seconds']+=event['exclusive_seconds']
            row['durations'].append(event['seconds'])
        return result


def run(output,size,name):
    output.mkdir(parents=True,exist_ok=True)
    # This process alone receives an empty driver-cache directory. No existing
    # cache is deleted, and the production shader body/constants stay unchanged.
    cache=Path(tempfile.mkdtemp(prefix='mesa-cache-',dir=output)).resolve()
    os.environ['MESA_SHADER_CACHE_DIR']=str(cache)
    trace=Trace()
    def initialize():
        import bpy,gpu
        bpy.context.preferences.system.gpu_backend='OPENGL';gpu.init();return bpy,gpu
    bpy,gpu=trace.call('blender_import_and_gpu_init',initialize)
    renderer=gpu.platform.renderer_get()
    if 'llvmpipe' not in renderer.lower():raise RuntimeError('This startup study requires llvmpipe')
    def prepare_lookup():return PolynomialTable(LegacyCapacityModel().boundary.cache)
    table=trace.call('immutable_lookup',prepare_lookup);rgb=lattice(size)
    settings,directions=cases()[name]
    if directions!=['INVERSE']:raise ValueError('Startup trace requires one inverse grade')
    outputs=[]
    with ExitStack() as patches:
        trace.install(gpu,patches)
        stack=trace.call('initial_grade_preparation',lambda:LegacyCapacityBakeStack(settings,directions,table, program_factory=ReferenceGPUProgram))
        program=trace.call('program_creation',stack.prepare_gpu)
        for trial in (1,2):
            trace.trial=trial
            start=time.perf_counter()
            stack=trace.call('grade_preparation',lambda:LegacyCapacityBakeStack(settings,directions,table, program_factory=ReferenceGPUProgram));stack.program=program
            outputs.append(trace.call('bake',lambda:stack.bake_native(rgb,'GPU')))
            print(f'Fresh-grade trial {trial}: {time.perf_counter()-start:.6f}s',flush=True)
    identical=bool(np.array_equal(outputs[0].view('u4'),outputs[1].view('u4')))
    if not identical or not np.isfinite(outputs[0]).all():raise ArithmeticError('Repeated GPU trace changed output or produced nonfinite values')
    files=[p for p in cache.rglob('*') if p.is_file()]
    report=dict(case=name,size=size,samples=len(rgb),renderer=renderer,blender=bpy.app.version_string,
        python=sys.version.split()[0],numpy=np.__version__,mesa_cache_dir=str(cache),
        driver_cache_files=len(files),driver_cache_bytes=sum(p.stat().st_size for p in files),
        acceptance=dict(relative=float(bake_inverse.RGB_RELATIVE_TOLERANCE),absolute=float(bake_inverse.RGB_ABSOLUTE_TOLERANCE)),
        stage3_iterations=bake_inverse.ITERATIONS,inner_stopping=float(bake_inverse.SEARCH_TOLERANCE),
        chroma_coordinate='brightness-scaled C2 toe',shader_body=trace.source,
        boundary_lookup_bytes=program.lookup_bytes,parameter_bytes=program.parameter_bytes,
        input_rgb_bytes=rgb.nbytes,readback_batch_bytes=4096*4*4,bit_identical_trials=identical,
        input_rgba_upload_bytes_per_bake=((len(rgb)+4095)//4096)*4096*4*4,
        rgba_readback_bytes_per_bake=((len(rgb)+4095)//4096)*4096*4*4,
        setup=trace.totals(None),trials={str(i):trace.totals(i) for i in (1,2)},events=trace.events,
        limitations=[
            'Every trial creates a fresh grade and bakes every vertex; both trials, including first use, are retained.',
            'Tracing starts before Blender import/GPU initialization but after Python launch and top-level NumPy/reference imports; it is not complete process startup timing.',
            'Timings are host wall intervals around actual Blender GPU API calls. texture.read is the existing synchronous completion/readback boundary.',
            'texture.read excludes the following NumPy buffer conversion and copies; those remain in exclusive bake host time.',
            'A long dispatch or readback can include deferred driver work; these intervals are not GPU hardware event timers.',
            'Wrappers add Python timing overhead but execute the original runtime methods with the same buffers, shader, dispatches and readbacks.',
            'Shader body bytes/hash refer to the Python-generated compute body, before Blender adds its interface declarations.',
            'The fresh isolated Mesa disk-cache directory avoids existing driver shader-cache entries. No cache is deleted.',
            'llvmpipe is a software GPU using runtime LLVM code generation; physical-GPU startup and bake timings are not measured.'],
        sources=['https://docs.mesa3d.org/drivers/llvmpipe.html','https://docs.mesa3d.org/envvars.html'])
    (output/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    lines=['# Cold llvmpipe inverse startup','',f'{name}, {size}³ vertices; shader body {trace.source["utf8_bytes"]:,} bytes; boundary lookup {program.lookup_bytes:,} bytes.',
        f'Isolated driver cache: {cache}; {len(files)} files after execution. Repeated full outputs bit-identical: {identical}.','',
        '| Phase / API | Setup total ms | First bake total ms | Second bake total ms | First call ms |',
        '| --- | ---: | ---: | ---: | ---: |']
    names=dict.fromkeys(event['name'] for event in trace.events)
    for event_name in names:
        rows=[report['setup'].get(event_name),report['trials']['1'].get(event_name),report['trials']['2'].get(event_name)]
        totals=['—' if row is None else f'{1000*row["seconds"]:.3f}' for row in rows]
        first=next(row for row in rows if row is not None)['durations'][0]
        lines.append(f'| {event_name} | '+ ' | '.join(totals)+f' | {1000*first:.3f} |')
    lines+=['','Parent rows include child API calls; use exclusive_seconds in report.json when adding phase durations.',
        'Complete per-call timings retain the first dispatch/readback and every later batch.','',*('- '+x for x in report['limitations']),'']
    (output/'summary.md').write_text('\n'.join(lines));return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir',type=Path,required=True)
    parser.add_argument('--size',type=int,default=65)
    parser.add_argument('--case',choices=('tone','mixed','mixed_tone'),default='mixed_tone')
    args=parser.parse_args()
    if args.size<2:parser.error('size >= 2 required')
    run(args.output_dir,args.size,args.case)
