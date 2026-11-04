"""Analytic nested 33/65-cube baking and matching tetrahedral evaluation, without bpy.

Ordinary Stage 1 stays an exact matrix; Stacks include every stage. Cubes use
fixed native ACEScg/ACES-white coordinates on a nonnegative log1p grid. The
analytic grading coordinates are unchanged. Outer cells extrapolate in linear
RGB; the input color is never clipped to the grid.
"""


from functools import lru_cache
from concurrent.futures import CancelledError
from threading import Event
import hashlib
import math
import numpy as np
from . import color as cm
from . import linear
from .pipeline import Prepared

SCHEMA=13
SIZE=65
PREVIEW_SIZE=33
CELLS=SIZE-1
SPACE='ACEScg'
CANONICAL_SPACE='Linear Rec.709'
MINIMUM=0.
MAXIMUM=128.
KAPPA=.01
LOG_RANGE=math.log1p(MAXIMUM/KAPPA)
ATLAS_WIDTH=1024
ATLAS_HEIGHT=(SIZE**3+ATLAS_WIDTH-1)//ATLAS_WIDTH
BLOCK=4096


def atlas_height(size,planes=1):
    return (planes*size**3+ATLAS_WIDTH-1)//ATLAS_WIDTH


@lru_cache(maxsize=8)
def basis(space=CANONICAL_SPACE):
    """Model RGB ↔ fixed LUT RGB, including white adaptation when required.

    GradeSpace uses canonical Rec.709 coordinates even when its CAM white is
    different. Named analytic RGB spaces are also supported by numerical
    tools; their chromatic adaptation is part of the coordinate conversion.
    """
    source=CANONICAL_SPACE if isinstance(space,linear.GradeSpace) else space
    to_lut=(np.asarray(linear.xyz_to_rgb(SPACE))
            @np.asarray(linear.bradford(linear.white(source),linear.white(SPACE)))
            @np.asarray(linear.rgb_to_xyz(source)))
    from_lut=np.linalg.inv(to_lut)
    to_lut.flags.writeable=False;from_lut.flags.writeable=False
    return to_lut,from_lut


TO_LUT,FROM_LUT=basis()


def model_space(model):
    if hasattr(model,'space'):return model.space
    if hasattr(model,'tone'):return model.tone.space
    return CANONICAL_SPACE


def pack_rgbe(rgb):
    """Signed RGB mantissas plus an exact shared base-2 exponent.

    This is lossless for normal float32 RGB at comparable channel magnitudes.
    Half-float image transport then has relative, rather than scene-dependent
    absolute, precision. Linear RGB is recovered *before* interpolation.
    """
    rgb=np.asarray(rgb,dtype=np.float32)
    magnitude=np.max(abs(rgb),axis=-1)
    _,exponent=np.frexp(magnitude)
    mantissa=np.ldexp(rgb,-exponent[...,None])
    return np.concatenate((mantissa,exponent[...,None]),axis=-1).astype(np.float32)


def unpack_rgbe(rgba):
    rgba=np.asarray(rgba,dtype=np.float32)
    return np.ldexp(rgba[...,:3],rgba[...,3].astype(np.int32)[...,None])


def encode(rgb):
    """Map nonnegative linear RGB to addresses, after address-only bounding."""
    x=np.asarray(rgb,dtype=float)
    if np.any(x<0):raise ValueError('LUT address shaper requires nonnegative coordinates')
    return np.log1p(x/KAPPA)/LOG_RANGE


def decode(value):
    """Inverse input shaper. Atlas output values already are linear RGB."""
    return KAPPA*np.expm1(np.asarray(value,dtype=float)*LOG_RANGE)


def signature(model,size=SIZE):
    if hasattr(model, 'cache_key'):
        key=(SCHEMA,size,SPACE,MINIMUM,MAXIMUM,KAPPA,model_space(model),
             'log1p-linear-rgb-tetrahedral',model.cache_key)
        return hashlib.sha256(repr(key).encode('utf8')).hexdigest()
    key=(SCHEMA,size,SPACE,MINIMUM,MAXIMUM,KAPPA,
         'log1p-linear-rgb-tetrahedral',cm.HK_KNEE,cm.HK_H_LIFT,cm.HK_ENERGY_POWER,
         model.tone.space,model.tone.params,model.params)
    return hashlib.sha256(repr(key).encode('utf8')).hexdigest()


@lru_cache(maxsize=2)
def axis(size=SIZE):
    if size==PREVIEW_SIZE:return axis()[::2]
    if size!=SIZE:raise ValueError('Unsupported LUT grid size')
    values=decode(np.linspace(0,1,SIZE))
    values[0]=MINIMUM;values[-1]=MAXIMUM
    values.flags.writeable=False
    return values


@lru_cache(maxsize=2)
def lattice(size=SIZE):
    grid=np.stack(np.meshgrid(axis(size),axis(size),axis(size),indexing='ij'),-1).reshape(-1,3)
    grid.flags.writeable=False
    return grid


@lru_cache(maxsize=1)
def refinement_indices():
    """Disjoint preview/refinement rows in the final B-fast lattice."""
    shared=np.arange(SIZE**3).reshape(SIZE,SIZE,SIZE)[::2,::2,::2].ravel()
    mask=np.ones(SIZE**3,dtype=bool);mask[shared]=False
    remaining=np.flatnonzero(mask)
    shared.flags.writeable=False;remaining.flags.writeable=False
    return shared,remaining


def cell_coordinates(rgb,size=SIZE):
    """Cell address and barycentric fractions in physical linear RGB.

    Bound only the address calculation. Fractions retain signed/HDR values
    outside [0, 128] and extrapolate the outermost cell continuously.
    """
    rgb=np.asarray(rgb,dtype=float)
    cells=size-1
    position=cells*encode(np.clip(rgb,MINIMUM,MAXIMUM))
    i=np.clip(np.floor(position),0,cells-1).astype(np.int64)
    values=axis(size);lo=values[i];hi=values[i+1]
    return i,(rgb-lo)/(hi-lo)


def tetrahedral(table,rgb):
    """Six tetrahedra with the common 000--111 diagonal, four vertex reads.

    The nonuniform grid locates the cell. Its actual linear RGB endpoints
    define the fractions, retaining exact affine interpolation in real
    arithmetic. Ties prefer R, then G, then B.
    """
    original=np.asarray(rgb,dtype=float);shape=original.shape
    values=np.asarray(table)
    size=round((values.size/3)**(1/3))
    values=values.reshape(size,size,size,3)
    x=original.reshape(-1,3);i,f=cell_coordinates(x,size)
    order=np.argsort(-f,axis=-1,kind='stable')
    first=np.eye(3,dtype=np.int64)[order[:,0]]
    second=np.eye(3,dtype=np.int64)[order[:,1]]
    fs=np.take_along_axis(f,order,axis=-1)
    corners=(i,i+first,i+first+second,i+1)
    vertices=[values[c[:,0],c[:,1],c[:,2]] for c in corners]
    # Equivalent barycentric interpolation with differences. In unsigned-grid
    # extrapolation, large signed weights must not cancel a constant offset.
    out=vertices[0].astype(float,copy=True)
    for a,b,fraction in zip(vertices,vertices[1:],fs.T):
        out+=(b.astype(float)-a.astype(float))*fraction[:,None]
    return out.reshape(shape)


class Cube:
    """Native ACEScg samples with apply() in the model's RGB coordinates."""
    def __init__(self,values,key,space=CANONICAL_SPACE,size=SIZE):
        axis(size)  # Validate the supported nested grids.
        self.size=size
        self.values=np.asarray(values,dtype=np.float32).reshape(size,size,size,3)
        self.signature=key
        self.diagnostics={}
        self.space=space
        self.to_lut,self.from_lut=basis(space)

    def apply(self,rgb):
        return tetrahedral(self.values,np.asarray(rgb)@self.to_lut.T)@self.from_lut.T

    def pixels(self):
        result=np.ones((atlas_height(self.size),ATLAS_WIDTH,4),np.float32)
        result.reshape(-1,4)[:self.size**3,:3]=self.values.reshape(-1,3)
        return result

    def packed_pixels(self):
        """Compositor base and three edge planes, each with its own RGBE.

        Half-float vertex subtraction would erase small first-cell slopes.
        Pack already-computed edge differences instead; runtime still reads
        only one base and three selected edges from this single image.
        """
        fields=[self.values]
        for axis in range(3):
            edge=np.zeros_like(self.values)
            lo=[slice(None)]*3;hi=lo.copy()
            lo[axis]=slice(None,-1);hi[axis]=slice(1,None)
            edge[tuple(lo)]=(self.values[tuple(hi)].astype(float)-self.values[tuple(lo)].astype(float)).astype('f4')
            fields.append(edge)
        result=np.zeros((atlas_height(self.size,4),ATLAS_WIDTH,4),np.float32)
        count=self.size**3
        for plane,field in enumerate(fields):
            result.reshape(-1,4)[plane*count:(plane+1)*count]=pack_rgbe(field.reshape(-1,3))
        return result


class Baker:
    """Incremental bake, optionally with a nested preview and disjoint refinement.

    No Blender objects. Inverse solves compact unresolved rows across the
    complete phase, instead of repeating long tails in independent blocks.
    A worker can finish the pool; edits cancel at numerical checkpoints.
    """
    backend='CPU'
    requires_main_thread=False

    def __init__(self,model,progressive=False):
        self.blocks={};self.tone_key=None
        self.progressive=progressive
        self.restart(model)

    def restart(self,model):
        self._cancelled=Event()
        self._progress=0.
        self.space=model_space(model)
        self.to_lut,self.from_lut=basis(self.space)
        tone_key=(self.space,(model.tone.space,model.tone.params) if getattr(model,'prepared',True) else model.cache_key)
        if tone_key!=self.tone_key:
            self.blocks.clear();self.tone_key=tone_key
        self.model=model;self.signature=signature(model);self.cursor=0
        self.output=np.empty((SIZE**3,3),np.float32)
        self.cube=None
        self.preview=None

    @property
    def progress(self):
        shared=PREVIEW_SIZE**3 if self.preview is not None else 0
        return max(self._progress,(shared+self.cursor)/(SIZE**3))

    def cancel(self):
        self._cancelled.set()

    def checkpoint(self,progress=None):
        if self._cancelled.is_set():raise CancelledError('Obsolete LUT bake')
        if progress is not None:self._progress=max(self._progress,min(.99,max(0,progress)))

    def advance(self):
        self.checkpoint()
        if self.cube is not None:return False
        if self.progressive and self.preview is None:
            shared,_=refinement_indices()
            values=self.evaluate(lattice()[shared]@self.from_lut.T,0,0,len(shared))
            self.output[shared]=values
            self.preview=Cube(values,signature(self.model,PREVIEW_SIZE),self.space,PREVIEW_SIZE)
            self.preview.diagnostics=getattr(self.model,'diagnostics',lambda:{})()
            return True
        pooled=getattr(self.model,'expensive',False)
        block=SIZE**3 if pooled else BLOCK
        remaining=refinement_indices()[1] if self.progressive else None
        total=len(remaining) if remaining is not None else SIZE**3
        begin=self.cursor;end=min(begin+block,total)
        rows=remaining[begin:end] if remaining is not None else slice(begin,end)
        offset=PREVIEW_SIZE**3 if self.progressive else 0
        values=self.evaluate(lattice()[rows]@self.from_lut.T,begin,offset+begin,offset+end)
        self.output[rows]=values
        self.cursor=end
        if end==total:
            self.cube=Cube(self.output,self.signature,self.space)
            self.cube.diagnostics=getattr(self.model,'diagnostics',lambda:{})()
        return self.cube is None

    def evaluate(self,rgb,begin,start,stop):
        if getattr(self.model,'prepared',True):
            prepared=self.blocks.get(begin)
            if prepared is None:
                base={'stage1_rgb':rgb,'stage2_rgb':self.model.tone.apply(rgb)}
                prepared=Prepared(base,self.model);self.blocks[begin]=prepared
            values=prepared.apply(self.model)
        else:
            def checkpoint(progress=None):
                self.checkpoint(None if progress is None else (start+(stop-start)*progress)/(SIZE**3))
            values=self.model.apply(rgb,checkpoint)
        values=np.asarray(values@self.to_lut.T,dtype=np.float32)
        self.checkpoint()
        if not np.isfinite(values).all():raise ArithmeticError('LUT bake produced a nonfinite value')
        return values

    def finish_preview(self):
        if not self.progressive:raise ValueError('Preview requested for a final-only bake')
        while self.preview is None:self.advance()
        return self.preview

    def finish(self):
        while self.cube is None:self.advance()
        return self.cube


class Model:
    """Inspector facade: analytic controls, selected cube for output pixels."""
    def __init__(self,reference,cube):
        self.reference=reference;self.lut=cube
    def __getattr__(self,name):return getattr(self.reference,name)
    def apply(self,rgb):return self.lut.apply(rgb)
