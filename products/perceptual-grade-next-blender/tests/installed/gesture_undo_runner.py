"""Drive the Grade gesture adapter directly in native Blender."""

import addon_utils
import faulthandler
import importlib
import json
from pathlib import Path
import sys
import time
from types import SimpleNamespace

import bpy


faulthandler.enable()
repository, report_path = map(Path, sys.argv[sys.argv.index("--") + 1:])
bpy.context.preferences.extensions.repos.new(
    name="Perceptual Grade gesture undo test",
    module="pg_gesture_undo",
    custom_directory=str(repository),
)
extension = importlib.import_module("bl_ext.pg_gesture_undo.perceptual_grade")
nodes = importlib.import_module("bl_ext.pg_gesture_undo.perceptual_grade.features.grade.host")
errors = []
assert addon_utils.enable(
    extension.__name__, default_set=False, handle_error=errors.append
) is extension
assert not errors, errors

bpy.context.preferences.edit.use_global_undo = True
bpy.context.preferences.view.show_splash = False
bpy.ops.wm.save_userpref()
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
pending_name = node.node_tree.name
pending_identity = (node.node_tree.as_pointer(), int(node.node_tree.session_uid))
del node, tree

push_results = []
push_gesture_undo = nodes._push_gesture_undo


def record_push(key):
    result = push_gesture_undo(key)
    push_results.append(result)
    return result


nodes._push_gesture_undo = record_push
pool_checks = {}
cycle_checks = 0


def assert_acyclic_groups():
    """Detect a group ID remapped to itself or a cyclic chain after undo."""
    global cycle_checks
    complete, active = set(), set()

    def visit(tree, path):
        pointer = tree.as_pointer()
        assert pointer not in active, path + (tree.name,)
        if pointer in complete:
            return
        active.add(pointer)
        for node in tree.nodes:
            child = getattr(node, "node_tree", None)
            if child is not None:
                visit(child, path + (tree.name, node.name))
        active.remove(pointer)
        complete.add(pointer)

    for tree in bpy.data.node_groups:
        visit(tree, ())
    cycle_checks += 1


def fallback_groups():
    return tuple(tree for tree in bpy.data.node_groups if tree.get(nodes.FALLBACK_KERNEL))


def assert_pending_pool():
    tree = current_node().node_tree
    assert tree.name == pending_name
    assert tree.use_fake_user
    assert tree.bl_idname == nodes.SHADER_TREE
    assert nodes.validate_fallback_instance(tree, "pending")
    assert (tree.as_pointer(), int(tree.session_uid)) == pending_identity
    pooled = fallback_groups()
    assert len(pooled) == 1, [(item.name, item.users) for item in pooled]
    assert pooled[0] == tree
    assert_acyclic_groups()


def current_node():
    return bpy.data.node_groups[tree_name].nodes[node_name]


def editor_context():
    window = next(item for item in bpy.context.window_manager.windows
                  if item.as_pointer() == window_key)
    area = next(item for item in window.screen.areas if item.type == "NODE_EDITOR")
    region = next(item for item in area.regions if item.type == "WINDOW")
    return window, area, region


def commit_gesture(exposure):
    assert_pending_pool()
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
    assert_pending_pool()


def undo():
    window, area, region = editor_context()
    with bpy.context.temp_override(window=window, area=area, region=region):
        assert bpy.ops.ed.undo.poll()
        assert bpy.ops.ed.undo() == {"FINISHED"}
    del window, area, region
    assert_pending_pool()


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
assert_pending_pool()

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


def commit_hue(name, value):
    node = current_node()
    nodes._arm_gesture(window_key, node, (0, 0))
    token = nodes._gesture_token(window_key)
    nodes._activate_gesture(window_key, token)
    setattr(node.pg_grade.pg_color, name, value)
    nodes._end_gesture(window_key, token)


# A manual edit at the identical pushed value only detaches provenance. It
# still needs its own undo checkpoint, without changing grading demand.
commit_hue("web_hue_0_0", 130.)
node = current_node()
claims_before = nodes._hue_claims(node.pg_grade.pg_color)
assert claims_before[0][1] is not None
hues_before = nodes._grade_settings(node.pg_grade, nodes._working_space()).color.web.hue_degrees
math_signature = nodes._settings_signature_for(node)
neighbor_value = node.pg_grade.pg_color.web_hue_0_1
del node
commit_hue("web_hue_0_1", neighbor_value)
node = current_node()
assert nodes._hue_claims(node.pg_grade.pg_color)[0][1] is None
assert nodes._settings_signature_for(node) == math_signature
assert nodes._grade_settings(node.pg_grade, nodes._working_space()).color.web.hue_degrees == hues_before
del node
undo()
node = current_node()
assert nodes._hue_claims(node.pg_grade.pg_color) == claims_before
assert nodes._grade_settings(node.pg_grade, nodes._working_space()).color.web.hue_degrees == hues_before
del node
undo()
node = current_node()
assert nodes._hue_claims(node.pg_grade.pg_color) == nodes.color_authoring.EMPTY_CLAIMS
assert nodes._grade_settings(node.pg_grade, nodes._working_space()).color.web.hue_degrees == ((0.,) * 6,) * 4
del node
assert push_results == [True] * 5, push_results

node = current_node()
color = node.pg_grade.pg_color
fields = ("adaptance_a_1", "adaptance_b_1")
token = nodes._begin_color_gesture(window_key, node, fields)
assert token is not None
assert nodes._edit_color_gesture(window_key, token, node, (1.0, -0.5))
assert nodes._end_color_gesture(window_key, token, node)
assert (color.adaptance_a_1, color.adaptance_b_1) == (1.0, -0.5)
assert push_results == [True] * 6, push_results
token = nodes._begin_color_gesture(window_key, node, fields)
assert token is not None
assert nodes._edit_color_gesture(window_key, token, node, (0.5, 0.25))
nodes._cancel_color_gesture(window_key, token)
assert (color.adaptance_a_1, color.adaptance_b_1) == (1.0, -0.5)
assert push_results == [True] * 6, push_results
del node, color
undo()
color = current_node().pg_grade.pg_color
assert (color.adaptance_a_1, color.adaptance_b_1) == (0.0, 0.0)
del color

# Scripted undo leaves reconciliation queued until Blender returns to its event loop.
assert nodes._undo_redo_reconcile_tick() is None
assert not nodes._lifecycle.reset_pending

# Reconciliation is idempotent, and independent nodes share the same immutable
# fallback. Removing either reader must preserve the ID held by undo history.
node = current_node()
for _ in range(8):
    assert not nodes._refresh_nodes((node,))
    assert_pending_pool()
pool_checks["repeated_reconciliation"] = True
tree = node.id_data
peer = nodes.create_node(tree)
assert peer.node_tree == node.node_tree
peer.pg_grade = node.pg_grade
assert peer.node_tree == node.node_tree
tree.nodes.remove(peer)
del peer, tree, node
assert_pending_pool()
pool_checks["shared_readers_and_removal"] = True

# Publishing a full kernel must retain the old fallback even with no native
# readers. A later pending demand must select that same persistent group.
assert not nodes._drain_preparations()
node = current_node()
assert nodes.node_policy.output_allowed(nodes._record_for(node)["state"])
assert node.node_tree.name != pending_name
pending = bpy.data.node_groups[pending_name]
assert pending.use_fake_user and pending.users == 1
assert (pending.as_pointer(), int(pending.session_uid)) == pending_identity
del pending
assert not nodes._dispatch(node, nodes.node_policy.Event("request"))
del node
assert_pending_pool()
pool_checks["pending_live_pending"] = True
assert not nodes._refresh_nodes((current_node(),))


reconcile_deadline = time.monotonic() + 30


def finish_after_undo_reconcile():
    # Undo recovery and preparation need event-loop time before shutdown.
    reconcile_pending = bpy.app.timers.is_registered(nodes._undo_redo_reconcile_tick)
    state = nodes._record_for(current_node())["state"]
    ready = nodes.node_policy.output_allowed(state)
    if reconcile_pending or not ready:
        if time.monotonic() < reconcile_deadline:
            return 0.02
    if not reconcile_pending and ready and not pool_checks.get("save_load"):
        saved_file = report_path.parent / "persistent-fallback-undo.blend"
        assert bpy.ops.wm.save_as_mainfile(filepath=str(saved_file)) == {"FINISHED"}
        assert bpy.ops.wm.open_mainfile(filepath=str(saved_file)) == {"FINISHED"}
        pending = bpy.data.node_groups[pending_name]
        assert pending.use_fake_user
        assert pending.bl_idname == nodes.SHADER_TREE
        assert nodes.validate_fallback_instance(pending, "pending")
        assert len(fallback_groups()) == 1
        del pending
        assert_acyclic_groups()
        pool_checks["save_load"] = True
        return 0.02
    assert_acyclic_groups()
    report = {
        "passed": not reconcile_pending and ready,
        "baseline": baseline,
        "push_results": push_results,
        "undo_states": [first_undo, second_undo, third_undo],
        "reconcile_pending": reconcile_pending,
        "fallback_pool": pool_checks,
        "cycle_checks": cycle_checks,
        "node_state": {
            "desired_signature": state.desired_signature,
            "applied_signature": state.applied_signature,
            "applied_quality": state.applied_quality,
            "error": state.error,
        },
    }
    if not report["passed"]:
        report["failure"] = "Undo recovery did not produce a current full-quality kernel"
    report_path.write_text(json.dumps(report, indent=2))
    print("PG_GESTURE_UNDO: requesting Blender shutdown", flush=True)
    window = bpy.context.window
    assert window is not None
    with bpy.context.temp_override(window=window):
        result = bpy.ops.wm.quit_blender("EXEC_DEFAULT")
        print(f"PG_GESTURE_UNDO: quit returned {result}", flush=True)
        assert result == {"FINISHED"}
        # Quit schedules a window event handler. Supply an event in the
        # isolated display, where no physical pointer movement wakes it.
        window.event_simulate(type="MOUSEMOVE", value="NOTHING", x=640, y=480)
        print("PG_GESTURE_UNDO: shutdown event queued", flush=True)
    return None


bpy.app.timers.register(finish_after_undo_reconcile, first_interval=0.1, persistent=True)
