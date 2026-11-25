"""Output lightness histogram for the Tone Curve."""

import numpy as np

from ...color_core.modcam16 import HK, encode_cones
from ...kernel.prepare import nits_to_j, prepare_tone


PLOT_MAX = float(nits_to_j(4000.0))
_HISTOGRAM_BINS = 128


def analyze(rgba, linear, tone):
    """Bin alpha-weighted output J after applying Linear and Tone to the capture."""
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
    visible = after <= PLOT_MAX
    histogram = np.histogram(after[visible], bins=_HISTOGRAM_BINS,
                             range=(0., PLOT_MAX), weights=weights[visible])[0]
    histogram = histogram.astype(np.float32)
    histogram.setflags(write=False)
    return histogram
