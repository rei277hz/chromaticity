"""Development-only mixed Stack inverse fidelity; no timing measurements."""
import argparse
import json
from pathlib import Path
from dataclasses import replace
import numpy as np
from color_tools.perceptual_grade_core.model import transforms, linear, tone, color, lut
from color_tools.perceptual_grade_core.model.bake_inverse import TOLERANCE
from color_tools.perceptual_grade_blender.model.stack_baking import CPU
from color_tools.perceptual_grade_reference.model import Settings,LinearSettings
from color_tools.perceptual_grade_reference.grading import ToneSettings
from color_tools.perceptual_grade_reference.grading import ColorSettings
from color_tools.perceptual_grade_core.model.tonal_web import WebSettings
from tests.reference.legacy_capacity import LegacyCapacityBakeStack


def settings(gain=0.,exposure=0.,**controls):
    return transforms.Settings.from_parameters(linear.Parameters(exposure=exposure),tone.Parameters(),
        color.Parameters(global_gain=gain,**controls),linear.GradeSpace('D65'))


def reference(value):
    p=value.color
    table=lambda stem:tuple(tuple(getattr(p,f'{stem}_{key}_{i}') for key in ('low','high','a','b')) for i in range(4))
    pairs=lambda stem:tuple(tuple(getattr(p,f'{stem}_{axis}_{i}') for axis in 'ab') for i in range(4))
    return Settings(linear=LinearSettings(matrix=value.matrix),
        tone=ToneSettings(value.tone.input_nits,value.tone.fit,value.tone.reference_nits,value.tone.peak_nits),
        color=ColorSettings(lightness=table('j'),chroma=table('c'),
            adaptance=pairs('adaptance'),lightness_fit=p.j_fit,chroma_fit=p.c_fit,
            global_gain=p.global_gain,adaptance_half_saturation=p.adaptance_half_saturation,
            web=WebSettings(**{name:tuple(tuple(getattr(p,f'web_{stem}_{i}_{j}')
                for j in range(6)) for i in range(4)) for name,stem in
                (('log_chroma','chroma'),('hue_degrees','hue'),('log_scale','scale'))})))


def comparison(actual,expected):
    return float(np.max(abs(actual-expected)/(1+np.max(abs(expected),axis=-1))[:,None],initial=0))


def generate(output):
    output.mkdir(parents=True,exist_ok=True)
    report={'scope':'Production adapter parity with portable reference kernels; no global convergence or conditioning certificate.',
            'production':'RGB arrays only; approximation diagnostics are development-only.', 'cases':{}}
    a,b=settings(.1,.2),settings(.05,-.1);x=np.array([[.1,.2,.3],[.6,.4,.2],[0,0,0.]])
    for directions in (['FORWARD','FORWARD'],['FORWARD','INVERSE'],['INVERSE','FORWARD'],['INVERSE','INVERSE']):
        value=transforms.Stack([a,b],directions=directions).apply_native(x)
        expected=LegacyCapacityBakeStack([reference(a),reference(b)],directions,hk_guard=True).apply_native(x)
        error=comparison(value,expected)
        if error>2e-6:raise AssertionError(f'{directions} oracle disagreement {error}')
        report['cases']['_'.join(directions)]={'samples':len(x),'normalized_oracle_error':error}
    for name,value,points in (
        ('raw_response_poles',settings(10.),np.array([[0.,.2,0.],[.2,0.,0.]])),
        ('general_nonlinear',settings(.15,web_hue_1_0=3.,web_chroma_1_1=.03,adaptance_b_2=.01,j_high_1=.1),x[:2])):
        core=transforms.Stack([value],directions=['INVERSE']).prepare();k=core.kernels[0]
        raw=k.grade(k.tone_state(k.enter(points)))
        result=core.solvers[0].evaluate(raw,True);inverse,error=result[:,:3],result[:,3]
        ref=LegacyCapacityBakeStack([reference(value)],['INVERSE'],hk_guard=True);expected=ref.solvers[0].evaluate(raw,True)
        parity=comparison(inverse,expected[:,:3])
        if error.max()>TOLERANCE or parity>2e-5:raise AssertionError(f'{name} fidelity failed')
        report['cases'][name]={'samples':len(points),'max_residual':float(error.max()),
            'approximate':int(np.sum(error>TOLERANCE)),'normalized_oracle_error':parity,
            'reference_max_residual':float(expected[:,3].max()),'signed_energy_minimum':float(raw[:,3].min())}
    value=settings(-8.);points=np.array([[.2,.01,.1],[0,0,0.]])
    result=transforms.Stack([value],directions=['INVERSE']).prepare().solvers[0].evaluate(points)
    expected=LegacyCapacityBakeStack([reference(value)],['INVERSE'],hk_guard=True).solvers[0].evaluate(points)
    report['cases']['unreachable_rgb']={'samples':len(points),'max_residual':float(result[:,3].max()),
        'approximate':int(np.sum(result[:,3]>TOLERANCE)),'reference_max_residual':float(expected[:,3].max()),
        'normalized_oracle_difference':comparison(result[:,:3],expected[:,:3])}
    a=settings(10.,c_high_2=-16.);b=replace(a,matrix=tuple(map(tuple,.001*np.eye(3))))
    stack=transforms.Stack([a,b],directions=['FORWARD','INVERSE'])
    baker=CPU(stack,progressive=True);preview=baker.finish_preview();full=baker.finish()
    np.testing.assert_array_equal(full.values.reshape(-1,3),lut.lattice().astype('f4'))
    stride=lut.PREVIEW_STRIDE
    np.testing.assert_array_equal(preview.values,full.values[::stride,::stride,::stride])
    output_rgb=stack.apply_native(np.array([[0.,2.,0.],[1024.,0.,1024.]]))
    report['cases']['matching_pair_full_lut']={'samples':65**3,'preview_samples':lut.PREVIEW_SIZE**3,
        'exact_float32_identity':True,'no_extra_output_guard':bool(output_rgb.max()>1024),
        'final_maximum':float(output_rgb.max())}
    # Exercise the real mismatched inverse baker on both supported grids.
    core=transforms.Stack([settings(),settings(.1)],directions=['FORWARD','INVERSE'])
    baker=CPU(core,progressive=True);small=baker.finish_preview();full=baker.finish()
    ids=np.array([0,1,7,65**2,16003,65**3-1])
    analytic=core.bake_native(lut.lattice()[ids])
    error=comparison(full.values.reshape(-1,3)[ids],analytic)
    if error>2e-6:raise AssertionError('Complete inverse LUT vertex fidelity failed')
    report['cases']['mismatched_pair_full_lut']={'samples':65**3,'preview_samples':lut.PREVIEW_SIZE**3,
        'vertex_error':error,'minimum':float(full.values.min()),'maximum':float(full.values.max())}
    (output/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    (output/'summary.md').write_text('# Stack inverse development audit\n\n'+report['scope']+'\n\n'+
        '\n'.join(f'- {name}: '+json.dumps(values) for name,values in report['cases'].items())+'\n')
    print('Stack inverse development audit passed; see report.json and summary.md.')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output-dir',type=Path,required=True)
    generate(parser.parse_args().output_dir)
