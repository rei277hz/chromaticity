"""Host-independent preparation of static matrices and tone coefficients."""
from dataclasses import dataclass, replace
from typing import Optional, TYPE_CHECKING
import math
import numpy as np

from ..color_core import linear as color_linear
from .settings import D65, LOW_Y, SPACES, LinearSettings, ToneSettings, ColorSettings, Settings
from .color_prepare import PreparedColor, prepare_color
from .tables import TEXTURE_WIDTH, kernel, readonly, build_runtime_table
from .layouts import TONE_CELLS

if TYPE_CHECKING:
    from .stage2_parameters import PreparedParameters

GAMMA = .525*(1.48+math.sqrt(.1))
CAT16 = np.asarray(color_linear.CAT16, dtype=np.float64)
WHITE_XYZ = np.asarray(color_linear.xyz(D65), dtype=np.float64)


def _finite(value, shape, description):
    array = np.asarray(value, dtype=np.float64)
    if array.shape != shape or not np.isfinite(array).all():
        raise ValueError(f'{description} must have shape {shape} and finite values')
    return array


def _native_array(value, description):
    array = np.asarray(value, dtype=np.float64)
    with np.errstate(over='ignore', invalid='ignore'):
        native = array.astype(np.float32)
    if not np.isfinite(array).all() or not np.isfinite(native).all():
        raise ValueError(f'{description} is not representable as float32')
    if np.any((array != 0) & (native == 0)):
        raise ValueError(f'{description} underflows float32')
    return readonly(array)


def project_source_white(point):
    """Nearest point in the CAT16-positive xy polygon used by the reference."""
    point = np.clip(_finite(point, (2,), 'Source xy'), 0., .9)
    normals = CAT16[:, :2]-CAT16[:, 2, None]
    offsets = CAT16[:, 2]-.002*np.linalg.norm(normals, axis=1)
    planes = np.vstack((np.column_stack((normals, offsets)), (0., 1., -.002)))
    polygon = np.array(((0., 0.), (.9, 0.), (.9, .9), (0., .9)))
    for a, b, c in planes:
        output = []
        for start, end in zip(polygon, np.roll(polygon, -1, axis=0)):
            p, q = a*start[0]+b*start[1]+c, a*end[0]+b*end[1]+c
            if p >= 0:
                output.append(start)
            if (p >= 0) != (q >= 0):
                output.append(start+p/(p-q)*(end-start))
        polygon = np.asarray(output)
    if np.all(planes[:, :2] @ point+planes[:, 2] >= 0):
        return tuple(map(float, point))
    edges = np.roll(polygon, -1, axis=0)-polygon
    t = np.clip(np.sum((point-polygon)*edges, axis=1)/np.sum(edges*edges, axis=1), 0., 1.)
    candidates = polygon+t[:, None]*edges
    return tuple(map(float, candidates[np.argmin(np.sum((candidates-point)**2, axis=1))]))


def project_source_white_component(point, axis):
    """Clamp one xy coordinate while keeping the other coordinate fixed."""
    if axis not in (0, 1):
        raise ValueError('Source xy axis must be 0 or 1')
    point = np.clip(_finite(point, (2,), 'Source xy'), 0., .9)
    normals = CAT16[:, :2]-CAT16[:, 2, None]
    offsets = CAT16[:, 2]-.002*np.linalg.norm(normals, axis=1)
    planes = np.vstack((np.column_stack((normals, offsets)), (0., 1., -.002)))
    other = 1-axis
    fixed = point[other]
    lower, upper = 0., .9
    for plane in planes:
        coefficient = plane[axis]
        offset = plane[other]*fixed+plane[2]
        if coefficient > 0:
            lower = max(lower, -offset/coefficient)
        elif coefficient < 0:
            upper = min(upper, -offset/coefficient)
        elif offset < 0:
            return project_source_white(point)[axis]
    result = point.copy()
    result[axis] = np.clip(point[axis], lower, upper)
    return float(result[axis])


def linear_matrix(settings=LinearSettings()):
    """Construct the complete XYZ matrix in the fixed D65 grading frame."""
    if not isinstance(settings, LinearSettings):
        raise TypeError('linear must be LinearSettings')
    exposure = _finite(settings.exposure, (), 'Exposure').item()
    balance = _finite(settings.balance, (2,), 'Balance')
    spread = _finite(settings.spread, (2,), 'Spread')
    heading = _finite(settings.heading, (2,), 'Heading')
    source = project_source_white(settings.source_xy)
    if settings.matrix is not None:
        return _native_array(_finite(settings.matrix, (3, 3), 'XYZ matrix'), 'XYZ matrix')
    cat = np.asarray(color_linear.cat16(source, D65))
    directional = np.eye(3)
    try:
        if np.any(balance != 0) or np.any(spread != 0) or np.any(heading != 0):
            anchors = np.asarray(D65)+.3*(np.array(((.64, .33), (.15, .06)))-D65)
            targets = []
            for anchor, gain, dilation, angle in zip(anchors, balance, spread, heading):
                radians = math.radians(float(angle % 360))
                c, s = math.cos(radians), math.sin(radians)
                direction = np.array(((c, -s), (s, c))) @ (anchor-D65)
                point = np.asarray(D65)+(1+dilation/100)*direction
                point[1] = max(.01, point[1])
                targets.append(np.asarray(color_linear.xyz(point))*2.**(-float(gain)))
            basis = np.column_stack((WHITE_XYZ, *(color_linear.xyz(p) for p in anchors)))
            target = np.column_stack((WHITE_XYZ, *targets))
            directional += (target-basis) @ np.linalg.inv(basis)
        result = 2.**exposure*(directional @ cat)
    except (OverflowError, FloatingPointError) as exc:
        raise ValueError('Linear controls exceed the practical float32 domain') from exc
    return _native_array(result, 'Prepared linear matrix')


@dataclass(frozen=True)
class PreparedLinear:
    settings: LinearSettings
    space: str
    xyz_matrix: np.ndarray
    rgb_matrix: np.ndarray
    rgb_to_xyz: np.ndarray
    xyz_to_rgb: np.ndarray
    to_cones: np.ndarray
    from_cones: np.ndarray
    linear_to_cones: np.ndarray


def prepare_linear(settings=LinearSettings(), space='Linear Rec.709'):
    if space not in SPACES:
        raise ValueError(f'Unsupported scene RGB space: {space}')
    matrix = linear_matrix(settings)
    raw = np.asarray(color_linear.rgb_to_xyz(space))
    rgb_white = color_linear.SPACES[space][1]
    before = np.asarray(color_linear.bradford(rgb_white, D65)) @ raw
    after = np.linalg.inv(before)
    normalized = CAT16/(CAT16 @ WHITE_XYZ)[:, None]
    to_cones = normalized @ before
    rgb = after @ matrix @ before
    # Preserve exact neutral/reset and scalar-exposure transforms.
    scalar = matrix[0, 0]
    if np.array_equal(matrix, scalar*np.eye(3)):
        rgb = scalar*np.eye(3)
    return PreparedLinear(settings, space, matrix, _native_array(rgb, 'RGB matrix'),
                          readonly(before), readonly(after), readonly(to_cones),
                          readonly(np.linalg.inv(to_cones)),
                          _native_array(normalized @ matrix @ before, 'Linear cone matrix'))


def viewing(reference=203.):
    la = .1*reference
    k = 1/(5*la+1)
    fl = .2*k**4*5*la+.1*(1-k**4)**2*(5*la)**(1/3)
    p = fl**.42
    return fl, 3.05*400*p/(27.13+p)


def nits_to_j(nits, reference=203.):
    """Normalized (J/100) neutral lightness, without response offsets."""
    fl, _ = viewing(reference)
    p = fl**.42
    white = p/(27.13+p)
    p = (fl*np.maximum(0., np.asarray(nits, dtype=np.float64))/reference)**.42
    return ((p/(27.13+p))/white)**GAMMA


def _smooth_floor(value, lower):
    d = value-lower
    return lower if d <= 0 else value if d >= 1 else lower+d**3*(6+d*(-8+3*d))


def _smooth_cap(value, upper):
    d = upper-value
    return upper if d <= 0 else value if d >= 1 else upper-d**3*(6+d*(-8+3*d))


@dataclass(frozen=True)
class PreparedTone:
    settings: ToneSettings
    reference: float
    peak: float
    fl: float
    aw: float
    gamma: float
    source: np.ndarray
    target: np.ndarray
    black: float
    span: float
    knots: np.ndarray
    width: float
    slope: float
    residual: np.ndarray
    norms: np.ndarray
    active: bool
    high: float
    table: object = None

    def remap_normalized(self, t):
        """Normalized target J at normalized source position t (always active math)."""
        t = np.maximum(0., np.asarray(t, dtype=np.float64))
        out = self.slope*t
        for left, right, weight, normal in zip(self.knots[:-1], self.knots[1:],
                                               self.residual, self.norms):
            if weight:
                out = out+(weight/normal)*kernel(t, left, right, self.width)
        return np.where(t == 1., self.high, out)

    def remap(self, h):
        """Full-precision scalar curve; H and result use J units, white = 100."""
        h = np.asarray(h, dtype=np.float64)
        if not self.active:
            return h.copy()
        return 100*self.remap_normalized(np.maximum(0., (h/100-self.black)/self.span))

    def remap_table(self, h, dtype=np.float32):
        h = np.asarray(h, dtype=dtype)
        if not self.active:
            return h.copy()
        t = np.maximum(dtype(0), (h/dtype(100)-dtype(self.black))/dtype(self.span))
        z = np.minimum(t/dtype(self.table.domain), dtype(1))
        result = dtype(100)*(dtype(self.slope)*t+self.table.evaluate(z, dtype))
        return np.where(t == dtype(1), dtype(100*self.high), result)


def prepare_tone(settings=ToneSettings(), *, full_fields=False):
    if not isinstance(settings, ToneSettings):
        raise TypeError('tone must be ToneSettings')
    nits = _finite(settings.input_nits, (5,), 'Tone input anchors')
    fit = _finite(settings.fit, (), 'Tone fit').item()
    reference = _finite(settings.reference_nits, (), 'Viewing reference').item()
    peak = _finite(settings.peak_nits, (), 'Tone peak').item()
    if reference != 203.:
        raise ValueError('This experiment supports the reference Model at D65 / 203 nits')
    if not -2. <= fit <= 2.:
        raise ValueError('The evaluated Tone fit domain is [-2, 2]')
    peak = _smooth_cap(_smooth_floor(peak, 2*reference), 10000.)
    target = nits_to_j((0., LOW_Y*reference, .18*reference, reference, peak), reference)
    target[0], target[3] = 0., 1.
    source = nits_to_j(nits, reference)
    for i in range(1, 5):
        source[i] = max(source[i], source[i-1]+.001)
    black, span = float(source[0]), float(source[-1]-source[0])
    knots = (source-black)/span
    width = .05*2.**(-fit)
    slope = float(np.min(np.diff(target)/np.diff(knots)))
    residual = np.maximum(0., np.diff(target)-slope*np.diff(knots))
    norms = np.array([kernel(1., left, right, width) for left, right in zip(knots[:-1], knots[1:])])
    if not np.isfinite(norms).all() or np.any(norms <= 0):
        raise ValueError('Tone kernel normalization is outside the practical domain')
    fl, aw = viewing(reference)
    prepared = PreparedTone(settings, reference, peak, fl, aw, GAMMA,
                            readonly(source), readonly(target), black, span, readonly(knots),
                            width, slope, readonly(residual), readonly(norms),
                            not np.array_equal(source, target), float(target[-1]))
    # An exact reset has an exact native bypass and needs no image resource.
    return replace(prepared, table=build_runtime_table(prepared, TONE_CELLS) if prepared.active or full_fields else None)


@dataclass(frozen=True)
class PreparedGrade:
    linear: PreparedLinear
    tone: PreparedTone
    space: str
    color: PreparedColor
    boundary: object = None
    full_fields: bool = False
    parameters: Optional['PreparedParameters'] = None

    @property
    def linear_rgb(self): return self.linear.rgb_matrix
    @property
    def to_cones(self): return self.linear.to_cones
    @property
    def from_cones(self): return self.linear.from_cones
    @property
    def linear_to_cones(self): return self.linear.linear_to_cones
    @property
    def fl(self): return self.tone.fl
    @property
    def aw(self): return self.tone.aw
    @property
    def gamma(self): return self.tone.gamma
    @property
    def table(self): return self.tone.table


def prepare(linear=LinearSettings(), tone=ToneSettings(), space='Linear Rec.709', *,
            color=ColorSettings(), boundary=None, full_fields=False, previous=None):
    """Prepare immutable static data; callable without importing Blender.

    A caller may reuse a PreparedBoundary across grades in the same appearance
    context. Its arrays contain geometry only; each built graph still owns its
    own packed Blender image. Omitting it loads the packaged boundary resource.
    """
    if previous is not None and not isinstance(previous, PreparedGrade):
        raise TypeError('previous must be PreparedGrade')
    first = (previous.linear if previous is not None and previous.linear.settings == linear
             and previous.space == space else prepare_linear(linear, space))
    second = (previous.tone if previous is not None and previous.tone.settings == tone
              and -2. <= tone.fit <= 2.
              and (previous.tone.table is None or (
                  previous.tone.table.cells == TONE_CELLS
                  and previous.tone.table.pixels.shape == (
                      (TONE_CELLS+TEXTURE_WIDTH)//TEXTURE_WIDTH, TEXTURE_WIDTH, 4)))
              and (not full_fields or previous.tone.table is not None)
              else prepare_tone(tone, full_fields=full_fields))
    if boundary is not None:
        from .boundary import PreparedBoundary
        if not isinstance(boundary, PreparedBoundary) or (boundary.fl, boundary.aw, boundary.gamma) != (second.fl, second.aw, second.gamma):
            raise ValueError('Boundary geometry belongs to a different appearance context')
    old_color = previous.color if previous is not None else None
    third = prepare_color(color, second, full_fields=full_fields, previous=old_color)
    return PreparedGrade(first, second, space, third, boundary, full_fields)


def prepare_update(settings, previous):
    """Prepare a value snapshot, reusing unchanged immutable field payloads.

    The caller owns native update admission and revision identity. Reuse here
    transfers no publication authority and never mutates the prior snapshot.
    """
    if not isinstance(settings, Settings):
        raise TypeError('settings must be Settings')
    if not isinstance(previous, PreparedGrade):
        raise TypeError('previous must be PreparedGrade')
    return prepare(settings.linear, settings.tone, settings.space, color=settings.color,
                   boundary=previous.boundary, full_fields=previous.full_fields, previous=previous)
