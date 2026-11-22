"""Run each installed DCTL's transform in the float32 C++ host."""
from functools import cache
from importlib.resources import files
import subprocess

import numpy as np

from .dctl import (
    ANCHOR_CENTER_PROTOTYPES, GAIN_PROTOTYPES, GLOBAL_SHAPE_PROTOTYPES,
    OVERLAP_PROTOTYPES, PROTOTYPES, STAGES, SURFACE_PROTOTYPES, TONE_FIT_LINEAR_GAIN_PROTOTYPES,
    TONE_FIT_PROTOTYPES, TONE_FIT_UNIFIED_CHROMA_PROTOTYPES, WARP_QUADRATIC_SCALE_PROTOTYPES, controls, filename,
)

RESOURCES = files("tests.support")
STAGE_DIR = RESOURCES / "stages"
PROTOTYPE_DIR = RESOURCES / "prototypes"
SURFACE_DIR = RESOURCES / "surfaces"
OVERLAP_DIR = RESOURCES / "overlaps"
ANCHOR_CENTER_DIR = RESOURCES / "anchor_centers"
GAIN_DIR = RESOURCES / "gains"
GLOBAL_SHAPE_DIR = RESOURCES / "global_shape"
TONE_FIT_DIR = RESOURCES / "tone_fit"
TONE_FIT_LINEAR_GAIN_DIR = RESOURCES / "tone_fit_linear_gain"
TONE_FIT_UNIFIED_CHROMA_DIR = RESOURCES / "tone_fit_unified_chroma"
WARP_QUADRATIC_SCALE_DIR = RESOURCES / "warp_quadratic_scale"
SOURCE_DIRS = ({stage: STAGE_DIR for stage in STAGES}
               | {stage: PROTOTYPE_DIR for stage in PROTOTYPES}
               | {stage: SURFACE_DIR for stage in SURFACE_PROTOTYPES}
               | {stage: OVERLAP_DIR for stage in OVERLAP_PROTOTYPES}
               | {stage: ANCHOR_CENTER_DIR for stage in ANCHOR_CENTER_PROTOTYPES}
               | {stage: GAIN_DIR for stage in GAIN_PROTOTYPES}
               | {stage: GLOBAL_SHAPE_DIR for stage in GLOBAL_SHAPE_PROTOTYPES}
               | {stage: TONE_FIT_DIR for stage in TONE_FIT_PROTOTYPES}
               | {stage: TONE_FIT_LINEAR_GAIN_DIR for stage in TONE_FIT_LINEAR_GAIN_PROTOTYPES}
               | {stage: TONE_FIT_UNIFIED_CHROMA_DIR for stage in TONE_FIT_UNIFIED_CHROMA_PROTOTYPES}
               | {stage: WARP_QUADRATIC_SCALE_DIR for stage in WARP_QUADRATIC_SCALE_PROTOTYPES})


@cache
def source(stage, locale="en"):
    return (SOURCE_DIRS[stage] / filename(stage, locale)).read_text(encoding="utf-8")


@cache
def ui(stage):
    return controls(source(stage))


def run(stage, values, settings=None, *, x=0, y=10):
    values = np.asarray(values, dtype=np.float32).reshape(-1, 3)
    settings = settings or {}
    declarations = ui(stage)
    unknown = settings.keys() - {field["name"] for field in declarations}
    if unknown:
        raise ValueError(f"Unknown {stage} controls: {unknown}")
    fields = []
    for item in declarations:
        value = settings.get(item["name"], item["default"])
        if item["type"] == "DCTLUI_SLIDER_FLOAT":
            fields.append(format(value, ".17g"))
        else:
            if int(value) != value:
                raise ValueError(f"{item['name']} requires an integer")
            fields.append(str(int(value)))
    lines = [" ".join(fields)]
    for pixel in values:
        coordinates = " ".join(format(channel, ".9g") for channel in pixel)
        lines.append(f"{coordinates} 1920 1080 {x} {y}")
    return invoke(stage, lines, values.shape)


def chroma_curve(stage, chroma, ja, pivot, lift, gamma, gain, weights):
    controls = (*lift, *gamma, *gain, *weights, ja, pivot)
    lines = [" ".join(format(value, ".17g") for value in controls)]
    lines.extend(format(value, ".17g") for value in chroma)
    return invoke(stage + "_chroma", lines, (len(chroma), 2)).T


def surface_response(samples, amounts, center=.5, width=.5, peak=1):
    values = (*amounts, center, width, peak)
    lines = [" ".join(format(value, ".17g") for value in values)]
    lines.extend(" ".join(format(value, ".17g") for value in sample) for sample in samples)
    return invoke("surface_response", lines, (len(samples), 3)).T


def invoke(operation, lines, shape):
    result = subprocess.run([str(RESOURCES / "oracle"), operation],
                            input="\n".join(lines) + "\n", text=True,
                            capture_output=True, check=True)
    actual = np.fromstring(result.stdout, dtype=np.float32, sep=" ").reshape(-1, shape[1])
    if actual.shape != shape:
        raise ValueError(f"Host produced {len(actual)} rows for {shape[0]} inputs")
    return actual
