"""Paired unchanged-512 DetMCD math benchmark; writes a standalone JSON report.

Run: buck2 run //products/perceptual-grade-blender:scope_statistics_profile -- --output /tmp/scope-math.json
Add --baseline /path/to/original/statistics.py to compare an archived version.
Both implementations receive exactly the same new-policy sample coordinates.
Photographs are stored every-12th-pixel fixtures, not UI256x192 captures.
"""
import argparse
import hashlib
import importlib.util
from importlib.resources import files
import json
from pathlib import Path
import platform
import sys
import time
import types
import numpy as np
from color_tools.perceptual_grade_core.model import color, forward, linear, scope_color, statistics, tone
from color_tools.perceptual_grade_core.model.saturation import project


def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def timed(function,*args):
    start=time.perf_counter_ns();result=function(*args)
    return result,(time.perf_counter_ns()-start)/1e6


def summary(values):
    values=np.asarray(values,float)
    return dict(median_ms=float(np.median(values)),p95_ms=float(np.percentile(values,95)),
                minimum_ms=float(np.min(values)),maximum_ms=float(np.max(values)),
                observations_ms=values.tolist())


def original_qn(x):
    x=np.asarray(x,float);n=len(x)
    if n<2:return 0.
    i,j=np.triu_indices(n,1);d=np.abs(x[i]-x[j]);h=n//2+1;k=h*(h-1)//2-1
    return statistics.QN_NORMAL*float(np.partition(d,k)[k])


def original_ranks(x):
    order=np.argsort(x,kind='stable');v=x[order];result=np.empty(len(x),float)
    starts=np.r_[0,np.flatnonzero(np.diff(v))+1];ends=np.r_[starts[1:],len(v)]
    for left,right in zip(starts,ends):result[order[left:right]]=(left+right+1)/2
    return result


def original_starts(z):
    n=len(z);h=(n+1)//2
    yield statistics.correlation(np.tanh(z))
    r=np.column_stack([original_ranks(z[:,i]) for i in range(2)])
    yield statistics.correlation(r)
    normal=np.array([[statistics.NORMAL.inv_cdf((v-1/3)/(n+1/3)) for v in row] for row in r])
    yield statistics.correlation(normal)
    lengths=np.linalg.norm(z,axis=1)
    signs=np.divide(z,lengths[:,None],out=np.zeros_like(z),where=lengths[:,None]>0)
    yield statistics.regular(signs.T@signs/n)
    yield statistics.regular(statistics.scatter(z[np.argsort(lengths,kind='stable')[:h]])[1])
    v=(original_qn(z[:,0]+z[:,1])**2-original_qn(z[:,0]-z[:,1])**2)/4
    ogk=np.array([[original_qn(z[:,0])**2,v],[v,original_qn(z[:,1])**2]])
    _,e=np.linalg.eigh(ogk)
    yield statistics.regular((e*np.array([original_qn((z@e)[:,i])**2 for i in range(2)]))@e.T)


def reference_math(path=None):
    if path is not None:
        spec=importlib.util.spec_from_file_location('original_scope_statistics',path)
        result=importlib.util.module_from_spec(spec);spec.loader.exec_module(result)
        return result
    # Rebind unchanged fit functions so corrected_start/detmcd resolve the old
    # Qn implementation too. Nothing is patched in the production module.
    result=types.ModuleType('original_scope_statistics');namespace=result.__dict__
    namespace.update(vars(statistics))
    for name,value in vars(statistics).items():
        if isinstance(value,types.FunctionType):
            namespace[name]=types.FunctionType(value.__code__,namespace,name,value.__defaults__,value.__closure__)
    namespace.update(qn=original_qn,ranks=original_ranks,starts=original_starts)
    return result


def cases():
    rng=np.random.default_rng(20261017)
    source=rng.normal(scale=.025,size=(192*256,2))
    near=np.hypot(source[:,0],source[:,1])<.1
    sample,ids=statistics.hashed_sample(source,near.astype(float))
    sample[-52:]+=[.15,-.12];sample=sample.astype(np.float32).astype(np.float64)
    yield dict(name='seeded-gaussian-10pct-output-outliers',
               basis='seed20261017;192x256Stage2field;52of512sampledoutputpointsshifted',
               source_count=len(source),eligible_count=int(near.sum()),sample=sample,sample_ids=ids)
    space=linear.GradeSpace('D65');parameters=tone.Parameters()
    tm=tone.model(parameters,space);cm=color.model(parameters,color.Parameters(),space)
    engine=forward.Model(tm)
    matrix=np.asarray(linear.xyz_to_rgb(space))@np.asarray(linear.rgb_to_xyz('Linear Rec.2020'))
    for path in sorted(files('perceptual_grade_photographs').iterdir(),key=lambda value:value.name):
        if not path.name.endswith('.npy'):continue
        source=np.load(path).astype(float);rgb=source@matrix.T
        app=engine.encode_cones(tm.cones(rgb));q=app.q;energy=app.ja*abs(app.ja)
        H=np.hypot(app.ja,np.sqrt(66*np.hypot(q[...,1],q[...,2])))
        groups=scope_color.tone_groups(cm,H);near=scope_color.near_neutral(q,energy)
        coordinates=project(q,energy).reshape(-1,2)
        for index in range(4):
            eligible=near&(groups==index);count=int(np.count_nonzero(eligible))
            if count<512:continue
            sample,ids=statistics.hashed_sample(coordinates,eligible.ravel().astype(float))
            sample=sample.astype(np.float32).astype(np.float64)
            yield dict(name=path.stem+'-tone'+str(index),basis='fixtureevery12throw/column;identitygrade',
                       fixture_sha256=digest(path),tone=index,source_shape=list(source.shape),
                       source_count=len(coordinates),eligible_count=count,sample=sample,sample_ids=ids)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline',type=Path,help='Archived original statistics.py; default uses embedded original Qn/rank/start math')
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--repetitions',type=int,default=50)
    args=parser.parse_args()
    if args.repetitions<1:parser.error('repetitions must be positive')
    baseline=reference_math(args.baseline)
    statistics._qn_indices.cache_clear();statistics._normal_scores.cache_clear()
    report=dict(python=sys.version,numpy=np.__version__,platform=platform.platform(),
                baseline_kind='archived_source' if args.baseline is not None else 'embedded_original_qn_ranks_starts',
                baseline_sha256=digest(args.baseline) if args.baseline is not None else None,
                optimized_sha256=digest(statistics.__file__),benchmark_sha256=digest(__file__),
                sample_policy='saturation<0.1;SplitMix64originalrasterID;distinctalphaweightedpriority;512',
                fit_precision='float32coordinatespromotedtofloat64,matchingGPUgatherthenfit',
                repetitions=args.repetitions,warmups=3,
                limitations='CPUmathonly;noGPU,IPC,BlenderdraworUIcapture;storedphotographfixturesarenotUI256x192grids',
                cases=[])
    for case in cases():
        points=case.pop('sample');ids=case.pop('sample_ids')
        assert len(points)==512
        case.update(sample_count=len(points),sample_ids_sha256=hashlib.sha256(ids.astype('<i8').tobytes()).hexdigest(),
                    sample_coordinates_sha256=hashlib.sha256(points.astype('<f8').tobytes()).hexdigest())
        original=baseline.detmcd(points);improved=statistics.detmcd(points)
        case['exact_center_equal']=np.array_equal(original[0],improved[0])
        case['exact_covariance_equal']=np.array_equal(original[1],improved[1])
        assert case['exact_center_equal'] and case['exact_covariance_equal']
        for _ in range(3):baseline.detmcd(points);statistics.detmcd(points)
        before=[];after=[]
        for iteration in range(args.repetitions):
            order=((baseline.detmcd,before),(statistics.detmcd,after))
            if iteration%2:order=order[::-1]
            for function,times in order:
                result,elapsed=timed(function,points);times.append(elapsed)
                assert all(np.array_equal(value,reference) for value,reference in zip(result,original))
        case['original_math']=summary(before);case['optimized_math']=summary(after)
        case['median_speedup']=case['original_math']['median_ms']/case['optimized_math']['median_ms']
        report['cases'].append(case)
        print(case['name'],case['eligible_count'],
              round(case['original_math']['median_ms'],3),'->',round(case['optimized_math']['median_ms'],3),
              'ms',round(case['median_speedup'],3),'x',flush=True)
    report['cache_info']={name:getattr(statistics,name).cache_info()._asdict()
                          for name in ('_qn_indices','_normal_scores')}
    report['retained_512_table_bytes']=sum(v.nbytes for v in statistics._qn_indices(512))+statistics._normal_scores(512).nbytes
    report['median_case_speedup']=float(np.median([case['median_speedup'] for case in report['cases']]))
    args.output.write_text(json.dumps(report,indent=2)+'\n')
    print('Report:',args.output,flush=True)


if __name__=='__main__':main()
