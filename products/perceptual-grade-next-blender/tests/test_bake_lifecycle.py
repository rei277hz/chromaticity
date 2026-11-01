import unittest

import numpy as np

from color_tools.perceptual_grade_next_blender.bake import (
    BakeRoute, BakeRouteFacts, capture_grade, capture_stack, freeze_bake_input,
    inspect_bake_route,
)
from color_tools.perceptual_grade_next_blender.image_publication import ImagePublication
from color_tools.perceptual_grade_next_blender.output_gateway import (
    EvaluatorBinding, OutputGateway, OutputRequest,
)
from color_tools.perceptual_grade_next_blender.lifecycle import (
    ProjectWorkflow, RestartSupervisor, ScopeActor, ViewAuthority,
)


class _IdentityLut:
    size = 65
    evaluator_id = "lut"
    manifest_id = "manifest"

    @staticmethod
    def apply(values):
        return np.asarray(values, dtype=np.float64)


class _BackupStore:
    def __init__(self):
        self.saved = {}
        self.committed = set()
        self.discarded = set()
        self.next_token = 0

    def snapshot(self, image):
        return image.copy()

    def save(self, image, payload):
        self.next_token += 1
        token = self.next_token
        self.saved[token] = payload.copy()
        return token

    def restore(self, image, token):
        image[:] = self.saved[token]

    def mark_committed(self, token, candidate=None):
        self.committed.add(token)

    def discard(self, token):
        self.discarded.add(token)
        self.saved.pop(token, None)


class BakeTests(unittest.TestCase):
    @staticmethod
    def _ready_gateway():
        gateway = OutputGateway()
        gateway.dispatch(
            "open", generation=1, owners=("grade",),
            owner_evaluators=(("grade", "native_grade_graph"),),
        )
        gateway.dispatch("intent", revision=1)
        gateway.dispatch("prepare_begin", revision=1, attempt=1)
        gateway.dispatch(
            "owner_ready", revision=1, attempt=1, owner="grade",
            evaluator="native_grade_graph", evaluator_id="graph",
            manifest_id="manifest", final_ready=True,
        )
        return gateway

    def test_gateway_binds_capture_to_native_grade_and_checked_publication(self):
        gateway = self._ready_gateway()
        request = OutputRequest(
            operation=1, owner="grade", source_revision=3, source_id="input",
            evaluator="native_grade_graph", evaluator_id="graph",
            manifest_id="manifest",
        )
        gateway.request_bake(request)
        route = BakeRoute("image:1", "image", "shader", "native_grade_graph", 3, "input")
        frozen = gateway.freeze_bake_source(
            request, route, BakeRouteFacts(engine="BLENDER_EEVEE_NEXT"),
            np.asarray(((0.1, 0.2, 0.3, 0.4),), dtype=np.float32),
        )
        binding = EvaluatorBinding(
            lambda value: value * np.asarray((2, 2, 2, 1), dtype=np.float32),
            "graph", "manifest",
        )
        gateway.start_bake(1)
        result = gateway.capture_grade(
            native_evaluator=binding,
            request=request, frozen_input=frozen, result_id="image",
        )
        gateway.retire_bake_reader(1)
        gateway.stage_bake(1, result)
        gateway.publish_bake(1)
        gateway.publish_bake_image(1, result, self._publication())
        gateway.complete_bake(request, result.result_id)
        self.assertEqual(gateway.state.bake_phase, "finished")

    @staticmethod
    def _publication():
        image = np.asarray([1.0, 1.0, 1.0, 1.0], dtype=np.float32)
        store = _BackupStore()
        return ImagePublication(
            image, backup_store=store,
            write=lambda target, payload: target.__setitem__(slice(None), payload.ravel()),
            verify=lambda target, payload: np.array_equal(target, payload.ravel()),
            image_id="image",
        )

    def test_gateway_rejects_preview_as_stack_capture_source(self):
        gateway = OutputGateway()
        request = OutputRequest(
            operation=1, owner="stack", source_revision=3, source_id="input",
            evaluator="stack_33_lut", evaluator_id="preview", manifest_id="manifest",
            preview_id="preview", final_ready=False,
        )
        with self.assertRaises(TypeError):
            gateway.capture_stack(lut=_IdentityLut(), pixels=np.zeros((1, 4), dtype=np.float32),
                                  request=request, result_id="image")

    def test_gateway_rejects_route_for_another_final_evaluator(self):
        gateway = self._ready_gateway()
        request = OutputRequest(
            operation=1, owner="grade", source_revision=3, source_id="input",
            evaluator="native_grade_graph", evaluator_id="graph",
            manifest_id="manifest",
        )
        gateway.request_bake(request)
        route = BakeRoute("image:wrong", "image", "shader", "stack_65_lut", 3, "input")
        with self.assertRaisesRegex(RuntimeError, "route does not match"):
            gateway.freeze_bake_source(
                request, route, BakeRouteFacts(engine="CYCLES"),
                np.zeros((1, 4), dtype=np.float32),
            )

    def test_save_and_render_callbacks_are_each_invoked_once_after_gate(self):
        gateway = self._ready_gateway()
        save_calls = []
        self.assertEqual(
            gateway.invoke_save(1, lambda: save_calls.append("save") or {"FINISHED"}),
            {"FINISHED"},
        )
        self.assertEqual(save_calls, ["save"])
        self.assertEqual(gateway.state.phase, "active")

        render_calls = []
        self.assertEqual(
            gateway.invoke_render(1, lambda: render_calls.append("render") or {"FINISHED"}),
            {"FINISHED"},
        )
        self.assertEqual(render_calls, ["render"])
        self.assertFalse(gateway.state.publication_hold)

    def test_failed_native_render_receives_a_terminal_cancel_receipt(self):
        gateway = self._ready_gateway()
        calls = []
        with self.assertRaisesRegex(RuntimeError, "native failure"):
            gateway.invoke_render(
                1, lambda: calls.append(1) or (_ for _ in ()).throw(RuntimeError("native failure"))
            )
        self.assertEqual(calls, [1])
        self.assertEqual(gateway.state.phase, "active")
        self.assertFalse(gateway.state.publication_hold)

    def test_running_modal_render_keeps_hold_until_matching_terminal_receipt(self):
        gateway = self._ready_gateway()
        calls = []
        self.assertEqual(
            gateway.invoke_render(1, lambda: calls.append(1) or {"RUNNING_MODAL"}),
            {"RUNNING_MODAL"},
        )
        self.assertEqual(calls, [1])
        self.assertEqual(gateway.state.phase, "rendering")
        self.assertTrue(gateway.state.publication_hold)
        gateway.complete_render(1, committed=True)
        self.assertEqual(gateway.state.phase, "active")
        self.assertFalse(gateway.state.publication_hold)

    def test_incomplete_save_waits_for_bake_retirement_without_reinvoking(self):
        gateway = self._ready_gateway()
        gateway.dispatch(
            "bake_request", operation=4, owner="grade", source_revision=3,
            source_id="input", evaluator="native_grade_graph",
            evaluator_id="graph", manifest_id="manifest", final_ready=True,
        )
        gateway.start_bake(4)
        gateway.dispatch("save_request", operation=2)
        calls = []
        with self.assertRaisesRegex(RuntimeError, "live Bake readers"):
            gateway.invoke_save(2, lambda: calls.append("save") or {"FINISHED"})
        self.assertEqual(calls, [])
        gateway.dispatch("bake_retired", operation=4)
        gateway.invoke_save(2, lambda: calls.append("save") or {"FINISHED"})
        self.assertEqual(calls, ["save"])

    def test_cancelled_bake_blocks_successor_until_native_reader_retires(self):
        gateway = self._ready_gateway()
        first = OutputRequest(
            operation=1, owner="grade", source_revision=3, source_id="input-a",
            evaluator="native_grade_graph", evaluator_id="graph",
            manifest_id="manifest", route_id="route-a",
        )
        second = OutputRequest(
            operation=2, owner="grade", source_revision=4, source_id="input-b",
            evaluator="native_grade_graph", evaluator_id="graph",
            manifest_id="manifest", route_id="route-b",
        )
        gateway.request_bake(first)
        gateway.start_bake(first.operation)
        gateway.cancel_bake(first.operation)
        self.assertEqual(gateway.state.bake_phase, "cancelled")
        self.assertEqual(gateway.state.bake_physical, "retiring")

        with self.assertRaisesRegex(RuntimeError, "not final-ready"):
            gateway.request_bake(second)
        self.assertEqual(gateway.state.bake_operation, first.operation)
        self.assertEqual(gateway.state.bake_physical, "retiring")

        gateway.retire_bake_reader(first.operation)
        gateway.request_bake(second)
        self.assertEqual(gateway.state.bake_operation, second.operation)
        self.assertEqual(gateway.state.bake_physical, "none")

    def test_bake_stage_requires_the_exact_captured_result(self):
        gateway = self._ready_gateway()
        request = OutputRequest(
            operation=1, owner="grade", source_revision=3, source_id="input",
            evaluator="native_grade_graph", evaluator_id="graph",
            manifest_id="manifest",
        )
        gateway.request_bake(request)
        gateway.start_bake(1)
        with self.assertRaisesRegex(RuntimeError, "not captured"):
            gateway.stage_bake(1, object())
    def test_grade_capture_requires_native_output_and_preserves_alpha(self):
        pixels = np.asarray(((0.1, 0.2, 0.3, 0.4),), dtype=np.float32)
        result = capture_grade(
            native_evaluator=lambda value: value * np.asarray((2, 2, 2, 1), dtype=np.float32),
            pixels=pixels, source_revision=3, source_id="input", evaluator_id="graph",
            result_id="image",
        )
        np.testing.assert_allclose(result.rgba[0], (0.2, 0.4, 0.6, 0.4), rtol=0, atol=1e-7)
        with self.assertRaises(TypeError):
            capture_grade(native_evaluator=None, pixels=pixels, source_revision=1,
                          source_id="input", evaluator_id="graph", result_id="image")

    def test_stack_capture_is_bound_to_final_lut(self):
        pixels = np.asarray(((0.1, 0.2, 0.3, 0.4),), dtype=np.float32)
        result = capture_stack(lut=_IdentityLut(), pixels=pixels, source_revision=3,
                               source_id="input", evaluator_id="lut", result_id="image")
        np.testing.assert_array_equal(result.rgba, pixels)

    def test_uv_route_requires_cycles_and_native_output(self):
        route = BakeRoute("uv:1", "uv", "shader", "native_grade_graph", 3, "input")
        verdict = inspect_bake_route(route, BakeRouteFacts(
            engine="BLENDER_EEVEE_NEXT", uv_layer_present=True,
        ))
        self.assertFalse(verdict.ready)
        self.assertIn("Cycles", verdict.reason)
        verdict = inspect_bake_route(
            route, BakeRouteFacts(
                engine="CYCLES", shader_to_rgb=True, uv_layer_present=True,
            ),
        )
        self.assertFalse(verdict.ready)
        self.assertIn("Shader to RGB", verdict.reason)

    def test_frozen_samples_are_immutable_and_bound_to_route(self):
        route = BakeRoute("image:1", "image", "compositor", "native_grade_graph", 3, "input")
        pixels = np.asarray(((0.1, 0.2, 0.3, 0.4),), dtype=np.float32)
        frozen = freeze_bake_input(route, BakeRouteFacts(engine="BLENDER_EEVEE_NEXT"), pixels)
        pixels[0, 0] = 0.9
        self.assertAlmostEqual(float(frozen.rgba[0, 0]), 0.1, places=7)
        self.assertFalse(frozen.rgba.flags.writeable)
        output = capture_grade(
            native_evaluator=lambda value: value,
            frozen_input=frozen, evaluator_id="graph", manifest_id="manifest",
            result_id="image",
        )
        self.assertEqual(output.source.route_id, "image:1")
        with self.assertRaises(ValueError):
            capture_grade(native_evaluator=lambda value: value, frozen_input=frozen,
                          source_revision=4, evaluator_id="graph", result_id="stale")

    def test_image_publication_restores_failed_overwrite_and_retains_verified_backup(self):
        image = np.asarray([1.0, 2.0, 3.0], dtype=np.float32)
        store = _BackupStore()
        publication = ImagePublication(
            image, backup_store=store,
            write=lambda target, payload: target.__setitem__(slice(None), payload),
            verify=lambda target, payload: False,
            image_id="image",
        )
        publication.stage(np.asarray([4.0, 5.0, 6.0], dtype=np.float32))
        with self.assertRaisesRegex(RuntimeError, "did not verify"):
            publication.commit()
        np.testing.assert_array_equal(image, (1.0, 2.0, 3.0))
        self.assertTrue(store.discarded)

        publication = ImagePublication(
            image, backup_store=store,
            write=lambda target, payload: target.__setitem__(slice(None), payload),
            verify=lambda target, payload: np.array_equal(target, payload),
            image_id="image",
        )
        publication.stage(np.asarray([7.0, 8.0, 9.0], dtype=np.float32))
        token = publication.backup.token
        publication.commit()
        self.assertIn(token, store.committed)
        self.assertIn(token, store.saved)
        publication.finalize()
        self.assertIn(token, store.discarded)


class LifecycleTests(unittest.TestCase):
    def test_view_close_is_independent_of_scope_retirement(self):
        view = ViewAuthority()
        actor = ScopeActor()
        self.assertTrue(actor.open(1, "app"))
        view_epoch = view.open("viewport")
        display = view.issue("display-1", owner="viewport", view_epoch=view_epoch)
        self.assertTrue(view.can_apply(display))
        self.assertTrue(actor.demand(1, 1, "image"))
        ticket = actor.begin(1, 1, "image", 1)
        self.assertIsNotNone(ticket)
        view.close()
        self.assertFalse(view.visible)
        self.assertFalse(view.can_apply(display))
        self.assertTrue(actor.cancel(ticket))
        self.assertTrue(actor.retire(ticket))

    def test_scope_receipt_keeps_original_view_identity_after_view_move(self):
        actor = ScopeActor()
        actor.open(1, "app", view_epoch=1)
        self.assertTrue(actor.demand(1, 1, "image-a"))
        ticket = actor.begin(1, 1, "image-a", 1)
        self.assertIsNotNone(ticket)

        self.assertTrue(actor.move(2))
        self.assertTrue(actor.complete(ticket))
        self.assertEqual(actor.state.accepted_request, 0)
        self.assertEqual(actor.state.physical, "none")
        self.assertFalse(actor.complete(ticket))

    def test_scope_receipts_require_the_original_ticket(self):
        actor = ScopeActor()
        actor.open(1, "app", view_epoch=1)
        self.assertTrue(actor.demand(1, 1, "image"))
        ticket = actor.begin(1, 1, "image", 1)
        self.assertIsNotNone(ticket)
        forged = ticket.__class__(
            ticket.generation, ticket.owner, ticket.view_epoch + 1,
            ticket.playback_epoch, ticket.request, ticket.source_revision,
            ticket.source_id, ticket.submission,
        )
        self.assertFalse(actor.complete(forged))
        self.assertTrue(actor.complete(ticket))
        self.assertTrue(actor.has_current_input())

    def test_view_display_cannot_cross_owner_or_epoch(self):
        view = ViewAuthority()
        epoch = view.open("first")
        display = view.issue("result", owner="first", view_epoch=epoch)
        self.assertTrue(view.can_apply(display))
        next_epoch = view.move("second")
        self.assertFalse(view.can_apply(display))
        with self.assertRaises(RuntimeError):
            view.issue("late-result", owner="first", view_epoch=epoch)
        replacement = view.issue("next-result", owner="second", view_epoch=next_epoch)
        self.assertTrue(view.can_apply(replacement))
        self.assertTrue(view.apply(replacement))
        self.assertFalse(view.can_apply(replacement))
        self.assertFalse(view.apply(replacement))

    def test_restart_requires_cleanup_receipts(self):
        restart = RestartSupervisor()
        generation = restart.request(("worker",))
        self.assertEqual(generation, 1)
        self.assertFalse(restart.complete())
        self.assertFalse(restart.receipt("unrelated"))
        self.assertFalse(restart.complete(("worker", "unrelated")))
        self.assertTrue(restart.receipt("worker"))
        self.assertTrue(restart.complete())

    def test_project_workflow_wraps_checked_state(self):
        workflow = ProjectWorkflow()
        self.assertTrue(workflow.dispatch(
            "open", generation=1, owners=("grade",),
            owner_evaluators=(("grade", "native_grade_graph"),),
        ))
        self.assertTrue(workflow.dispatch("intent", revision=1))
        self.assertTrue(workflow.dispatch("prepare_begin", revision=1, attempt=1))
        self.assertTrue(workflow.dispatch(
            "owner_ready", revision=1, attempt=1, owner="grade",
            evaluator="native_grade_graph", evaluator_id="graph",
            manifest_id="manifest", final_ready=True,
        ))
        self.assertTrue(workflow.ready)


if __name__ == "__main__":
    unittest.main()
