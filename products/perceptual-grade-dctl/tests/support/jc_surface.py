"""Float64 equations for the product-local Color J/C surface prototype."""
from typing import NamedTuple

import numpy as np

from color_tools.perceptual_grade_core.model.hk_guard import guard
from color_tools.perceptual_grade_reference.grading import smoother
from color_tools.perceptual_grade_reference.responses import HK, requested_energy


class Result(NamedTuple):
    q: np.ndarray
    energy: np.ndarray
    changed: np.ndarray


def smoothstep(value):
    value = np.clip(value, 0., 1.)
    return value * value * (3. - 2. * value)


def anchor(height, anchors, amounts):
    i = np.clip(np.searchsorted(anchors, height) - 1, 0, 2)
    left, right = anchors[i], anchors[i + 1]
    u = smoothstep((height - left) / (right - left))
    return amounts[i] + (amounts[i + 1] - amounts[i]) * u


def log_ratio(chroma, ja, center):
    pivot = (35. / 75.) * abs(ja) * center / (1. - center)
    return np.log2(chroma / pivot)


def j_response(chroma, ja, center, width):
    base = (35. / 75.) * abs(ja)
    regular = (chroma > 0.) & (ja != 0.)
    c = chroma[regular]
    saturation = c / (c + base[regular])
    ratio = log_ratio(c, ja[regular], center)
    span = 1. + 2. * width
    curve = 1. - np.exp2(-abs(ratio) / span)
    response = ((chroma > 0.) & (ja == 0.)).astype(float)
    response[regular] = np.sign(ratio) * curve * smoothstep(saturation / .1)
    return response


def c_response(chroma, ja, center, width, amount):
    regular = (chroma > 0.) & (ja != 0.)
    centers = np.broadcast_to(center, chroma.shape)
    ratio = log_ratio(chroma[regular], ja[regular], centers[regular])
    span = 1. + 2. * width
    magnitude = abs(ratio)
    mapped = span * np.log2(1. + np.exp2(amount[regular] / span) * np.expm1(np.log(2.) * magnitude / span))
    response = np.where((chroma > 0.) & (ja == 0.), amount, 0.)
    response[regular] = np.sign(ratio) * (mapped - magnitude)
    return response


def apply(appearance, tone, settings):
    q, ja = appearance.q, appearance.ja
    energy = ja * abs(ja)
    j_amounts = np.array([settings.get(f"tone{row}JContrast", 0.) for row in "SMWH"])
    c_amounts = np.array([settings.get(f"tone{row}CContrast", 0.) for row in "SMWH"])
    j_center = settings.get("jSaturationCenter", .5)
    j_width = settings.get("jSaturationWidth", .5)
    c_center = settings.get("cSaturationCenter", .5)
    c_width = settings.get("cSaturationWidth", .5)
    gain = settings.get("globalChromaGain", 0.)
    if not (np.any(j_amounts) or np.any(c_amounts) or gain):
        return Result(q, energy, np.zeros_like(ja, dtype=bool))

    chroma = np.hypot(q[..., 1], q[..., 2])
    height = np.hypot(ja, np.sqrt(HK * chroma))
    anchors = 100. * tone.target[1:]
    edited = q.copy()
    if np.any(j_amounts):
        j = anchor(height, anchors, j_amounts)
        edited[..., 0] += j * j_response(chroma, ja, j_center, j_width) * smoother(height / anchors[0])
    if np.any(c_amounts) or gain:
        c = anchor(height, anchors, c_amounts)
        scale = np.exp2(gain + c_response(chroma, ja, c_center, c_width, c))
        edited[..., 1:] *= scale[..., None]
    changed = np.any(edited != q, axis=-1)
    if np.any(changed):
        requested = requested_energy(edited[changed], q[changed], ja[changed])
        edited[changed], energy[changed] = guard(edited[changed], requested, energy[changed])
    return Result(edited, energy, changed)
