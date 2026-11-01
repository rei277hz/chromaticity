"""Legacy-capacity forced-pair LUT study for the current production equations."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from functools import lru_cache
import numpy as np
from color_tools.perceptual_grade_reference.export import input_repair
from color_tools.perceptual_grade_reference.grading import ToneSettings
from color_tools.perceptual_grade_reference.grading import ColorSettings
from color_tools.perceptual_grade_core.model.tonal_web import WebSettings
from color_tools.perceptual_grade_reference.model import Settings,LinearSettings
from color_tools.perceptual_grade_reference.stack import matrix_native
from tests.reference.legacy_capacity import LegacyCapacityBakeStack
from color_tools.perceptual_grade_blender.model.bake_inverse_gpu import Program as ReferenceGPUProgram
from color_tools.perceptual_grade_core.model import bake_inverse


class ForcedStack(LegacyCapacityBakeStack):
    """Exercise the real raw inverse even when matching settings could cancel."""
    def __init__(self, *args, program_factory=ReferenceGPUProgram, **kwargs):
        super().__init__(*args, program_factory=program_factory, **kwargs)

    def matching(self,left,right):return False


def cases():
    tone=ToneSettings(input_nits=(0.,7.,45.,203.,1000.))
    mixed=Settings(color=ColorSettings(global_gain=.15,web=WebSettings(
            hue_degrees=((0.,)*6,(3.,2.,1.,-1.,-2.,0.),(0.,)*6,(0.,)*6),
            log_chroma=((0.,)*6,(.03,0.,-.02,0.,.01,0.),(0.,)*6,(0.,)*6),
            log_scale=((0.,)*6,(0.,)*6,(.02,0.,0.,-.01,0.,0.),(0.,)*6)),
        adaptance=((0.,0.),(0.,0.),(0.,.01),(0.,0.)),
        lightness=((0.,0.,0.,0.),(0.,.1,0.,0.),(0.,0.,0.,0.),(0.,0.,0.,0.))))
    return dict(reset=Settings(),exposure=Settings(linear=LinearSettings(exposure=2.)),
        tone=Settings(tone=tone),chroma=Settings(color=ColorSettings(global_gain=.25)),
        hue=Settings(color=ColorSettings(web=WebSettings(hue_degrees=((8.,)*6,)*4))),mixed=mixed,
        mixed_tone=replace(mixed,tone=tone),strong_chroma=Settings(color=ColorSettings(global_gain=3.)))


@lru_cache(maxsize=2)
def axis(size=65):
    if size<2:raise ValueError('A LUT needs at least two samples per axis')
    values=.01*np.expm1(np.linspace(0,1,size)*np.log1p(1024/.01))
    values[0],values[-1]=0.,1024.;values.flags.writeable=False
    return values


def lattice(size=65):
    """B-fast native AP1 lattice, rounded once for the float32 baker."""
    return np.stack(np.meshgrid(axis(size),axis(size),axis(size),indexing='ij'),-1).reshape(-1,3).astype('f4')


def _addresses(prepared_rgb,size):
    rgb=np.asarray(prepared_rgb,dtype=float)
    if rgb.shape[-1:]!=(3,) or not np.isfinite(rgb).all() or np.any((rgb<0)|(rgb>1024)):
        raise ValueError('LUT interpolation needs repaired finite AP1 RGB in [0,1024]')
    x=rgb.reshape(-1,3);grid=axis(size)
    position=(size-1)*np.log1p(x/.01)/np.log1p(1024/.01)
    cell=np.clip(np.floor(position),0,size-2).astype(np.int64)
    fraction=np.clip((x-grid[cell])/(grid[cell+1]-grid[cell]),0,1)
    order=np.argsort(-fraction,axis=-1,kind='stable')
    first=np.eye(3,dtype=np.int64)[order[:,0]]
    second=np.eye(3,dtype=np.int64)[order[:,1]]
    corners=(cell,cell+first,cell+first+second,cell+1)
    return rgb,corners,np.take_along_axis(fraction,order,axis=-1)


def _blend(vertices,fractions):
    result=vertices[0].astype(float,copy=True)
    for a,b,f in zip(vertices,vertices[1:],fractions.T):
        result+=(b.astype(float)-a.astype(float))*f[:,None]
    return result


def tetrahedral(values,prepared_rgb):
    """Interpolate repaired AP1 inputs using physical, not logarithmic, fractions.

    This small numerical counterpart follows the current six-tetrahedron LUT
    contract, with the common 000--111 diagonal and R/G/B tie priority. Input
    repair belongs to prepare(), so an accidental out-of-domain input fails.
    """
    table=np.asarray(values);size=round((table.size/3)**(1/3))
    if size<2 or table.size!=3*size**3:raise ValueError('Expected a complete RGB cube')
    table=table.reshape(size,size,size,3)
    rgb,corners,fractions=_addresses(prepared_rgb,size)
    vertices=[table[p[:,0],p[:,1],p[:,2]] for p in corners]
    result=_blend(vertices,fractions)
    return result.reshape(rgb.shape)


def vertex_diagnostic(cube,prepared_rgb):
    """Audit one lookup from saved RGB+raw-residual vertices, without rebaking.

    Source errors use the float32 lattice inputs actually sent to the baker.
    grid_roundoff distinguishes their interpolation from the float64 grid used
    for addressing. Failed vertices include all four, even at zero weight.
    """
    table=np.asarray(cube);size=round((table.size/4)**(1/3))
    if table.shape[-1:]!=(4,) or size<2 or table.size!=4*size**3:
        raise ValueError('Expected a complete saved RGB+residual cube')
    rgb=np.asarray(prepared_rgb,dtype=float)
    if rgb.size!=3:raise ValueError('A vertex diagnostic needs exactly one RGB pixel')
    rgb,corners,fractions=_addresses(rgb.reshape(1,3),size)
    indices=np.stack(corners,axis=1)[0];table=table.reshape(size,size,size,4)
    selected=table[indices[:,0],indices[:,1],indices[:,2]]
    coordinates=axis(size)[indices].astype('f4')
    f=fractions[0];weights=np.array([1-f[0],f[0]-f[1],f[1]-f[2],f[2]])
    errors=selected[:,:3].astype(float)-coordinates.astype(float)
    weighted=weights[:,None]*errors;neutral=np.all(indices==indices[:,:1],axis=1)
    predicted=_blend([value[None,:3] for value in selected],fractions)[0]
    return dict(input=rgb[0].tolist(),indices=indices.tolist(),coordinates=coordinates.tolist(),
        weights=weights.tolist(),selected_rgb=selected[:,:3].tolist(),residuals=selected[:,3].tolist(),
        source_errors=errors.tolist(),weighted_source_errors=weighted.tolist(),neutral=neutral.tolist(),
        neutral_weight=float(weights[neutral].sum()),failed_vertices=int(np.count_nonzero(selected[:,3]>bake_inverse.TOLERANCE)),
        predicted_core=predicted.tolist(),weighted_error=weighted.sum(axis=0).tolist(),
        grid_roundoff=(weights@coordinates.astype(float)-rgb[0]).tolist())


def endpoint(stack,core_rgb):
    """Apply inverse Stage 1 once; deliberately retain signed/HDR output."""
    rgb=np.asarray(core_rgb)
    if rgb.shape[-1:]!=(3,):raise ValueError('Endpoint expects RGB without the residual column')
    return stack.matrix(rgb,stack.output_matrix)


def prepare(stack,values):
    """Separate the float64 repair-aware ideal from float32 execution inputs."""
    if (stack.directions!=('FORWARD','INVERSE') or
            stack.models[0].settings!=stack.models[1].settings):
        raise ValueError('The reset ideal requires an identical forward/inverse pair')
    original=np.asarray(values,dtype=float)
    if original.shape[-1:]!=(3,) or not np.isfinite(original).all():raise ValueError('Expected finite RGB triples')
    matrix=matrix_native(stack.models[0]);linear=original@matrix.T
    repaired=input_repair(linear,stack.models[0].acescg_y)
    ideal=repaired@np.linalg.inv(matrix).T
    prepared=stack.solvers[0].repair(stack.matrix(original.astype('f4'),stack.input_matrix))
    return dict(ideal=ideal,input=prepared,prepared=endpoint(stack,prepared),
        linear=linear,repaired=repaired,repair_changed=np.any(repaired!=linear,axis=-1),
        repair_delta=ideal-original)


def eval_core(stack,prepared_rgb,backend='CPU',chunk=4096):
    """Evaluate spatial arrays; CPU has four workers, GPU dispatch is sequential."""
    if backend not in ('CPU','GPU') or chunk<=0:raise ValueError('Invalid backend or chunk size')
    rgb=np.asarray(prepared_rgb,dtype='f4')
    if rgb.shape[-1:]!=(3,) or not np.isfinite(rgb).all():raise ValueError('Expected finite RGB triples')
    shape=rgb.shape[:-1];rows=rgb.reshape(-1,3)
    if not len(rows):return np.empty((*shape,4),dtype='f4')
    pieces=[rows[i:i+chunk] for i in range(0,len(rows),chunk)]
    if backend=='CPU':
        with ThreadPoolExecutor(max_workers=4,thread_name_prefix='PG photo inverse') as pool:
            result=list(pool.map(stack.bake_native,pieces))
    else:result=[stack.bake_native(part,'GPU') for part in pieces]
    return np.concatenate(result).reshape(*shape,4)
