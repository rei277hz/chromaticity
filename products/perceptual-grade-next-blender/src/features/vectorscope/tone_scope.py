"""Output lightness histogram for the Tone Curve."""

import numpy as np

from ...color_core.modcam16 import HK, encode_cones
from ...kernel.prepare import nits_to_j, prepare_tone


_HISTOGRAM_BINS = 128


def peak_j(tone):
    """Return neutral J at the selected peak, in the tone curve's units."""
    return float(nits_to_j(tone.peak_nits, tone.reference_nits))


def analyze(rgba, linear, tone):
    """Bin alpha-weighted output J after applying Linear and Tone to the capture."""
    maximum = peak_j(tone)
    tone = prepare_tone(tone)
    pixels = np.asarray(rgba, dtype=np.float64)
    valid = np.isfinite(pixels).all(axis=-1) & (pixels[..., 3] > 0.)
    samples = pixels[valid]
    weights = np.minimum(samples[:, 3], 1.)
    cones = samples[:, :3] @ linear.linear_to_cones.T
    appearance = encode_cones(cones, constants=(tone.fl, tone.aw))
    chroma = np.hypot(appearance.q[..., 1], appearance.q[..., 2])
    chroma *= tone.chroma_gain(appearance.ja, chroma)
    magnitude = np.hypot(appearance.ja, np.sqrt(HK * chroma))
    after = tone.remap(magnitude) / 100.
    visible = after <= maximum
    histogram = np.histogram(after[visible], bins=_HISTOGRAM_BINS,
                             range=(0., maximum), weights=weights[visible])[0]
    histogram = histogram.astype(np.float32)
    histogram.setflags(write=False)
    return histogram
