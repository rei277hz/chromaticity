"""Study-only scalar input grids; interpolation remains physical RGB."""
from dataclasses import dataclass,replace
from functools import lru_cache
from itertools import product
import math
import numpy as np

MAXIMUM=1024.
LOG_KAPPAS=tuple(10**(j/2) for j in range(-8,5))
COMPOSED_KAPPAS=(.001,.01,.1,1.)
STRENGTHS=(1.,2.,4.)
CENTERS=(0.,.5,1.)
COMPOSED_CENTERS=(0.,.25,.5,.75,1.)


@dataclass(frozen=True)
class Shaper:
    family: str='log'
    kappa: float=.01
    strength: float=1.
    center: float=.5

    def __post_init__(self):
        if self.family not in ('linear','log','tanh','log_tanh'):
            raise ValueError('Unknown input shaper')
        if not all(math.isfinite(v) for v in (self.kappa,self.strength,self.center)):
            raise ValueError('Shaper parameters must be finite')
        if self.kappa<=0 or self.strength<=0 or not 0<=self.center<=1:
            raise ValueError('Expected positive kappa/strength and center in [0,1]')

    def to_dict(self):
        result={'family':self.family}
        if self.family in ('log','log_tanh'):result['kappa']=float(self.kappa)
        if self.family in ('tanh','log_tanh'):
            result.update(strength=float(self.strength),center=float(self.center))
        return result

    @property
    def key(self):
        return self.family+''.join(f'-{k}{v!r}' for k,v in self.to_dict().items() if k!='family')

    @staticmethod
    def _values(values,maximum,dtype):
        x=np.asarray(values,dtype=dtype)
        if not np.isfinite(x).all() or np.any((x<0)|(x>maximum)):
            raise ValueError(f'Shaper input must be finite and in [0,{maximum:g}]')
        return x

    def _tanh_constants(self,dtype):
        cast=np.dtype(dtype).type;a,c=cast(self.strength),cast(self.center)
        normal=np.sinh(a)/np.cosh(a*(cast(1)-c))
        return a,c,normal

    def encode(self,values,dtype=np.float64):
        x=self._values(values,MAXIMUM,dtype);cast=np.dtype(dtype).type
        k=cast(self.kappa);maximum=cast(MAXIMUM)
        z=np.log1p(x/k)/np.log1p(maximum/k) if self.family in ('log','log_tanh') else x/maximum
        if self.family in ('tanh','log_tanh'):
            a,c,normal=self._tanh_constants(dtype)
            # The centered tanh difference, without near-black cancellation.
            z=np.sinh(a*z)/(np.cosh(a*(z-c))*normal)
        return np.where(x==0,cast(0),np.where(x==maximum,cast(1),z))

    def decode(self,values,dtype=np.float64):
        y=self._values(values,1.,dtype);cast=np.dtype(dtype).type;z=y
        if self.family in ('tanh','log_tanh'):
            a,c,normal=self._tanh_constants(dtype)
            z=(np.log1p(y*normal*np.exp(a*c))-np.log1p(-y*normal*np.exp(-a*c)))/(cast(2)*a)
        k=cast(self.kappa);maximum=cast(MAXIMUM)
        x=k*np.expm1(z*np.log1p(maximum/k)) if self.family in ('log','log_tanh') else maximum*z
        return np.where(y==0,cast(0),np.where(y==1,maximum,x))

    @lru_cache(maxsize=None)
    def axis(self,size=65):
        if size==33:return self.axis()[::2]
        if size!=65:raise ValueError('This study uses the fixed 65 grid and its 33 subset')
        values=self.decode(np.linspace(0,1,size));values[0],values[-1]=0.,MAXIMUM
        if (not np.isfinite(values).all() or np.any(np.diff(values)<=0)
                or np.any(np.diff(values.astype('f4'))<=0)):
            raise ArithmeticError('Shaper knots must be finite and strictly increasing in float32')
        values.flags.writeable=False
        return values

    def lattice(self,size=65):
        a=self.axis(size)
        return np.stack(np.meshgrid(a,a,a,indexing='ij'),-1).reshape(-1,3).astype('f4')

    def diagnostics(self,size=65):
        knots=self.axis(size);rounded=knots.astype('f4');u=np.linspace(0,1,size)
        encoded=self.encode(rounded,dtype=np.float32)
        decoded=self.decode(u,dtype=np.float32)
        returned=self.decode(encoded,dtype=np.float32)
        finite=bool(all(np.isfinite(v).all() for v in (encoded,decoded,returned)))
        monotone=bool(np.all(np.diff(encoded)>0) and np.all(np.diff(decoded)>0))
        endpoints=bool(encoded[0]==0 and encoded[-1]==1 and decoded[0]==0 and decoded[-1]==MAXIMUM)
        return dict(valid=finite and monotone and endpoints,finite_float32=finite,
            monotone_float32=monotone,exact_endpoints=endpoints,
            minimum_knot_spacing=float(np.min(np.diff(rounded))),
            maximum_knot_address_error_cells=float(np.max(abs(encoded.astype(float)-u))*(size-1)),
            maximum_decode_error=float(np.max(abs(decoded.astype(float)-knots))),
            maximum_roundtrip_error=float(np.max(abs(returned.astype(float)-rounded))),
            maximum_float64_roundtrip_error=float(np.max(abs(self.decode(self.encode(knots))-knots))))


def initial_candidates():
    return (Shaper('linear'),*(Shaper('log',kappa=k) for k in LOG_KAPPAS),
        *(Shaper('tanh',strength=a,center=c) for a,c in product(STRENGTHS,CENTERS)),
        *(Shaper('log_tanh',kappa=k,strength=a,center=c)
          for k,a,c in product(COMPOSED_KAPPAS,STRENGTHS,COMPOSED_CENTERS)))


def refinements(shaper):
    """Change one active parameter halfway toward each initial-grid neighbor."""
    axes={}
    if shaper.family=='log':axes['kappa']=LOG_KAPPAS
    if shaper.family=='log_tanh':axes['kappa']=COMPOSED_KAPPAS
    if shaper.family in ('tanh','log_tanh'):
        axes['strength']=STRENGTHS
        axes['center']=CENTERS if shaper.family=='tanh' else COMPOSED_CENTERS
    result=[]
    for name,axis in axes.items():
        value=getattr(shaper,name);lower=[v for v in axis if v<value];upper=[v for v in axis if v>value]
        neighbors=([lower[-1]] if lower else [])+([upper[0]] if upper else [])
        for neighbor in neighbors:
            midpoint=math.sqrt(value*neighbor) if name=='kappa' else (value+neighbor)/2
            result.append(replace(shaper,**{name:midpoint}))
    return tuple(result)


def addresses(prepared_rgb,shaper,size=65):
    rgb=np.asarray(prepared_rgb,dtype=float)
    if rgb.shape[-1:]!=(3,) or not np.isfinite(rgb).all() or np.any((rgb<0)|(rgb>MAXIMUM)):
        raise ValueError('LUT interpolation needs repaired finite AP1 RGB in [0,1024]')
    x=rgb.reshape(-1,3);grid=shaper.axis(size)
    if shaper.family=='log':
        # Preserve the adopted baseline's multiplication/division ordering.
        position=(size-1)*np.log1p(x/shaper.kappa)/np.log1p(MAXIMUM/shaper.kappa)
    else:position=(size-1)*shaper.encode(x)
    cell=np.clip(np.floor(position),0,size-2).astype(np.int64)
    fraction=np.clip((x-grid[cell])/(grid[cell+1]-grid[cell]),0,1)
    order=np.argsort(-fraction,axis=-1,kind='stable')
    first=np.eye(3,dtype=np.int64)[order[:,0]];second=np.eye(3,dtype=np.int64)[order[:,1]]
    corners=(cell,cell+first,cell+first+second,cell+1)
    return rgb,corners,np.take_along_axis(fraction,order,axis=-1)


def tetrahedral(values,prepared_rgb,shaper):
    table=np.asarray(values);size=round((table.size/3)**(1/3))
    if size<2 or table.size!=3*size**3:raise ValueError('Expected a complete RGB cube')
    table=table.reshape(size,size,size,3)
    rgb,corners,fractions=addresses(prepared_rgb,shaper,size)
    vertices=[table[p[:,0],p[:,1],p[:,2]] for p in corners]
    result=vertices[0].astype(float,copy=True)
    for a,b,f in zip(vertices,vertices[1:],fractions.T):
        result+=(b.astype(float)-a.astype(float))*f[:,None]
    return result.reshape(rgb.shape)
