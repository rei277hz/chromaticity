"""Fresh template instances preserve private bindings and file portability."""

from pathlib import Path
from dataclasses import replace
from importlib import resources
import json
import tempfile
import unittest
from unittest.mock import patch

import bpy
import numpy as np

from color_tools.kernel import node_templates
from color_tools.kernel.stage2_bindings import (
    PARAMETER_ACTIVE_BANK, PARAMETER_BANK_BINDINGS, PARAMETER_GENERATION,
    PARAMETER_READER, PARAMETER_READER_BANK, PARAMETER_SELECTOR,
)
from color_tools.kernel.stage2_parameters import prepare_parameters

from .template_support import SPACES, TREE_TYPES, complete_prepared, stack_prepared


def image_pixels(image):
    values = np.empty(len(image.pixels), dtype=np.float32)
    image.pixels.foreach_get(values)
    return values.reshape(image.size[1], image.size[0], 4)


class NodeTemplateTests(unittest.TestCase):
    def setUp(self):
        bpy.ops.wm.read_factory_settings(use_empty=True)

    def tearDown(self):
        bpy.ops.wm.read_factory_settings(use_empty=True)

    def assert_local(self, instance):
        self.assertIsNone(instance.tree.library)
        self.assertTrue(all(image.library is None for image in instance.images))
        self.assertTrue(all(image.packed_file is not None and not image.is_dirty
                            for image in instance.images))

    def assert_parameter_bindings(self, instance, prepared, active, generation):
        tree = instance.tree
        banks = tuple(tree[key] for key in PARAMETER_BANK_BINDINGS)
        self.assertEqual(tree[PARAMETER_ACTIVE_BANK], active)
        self.assertEqual(tree[PARAMETER_GENERATION], generation)
        self.assertNotEqual(banks[0], banks[1])
        for bank in banks:
            np.testing.assert_array_equal(image_pixels(bank), prepare_parameters(prepared).pixels)
        readers = tuple(node for node in tree.nodes if node.get(PARAMETER_READER))
        self.assertEqual({node[PARAMETER_READER_BANK] for node in readers}, {0, 1})
        for reader in readers:
            self.assertEqual(reader.image, banks[reader[PARAMETER_READER_BANK]])
        selector, = (node for node in tree.nodes if node.get(PARAMETER_SELECTOR))
        value = (selector.outputs["Value"].default_value if tree.bl_idname == "ShaderNodeTree"
                 else selector.inputs[0].default_value)
        self.assertEqual(value, float(active))
        self.assert_local(instance)
        return banks

    def test_manifest_covers_every_product_variant(self):
        expected = {
            f"grade:{tree_type}:{space}" for tree_type in TREE_TYPES for space in SPACES
        } | {
            f"stack:{tree_type}:{space}:{size}"
            for tree_type in TREE_TYPES for space in SPACES for size in (33, 65)
        } | {f"wrapper:{tree_type}" for tree_type in TREE_TYPES}
        manifest, records = node_templates.load_manifest()
        self.assertEqual(set(manifest["variants"]), expected)
        self.assertEqual(set(records), expected)

    def test_missing_and_corrupt_bundled_assets_fail_without_allocating_native_ids(self):
        prepared = complete_prepared()
        source = resources.files("color_tools.kernel")
        files = {name: source.joinpath(name).read_bytes()
                 for name in ("node_templates.json", "node_templates.blend", "grade_stack.glsl")}
        for failure in ("missing_blend", "corrupt_blend", "invalid_manifest",
                        "missing_variant", "wrong_structure"):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory(
                    prefix="pg-invalid-template-") as directory:
                root = Path(directory)
                for name, data in files.items():
                    (root / name).write_bytes(data)
                if failure == "missing_blend":
                    (root / "node_templates.blend").unlink()
                elif failure == "corrupt_blend":
                    (root / "node_templates.blend").write_bytes(b"corrupt template")
                else:
                    manifest = json.loads(files["node_templates.json"])
                    if failure == "invalid_manifest":
                        manifest["schema"] = -1
                    elif failure == "missing_variant":
                        del manifest["variants"]["grade:ShaderNodeTree:Linear Rec.709"]
                    else:
                        manifest["variants"]["grade:ShaderNodeTree:Linear Rec.709"][
                            "structure_sha256"] = "0" * 64
                    (root / "node_templates.json").write_text(json.dumps(manifest))
                before = (set(bpy.data.node_groups), set(bpy.data.images))
                store = node_templates.TemplateStore()
                with patch.object(node_templates.resources, "files", return_value=root):
                    with self.assertRaises(node_templates.TemplateAssetError):
                        node_templates.instantiate_grade(prepared, "ShaderNodeTree", store=store)
                self.assertEqual((set(bpy.data.node_groups), set(bpy.data.images)), before)

    def test_existing_group_named_like_template_is_never_adopted_as_source(self):
        prepared = complete_prepared()
        _, records = node_templates.load_manifest()
        record = records["grade:ShaderNodeTree:Linear Rec.709"]
        before_groups = set(bpy.data.node_groups)
        before_images = set(bpy.data.images)
        user_tree = bpy.data.node_groups.new(record.name, "ShaderNodeTree")
        user_tree["user_content"] = "keep me"
        first = node_templates.instantiate_grade(prepared, "ShaderNodeTree")
        try:
            self.assertNotEqual(first.tree, user_tree)
            self.assertEqual(user_tree["user_content"], "keep me")
            self.assertEqual(len(user_tree.nodes), 0)
            self.assert_parameter_bindings(first, prepared, 0, 0)
        finally:
            first.dispose()
        self.assertEqual(set(bpy.data.node_groups), before_groups | {user_tree})
        self.assertEqual(set(bpy.data.images), before_images)

    def test_every_grade_variant_has_private_parameter_bindings(self):
        for space in SPACES:
            for tree_type in TREE_TYPES:
                with self.subTest(space=space, tree_type=tree_type):
                    before = (set(bpy.data.node_groups), set(bpy.data.images))
                    first_prepared = complete_prepared(space)
                    second_prepared = complete_prepared(space, adjusted=True)
                    first = node_templates.instantiate_grade(first_prepared, tree_type,
                                                             active_bank=0, generation=3)
                    second = node_templates.instantiate_grade(second_prepared, tree_type,
                                                              active_bank=1, generation=7)
                    try:
                        first_banks = self.assert_parameter_bindings(first, first_prepared, 0, 3)
                        second_banks = self.assert_parameter_bindings(second, second_prepared, 1, 7)
                        self.assertNotEqual(first.tree, second.tree)
                        self.assertFalse(set(first_banks).intersection(second_banks))
                        self.assertFalse(set(first.images).intersection(second.images))
                        first.tree.nodes.remove(next(node for node in first.tree.nodes
                                                     if node.get(PARAMETER_READER)))
                        third = node_templates.instantiate_grade(first_prepared, tree_type)
                        try:
                            self.assert_parameter_bindings(third, first_prepared, 0, 0)
                            self.assert_parameter_bindings(second, second_prepared, 1, 7)
                        finally:
                            third.dispose()
                    finally:
                        second.dispose()
                        first.dispose()
                    self.assertEqual((set(bpy.data.node_groups), set(bpy.data.images)), before)

    def test_borrowed_grade_banks_survive_instance_disposal(self):
        prepared = complete_prepared(adjusted=True)
        first = node_templates.instantiate_grade(prepared, "ShaderNodeTree")
        banks = tuple(first.tree[key] for key in PARAMETER_BANK_BINDINGS)
        second = node_templates.instantiate_grade(prepared, "CompositorNodeTree",
                                                  parameter_images=banks, active_bank=1)
        bank_names = tuple(image.name for image in banks)
        try:
            self.assertEqual(tuple(second.tree[key] for key in PARAMETER_BANK_BINDINGS), banks)
            second.dispose()
            self.assertTrue(all(name in bpy.data.images for name in bank_names))
            self.assert_parameter_bindings(first, prepared, 0, 0)
        finally:
            first.dispose()

    def test_every_stack_variant_uploads_its_own_atlas(self):
        for space in SPACES:
            for size in (33, 65):
                prepared = stack_prepared(space, size)
                changed = stack_prepared(space, size, scale=0.8)
                for tree_type in TREE_TYPES:
                    with self.subTest(space=space, size=size, tree_type=tree_type):
                        first = node_templates.instantiate_stack(prepared, tree_type)
                        second = node_templates.instantiate_stack(changed, tree_type)
                        try:
                            self.assert_local(first)
                            self.assert_local(second)
                            self.assertNotEqual(first.tree, second.tree)
                            first_image, = first.images
                            second_image, = second.images
                            self.assertNotEqual(first_image, second_image)
                            expected = (prepared.cube.shader_pixels() if tree_type == "ShaderNodeTree"
                                        else prepared.cube.compositor_pixels())
                            np.testing.assert_array_equal(image_pixels(first_image), expected)
                            readers = [node for node in first.tree.nodes
                                       if getattr(node, "image", None) is not None]
                            self.assertTrue(readers)
                            self.assertTrue(all(node.image == first_image for node in readers))
                        finally:
                            second.dispose()
                            first.dispose()

    def test_wrapper_instances_share_only_the_requested_live_kernel(self):
        prepared = complete_prepared()
        for tree_type in TREE_TYPES:
            with self.subTest(tree_type=tree_type):
                live = node_templates.instantiate_grade(prepared, tree_type)
                first = node_templates.TemplateInstance(
                    node_templates.instantiate_wrapper(tree_type, live.tree))
                second = node_templates.TemplateInstance(
                    node_templates.instantiate_wrapper(tree_type, live.tree))
                try:
                    self.assertNotEqual(first.tree, second.tree)
                    first_live, = (node for node in first.tree.nodes if node.get("_pg_next_bake_live"))
                    second_live, = (node for node in second.tree.nodes if node.get("_pg_next_bake_live"))
                    self.assertEqual(first_live.node_tree, live.tree)
                    self.assertEqual(second_live.node_tree, live.tree)
                    first_reader, = (node for node in first.tree.nodes if node.get("_pg_next_bake_reader"))
                    second_reader, = (node for node in second.tree.nodes if node.get("_pg_next_bake_reader"))
                    first_reader.image = live.images[0]
                    self.assertIsNone(second_reader.image)
                    self.assert_local(first)
                    self.assert_local(second)
                finally:
                    second.dispose()
                    first.dispose()
                    live.dispose()

    def test_wrapper_validation_failure_retires_root_and_helpers(self):
        """A failed wrapper append cannot strand its live-interface helper."""
        prepared = complete_prepared()
        live = node_templates.instantiate_grade(prepared, "ShaderNodeTree")
        before = (set(bpy.data.node_groups), set(bpy.data.images))
        calls = []

        def retire(kind, resource):
            # Production policy retirement also refuses protected/in-use IDs;
            # this callback deliberately does not unlink dependants for us.
            self.assertFalse(resource.use_fake_user)
            self.assertEqual(resource.users, 0)
            calls.append((kind, resource.name))
            collection = bpy.data.images if kind == "image" else bpy.data.node_groups
            collection.remove(resource, do_unlink=False)

        try:
            store = node_templates.TemplateStore()
            variant = node_templates.TemplateVariant("wrapper", "ShaderNodeTree")
            record = replace(store.record(variant), structure_sha256="0" * 64)
            with patch.object(store, "record", return_value=record):
                with self.assertRaises(node_templates.TemplateAssetError):
                    node_templates.instantiate_wrapper(
                        "ShaderNodeTree", live.tree, store=store, retire=retire,
                    )
            self.assertEqual(len(calls), 2)
            self.assertEqual((set(bpy.data.node_groups), set(bpy.data.images)), before)
        finally:
            live.dispose()

    def test_saved_instances_are_local_and_factory_reset_needs_no_native_cache(self):
        prepared = complete_prepared("ACEScg", adjusted=True)
        with tempfile.TemporaryDirectory(prefix="pg-template-roundtrip-") as directory:
            first = node_templates.instantiate_grade(prepared, "ShaderNodeTree", active_bank=1,
                                                     generation=9)
            first.tree.use_fake_user = True
            name = first.tree.name
            filename = Path(directory) / "template-instance.blend"
            bpy.ops.wm.save_as_mainfile(filepath=str(filename))
            bpy.ops.wm.read_factory_settings(use_empty=True)
            fresh = node_templates.instantiate_grade(prepared, "ShaderNodeTree")
            self.assert_parameter_bindings(fresh, prepared, 0, 0)
            fresh.dispose()
            bpy.ops.wm.open_mainfile(filepath=str(filename))
            restored = bpy.data.node_groups[name]
            self.assertIsNone(restored.library)
            restored_banks = tuple(restored[key] for key in PARAMETER_BANK_BINDINGS)
            self.assertEqual(restored[PARAMETER_ACTIVE_BANK], 1)
            self.assertEqual(restored[PARAMETER_GENERATION], 9)
            for image in restored_banks:
                self.assertIsNone(image.library)
                self.assertIsNotNone(image.packed_file)
                np.testing.assert_array_equal(image_pixels(image), prepare_parameters(prepared).pixels)
            replacement = node_templates.instantiate_grade(prepared, "ShaderNodeTree")
            try:
                self.assertNotEqual(replacement.tree, restored)
                self.assertFalse(set(restored_banks).intersection(
                    replacement.tree[key] for key in PARAMETER_BANK_BINDINGS))
            finally:
                replacement.dispose()


if __name__ == "__main__":
    unittest.main()
