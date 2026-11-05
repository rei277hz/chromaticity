"""Measure real Compositor Grade drags against passive X11 Viewer captures."""

from dataclasses import asdict
import importlib
import json
import math
from pathlib import Path
import sys
import time
import traceback


SOURCE_WIDTH = 438
SOURCE_HEIGHT = 841


def palette_matches(observed, expected, tolerance=2):
    """Accept four finite RGB swatches only when every channel agrees."""
    if not isinstance(tolerance, (int, float)) or not math.isfinite(tolerance) or tolerance < 0:
        return False
    if not isinstance(observed, (list, tuple)) or not isinstance(expected, (list, tuple)):
        return False
    if len(observed) != 4 or len(expected) != 4:
        return False
    for actual, wanted in zip(observed, expected):
        if not isinstance(actual, (list, tuple)) or not isinstance(wanted, (list, tuple)):
            return False
        if len(actual) != 3 or len(wanted) != 3:
            return False
        for left, right in zip(actual, wanted):
            if (isinstance(left, bool) or isinstance(right, bool)
                    or not isinstance(left, (int, float))
                    or not isinstance(right, (int, float))
                    or not math.isfinite(left) or not math.isfinite(right)
                    or abs(left - right) > tolerance):
                return False
    return True


def classify_palette(observed, candidates, tolerance=2):
    """Return the sole matching signature, or None for absent/ambiguous pixels."""
    matches = [signature for signature, expected in candidates.items()
               if palette_matches(observed, expected, tolerance)]
    return matches[0] if len(matches) == 1 else None


def main():
    import addon_utils
    import bpy
    import gpu

    config = json.loads(Path(sys.argv[sys.argv.index("--") + 1]).read_text(encoding="utf8"))
    sys.path[:0] = config.get("import_paths", ())
    import numpy as np
    from color_tools.perceptual_grade_reference import appearance, grading, model
    from color_tools.perceptual_grade_reference.responses import GAMMA, INVERSE, eccentricity

    destination = Path(config["report"])
    request_path = Path(config["capture_request"])
    trace_path = Path(config["capture_trace"])
    started_ns = time.perf_counter_ns()
    report = {
        "schema": 1, "completed": False, "session": config.get("session", 0),
        "samples": [], "captures": [], "drags": [], "events": [],
        "calibration": [], "observer_on": {}, "observer_off": {},
        "limitations": [
            "Capture completion is an observed upper bound including X11 readback, not physical scanout time.",
            "Acceptance timestamps mark entry to the actual Grade property callback, after native event delivery.",
            "The fixed Linux fixture uses Mesa llvmpipe rather than a hardware GPU.",
            "Calibration and independent reference calculations occur outside measured input intervals.",
            "The Viewer image is shown in Blender's Image Editor beside the production Compositor sidebar.",
        ],
    }
    request_id = 0
    points = []
    trace_offset = 0
    trace_partial = ""
    finished = False
    draw_handler = None
    original_changed = None
    nodes = None
    extension = None
    pending_error = None
    active = None
    injection = None
    palette_cache = {}
    calibration_callbacks = []
    visible_signature = None
    calibrating = False
    native_acceptances = 0
    capture_is_enabled = False
    draw_stamps = []
    cadence_mode = None
    compositor_pre = []

    def save():
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(".tmp")
        temporary.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf8")
        temporary.replace(destination)

    def capture_enabled(enabled):
        nonlocal request_id, capture_is_enabled
        request_id += 1
        capture_is_enabled = enabled
        temporary = request_path.with_suffix(".tmp")
        temporary.write_text(json.dumps({
            "enabled": enabled, "request_id": request_id, "points": points,
        }) + "\n", encoding="utf8")
        temporary.replace(request_path)

    def read_captures():
        nonlocal trace_offset, trace_partial
        try:
            with trace_path.open(encoding="utf8") as source:
                source.seek(trace_offset)
                value = trace_partial + source.read()
                trace_offset = source.tell()
        except FileNotFoundError:
            return []
        lines = value.split("\n")
        trace_partial = lines.pop()
        rows = [json.loads(line) for line in lines if line.strip()]
        report["captures"].extend(rows)
        return rows

    def finish(error=None):
        nonlocal finished, draw_handler
        if finished:
            return None
        finished = True
        if original_changed is not None:
            nodes._grade_changed = original_changed
        if draw_handler is not None:
            bpy.types.SpaceImageEditor.draw_handler_remove(draw_handler, "WINDOW")
            draw_handler = None
        try:
            bpy.app.handlers.composite_pre.remove(on_composite_pre)
        except (ValueError, NameError):
            pass
        try:
            bpy.app.handlers.composite_post.remove(on_composite_post)
        except (ValueError, NameError):
            pass
        try:
            bpy.app.handlers.composite_cancel.remove(on_composite_cancel)
        except (ValueError, NameError):
            pass
        capture_enabled(False)
        read_captures()
        report["duration_seconds"] = (time.perf_counter_ns() - started_ns) / 1e9
        if error is not None:
            report["error"] = str(error)
            report["traceback"] = traceback.format_exc()
            for sample in report["samples"]:
                if sample["outcome"] == "pending":
                    sample["outcome"] = "missing"
            print("PG_COMPOSITOR_DISPLAY", report["error"], report["traceback"], flush=True)
        report["completed"] = error is None
        save()
        if extension is not None:
            addon_utils.disable(extension.__name__, default_set=False)
        bpy.ops.wm.quit_blender()
        return None

    try:
        bpy.context.preferences.view.show_splash = False
        bpy.context.preferences.edit.use_global_undo = True
        bpy.ops.wm.save_userpref()
        bpy.context.preferences.extensions.repos.new(
            name="Perceptual Grade Compositor display timing", module="pg_compositor_display_timing",
            custom_directory=config["repository"],
        )
        extension = importlib.import_module("bl_ext.pg_compositor_display_timing.perceptual_grade")
        errors = []
        if addon_utils.enable(extension.__name__, default_set=False,
                              handle_error=errors.append) is not extension or errors:
            raise RuntimeError("Could not enable the installed extension: " + repr(errors))
        nodes = importlib.import_module(extension.__package__ + ".nodes")
        window = bpy.context.window
        if window is None:
            raise RuntimeError("Native Compositor display timing requires a Blender window")
        window_key = window.as_pointer()
        original_area = max((area for area in window.screen.areas if area.type == "VIEW_3D"),
                            key=lambda area: area.width * area.height)
        previous = {area.as_pointer() for area in window.screen.areas}
        with bpy.context.temp_override(window=window, area=original_area):
            bpy.ops.screen.area_split(direction="VERTICAL", factor=.58)
        split = [area for area in window.screen.areas
                 if area.as_pointer() == original_area.as_pointer() or area.as_pointer() not in previous]
        if len(split) != 2:
            raise RuntimeError("Could not create the native Viewer/sidebar fixture")
        viewer_area, editor = sorted(split, key=lambda area: area.x)
        viewer_area.type = "IMAGE_EDITOR"
        editor.type = "NODE_EDITOR"
        editor.ui_type = nodes.COMPOSITOR_TREE
        editor.spaces.active.show_region_ui = True
        # Blender schedules live composite jobs for an open compositor backdrop;
        # measured pixels still come from the separate Image Editor's Viewer.
        editor.spaces.active.show_backdrop = True
        viewer_key, editor_key = viewer_area.as_pointer(), editor.as_pointer()

        scene = bpy.context.scene
        scene.render.compositor_device = "GPU"
        scene.render.compositor_precision = "AUTO"
        scene.view_settings.view_transform = "Standard"
        scene.view_settings.look = "None"
        scene.view_settings.exposure = 0.
        scene.view_settings.gamma = 1.
        scene.render.dither_intensity = 0.
        scene.display_settings.display_device = "sRGB"
        if hasattr(scene.view_settings, "use_white_balance"):
            scene.view_settings.use_white_balance = False

        # Four broad vertical swatches in a full-size spatial image make both
        # Viewer sampling and image-processing work representative and stable.
        inputs = np.asarray([(.005,) * 3, (.025,) * 3, (.10,) * 3, (.30,) * 3])
        rgba = np.ones((SOURCE_HEIGHT, SOURCE_WIDTH, 4), dtype=np.float32)
        boundaries = np.linspace(0, SOURCE_WIDTH, len(inputs) + 1, dtype=int)
        for index, value in enumerate(inputs):
            rgba[:, boundaries[index]:boundaries[index + 1], :3] = value
        image = bpy.data.images.new("Compositor timing input", width=SOURCE_WIDTH,
                                    height=SOURCE_HEIGHT, alpha=True, float_buffer=True)
        image.colorspace_settings.name = "Non-Color"
        image.alpha_mode = "CHANNEL_PACKED"
        image.use_half_precision = False
        image.pixels.foreach_set(rgba.ravel())
        image.update()
        image.pack()

        root = bpy.data.node_groups.new("Compositor display timing", nodes.COMPOSITOR_TREE)
        root.interface.new_socket(name="Image", in_out="OUTPUT", socket_type="NodeSocketColor")
        output = root.nodes.new("NodeGroupOutput")
        source = root.nodes.new("CompositorNodeImage")
        source.image = image
        grade_node = nodes.create_node(root)
        grade_node.name = "Measured Grade"
        grade_node.pg_grade = nodes._make_grade()
        grade = grade_node.pg_grade
        viewer = root.nodes.new("CompositorNodeViewer")
        root.nodes.active = viewer
        root.links.new(source.outputs["Image"], grade_node.inputs["Color"])
        root.links.new(grade_node.outputs["Color"], viewer.inputs["Image"])
        root.links.new(grade_node.outputs["Color"], output.inputs["Image"])
        root.nodes.active = grade_node
        grade_node.select = True
        scene.compositing_node_group = root

        editor.spaces.active.node_tree = root
        editor.spaces.active.show_region_ui = True
        viewer_space = viewer_area.spaces.active
        viewer_space.image = bpy.data.images.get("Viewer Node")
        viewer_space.show_region_ui = False
        if hasattr(viewer_space, "show_region_toolbar"):
            viewer_space.show_region_toolbar = False

        gpu.init()
        report["environment"] = {
            "blender_version": bpy.app.version_string,
            "blender_build": bpy.app.build_hash.decode("ascii", errors="replace"),
            "gpu": {"backend": gpu.platform.backend_type_get(),
                    "renderer": gpu.platform.renderer_get(),
                    "vendor": gpu.platform.vendor_get(),
                    "version": gpu.platform.version_get()},
        }
        report["profile"] = {
            "context": "compositor", "scenarios": ["drag"],
            "measurement_surface": "Image Editor live Viewer",
            "compositor_backdrop_enabled": editor.spaces.active.show_backdrop,
            "engine": "Compositor", "compositor_device": scene.render.compositor_device,
            "compositor_precision": scene.render.compositor_precision,
            "view_transform": scene.view_settings.view_transform,
            "look": scene.view_settings.look,
            "display_device": scene.display_settings.display_device,
            "working_space": nodes._working_space(),
            "source_dimensions": [SOURCE_WIDTH, SOURCE_HEIGHT],
            "source_colors": inputs.tolist(), "sampled_swatches": 4,
            "pixel_tolerance": 2, "capture_patch_size": [5, 5],
            "window_size": [window.width, window.height],
            "drag_duration_seconds": config.get("drag_duration", 3.),
            "update_interval_ms": config.get("interval_ms", 50.),
            "capture_interval_ms": config.get("capture_interval_ms", 5.),
            "drag_motion": "alternating endpoint scrub through a held native numeric slider",
            "reference": "independent analytic Linear/Tone; spatial in-gamut swatches",
            "observer_off": "external capture disabled; Image Editor draw cadence retained; acceptance snapshots disabled",
        }
        for name, value in zip(nodes.TONE_LEVEL_FIELDS, (0., 10., 20., 300., 1200.)):
            setattr(grade.pg_tone, name, value)
        report["profile"]["baseline_settings"] = asdict(nodes._grade_settings(grade, nodes._working_space()))

        def current_window():
            return next(value for value in bpy.context.window_manager.windows
                        if value.as_pointer() == window_key)

        def area_for(key):
            return next(value for value in current_window().screen.areas if value.as_pointer() == key)

        def viewer_image():
            value = bpy.data.images.get("Viewer Node")
            if value is None or value.type != "COMPOSITING":
                return None
            if tuple(value.size) != (SOURCE_WIDTH, SOURCE_HEIGHT):
                return None
            return value

        def state():
            return nodes._record_for(grade_node)["state"]

        def current():
            return nodes.node_policy.output_allowed(state())

        def signature():
            return nodes._settings_signature_for(grade_node)

        def snap():
            return nodes._grade_settings(grade, nodes._working_space())

        def on_composite_pre(*_args):
            nonlocal pending_error
            evaluation_started_ns = time.perf_counter_ns()
            if compositor_pre:
                pending_error = RuntimeError("Compositor evaluations overlapped; attribution is ambiguous")
                return
            settings = snap()
            state_value = state()
            compositor_pre.append({
                "started_ns": evaluation_started_ns,
                "signature": signature(),
                "settings": asdict(settings),
                "output_allowed": nodes.node_policy.output_allowed(state_value),
            })

        def on_composite_post(*_args):
            nonlocal pending_error
            finished_ns = time.perf_counter_ns()
            if not compositor_pre:
                pending_error = RuntimeError("Compositor completion has no evaluation start")
                return
            evaluation = compositor_pre.pop(0)
            evaluation["finished_ns"] = finished_ns
            report["compositor_evaluations"].append(evaluation)

        def on_composite_cancel(*_args):
            nonlocal pending_error
            if compositor_pre:
                report.setdefault("cancelled_compositor_evaluations", []).append({
                    **compositor_pre.pop(0), "cancelled_ns": time.perf_counter_ns(),
                })
            else:
                pending_error = RuntimeError("Compositor cancellation has no evaluation start")

        def reference_palette(settings):
            # Independent reference code, never production parameters or texture
            # reads. This is called only during setup/calibration.
            white = model.xyz_from_xy(model.WHITES["D65"])
            matrix = model.rgb_matrix(settings.space)
            if settings.space != "Linear Rec.709":
                raise RuntimeError("The fixed display fixture requires Linear Rec.709")
            correction = model.linear_matrix(model.LinearSettings(**asdict(settings.linear)), white)
            xyz = inputs[:, 1, None] * white + (inputs - inputs[:, 1, None]) @ matrix.T
            xyz = xyz @ correction.T
            encoded = appearance.encode(xyz, white, 203.)
            mapped = grading.Tone(grading.ToneSettings(**asdict(settings.tone))).apply(encoded)
            _fl, aw = appearance.response_constants(203.)
            hue = np.arctan2(mapped.q[:, 2], mapped.q[:, 1])
            ab = mapped.q[:, 1:] * (aw / (1204 * eccentricity(hue)))[:, None]
            ac = aw * np.sign(mapped.ja) * (abs(mapped.ja) / 100) ** (1 / GAMMA)
            responses = np.column_stack((ac, ab)) @ INVERSE.T
            if not np.isfinite(responses).all() or np.max(abs(responses)) >= 300:
                raise RuntimeError("Reference swatches leave the well-conditioned decode domain")
            rgb = appearance.decode(mapped.q, mapped.ja * abs(mapped.ja), white, 203.) @ np.linalg.inv(matrix).T
            if not np.isfinite(rgb).all() or np.min(rgb) < 0 or np.max(rgb) > 1:
                raise RuntimeError("Reference swatches require export gamut handling")
            display = np.where(rgb <= .0031308, 12.92 * rgb,
                               1.055 * np.maximum(rgb, 0) ** (1 / 2.4) - .055)
            return np.rint(display * 255).astype(int).tolist(), rgb.tolist()

        def cache_settings(sig, settings):
            if sig not in palette_cache:
                expected, linear = reference_palette(settings)
                palette_cache[sig] = expected
                report["calibration"].append({"signature": sig, "settings": asdict(settings),
                                               "expected": expected, "linear_output": linear})

        def observed_change(owner):
            nonlocal pending_error, native_acceptances
            accepted_ns = time.perf_counter_ns()
            if owner.as_pointer() == grade.as_pointer():
                native_acceptances += 1
                if calibrating:
                    calibration_callbacks.append((signature(), snap()))
                if active is not None:
                    sig = signature()
                    if injection is None:
                        pending_error = RuntimeError("Native acceptance has no injected event identity")
                    elif sig not in palette_cache:
                        pending_error = RuntimeError("Timed native input accepted an uncalibrated signature")
                    elif not report["samples"] or report["samples"][-1]["signature"] != sig:
                        report["samples"].append({
                            "sample_id": len(report["samples"]), "control": active["control"],
                            "scenario": "drag", "signature": sig,
                            "settings": asdict(snap()),
                            "requested_ns": injection["requested_ns"],
                            "injected_ns": injection["injected_ns"],
                            "accepted_ns": accepted_ns, "outcome": "pending",
                        })
                        injection["accepted_signature"] = sig
                        injection["accepted_ns"] = accepted_ns
            return original_changed(owner)

        original_changed = nodes._grade_changed
        nodes._grade_changed = observed_change
        report["compositor_evaluations"] = []
        bpy.app.handlers.composite_pre.append(on_composite_pre)
        bpy.app.handlers.composite_post.append(on_composite_post)
        bpy.app.handlers.composite_cancel.append(on_composite_cancel)

        def draw():
            if not finished and bpy.context.area == area_for(viewer_key):
                draw_stamps.append((cadence_mode, time.perf_counter_ns()))

        draw_handler = bpy.types.SpaceImageEditor.draw_handler_add(draw, (), "WINDOW", "POST_PIXEL")

        def pump_captures():
            nonlocal visible_signature
            if not capture_is_enabled:
                return
            for capture in read_captures():
                if capture.get("request_id") != request_id:
                    continue
                sig = classify_palette(capture.get("observed"), palette_cache)
                if sig is None or sig == visible_signature:
                    continue
                visible_signature = sig
                matches = [sample for sample in report["samples"]
                           if sample["signature"] == sig and sample["outcome"] == "pending"
                           and sample["accepted_ns"] <= capture["start_ns"]]
                if not matches:
                    continue
                sample_settings = matches[-1]["settings"]
                completed = [evaluation for evaluation in report["compositor_evaluations"]
                             if evaluation["signature"] == sig and evaluation["output_allowed"]
                             and evaluation["settings"] == sample_settings
                             and matches[-1]["accepted_ns"] <= evaluation["started_ns"]
                             and evaluation["finished_ns"] <= capture["start_ns"]]
                if not completed:
                    continue
                sample = matches[-1]
                for old in report["samples"]:
                    if old["outcome"] == "pending" and old["accepted_ns"] < sample["accepted_ns"]:
                        old["outcome"] = "superseded"
                sample["outcome"] = "displayed"
                sample["capture"] = {**capture, "sample_id": sample["sample_id"],
                                     "signature": sig, "matches": True,
                                     "compositor_evaluation": completed[-1]}

        def send(kind, value, point, *, measured=False, requested_ns=None):
            nonlocal injection
            now = time.perf_counter_ns()
            event = {"type": kind, "value": value, "point": list(point),
                     "requested_ns": now if requested_ns is None else requested_ns,
                     "injected_ns": now, "measured": measured}
            if measured:
                injection = event
            report["events"].append(event)
            current_window().event_simulate(type=kind, value=value, x=int(point[0]), y=int(point[1]))

        def wait_for(predicate, message, timeout=40.):
            deadline = time.perf_counter() + timeout
            while not predicate():
                if time.perf_counter() > deadline:
                    raise TimeoutError(message)
                yield .01

        def sleep(seconds):
            deadline = time.perf_counter() + seconds
            while time.perf_counter() < deadline:
                yield min(.02, max(0., deadline - time.perf_counter()))

        def select_category():
            target = area_for(editor_key)
            region = next(value for value in target.regions if value.type == "UI")
            try:
                region.active_panel_category = "Perceptual Grade"
            except (AttributeError, TypeError):
                pass
            target.tag_redraw()
            yield from sleep(.2)

        def scan_widgets():
            target = area_for(editor_key)
            region = next(value for value in target.regions if value.type == "UI")
            x = region.x + region.width // 2
            manager = bpy.context.window_manager
            previous_clipboard = manager.clipboard
            found = {}
            try:
                for y in range(region.y + region.height - 8, region.y + 8, -4):
                    send("MOUSEMOVE", "NOTHING", (x, y))
                    yield .005
                    with bpy.context.temp_override(window=current_window(), area=target, region=region):
                        if not bpy.ops.ui.copy_data_path_button.poll():
                            continue
                        bpy.ops.ui.copy_data_path_button()
                        path = manager.clipboard
                    for control, suffix in (("exposure", "pg_linear.exposure"),
                                            ("fit", "pg_tone.fit")):
                        if path.endswith(suffix) and control not in found:
                            found[control] = (x, y - 2)
                    if len(found) == 2:
                        return found
            finally:
                manager.clipboard = previous_clipboard
            return found

        def find_widgets():
            yield from select_category()
            found = yield from scan_widgets()
            if len(found) == 2:
                return found
            target = area_for(editor_key)
            region = next(value for value in target.regions if value.type == "UI")
            for y in range(region.y + region.height - 30, region.y + 10, -24):
                point = (region.x + region.width - 12, y)
                send("MOUSEMOVE", "NOTHING", point)
                send("LEFTMOUSE", "PRESS", point)
                yield .02
                send("LEFTMOUSE", "RELEASE", point)
                yield .08
                found = yield from scan_widgets()
                if len(found) == 2:
                    return found
            raise RuntimeError("Could not locate both real Grade sliders in the production sidebar")

        def press(point):
            yield from wait_for(lambda: nodes._gesture_observer_token(window_key) is not None,
                                "Native gesture router was not registered")
            root.nodes.active = grade_node
            send("MOUSEMOVE", "NOTHING", point)
            yield .03
            send("LEFTMOUSE", "PRESS", point)
            yield from wait_for(lambda: nodes._gesture_phase(window_key) == "armed",
                                "The real Grade widget did not arm a native gesture")
            send("MOUSEMOVE", "NOTHING", (point[0] + 6, point[1]))
            yield from wait_for(lambda: state().gesture_active,
                                "Native widget movement did not activate the held slider")
            yield .05

        def release(point):
            send("LEFTMOUSE", "RELEASE", point)
            yield from wait_for(lambda: not state().gesture_active,
                                "Native slider release did not finish the gesture")
            yield .05

        def baseline():
            nonlocal active
            active = None
            grade.pg_linear.exposure = 0.
            grade.pg_tone.fit = 0.
            yield from wait_for(current, "Baseline Grade did not become current")
            cache_settings(signature(), snap())

        def wait_palette(sig, *, after_ns=None):
            deadline = time.perf_counter() + 40.
            after_ns = time.perf_counter_ns() if after_ns is None else after_ns
            while True:
                for capture in report["captures"][-200:]:
                    if (capture.get("request_id") == request_id and capture["start_ns"] >= after_ns
                            and palette_matches(capture.get("observed"), palette_cache[sig])):
                        return capture
                if time.perf_counter() > deadline:
                    observed = report["captures"][-1:] or None
                    raise TimeoutError(f"Viewer did not display {sig}: expected {palette_cache[sig]}, last {observed}")
                yield .01

        def cadence_summary(mode, start, end, events):
            stamps = [stamp for label, stamp in draw_stamps if label == mode and start <= stamp <= end]
            gaps = [(right - left) / 1e9 for left, right in zip(stamps, stamps[1:])]
            return {"started_ns": start, "ended_ns": end, "draws": len(stamps),
                    "draw_intervals_seconds": gaps, "injected_motion_events": events,
                    "duration_seconds": (end - start) / 1e9}

        def run():
            nonlocal active, cadence_mode, points, calibrating
            send("ESC", "PRESS", (20, 20))
            send("ESC", "RELEASE", (20, 20))
            yield from wait_for(current, "Initial Compositor Grade did not become current")
            yield from wait_for(lambda: bool(report["compositor_evaluations"]),
                                "No live Compositor evaluation was observed")
            yield from wait_for(lambda: viewer_image() is not None,
                                "Compositor did not publish the expected live Viewer image")
            viewer_space = area_for(viewer_key).spaces.active
            viewer_space.image = viewer_image()
            viewer_area = area_for(viewer_key)
            viewer_region = next(value for value in viewer_area.regions if value.type == "WINDOW")
            with bpy.context.temp_override(window=current_window(), area=viewer_area, region=viewer_region):
                bpy.ops.image.view_all(fit_view=True)
            area_for(viewer_key).tag_redraw()
            yield from sleep(config.get("warmup", 2.))
            viewer = viewer_image()
            if viewer is None:
                raise RuntimeError("Live Viewer image disappeared during setup")
            region = next(value for value in area_for(viewer_key).regions if value.type == "WINDOW")
            image_x = (boundaries[:-1] + boundaries[1:]) / 2
            image_y = SOURCE_HEIGHT / 2
            projected = [region.view2d.view_to_region(float(x) / SOURCE_WIDTH,
                                                    image_y / SOURCE_HEIGHT, clip=False)
                         for x in image_x[:4]]
            if any(value is None or not 5 < value[0] < region.width - 5
                   or not 5 < value[1] < region.height - 5 for value in projected):
                raise RuntimeError("Projected Compositor swatches lie outside the live Viewer region")
            points = [[round(region.x + value[0]), round(window.height - 1 - (region.y + value[1]))]
                      for value in projected]
            report["geometry"] = {
                "window": [window.width, window.height], "root_origin": [0, 0],
                "viewer_region": [region.x, region.y, region.width, region.height],
                "sidebar_editor": [area_for(editor_key).x, area_for(editor_key).y,
                                   area_for(editor_key).width, area_for(editor_key).height],
                "capture_points_root": points,
                "image_dimensions": list(viewer.size),
            }
            report["profile"]["viewer_region"] = [region.x, region.y, region.width, region.height]
            report["profile"]["capture_points_root"] = points
            capture_enabled(True)
            yield from baseline()
            yield from wait_palette(signature())
            widgets = yield from find_widgets()
            report["widgets"] = {name: list(point) for name, point in widgets.items()}
            save()
            controls = [value.rsplit(".", 1)[-1] for value in config.get(
                "controls", ("pg_linear.exposure", "pg_tone.fit"))]
            recipes = {"exposure": (12, -6, 18), "fit": (45, -30, 80)}
            report["profile"]["native_slider_recipes"] = {
                "activation_offset_px": 6,
                "endpoint_offsets_px": {control: list(recipes[control]) for control in controls},
            }
            report["profile"]["calibrated_endpoints"] = {}
            for control in controls:
                point = widgets[control]
                *offsets, final_offset = recipes[control]
                yield from baseline()
                yield from press(point)
                before = len(calibration_callbacks)
                calibrating = True
                for offset in (*offsets, final_offset):
                    previous_acceptances = native_acceptances
                    send("MOUSEMOVE", "NOTHING", (point[0] + offset, point[1]))
                    yield from wait_for(lambda: native_acceptances > previous_acceptances,
                                        "Calibration motion did not accept a changed value")
                    yield .05
                calibrating = False
                yield from release(point)
                yield from wait_for(current, "Calibrated Grade did not become current")
                for sig, settings in calibration_callbacks[before:]:
                    cache_settings(sig, settings)
                unique = {sig: palette_cache[sig] for sig, _settings in calibration_callbacks[before:]}
                if len(unique) != 3:
                    raise RuntimeError("Endpoint calibration must accept exactly three distinct settings values")
                values = list(unique.values())
                for index, left in enumerate(values):
                    if any(palette_matches(left, right, tolerance=4)
                           for right in values[index + 1:]):
                        raise RuntimeError("Calibrated slider endpoints are not distinguishable within tolerance")
                report["profile"]["calibrated_endpoints"][control] = [
                    {"value": getattr(settings.linear if control == "exposure" else settings.tone, control),
                     "expected": palette_cache[sig]}
                    for sig, settings in calibration_callbacks[before:]
                ]

            for control in controls:
                point = widgets[control]
                offsets, final_offset = recipes[control][:2], recipes[control][-1]
                for observer in (True, False):
                    yield from baseline()
                    if observer:
                        capture_enabled(True)
                        yield from wait_palette(signature())
                    else:
                        capture_enabled(False)
                    yield from press(point)
                    active = {"control": control} if observer else None
                    cadence_mode = "observer_on" if observer else "observer_off"
                    start = time.perf_counter_ns()
                    deadline = start + round(config.get("drag_duration", 3.) * 1e9)
                    interval = max(0, round(config.get("interval_ms", 50.) * 1e6))
                    next_event = start
                    count = 0
                    last_motion = None
                    while time.perf_counter_ns() < deadline:
                        now = time.perf_counter_ns()
                        if now < next_event:
                            yield min(.01, (next_event - now) / 1e9)
                            continue
                        offset = offsets[count % len(offsets)]
                        previous_acceptances = native_acceptances
                        send("MOUSEMOVE", "NOTHING", (point[0] + offset, point[1]),
                             measured=observer, requested_ns=next_event)
                        count += 1
                        last_motion = offset
                        yield from wait_for(lambda: native_acceptances > previous_acceptances,
                                            "Timed native motion was not accepted before another injection")
                        next_event = report["events"][-1]["injected_ns"] + interval
                        now = time.perf_counter_ns()
                        if interval and next_event < now:
                            next_event += ((now - next_event) // interval + 1) * interval
                        yield .001
                    previous_acceptances = native_acceptances
                    send("MOUSEMOVE", "NOTHING", (point[0] + final_offset, point[1]),
                         measured=observer)
                    count += 1
                    last_motion = final_offset
                    yield from wait_for(lambda: native_acceptances > previous_acceptances,
                                        "The final drag target was not accepted")
                    release_ns = time.perf_counter_ns()
                    send("LEFTMOUSE", "RELEASE", (point[0] + last_motion, point[1]))
                    yield from wait_for(lambda: not state().gesture_active,
                                        "Timed native slider release did not finish the gesture")
                    active = None
                    report[cadence_mode][control] = cadence_summary(cadence_mode, start, release_ns, count)
                    cadence_mode = None
                    if observer:
                        final = report["samples"][-1]
                        yield from wait_for(lambda: final["outcome"] == "displayed",
                                            "Final accepted drag value did not reach the live Viewer image")
                        capture = yield from wait_palette(final["signature"], after_ns=release_ns)
                        report["drags"].append({
                            "control": control, "started_ns": start, "release_ns": release_ns,
                            "final_capture_end_ns": capture["end_ns"],
                            "final_capture": {**capture, "sample_id": final["sample_id"],
                                              "signature": final["signature"], "matches": True,
                                              "compositor_evaluation": final["capture"]["compositor_evaluation"]},
                        })
                        for sample in report["samples"]:
                            if sample["outcome"] == "pending":
                                sample["outcome"] = "superseded"
                    else:
                        yield from wait_for(current, "Observer-off drag did not settle")
                        capture_enabled(True)
                    save()
            if any(sample["outcome"] == "pending" for sample in report["samples"]):
                raise RuntimeError("Timing session has unclassified accepted inputs")
            report["final_current"] = current()
            if not report["final_current"]:
                yield from wait_for(current, "Final Grade did not become current")
                report["final_current"] = True

        iterator = run()

        def advance():
            try:
                if time.perf_counter_ns() - started_ns > config.get("timeout", 1800.) * 1e9:
                    raise TimeoutError("Compositor display timing exceeded its session deadline")
                if pending_error is not None:
                    raise pending_error
                error = state().error
                if error is not None:
                    raise RuntimeError(error)
                pump_captures()
                return max(0., next(iterator))
            except StopIteration:
                return finish()
            except BaseException as error:
                return finish(error)

        save()
        bpy.app.timers.register(advance, first_interval=.1)
    except BaseException as error:
        finish(error)


if __name__ == "__main__":
    main()
