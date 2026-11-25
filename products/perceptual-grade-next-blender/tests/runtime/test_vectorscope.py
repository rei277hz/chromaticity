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
        cls.policy = importlib.import_module(scope + "policy")
        cls.runtime = importlib.import_module(scope + "runtime")
        cls.analysis = importlib.import_module(scope + "analysis")
        cls.appearance_scope = importlib.import_module(scope + "appearance_scope")
        cls.tone_scope = importlib.import_module(scope + "tone_scope")
        cls.appearance_preview = importlib.import_module(scope + "appearance_preview")
        cls.white_drag = importlib.import_module(scope + "white_drag")
        cls.kernel = importlib.import_module(package_name + ".kernel")

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

    def request(self, state, capture, *, key=1, source="source", analysis=None,
                cached=False, ready=True):
        return self.policy.step(state, self.policy.Event(
            "request", key=key, capture_signature=capture, source_signature=source,
            analysis_signature=capture if analysis is None else analysis, cache_available=cached,
            ready=ready,
        ))

    def schedule(self, state):
        state, effects = self.policy.step(state, self.policy.Event("schedule"))
        return state, effects.start

    def start(self, state):
        state, ticket = self.schedule(state)
        self.assertIsNotNone(ticket)
        state, effects = self.policy.step(state, self.policy.Event("started", ticket=ticket))
        self.assertEqual(effects, self.policy.Effects())
        return state, ticket

    def capture(self, state, ticket, *, success=True):
        return self.policy.step(state, self.policy.Event(
            "capture_result", ticket=ticket, success=success, error="Capture failed",
        ))

    def test_playback_publishes_lagging_density_then_latest_demand(self):
        state, effects = self.request(self.policy.State(), "frame one")
        self.assertIsNone(effects.start)
        state, first = self.start(state)
        state, _ = self.request(state, "frame two")
        state, _ = self.request(state, "frame three")
        state, effects = self.capture(state, first)
        self.assertEqual(effects.publish.capture_signature, "frame three")
        self.assertEqual(effects.retain_samples, "frame one")
        self.assertEqual(self.policy.status(state, 1), ("updating", None))
        self.assertIsNone(effects.start)
        state, next_ticket = self.start(state)
        self.assertEqual(next_ticket.capture_signature, "frame three")
        state, effects = self.capture(state, next_ticket)
        self.assertIsNotNone(effects.publish)
        self.assertEqual(self.policy.status(state, 1), ("current", None))

    def test_newer_cached_plot_survives_superseded_capture(self):
        state, _ = self.request(self.policy.State(), "frame one")
        state, first = self.start(state)
        state, _ = self.request(state, "frame two", cached=True)
        state, _ = self.request(state, "frame three")
        state, effects = self.capture(state, first)
        self.assertIsNone(effects.publish)
        state, next_ticket = self.schedule(state)
        self.assertEqual(next_ticket.capture_signature, "frame three")
        self.assertEqual(self.policy.status(state, 1), ("updating", None))

    def test_latest_linear_revision_reuses_matching_capture(self):
        state, _ = self.request(self.policy.State(), "frame one")
        state, first = self.start(state)
        state, effects = self.request(state, "frame one", analysis="new matrix")
        self.assertIsNone(effects.start)
        state, effects = self.capture(state, first)
        self.assertEqual(effects.publish.analysis_signature, "new matrix")
        self.assertEqual(self.policy.status(state, 1), ("current", None))
        self.assertEqual(self.schedule(state), (state, None))

    def test_linear_edit_uses_retained_input_samples_without_starting_capture(self):
        state, _ = self.request(self.policy.State(), "same input")
        state, ticket = self.start(state)
        state, effects = self.capture(state, ticket)
        self.assertEqual(effects.retain_samples, "same input")
        state, effects = self.policy.step(state, self.policy.Event(
            "request", key=1, capture_signature="same input", source_signature="source",
            analysis_signature="linear correction", cache_available=True,
        ))
        self.assertIsNone(effects.start)
        self.assertEqual(effects.publish.capture_signature, "same input")
        self.assertEqual(effects.publish.analysis_signature, "linear correction")
        self.assertEqual(self.schedule(state), (state, None))

    def test_waiting_editor_does_not_hold_capture_slot(self):
        state, _ = self.request(self.policy.State(), "waiting", ready=False)
        waiting_ticket = state.desired[0]
        self.assertEqual(self.schedule(state), (state, None))
        state, _ = self.request(state, "ready", key=2)
        state, ticket = self.start(state)
        self.assertEqual(ticket.key, 2)
        state, _ = self.capture(state, ticket)
        self.assertEqual(self.schedule(state), (state, None))
        state, effects = self.request(state, "waiting", ready=True)
        self.assertEqual(effects, self.policy.Effects())
        state, ticket = self.start(state)
        self.assertEqual(ticket, waiting_ticket)

    def test_waiting_editor_keeps_matching_trace_updating(self):
        state, _ = self.request(self.policy.State(), "frame one")
        state, ticket = self.start(state)
        state, _ = self.request(state, "frame one", ready=False)
        state, effects = self.capture(state, ticket)
        self.assertEqual(effects.publish, ticket)
        self.assertEqual(effects.retain_samples, "frame one")
        self.assertEqual(self.policy.status(state, 1), ("updating", None))
        state, _ = self.request(state, "frame one", ready=True)
        self.assertEqual(self.policy.status(state, 1), ("current", None))
        self.assertEqual(self.schedule(state), (state, None))

    def test_deferred_capture_keeps_position_and_uses_latest_demand(self):
        state, _ = self.request(self.policy.State(), "first")
        state, _ = self.request(state, "second", key=2)
        state, reserved = self.schedule(state)
        self.assertEqual(reserved.key, 1)
        self.assertEqual(self.schedule(state), (state, None))
        state, _ = self.policy.step(state, self.policy.Event("deferred", ticket=reserved))
        self.assertIsNone(state.active)
        state, _ = self.request(state, "first updated")
        state, ticket = self.start(state)
        self.assertEqual(ticket.key, 1)
        self.assertEqual(ticket.capture_signature, "first updated")
        for event in ("started", "deferred", "capture_result"):
            with self.subTest(event=event):
                self.assertEqual(
                    self.policy.step(state, self.policy.Event(event, ticket=reserved)),
                    (state, self.policy.Effects()),
                )
        state, _ = self.capture(state, ticket)
        state, ticket = self.start(state)
        self.assertEqual(ticket.key, 2)

    def test_started_receipt_removes_only_its_reserved_demand(self):
        state, _ = self.request(self.policy.State(), "first")
        state, reserved = self.schedule(state)
        state, _ = self.request(state, "second")
        state, _ = self.policy.step(state, self.policy.Event("started", ticket=reserved))
        self.assertEqual(state.active, reserved)
        self.assertEqual(state.queued, state.desired)
        state, _ = self.capture(state, reserved)
        state, ticket = self.start(state)
        self.assertEqual(ticket.capture_signature, "second")

    def test_release_and_unavailable_cancel_only_the_affected_capture(self):
        for kind in ("release", "unavailable"):
            with self.subTest(kind=kind):
                state, _ = self.request(self.policy.State(), "active")
                state, ticket = self.start(state)
                state, _ = self.request(state, "waiting", key=2, ready=False)
                state, effects = self.policy.step(state, self.policy.Event(kind, key=2))
                self.assertIsNone(effects.cancel)
                self.assertEqual(state.waiting, frozenset())
                state, _ = self.request(state, "queued", key=3)
                state, effects = self.policy.step(state, self.policy.Event(kind, key=1))
                self.assertEqual(effects.cancel, ticket)
                self.assertEqual(effects.clear, (1,))
                self.assertEqual(self.schedule(state), (state, None))
                state, effects = self.capture(state, ticket)
                self.assertEqual(effects, self.policy.Effects())
                state, next_ticket = self.start(state)
                self.assertEqual(next_ticket.key, 3)

    def test_reset_retires_active_ticket_and_clears_waiting_demand(self):
        state, _ = self.request(self.policy.State(), "active")
        state, ticket = self.start(state)
        state, _ = self.request(state, "waiting", key=2, ready=False)
        state, effects = self.policy.step(state, self.policy.Event("reset"))
        self.assertEqual(effects.cancel, ticket)
        self.assertEqual(effects.clear, (1, 2))
        self.assertEqual(state, self.policy.State(generation=2, active=ticket))
        state, _ = self.request(state, "active")
        state, effects = self.capture(state, ticket)
        self.assertEqual(effects, self.policy.Effects())
        self.assertEqual(self.policy.status(state, 1), ("updating", None))
        state, next_ticket = self.start(state)
        self.assertGreater(next_ticket.source_generation, ticket.source_generation)

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
                             (None, "updating", None))
            self.assertEqual(self.input_result(self.observe(runtime, node, tone=tone)),
                             (histogram, "current", None))
            self.assertTrue(runtime.poll())
            job.advance.side_effect = RuntimeError("Capture failed")
            self.assertFalse(runtime.poll())
            self.assertEqual(self.observe_appearance(runtime, node, tone=tone),
                             (None, "error", "Capture failed"))

            node.pg_use_bake = True
            self.assertEqual(self.observe_appearance(runtime, node, tone=tone),
                             (None, "bake", None))
            self.assertEqual(self.input_result(self.observe(runtime, node, tone=tone)),
                             (histogram, "current", None))

    def test_dirty_appearance_completion_cannot_publish(self):
        pixels = np.ones((2, 2, 4), dtype=np.float32)
        tree = self.changed_id(100, "CompositorNodeTree")
        node = self.changed_id(1, "Grade", id_data=tree)
        job = Mock()
        job.advance.return_value = {"rgba": pixels}
        runtime = self.runtime.ScopeRuntime(
            lambda _route: (None, "snapshot.blend", []),
            lambda _node: self.kernel.LinearSettings(), lambda: "Linear Rec.709",
            create_job=Mock(return_value=job), grade_signature=Mock(return_value="Grade"),
        )
        route = {"owner_kind": "compositor", "capture_signature": "frame",
                 "source_signature": "source"}
        tone = self.kernel.ToneSettings()

        def readout(selected=node, *, frame=self.FRAME, stage="TONE"):
            return runtime.display_state(1, selected, frame=frame, stage=stage, dragging=False)

        with (patch.object(self.runtime.routes, "describe_vectorscope", return_value=route),
              patch.object(self.runtime, "capture_loaded_image", return_value=pixels)):
            self.observe(runtime, node, tone=tone)
            self.assertTrue(runtime.poll())
            self.assertTrue(runtime.poll())
            self.assertEqual(runtime.appearance_changed(node), (1,))
            self.assertFalse(runtime.poll())
            self.assertEqual(self.appearance_result(readout()), (None, "updating", None))
            self.assertEqual(readout().status, "current")
            self.assertIsNone(runtime.displays.get(self.runtime._AppearanceKey(1)))

            self.observe(runtime, node, tone=tone)
            self.assertTrue(runtime.poll())
            self.assertFalse(runtime.poll())
            self.assertEqual(readout().appearance_status, "current")
            self.assertIsNone(readout(stage="LINEAR"))
            self.assertIsNone(readout(self.changed_id(2, "Grade", id_data=tree)))
            self.assertEqual(readout(frame=(self.FRAME[0], 2, 0.)).appearance_status, "updating")
            self.assertEqual(runtime.frame_changed(self.FRAME[0]), (1,))
            state = readout()
            self.assertEqual(state.status, "updating")
            self.assertIsNotNone(state.tone_histogram)
            self.assertEqual(self.appearance_result(state), (None, "updating", None))

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
            state = runtime.display_state(1, node, frame=self.FRAME, stage="LINEAR", dragging=False)
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
            self.assertIsNone(runtime.state.active)

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
        )
        frame = "first frame"

        def describe(*_args, scope_capture="input", **_kwargs):
            return {"owner_kind": "compositor", "capture_signature": (frame, scope_capture),
                    "source_signature": frame, "scope_capture": scope_capture}

        def dragging():
            return self.observe_appearance(runtime, node, dragging=True)

        def input_observation():
            return self.observe(runtime, node, tone=self.kernel.ToneSettings())

        with (patch.object(self.runtime.routes, "describe_vectorscope", side_effect=describe),
              patch.object(self.runtime, "capture_loaded_image", return_value=pixels)):
            input_observation()
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
            self.assertIsNot(dragging()[0], trace)
            self.assertFalse(runtime.poll())
            self.assertEqual(preview.evaluate.call_count, 2)
            backend.create_job.assert_not_called()

            frame = "second frame"
            input_observation()
            self.assertEqual(dragging(), (None, "updating", None))
            runtime.poll()
            self.assertEqual(dragging()[1], "preview")
            self.assertEqual(preview.evaluate.call_count, 3)
            node.mute = True
            self.assertEqual(dragging()[1], "unavailable")
            node.mute = False
            node.pg_use_bake = True
            self.assertEqual(dragging(), (None, "bake", None))
            node.pg_use_bake = False

            self.assertEqual(self.observe_appearance(runtime, node, dragging=False),
                             (None, "updating", None))
            runtime.poll()
            runtime.poll()
            self.assertEqual(self.observe_appearance(runtime, node, dragging=False)[1], "current")
            self.assertEqual(backend.create_job.call_count, 1)
            runtime.reset()
            preview.close.assert_called_once()

    def test_appearance_preview_sample_subset_is_bounded_and_repeatable(self):
        source = np.arange(128 * 128 * 4, dtype=np.float32).reshape(128, 128, 4)
        first = self.appearance_preview._sample_subset(source)
        second = self.appearance_preview._sample_subset(source)
        self.assertEqual(first.shape, (1, 4096, 4))
        np.testing.assert_array_equal(first, second)
        self.assertEqual(first.dtype, np.float32)

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
        state, _ = self.request(self.policy.State(), "frame one")
        state, first = self.start(state)
        state, effects = self.policy.step(state, self.policy.Event("release", key=1))
        self.assertEqual(effects.clear, (1,))
        self.assertEqual(effects.cancel, first)
        state, _ = self.request(state, "frame one")
        state, effects = self.capture(state, first)
        self.assertIsNone(effects.publish)
        self.assertIsNone(effects.retain_samples)
        state, ticket = self.start(state)
        self.assertNotEqual(ticket.generation, first.generation)
        self.assertEqual(self.policy.status(state, 1), ("updating", None))

    def test_superseded_failure_is_inert_and_exact_failure_is_visible(self):
        state, _ = self.request(self.policy.State(), "frame one")
        state, first = self.start(state)
        state, _ = self.request(state, "frame two")
        state, _ = self.capture(state, first, success=False)
        self.assertEqual(self.policy.status(state, 1), ("updating", None))
        state, ticket = self.start(state)
        state, _ = self.capture(state, ticket, success=False)
        self.assertEqual(self.policy.status(state, 1), ("error", "Capture failed"))

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
        self.assertEqual(float(scope.lightness_position(0.)), 0.)
        self.assertAlmostEqual(float(scope.lightness_position(100.)), .8)
        self.assertAlmostEqual(float(scope.lightness_position(scope.LIGHTNESS_MAX)), 1.)
        self.assertAlmostEqual(float(scope.lightness_position(50.)), .423, places=3)
        self.assertTrue(np.all(np.diff(scope.lightness_position(np.linspace(
            0., scope.LIGHTNESS_MAX, 100))) > 0.))
        self.assertEqual(float(scope.saturation_position(0.)), 0.)
        self.assertAlmostEqual(float(scope.saturation_position(1.)), 1. / np.sqrt(2.))
        self.assertEqual(float(scope.saturation_position(np.inf)), 1.)
        np.testing.assert_array_equal(scope.saturation_position(np.array([0., np.inf], np.float32)),
                                      [0., 1.])

    def test_appearance_lightness_has_continuous_slope_and_curvature_at_reference(self):
        step = .01
        offsets = step * np.arange(-3, 4)
        left, near_left, before, center, after, near_right, right = (
            self.appearance_scope.lightness_position(100. + offsets)
        )
        slope_left = (3 * center - 4 * before + near_left) / (2 * step)
        slope_right = (-3 * center + 4 * after - near_right) / (2 * step)
        curvature_left = (2 * center - 5 * before + 4 * near_left - left) / step**2
        curvature_right = (2 * center - 5 * after + 4 * near_right - right) / step**2
        self.assertAlmostEqual(slope_left, slope_right, places=8)
        self.assertLess(curvature_left, -1e-4)
        self.assertAlmostEqual(curvature_left, curvature_right, places=8)

    def test_appearance_scope_reports_alpha_weighted_overflow(self):
        scope = self.appearance_scope
        pixels = np.array([[[scope.LIGHTNESS_MAX + 1., 0., 0., .25], [50., 0., 0., .75],
                            [scope.LIGHTNESS_MAX + 4., 0., 0., 0.], [np.nan, 0., 0., 1.]]])
        result = scope.analyze(pixels)
        self.assertAlmostEqual(result.overflow_fraction, .25)
        self.assertEqual(result.rgba.shape, (144, 288, 4))
        self.assertFalse(result.rgba.flags.writeable)
        np.testing.assert_array_equal(result.rgba, scope.analyze(pixels[:, 1:2]).rgba)
        self.assertFalse(scope.analyze(pixels[:, :1]).rgba.any())
        self.assertEqual(scope.analyze(pixels[:, 2:]).overflow_fraction, 0.)

    def test_appearance_scope_places_black_4000_nits_and_infinite_saturation(self):
        scope = self.appearance_scope
        for pixel, expected in (((0., 0., 0., 1.), (0, 0)),
                                ((scope.LIGHTNESS_MAX, 0., 0., 1.), (143, 0)),
                                ((100., 0., 0., 1.), (115, 0)),
                                ((0., 20., 0., 1.), (44, 287))):
            with self.subTest(pixel=pixel):
                density = scope.analyze(np.array([[pixel]])).rgba[..., 3]
                self.assertEqual(np.unravel_index(np.argmax(density), density.shape), expected)

    def test_appearance_scope_keeps_density_when_opposite_hues_cancel(self):
        scope = self.appearance_scope
        opposing = scope.analyze(np.array([[[50., 20., 0., 1.], [50., -20., 0., 1.]]]))
        hue = scope.analyze(np.array([[[50., 20., 0., 1.]]]))
        occupied = opposing.rgba[..., 3] > 0.
        self.assertTrue(occupied.any())
        np.testing.assert_allclose(opposing.rgba[occupied, :3], .6, atol=1e-6)
        np.testing.assert_array_equal(opposing.rgba[..., 3], hue.rgba[..., 3])
        weighted = scope.analyze(np.array([[[50., 20., 0., 1.], [50., -20., 0., .25]]]))
        np.testing.assert_allclose(weighted.rgba[occupied, :3] - .6,
                                   .6 * (hue.rgba[occupied, :3] - .6), atol=1e-6)

    def test_appearance_scope_fades_hue_toward_neutral_and_palette_is_luminance_constant(self):
        scope = self.appearance_scope
        chromatic = scope.analyze(np.array([[[50., 8., 0., 1.]]]))
        near_gray = scope.analyze(np.array([[[50., .2, 0., 1.]]]))
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
        histogram = self.tone_scope.analyze(pixels, linear, self.kernel.ToneSettings())
        self.assertEqual(histogram.shape, (128,))
        white_bin = int(histogram.size / self.tone_scope.PLOT_MAX)
        np.testing.assert_array_equal(np.flatnonzero(histogram), [0, white_bin])
        np.testing.assert_array_equal(histogram[[0, white_bin]], [1., 1.25])
        self.assertFalse(histogram.flags.writeable)

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
