"""Calibrate one a/b grid against two saturation-matched HDR appearance levels."""
import argparse
from pathlib import Path
import numpy as np
from PIL import Image
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument("--output-dir",type=Path,required=True)
OUTPUT=parser.parse_args().output_dir
from color_tools.perceptual_grade_core.model import tone as tm, color as ch
m=ch.model(tm.Parameters(),ch.Parameters(),'Linear Rec.709')
H_DARK=45.;H_BRIGHT=65.;n=65
v,u=np.meshgrid(np.linspace(-1,1,n),np.linspace(-1,1,n),indexing='ij')
# a increases upward; b increases to the LEFT, as requested.
unit=np.stack([v,-u],axis=-1)
def coordinates(radius,H):
    ab=unit*radius;C=np.linalg.norm(ab,axis=-1)
    JA=np.sqrt(np.maximum(0,H_DARK**2-66*C))
    gain=tm.saturation_gain(H_DARK,JA,C,H)
    return np.concatenate([np.full((n,n,1),H),ab*gain[...,None]],axis=-1)
def decode(q):
    # These are absolute chart colors, with no creative departure from q.
    cones,ok=m.decode(q,q);return cones@m.tone.from_cone.T,ok

def boundary(radius):
    rgb,ok=zip(*(decode(coordinates(radius,H)) for H in (H_DARK,H_BRIGHT)))
    return all(a.all() for a in ok) and all(a.min()>=0 and a.max()<=1 for a in rgb)
lo=0.;hi=H_DARK**2/(66*np.sqrt(2))
for _ in range(54):
    mid=(lo+hi)/2
    if boundary(mid):lo=mid
    else:hi=mid
radius=lo
q1=coordinates(radius,H_DARK);q2=coordinates(radius,H_BRIGHT)
rgb1,ok1=decode(q1);rgb2,ok2=decode(q2)
def saturation(q):
    C=np.linalg.norm(q[...,1:],axis=-1)
    return 75*C/np.sqrt(q[...,0]**2-66*C)
sat_error=float(np.max(abs(saturation(q2)-saturation(q1))))
assert sat_error<1e-10 and ok1.all() and ok2.all()
assert boundary(radius) and not boundary(radius*(1+1e-5))
# Endpoint images are decoded physical appearance levels, with no RGB gain.
def rgba(rgb):
    srgb=np.where(rgb<=.0031308,12.92*rgb,1.055*np.maximum(rgb,0)**(1/2.4)-.055)
    return np.concatenate([srgb,np.ones((n,n,1))],axis=-1).astype(np.float32)
OUTPUT.mkdir(parents=True, exist_ok=True)
pixels = np.rint(np.clip(np.concatenate([rgba(rgb1), rgba(rgb2)], axis=0), 0, 1) * 255).astype(np.uint8)
Image.fromarray(pixels, mode='RGBA').save(OUTPUT / 'ab_background.png')
