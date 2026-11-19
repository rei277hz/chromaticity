"""Value-only snapshots crossing the private Stack GPU helper boundary."""

from dataclasses import asdict
import math

import numpy as np

from .kernel import lut
from .kernel.settings import (
    ColorSettings, LinearSettings, Settings, SPACES, ToneSettings, stack_directions,
)
from .lut_gpu import PreparedStack


def freeze_settings(settings):
    if any(not isinstance(item, Settings) for item in settings):
        raise TypeError("Stack settings must be complete frozen Settings")
    return tuple(asdict(item) for item in settings)


def thaw_settings(settings):
    result = []
    for item in settings:
        snapshot = Settings(
            linear=LinearSettings(**item["linear"]),
            tone=ToneSettings(**item["tone"]),
            space=item["space"],
            color=ColorSettings(**item["color"]),
        )
        if snapshot.space not in SPACES:
            raise ValueError("Stack settings require a supported working space")
        result.append(snapshot)
    return tuple(result)


def freeze_prepared(prepared, diagnostics=None):
    cube = prepared.cube
    return {
        "settings": freeze_settings(prepared.settings),
        "directions": stack_directions(len(prepared.settings), prepared.directions or None),
        "working_space": prepared.space,
        "signature": cube.signature,
        "size": cube.size,
        "values": cube.values,
        "edge_values": cube.edge_values,
        "to_lut": cube.to_lut,
        "from_lut": cube.from_lut,
        "diagnostics": prepared.diagnostics if diagnostics is None else diagnostics,
    }


def _array(value, shape, label):
    value = np.asarray(value)
    if value.dtype.kind != "f" or value.shape != shape or not np.isfinite(value).all():
        raise ValueError("Invalid Stack helper " + label)
    value.flags.writeable = False
    return value


def _validate_inverse_diagnostics(diagnostics, size):
    if not isinstance(diagnostics, dict):
        raise ValueError("Missing Stack helper inverse diagnostics")
    count = diagnostics.get("inverse_approximate_vertices")
    residual = diagnostics.get("inverse_max_residual")
    if (
        type(count) is not int or not 0 <= count <= size**3
        or type(residual) is not float or not math.isfinite(residual) or residual < 0.0
        or (count > 0) != (residual > 1.0)
    ):
        raise ValueError("Invalid Stack helper inverse diagnostics")


def thaw_prepared(payload):
    """Validate a complete receipt before it can authorize graph installation."""
    size = payload["size"]
    if type(size) is not int or size not in (lut.PREVIEW_SIZE, lut.SIZE):
        raise ValueError("Invalid Stack helper cube size")
    space = payload["working_space"]
    if space not in SPACES:
        raise ValueError("Invalid Stack helper working space")
    signature = payload["signature"]
    if not isinstance(signature, str) or not signature:
        raise ValueError("Invalid Stack helper cube signature")
    cube = lut.LinearCube(
        _array(payload["values"], (size, size, size, 3), "values"),
        _array(payload["edge_values"], (3, size, size, size, 3), "edge values"),
        signature, space,
        _array(payload["to_lut"], (3, 3), "input basis"),
        _array(payload["from_lut"], (3, 3), "output basis"),
        size,
    )
    settings = thaw_settings(payload["settings"])
    directions = stack_directions(len(settings), payload.get("directions"))
    diagnostics = payload.get("diagnostics")
    if "INVERSE" in directions:
        _validate_inverse_diagnostics(diagnostics, size)
    return PreparedStack(settings, space, cube, diagnostics, directions)
