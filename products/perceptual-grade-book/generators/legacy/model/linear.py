"""Stage 1 math, independent of Blender; decomposition uses its bundled NumPy.

RGB -> XYZ -> CAT16 -> directional 3x3 -> XYZ -> RGB. Exposure commutes with
all these matrices. UI endpoints are symmetric control axes, not assertions
about the transformed chromaticities of arbitrary complementary RGB samples.
"""
from ..localization.i18n import tr

from dataclasses import dataclass, replace
from functools import lru_cache
import math

I3 = ((1., 0., 0.), (0., 1., 0.), (0., 0., 1.))
CAT16 = ((.401288, .650173, -.051461), (-.250268, 1.204414, .045854),
         (-.002079, .048952, .953127))
D65 = (.3127, .3290)
ACES_WHITE = (.32168, .33767)
REC709 = ((.64, .33), (.30, .60), (.15, .06))
WHITES = {
    'D65': D65, 'D60': (.32161671, .33761992), 'ACES': ACES_WHITE,
    'D50': (.34567, .35850), 'D55': (.33242, .34743),
    'D75': (.29903, .31488), 'DCI': (.314, .351), 'E': (1/3, 1/3),
}
BRADFORD = ((.8951, .2664, -.1614), (-.7502, 1.7135, .0367),
            (.0389, -.0685, 1.0296))


@dataclass(frozen=True)
class GradeSpace:
    """Fixed Rec.709 sampling coordinates, Bradford-adapted to a Grade white.

    The coordinates of RGB samples do not depend on Blender's working gamut.
    Only their XYZ interpretation and the CAM reference white change here.
    """
    preset: str = 'D65'
SPACES = {
    'Linear Rec.709': (REC709, D65),
    'Linear Rec.2020': (((.708, .292), (.170, .797), (.131, .046)), D65),
    'ACEScg': (((.713, .293), (.165, .830), (.128, .044)), ACES_WHITE),
}
INTEROP = {'lin_rec709_scene': 'Linear Rec.709', 'lin_rec2020_scene': 'Linear Rec.2020',
           'lin_ap1_scene': 'ACEScg'}
PARAM_NAMES = ('exposure', 'source_x', 'source_y', 'cr_balance', 'yb_balance',
               'cr_spread', 'yb_spread', 'cr_heading', 'yb_heading')
LIMITS = {'exposure': (-6., 6.), 'source_x': (0., .9), 'source_y': (0., .9),
          'cr_balance': (-2., 2.), 'yb_balance': (-2., 2.),
          'cr_spread': (-100., 150.), 'yb_spread': (-100., 150.),
          'cr_heading': (-180., 180.), 'yb_heading': (-180., 180.)}


@dataclass(frozen=True)
class Parameters:
    exposure: float = 0.
    source_x: float = D65[0]
    source_y: float = D65[1]
    cr_balance: float = 0.
    yb_balance: float = 0.
    cr_spread: float = 0.
    yb_spread: float = 0.
    cr_heading: float = 0.
    yb_heading: float = 0.


def dot(a, b):
    return sum(x*y for x, y in zip(a, b))


def mv(m, v):
    return tuple(dot(row, v) for row in m)


def mm(a, b):
    return tuple(tuple(dot(row, col) for col in zip(*b)) for row in a)


def columns(*cols):
    return tuple(tuple(row) for row in zip(*cols))


def cross(a, b):
    return (a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0])


def inverse(m):
    u, v, w = cross(m[1], m[2]), cross(m[2], m[0]), cross(m[0], m[1])
    det = dot(m[0], u)
    if not math.isfinite(det) or abs(det) < 1e-14:
        raise ValueError(tr('error.singular_basis'))
    return tuple(tuple(x/det for x in row) for row in columns(u, v, w))


ICAT16 = inverse(CAT16)

# CAT16 adaptation is similar to diag(destination_cones/source_cones).
# Requiring each source cone to be positive keeps every adaptation eigenvalue
# positive. The margin is perpendicular distance in xy from each zero-cone
# line. y has its own positive floor to keep normalized XYZ finite.
WHITE_MARGIN = .002
WHITE_Y_MIN = .002
WHITE_PLANES = ((1., 0., 0.), (-1., 0., .9),
                (0., 1., -WHITE_Y_MIN), (0., -1., .9)) + tuple(
    (row[0]-row[2], row[1]-row[2],
     row[2]-WHITE_MARGIN*math.hypot(row[0]-row[2], row[1]-row[2]))
    for row in CAT16)


def _white_polygon():
    polygon = [(0., WHITE_Y_MIN), (.9, WHITE_Y_MIN), (.9, .9), (0., .9)]
    for a, b, c in WHITE_PLANES[4:]:
        result = []
        for p, q in zip(polygon, polygon[1:]+polygon[:1]):
            fp, fq = a*p[0]+b*p[1]+c, a*q[0]+b*q[1]+c
            if fp >= 0:
                result.append(p)
            if (fp >= 0) != (fq >= 0):
                t = fp/(fp-fq)
                result.append(tuple(p[i]+t*(q[i]-p[i]) for i in (0, 1)))
        polygon = result
    return tuple(polygon)


WHITE_POLYGON = _white_polygon()


def safe_source_white(point):
    """Closest admissible xy, shared by diagram drags and the math kernel."""
    if not all(math.isfinite(v) for v in point):
        return D65
    x, y = (min(.9, max(0., float(v))) for v in point)
    if all(a*x+b*y+c >= -1e-14 for a, b, c in WHITE_PLANES):
        return (x, y)
    candidates = []
    for p, q in zip(WHITE_POLYGON, WHITE_POLYGON[1:]+WHITE_POLYGON[:1]):
        dx, dy = q[0]-p[0], q[1]-p[1]
        t = min(1., max(0., ((x-p[0])*dx+(y-p[1])*dy)/(dx*dx+dy*dy)))
        candidates.append((p[0]+t*dx, p[1]+t*dy))
    return min(candidates, key=lambda p: (x-p[0])**2+(y-p[1])**2)


def source_component(point, axis):
    """Clamp a numeric edit while holding the other coordinate fixed."""
    if not all(math.isfinite(v) for v in point):
        return D65
    other = 1-axis
    fixed = float(point[other])
    lo, hi = 0., .9
    for a, b, c in WHITE_PLANES:
        coefficient, offset = (a, b*fixed+c) if axis == 0 else (b, a*fixed+c)
        if coefficient > 0:
            lo = max(lo, -offset/coefficient)
        elif coefficient < 0:
            hi = min(hi, -offset/coefficient)
        elif offset < -1e-12:
            return safe_source_white(point)
    if hi < lo-1e-12:
        return safe_source_white(point)
    hi = max(hi, lo)
    result = list(point)
    result[axis] = min(hi, max(lo, point[axis]))
    return tuple(result)


def xyz(p, Y=1.):
    x, y = p
    if y <= 0 or not all(math.isfinite(v) for v in (x, y, Y)):
        raise ValueError(tr('error.invalid_xy'))
    return (x*Y/y, Y, (1-x-y)*Y/y)


def xy(v):
    s = sum(v)
    if abs(s) < 1e-14 or not math.isfinite(s):
        return None
    return (v[0]/s, v[1]/s)


def white(space):
    if isinstance(space, GradeSpace):
        return WHITES[space.preset]
    return SPACES[space][1]


def neutral_parameters(space):
    return replace(Parameters(), source_x=white(space)[0], source_y=white(space)[1])


def adaptation(source, destination):
    source = safe_source_white(source)
    # RNA FloatProperty values are float32; keep reset exactly identity after
    # storing a standard white as two Blender properties.
    if max(abs(a-b) for a, b in zip(source, destination)) < 5e-8:
        return I3
    a, b = mv(CAT16, xyz(source)), mv(CAT16, xyz(destination))
    return mm(ICAT16, tuple(tuple(x*b[i]/a[i] for x in row) for i, row in enumerate(CAT16)))


@lru_cache(maxsize=64)
def bradford(source, destination):
    """Full Bradford adaptation of XYZ, with both whites normalized to Y=1."""
    if source == destination:
        return I3
    a, b = mv(BRADFORD, xyz(source)), mv(BRADFORD, xyz(destination))
    return mm(inverse(BRADFORD), tuple(tuple(x*b[i]/a[i] for x in row)
                                     for i, row in enumerate(BRADFORD)))


@lru_cache(maxsize=16)
def rgb_to_xyz(space):
    if isinstance(space, GradeSpace):
        return mm(bradford(D65, white(space)), rgb_to_xyz('Linear Rec.709'))
    primaries, wp = SPACES[space]
    p = columns(*(xyz(v) for v in primaries))
    scale = mv(inverse(p), xyz(wp))
    return tuple(tuple(row[k]*scale[k] for k in range(3)) for row in p)


@lru_cache(maxsize=16)
def xyz_to_rgb(space):
    return inverse(rgb_to_xyz(space))


@lru_cache(maxsize=16)
def references(space):
    """Original DCTL: 30% of the adapted Rec.709 red/blue xy displacement."""
    wd = white(space)
    cat = adaptation(D65, wd)
    result = []
    for i in (0, 2):
        p = xy(mv(cat, xyz(REC709[i])))
        result.append(tuple(wd[k]+.3*(p[k]-wd[k]) for k in (0, 1)))
    return tuple(result)


def moved_endpoint(wp, ref, heading, spread):
    a = math.radians(heading)
    c, s, k = math.cos(a), math.sin(a), 1+spread/100
    dx, dy = ref[0]-wp[0], ref[1]-wp[1]
    return (wp[0]+k*(c*dx-s*dy), wp[1]+k*(s*dx+c*dy))


def directional_matrix(params, space):
    wp = white(space)
    if all(getattr(params, n) == 0 for n in PARAM_NAMES[3:]):
        return I3
    refs = references(space)
    base = columns(xyz(wp), *(xyz(p) for p in refs))
    targets = []
    for axis, ref in zip(('cr', 'yb'), refs):
        p = moved_endpoint(wp, ref, getattr(params, axis+'_heading'), getattr(params, axis+'_spread'))
        # Matches the DCTL's existing target-construction guard. For the
        # supported whites and UI bounds this guard should remain inactive.
        v = xyz((p[0], max(.01, p[1])))
        targets.append(tuple(x*2**getattr(params, axis+'_balance') for x in v))
    return mm(columns(xyz(wp), *targets), inverse(base))


def matrices(params, space):
    if not isinstance(space, GradeSpace) and space not in SPACES:
        raise ValueError('Unsupported working color space: {space}'.format(space=space))
    if not all(math.isfinite(getattr(params, n)) for n in PARAM_NAMES):
        raise ValueError(tr('error.nonfinite_parameter'))
    cat = adaptation((params.source_x, params.source_y), white(space))
    linear = directional_matrix(params, space)
    total = mm(linear, cat)
    gain = 2**params.exposure
    if cat == I3 and linear == I3:
        rgb = tuple(tuple(x*gain for x in row) for row in I3)
    else:
        rgb = mm(xyz_to_rgb(space), mm(total, rgb_to_xyz(space)))
        rgb = tuple(tuple(x*gain for x in row) for row in rgb)
    return {'cat': cat, 'linear': linear, 'xyz_without_exposure': total, 'rgb': rgb,
            'xyz': tuple(tuple(x*gain for x in row) for row in total)}


def rebase(matrix, source, destination):
    """Change a correction's XYZ white context without changing its action."""
    if source == destination or all(matrix[i][j] == (matrix[0][0] if i == j else 0.)
                                    for i in range(3) for j in range(3)):
        return matrix
    cat = bradford(source, destination)
    return mm(cat, mm(matrix, inverse(cat)))


def rgb_matrix(matrix, space):
    if all(matrix[i][j] == (matrix[0][0] if i == j else 0.) for i in range(3) for j in range(3)):
        return matrix
    return mm(xyz_to_rgb(space), mm(matrix, rgb_to_xyz(space)))


@lru_cache(maxsize=256)
def decompose(matrix, space):
    """Derive editing controls; the matrix remains authoritative.

    For an invertible matrix, M^-1 w = source_white / exposure_gain.
    Singular matrices use the least-squares preimage closest to the white.
    Unrepresentable coordinates are finite editing approximations only.
    """
    import numpy as np
    m = np.asarray(matrix, float); w = np.asarray(xyz(white(space)))
    if m[0, 0] > 0 and np.max(abs(m-np.eye(3)*m[0, 0])) < 1e-13*max(1., abs(m[0, 0])):
        return replace(neutral_parameters(space), exposure=math.log2(m[0, 0]))
    if np.max(abs(m-np.eye(3))) < 1e-13:
        return neutral_parameters(space)
    try:
        u = np.linalg.solve(m, w)
    except np.linalg.LinAlgError:
        u = w + np.linalg.pinv(m, rcond=1e-12) @ (w-m@w)
    gain = 1/u[1] if u[1] > 1e-15 else 1.
    source = xy(u) or white(space)
    if not all(math.isfinite(x) for x in source):
        source = white(space)
    safe = safe_source_white(source)
    cat = np.asarray(adaptation(safe, white(space)))
    directional = m @ np.linalg.inv(cat) / gain
    fields = dict(exposure=math.log2(gain), source_x=source[0], source_y=source[1])
    for axis, ref in zip(('cr', 'yb'), references(space)):
        v = directional @ np.asarray(xyz(ref))
        target = xy(v) or white(space)
        dx, dy = (target[i]-white(space)[i] for i in (0, 1))
        bx, by = (ref[i]-white(space)[i] for i in (0, 1))
        radius = math.hypot(dx, dy)
        fields[axis+'_balance'] = math.log2(v[1]) if v[1] > 1e-15 else 0.
        fields[axis+'_spread'] = 100*(radius/math.hypot(bx, by)-1)
        fields[axis+'_heading'] = math.degrees(math.atan2(bx*dy-by*dx, bx*dx+by*dy)) if radius > 1e-14 else 0.
    # Suppress numerical noise in neutral and integer-valued editing readouts.
    return Parameters(**{k: round(v) if abs(v-round(v)) < 2e-11 else v
                         for k, v in fields.items()})


def edited_matrix(matrix, space, values):
    """Apply a control edit without discarding an unrepresentable remainder."""
    import numpy as np
    previous = decompose(matrix, space)
    if all(getattr(previous, k) == v for k, v in values.items()):
        return matrix
    if set(values) == {'exposure'}:
        gain = 2**(values['exposure']-previous.exposure)
        return tuple(tuple(x*gain for x in row) for row in matrix)
    new = replace(previous, **values)
    old_fit = np.asarray(matrices(previous, space)['xyz'])
    new_fit = np.asarray(matrices(new, space)['xyz'])
    result = np.asarray(matrix) + new_fit-old_fit
    return tuple(tuple(float(x) for x in row) for row in result)


@lru_cache(maxsize=256)
def control_error(matrix, space):
    """Relative reconstruction error of the editing view, never of rendering."""
    try:
        fitted=matrices(decompose(matrix,space),space)['xyz']
        return max(abs(a-b) for row,fit in zip(matrix,fitted) for a,b in zip(row,fit))/(1+max(abs(x) for row in matrix for x in row))
    except (ArithmeticError,ValueError):
        return math.inf


def symmetric_endpoints(params, space):
    wp = white(space)
    out = {}
    for axis, ref in zip(('cr', 'yb'), references(space)):
        positive = moved_endpoint(wp, ref, getattr(params, axis+'_heading'), getattr(params, axis+'_spread'))
        negative = tuple(2*wp[k]-positive[k] for k in (0, 1))
        out[axis] = (positive, negative)
    return out


def drag_axis(point, axis, sign, params, space):
    """Inverse of the diagram mapping. Negative endpoint edits the same axis."""
    if axis not in ('cr', 'yb') or sign not in (-1, 1):
        raise ValueError('Unknown control endpoint')
    wp = white(space)
    ref = references(space)[0 if axis == 'cr' else 1]
    dx, dy = (sign*(point[k]-wp[k]) for k in (0, 1))
    bx, by = (ref[k]-wp[k] for k in (0, 1))
    radius = math.hypot(dx, dy)
    lo, hi = LIMITS[axis+'_spread']
    spread = min(hi, max(lo, 100*(radius/math.hypot(bx, by)-1)))
    if radius < 1e-12:
        heading = getattr(params, axis+'_heading')
    else:
        heading = math.degrees(math.atan2(bx*dy-by*dx, bx*dx+by*dy))
        lo,hi=LIMITS[axis+'_heading']
        heading = min(hi, max(lo, heading))
    return {axis+'_heading': heading, axis+'_spread': spread}


def drag_white(point):
    return dict(zip(('source_x', 'source_y'), safe_source_white(point)))


def diagram_geometry(params, space, matrix=None):
    m = matrices(params, space)
    original = list(REC709)
    # Sample every edge: xy can have a projective pole under extreme matrices.
    # The renderer clips individual segments, not just triangle corners.
    def boundary(matrix):
        result = []
        for i in range(3):
            a, b = xyz(REC709[i]), xyz(REC709[(i+1) % 3])
            previous_sum = None
            for k in range(25):
                t = k/24
                value = mv(matrix, tuple((1-t)*a[j]+t*b[j] for j in range(3)))
                total = sum(value)
                if previous_sum is not None and total*previous_sum <= 0:
                    result.append(None)
                result.append(xy(value))
                previous_sum = total
            result.append(None)
        return result
    return {'source': (params.source_x, params.source_y), 'destination': white(space),
            'reference': original, 'adapted': boundary(m['cat']),
            'graded': boundary(matrix if matrix is not None else m['xyz_without_exposure']), 'endpoints': symmetric_endpoints(params, space)}
