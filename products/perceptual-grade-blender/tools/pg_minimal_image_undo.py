"""Prepare an ordinary Image Texture New/Open -> Ctrl-Z test.

Run in a fresh Blender GUI session's Text Editor. Switch to Shader Editor,
use the test Image Texture node's New/Open button, finish that operator, and
press Ctrl-Z with the mouse over Shader Editor. Optionally redo and undo again.
Run New and Open separately in fresh sessions; save each log before restarting.
No add-on is required. The script does not load/save a project or assign an Image.
"""
import bpy
from datetime import datetime
from pathlib import Path
import tempfile
import traceback

MATERIAL_NAME = "PG Minimal Image Undo Test"
NODE_NAME = "PG Image Undo Texture"
LOG_FILE = (Path.home() / "Desktop") / "pg-minimal-image-undo.log"
_pre_image_pointer = 0


def _start_log():
    global LOG_FILE
    for candidate in (LOG_FILE, Path.home() / LOG_FILE.name,
                      Path(tempfile.gettempdir()) / LOG_FILE.name):
        try:
            candidate.write_text("", encoding="utf-8")
        except OSError as error:
            print(f"Cannot write {candidate}: {error}", flush=True)
            continue
        LOG_FILE = candidate
        return
    raise OSError("Could not create the test log on Desktop, in home or temp.")


def log(message):
    line = f"{datetime.now().astimezone().isoformat(timespec='milliseconds')} {message}"
    with LOG_FILE.open("a", encoding="utf-8") as stream:
        stream.write(line + "\n")
        stream.flush()
    print(line, flush=True)


def _node():
    """Resolve fresh after every undo boundary; retain only names/scalars."""
    material = bpy.data.materials.get(MATERIAL_NAME)
    if material is None or material.node_tree is None:
        return None
    return material.node_tree.nodes.get(NODE_NAME)


def _observe(label):
    node = _node()
    if node is None:
        log(f"{label}: test node is absent")
        return 0
    log(f"{label}: tree={node.id_data.as_pointer():#x}; node={node.as_pointer():#x}; "
        f"scene marker={bpy.context.scene.get('pg_minimal_image_undo_step')!r}")
    # Collect descriptions from current Main, not from a possibly stale link.
    live = {image.as_pointer(): (image.name, image.source, image.filepath)
            for image in bpy.data.images}
    log(f"{label}: live Images (name, source, filepath) = "
        f"{[(hex(pointer), info) for pointer, info in live.items()]!r}")
    log(f"{label}: pre-boundary Image={_pre_image_pointer:#x}; "
        f"that address is in current Main={_pre_image_pointer in live}")
    log(f"{label}: BEFORE node.image getter (a stale native link could crash here)")
    image = node.image
    log(f"{label}: AFTER node.image getter; BEFORE image.as_pointer")
    pointer = image.as_pointer() if image is not None else 0
    log(f"{label}: AFTER image.as_pointer; restored pointer={pointer:#x}; "
        f"null or in current Main={pointer == 0 or pointer in live}; "
        f"image={live.get(pointer)!r}")
    return pointer


def _boundary(label, before=False):
    global _pre_image_pointer
    try:
        if before:
            _pre_image_pointer = 0
        pointer = _observe(label)
        if before:
            _pre_image_pointer = pointer
    except Exception:
        # Python failures go in the log too. Native faults cannot be caught here.
        log(f"{label}: Python diagnostic failure:\n{traceback.format_exc()}")


def _undo_pre(*_args):
    _boundary("UNDO PRE", before=True)


def _redo_pre(*_args):
    _boundary("REDO PRE", before=True)


def _undo_post(*_args):
    _boundary("UNDO POST")


def _redo_post(*_args):
    _boundary("REDO POST")


def setup():
    if bpy.data.materials.get(MATERIAL_NAME) is not None:
        raise RuntimeError("Test already exists; restart Blender before running again.")
    _start_log()
    log(f"Blender {bpy.app.version_string}; build {bpy.app.build_hash.decode()}")
    log(f"Log file: {LOG_FILE}")
    log(f"Enabled add-ons: {list(bpy.context.preferences.addons.keys())!r}")
    log(f"Global undo before setup: {bpy.context.preferences.edit.use_global_undo}")
    bpy.context.preferences.edit.use_global_undo = True

    collection = bpy.data.collections.new("PG Minimal Image Undo Test")
    bpy.context.scene.collection.children.link(collection)
    mesh = bpy.data.meshes.new("PG Image Undo Test Mesh")
    obj = bpy.data.objects.new("PG Image Undo Test", mesh)
    collection.objects.link(obj)
    for selected in list(bpy.context.selected_objects):
        selected.select_set(False)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    material = bpy.data.materials.new(MATERIAL_NAME)
    material.use_nodes = True
    nodes = material.node_tree.nodes
    node = nodes.new("ShaderNodeTexImage")
    node.name = NODE_NAME
    node.label = "Create/Open an image, then Ctrl-Z"
    node.location = (-350, 0)
    for candidate in nodes:
        candidate.select = candidate == node
    nodes.active = node
    obj.data.materials.append(material)
    obj.active_material = material

    # Keep identical test-node topology in several baseline snapshots before
    # Blender's own image.new/image.open undoable operator runs.
    for value in (0, 1, 2):
        bpy.context.scene["pg_minimal_image_undo_step"] = value
        result = bpy.ops.ed.undo_push(message=f"Before PG Image Undo Test {value}")
        if result != {"FINISHED"}:
            raise RuntimeError(f"Baseline undo push failed: {result}")
    for handlers, callback in (
        (bpy.app.handlers.undo_pre, _undo_pre),
        (bpy.app.handlers.undo_post, _undo_post),
        (bpy.app.handlers.redo_pre, _redo_pre),
        (bpy.app.handlers.redo_post, _redo_post),
    ):
        if callback not in handlers:
            handlers.append(callback)
    _observe("BASELINE")
    log("READY: switch to Shader Editor (Object mode, unpinned); Home frames all nodes.")
    log("Click New (or Open) on the test node, finish the operator, then Ctrl-Z once.")
    log("Keep the mouse over Shader Editor for undo; expected node.image is None.")
    log("Optionally Ctrl-Shift-Z then Ctrl-Z; copy the log before another run.")


setup()
