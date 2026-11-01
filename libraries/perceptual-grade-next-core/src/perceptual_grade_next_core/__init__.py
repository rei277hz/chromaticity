"""Portable Perceptual Grade Next settings and numerical primitives."""

from .settings import (
    ColorSettings,
    Direction,
    GradeSettings,
    LinearSettings,
    StackEntry,
    StackSettings,
    ToneSettings,
    WebSettings,
)
__all__ = [
    "ColorSettings",
    "Direction",
    "GradeSettings",
    "LinearSettings",
    "StackEntry",
    "StackSettings",
    "ToneSettings",
    "WebSettings",
]


def __getattr__(name):
    if name in {"GradeModel", "InverseResult", "StackModel"}:
        from .model import GradeModel, InverseResult, StackModel
        return {"GradeModel": GradeModel, "InverseResult": InverseResult,
                "StackModel": StackModel}[name]
    raise AttributeError(name)
