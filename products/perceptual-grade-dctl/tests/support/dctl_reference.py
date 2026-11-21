"""Float64 reference stages at the DCTL XYZ and cone-response boundaries."""
import numpy as np

from color_tools.perceptual_grade_reference.appearance import encode, decode
from color_tools.perceptual_grade_reference.grading import Tone, ToneSettings
from color_tools.perceptual_grade_reference.model import LinearSettings, WHITES, linear_matrix

from . import cone_color, cone_reference, jc_prototype, jc_surface
from .dctl import PROTOTYPES, SURFACE_PROTOTYPES

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


def apply(stage, values, controls):
    """Evaluate one node using only its own input for all selectors and repair."""
    values = np.asarray(values, dtype=np.float64)
    if stage == "linear":
        return values @ linear_matrix(linear_settings(controls), WHITE).T
    if stage == "input":
        return cone_reference.from_xyz(values)
    if stage == "output":
        return cone_reference.output(values)
    tone = Tone(tone_settings(controls))
    if stage in ("jc", "warp"):
        if controls.get("direction", 0):
            raise ValueError("The independent Stage 3 reference evaluates the forward direction")
        return (cone_color.jc if stage == "jc" else cone_color.warp)(values, tone, controls)
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
