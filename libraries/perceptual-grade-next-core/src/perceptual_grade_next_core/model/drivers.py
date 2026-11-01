"""Reference low/high and opponent driver construction."""

import numpy as np


CHROMA_CROSSOVER = 35.0 / 75.0


def drivers(q, ja):
    """Return ``(low, high, a, b)`` post-Tone drivers.

    Low/high membership crosses when chroma equals
    ``(35/75) * abs(J_A)``. Low and high share a chroma-visibility fade and
    vanish on the neutral axis. Inputs may be scalar triples or arrays ending
    in three coordinates; ``ja`` broadcasts over the leading dimensions.
    """
    q = np.asarray(q, dtype=np.float64)
    ja = np.asarray(ja, dtype=np.float64)
    if q.shape[-1:] != (3,) or not np.isfinite(q).all() or not np.isfinite(ja).all():
        raise ValueError("Drivers require finite appearance triples and J_A values")
    try:
        leading = np.broadcast_shapes(q.shape[:-1], ja.shape)
    except ValueError as exc:
        raise ValueError("J_A does not broadcast over appearance values") from exc
    q = np.broadcast_to(q, leading + (3,))
    ja = np.broadcast_to(ja, leading)
    chroma = np.hypot(q[..., 1], q[..., 2])
    radius = CHROMA_CROSSOVER * np.abs(ja)
    scale = np.maximum(chroma, radius)
    c = np.divide(chroma, scale, out=np.zeros_like(chroma), where=scale > 0)
    r = np.divide(radius, scale, out=np.zeros_like(radius), where=scale > 0)
    denominator = c * c + r * r
    visibility = np.square(chroma / np.hypot(chroma, 2.0))
    low = visibility * np.divide(r * r, denominator, out=np.zeros_like(r), where=denominator > 0)
    high = visibility * np.divide(c * c, denominator, out=np.zeros_like(c), where=denominator > 0)
    opponent = np.divide(q[..., 1:], np.hypot(chroma, 2.0)[..., None],
                         out=np.zeros(leading + (2,)), where=np.hypot(chroma, 2.0)[..., None] > 0)
    return np.concatenate((np.stack((low, high), axis=-1), opponent), axis=-1)
