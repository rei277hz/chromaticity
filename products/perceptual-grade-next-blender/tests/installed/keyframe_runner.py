"""Exercise RNA paths, context menus, and keying on actual Grade sidebar controls."""

import addon_utils
import importlib
import json
from pathlib import Path
import sys
import time
import traceback

import bpy


repository, report_path = map(Path, sys.argv[sys.argv.index("--") + 1:])
bpy.context.preferences.extensions.repos.new(
    name="Perceptual Grade keyframe test", module="pg_keyframe_gui",
    custom_directory=str(repository),
)
extension = importlib.import_module("bl_ext.pg_keyframe_gui.perceptual_grade")
nodes = importlib.import_module(extension.__name__ + ".nodes")
errors = []
assert addon_utils.enable(
    extension.__name__, default_set=False, handle_error=errors.append,
) is extension
assert not errors and not bpy.app.background, errors
bpy.context.preferences.edit.use_global_undo = True
bpy.context.preferences.view.show_splash = False
# Suppress Quick Setup as well as the splash in this isolated configuration.
bpy.ops.wm.save_userpref()

window_key = bpy.context.window.as_pointer()
area = next(area for area in bpy.context.window.screen.areas if area.type == "VIEW_3D")
area.type = "NODE_EDITOR"
area_key = area.as_pointer()
del area

MATERIAL = "Native keyframe material"
COMPOSITOR = "Native keyframe compositor"
NODE = 'Keyframe Grade "quoted"'
FIELDS = ("exposure", "fit")
tree_type = nodes.SHADER_TREE
report = {"passed": False, "cases": []}


def current_window():
    return next(window for window in bpy.context.window_manager.windows
                if window.as_pointer() == window_key)


def current_area():
    return next(area for area in current_window().screen.areas
                if area.as_pointer() == area_key)


def current_tree():
    if tree_type == nodes.SHADER_TREE:
        return bpy.data.materials[MATERIAL].node_tree
    return bpy.data.node_groups[COMPOSITOR]


def current_node():
    return current_tree().nodes[NODE]


def property_path(field):
    return current_node().path_from_id() + "." + field


def copied_property_path(field):
    prefix = "node_tree." if tree_type == nodes.SHADER_TREE else ""
    return prefix + property_path(field)


def ui_region():
    return next(region for region in current_area().regions if region.type == "UI")


def wait_for(predicate, message, timeout=20):
    deadline = time.monotonic() + timeout
    while not predicate():
        assert time.monotonic() < deadline, message
        yield .05


def send(kind, value, position, **modifiers):
    current_window().event_simulate(
        type=kind, value=value, x=position[0], y=position[1], **modifiers,
    )


def copied_path():
    manager = bpy.context.window_manager
    previous = manager.clipboard
    try:
        with bpy.context.temp_override(window=current_window(), area=current_area(),
                                       region=ui_region()):
            if not bpy.ops.ui.copy_data_path_button.poll():
                return None
            assert bpy.ops.ui.copy_data_path_button() == {"FINISHED"}
            return manager.clipboard
    finally:
        manager.clipboard = previous


def hover(field, position):
    expected = copied_property_path(field)
    region = ui_region()
    send("MOUSEMOVE", "NOTHING", (region.x - 10, position[1]))
    yield .03
    deadline = time.monotonic() + 5
    path = None
    while path != expected:
        send("MOUSEMOVE", "NOTHING", position)
        yield .05
        path = copied_path()
        assert time.monotonic() < deadline, (field, position, path, expected)
    owner = (current_area().spaces.active if tree_type == nodes.SHADER_TREE
             else current_tree())
    value = owner.path_resolve(path)
    assert value == getattr(current_node(), field), (field, path, value)


def select_grade_panel():
    area = current_area()
    area.tag_redraw()
    region = ui_region()
    if region.width <= 20 or region.height <= 20:
        return False
    try:
        # Blender populates this dynamic enum only after drawing the editor
        # with its new active node. edit_tree can already be set before then.
        region.active_panel_category = "Perceptual Grade"
    except TypeError:
        return False
    return region.active_panel_category == "Perceptual Grade"


def find_buttons():
    yield from wait_for(select_grade_panel,
                        "Grade sidebar category did not appear after editor redraw")
    region = ui_region()
    current_area().tag_redraw()
    yield .2
    expected = {copied_property_path(field): field for field in FIELDS}
    found = {}
    observed_paths = []
    x = region.x + region.width // 2
    for y in range(region.y + region.height - 5, region.y + 5, -3):
        send("MOUSEMOVE", "NOTHING", (x, y))
        yield .02
        path = copied_path()
        if path is not None and path not in observed_paths:
            observed_paths.append(path)
        field = expected.get(path)
        if field is None or field in found:
            continue
        position = x, y
        yield from hover(field, position)
        found[field] = position
        if len(found) == len(FIELDS):
            return found
    area = current_area()
    active = area.spaces.active
    try:
        with bpy.context.temp_override(window=current_window(), area=area,
                                       region=region):
            panel_poll = nodes.PG_PT_linear.poll(bpy.context)
    except Exception as error:
        panel_poll = repr(error)
    raise AssertionError((
        "Actual Grade sidebar controls were not found", tree_type, found,
        {"region": (region.x, region.y, region.width, region.height),
         "ui_type": area.ui_type,
         "edit_tree": getattr(getattr(active, "edit_tree", None), "name", None),
         "node_tree": getattr(getattr(active, "node_tree", None), "name", None),
         "active_node": getattr(getattr(getattr(active, "edit_tree", None),
                                         "nodes", None), "active", None),
         "panel_poll": panel_poll,
         "observed_paths": observed_paths},
    ))


def curves():
    animation = current_tree().animation_data
    if animation is None or animation.action is None:
        return ()
    return tuple(curve for layer in animation.action.layers for strip in layer.strips
                 if (bag := strip.channelbag(animation.action_slot)) is not None
                 for curve in bag.fcurves)


def curve(field):
    matching = [item for item in curves() if item.data_path == property_path(field)]
    assert len(matching) <= 1, (field, matching)
    return matching[0] if matching else None


def key_value(field, frame):
    channel = curve(field)
    if channel is None:
        return None
    point = next((point for point in channel.keyframe_points
                  if abs(point.co.x - frame) < 1e-6), None)
    return None if point is None else float(point.co.y)


def insert_key_from_menu(field, position, frame, value):
    assert curve(field) is None, ("Context-menu test requires an unkeyed field", field)
    assert bpy.context.scene.frame_current == frame
    setattr(current_node(), field, value)
    yield from hover(field, position)
    send("RIGHTMOUSE", "PRESS", position)
    send("RIGHTMOUSE", "RELEASE", position)
    yield .2
    # Pinned Blender 5.2.2 puts Insert Keyframe first for an unkeyed scalar.
    # Activate the actual popup item; neither an I shortcut nor a direct keying
    # operator can stand in for a missing or disabled context-menu command.
    send("HOME", "PRESS", position)
    send("HOME", "RELEASE", position)
    yield .05
    send("RET", "PRESS", position)
    send("RET", "RELEASE", position)
    yield from wait_for(
        lambda: key_value(field, frame) is not None,
        f"Right-click Insert Keyframe did not key {tree_type} {field} at {position}",
    )
    assert len(curve(field).keyframe_points) == 1
    assert abs(key_value(field, frame) - value) < 1e-6
    report["cases"][-1].setdefault("context_menu_channels", []).append({
        "field": field,
        "action_owner": current_tree().name,
        "data_path": curve(field).data_path,
        "frame": frame,
        "value": key_value(field, frame),
    })


def insert_key(field, position, frame, value):
    setattr(current_node(), field, value)
    yield from hover(field, position)
    # No explicit data path or context-button override is supplied to keying.
    send("I", "PRESS", position)
    send("I", "RELEASE", position)
    yield from wait_for(
        lambda: key_value(field, frame) is not None,
        f"Native I did not key {tree_type} {field} at frame {frame}",
    )
    assert abs(key_value(field, frame) - value) < 1e-6
    report["cases"][-1].setdefault("native_i_channels", []).append({
        "field": field,
        "action_owner": current_tree().name,
        "data_path": curve(field).data_path,
    })


def setup():
    area = current_area()
    area.ui_type = tree_type
    area.spaces.active.show_region_ui = True
    if tree_type == nodes.SHADER_TREE:
        material = bpy.data.materials.new(MATERIAL)
        material.use_nodes = True
        assert bpy.context.object is not None
        bpy.context.object.active_material = material
        tree = material.node_tree
    else:
        tree = bpy.data.node_groups.new(COMPOSITOR, tree_type)
        bpy.context.scene.compositing_node_group = tree
    node = nodes.create_per_node_node(tree)
    node.name = NODE
    area.spaces.active.node_tree = tree
    for item in tree.nodes:
        item.select = item == node
    tree.nodes.active = node
    area.spaces.active.edit_tree.nodes.active = node
    area.spaces.active.show_region_ui = True
    area.tag_redraw()


def run_case():
    case = {"tree_type": tree_type, "keyed_fields": [], "deleted_fields": []}
    report["cases"].append(case)
    bpy.context.scene.tool_settings.use_keyframe_insert_auto = False
    setup()
    yield from wait_for(
        lambda: current_area().spaces.active.edit_tree == current_tree(),
        "Node Editor did not select the test tree",
    )
    positions = yield from find_buttons()
    case["copied_paths"] = {field: property_path(field) for field in FIELDS}
    case["copy_data_paths"] = {
        field: copied_property_path(field) for field in FIELDS
    }
    case["action_owner"] = current_tree().name
    bpy.context.scene.frame_set(1)
    for field, value in zip(FIELDS, (1.25, 0.25)):
        yield from insert_key_from_menu(field, positions[field], 1, value)
    assert len(curves()) == len(FIELDS)
    # Reset the fixture so the I checks must insert their own keys.
    current_tree().animation_data_clear()
    assert not curves()
    current_area().tag_redraw()
    yield .1
    for frame, values in ((1, (0.0, -0.5)), (3, (2.0, 0.5))):
        bpy.context.scene.frame_set(frame)
        for field, value in zip(FIELDS, values):
            yield from insert_key(field, positions[field], frame, value)
    for field in FIELDS:
        assert len(curve(field).keyframe_points) == 2
        case["keyed_fields"].append(field)

    for field, value in zip(FIELDS, (2.0, 0.5)):
        position = positions[field]
        yield from hover(field, position)
        send("I", "PRESS", position, alt=True)
        send("I", "RELEASE", position, alt=True)
        yield from wait_for(lambda: key_value(field, 3) is None,
                            f"Native Alt+I did not delete {tree_type} {field}")
        assert key_value(field, 1) is not None
        case["deleted_fields"].append(field)
        yield from insert_key(field, position, 3, value)

    for channel in curves():
        for point in channel.keyframe_points:
            point.interpolation = "LINEAR"
    bpy.context.scene.frame_set(2)
    yield from wait_for(
        lambda: abs(current_node().exposure - 1.0) < 1e-6
        and abs(current_node().fit) < 1e-6,
        "Native sidebar keys did not evaluate the authoritative Grade settings",
    )

    bpy.context.scene.frame_set(5)
    bpy.context.scene.tool_settings.use_keyframe_insert_auto = True
    position = positions["exposure"]
    yield from hover("exposure", position)
    before = float(current_node().exposure)
    yield from wait_for(lambda: nodes._gesture_observer_token(window_key) is not None,
                        "Grade gesture router was not registered")
    send("LEFTMOUSE", "PRESS", position)
    yield from wait_for(lambda: nodes._gesture_phase(window_key) == "armed",
                        "Native Exposure press did not arm Auto Key")
    for offset in (8, 20, 36):
        send("MOUSEMOVE", "NOTHING", (position[0] + offset, position[1]))
        yield .08
    value = float(current_node().exposure)
    assert abs(value - before) > 1e-5, "Native Exposure drag did not change its value"
    send("LEFTMOUSE", "RELEASE", (position[0] + 36, position[1]))
    yield from wait_for(lambda: nodes._gesture_phase(window_key) is None,
                        "Native release did not finish the Auto Key gesture")
    yield from wait_for(lambda: key_value("exposure", 5) is not None,
                        "Auto Key did not use the native Exposure channel")
    assert abs(key_value("exposure", 5) - value) < 1e-6
    bpy.context.scene.tool_settings.use_keyframe_insert_auto = False
    case["auto_key_frames"] = [round(point.co.x)
                               for point in curve("exposure").keyframe_points]
    case["channel_count"] = len(curves())
    case["auto_key_channel"] = {
        "action_owner": current_tree().name,
        "data_path": curve("exposure").data_path,
    }
    assert case["auto_key_frames"] == [1, 3, 5], case
    assert case["channel_count"] == 2, case
    assert len(curve("fit").keyframe_points) == 2


def run():
    global tree_type
    send("ESC", "PRESS", (10, 10))
    send("ESC", "RELEASE", (10, 10))
    yield .2
    for tree_type in (nodes.SHADER_TREE, nodes.COMPOSITOR_TREE):
        yield from run_case()
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
