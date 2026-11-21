"""Float64 equations for the product-local Color J/C LGG prototypes."""
from typing import NamedTuple

import numpy as np

from color_tools.perceptual_grade_core.model.hk_guard import guard
from color_tools.perceptual_grade_reference.grading import coefficient_weights, smoother
from color_tools.perceptual_grade_reference.responses import HK, requested_energy

PIVOT = 35. / 75.


class Result(NamedTuple):
    q: np.ndarray
    energy: np.ndarray
    changed: np.ndarray


def axis(chroma, ja, pivot, nonlog):
    denominator = np.abs(ja) * pivot
    ratio = np.divide(chroma, denominator, out=np.full_like(chroma, np.inf), where=denominator != 0)
    if nonlog:
        position = 1. - 1. / np.sqrt(1. + 3. * ratio)
    else:
        position = 1. - 1. / (1. + np.log1p(ratio) / np.log(2.))
    return np.where(chroma == 0., 0., position)


def chroma_scale(x, lift, gamma, gain, weights):
    stops = lift * (1. - x[..., None]) - gamma * (2. * x[..., None] - 1.) + gain
    return np.exp2(np.sum(stops * weights, axis=-1))


def apply(stage, appearance, tone, settings):
    def wheels(family):
        return np.array([[settings.get(f"tone{band}{family}{wheel}", 0.) for band in "SMWH"]
                         for wheel in ("Lift", "Gamma", "Gain")])

    q, ja = appearance.q, appearance.ja
    energy = ja * abs(ja)
    j_controls, c_controls = wheels("J"), wheels("C")
    if not (np.any(j_controls) or np.any(c_controls)):
        return Result(q, energy, np.zeros_like(ja, dtype=bool))

    chroma = np.hypot(q[..., 1], q[..., 2])
    height = np.hypot(ja, np.sqrt(HK * chroma))
    pivot = settings.get("saturationPivot", PIVOT) if stage == "lgg_pivot" else PIVOT
    x = axis(chroma, ja, pivot, stage == "lgg_nonlog")

    def weights(fit):
        return coefficient_weights(height, tone.coefficient_knots, tone.high, settings.get(fit, 0))

    adjust_j = bool(np.any(j_controls)) & (height > 0.)
    adjust_c = bool(np.any(c_controls)) & (chroma > 0.)
    active = adjust_j | adjust_c
    if not np.any(active):
        return Result(q, energy, np.zeros_like(ja, dtype=bool))

    lift, gamma, gain = j_controls
    domain = 20. * x[..., None]
    row_offsets = np.exp2(gain) * (domain * np.exp2(-gamma * (2. * x[..., None] - 1.))
                                 + lift * (1. - x[..., None])) - domain
    lightness = q[..., 0] + smoother(height / (100. * tone.target[1])) * np.sum(
        row_offsets * weights("lightnessFit"), axis=-1)
    ab = q[..., 1:] * chroma_scale(x, *c_controls, weights("chromaFit"))[..., None]
    lightness = np.where(adjust_j, lightness, q[..., 0])
    ab = np.where(adjust_c[..., None], ab, q[..., 1:])
    edited = np.concatenate((lightness[..., None], ab), axis=-1)
    guarded_q, guarded_energy = guard(edited, requested_energy(edited, q, ja), energy)
    # Preserve the exact input path when both the requested state and repair
    # are bit-identical. Signed-energy-only repairs still reach the decoder.
    changed = active & (np.any(guarded_q != q, axis=-1) | (guarded_energy != energy))
    return Result(guarded_q, guarded_energy, changed)
