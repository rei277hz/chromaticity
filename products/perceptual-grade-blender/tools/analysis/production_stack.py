"""Photographic acceptance of production CPU/GLSL Grade Stack LUTs."""
import argparse
import json
from pathlib import Path
import numpy as np
from color_tools.perceptual_grade_core.model import transforms, linear, tone, color, lut
from color_tools.perceptual_grade_blender.model import stack_baking
from tools.analysis.photo_io import load_fixtures,ocio_processors,apply_processor
from tools.analysis.photo_stack import cases,ForcedStack,prepare,endpoint,tetrahedral
from tools.analysis.stack_photo_error import metrics,CODE_MAX


def settings(value):
    """Convert independent reference controls at the production API boundary."""
    from tests.reference.legacy_capacity import LegacyCapacityModel
    model=LegacyCapacityModel(value);p=value.color
    fields=dict(global_gain=p.global_gain,adaptance_half_saturation=p.adaptance_half_saturation,
        j_fit=p.lightness_fit,c_fit=p.chroma_fit)
    for stem,name,axes in (('j','lightness',('low','high','a','b')),('c','chroma',('low','high','a','b')),
                           ('adaptance','adaptance',('a','b'))):
        for i,row in enumerate(getattr(p,name)):
            fields.update({f'{stem}_{axis}_{i}':v for axis,v in zip(axes,row)})
    for stem,name in (('chroma','log_chroma'),('hue','hue_degrees'),('scale','log_scale')):
        for i,row in enumerate(getattr(p.web,name)):
            fields.update({f'web_{stem}_{i}_{j}':v for j,v in enumerate(row)})
    t=value.tone
    tp=tone.Parameters(**dict(zip(tone.LEVEL_FIELDS,t.input_nits)),fit=t.fit,
        reference_nits=t.reference_nits,peak_nits=t.peak_nits)
    return transforms.Settings(tuple(map(tuple,model.linear)),tp,color.Parameters(**fields),linear.GradeSpace('D65'))


def run(output,cpu_only=False):
    output.mkdir(parents=True,exist_ok=True)
    fixtures=load_fixtures();ocio=ocio_processors();rows=[];program=None
    if not cpu_only:
        import bpy,gpu
        bpy.context.preferences.system.gpu_backend='OPENGL';gpu.init()
        if not gpu.capabilities.compute_shader_support_get():raise RuntimeError('Compute shaders required')
    for name,value in cases().items():
        reference=ForcedStack([value,value],['FORWARD','INVERSE'],hk_guard=True)
        prepared=[prepare(reference,apply_processor(ocio['convert'],f['rgb'])) for f in fixtures]
        for backend in (('CPU',) if cpu_only else ('CPU','GPU')):
            entry=settings(value);model=transforms.Stack([entry,entry],directions=['FORWARD','INVERSE'])
            core=model.prepare()
            # Exercise actual inverse kernels rather than exact pair cancellation.
            core.matching=lambda left,right:False
            if backend=='CPU':baker=stack_baking.CPU(model,progressive=True,encoded=True)
            else:
                if program is None:program=stack_baking.Program(core.solvers[0])
                baker=stack_baking.GPU(model,program,True,True,gpu.platform.renderer_get())
            cube=baker.finish()
            np.testing.assert_array_equal(baker.preview.values,cube.values[::2,::2,::2])
            for fixture,source in zip(fixtures,prepared):
                actual=endpoint(core,tetrahedral(cube.values,source['input']))
                for view,processor in ocio['displays'].items():
                    result=metrics(apply_processor(processor,actual),
                        apply_processor(processor,source['ideal']),CODE_MAX[view])
                    limit=.1 if view=='SDR100' else .4
                    rows.append(dict(case=name,backend=backend,fixture=fixture['name'],view=view,
                        limit_codes=limit,passed=result['codes']['maximum']<limit,metrics=result))
            maxima={view:max(r['metrics']['codes']['maximum'] for r in rows if
                r['case']==name and r['backend']==backend and r['view']==view) for view in CODE_MAX}
            print(name,backend,maxima,flush=True)
    report=dict(passed=all(r['passed'] for r in rows),ocio=ocio['metadata'],results=rows,
        scope='Actual production progressive CPU/GLSL 65^3 baker; numerical physical-RGB tetrahedral sampling and pinned ACES 2 display transforms.',
        forced_inverse=True,resource_regenerated=False)
    (output/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    lines=['# Production Stack photographic gate','',report['scope'],'',
           '| Case | Backend | SDR max codes | HDR max codes |','| --- | --- | ---: | ---: |']
    for name in cases():
        for backend in (('CPU',) if cpu_only else ('CPU','GPU')):
            maxima=[max(r['metrics']['codes']['maximum'] for r in rows if r['case']==name and
                r['backend']==backend and r['view']==view) for view in CODE_MAX]
            lines.append(f'| {name} | {backend} | {maxima[0]:.8g} | {maxima[1]:.8g} |')
    (output/'summary.md').write_text('\n'.join(lines)+'\n')
    if not report['passed']:raise AssertionError('Production photographic gate failed; see report.json')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir',type=Path,required=True);parser.add_argument('--cpu-only',action='store_true')
    args=parser.parse_args();run(args.output_dir,args.cpu_only)
