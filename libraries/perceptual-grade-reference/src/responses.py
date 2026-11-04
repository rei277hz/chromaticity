"""Signed base modCAM16 response equations, with explicit decoder domains."""
from dataclasses import dataclass
import numpy as np
from colour.appearance.hellwig2022 import eccentricity_factor, VIEWING_CONDITIONS_HELLWIG2022
from ..color_core.scaled import Scalar as S, dot, norm, signed_power, total


@dataclass(frozen=True)
class State:
    q: np.ndarray
    energy: np.ndarray

    @property
    def ja(self):
        e=np.asarray(self.energy)
        if e.dtype==object:return np.asarray([signed_power(v,.5) for v in e.flat],dtype=object).reshape(e.shape)
        return np.sign(e)*np.sqrt(abs(e))

B = 400.
POWER = .42
HK = 66.
GAMMA = VIEWING_CONDITIONS_HELLWIG2022['Dark'].c*(1.48+np.sqrt(.1))
OPPONENT = np.array([[1., -12/11, 1/11], [1/9, 1/9, -2/9]])
INVERSE = np.array([[460., 451., 288.], [460., -891., -261.], [460., -220., -6300.]])/1403


@dataclass(frozen=True)
class Response:
    value: S
    margin: S  # B - abs(value), including when value rounds to +/-B.


def compress(cone, fl):
    cone = S(cone)
    p = (fl*abs(cone))**POWER
    return Response((1 if cone >= 0 else -1)*B*p/(27.13+p), B*27.13/(27.13+p))


def uncompress(response, fl):
    if response.margin <= 0:
        raise ValueError('Uncompression requires a strictly positive pole margin')
    return (1 if response.value >= 0 else -1)*(27.13*abs(response.value)/response.margin)**(1/POWER)/fl


def eccentricity(angle):
    return np.asarray(eccentricity_factor(np.rad2deg(angle) % 360), dtype=np.float64)


def signed_hk(ja, chroma):
    """Reflect H about sqrt(66C) on the negative achromatic side."""
    if isinstance(ja, S):
        b = (HK*chroma)**.5
        magnitude = norm([ja, b])
        return magnitude if ja >= 0 else 2*b-magnitude
    b = np.sqrt(HK*np.asarray(chroma))
    magnitude = np.hypot(ja, b)
    return np.where(np.asarray(ja) >= 0, magnitude, 2*b-magnitude)


def hk_energy(h, chroma):
    """Continuous signed inverse E=JA*abs(JA); all real H are defined."""
    b = (HK*chroma)**.5 if isinstance(h, S) else np.sqrt(HK*np.asarray(chroma))
    u = h-b
    return u*(abs(u)+2*b) if isinstance(h, S) else u*(np.abs(u)+2*b)


def achromatic_response(energy, aw):
    """Authoritative requested A from carried signed energy, without cancellation."""
    return aw*signed_power(energy, 1/(2*GAMMA))/100**(1/GAMMA)


def requested_energy(q, base_q, base_ja):
    """Carry the anchor energy through signed coordinate changes.

    u=E/(M+B) retains tiny signed departures that rounded H cannot store.
    The difference of u*abs(u) is factored; near reset E+delta is exact at
    zero change, while the direct form avoids large-change cancellation.
    """
    if isinstance(base_ja, S):
        c, c0 = norm(q[1:]), norm(base_q[1:])
        b, b0 = (HK*c)**.5, (HK*c0)**.5
        e0 = base_ja*abs(base_ja)
        denominator = norm([base_ja, b0])+b0
        u0 = e0/denominator if denominator else S()
        db = HK*(c-c0)/(b+b0) if b+b0 else S()
        du = q[0]-base_q[0]-db
        u = u0+du
        r = abs(u)+abs(u0)
        slope = r if u*u0 >= 0 else (u*u+u0*u0)/r
        change = total([du*(slope+2*b), 2*u0*db])
        return e0+change if abs(change) <= .25*abs(e0) else u*(abs(u)+2*b)
    c, c0 = np.hypot(q[..., 1], q[..., 2]), np.hypot(base_q[..., 1], base_q[..., 2])
    b, b0 = np.sqrt(HK*c), np.sqrt(HK*c0)
    e0 = base_ja*np.abs(base_ja)
    denominator = np.hypot(base_ja, b0)+b0
    u0 = np.divide(e0, denominator, out=np.zeros_like(e0), where=denominator > 0)
    db = np.divide(HK*(c-c0), b+b0, out=np.zeros_like(c), where=b+b0 > 0)
    du = q[..., 0]-base_q[..., 0]-db
    u = u0+du
    r = np.abs(u)+np.abs(u0)
    opposite = np.divide(u*u+u0*u0, r, out=np.zeros_like(r), where=r > 0)
    slope = np.where(u*u0 >= 0, r, opposite)
    change = du*(slope+2*b)+2*u0*db
    return np.where(np.abs(change) <= .25*np.abs(e0), e0+change, u*(np.abs(u)+2*b))


def coordinates(responses, aw):
    values = [r.value for r in responses]
    ac = dot([2., 1., .05], values)
    # Opponent rows sum to zero. Margins retain chroma near the white pole;
    # values retain it near black (without adding and subtracting Colour's .1).
    same_sign = all(v >= 0 for v in values) or all(v <= 0 for v in values)
    near_pole = same_sign and max(abs(v) for v in values) > B/2
    sign = 1 if ac >= 0 else -1
    ab = [(-sign*dot(row, [r.margin for r in responses]) if near_pole else dot(row, values))
          for row in OPPONENT]
    radius = norm(ab)
    angle = np.arctan2(float(ab[1]/radius), float(ab[0]/radius)) if radius else 0.
    factor = 1204*eccentricity(angle)/aw
    ab = [v*factor for v in ab]
    ja = 100*signed_power(ac/aw, GAMMA)
    return [signed_hk(ja, norm(ab)), *ab], ja


