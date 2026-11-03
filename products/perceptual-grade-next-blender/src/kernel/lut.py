"""LUT metadata, host-side packaging, and tetrahedral Stage 1 lookup."""
from dataclasses import dataclass
import hashlib
import math

import numpy as np

from ..color_core import linear as color_linear


SIZE = 65
PREVIEW_SIZE = 33
CELLS = SIZE - 1
MINIMUM = 0.0
MAXIMUM = 1024.0
KAPPA = 0.01
LOG_RANGE = math.log1p(MAXIMUM / KAPPA)
ATLAS_WIDTH = 1024
ATLAS_HEIGHT = (4 * SIZE**3 + ATLAS_WIDTH - 1) // ATLAS_WIDTH
_SPACE = "ACEScg"


def basis(space="Linear Rec.709"):
    """Return matrices converting between scene RGB and the fixed ACEScg LUT."""
    if space not in color_linear.SPACES:
        raise ValueError(f"Unsupported scene RGB space: {space}")
    source_white = color_linear.SPACES[space][1]
    destination_white = color_linear.SPACES[_SPACE][1]
    to_lut = (np.asarray(color_linear.xyz_to_rgb(_SPACE), dtype=np.float64)
              @ np.asarray(color_linear.bradford(source_white, destination_white),
                            dtype=np.float64)
              @ np.asarray(color_linear.rgb_to_xyz(space), dtype=np.float64))
    return to_lut, np.linalg.inv(to_lut)


def axis(size=SIZE):
    """Nonnegative log1p-spaced ACEScg coordinates, including endpoints."""
    if not isinstance(size, int) or size < 2:
        raise ValueError("A LUT axis must contain at least two samples")
    values = KAPPA * np.expm1(np.linspace(0.0, LOG_RANGE, size, dtype=np.float64))
    values[0], values[-1] = MINIMUM, MAXIMUM
    values.flags.writeable = False
    return values


def atlas_height(size=SIZE):
    """Height of the four-plane atlas for one cube resolution."""
    if not isinstance(size, int) or size < 2:
        raise ValueError("A LUT atlas requires at least two samples per axis")
    return (4 * size**3 + ATLAS_WIDTH - 1) // ATLAS_WIDTH


def pack_rgbe(rgb):
    """Encode signed RGB coefficients with a shared exact binary exponent."""
    rgb = np.asarray(rgb, dtype=np.float32)
    magnitude = np.max(np.abs(rgb), axis=-1)
    _, exponent = np.frexp(magnitude)
    packed = np.zeros((*rgb.shape[:-1], 4), dtype=np.float32)
    np.ldexp(rgb, -exponent[..., None], out=packed[..., :3])
    packed[..., 3] = exponent
    return packed


def unpack_rgbe(rgba):
    rgba = np.asarray(rgba, dtype=np.float32)
    return np.ldexp(rgba[..., :3], rgba[..., 3].astype(np.int32)[..., None])


def _axis_socket(graph, value, size):
    cells = size - 1
    bounded = graph.clamp(value, MINIMUM, MAXIMUM)
    encoded = graph.div(
        graph.op("LOGARITHM", graph.add(1.0, graph.div(bounded, KAPPA)), math.e),
        LOG_RANGE,
    )
    position = graph.mul(cells, encoded)
    index = graph.minimum(cells - 1, graph.maximum(0.0, graph.op("FLOOR", position)))
    low = graph.mul(KAPPA, graph.sub(graph.op("EXPONENT", graph.mul(index, LOG_RANGE / cells)), 1.0))
    high_exp = graph.op("EXPONENT", graph.mul(graph.add(index, 1.0), LOG_RANGE / cells))
    high_value = graph.mul(KAPPA, graph.sub(high_exp, 1.0))
    high = graph.select(graph.lt(index, cells - 1), high_value, MAXIMUM)
    fraction = graph.div(graph.sub(value, low), graph.sub(high, low))
    return index, fraction


def append_lut_lookup(graph, cube, rgb):
    """Append one four-read tetrahedral lookup to a native Graph."""
    size = cube.size
    count = size**3
    channels = graph.split(rgb)
    coordinates = [_axis_socket(graph, channel, size) for channel in channels]
    low = [item[0] for item in coordinates]
    fractions = [item[1] for item in coordinates]
    r, g, b = fractions
    ge = lambda a, c: graph.sub(1.0, graph.lt(a, c))
    high_axis = (
        graph.mul(ge(r, g), ge(r, b)),
        graph.mul(graph.lt(r, g), ge(g, b)),
        graph.mul(graph.lt(r, b), graph.lt(g, b)),
    )
    low_axis = (
        graph.mul(graph.lt(r, g), graph.lt(r, b)),
        graph.mul(ge(r, g), graph.lt(g, b)),
        graph.mul(ge(r, b), ge(g, b)),
    )
    strides = (size * size, size, 1)
    base = graph.add(graph.add(graph.mul(low[0], strides[0]),
                               graph.mul(low[1], strides[1])), low[2])
    first = graph.add(graph.add(graph.mul(high_axis[0], strides[0]),
                                graph.mul(high_axis[1], strides[1])),
                      graph.mul(high_axis[2], strides[2]))
    last = graph.add(graph.add(graph.mul(low_axis[0], strides[0]),
                               graph.mul(low_axis[1], strides[1])),
                     graph.mul(low_axis[2], strides[2]))
    diagonal = sum(strides)
    middle_axis = tuple(graph.sub(graph.sub(1.0, high), low_value)
                        for high, low_value in zip(high_axis, low_axis))
    high_plane = graph.add(graph.add(high_axis[0], graph.mul(2.0, high_axis[1])),
                           graph.mul(3.0, high_axis[2]))
    low_plane = graph.add(graph.add(low_axis[0], graph.mul(2.0, low_axis[1])),
                          graph.mul(3.0, low_axis[2]))
    middle_plane = graph.sub(graph.sub(6.0, high_plane), low_plane)
    middle_fraction = graph.add(graph.add(graph.mul(r, middle_axis[0]),
                                          graph.mul(g, middle_axis[1])),
                                graph.mul(b, middle_axis[2]))
    high_fraction = graph.add(graph.add(graph.mul(r, high_axis[0]),
                                        graph.mul(g, high_axis[1])),
                              graph.mul(b, high_axis[2]))
    low_fraction = graph.add(graph.add(graph.mul(r, low_axis[0]),
                                       graph.mul(g, low_axis[1])),
                             graph.mul(b, low_axis[2]))
    vertex_indices = (
        base,
        graph.add(base, graph.mul(count, high_plane)),
        graph.add(graph.add(base, first), graph.mul(count, middle_plane)),
        graph.add(graph.add(base, graph.sub(diagonal, last)),
                  graph.mul(count, low_plane)),
    )

    pixels = cube.compositor_pixels() if graph.tree.bl_idname == "CompositorNodeTree" else cube.shader_pixels()
    field_key = ("linear_stack_lut", cube.signature, cube.size, graph.tree.bl_idname)
    sampled = []
    width = ATLAS_WIDTH
    for index in vertex_indices:
        row = graph.op("FLOOR", graph.div(index, width))
        column = graph.sub(index, graph.mul(width, row))
        color, exponent = graph.sample_texture(
            pixels, key=field_key, interpolation="Closest",
            label="Perceptual Grade stack LUT",
            pixel_coordinates=(column, row),
        )
        value = color
        if graph.tree.bl_idname == "CompositorNodeTree":
            factor = graph.power(2.0, exponent)
            value = graph.vscale(value, factor)
        sampled.append(value)
    return graph.vadd(
        graph.vadd(sampled[0], graph.vscale(sampled[1], high_fraction)),
        graph.vadd(graph.vscale(sampled[2], middle_fraction),
                   graph.vscale(sampled[3], low_fraction)),
    )


def _cell_coordinates(rgb, size=SIZE):
    rgb = np.asarray(rgb, dtype=np.float64)
    if rgb.shape[-1] != 3 or not np.isfinite(rgb).all():
        raise ValueError("LUT input must be finite RGB")
    bounded = np.clip(rgb, MINIMUM, MAXIMUM)
    cells = size - 1
    position = cells * np.log1p(bounded / KAPPA) / LOG_RANGE
    index = np.clip(np.floor(position).astype(np.int64), 0, cells - 1)
    grid = axis(size)
    low, high = grid[index], grid[index + 1]
    fraction = (rgb - low) / (high - low)
    return index, fraction


def _tetrahedral(cube, rgb):
    rgb = np.asarray(rgb, dtype=np.float64)
    shape = rgb.shape
    flat = rgb.reshape(-1, 3)
    index, fraction = _cell_coordinates(flat, cube.size)
    # Stable descending sort makes ties prefer R, then G, then B.
    order = np.argsort(-fraction, axis=-1, kind="stable")
    result = np.empty_like(flat)
    for row, (point, fractions, axes) in enumerate(zip(flat, fraction, order)):
        current = index[row].copy()
        value = cube.values[tuple(current)].astype(np.float64)
        for axis_index in axes:
            edge = cube.edge_values[axis_index][tuple(current)].astype(np.float64)
            value = value + edge * fractions[axis_index]
            current[axis_index] += 1
        result[row] = value
    return result.reshape(shape)


@dataclass(frozen=True)
class LinearCube:
    """Baked stack in fixed ACEScg coordinates with independent edge payloads."""
    values: np.ndarray
    edge_values: np.ndarray
    signature: str
    space: str
    to_lut: np.ndarray
    from_lut: np.ndarray
    size: int = SIZE

    def apply_lut(self, rgb):
        return _tetrahedral(self, rgb)

    def apply(self, rgb):
        rgb = np.asarray(rgb, dtype=np.float64)
        return self.apply_lut(rgb @ self.to_lut.T) @ self.from_lut.T

    def pixels(self, *, encoded=False):
        """Return a four-plane atlas: base then forward R, G, and B edges.

        The GPU baker computes affine edge vectors directly from the matrix and
        axis spacing, avoiding subtraction of rounded high-offset vertices.
        """
        count = self.size**3
        fields = np.concatenate((self.values[None, ...], self.edge_values), axis=0)
        if encoded:
            fields = np.stack([pack_rgbe(field.reshape(-1, 3)) for field in fields])
        else:
            packed = np.zeros((4, count, 4), dtype=np.float32)
            packed[..., :3] = fields.reshape(4, count, 3)
            packed[..., 3] = 1.0
            fields = packed
        height = atlas_height(self.size)
        atlas = np.zeros((height * ATLAS_WIDTH, 4), dtype=np.float32)
        atlas[:fields.shape[0] * count] = fields.reshape(-1, 4)
        return atlas.reshape(height, ATLAS_WIDTH, 4)

    def shader_pixels(self):
        return self.pixels(encoded=False)

    def compositor_pixels(self):
        return self.pixels(encoded=True)

    def packed_values(self):
        """Return the four independently RGBE-encoded payload planes."""
        fields = np.concatenate((self.values[None, ...], self.edge_values), axis=0)
        return np.stack([pack_rgbe(field.reshape(-1, 3)) for field in fields])


def _stack_matrix(matrices, space):
    stages = []
    for matrix in matrices:
        value = np.asarray(matrix, dtype=np.float64)
        if value.shape != (3, 3) or not np.isfinite(value).all():
            raise ValueError("Each Stage 1 matrix must be finite 3x3")
        stages.append(value)
    composed = np.eye(3, dtype=np.float64)
    for matrix in stages:
        composed = matrix @ composed
    to_lut, from_lut = basis(space)
    lut_matrix = to_lut @ composed @ from_lut

    digest = hashlib.sha256()
    digest.update(space.encode("utf8"))
    digest.update(np.asarray(composed, dtype="<f8").tobytes())
    return lut_matrix, to_lut, from_lut, digest.hexdigest()


__all__ = ("SIZE", "PREVIEW_SIZE", "CELLS", "MINIMUM", "MAXIMUM", "KAPPA",
           "LOG_RANGE", "ATLAS_WIDTH", "ATLAS_HEIGHT", "LinearCube", "axis",
           "atlas_height", "basis", "pack_rgbe", "unpack_rgbe")
