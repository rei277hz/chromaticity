"""Deterministic full-grade controls and independently constructed stress inputs."""
from dataclasses import replace
import numpy as np
from color_tools.kernel import ColorSettings, WebSettings, LinearSettings, ToneSettings
from color_tools.kernel.settings import TONE_CHROMA_LIMITS
from . import cases, oracle


def all_active():
    return ColorSettings(
        adaptance=((2.,-1.),(-1.,2.),(3.,1.),(-2.,-1.)),
        web=WebSettings(
            log_chroma=tuple(tuple(.12*np.sin(row+col) for col in range(6)) for row in range(4)),
            hue_degrees=tuple(tuple(7.*np.cos(row+col) for col in range(6)) for row in range(4)),
            log_scale=tuple(tuple(.08*np.cos(row-col) for col in range(6)) for row in range(4))))


def saturation_grade():
    return ColorSettings(
        adaptance=((-260.8694152832031,0.),(0.,0.),(0.,0.),(0.,0.)),
        web=WebSettings(log_chroma=((16.,)*6,)*4,log_scale=((8.,)*6,)*4))


def guard_before_scale_grade():
    """An active Adaptance/Scale request that distinguishes repair order."""
    return ColorSettings(
        adaptance=((3., -1.), (-2., 2.), (4., 1.), (-3., -2.)),
        web=WebSettings(log_chroma=((.5,)*6,)*4, log_scale=((2.,)*6,)*4))


def maximum_grade():
    """All Color families at authored UI extremes, with valid cyclic hues."""
    return ColorSettings(
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
    yield 'adaptance',linear,tone,ColorSettings(adaptance=base.adaptance)
    for name in ('log_chroma','hue_degrees','log_scale'):
        yield 'web_'+name,linear,tone,ColorSettings(web=WebSettings(**{name:getattr(base.web,name)}))
    _, combined_linear, combined_tone = next(row for row in cases.grades() if row[0] == 'combined')
    active_tone = replace(combined_tone, black_compression_nits=.25,
        muted_gain=-.3, vivid_gain=.4, saturation_crossover=.45,
        shadow_chroma=.2, highlight_chroma=-.15, tone_crossover=52.)
    yield 'all_active',combined_linear,active_tone,base
    yield 'guard_before_scale',linear,tone,guard_before_scale_grade()
    yield 'saturation',linear,tone,saturation_grade()
    yield 'all_active_saturation', combined_linear, active_tone, replace(base,
        adaptance=saturation_grade().adaptance,
        web=replace(base.web, log_chroma=((16.,)*6,)*4, log_scale=((8.,)*6,)*4))


def ui_boundaries():
    for name, linear, tone in cases.ui_boundaries():
        yield name, linear, tone, ColorSettings()
    linear,tone=LinearSettings(),ToneSettings()
    chromatic_tone = replace(tone, muted_gain=-1., vivid_gain=1.,
                             shadow_chroma=-1., highlight_chroma=1.)
    for name, limits in TONE_CHROMA_LIMITS.items():
        for value in limits:
            yield f'{name}_{value:g}',linear,replace(chromatic_tone, **{name: value}),ColorSettings()
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
    _, combined_linear, combined_tone = next(row for row in cases.grades() if row[0] == 'combined')
    maximum_tone = replace(combined_tone, fit=2., black_compression_nits=2.,
        muted_gain=-2., vivid_gain=2., saturation_crossover=.05,
        shadow_chroma=2., highlight_chroma=2., tone_crossover=10.)
    yield 'all_families_max', combined_linear, maximum_tone, maximum_grade()
    yield 'all_families_max_active_tail', combined_linear, maximum_tone, maximum_grade_active_tail()


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
