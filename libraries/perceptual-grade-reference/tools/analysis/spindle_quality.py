"""D65 fitted primitive round trips, continuity, conditioning and cost."""
import argparse
import json
from pathlib import Path
from time import perf_counter
import numpy as np
from color_tools.perceptual_grade_reference.model import Model
from color_tools.perceptual_grade_reference.spindle import Context,FORMAT,white_response
from color_tools.perceptual_grade_reference.appearance import encode_cones
from color_tools.perceptual_grade_reference.responses import GAMMA,hk_energy
from color_tools.perceptual_grade_core.model import forward, linear, tone, lut
from color_tools.perceptual_grade_core.model.spindle import Context as Blender
from color_tools.color_core.modcam16 import encode_cones as blender_encode


def appearance(rgb,ctx,encoder=encode_cones):
    inv=np.linalg.inv(ctx.matrix)
    cones=rgb[...,1,None]+(rgb-rgb[...,1,None])@inv.T
    a=encoder(cones)
    return a.q,a.ja*a.ja


def distribution(x):
    return {str(p):float(np.quantile(x,p/100)) for p in (0,50,95,99,100)}


def reset(rgb,ctx,encoder=encode_cones):
    q,e=appearance(rgb,ctx,encoder)
    q,e=ctx.compress(q,e);q,e=ctx.guard(q,e);q,e=ctx.release(q,e)
    return ctx.decode(q,e)


def run(path,output):
    checked=[]
    def observe(rgb):
        rgb=np.asarray(rgb).reshape(-1,3)
        if not np.isfinite(rgb).all():raise AssertionError('Nonfinite sampled boundary output')
        checked.append((len(rgb),int(np.count_nonzero(np.any((rgb<0)|(rgb>1024),axis=-1))),float(rgb.min()),float(rgb.max())))
    m=Model();ctx=Context.load(path,m.fl,m.aw,m.native_matrix)
    model=forward.Model(tone.model(tone.Parameters(),linear.GradeSpace('D65')))
    other=Blender.load(path,model.fl,model.aw,model.native_matrix)
    output.mkdir(parents=True,exist_ok=True)
    report={'context_format':FORMAT,'scope':'Adopted uint16 primitive round trips, not the exact full-grade reset bypass. Sampled float64 diagnostics; profile certification remains. Face interpolation is bilinear, not C2 or continuously certified. Range/accuracy excursions are reported, not repaired.',
            'populations':{}}
    axes={'uniform65':np.linspace(0,1024,65),'log65':lut.axis()};tables={}
    for name,values in axes.items():
        rgb=np.stack(np.meshgrid(values,values,values,indexing='ij'),axis=-1).reshape(-1,3)
        start=perf_counter();actual=reset(rgb,ctx);seconds=perf_counter()-start
        observe(actual)
        peak=np.max(rgb,axis=-1);error=np.max(abs(actual-rgb),axis=-1)
        relative=np.divide(error,peak,out=np.zeros_like(error),where=peak>0)
        if np.any(actual[peak==0]!=0):raise AssertionError('Round trip changed exact black')
        np.testing.assert_array_equal(model.apply_native(rgb,apply_linear=False),rgb)
        parallel=reset(rgb,other,blender_encode);observe(parallel)
        parity=np.max(abs(parallel-actual),axis=-1)
        if np.any(parity>2e-12*peak):raise AssertionError(f'{name} independent parity exceeds tolerance')
        largest=int(np.argmax(relative))
        report['populations'][name]={'samples':len(rgb),'absolute_rgb_error':distribution(error),
            'relative_rgb_error':distribution(relative),'independent_rgb_error':distribution(parity),
            'former_tolerance_failures':int(np.count_nonzero(error>np.maximum(.001*peak,1e-7))),
            'output_min':actual.min(axis=0).tolist(),'output_max':actual.max(axis=0).tolist(),
            'seconds_reference_reset':seconds,'worst_relative':{'input':rgb[largest].tolist(),'output':actual[largest].tolist()}}
        tables[name]=actual
        print(f'{name}: maximum relative reset error {relative.max():.5g}; {seconds:.2f} seconds',flush=True)
    witnesses=np.array([[0.,0.,0.],[1024.]*3,[0.,1.,0.],[0.,938.63,0.],[0.,1024.,0.],
        [1024.,1024.,0.],[1000.284957530972,1024.,387.767172054212],
        [1019.786927720954,1024.,15.754414476996],[1021.870198040528,1021.366578294394,0.],
        [2.,0.,128.],[0.,1e-200,0.],[1e-100,1e-100,1e-100]])
    actual=reset(witnesses,ctx);observe(actual)
    peak=np.max(witnesses,axis=-1)
    report['witness_former_tolerance_failures']=int(np.count_nonzero(
        np.max(abs(actual-witnesses),axis=-1)>np.maximum(.001*peak,1e-7)))
    report['witnesses']=[{'input':a.tolist(),'output':b.tolist()} for a,b in zip(witnesses,actual)]
    t=np.unique(np.r_[0.,np.geomspace(1e-12,.001,12),np.linspace(.001,.999,129),1-np.geomspace(1e-12,.001,12),1.])
    angle=np.linspace(0,2*np.pi,721,endpoint=False)
    T,A=np.meshgrid(t,angle,indexing='ij');j=ctx.white*T**GAMMA
    T=(np.sqrt(j*j)/ctx.white)**(1/GAMMA);g=ctx.coefficient(T)
    unit=ctx.unit(T,A)
    k=white_response(ctx.fl)/ctx.white*unit/g;retention=1/np.min(k,axis=-1)
    report['boundary']={'samples':T.size,'round_radius_retention':distribution(retention),
                        'capacity_ratio':distribution(k),'maximum_release_slope':float(np.max(3*k-2))}
    c=white_response(ctx.fl)*T*(1-T)*unit
    low=np.full(3,np.inf);high=np.full(3,-np.inf);response=0.
    for fraction in np.linspace(0,1,17):
        radius=c*fraction
        q=np.stack((np.hypot(j,np.sqrt(66*radius)),radius*np.cos(A),radius*np.sin(A)),-1)
        rgb=ctx.decode(q,j*j);observe(rgb.reshape(-1,3))
        low=np.minimum(low,rgb.min(axis=(0,1)));high=np.maximum(high,rgb.max(axis=(0,1)))
        response=max(response,float(np.max(abs(ctx.responses(q,j*j)))))
    report['prefix']={'samples':T.size*17,'minimum_rgb':low.tolist(),'maximum_rgb':high.tolist(),'raw_response_max':response}
    if response>=400:raise AssertionError('Candidate approaches response pole')
    print('Boundary/radial ranges recorded; response-pole check passes.',flush=True)
    # Profile first-derivative disagreement at every C2 join should vanish.
    knots=ctx.knots[1:-1];r=.25*np.minimum(np.diff(ctx.knots)[:-1],np.diff(ctx.knots)[1:])
    joins=np.r_[knots-r,knots,knots+r];rows=[]
    for eps in (1e-5,1e-6,1e-7):
        center=ctx.coefficient(joins);left=ctx.coefficient(joins-eps);right=ctx.coefficient(joins+eps)
        rows.append({'step':eps,'maximum_slope_disagreement':float(np.max(abs(left+right-2*center)/eps))})
    report['profile_join_convergence']=rows
    if rows[-1]['maximum_slope_disagreement']>rows[0]['maximum_slope_disagreement']*.05:
        raise AssertionError('C2 profile joins fail derivative convergence')
    # Complete RGB entry Jacobians; reciprocal singular values give local
    # release amplification. Avoid face seams for finite-difference convergence.
    rng=np.random.default_rng(51013)
    points=rng.uniform(.01,.99,(128,3))*np.exp(rng.uniform(-12,np.log(1024),(128,1)))
    points[:64,0]=np.max(points[:64],axis=-1)*1e-4
    def entry(rgb):
        q,e=appearance(rgb,ctx);q,e=ctx.compress(q,e)
        return ctx.decode(q,e)
    jacobians=[]
    for step in (1e-6,2e-7):
        d=np.max(points,axis=-1)*step;columns=[]
        for axis in range(3):
            delta=np.zeros_like(points);delta[:,axis]=d
            columns.append((entry(points+delta)-entry(points-delta))/(2*d[:,None]))
        jacobians.append(np.stack(columns,axis=-1))
    singular=np.linalg.svd(jacobians[-1],compute_uv=False)
    report['rgb_sensitivity']={'samples':len(points),'entry_maximum_gain':distribution(singular[:,0]),
        'release_maximum_gain':distribution(1/singular[:,-1]),'condition_number':distribution(singular[:,0]/singular[:,-1]),
        'maximum_jacobian_step_change':float(np.max(abs(jacobians[0]-jacobians[1]))),
        'scope':'Interior RGB entry map; inverse Jacobian implied by bijection. Face seams and hard guard intentionally have kinks.'}
    # Coordinate requests exercise huge chroma, signed carried energy and H
    # crossings. Complete Stack regressions are tested separately.
    source=np.array([[0.,.2,0.],[2.,0.,128.],[1.,1.,1.],[1024.,1024.,0.]])
    base,_=ctx.compress(*appearance(source,ctx));requests=[]
    for gain in (2**-10,1.,2**10,1e100):
        for height in (-1.,.01,1.,2.,1e100):
            q=base.copy();q[:,0]*=height;q[:,1:]*=gain
            e=hk_energy(q[:,0],np.hypot(q[:,1],q[:,2]))
            q,e=ctx.guard(q,e);q,e=ctx.release(q,e);rgb=ctx.decode(q,e);observe(rgb)
            requests.append({'chroma_gain':gain,'H_gain':height,'rgb':rgb.tolist()})
    report['guard_requests']=requests
    rgb=np.exp(rng.uniform(np.log(1e-8),np.log(1024),(8192,3)))
    table=tables['log65'];analytic=reset(rgb,ctx)
    approx=lut.tetrahedral(table.astype('f4'),rgb);observe(approx)
    report['lut_reset']={'samples':len(rgb),'maximum_absolute_error':float(np.max(abs(approx-analytic))),
        'maximum_peak_relative_error':float(np.max(np.max(abs(approx-analytic),axis=-1)/np.max(rgb,axis=-1))),
        'scope':'Float32 fitted primitive samples and linear-RGB tetrahedra. Compositor transport and complete grades are tested separately.'}
    report['range_audit']=dict(evaluations=sum(x[0] for x in checked),
        outside_cube_evaluations=sum(x[1] for x in checked),minimum_rgb=min(x[2] for x in checked),
        maximum_rgb=max(x[3] for x in checked))
    report['checks_passed']=True
    (output/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    summary=['# D65 constant-J_A spindle candidate quality','',report['scope'],'']
    for name,data in report['populations'].items():
        summary.append(f'- {name}: {data["samples"]:,} samples; maximum relative reset error {data["relative_rgb_error"]["100"]:.6g}.')
    summary.extend([f'- Sampled round-radius retention: {retention.min():.6%}–{retention.max():.6%}.',
        f'- Maximum scalar release slope: {np.max(3*k-2):.6g}.',
        f'- Maximum sampled full-RGB release gain: {np.max(1/singular[:,-1]):.6g}.',
        f'- Raw responses after release: at most {response:.12g}, below the pole at 400.','',
        f'- Observed RGB range [{report["range_audit"]["minimum_rgb"]:.9g}, {report["range_audit"]["maximum_rgb"]:.9g}]; '+
        f'{report["range_audit"]["outside_cube_evaluations"]:,} out-of-cube evaluations (populations overlap).','',
        'Finite-output, exact-reset/black, independent parity, response-pole and profile-join checks pass. Range and former 0.1% deviations are reported separately. Scalar radial curves are C-infinity; profile joins are C2; bilinear faces are continuous with derivative kinks.'])
    (output/'summary.md').write_text('\n'.join(summary)+'\n');print('\n'.join(summary),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--context',type=Path,required=True);p.add_argument('--output-dir',type=Path,required=True)
    args=p.parse_args();run(args.context,args.output_dir)
