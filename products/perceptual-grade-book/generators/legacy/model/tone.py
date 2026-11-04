"""Stage 2 reference/evaluation math; scene-linear working RGB in and out.

The rendering graph lives in graph/tone.py. This NumPy implementation is used
for image scopes and cross-checks, never as an image-editing/baking substitute.
"""
from dataclasses import dataclass
from functools import lru_cache
import math
import numpy as np
from . import linear as cm

GAMMA = .943019577159
LOW_Y = .037153526983
DEFAULT_HIGH_J = 183.7488220213084
PEAKS = (500, 1000, 2000, 4000)
LEVEL_NAMES = ('Black', 'Shadows', 'Midtones', 'White', 'Highlights')
LEVEL_FIELDS = tuple('input_'+name.lower() for name in LEVEL_NAMES)
LEVEL_DEFAULTS = (0., LOW_Y*203., .18*203., 203., 1000.)
LEVEL_LIMITS = ((0., 2.), (.01, 50.), (.1, 250.), (10., 1000.), (100., 10000.))
PARAM_NAMES = (*LEVEL_FIELDS, 'fit', 'reference_nits', 'peak_nits')


@dataclass(frozen=True)
class Parameters:
    input_black: float = 0.
    input_shadows: float = LOW_Y*203.
    input_midtones: float = 36.54
    input_white: float = 203.
    input_highlights: float = 1000.
    fit: int = 0
    reference_nits: int = 203
    peak_nits: int = 1000


def viewing(reference):
    la=.1*reference; k=1/(5*la+1)
    fl=.2*k**4*5*la+.1*(1-k**4)**2*(5*la)**(1/3)
    p=fl**.42
    return fl, 3.05*400*p/(27.13+p)


def response(n, fl):
    n=np.asarray(n, dtype=float)
    p=(fl*np.abs(n))**.42
    return np.sign(n)*400*p/(27.13+p)


def unresponse(s, fl):
    s=np.asarray(s, dtype=float); a=np.abs(s)
    with np.errstate(over='ignore', invalid='ignore', divide='ignore'):
        return np.sign(s)*(27.13*a/(400-a))**(1/.42)/fl


def eccentricity(c, s):
    c2=c*c-s*s; s2=2*c*s; c3=c2*c-s2*s; s3=s2*c+c2*s
    c4=c2*c2-s2*s2; s4=2*c2*s2
    return 1-.0582*c-.0258*c2-.1347*c3+.0289*c4-.1475*s-.0308*s2+.0385*s3+.0096*s4


def saturation_gain(H, JA, C, H2):
    """Scale JA and C together, preserving s=75*C/JA at fixed viewing conditions.

    Rationalized, scaled positive quadratic root. No division by JA or
    subtraction of nearly equal roots. Black uses the zero-output limit.
    """
    H,JA,C,H2=np.broadcast_arrays(H,JA,C,H2)
    divide=lambda a,b:np.divide(a,b,out=np.zeros_like(a+b,dtype=float),where=b!=0)
    r=divide(H2,H);scale=np.maximum(1,r)
    x=divide(JA,H)*(r/scale);y=divide(divide(33*C,H),H)/scale
    gain=divide(r/scale,np.hypot(x,y)+y)*r
    return np.where((H>0)&(H2>0),gain,0)


def sigmoid(x):
    x=np.asarray(x, dtype=float); e=np.exp(-np.abs(x))
    return np.where(x>=0, 1/(1+e), e/(1+e))


def softplus_delta(x, t, w):
    """Stable phi(x+t)-phi(x), t >= 0; mirrors the DCTL's analytic branches."""
    t=np.asarray(t, dtype=float); d=t/w
    small=w*np.log1p(sigmoid(x/w)*np.expm1(np.minimum(d, 1)))
    if x >= 0:
        large=t+w*np.log1p(sigmoid(-x/w)*np.expm1(-d))
    else:
        neg=w*np.log1p(np.exp(np.minimum((x+t)/w, 0))*(-np.expm1(-d))/(1+math.exp(x/w)))
        pos=x+t+w*(np.log1p(np.exp(-np.maximum((x+t)/w, 0)))-np.log1p(math.exp(x/w)))
        large=np.where(x+t<=0, neg, pos)
    return np.where(d<1, small, large)


def kernel_integral(t, left, right, w):
    t=np.asarray(t, dtype=float); delta=right-left
    if delta < .1*w:
        mid=.5*(left+right); d=.387298334621*delta
        def diff(s):
            x=-s/w; dt=t/w; a=math.exp(x); e=np.expm1(np.minimum(dt, 1))
            stable=a*e/((1+a)*(1+a*(1+e)))
            return np.where(dt<1, stable, sigmoid(x+dt)-sigmoid(x))
        return delta*(.277777777778*(diff(mid-d)+diff(mid+d))+.444444444444*diff(mid))
    low=softplus_delta(-left, t, w)-softplus_delta(-right, t, w)
    high=delta+w*(np.log1p(np.exp(-np.maximum(t-left, 0)/w))-np.log1p(np.exp(-np.maximum(t-right, 0)/w)))
    high-=w*(np.log1p(math.exp(-left/w))-np.log1p(math.exp(-right/w)))
    return np.where(t>=right, high, low)


class Model:
    def __init__(self, params, space='Linear Rec.709'):
        self.params=params; self.space=space
        self.reference=max(48, min(1000, math.floor(params.reference_nits+.5)))
        self.peak=max(2*self.reference, min(10000, math.floor(params.peak_nits+.5)))
        self.fl, self.aw=viewing(self.reference)
        self.w=np.asarray(cm.xyz(cm.white(space)))
        self.wc=np.asarray(cm.mv(cm.CAT16, self.w))
        self.rgb_to_xyz=np.asarray(cm.rgb_to_xyz(space))
        self.xyz_to_rgb=np.asarray(cm.xyz_to_rgb(space))
        self.to_cone=np.asarray(cm.CAT16)@self.rgb_to_xyz/self.wc[:,None]
        self.from_cone=self.xyz_to_rgb@np.asarray(cm.ICAT16)@np.diag(self.wc)
        self.target_nits=np.array([0, LOW_Y*self.reference, .18*self.reference, self.reference, self.peak])
        self.target=self.nits_to_j(self.target_nits)
        self.target[0]=0.; self.target[3]=1.
        self.source=self.nits_to_j([getattr(params,n) for n in LEVEL_FIELDS])
        for i in range(1,5): self.source[i]=max(self.source[i], self.source[i-1]+.001)
        self.black=float(self.source[0]); self.span=float(self.source[-1]-self.black)
        self.knots=(self.source-self.black)/self.span
        self.width=.05*2**(-params.fit)
        self.slope=float(np.min(np.diff(self.target)/np.diff(self.knots)))
        self.residual=np.maximum(0, np.diff(self.target)-self.slope*np.diff(self.knots))
        self.norm=np.array([kernel_integral(1,l,r,self.width) for l,r in zip(self.knots,self.knots[1:])])
        self.active=not (self.black==0 and np.max(np.abs(self.source-self.target))<3e-7)
        self.high_j=float(self.target[-1]*100)
        self.plot_max=float(self.nits_to_j(4000))

    def nits_to_j(self, n):
        return (3.05*response(np.maximum(n,0)/self.reference,self.fl)/self.aw)**GAMMA

    def j_to_nits(self, j):
        return unresponse(self.aw*np.maximum(j,0)**(1/GAMMA)/3.05,self.fl)*self.reference

    def remap(self, j):
        j=np.asarray(j, dtype=float)
        if not self.active: return j.copy()
        t=np.maximum(0, (j-self.black)/self.span)
        out=self.slope*t
        for l,r,n,v in zip(self.knots,self.knots[1:],self.norm,self.residual):
            out=out+v*kernel_integral(t,l,r,self.width)/n
        return np.where(t==1,self.target[-1],out)

    def cones(self, rgb):
        xyz=np.asarray(rgb,dtype=float)@self.rgb_to_xyz.T
        n=(xyz@np.asarray(cm.CAT16).T)/self.wc
        uncertainty=(np.abs(xyz)@np.abs(np.asarray(cm.CAT16)).T)/self.wc*4e-7
        return np.where(np.abs(n)<=uncertainty,0,n)

    def attributes(self, n):
        n=np.asarray(n,dtype=float); s=response(n,self.fl)
        a=(s[...,0]-s[...,1])+(s[...,2]-s[...,1])/11
        b=((s[...,0]-s[...,2])+(s[...,1]-s[...,2]))/9
        ach=2*s[...,0]+s[...,1]+.05*s[...,2]
        ja=100*(np.maximum(ach,0)/self.aw)**GAMMA
        radius=np.hypot(a,b)
        ch=np.divide(a,radius,out=np.zeros_like(a),where=radius>0)
        sh=np.divide(b,radius,out=np.zeros_like(b),where=radius>0)
        C=1204*eccentricity(ch,sh)*radius/self.aw
        j=np.sqrt(ja*ja+66*C)
        q=np.stack([j,C*ch,C*sh],axis=-1)
        valid=np.isfinite(q).all(axis=-1)&((ach>0)|np.all(s==0,axis=-1))
        return q,valid,ach,a,b

    def appearance(self, rgb):
        q,valid,*_=self.attributes(self.cones(rgb))
        return np.where(valid[...,None],q,np.nan)

    def core(self,n):
        q,valid,ach,a,b=self.attributes(n)
        j2=100*self.remap(q[...,0]/100)
        ja=100*(np.maximum(ach,0)/self.aw)**GAMMA
        C=np.hypot(q[...,1],q[...,2])
        gain=saturation_gain(q[...,0],ja,C,j2)
        ach2=ach*gain**(1/GAMMA); aa=a*gain; bb=b*gain
        s=np.stack([(460*ach2+451*aa+288*bb)/1403,
                    (460*ach2-891*aa-261*bb)/1403,
                    (460*ach2-220*aa-6300*bb)/1403],axis=-1)
        valid &= np.max(np.abs(s),axis=-1)<399.998
        out=unresponse(np.clip(s,-399.998,399.998),self.fl)
        # Domain/finite checks only. No encode/decode residual threshold.
        valid &= (j2>=0)&np.isfinite(j2)&np.isfinite(out).all(axis=-1)
        return out,valid

    def apply(self,rgb):
        rgb=np.asarray(rgb,dtype=float)
        if not self.active: return rgb.copy()
        n=self.cones(rgb); lift=np.maximum(0,-np.min(n,axis=-1))
        lifted=n+lift[...,None]
        lifted=np.where(np.abs(lifted)<=4e-7*(np.abs(n)+lift[...,None]),0,lifted)
        out,valid=self.core(lifted)
        offset,offset_valid=self.core(np.broadcast_to(lift[...,None],n.shape))
        valid &= offset_valid | (lift==0)
        result=(out-offset)@self.from_cone.T
        valid &= np.isfinite(result).all(axis=-1)
        return np.where(valid[...,None],result,rgb)


@lru_cache(maxsize=64)
def model(params,space='Linear Rec.709'):
    return Model(params,space)


def clamp_landmark(params,index,value,space='Linear Rec.709'):
    """Clamp the edited source landmark, never push a neighboring control."""
    m=model(params,space); lo,hi=LEVEL_LIMITS[index]
    j=float(m.nits_to_j(max(lo,min(hi,value))))
    low=float(m.nits_to_j(lo)); high=float(m.nits_to_j(hi))
    if index: low=max(low,float(m.nits_to_j(getattr(params,LEVEL_FIELDS[index-1])))+.001)
    if index<4: high=min(high,float(m.nits_to_j(getattr(params,LEVEL_FIELDS[index+1])))-.001)
    return float(m.j_to_nits(max(low,min(high,j))))
