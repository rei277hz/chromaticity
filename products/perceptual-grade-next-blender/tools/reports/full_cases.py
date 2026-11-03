"""Deterministic full-grade controls and independently constructed stress inputs."""
from dataclasses import replace
import numpy as np
from color_tools.kernel import ColorSettings, WebSettings, LinearSettings, ToneSettings
from . import cases, oracle


def all_active():
    return ColorSettings(
        lightness=((2.,-3.,1.,-.5),(3.,2.,-1.,.5),(-2.,4.,.5,-1.),(1.,-2.,1.,.5)),
        chroma=((.1,-.2,.1,.05),(.2,.1,-.1,.05),(-.1,.2,.05,-.1),(.1,-.1,.1,.05)),
        global_gain=.2, lightness_fit=2., chroma_fit=3.,
        adaptance=((2.,-1.),(-1.,2.),(3.,1.),(-2.,-1.)),
        web=WebSettings(
            log_chroma=tuple(tuple(.12*np.sin(row+col) for col in range(6)) for row in range(4)),
            hue_degrees=tuple(tuple(7.*np.cos(row+col) for col in range(6)) for row in range(4)),
            log_scale=tuple(tuple(.08*np.cos(row-col) for col in range(6)) for row in range(4))))


def saturation_grade():
    return ColorSettings(global_gain=3.,
        adaptance=((-260.8694152832031,0.),(0.,0.),(0.,0.),(0.,0.)),
        web=WebSettings(log_chroma=((16.,)*6,)*4,log_scale=((8.,)*6,)*4))


def maximum_grade():
    """All Color families at authored UI extremes, with valid cyclic hues."""
    return ColorSettings(
        lightness=((30,100,20,20),(50,200,20,20),(100,400,30,30),(200,700,50,50)),
        chroma=((4,16,4,4),(4,16,2,2),(4,16,1,1),(4,16,1,1)),
        global_gain=3., lightness_fit=6., chroma_fit=6.,
        adaptance=saturation_grade().adaptance, adaptance_half_saturation=.05,
        web=replace(all_active().web,log_chroma=((16.,)*6,)*4,log_scale=((8.,)*6,)*4))


def maximum_grade_active_tail():
    """Exercise nonidentity exterior normalization at maximal-family controls."""
    maximum = maximum_grade()
    return replace(maximum, adaptance=(*maximum.adaptance[:-1], all_active().adaptance[-1]))


def grades():
    for name,linear,tone in cases.grades():
        yield name,linear,tone,ColorSettings()
    base=all_active();linear,tone=LinearSettings(),ToneSettings()
    for name in ('lightness','chroma','adaptance'):
        yield name,linear,tone,replace(ColorSettings(),**{name:getattr(base,name)})
    yield 'global_gain',linear,tone,ColorSettings(global_gain=.7)
    for name in ('log_chroma','hue_degrees','log_scale'):
        yield 'web_'+name,linear,tone,ColorSettings(web=WebSettings(**{name:getattr(base.web,name)}))
    yield 'all_active',list(cases.grades())[5][1],list(cases.grades())[5][2],base
    yield 'saturation',linear,tone,saturation_grade()
    combined = next(row for row in cases.grades() if row[0] == 'combined')
    yield 'all_active_saturation', combined[1], combined[2], replace(base,
        adaptance=saturation_grade().adaptance,
        web=replace(base.web, log_chroma=((16.,)*6,)*4, log_scale=((8.,)*6,)*4))


def ui_boundaries():
    for name, linear, tone in cases.ui_boundaries():
        yield name, linear, tone, ColorSettings()
    linear,tone=LinearSettings(),ToneSettings()
    light=np.array(((30,100,20,20),(50,200,20,20),(100,400,30,30),(200,700,50,50)))
    chroma=np.array(((4,16,4,4),(4,16,2,2),(4,16,1,1),(4,16,1,1)))
    for name,limits in (('lightness',light),('chroma',chroma)):
        for row in range(4):
            for column in range(4):
                for sign in (-1,1):
                    values=np.zeros((4,4));values[row,column]=sign*limits[row,column]
                    yield f'{name}_{row}_{column}_{sign:+d}',linear,tone,ColorSettings(**{name:tuple(map(tuple,values))})
        for fit in (-2,6):
            signed=limits*np.array((1,-1,1,-1))[:,None]
            yield f'{name}_fit_{fit}',linear,tone,ColorSettings(**{
                name:tuple(map(tuple,signed)),name+'_fit':fit})
    for gain in (-3,3):
        yield f'global_{gain:+d}',linear,tone,ColorSettings(global_gain=gain)
    for half in (.05,1.):
        yield f'adaptance_half_{half}',linear,tone,replace(ColorSettings(),
            adaptance=all_active().adaptance,adaptance_half_saturation=half)
    for name,limit in (('log_chroma',16.),('log_scale',8.)):
        for sign in (-1,1):
            yield f'web_{name}_{sign:+d}',linear,tone,ColorSettings(web=WebSettings(**{name:((sign*limit,)*6,)*4}))
    # Uniform rotations at either UI endpoint retain strict cyclic order.
    for angle in (-360.,360.):
        yield f'web_rotation_{angle:g}',linear,tone,ColorSettings(web=WebSettings(hue_degrees=((angle,)*6,)*4))
    yield 'web_alternating_extremes',linear,tone,ColorSettings(web=WebSettings(
        log_chroma=tuple(tuple(16.*(-1)**(row+col) for col in range(6)) for row in range(4)),
        log_scale=tuple(tuple(8.*(-1)**(row+col) for col in range(6)) for row in range(4))))
    combined = next(row for row in cases.grades() if row[0] == 'combined')
    yield 'all_families_max', combined[1], combined[2], maximum_grade()
    yield 'all_families_max_active_tail', combined[1], combined[2], maximum_grade_active_tail()


def rgba(space='Linear Rec.709',count=1024):
    values=cases.rgba(count)
    from color_tools.perceptual_grade_reference import appearance,grading
    from color_tools.perceptual_grade_reference.responses import signed_hk
    white,_,after=oracle.adapters(space)
    ja=float(grading.Tone(grading.ToneSettings()).target[1])*100
    angle=np.arange(4)*np.pi/2
    q=np.column_stack((np.full(4,signed_hk(ja,1.)),np.cos(angle),np.sin(angle)))
    values[-4:,:3]=(appearance.decode(q,np.full(4,ja*ja),white,203.)@after.T).astype(np.float32)
    return values
