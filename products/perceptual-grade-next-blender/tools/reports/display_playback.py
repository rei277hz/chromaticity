"""Measure timeline playback using the same endpoints as a native drag."""

import math
import time


def visible_cadence(captures, classify, started_ns, ended_ns, *, request_id):
    visible = None
    matched = 0
    sampled = 0
    transitions = []
    for capture in captures:
        if (capture["request_id"] != request_id or capture["start_ns"] < started_ns
                or capture["end_ns"] > ended_ns):
            continue
        sampled += 1
        classification = classify(capture["observed"])
        if classification is None:
            continue
        matched += 1
        if classification != visible:
            transitions.append({"endpoint": classification, "end_ns": capture["end_ns"]})
            visible = classification
    return {
        "started_ns": started_ns, "ended_ns": ended_ns,
        "capture_count": sampled, "matching_count": matched,
        "transitions": transitions,
        "updates_per_second": len(transitions) * 1e9 / (ended_ns - started_ns),
    }


def measure_playback(bpy, nodes, scene, window, node, control, endpoints, duration, interval_ms,
                     *, signature, settled, wait_for, wait_palette):
    """Start and stop Blender's native Timeline and witness the selected frame."""
    fps = min(240, max(1, round(1000 / interval_ms)))
    scene.render.fps = fps
    scene.render.fps_base = fps * interval_ms / 1000
    scene.sync_mode = "NONE"
    scene.frame_start = 1
    scene.frame_end = max(4, math.ceil(duration * 1000 / interval_ms) + 3)
    scene.frame_set(1)
    neutral_signature = signature()
    values = [getattr(node, control)]
    values.extend(endpoints[index % len(endpoints)] for index in range(scene.frame_end - 1))
    tree = node.id_data
    path = node.path_from_id(control)
    try:
        with nodes._suspend(node):
            for frame, value in enumerate(values, start=1):
                setattr(node, control, value)
                if not tree.keyframe_insert(data_path=path, frame=frame):
                    raise RuntimeError(f"Blender rejected the {control} keyframe at {frame}")
            setattr(node, control, values[0])
        animation = tree.animation_data
        strip = animation.action.layers[0].strips[0]
        curve = strip.channelbag(animation.action_slot).fcurves.find(path)
        for key in curve.keyframe_points:
            key.interpolation = "CONSTANT"
        scene.frame_set(1)
        yield from wait_for(lambda: settled(neutral_signature), "Playback baseline did not become current")
        yield from wait_palette(neutral_signature)

        frames = []
        worker_times = []
        delivery_times = []
        installation_times = []
        original_transition = nodes._dispatch_transition
        preparation = nodes._preparation_runtime
        original_observer = preparation.on_event

        def observe_preparation(event, **fields):
            if (event == "preparation_execute_finish" and fields["lane"] == "grade"
                    and fields["error"] is None):
                worker_times.append(time.perf_counter_ns())
            if original_observer is not None:
                original_observer(event, **fields)

        def observe_frame(changed_scene, *_args):
            if changed_scene == scene:
                gate = nodes._grade_resources.gate
                identity = scene.as_pointer()
                frames.append({
                    "frame": scene.frame_current, "value": getattr(node, control),
                    "observed_ns": time.perf_counter_ns(),
                    "compositor_job": bpy.app.is_job_running("COMPOSITE"),
                    "compositor_lease": gate.evaluation_active("compositor", identity),
                    "render_lease": gate.evaluation_active("render", identity),
                })

        def observe_transition(target, record, event, *args, **kwargs):
            before = record["state"]
            effects, failures = original_transition(target, record, event, *args, **kwargs)
            after = record["state"]
            if target == node and event.error is None and not failures:
                now = time.perf_counter_ns()
                if event.kind == "preparation_result":
                    delivery_times.append(now)
                elif (event.kind in ("installation_result", "recovery_result")
                      and after.applied_signature == event.signature
                      and after.applied_signature != before.applied_signature):
                    installation_times.append(now)
            return effects, failures

        timeline = next(area for area in window.screen.areas if area.type == "DOPESHEET_EDITOR")
        region = next(region for region in timeline.regions if region.type == "WINDOW")
        screen = window.screen
        screen.use_play_3d_editors = True
        screen.use_play_image_editors = True
        screen.use_play_node_editors = True
        stopped_ns = None
        bpy.app.handlers.frame_change_post.append(observe_frame)
        nodes._dispatch_transition = observe_transition
        preparation.on_event = observe_preparation
        try:
            with bpy.context.temp_override(window=window, area=timeline, region=region):
                started_ns = time.perf_counter_ns()
                if bpy.ops.screen.animation_play() != {"FINISHED"}:
                    raise RuntimeError("Native Timeline playback did not start")
            yield from wait_for(lambda: screen.is_animation_playing, "Timeline did not enter playback")
            deadline = started_ns + round(duration * 1e9)
            while time.perf_counter_ns() < deadline:
                yield .01
        finally:
            try:
                if screen.is_animation_playing:
                    with bpy.context.temp_override(window=window, area=timeline, region=region):
                        stopped_ns = time.perf_counter_ns()
                        bpy.ops.screen.animation_cancel(restore_frame=False)
            finally:
                preparation.on_event = original_observer
                nodes._dispatch_transition = original_transition
                bpy.app.handlers.frame_change_post.remove(observe_frame)
        if stopped_ns is None or screen.is_animation_playing:
            raise RuntimeError("Native Timeline playback did not remain active until stopped")
        frame = scene.frame_current
        value = getattr(node, control)
        if not frames or value != values[frame - 1]:
            raise RuntimeError(f"Timeline did not evaluate {control} at the stopped frame {frame}")
        wanted = signature()
        yield from wait_for(lambda: settled(wanted), "Stopped Grade did not install the full selected frame")
        capture = yield from wait_palette(wanted, after_ns=stopped_ns)
        return started_ns, stopped_ns, {
            "frame_interval_ms": interval_ms, "evaluated_frames": frames,
            "worker_completions": sum(started_ns <= value < stopped_ns for value in worker_times),
            "delivered_preparations": sum(started_ns <= value < stopped_ns for value in delivery_times),
            "published_frames": sum(started_ns <= value < stopped_ns for value in installation_times),
            "stopped_frame": frame, "stopped_value": value, "stopped_signature": wanted,
            "stopped_capture": capture,
        }
    finally:
        tree.animation_data_clear()


def compare_controls(bpy, nodes, scene, window, node, widgets, recipes, report, config, *,
                     classify, capture_request, baseline, press, release, send,
                     signature, settled, wait_for, wait_palette, save):
    report["playback_comparison"] = {}
    duration = config["drag_duration"]
    interval_ms = config["interval_ms"]
    interval = round(interval_ms * 1e6)
    for control, calibration in report["profile"]["calibrated_endpoints"].items():
        endpoints = calibration
        palettes = {entry["value"]: entry["expected"] for entry in endpoints}
        point = widgets[control]
        offsets = recipes[control]
        yield from baseline()
        yield from wait_palette(signature())
        yield from press(point)
        started = next_motion = time.perf_counter_ns()
        deadline = started + round(duration * 1e9)
        count = 0
        while (now := time.perf_counter_ns()) < deadline:
            if now < next_motion:
                yield min(.01, (next_motion - now) / 1e9)
                continue
            index = count % len(offsets)
            send("MOUSEMOVE", "NOTHING", (point[0] + offsets[index], point[1]))
            yield from wait_for(lambda: getattr(node, control) == endpoints[index]["value"],
                                f"The native {control} drag did not accept an endpoint")
            count += 1
            next_motion = now + interval
        released = time.perf_counter_ns()
        yield from release(point)

        def cadence(start, stop):
            return visible_cadence(
                report["captures"], lambda observed: classify(observed, palettes),
                start, stop, request_id=capture_request,
            )

        drag = {**cadence(started, released), "accepted_endpoints": count}
        yield from baseline()
        start, stop, playback = yield from measure_playback(
            bpy, nodes, scene, window, node, control, tuple(palettes), duration, interval_ms,
            signature=signature, settled=settled,
            wait_for=wait_for, wait_palette=wait_palette,
        )
        report["playback_comparison"][control] = {
            "drag": drag, "playback": {**playback, **cadence(start, stop)},
        }
        save()
