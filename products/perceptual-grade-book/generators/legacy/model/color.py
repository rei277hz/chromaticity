"""Stage 3 controls and reference math, shared by native uniforms and scopes.

Coefficients act on Stage 2 attributes. Selection and scope statistics never
enter this model. The inverse shares the H-K repair between a bounded H lift
and chroma reduction, preserving hue and carrying achromatic energy directly.
Remaining inverse-domain failures use the paired fallback.
"""
from ..localization.i18n import M
from ..localization.controls import control_label
from dataclasses import make_dataclass
from functools import lru_cache
import math
import numpy as np
from . import tone as tm

TONES=('Shadows','Midtones','White','Highlights')
IDS='SMWH'
# name, UI label, default, minimum, maximum, precision, DCTL identifier
CONTROLS=[]
def add(name,default,lo,hi,precision,dctl):
    CONTROLS.append((name,M(control_label(name)),default,lo,hi,precision,dctl))
for axis in 'ab':
    for i,(tone,tid,limit) in enumerate(zip(TONES,IDS,(100,)*4)):
        add(f'adaptance_{axis}_{i}',0.,-limit,limit,1,f'tone{tid}Adaptance{axis.upper()}')
add('adaptance_strength',.5,0,1,2,'adaptanceStrength')
add('adaptance_fit',0,-2,6,0,'adaptanceFit')
LIMITS_J={'low':(30,50,100,200),'high':(100,200,400,700),'a':(20,20,30,50),'b':(20,20,30,50)}
LIMITS_C={'low':(4,)*4,'high':(16,)*4,'a':(4,2,1,1),'b':(4,2,1,1)}
DRIVERS=(('low','Cₗ','Low'),('high','Cₕ','High'),('a','a','a'),('b','b','b'))
for family,target,limits,fit in [('j','J',LIMITS_J,'lightnessFit'),('c','C',LIMITS_C,'chromaFit')]:
    for driver,label,dctl in DRIVERS:
        for i,(tone,tid,limit) in enumerate(zip(TONES,IDS,limits[driver])):
            add(f'{family}_{driver}_{i}',0.,-limit,limit,1 if family=='j' else 2,f'tone{tid}{dctl}To{target}')
    add(f'{family}_fit',0,-2,6,0,fit)
for i,(tone,tid) in enumerate(zip(TONES,IDS)):
    add(f'hue_{i}',0.,-90,90,1,f'tone{tid}Hue')
for i,(tone,tid) in enumerate(zip(TONES,IDS)):
    for axis in 'ab':
        add(f'concentration_{axis}_{i}',0.,-1,1,2,f'tone{tid}Concentration{axis.upper()}')
add('hue_fit',0,-2,6,0,'hueFit')
add('global_gain',0.,-3,3,2,'globalChromaGain')
add('global_low_hue',0.,-90,90,1,'globalLowChromaHue')
add('global_high_hue',0.,-360,360,1,'globalHighChromaHue')
META={c[0]:c for c in CONTROLS}
PARAM_NAMES=tuple(META)
Parameters=make_dataclass('Parameters',[(c[0],int if c[5]==0 else float,c[2]) for c in CONTROLS],frozen=True)
Parameters.__module__=__name__
ADJUST_NAMES=tuple(n for n in PARAM_NAMES if 'fit' not in n and n!='adaptance_strength')

# Global engineering constant, never a user parameter or fitted per image.
# The decoder carries repaired J_A^2 directly, avoiding cancellation in H^2-66C.
HK_KNEE=1.0
HK_H_LIFT=.20
HK_ENERGY_POWER=.25
ADAPTANCE_C0=30.
ADAPTANCE_RHO=.25
CHROMA_SATURATION=35.
CHROMA_NEUTRAL=2.
SATURATION_SCALE=75.


def chroma_drivers(C,JA):
    """Complementary p=2 weights on modCAM16 saturation, with neutral fade.

    s=75*C/JA; the classifier midpoint is s=35. Carry JA from the
    encoder/Tone stage: reconstructing it from H²-66C loses dark precision.
    Ratios are scaled before squaring, including the exact black limit.
    """
    C,JA=np.broadcast_arrays(np.asarray(C,dtype=float),np.asarray(JA,dtype=float))
    a=np.maximum(C,0);b=(CHROMA_SATURATION/SATURATION_SCALE)*np.maximum(JA,0)
    scale=np.maximum(a,b)
    u=np.divide(a,scale,out=np.zeros_like(a),where=scale>0)
    v=np.divide(b,scale,out=np.zeros_like(b),where=scale>0)
    denominator=u*u+v*v
    high=np.divide(u*u,denominator,out=np.zeros_like(u),where=denominator>0)
    low=np.divide(v*v,denominator,out=np.zeros_like(v),where=denominator>0)
    visible=(a/np.hypot(a,CHROMA_NEUTRAL))**2
    return np.stack([visible*low,visible*high],axis=-1)


def chroma_crossover(H):
    """C at s=35 on H²=JA²+66C, for scope annotations only."""
    r=CHROMA_SATURATION/SATURATION_SCALE;H=np.maximum(np.asarray(H,dtype=float),0)
    # Rationalized positive root; H*(H/hypot(...)) avoids H² overflow.
    return r*H*(H/(np.hypot(H,33*r)+33*r))


def adaptance_weight(H,C,alpha):
    """Adaptance envelope on fixed Stage-2 H=J_HK and actual modCAM16 C.

    gamma=1, p=2, C0=30, rho=.25. H=100 is reference white (203 nits
    by default); HDR H extends above 100. The stored a/b coordinates have
    radius C, so no CAM16-UCS M-prime conversion is involved.
    """
    H,C=np.broadcast_arrays(np.asarray(H,dtype=float),np.asarray(C,dtype=float))
    with np.errstate(over='ignore'):
        rate=ADAPTANCE_RHO+(1-ADAPTANCE_RHO)/(1+(C/ADAPTANCE_C0)**2)
    amount=np.clip(alpha,0,1)
    return np.maximum(H,0)*.01*(amount*rate)/(1-amount+amount*rate)


CONCENTRATION_LIMIT=.6
CONCENTRATION_NEUTRAL=2.


def concentration_parameter(v):
    """Smooth bounded disk; raw control heights have range [-1,1] per axis."""
    v=np.asarray(v,dtype=float);t=np.linalg.norm(v,axis=-1)/CONCENTRATION_LIMIT
    scale=np.divide(np.tanh(t),t,out=np.ones_like(t),where=t>0)
    return v*scale[...,None]


def hue_concentration(ab,v):
    """Orientation-preserving circle automorphism, evaluated before rotation.

    All driver inputs are fixed Stage-2 attributes. This operator preserves C;
    neutral fade avoids an undefined hue at C=0. Positive v concentrates hue
    spacing around v and expands it opposite. Coefficients use fixed inputs.
    """
    ab=np.asarray(ab,dtype=float);C=np.linalg.norm(ab,axis=-1)
    z=np.divide(ab[...,0]+1j*ab[...,1],C,out=np.zeros_like(C,dtype=complex),where=C>0)
    wv=concentration_parameter(v);fade=(C/np.hypot(C,CONCENTRATION_NEUTRAL))**2
    w=(wv[...,0]+1j*wv[...,1])*fade
    out=C*(z+w)/(1+np.conj(w)*z)
    result=np.stack([out.real,out.imag],axis=-1)
    return np.where((np.linalg.norm(v,axis=-1)==0)[...,None],ab,result)


def hk_energy(q,reference=None):
    """Fourth-root achromatic energy, C2-matched at the H-K knee.

    reference is the paired Stage-2 H,a,b, before creative contributions.
    delta = HK_KNEE * E0 * H^2/(E0+H^2). Its harmonic form is evaluated
    without multiplying the two squared-lightness values. This is a pointwise
    colour transform: image content, histograms and sample selection play no role.
    A neutral reference is used only for standalone target probes.
    """
    q=np.asarray(q,dtype=float);H=q[...,0];C=np.hypot(q[...,1],q[...,2])
    h2=H*H;D=h2-66*C
    E0=h2 if reference is None else np.maximum(0,np.asarray(reference)[...,0]**2-66*np.hypot(np.asarray(reference)[...,1],np.asarray(reference)[...,2]))
    low=np.minimum(E0,h2);high=np.maximum(E0,h2)
    ratio=np.divide(low,high,out=np.zeros_like(D),where=high>0)
    delta=HK_KNEE*low/(1+ratio)
    # p=1/4: delta/(1+4*t+10*t*t)^p. Use v=1/(1+t) to
    # keep the polynomial bounded and evaluate the fourth root with SQRTs.
    v=np.divide(delta,delta+np.maximum(delta-D,0),out=np.zeros_like(D),where=delta>0)
    u=1-v
    floor=delta*np.sqrt(v)/np.sqrt(np.sqrt(v*v+4*v*u+10*u*u))
    energy=np.where(D>=delta,D,floor)
    return np.where((H>=0)&np.isfinite(q).all(axis=-1),energy,D)


def _project_hk_energy(q,energy):
    """Allocate the repair; H rises by at most 20%, with hue held fixed."""
    q=np.asarray(q,dtype=float);H=q[...,0];C=np.hypot(q[...,1],q[...,2]);X=H*H;D=X-66*C
    Z=np.maximum(energy-D,0);L=((1+HK_H_LIFT)**2-1)*X
    denominator=np.hypot(2*L,Z)
    G=L*np.divide(Z,denominator,out=np.zeros_like(Z),where=denominator>0)
    Cout=np.minimum(C,np.maximum(0,(X+G-energy)/66))
    scale=np.divide(Cout,C,out=np.ones_like(C),where=C>0)
    result=np.concatenate((np.sqrt(np.maximum(0,X+G))[...,None],q[...,1:]*scale[...,None]),axis=-1)
    active=(H>=0)&np.isfinite(q).all(axis=-1)&(energy>D)
    return np.where(active[...,None],result,q)


def project_hk(q,reference=None):
    """Reported repaired H,a,b; the inverse separately carries J_A²."""
    return _project_hk_energy(q,hk_energy(q,reference))


def smoother(x):
    x=np.clip(x,0,1)
    return x*x*x*(x*(x*6-15)+10)


class Model:
    def __init__(self,tone,params):
        self.tone=tone;self.params=params
        self.active=any(getattr(params,n)!=0 for n in ADJUST_NAMES)
        self.anchors=tone.target[1:]*100
        self.knots=np.r_[0.,smoother(self.anchors/tone.high_j)]
        self.kernels={}
        for fit in {4,params.adaptance_fit,params.j_fit,params.c_fit,params.hue_fit}:
            width=.05*2**(-fit)
            norm=np.array([tm.kernel_integral(1,l,r,width) for l,r in zip(self.knots,self.knots[1:])])
            self.kernels[fit]=(width,norm)

    def weights(self,H,fit=4,zero_black=False):
        t=smoother(np.asarray(H)/self.tone.high_j)
        w,norm=self.kernels[fit]
        f=np.stack([np.clip(tm.kernel_integral(t,l,r,w)/n,0,1) for l,r,n in zip(self.knots,self.knots[1:],norm)],axis=-1)
        f=np.minimum.accumulate(f,axis=-1)
        result=np.stack([1-f[...,1],f[...,1]-f[...,2],f[...,2]-f[...,3],f[...,3]],axis=-1)
        if zero_black:result[...,0]-=1-f[...,0]
        return result

    def heights(self,stem):
        return np.array([getattr(self.params,f'{stem}_{i}') for i in range(4)])

    def curve(self,H,stem):
        family='hue' if stem.startswith('concentration_') else stem.split('_')[0]
        return self.weights(H,getattr(self.params,f'{family}_fit'),family=='adaptance')@self.heights(stem)

    def drivers(self,q,JA=None):
        H,a,b=np.moveaxis(np.asarray(q,dtype=float),-1,0);C=np.hypot(a,b)
        if JA is None:JA=np.sqrt(np.maximum(0,H*H-66*C))
        pair=chroma_drivers(C,JA);denom=np.hypot(C,CHROMA_NEUTRAL)
        return np.concatenate([pair,np.stack([a/denom,b/denom],axis=-1)],axis=-1)

    def adjustments(self,q,JA=None):
        H=q[...,0];p=self.params;d=self.drivers(q,JA)
        light=np.stack([self.curve(H,'j_'+key) for key,_,_ in DRIVERS],axis=-1)
        radius=np.stack([self.curve(H,'c_'+key) for key,_,_ in DRIVERS],axis=-1)
        dj=np.sum(light*d,axis=-1);gain=np.exp2(p.global_gain+np.sum(radius*d,axis=-1))
        theta=np.deg2rad(self.curve(H,'hue')+p.global_low_hue*d[...,0]+p.global_high_hue*d[...,1])
        weight=adaptance_weight(H,np.hypot(q[...,1],q[...,2]),p.adaptance_strength)
        adaptance=np.stack([self.curve(H,'adaptance_a'),self.curve(H,'adaptance_b')],axis=-1)*weight[...,None]
        return dj,gain,theta,adaptance

    def stage3(self,q,JA=None):
        q=np.asarray(q,dtype=float)
        if not self.active:return q.copy()
        dj,g,th,adaptance=self.adjustments(q,JA);co=np.cos(th);si=np.sin(th)
        concentration=np.stack([self.curve(q[...,0],'concentration_a'),self.curve(q[...,0],'concentration_b')],axis=-1)
        ab=hue_concentration(q[...,1:],concentration);a,b=ab[...,0],ab[...,1]
        out=np.stack([q[...,0]+dj,adaptance[...,0]+g*(co*a-si*b),adaptance[...,1]+g*(si*a+co*b)],axis=-1)
        return np.where((q[...,0]==0)[...,None],q,out)

    def stage2_with_ja(self,q,JA=None):
        q=np.asarray(q,dtype=float)
        H=q[...,0];C=np.hypot(q[...,1],q[...,2])
        valid=np.ones_like(H,dtype=bool) if JA is not None else H*H>=66*C
        if JA is None:JA=np.sqrt(np.maximum(0,H*H-66*C))
        if not self.tone.active:return q.copy(),np.asarray(JA).copy()
        H=q[...,0];C=np.hypot(q[...,1],q[...,2]);H2=100*self.tone.remap(H/100)
        gain=tm.saturation_gain(H,JA,C,H2)
        out=np.concatenate([H2[...,None],q[...,1:]*gain[...,None]],axis=-1)
        return np.where(valid[...,None],out,q),np.where(valid,gain*JA,JA)

    def stage2(self,q):return self.stage2_with_ja(q)[0]

    def decode(self,q,reference=None):
        square=hk_energy(q,reference)
        q=_project_hk_energy(q,square)
        H,a,b=np.moveaxis(q,-1,0);C=np.hypot(a,b)
        ja=np.sqrt(np.maximum(0,square));ach=self.tone.aw*(ja/100)**(1/tm.GAMMA)
        co=np.divide(a,C,out=np.zeros_like(a),where=C>0);si=np.divide(b,C,out=np.zeros_like(b),where=C>0)
        scale=self.tone.aw/(1204*tm.eccentricity(co,si));ar=a*scale;br=b*scale
        s=np.stack([(460*ach+451*ar+288*br)/1403,(460*ach-891*ar-261*br)/1403,(460*ach-220*ar-6300*br)/1403],axis=-1)
        out=tm.unresponse(np.clip(s,-399.998,399.998),self.tone.fl)
        valid=(H>=0)&(square>=0)&(np.max(np.abs(s),axis=-1)<399.998)
        valid &= np.isfinite(q).all(axis=-1)&np.isfinite(square)&np.isfinite(out).all(axis=-1)
        return out,valid

    def core(self,n):
        q,valid,ach,*_=self.tone.attributes(n)
        JA=100*(np.maximum(ach,0)/self.tone.aw)**tm.GAMMA
        q2,JA2=self.stage2_with_ja(q,JA);q3=self.stage3(q2,JA2)
        out,ok=self.decode(q3,q2)
        unchanged=np.all(q==q3,axis=-1)
        return np.where(unchanged[...,None],n,out),valid&(ok|unchanged)

    def apply(self,rgb):
        rgb=np.asarray(rgb,dtype=float)
        fallback=self.tone.apply(rgb)
        if not self.active:return fallback
        n=self.tone.cones(rgb);lift=np.maximum(0,-np.min(n,axis=-1));lifted=n+lift[...,None]
        lifted=np.where(np.abs(lifted)<=4e-7*(np.abs(n)+lift[...,None]),0,lifted)
        out,valid=self.core(lifted);offset,offset_valid=self.core(np.broadcast_to(lift[...,None],n.shape))
        result=(out-offset)@self.tone.from_cone.T
        return np.where((valid&offset_valid&np.isfinite(result).all(axis=-1))[...,None],result,fallback)


@lru_cache(maxsize=64)
def model(tone_params,params,space='Linear Rec.709'):
    return Model(tm.model(tone_params,space),params)
