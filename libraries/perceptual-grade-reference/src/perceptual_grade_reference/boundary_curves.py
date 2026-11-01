"""C2 joins derived from packed boundary values; explicit monotone inversion."""
import numpy as np

PATCH = .25


def take(values, index):
    return np.take_along_axis(values, index[..., None], axis=-1)[..., 0]


def hinge(z, radius, order=0):
    """Positive-part convolved with a triangular kernel of radius r."""
    t = np.maximum(0., radius-np.abs(z))
    if order == 0:return np.maximum(z, 0.)+t**3/(6*radius*radius)
    if order == 1:return np.where(z < 0, t*t/(2*radius*radius), 1-t*t/(2*radius*radius))
    if order == 2:return t/(radius*radius)
    raise ValueError('Only value, slope and curvature are supported')


def rounded_weights(axis, x, period=0., order=0):
    """Three nonnegative value weights; derivative weights sum to zero."""
    axis, x = np.asarray(axis, dtype=float), np.asarray(x, dtype=float)
    n = len(axis)
    x = x % period if period else np.clip(x, axis[0], axis[-1])
    i = np.searchsorted(axis, x, side='right')-1
    i = i % n if period else np.clip(i, 0, n-2)
    j = (i+1) % n
    start = axis[i]
    end = np.where(j == 0, period, axis[j]) if period else axis[j]
    span = end-start
    before = np.where(i == 0, axis[-1]-period, axis[(i-1) % n]) if period else axis[np.maximum(0, i-1)]
    after = np.where(j == n-1, period+axis[0], axis[(j+1) % n]) if period else axis[np.minimum(n-1, j+1)]
    # At the wrap, the right node is represented at +period.
    if period:after = np.where(j == 0, period+axis[1], after)
    rl, rr = PATCH*np.minimum(start-before, span), PATCH*np.minimum(span, after-end)
    left = (x-start < rl) & (rl > 0)
    right = (end-x < rr) & (rr > 0)
    k = np.where(left, i, j)
    radius = np.where(left, rl, rr)
    active = left | right
    radius = np.where(active, radius, 1.)
    center = np.where(left, start, end)
    lg = np.where(left, start-before, span)
    rg = np.where(left, span, after-end)
    lg, rg = np.where(active, lg, 1.), np.where(active, rg, 1.)
    z = x-center
    sh = hinge(z, radius, order)
    wl = (sh-(z if order == 0 else 1. if order == 1 else 0.))/lg
    wr = sh/rg
    wm = (1. if order == 0 else 0.)-wl-wr
    f = (x-start)/span
    if order == 0:ordinary = np.stack((1-f, f, np.zeros_like(f)), axis=-1)
    elif order == 1:ordinary = np.stack((-1/span, 1/span, np.zeros_like(f)), axis=-1)
    else:ordinary = np.zeros((*x.shape, 3))
    ids = np.where(active[..., None], np.stack(((k-1) % n, k % n, (k+1) % n), axis=-1),
                   np.stack((i, j, j), axis=-1))
    weights = np.where(active[..., None], np.stack((wl, wm, wr), axis=-1), ordinary)
    return ids, weights


def rounded_linear(axis, values, x, order=0):
    ids, weights = rounded_weights(axis, x, order=order)
    return np.sum(np.take_along_axis(np.broadcast_to(values, (*np.shape(x), len(axis))), ids, axis=-1)*weights, axis=-1)


def depressed_root(a, b, v):
    """Root of a*t+b*t^3=v on [0,1], a>0 and b>=-a/6.

    Rationalized hyperbolic/trigonometric forms retain the linear limit.
    Both real-root cases use the unique increasing branch of the patch.
    """
    a, b, v = np.broadcast_arrays(a, b, v)
    r = v/a
    t = 1.5*r*np.sqrt(3*np.abs(b)/a)
    positive = b >= 0
    theta = np.where(positive, np.arcsinh(t), np.arcsin(np.minimum(t, 1.)))/3
    numerator = np.where(positive, 3*np.sinh(theta), 3*np.sin(theta))
    return r*np.divide(numerator, t, out=np.ones_like(t), where=t != 0)


