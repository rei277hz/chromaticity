"""Density and hue of the Grade's final pre-RGB appearance samples."""

from dataclasses import dataclass

import numpy as np

from .color_core.linear import rgb_to_xyz
from .color_core.modcam16 import encode_cones, signed_hk
from .kernel.prepare import nits_to_j, prepare_linear
from .vectorscope import normalize_histogram, splat_components


LIGHTNESS_KNEE = 100.
LIGHTNESS_MAX = float(100. * nits_to_j(4000.))
_KNEE_POSITION = .8
_WIDTH = 288
_HEIGHT = 144
_LUMINANCE = .6
_REC709_LUMINANCE = np.asarray(rgb_to_xyz("Linear Rec.709"))[1]
_FULL_HUE_CHROMA = 4.
_FULL_HUE_SATURATION = .04


@dataclass(frozen=True, eq=False)
class AppearanceScope:
    rgba: np.ndarray
    overflow_fraction: float


def lightness_position(j):
    """Return the normalized plot position of a raw J_HK value."""
    value = np.clip(j, 0., LIGHTNESS_MAX)
    return (_KNEE_POSITION * np.minimum(value, LIGHTNESS_KNEE) / LIGHTNESS_KNEE
            + (1. - _KNEE_POSITION) * np.maximum(value - LIGHTNESS_KNEE, 0.)
            / (LIGHTNESS_MAX - LIGHTNESS_KNEE))


def saturation_position(s):
    """Compress raw C/|J_A| into [0, 1], including the infinite limit."""
    saturation = np.clip(np.asarray(s, dtype=np.float64), 0., np.finfo(np.float64).max)
    return saturation / np.hypot(1., saturation)


def _palette_anchors():
    space = "Linear Rec.709"
    swatches = np.array(((1., 0., 0.), (1., 1., 0.), (0., 1., 0.),
                         (0., 1., 1.), (0., 0., 1.), (1., 0., 1.)))
    opponent = encode_cones(swatches @ prepare_linear(space=space).to_cones.T).q[:, 1:]
    hue = np.arctan2(opponent[:, 1], opponent[:, 0])
    luminance = swatches @ _REC709_LUMINANCE
    # Preserve each swatch's RGB direction from gray at fixed linear luminance.
    scale = np.minimum(_LUMINANCE / luminance, (1. - _LUMINANCE) / (1. - luminance))
    rgb = _LUMINANCE + scale[:, None] * (swatches - luminance[:, None])
    return hue, rgb


_HUE_ANCHORS, _RGB_ANCHORS = _palette_anchors()


def _trace(mass, hue_vector):
    rgba = np.zeros((*mass.shape, 4), dtype=np.float32)
    occupied = mass > 0.
    x, y = hue_vector[occupied].T
    hue = np.arctan2(y, x)
    coherence = np.minimum(np.hypot(x, y) / mass[occupied], 1.)
    rgb = np.column_stack([np.interp(hue, _HUE_ANCHORS, channel, period=2. * np.pi)
                           for channel in _RGB_ANCHORS.T])
    rgba[occupied, :3] = _LUMINANCE + coherence[:, None] * (rgb - _LUMINANCE)
    rgba[..., 3] = normalize_histogram(mass)
    rgba.setflags(write=False)
    return rgba


def analyze(rgba):
    """Plot final (J_A, a, b, alpha) samples and report off-scale alpha mass."""
    pixels = np.asarray(rgba, dtype=np.float64)
    if pixels.ndim != 3 or pixels.shape[-1] != 4 or min(pixels.shape[:2]) < 1:
        raise ValueError("Appearance scope input must be a nonempty RGBA image")
    finite = np.isfinite(pixels).all(axis=-1) & (pixels[..., 3] > 0.)
    ja, a, b, alpha = pixels[finite].T
    with np.errstate(over="ignore", invalid="ignore"):
        chroma = np.hypot(a, b)
        lightness = signed_hk(ja, chroma)
    valid = np.isfinite(lightness)
    weights = np.minimum(alpha, 1.)
    total = weights[valid].sum()
    overflow = lightness > LIGHTNESS_MAX
    overflow_fraction = float(weights[valid & overflow].sum() / total) if total > 0. else 0.

    visible = valid & ~overflow
    ja, a, b, chroma, lightness, weights = (
        channel[visible] for channel in (ja, a, b, chroma, lightness, weights))
    saturation = np.where(chroma > 0., np.inf, 0.)
    with np.errstate(over="ignore"):
        np.divide(chroma, np.abs(ja), out=saturation, where=ja != 0.)
    rows = np.minimum((_HEIGHT * lightness_position(lightness)).astype(int), _HEIGHT - 1)
    cols = np.minimum((_WIDTH * saturation_position(saturation)).astype(int), _WIDTH - 1)
    bins = rows * _WIDTH + cols

    hue = np.arctan2(b, a)
    reliability = np.minimum(np.minimum(chroma, _FULL_HUE_CHROMA) / _FULL_HUE_CHROMA,
                             np.minimum(saturation, _FULL_HUE_SATURATION) / _FULL_HUE_SATURATION)
    hue_weight = weights * reliability
    grid = np.stack([np.bincount(bins, weights=component, minlength=_WIDTH * _HEIGHT)
                     for component in (weights, hue_weight * np.cos(hue), hue_weight * np.sin(hue))])
    grid = grid.reshape(3, _HEIGHT, _WIDTH)
    mass, hue_vector = splat_components(grid[0], np.moveaxis(grid[1:], 0, -1))
    return AppearanceScope(_trace(mass, hue_vector), overflow_fraction)
