"""Source-white drag response for a frozen vectorscope sample cohort."""

from dataclasses import dataclass, replace

import numpy as np

from ...kernel.prepare import prepare_linear, project_source_white, project_source_white_component
from .analysis import CHROMA_LIMIT, SIZE, _project, linear_to_rec709


_DRAG_GRID = 16
_DRAG_LIMIT = _DRAG_GRID * _DRAG_GRID
_DRAG_GAIN = 0.25
_WHITE_DIFFERENCE = 1e-4
_MIN_RESPONSE = 1e-8


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
