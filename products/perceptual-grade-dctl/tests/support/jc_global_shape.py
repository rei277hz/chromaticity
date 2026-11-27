"""Independent float64 forward model for Global Shape."""
import numpy as np

from . import cone_reference as cone, jc_gain, jc_surface


def saturation_at_position(position):
    """Decode the HDR Color Picker coordinate into raw C/abs(J_A)."""
    return (34.09902169100728 / 75.) * position / np.sqrt(1. - position**2)


def spline(value, knots, outputs, slopes):
    result = outputs[-1] + (value - knots[-1])
    for index, (left, right) in enumerate(zip(knots, knots[1:])):
        # Evaluate the interval directly in Bernstein form.
        start, end = outputs[index:index + 2]
        width = right - left
        secant = (end - start) / width
        t = np.clip((value - left) / width, 0., 1.)
        a, b, c = (1. - t) ** 2, t * (1. - t), t ** 2
        denominator = secant * (a + c) + (slopes[index] + slopes[index + 1]) * b
        segment = (secant * (start * a + end * c)
                   + (end * slopes[index] + start * slopes[index + 1]) * b) / denominator
        result = np.where((value >= left) & (value < right), segment, result)
    return result


def end_shape(value, pivot, lower, upper):
    knots = (0., pivot / 2., pivot, pivot + 2.)
    outputs = (0., pivot / 2. * (1. + lower / 2.), pivot, pivot + 2. + upper)
    return spline(value, knots, outputs, (1., 1., 1., 1.))


def shape(value, pivot, contrast, lower, upper):
    knots = (0., pivot, pivot + 2.)
    value = spline(value, knots, knots, (1., np.exp2(contrast), 1.))
    return end_shape(value, pivot, lower, upper)


def chroma_map(height, chroma, settings, *, linear_gain=False):
    c_base = (35. / 75.) * height
    pivot = settings.get("cPivot", .5)
    knee = c_base * pivot / (1. - pivot)
    contrast_gain = np.exp2(settings.get("cContrast", 0.))
    below = chroma < knee
    fraction = np.divide(chroma, knee, out=np.zeros_like(chroma), where=below)
    contrasted = np.where(below, chroma / (contrast_gain * (1. - fraction) + fraction),
                          knee + contrast_gain * (chroma - knee))

    c_upper = settings.get("cVivid", 0.)
    c_ratio = np.divide(contrasted, c_base, out=np.zeros_like(chroma), where=c_base > 0.)
    c_position = np.log1p(c_ratio) / np.log(2.)
    c_result = end_shape(c_position, 1., settings.get("cMuted", 0.), c_upper)
    c_mapped = np.where(height == 0., contrasted * np.exp2(c_upper),
                        c_base * np.expm1(c_result * np.log(2.)))
    tone_ratio = height / settings.get("cToneCrossover", 45.)
    return tonal_chroma_gain(tone_ratio, c_base, c_mapped, settings, linear_gain)


def unified_chroma_map(height, chroma, settings):
    c_base = (35. / 75.) * height
    pivot = saturation_at_position(settings.get("cSaturationCrossover", .5))
    knee = height * pivot
    muted = np.exp2(settings.get("cMutedGain", 0.))
    vivid = np.exp2(settings.get("cVividGain", 0.))
    ratio = np.sqrt(vivid / muted)
    gain = np.divide(np.sqrt(muted * vivid) * (ratio * chroma + knee), chroma + ratio * knee,
                     out=np.full_like(chroma, vivid), where=(chroma + ratio * knee) > 0.)
    tone_ratio = (height / 100.) / settings.get("cToneCrossover", .45)
    return tonal_chroma_gain(tone_ratio, c_base, chroma * gain, settings, linear_gain=True)


def tonal_chroma_gain(tone, c_base, c_mapped, settings, linear_gain):
    gain_stops = (settings.get("shadowChroma", 0.) * jc_surface.smoothstep(1. - tone)
                  + settings.get("highlightChroma", 0.) * jc_surface.smoothstep(tone - 1.))
    fade = np.divide(c_mapped, c_mapped + c_base / 9., out=np.zeros_like(c_mapped),
                     where=c_mapped + c_base / 9. > 0.)
    if linear_gain:
        return c_mapped * ((1. - fade) + fade * np.exp2(gain_stops))
    return c_mapped * np.exp2(gain_stops * fade)


def apply(wire, settings):
    if settings.get("direction", 0):
        raise ValueError("The Global Shape reference evaluates the forward direction")
    point = cone.enter(wire)
    ja, ab = point.ja, point.q[:, 1:]
    height = abs(ja)
    chroma = np.linalg.norm(ab, axis=-1)
    c_mapped = chroma_map(height, chroma, settings)
    c_scale = np.divide(c_mapped, chroma, out=np.ones_like(chroma), where=chroma > 0.)

    saturation = jc_gain.saturation(c_mapped, height)
    bias = settings.get("jSaturationBias", 0.)
    strength = 1. - bias * (1. - saturation) if bias > 0. else 1. + bias * saturation
    j_pivot = np.log2(1. + settings.get("jPivot", 45.) / 16.)
    j_position = np.log1p(height / 16.) / np.log(2.)
    j_result = shape(j_position, j_pivot, strength * settings.get("jContrast", 0.),
                     strength * settings.get("jToe", 0.), strength * settings.get("jShoulder", 0.))
    j_mapped = 16. * np.expm1(j_result * np.log(2.))
    j_scale = np.divide(j_mapped, height, out=np.ones_like(height), where=height > 0.)
    ab = ab * (c_scale * j_scale)[:, None]
    return cone.pack(ja * j_scale, ab[:, 0], ab[:, 1])
