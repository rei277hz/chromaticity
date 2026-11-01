"""Historical p=1.001, d=20 radial experiment; excluded from active grading.

Retained unchanged for reproducible diagnostics and its corresponding Lean
proofs. The active reference and Blender production use the cubic in spindle.py.
"""
import numpy as np

RADIAL_POLE = 1001./1000.
RADIAL_SHAPE = 1.
RADIAL_BOUNDARY_SLOPE = 20.
_POLE_SQUARED = 1002001./1000000.
_POLE_GAP = 2001./1000000.
_RADIAL_BLEND = (RADIAL_BOUNDARY_SLOPE-1)*_POLE_GAP
_RADIAL_A = _POLE_SQUARED+1-2*_RADIAL_BLEND
_RADIAL_B = _POLE_SQUARED-3+2*_RADIAL_BLEND



def _pole_profile(z):
    """F(z)=z(A+Bz)/((1+z)(p²-z)); F'(1)=RADIAL_BOUNDARY_SLOPE.

    Evaluate as a convex blend to avoid cancellation in A+Bz near z=1.
    The blend controls boundary slope independently of the pole position.
    """
    denominator=_POLE_GAP+(1-z)
    base=z+z*(1-z)**2/((RADIAL_SHAPE+z)*denominator)
    pole=z*_POLE_GAP/denominator
    return (1-_RADIAL_BLEND)*base+_RADIAL_BLEND*pole


def _release_radius(x, k):
    """Unclipped C_cube/B from C_spindle/B, on 0 <= x < p.

    The k=1 identity has no pole. This analytic extension is separate from
    the physical-domain clipping in radius_map and from the grading guard.
    """
    x,k=np.broadcast_arrays(np.asarray(x,dtype=float),np.asarray(k,dtype=float))
    out=x.copy();active=(k>1)&(x>0)
    z=x[active]**2
    out[active]=x[active]*np.hypot(1.,np.sqrt(k[active]-1)*np.sqrt(k[active]+1)*np.sqrt(_pole_profile(z)))
    return out


def _compress_radius(y, k):
    """Unclipped C_spindle/B from C_cube/B; explicit cubic, no iteration.

    The cosine expression selects the largest cubic root L (> p²). The
    positive root of the remaining quadratic is the physical squared radius.
    Rationalizing that root retains the linear limit without cancellation.
    Factoring r out of its square root also preserves very small chroma.
    """
    y,k=np.broadcast_arrays(np.asarray(y,dtype=float),np.asarray(k,dtype=float))
    out=y.copy();active=(k>1)&(y>0)
    ka=k[active];r=y[active]/ka;inv=1/ka;t=inv*inv
    gain=(1-inv)*(1+inv);p=_POLE_SQUARED;c=RADIAL_SHAPE
    a3=-t+gain*_RADIAL_B
    a2=t*_POLE_GAP+gain*_RADIAL_A+r*r
    a1=t*c*p-r*r*_POLE_GAP
    # The usual acos invariant loses several digits when the largest root is
    # close to the pole.  Evaluate the same trigonometric solution from the
    # two cubic extrema instead.  Their values are positive sums, so this
    # remains stable for the narrow pole while retaining a closed form.
    discriminant=a2*a2-3*a3*a1
    sqrt_discriminant=np.sqrt(discriminant)
    pole_gap=_POLE_GAP
    derivative_at_p=(1+p)*(r*r-p)+gain*p*pole_gap*(
        2*(RADIAL_BOUNDARY_SLOPE-1)
        +3*(2*RADIAL_BOUNDARY_SLOPE-1)*pole_gap)
    h=a2+3*a3*p
    delta_max=np.empty_like(h);near=h<=0
    delta_max[near]=derivative_at_p[near]/(sqrt_discriminant[near]-h[near])
    delta_max[~near]=(-h[~near]-sqrt_discriminant[~near])/(3*a3[~near])
    maximum=(gain*p*p*(2*RADIAL_BOUNDARY_SLOPE-1)*pole_gap*pole_gap
             +delta_max*delta_max*(2*sqrt_discriminant-h)/3)
    minimum_location=-a1/(a2+sqrt_discriminant)
    negative_minimum=(r*r*p
                      +minimum_location*minimum_location
                      *(a2+2*sqrt_discriminant)/3)
    theta=np.arctan2(2*np.sqrt(maximum)*np.sqrt(negative_minimum),
                      maximum-negative_minimum)/3
    large=(a2+2*sqrt_discriminant*np.cos(theta))/(-3*a3)
    q=r*r*c*p/(a3*large)
    s=(q-a1/a3)/large
    h=np.hypot(s,2*np.sqrt(-q))
    x=np.empty_like(r);near=s>=0
    # Algebraically this is r*sqrt(factor). Evaluating it as y*sqrt(factor)/k
    # avoids losing a subnormal y when the cube capacity ratio is greater than
    # one; near neutral the factor is approximately k^2.
    x[near]=y[active][near]*(np.sqrt((-2*c*p/a3[near])/(large[near]*(h[near]+s[near])))/ka[near])
    x[~near]=np.sqrt((h[~near]-s[~near])/2)
    out[active]=x
    return out


def radius_map(value, boundary, ratio, release=False):
    """Map the physical radius with exact endpoints and a closed-form pair."""
    v,b,k=np.broadcast_arrays(np.asarray(value,dtype=float),boundary,ratio)
    if np.any(v<0) or np.any(b<0) or np.any(k<1):raise ValueError('Invalid radial domain')
    endpoint=b if release else b*k
    x=np.divide(np.minimum(v,endpoint),b,out=np.zeros_like(v),where=b>0)
    y=_release_radius(x,k) if release else _compress_radius(x,k)
    physical=b*(k if release else 1.)
    mapped=np.minimum(physical,np.maximum(0.,b*y))
    return np.where(v>=endpoint,physical,mapped)

