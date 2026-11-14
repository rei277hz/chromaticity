"""Build-only native Stack lookup emission."""
import math

from ..kernel.lut import MINIMUM, MAXIMUM, KAPPA, LOG_RANGE, ATLAS_WIDTH


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
    """Convert scene RGB, sample the fixed AP1 lattice, and return scene RGB."""
    size = cube.size
    count = size**3
    rgb = graph.matrix(rgb, cube.to_lut)
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
    result = graph.vadd(
        graph.vadd(sampled[0], graph.vscale(sampled[1], high_fraction)),
        graph.vadd(graph.vscale(sampled[2], middle_fraction),
                   graph.vscale(sampled[3], low_fraction)),
    )
    return graph.matrix(result, cube.from_lut)


