"""Independent oracle for the current DCTL; not bundled with Blender/reference."""
from dataclasses import dataclass
import numpy as np
from color_tools.perceptual_grade_reference.appearance import Appearance
from color_tools.color_core.scaled import Scalar as S, total, dot, norm
from color_tools.perceptual_grade_reference.responses import HK, signed_hk, requested_energy, State
from color_tools.perceptual_grade_reference.grading import (ZERO4, ZERO44, ZERO42,
                      coefficient_weights, scaled_weights)


# DCTL retains its existing physical-capacity classifier independently of the
# current reference model's achromatic-lightness crossover.
CHROMA_CAPACITY_FRACTION = .4


def capacity_drivers(q, capacity):
    q = np.asarray(q, dtype=np.float64)
    c = np.hypot(q[..., 1], q[..., 2])
    r = CHROMA_CAPACITY_FRACTION*np.asarray(capacity, dtype=np.float64)
    scale = np.maximum(c, r)
    a = np.divide(c, scale, out=np.zeros_like(c), where=scale > 0)
    b = np.divide(r, scale, out=np.zeros_like(c), where=scale > 0)
    denominator = a*a+b*b
    visible = (c/np.hypot(c, 2))**2
    high = np.divide(a*a, denominator, out=np.zeros_like(c), where=denominator > 0)
    low = np.divide(b*b, denominator, out=np.zeros_like(c), where=denominator > 0)
    return np.concatenate((np.stack((visible*low, visible*high), axis=-1),
                           q[..., 1:]/np.hypot(c, 2)[..., None]), axis=-1)


def adaptance_weight(magnitude, chroma, strength):
    """DCTL's retained translation envelope, separate from Blender Reach."""
    rate = .25+.75/(1+(np.asarray(chroma)/30)**2)
    alpha = np.clip(strength, 0, 1)
    return np.asarray(magnitude)/100*(alpha*rate)/(1-alpha+alpha*rate)

@dataclass(frozen=True)
class ColorSettings:
    # Tonal rows: Shadows, Midtones, White, Highlights. Driver columns: low, high, a, b.
    lightness: tuple = ZERO44
    chroma: tuple = ZERO44
    hue: tuple = ZERO4
    concentration: tuple = ZERO42
    adaptance: tuple = ZERO42
    lightness_fit: float = 0.
    chroma_fit: float = 0.
    hue_fit: float = 0.
    adaptance_fit: float = 0.
    global_gain: float = 0.
    global_hues: tuple = (0., 0.)
    adaptance_strength: float = .5


def concentration(ab, controls):
    ab, controls = np.asarray(ab, dtype=np.float64), np.asarray(controls, dtype=np.float64)
    c = np.hypot(ab[..., 0], ab[..., 1])
    v = controls[..., 0]+1j*controls[..., 1]
    t = np.abs(v)/.6
    scale = np.divide(np.tanh(t), t, out=np.ones_like(t), where=t > 0)
    w = scale*v*(c/np.hypot(c, 2))**2
    z = np.divide(ab[..., 0]+1j*ab[..., 1], c, out=np.zeros_like(c, dtype=np.complex128), where=c > 0)
    transformed = c*(z+w)/(1+np.conj(w)*z)
    result = np.stack((transformed.real, transformed.imag), axis=-1)
    return np.where((np.abs(v) == 0)[..., None], ab, result)


class Color:
    def __init__(self, settings, tone, boundary=None):
        self.settings, self.tone = settings, tone
        self._boundary = boundary
        self.active = any(np.any(getattr(settings, name)) for name in
                          ('lightness', 'chroma', 'hue', 'concentration', 'adaptance', 'global_gain', 'global_hues'))

    @property
    def boundary(self):
        if self._boundary is None:
            from color_tools.perceptual_grade_reference.cube import default_context
            return default_context()
        return self._boundary() if callable(self._boundary) else self._boundary

    def terms(self, h):
        p = self.settings
        def evaluate(values, fit, adapt=False):
            return coefficient_weights(h, self.tone.coefficient_knots, self.tone.high, fit, adapt) @ np.asarray(values)
        return (evaluate(p.lightness, p.lightness_fit), evaluate(p.chroma, p.chroma_fit),
                evaluate(p.hue, p.hue_fit), evaluate(p.concentration, p.hue_fit),
                evaluate(p.adaptance, p.adaptance_fit, True))

    def apply(self, appearance):
        if not self.active:
            return appearance.q.copy()
        q = appearance.q
        c = np.hypot(q[..., 1], q[..., 2])
        magnitude = np.hypot(appearance.ja, np.sqrt(HK*c))
        light, chroma, hue, concentrated, adapted = self.terms(magnitude)
        # These weights belong to the post-tone state and are sampled once.
        capacity = self.boundary.capacity(appearance.ja, np.arctan2(q[..., 2], q[..., 1]))
        d = capacity_drivers(q, capacity)
        ab = concentration(q[..., 1:], concentrated)
        angle = np.deg2rad(hue+d[..., :2] @ np.asarray(self.settings.global_hues))
        gain = np.exp2(self.settings.global_gain+np.sum(chroma*d, axis=-1))
        z = (ab[..., 0]+1j*ab[..., 1])*gain*np.exp(1j*angle)
        offset = adapted*adaptance_weight(magnitude, c, self.settings.adaptance_strength)[..., None]
        result = np.stack((q[..., 0]+np.sum(light*d, axis=-1), z.real+offset[..., 0], z.imag+offset[..., 1]), axis=-1)
        return np.where((magnitude == 0)[..., None], q, result)

    def scaled_apply(self, q, ja):
        if not self.active:
            return list(q)
        p = self.settings
        h, c = q[0], norm(q[1:])
        magnitude = norm([ja, (HK*c)**.5])
        if not magnitude:
            return list(q)
        hue_angle = np.arctan2(float(q[2]/c), float(q[1]/c)) if c else 0.
        r = CHROMA_CAPACITY_FRACTION*self.boundary.capacity_scaled(ja, hue_angle)
        denominator = c*c+r*r
        visibility = c*c/(c*c+4)
        d = [visibility*r*r/denominator if denominator else S(),
             visibility*c*c/denominator if denominator else S(),
             *(v/norm([c, 2]) for v in q[1:])]
        def evaluate(values, fit, adapt=False):
            weights = scaled_weights(magnitude, self.tone.coefficient_knots, self.tone.high, fit, adapt)
            values = np.asarray(values)
            return ([dot(weights, values[:, i]) for i in range(values.shape[1])]
                    if values.ndim == 2 else dot(weights, values))
        light = evaluate(p.lightness, p.lightness_fit)
        chroma = evaluate(p.chroma, p.chroma_fit)
        hue = evaluate(p.hue, p.hue_fit)
        concentrated = evaluate(p.concentration, p.hue_fit)
        adapted = evaluate(p.adaptance, p.adaptance_fit, True)
        radius = norm(concentrated)
        z = complex(float(q[1]/c), float(q[2]/c)) if c else 0j
        if radius:
            t = radius/.6
            tanh = 1. if t > 20 else np.tanh(float(t))
            w = .6*float(visibility)*tanh*complex(*(float(v/radius) for v in concentrated))
            z = (z+w)/(1+np.conj(w)*z)
        angle = (hue+dot(p.global_hues, d[:2])).modulo(360)
        z *= np.exp(1j*np.deg2rad(angle))
        gain = (S(p.global_gain)+dot(chroma, d)).exp2()
        rate = .25+.75/(1+(c/30)**2)
        strength = float(np.clip(p.adaptance_strength, 0, 1))
        envelope = magnitude/100*(strength*rate)/(1-strength+strength*rate)
        return [h+dot(light, d),
                total([c*gain*z.real, adapted[0]*envelope]),
                total([c*gain*z.imag, adapted[1]*envelope])]

    def apply_state(self, appearance):
        q = self.apply(appearance)
        return State(q, requested_energy(q, appearance.q, appearance.ja))

    def scaled_apply_state(self, q, ja, carried_energy=None):
        result = self.scaled_apply(q, ja)
        energy = (S(carried_energy) if carried_energy is not None and result == list(q)
                  else requested_energy(result, q, ja))
        return result, energy


from dataclasses import field, replace
from color_tools.perceptual_grade_reference.model import Model as ReferenceModel, Settings as ReferenceSettings, LinearSettings
from color_tools.perceptual_grade_reference.grading import ToneSettings, ColorSettings as CurrentColorSettings

@dataclass(frozen=True)
class Settings:
    white: str = 'D65'
    linear: LinearSettings = field(default_factory=LinearSettings)
    tone: ToneSettings = field(default_factory=ToneSettings)
    color: ColorSettings = field(default_factory=ColorSettings)

class Model(ReferenceModel):
    """DCTL equations reuse independent appearance/tone/cube math, without H–K repair."""
    def __init__(self, settings=None, space='Linear Rec.709', **kwargs):
        settings = Settings() if settings is None else settings
        super().__init__(ReferenceSettings(settings.white, settings.linear, settings.tone,
                         CurrentColorSettings()), space, hk_guard=False)
        self.settings = settings
        self.color = Color(settings.color, self.tone, lambda: self.boundary)
        p = settings.color
        values = np.r_[np.asarray(p.lightness).ravel(), np.asarray(p.chroma).ravel(),
                       np.asarray(p.adaptance).ravel(), np.asarray(p.concentration).ravel(),
                       p.hue, p.global_hues, p.global_gain, p.adaptance_strength,
                       p.lightness_fit, p.chroma_fit, p.hue_fit, p.adaptance_fit]
        if not np.isfinite(values).all():
            raise ValueError('DCTL controls must be finite')
        self.vector_controls = self.vector_controls and (
            np.max(abs(np.asarray(p.lightness))) < 2.**100 and
            np.max(abs(np.asarray(p.adaptance))) < 2.**100 and
            np.max(abs(np.asarray(p.chroma))) <= 64 and abs(p.global_gain) <= 128 and
            np.max(abs(np.asarray(p.hue))) < 2.**100 and
            np.max(abs(np.asarray(p.global_hues))) < 2.**100 and
            np.max(abs(np.asarray(p.concentration))) < 2.**100)
