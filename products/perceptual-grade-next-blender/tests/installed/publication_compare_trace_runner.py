"""Exercise publication diagnostics through real Blender F3 search."""

import addon_utils
import importlib
import json
from pathlib import Path
import sys
import time
import traceback

import bpy


repository, report_path = map(Path, sys.argv[sys.argv.index("--") + 1:])
trace_directory = report_path.parent / "traces"
bpy.context.preferences.extensions.repos.new(
    name="Publication Compare trace test", module="pg_publication_compare",
    custom_directory=str(repository),
)
extension = importlib.import_module(
    "bl_ext.pg_publication_compare.grade_publication_compare"
)
errors = []
assert addon_utils.enable(extension.__name__, default_set=False,
                         handle_error=errors.append) is extension
assert not errors, errors
nodes = importlib.import_module(extension.__name__ + ".nodes")
original_capture = nodes.Capture


def isolated_capture(module, directory=None):
    return original_capture(module, directory=str(trace_directory))


nodes.Capture = isolated_capture
bpy.context.preferences.view.show_developer_ui = False
bpy.context.preferences.view.show_splash = False
window_id = bpy.context.window.as_pointer()
editor = next(area for area in bpy.context.screen.areas if area.type == "VIEW_3D")
editor.type = "NODE_EDITOR"
editor.spaces.active.show_region_ui = True
editor_id = editor.as_pointer()
del editor

report = {"passed": False, "searches": [], "publications": []}
strategies = (
    ("versioned", nodes.VERSIONED_IDS),
    ("original", nodes.ORIGINAL_IDS),
    ("banked", nodes.BANKED_IDS),
)


def window():
    return next(item for item in bpy.context.window_manager.windows
                if item.as_pointer() == window_id)


def area(identity):
    return next(item for item in window().screen.areas if item.as_pointer() == identity)


def wait_for(predicate, message, timeout=20):
    deadline = time.monotonic() + timeout
    while not predicate():
        assert time.monotonic() < deadline, message
        yield .02


def send(kind, value, position):
    window().event_simulate(type=kind, value=value, x=position[0], y=position[1])


def search_operator(start):
    editor = area(editor_id)
    region = next(item for item in editor.regions if item.type == "WINDOW")
    position = region.x + region.width // 2, region.y + region.height // 2
    command = "start" if start else "stop"
    query = "publication compare " + command + " drag trace"
    send("MOUSEMOVE", "NOTHING", position)
    send("F3", "PRESS", position)
    send("F3", "RELEASE", position)
    yield .15
    send("A", "PRESS", position)
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
    expected = start
    yield from wait_for(lambda: (nodes._publication_trace is not None) == expected,
                        "F3 search did not execute " + query, timeout=8)
    report["searches"].append(query)
    yield .1


def create_node(tree_type, node_type, name):
    if tree_type == nodes.SHADER_TREE:
        material = bpy.data.materials.new(name)
        material.use_nodes = True
        active = bpy.context.view_layer.objects.active
        assert active is not None
        active.active_material = material
        outer = material.node_tree
    else:
        outer = bpy.data.node_groups.new(name, tree_type)
        bpy.context.scene.compositing_node_group = outer
    node = outer.nodes.new(node_type)
    outer.nodes.active = node
    editor = area(editor_id)
    editor.ui_type = tree_type
    editor.spaces.active.show_region_ui = True
    return outer, node, node.node_tree


def find_exposure_slider():
    editor = area(editor_id)
    region = next(item for item in editor.regions if item.type == "UI")
    editor.tag_redraw()
    yield .2
    region.active_panel_category = "Publication"
    editor.tag_redraw()
    yield .1
    x = region.x + region.width // 2
    manager = bpy.context.window_manager
    clipboard = manager.clipboard
    try:
        for y in range(region.y + region.height - 5, region.y + 5, -3):
            send("MOUSEMOVE", "NOTHING", (x, y))
            yield .02
            with bpy.context.temp_override(window=window(), area=editor, region=region):
                if not bpy.ops.ui.copy_data_path_button.poll():
                    continue
                bpy.ops.ui.copy_data_path_button()
                if manager.clipboard.endswith("pg_publication.exposure"):
                    return x, y - 4
    finally:
        manager.clipboard = clipboard
    raise AssertionError("Publication Exposure slider was not found")


def drag_exposure_slider(tree, position):
    before = float(tree.pg_publication.exposure)
    x, y = position
    send("MOUSEMOVE", "NOTHING", position)
    yield .05
    send("LEFTMOUSE", "PRESS", position)
    for offset in (8, 16, 24, 32, 40, 48):
        send("MOUSEMOVE", "NOTHING", (x + offset, y))
        yield .02
    send("LEFTMOUSE", "RELEASE", (x + 48, y))
    yield .1
    after = float(tree.pg_publication.exposure)
    assert after != before, (before, after, position)
    return after


def run():
    send("ESC", "PRESS", (10, 10))
    send("ESC", "RELEASE", (10, 10))
    editor = area(editor_id)
    editor.ui_type = nodes.SHADER_TREE
    yield from search_operator(True)
    capture = nodes._publication_trace
    assert capture is not None
    assert bpy.app.timers.is_registered(capture.timer)
    trace_path = capture.recorder.path

    for tree_type, tree_name in ((nodes.SHADER_TREE, "Shader"),
                                 (nodes.COMPOSITOR_TREE, "Compositor")):
        for variant, node_ids in strategies:
            node_type = node_ids[tree_type]
            _outer, _node, kernel = create_node(
                tree_type, node_type, "Trace " + tree_name + " " + variant,
            )
            assert kernel is not None
            old_bank = nodes._active_bank(kernel)
            slider = yield from find_exposure_slider()
            exposure = yield from drag_exposure_slider(kernel, slider)
            assert abs(float(nodes._helper_image(kernel).pixels[0]) - exposure) < 1e-6
            assert not kernel.get("_pg_publication_error"), (
                tree_type, variant, kernel.get("_pg_publication_error"),
            )
            if variant == "banked":
                assert nodes._active_bank(kernel) != old_bank
            report["publications"].append({"tree_type": tree_type,
                                           "variant": variant,
                                           "exposure": exposure})

    yield .2
    yield from search_operator(False)
    assert nodes._publication_trace is None
    assert capture.closed
    assert not bpy.app.timers.is_registered(capture.timer)

    rows = [json.loads(line) for line in trace_path.read_text().splitlines()]
    assert rows[0]["event"] == "session_start", rows[:1]
    assert rows[-1]["event"] == "session_stop", rows[-1:]
    footer = rows[-1]["fields"]
    assert footer["error"] is None, footer
    assert footer["dropped"] == 0, footer
    sequences = [row["seq"] for row in rows]
    assert sequences == sorted(set(sequences)), sequences

    callbacks = [row["fields"] for row in rows if row["event"] == "slider_callback"]
    stages = [row["fields"] for row in rows
              if row["event"] == "publication_stage_finished"]
    expected = {(tree_type, variant) for tree_type in
                (nodes.SHADER_TREE, nodes.COMPOSITOR_TREE)
                for variant, _node_ids in strategies}
    observed_callbacks = {(item["tree_type"], item["variant"])
                         for item in callbacks
                         if any(item.get("exposure") == publication["exposure"]
                                and item.get("tree_type") == publication["tree_type"]
                                and item.get("variant") == publication["variant"]
                                for publication in report["publications"])}
    observed_stages = {(item["tree_type"], item["variant"])
                       for item in stages if item.get("error") is None}
    assert expected <= observed_callbacks, (expected, observed_callbacks, callbacks)
    assert expected <= observed_stages, (expected, observed_stages, stages)
    assert any(row["event"] == "publication_reconciled" for row in rows), rows[-20:]
    assert not any(row["event"] == "publication_error" for row in rows), [
        row for row in rows if row["event"] == "publication_error"
    ]
    report["trace"] = {"path": str(trace_path), "events": len(rows),
                       "dropped": footer["dropped"],
                       "callback_pairs": sorted([list(pair) for pair in observed_callbacks]),
                       "stage_pairs": sorted([list(pair) for pair in observed_stages])}

    menu_draws = bpy.types.TOPBAR_MT_help.draw._draw_funcs
    assert menu_draws.count(nodes._draw_trace_menu) == 1, menu_draws
    extension.unregister()
    assert nodes._draw_trace_menu not in bpy.types.TOPBAR_MT_help.draw._draw_funcs
    assert not bpy.app.timers.is_registered(capture.timer)
    report["cleanup"] = True
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
            nodes.Capture = original_capture
            report_path.write_text(json.dumps(report, indent=2))
            bpy.ops.wm.quit_blender("EXEC_DEFAULT")
            return None
    return .02


bpy.app.timers.register(tick, first_interval=1.0)
