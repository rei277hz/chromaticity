"""GPU renderer for the Linear and Tone Gizmo tabs."""

import math

import numpy as np

from ... import localization
from . import appearance_scope, geometry
from .geometry import AXIS_LABELS as _AXIS_LABELS
from .geometry import SLIDER_RANGES as _SLIDER_RANGES
from .geometry import curve_point as _curve_point
from .geometry import tone_anchor_levels as _tone_anchor_levels
from .geometry import tone_model as _tone_model
from .tone_scope import PLOT_MAX


_TEXTURES = {}
_SHADERS = {}
_BATCHES = {}
_PALETTE = {
    name: tuple(int(rgb[index:index + 2], 16) / 255 for index in (0, 2, 4)) + (1.,)
    for name, rgb in {
        "panel": "3d3d3d", "header": "303030", "plot": "282828",
        "outline": "575757", "grid": "404040", "text": "e6e6e6",
        "muted": "aaaaaa", "blue": "265787", "orange": "e87d0d",
        "reference": "9b9b9b", "hdr": "87a3bd",
        "R": "ff3352", "C": "4bc9cc", "B": "2890ff", "Y": "f0cf5a",
    }.items()
}

_J_TICKS = tuple(range(math.floor(PLOT_MAX) + 1))


def _shader(name):
    import gpu
    if name not in _SHADERS:
        _SHADERS[name] = gpu.shader.from_builtin(name)
    return _SHADERS[name]


def _quad(x, y, width, height):
    return (x, y), (x + width, y), (x + width, y + height), (x, y + height)


def _fill(rect, color):
    from gpu_extras.batch import batch_for_shader
    shader = _shader("UNIFORM_COLOR")
    shader.bind()
    shader.uniform_float("color", color)
    key = ("fill", tuple(rect))
    batch = _BATCHES.get(key)
    if batch is None:
        batch = batch_for_shader(shader, "TRI_FAN", {"pos": _quad(*rect)})
        _remember_batch(key, batch)
    batch.draw(shader)


def _remember_batch(key, batch):
    _BATCHES[key] = batch
    while len(_BATCHES) > 32:
        _BATCHES.pop(next(iter(_BATCHES)))


def _draw_trace(rect, data, key, *, color=None, additive=True):
    import gpu
    from gpu_extras.batch import batch_for_shader
    cached = _TEXTURES.get(key)
    if cached is None or cached[0] is not data:
        if color is None:
            rgba = data
        else:
            rgba = np.empty((*data.shape, 4), dtype=np.float32)
            rgba[..., :3] = color[:3]
            rgba[..., 3] = data
        height, width, _ = rgba.shape
        texture = gpu.types.GPUTexture(
            (width, height), format="RGBA16F",
            data=gpu.types.Buffer("FLOAT", rgba.shape, rgba),
        )
        texture.filter_mode(False)
        cached = data, texture
        _TEXTURES[key] = cached
    shader = _shader("IMAGE")
    shader.bind()
    shader.uniform_sampler("image", cached[1])
    batch_key = ("density", tuple(rect))
    batch = _BATCHES.get(batch_key)
    if batch is None:
        batch = batch_for_shader(shader, "TRI_FAN", {
            "pos": _quad(*rect), "texCoord": _quad(0, 0, 1, 1),
        })
        _remember_batch(batch_key, batch)
    blend = gpu.state.blend_get()
    try:
        # Additive blending applies the trace density once to measured RGB.
        gpu.state.blend_set("ADDITIVE" if additive and color is None else "ALPHA")
        batch.draw(shader)
    finally:
        gpu.state.blend_set(blend)


_CIRCLE = tuple((math.cos(i * math.tau / 96), math.sin(i * math.tau / 96))
                for i in range(97))
_SKIN_ANGLE = math.radians(123.0)


def _text(label, x, y, size, color, width, *, align=0.):
    import blf
    blf.size(0, max(1, round(size)))
    if blf.dimensions(0, label)[0] > width:
        suffix = "..."
        label = label[:128]
        while label and blf.dimensions(0, label + suffix)[0] > width:
            label = label[:-1]
        label += suffix
    if align:
        x -= align * blf.dimensions(0, label)[0]
    blf.position(0, x, y, 0)
    blf.color(0, *color)
    blf.draw(0, label)


def _lines(points, color, width=1., *, cache=None):
    import gpu
    from gpu_extras.batch import batch_for_shader
    shader = _shader("POLYLINE_UNIFORM_COLOR")
    shader.bind()
    shader.uniform_float("viewportSize", gpu.state.viewport_get()[2:])
    shader.uniform_float("lineWidth", width)
    shader.uniform_float("color", color)
    batch = _BATCHES.get(cache) if cache is not None else None
    if batch is None:
        batch = batch_for_shader(shader, "LINES", {"pos": [(*point, 0.) for point in points]})
        if cache is not None:
            _remember_batch(cache, batch)
    batch.draw(shader)


def _circle(center, radius, color, width=1., *, cache=None):
    cx, cy = center
    step = 4 if radius <= 8 else 1
    points = [(cx + radius * dx, cy + radius * dy) for dx, dy in _CIRCLE[::step]]
    _lines([p for segment in zip(points, points[1:]) for p in segment], color, width, cache=cache)


def _target_corners(point, half, arm):
    x, y = point
    for sx, sy in ((-1, -1), (-1, 1), (1, -1), (1, 1)):
        corner = x + sx * half, y + sy * half
        yield from (corner, (corner[0] - sx * arm, corner[1]),
                    corner, (corner[0], corner[1] - sy * arm))


def _guides(rect, scale, linear):
    x, y, side, _ = rect
    radius = side * .5
    center = x + radius, y + radius
    targets = geometry.scope_targets(rect)
    reference = _PALETTE["reference"][:3]
    _circle(center, radius, (*reference, .55), scale, cache=("graticule", rect))
    skin = (center[0] + radius * math.cos(_SKIN_ANGLE),
            center[1] + radius * math.sin(_SKIN_ANGLE))
    _lines((center, skin), (*reference, .32), scale, cache=("skin", rect))
    for label, point in targets.items():
        px, py = point
        color = _PALETTE.get(label, _PALETTE["reference"])
        if label in _AXIS_LABELS.values():
            _lines((center, point), (*color[:3], .28), scale, cache=("axis", rect, label))
        _lines(_target_corners(point, 7 * scale, 3 * scale), color, scale,
               cache=("target", rect, scale, label))
        _text(label, px + 9 * scale, py + 5 * scale, 9 * scale, color, 16 * scale)
    for axis, point in geometry.handle_positions(rect, linear, scale).items():
        label = _AXIS_LABELS[axis]
        color = _PALETTE[label]
        if math.dist(point, targets[label]) > scale:
            _lines((center, point), (*color[:3], .35), scale)
        _circle(point, 4.5 * scale, color, 1.6 * scale)


def _slider(rect, field, value, scale, *, vertical=False, track=None):
    lo, hi = _SLIDER_RANGES[field]
    x, y, width, height = rect
    amounts = (value - lo) / (hi - lo)
    label = localization.tr("property." + field)
    if track is not None:
        start, end = track
        if vertical:
            _text(label, x + 5 * scale, y + height - 9 * scale, 8 * scale,
                  _PALETTE["text"], width - 5 * scale)
            _text(f"{value:+.2f}", x + 5 * scale, y, 8 * scale,
                  _PALETTE["orange"], width - 5 * scale)
        else:
            label_y = start[1] - 36 * scale
            _text(label, x, label_y, 9 * scale, _PALETTE["text"], width - 34 * scale)
            _text(f"{value:+.2f}", x + width, label_y, 9 * scale,
                  _PALETTE["orange"], 34 * scale, align=1.)
    elif vertical:
        _text(label, x + scale, y + height - 10 * scale, 9 * scale, _PALETTE["text"], width)
        _text(f"{value:+.2f}", x + scale, y + 4 * scale, 9 * scale, _PALETTE["orange"], width)
        start = x + width / 2, y + 21 * scale
        end = start[0], y + height - 20 * scale
    else:
        _text(label, x, y + height - 10 * scale, 9 * scale, _PALETTE["text"], width - 42 * scale)
        _text(f"{value:+.2f}", x + width - 35 * scale, y + height - 10 * scale, 9 * scale,
              _PALETTE["orange"], 35 * scale)
        start, end = (x, y + 8 * scale), (x + width, y + 8 * scale)
    middle = tuple((a + b) / 2 for a, b in zip(start, end))
    knob = tuple(a + amounts * (b - a) for a, b in zip(start, end))
    colors = {"cr_balance": ("R", "C"), "yb_balance": ("B", "Y")}
    if field in colors:
        negative, positive = colors[field]
        _lines((start, middle), _PALETTE[negative], scale)
        _lines((middle, end), _PALETTE[positive], scale)
        tint = _PALETTE[positive if value >= 0 else negative]
    else:
        _lines((start, end), _PALETTE["outline"], 3 * scale)
        tint = _PALETTE["orange"]
    _lines((middle, knob), tint, 3 * scale)
    _fill((knob[0] - 3 * scale, knob[1] - 3 * scale, 6 * scale, 6 * scale), tint)


def _draw_header(box, stage):
    x, y, _, _ = box["header"]
    scale = box["scale"]
    _fill(box["rect"], _PALETTE["panel"])
    _fill(box["header"], _PALETTE["header"])
    _text(localization.tr("gizmo.wordmark"), x + 12 * scale, y + 10 * scale,
          10 * scale, _PALETTE["text"], 119 * scale)
    for value, name in (("LINEAR", "linear"), ("TONE", "tone")):
        rect = box[name + "_tab"]
        active = stage == value
        if active:
            _fill(rect, _PALETTE["blue"])
        _text(localization.tr("panel." + name), rect[0] + 4 * scale, rect[1] + 6 * scale,
              9 * scale, _PALETTE["text" if active else "muted"], rect[2] - 8 * scale)
    x, y, _, _ = box["close"]
    _lines(((x + 7 * scale, y + 7 * scale), (x + 15 * scale, y + 15 * scale),
            (x + 15 * scale, y + 7 * scale), (x + 7 * scale, y + 15 * scale)),
           _PALETTE["muted"], scale)
    px, py, width, height = box["rect"]
    _lines(((px, py), (px + width, py),
            (px + width, py), (px + width, py + height),
            (px + width, py + height), (px, py + height),
            (px, py + height), (px, py)), _PALETTE["outline"], scale)
    grip = 7 * scale
    for cx, cy, sx, sy in ((px, py, 1, 1), (px + width, py, -1, 1),
                           (px, py + height, 1, -1), (px + width, py + height, -1, -1)):
        _lines(((cx + sx * grip, cy + sy * 2 * scale),
                (cx + sx * 2 * scale, cy + sy * grip)), _PALETTE["muted"], scale)


def _draw_linear(box, state, key, linear):
    rect, scale = box["scope"], box["scale"]
    _fill(rect, _PALETTE["plot"])
    if state is not None and state.rgba is not None:
        _draw_trace(rect, state.rgba, key)
    _guides(rect, scale, linear)
    _slider(box["exposure"], "exposure", linear.exposure, scale, vertical=True)
    _slider(box["cr_balance"], "cr_balance", -linear.balance[0], scale, vertical=True)
    _slider(box["yb_balance"], "yb_balance", -linear.balance[1], scale)


def _draw_tone_curve(rect, model, histogram, selected, scale):
    from gpu_extras.batch import batch_for_shader

    x, y, width, height = rect
    _fill(rect, _PALETTE["plot"])
    if histogram is not None and (maximum := histogram.max()) > 0:
        bin_width = width / histogram.size
        points = []
        for index in np.flatnonzero(histogram):
            a, b, c, d = _quad(x + index * bin_width, y, bin_width,
                                height * .72 * histogram[index] / maximum)
            points.extend((a, b, c, a, c, d))
        shader = _shader("UNIFORM_COLOR")
        shader.bind()
        shader.uniform_float("color", (*_PALETTE["muted"][:3], .24))
        batch_for_shader(shader, "TRIS", {"pos": points}).draw(shader)

    grid = []
    for tick in _J_TICKS:
        px, py = _curve_point(rect, tick, tick)
        grid.extend(((px, y), (px, y + height), (x, py), (x + width, py)))
        _text(str(tick), px, y - 12 * scale, 8 * scale,
              _PALETTE["muted"], 14 * scale, align=.5)
        _text(str(tick), x - 4 * scale, py - 3 * scale, 8 * scale,
              _PALETTE["muted"], 14 * scale, align=1.)
    _lines(grid, _PALETTE["grid"], scale, cache=("curve grid", rect))
    right, top = x + width, y + height
    _lines(((x, top), (right, top)), _PALETTE["outline"], scale,
           cache=("curve top", rect))
    identity = []
    for index in range(0, 36, 2):
        for tick in (index, index + 1):
            level = PLOT_MAX * tick / 36
            identity.append(_curve_point(rect, level, level))
    _lines(identity, _PALETTE["reference"], scale, cache=("curve identity", rect))
    source = np.linspace(0., PLOT_MAX, 192)
    target = model.remap(source * 100.) / 100.
    visible = target <= PLOT_MAX
    curve = [_curve_point(rect, a, b) for a, b in zip(source[visible], target[visible])]
    if curve and not visible.all():
        position = float(np.interp(PLOT_MAX, target, source))
        curve.append(_curve_point(rect, position, PLOT_MAX))
    if len(curve) > 1:
        _lines([point for segment in zip(curve, curve[1:]) for point in segment],
               _PALETTE["orange"], 1.6 * scale)
    sources, targets = _tone_anchor_levels(model)
    actual = model.remap(sources * 100.) / 100.
    for index, source_j in enumerate(sources):
        if source_j > PLOT_MAX:
            continue
        color = _PALETTE["orange" if index == selected else "reference"]
        _circle(_curve_point(rect, source_j, targets[index]), 3 * scale, color, scale)
        if actual[index] <= PLOT_MAX:
            _circle(_curve_point(rect, source_j, actual[index]), 1.5 * scale, color, 2 * scale)
    sdr_width = width / PLOT_MAX
    _fill((x, top + 4 * scale, sdr_width, 3 * scale), _PALETTE["reference"])
    _fill((x + sdr_width, top + 4 * scale, width - sdr_width, 3 * scale), _PALETTE["hdr"])
    _text("SDR", x, top + 12 * scale, 7 * scale, _PALETTE["muted"], sdr_width)
    _text("HDR", x + sdr_width + 3 * scale, top + 12 * scale,
          7 * scale, _PALETTE["muted"], width - sdr_width - 3 * scale)
    _text(localization.tr("gizmo.output_j"), x, top + 21 * scale,
          8 * scale, _PALETTE["muted"], width)
    _text(localization.tr("gizmo.input_j"), x + width * .5, y - 24 * scale,
          8 * scale, _PALETTE["muted"], width, align=.5)


def _draw_appearance(box, state, key):
    rect, scale = box["appearance"], box["scale"]
    x, y, width, height = rect
    top, right = y + height, x + width
    left = box["rect"][0] + 12 * scale
    column_width = box["curve_title"][0] - left - 8 * scale
    compact = height < 55 * scale
    appearance = None if state is None else state.appearance
    status = None if state is None else state.appearance_status
    _fill(rect, _PALETTE["plot"])
    guide = []
    saturation_ticks = ((0., "0"), (.5, "0.5"), (1., "1"), (2., "2"), (math.inf, "\u221e"))
    for value, label in saturation_ticks:
        px = x + appearance_scope.saturation_position(value) * width
        if 0. < value < math.inf:
            guide.extend(((px, y), (px, top)))
        if not compact or value in (0., 1., math.inf):
            alignment = 1. if value == math.inf else .5
            _text(label, px, y - 11 * scale, 8 * scale, _PALETTE["muted"],
                  20 * scale, align=alignment)
    lightness_ticks = tuple(
        (tick, y + appearance_scope.lightness_position(tick * appearance_scope.LIGHTNESS_KNEE) * height)
        for tick in _J_TICKS
    )
    for tick, py in lightness_ticks[2:]:
        guide.extend(((x, py), (right, py)))
    _lines(guide, _PALETTE["grid"], scale, cache=("appearance grid", rect))
    if appearance is not None:
        _draw_trace(rect, appearance.rgba, (key, "appearance"), additive=False)

    knee = lightness_ticks[1][1]
    dash = 5 * scale
    segments = [point for start in np.arange(x, right, 2 * dash)
                for point in ((start, knee), (min(start + dash, right), knee))]
    _lines(segments, (*_PALETTE["orange"][:3], .65), scale, cache=("appearance knee", rect))
    _lines(((x, y), (x, top), (x, y), (right, y), (x, top), (right, top),
            (right, top), (right, y)), _PALETTE["outline"], scale,
           cache=("appearance outline", rect))

    last_label = y
    for tick, py in lightness_ticks:
        _lines(((x - 2 * scale, py), (x, py)), _PALETTE["outline"], scale)
        if tick <= 1 or (py - last_label >= 9 * scale and top - py >= 8 * scale):
            _text(str(tick), x - 4 * scale, py - 3 * scale, 8 * scale,
                  _PALETTE["orange" if tick == 1 else "muted"], 20 * scale, align=1.)
            last_label = py
    _text(f"{appearance_scope.LIGHTNESS_MAX / appearance_scope.LIGHTNESS_KNEE:.2f}",
          x - 4 * scale, top + 1 * scale,
          8 * scale, _PALETTE["muted"], 22 * scale, align=1.)
    _text("J_HK", left, top + 13 * scale, 8 * scale, _PALETTE["muted"], 28 * scale)
    _text("s" if compact else localization.tr("scope.appearance.axis_saturation"),
          x - 11 * scale if compact else x + width * .5,
          y - (11 if compact else 22) * scale, 8 * scale, _PALETTE["muted"],
          width, align=.5)
    title_y = box["curve_title"][1] + 8 * scale
    _text(localization.tr("scope.appearance.title"), left, title_y, 9 * scale,
          _PALETTE["text"], column_width)
    if appearance is not None:
        _text(localization.tr("scope.appearance.overflow", fraction=appearance.overflow_fraction),
              left + column_width, top + 13 * scale, 8 * scale,
              _PALETTE["orange" if appearance.overflow_fraction else "muted"],
              column_width, align=1.)
    if status == "preview":
        _text(localization.tr("scope.appearance.preview"), right - 4 * scale,
              y + 4 * scale, 8 * scale, _PALETTE["text"], width - 8 * scale, align=1.)
    elif status != "current":
        status_id = status if status in {"bake", "unavailable"} else (
            "unavailable" if status == "error" else "updating")
        _text(localization.tr("scope.appearance." + status_id), x + width * .5,
              y + height * .5 - 3 * scale, 8 * scale,
              _PALETTE["orange" if status_id == "unavailable" else "text"],
              width - 4 * scale, align=.5)
        if status_id == "unavailable" and state is not None and state.appearance_error and not compact:
            _text(state.appearance_error.splitlines()[0], x + width * .5,
                  y + height * .5 - 15 * scale, 8 * scale,
                  _PALETTE["muted"], width - 4 * scale, align=.5)


def _draw_tone(box, state, key, linear, tone, selected):
    scale = box["scale"]
    model = _tone_model(tone)
    histogram = None if state is None else state.tone_histogram
    _draw_appearance(box, state, key)
    _draw_tone_curve(box["curve"], model, histogram, selected, scale)
    _slider(box["exposure"], "exposure", linear.exposure, scale, track=box["exposure_track"])
    _slider(box["fit"], "fit", tone.fit, scale, vertical=True, track=box["fit_track"])
    tx, ty, tw, _ = box["curve_title"]
    _text(localization.tr("gizmo.tone_curve"), tx, ty + 8 * scale,
          10 * scale, _PALETTE["text"], tw)
    peak = box["peak"]
    _fill(peak, _PALETTE["header"])
    px, py, pw, _ = peak
    peak_value = localization.tr(f"tone.peak.{int(tone.peak_nits)}")
    label = localization.tr("gizmo.peak", value=peak_value) if pw >= 100 * scale else peak_value
    _text(label, px + 6 * scale, py + 8 * scale, 9 * scale, _PALETTE["text"], pw - 23 * scale)
    _lines(((px + pw - 15 * scale, py + 15 * scale), (px + pw - 11 * scale, py + 11 * scale),
            (px + pw - 11 * scale, py + 11 * scale), (px + pw - 7 * scale, py + 15 * scale)),
           _PALETTE["muted"], scale)


def _draw_status(box, state):
    if state is not None and state.status == "current":
        return
    failed = state is not None and state.status in {"error", "unavailable"}
    title = localization.tr("scope.vectorscope.unavailable" if failed
                            else "scope.vectorscope.updating")
    if failed and state.error:
        title += "  " + state.error.splitlines()[0]
    x, y, width, _ = box["status"]
    scale = box["scale"]
    _text(title, x, y + 3 * scale, 9 * scale,
          _PALETTE["orange" if failed else "muted"], width)


def draw(region, box, state, key, stage, linear, tone, selected):
    """Draw only the supplied view, with GPU state restored on exit."""
    import gpu
    from mathutils import Matrix

    blend, depth = gpu.state.blend_get(), gpu.state.depth_test_get()
    try:
        gpu.state.blend_set("ALPHA")
        gpu.state.depth_test_set("NONE")
        with gpu.matrix.push_pop(), gpu.matrix.push_pop_projection():
            gpu.matrix.load_identity()
            gpu.matrix.load_projection_matrix(Matrix((
                (2 / region.width, 0, 0, -1),
                (0, 2 / region.height, 0, -1),
                (0, 0, -1, 0), (0, 0, 0, 1),
            )))
            _draw_header(box, stage)
            if stage == "LINEAR":
                _draw_linear(box, state, key, linear)
            else:
                _draw_tone(box, state, key, linear, tone, selected)
            _draw_status(box, state)
    finally:
        gpu.state.blend_set(blend)
        gpu.state.depth_test_set(depth)


def release(key, *, appearance_only=False):
    _TEXTURES.pop((key, "appearance"), None)
    if not appearance_only:
        _TEXTURES.pop(key, None)


def reset():
    _TEXTURES.clear()
    _BATCHES.clear()
    _tone_model.cache_clear()


def close():
    reset()
    _SHADERS.clear()

