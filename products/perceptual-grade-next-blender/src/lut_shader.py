"""Load the Buck-generated Stack helper shader from the product resource."""

from .kernel.node_templates import shader_source


def grade_source(boundary=None):
    """Return the verified generated Stage 2 GLSL source."""
    return shader_source(boundary)


__all__ = ("grade_source",)
