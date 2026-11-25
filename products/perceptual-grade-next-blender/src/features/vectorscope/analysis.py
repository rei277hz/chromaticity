"""Rec.709 Cb/Cr density analysis for the Linear Gizmo scope."""

import numpy as np

from ...color_core import linear as color_linear


SIZE = 144
CHROMA_LIMIT = 0.65
_DISPLAY_GAIN = 65535.0
_Y = np.array((0.2126, 0.7152, 0.0722), dtype=np.float64)
_COLOR_BARS = (("R", (1, 0, 0)), ("Y", (1, 1, 0)), ("G", (0, 1, 0)),
               ("C", (0, 1, 1)), ("B", (0, 0, 1)), ("M", (1, 0, 1)))
_GAUSSIAN_SIGMA = 1.0
_GAUSSIAN_RADIUS = 3


def linear_to_rec709(space):
    if space not in color_linear.SPACES:
        raise ValueError("Unsupported vectorscope working space: " + str(space))
    return (np.asarray(color_linear.xyz_to_rgb("Linear Rec.709"))
            @ np.asarray(color_linear.bradford(
                color_linear.SPACES[space][1],
                color_linear.SPACES["Linear Rec.709"][1],
            ))
            @ np.asarray(color_linear.rgb_to_xyz(space)))


def chroma(code):
    """Return Cb and Cr from Rec.709 code RGB."""
    code = np.asarray(code, dtype=np.float64)
    luma = code @ _Y
    cb = (code[..., 2] - luma) / 1.8556
    cr = (code[..., 0] - luma) / 1.5748
    return cb, cr


def color_bar_targets():
    """Return labeled Cb/Cr positions of the 75% Rec.709 code-space bars."""
    labels, code = zip(*_COLOR_BARS)
    cb, cr = chroma(0.75 * np.asarray(code))
    return tuple(zip(labels, cb.tolist(), cr.tolist()))


def _project_rgb(rgb, matrix, to_rec709):
    with np.errstate(over="ignore", invalid="ignore"):
        rgb = (rgb @ matrix.T) @ to_rec709.T
        magnitude = np.abs(rgb)
        code = np.sign(rgb) * np.where(
            magnitude < 0.018,
            4.5 * magnitude,
            1.099 * np.power(magnitude, 0.45) - 0.099,
        )
        cb, cr = chroma(code)
        return code, cb, cr


def _project(rgb, matrix, to_rec709):
    _code, cb, cr = _project_rgb(rgb, matrix, to_rec709)
    return cb, cr


def _plot_samples(rgba, linear_matrix, space, size):
    rgba = np.asarray(rgba, dtype=np.float64)
    matrix = np.asarray(linear_matrix, dtype=np.float64)
    if rgba.ndim != 3 or rgba.shape[-1] != 4 or min(rgba.shape[:2]) < 1:
        raise ValueError("Vectorscope input must be a nonempty RGBA image")
    if matrix.shape != (3, 3) or not np.isfinite(matrix).all():
        raise ValueError("Vectorscope Linear matrix must be finite and 3 by 3")
    if type(size) is not int or size < 1:
        raise ValueError("Vectorscope size must be a positive integer")

    code, cb, cr = _project_rgb(rgba[..., :3], matrix, linear_to_rec709(space))
    alpha = rgba[..., 3]
    valid = (np.isfinite(cb) & np.isfinite(cr) & np.isfinite(alpha)
             & (alpha > 0.0))
    inside = (valid & (np.abs(cb) <= CHROMA_LIMIT)
              & (np.abs(cr) <= CHROMA_LIMIT))
    edges = np.linspace(-CHROMA_LIMIT, CHROMA_LIMIT, size + 1)
    return code, inside, cr[inside], cb[inside], np.clip(alpha[inside], 0.0, 1.0), edges


def chroma_samples(rgba, linear_matrix, space, *, size=SIZE):
    """Return the in-range chroma coordinates, weights, and histogram edges."""
    _code, _inside, cr, cb, weights, edges = _plot_samples(rgba, linear_matrix, space, size)
    return cr, cb, weights, edges


def accumulate(cr, cb, weights, edges):
    """Sum alpha weights into bins indexed by Cr, then Cb."""
    return np.histogram2d(cr, cb, bins=(edges, edges), weights=weights)[0]


def normalize_histogram(histogram):
    """Convert raw histogram weights to immutable display density."""
    total = float(histogram.sum())
    if total > 0.0:
        normalized = histogram / total
        log_density = np.log1p(_DISPLAY_GAIN * normalized) / np.log1p(_DISPLAY_GAIN)
        brightness = np.expm1(-log_density) / np.expm1(-1.0)
    else:
        brightness = np.zeros_like(histogram, dtype=np.float64)
    result = np.asarray(brightness, dtype=np.float32)
    result.setflags(write=False)
    return result


def density(rgba, linear_matrix, space, *, size=SIZE):
    """Apply Linear correction and plot alpha-weighted Rec.709 chroma."""
    return normalize_histogram(accumulate(*chroma_samples(rgba, linear_matrix, space, size=size)))


def color_histogram(rgba, linear_matrix, space, *, size=SIZE):
    """Sum sample alpha and alpha-weighted display RGB in matching bins."""
    code, inside, cr, cb, weights, edges = _plot_samples(rgba, linear_matrix, space, size)
    rows = np.minimum(np.searchsorted(edges, cr, side="right") - 1, size - 1)
    columns = np.minimum(np.searchsorted(edges, cb, side="right") - 1, size - 1)
    bins = rows * size + columns
    rgb_energy = weights[:, None] * np.clip(code[inside], 0.0, 1.0)
    mass = np.bincount(bins, weights=weights, minlength=size * size).reshape(size, size)
    energy = np.stack([
        np.bincount(bins, weights=channel, minlength=size * size).reshape(size, size)
        for channel in rgb_energy.T
    ], axis=-1)
    return mass, energy


def _splat_axis(grid, kernel, normalization):
    # Normalize each source bin by the part of its kernel inside the plot.
    size = grid.shape[0]
    radius = _GAUSSIAN_RADIUS
    grid = np.asarray(grid, dtype=np.float64)
    padded = np.pad(grid / normalization[:, None, None], ((radius, radius), (0, 0), (0, 0)))
    splatted = np.zeros_like(grid, dtype=np.float64)
    for index, weight in enumerate(kernel):
        splatted += weight * padded[index:index + size]
    return splatted


def splat_components(mass, energy):
    """Spread each bin's mass and associated components over a one-bin Gaussian."""
    height, width = mass.shape
    radius = _GAUSSIAN_RADIUS
    offsets = np.arange(-radius, radius + 1) / _GAUSSIAN_SIGMA
    kernel = np.exp(-0.5 * np.square(offsets))
    row_weights = np.convolve(np.ones(height), kernel, mode="full")[radius:radius + height]
    col_weights = np.convolve(np.ones(width), kernel, mode="full")[radius:radius + width]
    grid = np.concatenate((mass[..., None], energy), axis=-1)
    rows = _splat_axis(grid, kernel, row_weights)
    splatted = _splat_axis(rows.swapaxes(0, 1), kernel, col_weights).swapaxes(0, 1)
    return splatted[..., 0], splatted[..., 1:]


def trace_components(rgba, linear_matrix, space, *, size=SIZE):
    """Return Gaussian-splatted density mass and measured Rec.709 RGB energy."""
    return splat_components(*color_histogram(rgba, linear_matrix, space, size=size))


def trace_rgba(mass, energy):
    """Encode peak-normalized tint and display density as straight-alpha RGBA."""
    rgba = np.zeros((*mass.shape, 4), dtype=np.float32)
    color = rgba[..., :3]
    # The shared mass divisor cancels when normalizing the mean by its peak.
    bounded = np.clip(energy, 0.0, mass[..., None])
    peak = bounded.max(axis=-1)
    np.divide(bounded, peak[..., None], out=color, where=peak[..., None] > 0.0)
    color[(mass > 0.0) & (peak == 0.0)] = 1.0
    rgba[..., 3] = normalize_histogram(mass)
    rgba.setflags(write=False)
    return rgba


def analyze(rgba, linear_matrix, space, *, size=SIZE):
    """Produce the display trace from a captured Grade input."""
    return trace_rgba(*trace_components(rgba, linear_matrix, space, size=size))


__all__ = ("CHROMA_LIMIT", "SIZE", "accumulate", "analyze", "chroma", "chroma_samples",
           "color_bar_targets", "color_histogram", "density", "linear_to_rec709",
           "normalize_histogram", "splat_components", "trace_components", "trace_rgba")
