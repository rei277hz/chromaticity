"""Portable Stack LUT preparation and lookup for the fixed Next recipe."""

from dataclasses import dataclass
from functools import lru_cache
import hashlib
import math

import numpy as np

from .._shared import linear as color_linear


SCHEMA = 1
FINAL_SIZE = 65
PREVIEW_SIZE = 33
STRIDE = (FINAL_SIZE - 1) // (PREVIEW_SIZE - 1)
MINIMUM = 0.0
MAXIMUM = 1024.0
KAPPA = 0.01
LOG_RANGE = math.log1p(MAXIMUM / KAPPA)
LUT_SPACE = "ACEScg"


def _as_matrix(value, name):
    matrix = np.asarray(value, dtype=np.float64)
    if matrix.shape != (3, 3) or not np.isfinite(matrix).all():
        raise ValueError(f"{name} must be a finite 3 by 3 matrix")
    return tuple(tuple(float(x) for x in row) for row in matrix)


@dataclass(frozen=True)
class StackRecipe:
    """Identity of one ordered Stack core and its endpoint adapters."""

    working_space: str
    directions: tuple[str, ...]
    input_matrix: tuple[tuple[float, ...], ...]
    output_matrix: tuple[tuple[float, ...], ...]
    model_key: str
    schema: int = SCHEMA

    def __post_init__(self):
        if self.working_space not in color_linear.SPACES:
            raise ValueError(f"Unsupported working RGB space: {self.working_space}")
        directions = tuple(getattr(direction, "value", direction) for direction in self.directions)
        if any(direction not in ("FORWARD", "INVERSE") for direction in directions):
            raise ValueError("Stack directions must be FORWARD or INVERSE")
        if type(self.schema) is not int or self.schema != SCHEMA:
            raise ValueError("Unsupported Stack LUT schema")
        if not isinstance(self.model_key, str) or not self.model_key:
            raise ValueError("model_key must identify the prepared Stack recipe")
        object.__setattr__(self, "directions", directions)
        object.__setattr__(self, "input_matrix", _as_matrix(self.input_matrix, "input_matrix"))
        object.__setattr__(self, "output_matrix", _as_matrix(self.output_matrix, "output_matrix"))

    @property
    def digest(self):
        recipe = (
            self.schema,
            self.working_space,
            self.directions,
            self.input_matrix,
            self.output_matrix,
            self.model_key,
            LUT_SPACE,
            MINIMUM,
            MAXIMUM,
            KAPPA,
            "log1p-linear-rgb-tetrahedral",
            FINAL_SIZE,
            PREVIEW_SIZE,
        )
        return hashlib.sha256(repr(recipe).encode("utf8")).hexdigest()


def make_recipe(*, working_space, directions, input_matrix, output_matrix, model_key):
    """Create the immutable recipe identity stored with preview/final payloads."""
    key = model_key if isinstance(model_key, str) else repr(model_key)
    return StackRecipe(
        working_space=working_space,
        directions=tuple(directions),
        input_matrix=input_matrix,
        output_matrix=output_matrix,
        model_key=key,
    )


@lru_cache(maxsize=1)
def axis():
    """The 65-point physical axis; its even vertices define the preview axis."""
    values = KAPPA * np.expm1(np.linspace(0.0, 1.0, FINAL_SIZE) * LOG_RANGE)
    values[0], values[-1] = MINIMUM, MAXIMUM
    values.flags.writeable = False
    return values


def encode(rgb):
    """Address nonnegative linear RGB on the fixed log1p LUT grid."""
    values = np.asarray(rgb, dtype=np.float64)
    if values.shape[-1:] != (3,) or not np.isfinite(values).all():
        raise ValueError("LUT addresses require finite RGB triples")
    if np.any(values < 0.0):
        raise ValueError("LUT addresses must be nonnegative")
    return np.log1p(values / KAPPA) / LOG_RANGE


def decode(address):
    """Decode normalized addresses into physical linear RGB coordinates."""
    value = np.asarray(address, dtype=np.float64)
    if not np.isfinite(value).all():
        raise ValueError("LUT coordinates must be finite")
    return KAPPA * np.expm1(value * LOG_RANGE)


@lru_cache(maxsize=2)
def lattice_axis(size):
    if size == FINAL_SIZE:
        return axis()
    if size == PREVIEW_SIZE:
        return axis()[::STRIDE]
    raise ValueError("Only the 33^3 preview and 65^3 final grids are supported")


@lru_cache(maxsize=2)
def _grid(size):
    values = lattice_axis(size)
    result = np.stack(np.meshgrid(values, values, values, indexing="ij"), axis=-1)
    result.flags.writeable = False
    return result


def lattice(size=FINAL_SIZE):
    """Return the canonical ``(size, size, size, 3)`` physical input grid."""
    return _grid(size)


def refinement_indices():
    """Flat 65^3 rows absent from the 33^3 even-coordinate preview."""
    indices = np.arange(FINAL_SIZE**3).reshape(FINAL_SIZE, FINAL_SIZE, FINAL_SIZE)
    shared = indices[::STRIDE, ::STRIDE, ::STRIDE].ravel()
    mask = np.ones(FINAL_SIZE**3, dtype=bool)
    mask[shared] = False
    remaining = np.flatnonzero(mask)
    shared.flags.writeable = False
    remaining.flags.writeable = False
    return shared, remaining


def _evaluate(evaluator, points, *, block_size, checkpoint):
    if not callable(evaluator):
        raise TypeError("evaluator must be callable")
    if type(block_size) is not int or block_size <= 0:
        raise ValueError("block_size must be a positive integer")
    source = np.asarray(points, dtype=np.float64).reshape(-1, 3)
    result = np.empty((len(source), 3), dtype=np.float32)
    for start in range(0, len(source), block_size):
        if checkpoint is not None:
            checkpoint()
        stop = min(start + block_size, len(source))
        values = np.asarray(evaluator(source[start:stop]), dtype=np.float64)
        if values.shape != (stop - start, 3) or not np.isfinite(values).all():
            raise ValueError("Stack evaluator must return finite RGB triples per input")
        result[start:stop] = values
    return result


@dataclass(frozen=True)
class PreviewLattice:
    """Interactive 33^3 Stack samples, tied to one immutable recipe."""

    values: np.ndarray
    recipe: StackRecipe

    def __post_init__(self):
        if not isinstance(self.recipe, StackRecipe):
            raise TypeError("preview requires a StackRecipe")
        values = np.array(self.values, dtype=np.float32, copy=True)
        if values.shape != (PREVIEW_SIZE, PREVIEW_SIZE, PREVIEW_SIZE, 3):
            raise ValueError("Stack preview must be 33^3 RGB samples")
        if not np.isfinite(values).all():
            raise ValueError("Stack preview must contain finite values")
        values.flags.writeable = False
        object.__setattr__(self, "values", values)

    @property
    def size(self):
        return PREVIEW_SIZE

    @property
    def recipe_digest(self):
        return self.recipe.digest


@dataclass(frozen=True)
class FinalLattice:
    """Accepted-quality 65^3 Stack samples with exact preview reuse."""

    values: np.ndarray
    recipe: StackRecipe
    preview: PreviewLattice

    def __post_init__(self):
        if not isinstance(self.recipe, StackRecipe):
            raise TypeError("final lattice requires a StackRecipe")
        if not isinstance(self.preview, PreviewLattice) or self.preview.recipe != self.recipe:
            raise ValueError("Stack final requires its matching immutable preview")
        values = np.array(self.values, dtype=np.float32, copy=True)
        if values.shape != (FINAL_SIZE, FINAL_SIZE, FINAL_SIZE, 3):
            raise ValueError("Stack final must be 65^3 RGB samples")
        if not np.isfinite(values).all():
            raise ValueError("Stack final must contain finite values")
        if not np.array_equal(values[::STRIDE, ::STRIDE, ::STRIDE], self.preview.values):
            raise ValueError("Stack final must exactly reuse all preview vertices")
        values.flags.writeable = False
        object.__setattr__(self, "values", values)

    @property
    def preview_digest(self):
        return self.preview.recipe_digest

    @property
    def reused_preview_vertices(self):
        return True

    @property
    def size(self):
        return FINAL_SIZE

    @property
    def final_ready(self):
        return True

    @property
    def recipe_digest(self):
        return self.recipe.digest


def sample_preview(evaluator, recipe, *, block_size=4096, checkpoint=None):
    """Evaluate the 33^3 interactive preview on the final lattice's even rows."""
    if not isinstance(recipe, StackRecipe):
        raise TypeError("recipe must be a StackRecipe")
    points = lattice(PREVIEW_SIZE)
    values = _evaluate(evaluator, points, block_size=block_size, checkpoint=checkpoint)
    return PreviewLattice(values.reshape(PREVIEW_SIZE, PREVIEW_SIZE, PREVIEW_SIZE, 3), recipe)


def refine_final(preview, evaluator, recipe, *, block_size=4096, checkpoint=None):
    """Refine a matching preview without reevaluating any shared vertex."""
    if not isinstance(preview, PreviewLattice):
        raise TypeError("refinement requires a PreviewLattice")
    if not isinstance(recipe, StackRecipe) or preview.recipe != recipe:
        raise ValueError("preview and final must use the same StackRecipe")
    final = np.empty((FINAL_SIZE, FINAL_SIZE, FINAL_SIZE, 3), dtype=np.float32)
    final[::STRIDE, ::STRIDE, ::STRIDE] = preview.values
    shared, remaining = refinement_indices()
    if len(shared) != PREVIEW_SIZE**3:
        raise AssertionError("preview refinement map has an invalid shared-row count")
    points = lattice(FINAL_SIZE).reshape(-1, 3)[remaining]
    refined = _evaluate(evaluator, points, block_size=block_size, checkpoint=checkpoint)
    final.reshape(-1, 3)[remaining] = refined
    return FinalLattice(final, recipe, preview)


@lru_cache(maxsize=8)
def basis(working_space):
    """Return working RGB to LUT ACEScg and its inverse, including Bradford."""
    cm = color_linear
    if working_space not in cm.SPACES:
        raise ValueError(f"Unsupported working RGB space: {working_space}")
    source_white = cm.SPACES[working_space][1]
    lut_white = cm.SPACES[LUT_SPACE][1]
    to_lut = (
        np.asarray(cm.xyz_to_rgb(LUT_SPACE), dtype=np.float64)
        @ np.asarray(cm.bradford(source_white, lut_white), dtype=np.float64)
        @ np.asarray(cm.rgb_to_xyz(working_space), dtype=np.float64)
    )
    from_lut = np.linalg.inv(to_lut)
    to_lut.flags.writeable = False
    from_lut.flags.writeable = False
    return to_lut, from_lut


def input_repair(rgb, weights=None):
    """Apply the Stack AP1 boundary repair; values already inside the cube pass."""
    cm = color_linear
    values = np.asarray(rgb, dtype=np.float64)
    if values.shape[-1:] != (3,) or not np.isfinite(values).all():
        raise ValueError("Stack LUT input must contain finite RGB triples")
    if weights is None:
        weights = np.asarray(cm.rgb_to_xyz(LUT_SPACE), dtype=np.float64)[1]
    weights = np.asarray(weights, dtype=np.float64)
    if weights.shape != (3,) or not np.isfinite(weights).all() or np.any(weights <= 0.0):
        raise ValueError("AP1 luminance weights must be positive")
    result = values.copy()
    active = (values.min(axis=-1) < MINIMUM) | (values.max(axis=-1) > MAXIMUM)
    if not np.any(active):
        return result
    outside = values[active]
    amplitude = np.max(np.abs(outside), axis=-1)
    unit = outside / amplitude[:, None]
    luminance = np.maximum(0.0, unit @ weights)
    offset = np.maximum(0.0, -unit.min(axis=-1))
    denominator = luminance + offset
    factor = np.divide(luminance, denominator, out=np.zeros_like(luminance), where=denominator > 0.0)
    repaired = np.where(
        (offset > 0.0)[:, None],
        (unit + offset[:, None]) * factor[:, None],
        unit,
    )
    peak = repaired.max(axis=-1)
    bound = np.nextafter(MAXIMUM, -np.inf)
    scale = np.minimum(
        amplitude,
        np.divide(bound, peak, out=np.zeros_like(peak), where=peak > 0.0),
    )
    result[active] = repaired * np.maximum(0.0, scale)[:, None]
    return result


def _cell_coordinates(rgb, size):
    repaired = input_repair(rgb)
    positions = (size - 1) * encode(np.clip(repaired, MINIMUM, MAXIMUM))
    cells = size - 1
    lower = np.clip(np.floor(positions).astype(np.int64), 0, cells - 1)
    coordinates = lattice_axis(size)
    lo = coordinates[lower]
    hi = coordinates[lower + 1]
    fractions = np.clip((repaired - lo) / (hi - lo), 0.0, 1.0)
    return repaired, lower, fractions


def tetrahedral(table, rgb):
    """Interpolate a fixed-grid table with four vertices and physical fractions."""
    values = np.asarray(table, dtype=np.float32)
    if values.ndim != 4 or values.shape[-1] != 3 or len(set(values.shape[:3])) != 1:
        raise ValueError("LUT table must have shape (size, size, size, 3)")
    size = values.shape[0]
    lattice_axis(size)
    source = np.asarray(rgb, dtype=np.float64)
    if source.shape[-1:] != (3,) or not np.isfinite(source).all():
        raise ValueError("LUT lookup requires finite RGB triples")
    shape = source.shape
    repaired, cell, fractions = _cell_coordinates(source.reshape(-1, 3), size)
    order = np.argsort(-fractions, axis=-1, kind="stable")
    first = np.eye(3, dtype=np.int64)[order[:, 0]]
    second = np.eye(3, dtype=np.int64)[order[:, 1]]
    ordered = np.take_along_axis(fractions, order, axis=-1)
    corners = (cell, cell + first, cell + first + second, cell + 1)
    vertices = [values[c[:, 0], c[:, 1], c[:, 2]] for c in corners]
    result = vertices[0].astype(np.float64, copy=True)
    for start, stop, fraction in zip(vertices, vertices[1:], ordered.T):
        result += (stop.astype(np.float64) - start.astype(np.float64)) * fraction[:, None]
    return result.reshape(shape)


class StackLUT:
    """Bake-capable lookup object; construction requires a 65^3 final lattice."""

    def __init__(self, final):
        if not isinstance(final, FinalLattice) or not final.final_ready:
            raise TypeError("Stack Bake requires an accepted 65^3 FinalLattice")
        self.final = final
        self.values = final.values
        self.recipe = final.recipe
        self.to_lut, self.from_lut = basis(self.recipe.working_space)
        self.input_matrix = np.asarray(self.recipe.input_matrix, dtype=np.float64)
        self.output_matrix = np.asarray(self.recipe.output_matrix, dtype=np.float64)

    @property
    def size(self):
        return FINAL_SIZE

    @property
    def recipe_digest(self):
        return self.recipe.digest

    def apply(self, rgb):
        """Sample the accepted LUT with its shaper, repair, and endpoint matrices."""
        source = np.asarray(rgb, dtype=np.float64)
        if source.shape[-1:] != (3,) or not np.isfinite(source).all():
            raise ValueError("Stack LUT input must contain finite RGB triples")
        native = (source @ self.to_lut.T) @ self.input_matrix.T
        native = input_repair(native)
        looked_up = tetrahedral(self.values, native)
        return (looked_up @ self.output_matrix.T) @ self.from_lut.T


def pack_rgbe(rgb):
    """Pack signed float32 RGB vertices as exact shared-exponent RGBA values."""
    values = np.asarray(rgb, dtype=np.float32)
    if values.shape[-1:] != (3,) or not np.isfinite(values).all():
        raise ValueError("RGBE packing requires finite RGB triples")
    magnitude = np.max(np.abs(values), axis=-1)
    _, exponent = np.frexp(magnitude)
    result = np.empty((*values.shape[:-1], 4), dtype=np.float32)
    np.ldexp(values, -exponent[..., None], out=result[..., :3])
    result[..., 3] = exponent
    return result


def unpack_rgbe(rgba):
    """Recover float32 RGB vertices before interpolation."""
    values = np.asarray(rgba, dtype=np.float32)
    if values.shape[-1:] != (4,) or not np.isfinite(values).all():
        raise ValueError("RGBE unpacking requires finite RGBA tuples")
    return np.ldexp(values[..., :3], values[..., 3].astype(np.int32)[..., None])
