"""Fixed-65-cube sample-placement study using unchanged production grading math."""
import argparse
from dataclasses import asdict
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sys
import time
import numpy as np
from color_tools.perceptual_grade_blender.model import baking, gpu as compute
from color_tools.perceptual_grade_core.model.bake_cache import CachedKernel, Store
from tests.reference.legacy_capacity import LegacyCapacityModel
from tools.analysis.grade_photo_error import direct, measure, resource_hashes
from tools.analysis.lut_shapers import Shaper, initial_candidates, refinements, addresses, tetrahedral
from tools.analysis.photo_grade import extension_model, prepare
from tools.analysis.photo_io import load_fixtures, ocio_processors, apply_processor, save_display
from tools.analysis.photo_stack import cases
from tools.analysis.stack_photo_error import CODE_MAX, heatmap, crop_triptych


FAMILIES=('log','tanh','log_tanh')
BASELINE=Shaper()


class ShapedRows:
    """Only substitute input vertices; keep production scheduling and arithmetic."""
    def __init__(self,shaper,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.samples=shaper.lattice()
        # A private store prevents fixed-grid row IDs from aliasing another
        # shaper. Every measured bake starts with empty row caches.
        self.cached=CachedKernel(self.kernel,65**3,Store())

    def evaluate_rows(self,rows):
        self.checkpoint();rgb=self.samples[rows]
        if self.backend=='GPU':
            compute.require_main_thread()
            if self.kernel.identity:return rgb.copy()
            self.program.parameters=self.parameters
            entry=self.cached.cached(('entry','GPU',self.device),rows,
                lambda missing:self.program.evaluate(rgb[missing],0))
            self.checkpoint();values=self.program.evaluate(entry,1)[:,:3]
        else:
            values=self.cached.evaluate(rgb,rows,self.checkpoint)
        self.checkpoint()
        if not np.isfinite(values).all():raise ArithmeticError('Nonfinite shaper-study bake')
        return values


class CPU(ShapedRows,baking.CPU):pass
class GPU(ShapedRows,compute.Baker):pass


def ranking(result,baseline):
    """Balance grades/views using relative regression, not absolute stress size."""
    maxima=[];percentiles=[]
    for row in result['aggregates']:
        if row['case'] in ('reset','exposure'):continue
        base=next(r for r in baseline['aggregates'] if (r['case'],r['view'])==(row['case'],row['view']))
        for metric,values in (('maximum',maxima),('p99',percentiles)):
            denominator=base['total']['codes'][metric]
            if denominator<=0:raise ValueError('Ranking requires positive baseline errors')
            values.append(row['total']['codes'][metric]/denominator)
    return dict(worst_maximum_ratio=float(max(maxima)),
        geometric_mean_p99_ratio=float(np.exp(np.mean(np.log(np.maximum(percentiles,1e-300))))),
        all_maxima_improved=bool(all(value<1 for value in maxima)))


def rank_key(result):
    rank=result['ranking']
    return (rank['worst_maximum_ratio'],rank['geometric_mean_p99_ratio'],result['key'])


def winners(results):
    return {family:min((r for r in results if r['shaper']['family']==family),key=rank_key)
            for family in FAMILIES}


def save_json(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,indent=2,allow_nan=False)+'\n')


def prepare_data(fixtures,ocio):
    data={};source=np.concatenate([f['native'].reshape(-1,3) for f in fixtures])
    for name,setting in cases().items():
        start=time.perf_counter();model=extension_model(setting);oracle=LegacyCapacityModel(setting,hk_guard=True)
        p=prepare(model,source);inputs=np.clip(p,0,1024)
        ideal=oracle.forward_native(source)
        baker=baking.CPU(model,True,False);actual=direct(baker,inputs)
        data[name]=dict(model=model,source=source,input=inputs,ideal=ideal,
            direct={'CPU':actual},encoded_ideal={},encoded_direct={'CPU':{}},
            preparation=dict(address_bounded_pixels=int(np.count_nonzero(np.any(p!=inputs,-1))),
                maximum_address_change=float(np.max(abs(p-inputs)))))
        item=data[name]
        for view,processor in ocio['displays'].items():
            item['encoded_ideal'][view]=apply_processor(processor,ideal)
            item['encoded_direct']['CPU'][view]=apply_processor(processor,actual)
        item['preparation_seconds']=time.perf_counter()-start
        print(f'Prepared fixed ideal/direct: {name} ({item["preparation_seconds"]:.2f}s)',flush=True)
    return data


def locate(metric,fixtures,item,native):
    index=metric['worst']['flat_index'];offset=0
    for f in fixtures:
        size=f['rgb'].shape[0]*f['rgb'].shape[1]
        if index<offset+size:
            y,x=np.unravel_index(index-offset,f['rgb'].shape[:2]);break
        offset+=size
    metric['worst'].update(fixture=f['name'],sample_xy=[int(x),int(y)],
        original_xy=[int(x)*12,int(y)*12],source_acescg=item['source'][index].tolist(),
        prepared_lut_input=item['input'][index].tolist(),
        ideal_acescg=item['ideal'][index].tolist(),actual_acescg=native[index].tolist())


def vertex_audit(shaper,cube,point,model):
    _,corners,f=addresses(np.asarray(point).reshape(1,3),shaper)
    ids=np.stack(corners,axis=1)[0];f=f[0]
    weights=np.array([1-f[0],f[0]-f[1],f[1]-f[2],f[2]])
    samples=shaper.axis()[ids].astype('f4');values=cube[ids[:,0],ids[:,1],ids[:,2]]
    fresh=baking.kernel(model).evaluate(samples)
    return dict(indices=ids.tolist(),coordinates=samples.tolist(),weights=weights.tolist(),
        stored_rgb=values.tolist(),fresh_cpu_rgb=fresh.tolist(),
        fresh_cpu_maximum_difference=float(np.max(abs(values-fresh))),
        reconstructed_rgb=(weights@values.astype(float)).tolist(),
        neutral_weight=float(weights[np.all(ids==ids[:,:1],axis=-1)].sum()))


def artifacts(folder,fixtures,item,native,encoded,backend,cube,shaper):
    folder.mkdir(parents=True,exist_ok=True);np.save(folder/'cube.npy',cube)
    np.save(folder/'axis.npy',shaper.axis());offset=0
    for fixture in fixtures:
        shape=fixture['rgb'].shape;size=shape[0]*shape[1];s=slice(offset,offset+size);offset+=size
        root=folder/fixture['name'];root.mkdir(exist_ok=True)
        np.savez_compressed(root/'native.npz',source=item['source'][s].reshape(shape),
            input=item['input'][s].reshape(shape),ideal=item['ideal'][s].reshape(shape),
            direct=item['direct'][backend][s].reshape(shape),lut=native[s].reshape(shape))
        for view in CODE_MAX:
            images=dict(ideal=item['encoded_ideal'][view][s].reshape(shape),
                direct=item['encoded_direct'][backend][view][s].reshape(shape),lut=encoded[view][s].reshape(shape))
            output=root/view;output.mkdir(exist_ok=True);np.savez_compressed(output/'encoded.npz',**images)
            for label,image in images.items():save_display(output/f'{label}.png',image,view)
            save_display(output/'error.png',heatmap(images['lut'],images['ideal'],CODE_MAX[view]),'SDR100')
            difference=np.max(abs(images['lut']-images['ideal']),-1)
            y,x=np.unravel_index(np.argmax(difference),difference.shape)
            crop,_=crop_triptych([images[k] for k in ('ideal','direct','lut')],y,x)
            save_display(output/'worst-crop.png',crop,view)


def evaluate(shaper,data,fixtures,ocio,backend='CPU',program=None,device=None,output=None):
    result=dict(key=shaper.key,shaper=shaper.to_dict(),backend=backend,
        diagnostics=shaper.diagnostics(),bakes={},aggregates=[],results=[],vertex_audits=[])
    if not result['diagnostics']['valid']:raise ArithmeticError('Invalid float32 shaper: '+shaper.key)
    for name,item in data.items():
        start=time.perf_counter()
        baker=CPU(shaper,item['model'],True,False) if backend=='CPU' else GPU(shaper,item['model'],program,True,False,device)
        cube=baker.finish();duration=time.perf_counter()-start
        result['bakes'][name]=dict(fresh_setup_bake_pack_seconds=duration,**cube.diagnostics)
        if shaper==BASELINE:
            # Independently exercise the unchanged production fixed-grid path.
            check=(baking.CPU(item['model'],True,False) if backend=='CPU'
                   else compute.Baker(item['model'],program,True,False,device))
            check.cached=CachedKernel(check.kernel,65**3,Store())
            original=check.finish().values
            if not np.array_equal(original,cube.values):
                raise ArithmeticError(f'{backend} baseline cube differs from production: {name}')
            result['bakes'][name]['production_baseline_bit_identical']=True
        start=time.perf_counter();native=tetrahedral(cube.values,item['input'],shaper)
        result['bakes'][name]['lookup_seconds']=time.perf_counter()-start
        encoded={}
        for view,processor in ocio['displays'].items():
            actual=apply_processor(processor,native);encoded[view]=actual
            row=dict(case=name,view=view,total=measure(actual,item['encoded_ideal'][view],CODE_MAX[view]),
                interpolation=measure(actual,item['encoded_direct'][backend][view],CODE_MAX[view]))
            locate(row['total'],fixtures,item,native);result['aggregates'].append(row)
            offset=0
            for f in fixtures:
                size=f['rgb'].shape[0]*f['rgb'].shape[1];s=slice(offset,offset+size)
                metric=measure(actual[s],item['encoded_ideal'][view][s],CODE_MAX[view])
                # Convert the index to the concatenated array for common provenance.
                metric['worst']['flat_index']+=offset;locate(metric,fixtures,item,native)
                result['results'].append(dict(case=name,view=view,fixture=f['name'],total=metric))
                offset+=size
            if output is not None:
                result['vertex_audits'].append(dict(case=name,view=view,
                    **vertex_audit(shaper,cube.values,row['total']['worst']['prepared_lut_input'],item['model'])))
        if output is not None:
            artifacts(output/shaper.key/backend.lower()/name,fixtures,item,native,encoded,backend,cube.values,shaper)
    return result


def summarize(output,report):
    rows=sorted(report.get('candidates',[]),key=rank_key)
    lines=['# Fixed 65³ input-shaper comparison','',
        'Only sample positions and matching addresses change. Linear-RGB tetrahedral '
        'fractions, four reads, grading math and output representation are unchanged. '
        'One shaper is shared by channels and grades.','',
        'All four sampled photographs and eight grades; errors before clipping/quantization '
        'through pinned ACES 2.0 views. SDR codes use 255; HDR codes use 1023. '
        'The float64 ideal retains the current fitted D65 boundary.','',
        'Ranking minimizes the largest candidate/baseline maximum-error ratio across '
        'six nontrivial grades and both views, then geometric-mean p99 ratios. Reset/exposure '
        'are controls. This is not a new acceptance gate.','',
        '| Candidate | Worst max ratio | Geometric p99 ratio | SDR max | HDR max |',
        '| --- | ---: | ---: | ---: | ---: |']
    for row in rows:
        maxima=[max(r['total']['codes']['maximum'] for r in row['aggregates'] if r['view']==v) for v in CODE_MAX]
        lines.append(f'| {row["key"]} | {row["ranking"]["worst_maximum_ratio"]:.6g} | '
            f'{row["ranking"]["geometric_mean_p99_ratio"]:.6g} | {maxima[0]:.6g} | {maxima[1]:.6g} |')
    if report.get('winners'):
        lines+=['','## Family finalists','',*('- '+family+': `'+key+'`' for family,key in report['winners'].items())]
    if report.get('validation'):
        lines+=['','## Finalist errors by grade','',
            '| Shaper | Backend | Grade | View | p99 | Maximum | >1 code pixels |',
            '| --- | --- | --- | --- | ---: | ---: | ---: |']
        for result in report['validation']:
            for row in result['aggregates']:
                metric=row['total'];c=metric['codes']
                lines.append(f'| {result["key"]} | {result["backend"]} | {row["case"]} | {row["view"]} | '
                    f'{c["p99"]:.6g} | {c["maximum"]:.6g} | {metric["pixels_above_codes"]["1.0"]} |')
        lines+=['','## Per-photograph tradeoffs','',
            'Improving the maximum across all photographs does not imply improving each photograph. '
            'Counts below exclude the reset/exposure controls; all 48 nontrivial photograph/view/grade '
            'comparisons are retained in JSON. Comparisons use each backend\'s own baseline.','',
            '| Shaper | Backend | Worse per-photo maxima | Improved per-photo p99 | Largest proportional maximum regression |',
            '| --- | --- | ---: | ---: | --- |']
        for result in report['validation']:
            if result['key']==BASELINE.key:continue
            baseline=next(r for r in report['validation'] if r['key']==BASELINE.key and r['backend']==result['backend'])
            base={(r['case'],r['view'],r['fixture']):r['total']['codes'] for r in baseline['results']}
            regressions=[];improved=0
            for row in result['results']:
                if row['case'] in ('reset','exposure'):continue
                b=base[row['case'],row['view'],row['fixture']];a=row['total']['codes']
                improved+=int(a['p99']<b['p99'])
                if a['maximum']>b['maximum']:
                    regressions.append((a['maximum']/b['maximum'],row,b['maximum'],a['maximum']))
            worst='None'
            if regressions:
                ratio,row,b,a=max(regressions,key=lambda r:r[0])
                worst=f'{row["case"]}, {row["view"]}, {row["fixture"]}: {b:.6g} → {a:.6g} ({ratio:.4g}×)'
            lines.append(f'| {result["key"]} | {result["backend"]} | {len(regressions)}/48 | {improved}/48 | {worst} |')
        lines+=['','## Fresh bake and lookup costs','',
            'Each bake starts with empty row caches and includes its own lattice, '
            'baker setup and raw atlas packing. Immutable D65 context and shader program '
            'are shared; their first setup costs are recorded separately in JSON. '
            'Lookup timings cover all 338,688 inputs, excluding display conversion. '
            'Single accuracy-run timings are not UI or physical-GPU benchmarks.','',
            '| Shaper | Backend | Grade | Fresh bake ms | Numerical lookup ms | Native min / max | Escaped vertices |',
            '| --- | --- | --- | ---: | ---: | --- | ---: |']
        for result in report['validation']:
            for name,b in result['bakes'].items():
                lines.append(f'| {result["key"]} | {result["backend"]} | {name} | '
                    f'{1000*b["fresh_setup_bake_pack_seconds"]:.3f} | {1000*b["lookup_seconds"]:.3f} | '
                    f'{b["minimum_rgb"]:.6g} / {b["maximum_rgb"]:.6g} | {b["outside_cube_pixels"]} |')
    if report.get('parity'):
        lines+=['','## Finalist CPU/GPU agreement','',
            '| Shaper | View | Maximum encoded disagreement | Native vertex disagreement |',
            '| --- | --- | ---: | ---: |']
        for key in dict.fromkeys(r['key'] for r in report['parity']):
            for view in CODE_MAX:
                selected=[r for r in report['parity'] if r['key']==key and r['view']==view]
                lines.append(f'| {key} | {view} | '
                    f'{max(r["lut"]["codes"]["maximum"] for r in selected):.6g} | '
                    f'{max(r["vertex_maximum_difference"] for r in selected):.6g} |')
    lines+=['','## Limits','',
        'Existing guard/cache range escapes remain visible; no final RGB repair was added. '
        'Numerical float64 addressing/interpolation excludes Blender graph/FMA and '
        'compositor/RGBE/half-float transport. Float32 shaper conditioning is reported separately. '
        'CPU and GPU use their production arithmetic, and the GPU uses llvmpipe. '
        'Only fixture samples are measured, not full-resolution originals or all possible colors. '
        'Parameters are selected on these same fixtures; there is no independent holdout set. '
        'Production defaults and D65 are unchanged.','',
        '```sh','buck2 run //products/perceptual-grade-blender:grade_shaper_error -- --output-dir buck-out/grade-shaper-error','```','']
    (output/'summary.md').write_text('\n'.join(lines))


def audit_saved_finalists(output,report):
    """Reproduce cross-backend agreement from final saved artifacts, without baking."""
    report['parity']=[]
    for result in report.get('validation',[]):
        if result['backend']!='CPU':continue
        screened=next(r for r in report['candidates'] if r['key']==result['key'])
        result['cpu_screen_reproduced']=(result['aggregates']==screened['aggregates'] and result['results']==screened['results'])
        if not result['cpu_screen_reproduced']:raise ArithmeticError('Final CPU result differs from its screen')
    keys={r['key'] for r in report.get('validation',[]) if r['backend']=='GPU'}
    for key in sorted(keys):
        for name in report['settings']:
            base=output/'finalists'/key
            cubes={b:np.load(base/b/name/'cube.npy',allow_pickle=False) for b in ('cpu','gpu')}
            maximum=float(np.max(abs(cubes['cpu'].astype(float)-cubes['gpu'])))
            for view in CODE_MAX:
                values={'cpu':[],'gpu':[]}
                for fixture in report['source_fixtures']:
                    for backend in values:
                        path=base/backend/name/fixture['name']/view/'encoded.npz'
                        with np.load(path,allow_pickle=False) as archive:values[backend].append(archive['lut'].reshape(-1,3))
                report['parity'].append(dict(key=key,case=name,view=view,vertex_maximum_difference=maximum,
                    lut=measure(np.concatenate(values['gpu']),np.concatenate(values['cpu']),CODE_MAX[view])))


def math_hash():
    """Fingerprint numerical inputs before resuming an interrupted sweep."""
    import color_tools.perceptual_grade_core.model.bake as core
    import color_tools.perceptual_grade_reference.model as reference
    import tools.analysis.lut_shapers as shapers
    from tests.reference import legacy_capacity
    paths={Path(shapers.__file__),Path(legacy_capacity.__file__)}
    for module in (baking,core,reference):paths.update(Path(module.__file__).parent.glob('*.py'))
    digest=hashlib.sha256()
    for path in sorted(paths):digest.update(path.name.encode());digest.update(path.read_bytes())
    return digest.hexdigest()


def run(output,resume=False):
    output.mkdir(parents=True,exist_ok=True);started=time.perf_counter()
    fixtures=load_fixtures();ocio=ocio_processors();hashes=resource_hashes()
    if hashes[0]!=hashes[1]:raise ValueError('D65 resources differ')
    for f in fixtures:f['native']=apply_processor(ocio['convert'],f['rgb'])
    start=time.perf_counter();baking.resource();context_seconds=time.perf_counter()-start
    report=dict(timestamp=datetime.now().astimezone().isoformat(),python=sys.version.split()[0],
        numpy=np.__version__,size=65,ocio=ocio['metadata'],d65_sha256=hashes[0],
        source_fixtures=[dict(name=f['name'],metadata=f['metadata']) for f in fixtures],
        settings={name:asdict(value) for name,value in cases().items()},
        math_sha256=math_hash(),d65_context_seconds=context_seconds,candidates=[],validation=[],direct=[])
    previous=None
    if resume:
        previous=json.loads((output/'report.json').read_text())
        for key in ('size','ocio','d65_sha256','source_fixtures','settings','math_sha256'):
            if previous[key]!=report[key]:raise ValueError('Cannot resume changed experiment: '+key)
    data=prepare_data(fixtures,ocio)
    report['preparation']={name:dict(seconds=item['preparation_seconds'],**item['preparation']) for name,item in data.items()}
    for name,item in data.items():
        for view in CODE_MAX:
            report['direct'].append(dict(case=name,backend='CPU',view=view,
                metric=measure(item['encoded_direct']['CPU'][view],item['encoded_ideal'][view],CODE_MAX[view])))
    policies=initial_candidates();baseline=evaluate(BASELINE,data,fixtures,ocio)
    baseline['ranking']=ranking(baseline,baseline);report['candidates'].append(baseline)
    baseline['phase']='initial'
    if previous is not None:
        saved=next(r for r in previous['candidates'] if r['key']==BASELINE.key)
        if saved['aggregates']!=baseline['aggregates']:raise ArithmeticError('Resumed baseline differs')
        report['candidates'].extend(r for r in previous['candidates'] if r['key']!=BASELINE.key)
        report['resumed_candidates']=len(report['candidates'])-1
    def screen(shaper,phase):
        start=time.perf_counter();result=evaluate(shaper,data,fixtures,ocio)
        result['ranking']=ranking(result,baseline);result['phase']=phase
        result['elapsed_seconds']=time.perf_counter()-start
        report['candidates'].append(result)
        save_json(output/'report.json',report);summarize(output,report)
        print(f'{len(report["candidates"]):3d} {shaper.key}: max ratio '
            f'{result["ranking"]["worst_maximum_ratio"]:.6g}, p99 ratio '
            f'{result["ranking"]["geometric_mean_p99_ratio"]:.6g}, {result["elapsed_seconds"]:.2f}s',flush=True)
    for shaper in policies:
        if shaper.key not in {r['key'] for r in report['candidates']}:screen(shaper,'initial')
    initial=winners([r for r in report['candidates'] if r['phase']=='initial'])
    report['initial_winners']={k:v['key'] for k,v in initial.items()}
    known={r['key'] for r in report['candidates']}
    for result in initial.values():
        for shaper in refinements(Shaper(**result['shaper'])):
            if shaper.key not in known:
                known.add(shaper.key);screen(shaper,'refinement')
    best=winners(report['candidates']);report['winners']={k:v['key'] for k,v in best.items()}
    finalists={BASELINE.key:BASELINE,**{r['key']:Shaper(**r['shaper']) for r in best.values()}}
    import bpy,gpu
    bpy.context.preferences.system.gpu_backend='OPENGL';gpu.init()
    report['renderer']=gpu.platform.renderer_get()
    if 'llvmpipe' not in report['renderer'].lower():raise RuntimeError('llvmpipe required; no CPU substitution')
    start=time.perf_counter();kernel=baking.kernel(next(iter(data.values()))['model'])
    program=compute.Program(kernel);compute.validate_program(program,kernel)
    report['gpu_program_setup_seconds']=time.perf_counter()-start
    report['shader_compile_seconds']=program.compile_seconds
    for name,item in data.items():
        baker=compute.Baker(item['model'],program,True,False,report['renderer'])
        actual=direct(baker,item['input']);item['direct']['GPU']=actual
        item['encoded_direct']['GPU']={v:apply_processor(p,actual) for v,p in ocio['displays'].items()}
        for view in CODE_MAX:
            report['direct'].append(dict(case=name,backend='GPU',view=view,
                metric=measure(item['encoded_direct']['GPU'][view],item['encoded_ideal'][view],CODE_MAX[view])))
    for shaper in finalists.values():
        for backend in ('CPU','GPU'):
            result=evaluate(shaper,data,fixtures,ocio,backend,program,report['renderer'],output/'finalists')
            result['ranking']=ranking(result,baseline);report['validation'].append(result)
            save_json(output/'report.json',report);summarize(output,report)
            print(f'Validated {shaper.key} {backend}',flush=True)
    report['d65_unchanged']=resource_hashes()==hashes
    if not report['d65_unchanged']:raise ArithmeticError('D65 changed')
    report['elapsed_seconds']=time.perf_counter()-started
    audit_saved_finalists(output,report)
    save_json(output/'report.json',report);summarize(output,report);compute.clear()
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir',type=Path,default=Path('buck-out/grade-shaper-error'))
    parser.add_argument('--resume',action='store_true',help='Reuse completed screens after provenance and baseline checks')
    parser.add_argument('--report-only',action='store_true',help='Rewrite summary from saved metrics, without baking')
    args=parser.parse_args()
    if args.report_only:
        report=json.loads((args.output_dir/'report.json').read_text())
        audit_saved_finalists(args.output_dir,report)
        save_json(args.output_dir/'report.json',report);summarize(args.output_dir,report)
    else:run(args.output_dir,args.resume)


if __name__=='__main__':main()
