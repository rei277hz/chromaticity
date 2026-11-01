"""Independent analytic custom grading equations; exact-real counterparts in proofs.

Kernels use an algebraic log-domain form of the exact softplus integral, not
the production quadrature/table branches. All other operations use NumPy f64.
"""
from dataclasses import dataclass, field, replace
import numpy as np
from .._shared import modcam16 as response_math, scaled
from .._shared import modcam16

Appearance = modcam16.Appearance
response_constants = modcam16.viewing
encode_cones = modcam16.encode_cones
S, total, dot, norm = scaled.Scalar, scaled.total, scaled.dot, scaled.norm
smooth_floor, smooth_cap = scaled.smooth_floor, scaled.smooth_cap
GAMMA, HK, signed_hk = modcam16.GAMMA, modcam16.HK, modcam16.signed_hk
requested_energy, State = modcam16.requested_energy, modcam16.State
from ..settings import ColorSettings, ToneSettings
from .tonal_web import WebSettings, TonalWeb
from .selective_adaptance import SelectiveAdaptance, GuardedWarpDisplay
from .saturation import project, bounded_project, bounded_unproject

# Derived by buck2 build //libraries/perceptual-grade-core:shadow_anchor.
LOW_Y = 0.015507796089266005
# Chroma per absolute achromatic J_A at equal low/high membership.
CHROMA_CROSSOVER = 35./75.
ZERO4 = (0.,)*4
ZERO44 = (ZERO4,)*4
ZERO42 = ((0., 0.),)*4


def kernel(t, left, right, width):
    """Integral from 0 to t of sigmoid((v-l)/w)-sigmoid((v-r)/w).

For t>=0, K/w=log(1+(B-A)(U-1)/((A+1)(B+U))), where
A=exp(l/w), B=exp(r/w), U=exp(t/w). Evaluate the positive quotient in logs.
This remains accurate for narrow intervals and tiny t without quadrature.
"""
    if not (0 <= left < right and width > 0):
        raise ValueError('Kernel requires 0 <= left < right and width > 0')
    t = np.asarray(t, dtype=np.float64)
    gap = np.log(-np.expm1(-(right-left)/width))
    base = np.log1p(np.exp(-left/width))
    with np.errstate(divide='ignore', invalid='ignore'):
        positive = ((t-left)/width-base-np.logaddexp(0, (t-right)/width)
                    +gap+np.log(-np.expm1(-np.maximum(t, 0)/width)))
        negative = (-left/width-base-np.logaddexp(0, (t-right)/width)
                    +gap+np.log(-np.expm1(np.minimum(t, 0)/width)))
        out = np.where(t >= 0, width*np.logaddexp(0, positive),
                       width*np.log1p(-np.exp(negative)))
    return np.where(t == 0, 0., out)


def smoother(t):
    t = np.clip(np.asarray(t, dtype=np.float64), 0, 1)
    return t**3*(10+t*(-15+6*t))


def normalized_kernel(t, left, right, width):
    """K(t)/K(1) without overflowing or underflowing the width/normalizer.

    When the width is below the input spacing, retain its endpoint log(2)
    terms; exponentially small tails round to zero. At the opposite limit,
    the quotient is t up to O((max(1,|t|)/w)^2), below float64 rounding.
    """
    t = np.asarray(t, dtype=np.float64)
    width = S(width)
    if width > S(max(1., float(np.max(np.abs(t), initial=0))))*2.**27:
        return t.copy()
    if width < S(2.**-500):
        w = float(width)
        result = np.maximum(0., np.minimum(t, right)-left)
        result = np.where(t == left, w*np.log(2), result)
        result = np.where(t == right, right-left-w*np.log(2), result)
        base = right-left-(w*np.log(2) if left == 0 else 0.)
        return result/base
    w = float(width)
    return kernel(t, left, right, w)/kernel(1., left, right, w)


def fit_width(fit):
    return .05*(-S(fit)).exp2()


def normalized_scaled_kernel(t, left, right, width):
    t, width = S(t), S(width)
    if not t:
        return S()
    if t.e >= -500:
        return S(float(normalized_kernel(float(t), left, right, width)))
    if width > 2.**27:
        return t
    if width < S(2.**-500):
        if left > 0:
            return S()  # Tail is below rounding relative to the positive baseline.
        ratio = t/width
        if ratio > 2.**53:
            integral = t-width*np.log(2)
        elif ratio < S(2.**-52):
            integral = t/2
        else:
            v = float(ratio)
            integral = width*(np.log1p(np.expm1(v)/2) if v < 1 else np.logaddexp(0, v)-np.log(2))
        return integral/right
    w = float(width)
    a, b = np.exp(-left/w), np.exp(-right/w)
    slope = a*(-np.expm1(-(right-left)/w))/((1+a)*(1+b))
    return t*(slope/float(kernel(1., left, right, w)))


def scaled_weights(h, knots, high, fit, adaptance=False):
    t = min(S(1.), max(S(), S(h)/high))
    t = t**3*(10+t*(-15+6*t))
    width = fit_width(fit)
    u, previous = [], S(1.)
    for left, right in zip(knots[:-1], knots[1:]):
        previous = min(previous, max(S(), min(S(1.), normalized_scaled_kernel(t, left, right, width))))
        u.append(previous)
    return [(u[0] if adaptance else S(1.))-u[1], u[1]-u[2], u[2]-u[3], u[3]]


def coefficient_weights(h, knots, high, fit, adaptance=False):
    t = smoother(np.asarray(h)/high)
    width = fit_width(fit)
    u = np.stack([normalized_kernel(t, l, r, width)
                  for l, r in zip(knots[:-1], knots[1:])], axis=-1)
    u = np.minimum.accumulate(np.clip(u, 0, 1), axis=-1)
    first = u[..., 0] if adaptance else np.ones_like(t)
    return np.stack((first-u[..., 1], u[..., 1]-u[..., 2], u[..., 2]-u[..., 3], u[..., 3]), axis=-1)


class Tone:
    def __init__(self, settings):
        self.settings = settings
        self.reference = float(smooth_cap(smooth_floor(settings.reference_nits, 48.), 1000.))
        self.peak = float(smooth_cap(smooth_floor(settings.peak_nits, 2*self.reference), 10000.))
        self.target = self.nits_to_j([0., LOW_Y*self.reference, .18*self.reference, self.reference, self.peak])
        self.target[0], self.target[3] = 0., 1.
        self.source = self.nits_to_j(settings.input_nits)
        for i in range(1, 5):
            self.source[i] = max(self.source[i], self.source[i-1]+.001)
        self.black, self.span = self.source[0], self.source[-1]-self.source[0]
        self.knots = (self.source-self.black)/self.span
        self.width = fit_width(settings.fit)
        self.slope = np.min(np.diff(self.target)/np.diff(self.knots))
        self.residual = np.maximum(0, np.diff(self.target)-self.slope*np.diff(self.knots))
        self.active = not np.array_equal(self.source, self.target)
        self.high = 100*self.target[-1]
        self.coefficient_knots = smoother(self.target/self.target[-1])

    def nits_to_j(self, nits):
        fl, _ = response_constants(self.reference)
        white_p = S(fl)**.42
        white_response = white_p/(27.13+white_p)
        result = []
        for value in np.asarray(nits, dtype=np.float64).flat:
            p = (fl*max(S(), S(value))/self.reference)**.42
            result.append(float(((p/(27.13+p))/white_response)**GAMMA))
        return np.asarray(result).reshape(np.shape(nits))

    def remap(self, h):
        h = np.asarray(h, dtype=np.float64)
        if not self.active:
            return h.copy()
        t = np.maximum(0, (h/100-self.black)/self.span)
        k = np.stack([normalized_kernel(t, l, r, self.width) for l, r in zip(self.knots[:-1], self.knots[1:])], axis=-1)
        out = 100*(self.slope*t+k @ self.residual)
        return np.where(t == 1, self.high, out)

    def inverse(self, h):
        """Unique positive tone inverse; black canonically selects H=0."""
        h = np.asarray(h, dtype=np.float64)
        if np.any(~np.isfinite(h)) or np.any(h < 0):
            raise ValueError('Tone inverse requires finite nonnegative lightness')
        if not self.active:
            return h.copy()
        low = np.zeros_like(h)
        high = np.maximum(100*(self.black+self.span), h)
        for _ in range(64):
            below = self.remap(high) < h
            if not np.any(below):
                break
            high = np.where(below, high*2+1, high)
        else:
            raise ArithmeticError('Tone inverse could not bracket the target')
        for _ in range(80):
            middle = (low+high)/2
            below = self.remap(middle) < h
            low, high = np.where(below, middle, low), np.where(below, high, middle)
        return np.where(h == 0, 0., (low+high)/2)

    def apply(self, appearance):
        if not self.active:
            return appearance
        q, j = appearance.q, appearance.ja
        c = np.hypot(q[..., 1], q[..., 2])
        h = self.remap(np.hypot(j, np.sqrt(HK*c)))
        denominator = np.hypot(HK*c, 2*j*h)+HK*c
        gain = np.divide(2*h*h, denominator, out=np.zeros_like(h), where=denominator > 0)
        ja, ab = gain*j, q[..., 1:]*gain[..., None]
        out = np.concatenate((signed_hk(ja, np.hypot(ab[..., 0], ab[..., 1]))[..., None], ab), axis=-1)
        return Appearance(out, ja)

    def scaled_apply(self, q, ja):
        if not self.active:
            return q, ja
        c = norm(q[1:])
        magnitude = norm([ja, (HK*c)**.5])
        t = max(S(), (magnitude/100-self.black)/self.span)
        if t.e >= -500 or not t:
            h = S(float(self.remap(float(magnitude))))
        else:
            values = [normalized_scaled_kernel(t, left, right, self.width)
                      for left, right in zip(self.knots[:-1], self.knots[1:])]
            h = 100*(self.slope*t+dot(values, self.residual))
        denominator = norm([HK*c, 2*ja*h])+HK*c
        gain = 2*h*h/denominator if denominator else S()
        ja, ab = ja*gain, [v*gain for v in q[1:]]
        return [signed_hk(ja, norm(ab)), *ab], ja


def _drivers_at_radius(q, radius):
    """Stable complementary memberships and opponent axes at a supplied radius."""
    q = np.asarray(q, dtype=np.float64)
    c = np.hypot(q[..., 1], q[..., 2])
    r = np.asarray(radius, dtype=np.float64)
    scale = np.maximum(c, r)
    a = np.divide(c, scale, out=np.zeros_like(c), where=scale > 0)
    b = np.divide(r, scale, out=np.zeros_like(c), where=scale > 0)
    denominator = a*a+b*b
    visible = (c/np.hypot(c, 2))**2
    high = np.divide(a*a, denominator, out=np.zeros_like(c), where=denominator > 0)
    low = np.divide(b*b, denominator, out=np.zeros_like(c), where=denominator > 0)
    return np.concatenate((np.stack((visible*low, visible*high), axis=-1),
                           q[..., 1:]/np.hypot(c, 2)[..., None]), axis=-1)


def drivers(q, ja):
    """Post-Tone drivers; low/high cross at C=(35/75)*abs(J_A).

    Both chroma memberships vanish on the neutral axis. Chromatic J_A=0
    belongs entirely to high chroma, with the same neutral visibility fade.
    """
    return _drivers_at_radius(q, CHROMA_CROSSOVER*np.abs(np.asarray(ja, dtype=np.float64)))



class Color(GuardedWarpDisplay):
    """J/C drivers, hue/chroma web, selective cone Adaptance and final scale."""
    def __init__(self, settings, tone, boundary=None):
        self.settings, self.tone, self._boundary = settings, tone, boundary
        web = settings.web
        if not isinstance(web, WebSettings):
            web = WebSettings(log_chroma=web.log_chroma,
                              hue_degrees=web.hue_degrees,
                              log_scale=web.log_scale)
        self.web = TonalWeb(web, tone, encoder=encode_cones)
        self.adaptation = SelectiveAdaptance(settings.adaptance, 100*np.asarray(tone.target[1:]),
                                             response_constants(tone.reference)[1], settings.adaptance_half_saturation,
                                             response_math=response_math)
        self.active = self.web.active or any(np.any(getattr(settings, name)) for name in
                                           ('lightness', 'chroma', 'adaptance', 'global_gain'))

    @property
    def boundary(self):
        if self._boundary is None:
            from .cube import default_context
            return default_context()
        return self._boundary() if callable(self._boundary) else self._boundary

    def terms(self, h):
        p = self.settings
        def evaluate(values, fit):
            return coefficient_weights(h, self.tone.coefficient_knots, self.tone.high, fit) @ np.asarray(values)
        return evaluate(p.lightness, p.lightness_fit), evaluate(p.chroma, p.chroma_fit)

    def _crossover_radius(self, q, ja):
        return CHROMA_CROSSOVER*np.abs(ja)

    def _scaled_crossover_radius(self, q, ja):
        return CHROMA_CROSSOVER*abs(ja)

    def warp_state(self, state, tonal_h=None, source_chroma=None, source_energy=None):
        c = np.hypot(state.q[..., 1], state.q[..., 2]) if source_chroma is None else np.asarray(source_chroma)
        h = np.hypot(state.ja, np.sqrt(HK*c)) if tonal_h is None else np.asarray(tonal_h)
        e0 = state.energy if source_energy is None else source_energy
        transform = lambda q, e: self.adaptation.apply(q, e, h, c, e0)
        q, e = self.web.apply(state.q, state.energy, h, transform=transform)
        return State(q, e)

    def apply_state(self, appearance):
        q = appearance.q
        c = np.hypot(q[..., 1], q[..., 2])
        h = np.hypot(appearance.ja, np.sqrt(HK*c))
        p = self.settings
        energy = appearance.energy if hasattr(appearance, 'energy') else appearance.ja*np.abs(appearance.ja)
        if not self.active:
            return State(q.copy(), np.array(energy, copy=True))
        if any(np.any(v) for v in (p.lightness, p.chroma, p.global_gain)):
            light, chroma = self.terms(h)
            d = _drivers_at_radius(q, self._crossover_radius(q, appearance.ja))
            gain = np.exp2(p.global_gain+np.sum(chroma*d, axis=-1))
            out = np.concatenate(((q[..., 0]+np.sum(light*d, axis=-1))[..., None],
                                  q[..., 1:]*gain[..., None]), axis=-1)
            out = np.where((h == 0)[..., None], q, out)
            energy = np.where(np.all(out == q, axis=-1), energy, requested_energy(out, q, appearance.ja))
        else:
            out = q.copy()
        return self.warp_state(State(out, energy), h, c, appearance.energy if hasattr(appearance, 'energy') else appearance.ja*abs(appearance.ja))

    def apply(self, appearance):
        return self.apply_state(appearance).q

    def scaled_apply_state(self, q, ja, carried_energy=None):
        q, ja = list(map(S, q)), S(ja)
        p = self.settings
        energy = S(carried_energy) if carried_energy is not None else ja*abs(ja)
        c = norm(q[1:]); h = norm([ja, (HK*c)**.5])
        if not self.active or not h:
            return q, energy
        result = list(q)
        if any(np.any(v) for v in (p.lightness, p.chroma, p.global_gain)):
            r = self._scaled_crossover_radius(q, ja)
            denominator = c*c+r*r; visibility = c*c/(c*c+4)
            d = [visibility*r*r/denominator if denominator else S(),
                 visibility*c*c/denominator if denominator else S(), *(v/norm([c, 2]) for v in q[1:])]
            def evaluate(values, fit):
                weights = scaled_weights(h, self.tone.coefficient_knots, self.tone.high, fit)
                return [dot(weights, np.asarray(values)[:, i]) for i in range(4)]
            light, chroma = evaluate(p.lightness, p.lightness_fit), evaluate(p.chroma, p.chroma_fit)
            gain = (S(p.global_gain)+dot(chroma, d)).exp2()
            result = [q[0]+dot(light, d), *(v*gain for v in q[1:])]
            if result != q:
                energy = requested_energy(result, q, ja)
        e0 = S(carried_energy) if carried_energy is not None else ja*abs(ja)
        transform = lambda value, stored: self.adaptation.scaled_apply(value, stored, h, c, e0)
        return self.web.scaled_apply(result, energy, h, transform=transform)

    def scaled_apply(self, q, ja):
        return self.scaled_apply_state(q, ja)[0]

    def warp_targets(self, tonal_row):
        geometry = self.web.geometry; h = geometry.anchors[tonal_row]
        q = np.concatenate(([[h, 0., 0.]], geometry.q[tonal_row]), axis=0)
        energy = np.r_[h*h, geometry.energy[tonal_row]]
        return self.warp_state(State(q, energy), h)

    def target_settings(self, tonal_row, handle, target_ab):
        """Absolute combined page target; -1 denotes the neutral center."""
        if not 0 <= tonal_row < 4 or not -1 <= handle < 6:
            raise ValueError('Warp target index is outside its four-by-seven grid')
        h = self.web.geometry.anchors[tonal_row]
        target = np.asarray(target_ab, float)
        if target.shape != (2,) or not np.isfinite(target).all():
            raise ValueError('Warp target must be a finite a/b pair')
        if handle == -1:
            adapted = np.array(self.settings.adaptance, float)
            adapted[tonal_row] = target
            SelectiveAdaptance(adapted, self.web.geometry.anchors, self.adaptation.aw,
                               self.settings.adaptance_half_saturation)
            return replace(self.settings, adaptance=tuple(map(tuple, adapted)))
        return replace(self.settings, web=self.adaptation.target(self.web, tonal_row, handle, target))

    def saturation_targets(self, tonal_row):
        state = self.warp_targets(tonal_row)
        return project(state.q, state.energy)

    def bounded_saturation_targets(self, tonal_row):
        state = self.warp_targets(tonal_row)
        return bounded_project(state.q, state.energy)

    def target_bounded_saturation_settings(self, tonal_row, handle, target):
        """Convert the bounded display destination to the branch-local solver."""
        return self.target_saturation_settings(tonal_row, handle, bounded_unproject(target))

    def target_saturation_settings(self, tonal_row, handle, target):
        """Set a linear saturation destination while preserving the local branch."""
        if not 0 <= tonal_row < 4 or not -1 <= handle < 6:
            raise ValueError('Warp target index is outside its four-by-seven grid')
        target = np.asarray(target, float)
        if target.shape != (2,) or not np.isfinite(target).all():
            raise ValueError('Warp saturation target must be a finite pair')
        if handle == -1:
            return self.target_settings(tonal_row, handle, self.web.geometry.anchors[tonal_row]*target)
        return replace(self.settings, web=self.adaptation.saturation_target(self.web, tonal_row, handle, target))
