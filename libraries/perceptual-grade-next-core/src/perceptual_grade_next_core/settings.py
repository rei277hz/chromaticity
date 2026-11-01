"""Immutable, host-independent authored settings for Next grading."""

from dataclasses import dataclass, field
from enum import Enum
import math


TONE_FIT_RANGE = (-2.0, 2.0)
COLOR_FIT_RANGE = (-2.0, 6.0)
SUPPORTED_WHITE = "D65"
REFERENCE_NITS = 203.0
RGB_SPACES = ("Linear Rec.709", "Linear Rec.2020", "ACEScg")
NEUTRAL_4 = ((0.0, 0.0, 0.0, 0.0),) * 4
NEUTRAL_6 = ((0.0,) * 6,) * 4
NEUTRAL_2 = ((0.0, 0.0),) * 4


class Direction(str, Enum):
    FORWARD = "FORWARD"
    INVERSE = "INVERSE"


def _finite(value, name):
    try:
        finite = math.isfinite(float(value))
    except (TypeError, ValueError, OverflowError):
        finite = False
    if not finite:
        raise ValueError(f"{name} must be finite")
    return float(value)


def _matrix(value, rows, columns, name):
    try:
        result = tuple(tuple(_finite(x, name) for x in row) for row in value)
    except TypeError as exc:
        raise ValueError(f"{name} must have shape {rows} by {columns}") from exc
    if len(result) != rows or any(len(row) != columns for row in result):
        raise ValueError(f"{name} must have shape {rows} by {columns}")
    return result


@dataclass(frozen=True)
class LinearSettings:
    exposure: float = 0.0
    source_white_xy: tuple[float, float] = (0.3127, 0.3290)
    balance: tuple[float, float] = (0.0, 0.0)
    spread: tuple[float, float] = (0.0, 0.0)
    heading: tuple[float, float] = (0.0, 0.0)
    matrix: tuple[tuple[float, float, float], ...] | None = None

    def __post_init__(self):
        object.__setattr__(self, "exposure", _finite(self.exposure, "exposure"))
        xy = tuple(_finite(v, "source_white_xy") for v in self.source_white_xy)
        if len(xy) != 2 or not (0.0 <= xy[0] <= 0.9 and 0.0 < xy[1] <= 0.9):
            raise ValueError("source_white_xy must be a finite xy pair in the supported range")
        object.__setattr__(self, "source_white_xy", xy)
        for name in ("balance", "spread", "heading"):
            values = tuple(_finite(v, name) for v in getattr(self, name))
            if len(values) != 2:
                raise ValueError(f"{name} must contain two directional controls")
            object.__setattr__(self, name, values)
        if self.matrix is not None:
            object.__setattr__(self, "matrix", _matrix(self.matrix, 3, 3, "matrix"))


@dataclass(frozen=True)
class ToneSettings:
    input_nits: tuple[float, float, float, float, float] = (
        0.0,
        0.015507796089266005 * REFERENCE_NITS,
        0.18 * REFERENCE_NITS,
        REFERENCE_NITS,
        1000.0,
    )
    fit: float = 0.0
    reference_nits: float = REFERENCE_NITS
    peak_nits: float = 1000.0

    def __post_init__(self):
        values = tuple(_finite(v, "input_nits") for v in self.input_nits)
        if len(values) != 5 or any(v < 0 for v in values):
            raise ValueError("input_nits must contain five finite nonnegative values")
        object.__setattr__(self, "input_nits", values)
        fit = _finite(self.fit, "Tone Fit")
        if not TONE_FIT_RANGE[0] <= fit <= TONE_FIT_RANGE[1]:
            raise ValueError("Tone Fit must be within [-2, 2]")
        object.__setattr__(self, "fit", fit)
        reference = _finite(self.reference_nits, "reference_nits")
        if reference != REFERENCE_NITS:
            raise ValueError("Next grading context is fixed at 203 reference nits")
        object.__setattr__(self, "reference_nits", reference)
        peak = _finite(self.peak_nits, "peak_nits")
        if not 2 * REFERENCE_NITS <= peak <= 10000.0:
            raise ValueError("peak_nits must be within [406, 10000]")
        object.__setattr__(self, "peak_nits", peak)


@dataclass(frozen=True)
class WebSettings:
    hue_degrees: tuple = NEUTRAL_6
    log_chroma: tuple = NEUTRAL_6
    log_scale: tuple = NEUTRAL_6

    def __post_init__(self):
        for name in ("hue_degrees", "log_chroma", "log_scale"):
            object.__setattr__(self, name, _matrix(getattr(self, name), 4, 6, name))

    @property
    def active(self):
        return any(value != 0.0 for grid in (self.hue_degrees, self.log_chroma, self.log_scale)
                   for row in grid for value in row)


@dataclass(frozen=True)
class ColorSettings:
    lightness: tuple = NEUTRAL_4
    chroma: tuple = NEUTRAL_4
    adaptance: tuple = NEUTRAL_2
    lightness_fit: float = 0.0
    chroma_fit: float = 0.0
    global_gain: float = 0.0
    adaptance_half_saturation: float = 0.25
    web: WebSettings = field(default_factory=WebSettings)

    def __post_init__(self):
        object.__setattr__(self, "lightness", _matrix(self.lightness, 4, 4, "lightness"))
        object.__setattr__(self, "chroma", _matrix(self.chroma, 4, 4, "chroma"))
        object.__setattr__(self, "adaptance", _matrix(self.adaptance, 4, 2, "adaptance"))
        for name in ("lightness_fit", "chroma_fit"):
            fit = _finite(getattr(self, name), name)
            if not COLOR_FIT_RANGE[0] <= fit <= COLOR_FIT_RANGE[1]:
                raise ValueError(f"{name} must be within [-2, 6]")
            object.__setattr__(self, name, fit)
        object.__setattr__(self, "global_gain", _finite(self.global_gain, "global_gain"))
        half = _finite(self.adaptance_half_saturation, "adaptance_half_saturation")
        if not 0.05 <= half <= 1.0:
            raise ValueError("adaptance_half_saturation must be within [0.05, 1]")
        object.__setattr__(self, "adaptance_half_saturation", half)
        if not isinstance(self.web, WebSettings):
            if isinstance(self.web, dict):
                object.__setattr__(self, "web", WebSettings(**self.web))
            elif all(hasattr(self.web, name) for name in ("hue_degrees", "log_chroma", "log_scale")):
                object.__setattr__(self, "web", WebSettings(
                    hue_degrees=self.web.hue_degrees,
                    log_chroma=self.web.log_chroma,
                    log_scale=self.web.log_scale,
                ))
            else:
                raise ValueError("web must be WebSettings")


@dataclass(frozen=True)
class GradeSettings:
    linear: LinearSettings = field(default_factory=LinearSettings)
    tone: ToneSettings = field(default_factory=ToneSettings)
    color: ColorSettings = field(default_factory=ColorSettings)
    grading_white: str = SUPPORTED_WHITE
    working_space: str = "Linear Rec.709"

    def __post_init__(self):
        if self.grading_white != SUPPORTED_WHITE:
            raise ValueError("Next grading appearance context is fixed to D65")
        if self.working_space not in RGB_SPACES:
            raise ValueError(f"working_space must be one of {RGB_SPACES}")
        if not isinstance(self.linear, LinearSettings):
            raise ValueError("linear must be LinearSettings")
        if not isinstance(self.tone, ToneSettings):
            raise ValueError("tone must be ToneSettings")
        if not isinstance(self.color, ColorSettings):
            raise ValueError("color must be ColorSettings")


@dataclass(frozen=True)
class StackEntry:
    settings: GradeSettings = field(default_factory=GradeSettings)
    direction: Direction = Direction.FORWARD

    def __post_init__(self):
        if not isinstance(self.settings, GradeSettings):
            raise ValueError("settings must be GradeSettings")
        try:
            direction = Direction(self.direction)
        except ValueError as exc:
            raise ValueError("Stack direction must be FORWARD or INVERSE") from exc
        object.__setattr__(self, "direction", direction)


@dataclass(frozen=True)
class StackSettings:
    entries: tuple[StackEntry, ...] = ()

    def __post_init__(self):
        entries = tuple(self.entries)
        if any(not isinstance(entry, StackEntry) for entry in entries):
            raise ValueError("Stack entries must be StackEntry values")
        object.__setattr__(self, "entries", entries)
