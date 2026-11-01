"""Compact C² quintic tone-residual data and deterministic quality validation.

There is one shared float32 value/slope/curvature jet per endpoint. Slopes and
curvatures are expressed in cell coordinates. Python prepares coefficient data;
pixel grading is performed by the generated Blender graph.
"""
from dataclasses import dataclass, replace
import math
import numpy as np

TEXTURE_WIDTH = 512
TABLE_ERROR_LIMIT = 1e-5


def readonly(value, dtype=np.float64):
    result = np.array(value, dtype=dtype, copy=True)
    result.flags.writeable = False
    return result


def kernel(t, left, right, width):
    """Exact sigmoid-difference integral on nonnegative t, in stable log form.

The asymptotic expression avoids subtracting two terms proportional to t;
its value therefore remains accurate at the compactification's far tail.
"""
    t = np.asarray(t, dtype=np.float64)
    if np.any(t < 0) or not 0 <= left < right or not width > 0:
        raise ValueError('Kernel requires t >= 0, 0 <= left < right, and width > 0')
    gap = (right-left)/width
    with np.errstate(divide='ignore', invalid='ignore', over='ignore'):
        logq = (gap-np.logaddexp(0., (right-t)/width)
                -np.logaddexp(0., -left/width)
                +np.log(-np.expm1(-gap))+np.log(-np.expm1(-t/width)))
        result = width*np.logaddexp(0., logq)
    return np.where(t == 0, 0., result)


def kernel_limit(left, right, width):
    return (right-left)+width*(np.log1p(np.exp(-right/width))
                              -np.log1p(np.exp(-left/width)))


def _sigmoid(x):
    e = np.exp(-np.abs(x))
    return np.where(x >= 0, 1/(1+e), e/(1+e))


def residual_jet(tone, z):
    z = np.asarray(z, dtype=np.float64)
    domain = 1+32*tone.width
    t = z*domain
    value, first, second = (np.zeros_like(z) for _ in range(3))
    for left, right, weight, normal in zip(tone.knots[:-1], tone.knots[1:],
                                           tone.residual, tone.norms):
        if weight == 0:
            continue
        scale = weight/normal
        a = _sigmoid((t-left)/tone.width)
        b = _sigmoid((t-right)/tone.width)
        # Complementary sigmoids retain the difference on the positive tail.
        d = np.where(t <= .5*(left+right), a-b,
                     _sigmoid((right-t)/tone.width)-_sigmoid((left-t)/tone.width))
        dd = d*(1-a-b)/tone.width
        value += scale*np.where(z < 1, kernel(t, left, right, tone.width),
                                kernel_limit(left, right, tone.width))
        first += scale*np.where(z < 1, d*domain, 0.)
        second += scale*np.where(z < 1, dd*domain**2, 0.)
    return value, first, second


def coefficients(jets):
    """Quintic power coefficients from cell-scaled endpoint jets."""
    data = np.asarray(jets, dtype=np.float64)
    a0, a1, a2 = data[:-1, 0], data[:-1, 1], .5*data[:-1, 2]
    d = data[1:, 0]-a0-a1-a2
    e = data[1:, 1]-a1-2*a2
    f = data[1:, 2]-2*a2
    return np.stack((a0, a1, a2, 10*d-4*e+.5*f,
                     -15*d+7*e-f, 6*d-3*e+.5*f), axis=-1)


def derivative_bernstein(poly):
    derivative = poly[..., 1:]*np.arange(1, 6)
    return np.stack([sum(derivative[..., j]*math.comb(k, j)/math.comb(4, j)
                         for j in range(k+1)) for k in range(5)], axis=-1)


@dataclass(frozen=True)
class ToneTable:
    cells: int
    domain: float
    jets: np.ndarray
    pixels: np.ndarray
    limited_knots: int
    max_error: float | None = None
    monotone: bool = False
    probe_count: int | None = None

    @property
    def height(self):
        return self.pixels.shape[0]

    @property
    def memory_bytes(self):
        return self.pixels.nbytes

    def evaluate(self, z, dtype=np.float32):
        """Evaluate the same endpoint basis used by the native lookup nodes."""
        z = np.clip(np.asarray(z, dtype=dtype), dtype(0), dtype(1))
        position = z*dtype(self.cells)
        cell = np.minimum(np.floor(position).astype(np.int64), self.cells-1)
        u = position-cell.astype(dtype)
        v = dtype(1)-u
        u2, v2 = u*u, v*v
        u3, v3 = u2*u, v2*v
        blend = u3*(u*(dtype(6)*u-dtype(15))+dtype(10))
        h10 = u*v3*(dtype(1)+dtype(3)*u)
        h11 = -u3*v*(dtype(4)-dtype(3)*u)
        h20, h21 = dtype(.5)*u2*v3, dtype(.5)*u3*v2
        left, right = self.jets[cell].astype(dtype), self.jets[cell+1].astype(dtype)
        a = (left[..., 0]*(dtype(1)-blend)+left[..., 1]*h10)+left[..., 2]*h20
        b = (right[..., 0]*blend+right[..., 1]*h11)+right[..., 2]*h21
        return a+b


def _probes(tone, cells):
    # Cover cells, source transitions and the analytic tail independently.
    # The float32 lookup is constant throughout a source-coordinate rounding
    # bin, but its monotone reference is not. Probe just inside both bin edges
    # as well as each center so rounding cannot hide a sharp-transition error.
    domain = 1+32*tone.width
    t = np.linspace(0., domain, cells*16+1)
    knots = np.asarray(tone.knots)
    nearby = np.maximum(0., knots[:, None]+tone.width*np.linspace(-2., 2., 1025))
    probes = np.unique(np.r_[0., t, knots, nearby.ravel(),
                             np.maximum(0., np.nextafter(knots, -np.inf)),
                             np.nextafter(knots, np.inf), 1., domain,
                             np.nextafter(domain, -np.inf), np.nextafter(domain, np.inf),
                             domain+tone.width*np.arange(1, 65),
                             np.geomspace(1e-12, 1e8, 4097)])
    native = np.unique(probes.astype(np.float32))
    center = native.astype(np.float64)
    previous = np.nextafter(native, np.float32(-np.inf)).astype(np.float64)
    following = np.nextafter(native, np.float32(np.inf)).astype(np.float64)
    low = np.nextafter((previous+center)/2, center)
    high = np.nextafter((center+following)/2, center)
    return np.unique(np.maximum(0., np.r_[probes, center, low, high]))


def _build_table(tone, cells, width=TEXTURE_WIDTH):
    """Build one packed table; callers own the production/diagnostic policy."""
    if not isinstance(cells, (int, np.integer)) or cells < 1:
        raise ValueError('Tone table cells must be a positive integer')
    if not isinstance(width, (int, np.integer)) or width < 1:
        raise ValueError('Tone table width must be a positive integer')
    y, d, dd = residual_jet(tone, np.linspace(0., 1., cells+1))
    data = np.stack((y, d/cells, dd/cells**2), axis=-1).astype(np.float32)
    if not np.isfinite(data).all():
        raise ValueError('Tone coefficients are not representable as float32')
    limited = set()
    # Certify the actual quantized data. Zeroing both incident endpoint jets
    # gives a monotone smoothstep and preserves common C² endpoint data.
    for _ in range(cells+1):
        bernstein = derivative_bernstein(coefficients(data))
        tolerance = 64*np.finfo(float).eps*np.maximum(1., np.max(abs(data[:, 0])))
        bad = np.min(bernstein, axis=-1) < -tolerance
        if not np.any(bad):
            break
        indices = np.unique(np.r_[np.flatnonzero(bad), np.flatnonzero(bad)+1])
        changing = indices[np.any(data[indices, 1:] != 0, axis=1)]
        if not len(changing):
            raise ValueError('Tone endpoint values are not monotone')
        limited.update(map(int, changing))
        data[indices, 1:] = 0.
    else:
        raise ValueError('Tone monotonicity certification did not converge')
    height = (cells+1+width-1)//width
    pixels = np.zeros((height, width, 4), np.float32)
    pixels[..., 3] = 1.
    pixels.reshape(-1, 4)[:cells+1, :3] = data
    table = ToneTable(cells, 1+32*tone.width, readonly(data, np.float32), readonly(pixels, np.float32),
                      len(limited), monotone=True)
    return table


def build_runtime_table(tone, cells=256):
    """Generate fixed production coefficients; dense auditing is separate."""
    if cells not in (256, 2048):
        raise ValueError('Tone tables support 256 or 2048 cells')
    return _build_table(tone, cells, TEXTURE_WIDTH)


def audit_table(tone, table):
    """Development-only dense check of the exact runtime coefficient data."""
    t = _probes(tone, table.cells)
    expected = 100*tone.remap_normalized(t)
    t32 = t.astype(np.float32)
    z32 = np.minimum(t32/np.float32(table.domain), np.float32(1))
    actual = np.float32(100)*(np.float32(tone.slope)*t32+table.evaluate(z32))
    actual = np.where(t32 == 1., np.float32(100*tone.high), actual)
    error = float(np.max(abs(actual.astype(float)-expected)/np.maximum(1., abs(expected))))
    if not np.isfinite(error):
        raise ValueError('Tone validation produced nonfinite samples')
    return replace(table, max_error=error, probe_count=len(t))


def build_table(tone, cells):
    """Development API: generate and densely audit one explicit resolution."""
    return audit_table(tone, build_runtime_table(tone, cells))


def build_diagnostic_table(tone, cells):
    """Build and audit a report-only Tone texture at an explicit resolution.

    The production builder intentionally accepts only its fixed layouts. This
    development helper keeps the same quantization, monotonicity limiter and
    native lookup while packing sub-512 grids into their smallest useful image
    width, so a sensitivity report measures actual storage reduction.
    """
    if (not isinstance(cells, (int, np.integer)) or isinstance(cells, (bool, np.bool_))
            or cells < 1 or int(cells) & (int(cells)-1)):
        raise ValueError('Diagnostic Tone cells must be a positive power of two')
    width = min(TEXTURE_WIDTH, int(cells) + 1)
    return audit_table(tone, _build_table(tone, int(cells), width))


def audit_tone(tone):
    """Return a PreparedTone with offline measured accuracy metadata."""
    if tone.table is None:
        return tone
    return replace(tone, table=audit_table(tone, tone.table))


def select_table(tone):
    """Prepare the fixed runtime Tone table; a missed gate is explicit."""
    table = build_table(tone, 256)
    if table.monotone and table.max_error <= TABLE_ERROR_LIMIT:
        return table
    raise ValueError(f'Quintic 256 does not meet {TABLE_ERROR_LIMIT:g} scalar accuracy '
                     f'(error: {table.max_error:.6g})')
