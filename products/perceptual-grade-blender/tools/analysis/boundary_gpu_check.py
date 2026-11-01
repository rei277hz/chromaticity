"""Execute the boundary GLSL on Blender's actual compute backend."""
import argparse
import json
from pathlib import Path
import sys
import bpy
import gpu
import numpy as np
from color_tools.perceptual_grade_blender.model.boundary_gpu import Program, header
from color_tools.perceptual_grade_core.model.boundary_polynomial import PolynomialTable
from color_tools.perceptual_grade_reference.responses import GAMMA


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate',type=Path,required=True)
    parser.add_argument('--output-dir',type=Path,required=True)
    args=parser.parse_args();args.output_dir.mkdir(parents=True,exist_ok=True)
    with np.load(args.candidate,allow_pickle=False) as archive:data=dict(archive)
    bpy.context.preferences.system.gpu_backend='METAL' if sys.platform=='darwin' else 'OPENGL';gpu.init()
    program=Program(data);cpu=PolynomialTable(data);rng=np.random.default_rng(5194)
    codes=cpu.expanded['face_codes']
    recovered=np.rint(np.array(program.face_atlas.read(),dtype='f4')*np.float32(65535)).astype('u2').reshape(codes.shape)
    tau=np.float32(2*np.pi);seams=np.arange(-12,13,dtype='f4')*tau
    bits=rng.integers(0,2**32,16384,dtype='u4').view('f4')
    general=np.r_[bits[np.isfinite(bits)],seams,np.nextafter(seams,np.float32(-np.inf)),
        np.nextafter(seams,np.float32(np.inf)),np.array([0.,-0.],dtype='f4')]
    t=np.r_[rng.uniform(0,1,50000),np.zeros(128),np.ones(128),rng.uniform(0,1,len(general))]
    hue=np.r_[rng.uniform(-2*np.pi,4*np.pi,50256),general];height=rng.uniform(0,float(data['white']),len(t))
    points=np.column_stack((t,hue,height)).astype('f4');t,hue,height=points.T
    actual=program.evaluate(points);expected=cpu.capacity(t,hue)
    cg,eg=cpu.intersection(height,float(np.float32(data['white'])),float(np.float32(GAMMA)))
    relative=abs(actual[:,0]/expected-1)
    def wrap_source(data,offsets,expanded):
        return header(data,offsets,expanded)+'''\nvoid main() {
            int id=int(gl_GlobalInvocationID.x);if(id>=sample_count)return;
            ivec2 address=ivec2(id%256,id/256);
            imageStore(output_pixels,address,vec4(pg_mod(texelFetch(input_pixels,address,0).x)));
        }'''
    wrap_program=Program(data,wrap_source,expanded=cpu.expanded)
    wrapped=wrap_program.evaluate(hue.astype('f4')[:,None])[:,0]
    wrap_expected=np.remainder(hue.astype('f4'),tau)
    report=dict(renderer=gpu.platform.renderer_get(),backend=gpu.platform.backend_type_get(),
                compile_seconds=program.compile_seconds,samples=len(t),runtime_lookup_bytes=program.lookup_bytes,
                face_codes=len(codes.ravel()),storage_code_mismatches=int(np.count_nonzero(codes!=recovered)),
                maximum_capacity_relative_error=float(relative.max()),
                wrap_samples=len(hue),wrap_mismatches=int(np.count_nonzero(wrapped!=wrap_expected)),
                maximum_wrap_error=float(np.max(abs(wrapped-wrap_expected))),
                face_mismatches=int(np.count_nonzero(actual[:,1]!=cpu.selector.select(t,hue)[0])),
                guard_chroma_error_over_height_squared=float(np.max(abs(actual[:,2]-cg)/np.maximum(height*height/66,np.finfo('f4').tiny))),
                guard_energy_error_over_height_squared=float(np.max(abs(actual[:,3]-eg)/np.maximum(height*height,np.finfo('f4').tiny))),
                finite=bool(np.isfinite(actual).all()))
    (args.output_dir/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2),flush=True)
    if (not report['finite'] or report['storage_code_mismatches'] or report['wrap_mismatches']
            or report['maximum_capacity_relative_error']>1e-4 or report['face_mismatches']
            or report['guard_chroma_error_over_height_squared']>2e-6
            or report['guard_energy_error_over_height_squared']>2e-6):
        raise SystemExit('GPU boundary conformance failed')


if __name__=='__main__':main()
