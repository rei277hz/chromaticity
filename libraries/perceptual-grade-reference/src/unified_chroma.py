"""Original Unified Chroma and full H-K Tone on signed appearance coordinates."""

from dataclasses import dataclass

import numpy as np

from .appearance import Appearance
from .grading import CHROMA_CROSSOVER, LOW_Y, Tone, ToneSettings, kernel
from .grading import normalized_kernel, normalized_scaled_kernel
from .responses import HK, State, signed_hk
from ..color_core.scaled import Scalar as S, dot, norm


@dataclass(frozen=True)
class UnifiedChromaSettings:
    input_nits: tuple = (LOW_Y * 203, .18 * 203, 203., 1000.)
    peak_nits: int = 1000
    fit: int = 0
    black_compression_nits: float = 0.
    muted_gain: float = 0.
    vivid_gain: float = 0.
    saturation_crossover: float = .45
    shadow_chroma: float = 0.
    highlight_chroma: float = 0.
    tone_crossover: float = 45.

    def __post_init__(self):
        anchors = np.asarray(self.input_nits, dtype=np.float64)
        if anchors.shape != (4,) or not np.isfinite(anchors).all():
            raise ValueError('Unified Chroma needs four finite input anchors')
        object.__setattr__(self, 'input_nits', tuple(anchors))
        if self.peak_nits not in (500, 1000, 2000, 4000):
            raise ValueError('Unified Chroma Peak Nits must be 500, 1000, 2000, or 4000')
        if self.fit not in (-2, -1, 0, 1, 2) or isinstance(self.fit, (bool, np.bool_)):
            raise ValueError('Unified Chroma Fit must be an integer from -2 through 2')
        object.__setattr__(self, 'fit', int(self.fit))
        ranges = (
            ('black_compression_nits', 0., 2.),
            ('muted_gain', -2., 2.),
            ('vivid_gain', -2., 2.),
            ('saturation_crossover', 0., 1.),
            ('shadow_chroma', -2., 2.),
            ('highlight_chroma', -2., 2.),
            ('tone_crossover', 10., 160.),
        )
        for name, lower, upper in ranges:
            if not lower <= getattr(self, name) <= upper:
                raise ValueError(f'Unified Chroma {name} must be between {lower} and {upper}')


def radial_gain(chroma, knee, low, high, invert=False):
    """Gain or reciprocal mapping gain of C (low*knee + high*C)/(knee+C)."""
    chroma, knee = np.broadcast_arrays(chroma, knee)
    if not invert:
        weight = np.divide(chroma, chroma + knee, out=np.ones_like(chroma), where=(chroma + knee) > 0)
        return low + (high - low) * weight

    # Solve for input / output. Normalization and conjugate roots avoid a
    # square of the input magnitude and subtraction of nearly equal values.
    scale = np.maximum(chroma, knee)
    x = np.divide(chroma, scale, out=np.zeros_like(chroma), where=scale > 0)
    k = np.divide(knee, scale, out=np.zeros_like(knee), where=scale > 0)
    d = low * k - x
    disc = np.hypot(d, 2 * np.sqrt(high * k) * np.sqrt(x))
    positive = (knee > 0) & (d >= 0)
    out = np.empty_like(chroma)
    out[...] = 1 / high
    np.divide(2 * k, disc + d, out=out, where=positive)
    np.divide(disc - d, 2 * high * x, out=out, where=(knee > 0) & ~positive)
    return np.where(low == high, 1 / high, out)


def _scaled_radial_gain(chroma, knee, low, high, invert):
    if not knee or low == high:
        return 1 / high if invert else high
    if not invert:
        return low + (high - low) * (chroma / (chroma + knee))
    d = low * knee - chroma
    disc = norm([d, 2 * (high * knee * chroma)**.5])
    if d >= 0:
        return 2 * knee / (disc + d)
    return (disc - d) / (2 * high * chroma)


def _ray_gain(ja, chroma, height):
    hk_chroma = HK * chroma
    denominator = np.hypot(hk_chroma, 2 * ja * height) + hk_chroma
    return np.divide(2 * height**2, denominator, out=np.ones_like(height), where=denominator > 0)


class _UnifiedTone(Tone):
    def __init__(self, settings):
        super().__init__(ToneSettings(input_nits=(0., *settings.input_nits),
                                      fit=settings.fit, peak_nits=settings.peak_nits))
        self.black = float(self.nits_to_j(settings.black_compression_nits))
        compressed = self._compress(self.source)
        self.span = float(compressed[-1])
        self.knots = compressed / self.span
        dx, dy = np.diff(self.knots), np.diff(self.target)
        self.slope = float(np.min(dy / dx))
        self.residual = np.maximum(0., dy - self.slope * dx)
        self.active = self.active or self.black != 0.
        self._intervals = tuple(zip(self.knots[:-1], self.knots[1:]))
        normalizers = np.array([kernel(1., left, right, float(self.width)) for left, right in self._intervals])
        # The derivative of an unnormalized transition is at most one.
        self._slope_upper_bound = self.slope + np.sum(self.residual / normalizers)

    def _compress(self, value, *, invert=False):
        # The black curve is the same rational map with end gains 1/2 and 1.
        return value * radial_gain(value, self.black * 2, .5, 1., invert=invert)

    def _curve(self, t):
        # Beyond 32 each softplus transition has reached its limit to f64 accuracy.
        transitions = np.stack([normalized_kernel(np.minimum(t, 32.), l, r, self.width)
                                for l, r in self._intervals], axis=-1)
        return np.where(t == 1., self.high / 100, self.slope * t + transitions @ self.residual)

    def _scaled_curve(self, t):
        if t == 1.:
            return S(self.high) / 100
        transitions = [normalized_scaled_kernel(min(t, S(32.)), l, r, self.width)
                       for l, r in self._intervals]
        return self.slope * t + dot(transitions, self.residual)

    def remap(self, height):
        height = np.asarray(height, dtype=np.float64)
        if not self.active:
            return height.copy()
        normalized = height / 100
        compressed = self._compress(normalized)
        return 100 * self._curve(compressed / self.span)

    def inverse(self, height):
        height = np.asarray(height, dtype=np.float64)
        if not np.isfinite(height).all() or np.any(height < 0.):
            raise ValueError('Tone inverse requires finite nonnegative lightness')
        if not self.active:
            return height.copy()
        if np.any((height > 2.**200) | ((height > 0.) & (height < 2.**-200))):
            return np.array([float(self.scaled_height(S(h), invert=True)) for h in height.flat]).reshape(height.shape)

        target = height / 100
        low, high = target / self._slope_upper_bound, target / self.slope
        for _ in range(60):
            middle = low + .5 * (high - low)
            below = self._curve(middle) < target
            low, high = np.where(below, middle, low), np.where(below, high, middle)
        t = np.where(height == self.high, 1., low + .5 * (high - low))
        compressed = self.span * t
        return 100 * self._compress(compressed, invert=True)

    def scaled_height(self, height, *, invert=False):
        if not self.active or not height:
            return height
        if not invert:
            normalized = height / 100
            compressed = normalized * _scaled_radial_gain(normalized, 2 * self.black, .5, 1., False)
            return 100 * self._scaled_curve(compressed / self.span)
        target = height / 100
        if height == self.high:
            t = S(1.)
        else:
            low, high = target / self._slope_upper_bound, target / self.slope
            for _ in range(60):
                middle = low + .5 * (high - low)
                if middle == low or middle == high:
                    break
                if self._scaled_curve(middle) < target:
                    low = middle
                else:
                    high = middle
            t = low + .5 * (high - low)
        compressed = self.span * t
        return 100 * compressed * _scaled_radial_gain(compressed, 2 * self.black, .5, 1., True)

    def scaled_ray(self, ja, ab, *, invert=False):
        hk_chroma = HK * norm(ab)
        height = norm([ja, hk_chroma**.5])
        if not height:
            return ja, ab
        mapped = self.scaled_height(height, invert=invert)
        gain = 2 * mapped**2 / (norm([hk_chroma, 2 * ja * mapped]) + hk_chroma)
        return ja * gain, [a * gain for a in ab]

    def scaled_apply(self, q, ja):
        if not self.active:
            return q, ja
        ja, ab = self.scaled_ray(ja, q[1:])
        return [signed_hk(ja, norm(ab)), *ab], ja


class UnifiedChroma:
    """Integrated 2-3A map on signed `(J_A, a, b)` appearance triples."""

    def __init__(self, settings=UnifiedChromaSettings()):
        self.settings = settings
        self.tone = _UnifiedTone(settings)
        self._muted = float(np.exp2(settings.muted_gain))
        self._vivid = float(np.exp2(settings.vivid_gain))
        self._saturation_knee = settings.saturation_crossover * np.sqrt(self._vivid / self._muted)
        self.chroma_active = any((settings.muted_gain, settings.vivid_gain,
                                  settings.shadow_chroma, settings.highlight_chroma))

    @property
    def active(self):
        return self.tone.active or self.chroma_active

    def chroma_gain(self, ja, chroma, *, invert=False):
        """Evaluate both chroma edits at the original signed achromatic lightness."""
        p = self.settings
        lightness = np.abs(ja)
        knee = lightness * self._saturation_knee
        tonal_knee = CHROMA_CROSSOVER * lightness / 9
        offset = lightness / p.tone_crossover - 1.
        t = np.minimum(1., np.abs(offset))
        amount = np.where(offset < 0., p.shadow_chroma, p.highlight_chroma) * t**2 * (3. - 2. * t)
        tonal_gain = np.exp2(amount)
        if invert:
            tonal = radial_gain(chroma, tonal_knee, 1., tonal_gain, invert=True)
            return tonal * radial_gain(chroma * tonal, knee, self._muted, self._vivid, invert=True)
        saturated = radial_gain(chroma, knee, self._muted, self._vivid)
        return saturated * radial_gain(chroma * saturated, tonal_knee, 1., tonal_gain)

    def chroma_map(self, ja, chroma, *, invert=False):
        return chroma * self.chroma_gain(ja, chroma, invert=invert)

    def _scaled_chroma_gain(self, ja, chroma, invert):
        p = self.settings
        lightness = abs(ja)
        knee = lightness * self._saturation_knee
        tonal_knee = CHROMA_CROSSOVER * lightness / 9
        offset = min(lightness / p.tone_crossover, S(2.)) - 1
        t = float(abs(offset))
        amount = (p.shadow_chroma if offset < 0 else p.highlight_chroma) * t**2 * (3 - 2 * t)
        tonal_gain = float(np.exp2(amount))
        if invert:
            g = _scaled_radial_gain(chroma, tonal_knee, 1., tonal_gain, True)
            return g * _scaled_radial_gain(chroma * g, knee, self._muted, self._vivid, True)
        g = _scaled_radial_gain(chroma, knee, self._muted, self._vivid, False)
        return g * _scaled_radial_gain(chroma * g, tonal_knee, 1., tonal_gain, False)

    def _array_map(self, points, invert):
        ja, ab = points[..., 0], points[..., 1:]
        if not invert and self.chroma_active:
            c = np.hypot(ab[..., 0], ab[..., 1])
            ab = ab * self.chroma_gain(ja, c)[..., None]
        if self.tone.active:
            c = np.hypot(ab[..., 0], ab[..., 1])
            height = np.hypot(ja, np.sqrt(HK * c))
            mapped = self.tone.inverse(height) if invert else self.tone.remap(height)
            gain = _ray_gain(ja, c, mapped)
            ja, ab = ja * gain, ab * gain[..., None]
        if invert and self.chroma_active:
            c = np.hypot(ab[..., 0], ab[..., 1])
            ab = ab * self.chroma_gain(ja, c, invert=True)[..., None]
        return np.concatenate((ja[..., None], ab), axis=-1)

    def _scaled_map(self, ja, ab, invert):
        if not invert and self.chroma_active:
            gain = self._scaled_chroma_gain(ja, norm(ab), False)
            ab = [a * gain for a in ab]
        if self.tone.active:
            ja, ab = self.tone.scaled_ray(ja, ab, invert=invert)
        if invert and self.chroma_active:
            gain = self._scaled_chroma_gain(ja, norm(ab), True)
            ab = [a * gain for a in ab]
        return ja, ab

    def _map(self, points, invert):
        points = np.asarray(points, dtype=np.float64)
        if points.shape[-1:] != (3,) or not np.isfinite(points).all():
            raise ValueError('Unified Chroma input must contain finite (J_A, a, b) triples')
        if not self.active:
            return points.copy()
        magnitude = np.abs(points)
        if np.all((magnitude == 0) | ((magnitude >= 2.**-200) & (magnitude <= 2.**200))):
            return self._array_map(points, invert)
        result = []
        for j, a, b in points.reshape(-1, 3):
            ja, ab = self._scaled_map(S(j), [S(a), S(b)], invert)
            result.append([float(v) for v in (ja, *ab)])
        return np.asarray(result, dtype=np.float64).reshape(points.shape)

    def forward(self, points):
        """Apply the integrated grade to signed appearance triples."""
        return self._map(points, False)

    def inverse(self, points):
        """Undo the integrated grade with one scalar softplus solve."""
        return self._map(points, True)

    def apply(self, appearance):
        if not self.active:
            return appearance
        chart = np.concatenate((appearance.ja[..., None], appearance.q[..., 1:]), axis=-1)
        point = self.forward(chart)
        ja, ab = point[..., 0], point[..., 1:]
        h = signed_hk(ja, np.hypot(ab[..., 0], ab[..., 1]))
        return Appearance(np.concatenate((h[..., None], ab), axis=-1), ja)

    def apply_state(self, state):
        if not self.active:
            return state
        result = self.apply(state)
        energy = result.ja * np.abs(result.ja) if self.tone.active else state.energy
        return State(result.q, energy)

    def scaled_apply(self, q, ja):
        if not self.active:
            return q, ja
        ja, ab = self._scaled_map(ja, q[1:], False)
        return [signed_hk(ja, norm(ab)), *ab], ja
