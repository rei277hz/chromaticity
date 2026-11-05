"""Drive real Shader Grade widgets and match passive native-window captures.

The importable helpers deliberately have no Blender dependency.  The experiment
itself runs only inside Blender; it never draws a replacement preview or asks
Blender to render/read back a second view of the scene.
"""

from dataclasses import asdict
import importlib
import json
import math
from pathlib import Path
import sys
import time
import traceback


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
    from mathutils import Quaternion, Vector
    from bpy_extras.view3d_utils import location_3d_to_region_2d

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
    settings_cache = {}
    calibration_callbacks = []
    visible_signature = None
    calibrating = False
    native_acceptances = 0
    capture_is_enabled = False
    draw_stamps = []
    cadence_mode = None

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
            bpy.types.SpaceView3D.draw_handler_remove(draw_handler, "WINDOW")
            draw_handler = None
        capture_enabled(False)
        read_captures()
        report["duration_seconds"] = (time.perf_counter_ns() - started_ns) / 1e9
        if error is not None:
            report["error"] = str(error)
            report["traceback"] = traceback.format_exc()
            for sample in report["samples"]:
                if sample["outcome"] == "pending":
                    sample["outcome"] = "missing"
            print("PG_SHADER_DISPLAY", report["error"], report["traceback"], flush=True)
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
            name="Perceptual Grade display timing", module="pg_shader_display_timing",
            custom_directory=config["repository"],
        )
        extension = importlib.import_module("bl_ext.pg_shader_display_timing.perceptual_grade")
        errors = []
        if addon_utils.enable(extension.__name__, default_set=False,
                              handle_error=errors.append) is not extension or errors:
            raise RuntimeError("Could not enable the installed extension: " + repr(errors))
        nodes = importlib.import_module(extension.__package__ + ".nodes")
        window = bpy.context.window
        if window is None:
            raise RuntimeError("Native Shader display timing requires a Blender window")
        window_key = window.as_pointer()
        # Split the large factory viewport, giving the production sidebar enough
        # vertical room for both panels while keeping a rendered view visible.
        viewport = max((area for area in window.screen.areas if area.type == "VIEW_3D"),
                       key=lambda area: area.width * area.height)
        previous = {area.as_pointer() for area in window.screen.areas}
        with bpy.context.temp_override(window=window, area=viewport):
            bpy.ops.screen.area_split(direction="VERTICAL", factor=.58)
        split = [area for area in window.screen.areas
                 if area.as_pointer() == viewport.as_pointer() or area.as_pointer() not in previous]
        if len(split) != 2:
            raise RuntimeError("Could not create the native viewport/sidebar fixture")
        viewport, editor = sorted(split, key=lambda area: area.x)
        viewport.type = "VIEW_3D"
        editor.type = "NODE_EDITOR"
        editor.ui_type = nodes.SHADER_TREE
        editor.spaces.active.show_region_ui = True
        viewport_key, editor_key = viewport.as_pointer(), editor.as_pointer()

        scene = bpy.context.scene
        scene.render.engine = "BLENDER_EEVEE"
        scene.view_settings.view_transform = "Standard"
        scene.view_settings.look = "None"
        scene.view_settings.exposure = 0.
        scene.view_settings.gamma = 1.
        scene.render.dither_intensity = 0.
        scene.display_settings.display_device = "sRGB"
        if hasattr(scene.view_settings, "use_white_balance"):
            scene.view_settings.use_white_balance = False
        scene.eevee.taa_samples = 1
        scene.eevee.taa_render_samples = 1
        scene.eevee.use_taa_reprojection = False
        scene.render.filter_size = .01
        for obj in list(scene.objects):
            bpy.data.objects.remove(obj, do_unlink=True)
        mesh = bpy.data.meshes.new("Shader timing swatches")
        mesh.from_pydata([(-2., -1.25, 0.), (2., -1.25, 0.),
                         (2., 1.25, 0.), (-2., 1.25, 0.)], [], [(0, 1, 2, 3)])
        mesh.update()
        uv = mesh.uv_layers.new()
        for loop, value in zip(uv.data, ((0., 0.), (1., 0.), (1., 1.), (0., 1.))):
            loop.uv = value
        obj = bpy.data.objects.new("Shader timing swatches", mesh)
        scene.collection.objects.link(obj)
        bpy.context.view_layer.objects.active = obj
        obj.select_set(True)
        material = bpy.data.materials.new("Installed Shader Grade display timing")
        material.use_nodes = True
        obj.data.materials.append(material)
        tree = material.node_tree
        tree.nodes.clear()
        grade_node = nodes.create_node(tree)
        grade_node.pg_grade = nodes._make_grade()
        grade = grade_node.pg_grade
        # Neutral inputs keep all four independently calculated outputs within
        # the cube, so entry repair and export gamut guards are inactive.
        inputs = np.asarray([(.005,) * 3, (.025,) * 3, (.10,) * 3, (.30,) * 3])
        image = bpy.data.images.new("Shader timing input colors", width=4, height=1,
                                    alpha=True, float_buffer=True)
        image.colorspace_settings.name = "Non-Color"
        image.alpha_mode = "CHANNEL_PACKED"
        image.use_half_precision = False
        image.pixels.foreach_set(np.column_stack((inputs, np.ones(4))).astype(np.float32).ravel())
        image.update()
        texture = tree.nodes.new("ShaderNodeTexImage")
        texture.image = image
        texture.interpolation = "Closest"
        coordinates = tree.nodes.new("ShaderNodeTexCoord")
        emission = tree.nodes.new("ShaderNodeEmission")
        output = tree.nodes.new("ShaderNodeOutputMaterial")
        tree.links.new(coordinates.outputs["UV"], texture.inputs["Vector"])
        tree.links.new(texture.outputs["Color"], grade_node.inputs["Color"])
        tree.links.new(grade_node.outputs["Color"], emission.inputs["Color"])
        tree.links.new(emission.outputs[0], output.inputs["Surface"])
        for item in tree.nodes:
            item.select = item == grade_node
        tree.nodes.active = grade_node
        editor.spaces.active.node_tree = tree
        editor.spaces.active.shader_type = "OBJECT"
        space = viewport.spaces.active
        space.shading.type = "RENDERED"
        space.overlay.show_overlays = False
        space.show_gizmo = False
        space.region_3d.view_perspective = "ORTHO"
        space.region_3d.view_rotation = Quaternion((1., 0., 0., 0.))
        space.region_3d.view_location = (0., 0., 0.)
        space.region_3d.view_distance = 6.
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
            "engine": scene.render.engine, "view_transform": scene.view_settings.view_transform,
            "look": scene.view_settings.look, "display_device": scene.display_settings.display_device,
            "working_space": nodes._working_space(), "taa_samples": scene.eevee.taa_samples,
            "source_colors": inputs.tolist(), "pixel_tolerance": 2,
            "capture_patch_size": [5, 5], "window_size": [window.width, window.height],
            "drag_motion": "alternating endpoint scrub through a held native numeric slider",
            "reference": "independent analytic Linear/Tone; neutral in-cube outputs verified",
            "observer_off": "external capture disabled; draw cadence counter retained; acceptance snapshots disabled",
        }
        # Strongly nonidentity anchors make Fit changes distinguishable. Setting
        # up the fixture uses RNA, while every measured edit uses native events.
        for name, value in zip(nodes.TONE_LEVEL_FIELDS, (0., 10., 20., 300., 1200.)):
            setattr(grade.pg_tone, name, value)
        report["profile"]["baseline_settings"] = asdict(nodes._grade_settings(grade, nodes._working_space()))

        def current_window():
            return next(value for value in bpy.context.window_manager.windows
                        if value.as_pointer() == window_key)

        def area_for(key):
            return next(value for value in current_window().screen.areas if value.as_pointer() == key)

        def state():
            return nodes._record_for(grade_node)["state"]

        def current():
            return nodes.node_policy.output_allowed(state())

        def signature():
            return nodes._settings_signature_for(grade_node)

        def snap():
            return nodes._grade_settings(grade, nodes._working_space())

        def reference_palette(settings):
            # Independent reference code, never production parameters or texture
            # reads. This is called only during calibration/setup.
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
                settings_cache[sig] = settings
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
                        if active["scenario"] == "isolated" and any(
                                sample["outcome"] == "pending" for sample in report["samples"]):
                            pending_error = RuntimeError("An isolated input accepted another value before its pixel witness")
                        report["samples"].append({
                            "sample_id": len(report["samples"]), "control": active["control"],
                            "scenario": active["scenario"], "signature": sig,
                            "requested_ns": injection["requested_ns"],
                            "injected_ns": injection["injected_ns"],
                            "accepted_ns": accepted_ns, "outcome": "pending",
                        })
                        injection["accepted_signature"] = sig
                        injection["accepted_ns"] = accepted_ns
            return original_changed(owner)

        original_changed = nodes._grade_changed
        nodes._grade_changed = observed_change

        def draw():
            if not finished and bpy.context.area == area_for(viewport_key):
                draw_stamps.append((cadence_mode, time.perf_counter_ns()))

        draw_handler = bpy.types.SpaceView3D.draw_handler_add(draw, (), "WINDOW", "POST_PIXEL")

        def pump_captures():
            nonlocal visible_signature
            if not capture_is_enabled:
                return
            for capture in read_captures():
                if capture.get("request_id") != request_id:
                    continue
                sig = classify_palette(capture.get("observed"), palette_cache)
                if sig is None:
                    continue
                if sig == visible_signature:
                    continue
                visible_signature = sig
                matches = [sample for sample in report["samples"]
                           if sample["signature"] == sig and sample["outcome"] == "pending"
                           and sample["accepted_ns"] <= capture["start_ns"]]
                if not matches:
                    continue
                # Equal palettes certify a settings value, not edit occurrence.
                # Repeated drag values remain ambiguous until the most recent
                # acceptance; only that occurrence can receive this witness.
                sample = matches[-1]
                for old in report["samples"]:
                    if old["outcome"] == "pending" and old["accepted_ns"] < sample["accepted_ns"]:
                        old["outcome"] = "superseded"
                sample["outcome"] = "displayed"
                sample["capture"] = {**capture, "sample_id": sample["sample_id"],
                                     "signature": sig, "matches": True}

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
            editor = area_for(editor_key)
            region = next(value for value in editor.regions if value.type == "UI")
            try:
                region.active_panel_category = "Perceptual Grade"
            except (AttributeError, TypeError):
                # The tab column lives at the right edge of the actual sidebar.
                # Click each candidate and scan the resulting real widgets.
                pass
            editor.tag_redraw()
            yield from sleep(.2)

        def scan_widgets():
            editor = area_for(editor_key)
            region = next(value for value in editor.regions if value.type == "UI")
            x = region.x + region.width // 2
            manager = bpy.context.window_manager
            previous_clipboard = manager.clipboard
            found = {}
            try:
                for y in range(region.y + region.height - 8, region.y + 8, -4):
                    send("MOUSEMOVE", "NOTHING", (x, y))
                    yield .005
                    with bpy.context.temp_override(window=current_window(), area=editor, region=region):
                        if not bpy.ops.ui.copy_data_path_button.poll():
                            continue
                        bpy.ops.ui.copy_data_path_button()
                        path = manager.clipboard
                    for control, suffix in (("exposure", "pg_linear.exposure"), ("fit", "pg_tone.fit")):
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
            editor = area_for(editor_key)
            region = next(value for value in editor.regions if value.type == "UI")
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
            tree.nodes.active = grade_node
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

        def baseline(control):
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
                    raise TimeoutError(f"Native window did not display {sig}: expected {palette_cache[sig]}, last {observed}")
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
            yield from wait_for(current, "Initial Shader Grade did not become current")
            yield from sleep(config.get("warmup", 2.))
            viewport = area_for(viewport_key)
            region = next(value for value in viewport.regions if value.type == "WINDOW")
            projected = [location_3d_to_region_2d(region, viewport.spaces.active.region_3d,
                                                Vector((x, 0., 0.))) for x in (-1.5, -.5, .5, 1.5)]
            if any(value is None or not 5 < value.x < region.width - 5
                   or not 5 < value.y < region.height - 5 for value in projected):
                raise RuntimeError("Projected Shader swatches lie outside the native viewport")
            # Xvfb has no window manager/decorations and the launcher fixes the
            # Blender client window at root (0,0). Blender's y axis points up.
            points = [[round(region.x + value.x), round(window.height - 1 - (region.y + value.y))]
                      for value in projected]
            report["geometry"] = {
                "window": [window.width, window.height], "root_origin": [0, 0],
                "viewport": [region.x, region.y, region.width, region.height],
                "capture_points_root": points,
            }
            report["profile"]["viewport_region"] = [region.x, region.y, region.width, region.height]
            report["profile"]["capture_points_root"] = points
            capture_enabled(True)
            yield from baseline("exposure")
            yield from wait_palette(signature())
            widgets = yield from find_widgets()
            report["widgets"] = {name: list(point) for name, point in widgets.items()}
            save()
            controls = [value.rsplit(".", 1)[-1] for value in config.get("controls", ("exposure", "fit"))]
            # Calibration replays the same endpoint recipes with observation
            # timing disabled. No oracle work occurs inside acceptance hooks.
            recipes = {"exposure": (12, -6, 18), "fit": (45, -30, 80)}
            report["profile"]["native_slider_recipes"] = {
                "activation_offset_px": 6,
                "endpoint_offsets_px": {control: list(recipes[control]) for control in controls},
            }
            report["profile"]["calibrated_endpoints"] = {}
            for control in controls:
                point = widgets[control]
                *offsets, final_offset = recipes[control]
                yield from baseline(control)
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
                    if any(palette_matches(left, right, tolerance=4) for right in values[index + 1:]):
                        raise RuntimeError("Calibrated slider endpoints are not distinguishable within pixel tolerance")
                report["profile"]["calibrated_endpoints"][control] = [
                    {"value": getattr(settings.linear if control == "exposure" else settings.tone, control),
                     "expected": palette_cache[sig]}
                    for sig, settings in calibration_callbacks[before:]
                ]

            for control in controls:
                point = widgets[control]
                *offsets, _final_offset = recipes[control]
                yield from baseline(control)
                yield from wait_palette(signature())
                yield from press(point)
                active = {"control": control, "scenario": "isolated"}
                for index in range(config.get("samples", 100)):
                    count = len(report["samples"])
                    offset = offsets[index % len(offsets)]
                    send("MOUSEMOVE", "NOTHING", (point[0] + offset, point[1]), measured=True)
                    yield from wait_for(lambda: len(report["samples"]) > count,
                                        "Isolated native input did not change the Grade")
                    sample = report["samples"][-1]
                    yield from wait_for(lambda: sample["outcome"] == "displayed",
                                        "Isolated accepted input did not reach native window pixels")
                active = None
                yield from release(point)
                save()

            for control in controls:
                point = widgets[control]
                *offsets, final_offset = recipes[control]
                for observer in (True, False):
                    yield from baseline(control)
                    if observer:
                        yield from wait_palette(signature())
                    else:
                        capture_enabled(False)
                    yield from press(point)
                    active = {"control": control, "scenario": "drag"} if observer else None
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
                        # A delayed native loop schedules from actual injection;
                        # it never emits a catch-up burst of queued movements.
                        next_event = report["events"][-1]["injected_ns"] + interval
                        now = time.perf_counter_ns()
                        if interval and next_event < now:
                            next_event += ((now - next_event) // interval + 1) * interval
                        yield .001
                    # A distinct calibrated final target prevents a static
                    # repeated endpoint from masquerading as final progress.
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
                                        "Timed drag release did not end the native gesture")
                    active = None
                    report[cadence_mode][control] = cadence_summary(cadence_mode, start, release_ns, count)
                    cadence_mode = None
                    if observer:
                        final = report["samples"][-1]
                        yield from wait_for(lambda: final["outcome"] == "displayed",
                                            "Final accepted drag value did not reach native pixels")
                        capture = yield from wait_palette(final["signature"], after_ns=release_ns)
                        report["drags"].append({
                            "control": control, "started_ns": start, "release_ns": release_ns,
                            "final_capture_end_ns": capture["end_ns"],
                            "final_capture": {**capture, "sample_id": final["sample_id"],
                                              "signature": final["signature"], "matches": True},
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
                    raise TimeoutError("Shader display timing exceeded its session deadline")
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
