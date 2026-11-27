"""Output lightness histogram for the Tone Curve."""

import numpy as np

from ...color_core.modcam16 import encode_cones, signed_hk
from ...kernel.prepare import nits_to_j, prepare_tone


_HISTOGRAM_BINS = 128


def peak_j(tone):
    """Return neutral J at the selected peak, in the tone curve's units."""
    return float(nits_to_j(tone.peak_nits, tone.reference_nits))


def analyze(rgba, linear, tone):
    """Bin alpha-weighted lightness after Linear and Stage 2."""
    maximum = peak_j(tone)
    tone = prepare_tone(tone)
    pixels = np.asarray(rgba, dtype=np.float64)
    valid = np.isfinite(pixels).all(axis=-1) & (pixels[..., 3] > 0.)
    samples = pixels[valid]
    weights = np.minimum(samples[:, 3], 1.)
    cones = samples[:, :3] @ linear.linear_to_cones.T
    appearance = encode_cones(cones, constants=(tone.fl, tone.aw))
    points = np.concatenate((appearance.ja[..., None], appearance.q[..., 1:]), axis=-1)
    output = tone.forward(points)
    chroma = np.hypot(output[..., 1], output[..., 2])
    after = signed_hk(output[..., 0], chroma) / 100.
    visible = after <= maximum
    histogram = np.histogram(after[visible], bins=_HISTOGRAM_BINS,
                             range=(0., maximum), weights=weights[visible])[0]
    histogram = histogram.astype(np.float32)
    histogram.setflags(write=False)
    return histogram
