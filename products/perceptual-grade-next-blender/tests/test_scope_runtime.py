import unittest
from dataclasses import replace
from unittest.mock import patch
from types import SimpleNamespace

from color_tools.perceptual_grade_next_blender.scope_runtime import ScopeRuntime


class ScopeRuntimeTests(unittest.TestCase):
    def _opened(self):
        runtime = ScopeRuntime()
        runtime.open("editor-a", app_owner="app")
        return runtime

    def test_view_transfer_keeps_one_actor_and_invalidates_old_display(self):
        runtime = self._opened()
        self.assertEqual(runtime.actor.state.owner, "app")
        self.assertIsNotNone(runtime.observe(1, "material-a", frame=1))
        ticket = runtime.begin_capture()
        self.assertTrue(runtime.complete_capture(ticket))
        visual = runtime.stage_display(payload="visual-a")
        self.assertIsNotNone(visual)
        self.assertTrue(runtime.apply_display(visual))
        self.assertFalse(runtime.apply_display(visual))

        self.assertTrue(runtime.move("editor-b"))
        self.assertEqual(runtime.actor.state.owner, "app")
        self.assertFalse(runtime.apply_display(visual))
        self.assertIsNone(runtime.displayed_visual)
        self.assertEqual(runtime.actor.state.view_epoch, runtime.view.view_epoch)

    def test_equal_observation_does_not_allocate_another_request(self):
        runtime = self._opened()
        first = runtime.observe(1, "material-a", frame=1)
        second = runtime.observe(1, "material-a", frame=1)
        self.assertEqual(first.request, 1)
        self.assertIsNone(second)
        self.assertEqual(runtime.actor.state.request, 1)

    def test_display_issuance_is_not_application(self):
        runtime = self._opened()
        runtime.observe(1, "image-a")
        self.assertTrue(runtime.complete_capture(runtime.begin_capture()))
        visual = runtime.stage_display()
        self.assertIsNotNone(visual)
        self.assertEqual(runtime.actor.state.display_token, visual.token.token)
        self.assertEqual(runtime.view.state.token, visual.token.token)
        self.assertNotEqual(runtime.actor.state.applied_token, visual.token.token)
        self.assertTrue(runtime.apply_display(visual))
        self.assertEqual(runtime.actor.state.applied_token, visual.token.token)
        self.assertEqual(runtime.view.state.applied_token, visual.token.token)

    def test_substituted_visual_cannot_consume_the_staged_receipt(self):
        runtime = self._opened()
        runtime.observe(1, "image-a")
        self.assertTrue(runtime.complete_capture(runtime.begin_capture()))
        visual = runtime.stage_display(payload="checked-analysis")
        before = (runtime.actor.state, runtime.view.state)

        self.assertFalse(runtime.apply_display(replace(visual, payload="substitution")))
        self.assertEqual((runtime.actor.state, runtime.view.state), before)
        self.assertIsNone(runtime.displayed_visual)
        self.assertTrue(runtime.apply_display(visual))
        self.assertIs(runtime.displayed_visual, visual)

    def test_foreground_issue_rejection_does_not_install_scope_receipt(self):
        runtime = self._opened()
        runtime.observe(1, "image-a")
        self.assertTrue(runtime.complete_capture(runtime.begin_capture()))
        runtime.view._state = replace(runtime.view.state, token="scope-display-1")
        before = (runtime.actor.state, runtime.view.state)

        self.assertIsNone(runtime.stage_display(payload="analysis"))
        self.assertEqual((runtime.actor.state, runtime.view.state), before)
        self.assertIsNone(runtime._staged_visual)

    def test_foreground_adoption_rejection_does_not_consume_scope_receipt(self):
        runtime = self._opened()
        runtime.observe(1, "image-a")
        self.assertTrue(runtime.complete_capture(runtime.begin_capture()))
        visual = runtime.stage_display(payload="analysis")
        runtime.view._state = replace(runtime.view.state, token="another-token")
        before = (runtime.actor.state, runtime.view.state)

        self.assertFalse(runtime.apply_display(visual))
        self.assertEqual((runtime.actor.state, runtime.view.state), before)
        self.assertIsNone(runtime.displayed_visual)

    def test_staged_visual_is_rejected_after_close_transfer_or_playback(self):
        for boundary in (lambda runtime: runtime.close(),
                         lambda runtime: runtime.move("editor-b"),
                         lambda runtime: runtime.playback_start()):
            with self.subTest(boundary=boundary):
                runtime = self._opened()
                runtime.observe(1, "image-a")
                self.assertTrue(runtime.complete_capture(runtime.begin_capture()))
                visual = runtime.stage_display(payload="analysis")
                self.assertTrue(boundary(runtime))
                before = (runtime.actor.state, runtime.view.state)

                self.assertFalse(runtime.apply_display(visual))
                self.assertEqual((runtime.actor.state, runtime.view.state), before)
                self.assertIsNone(runtime.displayed_visual)

    def test_local_failure_waits_for_retirement_then_retries_without_dropping_result(self):
        runtime = self._opened()
        runtime.observe(1, "image-a")
        self.assertTrue(runtime.complete_capture(runtime.begin_capture()))
        first_visual = runtime.stage_display(payload={"analysis": "first"})
        self.assertTrue(runtime.apply_display(first_visual))

        runtime.observe(2, "image-b")
        failed_ticket = runtime.begin_capture()
        self.assertTrue(runtime.fail_capture(failed_ticket, "native capture fault"))
        waiting = runtime.presentation
        self.assertEqual(waiting.status, "retiring_after_failure")
        self.assertEqual(waiting.displayed, first_visual)
        self.assertTrue(waiting.result_stale)
        self.assertFalse(waiting.can_retry)
        self.assertEqual(waiting.failure.message_key,
                         "PERCEPTUAL_GRADE_SCOPE_CAPTURE_FAILED")
        self.assertEqual(waiting.failure.diagnostic, "native capture fault")

        self.assertTrue(runtime.retire_capture(failed_ticket))
        failed = runtime.presentation
        self.assertEqual(failed.status, "failed")
        self.assertTrue(failed.can_retry)
        self.assertEqual(failed.displayed, first_visual)
        self.assertIsNone(runtime.observe(2, "image-b"))
        self.assertEqual(runtime.state.phase, "failed")

        retry = runtime.retry()
        self.assertEqual(retry.request, failed_ticket.request + 1)
        self.assertEqual(retry.source_id, "image-b")
        self.assertIsNone(runtime.presentation.failure)
        retry_ticket = runtime.begin_capture()
        self.assertTrue(runtime.complete_capture(retry_ticket))
        ready = runtime.presentation
        self.assertEqual(ready.status, "result_ready")
        self.assertTrue(ready.result_stale)
        retry_visual = runtime.stage_display(payload={"analysis": "second"})
        self.assertTrue(runtime.apply_display(retry_visual))
        self.assertEqual(runtime.presentation.status, "ready")
        self.assertFalse(runtime.presentation.result_stale)
        self.assertEqual(runtime.displayed_visual, retry_visual)

    def test_playback_retains_the_last_applied_visual_until_a_new_one_is_adopted(self):
        runtime = self._opened()
        runtime.observe(1, "frame-1", frame=1)
        self.assertTrue(runtime.complete_capture(runtime.begin_capture()))
        visual = runtime.stage_display(payload="frame-1-analysis")
        self.assertTrue(runtime.apply_display(visual))

        runtime.observe(2, "frame-2", frame=2)
        ticket = runtime.begin_capture()
        self.assertTrue(runtime.playback_start())
        self.assertEqual(runtime.presentation.status, "paused")
        self.assertEqual(runtime.presentation.displayed, visual)
        self.assertTrue(runtime.retire_capture(ticket))
        self.assertTrue(runtime.playback_stop())
        self.assertEqual(runtime.presentation.displayed, visual)
        self.assertTrue(runtime.presentation.result_stale)

    def test_closed_foreground_hides_the_retained_result_immediately(self):
        runtime = self._opened()
        runtime.observe(1, "image-a")
        self.assertTrue(runtime.complete_capture(runtime.begin_capture()))
        visual = runtime.stage_display(payload="analysis")
        self.assertTrue(runtime.apply_display(visual))
        self.assertTrue(runtime.close())
        self.assertIsNone(runtime.displayed_visual)
        self.assertEqual(runtime.presentation.status, "closed")

    def test_one_demand_cannot_start_two_physical_submissions(self):
        runtime = self._opened()
        runtime.observe(1, "image-a")
        ticket = runtime.begin_capture()
        self.assertIsNotNone(ticket)
        self.assertIsNone(runtime.begin_capture())
        self.assertTrue(runtime.complete_capture(ticket))
        self.assertIsNone(runtime.begin_capture())

    def test_playback_retires_old_capture_and_services_newest_source_after_stop(self):
        runtime = self._opened()
        runtime.observe(1, "frame-1", frame=1)
        ticket = runtime.begin_capture()
        self.assertTrue(runtime.playback_start())
        self.assertIsNone(runtime.observe(2, "frame-2", frame=2))
        self.assertTrue(runtime.retire_capture(ticket))
        self.assertTrue(runtime.playback_stop())
        self.assertEqual(runtime.actor.state.request, 2)
        self.assertEqual(runtime.actor.state.source_id, "frame-2")
        self.assertEqual(runtime.actor.state.physical, "none")

    def test_close_revokes_display_immediately_and_reopen_waits_for_retirement(self):
        runtime = self._opened()
        runtime.observe(1, "image-a")
        ticket = runtime.begin_capture()
        self.assertTrue(runtime.close())
        self.assertFalse(runtime.visible)
        with self.assertRaisesRegex(RuntimeError, "obligations"):
            runtime.open("editor-b")
        self.assertTrue(runtime.retire_capture(ticket))
        runtime.open("editor-b")
        self.assertEqual(runtime.generation, 2)
        self.assertEqual(runtime.actor.state.owner, "scope-app-2")

    def test_native_readiness_barrier_retains_newest_source(self):
        runtime = self._opened()
        runtime.set_native_ready(False)
        self.assertIsNone(runtime.observe(1, "image-a"))
        self.assertEqual(runtime.actor.state.request, 0)
        demand = runtime.set_native_ready(True)
        self.assertEqual(demand.source_id, "image-a")
        self.assertEqual(demand.request, 1)

    def test_frame_change_post_releases_only_after_dependency_updates_settle(self):
        from color_tools.perceptual_grade_next_blender import scope_runtime

        class Runtime:
            visible = True

            def __init__(self):
                self.observations = []

            def observe(self, revision, source_id, *, frame=None):
                self.observations.append((revision, source_id, frame))

        runtime = Runtime()
        scene = object()
        with (patch.object(scope_runtime, "_RUNTIME", runtime),
              patch.object(scope_runtime, "_scene_source",
                           return_value=(2, "scene:11:frame:2", 2)),
              patch.object(scope_runtime, "_DEPSGRAPH_IN_FLIGHT", {}),
              patch.object(scope_runtime, "_DEPSGRAPH_SETTLED", False)):
            scope_runtime._frame_change_post(scene)
            self.assertEqual(runtime.observations,
                             [(2, "scene:11:frame:2", 2)])
            self.assertTrue(scope_runtime._DEPSGRAPH_SETTLED)

            scope_runtime._DEPSGRAPH_IN_FLIGHT[11] = 1
            scope_runtime._frame_change_post(scene)
            self.assertFalse(scope_runtime._DEPSGRAPH_SETTLED)

    def test_viewport_source_ignores_inactive_studio_controls(self):
        from color_tools.perceptual_grade_next_blender.scope_runtime import (
            _effective_shading_source,
        )

        scene = SimpleNamespace(
            render=SimpleNamespace(engine="BLENDER_EEVEE_NEXT"),
        )
        shading = SimpleNamespace(
            type="RENDERED", light="STUDIO", studio_light="paint.sl",
            studiolight_rotate_z=0.0, studiolight_intensity=1.0,
            use_scene_world=False, use_scene_lights=False,
        )
        rendered = _effective_shading_source(scene, shading)
        shading.studio_light = "forest.exr"
        shading.studiolight_rotate_z = 1.25
        shading.studiolight_intensity = 2.0
        self.assertEqual(_effective_shading_source(scene, shading), rendered)
        shading.use_scene_world = True
        rendered_world = _effective_shading_source(scene, shading)
        self.assertNotEqual(rendered_world, rendered)
        scene.render.engine = "BLENDER_CYCLES"
        self.assertNotEqual(_effective_shading_source(scene, shading), rendered_world)

        shading.type = "MATERIAL"
        shading.use_scene_world = False
        scene.render.engine = "BLENDER_EEVEE_NEXT"
        preview = _effective_shading_source(scene, shading)
        shading.studio_light = "city.exr"
        self.assertNotEqual(_effective_shading_source(scene, shading), preview)
        shading.use_scene_world = True
        world_preview = _effective_shading_source(scene, shading)
        shading.studio_light = "studio.exr"
        shading.studiolight_rotate_z = 2.5
        shading.studiolight_intensity = 0.25
        self.assertEqual(_effective_shading_source(scene, shading), world_preview)
        scene.render.engine = "BLENDER_CYCLES"
        self.assertEqual(_effective_shading_source(scene, shading), world_preview)

    def test_context_owner_tracks_window_and_area_incarnation(self):
        from color_tools.perceptual_grade_next_blender.scope_runtime import context_owner

        window_a = SimpleNamespace(as_pointer=lambda: 11)
        area_a = SimpleNamespace(as_pointer=lambda: 21)
        area_b = SimpleNamespace(as_pointer=lambda: 22)
        self.assertEqual(
            context_owner(SimpleNamespace(window=window_a, area=area_a)),
            "view:11:21",
        )
        self.assertNotEqual(
            context_owner(SimpleNamespace(window=window_a, area=area_a)),
            context_owner(SimpleNamespace(window=window_a, area=area_b)),
        )

    def test_view_area_selection_prefers_last_observed_then_largest(self):
        from color_tools.perceptual_grade_next_blender.scope_runtime import (
            _choose_view_area,
        )

        preferred = SimpleNamespace(
            type="VIEW_3D", width=400, height=300, as_pointer=lambda: 22,
        )
        largest = SimpleNamespace(
            type="VIEW_3D", width=1200, height=800, as_pointer=lambda: 33,
        )
        other = SimpleNamespace(
            type="NODE_EDITOR", width=2000, height=1200, as_pointer=lambda: 44,
        )
        window = SimpleNamespace(
            screen=SimpleNamespace(areas=[preferred, largest, other]),
        )
        self.assertIs(_choose_view_area(window, 22), preferred)
        self.assertIs(_choose_view_area(window, 999), largest)

        window.screen.areas.remove(preferred)
        self.assertIs(_choose_view_area(window, 22), largest)
        window.screen.areas.clear()
        self.assertIsNone(_choose_view_area(window, 22))

    def test_removed_owned_view_transfers_to_fallback_without_relabeling_capture(self):
        from color_tools.perceptual_grade_next_blender import scope_runtime

        old_area = SimpleNamespace(
            type="VIEW_3D", width=500, height=400, as_pointer=lambda: 22,
            spaces=SimpleNamespace(active=SimpleNamespace(show_gizmo=False)),
        )
        fallback = SimpleNamespace(
            type="VIEW_3D", width=900, height=700, as_pointer=lambda: 33,
            spaces=SimpleNamespace(active=SimpleNamespace(show_gizmo=False)),
            tag_redraw=lambda: None,
        )
        window = SimpleNamespace(
            screen=SimpleNamespace(areas=[old_area, fallback]),
            view_layer=SimpleNamespace(objects=SimpleNamespace(active=None)),
            scene=object(),
            as_pointer=lambda: 11,
        )
        old_context = SimpleNamespace(window=window, area=old_area)
        runtime = ScopeRuntime()
        runtime.open_context(old_context, app_owner="app")
        runtime.observe(1, "viewport:source-a")
        ticket = runtime.begin_capture()
        old_owner = runtime.view.owner
        old_epoch = runtime.view.view_epoch

        window.screen.areas.remove(old_area)
        previous_runtime = scope_runtime._RUNTIME
        previous_last_areas = dict(scope_runtime._LAST_VIEW_AREA_BY_WINDOW)
        scope_runtime._RUNTIME = runtime
        scope_runtime._LAST_VIEW_AREA_BY_WINDOW.clear()
        scope_runtime._LAST_VIEW_AREA_BY_WINDOW[11] = 999
        try:
            context = scope_runtime._recover_owned_view_context(
                SimpleNamespace(context=SimpleNamespace(
                    window_manager=SimpleNamespace(windows=[window]),
                )),
            )
            self.assertIsNotNone(context)
            self.assertIs(context.area, fallback)
            self.assertNotEqual(runtime.view.owner, old_owner)
            self.assertGreater(runtime.view.view_epoch, old_epoch)
            self.assertTrue(fallback.spaces.active.show_gizmo)
            self.assertEqual(ticket.owner, "app")
            self.assertEqual(ticket.view_epoch, old_epoch)
            self.assertFalse(runtime.complete_capture(ticket))
            self.assertEqual(runtime.state.physical, "none")
        finally:
            scope_runtime._RUNTIME = previous_runtime
            scope_runtime._LAST_VIEW_AREA_BY_WINDOW.clear()
            scope_runtime._LAST_VIEW_AREA_BY_WINDOW.update(previous_last_areas)

    def test_target_source_tracks_only_installed_evaluator_changes(self):
        from color_tools.perceptual_grade_next_blender.scope_runtime import _target_source

        class DataBlock:
            def __init__(self, pointer, values=None):
                self.pointer = pointer
                self.values = values or {}

            def as_pointer(self):
                return self.pointer

            def get(self, name, default=None):
                return self.values.get(name, default)

        inner_tree = DataBlock(31)
        node = DataBlock(22, {
            "perceptual_grade_next_backend": "native_grade_graph",
            "perceptual_grade_next_edit_revision": 8,
            "perceptual_grade_next_applied_revision": 5,
        })
        node.node_tree = inner_tree
        owner_tree = DataBlock(11)
        owner_tree.nodes = [node]
        bpy = SimpleNamespace(data=SimpleNamespace(node_groups=[owner_tree]))

        installed = _target_source(bpy, "node:11:22")
        self.assertEqual(installed, (11, 22, "native_grade_graph", 5, "", "", 31))
        node.values["perceptual_grade_next_edit_revision"] = 9
        self.assertEqual(_target_source(bpy, "node:11:22"), installed)
        node.values["perceptual_grade_next_applied_revision"] = 6
        self.assertNotEqual(_target_source(bpy, "node:11:22"), installed)

    def test_stack_target_source_tracks_preview_to_final_evaluator(self):
        from color_tools.perceptual_grade_next_blender.scope_runtime import _target_source

        class DataBlock:
            def __init__(self, pointer, values=None):
                self.pointer = pointer
                self.values = values or {}

            def as_pointer(self):
                return self.pointer

            def get(self, name, default=None):
                return self.values.get(name, default)

        stack_tree = DataBlock(31)
        node = DataBlock(22, {
            "perceptual_grade_next_backend": "native_stack_lut",
            "perceptual_grade_next_applied_revision": 3,
            "perceptual_grade_next_stack_quality_tier": "33^3",
            "perceptual_grade_next_stack_evaluator": "preview-a",
        })
        node.node_tree = stack_tree
        owner_tree = DataBlock(11)
        owner_tree.nodes = [node]
        bpy = SimpleNamespace(data=SimpleNamespace(node_groups=[owner_tree]))

        preview = _target_source(bpy, "node:11:22")
        node.values["perceptual_grade_next_stack_quality_tier"] = "65^3"
        node.values["perceptual_grade_next_stack_evaluator"] = "final-a"
        self.assertNotEqual(_target_source(bpy, "node:11:22"), preview)

    def test_material_owned_grade_is_found_and_tracks_applied_revision(self):
        from color_tools.perceptual_grade_next_blender.scope_runtime import (
            _target_exists, _target_source,
        )

        class DataBlock:
            def __init__(self, pointer, values=None):
                self.pointer = pointer
                self.values = values or {}

            def as_pointer(self):
                return self.pointer

            def get(self, name, default=None):
                return self.values.get(name, default)

        native = DataBlock(31)
        node = DataBlock(22, {
            "perceptual_grade_next_backend": "native_grade_graph",
            "perceptual_grade_next_applied_revision": 7,
        })
        node.node_tree = native
        tree = DataBlock(11)
        tree.nodes = [node]
        material = SimpleNamespace(node_tree=tree)
        bpy = SimpleNamespace(data=SimpleNamespace(
            node_groups=[], materials=[material], worlds=[], lights=[], cameras=[], scenes=[],
        ))

        identity = "node:11:22"
        self.assertTrue(_target_exists(bpy, identity))
        source = _target_source(bpy, identity)
        self.assertEqual(source, (11, 22, "native_grade_graph", 7, "", "", 31))
        node.values["perceptual_grade_next_applied_revision"] = 8
        self.assertNotEqual(_target_source(bpy, identity), source)

    def test_scene_linear_capture_analysis_returns_channel_statistics(self):
        import numpy as np
        from color_tools.perceptual_grade_next_blender.scope_capture import (
            HISTOGRAM_BINS, VECTORSCOPE_SIZE, WAVEFORM_HEIGHT, WAVEFORM_WIDTH,
            ScopeAnalysis, analyze_scene_linear_rgba,
        )

        pixels = np.array([
            [[-1.0, 0.0, 0.5, 0.0], [1.0, 2.0, 3.0, 1.0]],
            [[0.0, 1.0, 1.5, 0.25], [2.0, 1.0, -0.5, 0.5]],
        ], dtype=np.float32)
        result = analyze_scene_linear_rgba(pixels)
        self.assertIsInstance(result, ScopeAnalysis)
        self.assertEqual(
            (result.statistics.width, result.statistics.height,
             result.statistics.sample_count), (2, 2, 4),
        )
        self.assertEqual(result.statistics.minimum, (-1.0, 0.0, -0.5))
        self.assertEqual(result.statistics.maximum, (2.0, 2.0, 3.0))
        np.testing.assert_allclose(result.statistics.mean, (0.5, 1.0, 1.125))
        self.assertEqual(result.histogram_bins, HISTOGRAM_BINS)
        self.assertEqual(len(result.histogram_rgb), 3)
        self.assertTrue(all(len(channel) == HISTOGRAM_BINS
                            for channel in result.histogram_rgb))
        self.assertTrue(all(sum(channel) == 4 for channel in result.histogram_rgb))
        self.assertEqual((result.waveform_width, result.waveform_height),
                         (WAVEFORM_WIDTH, WAVEFORM_HEIGHT))
        self.assertTrue(all(len(channel) == WAVEFORM_WIDTH * WAVEFORM_HEIGHT
                            for channel in result.waveform_rgb))
        self.assertTrue(all(sum(channel) == 4 for channel in result.waveform_rgb))
        self.assertEqual(result.vectorscope_size, VECTORSCOPE_SIZE)
        self.assertEqual(len(result.vectorscope_rg_bg), VECTORSCOPE_SIZE ** 2)
        self.assertEqual(sum(result.vectorscope_rg_bg), 4)
        with self.assertRaises(AttributeError):
            result.histogram_bins = 8

    def test_chart_analysis_counts_known_constant_and_extreme_pixels(self):
        import numpy as np
        from color_tools.perceptual_grade_next_blender.scope_capture import (
            analyze_scene_linear_rgba,
        )

        pixels = np.array([
            [[0.0, 0.0, 0.0, 0.0], [1.0, 1.0, 1.0, 0.25]],
        ], dtype=np.float32)
        result = analyze_scene_linear_rgba(pixels)
        self.assertEqual(result.histogram_rgb[0][0], 1)
        self.assertEqual(result.histogram_rgb[0][-1], 1)
        self.assertEqual(sum(result.histogram_rgb[0]), 2)
        self.assertEqual(sum(result.waveform_rgb[0]), 2)
        self.assertEqual(sum(result.vectorscope_rg_bg), 2)

        constant = analyze_scene_linear_rgba(
            np.full((2, 2, 4), (0.25, 0.25, 0.25, 1.0), dtype=np.float32)
        )
        self.assertEqual(sum(constant.histogram_rgb[0]), 4)
        self.assertEqual(sum(constant.waveform_rgb[0]), 4)
        self.assertEqual(sum(constant.vectorscope_rg_bg), 4)
        with self.assertRaisesRegex(ValueError, "non-finite"):
            analyze_scene_linear_rgba(np.full((1, 1, 4), np.nan, dtype=np.float32))

    def test_page_selection_is_presentational_and_retains_visual_provenance(self):
        runtime = self._opened()
        runtime.observe(4, "viewport:frame-12")
        ticket = runtime.begin_capture()
        self.assertTrue(runtime.complete_capture(ticket))
        payload = object()
        visual = runtime.stage_display(payload=payload)
        self.assertTrue(runtime.apply_display(visual))

        state = runtime.state
        request_count = runtime._request
        submission_count = runtime._submission
        display_count = runtime._display
        self.assertTrue(runtime.select_page("waveform"))
        self.assertEqual(runtime.selected_page, "waveform")
        self.assertEqual(runtime.presentation.selected_page, "waveform")
        self.assertIs(runtime.presentation.displayed, visual)
        self.assertIs(runtime.presentation.displayed.payload, payload)
        self.assertEqual(runtime.presentation.displayed.source_id, "viewport:frame-12")
        self.assertEqual(runtime.presentation.displayed.source_revision, 4)
        self.assertIs(runtime.state, state)
        self.assertEqual(runtime._request, request_count)
        self.assertEqual(runtime._submission, submission_count)
        self.assertEqual(runtime._display, display_count)
        self.assertFalse(runtime.select_page("falsecolor"))
        self.assertIs(runtime.presentation.displayed, visual)

    def test_selected_page_survives_source_change_and_old_visual_stays_provenanced(self):
        runtime = self._opened()
        runtime.observe(1, "source-a")
        self.assertTrue(runtime.complete_capture(runtime.begin_capture()))
        visual = runtime.stage_display(payload={"chart": "source-a"})
        self.assertTrue(runtime.apply_display(visual))
        runtime.select_page("vectorscope")
        runtime.observe(2, "source-b")
        self.assertEqual(runtime.presentation.selected_page, "vectorscope")
        self.assertTrue(runtime.presentation.result_stale)
        self.assertIs(runtime.presentation.displayed, visual)
        self.assertEqual(runtime.presentation.displayed.source_id, "source-a")
        self.assertEqual(runtime.presentation.displayed.source_revision, 1)

    def test_each_scope_page_draws_gpu_geometry_from_displayed_analysis(self):
        import sys
        import numpy as np
        from color_tools.perceptual_grade_next_blender.scope_capture import (
            analyze_scene_linear_rgba,
        )
        from color_tools.perceptual_grade_next_blender import scope_runtime

        calls = []

        class Shader:
            def bind(self):
                pass

            def uniform_float(self, *_args):
                pass

        class Batch:
            def __init__(self, primitive, content):
                self.primitive = primitive
                self.content = content

            def draw(self, _shader):
                calls.append((self.primitive, len(self.content.get("pos", ()))))

        shader = Shader()
        batch_module = SimpleNamespace(
            batch_for_shader=lambda _shader, primitive, content: Batch(primitive, content)
        )
        gpu_state = SimpleNamespace(
            blend_get=lambda: "NONE", depth_test_get=lambda: "LESS_EQUAL",
            blend_set=lambda _value: None, depth_test_set=lambda _value: None,
        )
        gpu_module = SimpleNamespace(
            state=gpu_state,
            shader=SimpleNamespace(from_builtin=lambda _name: shader),
        )
        blf_module = SimpleNamespace(
            size=lambda *_args: None, position=lambda *_args: None,
            color=lambda *_args: None, draw=lambda *_args: None,
        )
        window = SimpleNamespace(as_pointer=lambda: 11)
        area = SimpleNamespace(as_pointer=lambda: 22, type="VIEW_3D")
        region = SimpleNamespace(type="WINDOW", width=800, height=600)
        context = SimpleNamespace(window=window, area=area, region=region)
        bpy_module = SimpleNamespace(context=context)
        runtime = ScopeRuntime()
        runtime.open(scope_runtime.context_owner(context), app_owner="app")
        runtime.observe(1, "viewport-a")
        self.assertTrue(runtime.complete_capture(runtime.begin_capture()))
        analysis = analyze_scene_linear_rgba(np.array([
            [[0.0, 0.0, 0.0, 1.0], [1.0, 0.2, 0.4, 1.0]],
            [[0.2, 0.7, 0.1, 1.0], [0.4, 0.1, 1.0, 1.0]],
        ], dtype=np.float32))
        visual = runtime.stage_display(payload=analysis)
        self.assertTrue(runtime.apply_display(visual))
        previous_runtime = scope_runtime._RUNTIME
        scope_runtime._RUNTIME = runtime
        modules = {
            "bpy": bpy_module,
            "blf": blf_module,
            "gpu": gpu_module,
            "gpu_extras": SimpleNamespace(),
            "gpu_extras.batch": batch_module,
        }
        try:
            with patch.dict(sys.modules, modules):
                page_draws = {}
                for page in ("histogram", "waveform", "vectorscope"):
                    runtime.select_page(page)
                    scope_runtime._SCOPE_LAST_DRAWN = None
                    call_start = len(calls)
                    scope_runtime._draw_scope_overlay()
                    page_draws[page] = calls[call_start:]
                    self.assertEqual(
                        scope_runtime._SCOPE_LAST_DRAWN, (visual.token.token, page),
                    )
                    self.assertTrue(page_draws[page])
                    self.assertTrue(all(vertex_count > 0
                                        for _primitive, vertex_count in page_draws[page]))
            self.assertEqual(set(page_draws), {"histogram", "waveform", "vectorscope"})
        finally:
            scope_runtime._RUNTIME = previous_runtime

    def test_capture_retirement_waits_for_offscreen_release(self):
        from color_tools.perceptual_grade_next_blender import scope_capture
        from color_tools.perceptual_grade_next_blender import native_admission

        runtime = self._opened()
        runtime.observe(1, "viewport-a")
        ticket = runtime.begin_capture()

        class Offscreen:
            def __init__(self):
                self.attempts = 0

            def free(self):
                self.attempts += 1
                if self.attempts == 1:
                    raise RuntimeError("GPU release is still pending")

        offscreen = Offscreen()
        lease = native_admission.acquire_reader(
            "scope-pending-free", reader_probe=lambda: True,
        )
        scope_capture._fail_and_release(
            runtime, ticket, "native capture failed", offscreen, lease,
        )
        self.assertIsNone(native_admission.acquire_writer(
            "grade-waiting", reader_probe=lambda: True,
        ))
        self.assertEqual(runtime.state.phase, "retiring")
        self.assertEqual(runtime.state.physical, "retiring")
        self.assertEqual(runtime.presentation.status, "retiring_after_failure")
        self.assertFalse(runtime.presentation.can_retry)
        self.assertEqual(scope_capture.service_pending_releases(), 0)
        self.assertEqual(offscreen.attempts, 2)
        self.assertEqual(runtime.state.phase, "failed")
        self.assertEqual(runtime.state.physical, "none")
        self.assertTrue(runtime.presentation.can_retry)
        writer = native_admission.acquire_writer(
            "grade-after-scope", reader_probe=lambda: True,
        )
        self.assertIsNotNone(writer)
        self.assertTrue(native_admission.release(writer))

    def test_scope_lease_releases_when_capture_ticket_creation_raises(self):
        from color_tools.perceptual_grade_next_blender import native_admission
        from color_tools.perceptual_grade_next_blender import scope_capture

        runtime = self._opened()
        runtime.observe(1, "viewport-a")
        with patch(
            "color_tools.perceptual_grade_next_blender.native_admission"
            "._host_readers_idle", return_value=True,
        ), patch.object(runtime, "begin_capture", side_effect=RuntimeError("injected")):
            with self.assertRaisesRegex(RuntimeError, "injected"):
                scope_capture.capture_viewport(runtime, bpy_module=object())
        self.assertEqual(native_admission.reader_count(), 0)


if __name__ == "__main__":
    unittest.main()
