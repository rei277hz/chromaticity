from color_tools.perceptual_grade_blender.model.bake_inverse_gpu import Program as ReferenceGPUProgram
"""Compare inverse tolerances and iteration caps across explicit repaired RGB chains."""
import argparse
from dataclasses import replace
import json
from pathlib import Path
import sys
from unittest.mock import patch
import numpy as np
from color_tools.perceptual_grade_core.model import bake_inverse
from color_tools.perceptual_grade_reference.grading import ToneSettings
from color_tools.perceptual_grade_reference.grading import ColorSettings
from color_tools.perceptual_grade_core.model.tonal_web import WebSettings
from color_tools.perceptual_grade_reference.model import Settings
from tests.reference.legacy_capacity import LegacyCapacityBakeStack


POLICIES=(('baseline40',1,40),('strict40',10,40),('strict80',10,80),('strict160',10,160),
          ('strict100_40',100,40),('strict100_80',100,80))
DEPTHS=(1,2,4)


def cases():
    tone=Settings(tone=ToneSettings(input_nits=(0.,7.,45.,203.,1000.)))
    mixed=replace(tone,color=ColorSettings(global_gain=.15,web=WebSettings(
            hue_degrees=((0.,)*6,(3.,2.,1.,-1.,-2.,0.),(0.,)*6,(0.,)*6),
            log_chroma=((0.,)*6,(.03,0.,-.02,0.,.01,0.),(0.,)*6,(0.,)*6),
            log_scale=((0.,)*6,(0.,)*6,(.02,0.,0.,-.01,0.,0.),(0.,)*6)),
        adaptance=((0.,0.),(0.,0.),(0.,.01),(0.,0.)),
        lightness=((0.,0.,0.,0.),(0.,.1,0.,0.),(0.,0.,0.,0.),(0.,0.,0.,0.))))
    return {'tone':tone,'mixed_tone':mixed}


def metrics(actual,expected,solver,masks,source):
    canonical=solver.canonical.astype(float)
    delta=solver.kernel.native(actual.astype(float)-expected,canonical)
    peak=np.max(abs(solver.kernel.native(expected.astype(float),canonical)),axis=1)
    error=np.max(abs(delta),axis=1);normalized=error/np.maximum(peak,1e-4)
    baseline=np.maximum(.001*peak,.0003)
    current=np.maximum(float(bake_inverse.RGB_RELATIVE_TOLERANCE)*peak,
                       float(bake_inverse.RGB_ABSOLUTE_TOLERANCE))
    result={}
    for region,mask in masks.items():
        ids=np.flatnonzero(mask)
        if not len(ids):result[region]={'samples':0};continue
        worst=ids[np.argmax(normalized[ids])]
        result[region]=dict(samples=len(ids),maximum_normalized=float(normalized[worst]),
            normalized_percentiles=dict(zip(('50','90','99'),np.percentile(normalized[ids],[50,90,99]).tolist())),
            maximum_absolute=float(error[ids].max()),baseline_failures=int(np.count_nonzero(error[ids]>baseline[ids])),
            policy_failures=int(np.count_nonzero(error[ids]>current[ids])),
            worst_source=source[worst].tolist(),expected=expected[worst].tolist(),actual=actual[worst].tolist())
    return result


def run(output,size,cpu_only,selected=None):
    selected=set(selected if selected is not None else (name for name,_,iterations in POLICIES if iterations<=80))
    policies=tuple(p for p in POLICIES if p[0] in selected)
    check_pairs={'baseline40','strict40'}<=selected
    output.mkdir(parents=True,exist_ok=True)
    axis=.01*np.expm1(np.linspace(0,1,size)*np.log1p(1024/.01));axis[0],axis[-1]=0.,1024.
    source=np.stack(np.meshgrid(axis,axis,axis,indexing='ij'),-1).reshape(-1,3).astype('f4')
    base=LegacyCapacityBakeStack([Settings()],['INVERSE'], program_factory=ReferenceGPUProgram);table=base.table
    peak=np.max(abs(base.kernels[0].native(source,base.solvers[0].canonical)),axis=1)
    masks=dict(all=np.ones(len(source),dtype=bool),dark=peak<.3,
               interior=np.all(source>0,axis=1)&(np.max(source,axis=1)<=128))
    report=dict(size=size,samples=len(source),depths=DEPTHS,regions={k:int(v.sum()) for k,v in masks.items()},
        policies=[dict(name=n,rgb_relative=.001/s,rgb_absolute=.0003/s,stage3_iterations=i) for n,s,i in policies],
        raw_threshold=float(bake_inverse.TOLERANCE),stage3_stopping=float(bake_inverse.SEARCH_TOLERANCE),
        limitations=[
            'Targets come from F^n(source), with explicit native AP1 RGB export and receiver repair after every F. Matching-pair cancellation is never used.',
            'Reachable means reachable through this repaired numerical chain; receiver repair can change the un-repaired forward output.',
            'Source reconstruction can differ because guarded grading is not injective. Forward reproduction is reported separately.',
            'Dark means source canonical linear Rec.709 peak below 0.3; interior means all source AP1 channels positive and peak at most 128.',
            'Errors use float64 canonical linear Rec.709 channel comparisons and normalization by max(target peak,1e-4). These are not perceptual errors.',
            'Per-stage acceptance uses each solver result and the current policy. Raw acceptance and Stage 3 stopping remain fixed.',
            'GPU executes actual GLSL. The shared CPU receiver-repair adapter matches current Stack handoffs; there is no device-failure fallback.',
            'CPU/GPU agreement compares complete chains, including their independently generated forward targets; it is not a same-target inverse parity test.',
            'Forward targets are reused between policies to isolate inverse changes. This study is not a fresh-bake timing benchmark or a global accuracy certificate.'],
        results=[],raw_handoff_invariants=[])
    if not cpu_only:
        import bpy,gpu
        bpy.context.preferences.system.gpu_backend='METAL' if sys.platform=='darwin' else 'OPENGL';gpu.init()
        report.update(blender=bpy.app.version_string,renderer=gpu.platform.renderer_get())
    targets={};cpu_results={};raw_baselines={}
    for policy,scale,iterations in policies:
        with patch.multiple(bake_inverse,RGB_RELATIVE_TOLERANCE=np.float32(.001/scale),
                            RGB_ABSOLUTE_TOLERANCE=np.float32(.0003/scale),ITERATIONS=iterations):
            program=None  # Compile each policy's constants into its GLSL program.
            for name,settings in cases().items():
                stack=LegacyCapacityBakeStack([settings],['INVERSE'],table, program_factory=ReferenceGPUProgram);solver=stack.solvers[0];k=solver.kernel
                for backend in (('CPU',) if cpu_only else ('CPU','GPU')):
                    if backend=='GPU':
                        if program is None:program=stack.prepare_gpu()
                        else:program.set_inverse(solver)
                    def forward(value):
                        raw=k.evaluate(value) if backend=='CPU' else program.evaluate(value,2)[:,:3]
                        repaired=solver.repair(raw);changed=np.any(repaired!=raw,axis=1)
                        repair={region:int(np.count_nonzero(changed&mask)) for region,mask in masks.items()}
                        repair['maximum_absolute_change']=float(np.max(abs(repaired-raw),initial=0))
                        return repaired,repair
                    key=(name,backend)
                    if key not in targets:
                        value=source.copy();history=[];targets[key]={}
                        for depth in range(1,max(DEPTHS)+1):
                            value,repair=forward(value);history.append(repair)
                            if depth in DEPTHS:targets[key][depth]=(value.copy(),history.copy())
                    for depth in DEPTHS:
                        target,repairs=targets[key][depth];value=target.copy();stages=[]
                        for step in range(depth):
                            evaluated=solver.evaluate(value) if backend=='CPU' else program.evaluate(value,0)
                            limits=solver.acceptance_limit(value)
                            stages.append({region:dict(samples=int(mask.sum()),
                                approximate=int(np.count_nonzero((evaluated[:,3]>limits)&mask)),
                                maximum_residual=float(evaluated[mask,3].max(initial=0))) for region,mask in masks.items()})
                            value=evaluated[:,:3]
                        reconstructed=value;reproduced=value;reproduction_repairs=[]
                        for _ in range(depth):
                            reproduced,repair=forward(reproduced);reproduction_repairs.append(repair)
                        item=dict(policy=policy,case=name,backend=backend,depth=depth,
                            source_reconstruction=metrics(reconstructed,source,solver,masks,source),
                            forward_reproduction=metrics(reproduced,target,solver,masks,source),
                            inverse_stages=stages,target_receiver_repairs=repairs,
                            reproduction_receiver_repairs=reproduction_repairs,
                            minimum_rgb=float(reconstructed.min()),maximum_rgb=float(reconstructed.max()))
                        parity_key=(policy,name,depth)
                        if backend=='CPU':cpu_results[parity_key]=reconstructed.copy()
                        else:
                            expected=cpu_results[parity_key].astype(float)
                            difference=np.max(abs(reconstructed-expected),axis=1)
                            limit=np.maximum(.001*np.max(abs(expected),axis=1),1e-7)
                            worst=int(np.argmax(difference/limit))
                            item['gpu_vs_cpu_chain']=dict(outside_tolerance=int(np.count_nonzero(difference>limit)),
                                maximum_tolerance_fraction=float((difference/limit)[worst]),
                                worst_source=source[worst].tolist(),expected=expected[worst].tolist(),actual=reconstructed[worst].tolist())
                        report['results'].append(item)
                        (output/'report.json').write_text(json.dumps(report,indent=2)+'\n')
                        errors=item['forward_reproduction']['all']
                        print(f'{policy} {name} {backend} n={depth}: reproduction max {errors["maximum_normalized"]:.6g}, baseline failures {errors["baseline_failures"]}/{len(source)}',flush=True)
            if check_pairs and policy in ('baseline40','strict40'):
                witness=np.array([[0,0,0],[.1,.2,.3],[.7,.2,.1],[1,2,3],
                    [168.81788635253906,117.71593475341797,9.427742004394531]],dtype='f4')
                gains=[Settings(color=ColorSettings(global_gain=v)) for v in (.1,.2)]
                raw_pair=LegacyCapacityBakeStack(gains,['FORWARD','INVERSE'],table, program_factory=ReferenceGPUProgram)
                setting=cases()['mixed_tone']
                matching=LegacyCapacityBakeStack([setting,setting],['FORWARD','INVERSE'],table, program_factory=ReferenceGPUProgram)
                for backend in (('CPU',) if cpu_only else ('CPU','GPU')):
                    if backend=='GPU':raw_pair.program=program;matching.program=program
                    actual=raw_pair.bake_native(witness,backend);cancelled=matching.bake_native(witness,backend)
                    if policy=='baseline40':raw_baselines[backend]=actual.copy()
                    check=dict(policy=policy,backend=backend,
                        raw_pair_equal_to_baseline=bool(np.array_equal(actual,raw_baselines[backend])),
                        matching_pair_exact=bool(np.array_equal(cancelled[:,:3],witness) and np.all(cancelled[:,3]==0)),
                        raw_pair_result=actual.tolist())
                    report['raw_handoff_invariants'].append(check)
                    if not check['raw_pair_equal_to_baseline'] or not check['matching_pair_exact']:
                        raise ArithmeticError('RGB acceptance policy changed a raw or matching-pair invariant')
                (output/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    lines=['# Inverse tolerance and repaired RGB chains','',
        f'{size}³ sources; {len(source):,} samples. Source-region counts: '+json.dumps(report['regions'])+'.','',
        'Policies: '+'; '.join(f'{name}: max({.001/scale:g} × target peak, {.0003/scale:g}), {iterations} Stage 3 iterations'
                              for name,scale,iterations in policies)+f'. Raw acceptance stays 1e-4 and Stage 3 stopping is {float(bake_inverse.SEARCH_TOLERANCE):.9g}.','',
        '| Policy | Case | Backend | Depth | Region | Source max normalized | Reproduction max normalized | Reproduction fails baseline / policy |',
        '| --- | --- | --- | ---: | --- | ---: | ---: | ---: |']
    for item in report['results']:
        for region,a in item['source_reconstruction'].items():
            b=item['forward_reproduction'][region]
            if not a['samples']:continue
            lines.append(f'| {item["policy"]} | {item["case"]} | {item["backend"]} | {item["depth"]} | {region} | '+
                         f'{a["maximum_normalized"]:.6g} | {b["maximum_normalized"]:.6g} | {b["baseline_failures"]} / {b["policy_failures"]} |')
    invariant_summary=('Raw handoff and matching-pair checks (five witnesses): '+json.dumps([
        {k:v for k,v in row.items() if k!='raw_pair_result'} for row in report['raw_handoff_invariants']])+'.'
        if report['raw_handoff_invariants'] else 'Raw handoff and matching-pair checks were not run; they require baseline40 and strict40 together.')
    lines+=['',invariant_summary,'',
        *(f'- {v}' for v in report['limitations']),'']
    (output/'summary.md').write_text('\n'.join(lines));return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir',type=Path,required=True)
    parser.add_argument('--size',type=int,default=17)
    parser.add_argument('--cpu-only',action='store_true')
    parser.add_argument('--policy',action='append',choices=[name for name,_,_ in POLICIES],
                        help='Repeat to select policies; defaults to all policies with at most 80 iterations.')
    args=parser.parse_args()
    if args.size<2:parser.error('size >= 2 required')
    run(args.output_dir,args.size,args.cpu_only,args.policy)
