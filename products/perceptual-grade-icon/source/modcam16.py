"""Standalone modCAM16 math matching Perceptual Grade 1.11.10.

Equations and constants follow the user's supplied src/blender/model/tone.py,
linear.py, and src/dctl/foundation.dctlh. GPL-3.0-or-later; see source/LICENSE.
Inputs and outputs use scene-linear sRGB/Rec.709 with D65, white RGB=(1,1,1).
Default viewing: reference 203 nits; LA=20.3; dark c=.525, Nc=.8; D=1.
Coordinates: H=J_HK, a=C*cos(h), b=C*sin(h), with true modCAM16 chroma C.
The adapted equations are GPL-3.0-or-later under the repository's
Perceptual Grade product license.
"""
import numpy as np

REFERENCE_NITS=203.0
D65=(.3127,.3290)
GAMMA=.943019577159
CAT16=np.array(((.401288,.650173,-.051461),
                (-.250268,1.204414,.045854),
                (-.002079,.048952,.953127)),dtype=float)
PRIMARIES=np.array(((.64,.33),(.30,.60),(.15,.06)),dtype=float)


def rgb_matrices():
    primary_xyz=np.stack((PRIMARIES[:,0]/PRIMARIES[:,1],
                          np.ones(3),
                          (1-PRIMARIES.sum(axis=1))/PRIMARIES[:,1]),axis=0)
    white=np.array((D65[0]/D65[1],1,(1-sum(D65))/D65[1]))
    scale=np.linalg.solve(primary_xyz,white)
    rgb_xyz=primary_xyz*scale[None,:]
    white_cones=CAT16@white
    to_cone=(CAT16@rgb_xyz)/white_cones[:,None]
    from_cone=np.linalg.inv(to_cone)
    return rgb_xyz,white_cones,to_cone,from_cone


RGB_TO_XYZ,WHITE_CONES,TO_CONE,FROM_CONE=rgb_matrices()
LA=.1*REFERENCE_NITS
K=1/(5*LA+1)
FL=.2*K**4*5*LA+.1*(1-K**4)**2*(5*LA)**(1/3)
AW=3.05*400*FL**.42/(27.13+FL**.42)


def response(cones):
    p=(FL*np.abs(cones))**.42
    return np.sign(cones)*400*p/(27.13+p)


def eccentricity(co,si):
    co2=co*co-si*si;si2=2*co*si
    co3=co2*co-si2*si;si3=si2*co+co2*si
    co4=co2*co2-si2*si2;si4=2*co2*si2
    return (1-.0582*co-.0258*co2-.1347*co3+.0289*co4
            -.1475*si-.0308*si2+.0385*si3+.0096*si4)


def linear_to_cam16(rgb):
    """Return H,a,b; matches the extension's forward appearance coordinates."""
    rgb=np.asarray(rgb,dtype=float)
    s=response(rgb@TO_CONE.T)
    a=(s[...,0]-s[...,1])+(s[...,2]-s[...,1])/11
    b=((s[...,0]-s[...,2])+(s[...,1]-s[...,2]))/9
    ach=2*s[...,0]+s[...,1]+.05*s[...,2]
    ja=100*(np.maximum(ach,0)/AW)**GAMMA
    radius=np.hypot(a,b)
    co=np.divide(a,radius,out=np.zeros_like(a),where=radius>0)
    si=np.divide(b,radius,out=np.zeros_like(b),where=radius>0)
    C=1204*eccentricity(co,si)*radius/AW
    return np.stack((np.sqrt(ja*ja+66*C),C*co,C*si),axis=-1)


def cam16_to_linear(JA,a,b):
    """Invert achromatic lightness JA and native a/b without creative grading.

    JA uses [0,100] reference units. Invalid response poles return NaN.
    Searching JA rather than H guarantees nonnegative H-K achromatic energy.
    """
    JA,a,b=np.broadcast_arrays(JA,a,b)
    C=np.hypot(a,b)
    co=np.divide(a,C,out=np.zeros_like(a,dtype=float),where=C>0)
    si=np.divide(b,C,out=np.zeros_like(b,dtype=float),where=C>0)
    ach=AW*(np.maximum(JA,0)/100)**(1/GAMMA)
    scale=AW/(1204*eccentricity(co,si))
    ar,br=a*scale,b*scale
    s=np.stack(((460*ach+451*ar+288*br)/1403,
                (460*ach-891*ar-261*br)/1403,
                (460*ach-220*ar-6300*br)/1403),axis=-1)
    abs_s=np.abs(s)
    safe=np.minimum(abs_s,399.998)
    cones=np.sign(s)*(27.13*safe/(400-safe))**(1/.42)/FL
    rgb=cones@FROM_CONE.T
    return np.where((np.max(abs_s,axis=-1)<399.998)[...,None],rgb,np.nan)


def inverse_hab(q):
    q=np.asarray(q,dtype=float)
    H,a,b=np.moveaxis(q,-1,0)
    JA=np.sqrt(np.maximum(0,H*H-66*np.hypot(a,b)))
    return cam16_to_linear(JA,a,b)
