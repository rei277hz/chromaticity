"""Before and after Tone waveforms for the current Grade input capture."""

from dataclasses import dataclass

import numpy as np

from .color_core.modcam16 import HK, encode_cones
from .kernel.prepare import nits_to_j, prepare_tone


PLOT_MAX = float(nits_to_j(4000.0))
_WAVEFORM_WIDTH = 192
_WAVEFORM_HEIGHT = 160
_HISTOGRAM_BINS = 128


@dataclass(frozen=True, eq=False)
class ToneWaveforms:
    before: np.ndarray
    after: np.ndarray
    histogram: np.ndarray

    @property
    def plot_max(self):
        return PLOT_MAX


def _waveform(lightness, columns, weights):
    rows = np.minimum((lightness * (_WAVEFORM_HEIGHT / PLOT_MAX)).astype(int),
                      _WAVEFORM_HEIGHT - 1)
    bins = rows * _WAVEFORM_WIDTH + columns
    mass = np.bincount(bins, weights=weights, minlength=_WAVEFORM_WIDTH * _WAVEFORM_HEIGHT)
    # Both waveforms use the same density transfer, including fractional alpha.
    level = np.minimum(7., 2. * np.log2(1. + mass))
    opacity = np.where(mass > 0., .22 + .1 * level, 0.)
    result = opacity.astype(np.float32).reshape(_WAVEFORM_HEIGHT, _WAVEFORM_WIDTH)
    result.setflags(write=False)
    return result


def analyze(rgba, linear, tone):
    """Project captured working-space RGB through Linear and Tone in J units."""
    tone = prepare_tone(tone)
    pixels = np.asarray(rgba, dtype=np.float64)
    valid = np.isfinite(pixels).all(axis=-1) & (pixels[..., 3] > 0.)
    samples = pixels[valid]
    weights = np.minimum(samples[:, 3], 1.)
    width = pixels.shape[1]
    columns = ((np.flatnonzero(valid) % width + .5) * (_WAVEFORM_WIDTH / width)).astype(int)
    cones = samples[:, :3] @ linear.linear_to_cones.T
    appearance = encode_cones(cones, constants=(tone.fl, tone.aw))
    chroma = np.hypot(appearance.q[..., 1], appearance.q[..., 2])
    magnitude = np.hypot(appearance.ja, np.sqrt(HK * chroma))
    before = magnitude / 100.
    # Tone's common appearance gain solves for this remapped magnitude.
    after = tone.remap(magnitude) / 100.
    before_visible = before <= PLOT_MAX
    after_visible = after <= PLOT_MAX
    histogram = np.histogram(after[after_visible], bins=_HISTOGRAM_BINS,
                             range=(0., PLOT_MAX), weights=weights[after_visible])[0]
    histogram = histogram.astype(np.float32)
    histogram.setflags(write=False)
    return ToneWaveforms(
        _waveform(before[before_visible], columns[before_visible], weights[before_visible]),
        _waveform(after[after_visible], columns[after_visible], weights[after_visible]),
        histogram,
    )
