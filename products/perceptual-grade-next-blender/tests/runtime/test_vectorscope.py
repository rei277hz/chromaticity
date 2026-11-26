"""Verify the vectorscope's installed analysis and receipt decisions."""

from dataclasses import replace
import importlib
from importlib.resources import files
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import zipfile

import numpy as np


class VectorscopeTests(unittest.TestCase):
    FRAME = (91, 1, 0.)

    @classmethod
    def setUpClass(cls):
        directory = tempfile.TemporaryDirectory(prefix="pg-vectorscope-unit-")
        cls.addClassCleanup(directory.cleanup)
        package_name = "vectorscope_test_extension"
        package = Path(directory.name) / package_name
        with zipfile.ZipFile(files("tests.perceptual_grade_blender") / "extension.zip") as archive:
            archive.extractall(package)
        sys.path.insert(0, directory.name)
        cls.addClassCleanup(sys.path.remove, directory.name)
        scope = package_name + ".features.vectorscope."
        cls.policy = importlib.import_module(scope + "policy.scope")
        cls.runtime = importlib.import_module(scope + "runtime")
        cls.analysis = importlib.import_module(scope + "analysis")
        cls.appearance_scope = importlib.import_module(scope + "appearance_scope")
        cls.tone_scope = importlib.import_module(scope + "tone_scope")
        cls.appearance_preview = importlib.import_module(scope + "appearance_preview")
        cls.white_drag = importlib.import_module(scope + "white_drag")
        cls.kernel = importlib.import_module(package_name + ".kernel")
        cls.modcam16 = importlib.import_module(package_name + ".color_core.modcam16")
        cls.peaks = importlib.import_module(package_name + ".kernel.settings").TONE_PEAKS

    def observe(self, runtime, node, *, key=1, tone=None, dragging=False, frame=None):
        return runtime.observe_editor(
            key, None, node, frame=self.FRAME if frame is None else frame,
            stage="LINEAR" if tone is None else "TONE", dragging=dragging, tone=tone,
        )

    def observe_appearance(self, runtime, node, *, key=1, dragging=False, frame=None,
                           tone=None):
        state = runtime.observe_editor(
            key, None, node, frame=self.FRAME if frame is None else frame,
            stage="TONE", dragging=dragging,
            tone=self.kernel.ToneSettings() if tone is None else tone,
        )
        return self.appearance_result(state)

    @staticmethod
    def input_result(state):
        plot = state.rgba if state.rgba is not None else state.tone_histogram
        return plot, state.status, state.error

    @staticmethod
    def appearance_result(state):
        return state.appearance, state.appearance_status, state.appearance_error

    def test_request_and_capture_receipts_are_scalar_policy_decisions(self):
        state = self.policy.initial_state()
        request = self.policy.step(state, self.policy.Event(
            "request", capture_signature="frame one", source_signature="source",
            analysis_signature="analysis", revision=4,
        ))
        self.assertTrue(request.effects.enqueue)
        generation = request.state.scope.desired_generation
        scheduled = self.policy.step(request.state, self.policy.Event(
            "schedule", ticket_generation=generation,
        ))
        self.assertTrue(scheduled.effects.start)
        self.assertTrue(scheduled.state.scheduler.busy)
        started = self.policy.step(scheduled.state, self.policy.Event(
            "started", ticket_generation=generation,
        ))
        completed = self.policy.step(started.state, self.policy.Event(
            "capture_result", ticket_generation=generation, success=True, revision=4,
        ))
        self.assertTrue(completed.effects.publish)
        self.assertTrue(completed.effects.retain_samples)
        self.assertFalse(completed.state.scheduler.busy)
        self.assertEqual(
            self.policy.status(completed.state.scope, 4, True).status, "current",
        )

    def test_superseded_capture_can_publish_only_as_lagging_same_source(self):
        state = self.policy.initial_state()
        first = self.policy.step(state, self.policy.Event(
            "request", capture_signature="frame one", source_signature="source",
            analysis_signature="analysis one", revision=1,
        ))
        generation = first.state.scope.desired_generation
        active = self.policy.step(first.state, self.policy.Event(
            "schedule", ticket_generation=generation,
        ))
        latest = self.policy.step(active.state, self.policy.Event(
            "request", capture_signature="frame two", source_signature="source",
            analysis_signature="analysis two", revision=2,
        ))
        result = self.policy.step(latest.state, self.policy.Event(
            "capture_result", ticket_generation=generation, success=True,
            revision=1, allow_lagging=True,
        ))
        self.assertTrue(result.effects.publish)
        self.assertTrue(result.effects.retain_samples)
        self.assertIsNone(result.state.scope.published_current_generation)
        self.assertEqual(
            self.policy.status(result.state.scope, 2, True).status, "updating",
        )

    def test_same_source_grade_refresh_projects_retained_appearance(self):
        state = self.policy.initial_state()
        requested = self.policy.step(state, self.policy.Event(
            "request", capture_signature="appearance one", source_signature="source",
            analysis_signature="grade one", revision=1,
        ))
        generation = requested.state.scope.desired_generation
        started = self.policy.step(requested.state, self.policy.Event(
            "schedule", ticket_generation=generation,
        ))
        started = self.policy.step(started.state, self.policy.Event(
            "started", ticket_generation=generation,
        ))
        complete = self.policy.step(started.state, self.policy.Event(
            "capture_result", ticket_generation=generation, success=True, revision=1,
        ))
        replacement = self.policy.step(complete.state, self.policy.Event(
            "request", capture_signature="appearance two", source_signature="source",
            analysis_signature="grade two", revision=2,
        ))
        readout = self.policy.project(
            complete.state.scope, replacement.state.scope,
            True, True, True, True, 1, 2, False, False,
        )
        self.assertEqual(readout.appearance_status, "retained")
        self.assertTrue(readout.appearance_show_plot)

        replacement_source = self.policy.step(replacement.state, self.policy.Event(
            "request", capture_signature="appearance three", source_signature="source two",
            analysis_signature="grade two", revision=3,
        ))
        readout = self.policy.project(
            complete.state.scope, replacement_source.state.scope,
            True, True, True, True, 1, 3, False, False,
        )
        self.assertEqual(readout.appearance_status, "updating")
        self.assertTrue(readout.appearance_show_plot)

    def test_preview_failure_keeps_last_preview_visible(self):
        scope = self.policy.initial_state()
        requested = self.policy.step(scope, self.policy.Event(
            "preview_request", revision=3, preview_input_signature="input",
            preview_grade_signature="grade",
        ))
        completed = self.policy.step(requested.state, self.policy.Event(
            "preview_result", revision=3, preview_input_signature="input",
            preview_grade_signature="grade", success=True,
        ))
        failed_request = self.policy.step(completed.state, self.policy.Event(
            "preview_request", revision=4, preview_input_signature="input",
            preview_grade_signature="next grade",
        ))
        failure = self.policy.step(failed_request.state, self.policy.Event(
            "preview_result", revision=4, preview_input_signature="input",
            preview_grade_signature="next grade", success=False,
        ))
        self.assertFalse(failure.effects.publish_preview)
        input_state = replace(
            self.policy.ScopeState(), generation=1, desired_generation=1,
            capture_signature="input", source_signature="source",
            source_generation=1, revision=0, published_capture_generation=1,
            published_current_generation=1, published_source_generation=1,
        )
        readout = self.policy.project(
            input_state, failure.state.scope,
            True, True, True, True, 0, 4, False, False,
        )
        self.assertEqual(readout.appearance_status, "retained")
        self.assertTrue(readout.appearance_show_plot)

    def test_stale_receipts_and_waiting_scopes_cannot_start(self):
        state = self.policy.initial_state()
        requested = self.policy.step(state, self.policy.Event(
            "request", capture_signature="waiting", source_signature="source",
            analysis_signature="analysis", ready=False,
        ))
        generation = requested.state.scope.desired_generation
        waiting = self.policy.step(requested.state, self.policy.Event(
            "schedule", ticket_generation=generation,
        ))
        self.assertEqual(waiting, self.policy.Transition(requested.state, self.policy.Effects()))
        stale = self.policy.step(requested.state, self.policy.Event(
            "started", ticket_generation=generation,
        ))
        self.assertEqual(stale, self.policy.Transition(requested.state, self.policy.Effects()))

    def test_reset_preserves_active_fence_until_capture_retires(self):
        state = self.policy.initial_state()
        requested = self.policy.step(state, self.policy.Event(
            "request", capture_signature="active", source_signature="source",
            analysis_signature="analysis",
        ))
        generation = requested.state.scope.desired_generation
        scheduled = self.policy.step(requested.state, self.policy.Event(
            "schedule", ticket_generation=generation,
        ))
        reset = self.policy.step(scheduled.state, self.policy.Event("reset"))
        self.assertTrue(reset.effects.cancel)
        self.assertEqual(reset.state.scope.active_generation, generation)
        self.assertTrue(reset.state.scheduler.busy)

    def test_runtime_queue_is_fifo_and_coalesces_queued_editor_demand(self):
        runtime = self.runtime.ScopeRuntime(
            lambda _route: None, lambda _node: None, lambda: None,
            create_job=Mock(),
        )
        runtime._dispatch(1, self.policy.Event(
            "request", capture_signature="first", source_signature="s1",
            analysis_signature="a1",
        ))
        runtime._dispatch(2, self.policy.Event(
            "request", capture_signature="second", source_signature="s2",
            analysis_signature="a2",
        ))
        runtime._dispatch(1, self.policy.Event(
            "request", capture_signature="first latest", source_signature="s1",
            analysis_signature="a1 latest",
        ))
        start = Mock()
        def start_and_ack(ticket):
            start(ticket)
            runtime._dispatch_ticket(ticket, "started")

        runtime._start = start_and_ack
        runtime._schedule_next()
        self.assertEqual(start.call_count, 1)
        self.assertEqual(start.call_args.args[0].key, 1)
        self.assertEqual(start.call_args.args[0].capture_signature, "first latest")
        self.assertEqual(tuple(key for key, _token in runtime.queue), (2,))

    def test_runtime_queue_removes_released_editor_and_keeps_other_entry(self):
        runtime = self.runtime.ScopeRuntime(
            lambda _route: None, lambda _node: None, lambda: None,
            create_job=Mock(),
        )
        runtime._dispatch(1, self.policy.Event(
            "request", capture_signature="first", source_signature="s1",
            analysis_signature="a1",
        ))
        runtime._dispatch(2, self.policy.Event(
            "request", capture_signature="second", source_signature="s2",
            analysis_signature="a2",
        ))
        runtime._dispatch(1, self.policy.Event("release"))
        self.assertNotIn(1, runtime.queued)
        self.assertEqual(tuple(key for key, _token in runtime.queue), (2,))

    def test_stale_start_receipt_cannot_remove_reopened_queue_entry(self):
        runtime = self.runtime.ScopeRuntime(
            lambda _route: None, lambda _node: None, lambda: None,
            create_job=Mock(),
        )
        runtime._dispatch(1, self.policy.Event(
            "request", capture_signature="first", source_signature="s1",
            analysis_signature="a1",
        ))
        old_ticket = runtime.queued[1][1]
        runtime._dispatch(1, self.policy.Event("release"))
        runtime._dispatch(1, self.policy.Event(
            "request", capture_signature="reopened", source_signature="s2",
            analysis_signature="a2",
        ))
        current_ticket = runtime.queued[1][1]
        effects = runtime._dispatch_ticket(old_ticket, "started")
        self.assertEqual(effects, self.policy.Effects())
        self.assertEqual(runtime.queued[1][1], current_ticket)
        self.assertEqual(tuple(key for key, _token in runtime.queue), (1,))

    def test_reset_removes_all_runtime_queue_entries(self):
        runtime = self.runtime.ScopeRuntime(
            lambda _route: None, lambda _node: None, lambda: None,
            create_job=Mock(),
        )
        for key in (1, 2):
            runtime._dispatch(key, self.policy.Event(
                "request", capture_signature=str(key), source_signature="source",
                analysis_signature="analysis",
            ))
        runtime.reset()
        self.assertEqual(tuple(runtime.queue), ())
        self.assertEqual(runtime.queued, {})
        self.assertTrue(all(state.desired_generation is None
                            for state in runtime.scope_states.values()))

    def test_runtime_release_rejects_late_success_and_advances_queue(self):
        first, second = Mock(), Mock()
        pixels = np.ones((1, 1, 4), dtype=np.float32)
        first.advance.side_effect = [None, {"rgba": pixels}]
        second.advance.return_value = {"rgba": pixels.copy()}
        backend = Mock()
        backend.create_job.side_effect = [first, second]
        tree = self.changed_id(100, "CompositorNodeTree")
        nodes = [self.changed_id(key, "Grade", id_data=tree) for key in (1, 2)]
        route = {"owner_kind": "compositor", "capture_signature": "frame",
                 "source_signature": "source"}
        with tempfile.TemporaryDirectory() as directory:
            roots = []

            def snapshot(_route):
                root = Path(directory) / str(len(roots))
                root.mkdir()
                roots.append(root)
                return root, root / "snapshot.blend", []

            runtime = self.runtime.ScopeRuntime(
                snapshot, lambda _node: self.kernel.LinearSettings(),
                lambda: "Linear Rec.709", create_job=backend.create_job,
            )
            with (patch.object(self.runtime.routes, "describe_vectorscope", return_value=route),
                  patch.object(self.runtime, "capture_loaded_image", return_value=None)):
                self.observe(runtime, nodes[0])
                self.observe(runtime, nodes[1], key=2)
                self.assertEqual(backend.create_job.call_count, 0)
                self.assertTrue(runtime.poll())
                self.assertTrue(runtime.poll())
                runtime.release(1)
                first.cancel.assert_called_once_with()
                self.assertTrue(roots[0].is_dir())
                self.assertTrue(runtime.poll())
                self.assertFalse(roots[0].exists())
                self.assertEqual(backend.create_job.call_count, 1)
                self.assertEqual(runtime.displays, {})
                self.assertEqual(len(runtime.samples), 0)
                self.assertTrue(runtime.poll())
                self.assertEqual(backend.create_job.call_count, 2)
                self.assertFalse(runtime.poll())
                self.assertFalse(roots[1].exists())
                trace, status, error = self.input_result(self.observe(runtime, nodes[1], key=2))
                self.assertIsNotNone(trace)
                self.assertEqual((status, error), ("current", None))

    def test_tone_switch_and_edits_reuse_the_linear_capture(self):
        pixels = np.ones((2, 2, 4), dtype=np.float32)
        backend = Mock()
        tree = self.changed_id(100, "CompositorNodeTree")
        node = self.changed_id(1, "Grade", id_data=tree, pg_use_bake=True)
        runtime = self.runtime.ScopeRuntime(
            Mock(), lambda _node: self.kernel.LinearSettings(),
            lambda: "Linear Rec.709", create_job=backend.create_job,
        )
        route = {"owner_kind": "compositor", "capture_signature": "frame one",
                 "source_signature": "source"}
        tone = self.kernel.ToneSettings()
        edited = replace(tone, input_nits=(*tone.input_nits[:3], 400.))
        with (patch.object(self.runtime.routes, "describe_vectorscope", return_value=route),
              patch.object(self.runtime, "capture_loaded_image", return_value=pixels) as capture):
            self.assertEqual(self.input_result(self.observe(runtime, node)),
                             (None, "updating", None))
            self.assertFalse(runtime.poll())
            self.assertEqual(runtime.tone_changed(node), ())

            first, status, error = self.input_result(self.observe(runtime, node, tone=tone))
            self.assertEqual((status, error), ("current", None))
            self.assertEqual(first.shape, (128,))
            self.assertEqual(runtime.tone_changed(node), (1,))
            self.assertEqual(runtime.linear_changed(node), (1,))
            self.assertIsNone(runtime.begin_white_drag(1, node, frame=self.FRAME))

            second, status, error = self.input_result(self.observe(runtime, node, tone=edited))
            self.assertEqual((status, error), ("current", None))
            self.assertFalse(np.array_equal(second, first))

            route["capture_signature"] = "frame two"
            self.assertEqual(self.input_result(self.observe(runtime, node)),
                             (None, "updating", None))
            self.assertEqual(capture.call_count, 1)
            self.assertFalse(runtime.poll())
            trace, status, error = self.input_result(self.observe(runtime, node))
            self.assertEqual(trace.shape[-1], 4)
            self.assertEqual((status, error), ("current", None))
            self.assertEqual(capture.call_count, 2)
            backend.create_job.assert_not_called()

    def test_pending_capture_publishes_the_latest_stage(self):
        job = Mock()
        job.advance.return_value = {"rgba": np.ones((1, 1, 4), dtype=np.float32)}
        backend = Mock()
        backend.create_job.return_value = job
        tree = self.changed_id(100, "CompositorNodeTree")
        node = self.changed_id(1, "Grade", id_data=tree, pg_use_bake=True)
        runtime = self.runtime.ScopeRuntime(
            lambda _route: (None, "snapshot.blend", []),
            lambda _node: self.kernel.LinearSettings(), lambda: "Linear Rec.709",
            create_job=backend.create_job,
        )
        route = {"owner_kind": "compositor", "capture_signature": "frame",
                 "source_signature": "source"}
        tone = self.kernel.ToneSettings()
        with (patch.object(self.runtime.routes, "describe_vectorscope", return_value=route),
              patch.object(self.runtime, "capture_loaded_image", return_value=None)):
            self.assertEqual(self.input_result(self.observe(runtime, node)),
                             (None, "updating", None))
            self.assertTrue(runtime.poll())
            self.assertEqual(self.input_result(self.observe(runtime, node, tone=tone)),
                             (None, "updating", None))
            self.assertFalse(runtime.poll())
            histogram, status, error = self.input_result(self.observe(runtime, node, tone=tone))
            self.assertEqual(histogram.shape, (128,))
            self.assertEqual((status, error), ("current", None))
            backend.create_job.assert_called_once()

    def test_final_appearance_waits_for_native_grade_and_refreshes_independently(self):
        pixels = np.ones((2, 2, 4), dtype=np.float32)
        route = {"owner_kind": "compositor", "capture_signature": "frame",
                 "source_signature": "source"}
        tree = self.changed_id(100, "CompositorNodeTree")
        node = self.changed_id(1, "Grade", id_data=tree, pg_use_bake=False)
        job = Mock()
        job.advance.return_value = {"rgba": pixels.copy()}
        backend = Mock()
        backend.create_job.return_value = job
        ready = Mock(side_effect=lambda grades: not grades)
        signature = Mock(return_value="initial Grade")
        runtime = self.runtime.ScopeRuntime(
            lambda _route: (None, "snapshot.blend", []),
            lambda _node: self.kernel.LinearSettings(), lambda: "Linear Rec.709",
            create_job=backend.create_job, upstream_ready=ready, grade_signature=signature,
            appearance_settle_seconds=0.,
        )
        tone = self.kernel.ToneSettings()

        def describe(*_args, scope_capture="input", **_kwargs):
            return dict(route, scope_capture=scope_capture)

        with (patch.object(self.runtime.routes, "describe_vectorscope", side_effect=describe),
              patch.object(self.runtime, "capture_loaded_image", return_value=pixels) as direct):
            self.observe(runtime, node, tone=tone)
            self.assertEqual(self.observe_appearance(runtime, node, tone=tone),
                             (None, "updating", None))
            ready.assert_called_with((node,))
            self.assertTrue(runtime.poll())
            self.assertTrue(runtime.poll())
            backend.create_job.assert_not_called()
            histogram, status, _error = self.input_result(self.observe(runtime, node, tone=tone))
            self.assertEqual(status, "current")

            ready.side_effect = None
            ready.return_value = True
            self.observe_appearance(runtime, node, tone=tone)
            self.assertTrue(runtime.poll())
            self.assertFalse(runtime.poll())
            plot, status, error = self.observe_appearance(runtime, node, tone=tone)
            self.assertEqual((status, error), ("current", None))
            self.assertIsInstance(plot, self.appearance_scope.AppearanceScope)
            request = backend.create_job.call_args.args[0]
            self.assertEqual(request["route"]["scope_capture"], "appearance")
            direct.assert_called_once()

            signature.return_value = "Grade with Warp edit"
            self.assertEqual(runtime.appearance_changed(node), (1,))
            self.assertEqual(self.observe_appearance(runtime, node, tone=tone),
                             (plot, "retained", None))
            self.assertEqual(self.input_result(self.observe(runtime, node, tone=tone)),
                             (histogram, "current", None))
            self.assertTrue(runtime.poll())
            job.advance.side_effect = RuntimeError("Capture failed")
            self.assertFalse(runtime.poll())
            _trace, status, error = self.observe_appearance(runtime, node, tone=tone)
            self.assertEqual((status, error), ("error", "Capture failed"))

            node.pg_use_bake = True
            self.assertEqual(self.observe_appearance(runtime, node, tone=tone),
                             (None, "bake", None))
            self.assertEqual(self.input_result(self.observe(runtime, node, tone=tone)),
                             (histogram, "current", None))

    def test_dirty_appearance_completion_cannot_publish(self):
        pixels = np.ones((2, 2, 4), dtype=np.float32)
        tree = self.changed_id(100, "CompositorNodeTree")
        node = self.changed_id(1, "Grade", id_data=tree, pg_use_bake=False, mute=False)
        initial_job = Mock()
        initial_job.advance.return_value = {"rgba": pixels.copy()}
        stale_job = Mock()
        stale_job.advance.side_effect = [None, {"rgba": pixels.copy()}]
        latest_job = Mock()
        latest_job.advance.return_value = {"rgba": pixels.copy()}
        backend = Mock()
        backend.create_job.side_effect = [initial_job, stale_job, latest_job]
        signature = Mock(return_value="original Grade")
        runtime = self.runtime.ScopeRuntime(
            lambda _route: (None, "snapshot.blend", []),
            lambda _node: self.kernel.LinearSettings(), lambda: "Linear Rec.709",
            create_job=backend.create_job, grade_signature=signature,
            appearance_settle_seconds=0.,
        )
        frame_token = ["frame one"]

        def describe(*_args, scope_capture="input", **_kwargs):
            return {"owner_kind": "compositor",
                    "capture_signature": (frame_token[0], scope_capture),
                    "source_signature": frame_token[0], "scope_capture": scope_capture}

        tone = self.kernel.ToneSettings()

        def readout(selected=node, *, frame=self.FRAME, stage="TONE"):
            return runtime.display_state(1, selected, frame=frame, stage=stage)

        with (patch.object(self.runtime.routes, "describe_vectorscope", side_effect=describe),
              patch.object(self.runtime, "capture_loaded_image", return_value=pixels)):
            self.observe(runtime, node, tone=tone)
            self.assertTrue(runtime.poll())
            self.assertTrue(runtime.poll())
            self.assertFalse(runtime.poll())
            previous_trace, status, error = self.appearance_result(readout())
            self.assertEqual((status, error), ("current", None))
            self.assertIsNotNone(previous_trace)

            signature.return_value = "first edit"
            self.assertEqual(runtime.appearance_changed(node), (1,))
            self.observe(runtime, node, tone=tone)
            self.assertTrue(runtime.poll())
            self.assertTrue(runtime.poll())
            signature.return_value = "second edit"
            self.assertEqual(runtime.appearance_changed(node), (1,))
            self.observe(runtime, node, tone=tone)
            self.assertTrue(runtime.poll())
            self.assertEqual(stale_job.advance.call_count, 2)
            self.assertEqual(self.appearance_result(readout()),
                             (previous_trace, "retained", None))
            self.assertEqual(readout().status, "current")

            self.assertTrue(runtime.poll())
            self.assertFalse(runtime.poll())
            self.assertEqual(readout().appearance_status, "current")
            self.assertIsNone(readout(stage="LINEAR"))
            self.assertIsNone(readout(self.changed_id(2, "Grade", id_data=tree)))
            changed_frame = (self.FRAME[0], 2, 0.)
            stale = readout(frame=changed_frame)
            self.assertEqual(stale.appearance_status, "updating")
            self.assertIsNotNone(stale.appearance)
            self.assertIsNone(readout(frame=(self.FRAME[0] + 1, 2, 0.)))
            self.assertEqual(runtime.frame_changed(self.FRAME[0]), (1,))
            frame_token[0] = "next frame"
            state = self.observe(runtime, node, frame=changed_frame, tone=tone)
            self.assertEqual(state.status, "updating")
            self.assertIsNotNone(state.tone_histogram)
            self.assertIsNotNone(state.appearance)
            self.assertEqual(state.appearance_status, "updating")

    def test_route_error_keeps_editor_bound_and_retries(self):
        tree = self.changed_id(100, "CompositorNodeTree")
        node = self.changed_id(1, "Grade", id_data=tree)
        runtime = self.runtime.ScopeRuntime(
            Mock(), lambda _node: self.kernel.LinearSettings(), lambda: "Linear Rec.709",
            create_job=Mock(),
        )
        route = {"owner_kind": "compositor", "capture_signature": "frame",
                 "source_signature": "source"}
        with patch.object(self.runtime.routes, "describe_vectorscope",
                          side_effect=[ValueError("Busy viewport"), route]):
            self.assertEqual(self.input_result(self.observe(runtime, node)),
                             (None, "error", "Busy viewport"))
            self.assertTrue(runtime.has_editor(1))
            self.assertEqual(runtime.linear_changed(node), (1,))
            state = runtime.display_state(1, node, frame=self.FRAME, stage="LINEAR")
            self.assertEqual(self.input_result(state), (None, "updating", None))
            self.assertEqual(self.input_result(self.observe(runtime, node)),
                             (None, "updating", None))

    def test_white_drag_receipt_survives_own_edit_until_source_changes(self):
        pixels = np.ones((2, 2, 4), dtype=np.float32)
        tree = self.changed_id(100, "CompositorNodeTree")
        node = self.changed_id(1, "Grade", id_data=tree)
        image = self.changed_id(4, "Image")
        linear = Mock(return_value=self.kernel.LinearSettings())
        runtime = self.runtime.ScopeRuntime(Mock(), linear, lambda: "Linear Rec.709", create_job=Mock())

        def describe(*_args, dependencies, **_kwargs):
            dependencies.append(image)
            return {"owner_kind": "compositor", "capture_signature": "frame",
                    "source_signature": "source"}

        with (patch.object(self.runtime.routes, "describe_vectorscope", side_effect=describe),
              patch.object(self.runtime, "capture_loaded_image", return_value=pixels)):
            self.observe(runtime, node)
            self.assertFalse(runtime.poll())
            receipt, samples, _settings, _space = runtime.begin_white_drag(1, node, frame=self.FRAME)
            self.assertFalse(samples.flags.writeable)
            linear.return_value = replace(linear.return_value, source_xy=(0.32, 0.33))
            self.assertEqual(runtime.linear_changed(node), (1,))
            self.assertIsNone(runtime.begin_white_drag(1, node, frame=self.FRAME))
            self.assertTrue(runtime.white_drag_current(receipt, node, frame=self.FRAME, stage="LINEAR"))
            self.observe(runtime, node)
            self.assertTrue(runtime.white_drag_current(receipt, node, frame=self.FRAME, stage="LINEAR"))
            self.assertEqual(runtime.invalidate(None, (image,)), (1,))
            self.assertFalse(runtime.white_drag_current(receipt, node, frame=self.FRAME, stage="LINEAR"))

    def test_shutdown_preserves_snapshot_until_capture_retires(self):
        tree = self.changed_id(100, "CompositorNodeTree")
        node = self.changed_id(1, "Grade", id_data=tree)
        job = Mock()
        job.retired.return_value = False
        route = {"owner_kind": "compositor", "capture_signature": "frame",
                 "source_signature": "source"}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "capture"
            root.mkdir()
            runtime = self.runtime.ScopeRuntime(
                lambda _route: (root, root / "snapshot.blend", []),
                lambda _node: self.kernel.LinearSettings(), lambda: "Linear Rec.709",
                create_job=Mock(return_value=job),
            )
            with (patch.object(self.runtime.routes, "describe_vectorscope", return_value=route),
                  patch.object(self.runtime, "capture_loaded_image", return_value=None)):
                self.observe(runtime, node)
                self.assertTrue(runtime.poll())
            runtime.begin_shutdown()
            runtime.begin_shutdown()
            job.cancel.assert_called_once_with()
            with self.assertRaisesRegex(RuntimeError, "before capture retirement"):
                runtime.finish_shutdown()
            self.assertTrue(root.is_dir())
            self.assertIsNotNone(runtime.active)
            job.retired.return_value = True
            runtime.finish_shutdown()
            self.assertFalse(root.exists())
            self.assertIsNone(runtime.active)
            self.assertFalse(runtime.scheduler.busy)

    def test_appearance_preview_waits_for_current_input_and_grade(self):
        pixels = np.ones((2, 2, 4), dtype=np.float32)
        tree = self.changed_id(100, "CompositorNodeTree")
        node = self.changed_id(1, "Grade", id_data=tree, pg_use_bake=False, mute=False)
        signature = Mock(return_value="initial Grade")
        roles = Mock(return_value=None)
        preview = Mock()
        preview.evaluate.return_value = pixels
        job = Mock()
        job.advance.return_value = {"rgba": pixels}
        backend = Mock()
        backend.create_job.return_value = job
        runtime = self.runtime.ScopeRuntime(
            lambda _route: (None, "snapshot.blend", []),
            lambda _node: self.kernel.LinearSettings(), lambda: "Linear Rec.709",
            create_job=backend.create_job, grade_signature=signature, preview_roles=roles,
            preview_backend=preview,
            appearance_settle_seconds=0.,
        )
        frame = "first frame"

        def describe(*_args, scope_capture="input", **_kwargs):
            return {"owner_kind": "compositor", "capture_signature": (frame, scope_capture),
                    "source_signature": frame, "scope_capture": scope_capture}

        def dragging():
            return self.observe_appearance(runtime, node, dragging=True)

        with (patch.object(self.runtime.routes, "describe_vectorscope", side_effect=describe),
              patch.object(self.runtime, "capture_loaded_image", return_value=pixels)):
            self.assertEqual(dragging(), (None, "updating", None))
            runtime.poll()
            self.assertEqual(dragging(), (None, "updating", None))
            preview.evaluate.assert_not_called()
            backend.create_job.assert_not_called()

            roles.return_value = object()
            trace, status, error = dragging()
            self.assertIsInstance(trace, self.appearance_scope.AppearanceScope)
            self.assertEqual((status, error), ("preview", None))
            self.assertEqual(dragging(), (trace, "preview", None))
            preview.evaluate.assert_called_once()
            signature.return_value = "edited Grade"
            edited_trace, status, error = dragging()
            self.assertEqual((status, error), ("preview", None))
            self.assertIsNot(edited_trace, trace)
            runtime.poll()
            self.assertEqual(preview.evaluate.call_count, 2)
            backend.create_job.assert_not_called()

            frame = "second frame"
            self.assertEqual(dragging(), (edited_trace, "updating", None))
            runtime.poll()
            changed_trace, status, error = dragging()
            self.assertIsInstance(changed_trace, self.appearance_scope.AppearanceScope)
            self.assertEqual((status, error), ("preview", None))
            self.assertIsNot(changed_trace, edited_trace)
            self.assertEqual(preview.evaluate.call_count, 3)
            node.mute = True
            self.assertEqual(dragging()[1], "unavailable")
            node.mute = False
            node.pg_use_bake = True
            self.assertEqual(dragging(), (None, "bake", None))
            node.pg_use_bake = False

            panel_trace, panel_status, panel_error = self.observe_appearance(
                runtime, node, dragging=False,
            )
            self.assertIsInstance(panel_trace, self.appearance_scope.AppearanceScope)
            self.assertEqual((panel_status, panel_error), ("preview", None))
            runtime.poll()
            runtime.poll()
            self.assertEqual(self.observe_appearance(runtime, node, dragging=False)[1], "current")
            backend.create_job.assert_called_once()
            runtime.reset()
            preview.close.assert_called_once()

    def test_appearance_preview_sample_subset_is_bounded_and_repeatable(self):
        source = np.arange(128 * 128 * 4, dtype=np.float32).reshape(128, 128, 4)
        first = self.appearance_preview._sample_subset(source)
        second = self.appearance_preview._sample_subset(source)
        self.assertEqual(first.shape, (1, 4096, 4))
        np.testing.assert_array_equal(first, second)
        self.assertEqual(first.dtype, np.float32)

    def test_cached_input_survives_successive_appearance_captures(self):
        runtime = self.runtime.ScopeRuntime(None, None, None, create_job=Mock())
        pixels = np.ones((1, 1, 4), dtype=np.float32)
        runtime._remember_samples("input", pixels.copy())
        for index in range(self.runtime.CACHE_LIMIT + 1):
            self.assertIsNotNone(runtime._cached_samples("input"))
            runtime._remember_samples(f"appearance {index}", pixels.copy())
        self.assertIn("input", runtime.samples)
        self.assertNotIn("appearance 0", runtime.samples)
        self.assertEqual(len(runtime.samples), self.runtime.CACHE_LIMIT)

    def make_runtime(self, watch, dependencies):
        runtime = self.runtime.ScopeRuntime(None, None, None, create_job=Mock())
        runtime.dependencies = {1: frozenset(dependencies)}
        runtime.watches = {1: watch}
        runtime.source_epochs = {1: next(runtime.epoch)}
        return runtime

    @staticmethod
    def changed_id(pointer, kind, **attributes):
        value = SimpleNamespace(
            bl_rna=SimpleNamespace(identifier=kind),
            as_pointer=lambda: pointer,
        )
        for name, item in attributes.items():
            setattr(value, name, item)
        return value

    def test_shader_tree_updates_skip_only_when_coverage_proof_passes(self):
        pointer = 23
        watch_type = self.runtime._ScopeWatch
        covered = watch_type(frozenset(), {}, frozenset({pointer}), 31, pointer,
                             True, True, "material", False)
        runtime = self.make_runtime(covered, (pointer,))
        tree = self.changed_id(pointer, "NodeTree")
        self.assertEqual(runtime.invalidate(None, (tree,)), ())
        self.assertEqual(runtime.source_epochs[1], 1)

        unproven = watch_type(frozenset(), {}, frozenset({pointer}), 31, pointer,
                              True, False, "material", False)
        runtime = self.make_runtime(unproven, (pointer,))
        self.assertEqual(runtime.invalidate(None, (tree,)), (1,))
        self.assertEqual(runtime.source_epochs[1], 2)

    def test_mesh_witness_compares_only_on_geometry_updates_and_advances_baseline(self):
        pointer = 37
        watch_type = self.runtime._ScopeWatch
        watch = watch_type(frozenset(), {pointer: "before"}, frozenset(), None, None,
                           False, False, "material", False)
        runtime = self.make_runtime(watch, (pointer,))
        mesh = self.changed_id(pointer, "Mesh", witness="before")
        with patch.object(self.runtime.routes, "vectorscope_mesh_witness",
                          side_effect=lambda value: value.witness):
            self.assertEqual(runtime.invalidate(None, (mesh,)), ())
            self.assertEqual(runtime.source_epochs[1], 1)
            mesh.witness = "after"
            self.assertEqual(runtime.invalidate(None, (mesh,)), (1,))
            self.assertEqual(runtime.watches[1].mesh_witnesses[pointer], "after")
            self.assertEqual(runtime.invalidate(None, (mesh,)), ())
            self.assertEqual(runtime.source_epochs[1], 2)

    def test_compositor_ignores_unrelated_objects_but_keeps_render_layer_dependencies(self):
        watch_type = self.runtime._ScopeWatch
        object_id = self.changed_id(41, "Object")
        without_layers = watch_type(frozenset(), {}, frozenset(), None, None,
                                    False, False, "compositor", False)
        runtime = self.make_runtime(without_layers, (17,))
        self.assertEqual(runtime.invalidate(None, (object_id,)), ())

        with_layers = watch_type(frozenset(), {}, frozenset(), None, None,
                                 False, False, "compositor", True)
        runtime = self.make_runtime(with_layers, (41,))
        self.assertEqual(runtime.invalidate(None, (object_id,)), (1,))

    def test_reopened_scope_rejects_prior_receipt_with_equal_signatures(self):
        state = self.policy.initial_state()
        requested = self.policy.step(state, self.policy.Event(
            "request", capture_signature="frame one", source_signature="source",
            analysis_signature="analysis", revision=1,
        ))
        generation = requested.state.scope.desired_generation
        active = self.policy.step(requested.state, self.policy.Event(
            "schedule", ticket_generation=generation,
        ))
        released = self.policy.step(active.state, self.policy.Event("release"))
        self.assertTrue(released.effects.clear)
        self.assertTrue(released.effects.cancel)
        self.assertEqual(released.state.scope.active_generation, generation)
        retired = self.policy.step(released.state, self.policy.Event(
            "capture_result", ticket_generation=generation, success=True,
            revision=1,
        ))
        self.assertFalse(retired.effects.publish)
        self.assertFalse(retired.effects.retain_samples)
        self.assertFalse(retired.state.scheduler.busy)

    def test_superseded_failure_is_inert_and_exact_failure_is_visible(self):
        state = self.policy.initial_state()
        first = self.policy.step(state, self.policy.Event(
            "request", capture_signature="frame one", source_signature="source",
            analysis_signature="analysis one", revision=1,
        ))
        first_generation = first.state.scope.desired_generation
        active = self.policy.step(first.state, self.policy.Event(
            "schedule", ticket_generation=first_generation,
        ))
        latest = self.policy.step(active.state, self.policy.Event(
            "request", capture_signature="frame two", source_signature="source",
            analysis_signature="analysis two", revision=2,
        ))
        stale_failure = self.policy.step(latest.state, self.policy.Event(
            "capture_result", ticket_generation=first_generation, revision=1,
            success=False, error="Capture failed",
        ))
        self.assertEqual(
            self.policy.status(stale_failure.state.scope, 2, True).status,
            "updating",
        )
        latest_generation = latest.state.scope.desired_generation
        scheduled = self.policy.step(stale_failure.state, self.policy.Event(
            "schedule", ticket_generation=latest_generation,
        ))
        failure = self.policy.step(scheduled.state, self.policy.Event(
            "capture_result", ticket_generation=latest_generation, revision=2,
            success=False, error="Capture failed",
        ))
        self.assertEqual(
            self.policy.status(failure.state.scope, 2, True).status, "error",
        )

    def test_linear_matrix_moves_density_to_rec709_target(self):
        rgba = np.array([[[1.0, 0.0, 0.0, 1.0]]])
        red_to_blue = np.array([[0, 0, 1], [0, 1, 0], [1, 0, 0]])
        density = self.analysis.density(rgba, red_to_blue, "Linear Rec.709")
        edges = np.linspace(-self.analysis.CHROMA_LIMIT, self.analysis.CHROMA_LIMIT,
                            self.analysis.SIZE + 1)
        blue_cr = -0.0722 / 1.5748
        expected = tuple(np.searchsorted(edges, coord) - 1 for coord in (blue_cr, 0.5))
        self.assertEqual(tuple(np.argwhere(density > 0)[0]), expected)
        self.assertEqual(density[expected], 1.0)
        self.assertFalse(density.flags.writeable)

    def test_density_weights_alpha_and_excludes_invalid_pixels(self):
        rgba = np.array([[[1, 0, 0, 1.0], [0, 1, 0, 0.25], [0, 0, 1, 0.0],
                          [0, np.nan, 1, 1.0], [1, 1, 0, np.inf]]])
        density = self.analysis.density(rgba, np.eye(3), "Linear Rec.709")
        levels = np.sort(density[density > 0])
        self.assertEqual(len(levels), 2)
        self.assertGreater(levels[1], levels[0])

    def test_raw_histogram_matches_density_sample_bins_and_alpha(self):
        rgba = np.array([[[1, 0, 0, 1.0], [0, 1, 0, 0.25], [0, 0, 1, 0.0],
                          [1, 1, 0, 2.0]]], dtype=np.float32)
        cr, cb, weights, edges = self.analysis.chroma_samples(
            rgba, np.eye(3), "Linear Rec.709", size=16)
        histogram = self.analysis.accumulate(cr, cb, weights, edges)
        brightness = self.analysis.normalize_histogram(histogram)

        self.assertEqual(histogram.shape, (16, 16))
        self.assertAlmostEqual(float(histogram.sum()), 2.25)
        np.testing.assert_array_equal(brightness, self.analysis.density(
            rgba, np.eye(3), "Linear Rec.709", size=16))
        self.assertFalse(brightness.flags.writeable)

    def test_empty_raw_histogram_normalizes_to_zero(self):
        histogram = np.zeros((8, 8), dtype=np.float64)
        brightness = self.analysis.normalize_histogram(histogram)
        np.testing.assert_array_equal(brightness, np.zeros((8, 8), dtype=np.float32))

    def test_appearance_scope_axis_mappings_have_requested_endpoints(self):
        scope = self.appearance_scope
        for peak in self.peaks:
            with self.subTest(peak=peak):
                tone = self.kernel.ToneSettings(peak_nits=peak)
                peak_j = self.tone_scope.peak_j(tone)
                maximum = 100. * self.kernel.prepare_tone(tone).target[-1]
                positions = scope.lightness_position([0., 100., maximum], peak_j)
                np.testing.assert_allclose(positions, [0., .8, 1.], atol=1e-12)
                positions = scope.lightness_position(np.linspace(0., maximum, 1025), peak_j)
                self.assertTrue((np.diff(positions) > 0.).all())
        self.assertEqual(float(scope.saturation_position(0.)), 0.)
        radius_k = self.kernel.settings.SATURATION_AXIS_SCALE
        self.assertAlmostEqual(float(scope.saturation_position(1.)),
                               1. / np.hypot(radius_k, 1.))
        self.assertAlmostEqual(float(scope.saturation_position(radius_k)),
                               1. / np.sqrt(2.))
        self.assertEqual(float(scope.saturation_position(np.inf)), 1.)
        np.testing.assert_array_equal(scope.saturation_position(np.array([0., np.inf], np.float32)),
                                      [0., 1.])

    def test_appearance_lightness_has_continuous_slope_and_curvature_at_reference(self):
        step = .01
        offsets = step * np.arange(-3, 4)
        for peak in self.peaks:
            with self.subTest(peak=peak):
                peak_j = self.tone_scope.peak_j(self.kernel.ToneSettings(peak_nits=peak))
                left, near_left, before, center, after, near_right, right = (
                    self.appearance_scope.lightness_position(100. + offsets, peak_j)
                )
                slope_left = (3 * center - 4 * before + near_left) / (2 * step)
                slope_right = (-3 * center + 4 * after - near_right) / (2 * step)
                curvature_left = (2 * center - 5 * before + 4 * near_left - left) / step**2
                curvature_right = (2 * center - 5 * after + 4 * near_right - right) / step**2
                self.assertAlmostEqual(slope_left, slope_right, places=8)
                self.assertLess(curvature_left, 0.)
                self.assertAlmostEqual(curvature_left, curvature_right, places=8)

    def test_appearance_scope_clips_samples_above_selected_peak(self):
        scope = self.appearance_scope
        peak_j = 3.0
        maximum = scope.lightness_max(peak_j)
        pixels = np.array([[[maximum + 1., 0., 0., .25], [50., 0., 0., .75],
                            [maximum + 4., 0., 0., 0.], [np.nan, 0., 0., 1.]]])
        result = scope.analyze(pixels, peak_j)
        self.assertEqual(result.peak_j, peak_j)
        self.assertEqual(result.rgba.shape, (144, 288, 4))
        self.assertFalse(result.rgba.flags.writeable)
        np.testing.assert_array_equal(result.rgba, scope.analyze(pixels[:, 1:2], peak_j).rgba)
        self.assertFalse(scope.analyze(pixels[:, :1], peak_j).rgba.any())

    def test_appearance_scope_places_selected_peak_and_infinite_saturation(self):
        scope = self.appearance_scope
        for peak in self.peaks:
            with self.subTest(peak=peak):
                peak_j = self.tone_scope.peak_j(self.kernel.ToneSettings(peak_nits=peak))
                for level, row in ((0., 0), (100., 115), (100. * peak_j, 143)):
                    density = scope.analyze([[[level, 0., 0., 1.]]], peak_j).rgba[..., 3]
                    self.assertEqual(np.unravel_index(np.argmax(density), density.shape), (row, 0))
                captured = np.array([[[100. * peak_j, 0., 0., 1.]]], dtype=np.float32)
                density = scope.analyze(captured, peak_j).rgba[..., 3]
                self.assertEqual(np.unravel_index(np.argmax(density), density.shape), (143, 0))
                captured[..., 0] = np.nextafter(captured[..., 0], np.float32(np.inf))
                self.assertFalse(scope.analyze(captured, peak_j).rgba.any())
                density = scope.analyze([[[0., 20., 0., 1.]]], peak_j).rgba[..., 3]
                self.assertEqual(np.unravel_index(np.argmax(density), density.shape)[1], 287)

    def test_retained_trace_rescales_to_new_peak(self):
        scope = self.appearance_scope
        low, high = (self.tone_scope.peak_j(self.kernel.ToneSettings(peak_nits=nits))
                     for nits in (500, 4000))
        for old, new in ((low, high), (high, low)):
            with self.subTest(old=old, new=new):
                pixels = [[[50., 0., 0., .5]]]
                original = scope.analyze(pixels, old)
                self.assertIs(scope.rescale(original, old), original)
                retained = scope.rescale(original, new)
                current = scope.analyze(pixels, new)
                self.assertEqual(retained.peak_j, new)
                self.assertFalse(retained.rgba.flags.writeable)
                expected = np.argmax(current.rgba[..., 3].sum(axis=1))
                actual = np.argmax(retained.rgba[..., 3].sum(axis=1))
                self.assertLessEqual(abs(int(actual) - int(expected)), 1)

    def test_appearance_scope_keeps_density_when_opposite_hues_cancel(self):
        scope = self.appearance_scope
        peak_j = 3.0
        opposing = scope.analyze(np.array([[[50., 20., 0., 1.], [50., -20., 0., 1.]]]), peak_j)
        hue = scope.analyze(np.array([[[50., 20., 0., 1.]]]), peak_j)
        occupied = opposing.rgba[..., 3] > 0.
        self.assertTrue(occupied.any())
        np.testing.assert_allclose(opposing.rgba[occupied, :3], .6, atol=1e-6)
        np.testing.assert_array_equal(opposing.rgba[..., 3], hue.rgba[..., 3])
        weighted = scope.analyze(np.array([[[50., 20., 0., 1.], [50., -20., 0., .25]]]), peak_j)
        np.testing.assert_allclose(weighted.rgba[occupied, :3] - .6,
                                   .6 * (hue.rgba[occupied, :3] - .6), atol=1e-6)

    def test_appearance_scope_fades_hue_toward_neutral_and_palette_is_luminance_constant(self):
        scope = self.appearance_scope
        peak_j = 3.0
        chromatic = scope.analyze(np.array([[[50., 8., 0., 1.]]]), peak_j)
        near_gray = scope.analyze(np.array([[[50., .2, 0., 1.]]]), peak_j)
        chromatic_rgb = chromatic.rgba[chromatic.rgba[..., 3] > 0., :3][0]
        neutral_rgb = near_gray.rgba[near_gray.rgba[..., 3] > 0., :3][0]
        self.assertGreater(np.linalg.norm(chromatic_rgb - .6), np.linalg.norm(neutral_rgb - .6))
        np.testing.assert_allclose([chromatic_rgb @ scope._REC709_LUMINANCE,
                                    neutral_rgb @ scope._REC709_LUMINANCE], .6)
        self.assertTrue(np.allclose(scope._RGB_ANCHORS @ scope._REC709_LUMINANCE, .6))

    def test_density_shoulder_lifts_logarithmic_response(self):
        histogram = np.array([[0.0, 1.0, 10.0, 159.0, 830.0]])
        brightness = self.analysis.normalize_histogram(histogram)
        fraction = histogram / histogram.sum()
        log_density = np.log1p(65535.0 * fraction) / np.log1p(65535.0)
        expected = (1.0 - np.exp(-log_density)) / (1.0 - np.exp(-1.0))
        np.testing.assert_allclose(brightness, expected, rtol=0, atol=1e-7)
        self.assertEqual(brightness[0, 0], 0.0)
        np.testing.assert_array_less(log_density[0, 1:], brightness[0, 1:])
        self.assertTrue(np.all(np.diff(brightness[0]) > 0.0))
        self.assertLess(float(brightness[0, -1]), 1.0)
        self.assertFalse(brightness.flags.writeable)

    def test_tone_histogram_uses_neutral_lightness_and_finite_alpha_mass(self):
        pixels = np.array([[[1., 1., 1., .25], [1., 1., 1., 0.], [np.inf, 1., 1., 1.]],
                           [[1., 1., 1., 1.], [1., 1., 1., np.nan], [0., 0., 0., 2.]]])
        linear = self.kernel.prepare_linear(space="ACEScg")
        defaults = self.kernel.ToneSettings()
        for peak in self.peaks:
            with self.subTest(peak=peak):
                tone = replace(defaults, peak_nits=peak, input_nits=(*defaults.input_nits[:3], peak))
                histogram = self.tone_scope.analyze(pixels, linear, tone)
                self.assertEqual(histogram.shape, (128,))
                white_bin = int(histogram.size / self.kernel.prepare_tone(tone).target[-1])
                np.testing.assert_array_equal(np.flatnonzero(histogram), [0, white_bin])
                np.testing.assert_array_equal(histogram[[0, white_bin]], [1., 1.25])
                self.assertFalse(histogram.flags.writeable)

    def test_tone_histogram_uses_post_tone_chroma_and_lightness(self):
        pixels = np.array([[[.07, .03, .015, 1.], [.015, .12, .025, .5]]])
        linear = self.kernel.prepare_linear(space="Linear Rec.709")
        tone = self.kernel.ToneSettings(
            input_nits=(3., 80., 216., 1200.), muted_gain=4., vivid_gain=4.,
        )
        prepared = self.kernel.prepare_tone(tone)
        cones = pixels[..., :3] @ linear.linear_to_cones.T
        captured = self.modcam16.encode_cones(cones, constants=(prepared.fl, prepared.aw))
        points = np.concatenate((captured.ja[..., None], captured.q[..., 1:]), axis=-1)
        toned = prepared.forward(points)
        chroma = np.hypot(toned[..., 1], toned[..., 2])
        lightness = self.modcam16.signed_hk(toned[..., 0], chroma) / 100.
        expected = np.histogram(lightness, bins=128, range=(0., self.tone_scope.peak_j(tone)),
                                weights=pixels[..., 3])[0]
        actual = self.tone_scope.analyze(pixels, linear, tone)
        np.testing.assert_array_equal(actual, expected)
        baseline = replace(tone, muted_gain=0., vivid_gain=0.)
        self.assertFalse(np.array_equal(actual, self.tone_scope.analyze(pixels, linear, baseline)))

    @staticmethod
    def linear_pixels(code, alpha):
        code = np.asarray(code, dtype=np.float64)
        magnitude = np.abs(code)
        linear = np.sign(code) * np.where(
            magnitude < 0.081,
            magnitude / 4.5,
            ((magnitude + 0.099) / 1.099) ** (1.0 / 0.45),
        )
        return np.column_stack((linear, alpha))[None]

    def test_trace_normalizes_alpha_weighted_tint_at_equal_chroma(self):
        dark = np.array((0.43, 0.19, 0.25))
        light = dark + 0.4
        pixels = self.linear_pixels([dark, light, light], [1.0, 0.25, 0.0])
        trace = self.analysis.analyze(pixels, np.eye(3), "Linear Rec.709")
        dark_trace = self.analysis.analyze(pixels[:, :1], np.eye(3), "Linear Rec.709")
        visible = trace[..., 3] > 0.0
        self.assertTrue(visible.any())
        weighted = dark + 0.25 * light
        expected = np.broadcast_to(weighted / weighted.max(), trace[visible, :3].shape)
        np.testing.assert_allclose(trace[visible, :3], expected, rtol=1e-6)
        np.testing.assert_allclose(dark_trace[visible, :3],
                                   np.broadcast_to(dark / dark.max(), expected.shape), rtol=1e-6)
        np.testing.assert_array_equal(trace[..., 3], dark_trace[..., 3])
        self.assertEqual(trace.dtype, np.float32)
        self.assertTrue(trace.flags.c_contiguous)
        self.assertFalse(trace.flags.writeable)

    def test_lower_exposure_moves_chroma_without_dimming_the_trace(self):
        pixels = self.linear_pixels([(0.54, 0.19, 0.11)], [0.3])
        peaks = []
        peak_densities = []
        for exposure in (0.0, -8.0):
            matrix = 2.0 ** exposure * np.eye(3)
            trace = self.analysis.analyze(pixels, matrix, "Linear Rec.709")
            density = trace[..., 3]
            peak = np.unravel_index(density.argmax(), density.shape)
            cr, cb, weights, edges = self.analysis.chroma_samples(pixels, matrix, "Linear Rec.709")
            np.testing.assert_array_equal(weights, [0.3])
            self.assertEqual(peak, tuple(np.searchsorted(edges, [cr[0], cb[0]], side="right") - 1))
            self.assertEqual(trace[peak][:3].max(), 1.0)
            peaks.append(peak)
            peak_densities.append(density[peak])
        self.assertNotEqual(*peaks)
        self.assertEqual(*peak_densities)

    def test_trace_shows_occupied_black_and_keeps_empty_bins_transparent(self):
        pixels = self.linear_pixels([(0.0, 0.0, 0.0)], [0.5])
        trace = self.analysis.analyze(pixels, np.eye(3), "Linear Rec.709")
        occupied = trace[..., 3] > 0.0
        self.assertTrue(occupied.any())
        self.assertTrue(np.all(trace[occupied, :3] == 1.0))
        self.assertTrue(np.all(trace[~occupied] == 0.0))

    def test_gaussian_splat_preserves_mass_and_rgb_energy_at_edges(self):
        for size in (1, 2, 16):
            with self.subTest(size=size):
                mass = np.zeros((size, size))
                mass[0, -1] = 2
                energy = mass[..., None] * (0.2, 0.4, 0.8)
                smoothed_mass, smoothed_energy = self.analysis.splat_components(mass, energy)
                self.assertAlmostEqual(smoothed_mass.sum(), mass.sum())
                np.testing.assert_allclose(smoothed_energy.sum(axis=(0, 1)), energy.sum(axis=(0, 1)))
                self.assertEqual(tuple(np.unravel_index(np.argmax(smoothed_mass), mass.shape)),
                                 (0, size - 1))

    def test_gaussian_splat_has_one_bin_sigma_and_compact_support(self):
        mass = np.zeros((16, 16))
        mass[8, 8] = 1.0
        sym, _energy = self.analysis.splat_components(mass, np.zeros((16, 16, 3)))
        self.assertAlmostEqual(sym[9, 8] / sym[8, 8], np.exp(-0.5))
        self.assertAlmostEqual(sym[8, 9] / sym[8, 8], np.exp(-0.5))
        self.assertEqual(np.count_nonzero(sym), 49)

    def test_trace_keeps_measured_chroma_connections(self):
        red, blue = (0.86, 0.12, 0.12), (0.12, 0.12, 0.86)
        endpoints = self.linear_pixels([red, blue], [1.0, 1.0])
        gradient = self.linear_pixels(np.linspace(red, blue, 128), np.ones(128))
        disconnected = self.analysis.analyze(endpoints, np.eye(3), "Linear Rec.709")
        connected = self.analysis.analyze(gradient, np.eye(3), "Linear Rec.709")
        cb, cr = self.analysis.chroma((np.asarray(red) + blue) * 0.5)
        limit = self.analysis.CHROMA_LIMIT
        size = self.analysis.SIZE
        row, column = (int((component + limit) * size / (2.0 * limit))
                       for component in (cr, cb))
        self.assertEqual(disconnected[row, column, 3], 0.0)
        self.assertGreater(connected[row, column, 3], 0.0)
        self.assertEqual(connected[size // 2, size // 2, 3], 0.0)

    def test_trace_uses_signed_coordinates_and_clips_display_rgb(self):
        pixels = self.linear_pixels([(-0.2, 0.1, 0.7), (2.0, 0.0, 0.0)], [0.5, 1.0])
        mass, energy = self.analysis.color_histogram(pixels, np.eye(3), "Linear Rec.709")
        cr, cb, weights, edges = self.analysis.chroma_samples(
            pixels, np.eye(3), "Linear Rec.709")
        self.assertAlmostEqual(mass.sum(), 0.5)
        np.testing.assert_array_equal(mass, self.analysis.accumulate(cr, cb, weights, edges))
        np.testing.assert_allclose(energy.sum(axis=(0, 1)), (0.0, 0.05, 0.35), atol=1e-12)
        expected = ((0.7 - 0.07954) / 1.8556, (-0.2 - 0.07954) / 1.5748)
        np.testing.assert_allclose((cb[0], cr[0]), expected, atol=1e-12)

    def test_trace_is_empty_for_nonfinite_or_transparent_pixels(self):
        pixels = np.array([[[np.nan, 0.7, 0.1, 1.0], [0.1, 0.7, 0.1, 0.0]]])
        trace = self.analysis.analyze(pixels, np.eye(3), "Linear Rec.709", size=8)
        np.testing.assert_array_equal(trace, np.zeros((8, 8, 4), dtype=np.float32))

    def test_guide_targets_are_75_percent_encoded_bars(self):
        positions = {label: (cb, cr) for label, cb, cr in self.analysis.color_bar_targets()}
        self.assertEqual(tuple(positions), ("R", "Y", "G", "C", "B", "M"))
        np.testing.assert_allclose(positions["R"], (-0.15945 / 1.8556, 0.375))
        np.testing.assert_allclose(positions["B"], (0.375, -0.05415 / 1.5748))
        for primary, secondary in (("R", "C"), ("G", "M"), ("B", "Y")):
            np.testing.assert_allclose(positions[primary], -np.asarray(positions[secondary]))

    def test_white_drag_moves_scope_color_in_pointer_direction(self):
        settings = self.kernel.LinearSettings()
        rgba = np.array([[[0.18, 0.18, 0.18, 1.0]]])
        for space in ("Linear Rec.709", "Linear Rec.2020", "ACEScg"):
            drag = self.white_drag.WhiteDrag.from_capture(rgba, settings, space)
            self.assertIsNotNone(drag)
            for direction in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                with self.subTest(space=space, direction=direction):
                    point = drag.move(settings, 10 * direction[0], 10 * direction[1], 200)
                    candidate = replace(settings, source_xy=point)
                    matrix = self.kernel.prepare_linear(candidate, space).rgb_matrix
                    cr, cb, _, _ = self.analysis.chroma_samples(rgba, matrix, space)
                    self.assertGreater(float(np.array((cb[0], cr[0])) @ direction), 0.0)
                    np.testing.assert_allclose(point, self.kernel.project_source_white(point), atol=1e-12)

    def test_white_drag_freezes_cohort_and_excludes_isolated_outlier(self):
        space = "Linear Rec.709"
        settings = self.kernel.LinearSettings()
        rgba = np.full((16, 16, 4), 0.18)
        rgba[..., 3] = 1.0
        expected = self.white_drag.WhiteDrag.from_capture(rgba, settings, space)
        self.assertIsNotNone(expected)
        rgba[0, 0] = (1.0, 0.0, 0.0, 1.0)
        drag = self.white_drag.WhiteDrag.from_capture(rgba, settings, space)
        rgba[:] = 0.0
        self.assertIsNotNone(drag)
        np.testing.assert_allclose(drag.move(settings, 15, 10, 200),
                                   expected.move(settings, 15, 10, 200), atol=1e-9)

    def test_white_drag_has_no_response_in_empty_black_or_overridden_capture(self):
        space = "Linear Rec.709"
        settings = self.kernel.LinearSettings()
        rgba = np.array([[[0.18, 0.18, 0.18, 1.0]]])
        override = replace(settings, matrix=np.eye(3))
        self.assertIsNone(self.white_drag.WhiteDrag.from_capture(rgba, override, space))
        for pixel in ((0.18, 0.18, 0.18, 0.0), (0.0, 0.0, 0.0, 1.0),
                      (np.nan, 0.18, 0.18, 1.0), (100.0, 0.0, 0.0, 1.0)):
            with self.subTest(pixel=pixel):
                self.assertIsNone(self.white_drag.WhiteDrag.from_capture(np.array([[pixel]]), settings, space))

    def test_white_drag_finds_visible_pixel_missed_by_sparse_grid(self):
        rgba = np.zeros((32, 32, 4), dtype=np.float64)
        rgba[0, 0] = (1.0, 0.0, 0.0, 1.0)
        drag = self.white_drag.WhiteDrag.from_capture(
            rgba, self.kernel.LinearSettings(), "Linear Rec.709")
        self.assertIsNotNone(drag)
        np.testing.assert_array_equal(drag._rgb, ((1.0, 0.0, 0.0),))

    def test_white_drag_uses_nearest_representative_when_inliers_empty(self):
        rgba = np.array([[[1.0, 0.0, 0.0, 1.0], [0.0, 1.0, 0.0, 1.0],
                          [0.0, 0.0, 1.0, 1.0]]])
        settings = self.kernel.LinearSettings()
        with patch.object(self.white_drag, "_robust_squared_distances",
                          return_value=np.array((10.0, 7.0, 8.0))):
            drag = self.white_drag.WhiteDrag.from_capture(rgba, settings, "Linear Rec.709")
        self.assertIsNotNone(drag)
        np.testing.assert_array_equal(drag._rgb, ((0.0, 1.0, 0.0),))

    def test_white_drag_keeps_long_moves_in_cat16_domain(self):
        settings = self.kernel.LinearSettings()
        rgba = np.array([[[0.003, 0.003, 0.003, 1.0]]])
        drag = self.white_drag.WhiteDrag.from_capture(rgba, settings, "Linear Rec.709")
        self.assertIsNotNone(drag)
        points = tuple(drag.move(settings, 1000 * dx, 1000 * dy, 100)
                       for dx, dy in ((1, 1), (1, -1), (-1, 1), (-1, -1)))
        self.assertTrue(any(point != settings.source_xy for point in points))
        for point in points:
            np.testing.assert_allclose(point, self.kernel.project_source_white(point), atol=1e-12)
        self.assertEqual(drag.move(settings, np.nan, 1.0, 200), settings.source_xy)
        self.assertEqual(drag.move(settings, 1.0, 1.0, 0), settings.source_xy)
