"""Generate the compact, certified D65 constant-J_A round spindle."""
import argparse
import json
from pathlib import Path
import numpy as np
from color_tools.perceptual_grade_reference.spindle import Context,BUDGET,white_response
from color_tools.perceptual_grade_reference.appearance import encode_cones
from color_tools.perceptual_grade_reference.model import Model
from color_tools.perceptual_grade_core.model import forward, linear, tone
from .spindle_certificate import certify_faces,certify_profile
from .boundary_oracle import capacity_unit

FORMAT=13


def models():return Model(),forward.Model(tone.model(tone.Parameters(),linear.GradeSpace('D65')))


def minimum_capacity(t,fl,aw,matrices):
    t=np.atleast_1d(t);angles=np.linspace(0,2*np.pi,720,endpoint=False)
    def capacity(x,h):
        return np.minimum.reduce([capacity_unit(x,h,fl,aw,m) for m in matrices])
    values=capacity(t[:,None],angles[None,:]);index=np.argmin(values,axis=-1)
    center=angles[index];left=center-2*np.pi/720;right=center+2*np.pi/720
    # The global sampled minimum seeds a local refinement; certificates,
    # not this optimizer, establish all-hue containment and retention.
    for _ in range(28):
        a=left+(right-left)/3;b=right-(right-left)/3
        va=capacity(t,a);vb=capacity(t,b)
        left=np.where(va>vb,a,left);right=np.where(va>vb,right,b)
    h=(left+right)/2
    return capacity(t,h),h


def generate(output):
    output.mkdir(parents=True,exist_ok=True);a,b=models()
    if (a.fl,a.aw)!=(b.fl,b.aw):raise ValueError('Independent D65 contexts disagree')
    matrices=np.array([a.native_matrix,b.native_matrix]);white=float(encode_cones(np.full(3,1024.)).ja)
    face_report=certify_faces(a.fl,matrices)
    (output/'faces.json').write_text(json.dumps(face_report,indent=2)+'\n')
    samples={}
    def minimum(positions):
        positions=np.atleast_1d(positions)
        missing=np.array(sorted(set(map(float,positions))-samples.keys()))
        if len(missing):
            radii,hues=minimum_capacity(missing,a.fl,a.aw,matrices)
            samples.update((float(t),(u,h)) for t,u,h in zip(missing,radii,hues))
        return np.array([samples[float(t)] for t in positions]).T
    knots=np.linspace(0,1,33)
    for attempt in range(12):
        values,_=minimum(knots)
        profile=.9975*white_response(a.fl)/white*values
        ctx=Context(knots,profile,white,a.fl,a.aw,a.native_matrix)
        positions=np.unique(np.concatenate([np.linspace(x,y,9) for x,y in zip(knots[:-1],knots[1:])]))
        exact,_=minimum(positions)
        ratio=ctx.coefficient(positions)/(white_response(a.fl)/white*exact)
        failed=positions[(ratio<.9965)|(ratio>.9985)]
        print(f'Profile fit: {len(knots)} knots, retention {ratio.min():.9f}..{ratio.max():.9f}',flush=True)
        if len(failed):
            ids=np.unique(np.clip(np.searchsorted(knots,failed,side='right')-1,0,len(knots)-2))
            knots=np.unique(np.r_[knots,(knots[ids]+knots[ids+1])/2])
            if len(knots)>256:raise ValueError('Round profile needs more than 256 knots')
            continue
        def witness(t):return minimum(t)[1][0]
        ok,certificate=certify_profile(ctx,matrices,witness)
        if ok:break
        (output/'unresolved.json').write_text(json.dumps(certificate,indent=2)+'\n')
        raise ValueError(f'Round profile certification unresolved: {certificate}')
    else:raise ValueError('Adaptive profile did not converge')
    payload=dict(format=FORMAT,knots=knots,profile=profile,white=white,fl=a.fl,aw=a.aw,matrices=matrices,certified=True)
    numeric=sum(np.asarray(v).nbytes for v in payload.values())
    path=output/'d65_boundary.npz';np.savez_compressed(path,**payload)
    if numeric>BUDGET or path.stat().st_size>BUDGET:raise ValueError('Aggregate D65 context exceeds 64 KiB')
    report=dict(format=FORMAT,certified=True,knots=len(knots),numeric_bytes=numeric,archive_bytes=path.stat().st_size,
                faces=face_report,profile=certificate,raw_response_upper_bound=white_response(a.fl),
                response_scope='Positive normalized native-to-cone rows put cube cones in [0,1024]; monotone base encoding bounds responses by white.')
    (output/'report.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output-dir',type=Path,required=True)
    generate(p.parse_args().output_dir)
