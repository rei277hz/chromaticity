"""Resolve the shared color library in Buck and extension package layouts."""

try:
    from ..color_core import linear, modcam16, scaled
except ImportError as error:
    if error.name is not None:
        raise
    from color_core import linear, modcam16, scaled

__all__ = ["linear", "modcam16", "scaled"]
