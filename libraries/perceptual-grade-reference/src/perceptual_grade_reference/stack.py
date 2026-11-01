"""Independent cube-constrained nonlinear inverse and mixed Stack oracle.

NumPy least-squares search deliberately does not share the portable inverse's
reduced three-variable solve or Broyden machinery. Only the immutable D65 context is shared.
"""
from itertools import product
import numpy as np
from .model import Model,CAT16,rgb_matrix,adaptation,xyz_from_xy,WHITES
from .responses import State
from .export import input_repair
from ..color_core.scaled import Scalar as S

TOLERANCE=2e-10
TO_NATIVE=np.linalg.inv(rgb_matrix('ACEScg'))@adaptation(xyz_from_xy(WHITES['D65']),xyz_from_xy(WHITES['ACES']),'Bradford')@rgb_matrix('Linear Rec.709')
FROM_NATIVE=np.linalg.inv(TO_NATIVE)


def matrix_native(model):
    return (model.boundary.matrix@(CAT16/model.white_cones[:,None])@model.linear
            @model.cones_to_xyz@np.linalg.inv(model.boundary.matrix))


def nonlinear_inverse(model,target,appearance=False):
    """Private oracle returns values/residuals for development comparison only."""
    shape=target.q.shape if appearance else np.asarray(target).shape
    # The raw appearance prior is only a cube projection, not a forward grade.
    if appearance:target=State(target.q.reshape(-1,3),target.energy.reshape(-1))
    else:target=input_repair(np.asarray(target).reshape(-1,3),model.acescg_y)
    prior=model.release_state(target,guard=True) if appearance else target.copy()
    def attributes(state):return np.concatenate((state.q[...,:1],state.ja[...,None],state.q[...,1:]),-1)
    wanted=attributes(target) if appearance else target@FROM_NATIVE.T
    scale=1+abs(wanted) if appearance else 1+np.max(abs(wanted),axis=-1)[:,None]
    if wanted.dtype==object:scale=np.asarray([S(1)+abs(S(v)) for v in wanted.flat],dtype=object).reshape(wanted.shape)
    def residual(x,rows):
        actual=model.grade_state(model.enter_native(x))
        value=attributes(actual) if appearance else model.release_state(actual,guard=True)@FROM_NATIVE.T
        delta=value-wanted[rows];divisor=scale[rows]
        if delta.dtype==object:
            return np.asarray([float(S(a)/S(b)) for a,b in zip(delta.flat,np.broadcast_to(divisor,delta.shape).flat)]).reshape(delta.shape)
        return delta/divisor
    out=np.empty_like(prior);errors=np.empty(len(prior))
    if not (model.tone.active or model.color.active):
        return prior.reshape(shape),np.max(abs(residual(prior,np.arange(len(prior)))),axis=-1).reshape(shape[:-1])
    for row,p in enumerate(prior):
        amplitude=max(1.,np.max(abs(p)))
        seeds=[p,np.zeros(3),np.full(3,p@model.acescg_y)]
        seeds.extend(p*f for f in (.25,.5,2.,4.))
        seeds.extend(p+amplitude*np.asarray(v) for v in product((-1.,0.,1.),repeat=3))
        x=np.unique(np.clip(seeds,0,1024),axis=0);z=np.arcsinh(x/.01)
        owners=np.full(len(z),row);r=residual(x,owners);damping=np.full(len(z),.001)
        for _ in range(128):
            active=np.flatnonzero((np.max(abs(r),axis=-1)>TOLERANCE/10)&(damping<1e12))
            if not len(active):break
            v=z[active];h=np.cbrt(np.finfo(float).eps)*(1+abs(v))
            jac=[]
            for axis in range(3):
                low=v.copy();high=v.copy();low[:,axis]=np.maximum(0,v[:,axis]-h[:,axis])
                high[:,axis]=np.minimum(np.arcsinh(1024/.01),v[:,axis]+h[:,axis])
                jac.append((residual(.01*np.sinh(high),owners[active])-residual(.01*np.sinh(low),owners[active]))/(high[:,axis]-low[:,axis])[:,None])
            jac=np.stack(jac,axis=-1);step=np.empty_like(v)
            for i,index in enumerate(active):
                a=np.vstack((jac[i],np.sqrt(damping[index])*np.eye(3)))
                step[i]=np.linalg.lstsq(a,np.r_[r[index],np.zeros(3)],rcond=None)[0]
            candidate=np.clip(v-step,0,np.arcsinh(1024/.01));rr=residual(.01*np.sinh(candidate),owners[active])
            better=np.sum(rr*rr,axis=-1)<np.sum(r[active]*r[active],axis=-1)
            ids=active[better];z[ids]=candidate[better];r[ids]=rr[better]
            damping[active]=np.clip(damping[active]*np.where(better,1/3,10),1e-12,1e12)
        x=np.clip(.01*np.sinh(z),0,1024);err=np.max(abs(residual(x,owners)),axis=-1)
        canonical=x@FROM_NATIVE.T;distance=np.sum((np.arcsinh(canonical)-np.arcsinh(p@FROM_NATIVE.T))**2,axis=-1)
        roots=err<=TOLERANCE;ids=np.flatnonzero(roots) if roots.any() else np.arange(len(err))
        index=min(ids,key=lambda i:(*(() if roots.any() else (err[i],)),distance[i],*canonical[i]))
        out[row]=x[index];errors[row]=err[index]
    return out.reshape(shape),errors.reshape(shape[:-1])


class Stack:
    def __init__(self,settings,directions=None,*,hk_guard=True):
        self.models=tuple(Model(s,hk_guard=hk_guard) for s in settings)
        self.directions=tuple(directions) if directions is not None else ('FORWARD',)*len(self.models)
        if len(self.models)!=len(self.directions) or any(d not in ('FORWARD','INVERSE') for d in self.directions):raise ValueError('Invalid Stack directions')
        self.inverses=[]
        for model,direction in zip(self.models,self.directions):
            if direction=='INVERSE' and np.linalg.matrix_rank(np.asarray(model.linear,dtype=float))<3:raise ValueError('Inverse Stage 1 matrix is singular')
            try:inverse=np.linalg.inv(matrix_native(model)) if direction=='INVERSE' else None
            except np.linalg.LinAlgError as exc:raise ValueError('Inverse Stage 1 matrix is singular') from exc
            self.inverses.append(inverse)

    def apply_native(self,values):
        result=np.asarray(values,dtype=float);pending=None;cancelled=False
        for i,(m,direction) in enumerate(zip(self.models,self.directions)):
            if direction=='FORWARD':
                before=m.cones_to_xyz@np.linalg.inv(m.boundary.matrix)
                result=m.input_native(result,before,True)
                following=i+1<len(self.models) and self.directions[i+1]=='INVERSE'
                n=self.models[i+1] if following else None
                cancelled=following and m.settings.tone==n.settings.tone and m.settings.color==n.settings.color
                pending=result if cancelled else m.grade_state(m.enter_native(result))
                if not following:result=m.release_state(pending,guard=True);pending=None
            else:
                if pending is None:result=nonlinear_inverse(m,input_repair(result,m.acescg_y))[0]
                elif cancelled:result=pending
                else:result=nonlinear_inverse(m,pending,True)[0]
                result=result@self.inverses[i].T;pending=None;cancelled=False
        return input_repair(result,rgb_matrix('ACEScg')[1]) if not self.models else result

    def apply(self,values):
        native=np.asarray(values)@TO_NATIVE.T
        return self.apply_native(native)@FROM_NATIVE.T
