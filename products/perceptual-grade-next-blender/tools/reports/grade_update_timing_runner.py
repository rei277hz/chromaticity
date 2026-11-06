"""Measure the installed Grade path in an actual Blender Shading workspace."""

import importlib
import json
import math
from pathlib import Path
import sys
import threading
import time
import traceback


def main():
    import addon_utils
    import bpy
    import gpu

    config_path = Path(sys.argv[sys.argv.index("--") + 1])
    config = json.loads(config_path.read_text(encoding="utf8"))
    output = Path(config["report"])
    started = time.perf_counter()
    report = {
        "schema": 1, "completed": False,
        "blender": bpy.app.version_string,
        "blender_build": bpy.app.build_hash.decode("ascii", errors="replace"),
        "profile": {name: config[name] for name in
                    ("stage", "viewport", "duration", "interval_ms", "warmup", "timeout")},
        "edits": [], "preparations": [], "received_results": [],
        "texture_publications": [], "ui_heartbeats": [], "viewport_draws": [],
        "initialization": {},
        "limitations": [
            "RNA edits exercise the installed property callbacks and gesture adapter, not physical mouse-event delivery.",
            "Viewport POST_PIXEL callbacks measure draw activity, not signature-verified rendered output or physical presentation.",
            "The Linux fixture uses Mesa llvmpipe, which executes GPU work on CPU cores.",
            "The edit and heartbeat timers are deliberately unthrottled by default; their observer overhead is included.",
        ],
    }

    def stamp():
        return time.perf_counter() - started

    def save():
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf8")

    repository = Path(config["repository"])
    bpy.context.preferences.extensions.repos.new(
        name="Perceptual Grade update timing", module="pg_grade_update_timing",
        custom_directory=str(repository),
    )
    extension = importlib.import_module("bl_ext.pg_grade_update_timing.perceptual_grade")
    errors = []
    enabled = addon_utils.enable(extension.__name__, default_set=False, handle_error=errors.append)
    if enabled is not extension or errors:
        raise RuntimeError("Could not enable the packaged extension: " + repr(errors))
    nodes = importlib.import_module(extension.__package__ + ".nodes")
    if not callable(getattr(nodes, "_write_grade_parameters", None)):
        raise RuntimeError("This report requires the persistent Grade parameter-texture path")

    window = bpy.context.window
    if window is None:
        raise RuntimeError("A native Blender window is required")
    workspace = bpy.data.workspaces.get("Shading")
    if workspace is None:
        raise RuntimeError("Factory startup did not provide the Shading workspace")
    window.workspace = workspace
    def run_workspace():
        area = next((item for item in window.screen.areas if item.type == "NODE_EDITOR"), None)
        viewport = next((item for item in window.screen.areas if item.type == "VIEW_3D"), None)
        if area is None or viewport is None:
            raise RuntimeError("Shading workspace requires a node editor and a visible viewport")
        area.ui_type = nodes.SHADER_TREE
        area.spaces.active.show_region_ui = True
        sidebar_selected = False
        for region in area.regions:
            if region.type == "UI" and hasattr(region, "active_panel_category"):
                try:
                    region.active_panel_category = "Perceptual Grade"
                except (AttributeError, TypeError):
                    # Blender 5 exposes this as read-only; panel visibility still
                    # exercises the production draw path without selecting a tab.
                    pass
                else:
                    sidebar_selected = True
        report["workspace"] = workspace.name
        report["sidebar_visible"] = bool(area.spaces.active.show_region_ui)
        report["sidebar_category_selected"] = sidebar_selected

        scene = bpy.context.scene
        scene.render.engine = "BLENDER_EEVEE"
        scene.view_settings.view_transform = "Standard"
        obj = bpy.data.objects.get("Cube")
        if obj is None:
            bpy.ops.mesh.primitive_cube_add()
            obj = bpy.context.object
        bpy.context.view_layer.objects.active = obj
        obj.select_set(True)
        material = bpy.data.materials.new("Grade update timing")
        material.use_nodes = True
        obj.data.materials.clear()
        obj.data.materials.append(material)
        tree = material.node_tree
        tree.nodes.clear()
        node = nodes.create_node(tree)
        node.pg_grade = nodes._make_grade()
        tree.nodes.active = node
        source = tree.nodes.new("ShaderNodeRGB")
        source.outputs["Color"].default_value = (.18, .27, .36, 1.)
        source.location = (-250, 0)
        emission = tree.nodes.new("ShaderNodeEmission")
        emission.location = (300, 0)
        sink = tree.nodes.new("ShaderNodeOutputMaterial")
        sink.location = (550, 0)
        tree.links.new(source.outputs["Color"], node.inputs["Color"])
        tree.links.new(node.outputs["Color"], emission.inputs["Color"])
        tree.links.new(emission.outputs["Emission"], sink.inputs["Surface"])
        for item in tree.nodes:
            item.select = item == node
        tree.nodes.active = node
        area.spaces.active.node_tree = tree
        viewport.spaces.active.shading.type = config["viewport"].upper()
        viewport.spaces.active.region_3d.view_location = obj.location
        viewport.spaces.active.region_3d.view_distance = 6.
        bpy.context.preferences.edit.use_global_undo = True
        gpu.init()
        report["gpu"] = {
            "backend": gpu.platform.backend_type_get(),
            "renderer": gpu.platform.renderer_get(),
            "vendor": gpu.platform.vendor_get(),
            "version": gpu.platform.version_get(),
        }
        report["engine"] = scene.render.engine

        def inventory():
            trees, images, parameter_images, seen = [], {}, set(), set()

            def binding(item):
                image = item.image
                if (item.get(nodes.PARAMETER_READER)
                        and image.get(nodes.PARAMETER_IMAGE) == nodes.PARAMETER_SCHEMA):
                    parameter_images.add(int(image.as_pointer()))
                    return int(item.as_pointer()), "versioned-parameter"
                return int(item.as_pointer()), int(image.as_pointer())

            def visit(value):
                pointer = int(value.as_pointer())
                if pointer in seen:
                    return
                seen.add(pointer)
                trees.append({
                    "pointer": pointer,
                    "nodes": sorted(int(item.as_pointer()) for item in value.nodes),
                    "links": sorted((int(link.from_socket.as_pointer()), int(link.to_socket.as_pointer()))
                                    for link in value.links),
                    "image_bindings": sorted(binding(item) for item in value.nodes
                                             if getattr(item, "image", None) is not None),
                })
                for item in value.nodes:
                    image = getattr(item, "image", None)
                    if image is not None:
                        images[int(image.as_pointer())] = {
                            "pointer": int(image.as_pointer()), "size": list(image.size),
                            "channels": image.channels, "float": image.is_float,
                            "color_space": image.colorspace_settings.name,
                            "alpha_mode": image.alpha_mode,
                        }
                    child = getattr(item, "node_tree", None)
                    if child is not None:
                        visit(child)

            visit(tree)
            return {"trees": sorted(trees, key=lambda item: item["pointer"]),
                    "images": sorted((image for pointer, image in images.items()
                                      if pointer not in parameter_images), key=lambda item: item["pointer"]),
                    "parameter_images": sorted(
                        ({key: value for key, value in images[pointer].items() if key != "pointer"}
                         for pointer in parameter_images), key=lambda item: json.dumps(item, sort_keys=True))}

        original_write = nodes._write_grade_parameters

        def timed_write(image, pixels):
            if threading.current_thread() is not threading.main_thread():
                raise RuntimeError("Grade publication ran outside Blender's main thread")
            before = time.perf_counter()
            result = original_write(image, pixels)
            report["texture_publications"].append({
                "at_seconds": stamp(), "duration_seconds": time.perf_counter() - before,
                "image_pointer": int(image.as_pointer()),
            })
            return result

        nodes._write_grade_parameters = timed_write
        original_receive = nodes._handle_preparation_result

        def timed_receive(source, preparation_signature, prepared, error,
                          quality="full", lane="grade", **kwargs):
            before = time.perf_counter()
            result = original_receive(source, preparation_signature, prepared, error,
                                      quality, lane, **kwargs)
            if lane == "grade":
                report["received_results"].append({
                    "at_seconds": stamp(), "duration_seconds": time.perf_counter() - before,
                    "signature": preparation_signature,
                    "quality": quality, "error": None if error is None else str(error),
                })
            return result

        nodes._handle_preparation_result = timed_receive
        preparer = nodes._grade_preparer
        original_trace = preparer.on_timing

        def trace(signature, component, child_started, child_finished):
            if original_trace is not None:
                original_trace(signature, component, child_started, child_finished)
            if component == "join":
                report["preparations"].append({
                    "at_seconds": child_finished - started,
                    "duration_seconds": child_finished - child_started,
                    "signature": signature,
                })

        preparer.on_timing = trace
        finished = False
        gesture = None
        ready_at = None
        initial_inventory = None
        draw_handler = None
        render_receipts = []
        render_terminal = threading.Event()
        node_pointer = node.as_pointer()

        def render_receipt(_scene, *_args):
            # Observe plain policy state after the production render_pre handler
            # has finished its cross-thread handoff; do not access RNA here.
            record = nodes._node_stores.get(node_pointer)
            state = None if record is None else record["state"]
            render_receipts.append({
                "on_main_thread": threading.current_thread() is threading.main_thread(),
                "current": state is not None and nodes.node_policy.output_allowed(state),
                "signature": None if state is None else state.applied_signature,
            })

        def render_complete(_scene, *_args):
            render_terminal.set()

        def current():
            record = nodes._node_stores.get(node.as_pointer())
            return record is not None and nodes.node_policy.output_allowed(record["state"])

        def finish(error=None):
            nonlocal finished, draw_handler
            if finished:
                return None
            finished = True
            if draw_handler is not None:
                bpy.types.SpaceView3D.draw_handler_remove(draw_handler, "WINDOW")
                draw_handler = None
            nodes._write_grade_parameters = original_write
            nodes._handle_preparation_result = original_receive
            preparer.on_timing = original_trace
            for handlers, callback in (
                (bpy.app.handlers.render_pre, render_receipt),
                (bpy.app.handlers.render_complete, render_complete),
                (bpy.app.handlers.render_cancel, render_complete),
            ):
                if callback in handlers:
                    handlers.remove(callback)
            report["duration_seconds"] = stamp()
            report["final_current"] = current()
            report["final_signature"] = nodes._settings_signature_for(node)
            if initial_inventory is not None:
                report["final_inventory"] = inventory()
                report["resource_inventory_preserved"] = report["final_inventory"] == initial_inventory
            if error is None and not report.get("resource_inventory_preserved"):
                error = RuntimeError("Grade update changed topology or non-parameter image identities")
            if error is None and not report["final_current"]:
                error = RuntimeError("Final Grade signature did not become current")
            if error is not None:
                report["error"] = str(error)
                report["traceback"] = traceback.format_exc()
            report["completed"] = error is None
            save()
            if error is not None:
                print("PG_GRADE_UPDATE", report["error"], report["traceback"], file=sys.stderr, flush=True)
            addon_utils.disable(extension.__name__, default_set=False)
            bpy.ops.wm.quit_blender()
            return None

        def draw():
            if not finished and bpy.context.area == viewport:
                report["viewport_draws"].append({"at_seconds": stamp()})

        draw_handler = bpy.types.SpaceView3D.draw_handler_add(draw, (), "WINDOW", "POST_PIXEL")

        def heartbeat():
            if finished:
                return None
            report["ui_heartbeats"].append({"at_seconds": stamp()})
            return 0.

        def edit():
            before = time.perf_counter()
            index = len(report["edits"]) + 1
            # Keep changing throughout the gesture. These are the same RNA fields
            # drawn by the product sidebar; preparation does not wait for settling.
            fraction = .5 + .45 * math.sin(index * .02137)
            if config["stage"] in ("linear", "both"):
                node.pg_grade.pg_linear.exposure = -1. + 2. * fraction
            if config["stage"] in ("tone", "both"):
                node.pg_grade.pg_tone.fit = -1.5 + 3. * fraction
            report["edits"].append({
                "at_seconds": stamp(), "duration_seconds": time.perf_counter() - before,
            })
            area.tag_redraw()
            viewport.tag_redraw()

        def advance():
            nonlocal gesture, ready_at, initial_inventory
            if finished:
                return None
            try:
                now = stamp()
                if now > config["timeout"]:
                    raise TimeoutError("Grade update timing exceeded its session deadline")
                record = nodes._node_stores.get(node.as_pointer())
                if record is not None and record["state"].error is not None:
                    raise RuntimeError(record["state"].error)
                if "drag_started_at" not in report:
                    if not current():
                        return 0.
                    if ready_at is None:
                        ready_at = now
                        report["initialization"]["grade_current_seconds"] = now
                    if now - ready_at < config["warmup"]:
                        viewport.tag_redraw()
                        return 0.
                    initial_inventory = inventory()
                    report["initial_inventory"] = initial_inventory
                    report["drag_started_at"] = stamp()
                    gesture = nodes._begin_gesture(window.as_pointer(), node)
                    edit()
                    return config["interval_ms"] / 1000.
                if "released_at" not in report:
                    if now - report["drag_started_at"] < config["duration"]:
                        edit()
                        return config["interval_ms"] / 1000.
                    nodes._end_gesture(window.as_pointer(), gesture)
                    report["released_at"] = stamp()
                    return 0.
                if "render_requested_at" in report:
                    if not render_terminal.is_set() or bpy.app.is_job_running("RENDER"):
                        return .01
                    report["render_preflight"] = render_receipts
                    if (len(render_receipts) != 1 or not render_receipts[0]["current"]
                            or render_receipts[0]["signature"] != report["render_expected_signature"]):
                        raise RuntimeError("Native render did not reconcile the exact Grade settings")
                    if render_receipts[0]["on_main_thread"]:
                        raise RuntimeError("Native render did not exercise a render-worker callback")
                    return finish()
                if current():
                    report["settled_at"] = stamp()
                    if not config["verify_render_preflight"]:
                        return finish()
                    bpy.app.handlers.render_pre.append(render_receipt)
                    bpy.app.handlers.render_complete.append(render_complete)
                    bpy.app.handlers.render_cancel.append(render_complete)
                    scene.render.resolution_x = scene.render.resolution_y = 32
                    scene.render.resolution_percentage = 100
                    node.pg_grade.pg_linear.exposure += .123
                    report["render_expected_signature"] = nodes._settings_signature_for(node)
                    report["render_requested_at"] = stamp()
                    if bpy.ops.render.render("INVOKE_DEFAULT") != {"RUNNING_MODAL"}:
                        raise RuntimeError("Could not invoke native render worker")
                    return .01
                return 0.
            except BaseException as error:
                return finish(error)

        report["initialization"]["scenario_setup_seconds"] = stamp()
        save()
        bpy.app.timers.register(heartbeat, first_interval=0.)
        bpy.app.timers.register(advance, first_interval=0.)

    def start_workspace():
        try:
            area_types = {item.type for item in window.screen.areas}
            if not {"NODE_EDITOR", "VIEW_3D"} <= area_types:
                if stamp() > min(30., config["timeout"]):
                    raise RuntimeError("Shading workspace did not realize its editors")
                return .01
            run_workspace()
        except BaseException as error:
            report["error"] = str(error)
            report["traceback"] = traceback.format_exc()
            save()
            print("PG_GRADE_UPDATE", report["error"], report["traceback"],
                  file=sys.stderr, flush=True)
            bpy.ops.wm.quit_blender()
        return None

    # Blender realizes a workspace switch after the startup script returns.
    bpy.app.timers.register(start_workspace, first_interval=.01)


if __name__ == "__main__":
    main()
