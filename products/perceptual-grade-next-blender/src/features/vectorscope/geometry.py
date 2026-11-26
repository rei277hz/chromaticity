"""Pure layout and vectorscope handle geometry for the Next Grade Gizmo.

Drawing and pointer handling consume these values so the visual and input
domains cannot drift apart when the editor is resized or scaled.
"""

from functools import lru_cache
import math

from ...kernel.prepare import prepare_tone
from ...kernel.settings import TONE_CHROMA_LIMITS
from . import appearance_scope
from .analysis import CHROMA_LIMIT, color_bar_targets
from .tone_scope import peak_j as tone_peak_j


_TARGETS = {label: (cb, cr) for label, cb, cr in color_bar_targets()}
AXIS_LABELS = {"cr": "R", "yb": "B"}
SLIDER_RANGES = {"exposure": (-6., 6.), "cr_balance": (-2., 2.),
                 "yb_balance": (-2., 2.), "fit": (-2., 2.)}
DEFAULT_LINEAR_SIZE = 300.
DEFAULT_TONE_SIZE = (500., 340.)
MIN_LINEAR_SIZE = 160.
MAX_LINEAR_SIZE = 900.
MIN_TONE_SIZE = (280., 232.)
MAX_TONE_SIZE = (1200., 900.)
_RESIZE_GRIP = 8.
CROSSOVER_HANDLE_RADIUS = 4.
_CROSSOVER_HIT_RADIUS = CROSSOVER_HANDLE_RADIUS + 1.
_CROSSOVER_MIN, _CROSSOVER_MAX = TONE_CHROMA_LIMITS["saturation_crossover"]
_TONE_CROSSOVER_MIN, _TONE_CROSSOVER_MAX = TONE_CHROMA_LIMITS["tone_crossover"]
APPEARANCE_GAIN_FIELDS = frozenset((
    "muted_gain", "vivid_gain", "shadow_chroma", "highlight_chroma",
))
_APPEARANCE_EDGE_STRIP = 5.


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


@lru_cache(maxsize=4)
def tone_model(tone):
    return prepare_tone(tone)


def curve_point(rect, source, target, peak_j):
    x, y, width, height = rect
    return (x + min(1., max(0., source / peak_j)) * width,
            y + min(1., max(0., target / peak_j)) * height)


def saturation_crossover_point(rect, value):
    """Return the guide position for the compressed saturation crossover."""
    x, y, width, _height = rect
    return (x + value * width, y)


def saturation_crossover_hit(rect, value, point, scale):
    """Return whether a pointer is close enough to the crossover guide."""
    marker = saturation_crossover_point(rect, value)
    band = _CROSSOVER_HIT_RADIUS * scale
    return (math.dist(point, marker) <= band
            or contains(rect, point) and abs(point[0] - marker[0]) <= band)


def drag_saturation_crossover(rect, value, dx):
    """Move the marker in plot space and return its compressed coordinate."""
    position = value + dx / rect[2]
    return min(_CROSSOVER_MAX, max(_CROSSOVER_MIN, position))


def tone_crossover_point(rect, peak_j, value):
    """Return the marker for a normalized output-neutral J crossover."""
    x, y, _width, height = rect
    output = appearance_scope.LIGHTNESS_KNEE * value
    position = 1. if value >= peak_j else appearance_scope.lightness_position(output, peak_j)
    return (x, y + float(position) * height), value > peak_j


def appearance_crossover_at(rect, tone, point, scale):
    """Resolve the existing Tone and Saturation guide hit zones."""
    x, y, width, height = rect
    band = _CROSSOVER_HIT_RADIUS * scale
    if not contains((x - band, y - band, width + 2 * band, height + 2 * band), point):
        return None
    marker, _pinned = tone_crossover_point(
        rect, tone_peak_j(tone), tone.tone_crossover,
    )
    if math.dist(point, marker) <= band:
        return "tone_crossover"
    if saturation_crossover_hit(rect, tone.saturation_crossover, point, scale):
        return "saturation_crossover"
    if not contains(rect, point):
        return None
    if abs(point[1] - marker[1]) <= band:
        return "tone_crossover"


def appearance_control_at(rect, tone, point, scale):
    """Resolve crossover guides before the tonal strips and saturation halves."""
    crossover = appearance_crossover_at(rect, tone, point, scale)
    if crossover is not None:
        return crossover
    x, y, width, _height = rect
    if not contains(rect, point):
        return None
    tone_y = tone_crossover_point(
        rect, tone_peak_j(tone), tone.tone_crossover,
    )[0][1]
    for field, strip in appearance_gain_strips(rect, tone_y, scale).items():
        if contains(strip, point):
            return field
    saturation_x, _ = saturation_crossover_point(rect, tone.saturation_crossover)
    return "muted_gain" if point[0] < saturation_x else "vivid_gain"


def appearance_gain_regions(rect, saturation_x, tone_y):
    """Return the four highlight rectangles bounded by the visible guides."""
    x, y, width, height = rect
    return {
        "muted_gain": (x, y, saturation_x - x, height),
        "vivid_gain": (saturation_x, y, x + width - saturation_x, height),
        "shadow_chroma": (x, y, width, tone_y - y),
        "highlight_chroma": (x, tone_y, width, y + height - tone_y),
    }


def appearance_gain_strips(rect, tone_y, scale):
    """Return edge strips that have room outside the Tone crossover hit band."""
    x, y, width, height = rect
    top = y + height
    band = _CROSSOVER_HIT_RADIUS * scale
    strip = _APPEARANCE_EDGE_STRIP * scale
    strips = {}
    if tone_y - y > band:
        strips["shadow_chroma"] = (x, y, width, min(strip, tone_y - y - band))
    if top - tone_y > band:
        thickness = min(strip, top - tone_y - band)
        strips["highlight_chroma"] = (x, top - thickness, width, thickness)
    return strips


def drag_appearance_gain(rect, field, value, dx):
    """Map a full-plot horizontal drag to the gain's full stop range."""
    low, high = TONE_CHROMA_LIMITS[field]
    return min(high, max(low, value + dx / rect[2] * (high - low)))


def drag_tone_crossover(rect, peak_j, value, dy):
    """Map vertical plot motion directly to normalized output-neutral J."""
    if dy == 0.:
        return value
    if value >= peak_j and dy > 0.:
        return value
    (_marker_x, marker_y), _pinned = tone_crossover_point(rect, peak_j, value)
    target = (marker_y - rect[1] + dy) / rect[3]
    output_j = (appearance_scope.lightness_at_position(target, peak_j)
                / appearance_scope.LIGHTNESS_KNEE)
    return min(_TONE_CROSSOVER_MAX, max(_TONE_CROSSOVER_MIN, output_j))


def tone_anchor_levels(model):
    # The first knot is the origin. The four following knots are editable.
    return model.source[1:], model.target[1:]


def layout(stage, width, height, scale=1.0, position=(24.0, 24.0), size=None):
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
        requested_side = DEFAULT_LINEAR_SIZE if size is None else float(size)
        max_side = min(MAX_LINEAR_SIZE * scale, available_width - 168 * scale,
                       available_height - 120 * scale)
        side = min(max_side, max(MIN_LINEAR_SIZE * scale, requested_side * scale))
        panel_width = side + 168 * scale
        panel_height = side + 120 * scale
    else:
        requested_size = DEFAULT_TONE_SIZE if size is None else tuple(map(float, size))
        panel_width = min(max(MIN_TONE_SIZE[0], requested_size[0]) * scale,
                          MAX_TONE_SIZE[0] * scale, available_width)
        panel_height = min(max(MIN_TONE_SIZE[1], requested_size[1]) * scale,
                           MAX_TONE_SIZE[1] * scale, available_height)
    px, py = (float(value) * scale for value in position)
    px = max(12.0 * scale, min(px, width - panel_width - 12.0 * scale))
    py = max(12.0 * scale, min(py, height - panel_height - 12.0 * scale))
    header_height = 32.0 * scale
    inner_x = px + 12 * scale
    inner_width = panel_width - 24 * scale
    result = {
        "rect": _rect(px, py, panel_width, panel_height),
        "bounds": _rect(12 * scale, 12 * scale, available_width, available_height),
        "size": (side / scale if stage == "LINEAR"
                 else (panel_width / scale, panel_height / scale)),
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
    grip = _RESIZE_GRIP * scale
    x, y, panel_width, panel_height = result["rect"]
    result["resize_grips"] = {
        "w": _rect(x, y + grip, grip, panel_height - 2 * grip),
        "e": _rect(x + panel_width - grip, y + grip, grip, panel_height - 2 * grip),
        "s": _rect(x + grip, y, panel_width - 2 * grip, grip),
        "n": _rect(x + grip, y + panel_height - grip, panel_width - 2 * grip, grip),
        "sw": _rect(x, y, grip, grip),
        "se": _rect(x + panel_width - grip, y, grip, grip),
        "nw": _rect(x, y + panel_height - grip, grip, grip),
        "ne": _rect(x + panel_width - grip, y + panel_height - grip, grip, grip),
    }
    return result


def _resize_axis(origin, extent, limit, delta, low, high):
    lo, hi = limit
    before, after = max(0., origin - lo), max(0., hi - origin - extent)
    if low:
        return -delta, before, 1.
    if high:
        return delta, after, 0.
    return None, before + after, .5


def resize(stage, rect, bounds, handle, dx, dy, scale):
    """Keep the opposite edge fixed and stay inside the editor region."""
    x, y, width, height = (value / scale for value in rect)
    bx, by, bw, bh = (value / scale for value in bounds)
    horizontal, room_x, anchor_x = _resize_axis(
        x, width, (bx, bx + bw), dx / scale, "w" in handle, "e" in handle)
    vertical, room_y, anchor_y = _resize_axis(
        y, height, (by, by + bh), dy / scale, "s" in handle, "n" in handle)
    if stage == "LINEAR":
        side = width - 168
        changes = [value for value in (horizontal, vertical) if value is not None]
        delta = min(sum(changes) / len(changes), room_x, room_y)
        size = min(MAX_LINEAR_SIZE, max(min(MIN_LINEAR_SIZE, side), side + delta))
        dw = dh = size - side
    elif stage == "TONE":
        size = tuple(min(hi, max(lo, extent + min(delta or 0., room)))
                     for lo, hi, extent, delta, room in zip(
                         MIN_TONE_SIZE, MAX_TONE_SIZE, (width, height),
                         (horizontal, vertical), (room_x, room_y)))
        dw, dh = size[0] - width, size[1] - height
    else:
        raise ValueError("Gizmo stage must be LINEAR or TONE")
    x = max(bx, min(x - dw * anchor_x, bx + bw - width - dw))
    y = max(by, min(y - dh * anchor_y, by + bh - height - dh))
    return (x, y), size


def _handle_polar(rect, axis, spread, heading):
    cb, cr = _TARGETS[AXIS_LABELS[axis]]
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
    for axis, spread, heading in zip(AXIS_LABELS, linear.spread, linear.heading):
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
