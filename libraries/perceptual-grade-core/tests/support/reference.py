"""Independent Colour oracle for production Blender grading with legacy .4U selectors."""
import numpy as np
from color_tools.perceptual_grade_reference import model, grading
from color_tools.perceptual_grade_core.model.tonal_web import WebSettings
from color_tools.perceptual_grade_reference.export import input_repair
from tests.reference.legacy_capacity import LegacyCapacityModel, LegacyCapacityStack, legacy_drivers


def tone_settings(p):
    return grading.ToneSettings(tuple(getattr(p,'input_'+level) for level in
                                     ('black','shadows','midtones','white','highlights')),
                                p.fit,p.reference_nits,p.peak_nits)


def color_settings(p):
    table=lambda stem:tuple(tuple(getattr(p,f'{stem}_{key}_{i}') for key in ('low','high','a','b')) for i in range(4))
    pairs=lambda stem:tuple(tuple(getattr(p,f'{stem}_{axis}_{i}') for axis in 'ab') for i in range(4))
    web = WebSettings(**{name: tuple(tuple(getattr(p,f'{stem}_{i}_{j}') for j in range(6))
                              for i in range(4))
                         for name,stem in (('log_chroma','web_chroma'),('hue_degrees','web_hue'),
                                           ('log_scale','web_scale'))})
    return grading.ColorSettings(lightness=table('j'), chroma=table('c'),
        adaptance=pairs('adaptance'), lightness_fit=p.j_fit, chroma_fit=p.c_fit,
        global_gain=p.global_gain, adaptance_half_saturation=p.adaptance_half_saturation, web=web)


def white_name(space):
    return space.preset if hasattr(space,'preset') else ('ACES' if space=='ACEScg' else 'D65')


def matrix(p,space):
    settings=model.LinearSettings(p.exposure,(p.source_x,p.source_y),(-p.cr_balance,-p.yb_balance),
                                 (p.cr_spread,p.yb_spread),(p.cr_heading,p.yb_heading))
    return model.linear_matrix(settings,model.xyz_from_xy(model.WHITES[white_name(space)]))


def evaluator(tp,cp,space,matrix_value=None):
    white=white_name(space)
    settings=model.Settings(white,model.LinearSettings(matrix=tuple(map(tuple,np.eye(3) if matrix_value is None else matrix_value))),
                            tone_settings(tp),color_settings(cp))
    engine=LegacyCapacityModel(settings,'Linear Rec.709' if hasattr(space,'preset') else space,hk_guard=True)
    if hasattr(space,'preset'):
        # Independent Colour NPM + Bradford adapter; never use Blender matrices.
        npm=(model.adaptation(model.xyz_from_xy(model.WHITES['D65']),engine.white,'Bradford')
             @model.rgb_matrix('Linear Rec.709'))
    else:npm=model.rgb_matrix(space)
    engine.native_matrix=(np.linalg.inv(model.rgb_matrix('ACEScg'))
                          @model.adaptation(engine.white,model.xyz_from_xy(model.WHITES['ACES']),'Bradford')
                          @engine.cones_to_xyz)
    inverse=np.linalg.inv(npm)
    # The adapter's RGB is calibrated to the grading white, including exact
    # neutral rows; its independently derived primary matrix remains Colour's.
    if hasattr(space,'preset'):
        engine.rgb_to_xyz,engine.xyz_to_rgb,engine.rgb_white=npm,inverse,engine.white
    return engine,npm,inverse


def grade(rgb,lp,tp,cp,space='Linear Rec.709'):
    engine,before,after=evaluator(tp,cp,space,matrix(lp,space))
    return engine._forward(rgb,before,after)


def settings(rgb,value,export=True,entry=True):
    engine,before,after=evaluator(value.tone,value.color,value.space,value.matrix)
    return engine._forward(rgb,before,after,export=export,entry=entry)


def native_settings(rgb,value,export=True,entry=True):
    engine,_,_=evaluator(value.tone,value.color,value.space,value.matrix)
    return engine.forward_native(rgb,export,entry)


def stack(rgb,values,directions=None):
    settings=[]
    for value in values:
        engine,_,_=evaluator(value.tone,value.color,value.space,value.matrix)
        settings.append(engine.settings)
    return LegacyCapacityStack(settings,directions,hk_guard=True).apply(rgb)


def nonlinear(rgb,tp,cp,space='Linear Rec.709'):
    engine,before,after=evaluator(tp,cp,space)
    return engine._forward(rgb,before,after)


def error(actual,expected):
    return np.max(abs(np.asarray(actual)-expected),axis=-1)/(1+np.max(abs(expected),axis=-1))


def lut(rgb,value,size=65,linear_stage=True):
    """Independent input repair, native float32 vertices and convex tetrahedra."""
    rgb=np.asarray(rgb,dtype=float)
    to_lut=(np.linalg.inv(model.rgb_matrix('ACEScg'))
            @model.adaptation(model.xyz_from_xy(model.WHITES['D65']),model.xyz_from_xy(model.WHITES['ACES']),'Bradford')
            @model.rgb_matrix('Linear Rec.709'))
    axis=.01*np.expm1(np.linspace(0,1,size)*np.log1p(1024/.01));axis[0],axis[-1]=0.,1024.
    engine,_,_=evaluator(value.tone,value.color,value.space,value.matrix)
    native=engine.input_native(rgb,apply_linear=True) if linear_stage else input_repair(rgb@to_lut.T,model.rgb_matrix('ACEScg')[1])
    if linear_stage:
        from dataclasses import replace
        value=replace(value,matrix=tuple(map(tuple,np.eye(3))))
    cell=np.clip(np.searchsorted(axis,np.clip(native,0,1024),side='right')-1,0,size-2)
    fraction=np.clip((native-axis[cell])/(axis[cell+1]-axis[cell]),0,1)
    order=np.argsort(-fraction,axis=-1,kind='stable')
    vertices=[cell.copy()];cursor=cell.copy()
    for i in range(3):
        step=np.eye(3,dtype=int)[order[...,i]]
        cursor=cursor+step;vertices.append(cursor.copy())
    from_lut=np.linalg.inv(to_lut)
    points=np.stack([axis[v] for v in vertices],axis=-2)
    outputs=native_settings(points,value).astype(np.float32).astype(float)
    result=outputs[...,0,:].copy()
    for i in range(3):
        result+=np.take_along_axis(fraction,order[...,i,None],axis=-1)*(outputs[...,i+1,:]-outputs[...,i,:])
    return result@from_lut.T
