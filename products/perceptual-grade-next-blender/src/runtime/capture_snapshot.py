"""Freeze Blender scene and source-image inputs for isolated capture jobs."""

from pathlib import Path
import shutil
import tempfile
import uuid

import numpy as np

from .capture_images import image_format, resolve_datablocks, route_datablock


def freeze_snapshot(bpy, route):
    """Write an immutable scene snapshot and its source-image sidecars.

    The returned root owns every path in the capture request. Callers retain
    the root until the corresponding helper job and publication have retired.
    """
    root = Path(tempfile.mkdtemp(prefix="pg-next-capture-"))
    try:
        snapshot = root / "snapshot.blend"
        scene = route_datablock(bpy, bpy.data.scenes, route, "scene")
        if scene is None:
            raise RuntimeError("Capture scene disappeared before snapshot")
        ids = {scene}
        owner_kind = route.get("owner_kind")
        if owner_kind == "material":
            owner = route_datablock(bpy, bpy.data.materials, route, "owner")
        elif owner_kind == "world":
            owner = route_datablock(bpy, bpy.data.worlds, route, "owner")
        else:
            owner = scene
        if owner is not None:
            ids.add(owner)
        obj = route_datablock(bpy, bpy.data.objects, route, "object")
        if obj is not None:
            ids.add(obj)
        bpy.data.libraries.write(str(snapshot), ids, path_remap="ABSOLUTE", fake_user=True)

        image_keys = {tuple(descriptor["image_key"])
                      for descriptor in route.get("images", ())}
        source_images = resolve_datablocks(bpy, bpy.data.images, image_keys)
        images = []
        for key, image in source_images.items():
            width, height = (int(value) for value in image.size)
            channels = int(image.channels)
            if (min(width, height) < 1
                    or width * height * max(channels, 4) * 4 > 512 * 1024 * 1024):
                raise MemoryError("Capture source Image exceeds the pixel budget")
            values = np.empty(width * height * channels, dtype=np.float32)
            image.pixels.foreach_get(values)
            path = root / ("image-" + uuid.uuid4().hex + ".npy")
            np.save(path, values.reshape(height, width, channels), allow_pickle=False)
            images.append(dict(
                image_key=key, width=width, height=height,
                pixels_path=str(path), **image_format(image),
            ))
        return root, snapshot, images
    except BaseException:
        shutil.rmtree(root, ignore_errors=True)
        raise


__all__ = ("freeze_snapshot",)
