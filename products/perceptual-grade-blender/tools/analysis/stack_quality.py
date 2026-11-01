from color_tools.perceptual_grade_blender.model.bake_inverse_gpu import Program as ReferenceGPUProgram
"""Production float32 Stack parity and separate cached-float64 diagnostics."""
import argparse
import json
from pathlib import Path
import numpy as np
from color_tools.perceptual_grade_reference.model import Settings, LinearSettings
from tests.reference.legacy_capacity import LegacyCapacityModel
from color_tools.perceptual_grade_reference.grading import ColorSettings
from color_tools.perceptual_grade_core.model.tonal_web import WebSettings
from tests.reference.legacy_capacity import LegacyCapacityBakeStack
from color_tools.perceptual_grade_core.model import transforms, linear, tone, color


def pair(exposure=0.,gain=0.,hue=0.):
    ref=LegacyCapacityModel(Settings(linear=LinearSettings(exposure=exposure),color=ColorSettings(global_gain=gain,web=WebSettings(hue_degrees=((hue,)*6,)*4))),hk_guard=True)
    settings=transforms.Settings.from_parameters(linear.Parameters(exposure=exposure),tone.Parameters(),
        color.Parameters(global_gain=gain,**{f'web_hue_{i}_{j}':hue for i in range(4) for j in range(6)}),linear.GradeSpace('D65'))
    return ref,settings


def grid(axis):return np.stack(np.meshgrid(axis,axis,axis,indexing='ij'),-1).reshape(-1,3)


def error(a,b):return np.max(abs(a-b),axis=-1)/np.maximum(np.max(abs(b),axis=-1),np.finfo(float).tiny)


def bounds(x):
    if not np.isfinite(x).all():raise AssertionError('Nonfinite Stack output')
    return {'minimum':float(x.min()),'maximum':float(x.max()),
        'outside_cube_pixels':int(np.count_nonzero(np.any((x<0)|(x>1024),axis=-1)))}


def compare(actual,expected):
    absolute=np.max(abs(actual.astype(float)-expected),axis=-1);worst=int(np.argmax(absolute))
    return {'max_absolute_error':float(absolute[worst]),
        'max_normalized_error':float(np.max(absolute/(1+np.max(abs(expected),axis=-1)))),
        'max_peak_relative_error':float(error(actual,expected).max()),'worst_absolute_index':worst}


def adapter_parity(actual,expected):
    result=compare(actual,expected)
    if result['max_normalized_error']>2e-6:raise AssertionError(f'Portable adapter disagreement: {result}')
    return result


def jacobian(fn,x,step):
    scale=max(np.max(abs(x)),1e-12)
    return np.stack([(fn(x+v*step*scale)-fn(x-v*step*scale))/(2*step*scale) for v in np.eye(3)],axis=-1)


def generate(output):
    output.mkdir(parents=True,exist_ok=True)
    report={'reset':{},'grades':{},'cached_float64_sensitivity':{},
        'scope':'Production float32 core versus legacy-capacity portable BakeStack on identical prepared inputs; independently constructed Stage 1 endpoints, cached float64 oracle and fitted-boundary range escapes are separate diagnostics. No global range, conditioning or response-pole certificate.',
        'adapter_normalized_tolerance':2e-6,'resource_regenerated':False}
    ref,setting=pair()
    axes={'uniform65':np.linspace(0,1024,65),'log65':np.r_[0.,np.geomspace(1e-12,1024,64)]}
    for name,axis in axes.items():
        x=grid(axis);expected=ref.forward_native(x)
        for count in (1,2,4):
            actual=transforms.Stack([setting]*count).apply_native(x)
            portable=LegacyCapacityBakeStack([ref.settings]*count,hk_guard=True, program_factory=ReferenceGPUProgram).apply_native(x)
            relative=error(actual,x);worst=int(np.argmax(relative))
            reset=adapter_parity(actual,x)
            np.testing.assert_array_equal(actual[0],0.)
            report['reset'][f'{name}_{count}_grades']={'samples':len(x),'max_peak_relative_error':float(relative.max()),
                'worst_input':x[worst].tolist(),'reset':reset,'bounds':bounds(actual),
                'portable_parity':adapter_parity(actual,portable),'cached_float64_difference':compare(actual,expected)}
    samples=grid(np.r_[0.,np.geomspace(1e-10,1024,16)])
    profiles={'minus8':(-8,0,0),'plus8':(8,0,0),'chroma8':(0,8,0),'both8':(8,8,0),'hue90':(0,0,90),'mixed':(.7,1.2,27)}
    for name,args in profiles.items():
        r,s=pair(*args);stack=transforms.Stack([s]);a=stack.apply_native(samples);b=r.forward_native(samples)
        core=stack.prepare();portable=LegacyCapacityBakeStack([r.settings],hk_guard=True, program_factory=ReferenceGPUProgram)
        prepared=core.solvers[0].repair(core.matrix(samples.astype('f4'),core.input_matrix))
        common=core.matrix(portable.bake_native(prepared)[:,:3],core.output_matrix)
        np.testing.assert_array_equal(a[0],0.)
        report['grades'][name]={'samples':len(a),'bounds':bounds(a),'cached_float64_bounds':bounds(b),
            'portable_core_parity':adapter_parity(a,common),
            'portable_end_to_end_difference':compare(a,portable.apply_native(samples)),
            'cached_float64_difference':compare(a,b)}
    # Seed-51013 worst release-only witness, with strictly positive neighbors.
    witness=np.array([1.609146194894814e-7,9.267665899672671e-5,.0016091461948948137])
    for name,args in {'reset':(0,0,0),'exposure':(.1,0,0),'chroma':(0,.1,0),'hue':(0,0,1)}.items():
        r,s=pair(*args);fn=r.forward_native;y=fn(witness)
        j=jacobian(fn,witness,1e-7);j2=jacobian(fn,witness,5e-8);singular=np.linalg.svd(j,compute_uv=False)
        report['cached_float64_sensitivity'][name]={'input':witness.tolist(),'output':y.tolist(),
            'production_float32_output':transforms.Stack([s]).apply_native(witness).tolist(),'absolute_gain':float(singular[0]),
            'relative_gain':float(singular[0]*np.linalg.norm(witness)/max(np.linalg.norm(y),np.finfo(float).tiny)),
            'step_disagreement':float(np.max(abs(j-j2)))}
    (output/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    (output/'summary.md').write_text('# Adopted stack diagnostics\n\n'+report['scope']+'\n\n'+
        '\n'.join(f'- {k}: {v["max_peak_relative_error"]:.6g} peak-relative reset error.' for k,v in report['reset'].items() if isinstance(v,dict))+'\n\n'+
        '\n'.join(f'- {k}: {v["bounds"]["outside_cube_pixels"]} sampled production range escapes; portable core normalized error {v["portable_core_parity"]["max_normalized_error"]:.6g}; complete endpoint difference {v["portable_end_to_end_difference"]["max_normalized_error"]:.6g}.' for k,v in report['grades'].items())+'\n\n'+
        '\n'.join(f'- {k}: cached-float64 absolute gain {v["absolute_gain"]:.6g}, relative gain {v["relative_gain"]:.6g}.' for k,v in report['cached_float64_sensitivity'].items())+'\n')
    print(json.dumps(report),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output-dir',type=Path,required=True)
    generate(p.parse_args().output_dir)
