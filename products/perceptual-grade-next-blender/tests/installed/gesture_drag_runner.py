"""Drive registered gesture handlers through Blender's native event queue."""

import addon_utils
from array import array
import asyncio
import hashlib
import importlib
import json
from pathlib import Path
import sys
import threading
import time
import traceback
from types import SimpleNamespace

import bpy


repository, report_path = map(Path, sys.argv[sys.argv.index("--") + 1:])
bpy.context.preferences.extensions.repos.new(
    name="Perceptual Grade drag test", module="pg_gesture_drag",
    custom_directory=str(repository),
)
extension = importlib.import_module("bl_ext.pg_gesture_drag.perceptual_grade")
nodes = importlib.import_module("bl_ext.pg_gesture_drag.perceptual_grade.nodes")
errors = []
assert addon_utils.enable(
    extension.__name__, default_set=False, handle_error=errors.append
) is extension
assert not errors, errors
bpy.context.preferences.edit.use_global_undo = True
bpy.context.preferences.view.show_splash = False
# This process has an isolated user configuration. A saved preference file also
# suppresses the first-run Quick Setup popup, which otherwise captures widgets.
bpy.ops.wm.save_userpref()

window_key = bpy.context.window.as_pointer()
area = next(area for area in bpy.context.window.screen.areas if area.type == "VIEW_3D")
area.type = "NODE_EDITOR"
area.ui_type = nodes.SHADER_TREE
area.spaces.active.show_region_ui = True
area_key = area.as_pointer()
material = bpy.data.materials.new("Drag Event Material")
material.use_nodes = True
bpy.context.object.active_material = material
material_name = material.name
node = nodes.create_node(material.node_tree)
material.node_tree.nodes.active = node
assert nodes.PG_OT_new_grade.execute(
    None, SimpleNamespace(pg_node=node)) == {"FINISHED"}
node_name = node.name
del node, material, area

report = {"passed": False, "cancellations": [], "deletions": []}
push_results = []
original_push = nodes._push_gesture_undo
slider_position = None


def record_push(key):
    result = original_push(key)
    push_results.append(result)
    return result


nodes._push_gesture_undo = record_push


def current_window():
    return next(window for window in bpy.context.window_manager.windows
                if window.as_pointer() == window_key)


def current_area():
    return next(area for area in current_window().screen.areas
                if area.as_pointer() == area_key)


def current_tree():
    return bpy.data.materials[material_name].node_tree


def current_node():
    return current_tree().nodes[node_name]


def state():
    return nodes._record_for(current_node())["state"]


def ready():
    return nodes.node_policy.output_allowed(state())


def wait_for(predicate, message, timeout=20):
    deadline = time.monotonic() + timeout
    while not predicate():
        assert time.monotonic() < deadline, message
        yield .05


def point():
    if slider_position is not None:
        return slider_position
    region = next(region for region in current_area().regions if region.type == "UI")
    assert region.width > 20 and region.height > 20
    return region.x + region.width // 2, region.y + 20


def send(kind, value, position=None):
    x, y = point() if position is None else position
    current_window().event_simulate(type=kind, value=value, x=x, y=y)


def press(*, activate=True):
    yield from wait_for(lambda: nodes._gesture_observer_token(window_key) is not None,
                        "Window gesture router was not registered")
    current_tree().nodes.active = current_node()
    send("MOUSEMOVE", "NOTHING")
    yield .05
    send("LEFTMOUSE", "PRESS")
    yield from wait_for(lambda: nodes._gesture_phase(window_key) == "armed",
                        "Native sidebar press did not arm the gesture")
    assert not state().gesture_active
    if activate:
        x, y = point()
        send("MOUSEMOVE", "NOTHING", (x + 6, y))
        yield from wait_for(lambda: state().gesture_active,
                            "Native mouse movement did not activate the gesture")


def release():
    _x, y = point()
    region = next(region for region in current_area().regions if region.type == "UI")
    # Release beyond the originating sidebar must still finish its gesture.
    send("LEFTMOUSE", "RELEASE", (region.x - 20, y))
    yield from wait_for(lambda: not state().gesture_active,
                        "Native release left the gesture active")
    yield .1


def test_hit_regions():
    first = SimpleNamespace(bl_idname=nodes.NODE_TYPES[nodes.SHADER_TREE])
    second = SimpleNamespace(bl_idname=nodes.STACK_NODE_TYPES[nodes.SHADER_TREE])

    def editor(active, x, y, scale=1):
        region = SimpleNamespace(type="UI", x=x, y=y,
                                 width=200 * scale, height=400 * scale)
        space = SimpleNamespace(show_region_ui=True,
                                edit_tree=SimpleNamespace(nodes=SimpleNamespace(active=active)))
        return SimpleNamespace(type="NODE_EDITOR", regions=[region],
                               spaces=SimpleNamespace(active=space))

    left, right = editor(first, 50, 100), editor(second, 800, 200, scale=2)
    window = SimpleNamespace(screen=SimpleNamespace(areas=[left, right]))
    assert nodes._gesture_target_at(None, 50, 100) is None
    assert nodes._gesture_target_at(window, 50, 100) is first
    assert nodes._gesture_target_at(window, 249, 499) is first
    assert nodes._gesture_target_at(window, 250, 100) is None
    assert nodes._gesture_target_at(window, 50, 500) is None
    assert nodes._gesture_target_at(window, 800, 200) is second
    assert nodes._gesture_target_at(window, 1199, 999) is second
    assert nodes._gesture_target_at(window, 1200, 999) is None
    left.spaces.active.show_region_ui = False
    assert nodes._gesture_target_at(window, 100, 200) is None
    left.spaces.active.show_region_ui = True
    left.regions[0].width = 1
    assert nodes._gesture_target_at(window, 50, 100) is None
    right.spaces.active.edit_tree.nodes.active = SimpleNamespace(bl_idname="ShaderNodeValue")
    assert nodes._gesture_target_at(window, 900, 300) is None


def find_exposure_slider():
    global slider_position
    region = next(region for region in current_area().regions if region.type == "UI")
    region.active_panel_category = "Perceptual Grade"
    current_area().tag_redraw()
    yield .2
    x = region.x + region.width // 2
    manager = bpy.context.window_manager
    previous_clipboard = manager.clipboard
    try:
        for y in range(region.y + region.height - 5,
                       max(region.y, region.y + region.height - 250), -3):
            send("MOUSEMOVE", "NOTHING", (x, y))
            yield .02
            with bpy.context.temp_override(window=current_window(), area=current_area(),
                                           region=region):
                if not bpy.ops.ui.copy_data_path_button.poll():
                    continue
                bpy.ops.ui.copy_data_path_button()
                if manager.clipboard.endswith("pg_linear.exposure"):
                    slider_position = x, y - 4
                    return
    finally:
        manager.clipboard = previous_clipboard
    raise AssertionError("The real Grade Exposure slider was not found in the sidebar")


def run():
    test_hit_regions()
    send("ESC", "PRESS", (10, 10))
    send("ESC", "RELEASE", (10, 10))
    yield .2
    yield from wait_for(ready, "Initial Grade did not finish preparation")
    yield from find_exposure_slider()
    initial_signature = state().applied_signature
    with bpy.context.temp_override(window=current_window(), area=current_area()):
        assert bpy.ops.ed.undo_push(message="Native drag baseline") == {"FINISHED"}

    runtime = nodes._preparation_runtime
    original_prepare = runtime.prepare
    input_sequence = [0]
    flush = threading.Event()

    async def prepare_after_newer_inputs(settings):
        start = input_sequence[0]
        # Every drag receipt lags at least three edits, independent of CPU speed.
        # The native timer requests edits at 20 Hz; release permits final demand.
        while not flush.is_set() and input_sequence[0] < start + 3:
            await asyncio.sleep(.002)
        return await original_prepare(settings)

    publications = {}
    exposures = set()
    runtime.prepare = prepare_after_newer_inputs
    try:
        yield from press()
        for index in range(1, 61):
            input_sequence[0] = index
            x, y = point()
            send("MOUSEMOVE", "NOTHING", (x + 6 + index, y))
            yield .05
            exposures.add(current_node().pg_grade.pg_linear.exposure)
            observed = state()
            assert observed.gesture_active
            assert observed.error is None, observed.error
            if (observed.applied_signature not in (None, initial_signature)
                    and observed.applied_signature != observed.desired_signature):
                assert nodes.node_policy.output_mode(observed) == "preview"
                image = current_node().node_tree[nodes.PARAMETER_BINDING]
                pixels = array("f", image.pixels[:]).tobytes()
                publications[observed.applied_signature] = hashlib.sha256(pixels).hexdigest()
        report["lagging_publications"] = len(publications)
        report["distinct_parameter_images"] = len(set(publications.values()))
        report["native_slider_changes"] = len(exposures)
        assert len(publications) >= 2, report
        assert len(set(publications.values())) >= 2, report
        assert len(exposures) >= 30, "Native slider did not process the rapid mouse movements"
        final_exposure = current_node().pg_grade.pg_linear.exposure
        # The preparation deliberately cannot settle until the held gesture ends.
        assert not ready()
        flush.set()
        yield from release()
        yield from wait_for(ready, "Released Grade did not converge to final settings")
        assert current_node().pg_grade.pg_linear.exposure == final_exposure
        report["drag_undo_pushes"] = list(push_results)
        assert push_results == [], push_results
    finally:
        flush.set()
        runtime.prepare = original_prepare

    region = next(region for region in current_area().regions if region.type == "WINDOW")
    with bpy.context.temp_override(window=current_window(), area=current_area(), region=region):
        assert bpy.ops.ed.undo() == {"FINISHED"}
    del region
    report["undo_exposure"] = current_node().pg_grade.pg_linear.exposure
    assert report["undo_exposure"] == 0.0
    yield from wait_for(ready, "Undo did not reconcile the Grade")

    # Release may already be queued when the post-press observer is installed.
    yield from wait_for(lambda: nodes._gesture_observer_token(window_key) is not None,
                        "Router did not return after undo")
    send("MOUSEMOVE", "NOTHING")
    yield .05
    send("LEFTMOUSE", "PRESS")
    send("LEFTMOUSE", "RELEASE")
    yield .2
    assert nodes._gesture_phase(window_key) not in ("armed", "finishing_armed")
    assert not state().gesture_active
    send("ESC", "PRESS")
    send("ESC", "RELEASE")
    yield .1

    for cancellation in ("ESC", "RIGHTMOUSE"):
        yield from press()
        before = 0.0
        x, y = point()
        send("MOUSEMOVE", "NOTHING", (x + 25, y))
        yield .1
        assert current_node().pg_grade.pg_linear.exposure != before
        send(cancellation, "PRESS")
        yield from wait_for(lambda: not state().gesture_active,
                            "Cancellation left a gesture active")
        send(cancellation, "RELEASE")
        send("LEFTMOUSE", "RELEASE")
        yield .1
        assert current_node().pg_grade.pg_linear.exposure == before
        assert push_results == [], push_results
        report["cancellations"].append(cancellation)

    # Deleting an armed or active node must withdraw its gesture references.
    # A same-name replacement must not inherit the deleted node's gesture.
    for phase in ("armed", "active"):
        yield from wait_for(ready, "Grade was not ready before deletion")
        survivor_name = None
        if phase == "active":
            survivor = nodes.create_node(current_tree())
            survivor.pg_grade = current_node().pg_grade
            survivor_name = survivor.name
            del survivor
        yield from press(activate=phase == "active")
        if survivor_name is not None:
            assert nodes._record_for(current_tree().nodes[survivor_name])["state"].gesture_active
        removed = current_node()
        pointer = removed.as_pointer()
        current_tree().nodes.remove(removed)
        del removed
        assert not nodes._gesture_is_active(pointer)
        assert not nodes._gesture_is_armed(pointer)
        assert nodes._gesture_identity_for_pointer(pointer) is None
        if survivor_name is not None:
            assert nodes._record_for(current_tree().nodes[survivor_name])["state"].gesture_active
        replacement = nodes.create_node(current_tree())
        assert replacement.name == node_name
        current_tree().nodes.active = replacement
        assert not nodes._record_for(replacement)["state"].gesture_active
        assert nodes.PG_OT_new_grade.execute(
            None, SimpleNamespace(pg_node=replacement)) == {"FINISHED"}
        del replacement
        # A delayed move/release from the deleted target must be harmless.
        x, y = point()
        send("MOUSEMOVE", "NOTHING", (x + 8, y))
        send("LEFTMOUSE", "RELEASE", (x - 30, y))
        yield .1
        assert not state().gesture_active
        if survivor_name is not None:
            yield from wait_for(
                lambda: not nodes._record_for(current_tree().nodes[survivor_name])["state"].gesture_active,
                "Deleting one user lost the surviving user's release",
            )
            current_tree().nodes.remove(current_tree().nodes[survivor_name])
        assert push_results == [], push_results
        report["deletions"].append(phase)
    yield from wait_for(ready, "Replacement Grade did not finish preparation")
    report["passed"] = True


steps = run()


def tick():
    try:
        return next(steps)
    except StopIteration:
        pass
    except BaseException:
        report["failure"] = traceback.format_exc()
        print(report["failure"], flush=True)
    report_path.write_text(json.dumps(report, indent=2))
    bpy.ops.wm.quit_blender("EXEC_DEFAULT")
    return None


bpy.app.timers.register(tick, first_interval=1.0)
