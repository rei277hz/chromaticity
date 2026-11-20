"""Float64 reference stages at the standalone DCTL XYZ boundary."""
import numpy as np

from color_tools.perceptual_grade_reference.appearance import encode, decode
from color_tools.perceptual_grade_reference.grading import Color, ColorSettings, Tone, ToneSettings
from color_tools.perceptual_grade_reference.model import LinearSettings, WHITES, linear_matrix, xyz_from_xy
from color_tools.perceptual_grade_reference.responses import State

WHITE = xyz_from_xy(WHITES["D65"])
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


def color_settings(controls):
    def coefficients(receiver):
        return tuple(tuple(controls.get(f"tone{tone}{driver}To{receiver}", 0)
                           for driver in ("Low", "High", "a", "b")) for tone in "SMWH")

    def web_field(family):
        return tuple(tuple(controls.get(f"web{family}{tone}{handle}", 0)
                           for handle in range(6)) for tone in range(4))

    return ColorSettings(
        lightness=coefficients("J"), chroma=coefficients("C"),
        global_gain=controls.get("globalChromaGain", 0),
        lightness_fit=controls.get("lightnessFit", 0), chroma_fit=controls.get("chromaFit", 0),
        adaptance=tuple(tuple(controls.get(f"tone{tone}Adaptance{axis}", 0)
                              for axis in "AB") for tone in "SMWH"),
        adaptance_half_saturation=controls.get("adaptanceHalfSaturation", .25),
        web=dict(log_chroma=web_field("chroma"), hue_degrees=web_field("hue"),
                 log_scale=web_field("scale")),
    )


def apply(stage, xyz, controls):
    """Evaluate one node using only its own input for all selectors and repair."""
    xyz = np.asarray(xyz, dtype=np.float64)
    if stage == "linear":
        return xyz @ linear_matrix(linear_settings(controls), WHITE).T
    tone = Tone(tone_settings(controls))
    appearance = encode(xyz, WHITE)
    if stage == "tone":
        if not tone.active:
            return xyz.copy()
        result = tone.apply(appearance)
        return decode(result.q, result.ja * abs(result.ja), WHITE)
    if stage not in ("jc", "warp"):
        raise ValueError(f"Unknown stage {stage}")
    color = Color(color_settings(controls), tone)
    if not color.active:
        return xyz.copy()
    source = State(appearance.q, appearance.ja * abs(appearance.ja))
    result = color.apply_state(source)
    return decode(result.q, result.energy, WHITE)


def tolerance(expected):
    """Per-pixel peak-relative tolerance for float32 output in linear XYZ."""
    return np.maximum(.001 * np.max(abs(expected), axis=-1), 1e-7)
