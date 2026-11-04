"""Drive the Grade gesture adapter directly in native Blender."""

import addon_utils
import importlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import bpy


repository, report_path = map(Path, sys.argv[sys.argv.index("--") + 1:])
bpy.context.preferences.extensions.repos.new(
    name="Perceptual Grade gesture undo test",
    module="pg_gesture_undo",
    custom_directory=str(repository),
)
extension = importlib.import_module("bl_ext.pg_gesture_undo.perceptual_grade")
nodes = importlib.import_module("bl_ext.pg_gesture_undo.perceptual_grade.nodes")
errors = []
assert addon_utils.enable(
    extension.__name__, default_set=False, handle_error=errors.append
) is extension
assert not errors, errors

bpy.context.preferences.edit.use_global_undo = True
window = bpy.context.window
assert window is not None
window_key = window.as_pointer()
area = next((area for area in window.screen.areas if area.type == "NODE_EDITOR"), None)
if area is None:
    area = next(area for area in window.screen.areas if area.type != "CONSOLE")
    area.type = "NODE_EDITOR"
area.ui_type = "ShaderNodeTree"

tree = bpy.data.node_groups.new("Gesture Undo GUI", nodes.SHADER_TREE)
tree.use_fake_user = True
tree_name = tree.name
node = nodes.create_node(tree)
node_name = node.name
assert nodes.PG_OT_new_grade.execute(
    None, SimpleNamespace(pg_node=node)) == {"FINISHED"}
grade_name = node.pg_grade.name
area.spaces.active.node_tree = tree
del node, tree

push_results = []
push_gesture_undo = nodes._push_gesture_undo


def record_push(key):
    result = push_gesture_undo(key)
    push_results.append(result)
    return result


nodes._push_gesture_undo = record_push


def current_node():
    return bpy.data.node_groups[tree_name].nodes[node_name]


def editor_context():
    window = next(item for item in bpy.context.window_manager.windows
                  if item.as_pointer() == window_key)
    area = next(item for item in window.screen.areas if item.type == "NODE_EDITOR")
    region = next(item for item in area.regions if item.type == "WINDOW")
    return window, area, region


def commit_gesture(exposure):
    node = current_node()
    nodes._arm_gesture(window_key, node, (0, 0))
    token = nodes._gesture_token(window_key)
    nodes._activate_gesture(window_key, token)
    assert node.pg_grade is not None
    assert node.pg_grade.name == grade_name
    settings = node.pg_grade.pg_linear
    settings.exposure = exposure
    del settings, node
    nodes._end_gesture(window_key, token)


def undo():
    window, area, region = editor_context()
    with bpy.context.temp_override(window=window, area=area, region=region):
        assert bpy.ops.ed.undo.poll()
        assert bpy.ops.ed.undo() == {"FINISHED"}
    del window, area, region


def snapshot():
    node = current_node()
    grade = node.pg_grade
    assert grade is not None and grade.name == grade_name
    state = {
        "grade": None if grade is None else "present",
        "exposure": node.pg_linear.exposure if grade is None else grade.pg_linear.exposure,
    }
    del grade, node
    return state


baseline = {
    "window": window_key,
    "tree": tree_name,
    "node": node_name,
}
del window, area
window, area, region = editor_context()
with bpy.context.temp_override(window=window, area=area, region=region):
    assert bpy.ops.ed.undo_push(message="Gesture undo baseline") == {"FINISHED"}
del window, area, region

commit_gesture(0.5)
assert snapshot() == {"grade": "present", "exposure": 0.5}
undo()
first_undo = snapshot()
assert first_undo == {"grade": "present", "exposure": 0.0}, first_undo

commit_gesture(0.625)
first_gesture = snapshot()
assert first_gesture == {"grade": "present", "exposure": 0.625}, first_gesture
commit_gesture(1.0)
assert snapshot() == {"grade": "present", "exposure": 1.0}
undo()
second_undo = snapshot()
assert second_undo == {"grade": "present", "exposure": 0.625}, second_undo
undo()
third_undo = snapshot()
assert third_undo == {"grade": "present", "exposure": 0.0}, third_undo

assert push_results == [True, True, True], push_results
report_path.write_text(json.dumps({
    "passed": True,
    "baseline": baseline,
    "push_results": push_results,
    "undo_states": [first_undo, second_undo, third_undo],
}, indent=2))
bpy.ops.wm.quit_blender("EXEC_DEFAULT")
