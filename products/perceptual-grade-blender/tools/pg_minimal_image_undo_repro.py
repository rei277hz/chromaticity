"""Run in a fresh Blender session's Text Editor. May intentionally crash Blender.

Wait two seconds, move the mouse over the 3D Viewport, then press Ctrl-Z.
Try Ctrl-Shift-Z, Ctrl-Z again if it survives. Restart Blender for each mode.
False: reproduce an Image assignment made outside the undo snapshots.
True: record creation + assignment together, like the normal New/Open UI path.
No Perceptual Grade installation is required. No project is loaded or saved.
"""
import bpy
from pathlib import Path

SNAPSHOT_ASSIGNMENT = False  # Change to True for the recorded-assignment control.
TREE = "Minimal Image Undo Test"
IMAGE = "Minimal Undo Image"
LOG_FILE = (Path.home() / "Desktop" if (Path.home() / "Desktop").is_dir()
            else Path.home()) / "pg-minimal-image-undo.log"


def log(message):
    with LOG_FILE.open("a", encoding="utf-8") as stream:
        stream.write(message + "\n")
        stream.flush()
    print(message, flush=True)


def check_link(*_args):
    # Resolve from current Main; do not keep an RNA reference across undo.
    tree = bpy.data.node_groups.get(TREE)
    if tree is None:
        log("Tree creation was undone; no link to inspect.")
        return
    live = {image.as_pointer() for image in bpy.data.images}
    log(f"AFTER UNDO/REDO: image exists = {IMAGE in bpy.data.images}")
    log("BEFORE node.image getter (this can crash if the native link is stale)")
    image = tree.nodes[0].image
    log("AFTER node.image getter")
    pointer = image.as_pointer() if image is not None else 0
    log(f"Link address = {pointer:#x}; valid = {pointer == 0 or pointer in live}")


def setup():
    if TREE in bpy.data.node_groups or IMAGE in bpy.data.images:
        raise RuntimeError("Restart Blender in a fresh session before rerunning this test.")
    LOG_FILE.write_text("", encoding="utf-8")
    log(f"Blender {bpy.app.version_string}, {bpy.app.build_hash.decode()}")
    log(f"SNAPSHOT_ASSIGNMENT = {SNAPSHOT_ASSIGNMENT}; log: {LOG_FILE}")
    bpy.context.preferences.edit.use_global_undo = True
    tree = bpy.data.node_groups.new(TREE, "ShaderNodeTree")
    tree.use_fake_user = True
    texture = tree.nodes.new("ShaderNodeTexImage")
    # These snapshots keep the node group identical, exercising partial undo.
    for value in (0, 1, 2):
        bpy.context.scene["minimal_undo_step"] = value
        bpy.ops.ed.undo_push(message=f"Image undo baseline {value}")
    image = bpy.data.images.new(IMAGE, 4, 4, float_buffer=True)
    texture.image = image
    log(f"Assigned new Image at {image.as_pointer():#x}")
    if SNAPSHOT_ASSIGNMENT:
        bpy.ops.ed.undo_push(message="Create and assign Image")
    bpy.app.handlers.undo_post.append(check_link)
    bpy.app.handlers.redo_post.append(check_link)
    log("READY: move the mouse over the 3D Viewport and press Ctrl-Z.")


# Let Run Script finish first; otherwise its own undo handling could change
# the experiment. The timer returns None and does not keep running.
bpy.app.timers.register(setup, first_interval=0.5)
