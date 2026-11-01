"""Regular Grade adapters for photographic numerical error measurements."""
import numpy as np
from color_tools.perceptual_grade_core.model import color, linear, tone, transforms
from color_tools.perceptual_grade_reference.model import WHITES,linear_matrix,xyz_from_xy


def extension_settings(settings):
    """Translate every reference control; preserve the complete XYZ Stage 1."""
    if settings.white!='D65':raise ValueError('This experiment uses cached D65 only')
    t,c=settings.tone,settings.color
    tonal=tone.Parameters(**dict(zip(tone.LEVEL_FIELDS,t.input_nits)),
        fit=t.fit,reference_nits=t.reference_nits,peak_nits=t.peak_nits)
    controls=dict(j_fit=c.lightness_fit,c_fit=c.chroma_fit,global_gain=c.global_gain,
        adaptance_half_saturation=c.adaptance_half_saturation)
    for family,values in (('j',c.lightness),('c',c.chroma)):
        for i,row in enumerate(values):
            controls.update({f'{family}_{driver}_{i}':value
                for driver,value in zip(('low','high','a','b'),row)})
    for i,row in enumerate(c.adaptance):
        controls.update({f'adaptance_{axis}_{i}':value for axis,value in zip('ab',row)})
    for stem,name in (('chroma','log_chroma'),('hue','hue_degrees'),('scale','log_scale')):
        for i,row in enumerate(getattr(c.web,name)):
            controls.update({f'web_{stem}_{i}_{j}':v for j,v in enumerate(row)})
    matrix=linear_matrix(settings.linear,xyz_from_xy(WHITES[settings.white]))
    return transforms.Settings(tuple(map(tuple,np.asarray(matrix,dtype=float))),
        tonal,color.Parameters(**controls),linear.GradeSpace('D65'))


def extension_model(settings):
    """The regular node's one-forward Stack, including its extracted matrix."""
    return transforms.Stack([extension_settings(settings)])


def _divide(a,b):
    a,b=np.broadcast_arrays(a,b)
    return np.divide(a,b,out=np.zeros(a.shape,dtype=np.float32),where=b!=0)


def prepare(model,native):
    """Numerically apply graph.repair_input to native AP1 in float32.

    Stage 1 stays outside the baked nonlinear LUT. Normalize the source before
    its matrix, project negative channels toward neutral, then bound the peak.
    This reproduces the graph's mathematical operations, not Blender's shader
    fusion or texture transport. There is deliberately no extra final clip:
    callers must report any float32 boundary overshoot before addressing.
    """
    if len(model.grades)!=1 or model.directions!=('FORWARD',):
        raise ValueError('Regular forward Grade required')
    x=np.asarray(native,dtype=np.float32)
    matrix=np.asarray(model.input_matrix,dtype=np.float32)
    if x.shape[-1:]!=(3,) or not np.isfinite(x).all() or not np.isfinite(matrix).all():
        raise ValueError('Expected finite float32 RGB and Stage 1 matrix')
    amplitude=np.max(abs(x),axis=-1)
    u=_divide(x,amplitude[...,None])
    unit=(u[...,0,None]*matrix[:,0]+u[...,1,None]*matrix[:,1])+u[...,2,None]*matrix[:,2]
    weights=np.asarray(model.grades[0].forward.acescg_y,dtype=np.float32)
    y=np.maximum(np.float32(0),(unit[...,0]*weights[0]+unit[...,1]*weights[1])+unit[...,2]*weights[2])
    k=np.maximum(np.float32(0),-np.min(unit,axis=-1))
    lifted=(unit+k[...,None])*_divide(y,y+k)[...,None]
    peak=np.max(lifted,axis=-1)
    factor=np.minimum(amplitude,_divide(np.float32(1024),peak))
    return lifted*factor[...,None]
