"""Signed creative grading with unchanged control names and UI ranges."""
from color_tools.perceptual_grade_core.localization.catalogs import M
from color_tools.perceptual_grade_core.localization.controls import control_label
from dataclasses import make_dataclass
from functools import lru_cache, cached_property
import math
import numpy as np
from color_tools.perceptual_grade_core.model import tone as tm

TONES=('Shadows','Midtones','White','Highlights')
CHROMA_CROSSOVER=.4
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


# DCTL-facing metadata is independent of Blender's Warp controls.
for family, limit in (('j',50.),('c',4.)):
    for axis in 'ab':
        for tone in range(4):
            field=f'{family}_{axis}_{tone}';old=META[field]
            META[field]=(*old[:3],-limit,limit,*old[5:])
def meta(field):return META[field]
def step(field):
    if field=='adaptance_strength':return .05
    return 1. if meta(field)[5]==0 else None
