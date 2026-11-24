"""Rec.709 Cb/Cr density analysis for the Linear Gizmo scope."""

from dataclasses import dataclass, replace

import numpy as np

from .color_core import linear as color_linear
from .kernel.prepare import prepare_linear, project_source_white, project_source_white_component


SIZE = 144
CHROMA_LIMIT = 0.65
_DISPLAY_GAIN = 65535.0
_Y = np.array((0.2126, 0.7152, 0.0722), dtype=np.float64)
_COLOR_BARS = (("R", (1, 0, 0)), ("Y", (1, 1, 0)), ("G", (0, 1, 0)),
               ("C", (0, 1, 1)), ("B", (0, 0, 1)), ("M", (1, 0, 1)))
_DRAG_GRID = 16
_DRAG_LIMIT = _DRAG_GRID * _DRAG_GRID
_DRAG_GAIN = 0.25
_WHITE_DIFFERENCE = 1e-4
_MIN_RESPONSE = 1e-8
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
    """Encode measured RGB and display density as straight-alpha RGBA."""
    rgba = np.zeros((*mass.shape, 4), dtype=np.float32)
    color = rgba[..., :3]
    np.divide(energy, mass[..., None], out=color, where=mass[..., None] > 0)
    np.clip(color, 0.0, 1.0, out=color)
    rgba[..., 3] = normalize_histogram(mass)
    rgba.setflags(write=False)
    return rgba


def analyze(rgba, linear_matrix, space, *, size=SIZE):
    """Produce the display trace from a captured Grade input."""
    return trace_rgba(*trace_components(rgba, linear_matrix, space, size=size))


def _weighted_median(values, weights):
    order = np.argsort(values, kind="stable")
    cumulative = np.cumsum(weights[order])
    midpoint = cumulative[-1] * 0.5
    index = np.searchsorted(cumulative, midpoint)
    if cumulative[index] == midpoint and index + 1 < len(order):
        return (values[order[index]] + values[order[index + 1]]) * 0.5
    return values[order[index]]


def _robust_squared_distances(positions, weights):
    """Measure chroma distance from the alpha-weighted coordinate medians."""
    center = np.array([_weighted_median(axis, weights) for axis in positions.T])
    residual = np.abs(positions - center)
    deviation = np.array([_weighted_median(axis, weights) for axis in residual.T])
    # Use one bin as the minimum spread for identical or quantized samples.
    scale = np.maximum(1.4826 * deviation, 2.0 * CHROMA_LIMIT / SIZE)
    return np.sum(np.square(residual / scale), axis=1)


def _visible_chroma(pixels, matrix, to_rec709):
    valid = np.isfinite(pixels).all(axis=1) & (pixels[:, 3] > 0.0)
    rgb = pixels[valid, :3]
    weights = np.minimum(pixels[valid, 3], 1.0)
    positions = np.column_stack(_project(rgb, matrix, to_rec709))
    visible = (np.isfinite(positions).all(axis=1)
               & (np.abs(positions) <= CHROMA_LIMIT).all(axis=1))
    return rgb[visible], weights[visible], positions[visible]


@dataclass(frozen=True, eq=False)
class WhiteDrag:
    """Steer the same alpha-weighted input cohort for the entire gesture."""

    _rgb: np.ndarray
    _weights: np.ndarray
    _space: str
    _to_rec709: np.ndarray

    @classmethod
    def from_capture(cls, rgba, linear_settings, space):
        """Freeze visible samples when source white can move their scope centroid."""
        rgba = np.asarray(rgba)
        if (linear_settings.matrix is not None or rgba.ndim != 3 or rgba.shape[-1] != 4
                or min(rgba.shape[:2]) < 1):
            return None

        to_rec709 = linear_to_rec709(space)
        try:
            matrix = prepare_linear(linear_settings, space).rgb_matrix
            height, width = rgba.shape[:2]
            nx, ny = min(width, _DRAG_GRID), min(height, _DRAG_GRID)
            xs = ((np.arange(nx) + 0.5) * width / nx).astype(int)
            ys = ((np.arange(ny) + 0.5) * height / ny).astype(int)
            grid = rgba[ys[:, None], xs].reshape(-1, 4)
            rgb, weights, positions = _visible_chroma(grid, matrix, to_rec709)
            if not weights.size:
                rgb, weights, positions = _visible_chroma(rgba.reshape(-1, 4), matrix, to_rec709)
                if weights.size > _DRAG_LIMIT:
                    indices = ((np.arange(_DRAG_LIMIT) + 0.5) * weights.size / _DRAG_LIMIT).astype(int)
                    rgb, weights, positions = rgb[indices], weights[indices], positions[indices]
            if not weights.size:
                return None

            weights = weights.astype(np.float64) / weights.max()
            distances = _robust_squared_distances(positions, weights)
            keep = distances <= 5.991464547107979
            if not np.any(keep):
                keep[np.argmin(distances)] = True

            rgb, weights = rgb[keep], weights[keep]
            weights = weights / weights.max()
            weights = weights / weights.sum()
            for array in (rgb, weights, to_rec709):
                array.setflags(write=False)
            drag = cls(rgb, weights, space, to_rec709)
            xy = np.asarray(project_source_white(linear_settings.source_xy))
            return drag if drag._inverse_response(linear_settings, xy) is not None else None
        except (ValueError, np.linalg.LinAlgError):
            return None

    def _position(self, settings, xy):
        matrix = prepare_linear(replace(settings, source_xy=xy), self._space).rgb_matrix
        return self._weights @ np.column_stack(_project(self._rgb, matrix, self._to_rec709))

    def _inverse_response(self, settings, xy):
        jacobian = np.zeros((2, 2))
        for axis in range(2):
            low, high = xy.copy(), xy.copy()
            low[axis] -= _WHITE_DIFFERENCE
            high[axis] += _WHITE_DIFFERENCE
            low[axis] = project_source_white_component(low, axis)
            high[axis] = project_source_white_component(high, axis)
            span = high[axis] - low[axis]
            if span > 1e-12:
                jacobian[:, axis] = (self._position(settings, high) - self._position(settings, low)) / span
        if not np.isfinite(jacobian).all():
            return None
        left, singular, right = np.linalg.svd(jacobian)
        if singular[0] < _MIN_RESPONSE:
            return None
        damping = 0.04 * singular[0]
        return right.T @ np.diag(singular / (np.square(singular) + damping * damping)) @ left.T

    def move(self, linear_settings, dx, dy, side):
        """Return source xy for a pointer delta with positive y pointing up."""
        original = linear_settings.source_xy
        pointer = np.asarray((dx, dy), dtype=np.float64)
        distance = np.linalg.norm(pointer)
        if (linear_settings.matrix is not None or not np.isfinite(side) or side <= 0
                or not np.isfinite(distance) or distance == 0):
            return original
        pointer /= distance
        travel = distance / side * _DRAG_GAIN
        try:
            xy = np.asarray(project_source_white(original))
            inverse = self._inverse_response(linear_settings, xy)
            if inverse is None:
                return original
            step = inverse @ pointer
            length = np.linalg.norm(step)
            if length < 1e-15:
                return original
            step *= travel / length
            before = self._position(linear_settings, xy)
            for _ in range(8):
                trial = project_source_white(xy + step)
                if np.linalg.norm(trial - xy) < 1e-12:
                    break
                progress = (self._position(linear_settings, trial) - before) @ pointer
                if progress > 1e-12:
                    return trial
                step *= 0.5
        except (ValueError, np.linalg.LinAlgError):
            return original
        return original


__all__ = ("CHROMA_LIMIT", "SIZE", "accumulate", "analyze", "chroma", "chroma_samples",
           "color_bar_targets", "color_histogram", "density", "linear_to_rec709",
           "normalize_histogram", "splat_components", "trace_components", "trace_rgba",
           "WhiteDrag")
