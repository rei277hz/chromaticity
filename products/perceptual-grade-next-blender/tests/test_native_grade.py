import unittest
from dataclasses import replace
import json
from unittest.mock import patch
import numpy as np

import bpy

from color_tools.perceptual_grade_next_blender.native_grade import (
    NativeGrade, _native_settings, apply_native_grade, build_native_grade,
)


class NativeGradeTests(unittest.TestCase):
    def test_failed_settings_compensation_invalidates_controller(self):
        from color_tools.perceptual_grade_next_core import GradeSettings

        class Tree(dict):
            def __setitem__(self, key, value):
                if value == "accepted-settings":
                    raise RuntimeError("injected settings rollback failure")
                super().__setitem__(key, value)

        class Controller:
            valid = True

            def apply(self, _prepared, *, expected_revision):
                self.asserted_revision = expected_revision
                raise RuntimeError("injected native write failure")

        tree = Tree(perceptual_grade_next_settings="accepted-settings")
        controller = Controller()
        native = NativeGrade(tree, controller, "ShaderNodeTree", GradeSettings())
        with self.assertRaisesRegex(RuntimeError, "settings rollback failed"):
            apply_native_grade(
                native, GradeSettings(), object(), expected_revision=0,
            )
        self.assertFalse(controller.valid)

    def test_invalid_controller_failure_retains_grade_backing(self):
        from color_tools.perceptual_grade_next_blender import controls, updates
        from color_tools.perceptual_grade_next_blender.native_grade import prepare_native_grade

        controls.register()
        native = build_native_grade(tree_type="ShaderNodeTree")
        host = bpy.data.node_groups.new("Next Grade Rollback Failure", "ShaderNodeTree")
        node = host.nodes.new("ShaderNodeGroup")
        node.node_tree = native.tree
        node["perceptual_grade_next_backend"] = "native_grade_graph"
        node["perceptual_grade_next_settings"] = native.tree[
            "perceptual_grade_next_settings"
        ]
        node["perceptual_grade_next_edit_revision"] = 1
        node["perceptual_grade_next_applied_revision"] = 0
        node["perceptual_grade_next_preparation_state"] = "PENDING"
        controls.attach_controls(node, native.settings)
        updates.register_native_owner(node, native, "grade")
        settings = replace(
            native.settings,
            tone=replace(native.settings.tone, fit=native.settings.tone.fit + 0.25),
        )
        _settings, prepared = prepare_native_grade(
            settings, previous=native.controller.prepared,
        )

        def failed_apply(controller, *_args, **_kwargs):
            controller.valid = False
            raise RuntimeError("injected field rollback failure")

        from color_tools.perceptual_grade_next_blender.preparation_ledger import (
            discard_grade_backing,
        )
        ledger_transaction = ""
        try:
            with patch.object(type(native.controller), "apply", new=failed_apply):
                with self.assertRaisesRegex(RuntimeError, "field rollback failure"):
                    updates._install_admitted(
                        host, node, "grade", 1, settings, (settings, prepared),
                    )
            ledger = json.loads(node[updates.PREPARATION_LEDGER_KEY])
            ledger_transaction = ledger["backup_transaction"]
            self.assertTrue(ledger_transaction)
            self.assertTrue(ledger["backup_slots"])
            self.assertIsNotNone(node.perceptual_grade_next_controls.preparation_ledger)
            self.assertEqual(node.get("perceptual_grade_next_preparation_state"), "FAILED")
            self.assertFalse(native.controller.valid)
        finally:
            updates._LIVE.pop(updates._key(host, node), None)
            if ledger_transaction:
                discard_grade_backing(node, ledger_transaction)
            native.controller.dispose(unlink=True)
            if host.users == 0:
                bpy.data.node_groups.remove(host, do_unlink=True)
            controls.unregister()

    def test_next_settings_are_mapped_into_the_native_graph_schema(self):
        from color_tools.perceptual_grade_next_core import (
            ColorSettings, GradeSettings, LinearSettings, ToneSettings, WebSettings,
        )

        settings = GradeSettings(
            linear=LinearSettings(exposure=0.75, source_white_xy=(0.31, 0.33)),
            tone=ToneSettings(fit=2.0, peak_nits=4000.0),
            color=ColorSettings(
                lightness_fit=-2.0,
                chroma_fit=6.0,
                web=WebSettings(hue_degrees=((1.0,) * 6,) * 4),
            ),
            working_space="Linear Rec.2020",
        )
        native = _native_settings(settings)
        self.assertEqual(native.linear.exposure, 0.75)
        self.assertEqual(native.linear.source_xy, (0.31, 0.33))
        self.assertEqual(native.tone.fit, 2.0)
        self.assertEqual(native.tone.reference_nits, 203.0)
        self.assertEqual(native.color.lightness_fit, -2.0)
        self.assertEqual(native.color.chroma_fit, 6.0)
        self.assertTrue(native.color.web.active)
        self.assertEqual(native.space, "Linear Rec.2020")

    def test_operator_registers_for_shader_and_compositor_add_menus(self):
        from color_tools.perceptual_grade_next_blender import operators

        operator = operators.register()
        try:
            self.assertEqual(operator.bl_idname, "node.pg_next_add_native_grade")
            self.assertEqual(operator.bl_label, "Add Perceptual Grade Next")
        finally:
            operators.unregister()

    def test_builds_one_persistent_forward_graph_without_preview_transform(self):
        grade = build_native_grade(tree_type="ShaderNodeTree")
        try:
            tree = grade.tree
            self.assertEqual(tree.bl_idname, "ShaderNodeTree")
            self.assertEqual(tree.get("perceptual_grade_next_backend"), "native_grade_graph")
            self.assertEqual(tree.get("perceptual_grade_next_schema"), 1)
            self.assertEqual(tree.get("perceptual_grade_next_quality_tier"), "native_graph")
            self.assertIs(tree.get("perceptual_grade_next_has_preview_transform"), False)
            self.assertIs(tree.get("perceptual_grade_nodes_persistent"), True)
            self.assertEqual(tree.get("perceptual_grade_nodes_schema"), 5)
            self.assertGreater(grade.stats.expanded_nodes, 0)
            self.assertGreater(grade.stats.texture_bytes, 0)
            self.assertTrue(grade.images)
            self.assertTrue(all(image.packed_file for image in grade.images))
            self.assertFalse(any(len(image.size) != 2 for image in grade.images))
        finally:
            grade.controller.dispose(unlink=True)

    def test_builds_the_compositor_backend_with_alpha_preservation(self):
        grade = build_native_grade(tree_type="CompositorNodeTree")
        try:
            tree = grade.tree
            sockets = {item.name for item in tree.interface.items_tree
                       if getattr(item, "item_type", None) == "SOCKET"}
            self.assertEqual(tree.bl_idname, "CompositorNodeTree")
            self.assertIn("Color", sockets)
            self.assertIn("Alpha", sockets)
            self.assertEqual(grade.quality_tier, "native_graph")
        finally:
            grade.controller.dispose(unlink=True)

    def test_control_edit_applies_a_complete_persistent_update_and_keeps_revision(self):
        from color_tools.perceptual_grade_next_blender import controls
        from color_tools.perceptual_grade_next_blender import updates

        controls.register()
        native = build_native_grade(tree_type="ShaderNodeTree")
        host = bpy.data.node_groups.new("Next Grade Edit Test", "ShaderNodeTree")
        host.interface.new_socket(name="Color", in_out="INPUT", socket_type="NodeSocketColor")
        host.interface.new_socket(name="Color", in_out="OUTPUT", socket_type="NodeSocketColor")
        source = host.nodes.new("NodeGroupInput")
        sink = host.nodes.new("NodeGroupOutput")
        node = host.nodes.new("ShaderNodeGroup")
        node.node_tree = native.tree
        host.links.new(source.outputs["Color"], node.inputs["Color"])
        host.links.new(node.outputs["Color"], sink.inputs["Color"])
        node.inputs["Color"].default_value = (0.2, 0.3, 0.4, 0.5)
        node["perceptual_grade_next_backend"] = "native_grade_graph"
        node["perceptual_grade_next_schema"] = 1
        node["perceptual_grade_next_settings"] = native.tree[
            "perceptual_grade_next_settings"
        ]
        node["perceptual_grade_next_edit_revision"] = 0
        node["perceptual_grade_next_applied_revision"] = 0
        node["perceptual_grade_next_preparation_state"] = "READY"
        controls.attach_controls(node, native.settings)
        from color_tools.perceptual_grade_next_blender.project_readiness import (
            accept_grade_manifest,
        )
        accept_grade_manifest(node, native)
        updates.register_native_owner(node, native, "grade")
        previous = node.node_tree
        try:
            node.perceptual_grade_next_controls.exposure = 0.5
            node.perceptual_grade_next_controls.global_gain = 0.25
            self.assertEqual(node.get("perceptual_grade_next_preparation_state"), "PENDING")
            self.assertEqual(node.get("perceptual_grade_next_edit_revision"), 2)
            self.assertEqual(updates.process_pending_updates(), ())
            self.assertEqual(node.get("perceptual_grade_next_preparation_state"), "READY")
            self.assertEqual(node.get("perceptual_grade_next_edit_revision"), 2)
            self.assertEqual(node.get("perceptual_grade_next_applied_revision"), 2)
            self.assertNotIn(updates.PREPARATION_LEDGER_KEY, node)
            self.assertIs(node.node_tree, previous)
            self.assertEqual(native.controller.revision, 1)
            self.assertTrue(any(link.from_node == source and link.to_node == node
                                for link in host.links))
            self.assertTrue(any(link.from_node == node and link.to_node == sink
                                for link in host.links))
            np.testing.assert_allclose(
                tuple(node.inputs["Color"].default_value), (0.2, 0.3, 0.4, 0.5),
                rtol=0, atol=1e-7,
            )
            settings = json.loads(node.get("perceptual_grade_next_settings"))
            self.assertEqual(settings["linear"]["exposure"], 0.5)
            self.assertEqual(settings["color"]["global_gain"], 0.25)
            accepted = node.node_tree
            with patch.object(updates, "_prepare", side_effect=RuntimeError("injected preparation failure")):
                node.perceptual_grade_next_controls.tone_fit = 0.75
                failures = updates.process_pending_updates()
            self.assertEqual(len(failures), 1)
            self.assertIs(node.node_tree, accepted)
            self.assertEqual(node.get("perceptual_grade_next_preparation_state"), "FAILED")
            self.assertEqual(node.get("perceptual_grade_next_preparation_error"),
                             "injected preparation failure")
            ledger = json.loads(node[updates.PREPARATION_LEDGER_KEY])
            self.assertEqual(ledger["stage"], "failed")
            self.assertEqual(ledger["revision"], 3)
        finally:
            updates.cancel_pending_updates()
            installed = node.node_tree
            bpy.data.node_groups.remove(host, do_unlink=True)
            if installed is not None and installed.users == 0:
                updates._remove_unused(installed)
            try:
                if previous is not None and previous.users == 0:
                    updates._remove_unused(previous)
            except ReferenceError:
                pass
            controls.unregister()

    def test_grade_preparation_backing_restores_field_pixels_after_interruption(self):
        """A staged live update can restore every accepted field after a crash."""
        from color_tools.perceptual_grade_next_blender import controls
        from color_tools.perceptual_grade_next_blender.native_grade import prepare_native_grade
        from color_tools.perceptual_grade_next_blender.preparation_ledger import (
            OWNER_ID_KEY, restore_grade_backing, stage_grade_backing,
        )

        controls.register()
        native = build_native_grade(tree_type="ShaderNodeTree")
        host = bpy.data.node_groups.new("Next Grade Recovery Test", "ShaderNodeTree")
        node = host.nodes.new("ShaderNodeGroup")
        node.node_tree = native.tree
        node["perceptual_grade_next_backend"] = "native_grade_graph"
        controls.attach_controls(node, native.settings)
        accepted = {}
        for name, (_table, image) in native.controller._graph.image_slots.items():
            pixels = np.empty(len(image.pixels), dtype=np.float32)
            image.pixels.foreach_get(pixels)
            accepted[name] = pixels.copy()
        try:
            changed_settings = replace(
                native.settings, tone=replace(native.settings.tone, fit=0.5),
            )
            _settings, candidate = prepare_native_grade(
                changed_settings, previous=native.controller.prepared,
            )
            transaction = "recovery-test-transaction"
            backup_transaction, backup_slots = stage_grade_backing(
                host, node, native, candidate, transaction,
            )
            self.assertEqual(backup_transaction, transaction)
            self.assertTrue(backup_slots)
            self.assertLessEqual(set(backup_slots), set(accepted))
            ledger = node.perceptual_grade_next_controls.preparation_ledger
            self.assertIsNotNone(ledger)

            # Simulate a partial native publication before Blender is terminated.
            for name in backup_slots:
                _table, image = native.controller._graph.image_slots[name]
                image.pixels.foreach_set(np.zeros(len(image.pixels), dtype=np.float32))
                image.update()

            # The ID reference may reach serialization before its companion
            # custom owner property; recovery must adopt the retained identity.
            del node[OWNER_ID_KEY]
            restored = restore_grade_backing(
                host, node, {"backup_transaction": transaction,
                             "backup_slots": backup_slots},
            )
            self.assertTrue(restored)
            self.assertIsNone(node.perceptual_grade_next_controls.preparation_ledger)
            for name, (_table, image) in native.controller._graph.image_slots.items():
                pixels = np.empty(len(image.pixels), dtype=np.float32)
                image.pixels.foreach_get(pixels)
                np.testing.assert_array_equal(pixels, accepted[name])
        finally:
            native.controller.dispose(unlink=True)
            if host.users == 0:
                bpy.data.node_groups.remove(host, do_unlink=True)
            controls.unregister()


if __name__ == "__main__":
    unittest.main()
