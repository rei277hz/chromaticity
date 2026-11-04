"""One-dimensional coefficient tables. No image pixels are graded in Python.

Tables contain float32 raw data. Quintics match analytic values and first two
derivatives. Stage 2 keeps its linear asymptote outside the bounded table.
"""


from functools import lru_cache
import math
import numpy as np
from . import tone as tm; from . import color as cm

STEMS = ('tone', 'adaptance_a', 'adaptance_b', 'j_low', 'j_high', 'j_a', 'j_b',
         'c_low', 'c_high', 'c_a', 'c_b', 'hue', 'concentration_a', 'concentration_b')
BASIS_STEMS = ('tone', *(f'{family}_w{i}' for family in ('adaptance','j','c','hue')
                       for i in range(4 if family=='adaptance' else 3)))
MODE = 'QUINTIC_2048'
TEXTURE_WIDTH=512
TEXTURE_BLOCKS=5  # 2,049 endpoint jets, in five short rows per curve.
TEXTURE_HEIGHT=TEXTURE_BLOCKS*len(BASIS_STEMS)


def texture_pixels(table):
    """Tile jets and normalize each channel for half-float image transport."""
    raw=table.pixels()[...,:3]
    maximum=np.max(abs(raw),axis=(0,1))
    _,exponent=np.frexp(maximum)
    scale=np.where(maximum>0,np.exp2(exponent),1).astype('f4')
    result=np.ones((TEXTURE_HEIGHT,TEXTURE_WIDTH,4),np.float32)
    result[...,:3]=0
    for i,row in enumerate(raw):
        target=result[i*TEXTURE_BLOCKS:(i+1)*TEXTURE_BLOCKS].reshape(-1,4)
        target[:len(row),:3]=row/scale
    return result,scale


def parse(mode=MODE):
    if mode != MODE:
        raise ValueError('Unsupported Perceptual Grade curve evaluation: {mode}'.format(mode=mode))
    return 'QUINTIC', 2048


def integral_jet(t, left, right, width):
    """Value, d/dt, d²/dt²; includes the reference's narrow-interval branch."""
    value = tm.kernel_integral(t, left, right, width)
    if right-left < .1*width:
        mid = .5*(left+right); d = .387298334621*(right-left)
        first = np.zeros_like(t); second = np.zeros_like(t)
        for s, weight in ((mid-d,.277777777778),(mid,.444444444444),(mid+d,.277777777778)):
            v = tm.sigmoid((t-s)/width); p = v*(1-v)
            first += weight*p/width
            second += weight*p*(1-2*v)/(width*width)
        return value, (right-left)*first, (right-left)*second
    a = tm.sigmoid((t-left)/width); b = tm.sigmoid((t-right)/width)
    return value, a-b, (a*(1-a)-b*(1-b))/width


def weights_jet(model, x, family):
    x = np.asarray(x, dtype=float)
    t = cm.smoother(x)
    dt = 30*x*x*(1-x)**2
    ddt = 60*x*(1-x)*(1-2*x)
    fit = getattr(model.params, family+'_fit')
    width, norms = model.kernels[fit]
    f, d, dd = [], [], []
    for l,r,n in zip(model.knots,model.knots[1:],norms):
        v,a,b = integral_jet(t,l,r,width)
        f.append(v/n); d.append(a*dt/n); dd.append((b*dt*dt+a*ddt)/n)
    def differences(values, zeroth):
        return np.stack([values[0]-values[1] if family=='adaptance' else zeroth-values[1],
                         values[1]-values[2],values[2]-values[3],values[3]],axis=-1)
    # Use the exact reference values, including its rounding guards.
    values = model.weights(x*model.tone.high_j,fit,family=='adaptance')
    return values, differences(d,0), differences(dd,0)


def jets(model, x):
    """All table curves at normalized coordinates. tone uses z=t/(1+t)."""
    x = np.asarray(x,dtype=float); tone=model.tone
    q = np.maximum(1-x,1e-12); t=x/q
    v=np.zeros_like(x); d=v.copy(); dd=v.copy()
    for l,r,n,res in zip(tone.knots,tone.knots[1:],tone.norm,tone.residual):
        a,b,c=integral_jet(t,l,r,tone.width)
        v+=res*a/n; d+=res*b/n/q**2; dd+=res*(c/q**4+2*b/q**3)/n
    d=np.where(x==1,0,d);dd=np.where(x==1,0,dd)
    result=[(v,d,dd)]; weights={}
    for stem in STEMS[1:]:
        family='hue' if stem.startswith('concentration_') else stem.split('_')[0]
        if family not in weights:weights[family]=weights_jet(model,x,family)
        w=weights[family]
        heights=model.heights(stem)
        result.append(tuple(a@heights for a in w))
    return tuple(np.stack([r[i] for r in result],axis=0) for i in range(3))


def coefficients(y, d, dd, step):
    a0=y[:,:-1];a1=d[:,:-1]*step;a2=dd[:,:-1]*step*step/2
    D=y[:,1:]-a0-a1-a2; E=d[:,1:]*step-a1-2*a2; F=dd[:,1:]*step*step-2*a2
    return np.stack([a0,a1,a2,10*D-4*E+F/2,-15*D+7*E-F,6*D-3*E+F/2],axis=-1)


def derivative_bernstein(poly):
    a=poly[...,1:]*np.arange(1,6)
    return np.stack([sum(a[...,j]*math.comb(k,j)/math.comb(4,j) for j in range(k+1))
                     for k in range(5)],axis=-1)


class Table:
    def __init__(self, model, mode):
        self.model=model;self.mode=mode;self.kind,self.cells=parse(mode)
        x=np.linspace(0,1,self.cells+1);y,d,dd=jets(model,x)
        self.stems=STEMS
        self.store(y,d,dd)

    def store(self,y,d,dd):
        self.limited_knots=0
        if self.kind=='QUINTIC':
            # Sufficient monotonicity certificate for the Stage-2 residual.
            # Shared derivatives at each knot preserve C² even if limited.
            for _ in range(self.cells+1):
                poly=coefficients(y,d,dd,1/self.cells)
                b=derivative_bernstein(poly[0]);bad=np.min(b,axis=-1)<-1e-13
                if not np.any(bad):break
                indices=np.unique(np.r_[np.flatnonzero(bad),np.flatnonzero(bad)+1])
                self.limited_knots+=int(np.count_nonzero((d[0,indices]!=0)|(dd[0,indices]!=0)))
                d[0,indices]=0;dd[0,indices]=0
            # Store shared endpoint jets, not independently rounded interval
            # polynomials: adjacent intervals then use exactly the same value,
            # slope and curvature at their common knot.
            self.data=np.stack([y,d/self.cells,dd/self.cells**2],axis=-1).astype(np.float32)
        else:self.data=y.astype(np.float32)
        # CPU scopes reuse interval polynomials. Native textures still store
        # shared endpoint jets, so adjacent intervals have identical C² joins.
        self.coef=None
        if self.kind=='QUINTIC':
            data=self.data.astype(float)
            self.coef=coefficients(data[:,:,0],data[:,:,1],data[:,:,2],1)

    def evaluate(self, x, stem, derivative=0):
        x=np.clip(np.asarray(x,dtype=float),0,1);index=self.stems.index(stem)
        p=x*self.cells;i=np.minimum(np.floor(p).astype(int),self.cells-1);u=p-i
        coef=self.coef[index,i]
        for _ in range(derivative):coef=coef[...,1:]*np.arange(1,coef.shape[-1])
        out=coef[...,-1]
        for k in range(coef.shape[-1]-2,-1,-1):out=out*u+coef[...,k]
        return out*self.cells**derivative

    def pixels(self):
        pixels=np.ones((len(self.stems),self.cells+1,4),dtype=np.float32)
        pixels[:,:,:3]=self.data
        return pixels


class BasisTable(Table):
    """Height-independent Stage 3 weights; only shape/anchor edits rebake."""
    def __init__(self,tone,space,mode,fit):
        params=cm.Parameters(**dict(zip(('adaptance_fit','j_fit','c_fit','hue_fit'),fit)))
        model=cm.model(tone,params,space)
        self.model=model;self.mode=mode;self.kind,self.cells=parse(mode);self.stems=BASIS_STEMS
        x=np.linspace(0,1,self.cells+1)
        # Preserve exactly the existing Stage 2 samples/certificate.
        old=jets(model,x)
        result=[tuple(v[0] for v in old)]
        for family in ('adaptance','j','c','hue'):
            w=weights_jet(model,x,family)
            result.extend(tuple(v[:,i] for v in w) for i in range(4 if family=='adaptance' else 3))
        self.store(*(np.stack([r[i] for r in result]) for i in range(3)))

    def weights(self,x,family):
        w=[self.evaluate(x,f'{family}_w{i}') for i in range(4 if family=='adaptance' else 3)]
        if family!='adaptance':w.append(1-w[0]-w[1]-w[2])
        return np.stack(w,axis=-1)


@lru_cache(maxsize=12)
def basis_table(tone,space,mode,fit):return BasisTable(tone,space,mode,fit)


def basis_for(model,mode):
    return basis_table(model.tone.params,model.tone.space,mode,
                       tuple(getattr(model.params,f+'_fit') for f in ('adaptance','j','c','hue')))


@lru_cache(maxsize=12)
def table(tone, chromatic, space, mode):
    return Table(cm.model(tone,chromatic,space),mode)


class ToneModel(tm.Model):
    def remap(self,j):
        j=np.asarray(j,dtype=float)
        if not self.active:return j.copy()
        t=np.maximum(0,(j-self.black)/self.span)
        out=self.slope*t+self.lut.evaluate(t/(1+t),'tone')
        return np.where(t==1,self.target[-1],out)


class ColorModel(cm.Model):
    def curve(self,H,stem):
        x=np.asarray(H)/self.tone.high_j
        if isinstance(self.lut,BasisTable):
            return self.lut.weights(x,'hue' if stem.startswith('concentration_') else stem.split('_')[0])@self.heights(stem)
        return self.lut.evaluate(x,stem)


@lru_cache(maxsize=12)
def model(tone,chromatic,space,mode=MODE):
    lut=basis_for(cm.model(tone,chromatic,space),mode)
    t=ToneModel(tone,space);t.lut=lut
    c=ColorModel(t,chromatic);c.lut=lut
    return c
