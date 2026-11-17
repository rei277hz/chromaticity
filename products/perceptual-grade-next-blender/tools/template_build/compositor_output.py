"""Finite output publication for the production Compositor Grade topology."""

from .graph import FLOAT_MAX


def finite_color(graph, color, *, observed=(), valid=1.):
    """Reject observed nonfinite values without mixing NaNs into magenta.

    Exported AP1 cube colors in the supported working spaces fit binary16.
    The finite output bound also makes the unused interpolation operand safe
    when an Auto compositor materializes it in a half-float image. This is an
    observed-state check, not a proof of every intermediate's accuracy.
    """
    components = graph.split(color)
    for value in observed:
        valid = graph.mul(valid, graph.lt(graph.abs(value), FLOAT_MAX))
    for value in components:
        valid = graph.mul(valid, graph.lt(graph.abs(value), 65504.))
    # Put the finite operand first: ordered min/max replaces a NaN only in
    # this unused branch. The validity mask always inspects the original.
    clean = graph.vector(tuple(
        graph.maximum(-65504., graph.minimum(65504., value))
        for value in components
    ))
    return graph.vselect(valid, clean, (1., 0., 1.)), valid


__all__ = ("finite_color",)
