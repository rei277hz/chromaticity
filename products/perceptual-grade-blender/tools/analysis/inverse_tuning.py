from color_tools.perceptual_grade_blender.model.bake_inverse_gpu import Program as ReferenceGPUProgram
"""Tune reference inverse settings against rendered combined 65-cube recovery."""
import argparse
from dataclasses import asdict,dataclass
import hashlib
from importlib.resources import files
import itertools
import json
from pathlib import Path
import time
import numpy as np
from color_tools.perceptual_grade_core.model import bake_inverse
from tools.analysis.inverse_bake_profile import study_policy,cpu_bake
from tests.reference.legacy_capacity import LegacyCapacityBakeStack
from tools.analysis.photo_io import load_fixtures,ocio_processors,apply_processor
from tools.analysis.photo_stack import ForcedStack,cases,lattice,prepare,eval_core,endpoint,tetrahedral
from tools.analysis.stack_photo_error import metrics,CODE_MAX


LIMITS={'SDR100':.1,'HDR1000':.4}


def gate(maximum_codes,view):
    """Strict final-LUT gate, in nominal encoded code values before rounding."""
    if not np.isfinite(maximum_codes) or maximum_codes<0:
        raise ValueError('Expected a finite nonnegative error')
    return bool(maximum_codes<LIMITS[view])


@dataclass(frozen=True)
class Policy:
    rounds:int=40
    stopping:float=1e-6
    raw:float=1e-4
    tone:float=2e-6

    @property
    def key(self):return f'i{self.rounds}_s{self.stopping:g}_a{self.raw:g}_t{self.tone:g}'

    def scope(self):
        return study_policy(stage3_iterations=self.rounds,stage3_stopping=self.stopping,
                            raw_tolerance=self.raw,tone_table_tolerance=self.tone)


def linear_metrics(actual,expected):
    """Native AP1 error; relative error is undefined at exact reference black."""
    a=np.asarray(actual,dtype=float).reshape(-1,3);e=np.asarray(expected,dtype=float).reshape(-1,3)
    error=np.max(abs(a-e),axis=1);peak=np.max(abs(e),axis=1);nonzero=peak>0
    relative=np.divide(error,peak,out=np.zeros_like(error),where=nonzero)
    absolute_index=int(np.argmax(error));relative_index=int(np.argmax(relative))
    return dict(maximum_absolute=float(error[absolute_index]),maximum_relative_nonblack=float(relative[relative_index]),
        reference_black_pixels=int(np.count_nonzero(~nonzero)),black_maximum_absolute=float(error[~nonzero].max(initial=0)),
        worst_absolute=dict(index=absolute_index,expected=e[absolute_index].tolist(),actual=a[absolute_index].tolist()),
        worst_relative=dict(index=relative_index,expected=e[relative_index].tolist(),actual=a[relative_index].tolist()))


class Experiment:
    def __init__(self,output):
        self.output=output;output.mkdir(parents=True,exist_ok=True)
        self.ocio=ocio_processors();self.fixtures=load_fixtures()
        for f in self.fixtures:f['native']=apply_processor(self.ocio['convert'],f['rgb'])
        self.resource=files('color_tools.perceptual_grade_reference')/'d65_boundary.npz'
        self.digest=hashlib.sha256(self.resource.read_bytes()).hexdigest()
        start=time.perf_counter();self.table=ForcedStack([],[]).table
        self.lookup_seconds=time.perf_counter()-start
        self.grid=lattice();self.prepared={};self.expected={};self.rows=[];self.renderer=None

    def inputs(self,name):
        if name not in self.prepared:
            s=cases()[name];stack=ForcedStack([s,s],['FORWARD','INVERSE'],self.table)
            self.prepared[name]={f['name']:prepare(stack,f['native']) for f in self.fixtures}
            self.expected[name]={f['name']:{view:apply_processor(p,self.prepared[name][f['name']]['ideal'])
                for view,p in self.ocio['displays'].items()} for f in self.fixtures}
        return self.prepared[name],self.expected[name]

    def evaluate(self,policy,names,backends=('CPU',),save=False):
        record=dict(policy=asdict(policy),key=policy.key,passed=True,cases=[],cpu_seconds=0.)
        program=None
        with policy.scope() as effective:
            record['effective_policy']=effective
            for name in names:
                prepared,expected=self.inputs(name)
                for backend in backends:
                    setting=cases()[name];start=time.perf_counter()
                    stack=ForcedStack([setting,setting],['FORWARD','INVERSE'],self.table)
                    setup=time.perf_counter()-start
                    if backend=='GPU':
                        if program is None:
                            start=time.perf_counter();program=stack.prepare_gpu()
                            record['gpu_preparation_seconds']=time.perf_counter()-start
                            record['shader_creation_seconds']=program.compile_seconds
                        else:stack.program=program
                    start=time.perf_counter();cube=eval_core(stack,self.grid,backend,65536 if backend=='CPU' else 4096)
                    duration=time.perf_counter()-start
                    if backend=='CPU':record['cpu_seconds']+=setup+duration
                    if save:np.save(self.output/f'{policy.key}-{name}-{backend.lower()}-65.npy',cube)
                    row=dict(case=name,backend=backend,setup_seconds=setup,bake_seconds=duration,
                        tone_table_seconds=stack.tone_table_seconds,
                        tone_tables=[dict(tolerance=t.tolerance,cells=t.cells,bytes=t.bytes,rounds=t.rounds,
                            maximum_root_iterations=t.maximum_root_iterations,max_error=t.max_error) for t in stack.tone_tables],
                        approximate_vertices=int(np.count_nonzero(cube[:,3]>policy.raw)),
                        maximum_raw_residual=float(cube[:,3].max()),minimum_rgb=float(cube[:,:3].min()),
                        maximum_rgb=float(cube[:,:3].max()),passed=True,photographs=[],maxima={v:0. for v in LIMITS})
                    for f in self.fixtures:
                        prep=prepared[f['name']];actual=endpoint(stack,tetrahedral(cube[:,:3],prep['input']))
                        item=dict(fixture=f['name'],linear=linear_metrics(actual,prep['ideal']),views={})
                        for view,p in self.ocio['displays'].items():
                            encoded=apply_processor(p,actual);m=metrics(encoded,expected[f['name']][view],CODE_MAX[view])
                            maximum=m['codes']['maximum'];passed=gate(maximum,view)
                            y,x=np.unravel_index(m['worst']['flat_index'],actual.shape[:2])
                            m['worst'].update(sample_xy=[int(x),int(y)],original_xy=[int(x)*12,int(y)*12],
                                source_acescg=f['native'][y,x].tolist(),ideal_acescg=prep['ideal'][y,x].tolist(),
                                actual_acescg=actual[y,x].tolist())
                            m['passed']=passed;item['views'][view]=m
                            row['maxima'][view]=max(row['maxima'][view],maximum);row['passed']&=passed
                        row['photographs'].append(item)
                    record['passed']&=row['passed'];record['cases'].append(row)
                    print(f'{policy.key} {name} {backend}: {1000*(setup+duration):.1f} ms, '
                          f'SDR {row["maxima"]["SDR100"]:.6f}, HDR {row["maxima"]["HDR1000"]:.6f}, '
                          f'{"PASS" if row["passed"] else "FAIL"}',flush=True)
        self.rows.append(record);self.write()
        return record

    def write(self):
        unchanged=self.digest==hashlib.sha256(self.resource.read_bytes()).hexdigest()
        if not unchanged:raise ArithmeticError('D65 resource changed')
        report=dict(limits=LIMITS,code_max=CODE_MAX,ocio=self.ocio['metadata'],
            samples=sum(f['rgb'].shape[0]*f['rgb'].shape[1] for f in self.fixtures),
            fixtures=[dict(name=f['name'],metadata=f['metadata']) for f in self.fixtures],
            d65_sha256=self.digest,d65_unchanged=unchanged,lookup_preparation_seconds=self.lookup_seconds,
            numpy=np.__version__,renderer=self.renderer,results=self.rows,limitations=[
                'The gate is the combined forced forward/inverse 65-cube versus the repair-aware original, not a direct-solver gate.',
                'Photographs retain every twelfth row/column; these are sampled findings, not global error bounds.',
                'Both endpoints use the same grade, with matching-pair cancellation disabled.',
                'RGB acceptance is unchanged and not exercised by the raw appearance handoff.',
                'Screening times are single fresh grade+bake trials, not final benchmark medians.',
                'GPU first dispatch can include deferred compilation; it is retained in reported first-bake time.',
                'No standalone inverse-LUT interpolation, Extension or D65 changes.'])
        (self.output/'report.json').write_text(json.dumps(report,indent=2,allow_nan=False)+'\n')
        lines=['# Inverse tuning against rendered combined LUT error','',
            'Strict maxima: SDR <0.1 of 255, HDR <0.4 of 1023. All comparisons precede quantization.','',
            '| Policy | Case | Backend | Fresh setup + bake ms | SDR maximum | HDR maximum | Gate |',
            '| --- | --- | --- | ---: | ---: | ---: | --- |']
        for r in self.rows:
            for c in r['cases']:
                lines.append(f'| {r["key"]} | {c["case"]} | {c["backend"]} | '
                    f'{1000*(c["setup_seconds"]+c["bake_seconds"]):.2f} | {c["maxima"]["SDR100"]:.6f} | '
                    f'{c["maxima"]["HDR1000"]:.6f} | {"PASS" if c["passed"] else "FAIL"} |')
        lines+=['','Immutable D65/context preparation: '+f'{1000*self.lookup_seconds:.2f} ms.','',
            'Single screening timings rank candidates provisionally; benchmark finalists with repeated fresh grades.','']
        (self.output/'summary.md').write_text('\n'.join(lines))


def screen(experiment):
    seen={}
    def evaluate(p):
        if p.key not in seen:seen[p.key]=experiment.evaluate(p,('mixed','mixed_tone'))
        return seen[p.key]
    evaluate(Policy())
    for rounds,stop in itertools.product((8,12,16,24,32,40),(1e-6,2e-6,5e-6,1e-5)):
        evaluate(Policy(rounds,stop))
    candidates=sorted((r for r in seen.values() if r['passed']),key=lambda r:r['cpu_seconds'])[:3]
    for r in candidates:
        base=Policy(**r['policy'])
        for raw,tone in itertools.product((5e-5,1e-4,2e-4,5e-4),(2e-6,5e-6,1e-5,2e-5)):
            evaluate(Policy(base.rounds,base.stopping,raw,tone))
    ranking=sorted((r for r in seen.values() if r['passed']),key=lambda r:r['cpu_seconds'])
    (experiment.output/'ranking.json').write_text(json.dumps([
        dict(key=r['key'],policy=r['policy'],cpu_seconds=r['cpu_seconds']) for r in ranking],indent=2)+'\n')


def parse_policy(value):
    values=value.split(',')
    if len(values)!=4:raise argparse.ArgumentTypeError('Policy is rounds,stopping,raw,tone')
    try:return Policy(int(values[0]),*map(float,values[1:]))
    except ValueError as e:raise argparse.ArgumentTypeError(str(e)) from e


def timings(experiment,policies,names,repeats):
    """Interleave fresh grades; shared immutable lookup preparation is separate."""
    rows={};outputs={}
    for trial in range(repeats):
        order=policies[trial%len(policies):]+policies[:trial%len(policies)]
        for name,route in itertools.product(names,('paired','inverse')):
            setting=cases()[name]
            for policy in order:
                with policy.scope():
                    start=time.perf_counter()
                    stack=(ForcedStack([setting,setting],['FORWARD','INVERSE'],experiment.table)
                           if route=='paired' else LegacyCapacityBakeStack([setting],['INVERSE'],experiment.table, program_factory=ReferenceGPUProgram))
                    setup=time.perf_counter()-start;start=time.perf_counter()
                    value=cpu_bake(stack,experiment.grid,65536);bake=time.perf_counter()-start
                key=(policy.key,name,route)
                row=rows.setdefault(key,dict(policy=asdict(policy),key=policy.key,case=name,route=route,trials=[]))
                equal=key not in outputs or np.array_equal(outputs[key],value)
                if not equal:raise ArithmeticError('Repeated CPU bake changed results')
                outputs[key]=value
                row['trials'].append(dict(setup_seconds=setup,bake_seconds=bake,total_seconds=setup+bake,
                    tone_table_seconds=stack.tone_table_seconds,bit_identical_to_first=equal))
                print(f'trial {trial+1} {policy.key} {name}/{route}: {1000*(setup+bake):.2f} ms',flush=True)
    for row in rows.values():
        values=[t['total_seconds'] for t in row['trials']]
        row.update(median_seconds=float(np.median(values)),minimum_seconds=min(values),maximum_seconds=max(values))
    ranking=[]
    for p in policies:
        values=[r['median_seconds'] for r in rows.values() if r['key']==p.key]
        ranking.append(dict(key=p.key,policy=asdict(p),geometric_mean_seconds=float(np.exp(np.mean(np.log(values))))))
    ranking.sort(key=lambda r:r['geometric_mean_seconds'])
    report=dict(repeats=repeats,cpu_workers=4,chunk=65536,lookup_preparation_seconds=experiment.lookup_seconds,
        d65_sha256=experiment.digest,results=list(rows.values()),ranking=ranking,
        selection='Geometric mean of fresh setup+bake medians over tone/mixed/mixed-tone paired and inverse workloads; image gates validated separately.')
    (experiment.output/'timings.json').write_text(json.dumps(report,indent=2)+'\n')
    lines=['# Interleaved fresh CPU bake timings','',
        'Every trial is retained. Policy order rotates between trials; no LUT results are reused.','',
        '| Policy | Grade | Route | Median ms | Min–max ms |','| --- | --- | --- | ---: | ---: |']
    for r in rows.values():lines.append(f'| {r["key"]} | {r["case"]} | {r["route"]} | {1000*r["median_seconds"]:.2f} | '
        f'{1000*r["minimum_seconds"]:.2f}–{1000*r["maximum_seconds"]:.2f} |')
    (experiment.output/'summary.md').write_text('\n'.join(lines)+'\n')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir',type=Path,required=True)
    parser.add_argument('--screen',action='store_true',help='Run the CPU screening sweep.')
    parser.add_argument('--timing',action='store_true',help='Interleave fresh CPU timing trials for supplied policies.')
    parser.add_argument('--repeats',type=int,default=5)
    parser.add_argument('--policy',action='append',type=parse_policy,help='rounds,stopping,raw,tone; repeat to validate finalists.')
    parser.add_argument('--case',action='append',choices=list(cases()))
    parser.add_argument('--cpu-only',action='store_true')
    args=parser.parse_args()
    if args.screen and (args.policy or args.timing):parser.error('--screen cannot be combined with --policy or --timing')
    if args.repeats<1:parser.error('--repeats must be positive')
    experiment=Experiment(args.output_dir)
    if args.screen:screen(experiment)
    elif args.timing:timings(experiment,args.policy or [Policy()],args.case or ['tone','mixed','mixed_tone'],args.repeats)
    else:
        if not args.cpu_only:
            import bpy,gpu
            bpy.context.preferences.system.gpu_backend='OPENGL';gpu.init()
            experiment.renderer=gpu.platform.renderer_get()
            if 'llvmpipe' not in experiment.renderer.lower():raise RuntimeError('Expected software GPU llvmpipe')
        for p in args.policy or [Policy()]:
            experiment.evaluate(p,args.case or list(cases()),('CPU',) if args.cpu_only else ('CPU','GPU'),save=True)
