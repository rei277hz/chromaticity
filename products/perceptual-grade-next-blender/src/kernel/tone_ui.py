"""Tone control limits and edited-anchor projection in normalized lightness."""

import math

from .prepare import GAMMA, nits_to_j, viewing
from .settings import TONE_CHROMA_LIMITS, TONE_PEAKS, ToneSettings


TONE_LEVEL_FIELDS = (
    "input_shadows", "input_midtones", "input_white", "input_highlights",
)
TONE_CHROMA_FIELDS = tuple(TONE_CHROMA_LIMITS)
TONE_FIELDS = (*TONE_LEVEL_FIELDS, *TONE_CHROMA_FIELDS, "fit", "peak_nits")
_DEFAULTS = ToneSettings()
TONE_DEFAULTS = dict(zip(TONE_LEVEL_FIELDS, _DEFAULTS.input_nits))
TONE_DEFAULTS.update((name, getattr(_DEFAULTS, name)) for name in TONE_CHROMA_FIELDS)
TONE_DEFAULTS.update(fit=_DEFAULTS.fit, peak_nits=str(int(_DEFAULTS.peak_nits)))
TONE_LIMITS = ((.01, 50.), (.1, 250.), (10., 1000.), (100., 10000.))


def _j_to_nits(value, reference):
    fl, aw = viewing(reference)
    response = aw * max(0., value) ** (1 / GAMMA) / 3.05
    return (27.13 * response / (400 - response)) ** (1 / .42) / fl * reference


def clamp_tone_anchor(settings, index, value):
    """Clamp only the edited anchor; never change either neighboring control."""
    if not isinstance(settings, ToneSettings):
        raise TypeError("Tone controls require ToneSettings")
    if type(index) is not int or not 0 <= index < len(TONE_LEVEL_FIELDS):
        raise ValueError("Tone anchor index must be between zero and three")
    if not math.isfinite(value):
        raise ValueError("Tone anchor must be finite")
    lo, hi = TONE_LIMITS[index]
    current = float(nits_to_j(min(hi, max(lo, value)), settings.reference_nits))
    low = float(nits_to_j(lo, settings.reference_nits))
    high = float(nits_to_j(hi, settings.reference_nits))
    if index:
        low = max(low, float(nits_to_j(settings.input_nits[index - 1], settings.reference_nits)) + .001)
    if index + 1 < len(TONE_LEVEL_FIELDS):
        high = min(high, float(nits_to_j(settings.input_nits[index + 1], settings.reference_nits)) - .001)
    return _j_to_nits(max(low, min(high, current)), settings.reference_nits)
