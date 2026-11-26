"""Float64 reference stages at the DCTL XYZ and cone-response boundaries."""
import numpy as np

from color_tools.perceptual_grade_reference.appearance import encode, decode
from color_tools.perceptual_grade_reference.export import OutputCompressionSettings
from color_tools.perceptual_grade_reference.grading import Tone, ToneSettings, kernel, normalized_kernel
from color_tools.perceptual_grade_reference.model import LinearSettings, WHITES, linear_matrix

from . import cone_color, cone_reference, jc_gain, jc_global_shape, jc_prototype, jc_surface
from .dctl import (
    ANCHOR_CENTER_PROTOTYPES, GAIN_PROTOTYPES, GLOBAL_SHAPE_PROTOTYPES,
    OVERLAP_PROTOTYPES, PROTOTYPES, SURFACE_PROTOTYPES,
    TONE_FIT_LINEAR_GAIN_PROTOTYPES, TONE_FIT_PROTOTYPES, UNIFIED_CHROMA_STAGES,
    WARP_QUADRATIC_SCALE_PROTOTYPES,
)

WHITE = cone_reference.WHITE
WHITE_NAMES = ("D65", "D60", "ACES", "D50", "D55", "D75", "DCI", "E")
PEAKS = (500, 1000, 2000, 4000)


def linear_settings(controls):
    index = controls.get("srcWhite", 8)
    xy = WHITES[WHITE_NAMES[index]] if index < 8 else (
        controls.get("srcX", WHITES["D65"][0]), controls.get("srcY", WHITES["D65"][1]))
    return LinearSettings(exposure=controls.get("globalExposure", 0), source_xy=xy,
                          balance=(controls.get("le", 0), controls.get("be", 0)),
                          spread=(controls.get("ls", 0), controls.get("bs", 0)),
                          heading=(controls.get("la", 0), controls.get("ba", 0)))


def tone_settings(controls):
    defaults = ToneSettings()
    nits = tuple(controls.get("input" + name, default) for name, default in
                 zip(("Black", "Shadows", "Midtones", "White", "Highlights"), defaults.input_nits))
    return ToneSettings(input_nits=nits, peak_nits=PEAKS[controls.get("peakNits", 1)],
                        fit=controls.get("remapFit", 0))


def overlap_settings(stage, controls):
    distance = np.abs(np.subtract.outer(np.arange(4), np.arange(4)))
    if stage == "jc_adjacent_overlap":
        weights = np.maximum(0., 1. - distance / 2.) ** 2
    else:
        weights = np.exp2(-(distance ** 2))
    weights /= weights.sum(axis=1, keepdims=True)
    blended = dict(controls)
    c_field = "CGain" if stage in GAIN_PROTOTYPES else "CContrast"
    for field in ("JContrast", c_field):
        names = [f"tone{row}{field}" for row in "SMWH"]
        blended.update(zip(names, weights @ [controls.get(name, 0.) for name in names]))
    return blended


def apply_tone_fit(stage, wire, tone, controls):
    compression = float(tone.nits_to_j(controls.get("blackCompression", 0.)))
    tone_active = tone.active or compression != 0.
    invert = controls.get("direction", 0)

    def compress(value):
        if compression == 0.:
            return value
        return value * (value + compression) / (value + 2. * compression)

    source = compress(tone.source)
    knots = source / source[-1]
    dx, dy = np.diff(knots), np.diff(tone.target)
    slope = min(dy / dx)
    residual = dy - slope * dx
    spans = tuple(zip(knots, knots[1:]))

    def remap(height):
        position = compress(height / 100.) / source[-1]
        transitions = np.stack([normalized_kernel(position, left, right, tone.width)
                                for left, right in spans], axis=-1)
        return 100. * (slope * position + transitions @ residual)

    point = cone_reference.enter(wire)
    ja, ab = point.ja, point.q[:, 1:]

    # The limit of remap(J)/J defines the J-only gain on the chromatic J=0 axis.
    width = float(tone.width)
    sigmoid = np.exp(-knots / width)
    sigmoid /= 1. + sigmoid
    integrals = np.array([kernel(1., left, right, width) for left, right in spans])
    transition_slopes = -np.diff(sigmoid) / integrals
    origin_gain = (slope + transition_slopes @ residual) / source[-1]
    if compression > 0.:
        origin_gain *= .5

    unified = stage in UNIFIED_CHROMA_STAGES
    influence = 1. if unified else controls.get("hkInfluence", 1.)

    def tone_ray(scale, ja, hk_chroma):
        if not tone_active:
            return scale
        hs = ja * scale
        if influence == 0. or np.all(hk_chroma == 0.):
            return np.divide(remap(hs), ja, out=scale * np.full_like(ja, origin_gain), where=ja > 0.)
        h = np.hypot(hs, np.sqrt(hk_chroma * scale))
        mapped = remap(h)
        denominator = np.hypot(hk_chroma * scale, 2. * hs * mapped) + hk_chroma * scale
        hk_gain = np.divide(scale * 2. * mapped ** 2, denominator,
                            out=scale * np.full_like(ja, origin_gain), where=denominator > 0.)
        if influence == 1.:
            return hk_gain
        j_gain = np.divide(remap(hs), ja, out=scale * np.full_like(ja, origin_gain), where=ja > 0.)
        return (1. - influence) * j_gain + influence * hk_gain

    def map_chroma(height, chroma):
        if unified:
            return jc_global_shape.unified_chroma_map(height, chroma, controls)
        return jc_global_shape.chroma_map(height, chroma, controls, linear_gain=stage in TONE_FIT_LINEAR_GAIN_PROTOTYPES)

    def tone_gain(height, chroma):
        output_hk_chroma = 66. * chroma
        if not invert:
            return tone_ray(np.ones_like(height), height, output_hk_chroma)
        low, high = np.zeros_like(height), np.ones_like(height)
        for _ in range(64):
            mapped = tone_ray(high, height, output_hk_chroma)
            done = mapped >= 1.
            if np.all(done):
                break
            high = np.where(done, high, high * 2.)
        for _ in range(80):
            middle = (low + high) / 2.
            below = tone_ray(middle, height, output_hk_chroma) < 1.
            low, high = np.where(below, middle, low), np.where(below, high, middle)
        return (low + high) / 2.

    def chroma_gain(height, chroma):
        if not invert:
            adjusted = map_chroma(height, chroma)
            return np.divide(adjusted, chroma, out=np.ones_like(chroma), where=chroma > 0.)
        low, high = np.zeros_like(chroma), np.maximum(chroma, 1.)
        for _ in range(64):
            mapped = map_chroma(height, high)
            done = mapped >= chroma
            if np.all(done):
                break
            high = np.where(done, high, high * 2.)
        for _ in range(80):
            middle = (low + high) / 2.
            below = map_chroma(height, middle) < chroma
            low, high = np.where(below, middle, low), np.where(below, high, middle)
        source_chroma = (low + high) / 2.
        return np.divide(source_chroma, chroma, out=np.ones_like(chroma), where=chroma > 0.)

    height = abs(ja)
    chroma = np.hypot(ab[:, 0], ab[:, 1])
    if unified != bool(invert):
        gain = tone_gain(height, chroma)
        c_gain = chroma_gain(height * gain, chroma * gain)
    else:
        c_gain = chroma_gain(height, chroma)
        gain = tone_gain(height, chroma * c_gain)
    mapped_ab = ab * (c_gain * gain)[:, None]
    return cone_reference.pack(ja * gain, mapped_ab[:, 0], mapped_ab[:, 1])


def apply(stage, values, controls):
    """Evaluate one node using only its own input for all selectors and repair."""
    values = np.asarray(values, dtype=np.float64)
    if stage == "linear":
        return values @ linear_matrix(linear_settings(controls), WHITE).T
    if stage == "input":
        return cone_reference.from_xyz(values)
    if stage == "output":
        defaults = OutputCompressionSettings()
        compression = OutputCompressionSettings(
            enabled=bool(controls.get("saturationCompression", defaults.enabled)),
            knee=controls.get("saturationKnee", defaults.knee),
            ceiling=controls.get("saturationCeiling", defaults.ceiling),
        )
        return cone_reference.output(values, compression)
    if stage in GLOBAL_SHAPE_PROTOTYPES:
        return jc_global_shape.apply(values, controls)
    if stage in OVERLAP_PROTOTYPES:
        controls = overlap_settings(stage, controls)
        stage = "jc"
    tone = Tone(tone_settings(controls))
    if stage in (*TONE_FIT_PROTOTYPES, *TONE_FIT_LINEAR_GAIN_PROTOTYPES, *UNIFIED_CHROMA_STAGES):
        return apply_tone_fit(stage, values, tone, controls)
    if stage in GAIN_PROTOTYPES:
        return jc_gain.apply(stage, values, tone, overlap_settings(stage, controls))
    if stage in ("jc", "warp") or stage in ANCHOR_CENTER_PROTOTYPES or stage in WARP_QUADRATIC_SCALE_PROTOTYPES:
        if controls.get("direction", 0):
            raise ValueError("The independent Stage 3 reference evaluates the forward direction")
        if stage == "jc_anchor_centers":
            controls = overlap_settings("jc_broad_overlap", controls)
            return cone_color.jc(values, tone, controls, anchor_centers=True)
        if stage == "jc":
            return cone_color.jc(values, tone, controls)
        return cone_color.warp(values, tone, controls, quadratic_scale=stage in WARP_QUADRATIC_SCALE_PROTOTYPES)
    if stage == "tone":
        if not tone.active:
            return values.copy()
        result = tone.apply(cone_reference.enter(values))
        return cone_reference.pack(result.ja, result.q[..., 1], result.q[..., 2])
    appearance = encode(values, WHITE)
    if stage in PROTOTYPES:
        result = jc_prototype.apply(stage, appearance, tone, controls)
    elif stage in SURFACE_PROTOTYPES:
        result = jc_surface.apply(appearance, tone, controls)
    else:
        raise ValueError(f"Unknown stage {stage}")
    graded = values.copy()
    if np.any(result.changed):
        graded[result.changed] = decode(result.q[result.changed], result.energy[result.changed], WHITE)
    return graded


def tolerance(expected):
    """Per-pixel peak-relative tolerance for float32 output in linear XYZ."""
    return np.maximum(.001 * np.max(abs(expected), axis=-1), 1e-7)
