"""Rec.709 Cb/Cr density analysis for the Linear Gizmo scope."""

import numpy as np

from .color_core import linear as color_linear


SIZE = 144
CHROMA_LIMIT = 0.65
_DISPLAY_GAIN = 65535.0
_Y = np.array((0.2126, 0.7152, 0.0722), dtype=np.float64)


def _linear_to_rec709(space):
    if space not in color_linear.SPACES:
        raise ValueError("Unsupported vectorscope working space: " + str(space))
    return (np.asarray(color_linear.xyz_to_rgb("Linear Rec.709"))
            @ np.asarray(color_linear.bradford(
                color_linear.SPACES[space][1],
                color_linear.SPACES["Linear Rec.709"][1],
            ))
            @ np.asarray(color_linear.rgb_to_xyz(space)))


def density(rgba, linear_matrix, space, *, size=SIZE):
    """Apply Linear correction and return an alpha-weighted Rec.709 Cb/Cr histogram."""
    rgba = np.asarray(rgba, dtype=np.float64)
    matrix = np.asarray(linear_matrix, dtype=np.float64)
    if rgba.ndim != 3 or rgba.shape[-1] != 4 or min(rgba.shape[:2]) < 1:
        raise ValueError("Vectorscope input must be a nonempty RGBA image")
    if matrix.shape != (3, 3) or not np.isfinite(matrix).all():
        raise ValueError("Vectorscope Linear matrix must be finite and 3 by 3")
    if type(size) is not int or size < 1:
        raise ValueError("Vectorscope size must be a positive integer")

    rgb = rgba[..., :3] @ matrix.T
    rgb = rgb @ _linear_to_rec709(space).T
    magnitude = np.abs(rgb)
    code = np.sign(rgb) * np.where(
        magnitude < 0.018,
        4.5 * magnitude,
        1.099 * np.power(magnitude, 0.45) - 0.099,
    )
    luma = code @ _Y
    cb = (code[..., 2] - luma) / 1.8556
    cr = (code[..., 0] - luma) / 1.5748
    alpha = rgba[..., 3]
    valid = (np.isfinite(cb) & np.isfinite(cr) & np.isfinite(alpha)
             & np.isfinite(rgb).all(axis=-1) & (alpha > 0.0))
    inside = (valid & (np.abs(cb) <= CHROMA_LIMIT)
              & (np.abs(cr) <= CHROMA_LIMIT))
    edges = np.linspace(-CHROMA_LIMIT, CHROMA_LIMIT, size + 1)
    histogram = np.histogram2d(
        cr[inside], cb[inside], bins=(edges, edges),
        weights=np.clip(alpha[inside], 0.0, 1.0),
    )[0]
    total = float(histogram.sum())
    if total > 0.0:
        normalized = histogram / total
        brightness = np.log1p(normalized * _DISPLAY_GAIN) / np.log1p(_DISPLAY_GAIN)
    else:
        brightness = np.zeros((size, size), dtype=np.float64)
    result = np.asarray(brightness, dtype=np.float32)
    result.setflags(write=False)
    return result


__all__ = ("CHROMA_LIMIT", "SIZE", "density")
