"""Tone control limits and edited-anchor projection in normalized lightness."""

import math

from .prepare import GAMMA, nits_to_j, viewing
from .settings import LOW_Y, ToneSettings


TONE_LEVEL_FIELDS = (
    "input_black", "input_shadows", "input_midtones", "input_white", "input_highlights",
)
TONE_FIELDS = (*TONE_LEVEL_FIELDS, "fit", "peak_nits")
TONE_DEFAULTS = dict(zip(TONE_LEVEL_FIELDS, (0., LOW_Y * 203., .18 * 203., 203., 1000.)))
TONE_DEFAULTS.update(fit=0., peak_nits="1000")
TONE_LIMITS = ((0., 2.), (.01, 50.), (.1, 250.), (10., 1000.), (100., 10000.))
TONE_PEAKS = (500, 1000, 2000, 4000)


def _j_to_nits(value, reference):
    fl, aw = viewing(reference)
    response = aw * max(0., value) ** (1 / GAMMA) / 3.05
    return (27.13 * response / (400 - response)) ** (1 / .42) / fl * reference


def clamp_tone_anchor(settings, index, value):
    """Clamp only the edited anchor; never change either neighboring control."""
    if not isinstance(settings, ToneSettings):
        raise TypeError("Tone controls require ToneSettings")
    if type(index) is not int or not 0 <= index < len(TONE_LEVEL_FIELDS):
        raise ValueError("Tone anchor index must be between zero and four")
    if not math.isfinite(value):
        raise ValueError("Tone anchor must be finite")
    lo, hi = TONE_LIMITS[index]
    current = float(nits_to_j(min(hi, max(lo, value)), settings.reference_nits))
    low = float(nits_to_j(lo, settings.reference_nits))
    high = float(nits_to_j(hi, settings.reference_nits))
    if index:
        low = max(low, float(nits_to_j(settings.input_nits[index - 1], settings.reference_nits)) + .001)
    if index < 4:
        high = min(high, float(nits_to_j(settings.input_nits[index + 1], settings.reference_nits)) - .001)
    return _j_to_nits(max(low, min(high, current)), settings.reference_nits)
