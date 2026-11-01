"""Build/audit the compact crease-selected D65 boundary; offline solves only."""
import argparse
import itertools
import json
from pathlib import Path
import numpy as np
from color_tools.perceptual_grade_core.model import boundary_table as spline
from color_tools.perceptual_grade_reference import spindle
from color_tools.perceptual_grade_reference.boundary_compact import CompactTable
from color_tools.perceptual_grade_core.model.creases import Selector
from color_tools.perceptual_grade_reference.model import Model
from color_tools.perceptual_grade_reference.spindle import white_response, beta, native
from color_tools.perceptual_grade_reference.responses import GAMMA, eccentricity
from .boundary_oracle import capacity_unit, intersection

EPS32 = np.finfo(np.float32).eps


def decode_unit(ctx,t,hue,unit):
    """Float64 cube-ray decode, keeping tip distances before powers round them.

    The audit measures fitted boundary error separately from conversion of
    t to J_A to carried energy and back. That round trip loses relative white
    distance at the final few float64 ulps.
    """
    rw=white_response(ctx.fl);x=t[...,None];u=unit[...,None]
    direction=beta(hue,ctx.aw);relative=1+(1-x)*u*direction
    denominator=1-rw*x/(400-rw*x)*(relative-1)
    scale=1024*(x*(400-rw)/(400-rw*x))**(50/21)
    out=scale*native((relative/denominator)**(50/21),ctx.matrix)
    active=t>.5
    if np.any(active):
        deficit=(1-x[active])*(1-x[active]*u[active]*direction[active])
        cones=-1024*np.expm1((50/21)*(np.log1p(-deficit)-np.log1p(rw/(400-rw)*deficit)))
        out[active]=1024-native(cones,ctx.matrix)
    return out


def weighted_fit(a,b,values,weights,regularization=0.):
    """Matrix-free, diagonally preconditioned least squares, offline only."""
    rhs=a.T@(weights*values)@b
    diagonal=(a*a).T@weights@(b*b)
    # Penalize relative to each basis function's support. A single global
    # penalty biased the tightly clustered edge controls toward zero.
    penalty=1e-20+regularization*diagonal
    diagonal+=penalty
    def operator(x):return a.T@(weights*(a@x@b.T))@b+penalty*x
    x=np.zeros_like(rhs);residual=rhs.copy();z=residual/diagonal;p=z.copy();dot=np.sum(residual*z)
    for _ in range(768):
        ap=operator(p);alpha=dot/np.sum(p*ap)
        x+=alpha*p;residual-=alpha*ap
        if np.max(abs(residual)/np.sqrt(diagonal))<1e-11*np.max(abs(rhs)/np.sqrt(diagonal)):break
        z=residual/diagonal;next_dot=np.sum(residual*z)
        p=z+(next_dot/dot)*p;dot=next_dot
    return x



def fit_guard(ctx):
    x=np.unique(np.r_[0.,np.geomspace(1e-10,.02,256),np.linspace(.02,1,8192)])
    _,energy=intersection(ctx,x[1:]*ctx.white)
    values=np.r_[ctx.white/(66*ctx.profile[0]),(np.sqrt(energy)/ctx.white)**(1/GAMMA)/x[1:]**2]
    radius=.25*np.minimum(np.diff(ctx.knots)[:-1],np.diff(ctx.knots)[1:])
    ts=np.unique(np.r_[ctx.knots,ctx.knots[1:-1]-radius,ctx.knots[1:-1]+radius])
    hs=np.sqrt(ts**(2*GAMMA)+(66/ctx.white)*ts*(1-ts)*ctx.coefficient(ts))
    inner=np.unique(np.r_[np.geomspace(1e-6,.02,16),hs[1:-1]])
    for _ in range(32):
        knots=np.r_[np.zeros(4),inner,np.ones(4)];a=spline.basis(knots,x)
        coefficients=np.linalg.lstsq(a/values[:,None],np.ones_like(values),rcond=None)[0]
        error=values-a@coefficients
        if np.max(abs(error/values))<5e-8 or len(inner)>=480:break
        peaks=np.flatnonzero((abs(error[1:-1]/values[1:-1])>=abs(error[:-2]/values[:-2]))&(abs(error[1:-1]/values[1:-1])>=abs(error[2:]/values[2:])))+1
        selected=peaks[np.argsort(-abs(error[peaks]/values[peaks]))[:min(12,480-len(inner))]]
        inner=np.unique(np.r_[inner,x[selected]])
    ids,w=spline.stencil(knots,x);margin=np.zeros_like(coefficients)
    for n in np.argsort(-error/values):
        weights=w[n];index=ids[n];gap=error[n]+2*np.finfo(np.float32).eps*values[n]-weights@margin[index]
        if gap>0:margin[index]+=weights*(gap/(weights@weights))
    return {'guard_knots':knots.astype(np.float32),'guard_coefficients':(coefficients+margin).astype(np.float32)}



def encode(ctx, rgb):
    inverse=np.linalg.inv(ctx.matrix)
    cone=rgb[...,1,None]+(rgb-rgb[...,1,None])@inverse.T
    p=(ctx.fl*np.maximum(cone,0))**.42
    r=400*p/(27.13+p)
    t=(2*r[...,0]+r[...,1]+.05*r[...,2])/(3.05*white_response(ctx.fl))
    a=(r[...,0]-r[...,1])+(r[...,2]-r[...,1])/11
    b=((r[...,0]-r[...,2])+(r[...,1]-r[...,2]))/9
    h=np.arctan2(b,a)
    c=1204*eccentricity(h)*np.hypot(a,b)/ctx.aw
    return t,h,c


def edge_values(ctx, v):
    """Independent cube-edge geometry, including both analytic tip limits."""
    vertices=np.array(list(itertools.product([0.,1024.],repeat=3)))
    vt,vh,vc=encode(ctx,vertices);vt[0]=0;vt[-1]=1
    edges=np.array([(lo,lo|(1<<(2-free)),free) for free in range(3)
                    for lo in range(8) if lo!=(lo|(1<<(2-free)))])
    low,high,free=edges.T
    t=vt[low,None]+(vt[high]-vt[low])[:,None]*v
    s0=np.zeros_like(t);s1=np.ones_like(t)
    for _ in range(64):
        s=(s0+s1)/2
        rgb=vertices[low,None,:]+s[...,None]*(vertices[high]-vertices[low])[:,None,:]
        current,_,_=encode(ctx,rgb);below=current<t
        s0=np.where(below,s,s0);s1=np.where(below,s1,s)
    rgb=vertices[low,None,:]+((s0+s1)/2)[...,None]*(vertices[high]-vertices[low])[:,None,:]
    _,h,c=encode(ctx,rgb)
    rw=white_response(ctx.fl);inverse=np.linalg.inv(ctx.matrix)
    with np.errstate(divide='ignore',invalid='ignore'):u=c/(rw*t*(1-t))
    for i,(lo,hi,axis) in enumerate(edges):
        for vertex,side in ((lo,0),(hi,-1)):
            if vertex not in (0,7):
                h[i,side]=vh[vertex]
                u[i,side]=vc[vertex]/(rw*vt[vertex]*(1-vt[vertex]))
                continue
            d=inverse[:,axis]**.42 if vertex==0 else -inverse[:,axis]
            aa=d[0]-d[1]+(d[2]-d[1])/11;bb=(d[0]+d[1]-2*d[2])/9
            h[i,side]=np.arctan2(bb,aa)
            weight=abs((2*d[0]+d[1]+.05*d[2])/3.05)
            u[i,side]=1204*eccentricity(h[i,side])*np.hypot(aa,bb)/(ctx.aw*weight)
    return vertices,vt,edges,t,np.unwrap(h,axis=1),u


def fit_edges(ctx):
    v=np.linspace(0,1,1025)
    vertices,vt,edges,t,h,u=edge_values(ctx,v)
    count=32
    knots=np.r_[np.zeros(4),np.linspace(0,1,count-2)[1:-1],np.ones(4)]
    a=spline.basis(knots,v);coefficients=[]
    for i in range(12):
        target=np.stack((h[i],1/u[i]),-1)
        c=np.zeros((count,2));c[0]=target[0];c[-1]=target[-1]
        c[1:-1]=np.linalg.lstsq(a[:,1:-1],target-a[:,0,None]*c[0]-a[:,-1,None]*c[-1],rcond=None)[0]
        coefficients.append(c)
    faces=[];mid=len(v)//2
    for sign in (-1,1):
        angle=h[:,mid]+sign*1e-5;tt=t[:,mid]
        cap=capacity_unit(tt,angle,ctx.fl,ctx.aw,ctx.matrix)
        j=ctx.white*tt**GAMMA;chroma=white_response(ctx.fl)*tt*(1-tt)*cap
        rgb=ctx.decode(np.stack((np.hypot(j,np.sqrt(66*chroma)),chroma*np.cos(angle),chroma*np.sin(angle)),-1),j*j)
        faces.append(np.concatenate((abs(rgb),abs(1024-rgb)),-1).argmin(-1))
    limits=[]
    for face in range(6):
        ids=np.flatnonzero(vertices[:,face%3]==(1024 if face>=3 else 0))
        limits.append((ids[np.argmin(vt[ids])],ids[np.argmax(vt[ids])]))
    coefficients=np.asarray(coefficients,dtype=np.float32)
    coefficients[...,1]*=1+128*EPS32
    return dict(edge_knots=knots.astype('f4'),edge_coefficients=coefficients,
                vertex_t=vt.astype('f4'),edges=edges[:,:2].astype('u1'),
                edge_faces=np.array(faces).T.astype('u1'),face_limits=np.array(limits).astype('u1'))


def face_ends(selector,t,face):
    values,active=selector.curves(t);row=np.arange(len(t))
    left=np.argmax(active&(selector.faces[None,:,1]==face),-1)
    right=np.argmax(active&(selector.faces[None,:,0]==face),-1)
    return values[row,left,0],values[row,right,0],values[row,left,1],values[row,right,1]


def face_samples(ctx,selector,face,x,s):
    lo,hi=selector.vertices[selector.limits[face]];t=lo+x*(hi-lo)
    hl,hr,rl,rr=face_ends(selector,t,face)
    hue=hl[:,None]+((hr-hl)%(2*np.pi))[:,None]*s
    exact=capacity_unit(t[:,None],hue,ctx.fl,ctx.aw,ctx.matrix)
    return exact,rl[:,None]*(1-s)+rr[:,None]*s


def fit_faces(ctx,data):
    selector=Selector(data);nt,ns=52,44
    sk=np.r_[np.zeros(4),(1-np.cos(np.linspace(0,np.pi,ns-2)[1:-1]))/2,np.ones(4)]
    vertices=np.array(list(itertools.product([0.,1024.],repeat=3)))
    axes=[];coefficients=[]
    for face in range(6):
        lo,hi=selector.vertices[selector.limits[face]]
        ids=np.flatnonzero(vertices[:,face%3]==(1024 if face>=3 else 0))
        splits=(np.sort(selector.vertices[ids])[1:-1]-lo)/(hi-lo)
        inner=np.r_[(1-np.cos(np.linspace(0,np.pi,nt-12)[1:-1]))/2,
                    *[v+np.array([-.005,-.0005,0,.0005,.005]) for v in splits]]
        tk=np.r_[np.zeros(4),np.sort(inner),np.ones(4)]
        x=np.unique(np.r_[(1-np.cos(np.linspace(0,np.pi,257)))/2,
             *[v+np.array([-.006,-.002,-.0007,-.0002,0,.0002,.0007,.002,.006]) for v in splits],
             np.concatenate([np.linspace(a,b,5) for a,b in zip(tk[3:-4],tk[4:-3]) if b>a])])
        x=np.clip(x,1e-7,1-1e-7);s=(1-np.cos(np.linspace(0,np.pi,257)))/2
        exact,base=face_samples(ctx,selector,face,x,s);factor=s*(1-s)
        values=np.divide(1/exact-base,factor,out=np.zeros_like(exact),where=factor>0)
        a=spline.basis(tk,x);b=spline.basis(sk,s)
        c=weighted_fit(a,b,values,(exact*factor)**2,1e-9)
        axes.append(tk);coefficients.append(c)
        print(f'Fit selected face {face}',flush=True)
    data.update(sector_t=np.array(axes).astype('f4'),sector_s=sk.astype('f4'),sectors=np.array(coefficients).astype('f4'))
    for face in range(6):
        tk=data['sector_t'][face]
        x=np.unique(np.r_[np.linspace(1e-7,1-1e-7,513),
            np.concatenate([np.linspace(a,b,5) for a,b in zip(tk[3:-4],tk[4:-3]) if b>a])])
        x=np.clip(x,1e-7,1-1e-7);s=(1-np.cos(np.linspace(0,np.pi,513)))/2
        exact,base=face_samples(ctx,selector,face,x,s);factor=s*(1-s)
        a=spline.basis(tk,x);b=spline.basis(data['sector_s'],s)
        value=base+factor*(a@data['sectors'][face]@b.T)
        need=np.maximum(0,(1+64*EPS32)/exact-value)
        ii,aa=spline.stencil(tk,np.broadcast_to(x[:,None],need.shape).ravel())
        jj,bb=spline.stencil(data['sector_s'],np.broadcast_to(s,need.shape).ravel())
        ids=(ii[:,:,None]*ns+jj[:,None,:]).reshape(-1,16)
        weights=(aa[:,:,None]*bb[:,None,:]).reshape(-1,16)*np.broadcast_to(factor,need.shape).ravel()[:,None]
        delta=np.zeros(nt*ns);need=need.ravel()
        for n in np.argsort(-need):
            if need[n]<=0:break
            ix=ids[n];w=weights[n];gap=need[n]-w@delta[ix]
            if gap>0 and w@w>1e-12:delta[ix]+=w*(gap/(w@w))
        data['sectors'][face]=(data['sectors'][face]+delta.reshape(nt,ns)).astype('f4')
        print(f'Reserve selected face {face}',flush=True)


def audit(ctx,data,table=None):
    if table is None:
        # Audit the compact splines fitted here. The runtime uint16 atlas is a
        # separately adopted approximation without this containment contract.
        table=CompactTable(data,np.float64)
    rng=np.random.default_rng(519300)
    errors=[];escaped=0;face_mismatch=0;minimum_ratio=np.inf;worst=(0.,0.,0.)
    for _ in range(10):
        t=np.r_[rng.uniform(1e-9,1-1e-9,40000),rng.uniform(.94,1,20000)]
        hue=np.r_[rng.uniform(-2*np.pi,4*np.pi,40000),rng.uniform(1.84,2,20000)]
        for vertex in data['vertex_t'][1:-1]:
            t=np.r_[t,vertex+rng.uniform(-.0005,.0005,2000)]
            hue=np.r_[hue,rng.uniform(0,2*np.pi,2000)]
        tiny=np.geomspace(1e-15,.01,500)
        t=np.r_[t,tiny,1-tiny];hue=np.r_[hue,rng.uniform(0,2*np.pi,1000)]
        exact=capacity_unit(t,hue,ctx.fl,ctx.aw,ctx.matrix)
        actual=table.capacity(t,hue).astype(float)
        expected,rgb=decode_unit(ctx,t,hue,exact),decode_unit(ctx,t,hue,actual)
        e=np.max(abs(rgb-expected),-1)/np.max(expected,-1);errors.append(e)
        escaped+=int(np.count_nonzero(np.any((rgb<0)|(rgb>1024),-1)))
        face=np.concatenate((abs(expected),abs(1024-expected)),-1).argmin(-1)
        selected=table.selector.select(t,hue)[0]
        # At tiny heights several absolute channel slacks round together.
        face_mismatch+=int(np.count_nonzero((face!=selected)&(t>1e-5)&(t<1-1e-5)))
        minimum_ratio=min(minimum_ratio,float(np.min(white_response(ctx.fl)/ctx.white*actual/ctx.coefficient(t))))
        i=e.argmax()
        if e[i]>worst[0]:worst=(float(e[i]),float(t[i]),float(hue[i]))
    x=np.unique(np.r_[np.geomspace(1e-15,.02,5000),np.linspace(.02,1,20000)])
    _,energy=intersection(ctx,x*ctx.white)
    target=(np.sqrt(energy)/ctx.white)**(1/GAMMA)/x**2
    guard_error=spline.Table(data).height_factor(x)/target-1
    errors=np.concatenate(errors)
    result=dict(numeric_bytes=sum(v.nbytes for v in data.values()),sampled_rays=len(errors),
                rgb_relative_error=np.quantile(errors,[.5,.99,.999,1]).tolist(),worst_error_t_h=worst,
                escaped_rays=escaped,face_mismatches_away_from_tips=face_mismatch,
                minimum_cube_to_spindle_ratio=minimum_ratio,
                guard_relative_error=[float(guard_error.min()),float(guard_error.max())],
                finite=bool(np.isfinite(errors).all()),certified=False)
    # Shared traces must meet continuously, without rounding the cube creases.
    precise=CompactTable(data,np.float64);selector=precise.selector
    trace=[];side_errors=0;minimum_kink=[]
    for edge,(lo,hi) in enumerate(data['edges']):
        t=selector.vertices[lo]+np.linspace(.1,.9,17)*(selector.vertices[hi]-selector.vertices[lo])
        curves,_=selector.curves(t);h=curves[:,edge,0];center=precise.capacity(t,h)
        jumps=[]
        for delta in (1e-6,1e-7,1e-8):
            left=precise.capacity(t,h-delta);right=precise.capacity(t,h+delta)
            jumps.append(float(np.max(abs(right-left)/center)))
        trace.append(jumps)
        minimum_kink.append(float(np.min(abs((right-center)-(center-left))/(1e-8*center))))
        before=selector.select(t,h-1e-6)[0];after=selector.select(t,h+1e-6)[0]
        side_errors+=int(np.count_nonzero(before!=data['edge_faces'][edge,0])+np.count_nonzero(after!=data['edge_faces'][edge,1]))
    result.update(crease_side_mismatches=side_errors,crease_relative_jumps=trace,
                  minimum_relative_crease_slope_jumps=minimum_kink)
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate',type=Path)
    parser.add_argument('--refit-guard',action='store_true',help='Reuse candidate cube fields and refit only the guard')
    parser.add_argument('--refit-faces',action='store_true',help='Reuse candidate edge/profile fields and refit face curvature')
    parser.add_argument('--output-dir',type=Path,required=True)
    args=parser.parse_args();args.output_dir.mkdir(parents=True,exist_ok=True)
    # This format-15 tool also fits and audits the historical spindle guard.
    # Model.boundary is the format-16 cube context, which has no spindle profile.
    model=Model();ctx=spindle.context(model.fl,model.aw,model.native_matrix)
    if args.candidate:
        with np.load(args.candidate,allow_pickle=False) as values:data=dict(values)
        path=args.candidate
        if args.refit_guard or args.refit_faces:
            if args.refit_guard:data.update(fit_guard(ctx))
            if args.refit_faces:fit_faces(ctx,data)
            path=args.output_dir/'d65_boundary.npz';np.savez_compressed(path,**data)
    else:
        data=fit_edges(ctx);fit_faces(ctx,data);data.update(fit_guard(ctx))
        with np.load(Path(spindle.__file__).with_name('d65_boundary.npz'),allow_pickle=False) as old:
            data.update({k:old[k] for k in ('knots','profile','white','fl','aw','matrices')})
        data.update(format=np.array(15),certified=np.array(False),profile_certified=np.array(True))
        path=args.output_dir/'d65_boundary.npz';np.savez_compressed(path,**data)
    report=audit(ctx,data);report['archive_bytes']=path.stat().st_size
    report['accepted']=(report['finite'] and report['escaped_rays']==0 and report['crease_side_mismatches']==0 and
                        report['face_mismatches_away_from_tips']==0 and
                        0<=report['guard_relative_error'][0]<=report['guard_relative_error'][1]<=1e-6 and
                        all(j[2]<j[1]*.11 and j[1]<j[0]*.11 for j in report['crease_relative_jumps']) and
                        min(report['minimum_relative_crease_slope_jumps'])>0 and
                        report['rgb_relative_error'][-1]<=.001 and report['minimum_cube_to_spindle_ratio']>=1 and
                        report['numeric_bytes']<=65536 and report['archive_bytes']<=65536)
    (args.output_dir/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    (args.output_dir/'summary.md').write_text('Boundary table sampled audit\n\n'+json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2),flush=True)
    if not report['accepted']:raise SystemExit('Candidate did not pass boundary adoption gates')


if __name__=='__main__':main()
