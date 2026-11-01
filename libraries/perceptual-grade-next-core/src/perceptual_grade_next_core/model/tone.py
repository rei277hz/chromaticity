"""Reference quintic-knot Tone map with the supported Next Fit range."""

import math
import numpy as np

from ..settings import ToneSettings
from .._shared import modcam16

GAMMA = modcam16.GAMMA
viewing = modcam16.viewing


LOW_Y = 0.015507796089266005


def _kernel(t, left, right, width):
    """Stable log-domain integral of a difference of logistic steps."""
    gap = math.log(-math.expm1(-(right - left) / width))
    base = math.log1p(math.exp(-left / width))
    t = np.asarray(t, dtype=np.float64)
    with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
        positive = ((t - left) / width - base - np.logaddexp(0, (t - right) / width)
                    + gap + np.log(-np.expm1(-np.maximum(t, 0.0) / width)))
        negative = (-left / width - base - np.logaddexp(0, (t - right) / width)
                    + gap + np.log(-np.expm1(np.minimum(t, 0.0) / width)))
        result = np.where(t >= 0.0, width * np.logaddexp(0.0, positive),
                          width * np.log1p(-np.exp(negative)))
    return np.where(t == 0.0, 0.0, result)


def _normalized_kernel(t, left, right, width):
    t = np.asarray(t, dtype=np.float64)
    if width > max(1.0, float(np.max(np.abs(t), initial=0.0))) * 2.0**27:
        return t.copy()
    if width < 2.0**-500:
        result = np.maximum(0.0, np.minimum(t, right) - left)
        result = np.where(t == left, width * math.log(2.0), result)
        result = np.where(t == right, right - left - width * math.log(2.0), result)
        base = right - left - (width * math.log(2.0) if left == 0.0 else 0.0)
        return result / base
    return _kernel(t, left, right, width) / _kernel(1.0, left, right, width)


def _smooth5(value):
    value = np.clip(np.asarray(value, dtype=np.float64), 0.0, 1.0)
    return value**3 * (10.0 + value * (-15.0 + 6.0 * value))


class ToneMap:
    """Prepared analytic Tone map; settings validation fixes D65 / 203 nits."""

    def __init__(self, settings: ToneSettings):
        if not isinstance(settings, ToneSettings):
            raise ValueError("settings must be ToneSettings")
        self.settings = settings
        self.reference = settings.reference_nits
        self.peak = settings.peak_nits
        self.width = 0.05 * 2.0**(-settings.fit)
        self.fl, self.aw = viewing(self.reference)
        self.target = self._nits_to_j(np.array([
            0.0, LOW_Y * self.reference, 0.18 * self.reference,
            self.reference, self.peak,
        ]))
        self.target[0], self.target[3] = 0.0, 1.0
        self.source = self._nits_to_j(np.asarray(settings.input_nits, dtype=np.float64))
        for i in range(1, 5):
            self.source[i] = max(self.source[i], self.source[i - 1] + 0.001)
        self.black = float(self.source[0])
        self.span = float(self.source[-1] - self.source[0])
        self.knots = (self.source - self.black) / self.span
        self.slope = float(np.min(np.diff(self.target) / np.diff(self.knots)))
        self.residual = np.maximum(0.0, np.diff(self.target) - self.slope * np.diff(self.knots))
        self.high = 100.0 * float(self.target[-1])
        self.active = not np.array_equal(self.source, self.target)

    def _nits_to_j(self, nits):
        white_p = self.fl**0.42
        white_response = white_p / (27.13 + white_p)
        nits = np.asarray(nits, dtype=np.float64)
        p = (self.fl * np.maximum(nits, 0.0) / self.reference)**0.42
        response = p / (27.13 + p)
        return np.sign(response) * np.abs(response / white_response)**GAMMA

    def remap(self, h):
        h = np.asarray(h, dtype=np.float64)
        if not np.isfinite(h).all():
            raise ValueError("Tone input must be finite")
        if not self.active:
            return h.copy()
        t = np.maximum(0.0, (h / 100.0 - self.black) / self.span)
        integrals = np.stack([
            _normalized_kernel(t, left, right, self.width)
            for left, right in zip(self.knots[:-1], self.knots[1:])
        ], axis=-1)
        result = 100.0 * (self.slope * t + integrals @ self.residual)
        return np.where(t == 1.0, self.high, result)

    def inverse(self, h):
        h = np.asarray(h, dtype=np.float64)
        if not np.isfinite(h).all() or np.any(h < 0.0):
            raise ValueError("Tone inverse requires finite nonnegative lightness")
        if not self.active:
            return h.copy()
        low = np.zeros_like(h)
        high = np.maximum(100.0 * (self.black + self.span), h)
        for _ in range(64):
            below = self.remap(high) < h
            if not np.any(below):
                break
            high = np.where(below, high * 2.0 + 1.0, high)
        else:
            raise ArithmeticError("Tone inverse could not bracket its target")
        for _ in range(80):
            middle = (low + high) / 2.0
            below = self.remap(middle) < h
            low, high = np.where(below, middle, low), np.where(below, high, middle)
        return np.where(h == 0.0, 0.0, (low + high) / 2.0)
