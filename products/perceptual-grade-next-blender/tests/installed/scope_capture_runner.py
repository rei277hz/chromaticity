"""Exercise Next viewport capture through the installed extension in Blender GUI."""

import addon_utils
import hashlib
import importlib
import json
import os
from pathlib import Path
import sys
import time
import traceback

import bpy
import numpy as np


def main(repository, report_path):
    repository = Path(repository).resolve()
    report_path = Path(report_path)
    assert not bpy.app.background and tuple(bpy.app.version) == (5, 2, 2)
    bpy.context.preferences.view.show_splash = False
    bpy.context.preferences.system.gpu_backend = "OPENGL"
    bpy.context.preferences.extensions.repos.new(
        name="Next scope capture acceptance",
        module="pg_next_scope",
        custom_directory=str(repository),
    )
    name = "bl_ext.pg_next_scope.perceptual_grade"
    errors = []
    addon = addon_utils.enable(name, default_set=False, handle_error=errors.append)
    assert addon is not None and not errors, repr(errors)
    assert Path(addon.__file__).resolve() == repository / "perceptual_grade/__init__.py"

    grade_module = importlib.import_module(
        name + ".perceptual_grade_next_blender.native_grade"
    )
    scope = importlib.import_module(
        name + ".perceptual_grade_next_blender.scope_runtime"
    )
    capture_module = importlib.import_module(
        name + ".perceptual_grade_next_blender.scope_capture"
    )
    native = grade_module.build_native_grade(name="Installed Scope Evaluator")

    material = bpy.data.materials.new("Installed Scope Material")
    material.use_nodes = True
    material_tree = material.node_tree
    material_tree.nodes.clear()
    color = material_tree.nodes.new("ShaderNodeRGB")
    color.name = "Animated Input"
    color.outputs["Color"].default_value = (0.25, 0.4, 0.6, 1.0)
    owner = material_tree.nodes.new("ShaderNodeGroup")
    owner.node_tree = native.tree
    owner["perceptual_grade_next_backend"] = "native_grade_graph"
    owner["perceptual_grade_next_schema"] = 1
    owner["perceptual_grade_next_settings"] = native.tree[
        "perceptual_grade_next_settings"
    ]
    owner["perceptual_grade_next_edit_revision"] = 0
    owner["perceptual_grade_next_applied_revision"] = 0
    owner["perceptual_grade_next_preparation_state"] = "READY"
    owner["perceptual_grade_next_preparation_error"] = ""
    emission = material_tree.nodes.new("ShaderNodeEmission")
    surface = material_tree.nodes.new("ShaderNodeOutputMaterial")
    material_tree.links.new(color.outputs["Color"], owner.inputs["Color"])
    material_tree.links.new(owner.outputs["Color"], emission.inputs["Color"])
    material_tree.links.new(emission.outputs["Emission"], surface.inputs["Surface"])
    color_path = 'nodes["Animated Input"].outputs[0].default_value'
    for frame, value in ((1, (1.0, 0.05, 0.0, 1.0)),
                         (100, (0.0, 0.1, 1.0, 1.0))):
        color.outputs["Color"].default_value = value
        assert material_tree.keyframe_insert(data_path=color_path, frame=frame)

    obj = bpy.context.view_layer.objects.active
    if obj is None or obj.type != "MESH":
        mesh = bpy.data.meshes.new("Installed Scope Mesh")
        mesh.from_pydata(
            [(-1, -1, -1), (1, -1, -1), (1, 1, -1), (-1, 1, -1),
             (-1, -1, 1), (1, -1, 1), (1, 1, 1), (-1, 1, 1)],
            [],
            [(0, 1, 2, 3), (4, 7, 6, 5), (0, 4, 5, 1), (1, 5, 6, 2),
             (2, 6, 7, 3), (4, 0, 3, 7)],
        )
        obj = bpy.data.objects.new("Installed Scope Object", mesh)
        bpy.context.scene.collection.objects.link(obj)
    obj.data.materials.clear()
    obj.data.materials.append(material)
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)

    window = bpy.context.window
    view = next(area for area in window.screen.areas if area.type == "VIEW_3D")
    view.spaces.active.shading.type = "MATERIAL"
    view.spaces.active.shading.use_scene_world = False
    scene = bpy.context.scene

    def matrix_values(matrix):
        return tuple(tuple(float(value) for value in row) for row in matrix)

    def viewport_signature():
        space = view.spaces.active
        region_3d = space.region_3d
        shading = space.shading
        return (
            shading.type, shading.light, shading.studio_light,
            float(shading.studiolight_rotate_z), float(shading.studiolight_intensity),
            bool(shading.use_scene_world), bool(shading.use_scene_lights),
            matrix_values(region_3d.view_matrix),
            matrix_values(region_3d.window_matrix),
            matrix_values(region_3d.perspective_matrix),
            tuple(float(value) for value in region_3d.view_location),
            tuple(float(value) for value in region_3d.view_rotation),
            float(region_3d.view_distance), region_3d.view_perspective,
            int(scene.frame_current), str(scene.render.engine),
            scene.world.as_pointer() if scene.world else 0,
            scene.camera.as_pointer() if scene.camera else 0,
        )

    def render_result_signature():
        image = bpy.data.images.get("Render Result")
        if image is None:
            return None
        size = tuple(int(value) for value in image.size)
        channels = int(image.channels)
        values = np.empty(len(image.pixels), dtype=np.float32)
        image.pixels.foreach_get(values)
        digest = hashlib.sha256(values.tobytes()).hexdigest()
        return (image.as_pointer(), size, channels, bool(image.is_float), digest)

    def timeline_operator(name, **kwargs):
        region = next(region for region in view.regions if region.type == "WINDOW")
        with bpy.context.temp_override(window=window, area=view, region=region):
            getattr(bpy.ops.screen, name)(**kwargs)

    target_owner = "node:%d:%d" % (material_tree.as_pointer(), owner.as_pointer())
    runtime = scope.runtime()
    runtime.open_context(
        type("ViewContext", (), {"window": window, "area": view})(),
        target_owner=target_owner,
    )

    def graph_signature():
        trees = list(bpy.data.node_groups)
        trees.extend(material.node_tree for material in bpy.data.materials
                     if material.node_tree is not None)
        return tuple(
            (candidate.name, candidate.bl_idname,
             tuple((node.name, node.bl_idname) for node in candidate.nodes),
             tuple((link.from_node.name, link.from_socket.identifier,
                    link.to_node.name, link.to_socket.identifier)
                   for link in candidate.links))
            for candidate in trees
        )

    before_graphs = graph_signature()
    capture_observations = []
    native_capture = capture_module.capture_viewport

    def capture_with_observation(*args, **kwargs):
        request = runtime.state.request
        before_view = viewport_signature()
        before_render_result = render_result_signature()
        before_graph = graph_signature()
        observation = dict(
            request=request,
            frame=int(scene.frame_current),
            playing=runtime.playing,
            completed=False,
        )
        capture_observations.append(observation)
        report["capture_observations"] = capture_observations
        report["capture_phase"] = frame_probe["phase"]
        report_path.write_text(json.dumps(report, indent=2), encoding="utf8")
        result = native_capture(*args, **kwargs)
        after_view = viewport_signature()
        after_render_result = render_result_signature()
        after_graph = graph_signature()
        observation.update(dict(
            completed=True,
            mean=(list(result.payload.statistics.mean)
                  if result is not None and result.payload is not None else None),
            viewport_unchanged=before_view == after_view,
            viewport_changed_fields=[
                str(index) for index, (before, after)
                in enumerate(zip(before_view, after_view)) if before != after
            ],
            render_result_unchanged=before_render_result == after_render_result,
            render_result_present=before_render_result is not None,
            graph_unchanged=before_graph == after_graph,
        ))
        report["capture_observations"] = capture_observations
        report_path.write_text(json.dumps(report, indent=2), encoding="utf8")
        return result

    capture_module.capture_viewport = capture_with_observation
    report = dict(passed=False, blender=list(bpy.app.version),
                  extension_origin=str(Path(addon.__file__).resolve()),
                  capture_started=False, graph_unchanged=False)
    deadline = time.monotonic() + 180
    page_probe = dict(index=0, requested=False, selected=[])
    frame_probe = dict(phase="pages", observed_frames=[])

    def fail():
        report["error"] = traceback.format_exc()
        report_path.write_text(json.dumps(report, indent=2), encoding="utf8")
        print(report["error"], file=sys.stderr, flush=True)
        os._exit(1)

    def check_capture():
        try:
            if time.monotonic() >= deadline:
                raise TimeoutError(
                    "Installed viewport capture did not settle: phase=%r status=%r "
                    "frame=%r observed=%r request=%r native_ready=%r captures=%r"
                    % (frame_probe["phase"], runtime.presentation.status,
                       int(scene.frame_current), runtime._observed,
                       runtime.state.request, runtime.native_ready,
                       capture_observations)
                )
            presentation = runtime.presentation
            report["capture_started"] |= runtime.state.begun_request > 0

            if frame_probe["phase"] == "wait_stopped_frame":
                stopped = frame_probe["stopped_frame"]
                visual = presentation.displayed
                if (runtime._observed is None or runtime._observed[2] != stopped
                        or runtime.state.request <= frame_probe["prior_request"]
                        or visual is None
                        or visual.request != runtime.state.request
                        or visual is frame_probe["prior_visual"]):
                    return 0.05
                frame_probe["stopped_frame_capture"] = dict(
                    frame=stopped, request=visual.request,
                    prior_request=frame_probe["prior_request"],
                    new_visual=True,
                mean=list(visual.payload.statistics.mean),
                )
                frame_probe["original_frame_end"] = int(scene.frame_end)
                scene.frame_end = max(scene.frame_end, 1000)
                frame_probe["prior_visual"] = visual
                frame_probe["prior_request"] = runtime.state.request
                frame_probe["prior_capture_count"] = len(capture_observations)
                frame_probe["started_at"] = time.monotonic()
                frame_probe["phase"] = "playing"
                timeline_operator("animation_play")
                return 0.05

            if frame_probe["phase"] == "playing":
                playing = any(
                    getattr(candidate.screen, "is_animation_playing", False)
                    for manager in bpy.data.window_managers
                    for candidate in manager.windows
                )
                if not playing:
                    raise AssertionError("Timeline playback did not start")
                assert runtime.playing
                frame_probe["observed_frames"].append(int(scene.frame_current))
                assert runtime.state.request == frame_probe["prior_request"]
                assert presentation.displayed is frame_probe["prior_visual"]
                assert len(capture_observations) == frame_probe["prior_capture_count"]
                assert runtime.stage_display() is None
                if time.monotonic() - frame_probe["started_at"] < 0.8:
                    return 0.05
                assert len(set(frame_probe["observed_frames"])) >= 2, (
                    "Timeline did not advance during playback",
                    frame_probe["observed_frames"],
                )
                timeline_operator("animation_cancel", restore_frame=False)
                frame_probe["stopped_frame"] = int(scene.frame_current)
                scene.frame_end = frame_probe["original_frame_end"]
                frame_probe["phase"] = "wait_playback_stop"
                return 0.05

            if frame_probe["phase"] == "wait_playback_stop":
                playing = any(
                    getattr(candidate.screen, "is_animation_playing", False)
                    for manager in bpy.data.window_managers
                    for candidate in manager.windows
                )
                if playing:
                    return 0.05
                assert not runtime.playing
                stopped = frame_probe["stopped_frame"]
                visual = presentation.displayed
                if (runtime._observed is None or runtime._observed[2] != stopped
                        or runtime.state.request <= frame_probe["prior_request"]
                        or visual is None
                        or visual.request != runtime.state.request
                        or visual is frame_probe["prior_visual"]):
                    return 0.05
                assert len(capture_observations) > frame_probe["prior_capture_count"]
                assert capture_observations[-1]["frame"] == stopped
                assert not any(item["playing"] for item in capture_observations)
                initial_mean = frame_probe["initial_mean"]
                frame_mean = frame_probe["stopped_frame_capture"]["mean"]
                stopped_mean = list(visual.payload.statistics.mean)
                assert max(abs(a - b) for a, b in zip(initial_mean, frame_mean)) > 1e-4
                assert max(abs(a - b) for a, b in zip(frame_mean, stopped_mean)) > 1e-4
                frame_probe["playback"] = dict(
                    frames=sorted(set(frame_probe["observed_frames"])),
                    stopped_frame=stopped,
                    resumed_request=visual.request,
                    prior_request=frame_probe["prior_request"],
                    held_visual_during_playback=True,
                    no_capture_during_playback=True,
                    new_visual_after_stop=True,
                    initial_mean=initial_mean,
                    frame_mean=frame_mean,
                    stopped_mean=stopped_mean,
                    animated_input_changed_pixels=True,
                )
                frame_probe["phase"] = "complete"

            if presentation.status != "ready":
                if presentation.status == "failed":
                    raise RuntimeError("Viewport capture failed: %r" % presentation.failure)
                return 0.1
            visual = presentation.displayed
            analysis = visual.payload
            statistics = analysis.statistics
            assert scope._SCOPE_DRAW_HANDLER is not None
            assert len(analysis.histogram_rgb) == 3
            assert all(sum(channel) == statistics.sample_count
                       for channel in analysis.histogram_rgb)
            assert len(analysis.waveform_rgb) == 3
            assert all(sum(channel) == statistics.sample_count
                       for channel in analysis.waveform_rgb)
            assert sum(analysis.vectorscope_rg_bg) == statistics.sample_count
            assert statistics.width == view.width
            window_region = next(region for region in view.regions if region.type == "WINDOW")
            assert statistics.height == window_region.height
            assert statistics.sample_count == statistics.width * statistics.height
            assert all(map(lambda value: value == value, statistics.minimum + statistics.mean
                           + statistics.maximum))
            assert any(low < high for low, high in zip(statistics.minimum, statistics.maximum))
            requests = [item["request"] for item in capture_observations]
            assert requests and len(requests) == len(set(requests)), capture_observations
            assert all(item["graph_unchanged"] for item in capture_observations)
            assert all(item["viewport_unchanged"] for item in capture_observations), capture_observations
            assert all(item["render_result_unchanged"] for item in capture_observations), capture_observations
            assert graph_signature() == before_graphs
            displayed_identity = (
                visual.request, visual.source_revision, visual.source_id, visual.payload,
            )
            request_before_pages = runtime.state.request
            begun_before_pages = runtime.state.begun_request
            pages = ("histogram", "waveform", "vectorscope")
            if page_probe["index"] < len(pages):
                page = pages[page_probe["index"]]
                if not page_probe["requested"]:
                    assert runtime.select_page(page)
                    scope._SCOPE_LAST_DRAWN = None
                    view.tag_redraw()
                    page_probe["requested"] = True
                    return 0.05
                if scope._SCOPE_LAST_DRAWN != (visual.token.token, page):
                    view.tag_redraw()
                    return 0.05
                assert runtime.select_page(page)
                assert runtime.presentation.displayed == visual
                assert runtime.state.request == request_before_pages
                assert runtime.state.begun_request == begun_before_pages
                assert runtime.displayed_visual.source_id == displayed_identity[2]
                assert runtime.displayed_visual.source_revision == displayed_identity[1]
                assert runtime.displayed_visual.payload is displayed_identity[3]
                page_probe["selected"].append(runtime.selected_page)
                page_probe["index"] += 1
                page_probe["requested"] = False
                return 0.01
            selected_pages = page_probe["selected"]
            assert selected_pages == ["histogram", "waveform", "vectorscope"]
            assert len(capture_observations) == len(requests)
            if frame_probe["phase"] == "pages":
                frame_probe["prior_visual"] = visual
                frame_probe["initial_mean"] = list(visual.payload.statistics.mean)
                frame_probe["prior_request"] = runtime.state.request
                frame_probe["stopped_frame"] = 50
                frame_probe["phase"] = "wait_stopped_frame"
                scene.frame_set(frame_probe["stopped_frame"])
                return 0.05
            if frame_probe["phase"] != "complete":
                return 0.05
            report.update(
                passed=True,
                capture_started=report["capture_started"],
                owner=target_owner,
                request=visual.request,
                source_revision=visual.source_revision,
                capture_requests=requests,
                dimensions=[statistics.width, statistics.height],
                sample_count=statistics.sample_count,
                minimum=list(statistics.minimum),
                mean=list(statistics.mean),
                maximum=list(statistics.maximum),
                chart_sizes=dict(
                    histogram_bins=analysis.histogram_bins,
                    waveform=[analysis.waveform_width, analysis.waveform_height],
                    vectorscope=analysis.vectorscope_size,
                ),
                chart_counts=dict(
                    histogram=sum(analysis.histogram_rgb[0]),
                    waveform=sum(analysis.waveform_rgb[0]),
                    vectorscope=sum(analysis.vectorscope_rg_bg),
                ),
                selected_pages=selected_pages,
                page_switch_kept_display=True,
                overlay_handler_registered=True,
                graph_unchanged=True,
                viewport_unchanged=True,
                capture_observations=capture_observations,
                render_result_present=any(
                    item["render_result_present"] for item in capture_observations
                ),
                render_result_unchanged=True,
                stopped_frame_capture=frame_probe["stopped_frame_capture"],
                playback=frame_probe["playback"],
            )
            report_path.write_text(json.dumps(report, indent=2), encoding="utf8")
            addon.unregister()
            bpy.ops.wm.quit_blender("EXEC_DEFAULT")
            return None
        except BaseException:
            fail()

    report_path.write_text(json.dumps(report, indent=2), encoding="utf8")
    bpy.app.timers.register(check_capture, first_interval=0.5)


if __name__ == "__main__":
    main(*sys.argv[sys.argv.index("--") + 1:])
