"""Atomic Color edits; numerical resolution and ownership remain host independent."""

# pg-book: technical-report/en#next-policy.color-authoring

from dataclasses import dataclass, replace
import math
from typing import Optional

from ..kernel.color_resolution import (
    HUE_MIN_GAP, HUE_REPAIR_GAP, adaptation_context, float32,
    hue_source_angles, limit_adaptance_pair, project_hue_offsets, resolve_settings,
)
from ..kernel.settings import Settings
from ..policy import color_authoring as ownership


@dataclass(frozen=True)
class Claim:
    origin_handle: int
    restore_offset: float

Claims = tuple[tuple[Optional[Claim], ...], ...]
EMPTY_CLAIMS: Claims = tuple((None,) * 6 for _ in range(4))


@dataclass(frozen=True)
class Effects:
    settings: Optional[Settings] = None
    claims: Optional[Claims] = None


def _claim_event(claims, row, handle, event, offset=None):
    claim = claims[row][handle]
    state = ownership.State(claim.origin_handle if claim is not None else None)
    _, effects = ownership.step(state, event)
    if effects.action == "clear":
        claims[row][handle] = None
    elif effects.action == "capture":
        claims[row][handle] = Claim(event.origin_handle, offset)


def _result(original, settings, before, claims):
    result = tuple(tuple(row) for row in claims)
    return Effects(settings if settings != original else None,
                   result if result != before else None)


def _with_hues(settings, rows):
    web = replace(settings.color.web, hue_degrees=tuple(tuple(row) for row in rows))
    return replace(settings, color=replace(settings.color, web=web))


def _valid(source, offsets):
    targets = [s + o for s, o in zip(source, offsets)]
    return (all(-360.0 <= value <= 360.0 for value in offsets)
            and all(targets[(i + 1) % 6] + (360.0 if i == 5 else 0.0)
                    - targets[i] >= HUE_MIN_GAP for i in range(6)))


def _stored_restoration(source, current, candidate):
    """Approach the projection while preserving stored cyclic separation."""
    def stored_at(fraction):
        return tuple(float32(a + fraction * (b - a))
                     for a, b in zip(current, candidate))

    stored = stored_at(1.0)
    if _valid(source, stored):
        return stored
    # The continuous segment is feasible, but FloatProperty rounding can put
    # its endpoint just across a four-degree face. First find a stored point
    # inside that face, then refine toward the rejected endpoint instead of
    # leaving the whole restoration at an arbitrary half-distance.
    invalid, valid, result = 1.0, 0.0, tuple(current)
    for _ in range(32):
        fraction = invalid * 0.5
        stored = stored_at(fraction)
        if _valid(source, stored):
            valid, result = fraction, stored
            break
        invalid = fraction
    for _ in range(32):
        fraction = (valid + invalid) * 0.5
        if fraction == valid or fraction == invalid:
            break
        stored = stored_at(fraction)
        if _valid(source, stored):
            valid, result = fraction, stored
        else:
            invalid = fraction
    return result


def edit_hue(settings: Settings, claims: Claims, row: int, handle: int,
             value: float) -> Effects:
    if not math.isfinite(value):
        raise ValueError("Hue must be finite")
    resolved = resolve_settings(settings)
    sources = hue_source_angles(resolved)[row]
    rows = [list(values) for values in resolved.color.web.hue_degrees]
    current = rows[row]
    metadata = [list(values) for values in claims]
    _claim_event(metadata, row, handle, ownership.Event("manual"))
    requested = float32(max(-360.0, min(360.0, value)))
    if requested == current[handle]:
        return _result(settings, resolved, claims, metadata)
    direction = 1 if requested > current[handle] else -1
    # Limit only at the existing RNA storage boundary. Circular separation can
    # otherwise push all five neighbors, including across Magenta/Red.
    root = sources[handle] + requested
    for distance in range(1, 6):
        raw_index = handle + direction * distance
        index = raw_index % 6
        revolution = raw_index // 6
        bound = sources[index] + revolution * 360.0 + direction * 360.0
        root = (min(root, bound - distance * HUE_REPAIR_GAP) if direction > 0
                else max(root, bound + distance * HUE_REPAIR_GAP))
    requested = float32(root - sources[handle])
    current[handle] = requested
    previous_target = sources[handle] + requested
    for distance in range(1, 6):
        raw_index = handle + direction * distance
        index = raw_index % 6
        revolution = raw_index // 6
        target = sources[index] + current[index] + revolution * 360.0
        boundary = previous_target + direction * HUE_REPAIR_GAP
        collision = ((target - previous_target) * direction < HUE_MIN_GAP)
        pushed = boundary if collision else target
        if pushed != target:
            baseline = current[index]
            stored = float32(pushed - sources[index] - revolution * 360.0)
            if stored != baseline:
                _claim_event(metadata, row, index,
                             ownership.Event("push", handle), baseline)
                current[index] = stored
        previous_target = sources[index] + current[index] + revolution * 360.0
    if not _valid(sources, current):
        raise ValueError("Hue edit cannot preserve cyclic separation in float storage")
    # Pin the new root first, then restore simultaneously. This avoids a
    # one-event retreat lag and never pushes unrelated or differently owned data.
    movable = {index: claim for index, claim in enumerate(metadata[row])
               if claim is not None and claim.origin_handle == handle}
    if movable:
        desired = tuple(movable[index].restore_offset if index in movable else offset
                        for index, offset in enumerate(current))
        fixed = {index: offset for index, offset in enumerate(current)
                 if index not in movable}
        bounds = {index: (min(current[index], claim.restore_offset),
                          max(current[index], claim.restore_offset))
                  for index, claim in movable.items()}
        candidate = project_hue_offsets(sources, desired, fixed=fixed, bounds=bounds)
        rows[row] = list(_stored_restoration(sources, current, candidate))
        for index in movable:
            _claim_event(metadata, row, index,
                         ownership.Event("restore", handle,
                                         rows[row][index] == movable[index].restore_offset))
    return _result(settings, _with_hues(resolved, rows), claims, metadata)


def edit_adaptance(settings: Settings, claims: Claims, row: int, axis: int,
                   value: float) -> Effects:
    if not math.isfinite(value):
        raise ValueError("Adaptance must be finite")
    resolved = resolve_settings(settings)
    rows = [list(pair) for pair in resolved.color.adaptance]
    rows[row][axis] = float32(value)
    anchors, aw = adaptation_context(resolved)
    rows[row] = limit_adaptance_pair(rows[row], anchors[row], aw)
    adaptance = tuple(tuple(pair) for pair in rows)
    result = replace(resolved, color=replace(resolved.color, adaptance=adaptance))
    return Effects(settings=result if result != settings else None)


def clear_claims(claims: Claims, rows: Optional[tuple[int, ...]] = None) -> Effects:
    metadata = [list(values) for values in claims]
    for row in range(4) if rows is None else rows:
        for handle in range(6):
            _claim_event(metadata, row, handle, ownership.Event("clear"))
    result = tuple(tuple(values) for values in metadata)
    return Effects(claims=result if result != claims else None)


def rebase(settings: Settings, claims: Claims) -> Effects:
    resolved = resolve_settings(settings)
    return Effects(resolved if resolved != settings else None,
                   clear_claims(claims).claims)
