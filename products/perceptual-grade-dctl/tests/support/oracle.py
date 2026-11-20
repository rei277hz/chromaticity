"""Run each installed DCTL's transform in the float32 C++ host."""
from functools import cache
from importlib.resources import files
import subprocess

import numpy as np

from .dctl import controls, filename

RESOURCES = files("tests.support")
STAGE_DIR = RESOURCES / "stages"


@cache
def source(stage, locale="en"):
    return (STAGE_DIR / filename(stage, locale)).read_text(encoding="utf-8")


@cache
def ui(stage):
    return controls(source(stage))


def run(stage, values, settings=None, *, x=0, y=10):
    values = np.asarray(values, dtype=np.float32).reshape(-1, 3)
    settings = settings or {}
    declarations = ui(stage)
    unknown = settings.keys() - {field["name"] for field in declarations}
    if unknown:
        raise ValueError(f"Unknown {stage} controls: {unknown}")
    fields = []
    for item in declarations:
        value = settings.get(item["name"], item["default"])
        if item["type"] == "DCTLUI_SLIDER_FLOAT":
            fields.append(format(value, ".17g"))
        else:
            if int(value) != value:
                raise ValueError(f"{item['name']} requires an integer")
            fields.append(str(int(value)))
    lines = [" ".join(fields)]
    for pixel in values:
        coordinates = " ".join(format(channel, ".9g") for channel in pixel)
        lines.append(f"{coordinates} 1920 1080 {x} {y}")
    result = subprocess.run([str(RESOURCES / "oracle"), stage],
                            input="\n".join(lines) + "\n", text=True,
                            capture_output=True, check=True)
    actual = np.fromstring(result.stdout, dtype=np.float32, sep=" ").reshape(-1, 3)
    if actual.shape != values.shape:
        raise ValueError(f"Host produced {len(actual)} rows for {len(values)} inputs")
    return actual
