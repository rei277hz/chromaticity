"""Output appearance effects and native AP1 input projection."""
from dataclasses import dataclass
import math

import numpy as np

from ..color_core.scaled import norm, signed_power
from .responses import HK, State, signed_hk

MAXIMUM=1024.


@dataclass(frozen=True)
class OutputCompressionSettings:
    """Optional saturation shoulder in raw modCAM16 C / |J_A| units."""

    enabled: bool = False
    knee: float = .5
    ceiling: float = 1.

    def __post_init__(self):
        if type(self.enabled) is not bool:
            raise ValueError('Output saturation compression enabled must be a boolean')
        try:
            knee, ceiling = float(self.knee), float(self.ceiling)
        except (TypeError, ValueError, OverflowError) as error:
            raise ValueError('Output saturation limits must be finite numbers') from error
        if (not math.isfinite(knee) or not math.isfinite(ceiling)
                or not 0. <= knee < ceiling <= 8.):
            raise ValueError('Output saturation requires 0 <= knee < ceiling <= 8')
        object.__setattr__(self, 'knee', knee)
        object.__setattr__(self, 'ceiling', ceiling)


@dataclass(frozen=True)
class OutputDensitySettings:
    """Saturation-weighted subtractive density in modCAM16 lightness units."""

    amount: float = 0.
    pivot: float = .5

    def __post_init__(self):
        try:
            amount, pivot = float(self.amount), float(self.pivot)
        except (TypeError, ValueError, OverflowError) as error:
            raise ValueError('Output density controls must be finite numbers') from error
        if not math.isfinite(amount) or not 0. <= amount <= .6:
            raise ValueError('Output density amount must be finite and between 0 and 0.6')
        if not math.isfinite(pivot) or not .05 <= pivot <= 8.:
            raise ValueError('Output density pivot must be finite and between 0.05 and 8')
        object.__setattr__(self, 'amount', amount)
        object.__setattr__(self, 'pivot', pivot)

    @property
    def enabled(self):
        return self.amount > 0.


def apply_density(state, settings):
    """Apply logarithmic density while preserving opponent chroma and hue."""
    if not settings.enabled:
        return state

    if state.q.dtype == object:
        result = state.q.copy()
        energy = state.energy.copy()
        for index, (row, original_energy) in enumerate(zip(
                result.reshape(-1, 3), state.energy.flat)):
            if not original_energy:
                continue
            chroma = norm(row[1:])
            if not chroma:
                continue
            ja = signed_power(original_energy, .5)
            lightness = abs(ja)
            scale = max(chroma, lightness)
            chroma_unit = chroma / scale
            pivot_unit = settings.pivot * (lightness / scale)
            weight = chroma_unit**2 / (chroma_unit**2 + pivot_unit**2)
            attenuation = 10.**(-settings.amount * float(weight))
            if attenuation == 1.:
                continue
            new_energy = original_energy * (attenuation * attenuation)
            new_ja = ja * attenuation
            energy.flat[index] = new_energy
            row[0] = signed_hk(new_ja, chroma)
        return State(result, energy)

    q, original_energy = state.q, state.energy
    opponent = q[..., 1:]
    opponent_scale = np.max(abs(opponent), axis=-1)
    opponent_unit = np.divide(opponent, opponent_scale[..., None],
                              out=np.zeros_like(opponent), where=opponent_scale[..., None] > 0.)
    chroma_unit = np.hypot(opponent_unit[..., 0], opponent_unit[..., 1])
    lightness = np.sqrt(abs(original_energy))
    active = (opponent_scale > 0.) & (original_energy != 0.)
    if not np.any(active):
        return state

    scale = np.maximum(opponent_scale[active], lightness[active])
    chroma_ratio = (opponent_scale[active] / scale) * chroma_unit[active]
    lightness_ratio = lightness[active] / scale
    pivot_ratio = settings.pivot * lightness_ratio
    weight = chroma_ratio**2 / (chroma_ratio**2 + pivot_ratio**2)
    attenuation = np.exp2(-settings.amount * weight * math.log2(10.))
    changed = attenuation != 1.
    if not np.any(changed):
        return state

    result = q.copy()
    energy = original_energy.copy()
    rows = np.flatnonzero(active)[changed]
    energy.flat[rows] = original_energy.flat[rows] * (attenuation[changed] * attenuation[changed])
    new_ja = np.sign(original_energy.flat[rows]) * lightness[active][changed] * attenuation[changed]
    active_opponent_scale = opponent_scale.flat[rows]
    active_unit = opponent_unit.reshape(-1, 2)[rows]
    radius_unit = np.hypot(active_unit[:, 0], active_unit[:, 1])
    root_chroma = np.sqrt(active_opponent_scale) * np.sqrt(radius_unit)
    height = np.sqrt(HK) * root_chroma
    magnitude = np.hypot(new_ja, height)
    result.reshape(-1, 3)[rows, 0] = np.where(new_ja >= 0., magnitude, 2.*height-magnitude)
    return State(result, energy)


def compress_saturation(state, settings):
    """Roll off chroma at fixed signed achromatic energy and hue."""
    if not settings.enabled:
        return state

    # Express the shoulder in chroma units to avoid a singular C / |J_A|.
    # At J_A == 0 both knee and width are zero, so chromatic rows become black.
    width = settings.ceiling - settings.knee
    if state.q.dtype == object:
        result = state.q.copy()
        for row, ja in zip(result.reshape(-1, 3), state.ja.flat):
            chroma = norm(row[1:])
            knee = abs(ja) * settings.knee
            if chroma > knee:
                span = abs(ja) * width
                excess = chroma - knee
                radius = knee + span * (excess / (span + excess))
                row[1:] = [component / chroma * radius for component in row[1:]]
                row[0] = signed_hk(ja, norm(row[1:]))
        return State(result, state.energy)

    ab = state.q[..., 1:]
    ja = state.ja
    lightness = abs(ja)
    knee = lightness * settings.knee
    with np.errstate(over='ignore'):
        chroma = np.hypot(ab[..., 0], ab[..., 1])
    active = chroma > knee
    if not np.any(active):
        return state

    # Normalize only the active rows. This also keeps an overflowing norm from
    # discarding the direction of finite opponent coordinates.
    ab = ab[active]
    scale = np.max(abs(ab), axis=-1)
    unit = ab / scale[:, None]
    unit /= np.hypot(unit[:, 0], unit[:, 1])[:, None]
    excess = chroma[active] - knee[active]
    span = lightness[active] * width
    smaller = np.minimum(excess, span)
    larger = np.maximum(excess, span)
    correction = np.divide(smaller, 1. + np.divide(smaller, larger),
                           out=np.zeros_like(smaller), where=larger > 0.)
    radius = knee[active] + correction
    result = state.q.copy()
    result[..., 1:][active] = unit * radius[:, None]
    result[..., 0][active] = signed_hk(ja[active], radius)
    return State(result, state.energy)


def apply_output_effects(state, density, compression):
    """Apply density before the optional saturation shoulder."""
    return compress_saturation(apply_density(state, density), compression)


def down(x):return np.nextafter(x,-np.inf)


def input_repair(rgb, weights):
    """Continuous idempotent input projection; identity throughout the LUT cube."""
    rgb = np.asarray(rgb, dtype=np.float64)
    weights = np.asarray(weights, dtype=np.float64)
    if rgb.shape[-1:] != (3,) or not np.isfinite(rgb).all():
        raise ValueError('LUT input must contain finite RGB triples')
    if weights.shape != (3,) or not np.isfinite(weights).all() or np.any(weights <= 0):
        raise ValueError('AP1 luminance weights must be positive')
    result = rgb.copy()
    active = (rgb.min(axis=-1) < 0) | (rgb.max(axis=-1) > MAXIMUM)
    x = rgb[active]
    if not len(x):return result
    amplitude = np.max(abs(x), axis=-1)
    unit = x/amplitude[:, None]
    y = np.maximum(0., unit @ weights)
    k = np.maximum(0., -unit.min(axis=-1))
    factor = np.divide(y, y+k, out=np.zeros_like(y), where=y+k > 0)
    v = np.where((k > 0)[:, None], (unit+k[:, None])*factor[:, None], unit)
    maximum = np.max(v, axis=-1)
    with np.errstate(over='ignore', divide='ignore'):
        scale = np.minimum(amplitude, down(np.divide(MAXIMUM, maximum, out=np.zeros_like(maximum), where=maximum > 0)))
    result[active] = v*np.maximum(0.,scale)[:, None]
    return result
