"""Iterative boundary oracles used only by offline generation and audits."""
import numpy as np
from contextlib import contextmanager
from color_tools.perceptual_grade_reference.spindle import MAXIMUM,beta,native,white_response
from color_tools.perceptual_grade_reference.responses import GAMMA
from color_tools.color_core.scaled import Scalar as S


@contextmanager
def exact_geometry():
    """Temporarily evaluate the full float64 model with independent geometry.

    Offline only. Restore methods even if an audit raises; the installed
    extension never imports this module or its iterative solvers.
    """
    from color_tools.perceptual_grade_reference.spindle import Context
    from color_tools.perceptual_grade_reference.cube import Context as CubeContext
    saved=Context.unit,Context.boundary,Context.guard
    cube_unit=CubeContext.unit
    try:
        Context.unit=lambda self,t,h:capacity_unit(t,h,self.fl,self.aw,self.matrix)
        Context.boundary=intersection;Context.guard=guard
        CubeContext.unit=lambda self,t,h:capacity_unit(t,h,self.fl,self.aw,self.matrix)
        yield
    finally:
        Context.unit,Context.boundary,Context.guard=saved
        CubeContext.unit=cube_unit


def ray_valid(t,unit,direction,rw,matrix,roundoff=True):
    """C=rw*t*(1-t)*unit. Analytic limits retain both vanishing tip margins."""
    t,unit=np.broadcast_arrays(np.asarray(t,dtype=float),unit)
    d=np.broadcast_to(direction,(*t.shape,3))
    shape=t.shape;t=t.ravel();unit=unit.ravel();d=d.reshape(-1,3)
    valid=np.zeros(len(t),dtype=bool)
    for top in (False,True):
        ids=np.flatnonzero((t>.5)==top)
        if not len(ids):continue
        x,u,dd=t[ids,None],unit[ids,None],d[ids]
        relative=1+(1-x)*u*dd
        domain=(relative>=0).all(-1)&(x*relative<=1+8*np.finfo(float).eps).all(-1)
        if top:
            delta=1-x;a=1-x*u*dd
            with np.errstate(divide='ignore',invalid='ignore'):
                logv=np.log1p(-delta*a)-np.log1p(rw/(400-rw)*delta*a)
                v=np.divide(-MAXIMUM*np.expm1((50/21)*logv),delta,
                            out=MAXIMUM*(50/21)*(400/(400-rw))*a,where=delta!=0)
            values=native(v,matrix)
            scale=delta[:,0]
        else:
            v=np.maximum(relative/(1-rw*x/(400-rw*x)*(relative-1)),0.)**(50/21)
            values=native(v,matrix)
            scale=MAXIMUM*(x[:,0]*(400-rw)/(400-rw*x[:,0]))**(50/21)
        margin=(32*np.finfo(float).eps*np.max(abs(v),axis=-1)[:,None]*
                np.sum(abs(matrix),axis=-1)) if roundoff else 0.
        valid[ids]=domain&np.all(values>=margin,axis=-1)&np.all(
            scale[:,None]*(values+margin)<=MAXIMUM,axis=-1)
    return valid.reshape(shape)


def capacity_unit(t,angle,fl,aw,matrix):
    """Actual cube boundary in normalized chroma; no fitted hue capacity."""
    t,angle=np.broadcast_arrays(np.asarray(t,dtype=float),angle)
    if np.any((t<0)|(t>1)):raise ValueError('Neutral response must be in [0,1]')
    d=beta(angle,aw);rw=white_response(fl)
    denom=np.where(d>0,t[...,None]*d,-(1-t[...,None])*d)
    limits=np.divide(1.,denom,out=np.full_like(d,np.inf),where=denom>0)
    hi=limits.min(axis=-1);lo=np.zeros_like(hi)
    for _ in range(64):
        mid=lo+(hi-lo)/2
        if np.all((mid==lo)|(mid==hi)):break
        good=ray_valid(t,mid,d,rw,matrix)
        lo=np.where(good,mid,lo);hi=np.where(good,hi,mid)
    if not np.isfinite(lo).all() or np.any(lo<=0):raise ValueError('Cube boundary solve failed')
    return lo


def intersection(self,h):
    """Constant-H hard-guard intersection; return its C and carried energy."""
    h=np.asarray(h,dtype=float)
    upper=(h/self.white)**(1/GAMMA)
    estimate=np.divide((h/np.sqrt(66*self.white*np.min(self.profile)))**2,1-upper,
                       out=np.full_like(h,np.inf),where=upper<1)
    upper=np.minimum(upper,estimate);lower=np.zeros_like(upper)
    for _ in range(64):
        t=lower+(upper-lower)/2
        j=self.white*t**GAMMA;b=self.white*t*(1-t)*self.coefficient(t)
        below=np.hypot(j,np.sqrt(66*b))<h
        lower=np.where(below,t,lower);upper=np.where(below,upper,t)
    j=np.minimum(h,self.white*upper**GAMMA)
    return (h-j)*(h+j)/66,j*j


def guard(self,q,energy):
    q=np.asarray(q,dtype=float);e=np.broadcast_to(np.asarray(energy,dtype=float),q.shape[:-1])
    if q.shape[-1:]!=(3,) or not np.isfinite(q).all() or not np.isfinite(e).all():
        raise ValueError('Guard requires finite triples and energy')
    out=np.zeros_like(q);eo=np.zeros_like(e)
    tip=q[...,0]>=self.white;out[...,0]=np.where(tip,self.white,0.);eo[tip]=self.white**2
    active=(q[...,0]>0)&~tip
    rows=q[active];en=e[active];h=rows[:,0];c=np.hypot(rows[:,1],rows[:,2])
    cap,eb=self.boundary(h);change=en<eb
    factor=np.divide(cap,c,out=np.ones_like(c),where=c>0)
    out[active]=np.column_stack((h,rows[:,1:]*np.where(change,factor,1.)[:,None]))
    eo[active]=np.where(change,eb,en)
    tiny=np.flatnonzero(h<1e-140)
    if len(tiny):
        values=out[active];energies=eo[active]
        for i in tiny:
            a,b=self.guard_scaled(list(map(S,rows[i])),S(en[i]))
            values[i]=list(map(float,a));energies[i]=float(b)
        out[active]=values;eo[active]=energies
    return out,eo

