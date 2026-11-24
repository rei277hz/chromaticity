"""Pure layout and vectorscope handle geometry for the Next Grade Gizmo.

Drawing and pointer handling consume these values so the visual and input
domains cannot drift apart when the editor is resized or scaled.
"""

import math

from .vectorscope import CHROMA_LIMIT, color_bar_targets


_TARGETS = {label: (cb, cr) for label, cb, cr in color_bar_targets()}
_HANDLE_TARGETS = {"cr": "R", "yb": "B"}


def _rect(x, y, width, height):
    return (float(x), float(y), float(width), float(height))


def contains(rect, point):
    """Return whether a point is inside an inclusive rectangle."""
    x, y, width, height = rect
    return x <= point[0] <= x + width and y <= point[1] <= y + height


def _scope_point(rect, cb, cr):
    x, y, side, _ = rect
    radius = side * 0.5
    return (x + radius + cb / CHROMA_LIMIT * radius,
            y + radius + cr / CHROMA_LIMIT * radius)


def scope_targets(rect):
    """Return the six fixed 75% Rec.709 target positions in screen pixels."""
    return {label: _scope_point(rect, cb, cr)
            for label, (cb, cr) in _TARGETS.items()}


def layout(stage, width, height, scale=1.0, position=(24.0, 24.0)):
    """Build the DPI-scaled Gizmo geometry for a Node Editor region.

    ``position`` is the lower-left logical panel position. The panel is
    clamped to the available region while keeping the caller's requested
    bottom-left origin whenever there is enough space.
    """
    if stage not in ("LINEAR", "TONE"):
        raise ValueError("Gizmo stage must be LINEAR or TONE")
    width, height, scale = float(width), float(height), float(scale)
    if width <= 0 or height <= 0 or scale <= 0:
        return None
    available_width = width - 24 * scale
    available_height = height - 24 * scale
    # Both tabs must fit before either can offer the stage switch.
    if available_width < 280 * scale or available_height < 232 * scale:
        return None
    if stage == "LINEAR":
        side = min(420 * scale, available_width - 168 * scale,
                   available_height - 120 * scale)
        panel_width = side + 168 * scale
        panel_height = side + 120 * scale
    else:
        panel_width = min(640 * scale, available_width)
        panel_height = min(420 * scale, available_height)
    px, py = (float(value) * scale for value in position)
    px = max(12.0 * scale, min(px, width - panel_width - 12.0 * scale))
    py = max(12.0 * scale, min(py, height - panel_height - 12.0 * scale))
    header_height = 32.0 * scale
    inner_x = px + 12 * scale
    inner_width = panel_width - 24 * scale
    result = {
        "rect": _rect(px, py, panel_width, panel_height),
        "header": _rect(px, py + panel_height - header_height,
                         panel_width, header_height),
        "close": _rect(px + panel_width - 28.0 * scale,
                        py + panel_height - 27.0 * scale,
                        22.0 * scale, 22.0 * scale),
        "linear_tab": _rect(px + 135.0 * scale,
                             py + panel_height - 27.0 * scale,
                             54.0 * scale, 22.0 * scale),
        "tone_tab": _rect(px + 192.0 * scale,
                           py + panel_height - 27.0 * scale,
                           54.0 * scale, 22.0 * scale),
        "scale": scale,
        "status": _rect(inner_x, py + 5 * scale, inner_width, 20 * scale),
    }
    if stage == "LINEAR":
        scope_x = px + 84 * scale
        scope_y = py + 72 * scale
        result.update({
            "scope": _rect(scope_x, scope_y, side, side),
            "exposure": _rect(inner_x, scope_y, 62 * scale, side),
            "cr_balance": _rect(scope_x + side + 10 * scale,
                                scope_y, 62 * scale, side),
            "yb_balance": _rect(scope_x, py + 32 * scale, side, 32 * scale),
        })
    else:
        # Both plots reserve a left gutter for their vertical tick labels.
        appearance_column = 104 * scale + .45 * (inner_width - 256 * scale)
        tone_x = inner_x + appearance_column + 14 * scale
        inner_right = inner_x + inner_width
        curve_x = tone_x + 20 * scale
        curve_y = py + 72 * scale
        curve_right = inner_right - 34 * scale
        curve_top = py + panel_height - 86 * scale
        curve_width = curve_right - curve_x
        curve_height = curve_top - curve_y
        appearance_width = min(appearance_column - 26 * scale, 2 * curve_height)
        appearance_height = appearance_width / 2
        title_y = py + panel_height - 58 * scale
        peak_width = min(116 * scale, inner_right - tone_x - 66 * scale)
        peak_x = inner_right - peak_width
        result.update({
            "appearance": _rect(inner_x + 26 * scale, curve_top - appearance_height,
                                appearance_width, appearance_height),
            "curve": _rect(curve_x, curve_y, curve_width, curve_height),
            "curve_title": _rect(tone_x, title_y, peak_x - tone_x - 6 * scale, 24 * scale),
            "peak": _rect(peak_x, title_y, peak_width, 24 * scale),
            "exposure": _rect(curve_x, curve_y - 16 * scale, curve_width, 16 * scale),
            "exposure_track": ((curve_x, curve_y), (curve_right, curve_y)),
            "fit": _rect(curve_right, curve_y, 34 * scale, curve_height),
            "fit_track": ((curve_right, curve_y), (curve_right, curve_top)),
        })
    return result


def _handle_polar(rect, axis, spread, heading):
    cb, cr = _TARGETS[_HANDLE_TARGETS[axis]]
    base_radius = math.hypot(cb, cr) / CHROMA_LIMIT * rect[2] * .5
    radius = base_radius * (1 + spread / 100)
    angle = math.atan2(cr, cb) + math.radians(heading)
    return base_radius, radius, angle


def _clip_to_circle(center, point, radius):
    dx, dy = point[0] - center[0], point[1] - center[1]
    distance = math.hypot(dx, dy)
    if distance <= radius or distance == 0:
        return point
    factor = radius / distance
    return center[0] + dx * factor, center[1] + dy * factor


def handle_positions(rect, linear, scale=1.0):
    """Return clipped CR/YB handle positions for a Linear settings object."""
    radius = rect[2] * .5
    center = (rect[0] + radius, rect[1] + radius)
    positions = {}
    for axis, spread, heading in zip(_HANDLE_TARGETS, linear.spread, linear.heading):
        _, distance, angle = _handle_polar(rect, axis, spread, heading)
        distance = min(distance, radius)
        positions[axis] = (center[0] + distance * math.cos(angle),
                           center[1] + distance * math.sin(angle))

    cr, yb = positions["cr"], positions["yb"]
    separation = 13 * scale
    if math.dist(cr, yb) < separation:
        # Separate coincident handles tangentially so both stay accessible at
        # the circle edge and neither changes the underlying drag baseline.
        midpoint = ((cr[0] + yb[0]) / 2, (cr[1] + yb[1]) / 2)
        angle = math.atan2(midpoint[1] - center[1], midpoint[0] - center[0])
        tangent = (-math.sin(angle), math.cos(angle))
        direction = (cr[0] - yb[0]) * tangent[0] + (cr[1] - yb[1]) * tangent[1]
        offset = math.copysign(separation / 2, direction)
        for axis, sign in (("cr", 1), ("yb", -1)):
            point = (midpoint[0] + sign * offset * tangent[0],
                     midpoint[1] + sign * offset * tangent[1])
            positions[axis] = _clip_to_circle(center, point, radius)
    return positions


def drag_handle(rect, axis, spread, heading, dx, dy):
    """Apply a relative drag and return unclipped Spread/Heading values."""
    base_radius, radius, angle = _handle_polar(rect, axis, spread, heading)
    cosine, sine = math.cos(angle), math.sin(angle)
    radial = dx * cosine + dy * sine
    tangential = -dx * sine + dy * cosine
    if abs(radial) > 1e-9:
        spread = max(-100.0, min(150.0, spread + 100 * radial / base_radius))
    if abs(tangential) > 1e-9:
        turn_radius = max(radius, base_radius / 4)
        heading += math.degrees(tangential / turn_radius)
        heading = (heading + 180) % 360 - 180
    return spread, heading


__all__ = ["contains", "drag_handle", "handle_positions", "layout", "scope_targets"]
