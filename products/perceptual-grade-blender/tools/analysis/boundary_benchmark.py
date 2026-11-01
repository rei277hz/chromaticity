"""Repeatable selector/lookup timing, including actual Blender compute dispatch.

Use the same seeded rays for each implementation; saved results can be compared
with --baseline. This measures lookup work, not complete drag-to-preview time.
"""
import argparse
import json
import importlib.util
from pathlib import Path
import sys
import time
import bpy
import gpu
import numpy as np
from color_tools.perceptual_grade_blender.model.boundary_gpu import Program
from color_tools.perceptual_grade_core.model.boundary_polynomial import PolynomialTable
from color_tools.perceptual_grade_core.model.boundary_table import Table


def timing(operation, repeats):
    samples=[]
    for _ in range(repeats):
        start=time.perf_counter();operation();samples.append(1000*(time.perf_counter()-start))
    return dict(median_ms=float(np.median(samples)),samples_ms=samples)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate',type=Path,required=True)
    parser.add_argument('--output-dir',type=Path,required=True)
    parser.add_argument('--baseline',type=Path)
    parser.add_argument('--compare-cpu',type=Path,help='Saved boundary_polynomial.py, interleaved with current NumPy lookup')
    parser.add_argument('--repeats',type=int,default=7)
    parser.add_argument('--compare-gpu',type=Path,nargs='*',default=[],help='Saved boundary_gpu.py versions, interleaved with the current shader')
    args=parser.parse_args();args.output_dir.mkdir(parents=True,exist_ok=True)
    with np.load(args.candidate,allow_pickle=False) as archive:data=dict(archive)
    cpu=PolynomialTable(data);oracle=Table(data);rng=np.random.default_rng(520)
    points=np.column_stack((rng.uniform(0,1,65**3),rng.uniform(-2*np.pi,4*np.pi,65**3),
                            rng.uniform(0,float(data['white']),65**3))).astype('f4')
    t,h,_=points.T
    bpy.context.preferences.system.gpu_backend='METAL' if sys.platform=='darwin' else 'OPENGL';gpu.init()
    program=Program(data,expanded=cpu.expanded)
    report=dict(renderer=gpu.platform.renderer_get(),samples=len(t),
                timing_scope='Every trial recomputes all rays; no row memoization or discarded warmup. Immutable lookup/shader setup is separate.',
                cpu_lookup_bytes=sum(v.nbytes for v in cpu.expanded.values()),
                gpu_lookup_bytes=program.lookup_bytes,compile_seconds=program.compile_seconds,timings={})
    for name,operation in (
        ('cpu_select',lambda:cpu.selector.select(t,h)),
        ('cpu_capacity',lambda:cpu.capacity(t,h)),
        ('cpu_capacity_chunked',lambda:[cpu.capacity(t[i:i+16384],h[i:i+16384]) for i in range(0,len(t),16384)]),
        ('float64_select',lambda:oracle.selector.select(t,h)),
        ('gpu_capacity_and_guard',lambda:program.evaluate(points))):
        report['timings'][name]=timing(operation,args.repeats)
    # Vertex ties, either side of vertices, each shared crease and hue seam.
    v=cpu.selector.vertices
    special_t=np.r_[v,np.nextafter(v,0),np.nextafter(v,1)]
    special_t,special_h=np.meshgrid(special_t,np.linspace(-2*np.pi,4*np.pi,193,dtype='f4'))
    edge_t=np.linspace(0,1,97,dtype='f4');curves,active=cpu.selector.curves(edge_t)
    et=np.broadcast_to(edge_t[:,None],active.shape)[active];eh=curves[...,0][active]
    tt=np.r_[special_t.ravel(),et,et,et];hh=np.r_[special_h.ravel(),eh,eh-1e-6,eh+1e-6]
    face=cpu.selector.select(tt,hh)[0];capacity=cpu.capacity(tt,hh)
    actual=program.evaluate(np.column_stack((tt,hh,np.zeros_like(tt))))
    report['gpu_face_mismatches']=int(np.count_nonzero(actual[:,1]!=face))
    report['gpu_capacity_relative_error']=float(np.max(abs(actual[:,0]/capacity-1)))
    result=dict(capacity=cpu.capacity(t,h),face=cpu.selector.select(t,h)[0],
                special_capacity=capacity,special_face=face)
    if args.compare_cpu:
        spec=importlib.util.spec_from_file_location('color_tools.perceptual_grade_core.model._cpu_comparison',args.compare_cpu)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        previous=module.PolynomialTable(data,expanded=cpu.expanded)
        for a,b in zip(cpu.selector.select(tt,hh),previous.selector.select(tt,hh)):
            np.testing.assert_array_equal(a,b)
        np.testing.assert_array_equal(result['capacity'],previous.capacity(t,h))
        np.testing.assert_array_equal(result['special_capacity'],previous.capacity(tt,hh))
        operations={}
        for name,table in (('current',cpu),('previous',previous)):
            operations[name]={
                'select':lambda table=table:table.selector.select(t,h),
                'capacity':lambda table=table:table.capacity(t,h),
                'capacity_chunked':lambda table=table:[table.capacity(t[i:i+16384],h[i:i+16384]) for i in range(0,len(t),16384)]}
        samples={name:{key:[] for key in values} for name,values in operations.items()}
        for repeat in range(args.repeats):
            for key in operations['current']:
                for name in (('previous','current') if repeat%2==0 else ('current','previous')):
                    start=time.perf_counter();operations[name][key]();elapsed=1000*(time.perf_counter()-start)
                    samples[name][key].append(elapsed)
        report['interleaved_cpu']={name:{key:dict(median_ms=float(np.median(v)),samples_ms=v)
            for key,v in values.items()} for name,values in samples.items()}
        report['cpu_comparison_identical']=True
    if args.compare_gpu:
        programs={'current':program}
        for i,path in enumerate(args.compare_gpu):
            spec=importlib.util.spec_from_file_location(f'color_tools.perceptual_grade_blender.model._comparison_{i}',path)
            module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
            programs[str(path)]=module.Program(data,expanded=cpu.expanded)
        for p in programs.values():
            np.testing.assert_array_equal(p.evaluate(points)[:,0],result['capacity'])
        samples={name:[] for name in programs};order=list(programs)
        for repeat in range(args.repeats):
            for name in order if repeat%2==0 else order[::-1]:
                start=time.perf_counter();programs[name].evaluate(points);elapsed=1000*(time.perf_counter()-start)
                samples[name].append(elapsed)
        report['interleaved_gpu']={name:dict(median_ms=float(np.median(v)),samples_ms=v) for name,v in samples.items()}
    if args.baseline:
        with np.load(args.baseline/'values.npz',allow_pickle=False) as base:
            report['baseline_comparison']={name:float(np.max(abs(value/base[name]-1)))
                if 'capacity' in name else int(np.count_nonzero(value!=base[name])) for name,value in result.items()}
    np.savez(args.output_dir/'values.npz',**result)
    (args.output_dir/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2),flush=True)
    if report['gpu_face_mismatches'] or report['gpu_capacity_relative_error']>1e-4:
        raise SystemExit('GPU lookup conformance failed')
    if any(report.get('baseline_comparison',{}).values()):
        raise SystemExit('The optimization changed the saved lookup results')


if __name__=='__main__':main()
