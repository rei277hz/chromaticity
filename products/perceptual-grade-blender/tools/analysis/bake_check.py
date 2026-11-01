"""Full-grade oracle and actual compute conformance, without a backend fallback."""
import argparse
import json
from pathlib import Path
import sys
import time
import numpy as np
from color_tools.perceptual_grade_core.model.bake import Kernel
from color_tools.perceptual_grade_reference.grading import ToneSettings
from color_tools.perceptual_grade_reference.grading import ColorSettings
from color_tools.perceptual_grade_core.model.tonal_web import WebSettings
from color_tools.perceptual_grade_reference.model import Settings
from tests.reference.legacy_capacity import LegacyCapacityModel
from tools.build.boundary_oracle import exact_geometry


def cases():
    yield 'reset',Settings()
    yield 'tone',Settings(tone=ToneSettings(input_nits=(0.,7.,45.,203.,1000.)))
    for gain in (1.,10.):
        chroma=np.zeros((4,4));chroma[2,1]=gain
        yield f'white_chroma_{gain:g}',Settings(color=ColorSettings(chroma=tuple(map(tuple,chroma))))
    yield 'web_hue',Settings(color=ColorSettings(web=WebSettings(hue_degrees=((20.,10.,0.,-10.,0.,10.),)*4)))
    yield 'adaptance',Settings(color=ColorSettings(adaptance=((20.,-10.),)*4))
    yield 'darken',Settings(color=ColorSettings(lightness=((-20.,-50.,0.,0.),)*4))
    yield 'web_scale',Settings(color=ColorSettings(web=WebSettings(
        log_chroma=((.1,-.1,.2,0.,-.2,.1),)*4,
        log_scale=((.1,0.,-.1,.05,0.,-.05),)*4)))
    for fit in (-2.,6.):
        yield f'combined_fit_{fit:g}',Settings(tone=ToneSettings(input_nits=(0.,7.,42.,203.,1000.),fit=fit),
            color=ColorSettings(lightness=((5.,-10.,2.,-3.),)*4,chroma=((.2,.5,-.1,.1),)*4,
                web=WebSettings(hue_degrees=((10.,5.,-5.,0.,-10.,0.),)*4,
                    log_chroma=((.1,0.,-.1,0.,.1,0.),)*4,
                    log_scale=((.05,0.,-.05,0.,.1,0.),)*4),adaptance=((5.,-3.),)*4,
                lightness_fit=fit,chroma_fit=fit))


def metrics(actual,expected):
    difference=np.max(abs(np.asarray(actual,dtype=float)-expected),axis=-1)
    peak=np.max(expected,axis=-1);limit=np.maximum(.001*peak,1e-7)
    score=difference/limit;i=int(np.argmax(score))
    return dict(maximum_tolerance_fraction=float(score[i]),worst_index=i,
                actual=actual[i].tolist(),expected=expected[i].tolist(),absolute_error=float(difference[i]),
                escaped=int(np.count_nonzero(np.any((actual<0)|(actual>1024),-1))),
                black_mismatches=int(np.count_nonzero(np.any(actual[peak==0]!=0,axis=-1))),
                finite=bool(np.isfinite(actual).all()))


def accepted(result):
    return result['finite'] and not result['escaped'] and not result['black_mismatches'] and result['maximum_tolerance_fraction']<=1


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate',required=True,type=Path)
    parser.add_argument('--output-dir',required=True,type=Path)
    parser.add_argument('--size',type=int,default=17)
    parser.add_argument('--cpu-only',action='store_true')
    args=parser.parse_args();args.output_dir.mkdir(parents=True,exist_ok=True)
    with np.load(args.candidate,allow_pickle=False) as archive:data=dict(archive)
    axis=.01*np.expm1(np.linspace(0,1,args.size)*np.log1p(1024/.01));axis[0],axis[-1]=0.,1024.
    rgb=np.stack(np.meshgrid(axis,axis,axis,indexing='ij'),-1).reshape(-1,3).astype('f4')
    # Include previously observed near-black and yellow-edge sensitivity witnesses.
    rgb=np.vstack((rgb,[[.0253184813856082,.0071734681614134,.0043407546657122],
                       [1024,1024,.0019752890009854]] )).astype('f4')
    program=None;report={'samples':len(rgb),'cases':[]};passed=True
    if not args.cpu_only:
        import bpy,gpu
        from color_tools.perceptual_grade_blender.model.bake_gpu import Program
        bpy.context.preferences.system.gpu_backend='METAL' if sys.platform=='darwin' else 'OPENGL';gpu.init()
        report['renderer']=gpu.platform.renderer_get();report['backend']=gpu.platform.backend_type_get()
    for name,settings in cases():
        oracle=LegacyCapacityModel(settings,space='ACEScg');kernel=Kernel(data,oracle.tone,oracle.color,hk_guard=True)
        start=time.perf_counter();cpu=kernel.evaluate(rgb);cpu_seconds=time.perf_counter()-start
        with exact_geometry():
            expected=rgb.astype(float) if name=='reset' else oracle.release_state(oracle.grade_state(oracle.enter_native(rgb.astype(float))),guard=True)
        item={'name':name,'cpu':metrics(cpu,expected),'cpu_seconds':cpu_seconds}
        passed=passed and accepted(item['cpu'])
        if not args.cpu_only:
            if program is None:
                program=Program(kernel);report['compile_seconds']=program.compile_seconds
            else:program.set_kernel(kernel)
            start=time.perf_counter();actual=program.evaluate(rgb)[:,:3];item['gpu_seconds']=time.perf_counter()-start
            item['gpu']=metrics(actual,expected);item['gpu_vs_cpu']=metrics(actual,cpu.astype(float))
            passed=passed and accepted(item['gpu']) and accepted(item['gpu_vs_cpu'])
        report['cases'].append(item)
        print(json.dumps(item),flush=True)
        (args.output_dir/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    report['accepted']=passed
    (args.output_dir/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    if not passed:raise SystemExit('Full-grade conformance failed')


if __name__=='__main__':main()
