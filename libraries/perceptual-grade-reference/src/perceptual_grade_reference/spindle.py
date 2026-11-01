"""Constant-J_A cube rays and the production cubic radial mapping pair."""
from dataclasses import dataclass
from functools import lru_cache, cached_property
from pathlib import Path
import numpy as np
from .responses import GAMMA, INVERSE, eccentricity
from .boundary_curves import rounded_weights, depressed_root
from ..color_core.scaled import Scalar as S, norm, dot
from ..perceptual_grade_core.model.boundary_cache import Boundary
from ..perceptual_grade_core.model.boundary_resource import LEGACY_FORMAT as FORMAT,BUDGET,load_data
from types import MappingProxyType

MAXIMUM = 1024.


def white_response(fl):
    p=np.power(np.float64(fl)*MAXIMUM,.42)
    return float(400*p/(27.13+p))


def _release_radius(x, k):
    """Unclipped C_cube/B = x + (k-1)x³, with x = C_spindle/B."""
    x,k=np.broadcast_arrays(np.asarray(x,dtype=float),np.asarray(k,dtype=float))
    return x*(1+(k-1)*x*x)


def _compress_radius(y, k):
    """Closed hyperbolic inverse of the production cubic; no iteration."""
    y,k=np.broadcast_arrays(np.asarray(y,dtype=float),np.asarray(k,dtype=float))
    out=y.copy()
    # The inverse gain is one to float64 precision for subnormal y. Avoid
    # subnormal rounding inside sinh(asinh(t)/3), retaining the input exactly.
    active=(k>1)&(y>=np.finfo(float).tiny)
    out[active]=depressed_root(1.,k[active]-1,y[active])
    return out


def radius_map(value, boundary, ratio, release=False):
    """Map the physical radius with exact endpoints and a closed-form pair."""
    v,b,k=np.broadcast_arrays(np.asarray(value,dtype=float),boundary,ratio)
    if np.any(v<0) or np.any(b<0) or np.any(k<1):raise ValueError('Invalid radial domain')
    endpoint=b if release else b*k
    x=np.divide(np.minimum(v,endpoint),b,out=np.zeros_like(v),where=b>0)
    y=_release_radius(x,k) if release else _compress_radius(x,k)
    physical=b*(k if release else 1.)
    mapped=np.minimum(physical,np.maximum(0.,b*y))
    return np.where(v>=endpoint,physical,mapped)


def beta(angle,aw):
    h=np.asarray(angle,dtype=float)
    return (aw/(1204*eccentricity(h)))[...,None]*(
        np.cos(h)[...,None]*INVERSE[:,1]+np.sin(h)[...,None]*INVERSE[:,2])


def native(values,matrix):
    return values[...,1,None]+(values-values[...,1,None])@matrix.T


def capacity_unit(t,angle,fl,aw,matrix):
    return context(fl,aw,matrix).unit(t,angle)


@dataclass(frozen=True)
class Context:
    knots: np.ndarray
    profile: np.ndarray
    white: float
    fl: float
    aw: float
    matrix: np.ndarray
    cache: dict | None = None

    @cached_property
    def lookup(self):
        from ..perceptual_grade_core.model.boundary_table import Table
        if self.cache is None:raise ValueError('Missing boundary resource')
        return Table(self.cache)

    def coefficient(self,t):
        ids,w=rounded_weights(self.knots,np.asarray(t,dtype=float))
        return np.sum(self.profile[ids]*w,axis=-1)

    def body(self,ja):
        t=(np.asarray(ja,dtype=float)/self.white)**(1/GAMMA)
        return self.white*t*(1-t)*self.coefficient(t)

    def unit(self,t,angle):return Boundary(self).capacity(t,angle)

    def capacity(self,ja,angle):
        t=(np.asarray(ja,dtype=float)/self.white)**(1/GAMMA)
        return white_response(self.fl)*t*(1-t)*self.unit(t,angle)

    def boundary(self,h):return Boundary(self).intersection(h)

    def guard(self,q,energy):
        q=np.asarray(q,dtype=float);e=np.broadcast_to(np.asarray(energy,dtype=float),q.shape[:-1])
        if q.shape[-1:]!=(3,) or not np.isfinite(q).all() or not np.isfinite(e).all():
            raise ValueError('Guard requires finite triples and energy')
        out=q.copy();eo=np.array(e,copy=True);h=q[...,0]
        black=h<=0;tip=h>=self.white
        out[black]=0.;eo[black]=0.;out[tip]=[self.white,0.,0.];eo[tip]=self.white**2
        active=~black&~tip
        if np.any(active):
            cap,eb=self.boundary(h[active]);c=np.hypot(q[active,1],q[active,2])
            change=e[active]<eb
            factor=np.divide(cap,c,out=np.ones_like(c),where=c>0)
            out[active,1:]=q[active,1:]*np.where(change,factor,1.)[:,None]
            eo[active]=np.where(change,eb,e[active])
            rows=q[active];values=out[active];energies=eo[active]
            for i in np.flatnonzero(h[active]<1e-140):
                a,b=self.guard_scaled(list(map(S,rows[i])),S(e[active][i]))
                values[i]=list(map(float,a));energies[i]=float(b)
            out[active]=values;eo[active]=energies
        return out,eo

    def finite(self,q,energy,release=False):
        q=np.asarray(q,dtype=float);e=np.broadcast_to(np.asarray(energy,dtype=float),q.shape[:-1])
        if q.shape[-1:]!=(3,) or not np.isfinite(q).all() or not np.isfinite(e).all() or np.any(e<0):
            raise ValueError('Finite mapping requires finite coordinates and nonnegative energy')
        j=np.sqrt(e)
        if np.any(j>self.white):raise ValueError('J_A is above cube white')
        out=q.copy();c=np.hypot(q[...,1],q[...,2]);active=(j>0)&(j<self.white)&(c>0)
        t=(j[active]/self.white)**(1/GAMMA)
        h=np.arctan2(q[active,2],q[active,1])
        coefficient=self.coefficient(t);b=self.white*t*(1-t)*coefficient
        k=(white_response(self.fl)/self.white)*self.unit(t,h)/coefficient
        if np.any(k<1-1e-12):raise ValueError('Spindle exceeds cube capacity')
        target=radius_map(c[active],b,np.maximum(k,1.),release)
        out[active,1:]=q[active,1:]*(target/c[active])[:,None]
        out[...,0]=np.hypot(j,np.sqrt(66*np.hypot(out[...,1],out[...,2])))
        ends=(j==0)|(j==self.white)
        out[ends,1:]=0.;out[ends,0]=j[ends]
        return out,np.array(e,copy=True)

    def compress(self,q,e):return self.finite(q,e)
    def release(self,q,e):return self.finite(q,e,True)

    def _scaled_body(self,t):return self.white*t*(1-t)*float(self.coefficient(float(t)))

    def guard_scaled(self,q,e):
        h=q[0];c=norm(q[1:])
        if h<=0:return [S(),S(),S()],S()
        if h>=self.white:return [S(self.white),S(),S()],S(self.white)**2
        cap,eb=Boundary(self).intersection_scaled(h)
        if e>=eb:return q,e
        factor=cap/c if c else S(1)
        return [h,q[1]*factor,q[2]*factor],eb

    def finite_scaled(self,q,e,release=False):
        if e<0:raise ValueError('Finite mapping requires nonnegative energy')
        j=e**.5;c=norm(q[1:])
        if j>self.white:raise ValueError('J_A is above cube white')
        if not j or j==self.white:return [j,S(),S()],e
        if not c:return [j,S(),S()],e
        t=(j/self.white)**(1/GAMMA);g=float(self.coefficient(float(t)));b=self._scaled_body(t)
        angle=np.arctan2(float(q[2]/c),float(q[1]/c))
        k=float(white_response(self.fl)/self.white*self.unit(float(t),angle)/g)
        if k<1-1e-12:raise ValueError('Spindle exceeds cube capacity')
        normalized=float(min(c/b,S(1 if release else k)))
        # Subnormal normalized radii have unit gain to far better than
        # mantissa precision. Keep Scaled chroma before the float conversion
        # loses significant bits, including values below the float range.
        target=c if normalized<np.finfo(float).tiny else b*float(radius_map(normalized,1.,max(k,1.),release))
        return [norm([j,(66*target)**.5]),q[1]*(target/c),q[2]*(target/c)],e

    def responses(self,q,energy):
        q=np.asarray(q);energy=np.asarray(energy)
        if np.any(energy<0):raise ValueError('Decode requires nonnegative energy')
        h=np.arctan2(q[...,2],q[...,1])
        ab=q[...,1:]*(self.aw/(1204*eccentricity(h)))[...,None]
        r=white_response(self.fl)*(np.sqrt(energy)/self.white)**(1/GAMMA)
        return r[...,None]+ab@INVERSE[:,1:].T

    def cones(self,q,energy):
        r=self.responses(q,energy);rw=white_response(self.fl)
        if not np.isfinite(r).all() or np.any(abs(r)>=400):raise ValueError('Response pole reached before decode')
        return np.sign(r)*MAXIMUM*(abs(r)*(400-rw)/(rw*(400-abs(r))))**(50/21)

    def decode(self,q,energy):
        q=np.asarray(q);e=np.broadcast_to(energy,q.shape[:-1]);out=native(self.cones(q,e),self.matrix)
        t=(np.sqrt(e)/self.white)**(1/GAMMA);active=t>.5
        if np.any(active):
            rows=q[active];h=np.arctan2(rows[:,2],rows[:,1]);rw=white_response(self.fl)
            ab=rows[:,1:]*(self.aw/(1204*eccentricity(h)))[:,None]
            deficit=(1-t[active,None])-(ab@INVERSE[:,1:].T)/rw
            # Algebraically identical inverse response, evaluated from white
            # so an ulp in an absolute cone cannot cross the upper cube face.
            positive=np.all(deficit<=1,axis=-1)
            d=deficit[positive]
            cones=-MAXIMUM*np.expm1((50/21)*(np.log1p(-d)-np.log1p(rw/(400-rw)*d)))
            values=out[active];values[positive]=MAXIMUM-native(cones,self.matrix);out[active]=values
        return out

    def decode_scaled(self,q,energy):
        if energy<0:raise ValueError('Decode requires nonnegative energy')
        c=norm(q[1:]);h=np.arctan2(float(q[2]/c),float(q[1]/c)) if c else 0.
        rw=white_response(self.fl);t=(energy**.5/self.white)**(1/GAMMA);r=rw*t
        ab=[v*float(self.aw/(1204*eccentricity(h))) for v in q[1:]]
        raw=[r+dot(row,ab) for row in INVERSE[:,1:]]
        if any(abs(v)>=400 for v in raw):raise ValueError('Response pole reached before decode')
        if t>.5 and all(v>=0 for v in raw):
            d=np.array([float((1-t)-dot(row,ab)/rw) for row in INVERSE[:,1:]])
            deficits=-MAXIMUM*np.expm1((50/21)*(np.log1p(-d)-np.log1p(rw/(400-rw)*d)))
            return [S(MAXIMUM)-S(deficits[1])-dot(row,[S(v)-deficits[1] for v in deficits]) for row in self.matrix]
        cones=[(1 if v>=0 else -1)*MAXIMUM*(abs(v)*(400-rw)/(rw*(400-abs(v))))**(50/21) for v in raw]
        return [cones[1]+dot(row,[v-cones[1] for v in cones]) for row in self.matrix]

    @classmethod
    def load(cls,path,fl,aw,matrix):
        with np.load(path,allow_pickle=False) as d:
            if int(d['format'])!=FORMAT:
                raise ValueError(f'Spindle cache format {int(d["format"])}; expected {FORMAT}')
            if 'profile_certified' not in d or not bool(d['profile_certified']):raise ValueError('Uncertified spindle profile')
            if sum(v.nbytes for v in d.values())>BUDGET or Path(path).stat().st_size>BUDGET:
                raise ValueError('Aggregate spindle cache exceeds 64 KiB')
            slack=64*np.finfo(np.float64).eps
            expected=np.array([float(d['fl']),float(d['aw'])]);actual=np.array([fl,aw],dtype=np.float64)
            matches=np.isfinite(actual)&np.isfinite(expected)&(abs(actual-expected)<=slack*(1+abs(expected)))
            if not matches.all():
                i=int(np.flatnonzero(~matches)[0]);name=('fl','aw')[i]
                raise ValueError(f'D65 cache metadata mismatch for {name}: {actual[i]!r}; cached {expected[i]!r}')
            candidate=np.asarray(matrix,dtype=np.float64);matrices=d['matrices']
            if candidate.shape!=(3,3) or matrices.shape!=(2,3,3) or not np.isfinite(candidate).all() or not np.isfinite(matrices).all():
                raise ValueError('D65 cache matrix metadata requires finite 3 by 3 adapters')
            errors=np.max(np.abs(matrices-candidate)/(1+np.abs(matrices)),axis=(1,2))
            selected=int(np.argmin(errors))
            if errors[selected]>slack:
                raise ValueError(f'D65 cache matrix metadata mismatch: scaled error {errors[selected]:.17g}; limit {slack:.17g}')
            result=cls(d['knots'].copy(),d['profile'].copy(),float(d['white']),
                       float(expected[0]),float(expected[1]),matrices[selected].copy(),MappingProxyType(load_data(d)))
        for v in vars(result).values():
            if isinstance(v,np.ndarray):v.flags.writeable=False
        for v in result.cache.values():v.flags.writeable=False
        return result


@lru_cache(maxsize=2)
def _context(fl,aw,matrix):
    return Context.load(Path(__file__).with_name('d65_boundary.npz'),fl,aw,np.asarray(matrix).reshape(3,3))


def context(fl,aw,matrix):return _context(float(fl),float(aw),tuple(np.asarray(matrix).ravel()))
