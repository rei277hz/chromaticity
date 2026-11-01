"""Exclusive CPU lookup costs on actual 65³ Grade rays; no production changes."""
import argparse
from importlib.resources import files
import hashlib
import inspect
import json
from pathlib import Path
import platform
from statistics import median
import sys
import time
from unittest.mock import patch
import numpy as np
from color_tools.perceptual_grade_core.model import bake, boundary_polynomial as bp, color, linear, lut, tone


def label(name,line,parent=''):
    if name=='wrap_hue':return 'hue.wrap'
    if name=='edge_address':return 'edge.address'
    if name=='edge_value':return 'edge.polynomial'
    if name=='region':return 'selection.height_region'
    if name=='hint_mask':return 'selection.hint_table'
    if name=='left':
        if line.startswith(('angle=','distance=','other=','d=')):return 'selection.left_hue_wrap_distance'
        return 'selection.candidate_gather_compare_scatter'
    if name=='select':
        if line.startswith(('left,r0','ri,rz','right_angle','dr=','ties=','if len(ties)','oi,oz','angle=',
                            'distance=','right[','ri[')):return 'selection.right_edge_and_vertex_ties'
        return 'selection.fraction_and_assembly'
    if name=='capacity':return 'face.validation_and_dispatch'
    if name=='field':
        if line.startswith(('u=','i=','a=')):return 'face.coordinates_and_address'
        if line.startswith(('q00=','row0=','row1=')):return 'face.four_fetches_and_interpolation'
        if line.startswith('correction='):return 'face.affine_decode'
        if line.startswith('return '):return 'face.combine_and_reciprocal'
        return 'face.setup'
    raise ValueError(name)


class Trace:
    """Charge a line only while no traced callee is running; never add children twice."""
    def __init__(self,table):
        functions=[table.capacity,table.field,bp.wrap_hue,table.selector.select,table.selector.left,
            table.selector.region,table.selector.hint_mask,table.selector.edge_address,
            table.selector.edge_value]
        self.functions={}
        for function in functions:
            source,first=inspect.getsourcelines(function)
            self.functions[function.__code__]=(function.__name__,{first+i:s.strip() for i,s in enumerate(source)})

    def charge(self,now):
        if self.stack:
            group=self.stack[-1][1]
            self.costs[group]=self.costs.get(group,0.)+now-self.last
        self.last=now

    def trace(self,frame,event,_arg):
        info=self.functions.get(frame.f_code)
        if info is None:return None
        now=time.perf_counter();self.charge(now)
        name,lines=info
        if event=='call':
            parent=self.stack[-1][1] if self.stack else ''
            self.stack.append([frame,label(name,lines.get(frame.f_lineno,''),parent),parent])
        elif event=='line':
            self.stack[-1][1]=label(name,lines.get(frame.f_lineno,''),self.stack[-1][2])
        elif event=='return':
            if name=='capacity':self.values=frame.f_locals.copy()
            self.stack.pop()
        self.last=time.perf_counter()
        return self.trace

    def run(self,function,*args):
        self.stack=[];self.costs={};self.values={};self.last=time.perf_counter()
        previous=sys.gettrace();sys.settrace(self.trace);start=time.perf_counter()
        try:value=function(*args)
        finally:
            elapsed=time.perf_counter()-start;sys.settrace(previous)
        return value,dict(total_ms=1000*elapsed,exclusive_ms={k:1000*v for k,v in self.costs.items()}),self.values


def paired(operations,repeats):
    samples={name:[] for name in operations};names=list(operations)
    for i in range(repeats):
        for name in names if i%2==0 else names[::-1]:
            start=time.perf_counter();operations[name]();samples[name].append(1000*(time.perf_counter()-start))
    return {name:dict(median_ms=median(v),samples_ms=v) for name,v in samples.items()}


def selection_probes(selector,t,h,repeats):
    region=selector.region(t);mask=selector.hint_mask(t,h,region)
    remaining=mask&~(1<<bp.FIRST[mask])
    def full_masks():return [np.flatnonzero(remaining&(1<<k)) for k in range(5)]
    def compact_masks():
        active=np.flatnonzero(remaining);rest=remaining[active]
        return [active[(rest&(1<<k))!=0] for k in range(5)]
    for a,b in zip(full_masks(),compact_masks()):np.testing.assert_array_equal(a,b)
    angles=[];hues=[]
    for k in range(5):
        rows=np.flatnonzero(mask&(1<<k));edge=selector.topology[region[rows],k,0]
        angles.append(selector.curve(t[rows],edge,0));hues.append(h[rows])
    angle=np.concatenate(angles);hue=np.concatenate(hues);tau=np.float32(2*np.pi)
    distance=hue-angle%tau
    if np.any((angle< -tau)|(angle>=2*tau)|(distance< -2*tau)|(distance>=tau)):
        raise ValueError('Actual rays exceed the bounded-wrap prototype domain')
    def wrap_angle(v):return np.where(v<0,v+tau,np.where(v>=tau,v-tau,v))
    def wrap_distance(v):return np.where(v< -tau,v+2*tau,np.where(v<0,v+tau,v))
    for values,function in ((angle,wrap_angle),(distance,wrap_distance)):
        np.testing.assert_array_equal(function(values),values%tau)
    # Check float32 neighbors at the wrap seams in each prototype's domain.
    for points,function,lo,hi in ((np.array([-tau,0,tau],dtype='f4'),wrap_angle,-tau,2*tau),
                                  (np.array([-2*tau,-tau,0],dtype='f4'),wrap_distance,-2*tau,tau)):
        probes=np.r_[points,np.nextafter(points,np.float32(-np.inf)),np.nextafter(points,np.float32(np.inf))]
        probes=probes[(probes>=lo)&(probes<hi)]
        np.testing.assert_array_equal(function(probes),probes%tau)
    return dict(candidate_rows=paired({'full_masks':full_masks,'compact_masks':compact_masks},repeats),
        wrapping=paired({'remainder':lambda:(angle%tau,distance%tau),
                         'bounded_conditions':lambda:(wrap_angle(angle),wrap_distance(distance))},repeats),
        angle_range=[float(angle.min()),float(angle.max())],distance_range=[float(distance.min()),float(distance.max())],
        evaluated_candidates=len(angle),exact_on_probes=True)


class FaceField:
    """Original face phase exposed only for independently checked diagnostics."""
    def __init__(self,table,data):
        self.table=table;self.expanded=bp.face_polynomials(data);self.selector=table.selector
        self.low=self.selector.vertices[self.selector.limits[:,0]]
        self.span=self.selector.vertices[self.selector.limits[:,1]]-self.low

    def polynomial(self,face,x,s):
        expanded=self.expanded
        ti=np.zeros_like(face,dtype=int);tx=np.zeros_like(x)
        for f in range(6):
            active=face==f
            if np.any(active):ti[active],tx[active]=bp.address(expanded['height_axes'][f],x[active])
        si,sx=bp.address(expanded['radius_axis'],s);sx=sx[:,None]
        c=expanded['face_polynomial'][face,ti,si]
        v=((c[...,3]*sx+c[...,2])*sx+c[...,1])*sx+c[...,0]
        return ((v[:,3]*tx+v[:,2])*tx+v[:,1])*tx+v[:,0]

    @staticmethod
    def combine(s,left,right,correction):return 1/((1-s)*left+s*right+s*(1-s)*correction)

    def current(self,t,face,s,left,right):
        limits=self.selector.vertices[self.selector.limits[face]]
        x=(t-limits[:,0])/(limits[:,1]-limits[:,0])
        return self.combine(s,left,right,self.polynomial(face,x,s))

    def sample(self,n):
        grid=np.linspace(0,1,n,dtype='f4');x,s=np.meshgrid(grid,grid,indexing='ij')
        x=x.ravel();s=s.ravel();values=np.empty((6,n*n),dtype='f4')
        for face in range(6):
            for begin in range(0,n*n,16384):
                end=min(begin+16384,n*n)
                values[face,begin:end]=self.polynomial(np.full(end-begin,face,dtype='i4'),x[begin:end],s[begin:end])
        return values.reshape(6,n,n)


def sampled_tables(kernel,queries,rgb,expected,repeats):
    """Diagnostic bilinear tables, derived from the existing resource without refitting.

    Keep the selector and shared edge baseline. Only sample the face correction;
    a global height/hue table would blur the intentionally sharp cube creases.
    These approximations are not installed or certified for production use.
    """
    table=kernel.table;selector=table.selector;field=FaceField(table,kernel.data)
    low,span=field.low,field.span;current=field.current;combine=field.combine
    fields=[]
    for t,h in queries:
        face,s,_,_,left,right=selector.select(t,h)
        fields.append((t,face,s,left,right))
    # Independent queries include tips, vertex-height neighborhoods and ordinary
    # rays. This is sampled comparison with the current implementation, not a
    # geometric-oracle certificate of either boundary.
    rng=np.random.default_rng(524)
    t=np.r_[rng.uniform(0,1,100000),np.geomspace(1e-10,.01,2000),
        1-np.geomspace(1e-7,.01,2000),
        (selector.vertices[:,None]+rng.uniform(-.001,.001,(8,2000))).ravel()]
    t=np.clip(t,0,1).astype('f4');h=rng.uniform(-np.pi,np.pi,len(t)).astype('f4')
    f,s,_,_,left,right=selector.select(t,h)
    probes=(t,f,s,left,right);probe_reference=current(*probes)
    reference=[current(*args) for args in fields]
    results=[]
    for n in (32,64,128,256,512,1024):
        start=time.perf_counter();values=field.sample(n).ravel();setup=1000*(time.perf_counter()-start)
        def sampled(tt,face,ss,ll,rr):
            u=(tt-low[face])/span[face]*(n-1);v=ss*(n-1)
            i=np.clip(u.astype('i4'),0,n-2);j=np.clip(v.astype('i4'),0,n-2)
            a=u-i.astype('f4');b=v-j.astype('f4');index=(face*n+i)*n+j
            q00=values[index];q01=values[index+1]
            row0=q00+a*(values[index+n]-q00)
            row1=q01+a*(values[index+n+1]-q01)
            return combine(ss,ll,rr,row0+b*(row1-row0))
        def capacity(tt,hh):
            tt,hh=np.broadcast_arrays(np.asarray(tt,dtype='f4'),np.asarray(hh,dtype='f4'))
            shape=tt.shape;tt=tt.ravel();hh=hh.ravel()
            face,s,_,_,left,right=selector.select(tt,hh)
            return sampled(tt,face,s,left,right).reshape(shape)
        times={};errors={}
        for name,args,ref in zip(('entry','export'),fields,reference):
            times[name]=paired({'current':lambda:current(*args),'sampled':lambda:sampled(*args)},repeats)
            error=sampled(*args)/ref-1
            errors[name]=dict(relative_error_quantiles=np.quantile(abs(error),[.5,.99,1]).tolist(),
                largest_outward_relative_error=float(error.max()))
        error=sampled(*probes)/probe_reference-1
        errors['independent_rays']=dict(samples=len(error),
            relative_error_quantiles=np.quantile(abs(error),[.5,.99,1]).tolist(),
            largest_outward_relative_error=float(error.max()))
        with patch.object(table,'capacity',side_effect=capacity):actual=kernel.evaluate(rgb)
        rgb_error=np.max(abs(actual-expected),-1);tolerance=np.maximum(.001*np.max(expected,-1),1e-7)
        outside=np.any((actual<0)|(actual>1024),-1)
        result=dict(nodes_per_axis=n,float32_bytes=values.nbytes,setup_ms=setup,
            face_phase=times,capacity_comparison=errors,
            full_grade_comparison=dict(max_absolute_rgb_error=float(rgb_error.max()),
                max_error_to_allowed=float(np.max(rgb_error/tolerance)),
                tolerance_failure_pixels=int(np.count_nonzero(rgb_error>tolerance)),
                nonfinite_pixels=int(np.count_nonzero(~np.isfinite(actual).all(-1))),
                outside_cube_pixels=int(np.count_nonzero(outside)),
                minimum_rgb=float(actual.min()),maximum_rgb=float(actual.max()),
                exact_black=bool(np.array_equal(actual[0],np.zeros(3,dtype='f4')))))
        results.append(result)
        print(f'Sampled {n}×{n} faces: {values.nbytes:,} bytes, '+
              f'{np.count_nonzero(outside)} out-of-cube pixels',flush=True)
    return dict(tables=results,source_face_polynomial_bytes=field.expanded['face_polynomial'].nbytes,
        limitations=['Isolated serial CPU face phase with selector outputs prepared; no end-to-end or GPU speed claim.',
            'Every timing recomputes all face values; immutable setup is reported separately; no per-ray result cache.',
            'Bilinear interpolation is continuous but not generally C1 or C2 inside a face.',
            'Boundary comparisons use the source polynomials; full-grade comparisons use the installed uint16 mapping, not the geometric oracle.',
            'Existing crease selector and shared edge values are retained; no D65 fitting/generation is performed.',
            'Full-grade RGB comparison uses White Ch→C +1 on the 65³ lattice; it is not exhaustive validation.'])


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir',type=Path,required=True)
    parser.add_argument('--repeats',type=int,default=7)
    parser.add_argument('--sampled-tables',action='store_true',help='Compare derived bilinear face tables instead of tracing')
    args=parser.parse_args()
    if args.repeats<1:parser.error('--repeats must be positive')
    args.output_dir.mkdir(parents=True,exist_ok=True)
    resource=files('color_tools.perceptual_grade_core.model')/'d65_boundary.npz'
    with np.load(resource,allow_pickle=False) as archive:data=dict(archive)
    tm=tone.model(tone.Parameters(),linear.GradeSpace('D65'))
    kernel=bake.Kernel(data,tm,color.Model(tm,color.Parameters(c_high_2=1.)))
    table=kernel.table;queries=[];capacity=table.capacity
    def capture(t,hue):
        queries.append((t.copy(),hue.copy()))
        return capacity(t,hue)
    with patch.object(table,'capacity',side_effect=capture):
        rgb=lut.lattice().astype('f4');entered=kernel.enter(rgb)
        output=kernel.export(kernel.grade(kernel.tone_state(entered)))
    if len(queries)!=2 or not np.isfinite(output).all():
        raise ArithmeticError('Unexpected lookup flow or invalid export')
    if args.sampled_tables:
        report=sampled_tables(kernel,queries,rgb,output,args.repeats)
        report.update(case='White Ch→C +1',python=platform.python_version(),numpy=np.__version__,
            resource_sha256=hashlib.sha256(resource.read_bytes()).hexdigest())
        (args.output_dir/'report.json').write_text(json.dumps(report,indent=2)+'\n')
        lines=['# Direct sampled face-table assessment','',
            'Serial CPU entry + export face phase; crease selection and edge evaluation excluded.','',
            '| Nodes per face | Bytes | Current ms | Table ms | Saved ms | Worst capacity error | Out-of-cube pixels |',
            '| --- | ---: | ---: | ---: | ---: | ---: | ---: |']
        for result in report['tables']:
            a=sum(p['current']['median_ms'] for p in result['face_phase'].values())
            b=sum(p['sampled']['median_ms'] for p in result['face_phase'].values())
            e=max(p['relative_error_quantiles'][-1] for p in result['capacity_comparison'].values())
            lines.append(f'| {result["nodes_per_axis"]}² | {result["float32_bytes"]:,} | {a:.2f} | {b:.2f} | {a-b:.2f} | {100*e:.6f}% | {result["full_grade_comparison"]["outside_cube_pixels"]:,} |')
        lines+=['',*(f'- {line}' for line in report['limitations']),'']
        (args.output_dir/'summary.md').write_text('\n'.join(lines))
        print(f'Reports: {args.output_dir}/summary.md and report.json',flush=True)
        return
    report=dict(case='White Ch→C +1',python=platform.python_version(),numpy=np.__version__,
        resource_sha256=hashlib.sha256(resource.read_bytes()).hexdigest(),paths={},
        limitations=['Serial CPU diagnosis, not concurrent bake or end-to-end latency.',
            'Every timed lookup recomputes all samples; immutable resource/setup and query capture are separate.',
            'Trace costs exclude traced callees and include untraced NumPy operations; tracing adds overhead.',
            'Prototypes are isolated CPU operations with prepared inputs, not installed optimizations or GPU measurements.'])
    for name,(t,h) in zip(('entry','export'),queries):
        expected=capacity(t,h);trace=Trace(table);trials=[];last=None
        for _ in range(args.repeats):
            actual,trial,last=trace.run(capacity,t,h);np.testing.assert_array_equal(actual,expected);trials.append(trial)
        untraced=paired({'capacity':lambda:capacity(t,h)},args.repeats)['capacity']
        s=table.selector;region=s.region(t);mask=s.hint_mask(t,h,region)
        counts=np.array([int(v).bit_count() for v in range(32)])[mask]
        chosen=s.left(t,h,region)[0]
        report['paths'][name]=dict(samples=len(t),trials=trials,untraced=untraced,
            hint_candidates={str(i):int(np.count_nonzero(counts==i)) for i in range(1,6)},
            vertex_tie_rows=int(np.count_nonzero(chosen[:,1]!=chosen[:,2])),
            face_rows=np.bincount(last['face'],minlength=6).tolist(),
            face_grid=list(table.expanded['face_codes'].shape),
            face_bytes=sum(v.nbytes for k,v in table.expanded.items() if k.startswith('face_')),
            selection_probes=selection_probes(s,t,h,args.repeats))
    (args.output_dir/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    lines=['# Boundary selection and face-field CPU diagnosis','',
        'Actual 65³ White Ch→C +1 entry/export queries. Milliseconds; serial, no per-ray result cache.','',
        '| Exclusive operation | Entry | Export | Combined |','| --- | ---: | ---: | ---: |']
    paths=report['paths'];groups=dict.fromkeys(k for p in paths.values() for r in p['trials'] for k in r['exclusive_ms'])
    for group in groups:
        times=[median(r['exclusive_ms'].get(group,0.) for r in paths[n]['trials']) for n in paths]
        lines.append(f'| {group} | {times[0]:.2f} | {times[1]:.2f} | {sum(times):.2f} |')
    for name,p in paths.items():
        lines+=['',f'## {name}: {p["samples"]:,} samples','',
            f'Untraced capacity {p["untraced"]["median_ms"]:.2f} ms; traced total '+
            f'{median(t["total_ms"] for t in p["trials"]):.2f} ms.',
            f'Candidate counts: {p["hint_candidates"]}; vertex tie rows: {p["vertex_tie_rows"]}.',
            f'Face grid: {p["face_grid"]}; uint16 field and metadata: {p["face_bytes"]:,} bytes.','',
            '| Isolated alternative | Median |','| --- | ---: |']
        for group in ('candidate_rows','wrapping'):
            for method,values in p['selection_probes'][group].items():
                lines.append(f'| {group}.{method} | {values["median_ms"]:.2f} ms |')
    lines+=['',*(f'- {line}' for line in report['limitations']),'']
    (args.output_dir/'summary.md').write_text('\n'.join(lines))
    print(f'Reports: {args.output_dir}/summary.md and report.json',flush=True)


if __name__=='__main__':main()
