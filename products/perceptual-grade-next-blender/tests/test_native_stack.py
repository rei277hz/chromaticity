import unittest
import json

import bpy
import numpy as np

from color_tools.perceptual_grade_next_blender.stack import (
    FINAL_EVALUATOR,
    StackDatablock,
    StackPreparation,
    prepare_stack,
    reopen_stack,
    refine_stack,
)
from color_tools.perceptual_grade_next_blender.stack_graph import build_native_stack
from color_tools.perceptual_grade_next_core import GradeSettings, StackEntry, StackSettings
from color_tools.perceptual_grade_next_core.model.lut import PreviewLattice, make_recipe


class NativeStackTests(unittest.TestCase):
    def test_native_stack_installs_preview_then_withholds_final_bake_authority(self):
        native = build_native_stack(tree_type="ShaderNodeTree", final=False, block_size=32768)
        try:
            tree = native.tree
            preview_name = tree["perceptual_grade_next_stack_preview_resource"]
            preview_lookups = [node for node in tree.nodes
                               if node.get("perceptual_grade_next_stack_preview_lookup")]
            self.assertEqual(len(preview_lookups), 4)
            self.assertTrue(all(node.image.name == preview_name for node in preview_lookups))
            self.assertFalse(native.final_ready)
            self.assertEqual(tree["perceptual_grade_next_stack_quality_tier"], "33^3-preview")
            self.assertEqual(tree["perceptual_grade_next_stack_bake_evaluator"], "")
            with self.assertRaisesRegex(RuntimeError, r"65\^3"):
                _ = native.bake_evaluator
        finally:
            native.dispose(unlink=True)

    def test_entry_edit_rebuilds_and_replaces_stack_with_new_authored_recipe(self):
        from color_tools.perceptual_grade_next_blender import controls
        from color_tools.perceptual_grade_next_blender import updates

        controls.register()
        settings = StackSettings((StackEntry(GradeSettings(), "FORWARD"),))
        native = build_native_stack(
            settings, tree_type="ShaderNodeTree", final=False, block_size=32768,
        )
        host = bpy.data.node_groups.new("Next Stack Edit Test", "ShaderNodeTree")
        host.interface.new_socket(name="Color", in_out="INPUT", socket_type="NodeSocketColor")
        host.interface.new_socket(name="Color", in_out="OUTPUT", socket_type="NodeSocketColor")
        source = host.nodes.new("NodeGroupInput")
        sink = host.nodes.new("NodeGroupOutput")
        node = host.nodes.new("ShaderNodeGroup")
        node.node_tree = native.tree
        host.links.new(source.outputs["Color"], node.inputs["Color"])
        host.links.new(node.outputs["Color"], sink.inputs["Color"])
        node["perceptual_grade_next_backend"] = "native_stack_lut"
        node["perceptual_grade_next_stack_evaluator"] = native.tree.get(
            "perceptual_grade_next_stack_bake_evaluator", ""
        )
        node["perceptual_grade_next_stack_quality_tier"] = native.tree.get(
            "perceptual_grade_next_stack_quality_tier", ""
        )
        node["perceptual_grade_next_edit_revision"] = 0
        node["perceptual_grade_next_applied_revision"] = 0
        node["perceptual_grade_next_preparation_state"] = "READY"
        controls.attach_stack_controls(node, settings)
        updates.register_native_owner(node, native, "stack")
        self.assertEqual(node.get("perceptual_grade_next_stack_evaluator"), "")
        previous = node.node_tree
        try:
            node.perceptual_grade_next_stack_controls.entries[0].settings.exposure = 0.25
            self.assertEqual(updates.process_pending_updates(), ())
            self.assertIsNot(node.node_tree, previous)
            self.assertEqual(node.get("perceptual_grade_next_preparation_state"), "READY")
            self.assertEqual(node.get("perceptual_grade_next_applied_revision"), 1)
            self.assertEqual(node.get("perceptual_grade_next_stack_evaluator"), FINAL_EVALUATOR)
            self.assertTrue(any(link.from_node == source and link.to_node == node
                                for link in host.links))
            self.assertTrue(any(link.from_node == node and link.to_node == sink
                                for link in host.links))
            saved = json.loads(node.get("perceptual_grade_next_stack_settings"))
            self.assertEqual(saved["entries"][0]["settings"]["linear"]["exposure"], 0.25)
            self.assertEqual(node.node_tree.get("perceptual_grade_next_stack_final_size"), 65)
        finally:
            updates.cancel_pending_updates()
            installed = node.node_tree
            bpy.data.node_groups.remove(host, do_unlink=True)
            if installed is not None and updates._pointer(installed) is not None and installed.users == 0:
                updates._remove_unused(installed)
            try:
                if previous is not None and previous.users == 0:
                    updates._remove_unused(previous)
            except ReferenceError:
                pass
            controls.unregister()

    def test_native_stack_graph_samples_only_the_accepted_final_image(self):
        native = build_native_stack(tree_type="ShaderNodeTree", block_size=32768)
        try:
            tree = native.tree
            final_name = tree["perceptual_grade_next_stack_final_resource"]
            preview_name = tree["perceptual_grade_next_stack_preview_resource"]
            lookup_nodes = [node for node in tree.nodes
                            if node.get("perceptual_grade_next_stack_final_lookup")]
            self.assertEqual(len(lookup_nodes), 4)
            self.assertTrue(all(node.image.name == final_name for node in lookup_nodes))
            self.assertNotEqual(final_name, preview_name)
            self.assertEqual(tree["perceptual_grade_next_stack_quality_tier"], "65^3")
            self.assertEqual(tree["perceptual_grade_next_stack_bake_evaluator"], FINAL_EVALUATOR)
            self.assertTrue(native.datablock.validate_persistent())
            self.assertEqual(native.bake_evaluator.size, 65)
            output = next(node for node in tree.nodes if node.bl_idname == "NodeGroupOutput")
            self.assertTrue(any(link.to_node == output and link.to_socket.name == "Color"
                                for link in tree.links))
        finally:
            native.dispose(unlink=True)

    def test_compositor_stack_graph_preserves_input_alpha(self):
        native = build_native_stack(tree_type="CompositorNodeTree", block_size=32768)
        try:
            tree = native.tree
            final_name = tree["perceptual_grade_next_stack_final_resource"]
            lookup_nodes = [node for node in tree.nodes
                            if node.get("perceptual_grade_next_stack_final_lookup")]
            self.assertEqual(len(lookup_nodes), 4)
            self.assertTrue(all(node.image.name == final_name for node in lookup_nodes))
            self.assertTrue(any(node.bl_idname == "ShaderNodeMath" for node in tree.nodes))
            alpha_links = [link for link in tree.links if link.to_socket.name == "Alpha"]
            self.assertTrue(any(link.from_socket.name == "Alpha" for link in alpha_links))
            output = next(node for node in tree.nodes if node.bl_idname == "NodeGroupOutput")
            self.assertTrue(any(link.to_node == output and link.to_socket.name == "Color"
                                for link in tree.links))
        finally:
            native.dispose(unlink=True)

    def test_reopen_revalidates_packed_payloads_and_rebuilds_invalid_derived_data(self):
        native = build_native_stack(tree_type="ShaderNodeTree", block_size=32768)
        try:
            tree = native.tree
            restored = reopen_stack(tree, rebuild=False)
            self.assertEqual(restored.preparation.recipe.digest, native.preparation.recipe.digest)
            self.assertTrue(restored.final_ready)
            preview = bpy.data.images[tree["perceptual_grade_next_stack_preview_resource"]]
            preview.pixels[0] = float(preview.pixels[0]) + 1.0
            preview.update()
            rebuilt = reopen_stack(tree, rebuild=True, block_size=32768)
            self.assertTrue(rebuilt.final_ready)
            self.assertTrue(rebuilt.validate_persistent())
        finally:
            native.dispose(unlink=True)
    def test_reference_preview_refinement_reuses_exact_vertices(self):
        preparation = prepare_stack(StackSettings(), block_size=32768)
        self.assertTrue(preparation.preview_ready)
        self.assertFalse(preparation.final_ready)
        self.assertEqual(preparation.preview.values.shape, (33, 33, 33, 3))
        final = refine_stack(preparation, block_size=32768)
        self.assertTrue(final.final_ready)
        self.assertEqual(final.final.values.shape, (65, 65, 65, 3))
        np.testing.assert_array_equal(
            final.final.values[::2, ::2, ::2], preparation.preview.values
        )
        self.assertEqual(final.evaluator_kind, FINAL_EVALUATOR)

    def test_persistent_datablock_separates_preview_from_final_bake_readiness(self):
        preparation = prepare_stack(StackSettings(), block_size=32768)
        tree = bpy.data.node_groups.new("Next Stack Metadata Test", "ShaderNodeTree")
        existing_images = {image.name for image in bpy.data.images}
        try:
            datablock = StackDatablock(tree, preparation)
            self.assertTrue(datablock.preview_ready)
            self.assertFalse(datablock.final_ready)
            self.assertEqual(tree["perceptual_grade_next_stack_preview_size"], 33)
            self.assertEqual(tree["perceptual_grade_next_stack_final_size"], 0)
            self.assertEqual(tree["perceptual_grade_next_stack_evaluator"], "")
            self.assertTrue(datablock.validate_persistent())
            preview_image = bpy.data.images[tree["perceptual_grade_next_stack_preview_resource"]]
            self.assertEqual(tuple(preview_image.size), (33 * 33, 33))
            self.assertTrue(preview_image.packed_file)
            with self.assertRaisesRegex(RuntimeError, "65\\^3"):
                datablock.bake_evaluator

            final = refine_stack(preparation, block_size=32768)
            metadata = datablock.update(final)
            self.assertTrue(datablock.final_ready)
            self.assertEqual(tree["perceptual_grade_next_stack_final_size"], 65)
            self.assertEqual(tree["perceptual_grade_next_stack_evaluator"], FINAL_EVALUATOR)
            self.assertFalse(tree["perceptual_grade_next_stack_preview_is_bake_source"])
            self.assertEqual(metadata["evaluator"], FINAL_EVALUATOR)
            self.assertTrue(datablock.validate_persistent())
            final_image = bpy.data.images[tree["perceptual_grade_next_stack_final_resource"]]
            self.assertEqual(tuple(final_image.size), (65 * 65, 65))
            self.assertTrue(final_image.packed_file)
            result = datablock.bake_evaluator.apply(np.asarray(((0.0, 0.0, 0.0), (0.18, 0.18, 0.18))))
            self.assertEqual(result.shape, (2, 3))
            self.assertTrue(np.isfinite(result).all())
            preview_image.pixels[0] = float(preview_image.pixels[0]) + 1.0
            preview_image.update()
            with self.assertRaisesRegex(RuntimeError, "does not match its recipe"):
                datablock.validate_persistent()
        finally:
            bpy.data.node_groups.remove(tree, do_unlink=True)
            for image in tuple(bpy.data.images):
                if (image.name not in existing_images
                        and image.get("perceptual_grade_next_stack_role")):
                    bpy.data.images.remove(image, do_unlink=True)

    def test_metadata_write_failure_rolls_back_properties_and_new_images(self):
        class FailingTree(dict):
            def __setitem__(self, key, value):
                if key == "perceptual_grade_next_stack_preview_ready":
                    raise RuntimeError("injected metadata write failure")
                super().__setitem__(key, value)

        preparation = prepare_stack(StackSettings(), block_size=32768)
        existing_images = {image.name for image in bpy.data.images}
        tree = FailingTree()
        with self.assertRaisesRegex(RuntimeError, "injected metadata"):
            StackDatablock(tree, preparation)
        self.assertEqual(tree, {})
        created_images = [
            image for image in bpy.data.images
            if image.name not in existing_images
            and image.get("perceptual_grade_next_stack_role")
        ]
        self.assertEqual(created_images, [])

    def test_shared_packed_resources_survive_one_owner_update(self):
        preparation = prepare_stack(StackSettings(), block_size=32768)
        existing_images = {image.name for image in bpy.data.images}
        tree_a = bpy.data.node_groups.new("Next Stack Shared A", "ShaderNodeTree")
        tree_b = bpy.data.node_groups.new("Next Stack Shared B", "ShaderNodeTree")
        try:
            owner_a = StackDatablock(tree_a, preparation)
            owner_b = StackDatablock(tree_b, preparation)
            shared_name = tree_a["perceptual_grade_next_stack_preview_resource"]
            self.assertEqual(shared_name, tree_b["perceptual_grade_next_stack_preview_resource"])
            original_recipe = preparation.recipe
            changed_recipe = make_recipe(
                working_space=original_recipe.working_space,
                directions=original_recipe.directions,
                input_matrix=original_recipe.input_matrix,
                output_matrix=original_recipe.output_matrix,
                model_key=original_recipe.model_key + "-replacement",
            )
            replacement = StackPreparation(
                preparation.settings,
                changed_recipe,
                PreviewLattice(preparation.preview.values, changed_recipe),
            )
            owner_a.update(replacement)
            self.assertNotEqual(tree_a["perceptual_grade_next_stack_preview_resource"], shared_name)
            self.assertTrue(bpy.data.images.get(shared_name).packed_file)
            self.assertTrue(owner_b.validate_persistent())
        finally:
            bpy.data.node_groups.remove(tree_a, do_unlink=True)
            bpy.data.node_groups.remove(tree_b, do_unlink=True)
            for image in tuple(bpy.data.images):
                if (image.name not in existing_images
                        and image.get("perceptual_grade_next_stack_role")):
                    bpy.data.images.remove(image, do_unlink=True)


if __name__ == "__main__":
    unittest.main()
