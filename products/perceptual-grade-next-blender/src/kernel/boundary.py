"""Packaged fixed D65/AP1 output-boundary geometry and analysis helpers.

The small two-dimensional image is a root seed indexed by neutral response and
hue. It does not grade RGB. Native derivative corrections use the actual signed
appearance decoder; the seed never supplies an unvalidated final colour.
"""
from dataclasses import dataclass
from importlib import resources
import numpy as np
from ..color_core import linear
from .tables import readonly

P = 1/.42
SEED_SPLIT = .9
SEED_LOW_CELLS = 128
SEED_HIGH_CELLS = 192
SEED_HUE_CELLS = 512
CORRECTION_STEPS = 1
INVERSE = np.array(((460/1403,451/1403,288/1403),
                    (460/1403,-891/1403,-261/1403),
                    (460/1403,-220/1403,-6300/1403)))


def eccentricity(hue):
    c,s=np.cos(hue),np.sin(hue)
    return ((((.2312*c-.5388)*c-.2828)*c+.3459)*c+1.0547 + s*(((.0768*c+.154)*c-.1)*c-.186))


@dataclass(frozen=True)
class PreparedBoundary:
    matrix: np.ndarray
    inverse: np.ndarray
    fl: float
    aw: float
    gamma: float
    response_white: float
    white: float
    pixels: np.ndarray
    seed_max_error: float
    max_error: float = 0.
    probe_count: int = 0
    # Canonical resources keep these defaults. Report-only seed candidates
    # carry their own grid so Python and native sampling use identical axes.
    seed_split: float = SEED_SPLIT
    seed_low_cells: int = SEED_LOW_CELLS
    seed_high_cells: int = SEED_HIGH_CELLS
    seed_hue_cells: int = SEED_HUE_CELLS
    correction_steps: int = CORRECTION_STEPS

    def direction(self,hue):
        hue=np.asarray(hue)
        return self.aw/(1204*eccentricity(hue))[...,None]*(np.cos(hue)[...,None]*INVERSE[:,1]+np.sin(hue)[...,None]*INVERSE[:,2])

    def normalized(self,t,u,beta,dtype=np.float64,curvature=False):
        """Stable actual-decoder values and derivatives for a normalized ray."""
        d=dtype;t=np.asarray(t,dtype=d);u=np.asarray(u,dtype=d);beta=np.asarray(beta,dtype=d)
        delta=d(1)-t;k=d(self.response_white/(400-self.response_white))
        rel=d(1)+delta[...,None]*u[...,None]*beta
        a=d(self.response_white)*t/(d(400)-d(self.response_white)*t)
        den=d(1)-a[...,None]*(rel-d(1))
        x=np.maximum(d(0),rel/den)
        v=x**d(P)
        dv=d(P)*np.where(rel!=0,v/np.where(rel!=0,rel,d(1)),d(0))*delta[...,None]*beta*(d(1)+a[...,None])/den
        upper=(d(1)/(t*(d(400-self.response_white))/(d(400)-d(self.response_white)*t)))**d(P)
        # Upper-tip deficits avoid subtracting almost equal 1024-nit values.
        aa=d(1)-t[...,None]*u[...,None]*beta
        dd=d(1)+k*delta[...,None]*aa
        z=(d(1)+k)*delta[...,None]*aa/dd
        poly=d(P*(P-1)*(P-2)*(P-3)*(P-4)/120)
        poly=poly*z-d(P*(P-1)*(P-2)*(P-3)/24)
        poly=poly*z+d(P*(P-1)*(P-2)/6)
        poly=poly*z-d(P*(P-1)/2)
        poly=poly*z+d(P)
        direct=(d(1)-np.maximum(d(0),d(1)-z)**d(P))/np.where(z!=0,z,d(1))
        ratio=np.where(abs(z)<d(.1),poly,direct)
        vv=aa*(d(1)+k)/dd*ratio
        ddv=-d(P)*(d(1)+k)*t[...,None]*beta*np.maximum(d(0),d(1)-z)**d(P-1)/(dd*dd)
        high=t>d(.5)
        v=np.where(high[...,None],vv,v)
        dv=np.where(high[...,None],ddv,dv)
        upper=np.where(high,d(1)/np.maximum(delta,d(1e-30)),upper)
        # The neutral-preserving adapter used by the graph, not rounded row sums.
        matrix=np.asarray(self.matrix,dtype=d)
        values=v[...,1,None]+(v-v[...,1,None])@matrix.T
        deriv=dv[...,1,None]+(dv-dv[...,1,None])@matrix.T
        if curvature:
            base=np.where(high[...,None],np.maximum(d(0),d(1)-z),x)
            divisor=np.where(high[...,None],dd,den)
            slope=np.where(high,-t,delta)
            den_slope=np.where(high,k*delta,-a)
            scale=d((P-1)/P)*np.where(high,-delta,d(1))
            power=base**d(P)
            curve=dv*(scale[...,None]*np.divide(dv,power,out=np.zeros_like(dv),where=power!=0)-d(2)*(den_slope*slope)[...,None]*beta/divisor)
            return values,deriv,upper,curve[...,1,None]+(curve-curve[...,1,None])@matrix.T
        return values,deriv,upper

    def outer(self,t,beta):
        t=np.asarray(t);beta=np.asarray(beta)
        positive=np.divide(1.,t[...,None]*beta,out=np.full_like(beta,np.inf),where=beta>0)
        negative=np.divide(-1.,(1-t)[...,None]*beta,out=np.full_like(beta,np.inf),where=beta<0)
        return np.min(np.minimum(positive,negative),axis=-1)

    def exact(self,t,hue):
        """Independent bracketed root for seed preparation and internal checks."""
        t,hue=np.broadcast_arrays(np.asarray(t,float),hue)
        t=np.clip(t,1e-9,1-1e-9)
        beta=self.direction(hue)
        lo=np.zeros_like(t);hi=self.outer(t,beta)
        for _ in range(42):
            mid=(lo+hi)/2
            values,_,upper=self.normalized(t,mid,beta)
            legal=np.all((values>=0)&(values<=upper[...,None]),axis=-1)
            lo=np.where(legal,mid,lo);hi=np.where(legal,hi,mid)
        return lo

    def seed(self,t,hue):
        x=np.mod(hue/(2*np.pi),1.)*self.seed_hue_cells
        t=np.clip(t,0,1)
        split=self.seed_split
        y=np.minimum(t,split)*(self.seed_low_cells/split)+np.maximum(t-split,0)*(self.seed_high_cells/(1-split))
        ix=np.minimum(x.astype(int),self.pixels.shape[1]-2);iy=np.minimum(y.astype(int),self.pixels.shape[0]-2)
        dx=(x-ix)[...,None];dy=(y-iy)[...,None];data=self.pixels[...,:3]
        values=((1-dy)*((1-dx)*data[iy,ix]+dx*data[iy,ix+1])+dy*((1-dx)*data[iy+1,ix]+dx*data[iy+1,ix+1]))
        return np.min(values,axis=-1)

    def corrected(self,t,hue,dtype=np.float32):
        """One safeguarded Halley step from the bilinear face-tangent seed."""
        d=dtype;t=np.clip(np.asarray(t,dtype=d),d(1e-9),d(1-1e-7));hue=np.asarray(hue,dtype=d)
        beta=self.direction(hue).astype(d)
        u=self.seed(t,hue).astype(d)
        for _ in range(self.correction_steps):
            v,dv,upper,curvature=self.normalized(t,u,beta,d,True)
            target=np.where(dv>0,upper[...,None],d(0))
            step=np.divide(target-v,dv,out=np.zeros_like(v),where=dv!=0)
            ratio=np.divide(curvature,dv,out=np.zeros_like(v),where=dv!=0)
            denominator=np.clip(d(1)+d(.5)*step*ratio,d(.5),d(1.5))
            u=np.maximum(d(0),np.min(u[...,None]+step/denominator,axis=-1))
        return u


RESOURCE_NAME = 'output_boundary.npz'
RESOURCE_SCHEMA = 1
RESOURCE_FLOATS = ('fl', 'aw', 'gamma', 'response_white', 'white', 'seed_max_error', 'max_error')
RESOURCE_INTS = ('schema', 'seed_low_cells', 'seed_high_cells', 'seed_hue_cells', 'correction_steps', 'probe_count')


def _context_geometry(fl, aw, gamma):
    """Small adapter calculation shared by the generator and resource checks."""
    white=np.asarray(linear.xyz(linear.D65))
    cones_to_xyz=np.linalg.inv(np.asarray(linear.CAT16))@np.diag(np.asarray(linear.CAT16)@white)
    matrix=np.linalg.inv(np.asarray(linear.rgb_to_xyz('ACEScg')))@np.asarray(linear.bradford(linear.D65,linear.ACES_WHITE))@cones_to_xyz
    matrix[:,1]=1-matrix[:,0]-matrix[:,2]
    p=(fl*1024)**.42;rw=400*p/(27.13+p)
    maximum=100*(3.05*rw/aw)**gamma
    return matrix, np.linalg.inv(matrix), rw, maximum


def _load_boundary(stream, fl, aw, gamma):
    """Validate the packaged representation without regenerating its geometry."""
    expected = {*RESOURCE_FLOATS, *RESOURCE_INTS, 'seed_split', 'matrix', 'inverse', 'pixels'}
    try:
        with np.load(stream, allow_pickle=False) as archive:
            if set(archive.files) != expected:
                raise ValueError('Output-boundary resource has unexpected fields')
            data = {name: np.array(archive[name], copy=True) for name in expected}
    except (OSError, EOFError, KeyError, TypeError) as error:
        raise ValueError('Cannot read packaged output-boundary resource') from error
    for name in (*RESOURCE_FLOATS, 'seed_split'):
        value = data[name]
        if value.shape != () or value.dtype != np.dtype('float64') or not np.isfinite(value):
            raise ValueError(f'Invalid output-boundary scalar: {name}')
    for name in RESOURCE_INTS:
        value = data[name]
        if value.shape != () or value.dtype != np.dtype('int64'):
            raise ValueError(f'Invalid output-boundary integer: {name}')
    contract = dict(schema=RESOURCE_SCHEMA, seed_low_cells=SEED_LOW_CELLS,
                    seed_high_cells=SEED_HIGH_CELLS, seed_hue_cells=SEED_HUE_CELLS,
                    seed_split=SEED_SPLIT, correction_steps=CORRECTION_STEPS)
    for name, value in contract.items():
        if data[name].item() != value:
            raise ValueError(f'Unsupported output-boundary resource {name}')
    for name, value in (('fl', fl), ('aw', aw), ('gamma', gamma)):
        if not np.isfinite(value) or float(data[name]) != value:
            raise ValueError(f'Output-boundary resource context mismatch: {name}')
    for name in ('matrix', 'inverse'):
        if data[name].shape != (3, 3) or data[name].dtype != np.dtype('float64') or not np.isfinite(data[name]).all():
            raise ValueError(f'Invalid output-boundary {name}')
    matrix, inverse, response_white, white = _context_geometry(fl, aw, gamma)
    tolerance = 64*np.finfo(np.float64).eps
    for name, expected_value in (('matrix', matrix), ('inverse', inverse),
                                 ('response_white', response_white), ('white', white)):
        if np.any(abs(data[name]-expected_value) > tolerance*(1+abs(expected_value))):
            raise ValueError(f'Output-boundary resource context mismatch: {name}')
    pixels = data['pixels']
    if (pixels.shape != (SEED_LOW_CELLS+SEED_HIGH_CELLS+1, SEED_HUE_CELLS+1, 4)
            or pixels.dtype != np.dtype('float32') or not np.isfinite(pixels).all()
            or np.any(pixels[..., :3] < 0) or not np.all(pixels[..., 3] == 1)):
        raise ValueError('Invalid output-boundary seed pixels')
    if (not 0 <= float(data['max_error']) <= 2e-5 or float(data['seed_max_error']) < 0
            or int(data['probe_count']) < (SEED_LOW_CELLS+SEED_HIGH_CELLS)*SEED_HUE_CELLS
            or not 0 < float(data['response_white']) < 400 or float(data['white']) <= 0):
        raise ValueError('Invalid output-boundary validation metadata')
    return PreparedBoundary(readonly(data['matrix']), readonly(data['inverse']),
                            *(float(data[name]) for name in ('fl', 'aw', 'gamma', 'response_white', 'white')),
                            readonly(pixels, np.float32), float(data['seed_max_error']),
                            float(data['max_error']), int(data['probe_count']))


def prepare_boundary(fl, aw, gamma):
    """Load immutable build-time geometry for reuse across grades.

    Missing or incompatible resources fail explicitly; runtime never generates
    or densely revalidates boundary geometry. Buck's ``boundary_resource`` target
    owns those operations. Each caller may retain the returned host object.
    """
    try:
        with resources.files(__package__).joinpath(RESOURCE_NAME).open('rb') as stream:
            return _load_boundary(stream, fl, aw, gamma)
    except FileNotFoundError as error:
        raise FileNotFoundError('Packaged output-boundary resource is missing; build '
                                '//products/perceptual-grade-next-blender:boundary_resource') from error
