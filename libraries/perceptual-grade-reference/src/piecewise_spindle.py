"""Experimental C2 radial pair; not adopted by Model or production kernels.

Radii use spindle capacity B as their common unit, and k=U/B >= 1.
The physical shoulder and exterior pole are independent.  Both inverse
branches are algebraic: real Cardano radicals and a rationalized quadratic.
"""
import numpy as np

JOIN = .75
SHOULDER_RATE = 14.
INNER_LIFT = .1
POLE = 1.01
# This standalone experiment is checked through this stress-test ratio;
# sampled model capacities are below 18.  Do not silently accept ratios whose
# Cardano intermediates have never been qualified for float64 evaluation.
MAX_CAPACITY_RATIO = 1e8


def _inputs(value, k, inner_lift, pole, release=False):
    if not np.isfinite(inner_lift) or not 0 < inner_lift <= .25:
        raise ValueError('Inner lift must be in (0, .25]')
    if not np.isfinite(pole) or not 1 < pole <= 1.05:
        raise ValueError('Pole must be in (1, 1.05]')
    value, k = np.broadcast_arrays(np.asarray(value, dtype=float), np.asarray(k, dtype=float))
    if (not np.isfinite(value).all() or not np.isfinite(k).all()
            or np.any(value < 0) or np.any(k < 1) or np.any(k > MAX_CAPACITY_RATIO)):
        raise ValueError('Finite nonnegative radii and capacity ratios in [1, 1e8] required')
    if release and np.any((k > 1) & (value >= pole)):
        raise ValueError('Release radius must be below the exterior pole')
    return value, k


def _coefficients(k, inner_lift):
    # Form surplus from k-1, avoiding cancellation as k tends to one.
    surplus = k - 1
    a = inner_lift * (surplus / k) / JOIN**2
    start = JOIN + a * JOIN**3
    slope = 1 + 3 * a * JOIN**2
    curvature = 3 * a * JOIN
    tail = 1072 * surplus - 913.5 * a
    return a, start, slope, curvature, tail


def _shoulder_derivatives(t, slope, q, h):
    z = SHOULDER_RATE * t
    denominator = 1 + z + z*z
    first = slope + (q*t*(2+z) + h*t*t*(3+2*z+z*z)) / denominator**2
    second = 2*(q*(1-3*z*z-z**3) + 3*h*t*(1+z)) / denominator**3
    return first, second


def release_radius(x, k, inner_lift=INNER_LIFT, pole=POLE):
    """C_cube/B from C_spindle/B, including the unclipped pole extension."""
    x, k = _inputs(x, k, inner_lift, pole, release=True)
    out = x.copy()
    inner = (k > 1) & (x <= JOIN)
    a, _, _, _, _ = _coefficients(k[inner], inner_lift)
    out[inner] = x[inner] * (1 + a*x[inner]**2)
    shoulder = (k > 1) & (x > JOIN) & (x <= 1)
    _, start, slope, q, h = _coefficients(k[shoulder], inner_lift)
    t = x[shoulder] - JOIN
    z = SHOULDER_RATE * t
    out[shoulder] = start + slope*t + t*t*(q+h*t)/(1+z+z*z)
    exterior = (k > 1) & (x > 1)
    _, _, slope, q, h = _coefficients(k[exterior], inner_lift)
    m, c = _shoulder_derivatives(1-JOIN, slope, q, h)
    u = x[exterior] - 1
    # pole-x retains the represented distance to the pole near its endpoint.
    out[exterior] = k[exterior] + m*u + (.5*c)*u*u*(pole-1)/(pole-x[exterior])
    return np.where(x == 1, k, out)


def release_derivatives(x, k, inner_lift=INNER_LIFT, pole=POLE):
    """Analytic first and second derivatives of the experimental release."""
    x, k = _inputs(x, k, inner_lift, pole, release=True)
    first, second = np.ones_like(x), np.zeros_like(x)
    inner = (k > 1) & (x <= JOIN)
    a, _, _, _, _ = _coefficients(k[inner], inner_lift)
    first[inner] = 1 + 3*a*x[inner]**2
    second[inner] = 6*a*x[inner]
    shoulder = (k > 1) & (x > JOIN) & (x <= 1)
    _, _, slope, q, h = _coefficients(k[shoulder], inner_lift)
    first[shoulder], second[shoulder] = _shoulder_derivatives(x[shoulder]-JOIN, slope, q, h)
    exterior = (k > 1) & (x > 1)
    _, _, slope, q, h = _coefficients(k[exterior], inner_lift)
    m, c = _shoulder_derivatives(1-JOIN, slope, q, h)
    u = x[exterior] - 1
    gap = pole-1
    remaining = (pole-x[exterior])/gap
    first[exterior] = m + .5*c*u*(2-u/gap)/remaining**2
    second[exterior] = c/remaining**3
    return first, second


def _shoulder_inverse(v, slope, q, h):
    """Unique real Cardano root, reconstructed without cancellation at v=0."""
    a = SHOULDER_RATE
    c3 = slope*a*a + h
    c2 = slope*a + q - v*a*a
    c1 = slope - v*a
    shift = c2/(3*c3)
    p = c1/c3 - 3*shift*shift
    half = (v/c3 + shift**3 + p*shift)/2
    discriminant = half*half + (p/3)**3
    root = np.cbrt(half + np.copysign(np.sqrt(discriminant), half))
    depressed = root - p/(3*root)
    # Exact factorization of the root equation, not a Newton correction.
    return v/(c3*(depressed**2 + depressed*shift + shift*shift + p))


def compress_radius(y, k, inner_lift=INNER_LIFT, pole=POLE):
    """C_spindle/B from C_cube/B; no iteration, root search, or trig branch."""
    y, k = _inputs(y, k, inner_lift, pole)
    out = y.copy()
    a, start, slope, q, h = _coefficients(k, inner_lift)
    inner = (k > 1) & (y <= start)
    # The inner cubic reduces to z^3+3z=2b.  Rationalize u-1/u
    # before dividing by sqrt(3A), retaining subnormal input radii.
    b = 1.5*y[inner]*np.sqrt(3*a[inner])
    u = np.cbrt(b + np.hypot(b, 1.))
    out[inner] = y[inner]*(3/(u*u + 1 + 1/(u*u)))
    shoulder = (k > 1) & (y > start) & (y <= k)
    offset = _shoulder_inverse(y[shoulder]-start[shoulder], slope[shoulder], q[shoulder], h[shoulder])
    out[shoulder] = JOIN + offset
    exterior = (k > 1) & (y > k)
    m, c = _shoulder_derivatives(1-JOIN, slope[exterior], q[exterior], h[exterior])
    e, gap = .5*c, pole-1
    delta = y[exterior] - k[exterior]
    scale = m*gap
    offset = np.empty_like(delta)
    small = delta <= scale
    # Scale the quadratic by whichever of delta and m*gap is larger.
    # The discriminant is a sum of nonnegative terms in both branches.
    v = delta[small]/scale[small]
    alpha = e[small]*gap/m[small]
    offset[small] = gap*(2*v/(1+v+np.sqrt((1-v)**2+4*alpha*v)))
    v = scale[~small]/delta[~small]
    alpha_v = (e[~small]*gap/delta[~small])*gap
    offset[~small] = gap*(2/(1+v+np.sqrt((1-v)**2+4*alpha_v)))
    # Extremely large finite y can round the exact inverse to its pole.
    out[exterior] = np.minimum(1+offset, np.nextafter(pole, 1.))
    out = np.where(y == start, JOIN, out)
    return np.where(y == k, 1., out)
