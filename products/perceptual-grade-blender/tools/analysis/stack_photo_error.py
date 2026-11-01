"""Photographic recovery through a forced forward/inverse Stack and its 65³ LUT."""
import argparse
from dataclasses import asdict
from datetime import datetime
import hashlib
from importlib.resources import files
import json
from pathlib import Path
import sys
import time
import numpy as np
from color_tools.perceptual_grade_core.model import bake_inverse
from tools.analysis.photo_io import load_fixtures,ocio_processors,apply_processor,save_display
from tools.analysis.photo_stack import ForcedStack,cases,lattice,prepare,eval_core,endpoint,tetrahedral,vertex_diagnostic


CODE_MAX={'SDR100':255,'HDR1000':1023}
COMPARISONS={'repair':('ideal','source'),'preparation':('prepared','ideal'),
    'core_recovery':('direct','prepared'),'direct_recovery':('direct','ideal'),'interpolation':('lut','direct'),
    'total_recovery':('lut','ideal')}


def metrics(actual,expected,code_max):
    """Unclipped encoded errors; percentiles use maximum absolute RGB per pixel."""
    a=np.asarray(actual,dtype=float).reshape(-1,3)
    e=np.asarray(expected,dtype=float).reshape(-1,3)
    if a.shape!=e.shape or not len(a) or not np.isfinite(a).all() or not np.isfinite(e).all():
        raise ValueError('Expected equally shaped, finite, nonempty RGB arrays')
    delta=abs(a-e);pixel=np.max(delta,axis=1);worst=int(np.argmax(pixel))
    encoded=dict(mean_absolute_channel=float(delta.mean()),rmse_channel=float(np.sqrt(np.mean(delta**2))),
        **dict(zip(('p95','p99','p99_9'),np.percentile(pixel,[95,99,99.9]).tolist())),
        maximum=float(pixel[worst]))
    counts={str(v):int(np.count_nonzero(pixel*code_max>v)) for v in (.5,1.,2.,4.)}
    return dict(pixels=len(a),encoded=encoded,codes={k:v*code_max for k,v in encoded.items()},
        pixels_above_codes=counts,fraction_above_codes={k:v/len(a) for k,v in counts.items()},
        exact_pixels=int(np.count_nonzero(pixel==0)),
        worst=dict(flat_index=worst,expected=e[worst].tolist(),actual=a[worst].tolist(),
                   absolute_channel_error=delta[worst].tolist()))


def heatmap(actual,expected,code_max):
    error=np.max(abs(np.asarray(actual,dtype=float)-expected),axis=-1)*code_max
    value=np.clip(np.log1p(error)/np.log(17),0,1)
    return np.stack((value,value*value,np.zeros_like(value)),axis=-1)


def forward_diagnostic(stack,u,direct,lut):
    """Independent float64 forward reproduction of the worst recovered sources."""
    model=stack.models[0]
    states=model.grade_state(model.enter_native(np.stack((u,direct,lut)).astype(float)))
    features=np.column_stack((states.q[:,0],states.ja,states.q[:,1:])).astype(float)
    error=np.max(abs(features[1:]-features[0])/(1+abs(features[0])),axis=1)
    return dict(space='float64 [J_HK,J_A,a,b], normalized by 1+abs(target)',
        target=features[0].tolist(),direct=features[1].tolist(),lut=features[2].tolist(),
        direct_residual=float(error[0]),lut_residual=float(error[1]),
        direct_within_raw_acceptance=bool(error[0]<=float(bake_inverse.TOLERANCE)),
        lut_within_raw_acceptance=bool(error[1]<=float(bake_inverse.TOLERANCE)))


def crop_triptych(images,row,column,radius=8):
    h,w=images[0].shape[:2]
    bounds=(max(0,row-radius),min(h,row+radius+1),max(0,column-radius),min(w,column+radius+1))
    y0,y1,x0,x1=bounds
    crop=np.concatenate([v[y0:y1,x0:x1] for v in images],axis=1)
    return np.repeat(np.repeat(crop,8,axis=0),8,axis=1),bounds


def located_metric(actual,expected,code_max,fixture):
    result=metrics(actual,expected,code_max);index=result['worst']['flat_index']
    y,x=np.unravel_index(index,actual.shape[:2])
    result['worst'].update(sample_xy=[int(x),int(y)],original_xy=[int(x)*12,int(y)*12],
        source_linear_rec2020=fixture['rgb'][y,x].tolist())
    return result


def audit_vertices(output,report):
    """Explain worst photographed LUT errors from saved cubes, without rebaking."""
    cubes={};audits=[]
    for aggregate in report['aggregates']:
        rows=[r for r in report['results'] if all(r[k]==aggregate[k] for k in ('case','backend','view'))]
        row=max(rows,key=lambda r:r['comparisons']['total_recovery']['encoded']['maximum'])
        worst=row['comparisons']['total_recovery']['worst'];key=(row['case'],row['backend'])
        if key not in cubes:cubes[key]=np.load(output/f'{key[0]}-{key[1].lower()}-65.npy',allow_pickle=False)
        audits.append(dict(case=row['case'],backend=row['backend'],view=row['view'],fixture=row['fixture'],
            sample_xy=worst['sample_xy'],total_error_codes=row['comparisons']['total_recovery']['codes']['maximum'],
            **vertex_diagnostic(cubes[key],np.array(worst['prepared_lut_input']))))
    report['vertex_audits']=audits


def write_summary(output,report):
    lines=['# Photographic forward–inverse stack error','',
        'Forced matching pairs; one combined 65³ LUT. Ideal is M⁻¹ P(Mx). '
        'Encoded errors are measured before PNG quantization, without additional clipping.','',
        'Direct recovery includes preparation roundoff; core recovery separately compares against the '
        'prepared baseline. Absolute errors and percentiles are not an additive error budget. '
        'OCIO processes all arms in float32; the independent worst-pixel forward audit uses float64.','',
        'SDR code units are 1/255; HDR code units are 1/1023. Percentiles use maximum-channel '
        'absolute pixel error. Aggregates include every sample in all four photographs.','',
        '| Case | Backend | View | Direct p99 / max | LUT total p99 / max | Interpolation max | LUT >1 code |',
        '| --- | --- | --- | ---: | ---: | ---: | ---: |']
    for row in report['aggregates']:
        d=row['comparisons']['direct_recovery']['codes'];t=row['comparisons']['total_recovery']
        i=row['comparisons']['interpolation']['codes']
        lines.append(f'| {row["case"]} | {row["backend"]} | {row["view"]} | '
            f'{d["p99"]:.6g} / {d["maximum"]:.6g} | '
            f'{t["codes"]["p99"]:.6g} / {t["codes"]["maximum"]:.6g} | {i["maximum"]:.6g} | '
            f'{100*t["fraction_above_codes"]["1.0"]:.6g}% |')
    lines+=['','## Input repair and preparation','',
        'These are separate comparisons against the unrepaired source and the float64 repair-aware '
        'ideal. Recovery results above already allow the mandatory repair. Maxima below cover all cases/backends.','',
        '| View | Input repair maximum (codes) | Preparation roundoff maximum (codes) |',
        '| --- | ---: | ---: |']
    for view in CODE_MAX:
        rows=[r for r in report['aggregates'] if r['view']==view]
        if rows:
            lines.append(f'| {view} | {max(r["comparisons"]["repair"]["codes"]["maximum"] for r in rows):.6g} | '
                f'{max(r["comparisons"]["preparation"]["codes"]["maximum"] for r in rows):.6g} |')
    lines+=['','## Worst photographed pixels','',
        '| Case | Backend | View | Image (sample x,y) | Expected encoded RGB | Actual LUT RGB | Error codes |',
        '| --- | --- | --- | --- | --- | --- | ---: |']
    for row in report['aggregates']:
        candidates=[r for r in report['results'] if all(r[k]==row[k] for k in ('case','backend','view'))]
        worst=max(candidates,key=lambda r:r['comparisons']['total_recovery']['encoded']['maximum'])
        value=worst['comparisons']['total_recovery'];w=value['worst']
        rgb=lambda v:', '.join(f'{c:.7g}' for c in v)
        lines.append(f'| {row["case"]} | {row["backend"]} | {row["view"]} | '
            f'{worst["fixture"]} {tuple(w["sample_xy"])} | {rgb(w["expected"])} | '
            f'{rgb(w["actual"])} | {value["codes"]["maximum"]:.6g} |')
    if report['parity']:
        lines+=['','## CPU versus GPU','',
            '| View | Maximum direct disagreement (codes) | Maximum LUT disagreement (codes) |',
            '| --- | ---: | ---: |']
        for view in CODE_MAX:
            rows=[r for r in report['parity'] if r['view']==view]
            lines.append(f'| {view} | {max(r["direct"]["codes"]["maximum"] for r in rows):.6g} | '
                f'{max(r["lut"]["codes"]["maximum"] for r in rows):.6g} |')
    if report.get('vertex_audits'):
        lines+=['','## Saved-vertex audit','',
            'For each worst photographed pixel, the JSON records all four cube vertices, convex '
            'weights, RGB errors and raw inverse residuals. The following witnesses contain '
            'vertices exceeding the 1e-4 raw acceptance threshold. These are already inaccurate '
            'baked values; tetrahedral interpolation propagates their errors.','',
            '| Case | Backend | View | Failed corners | Neutral weight | Weighted core RGB error |',
            '| --- | --- | --- | ---: | ---: | --- |']
        for row in report['vertex_audits']:
            if not row['failed_vertices']:continue
            error=', '.join(f'{v:.7g}' for v in row['weighted_error'])
            lines.append(f'| {row["case"]} | {row["backend"]} | {row["view"]} | '
                f'{row["failed_vertices"]} | {100*row["neutral_weight"]:.5f}% | {error} |')
    lines+=['','## Interpretation and artifacts','',
        'Each image directory contains floating encoded arrays, ideal/direct/LUT PNGs, three error '
        'heatmaps, and a worst-total-error crop (ideal | direct | LUT, enlarged 8×). '
        'Heatmaps use log1p(error in codes)/log(17), saturating at 16 codes. '
        'HDR PNGs contain 16-bit PQ data with Rec.2020/PQ cICP metadata; the nominal error unit '
        'remains 10-bit. Native arrays and LUT vertices are saved separately.','',
        'The JSON retains per-image metrics, repair/preparation errors, exact grade settings, '
        'configuration/resource hashes, raw inverse acceptance and independent float64 forward '
        'reproduction at each worst total-error pixel. A small reproduction residual does not '
        'guarantee recovery of the original source. Small photographic encoded errors also do not '
        'establish inverse convergence over the full cube; raw acceptance exceptions remain in '
        'the saved lattice and some direct photographic evaluations.','',
        'Candidate reporting bands are 0.5, 1, 2 and 4 nominal codes. None is an adopted acceptance '
        'threshold. Choose regression limits after reviewing distributions and worst crops; '
        'do not make an existing large error acceptable merely by fitting a threshold to it.','',
        *('- '+v for v in report['limitations']),'']
    (output/'summary.md').write_text('\n'.join(lines))


def run(output,selected,cpu_only=False):
    output.mkdir(parents=True,exist_ok=True);started=time.perf_counter()
    fixtures=load_fixtures();ocio=ocio_processors()
    resource=files('color_tools.perceptual_grade_reference')/'d65_boundary.npz'
    report=dict(timestamp=datetime.now().astimezone().isoformat(),size=65,
        source_fixtures=[dict(name=f['name'],metadata=f['metadata']) for f in fixtures],
        ocio=ocio['metadata'],d65_sha256=hashlib.sha256(resource.read_bytes()).hexdigest(),
        python=sys.version.split()[0],numpy=np.__version__,settings={},bakes={},results=[],aggregates=[],parity=[],
        inverse_policy=dict(raw_normalized=float(bake_inverse.TOLERANCE),
            inner_stopping=float(bake_inverse.SEARCH_TOLERANCE),chroma_coordinate='brightness-scaled C2 toe',
            rgb_relative=float(bake_inverse.RGB_RELATIVE_TOLERANCE),
            rgb_absolute=float(bake_inverse.RGB_ABSOLUTE_TOLERANCE),rounds=int(bake_inverse.ITERATIONS)),
        limitations=[
            'Photographs are every-12th-row/column samples, not full-resolution originals; no added exposure scaling.',
            'One matching forward/inverse pair, same D65 and settings, with cancellation disabled only in this experiment.',
            'The known repair-aware original is the recovery target, not a uniqueness claim about inverse roots.',
            'Raw appearance handoff uses 1e-4 normalized acceptance; RGB acceptance settings do not govern this path.',
            'Reference CPU/GLSL computation plus numerical tetrahedral interpolation only; no Blender compositor, RGBE or half-float transport.',
            'No final repair after inverse Stage 1. OCIO performs the chosen display transform identically on every comparison arm.',
            'Native images and metrics are unclipped; only PNG serialization clips/quantizes and records those changes.',
            'Timing fields describe this single accuracy run, including first uses, and are not UI or benchmark claims.'])
    if not cpu_only:
        import bpy,gpu
        bpy.context.preferences.system.gpu_backend='METAL' if sys.platform=='darwin' else 'OPENGL'
        gpu.init();report['renderer']=gpu.platform.renderer_get()
        if sys.platform!='darwin' and 'llvmpipe' not in report['renderer'].lower():
            raise RuntimeError('This experiment requires the software GPU (llvmpipe)')
    for fixture in fixtures:fixture['native']=apply_processor(ocio['convert'],fixture['rgb'])
    grid=lattice();table=None;program=None
    for name in selected:
        setting=cases()[name];start=time.perf_counter()
        stack=ForcedStack([setting,setting],['FORWARD','INVERSE'],table)
        table=stack.table;report['settings'][name]=asdict(setting)
        item=dict(setup_seconds=time.perf_counter()-start);report['bakes'][name]=item
        if not cpu_only:
            if program is None:program=stack.prepare_gpu();report['shader_creation_seconds']=program.compile_seconds
            else:stack.program=program
        prepared={f['name']:prepare(stack,f['native']) for f in fixtures}
        cpu_images={};pools={}
        for backend in (('CPU',) if cpu_only else ('CPU','GPU')):
            start=time.perf_counter();cube=eval_core(stack,grid,backend)
            item[backend]=dict(bake_seconds=time.perf_counter()-start,
                approximate_vertices=int(np.count_nonzero(cube[:,3]>bake_inverse.TOLERANCE)),
                maximum_raw_residual=float(cube[:,3].max()),minimum_rgb=float(cube[:,:3].min()),
                maximum_rgb=float(cube[:,:3].max()))
            np.save(output/f'{name}-{backend.lower()}-65.npy',cube)
            print(f'{name} {backend}: baked 65³, {item[backend]["approximate_vertices"]} vertices outside raw acceptance',flush=True)
            for fixture in fixtures:
                fkey=fixture['name'];prep=prepared[fkey];u=prep['input']
                start=time.perf_counter();direct=eval_core(stack,u,backend)
                duration=time.perf_counter()-start
                lut_core=tetrahedral(cube[:,:3],u)
                native=dict(source=fixture['native'],ideal=prep['ideal'],prepared=prep['prepared'],
                    direct=endpoint(stack,direct[...,:3]),lut=endpoint(stack,lut_core))
                folder=output/name/backend.lower()/fkey;folder.mkdir(parents=True,exist_ok=True)
                np.savez_compressed(folder/'native.npz',**native,input=u,direct_raw_residual=direct[...,3])
                for view,processor in ocio['displays'].items():
                    encoded={key:apply_processor(processor,value) for key,value in native.items()}
                    viewdir=folder/view;viewdir.mkdir(exist_ok=True)
                    np.savez_compressed(viewdir/'encoded.npz',**encoded)
                    png={key:save_display(viewdir/f'{key}.png',encoded[key],view) for key in ('ideal','direct','lut')}
                    row=dict(case=name,backend=backend,fixture=fkey,view=view,
                        direct_seconds=duration,repair_changed_pixels=int(prep['repair_changed'].sum()),
                        raw_inverse=dict(approximate_pixels=int(np.count_nonzero(direct[...,3]>bake_inverse.TOLERANCE)),
                            maximum_residual=float(direct[...,3].max())),png=png,comparisons={})
                    for label,(actual,expected) in COMPARISONS.items():
                        measure=located_metric(encoded[actual],encoded[expected],CODE_MAX[view],fixture)
                        row['comparisons'][label]=measure
                        pools.setdefault((backend,view,label),[]).append((encoded[actual],encoded[expected]))
                        if label in ('direct_recovery','interpolation','total_recovery'):
                            save_display(viewdir/f'{label}-error.png',heatmap(encoded[actual],encoded[expected],CODE_MAX[view]),'SDR100')
                    worst=row['comparisons']['total_recovery']['worst'];x,y=worst['sample_xy']
                    worst.update(source_acescg=fixture['native'][y,x].tolist(),prepared_lut_input=u[y,x].tolist(),
                        ideal_acescg=prep['ideal'][y,x].tolist(),direct_acescg=native['direct'][y,x].tolist(),
                        lut_acescg=native['lut'][y,x].tolist(),direct_encoded=encoded['direct'][y,x].tolist(),
                        actual_backend_raw_residual=float(direct[y,x,3]),
                        forward_reproduction=forward_diagnostic(stack,u[y,x],direct[y,x,:3],lut_core[y,x]))
                    crop,bounds=crop_triptych([encoded[k] for k in ('ideal','direct','lut')],y,x)
                    save_display(viewdir/'worst-crop.png',crop,view);worst['crop_y0_y1_x0_x1']=list(bounds)
                    report['results'].append(row)
                    if backend=='CPU':cpu_images[fkey,view]={k:encoded[k] for k in ('direct','lut')}
                    else:
                        report['parity'].append(dict(case=name,fixture=fkey,view=view,
                            **{key:located_metric(encoded[key],cpu_images[fkey,view][key],CODE_MAX[view],fixture)
                               for key in ('direct','lut')}))
            for view in CODE_MAX:
                aggregate=dict(case=name,backend=backend,view=view,comparisons={})
                for label in COMPARISONS:
                    pairs=pools[backend,view,label]
                    aggregate['comparisons'][label]=metrics(np.concatenate([p[0].reshape(-1,3) for p in pairs]),
                        np.concatenate([p[1].reshape(-1,3) for p in pairs]),CODE_MAX[view])
                report['aggregates'].append(aggregate)
                total=aggregate['comparisons']['total_recovery']['codes']
                print(f'  {view}: total p99={total["p99"]:.6g}, maximum={total["maximum"]:.6g} codes',flush=True)
            (output/'report.json').write_text(json.dumps(report,indent=2,allow_nan=False)+'\n')
        write_summary(output,report)
    report['elapsed_seconds']=time.perf_counter()-started
    report['d65_unchanged']=report['d65_sha256']==hashlib.sha256(resource.read_bytes()).hexdigest()
    if not report['d65_unchanged']:raise ArithmeticError('D65 resource changed')
    audit_vertices(output,report)
    (output/'report.json').write_text(json.dumps(report,indent=2,allow_nan=False)+'\n')
    write_summary(output,report)
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir',type=Path,required=True)
    parser.add_argument('--case',action='append',choices=list(cases()))
    parser.add_argument('--cpu-only',action='store_true')
    parser.add_argument('--report-only',action='store_true',help='Audit saved LUT vertices and rewrite the report without baking or rendering.')
    args=parser.parse_args()
    if args.report_only:
        report=json.loads((args.output_dir/'report.json').read_text())
        audit_vertices(args.output_dir,report)
        (args.output_dir/'report.json').write_text(json.dumps(report,indent=2,allow_nan=False)+'\n')
        write_summary(args.output_dir,report)
    else:run(args.output_dir,args.case or list(cases()),args.cpu_only)
