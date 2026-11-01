"""Regular Grade 65-cube photographic error against the cached float64 model."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from datetime import datetime
import hashlib
from importlib.resources import files
import json
from pathlib import Path
import sys
import time
import numpy as np
from color_tools.perceptual_grade_blender.model import baking, gpu as compute
from color_tools.perceptual_grade_reference.cube_guard import guard as cube_guard
from tests.reference.legacy_capacity import LegacyCapacityModel
from tools.analysis.photo_grade import extension_model, prepare
from tools.analysis.photo_io import load_fixtures, ocio_processors, apply_processor, save_display
from tools.analysis.photo_stack import cases, tetrahedral, _addresses, axis
from tools.analysis.stack_photo_error import metrics, heatmap, crop_triptych, CODE_MAX


BANDS=(.1,.4,.5,1.,2.)
COMPARISONS={'total':('lut','ideal'),'implementation':('direct','ideal'),
             'interpolation':('lut','direct')}


def resource_hashes():
    paths=(files('color_tools.perceptual_grade_core.model')/'d65_boundary.npz',
           files('color_tools.perceptual_grade_reference')/'d65_cube.npz')
    return [hashlib.sha256(path.read_bytes()).hexdigest() for path in paths]


def measure(actual,expected,code_max):
    result=metrics(actual,expected,code_max)
    pixel=np.max(abs(np.asarray(actual,dtype=float)-expected),axis=-1).ravel()*code_max
    result['pixels_above_codes']={str(v):int(np.count_nonzero(pixel>v)) for v in BANDS}
    result['fraction_above_codes']={key:value/len(pixel) for key,value in result['pixels_above_codes'].items()}
    return result


def located(actual,expected,code_max,fixture):
    result=measure(actual,expected,code_max)
    y,x=np.unravel_index(result['worst']['flat_index'],actual.shape[:2])
    result['worst'].update(sample_xy=[int(x),int(y)],original_xy=[int(x)*12,int(y)*12])
    return result


def direct(baker,values):
    rows=np.asarray(values,dtype='f4').reshape(-1,3)
    if baker.backend=='GPU':
        if baker.kernel.identity:return rows.copy().reshape(values.shape)
        baker.program.parameters=baker.parameters
        # Match the production baker's two dispatches, including RGBA32F storage.
        result=baker.program.evaluate(baker.program.evaluate(rows,0),1)[:,:3]
    else:
        with ThreadPoolExecutor(max_workers=4,thread_name_prefix='PG photo forward') as pool:
            result=np.concatenate(list(pool.map(baker.kernel.evaluate,
                [rows[i:i+baker.block] for i in range(0,len(rows),baker.block)])))
    return result.reshape(values.shape)


def audit_vertices(output,report):
    """Check worst-pixel interpolation from saved cubes, without rebaking."""
    if resource_hashes()!=[report['d65_sha256']]*2:raise ValueError('Saved report and current D65 resources differ')
    audits=[];ranges=[]
    for name in report['settings']:
        if json.dumps(report['settings'][name],sort_keys=True)!=json.dumps(asdict(cases()[name]),sort_keys=True):
            raise ValueError('Saved report and current grade settings differ: '+name)
        setting=cases()[name];oracle=LegacyCapacityModel(setting,hk_guard=True);kernel=baking.kernel(extension_model(setting))
        for backend in ('CPU','GPU'):
            path=output/f'{name}-{backend.lower()}-65.npy'
            if not path.exists():continue
            cube=np.load(path,allow_pickle=False)
            extrema=np.array([np.argmin(cube),np.argmax(cube)])
            ids=np.array(np.unravel_index(extrema//3,(65,65,65))).T
            points=axis()[ids].astype('f4')
            ranges.append(dict(case=name,backend=backend,minimum_then_maximum=True,
                coordinates=points.tolist(),channels=(extrema%3).tolist(),
                stored_rgb=cube[ids[:,0],ids[:,1],ids[:,2]].tolist(),
                fresh_cpu_rgb=kernel.evaluate(points).tolist(),
                cached_float64_rgb=oracle.forward_native(points,apply_linear=False).tolist()))
            for view in CODE_MAX:
                rows=[r for r in report['results'] if (r['case'],r['backend'],r['view'])==(name,backend,view)]
                if not rows:continue
                row=max(rows,key=lambda r:r['comparisons']['total']['codes']['maximum'])
                worst=row['comparisons']['total']['worst'];point=np.array(worst['prepared_lut_input'])
                _,corners,fractions=_addresses(point.reshape(1,3),65)
                ids=np.stack(corners,axis=1)[0];coordinates=axis()[ids].astype('f4')
                selected=cube[ids[:,0],ids[:,1],ids[:,2]].astype(float)
                f=fractions[0];weights=np.array([1-f[0],f[0]-f[1],f[1]-f[2],f[2]])
                expected=oracle.forward_native(coordinates,apply_linear=False)
                fresh=kernel.evaluate(coordinates)
                state=oracle.grade_state(oracle.enter_native(np.vstack((point,coordinates))))
                guarded,energy,_=cube_guard(oracle.boundary,state.q,state.energy)
                projected=np.zeros(5,dtype=bool) if kernel.identity else np.any(guarded!=state.q,axis=-1)|(energy!=state.energy)
                audits.append(dict(case=name,backend=backend,view=view,fixture=row['fixture'],
                    original_xy=worst['original_xy'],input=point.tolist(),indices=ids.tolist(),
                    coordinates=coordinates.tolist(),weights=weights.tolist(),selected_rgb=selected.tolist(),
                    neutral_weight=float(weights[np.all(ids==ids[:,:1],axis=-1)].sum()),
                    reference_corner_rgb=expected.tolist(),float64_corner_blend=(weights@expected).tolist(),
                    stored_corner_reference_maximum=float(np.max(abs(selected-expected))),
                    stored_corner_fresh_cpu_maximum=float(np.max(abs(selected-fresh))),
                    reconstructed_lut=(weights@selected).tolist(),
                    guard_changed_pixel_and_corners=projected.tolist()))
    report['vertex_audits']=audits
    report['cube_range_audits']=ranges


def write_summary(output,report):
    lines=['# Regular Grade 65³ photographic error','',
        'Ideal: direct float64 grading with the active D65 cube cache. '
        'Direct: production float32 per-pixel grading. LUT: actual regular Grade CPU/GLSL '
        '65³ vertices with numerical tetrahedral interpolation. Stage 1 is outside the LUT.','',
        'Errors are measured after pinned ACES 2.0 display conversion, before extra clipping '
        'or quantization. SDR units are 1/255; HDR units are 1/1023. '
        'Percentiles use the largest absolute channel error per pixel. '
        'The 338,688 pixels are spatial samples from four photographs.','',
        '| Grade | Backend | View | LUT−ideal p99 / max | Direct−ideal max | LUT−direct max |',
        '| --- | --- | --- | ---: | ---: | ---: |']
    for row in report['aggregates']:
        c=row['comparisons'];v=c['total']['codes']
        lines.append(f'| {row["case"]} | {row["backend"]} | {row["view"]} | '
            f'{v["p99"]:.6g} / {v["maximum"]:.6g} | '
            f'{c["implementation"]["codes"]["maximum"]:.6g} | '
            f'{c["interpolation"]["codes"]["maximum"]:.6g} |')
    lines+=['','## Worst total-error pixels','',
        '| View | Grade / backend | Photograph, original (x,y) | Expected encoded RGB | LUT encoded RGB | Error codes |',
        '| --- | --- | --- | --- | --- | ---: |']
    for view in CODE_MAX:
        rows=[r for r in report['results'] if r['view']==view]
        if not rows:continue
        row=max(rows,key=lambda r:r['comparisons']['total']['codes']['maximum'])
        result=row['comparisons']['total'];w=result['worst']
        rgb=lambda v:', '.join(f'{x:.9g}' for x in v)
        lines.append(f'| {view} | {row["case"]} / {row["backend"]} | '
            f'{row["fixture"]}, {tuple(w["original_xy"])} | {rgb(w["expected"])} | '
            f'{rgb(w["actual"])} | {result["codes"]["maximum"]:.9g} |')
    lines+=['','## CPU/GPU agreement','',
        '| View | Direct maximum codes | LUT maximum codes |','| --- | ---: | ---: |']
    for view in CODE_MAX:
        rows=[r for r in report['parity'] if r['view']==view]
        if rows:lines.append(f'| {view} | {max(r["direct"]["codes"]["maximum"] for r in rows):.6g} | '
            f'{max(r["lut"]["codes"]["maximum"] for r in rows):.6g} |')
    lines+=['','## Native cube validity','',
        'These are measured outputs, without an added repair. Escaped vertices show that '
        'the current baker does not strictly satisfy [0,1024] for these grades. '
        'JSON range audits compare each extremum with fresh CPU and cached-float64 evaluation.','',
        '| Grade | Backend | Minimum | Maximum | Vertices outside [0,1024] |',
        '| --- | --- | ---: | ---: | ---: |']
    for name,bakes in report['bakes'].items():
        for backend in ('CPU','GPU'):
            if backend not in bakes:continue
            b=bakes[backend]
            lines.append(f'| {name} | {backend} | {b["minimum_rgb"]:.9g} | '
                f'{b["maximum_rgb"]:.9g} | {b["outside_cube_pixels"]} |')
    if report.get('vertex_audits'):
        lines+=['','## Worst-pixel vertex checks','',
            'The JSON records all four corners, convex weights, neutral weight, fresh CPU '
            'corner checks, cached-float64 corner checks, and whether the pixel/corners '
            'activate the cube export guard. It also reconstructs each LUT value from its corners. '
            'This separates inaccurate stored vertices from interpolation of accurate vertices.']
    lines+=['','## Artifacts and limits','',
        'report.json includes mean absolute error, RMSE, p95/p99/p99.9, maximum, and strict '
        '>0.1/0.4/0.5/1/2-code counts for every photograph and aggregate. These bands are '
        'diagnostic, not adopted acceptance gates. Comparison maxima are not additive.','',
        'Per-image directories contain native and floating encoded arrays, ideal/direct/LUT PNGs, '
        'three error heatmaps and an enlarged worst crop (ideal | direct | LUT). HDR PNGs store '
        '16-bit Rec.2020 PQ with cICP metadata; error units remain nominal 10-bit. '
        'Heatmaps use log1p(error in codes)/log(17), capped at 16 codes.','',
        *('- '+value for value in report['limitations']),'',
        'Reproduce from the repository:','',
        '```sh','buck2 run //products/perceptual-grade-blender:grade_photo_error -- --output-dir buck-out/grade-photo-error','```','']
    (output/'summary.md').write_text('\n'.join(lines))


def run(output,selected,cpu_only=False):
    output.mkdir(parents=True,exist_ok=True);started=time.perf_counter()
    fixtures=load_fixtures();ocio=ocio_processors()
    digests=resource_hashes()
    if digests[0]!=digests[1]:raise ValueError('Extension and reference D65 resources differ')
    report=dict(timestamp=datetime.now().astimezone().isoformat(),size=65,
        source_fixtures=[dict(name=f['name'],metadata=f['metadata']) for f in fixtures],
        ocio=ocio['metadata'],d65_sha256=digests[0],python=sys.version.split()[0],numpy=np.__version__,
        settings={},bakes={},results=[],aggregates=[],parity=[],
        limitations=[
            'Cached float64 ideal uses the fitted cube capacity for driver placement; export checks decoded RGB legality.',
            'Four every-12th-row/column photographic samples, no added exposure scaling.',
            'Stage 1/input repair use a numerical float32 AP1 adapter; compositor matrix/FMA rounding is not measured.',
            'Repaired float32 input is bounded to [0,1024] for addressing; pre-bound escapes are reported.',
            'Actual regular Grade bakers, with numerical interpolation; no compositor, RGBE or half-float transport.',
            'OCIO evaluates every arm in float32. Native/encoded arrays are unclipped; PNG storage alone clips/quantizes.',
            'Single accuracy run timings include first uses and are not UI or repeated benchmark measurements.',
            'No adopted single-forward error gate; paired forward/inverse limits do not apply automatically.'])
    if not cpu_only:
        import bpy,gpu
        bpy.context.preferences.system.gpu_backend='OPENGL';gpu.init()
        report['renderer']=gpu.platform.renderer_get()
        if 'llvmpipe' not in report['renderer'].lower():raise RuntimeError('Software GPU llvmpipe required')
    for fixture in fixtures:fixture['native']=apply_processor(ocio['convert'],fixture['rgb'])
    program=None
    for name in selected:
        setting=cases()[name];model=extension_model(setting);ideal_model=LegacyCapacityModel(setting,hk_guard=True)
        report['settings'][name]=asdict(setting);item={};report['bakes'][name]=item
        inputs={};ideals={};prep_stats={}
        start=time.perf_counter()
        for f in fixtures:
            p=prepare(model,f['native']);inputs[f['name']]=np.clip(p,0,1024)
            prep_stats[f['name']]=dict(address_bounded_pixels=int(np.count_nonzero(np.any((p<0)|(p>1024),-1))),
                maximum_address_change=float(np.max(abs(inputs[f['name']]-p))))
            ideals[f['name']]=ideal_model.forward_native(f['native'])
        item['ideal_and_preparation_seconds']=time.perf_counter()-start
        cpu_images={}
        for backend in (('CPU',) if cpu_only else ('CPU','GPU')):
            start=time.perf_counter()
            if backend=='CPU':baker=baking.CPU(model,progressive=True,encoded=False)
            else:
                if program is None:
                    kernel=baking.kernel(model);program=compute.Program(kernel)
                    compute.validate_program(program,kernel)
                    report['shader_creation_seconds']=program.compile_seconds
                baker=compute.Baker(model,program,True,False,report['renderer'])
            cube=baker.finish();duration=time.perf_counter()-start
            np.save(output/f'{name}-{backend.lower()}-65.npy',cube.values)
            item[backend]=dict(setup_bake_pack_seconds=duration,**cube.diagnostics)
            print(f'{name} {backend}: baked actual regular Grade 65³',flush=True)
            pools={}
            for fixture in fixtures:
                key=fixture['name'];u=inputs[key];start=time.perf_counter()
                native=dict(ideal=ideals[key],direct=direct(baker,u),lut=tetrahedral(cube.values,u))
                if any(not np.isfinite(v).all() for v in native.values()):raise ArithmeticError('Nonfinite graded photograph')
                direct_seconds=time.perf_counter()-start
                folder=output/name/backend.lower()/key;folder.mkdir(parents=True,exist_ok=True)
                np.savez_compressed(folder/'native.npz',source=fixture['native'],input=u,**native)
                for view,processor in ocio['displays'].items():
                    encoded={k:apply_processor(processor,v) for k,v in native.items()}
                    viewdir=folder/view;viewdir.mkdir(exist_ok=True)
                    np.savez_compressed(viewdir/'encoded.npz',**encoded)
                    png={k:save_display(viewdir/f'{k}.png',v,view) for k,v in encoded.items()}
                    row=dict(case=name,backend=backend,fixture=key,view=view,direct_and_lookup_seconds=direct_seconds,
                        preparation=prep_stats[key],png=png,comparisons={})
                    for label,(actual,expected) in COMPARISONS.items():
                        metric=located(encoded[actual],encoded[expected],CODE_MAX[view],fixture)
                        row['comparisons'][label]=metric
                        pools.setdefault((view,label),[]).append((encoded[actual],encoded[expected]))
                        x,y=metric['worst']['sample_xy']
                        metric['worst'].update(source_acescg=fixture['native'][y,x].tolist(),
                            prepared_lut_input=u[y,x].tolist(),
                            **{k+'_acescg':v[y,x].tolist() for k,v in native.items()},
                            direct_encoded=encoded['direct'][y,x].tolist())
                        save_display(viewdir/f'{label}-error.png',heatmap(encoded[actual],encoded[expected],CODE_MAX[view]),'SDR100')
                    worst=row['comparisons']['total']['worst'];x,y=worst['sample_xy']
                    crop,bounds=crop_triptych([encoded[k] for k in ('ideal','direct','lut')],y,x)
                    save_display(viewdir/'worst-crop.png',crop,view);worst['crop_y0_y1_x0_x1']=list(bounds)
                    report['results'].append(row)
                    if backend=='CPU':cpu_images[key,view]=encoded
                    else:report['parity'].append(dict(case=name,fixture=key,view=view,
                        **{k:located(encoded[k],cpu_images[key,view][k],CODE_MAX[view],fixture) for k in ('direct','lut')}))
            for view in CODE_MAX:
                row=dict(case=name,backend=backend,view=view,comparisons={})
                for label in COMPARISONS:
                    pairs=pools[view,label]
                    row['comparisons'][label]=measure(np.concatenate([p[0].reshape(-1,3) for p in pairs]),
                        np.concatenate([p[1].reshape(-1,3) for p in pairs]),CODE_MAX[view])
                report['aggregates'].append(row);v=row['comparisons']['total']['codes']
                print(f'  {view}: LUT−ideal p99 {v["p99"]:.6g}, max {v["maximum"]:.6g} codes',flush=True)
            (output/'report.json').write_text(json.dumps(report,indent=2,allow_nan=False)+'\n')
            write_summary(output,report)
    report['elapsed_seconds']=time.perf_counter()-started
    report['d65_unchanged']=digests==resource_hashes()
    if not report['d65_unchanged']:raise ArithmeticError('D65 resource changed')
    audit_vertices(output,report)
    (output/'report.json').write_text(json.dumps(report,indent=2,allow_nan=False)+'\n')
    write_summary(output,report)
    compute.clear()
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir',type=Path,required=True)
    parser.add_argument('--case',action='append',choices=list(cases()))
    parser.add_argument('--cpu-only',action='store_true')
    parser.add_argument('--report-only',action='store_true',help='Rewrite the summary from saved measurements.')
    args=parser.parse_args()
    if args.report_only:
        report=json.loads((args.output_dir/'report.json').read_text())
        audit_vertices(args.output_dir,report)
        (args.output_dir/'report.json').write_text(json.dumps(report,indent=2,allow_nan=False)+'\n')
        write_summary(args.output_dir,report)
    else:run(args.output_dir,args.case or list(cases()),args.cpu_only)
