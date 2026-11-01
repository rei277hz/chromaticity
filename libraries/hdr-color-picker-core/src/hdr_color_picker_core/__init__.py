"""Immutable-value modCAM16-HK picker math; no Blender dependencies.

Authority: the legacy browser picker in rei277hz/modcam16-hk-ucs, rather
than its Photoshop fork. J′/x′/y′ are normalized Cartesian picker controls.
"""
from dataclasses import dataclass
import numpy as np

from ..color_core.linear import CAT16 as CAT16_VALUES
from ..color_core import aces2

PICKER_J_PEAK = 217.2768649129496
AUTHORING_PEAK = 10.0 / 2.03
RADIUS_K = 34.09902169100728
RADIUS_CUBIC = 0.0
SURROUND_C = .525
FL = .46646834500532247
AW = 31.7941491565276
Z = 1.48+np.sqrt(.1)
CAT16 = np.array(CAT16_VALUES)
CAT16_INVERSE = np.array([[1.862067855087233, -1.011254630531684, .149186775444452],
                          [.387526543236137, .621447441931475, -.008973985167613],
                          [-.015841498849334, -.034122938028516, 1.04996443687785]])
OPPONENT_TO_COMPRESSED = np.array([[460., 451., 288.], [460., -891., -261.], [460., -220., -6300.]])/1403
WHITE = np.array([.3127/.329, 1., (1-.3127-.329)/.329])
ADAPTATION = 1/(CAT16@WHITE)
_RADIUS_BELOW_ONE = np.nextafter(1.0, 0.0)
XYZ_TO_P3 = np.array([[2.493496911941425, -.931383617919124, -.402710784450717],
                      [-.829488969561575, 1.762664060318347, .023624685841944],
                      [.035845830243784, -.076172389268042, .956884524007687]])


def _hyperbolic(v):
    power = (FL*v/100)**.42
    return 400*power/(27.13+power)


LOW = _hyperbolic(.26)
HIGH = _hyperbolic(150.)
SLOPE = 1.68*27.13*FL*(FL*150/100)**-.58/(27.13+(FL*150/100)**.42)**2


def _response(v):
    return np.where(v < .26, LOW*v/.26+.1,
                    np.where(v > 150, HIGH+SLOPE*(v-150)+.1, _hyperbolic(np.maximum(v, 0))+.1))


def _inverse_response(v):
    v = v-.1
    base = np.maximum(27.13*v/(400-v), 0)
    return np.where(v < LOW, .26*v/LOW,
                    np.where(v > HIGH, 150+(v-HIGH)/SLOPE, 100/FL*base**(1/.42)))


def _radius_from_saturation(saturation, k, cubic):
    """Compact finite nonnegative saturation into the open unit interval."""
    saturation = np.asarray(saturation, dtype=np.float64)
    with np.errstate(all='ignore'):
        log_u = np.log(saturation) - np.log(k)
        if cubic == 0:
            log_t = log_u
        else:
            log_t = np.logaddexp(log_u, np.log(cubic) + 3.0*log_u)
        small = np.exp(log_t)
        radius = np.where(log_t < 0,
                          small / np.hypot(1.0, small),
                          1.0 / np.sqrt(1.0 + np.exp(-2.0*log_t)))
    radius = np.where(saturation == 0, 0.0, radius)
    valid = np.isfinite(saturation) & (saturation >= 0) & np.isfinite(k) & (k > 0)
    if cubic < 0 or not np.isfinite(cubic):
        valid &= False
    radius = np.where(valid, np.minimum(radius, _RADIUS_BELOW_ONE), np.nan)
    return radius


def _saturation_from_radius(radius, k, cubic):
    """Invert the compact radius; the circle edge represents infinity."""
    radius = np.asarray(radius, dtype=np.float64)
    inside = np.isfinite(radius) & (radius >= 0) & (radius < 1)
    with np.errstate(all='ignore'):
        t = np.divide(radius, np.sqrt((1.0-radius)*(1.0+radius)))
        if cubic == 0:
            u = t
        else:
            scale = np.sqrt(3.0*cubic)
            u = (2.0/scale)*np.sinh(np.arcsinh(1.5*scale*t)/3.0)
        saturation = k*u
    valid = inside & np.isfinite(k) & (k > 0) & np.isfinite(cubic) & (cubic >= 0)
    return np.where(valid, saturation, np.nan)


def _eccentricity(radians):
    h = radians
    return (1-.0582*np.cos(h)-.0258*np.cos(2*h)-.1347*np.cos(3*h)+.0289*np.cos(4*h)
            -.1475*np.sin(h)-.0308*np.sin(2*h)+.0385*np.sin(3*h)+.0096*np.sin(4*h))


def code_to_xyz(code):
    """Decode normalized (..., 3) controls; invalid-domain samples are NaN."""
    code = np.asarray(code, dtype=np.float64)
    if code.shape[-1:] != (3,):
        raise ValueError('Picker coordinates require a final dimension of three')
    j, x, y = np.moveaxis(code, -1, 0)
    x, y = 2*x-1, 2*y-1
    radius = np.hypot(x, y)
    valid = np.isfinite(code).all(axis=-1) & (code >= 0).all(axis=-1) & (code <= 1).all(axis=-1) & (radius < 1)
    with np.errstate(all='ignore'):
        saturation = _saturation_from_radius(radius, RADIUS_K, RADIUS_CUBIC)
        jhk = j*PICKER_J_PEAK
        u = .007/SURROUND_C*saturation
        denominator = np.hypot(jhk, 33*u)+33*u
        ja = np.divide(jhk*jhk, denominator, out=np.zeros_like(jhk), where=denominator > 0)
        chroma = u*ja
        hue = np.arctan2(-x, y)
        radicand = jhk*jhk-66*chroma
        valid &= np.isfinite(chroma) & (chroma >= 0) & (radicand >= -1e-12*np.maximum(1, jhk*jhk))
        lightness = np.sqrt(np.maximum(radicand, 0))
        opponent_radius = (chroma*AW/35)/(43*.8*_eccentricity(hue))
        opponent = np.stack((AW*(lightness/100)**(1/(SURROUND_C*Z))+.305,
                             opponent_radius*np.cos(hue), opponent_radius*np.sin(hue)), axis=-1)
        compressed = opponent@OPPONENT_TO_COMPRESSED.T
        xyz = (_inverse_response(compressed)/ADAPTATION)@CAT16_INVERSE.T/100
    return np.where(valid[..., None], xyz, np.nan)


def _xyz_to_jsh(xyz):
    """Extract radius-independent (J_HK, saturation, hue, chroma) arrays."""
    xyz = np.asarray(xyz, dtype=np.float64)
    with np.errstate(all='ignore'):
        compressed = _response((xyz*100)@CAT16.T*ADAPTATION)
        r, g, b = np.moveaxis(compressed, -1, 0)
        a = r-12*g/11+b/11
        opponent_b = (r+g-2*b)/9
        hue = np.arctan2(opponent_b, a)
        achromatic = (2*r+g+.05*b-.305)/AW
        lightness = 100*np.sign(achromatic)*np.abs(achromatic)**(SURROUND_C*Z)
        chroma = 35*(43*.8*_eccentricity(hue)*np.hypot(a, opponent_b))/AW
        jhk = np.sqrt(np.maximum(lightness*lightness+66*chroma, 0))
        ja = np.sqrt(np.maximum(jhk*jhk-66*chroma, 0))
        saturation = np.divide(SURROUND_C*chroma, .007*ja, out=np.zeros_like(chroma), where=(ja > 0) & np.isfinite(chroma))
        saturation = np.maximum(saturation, 0)
    return jhk, saturation, hue, chroma


def xyz_to_code(xyz):
    """Encode display XYZ; return (controls, appearance-domain validity)."""
    xyz = np.asarray(xyz, dtype=np.float64)
    jhk, saturation, hue, chroma = _xyz_to_jsh(xyz)
    j = jhk/PICKER_J_PEAK
    radius = _radius_from_saturation(saturation, RADIUS_K, RADIUS_CUBIC)
    code = np.stack((np.clip(j, 0, 1),
                     .5-.5*radius*np.sin(hue),
                     .5+.5*radius*np.cos(hue)), axis=-1)
    valid = np.isfinite(xyz).all(axis=-1) & np.isfinite(j) & (j >= -1e-10) & (j <= 1+1e-10)
    valid &= np.isfinite(saturation) & (chroma >= -1e-10) & np.isfinite(radius) & (radius < 1)
    return code, valid


def source_valid(xyz, full_rec2020=True):
    """Rec.2020 authoring cube, optionally intersected with the P3 cube."""
    xyz = np.asarray(xyz, dtype=np.float64)
    rgb = xyz@aces2.XYZ_TO_REC2020.T
    valid = np.isfinite(rgb).all(axis=-1) & (rgb >= -1e-8).all(axis=-1) & (rgb <= AUTHORING_PEAK+1e-7).all(axis=-1)
    if not full_rec2020:
        p3 = xyz@XYZ_TO_P3.T
        valid &= np.isfinite(p3).all(axis=-1) & (p3 >= -1e-8).all(axis=-1) & (p3 <= AUTHORING_PEAK+1e-7).all(axis=-1)
    return valid


@dataclass(frozen=True)
class Pick:
    """Scalar selection; invalid selections never expose a clipped scene value."""
    code: tuple
    xyz: tuple
    rec2020: tuple
    acescg: tuple
    valid: bool


def evaluate(j, x, y, full_rec2020=True):
    """Evaluate a scalar pick in the fixed legacy 203-nit authoring model."""
    code = (float(j), float(x), float(y))
    xyz = code_to_xyz(code)
    valid = bool(source_valid(xyz, full_rec2020))
    scene = aces2.inverse_from_xyz_d65(xyz) if valid else np.full(3, np.nan)
    valid = valid and bool(np.isfinite(scene).all())
    return Pick(code, tuple(xyz), tuple(xyz@aces2.XYZ_TO_REC2020.T), tuple(scene), valid)


def from_acescg(rgb):
    """Return (normalized controls, validity) for a scene-linear ACEScg color."""
    rgb = np.asarray(rgb, dtype=np.float64)
    xyz = aces2.forward_to_xyz_d65(rgb)
    code, valid = xyz_to_code(xyz)
    return code, valid & source_valid(xyz) & np.isfinite(rgb).all(axis=-1)


def slice_source(j, width, height, full_rec2020=True):
    """Return double-precision source XYZ and its authoritative gamut mask."""
    width, height = int(width), int(height)
    if width < 1 or height < 1 or width*height > 4096*4096:
        raise ValueError('Slice dimensions must be positive and at most 16M pixels')
    x = np.linspace(0, 1, width) if width > 1 else np.array([.5])
    y = np.linspace(1, 0, height) if height > 1 else np.array([.5])
    xx, yy = np.meshgrid(x, y)
    xyz = code_to_xyz(np.stack((np.full_like(xx, j), xx, yy), axis=-1))
    return xyz, source_valid(xyz, full_rec2020)


def render_slice(j, width, height, full_rec2020=True):
    """Scene-linear ACEScg RGBA slice; invalid samples are transparent black.

    The display/view transform belongs to the Blender presenter, so this
    renderer transports scene values and never bakes a display encoding.
    Row zero is the upper edge, matching the browser renderer.
    """
    width, height = int(width), int(height)
    xyz, valid = slice_source(j, width, height, full_rec2020)
    output = np.zeros((height, width, 4), dtype=np.float32)
    if np.any(valid):
        rgb = aces2.inverse_from_xyz_d65(xyz[valid])
        finite = np.isfinite(rgb).all(axis=-1)
        output[valid] = np.column_stack((np.where(finite[:, None], rgb, 0), finite))
    return output


REFERENCE_WHITE_J = 100/PICKER_J_PEAK
__all__ = ('Pick', 'evaluate', 'from_acescg', 'render_slice', 'code_to_xyz', 'xyz_to_code',
           'source_valid', 'PICKER_J_PEAK', 'AUTHORING_PEAK', 'REFERENCE_WHITE_J')
