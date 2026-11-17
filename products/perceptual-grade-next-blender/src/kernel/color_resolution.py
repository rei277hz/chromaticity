"""Resolve finite authored Color requests into the supported model domain.

Resolution changes immutable settings, never RNA, animation keys, or authoring
ownership. The same snapshot can therefore feed every native Grade consumer.
"""

from dataclasses import replace
from functools import lru_cache
import math

import numpy as np

from ..color_core.modcam16 import GAMMA, INVERSE, eccentricity
from .color_prepare import web_geometry
from .settings import LOW_Y, Settings


COLOR_RESOLUTION_SCHEMA = 1
HUE_MIN_GAP = 4.0
HUE_REPAIR_GAP = 4.0001
ADAPTANCE_MARGIN = 2. ** -16
_HUE_COUNT = 6
_FEASIBILITY_TOLERANCE = 1.e-9


def float32(value):
    """Return the exact finite value Blender's FloatProperty can store."""
    value = float(value)
    with np.errstate(over="ignore", invalid="ignore"):
        native = float(np.float32(value))
    if not math.isfinite(value) or not math.isfinite(native):
        raise ValueError("Color controls must be finite float32 values")
    return native


def _finite_tuple(values, length, description):
    values = tuple(float(value) for value in values)
    if len(values) != length or not all(math.isfinite(value) for value in values):
        raise ValueError(description + " must contain finite values")
    return values


@lru_cache(maxsize=32)
def _context(reference, peak):
    # Importing preparation helpers does not build Tone tables. Calibration
    # uses output anchors only; authored input anchors and Fit are irrelevant.
    from .prepare import _smooth_cap, _smooth_floor, nits_to_j, viewing

    if not math.isfinite(reference) or reference != 203. or not math.isfinite(peak):
        raise ValueError("Color resolution requires the supported viewing context")
    peak = _smooth_cap(_smooth_floor(peak, 2. * reference), 10000.)
    targets = nits_to_j((LOW_Y * reference, .18 * reference, reference, peak), reference)
    targets[2] = 1.
    anchors = tuple(float(value) for value in 100. * targets)
    _, aw = viewing(reference)
    geometry = web_geometry(anchors, reference)
    angles = tuple(tuple(float(value) for value in row)
                   for row in np.rad2deg(geometry.angles))
    return anchors, float(aw), angles


def adaptation_context(settings):
    """Return immutable neutral calibration anchors and white response."""
    anchors, aw, _ = _context(float(settings.tone.reference_nits),
                              float(settings.tone.peak_nits))
    return anchors, aw


def hue_source_angles(settings):
    """Return four rows of six unwrapped source angles, in degrees."""
    return _context(float(settings.tone.reference_nits),
                    float(settings.tone.peak_nits))[2]


def _hue_gaps(targets):
    return tuple(targets[index + 1] - targets[index] for index in range(5)) + (
        targets[0] + 360. - targets[5],)


def _index(index):
    if not isinstance(index, int) or not 0 <= index < _HUE_COUNT:
        raise ValueError("Hue handle index must be in [0, 5]")
    return index


def project_hue_offsets(source_angles, offsets, *, gap=HUE_MIN_GAP,
                        fixed=None, bounds=None):
    """Closest equal-weight cyclic targets with optional fixed/bounded offsets.

    ``fixed`` maps handle indices to offsets in degrees. ``bounds`` maps them
    to inclusive (lower, upper) offset pairs. Targets retain their unwrapped
    identities; the sixth edge crosses the 360-degree seam.

    There are only 63 feasible edge-active sets. Within each connected active
    component all differences are fixed, leaving one least-squares mean,
    clipped to the component's bounds. Enumerating these sets includes the
    convex problem's unique minimizer without an iterative optimizer.
    """
    source = _finite_tuple(source_angles, _HUE_COUNT, "Hue source angles")
    offsets = _finite_tuple(offsets, _HUE_COUNT, "Hue offsets")
    gap = float(gap)
    if not math.isfinite(gap) or not 0. < gap < 60.:
        raise ValueError("Cyclic hue gap must be positive and less than 60 degrees")
    lower, upper = [-math.inf] * _HUE_COUNT, [math.inf] * _HUE_COUNT
    for index, interval in (bounds or {}).items():
        index = _index(index)
        low, high = _finite_tuple(interval, 2, "Hue offset bounds")
        if low > high:
            raise ValueError("Hue offset bounds are reversed")
        lower[index], upper[index] = source[index] + low, source[index] + high
    for index, value in (fixed or {}).items():
        index = _index(index)
        value = float(value)
        if not math.isfinite(value):
            raise ValueError("Fixed hue offsets must be finite")
        target = source[index] + value
        if target < lower[index] or target > upper[index]:
            raise ValueError("Fixed hue offset exceeds its bounds")
        lower[index] = upper[index] = target
    targets = tuple(a + b for a, b in zip(source, offsets))
    if (all(value >= gap - _FEASIBILITY_TOLERANCE for value in _hue_gaps(targets))
            and all(low <= value <= high
                    for low, value, high in zip(lower, targets, upper))):
        return offsets
    best, best_cost = None, math.inf
    cost_scale = max(1., *(abs(value) for value in targets))
    # All six edges active would require 6 * gap == 360, excluded above.
    for mask in range((1 << _HUE_COUNT) - 1):
        adjacency = [[] for _ in range(_HUE_COUNT)]
        for index in range(_HUE_COUNT):
            if mask & (1 << index):
                following = (index + 1) % _HUE_COUNT
                difference = gap if index < 5 else gap - 360.
                adjacency[index].append((following, difference))
                adjacency[following].append((index, -difference))
        candidate, visited, feasible = [0.] * _HUE_COUNT, set(), True
        for first in range(_HUE_COUNT):
            if first in visited:
                continue
            relative, pending = {first: 0.}, [first]
            while pending:
                index = pending.pop()
                visited.add(index)
                for following, difference in adjacency[index]:
                    if following not in relative:
                        relative[following] = relative[index] + difference
                        pending.append(following)
            low = max(lower[index] - delta for index, delta in relative.items())
            high = min(upper[index] - delta for index, delta in relative.items())
            if low > high + _FEASIBILITY_TOLERANCE:
                feasible = False
                break
            mean = math.fsum((targets[index] - delta) / len(relative)
                             for index, delta in relative.items())
            center = min(high, max(low, mean))
            for index, delta in relative.items():
                candidate[index] = center + delta
        if not feasible:
            continue
        if any(value < gap - _FEASIBILITY_TOLERANCE for value in _hue_gaps(candidate)):
            continue
        cost = math.fsum(((value - target) / cost_scale) ** 2
                        for value, target in zip(candidate, targets))
        if cost < best_cost:
            best, best_cost = candidate, cost
    if best is None:
        raise ValueError("Hue targets cannot satisfy the fixed cyclic bounds")
    result = [value - origin for value, origin in zip(best, source)]
    # Preserve explicitly fixed authored values instead of subtracting two
    # rounded target angles to recover them.
    for index, value in (fixed or {}).items():
        result[index] = float(value)
    return tuple(result)


def _responses(pair, r0, aw):
    angle = math.atan2(pair[1], pair[0])
    factor = aw / (1204. * float(eccentricity(angle)))
    with np.errstate(over="ignore", invalid="ignore"):
        return r0 + (np.asarray(pair) * factor) @ INVERSE[:, 1:].T


def _valid_responses(responses):
    return bool(np.isfinite(responses).all()
                and np.all(responses > 0.) and np.all(responses < 400.))


def limit_adaptance_pair(pair, anchor, aw):
    """Limit an invalid neutral destination along its original tint ray.

    Valid requests, including valid legacy near-pole requests, stay exact.
    Only repaired pairs acquire an interior margin and float32 storage round.
    """
    pair = _finite_tuple(pair, 2, "Adaptance destination")
    anchor, aw = float(anchor), float(aw)
    if not all(math.isfinite(value) and value > 0. for value in (anchor, aw)):
        raise ValueError("Adaptance calibration must be finite and positive")
    r0 = aw / 3.05 * (anchor / 100.) ** (1. / GAMMA)
    if not 0. < r0 < 400.:
        raise ValueError("Adaptance calibration anchors exceed physical response range")
    if _valid_responses(_responses(pair, r0, aw)):
        return pair
    scale = max(map(abs, pair))
    unit = tuple(value / scale for value in pair)
    length = math.hypot(*unit)
    unit = tuple(value / length for value in unit)
    delta = _responses(unit, 0., aw)
    radius = min((-r0 / value if value < 0. else (400. - r0) / value)
                 for value in delta if value != 0.)
    radius *= 1. - ADAPTANCE_MARGIN
    for _ in range(8):
        result = tuple(float32(value * radius) for value in unit)
        if _valid_responses(_responses(result, r0, aw)):
            return result
        radius *= 1. - ADAPTANCE_MARGIN
    raise ValueError("Adaptance destination cannot retain a finite response margin")


def resolve_settings(settings):
    """Resolve a finite snapshot without mutating authored settings or keys."""
    if not isinstance(settings, Settings):
        raise TypeError("Color resolution requires Settings")
    anchors, aw = adaptation_context(settings)
    angles = hue_source_angles(settings)
    color = settings.color
    if len(color.adaptance) != 4 or len(color.web.hue_degrees) != 4:
        raise ValueError("Color resolution requires four tonal rows")
    adapted = tuple(limit_adaptance_pair(pair, anchor, aw)
                    for pair, anchor in zip(color.adaptance, anchors))
    hues = []
    bounds = {index: (-360., 360.) for index in range(_HUE_COUNT)}
    for source, offsets in zip(angles, color.web.hue_degrees):
        offsets = _finite_tuple(offsets, _HUE_COUNT, "Hue offsets")
        targets = tuple(a + b for a, b in zip(source, offsets))
        if all(value >= HUE_MIN_GAP for value in _hue_gaps(targets)):
            hues.append(offsets)
            continue
        projected = project_hue_offsets(source, offsets, gap=HUE_REPAIR_GAP, bounds=bounds)
        projected = tuple(float32(value) for value in projected)
        if min(_hue_gaps(tuple(a + b for a, b in zip(source, projected)))) < HUE_MIN_GAP:
            raise ValueError("Resolved hue gaps cannot survive float32 storage")
        hues.append(projected)
    hues = tuple(hues)
    if adapted == color.adaptance and hues == color.web.hue_degrees:
        return settings
    return replace(settings, color=replace(color, adaptance=adapted,
                   web=replace(color.web, hue_degrees=hues)))
