"""Capture a compositor Grade/Stack through Blender's installed node graph.

The scene and exact group-instance path are copied into a temporary .blend and
evaluated by a private Blender process. That keeps the caller's render context
and global Render Result outside the capture process.
"""

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile

import numpy as np

from .native_bake import MAX_PIXEL_BYTES


def _pointer(value):
    try:
        return int(value.as_pointer())
    except (AttributeError, ReferenceError, RuntimeError):
        return 0


def _socket(collection, name):
    value = collection.get(name) if hasattr(collection, "get") else None
    if value is None:
        value = next((item for item in collection if item.name == name), None)
    if value is None:
        raise RuntimeError("Compositor Bake socket is unavailable: " + name)
    return value


def _group_path(root, target):
    """Find one unambiguous group-instance path from root to target tree."""
    wanted = _pointer(target)
    matches = []

    def visit(tree, path, active):
        if _pointer(tree) == wanted:
            matches.append(tuple(path))
            return
        pointer = _pointer(tree)
        if not pointer or pointer in active:
            return
        active = active | {pointer}
        for node in getattr(tree, "nodes", ()):
            nested = getattr(node, "node_tree", None)
            if nested is not None:
                visit(nested, path + [str(node.name)], active)

    visit(root, [], set())
    if len(matches) != 1:
        raise RuntimeError("Select a unique Compositor Grade occurrence in the active scene")
    return matches[0]


def _copy_occurrence(root, path, directory):
    descendants = []

    def copy_tree(source, ancestry):
        pointer = _pointer(source)
        if not pointer or pointer in ancestry:
            raise RuntimeError("Compositor Bake contains a cyclic node-group graph")
        copied = source.copy()
        descendants.append(copied)
        ancestry = ancestry | {pointer}
        for node in copied.nodes:
            nested = getattr(node, "node_tree", None)
            if nested is not None:
                node.node_tree = copy_tree(nested, ancestry)
        return copied

    copied = copy_tree(root, set())
    tree = copied
    for name in path:
        node = tree.nodes.get(name)
        if node is None or getattr(node, "node_tree", None) is None:
            raise RuntimeError("Compositor Bake group path changed during capture")
        tree = node.node_tree
    images = []
    image_copies = {}
    image_manifest = []
    payload_bytes = 0
    for group in descendants:
        for node in group.nodes:
            image = getattr(node, "image", None)
            pointer = _pointer(image)
            if image is None or not pointer:
                continue
            private_image = image_copies.get(pointer)
            if private_image is None:
                source = str(getattr(image, "source", ""))
                if source in {"MOVIE", "SEQUENCE", "VIEWER", "TILED"}:
                    raise RuntimeError("Compositor Bake requires a still Image source")
                private_image = image.copy()
                images.append(private_image)
                image_copies[pointer] = private_image
                if source == "FILE" and not getattr(private_image, "packed_file", None):
                    private_image.pack()
                channels = int(image.channels)
                width, height = (int(value) for value in image.size[:2])
                payload_bytes += width * height * channels * 4
                if width < 1 or height < 1 or payload_bytes > MAX_PIXEL_BYTES:
                    raise MemoryError("Compositor Bake Image snapshots exceed the 512 MiB limit")
                values = np.empty(width * height * channels, dtype=np.float32)
                image.pixels.foreach_get(values)
                pixels_name = "image_%04d.npy" % len(image_manifest)
                np.save(directory / pixels_name, values, allow_pickle=False)
                image_manifest.append({
                    "name": str(private_image.name),
                    "size": [width, height],
                    "channels": channels,
                    "pixels": pixels_name,
                })
            node.image = private_image
    (directory / "image_manifest.json").write_text(json.dumps({
        "images": image_manifest,
    }, sort_keys=True), encoding="utf8")
    return copied, tree, descendants[1:], images


def _new_output(tree, output_node, name):
    field = tree.interface.new_socket(
        name=name, in_out="OUTPUT", socket_type="NodeSocketColor",
    )
    return output_node.inputs[field.identifier]


def _expose_signal(root, active_tree, path, node, socket_name, token):
    """Tunnel one exact occurrence signal from a nested tree to the root."""
    if socket_name.startswith("INPUT:"):
        source = _socket(node.inputs, socket_name[6:])
        links = tuple(link for link in source.links if link.is_valid and not link.is_muted)
        if links:
            signal = links[0].from_socket
        else:
            constant = active_tree.nodes.new("CompositorNodeRGB")
            constant.outputs[0].default_value = tuple(source.default_value)
            signal = constant.outputs[0]
    else:
        signal = _socket(node.outputs, socket_name)

    parents = [root]
    tree = root
    for name in path:
        group = tree.nodes.get(name)
        if group is None or getattr(group, "node_tree", None) is None:
            raise RuntimeError("Copied Compositor Bake group path is incomplete")
        tree = group.node_tree
        parents.append(tree)
    tree = active_tree
    for depth in range(len(path), 0, -1):
        instance_name = path[depth - 1]
        group_output = next((item for item in tree.nodes
                             if item.bl_idname == "NodeGroupOutput"
                             and item.is_active_output), None)
        if group_output is None:
            group_output = tree.nodes.new("NodeGroupOutput")
            group_output.is_active_output = True
        field_name = "PG Next Bake " + token + " " + str(depth)
        endpoint = tree.interface.new_socket(
            name=field_name, in_out="OUTPUT", socket_type="NodeSocketColor",
        )
        tree.links.new(signal, group_output.inputs[endpoint.identifier])
        tree = parents[depth - 1]
        group_instance = tree.nodes.get(instance_name)
        if group_instance is None:
            raise RuntimeError("Copied Compositor Bake group path is incomplete")
        signal = _socket(group_instance.outputs, endpoint.identifier)
    return signal


def _prepare_private_scene(scene, root_tree, path, owner_name, stage, directory, token):
    private_scene = scene.copy()
    private_scene.name = "PG Next Private Compositor Bake " + token
    copied_root, active_tree, descendants, images = _copy_occurrence(
        root_tree, path, directory,
    )
    private_scene.compositing_node_group = copied_root
    try:
        owner = active_tree.nodes.get(owner_name)
        if owner is None:
            raise RuntimeError("Selected Compositor Grade node disappeared")
        input_signal = _expose_signal(
            copied_root, active_tree, path, owner, "INPUT:Color", token + "i",
        )
        output_signal = _expose_signal(
            copied_root, active_tree, path, owner, "Color", token + "o",
        )
        signal = input_signal if stage == "input" else output_signal

        # Existing root outputs could select a different graph branch. The
        # private scene needs one explicit output so the compositor evaluates
        # the selected capture branch for this render.
        for existing in tuple(copied_root.nodes):
            if existing.bl_idname in {"NodeGroupOutput", "CompositorNodeViewer"}:
                copied_root.nodes.remove(existing)
        output_field = next((item for item in copied_root.interface.items_tree
                             if item.item_type == "SOCKET"
                             and item.in_out == "OUTPUT"
                             and item.socket_type == "NodeSocketColor"), None)
        if output_field is None:
            output_field = copied_root.interface.new_socket(
                name="Image", in_out="OUTPUT", socket_type="NodeSocketColor",
            )
        root_output = copied_root.nodes.new("NodeGroupOutput")
        root_output.is_active_output = True
        copied_root.links.new(signal, root_output.inputs[output_field.identifier])

        captures = (("input", input_signal),) if stage == "input" else (
            ("input_verify", input_signal), ("output", output_signal),
        )
        for capture_name, capture_signal in captures:
            endpoint = copied_root.nodes.new("CompositorNodeOutputFile")
            endpoint.name = "PG Next Private Bake " + capture_name
            endpoint.directory = str(directory)
            endpoint.file_name = "pg_next_" + capture_name + "_"
            item = endpoint.file_output_items.new("RGBA", "capture")
            endpoint.format.media_type = "IMAGE"
            endpoint.format.file_format = "OPEN_EXR"
            endpoint.format.color_mode = "RGBA"
            endpoint.format.color_depth = "32"
            endpoint.format.exr_codec = "ZIPS"
            endpoint.format.color_management = "OVERRIDE"
            endpoint.format.linear_colorspace_settings.name = "scene_linear"
            endpoint.save_as_render = False
            copied_root.links.new(capture_signal, endpoint.inputs[item.name])
        private_scene.render.use_compositing = True
        private_scene.render.use_sequencer = False
        private_scene.render.filepath = str(Path(directory) / "unused")
        return private_scene, copied_root, descendants, images
    except BaseException:
        _remove_private(private_scene, copied_root, descendants, images)
        raise


def _remove_private(scene, root, descendants, images=()):
    import bpy

    if scene is not None:
        try:
            bpy.data.scenes.remove(scene, do_unlink=True)
        except (ReferenceError, RuntimeError, TypeError):
            pass
    for tree in reversed((tuple(descendants) if descendants else ()) +
                         ((root,) if root is not None else ())):
        try:
            if tree.users == 0:
                bpy.data.node_groups.remove(tree, do_unlink=True)
        except (ReferenceError, RuntimeError, TypeError):
            pass
    for image in reversed(tuple(images)):
        try:
            if image.users == 0:
                bpy.data.images.remove(image, do_unlink=True)
        except (ReferenceError, RuntimeError, TypeError):
            pass


def _read_exr(path):
    import bpy

    image = bpy.data.images.load(str(path), check_existing=False)
    try:
        image.colorspace_settings.name = "Non-Color"
        image.alpha_mode = "CHANNEL_PACKED"
        if hasattr(image, "use_half_precision"):
            image.use_half_precision = False
        width, height = (int(value) for value in image.size[:2])
        if min(width, height) < 1 or width * height * 16 > MAX_PIXEL_BYTES:
            raise ValueError("Compositor Bake capture has an invalid pixel domain")
        if int(image.channels) != 4:
            raise ValueError("Compositor Bake capture must be float32 RGBA")
        pixels = np.empty((height, width, 4), dtype=np.float32)
        image.pixels.foreach_get(pixels.reshape(-1))
        if not np.isfinite(pixels).all():
            raise ValueError("Compositor Bake capture contains non-finite pixels")
        return np.ascontiguousarray(pixels)
    finally:
        bpy.data.images.remove(image)


def _run_worker(scene_name, path, image_manifest):
    import bpy

    worker = Path(__file__).with_name("compositor_bake_worker.py")
    command = (
        bpy.app.binary_path, "--background", str(path), "--disable-autoexec",
        "--python-exit-code", "1", "--python", str(worker), "--",
        str(scene_name), str(image_manifest),
    )
    try:
        result = subprocess.run(
            command, cwd=str(path.parent), env=dict(os.environ),
            capture_output=True, text=True, timeout=900, check=False,
        )
    except subprocess.TimeoutExpired as error:
        raise RuntimeError("Private Compositor Bake exceeded its time limit") from error
    if result.returncode != 0:
        details = (result.stdout + "\n" + result.stderr)[-8000:]
        raise RuntimeError("Private Compositor Bake failed: " + details)


def capture_compositor_signal(scene, root_tree, active_tree, owner, group_path,
                              *, stage):
    """Capture the exact Color input or native Color output in a private process."""
    import bpy

    if stage not in {"input", "output"}:
        raise ValueError("Compositor Bake capture stage must be input or output")
    token = hashlib.sha256(
        (str(_pointer(root_tree)) + ":" + str(_pointer(owner)) + ":" + stage)
        .encode("ascii")
    ).hexdigest()[:16]
    with tempfile.TemporaryDirectory(prefix="pg-next-compositor-bake-") as temporary:
        directory = Path(temporary)
        private_scene = root_copy = None
        descendants = []
        images = []
        scene_name = ""
        try:
            private_scene, root_copy, descendants, images = _prepare_private_scene(
                scene, root_tree, tuple(group_path), str(owner.name), stage,
                directory, token,
            )
            project = directory / "capture.blend"
            image_manifest = directory / "image_manifest.json"
            scene_name = str(private_scene.name)
            bpy.data.libraries.write(str(project), {private_scene}, compress=True)
            if not project.is_file() or project.stat().st_size < 1:
                raise RuntimeError("Could not write the private Compositor Bake snapshot")
        finally:
            _remove_private(private_scene, root_copy, descendants, images)
        _run_worker(scene_name, project, image_manifest)
        expected = (("input",) if stage == "input" else ("input_verify", "output"))
        captured = {}
        for capture_name in expected:
            outputs = tuple(directory.glob("pg_next_" + capture_name + "_*.exr"))
            if len(outputs) != 1:
                raise RuntimeError(
                    "Private Compositor Bake did not produce exactly one "
                    + capture_name + " EXR"
                )
            captured[capture_name] = _read_exr(outputs[0])
        return captured["input"] if stage == "input" else (
            captured["input_verify"], captured["output"],
        )


def unique_compositor_group_path(root_tree, active_tree):
    return _group_path(root_tree, active_tree)


@dataclass(frozen=True)
class NativeCompositorGradeEvaluator:
    evaluator_id: object
    manifest_id: object
    frozen_input: np.ndarray
    output: np.ndarray

    def evaluate_native(self, pixels):
        values = np.asarray(pixels, dtype=np.float32)
        if values.shape != self.frozen_input.shape or not np.array_equal(values, self.frozen_input):
            raise RuntimeError("Compositor input changed after its native snapshot")
        return np.array(self.output, dtype=np.float32, copy=True)


@dataclass(frozen=True)
class NativeCompositorStackEvaluator:
    evaluator_id: object
    manifest_id: object
    frozen_input: np.ndarray
    output: np.ndarray
    accepted_lut: object = None
    size: int = 65

    def __post_init__(self):
        if (self.accepted_lut is None
                or getattr(self.accepted_lut, "size", None) != self.size):
            raise TypeError("Compositor Stack capture requires the accepted final LUT")

    def apply(self, rgb):
        values = np.asarray(rgb, dtype=np.float32)
        if values.shape != self.frozen_input.shape[:-1] + (3,):
            raise ValueError("Compositor Stack input shape changed after capture")
        if not np.array_equal(values, self.frozen_input[..., :3]):
            raise RuntimeError("Compositor Stack input changed after its native snapshot")
        return np.array(self.output[..., :3], dtype=np.float32, copy=True)

    def apply_rgba(self, rgba):
        return NativeCompositorGradeEvaluator(
            self.evaluator_id, self.manifest_id, self.frozen_input, self.output,
        ).evaluate_native(rgba)


__all__ = (
    "NativeCompositorGradeEvaluator", "NativeCompositorStackEvaluator",
    "capture_compositor_signal", "unique_compositor_group_path",
)
