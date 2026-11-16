"""Build-only native Stack lookup emission."""
import math

from ..kernel.lut import (
    MINIMUM, MAXIMUM, KAPPA, LOG_RANGE, ATLAS_WIDTH,
    basis_pixels, stack_config_pixels,
)


def _axis_socket(graph, value, cells, axis_step):
    bounded = graph.clamp(value, MINIMUM, MAXIMUM)
    encoded = graph.div(
        graph.op("LOGARITHM", graph.add(1.0, graph.div(bounded, KAPPA)), math.e),
        LOG_RANGE,
    )
    position = graph.mul(cells, encoded)
    index = graph.minimum(graph.sub(cells, 1.0),
                          graph.maximum(0.0, graph.op("FLOOR", position)))
    low = graph.mul(KAPPA, graph.sub(graph.op("EXPONENT", graph.mul(index, axis_step)), 1.0))
    high_exp = graph.op("EXPONENT", graph.mul(graph.add(index, 1.0), axis_step))
    high_value = graph.mul(KAPPA, graph.sub(high_exp, 1.0))
    high = graph.select(graph.lt(index, graph.sub(cells, 1.0)), high_value, MAXIMUM)
    fraction = graph.div(graph.sub(value, low), graph.sub(high, low))
    return index, fraction


def append_lut_lookup(graph, cube, rgb):
    """Convert scene RGB, sample the fixed AP1 lattice, and return scene RGB."""
    basis = basis_pixels(cube.to_lut, cube.from_lut)
    basis_key = ("linear_stack_basis", graph.tree.bl_idname)
    basis_image = graph._packed_image(
        basis, key=basis_key, label="Perceptual Grade stack basis",
    )
    basis_image["perceptual_grade_nodes_field_role"] = "stack_basis"
    basis_vectors = tuple(
        graph.sample_texture(
            basis, pixel_coordinates=(index, 0), key=basis_key,
            interpolation="Closest", label="Perceptual Grade stack basis",
        )[0]
        for index in range(6)
    )

    def apply_basis(vector, offset):
        red, green, blue = graph.split(vector)
        red_delta = graph.vscale(basis_vectors[offset], graph.sub(red, green))
        blue_delta = graph.vscale(basis_vectors[offset + 1], graph.sub(blue, green))
        neutral = graph.vscale(basis_vectors[offset + 2], green)
        return graph.vadd(graph.vadd(red_delta, blue_delta), neutral)

    rgb = apply_basis(rgb, 0)
    config_pixels = stack_config_pixels(int(cube.size))
    config_key = ("linear_stack_config", graph.tree.bl_idname)
    config_image = graph._packed_image(
        config_pixels, key=config_key, label="Perceptual Grade stack lookup config",
    )
    config_image["perceptual_grade_nodes_field_role"] = "stack_config"
    config_rgb, atlas_height_inverse = graph.sample_texture(
        config_pixels, pixel_coordinates=(0, 0), key=config_key,
        interpolation="Closest", label="Perceptual Grade stack lookup config",
    )
    size, size_squared, count = graph.split(config_rgb)
    cells = graph.sub(size, 1.0)
    axis_step = graph.div(LOG_RANGE, cells)
    channels = graph.split(rgb)
    coordinates = [_axis_socket(graph, channel, cells, axis_step) for channel in channels]
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
    strides = (size_squared, size, 1)
    base = graph.add(graph.add(graph.mul(low[0], strides[0]),
                               graph.mul(low[1], strides[1])), low[2])
    first = graph.add(graph.add(graph.mul(high_axis[0], strides[0]),
                                graph.mul(high_axis[1], strides[1])),
                      graph.mul(high_axis[2], strides[2]))
    last = graph.add(graph.add(graph.mul(low_axis[0], strides[0]),
                               graph.mul(low_axis[1], strides[1])),
                     graph.mul(low_axis[2], strides[2]))
    diagonal = graph.add(graph.add(size_squared, size), 1.0)
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
    lut_image = graph._packed_image(
        pixels, key=field_key, label="Perceptual Grade stack LUT",
    )
    lut_image["perceptual_grade_nodes_field_role"] = "stack_lut"
    sampled = []
    width = ATLAS_WIDTH
    for index in vertex_indices:
        row = graph.op("FLOOR", graph.div(index, width))
        column = graph.sub(index, graph.mul(width, row))
        u = graph.madd(1.0 / width, column, 0.5 / width)
        v = graph.mul(graph.add(row, 0.5), atlas_height_inverse)
        color, exponent = graph.sample_texture(
            pixels, u, v, key=field_key, interpolation="Closest",
            label="Perceptual Grade stack LUT",
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
    return apply_basis(result, 3)


