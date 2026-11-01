"""Compatibility exports for the co-located scope/view policy.

The implementation lives in scope.py so symbolic joint traces execute the same
scope and foreground transitions that the production adapters call.
"""

from .scope import (
    ForegroundEvent, ForegroundState, foreground_can_apply, foreground_step,
    new_foreground,
)

__all__ = (
    "ForegroundEvent", "ForegroundState", "foreground_can_apply",
    "foreground_step", "new_foreground",
)
