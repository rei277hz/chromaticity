"""Value-only snapshots crossing the private Stack GPU helper boundary."""

from dataclasses import asdict

import numpy as np

from .kernel import lut
from .kernel.settings import ColorSettings, LinearSettings, Settings, SPACES, ToneSettings
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
        if snapshot.space not in SPACES or snapshot.color != ColorSettings():
            raise ValueError("Stack settings require a supported space and neutral Color")
        result.append(snapshot)
    return tuple(result)


def freeze_prepared(prepared, diagnostics=None):
    cube = prepared.cube
    return {
        "settings": freeze_settings(prepared.settings),
        "working_space": prepared.space,
        "signature": cube.signature,
        "size": cube.size,
        "values": cube.values,
        "edge_values": cube.edge_values,
        "to_lut": cube.to_lut,
        "from_lut": cube.from_lut,
        "diagnostics": diagnostics,
    }


def _array(value, shape, label):
    value = np.asarray(value)
    if value.dtype.kind != "f" or value.shape != shape or not np.isfinite(value).all():
        raise ValueError("Invalid Stack helper " + label)
    value.flags.writeable = False
    return value


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
    return PreparedStack(thaw_settings(payload["settings"]), space, cube,
                         payload.get("diagnostics"))
