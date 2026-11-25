"""Blender host operations shared by Bake and scope capture workers."""

from pathlib import Path

import numpy as np

from .capture_images import image_format, resolve_datablocks
from .compositor_effects import matching_compositor_occurrences


MAX_PIXEL_BYTES = 512 * 1024 * 1024

def register_snapshot_node_types():
    """Register only persisted node ABI classes needed while opening a snapshot."""
    import bpy

    for base, identifier in (
        ("NodeTree", "PGGradeData"),
        ("ShaderNodeCustomGroup", "PGShaderGrade"),
        ("CompositorNodeCustomGroup", "PGCompositorGrade"),
        ("ShaderNodeCustomGroup", "PGShaderGradeStack"),
        ("CompositorNodeCustomGroup", "PGCompositorGradeStack"),
        ("ShaderNodeCustomGroup", "PGShaderGradePerNode"),
        ("CompositorNodeCustomGroup", "PGCompositorGradePerNode"),
    ):
        registry = bpy.types.NodeTree if base == "NodeTree" else bpy.types.Node
        if registry.bl_rna_get_subclass_py(identifier, None) is not None:
            continue
        cls = type(identifier, (getattr(bpy.types, base),), {
            "__module__": __name__, "bl_idname": identifier,
            "bl_label": identifier, "bl_icon": "COLOR",
        })
        bpy.utils.register_class(cls)


def open_snapshot(inputs):
    """Open the immutable per-request Blender snapshot."""
    import bpy

    value = inputs.get("snapshot_path")
    if not isinstance(value, str):
        raise ValueError("Bake snapshot path is absent")
    path = Path(value)
    if not path.is_absolute() or path.is_symlink() or not path.is_file():
        raise ValueError("Invalid bake snapshot path")
    register_snapshot_node_types()
    result = bpy.ops.wm.open_mainfile(filepath=str(path), use_scripts=False, load_ui=False)
    if "FINISHED" not in result:
        raise RuntimeError("Bake snapshot could not be opened")
    route = inputs["route"]
    restore_images(inputs["images"], route["images"])


def _verify_sampler_bindings(host, occurrences, images):
    """Require the native sampler at every recorded occurrence to use its frozen Image."""
    collections = {
        "material": "materials", "world": "worlds", "light": "lights", "compositor": "scenes",
    }
    owners = {}
    for kind, key in (item["owner"] for item in occurrences):
        owners.setdefault(kind, set()).add(tuple(key))
    roots = {
        kind: resolve_datablocks(host, getattr(host.data, collections[kind]), keys)
        for kind, keys in owners.items()
    }
    for occurrence in occurrences:
        kind, owner_key = occurrence["owner"]
        owner = roots[kind][tuple(owner_key)]
        tree = (compositor_root(host, owner, occurrence)
                if kind == "compositor" else owner.node_tree)
        reader_path = occurrence["reader_path"]
        if reader_path is None:
            raise ValueError("Bake source has no bound native Image reader")
        path = (*occurrence["group_path"], occurrence["node_name"], *reader_path)
        node = None
        for name in path:
            node = tree.nodes.get(name) if tree is not None else None
            if node is None:
                raise ValueError(f"Bake source sampler is missing at {path!r}")
            tree = getattr(node, "node_tree", None)
        if (node.bl_idname not in {"ShaderNodeTexImage", "CompositorNodeImage"}
                or node.image != images[tuple(occurrence["image_key"])]):
            raise ValueError(f"Bake source sampler at {path!r} has a different Image")


def restore_images(records, occurrences):
    import bpy

    required = {tuple(item["image_key"]) for item in occurrences}
    provided = {tuple(record["image_key"]) for record in records}
    if len(provided) != len(records) or provided != required:
        raise ValueError("Bake Image payload identities do not match the requested samplers")
    if not required:
        return
    images = resolve_datablocks(bpy, bpy.data.images, required)
    _verify_sampler_bindings(bpy, occurrences, images)
    for record in records:
        image = images[tuple(record["image_key"])]
        width, height = (int(value) for value in image.size)
        if ((width, height) != (record["width"], record["height"])
                or any(record[name] != value for name, value in image_format(image).items())):
            raise ValueError(f"Bake source Image format changed: {record['image_key']!r}")
        if min(width, height) < 1 or width * height * 16 > MAX_PIXEL_BYTES:
            raise ValueError("Bake source Image exceeds the pixel budget")
        path = Path(record["pixels_path"])
        if not path.is_absolute() or path.is_symlink() or not path.is_file():
            raise ValueError("Invalid bake image payload")
        values = np.load(path, allow_pickle=False)
        if (values.dtype != np.float32 or not 1 <= record["channels"] <= 4
                or values.shape != (height, width, record["channels"])):
            raise ValueError("Bake Image payload does not match its captured storage")
        if not np.isfinite(values).all():
            raise ValueError("Bake image payload contains nonfinite pixels")
        image.pixels.foreach_set(values.ravel())
        image.update()


def configure_linear(scene):
    """Configure a helper render for untransformed float pixels."""
    settings = scene.render.image_settings
    settings.file_format = "OPEN_EXR"
    settings.color_mode = "RGBA"
    settings.color_depth = "32"
    settings.exr_codec = "ZIPS"
    if hasattr(settings, "color_management"):
        settings.color_management = "OVERRIDE"
    try:
        settings.linear_colorspace_settings.name = "scene_linear"
    except (AttributeError, RuntimeError, ValueError):
        pass
    try:
        scene.view_settings.view_transform = "Standard"
        scene.view_settings.look = "None"
        scene.view_settings.exposure = 0.0
        scene.view_settings.gamma = 1.0
    except (AttributeError, RuntimeError, ValueError):
        pass


def disable_file_outputs():
    import bpy

    for tree in tuple(bpy.data.node_groups):
        if tree.bl_idname != "CompositorNodeTree":
            continue
        for node in tuple(tree.nodes):
            if node.bl_idname == "CompositorNodeOutputFile":
                tree.nodes.remove(node)


def compositor_root(host, scene, route):
    matches = tuple(matching_compositor_occurrences(host, scene, route))
    if len(matches) != 1:
        raise ValueError("Bake compositor effect is missing or ambiguous in the snapshot")
    return matches[0][1]


