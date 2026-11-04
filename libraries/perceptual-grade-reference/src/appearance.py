"""Colour's Hellwig2022 conversion, with our H,a,b coordinates and decoder domain.

XYZ and white XYZ use Y=1 normalization. Colour's XYZ domain is explicitly 100.
Signed energy is J_A*abs(J_A); it is carried rather than reconstructed at decode.
"""
from dataclasses import dataclass
import colour
import numpy as np
from colour.appearance.hellwig2022 import viewing_conditions_dependent_parameters
from ..color_core.scaled import Scalar as S, norm, signed_power
from .responses import (OPPONENT, INVERSE, GAMMA, eccentricity, Response,
                        uncompress, signed_hk, achromatic_response)

CAT16 = np.array([[.401288, .650173, -.051461], [-.250268, 1.204414, .045854],
                  [-.002079, .048952, .953127]], dtype=np.float64)


@dataclass(frozen=True)
class Appearance:
    q: np.ndarray
    ja: np.ndarray


def viewing(white, reference):
    return dict(XYZ_w=100*np.asarray(white, dtype=np.float64), L_A=.1*reference,
                Y_b=10., surround=colour.VIEWING_CONDITIONS_HELLWIG2022['Dark'],
                discount_illuminant=True)


def response_constants(reference):
    if not np.isfinite(reference) or not 48 <= reference <= 1000:
        raise ValueError('Effective viewing reference must be between 48 and 1000 nits')
    fl, _ = viewing_conditions_dependent_parameters(10., 100., .1*reference)
    p = fl**.42
    return fl, 3.05*400*p/(27.13+p)


def encode(xyz, white, reference=203.):
    xyz = np.asarray(xyz, dtype=np.float64)
    if xyz.shape[-1:] != (3,):
        raise ValueError('XYZ must have a final dimension of three')
    appearance = encode_cones(xyz @ CAT16.T/(CAT16 @ white), reference)
    neutral = np.all(xyz == xyz[..., 1, None]*np.asarray(white), axis=-1)
    q = appearance.q.copy()
    q[..., 0] = np.where(neutral, appearance.ja, q[..., 0])
    q[..., 1:] = np.where(neutral[..., None], 0., q[..., 1:])
    return Appearance(q, appearance.ja)


def encode_cones(cones, reference=203., constants=None):
    """Offset-free algebraic form of Colour's adapted-cone appearance components.

    Signed coordinates avoid an XYZ round trip and retain achromatic sign.
    The external XYZ_to_Hellwig2022 equations are unchanged; removing the .1
    offset keeps subnormal responses distinct from camera black.
    """
    cones = np.asarray(cones, dtype=np.float64)
    if cones.shape[-1:] != (3,) or not np.isfinite(cones).all():
        raise ValueError('Cones must be finite triples')
    fl, aw = response_constants(reference) if constants is None else constants
    p = fl**.42*np.abs(cones)**.42
    responses = np.sign(cones)*400*p/(27.13+p)
    margins = 400*27.13/(27.13+p)
    ac = responses @ np.array([2., 1., .05])
    ab = responses @ OPPONENT.T
    same_sign = np.all(cones >= 0, axis=-1) | np.all(cones <= 0, axis=-1)
    near_pole = same_sign & (np.max(np.abs(responses), axis=-1, initial=0) > 200)
    sign = np.where(ac >= 0, 1., -1.)
    ab = np.where(near_pole[..., None], -sign[..., None]*(margins @ OPPONENT.T), ab)
    angle = np.arctan2(ab[..., 1], ab[..., 0])
    ab *= (1204*eccentricity(angle)/aw)[..., None]
    neutral = np.all(cones == cones[..., :1], axis=-1)
    ab = np.where(neutral[..., None], 0., ab)
    ja = 100*signed_power(ac/aw, GAMMA)
    c = np.hypot(ab[..., 0], ab[..., 1])
    return Appearance(np.concatenate((signed_hk(ja, c)[..., None], ab), axis=-1), ja)


def decode(q, signed_energy, white, reference=203.):
    q = np.asarray(q, dtype=np.float64)
    if q.shape[-1:] != (3,):
        raise ValueError('Appearance coordinates need a final dimension of three')
    shape = q.shape
    energy = np.broadcast_to(np.asarray(signed_energy, dtype=np.float64), shape[:-1]).reshape(-1)
    if not np.isfinite(q).all() or not np.isfinite(energy).all():
        raise ValueError('Decode requires finite signed coordinates and energy')
    fl, aw = response_constants(reference)
    matrix = np.linalg.inv(CAT16) @ np.diag(CAT16 @ white)
    result = []
    for row, e in zip(q.reshape(-1, 3), energy):
        ab = list(map(S, row[1:]))
        c = norm(ab)
        h = np.arctan2(float(ab[1]/c), float(ab[0]/c)) if c else 0.
        ac = achromatic_response(S(e), aw)
        components = [ac, *(v*aw/(1204*eccentricity(h)) for v in ab)]
        values = [sum((S(v)*x for v, x in zip(axis, components)), S()) for axis in INVERSE]
        responses = [Response(v, 400-abs(v)) for v in values]
        if any(r.margin <= 0 for r in responses):
            raise ValueError('Mathematical decode requires response magnitudes below 400')
        result.append([float(uncompress(r, fl)) for r in responses])
    return (np.asarray(result, dtype=np.float64).reshape(shape) @ matrix.T)
