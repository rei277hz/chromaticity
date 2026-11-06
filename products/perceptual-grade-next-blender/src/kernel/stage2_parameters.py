"""Immutable data for one complete Linear/Tone parameter image.

The fixed layout includes both the Tone endpoint jets and every changing
scalar used by a Stage 2 graph. Preparing it never touches Blender or grants
permission to publish it to a native reader.
"""

from dataclasses import dataclass
import hashlib
import math

import numpy as np

from .layouts import TONE_CELLS
from .prepare import PreparedGrade
from .tables import TEXTURE_WIDTH


PARAMETER_SCHEMA = 1
PARAMETER_SHAPE = (1, TEXTURE_WIDTH, 4)
PARAMETER_CONTENT_SIGNATURE = "_perceptual_grade_parameter_content_signature"
TONE_JET_COUNT = TONE_CELLS + 1
MATRIX_RED_SLOT = TONE_JET_COUNT
MATRIX_BLUE_SLOT = MATRIX_RED_SLOT + 1
MATRIX_NEUTRAL_SLOT = MATRIX_BLUE_SLOT + 1
TONE_SCALARS_SLOT = MATRIX_NEUTRAL_SLOT + 1
TONE_DOMAIN_SLOT = TONE_SCALARS_SLOT + 1


@dataclass(frozen=True)
class PreparedParameters:
    """An owned snapshot whose float32 storage cannot be made writable."""

    pixels: np.ndarray
    schema: int = PARAMETER_SCHEMA

    def __post_init__(self):
        if type(self.schema) is not int or self.schema != PARAMETER_SCHEMA:
            raise ValueError("Unsupported Stage 2 parameter schema")
        data = np.asarray(self.pixels)
        if data.shape != PARAMETER_SHAPE or data.dtype != np.float32:
            raise ValueError("Stage 2 parameters require a 1 by 512 RGBA32F image")
        if not np.isfinite(data).all():
            raise ValueError("Stage 2 parameters contain nonfinite values")
        if (not np.all(data[0, :TONE_SCALARS_SLOT, 3] == 1.)
                or not np.all(data[0, TONE_SCALARS_SLOT + 1:, 3] == 1.)):
            raise ValueError("Stage 2 parameter alpha lane must be one")
        if (data[0, TONE_SCALARS_SLOT, 0] < 0
                or data[0, TONE_SCALARS_SLOT, 1] <= 0
                or data[0, TONE_SCALARS_SLOT, 2] <= 0
                or data[0, TONE_SCALARS_SLOT, 3] <= 0
                or data[0, TONE_DOMAIN_SLOT, 0] <= 0):
            raise ValueError("Stage 2 Tone parameters are outside their valid domain")
        if (np.any(data[0, TONE_DOMAIN_SLOT, 1:3] != 0.)
                or np.any(data[0, TONE_DOMAIN_SLOT + 1:, :3] != 0.)):
            raise ValueError("Stage 2 parameter reserved channels must be zero")
        # An ndarray with writeable=False can otherwise be made writable again
        # when it owns its allocation. Immutable bytes also isolate the caller.
        owned = np.frombuffer(data.tobytes(), dtype=np.float32).reshape(PARAMETER_SHAPE)
        object.__setattr__(self, "pixels", owned)


def parameter_content_signature(pixels) -> str:
    """Identify the exact RGBA32F bytes stored in a parameter bank."""
    data = np.ascontiguousarray(pixels, dtype=np.float32)
    if data.shape != PARAMETER_SHAPE:
        raise ValueError("Stage 2 content signatures require a 1 by 512 RGBA32F image")
    return hashlib.sha256(data.tobytes()).hexdigest()


def parameter_image_matches(image, content_signature=None) -> bool:
    """Check a packed helper against its exact stored RGBA32F content receipt."""
    try:
        if (image.as_pointer() == 0 or image.is_dirty or image.packed_file is None
                or (content_signature is None
                    and image.get(PARAMETER_CONTENT_SIGNATURE) is None)):
            return False
        pixels = np.empty(PARAMETER_SHAPE, dtype=np.float32)
        image.pixels.foreach_get(pixels.ravel())
        actual = parameter_content_signature(pixels)
        expected = (image.get(PARAMETER_CONTENT_SIGNATURE)
                    if content_signature is None else content_signature)
        return actual == expected
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return False


def prepare_parameters(prepared: PreparedGrade) -> PreparedParameters:
    """Pack the complete snapshot without changing its numerical semantics."""
    if not isinstance(prepared, PreparedGrade):
        raise TypeError("Stage 2 parameters require a PreparedGrade")
    if prepared.color.active:
        raise ValueError("Stage 2 parameters do not support Color adjustments")
    table = prepared.table
    if (table is None or table.cells != TONE_CELLS
            or table.pixels.shape != PARAMETER_SHAPE
            or table.jets.shape != (TONE_JET_COUNT, 3)
            or table.jets.dtype != np.float32):
        raise ValueError("Stage 2 parameters require the complete 256-cell Tone table")
    if (not np.isfinite(table.jets).all()
            or not np.array_equal(table.pixels[0, :TONE_JET_COUNT, :3], table.jets)):
        raise ValueError("Stage 2 Tone pixels and endpoint jets disagree")
    matrix = np.asarray(prepared.linear_to_cones)
    if matrix.shape != (3, 3) or not np.isfinite(matrix).all():
        raise ValueError("Stage 2 parameters require a finite 3 by 3 cone matrix")

    pixels = np.zeros(PARAMETER_SHAPE, dtype=np.float32)
    pixels[..., 3] = 1.
    try:
        with np.errstate(over="raise", invalid="raise"):
            pixels[0, :TONE_JET_COUNT, :3] = table.jets
            pixels[0, MATRIX_RED_SLOT, :3] = matrix[:, 0]
            pixels[0, MATRIX_BLUE_SLOT, :3] = matrix[:, 2]
            # Match Graph.matrix's neutral-preserving arithmetic exactly.
            pixels[0, MATRIX_NEUTRAL_SLOT, :3] = tuple(
                math.fsum(float(value) for value in row) for row in matrix
            )
            tone = prepared.tone
            pixels[0, TONE_SCALARS_SLOT] = tone.black, tone.span, tone.slope, tone.high
            pixels[0, TONE_DOMAIN_SLOT, 0] = table.domain
    except (FloatingPointError, OverflowError) as error:
        raise ValueError("Stage 2 parameters are not representable as float32") from error
    return PreparedParameters(pixels)
