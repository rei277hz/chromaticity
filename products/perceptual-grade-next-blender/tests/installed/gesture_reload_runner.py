"""Drag real sidebar widgets after file loads in all three evaluation contexts.

Each load starts a fresh timer driver and resolves its RNA objects again. Only
small parameter images are read during dragging; Viewer/framebuffer readback
must not supply synchronization that could hide a publication failure.
"""

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
from bpy.app.handlers import persistent


repository, report_path = map(Path, sys.argv[sys.argv.index("--") + 1:])
bpy.context.preferences.extensions.repos.new(
    name="Perceptual Grade reload test", module="pg_gesture_reload",
    custom_directory=str(repository),
)
extension = importlib.import_module("bl_ext.pg_gesture_reload.perceptual_grade")
nodes = importlib.import_module(extension.__name__ + ".nodes")
errors = []
assert addon_utils.enable(extension.__name__, default_set=True,
                         handle_error=errors.append) is extension
assert not errors, errors
bpy.context.preferences.view.show_splash = False
bpy.ops.wm.save_userpref()

MATERIAL = "Reload Drag Material"
COMPOSITOR = "Reload Drag Compositor"
GRADE = "Reload Drag Grade"
MODES = ("MATERIAL", "RENDERED", "COMPOSITOR")
mode_index = 0
previous_token = 0
report = {"passed": False, "loads": [], "drags": [], "router_before_repair": []}


def current_window():
    return bpy.context.window_manager.windows[0]


def current_area():
    return next(area for area in current_window().screen.areas
                if area.type == "NODE_EDITOR")


def current_tree():
    if MODES[mode_index] == "COMPOSITOR":
        return bpy.data.node_groups[COMPOSITOR]
    return bpy.data.materials[MATERIAL].node_tree


def current_node():
    return current_tree().nodes[GRADE]


def state():
    return nodes._record_for(current_node())["state"]


def ready():
    return nodes.node_policy.output_allowed(state())


def wait_for(predicate, message, timeout=40):
    deadline = time.monotonic() + timeout
    while not predicate():
        assert time.monotonic() < deadline, (message, report)
        yield .05


def observers_ready():
    windows = {window.as_pointer() for window in bpy.context.window_manager.windows}
    observers = nodes._gesture_state.observers
    return (len(observers) == len(windows)
            and {item.window_id for item in observers} == windows
            and all(item.current_token is not None and item.pending_token is None
                    for item in observers))


def check_observers():
    assert bpy.app.timers.is_registered(nodes._gesture_router_tick)
    assert observers_ready(), nodes._gesture_state
    before = nodes._gesture_state.observers
    # Repeated reconciliation must not add another current observer.
    for _ in range(3):
        nodes._ensure_gesture_router_timer()
        nodes._gesture_router_tick()
    assert nodes._gesture_state.observers == before
    return max(item.current_token for item in before)


def configure_mode():
    area = current_area()
    area.ui_type = (nodes.COMPOSITOR_TREE if MODES[mode_index] == "COMPOSITOR"
                    else nodes.SHADER_TREE)
    area.spaces.active.show_region_ui = True
    if MODES[mode_index] == "COMPOSITOR":
        area.spaces.active.show_backdrop = True
    for view in current_window().screen.areas:
        if view.type == "VIEW_3D":
            view.spaces.active.shading.type = (
                "SOLID" if MODES[mode_index] == "COMPOSITOR" else MODES[mode_index])
    current_tree().nodes.active = current_node()
    area.tag_redraw()


def setup():
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_EEVEE"
    scene.render.resolution_x, scene.render.resolution_y = 128, 96
    scene.render.resolution_percentage = 100
    scene.render.compositor_device = "GPU"
    scene.render.compositor_precision = "AUTO"
    area = next(area for area in current_window().screen.areas if area.type == "VIEW_3D")
    area.type = "NODE_EDITOR"
    preview = next(area for area in current_window().screen.areas if area.type == "PROPERTIES")
    preview.type = "VIEW_3D"

    material = bpy.data.materials.new(MATERIAL)
    material.use_nodes = True
    bpy.context.object.active_material = material
    shader = nodes.create_node(material.node_tree)
    shader.name = GRADE
    assert nodes.PG_OT_new_grade.execute(None, SimpleNamespace(pg_node=shader)) == {"FINISHED"}
    shader.inputs["Color"].default_value = (.2, .1, .05, 1)
    emission = material.node_tree.nodes.new("ShaderNodeEmission")
    material.node_tree.links.new(shader.outputs["Color"], emission.inputs["Color"])
    output = next(node for node in material.node_tree.nodes
                  if node.bl_idname == "ShaderNodeOutputMaterial")
    material.node_tree.links.new(emission.outputs["Emission"], output.inputs["Surface"])

    tree = bpy.data.node_groups.new(COMPOSITOR, nodes.COMPOSITOR_TREE)
    scene.compositing_node_group = tree
    source_image = bpy.data.images.new("Reload Drag Source", width=128, height=96,
                                       alpha=True, float_buffer=True)
    source_image.generated_color = (.2, .1, .05, .625)
    source_image.pack()
    source = tree.nodes.new("CompositorNodeImage")
    source.image = source_image
    compositor = nodes.create_node(tree)
    compositor.name = GRADE
    assert nodes.PG_OT_new_grade.execute(
        None, SimpleNamespace(pg_node=compositor)) == {"FINISHED"}
    viewer = tree.nodes.new("CompositorNodeViewer")
    tree.links.new(source.outputs["Image"], compositor.inputs["Color"])
    tree.links.new(compositor.outputs["Color"], viewer.inputs["Image"])
    configure_mode()


def send(kind, value, position):
    current_window().event_simulate(type=kind, value=value, x=position[0], y=position[1])


def find_exposure_slider():
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
                    return x, y - 4
    finally:
        manager.clipboard = previous_clipboard
    raise AssertionError("The real Grade Exposure slider was not found after loading")


def drag():
    # All identities below are acquired after this file load, never carried from
    # the driver that saved or reopened the preceding file.
    window_key = current_window().as_pointer()
    grade_key = current_node().pg_grade.as_pointer()
    yield from wait_for(ready, "Loaded Grade did not finish preparation")
    x, y = yield from find_exposure_slider()
    baseline = state().applied_signature
    runtime = nodes._preparation_runtime
    original_prepare, original_changed = runtime.prepare, nodes._grade_changed
    accepted_inputs = [0]
    flush = threading.Event()

    def count_changed(grade):
        if grade.as_pointer() == grade_key:
            accepted_inputs[0] += 1
        return original_changed(grade)

    async def prepare_after_newer_inputs(settings):
        start = accepted_inputs[0]
        # Count actual accepted property callbacks, not injected mouse events.
        while not flush.is_set() and accepted_inputs[0] < start + 3:
            await asyncio.sleep(.002)
        return await original_prepare(settings)

    publications, exposures = {}, set()
    runtime.prepare, nodes._grade_changed = prepare_after_newer_inputs, count_changed
    try:
        send("MOUSEMOVE", "NOTHING", (x, y))
        yield .05
        send("LEFTMOUSE", "PRESS", (x, y))
        yield from wait_for(lambda: nodes._gesture_phase(window_key) == "armed",
                            "Loaded sidebar press did not arm a gesture")
        send("MOUSEMOVE", "NOTHING", (x + 6, y))
        yield from wait_for(lambda: state().gesture_active,
                            "Loaded sidebar movement did not activate a gesture")
        for index in range(1, 61):
            send("MOUSEMOVE", "NOTHING", (x + 6 + index, y))
            yield .05
            exposures.add(current_node().pg_grade.pg_linear.exposure)
            observed = state()
            assert observed.gesture_active
            assert observed.error is None, observed.error
            if (observed.applied_signature not in (None, baseline)
                    and observed.applied_signature != observed.desired_signature):
                assert nodes.node_policy.output_mode(observed) == "preview"
                kernel = current_node().node_tree
                active = kernel[nodes.PARAMETER_ACTIVE_BANK]
                banks = tuple(kernel[key] for key in nodes.PARAMETER_BANK_BINDINGS)
                selector = next(node for node in kernel.nodes
                                if node.get(nodes.PARAMETER_SELECTOR))
                selected = (selector.outputs["Value"].default_value
                            if kernel.bl_idname == nodes.SHADER_TREE
                            else selector.inputs[0].default_value)
                assert int(round(float(selected))) == active
                parameter = banks[active]
                readers = [node for node in kernel.nodes if node.get(nodes.PARAMETER_READER)]
                mapped = {node.get(nodes.PARAMETER_READER_BANK): node.image
                          for node in readers}
                assert set(mapped) == {0, 1}
                assert all(mapped[bank] == banks[bank] for bank in (0, 1))
                publications[observed.applied_signature] = hashlib.sha256(
                    array("f", parameter.pixels[:]).tobytes()).hexdigest()
        result = {"mode": MODES[mode_index], "lagging_publications": len(publications),
                  "distinct_parameter_images": len(set(publications.values())),
                  "native_slider_changes": len(exposures),
                  "accepted_property_callbacks": accepted_inputs[0]}
        report["drags"].append(result)
        assert result["lagging_publications"] >= 2, result
        assert result["distinct_parameter_images"] >= 2, result
        assert result["native_slider_changes"] >= 30, result
        assert not ready(), "Deliberately lagged preparation settled before release"
        final_exposure = current_node().pg_grade.pg_linear.exposure
        flush.set()
        region = next(region for region in current_area().regions if region.type == "UI")
        send("LEFTMOUSE", "RELEASE", (region.x - 20, y))
        yield from wait_for(lambda: not state().gesture_active,
                            "Loaded sidebar release left a gesture active")
        yield from wait_for(ready, "Released drag did not converge to the latest settings")
        assert current_node().pg_grade.pg_linear.exposure == final_exposure
        assert state().applied_signature == state().desired_signature
    finally:
        flush.set()
        runtime.prepare, nodes._grade_changed = original_prepare, original_changed


def finish(error=None):
    if error is not None:
        report["error"] = error
    report_path.write_text(json.dumps(report, indent=2))
    bpy.ops.wm.quit_blender("EXEC_DEFAULT")


def start_driver(steps):
    def tick():
        try:
            return next(steps)
        except StopIteration:
            return None
        except BaseException:
            finish(traceback.format_exc())
            return None
    bpy.app.timers.register(tick, first_interval=.2)


def request_reopen():
    # The current generator finishes before open_mainfile. Blender can remove
    # its nonpersistent timer without leaving a competing pre-load driver.
    def reopen():
        global previous_token
        try:
            previous_token = check_observers()
            path = report_path.parent / (MODES[mode_index].lower() + ".blend")
            bpy.ops.wm.save_as_mainfile(filepath=str(path))
            if mode_index == 1:
                bpy.app.timers.unregister(nodes._gesture_router_tick)
            if mode_index == 2:
                gate = nodes._grade_resources.gate
                original_reset = gate.reset

                def defer_once():
                    gate.reset = original_reset
                    raise nodes.PublicationDeferred("Injected one-load reset deferral")

                gate.reset = defer_once
            bpy.ops.wm.open_mainfile(filepath=str(path))
        except BaseException:
            finish(traceback.format_exc())
        return None
    bpy.app.timers.register(reopen, first_interval=.1)


@persistent
def before_load_repair(_filepath):
    try:
        registered = bpy.app.timers.is_registered(nodes._gesture_router_tick)
        report["router_before_repair"].append(registered)
        # The normal timer must survive loading itself. The separate missing
        # timer case verifies repair without masking loss of persistence.
        assert registered == (mode_index != 1), (MODES[mode_index], registered)
    except BaseException:
        finish(traceback.format_exc())


@persistent
def loaded(_filepath):
    try:
        snapshot = {"mode": MODES[mode_index], "previous_token": previous_token,
                    "router_timer": bpy.app.timers.is_registered(nodes._gesture_router_tick),
                    "pending_reset": nodes._node_reset_pending,
                    "observer_count": len(nodes._gesture_state.observers)}
        report["loads"].append(snapshot)
        assert snapshot["router_timer"], snapshot
        assert snapshot["observer_count"] == 0, snapshot
        if mode_index == 2:
            assert snapshot["pending_reset"], snapshot
            original_dispatch = nodes._dispatch_gesture

            def forbidden_dispatch(_event):
                raise AssertionError("Router attempted observation during pending reset")

            nodes._dispatch_gesture = forbidden_dispatch
            try:
                assert nodes._gesture_router_tick() == .1
            finally:
                nodes._dispatch_gesture = original_dispatch
            snapshot["pending_router_guarded"] = True
        start_driver(after_load())
    except BaseException:
        finish(traceback.format_exc())


def after_load():
    global mode_index
    yield from wait_for(lambda: not nodes._node_reset_pending and observers_ready(),
                        "Loading did not restore exactly one observer per window")
    token = check_observers()
    assert token > previous_token, (token, previous_token)
    report["loads"][-1]["restored_token"] = token
    yield from drag()
    if mode_index + 1 < len(MODES):
        mode_index += 1
        configure_mode()
        yield from wait_for(ready, "Next evaluation context did not become ready")
        yield from wait_for(nodes._grade_resources.gate.quiescent,
                            "Next context did not reach a safe save/load boundary")
        request_reopen()
        return

    before_disable = check_observers()
    yield from wait_for(nodes._grade_resources.gate.quiescent,
                        "Cannot disable while native evaluation is active")
    addon_utils.disable(extension.__name__, default_set=True, handle_error=errors.append)
    assert not errors, errors
    assert not bpy.app.timers.is_registered(nodes._gesture_router_tick)
    assert not nodes._gesture_state.observers and not nodes._gesture_state.gestures
    report["disabled_router_removed"] = True
    assert addon_utils.enable(extension.__name__, default_set=True,
                             handle_error=errors.append) is extension
    assert not errors, errors
    yield from wait_for(observers_ready, "Re-enable did not restore window observation")
    assert check_observers() > before_disable
    yield from wait_for(ready, "Re-enable did not reconcile the Grade")
    report["reenabled_router_restored"] = True
    report["passed"] = True
    finish()


def initial():
    setup()
    yield from wait_for(lambda: ready() and observers_ready(),
                        "Initial fixture did not become ready")
    yield from wait_for(nodes._grade_resources.gate.quiescent,
                        "Initial fixture did not reach a safe save/load boundary")
    request_reopen()


bpy.app.handlers.load_post.insert(0, before_load_repair)
bpy.app.handlers.load_post.append(loaded)
start_driver(initial())
