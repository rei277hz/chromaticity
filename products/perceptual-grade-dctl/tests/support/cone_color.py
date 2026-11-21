"""Independent float64 forward maps for the two Resolve Stage 3 nodes."""
import numpy as np

from color_tools.perceptual_grade_core.model.tonal_web import cardinal_values, smoother
from color_tools.perceptual_grade_reference.grading import Color, ColorSettings

from . import cone_reference as cone, jc_surface


def integrate_stretch(value, knots, slopes):
    """Two-point Gauss quadrature integrates the cubic slope exactly on each span."""
    result = np.zeros_like(value)
    for i in range(4):
        width = knots[..., i + 1] - knots[..., i]
        length = np.clip(value - knots[..., i], 0., width)
        middle = length / (2. * width)
        offset = middle / np.sqrt(3.)
        blend = (jc_surface.smoothstep(middle - offset) + jc_surface.smoothstep(middle + offset)) / 2.
        result += length * ((1. - blend) * slopes[..., i] + blend * slopes[..., i + 1])
    return result + np.maximum(value - knots[..., -1], 0.) * slopes[..., -1]


def jc(wire, tone, settings):
    point = cone.enter(wire)
    ja, ab = point.ja, point.q[:, 1:]
    chroma = np.linalg.norm(ab, axis=-1)
    anchors = 100. * tone.target[1:]
    amounts = np.array([settings.get(f"tone{row}CContrast", 0.) for row in "SMWH"])
    contrast = jc_surface.anchor(abs(ja), anchors, amounts)
    stops = jc_surface.c_response(chroma, ja, settings.get("cSaturationCenter", .5),
                                  settings.get("cSaturationWidth", .5), contrast)
    ab = ab * np.exp2(settings.get("globalChromaGain", 0.) + stops)[:, None]

    chroma = np.linalg.norm(ab, axis=-1)
    slopes = [np.ones_like(ja)]
    for row, anchor in zip("SMWH", anchors):
        response = jc_surface.j_response(chroma, np.full_like(ja, anchor),
                                         settings.get("jSaturationCenter", .5),
                                         settings.get("jSaturationWidth", .5))
        slopes.append(np.exp2(settings.get(f"tone{row}JContrast", 0.) * response))
    ja = np.sign(ja) * integrate_stretch(abs(ja), np.r_[0., anchors], np.stack(slopes, axis=-1))
    return cone.pack(ja, ab[:, 0], ab[:, 1])


def adaptance(ab, targets, reach):
    length = np.linalg.norm(targets, axis=-1)
    direction = np.divide(targets, length[:, None], out=np.zeros_like(ab), where=length[:, None] > 0.)
    u = np.sum(ab * direction, axis=-1)
    v = ab[:, 1] * direction[:, 0] - ab[:, 0] * direction[:, 1]
    travel = reach ** 4 * length + length ** 5 / 5.
    # Three-point quadrature integrates the quartic inverse speed exactly.
    low, high = np.zeros_like(length), 2. * length
    for _ in range(56):
        step = (low + high) / 2.
        mid = u + step / 2.
        offset = np.sqrt(3. / 5.) * step / 2.
        left = ((mid - offset) ** 2 + v ** 2) ** 2
        right = ((mid + offset) ** 2 + v ** 2) ** 2
        center = (mid ** 2 + v ** 2) ** 2
        below = step * (reach ** 4 + (5. * (left + right) + 8. * center) / 18.) < travel
        low, high = np.where(below, step, low), np.where(below, high, step)
    return ab + ((low + high) / 2.)[:, None] * direction


def hue_field(angle, knots, values):
    extended_knots = np.r_[knots, knots[0] + 2. * np.pi]
    wrapped = (angle - knots[0]) % (2. * np.pi) + knots[0]
    i = np.clip(np.searchsorted(extended_knots, wrapped, side="right") - 1, 0, 5)
    u = smoother((wrapped - extended_knots[i]) / (extended_knots[i + 1] - extended_knots[i]))
    return (1. - u) * values[i] + u * values[(i + 1) % 6]


def warp(wire, tone, settings):
    point = cone.enter(wire)
    ja, ab = point.ja, point.q[:, 1:]
    controls = {family: np.array([[settings.get(f"web{family}{i}{j}", 0.) for j in range(6)]
                                  for i in range(4)]) for family in ("chroma", "hue", "scale")}
    # The existing independent web includes the same hue and radius edits.
    # Request just those two spatial components and retain the input signed JA.
    web = Color(ColorSettings(web=dict(log_chroma=controls["chroma"], hue_degrees=controls["hue"])), tone).web
    q, _ = web.apply(point.q, ja * abs(ja), abs(ja))
    anchors = web.geometry.anchors
    tints = np.array([[settings.get(f"tone{row}Adaptance{axis}", 0.) for axis in "AB"] for row in "SMWH"])
    tint = cardinal_values(abs(ja), anchors, tints) * smoother(abs(ja) / anchors[0])[:, None]
    ab = adaptance(q[:, 1:], tint, settings.get("adaptanceHalfSaturation", .25) * abs(ja))

    c = np.linalg.norm(ab, axis=-1)
    radius = np.hypot(ja, c)
    c_fraction = np.divide(c, radius, out=np.zeros_like(c), where=radius > 0.)
    j_fraction = np.divide(abs(ja), radius, out=np.ones_like(c), where=radius > 0.)
    hue = np.arctan2(ab[:, 1], ab[:, 0])
    knots, slopes = [], []
    for i, height in enumerate(anchors):
        # Solve height**2 = (r * j_fraction)**2 + 66 * r * c_fraction.
        knots.append(2. * height ** 2 / (np.hypot(66. * c_fraction, 2. * height * j_fraction) + 66. * c_fraction))
        angles = web.geometry.angles[i] + np.deg2rad(controls["hue"][i])
        stops = hue_field(hue, angles, controls["scale"][i])
        slopes.append(np.exp2(stops * jc_surface.smoothstep(10. * c_fraction)))
    stretch = integrate_stretch(radius, np.stack([np.zeros_like(radius), *knots], axis=-1),
                               np.stack([slopes[0], *slopes], axis=-1))
    gain = np.divide(stretch, radius, out=np.ones_like(radius), where=radius > 0.)
    return cone.pack(ja * gain, ab[:, 0] * gain, ab[:, 1] * gain)
