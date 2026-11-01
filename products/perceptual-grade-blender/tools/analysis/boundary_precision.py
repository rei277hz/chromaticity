"""Compare 16-bit face tables within 1 MiB; diagnostic only, no resource refit."""
import argparse
import hashlib
from importlib.resources import files
import itertools
import json
import math
from pathlib import Path
import time
from unittest.mock import patch
import numpy as np
from color_tools.perceptual_grade_blender.model import boundary_gpu
from color_tools.perceptual_grade_core.model import boundary_polynomial, lut
from color_tools.perceptual_grade_core.model.bake import Kernel
from tests.reference.legacy_capacity import LegacyCapacityModel
from tools.build.boundary_oracle import capacity_unit, exact_geometry
from tools.build.boundary_table import decode_unit
from .bake_check import cases
from .boundary_profile import FaceField, paired


class StoredFace:
    """Float16 or affine uint16 storage; four decoded fetches and float32 math."""
    def __init__(self,field,values,storage):
        self.field=field;self.n=values.shape[1];self.storage=storage
        if storage=='uint16':
            self.offset=values.min(axis=(1,2))
            self.scale=((values.max(axis=(1,2)).astype(float)-self.offset)/65535).astype('f4')
            if np.any(self.scale<=0):raise ArithmeticError('Degenerate fixed-point face range')
            self.values=np.rint((values.astype(float)-self.offset[:,None,None])/self.scale[:,None,None]).clip(0,65535).astype('u2')
            decoded=self.values.astype('f4')*self.scale[:,None,None]+self.offset[:,None,None]
        else:
            self.values=values.astype('f2' if storage=='float16' else 'f4')
            decoded=self.values.astype('f4')
        if not np.isfinite(decoded).all():raise ArithmeticError('Nonfinite storage conversion')
        error=abs(decoded.astype(float)-values);worst=np.unravel_index(error.argmax(),error.shape)
        self.quantization=dict(max_absolute_node_error=float(error[worst]),
            face_xy=list(map(int,worst)),expected=float(values[worst]),actual=float(decoded[worst]),
            per_face_max_absolute_error=error.max(axis=(1,2)).tolist(),
            per_face_value_range=np.stack((values.min(axis=(1,2)),values.max(axis=(1,2))),-1).tolist(),
            offset=self.offset.tolist() if storage=='uint16' else None,
            step=self.scale.tolist() if storage=='uint16' else None)
        self.values=self.values.ravel()
        self.bytes=self.values.nbytes+(48 if storage=='uint16' else 0)

    def evaluate(self,t,face,s,left,right):
        n=self.n;u=(t-self.field.low[face])/self.field.span[face]*(n-1);v=s*(n-1)
        i=np.clip(u.astype('i4'),0,n-2);j=np.clip(v.astype('i4'),0,n-2)
        a=u-i.astype('f4');b=v-j.astype('f4');index=(face*n+i)*n+j
        q00=self.values[index].astype('f4',copy=False);q01=self.values[index+1].astype('f4',copy=False)
        row0=q00+a*(self.values[index+n].astype('f4',copy=False)-q00)
        row1=q01+a*(self.values[index+n+1].astype('f4',copy=False)-q01)
        correction=row0+b*(row1-row0)
        if self.storage=='uint16':correction=correction*self.scale[face]+self.offset[face]
        return self.field.combine(s,left,right,correction)

    def capacity(self,t,hue):
        t,hue=np.broadcast_arrays(np.asarray(t,dtype='f4'),np.asarray(hue,dtype='f4'))
        shape=t.shape;t=t.ravel();hue=hue.ravel()
        f,s,_,_,left,right=self.field.selector.select(t,hue)
        return self.evaluate(t,f,s,left,right).reshape(shape)


def pixel_metrics(actual,expected,rgb,coordinate_name='input_rgb'):
    actual=np.asarray(actual,dtype=float);expected=np.asarray(expected,dtype=float)
    difference=np.max(abs(actual-expected),-1);peak=np.max(expected,-1)
    limit=np.maximum(.001*peak,1e-7);score=difference/limit
    relative=np.divide(difference,peak,out=np.zeros_like(difference),where=peak>0)
    def witness(i):
        return dict(index=int(i),**{coordinate_name:rgb[i].tolist()},expected=expected[i].tolist(),actual=actual[i].tolist(),
            max_absolute_error=float(difference[i]),relative_to_peak=float(relative[i]) if peak[i]>0 else None,
            tolerance_fraction=float(score[i]))
    return dict(samples=len(rgb),maximum_absolute_error=float(difference.max()),
        maximum_relative_error=float(relative.max()),maximum_tolerance_fraction=float(score.max()),
        tolerance_failures=int(np.count_nonzero(score>1)),
        outside_cube_pixels=int(np.count_nonzero(np.any((actual<0)|(actual>1024),-1))),
        nonfinite_pixels=int(np.count_nonzero(~np.isfinite(actual).all(-1))),
        black_mismatches=int(np.count_nonzero(np.any(actual[peak==0]!=0,axis=-1))),
        minimum_rgb=float(actual.min()),maximum_rgb=float(actual.max()),
        worst_absolute=witness(int(difference.argmax())),worst_relative=witness(int(relative.argmax())),
        worst_tolerance=witness(int(score.argmax())),
        minimum_witness=witness(int(np.argmin(actual)//3)),maximum_witness=witness(int(np.argmax(actual)//3)))


def inputs(size):
    axis=.01*np.expm1(np.linspace(0,1,size)*np.log1p(1024/.01));axis[0],axis[-1]=0,1024
    grid=np.stack(np.meshgrid(axis,axis,axis,indexing='ij'),-1).reshape(-1,3)
    linear=np.linspace(0,1024,33)
    grid=np.vstack((grid,np.stack(np.meshgrid(linear,linear,linear,indexing='ij'),-1).reshape(-1,3)))
    rng=np.random.default_rng(525);count=16384
    grid=np.vstack((grid,rng.uniform(0,1024,(count,3)),.01*np.expm1(rng.uniform(0,1,(count,3))*np.log1p(1024/.01))))
    # Probe both sides of every cube edge, in addition to exact faces/corners.
    edges=[]
    for free in range(3):
        for ends in itertools.product((0.,1024.),repeat=2):
            row=np.empty((257,3));row[:,free]=np.linspace(0,1024,len(row))
            row[:,[i for i in range(3) if i!=free]]=ends
            edges.extend((row,np.clip(row+1e-5,0,1024),np.clip(row-1e-5,0,1024)))
    grid=np.vstack((grid,*edges,[[.0253184813856082,.0071734681614134,.0043407546657122],
        [1024,1024,.0019752890009854],[0,938.63,0],[0,1,0],[2,0,128],[2,0,1]]))
    return grid.astype('f4')


def aggregate(items):
    summary={}
    for group,metric in (('worst_absolute','maximum_absolute_error'),('worst_relative','maximum_relative_error'),
                         ('worst_tolerance','maximum_tolerance_fraction')):
        case=max(items,key=lambda item:item['oracle'][metric])
        summary[group]=dict(case=case['name'],**case['oracle'][group])
    for key in ('tolerance_failures','outside_cube_pixels','nonfinite_pixels','black_mismatches'):
        summary[key]=sum(item['oracle'][key] for item in items)
    for group,metric,choose in (('minimum_witness','minimum_rgb',min),('maximum_witness','maximum_rgb',max)):
        case=choose(items,key=lambda item:item['oracle'][metric])
        summary[metric]=case['oracle'][metric];summary[group]=dict(case=case['name'],**case['oracle'][group])
    return summary


def render(report,output_dir):
    lines=['# 1 MiB face-table storage experiment','',
        f'{report["samples_per_case"]:,} input pixels × {len(report["current_baseline"])} grades; independent float64 geometric oracle.','',
        'Each maximum below is over the stated sample set, not a continuous-domain certificate.','',
        '| Storage | Grid | Whole lookup bytes | Within 1 MiB | CPU face ms | Max absolute RGB error | Worst tolerance fraction | Out-of-cube pixels |',
        '| --- | --- | ---: | --- | ---: | ---: | ---: | ---: |']
    for key,result in report['candidates'].items():
        result['summary']=aggregate(result['cases']);summary=result['summary']
        result['summary_vs_current']=aggregate([dict(name=c['name'],oracle=c['current']) for c in result['cases']])
        if result['cases'][0]['quantization_only'] is not None:
            result['summary_quantization_only']=aggregate([dict(name=c['name'],oracle=c['quantization_only']) for c in result['cases']])
        ms=sum(v['median_ms'] for v in result['face_timing'].values())
        lines.append(f'| {key} | {result["nodes"]}² | {result["total_lookup_bytes"]:,} | {result["within_budget"]} | {ms:.2f} | '+
            f'{summary["worst_absolute"]["max_absolute_error"]:.8g} | {summary["worst_tolerance"]["tolerance_fraction"]:.8g} | {summary["outside_cube_pixels"]:,} |')
    current_ms=sum(v['median_ms'] for v in report['current_face_timing'].values())
    report['current_summary']=aggregate(report['current_baseline']);baseline=report['current_summary']
    lines+=['',f'Current polynomial face phase: {current_ms:.2f} ms. Current full-grade baseline: '+
        f'{baseline["tolerance_failures"]} tolerance failures, {baseline["outside_cube_pixels"]} out-of-cube evaluations.',
        '', 'Tolerance is max(0.001 × oracle pixel peak, 1e-7 ACEScg); a fraction above 1 fails.',
        'Large raw relative errors at nearly black pixels can still be far below the absolute tolerance.','',
        '| Storage | Max table-node quantization error | Max boundary-capacity error vs oracle | Max RGB error from 16-bit storage alone |',
        '| --- | ---: | ---: | ---: |']
    for key,result in report['candidates'].items():
        quant=result.get('summary_quantization_only')
        extra=f'{quant["worst_absolute"]["max_absolute_error"]:.8g}' if quant is not None else 'Different grid'
        lines.append(f'| {key} | {result["quantization"]["max_absolute_node_error"]:.8g} | '+
            f'{100*result["boundary"]["maximum_absolute_relative_error"]:.6f}% | {extra} |')
    for key,result in report['candidates'].items():
        summary=result['summary'];lines+=['',f'## {key}','',
            f'Observed RGB range [{summary["minimum_rgb"]:.9g}, {summary["maximum_rgb"]:.9g}]. '+
            f'Tolerance failures: {summary["tolerance_failures"]}; nonfinite: {summary["nonfinite_pixels"]}; black mismatches: {summary["black_mismatches"]}.']
        for metric in ('worst_absolute','worst_tolerance','worst_relative','minimum_witness','maximum_witness'):
            witness=summary[metric]
            lines+=['',f'- {metric}, {witness["case"]}: input {witness["input_rgb"]}; expected {witness["expected"]}; actual {witness["actual"]}.']
        if 'summary_quantization_only' in result:
            witness=result['summary_quantization_only']['worst_absolute']
            lines+=['',f'- Largest storage-only difference, {witness["case"]}: input {witness["input_rgb"]}; same-grid float32 {witness["expected"]}; stored format {witness["actual"]}.']
    witness=baseline['worst_tolerance']
    lines+=['','## Existing implementation witness','',
        f'{witness["case"]}: input {witness["input_rgb"]}; oracle {witness["expected"]}; current {witness["actual"]}; '+
        f'tolerance fraction {witness["tolerance_fraction"]:.9g}.','',*(f'- {line}' for line in report['limitations']),'']
    (output_dir/'report.json').write_text(json.dumps(report,indent=2,allow_nan=False)+'\n')
    (output_dir/'summary.md').write_text('\n'.join(lines))
    print(f'Reports: {output_dir}/summary.md and report.json',flush=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir',required=True,type=Path)
    parser.add_argument('--size',type=int,default=65)
    parser.add_argument('--repeats',type=int,default=7)
    parser.add_argument('--summarize',action='store_true',help='Format an existing report without rerunning numerical work')
    args=parser.parse_args()
    if args.size<2 or args.repeats<1:parser.error('Require size >= 2 and repeats >= 1')
    args.output_dir.mkdir(parents=True,exist_ok=True)
    if args.summarize:
        render(json.loads((args.output_dir/'report.json').read_text()),args.output_dir)
        return
    resource=files('color_tools.perceptual_grade_core.model')/'d65_boundary.npz'
    with np.load(resource,allow_pickle=False) as archive:data=dict(archive)
    table=boundary_polynomial.PolynomialTable(data);field=FaceField(table,data)
    packed,_=boundary_gpu.pack(data,table.expanded)
    cpu_other=sum(v.nbytes for k,v in table.expanded.items() if not k.startswith('face_'))
    # GPU pack already includes affine metadata and bounds; keep the conservative
    # experiment accounting (48 extra bytes of bounds) for comparable grid sizes.
    shared=max(packed.nbytes,cpu_other)+field.low.nbytes+field.span.nbytes;budget=1024**2
    n32=math.isqrt((budget-shared)//24);n16=math.isqrt((budget-shared-48)//12)
    candidates={};setups={}
    for n in (n32,n16):
        start=time.perf_counter();values=field.sample(n);setup=1000*(time.perf_counter()-start)
        for storage in (('float32',) if n==n32 else ('float32','float16','uint16')):
            key=f'{storage}_{n}';candidates[key]=StoredFace(field,values,storage);setups[key]=setup
    report=dict(budget_bytes=budget,shared_lookup_budget_bytes=shared,unchanged_cpu_bytes=cpu_other,
        unchanged_gpu_payload_bytes=packed.nbytes,resource_sha256=hashlib.sha256(resource.read_bytes()).hexdigest(),
        samples_per_case=0,candidates={},limitations=[
            'Measured maxima over stated deterministic samples, not continuous global error bounds.',
            'Storage budget counts unchanged GPU-padded or CPU numeric payload, whichever is larger, plus table metadata; driver allocation is unmeasured.',
            'All candidate interpolation is bilinear and does not satisfy the existing C2 contract.',
            'No new containment reserve or RGB repair is added; quantify the raw approximation and quantization.',
            'Reference expectations use float64 grading and offline iterative geometry; no persistent resource is regenerated.',
            'Face timings recompute all values, excluding selector and immutable setup; not end-to-end or GPU timing.'])
    for key,candidate in candidates.items():
        report['candidates'][key]=dict(storage=candidate.storage,nodes=candidate.n,
            table_bytes=candidate.bytes,total_lookup_bytes=shared+candidate.bytes,
            within_budget=shared+candidate.bytes<=budget,table_setup_ms=setups[key],
            quantization=candidate.quantization,cases=[])
    def save():
        (args.output_dir/'report.json').write_text(json.dumps(report,indent=2,allow_nan=False)+'\n')
    rgb=inputs(args.size);report['samples_per_case']=len(rgb);save()
    settings_list=list(cases());base=LegacyCapacityModel(settings_list[0][1],space='ACEScg',hk_guard=True);ctx=base.boundary
    print(f'Budget: float32 {n32}²; 16-bit {n16}². {len(rgb):,} input pixels per grade.',flush=True)
    with exact_geometry():oracle_entry=base.enter_native(rgb.astype(float))
    print('Independent float64 entry complete.',flush=True)
    for name,settings in settings_list:
        oracle=LegacyCapacityModel(settings,space='ACEScg',hk_guard=True);kernel=Kernel(data,oracle.tone,oracle.color,table=table,hk_guard=True)
        with exact_geometry():
            expected=rgb.astype(float) if name=='reset' else oracle.release_state(oracle.grade_state(oracle_entry),guard=True)
        current=kernel.evaluate(rgb);actuals={}
        for key,candidate in candidates.items():
            with patch.object(table,'capacity',side_effect=candidate.capacity):actuals[key]=kernel.evaluate(rgb)
        for key,actual in actuals.items():
            item=dict(name=name,oracle=pixel_metrics(actual,expected,rgb),
                current=pixel_metrics(actual,current,rgb),
                quantization_only=pixel_metrics(actual,actuals[f'float32_{n16}'],rgb) if candidates[key].n==n16 else None)
            report['candidates'][key]['cases'].append(item)
        report.setdefault('current_baseline',[]).append(dict(name=name,oracle=pixel_metrics(current,expected,rgb)))
        save();print(f'Grade {name} complete.',flush=True)
    # Boundary-only probes expose worst geometry even where a grade does not
    # reach the face. Include vertex/crease neighborhoods and both tips.
    rng=np.random.default_rng(5251)
    t=np.r_[rng.uniform(0,1,65536),np.geomspace(1e-10,.01,1024),1-np.geomspace(1e-7,.01,1024),
        (field.selector.vertices[:,None]+rng.uniform(-.001,.001,(8,2048))).ravel()]
    t=np.clip(t,0,1).astype('f4');h=rng.uniform(-np.pi,np.pi,len(t)).astype('f4')
    edges=np.repeat(np.arange(12),513);edge_x=np.tile(np.linspace(0,1,513,dtype='f4'),12)
    low,high=field.selector.vertices[field.selector.edges[edges]].T;et=low+(high-low)*edge_x
    eh=field.selector.curve(et,edges,0)
    t=np.r_[t,et,et,et];h=np.r_[h,eh,np.nextafter(eh,np.float32(-np.inf)),np.nextafter(eh,np.float32(np.inf))]
    f,s,_,_,left,right=field.selector.select(t,h);queries=(t,f,s,left,right)
    exact=capacity_unit(t.astype(float),h.astype(float),ctx.fl,ctx.aw,ctx.matrix)
    expected_rgb=decode_unit(ctx,t.astype(float),h.astype(float),exact)
    current=table.capacity(t,h)
    # The adopted path must match the independent experiment's addressing,
    # storage and interpolation, not the superseded polynomial field.
    np.testing.assert_array_equal(candidates['uint16_257'].capacity(t,h),current)
    for key,candidate in candidates.items():
        actual=candidate.evaluate(*queries);error=actual.astype(float)/exact-1;i=int(np.argmax(abs(error)))
        decoded=decode_unit(ctx,t.astype(float),h.astype(float),actual.astype(float))
        qerror=actual.astype(float)/candidates[f'float32_{n16}'].evaluate(*queries)-1 if candidate.n==n16 else None
        report['candidates'][key]['boundary']=dict(samples=len(t),maximum_absolute_relative_error=float(abs(error).max()),
            minimum_signed_relative_error=float(error.min()),maximum_signed_relative_error=float(error.max()),
            quantization_only_max_relative_error=float(abs(qerror).max()) if qerror is not None else None,
            worst_capacity=dict(t=float(t[i]),hue=float(h[i]),face=int(f[i]),expected=float(exact[i]),actual=float(actual[i]),
                expected_rgb=expected_rgb[i].tolist(),actual_rgb=decoded[i].tolist()),
            rgb=pixel_metrics(decoded,expected_rgb,np.column_stack((t,h,exact)),coordinate_name='ray_t_h_capacity'))
        report['candidates'][key]['summary']=aggregate(report['candidates'][key]['cases'])
    report['current_summary']=aggregate(report['current_baseline'])
    # Time the same actual 65³ White +1 entry/export face work as the previous
    # experiment. Per-lattice entry/tone/weight results are never memoized.
    _,settings=settings_list[2];oracle=LegacyCapacityModel(settings,space='ACEScg',hk_guard=True);kernel=Kernel(data,oracle.tone,oracle.color,table=table,hk_guard=True)
    captured=[];original=table.capacity
    def capture(t,h):
        f,s,_,_,left,right=field.selector.select(t,h);captured.append((t.copy(),f,s,left,right))
        return original(t,h)
    with patch.object(table,'capacity',side_effect=capture):kernel.evaluate(lut.lattice().astype('f4'))
    if len(captured)!=2:raise ArithmeticError('Unexpected timed lookup flow')
    for name,query in zip(('entry','export'),captured):
        operations={'current':lambda:table.field(*query),'source_polynomial':lambda:field.current(*query)}
        operations.update({key:lambda c=c:c.evaluate(*query) for key,c in candidates.items()})
        timing=paired(operations,args.repeats)
        report.setdefault('current_face_timing',{})[name]=timing['current']
        report.setdefault('source_polynomial_face_timing',{})[name]=timing['source_polynomial']
        for key in candidates:report['candidates'][key].setdefault('face_timing',{})[name]=timing[key]
    render(report,args.output_dir)


if __name__=='__main__':main()
