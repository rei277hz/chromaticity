import unittest
from unittest.mock import patch

import bpy
import numpy as np

from color_tools.perceptual_grade_next_blender import controls
from color_tools.perceptual_grade_next_blender.native_grade import build_native_grade
from color_tools.perceptual_grade_next_blender.native_capture import (
    bind_grade_evaluator, bind_stack_evaluator,
)
from color_tools.perceptual_grade_next_blender.output_gateway import OutputGateway, OutputRequest
from color_tools.perceptual_grade_next_blender.output_operators import (
    OutputActionController, RenderOptions,
)
from color_tools.perceptual_grade_next_blender.project_readiness import (
    ProjectReadiness,
    accept_grade_manifest,
    inspect_project_owners,
)
from color_tools.perceptual_grade_next_blender.stack_graph import build_native_stack


class ProjectReadinessTests(unittest.TestCase):
    def setUp(self):
        controls.register()

    def tearDown(self):
        controls.unregister()

    def test_empty_project_has_no_missing_owner_debt(self):
        runtime = ProjectReadiness()
        snapshot = runtime.refresh(())
        self.assertEqual(snapshot.owners, ())
        self.assertTrue(snapshot.ready)
        self.assertTrue(runtime.workflow.ready)

    def test_material_grade_participates_in_readiness_and_recovery(self):
        from color_tools.perceptual_grade_next_blender import recovery
        from color_tools.perceptual_grade_next_blender.scope_runtime import (
            _project_node_trees,
        )
        from color_tools.perceptual_grade_next_blender.updates import _find_owner

        native = build_native_grade(tree_type="ShaderNodeTree")
        material = bpy.data.materials.new("Next Material Readiness Host")
        material.use_nodes = True
        node = material.node_tree.nodes.new("ShaderNodeGroup")
        node.node_tree = native.tree
        node["perceptual_grade_next_backend"] = "native_grade_graph"
        node["perceptual_grade_next_schema"] = 1
        node["perceptual_grade_next_settings"] = native.tree[
            "perceptual_grade_next_settings"
        ]
        node["perceptual_grade_next_edit_revision"] = 0
        node["perceptual_grade_next_applied_revision"] = 0
        node["perceptual_grade_next_preparation_state"] = "READY"
        node["perceptual_grade_next_preparation_error"] = ""
        controls.attach_controls(node, native.settings)
        accept_grade_manifest(node, native)
        runtime = ProjectReadiness()
        runtime.begin_document()
        trees = tuple(_project_node_trees(bpy))
        identity = f"{material.node_tree.as_pointer()}:{node.as_pointer()}"
        try:
            self.assertTrue(recovery._is_complete_project_tree_collection(trees, bpy))
            self.assertFalse(recovery._is_complete_project_tree_collection(
                (material.node_tree,), bpy,
            ))
            found = _find_owner(node.perceptual_grade_next_controls)
            self.assertIsNotNone(found)
            self.assertEqual(found[0].as_pointer(), material.node_tree.as_pointer())
            self.assertEqual(found[1].as_pointer(), node.as_pointer())

            initial = runtime.refresh(trees)
            owner = next(item for item in initial.owners if item.identity == identity)
            self.assertTrue(owner.ready, owner.reason)

            image = native.images[0]
            original = float(image.pixels[0])
            image.pixels[0] = original + 1.0
            image.update()
            corrupted = runtime.refresh(trees)
            owner = next(item for item in corrupted.owners if item.identity == identity)
            self.assertFalse(owner.ready)
            self.assertIn("accepted manifest", owner.reason)
            controller = OutputActionController(
                OutputGateway(runtime.workflow),
                refresh=lambda: runtime.refresh(trees).ready,
            )
            with self.assertRaisesRegex(RuntimeError, "preparation failed"):
                controller.save(lambda _options: {"FINISHED"})

            queued = recovery.requeue_prepared_nodes(
                trees, mark_dirty=lambda candidate: (
                    candidate.as_pointer() == node.as_pointer()
                ),
            )
            self.assertIn(node.as_pointer(), tuple(item.as_pointer() for item in queued))
            image.pixels[0] = original
            image.update()
        finally:
            bpy.data.materials.remove(material, do_unlink=True)
            if native.tree.users == 0:
                native.controller.dispose(unlink=True)

    def test_missing_backend_marker_keeps_fifth_owner_in_save_and_render_gate(self):
        host = bpy.data.node_groups.new("Next Five Owner Host", "ShaderNodeTree")
        evaluators = []
        nodes = []
        for index in range(5):
            evaluator = bpy.data.node_groups.new(
                f"Next Five Owner Evaluator {index}", "ShaderNodeTree",
            )
            evaluator["perceptual_grade_next_backend"] = "native_grade_graph"
            evaluators.append(evaluator)
            node = host.nodes.new("ShaderNodeGroup")
            node.node_tree = evaluator
            node["perceptual_grade_next_backend"] = "native_grade_graph"
            node["perceptual_grade_next_schema"] = 1
            node["perceptual_grade_next_edit_revision"] = 0
            node["perceptual_grade_next_applied_revision"] = 0
            node["perceptual_grade_next_preparation_state"] = "READY"
            nodes.append(node)

        node_groups = (host, *evaluators)
        runtime = ProjectReadiness()
        runtime.begin_document()
        try:
            with patch(
                "color_tools.perceptual_grade_next_blender.project_readiness._validate_grade",
                side_effect=lambda node: (node.node_tree, f"manifest-{node.name}"),
            ):
                initial = runtime.refresh(node_groups)
                self.assertEqual(len(initial.owners), 5)
                self.assertTrue(initial.ready)
                self.assertTrue(runtime.workflow.ready)

                del nodes[-1]["perceptual_grade_next_backend"]
                corrupted = runtime.refresh(node_groups)
                self.assertEqual(len(corrupted.owners), 5)
                self.assertFalse(corrupted.owners[-1].ready)
                self.assertIn("backend metadata", corrupted.owners[-1].reason)
                self.assertFalse(runtime.workflow.ready)
                self.assertIn(corrupted.owners[-1].identity,
                              runtime.workflow.state.repair_owners)

                calls = []
                controller = OutputActionController(
                    OutputGateway(runtime.workflow),
                    refresh=lambda: runtime.refresh(node_groups).ready,
                )
                with self.assertRaisesRegex(RuntimeError, "preparation failed"):
                    controller.save(lambda options: calls.append("save") or {"FINISHED"})
                with self.assertRaisesRegex(RuntimeError, "preparation failed"):
                    controller.render(
                        lambda options: calls.append("render") or {"FINISHED"},
                        RenderOptions(),
                    )
                self.assertEqual(calls, [])
        finally:
            bpy.data.node_groups.remove(host, do_unlink=True)
            for evaluator in evaluators:
                if evaluator.users == 0:
                    bpy.data.node_groups.remove(evaluator, do_unlink=True)

    @staticmethod
    def _host_with_owner(native, backend):
        host = bpy.data.node_groups.new("Next Readiness Host", "ShaderNodeTree")
        node = host.nodes.new("ShaderNodeGroup")
        node.node_tree = native.tree
        node["perceptual_grade_next_backend"] = backend
        node["perceptual_grade_next_schema"] = 1
        node["perceptual_grade_next_edit_revision"] = 0
        node["perceptual_grade_next_applied_revision"] = 0
        node["perceptual_grade_next_preparation_state"] = "READY"
        node["perceptual_grade_next_preparation_error"] = ""
        if backend == "native_grade_graph":
            node["perceptual_grade_next_settings"] = native.tree[
                "perceptual_grade_next_settings"
            ]
            controls.attach_controls(node, native.settings)
            accept_grade_manifest(node, native)
        else:
            node["perceptual_grade_next_stack_settings"] = native.tree[
                "perceptual_grade_next_stack_settings"
            ]
            node["perceptual_grade_next_stack_quality_tier"] = "65^3"
            node["perceptual_grade_next_stack_evaluator"] = "stack_65_lut"
            controls.attach_stack_controls(node, native.preparation.settings)
        return host, node

    def test_grade_snapshot_requires_matching_packed_native_fields(self):
        native = build_native_grade(tree_type="ShaderNodeTree")
        host, node = self._host_with_owner(native, "native_grade_graph")
        try:
            snapshot = inspect_project_owners((host,), generation=1)
            self.assertEqual(len(snapshot.owners), 1)
            self.assertTrue(snapshot.owners[0].ready, snapshot.owners[0].reason)
            self.assertEqual(snapshot.owners[0].evaluator, "native_grade_graph")
            self.assertTrue(snapshot.owners[0].evaluator_id)

            math_node = next(item for item in native.tree.nodes
                             if item.bl_idname == "ShaderNodeMath")
            socket = next(item for item in math_node.inputs
                          if hasattr(item, "default_value")
                          and not any(link.to_socket == item for link in native.tree.links))
            previous_default = float(socket.default_value)
            socket.default_value = previous_default + 0.125
            changed_default = inspect_project_owners((host,), generation=1)
            self.assertFalse(changed_default.owners[0].ready)
            self.assertIn("accepted manifest", changed_default.owners[0].reason)
            runtime = ProjectReadiness()
            runtime.begin_document()
            calls = []
            controller = OutputActionController(
                OutputGateway(runtime.workflow),
                refresh=lambda: runtime.refresh((host,)).ready,
            )
            with self.assertRaisesRegex(RuntimeError, "preparation failed"):
                controller.save(lambda options: calls.append(options) or {"FINISHED"})
            self.assertEqual(calls, [])
            socket.default_value = previous_default

            resource = next(item.image for item in native.tree.nodes
                            if getattr(item, "image", None) is not None)
            original = float(resource.pixels[0])
            resource.pixels[0] = original + 1.0
            resource.update()
            corrupted_pixels = inspect_project_owners((host,), generation=1)
            self.assertFalse(corrupted_pixels.owners[0].ready)
            self.assertIn("accepted manifest", corrupted_pixels.owners[0].reason)
            resource.pixels[0] = original
            resource.update()

            node["perceptual_grade_next_preparation_ledger"] = "{}"
            json_debt = inspect_project_owners((host,), generation=1)
            self.assertFalse(json_debt.owners[0].ready)
            del node["perceptual_grade_next_preparation_ledger"]

            ledger = bpy.data.node_groups.new("Next Grade Pointer Debt", "ShaderNodeTree")
            node.perceptual_grade_next_controls.preparation_ledger = ledger
            pointer_debt = inspect_project_owners((host,), generation=1)
            self.assertFalse(pointer_debt.owners[0].ready)
            node.perceptual_grade_next_controls.preparation_ledger = None
            bpy.data.node_groups.remove(ledger, do_unlink=True)

            resource.use_half_precision = True
            rejected = inspect_project_owners((host,), generation=1)
            self.assertFalse(rejected.owners[0].ready)
            self.assertIn("float32", rejected.owners[0].reason)
        finally:
            bpy.data.node_groups.remove(host, do_unlink=True)
            if native.tree.users == 0:
                native.controller.dispose(unlink=True)

    def test_grade_capture_binding_requires_current_native_owner_receipt(self):
        native = build_native_grade(tree_type="ShaderNodeTree")
        host, node = self._host_with_owner(native, "native_grade_graph")
        try:
            owner = inspect_project_owners((host,), generation=1).owners[0]
            self.assertTrue(owner.ready, owner.reason)
            request = OutputRequest(
                operation=1, owner=owner.identity, source_revision=4,
                source_id="frozen-image", evaluator=owner.evaluator,
                evaluator_id=owner.evaluator_id, manifest_id=owner.manifest_id,
            )
            binding = bind_grade_evaluator(node, request, lambda rgba: rgba)
            self.assertEqual(binding.evaluator_id, owner.evaluator_id)
            self.assertEqual(binding.manifest_id, owner.manifest_id)
            pixels = np.asarray(((0.1, 0.2, 0.3, 0.4),), dtype=np.float32)
            np.testing.assert_array_equal(
                binding.evaluate_native(pixels), pixels,
            )
            stale = OutputRequest(
                operation=2, owner=owner.identity, source_revision=4,
                source_id="frozen-image", evaluator=owner.evaluator,
                evaluator_id=owner.evaluator_id, manifest_id="stale-manifest",
            )
            with self.assertRaisesRegex(RuntimeError, "does not match"):
                bind_grade_evaluator(node, stale, lambda rgba: rgba)
            with self.assertRaises(TypeError):
                bind_grade_evaluator(node, request, None)
        finally:
            bpy.data.node_groups.remove(host, do_unlink=True)
            if native.tree.users == 0:
                native.controller.dispose(unlink=True)

    def test_stack_snapshot_requires_final_lut_and_edit_receipt(self):
        native = build_native_stack(tree_type="ShaderNodeTree", block_size=32768)
        host, node = self._host_with_owner(native, "native_stack_lut")
        runtime = ProjectReadiness()
        runtime.begin_document()
        try:
            snapshot = runtime.refresh((host,))
            self.assertTrue(snapshot.ready, snapshot.owners[0].reason)
            self.assertTrue(runtime.workflow.ready, runtime.workflow.state)
            self.assertEqual(snapshot.owners[0].evaluator, "stack_65_lut")

            node["perceptual_grade_next_preparation_ledger"] = "{}"
            self.assertFalse(inspect_project_owners((host,), generation=1).ready)
            del node["perceptual_grade_next_preparation_ledger"]
            ledger = bpy.data.node_groups.new("Next Stack Pointer Debt", "ShaderNodeTree")
            node.perceptual_grade_next_stack_controls.preparation_ledger = ledger
            self.assertFalse(inspect_project_owners((host,), generation=1).ready)
            node.perceptual_grade_next_stack_controls.preparation_ledger = None
            bpy.data.node_groups.remove(ledger, do_unlink=True)

            node["perceptual_grade_next_edit_revision"] = 1
            node["perceptual_grade_next_preparation_state"] = "PENDING"
            pending = runtime.refresh((host,))
            self.assertFalse(pending.ready)
            self.assertFalse(runtime.workflow.ready)

            node["perceptual_grade_next_applied_revision"] = 1
            node["perceptual_grade_next_preparation_state"] = "READY"
            accepted = runtime.refresh((host,))
            self.assertTrue(accepted.ready, accepted.owners[0].reason)
            self.assertTrue(runtime.workflow.ready)

            tree = native.tree
            image = bpy.data.images[tree["perceptual_grade_next_stack_final_resource"]]
            image.pixels[0] = float(image.pixels[0]) + 1.0
            image.update()
            corrupted = runtime.refresh((host,))
            self.assertFalse(corrupted.ready)
            self.assertFalse(runtime.workflow.ready)
            empty = runtime.refresh(())
            self.assertEqual(empty.owners, ())
            self.assertTrue(empty.ready)
            self.assertTrue(runtime.workflow.ready)
        finally:
            bpy.data.node_groups.remove(host, do_unlink=True)
            native.dispose(unlink=True)

    def test_preview_to_final_is_progressive_and_preserves_waiting_bake(self):
        preview = build_native_stack(tree_type="ShaderNodeTree", final=False, block_size=32768)
        host, node = self._host_with_owner(preview, "native_stack_lut")
        node["perceptual_grade_next_stack_quality_tier"] = "33^3-preview"
        node["perceptual_grade_next_stack_evaluator"] = ""
        node["perceptual_grade_next_edit_revision"] = 1
        node["perceptual_grade_next_applied_revision"] = 0
        node["perceptual_grade_next_preparation_state"] = "PENDING"
        runtime = ProjectReadiness()
        runtime.begin_document()
        final = None
        try:
            snapshot = runtime.refresh((host,))
            owner = snapshot.owners[0]
            self.assertTrue(owner.preview_ready, owner.reason)
            self.assertFalse(owner.final_ready)
            preparation_attempt = runtime.workflow.state.preparation_attempt
            gateway = OutputGateway(runtime.workflow)
            gateway.request_bake(OutputRequest(
                operation=1, owner=owner.identity, source_revision=4,
                source_id="frozen", evaluator="stack_65_lut",
                evaluator_id=owner.preview_id, manifest_id=owner.manifest_id,
                preview_id=owner.preview_id, final_ready=False,
            ))
            self.assertEqual(runtime.workflow.state.bake_phase, "waiting_for_final")

            from color_tools.perceptual_grade_next_blender.stack import refine_stack
            final_preparation = refine_stack(preview.preparation, block_size=32768)
            final = build_native_stack(
                preparation=final_preparation, tree_type="ShaderNodeTree", block_size=32768,
            )
            node.node_tree = final.tree
            node["perceptual_grade_next_stack_settings"] = final.tree[
                "perceptual_grade_next_stack_settings"
            ]
            node["perceptual_grade_next_stack_quality_tier"] = "65^3"
            node["perceptual_grade_next_stack_evaluator"] = "stack_65_lut"
            node["perceptual_grade_next_applied_revision"] = 1
            node["perceptual_grade_next_preparation_state"] = "READY"

            complete = runtime.refresh((host,))
            accepted = complete.owners[0]
            self.assertTrue(accepted.final_ready, accepted.reason)
            self.assertTrue(runtime.workflow.ready)
            self.assertEqual(runtime.workflow.state.preparation_attempt, preparation_attempt)
            self.assertEqual(runtime.workflow.state.bake_phase, "waiting_for_final")
            self.assertEqual(accepted.manifest_id, owner.manifest_id)
            self.assertTrue(accepted.evaluator_id)
            gateway.final_ready(OutputRequest(
                operation=1, owner=owner.identity, source_revision=4,
                source_id="frozen", evaluator="stack_65_lut",
                evaluator_id=accepted.evaluator_id,
                manifest_id=accepted.manifest_id,
            ))
            self.assertEqual(runtime.workflow.state.bake_phase, "evaluating")
        finally:
            bpy.data.node_groups.remove(host, do_unlink=True)
            preview.dispose(unlink=True)
            if final is not None:
                final.dispose(unlink=True)

    def test_stack_capture_binding_requires_current_native_owner_receipt(self):
        native = build_native_stack(tree_type="ShaderNodeTree", block_size=32768)
        host, node = self._host_with_owner(native, "native_stack_lut")
        try:
            owner = inspect_project_owners((host,), generation=1).owners[0]
            self.assertTrue(owner.ready, owner.reason)
            request = OutputRequest(
                operation=1, owner=owner.identity, source_revision=4,
                source_id="frozen-image", evaluator=owner.evaluator,
                evaluator_id=owner.evaluator_id, manifest_id=owner.manifest_id,
            )
            binding = bind_stack_evaluator(node, request)
            self.assertEqual(binding.evaluator_id, owner.evaluator_id)
            self.assertEqual(binding.manifest_id, owner.manifest_id)
            self.assertEqual(binding.size, 65)
            self.assertEqual(binding.apply(((0.1, 0.2, 0.3),)).shape, (1, 3))

            stale = OutputRequest(
                operation=2, owner=owner.identity, source_revision=4,
                source_id="frozen-image", evaluator=owner.evaluator,
                evaluator_id=owner.evaluator_id, manifest_id="stale-manifest",
            )
            with self.assertRaisesRegex(RuntimeError, "does not match"):
                bind_stack_evaluator(node, stale)
            wrong_owner = OutputRequest(
                operation=3, owner="other-owner", source_revision=4,
                source_id="frozen-image", evaluator=owner.evaluator,
                evaluator_id=owner.evaluator_id, manifest_id=owner.manifest_id,
            )
            with self.assertRaisesRegex(RuntimeError, "different Stack owner"):
                bind_stack_evaluator(node, wrong_owner)
        finally:
            bpy.data.node_groups.remove(host, do_unlink=True)
            native.dispose(unlink=True)

    def test_waiting_save_and_render_retry_a_restored_owner(self):
        native = build_native_grade(tree_type="ShaderNodeTree")
        host, node = self._host_with_owner(native, "native_grade_graph")
        runtime = ProjectReadiness()
        runtime.begin_document()
        refresh_count = 0

        def refresh():
            nonlocal refresh_count
            refresh_count += 1
            if refresh_count in (2, 5):
                node["perceptual_grade_next_preparation_state"] = "PENDING"
            elif refresh_count in (3, 6):
                node["perceptual_grade_next_preparation_state"] = "READY"
            return runtime.refresh((host,)).ready

        calls = []
        controller = OutputActionController(
            OutputGateway(runtime.workflow), refresh=refresh,
        )
        try:
            self.assertEqual(
                controller.save(lambda options: calls.append("save") or {"FINISHED"}),
                {"RUNNING_MODAL"},
            )
            self.assertEqual(calls, [])
            self.assertTrue(runtime.workflow.state.repair_owners)
            self.assertEqual(controller.continue_save(), {"FINISHED"})
            self.assertEqual(calls, ["save"])
            self.assertFalse(runtime.workflow.state.publication_hold)
            self.assertFalse(runtime.workflow.state.repair_owners)

            self.assertEqual(
                controller.render(
                    lambda options: calls.append("render") or {"RUNNING_MODAL"},
                    RenderOptions(),
                ),
                {"RUNNING_MODAL"},
            )
            self.assertEqual(calls, ["save"])
            self.assertTrue(runtime.workflow.state.repair_owners)
            self.assertEqual(controller.continue_render(), {"RUNNING_MODAL"})
            self.assertEqual(calls, ["save", "render"])
            self.assertTrue(runtime.workflow.state.publication_hold)
            controller.complete_render(committed=True)
            self.assertFalse(runtime.workflow.state.publication_hold)
        finally:
            bpy.data.node_groups.remove(host, do_unlink=True)
            if native.tree.users == 0:
                native.controller.dispose(unlink=True)

    def test_save_signature_drift_cancels_the_wait_without_native_invocation(self):
        native = build_native_grade(tree_type="ShaderNodeTree")
        host, node = self._host_with_owner(native, "native_grade_graph")
        runtime = ProjectReadiness()
        runtime.begin_document()
        refresh_count = 0

        def refresh():
            nonlocal refresh_count
            refresh_count += 1
            if refresh_count == 2:
                node["perceptual_grade_next_edit_revision"] = 1
            return runtime.refresh((host,)).ready

        calls = []
        controller = OutputActionController(
            OutputGateway(runtime.workflow), refresh=refresh,
        )
        try:
            result = controller.save(
                lambda options: calls.append(options) or {"FINISHED"},
            )
            self.assertEqual(result, {"CANCELLED"})
            self.assertEqual(calls, [])
            self.assertIsNone(controller.pending_save_operation)
            self.assertEqual(runtime.workflow.state.phase, "active")
            self.assertFalse(runtime.workflow.state.publication_hold)
        finally:
            bpy.data.node_groups.remove(host, do_unlink=True)
            if native.tree.users == 0:
                native.controller.dispose(unlink=True)

    def test_render_owner_membership_drift_cancels_the_wait(self):
        native = build_native_grade(tree_type="ShaderNodeTree")
        host, _node = self._host_with_owner(native, "native_grade_graph")
        runtime = ProjectReadiness()
        runtime.begin_document()
        node_groups = [host]
        refresh_count = 0

        def refresh():
            nonlocal refresh_count
            refresh_count += 1
            if refresh_count == 2:
                node_groups.clear()
            return runtime.refresh(tuple(node_groups)).ready

        calls = []
        controller = OutputActionController(
            OutputGateway(runtime.workflow), refresh=refresh,
        )
        try:
            result = controller.render(
                lambda options: calls.append(options) or {"FINISHED"},
                RenderOptions(),
            )
            self.assertEqual(result, {"CANCELLED"})
            self.assertEqual(calls, [])
            self.assertIsNone(controller.pending_render_operation)
            self.assertEqual(runtime.workflow.state.phase, "active")
            self.assertFalse(runtime.workflow.state.publication_hold)
        finally:
            bpy.data.node_groups.remove(host, do_unlink=True)
            if native.tree.users == 0:
                native.controller.dispose(unlink=True)


if __name__ == "__main__":
    unittest.main()
