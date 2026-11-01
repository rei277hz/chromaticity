"""Private Blender process entry point for a captured compositor Bake."""

import sys
import json
from pathlib import Path

import numpy as np


def main(arguments):
    import bpy

    if len(arguments) != 2:
        raise RuntimeError("Compositor Bake worker requires scene and image manifest")
    scene = bpy.data.scenes.get(arguments[0])
    if scene is None or scene.compositing_node_group is None:
        raise RuntimeError("Private Compositor Bake scene is incomplete")
    scene.render.use_compositing = True
    scene.render.use_sequencer = False
    scene.render.compositor_device = "CPU"
    manifest = json.loads(Path(arguments[1]).read_text(encoding="utf8"))
    for item in manifest.get("images", ()):
        image = bpy.data.images.get(item["name"])
        if image is None:
            raise RuntimeError("Private Compositor Bake Image is missing")
        size = tuple(int(value) for value in image.size[:2])
        channels = int(image.channels)
        if size != tuple(item["size"]) or channels != int(item["channels"]):
            raise RuntimeError("Private Compositor Bake Image domain changed")
        values = np.load(Path(arguments[1]).parent / item["pixels"], allow_pickle=False)
        if values.size != len(image.pixels) or values.dtype != np.float32:
            raise RuntimeError("Private Compositor Bake Image payload is invalid")
        image.pixels.foreach_set(values.reshape(-1))
        image.update()
    result = bpy.ops.render.render(write_still=False, scene=scene.name)
    if "FINISHED" not in result:
        raise RuntimeError("Private Compositor Bake render did not finish")


if __name__ == "__main__":
    main(sys.argv[sys.argv.index("--") + 1:])
