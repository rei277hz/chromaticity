"""Directed interval checks of the compact appearance body's raw decoder.

Powers use interval log/exp series; no assumed libm pow error is used. This
checks real equations with the stored binary constants, not NumPy execution.
"""
import numpy as np


def down(x):return np.nextafter(x, -np.inf)
def up(x):return np.nextafter(x, np.inf)


class I:
    __array_priority__ = 1000

    def __init__(self, lo, hi=None):
        self.lo = np.asarray(lo, dtype=float)
        self.hi = self.lo if hi is None else np.asarray(hi, dtype=float)

    def __add__(self, other):
        b = interval(other)
        return I(down(self.lo+b.lo), up(self.hi+b.hi))

    __radd__ = __add__

    def __neg__(self):return I(-self.hi, -self.lo)
    def __sub__(self, other):return self+-interval(other)
    def __rsub__(self, other):return interval(other)+-self

    def __mul__(self, other):
        b = interval(other)
        terms = np.broadcast_arrays(self.lo*b.lo, self.lo*b.hi, self.hi*b.lo, self.hi*b.hi)
        return I(down(np.minimum.reduce(terms)), up(np.maximum.reduce(terms)))

    __rmul__ = __mul__

    def __truediv__(self, other):
        b = interval(other)
        if np.any((b.lo <= 0) & (b.hi >= 0)):raise ValueError('Interval division crosses zero')
        return self*I(down(1/b.hi), up(1/b.lo))

    def __rtruediv__(self, other):return interval(other)/self

    def __getitem__(self, key):return I(self.lo[key], self.hi[key])

    def sqrt(self):
        if np.any(self.lo < 0):raise ValueError('Negative interval square root')
        return I(np.maximum(0., down(np.sqrt(self.lo))), up(np.sqrt(self.hi)))

    def positive(self):return I(np.maximum(0., self.lo), np.maximum(0., self.hi))

    def power(self, p):
        p = interval(p)
        if np.any(self.lo < 0) or (np.any(p.lo < 0) and np.any(self.lo == 0)):
            raise ValueError('Power interval outside its positive domain')
        lo = np.maximum(self.lo, np.finfo(float).smallest_subnormal)
        hi = np.maximum(self.hi, np.finfo(float).smallest_subnormal)
        logs = I(log_point(lo).lo, log_point(hi).hi)*p
        result = I(exp_point(logs.lo).lo, exp_point(logs.hi).hi)
        if np.all(p.lo > 0):result = I(np.where(self.lo == 0, 0., result.lo), np.where(self.hi == 0, 0., result.hi))
        return result


def interval(x):return x if isinstance(x, I) else I(x)


# Enclose ln(2) and pi between adjacent binary64 values.
LOG2 = I(float.fromhex('0x1.62e42fefa39efp-1'), float.fromhex('0x1.62e42fefa39f0p-1'))
PI = I(float.fromhex('0x1.921fb54442d18p+1'), float.fromhex('0x1.921fb54442d19p+1'))


def log_point(x):
    mantissa, exponent = np.frexp(x)
    m = I(2*mantissa)
    z = ((m-1)/(m+1)).positive()
    square = z*z
    term, result = z, z
    for k in range(1, 22):
        term = term*square
        result = result+term/(2*k+1)
    tail = term*square/(45*(1-square))
    return 2*I(result.lo, up(result.hi+tail.hi))+(exponent-1)*LOG2


def exp_point(x):
    exponent = np.floor(x/float(LOG2.lo)).astype(int)-1
    r = I(x)-exponent*LOG2
    if np.any(r.lo < 0) or np.any(r.hi > 1.5):raise ValueError('Exponential range reduction failed')
    term, result = I(np.ones_like(x)), I(np.ones_like(x))
    for k in range(1, 33):
        term = term*r/k
        result = result+term
    remainder = term*r/33/(1-r/34)
    return I(np.maximum(0., down(np.ldexp(result.lo, exponent))),
             up(np.ldexp(up(result.hi+remainder.hi), exponent)))


def trig_point(x, cosine=False):
    turns = np.rint(x/(2*float(PI.lo)))
    r = I(x)-turns*2*PI
    squared = r*r
    term = I(np.ones_like(x)) if cosine else r
    result = term
    for k in range(1, 27):
        divisor = (2*k-1)*(2*k) if cosine else (2*k)*(2*k+1)
        term = -term*squared/divisor
        result = result+term
    # |r| < 3.142; Taylor's omitted term is < 1e-40 at this order.
    return result+I(-1e-40, 1e-40)


def trig(x, cosine=False):
    midpoint = (x.lo+x.hi)/2
    radius = up(np.maximum(midpoint-x.lo, x.hi-midpoint))
    value = trig_point(midpoint, cosine)
    return I(np.maximum(-1., down(value.lo-radius)), np.minimum(1., up(value.hi+radius)))


