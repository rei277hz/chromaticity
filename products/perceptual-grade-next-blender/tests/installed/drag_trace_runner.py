"""Exercise drag diagnostics through native Shader and Compositor widgets."""

import addon_utils
import importlib
import json
import os
from pathlib import Path
import sys
import time
import traceback
from types import SimpleNamespace

import bpy


repository, report_path = map(Path, sys.argv[sys.argv.index("--") + 1:])
trace_directory = report_path.parent / "traces"
bpy.context.preferences.extensions.repos.new(
    name="Perceptual Grade trace test", module="pg_drag_trace",
    custom_directory=str(repository),
)
extension = importlib.import_module("bl_ext.pg_drag_trace.perceptual_grade")
nodes = importlib.import_module(extension.__name__ + ".nodes")
diagnostics = importlib.import_module(extension.__name__ + ".runtime.drag_diagnostics")
original_capture = diagnostics.Capture


def isolated_capture(nodes_module, directory=None):
    return original_capture(nodes_module, directory=directory or trace_directory)


diagnostics.Capture = isolated_capture
errors = []
assert addon_utils.enable(extension.__name__, default_set=False,
                         handle_error=errors.append) is extension
assert not errors, errors
bpy.context.preferences.view.show_splash = False
bpy.context.preferences.view.show_developer_ui = False
bpy.ops.wm.save_userpref()

window_id = bpy.context.window.as_pointer()
editor = next(area for area in bpy.context.screen.areas if area.type == "VIEW_3D")
editor.type = "NODE_EDITOR"
editor.spaces.active.show_region_ui = True
editor_id = editor.as_pointer()
display = next(area for area in bpy.context.screen.areas if area.type == "PROPERTIES")
display_id = display.as_pointer()
del editor, display

target = None
slider_position = None
measured_grade = None
measured_property = "pg_linear.exposure"
acceptances = []
completions = []
report = {"passed": False, "drags": [], "traces": [], "menu_searches": []}
original_changed = nodes._grade_changed


def record_change(grade):
    if measured_grade is not None and grade.as_pointer() == measured_grade:
        group, field = measured_property.split(".")
        acceptances.append((time.perf_counter_ns(), float(getattr(getattr(grade, group), field))))
    return original_changed(grade)


def record_compositor(*_args):
    completions.append(time.perf_counter_ns())


nodes._grade_changed = record_change
bpy.app.handlers.composite_post.append(record_compositor)


def window():
    return next(item for item in bpy.context.window_manager.windows
                if item.as_pointer() == window_id)


def area(identity):
    return next(item for item in window().screen.areas if item.as_pointer() == identity)


def state():
    return nodes._record_for(target)["state"]


def ready():
    return nodes.node_policy.output_allowed(state())


def wait_for(predicate, message, timeout=40):
    deadline = time.monotonic() + timeout
    while not predicate():
        assert time.monotonic() < deadline, message
        yield .02


def send(kind, value, position=None, *, shift=False, ctrl=False):
    x, y = slider_position if position is None else position
    window().event_simulate(type=kind, value=value, x=x, y=y, shift=shift, ctrl=ctrl)


def search_trace(start):
    # Exercise the documented user path. Calling bpy.ops directly would miss
    # an operator which is registered but absent from the F3 menu index.
    assert not bpy.context.preferences.view.show_developer_ui
    editor = area(editor_id)
    region = next(item for item in editor.regions if item.type == "WINDOW")
    position = region.x + region.width // 2, region.y + region.height // 2
    query = "perceptual grade " + ("start" if start else "stop") + " drag trace"
    send("MOUSEMOVE", "NOTHING", position)
    send("F3", "PRESS", position)
    send("F3", "RELEASE", position)
    yield .15
    send("A", "PRESS", position, ctrl=True)
    send("A", "RELEASE", position)
    send("BACK_SPACE", "PRESS", position)
    send("BACK_SPACE", "RELEASE", position)
    for character in query:
        kind = "SPACE" if character == " " else character.upper()
        window().event_simulate(type=kind, value="PRESS", unicode=character,
                                x=position[0], y=position[1])
        send(kind, "RELEASE", position)
    yield .2
    send("RET", "PRESS", position)
    send("RET", "RELEASE", position)
    yield from wait_for(lambda: (nodes._drag_trace is not None) == start,
                        "F3 menu did not execute " + query, timeout=8)
    report["menu_searches"].append({"query": query, "tree_type": editor.ui_type})
    yield .1


def new_grade(tree):
    node = nodes.create_node(tree)
    tree.nodes.active = node
    assert nodes.PG_OT_new_grade.execute(None, SimpleNamespace(pg_node=node)) == {"FINISHED"}
    node.inputs["Color"].default_value = (.2, .1, .05, 1.)
    return node


def shader_fixture():
    global target, slider_position
    slider_position = None
    editor = area(editor_id)
    editor.ui_type = nodes.SHADER_TREE
    editor.spaces.active.show_region_ui = True
    material = bpy.data.materials.new("Drag Trace Shader")
    material.use_nodes = True
    bpy.context.view_layer.objects.active.active_material = material
    target = new_grade(material.node_tree)
    shader = material.node_tree.nodes.get("Principled BSDF")
    material.node_tree.links.new(target.outputs["Color"], shader.inputs["Base Color"])
    display = area(display_id)
    display.type = "VIEW_3D"
    # A small rendered region exercises viewport draws without a full-scene render.
    display.spaces.active.shading.type = "RENDERED"


def compositor_fixture():
    global target, slider_position
    slider_position = None
    scene = bpy.context.scene
    scene.render.compositor_device = "GPU"
    large = os.environ.get("PG_DRAG_TRACE_LARGE") == "1"
    scene.render.compositor_precision = "FULL" if large else "AUTO"
    report["compositor_precision"] = scene.render.compositor_precision
    size = (2000, 1500) if large else (128, 96)
    report["compositor_size"] = size
    scene.render.resolution_x, scene.render.resolution_y = size
    scene.render.resolution_percentage = 100
    tree = bpy.data.node_groups.new("Drag Trace Compositor", nodes.COMPOSITOR_TREE)
    scene.compositing_node_group = tree
    image = bpy.data.images.new("Drag Trace Source", width=size[0], height=size[1],
                                alpha=True, float_buffer=True)
    image.generated_color = (.2, .1, .05, 1.)
    image.pack()
    source = tree.nodes.new("CompositorNodeImage")
    source.image = image
    target = new_grade(tree)
    viewer = tree.nodes.new("CompositorNodeViewer")
    tree.links.new(source.outputs["Image"], target.inputs["Color"])
    tree.links.new(target.outputs["Color"], viewer.inputs["Image"])
    tree.nodes.active = target
    editor = area(editor_id)
    editor.ui_type = nodes.COMPOSITOR_TREE
    editor.spaces.active.show_region_ui = True
    editor.spaces.active.show_backdrop = True
    area(display_id).type = "IMAGE_EDITOR"


def find_property(path="pg_linear.exposure"):
    global slider_position
    region = next(item for item in area(editor_id).regions if item.type == "UI")
    region.active_panel_category = "Perceptual Grade"
    area(editor_id).tag_redraw()
    yield .2
    x = region.x + region.width // 2
    manager = bpy.context.window_manager
    clipboard = manager.clipboard
    try:
        for y in range(region.y + region.height - 5,
                       region.y + 5, -3):
            send("MOUSEMOVE", "NOTHING", (x, y))
            yield .02
            with bpy.context.temp_override(window=window(), area=area(editor_id), region=region):
                if not bpy.ops.ui.copy_data_path_button.poll():
                    continue
                bpy.ops.ui.copy_data_path_button()
                if manager.clipboard.endswith(path):
                    slider_position = x, y - 4
                    return
    finally:
        manager.clipboard = clipboard
    raise AssertionError("Grade slider was not found: " + path)


def drag(path="pg_linear.exposure"):
    global measured_grade, measured_property
    yield from wait_for(lambda: nodes._gesture_observer_token(window_id) is not None,
                        "Gesture observer was not installed")
    measured_grade = target.pg_grade.as_pointer()
    measured_property = path
    acceptances.clear()
    send("MOUSEMOVE", "NOTHING")
    yield .05
    send("LEFT_SHIFT", "PRESS", shift=True)
    send("LEFTMOUSE", "PRESS", shift=True)
    x, y = slider_position
    requested_rate = 277
    requested_duration = (10 if target.id_data.bl_idname == nodes.COMPOSITOR_TREE
                          and os.environ.get("PG_DRAG_TRACE_LARGE") == "1" else 1)
    count = requested_rate * requested_duration
    start = time.perf_counter()
    sent = 0
    # Queue events from a fixed clock. Never wait for value acceptance or a
    # prepared result before sending the next motion. Native event-loop delays
    # form batches; the report records the achieved callback rate separately.
    while sent < count:
        due = min(count, int((time.perf_counter() - start) * requested_rate) + 1)
        for index in range(sent + 1, due + 1):
            offset = index % 192
            offset = offset if offset <= 96 else 192 - offset
            send("MOUSEMOVE", "NOTHING", (x + 6 + offset, y), shift=True)
        sent = due
        yield 1 / requested_rate
    released = time.perf_counter_ns()
    send("LEFTMOUSE", "RELEASE", (x + 6 + offset, y), shift=True)
    send("LEFT_SHIFT", "RELEASE", (x + 6 + offset, y))
    yield from wait_for(lambda: not state().gesture_active and ready(),
                        "Released Grade did not converge")
    measured_grade = None
    held = [(stamp, value) for stamp, value in acceptances if stamp <= released]
    distinct = len({value for _stamp, value in held})
    assert distinct >= 30, (target.id_data.bl_idname, distinct, len(held))
    group, field = path.split(".")
    descriptor = getattr(target.pg_grade, group).bl_rna.properties[field]
    assert all(descriptor.hard_min < value < descriptor.hard_max for _stamp, value in held)
    report["drags"].append({
        "property": path,
        "completions_before_release": sum(start * 1e9 <= stamp <= released for stamp in completions),
        "tree_type": target.id_data.bl_idname,
        "requested_hz": requested_rate,
        "requested_duration_seconds": requested_duration,
        "held_seconds": released / 1e9 - start,
        "injected": sent,
        "accepted_before_release": len(held),
        "distinct_values": distinct,
        "accepted_hz": ((len(held) - 1) * 1e9 / (held[-1][0] - held[0][0])
                        if len(held) > 1 else 0.),
    })
    yield .15


def read_trace(path):
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    assert rows[0]["event"] == "session_start", rows[:1]
    assert rows[-1]["event"] == "session_stop", rows[-1:]
    assert rows[-1]["fields"]["error"] is None, rows[-1]
    assert rows[-1]["fields"]["dropped"] == 0, rows[-1]
    sequences = [row["seq"] for row in rows]
    assert sequences == sorted(set(sequences)), sequences
    return rows


def stop_capture():
    capture = nodes._drag_trace
    assert capture is not None
    assert bpy.app.timers.is_registered(capture.timer)
    assert len(capture.draw_handlers) == 2
    yield from search_trace(False)
    assert nodes._drag_trace is None
    assert capture.closed
    assert not bpy.app.timers.is_registered(capture.timer)
    assert not capture.draw_handlers
    assert capture.runtime.on_event is capture.previous_observer
    assert capture.preparer.on_timing is capture.previous_timing


def run():
    send("ESC", "PRESS", (10, 10))
    send("ESC", "RELEASE", (10, 10))
    shader_fixture()
    yield from wait_for(ready, "Shader Grade did not initialize")
    yield from find_property()
    yield from search_trace(True)
    # A callback suppressed before preparation must still leave diagnostic
    # evidence. Restore immediately; this is not part of the measured drag.
    settings = target.pg_grade.pg_linear
    before = settings.exposure
    with nodes._suspend(settings):
        settings.exposure = .123
    settings.exposure = before
    yield .15
    yield from drag()
    for path in ("pg_linear.cr_balance", "pg_tone.fit"):
        yield from find_property(path)
        yield from drag(path)

    compositor_fixture()
    previous_completions = len(completions)
    yield from wait_for(lambda: ready() and len(completions) > previous_completions,
                        "Compositor Viewer did not initialize")
    area(display_id).spaces.active.image = bpy.data.images["Viewer Node"]
    area(editor_id).spaces.active.show_backdrop = False
    yield from find_property()
    yield from drag()
    for path in ("pg_linear.cr_balance", "pg_tone.fit"):
        yield from find_property(path)
        yield from drag(path)
    yield from wait_for(lambda: not bpy.app.is_job_running("COMPOSITE"),
                        "Compositor job did not finish")
    yield from stop_capture()
    first_files = tuple(trace_directory.glob("*.jsonl"))
    assert len(first_files) == 1, first_files
    first = first_files[0]
    rows = read_trace(first)
    kinds = {row["event"] for row in rows}
    assert "diagnostic_error" not in kinds, [row for row in rows if row["event"] == "diagnostic_error"]
    assert {"ui_event", "property_callback", "node_transition", "heartbeat"} <= kinds, kinds
    assert any("preparation" in kind for kind in kinds), kinds
    assert any("publication" in kind for kind in kinds), kinds
    assert {"compositor_pre", "compositor_post", "compositor_snapshot",
            "compositor_receipt"} <= kinds, kinds
    for row in rows:
        if row["event"] in {"compositor_snapshot", "compositor_receipt"}:
            assert isinstance(row["fields"]["generations"], list), row
            assert all(len(pair) == 2 and all(isinstance(value, int) for value in pair)
                       for pair in row["fields"]["generations"]), row
    callbacks = [row["fields"] for row in rows if row["event"] == "property_callback"]
    assert any(fields.get("syncing") for fields in callbacks), callbacks[:2]
    assert any(row["event"] == "property_skipped" and row["fields"].get("reason") == "syncing"
               for row in rows)
    for tree_type in (nodes.SHADER_TREE, nodes.COMPOSITOR_TREE):
        values = {fields["values"]["exposure"] for fields in callbacks
                  if fields.get("context", {}).get("tree_type") == tree_type
                  and "exposure" in fields.get("values", {})}
        assert len(values) >= 30, (tree_type, len(values), callbacks[:2])
    serialized = json.dumps(rows)
    assert nodes.SHADER_TREE in serialized and nodes.COMPOSITOR_TREE in serialized
    assert "desired_signature" in serialized and "applied_signature" in serialized
    report["traces"].append({"events": len(rows), "kinds": sorted(kinds)})

    # Stopping must make the old file inert. Starting again must use a new file
    # and remain usable, including after both editor types were visited.
    old_contents = first.read_bytes()
    target.pg_grade.pg_linear.exposure += .05
    yield from wait_for(ready, "Untraced edit did not finish")
    yield .1
    assert first.read_bytes() == old_contents
    yield from search_trace(True)
    target.pg_grade.pg_linear.exposure += .05
    yield from wait_for(ready, "Second trace edit did not finish")
    yield .15
    yield from stop_capture()
    second_files = set(trace_directory.glob("*.jsonl")) - set(first_files)
    assert len(second_files) == 1, second_files
    second = second_files.pop()
    second_rows = read_trace(second)
    assert not any(row["event"] == "diagnostic_error" for row in second_rows), second_rows
    assert any(row["event"] == "property_callback" for row in second_rows)
    assert first.read_bytes() == old_contents
    report["traces"].append({"events": len(second_rows)})
    nodes.register()
    menu_draws = bpy.types.TOPBAR_MT_help.draw._draw_funcs
    assert menu_draws.count(nodes.draw_trace_menu) == 1, menu_draws
    addon_utils.disable(extension.__name__, default_set=False, handle_error=errors.append)
    assert not errors, errors
    assert nodes.draw_trace_menu not in bpy.types.TOPBAR_MT_help.draw._draw_funcs
    report["menu_registration_cleanup"] = True
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
    finally:
        if report.get("passed") or report.get("failure"):
            diagnostics.Capture = original_capture
            nodes._grade_changed = original_changed
            if record_compositor in bpy.app.handlers.composite_post:
                bpy.app.handlers.composite_post.remove(record_compositor)
    report_path.write_text(json.dumps(report, indent=2))
    bpy.ops.wm.quit_blender("EXEC_DEFAULT")
    return None


bpy.app.timers.register(tick, first_interval=1.)
