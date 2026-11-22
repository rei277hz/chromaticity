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
    PARAMETER_READER, PARAMETER_READER_BANK, PARAMETER_READER_ROLE, PARAMETER_SELECTOR,
)
from color_tools.kernel.stage2_parameters import (
    PARAMETER_ROLES, parameter_bank_images, prepare_parameters,
)
from color_tools.kernel.lut import basis, basis_pixels, stack_config_pixels

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
        parameters = prepare_parameters(prepared)
        for bank in banks:
            images = parameter_bank_images(bank)
            self.assertEqual(set(images), set(PARAMETER_ROLES))
            self.assertEqual(len({image.as_pointer() for image in images.values()}),
                             len(PARAMETER_ROLES))
            for role, image in images.items():
                np.testing.assert_array_equal(image_pixels(image), parameters.roles[role])
        readers = tuple(node for node in tree.nodes if node.get(PARAMETER_READER))
        self.assertEqual({node[PARAMETER_READER_BANK] for node in readers}, {0, 1})
        self.assertEqual({(node[PARAMETER_READER_BANK], node[PARAMETER_READER_ROLE])
                          for node in readers},
                         {(bank, role) for bank in (0, 1) for role in PARAMETER_ROLES})
        for reader in readers:
            bank, role = reader[PARAMETER_READER_BANK], reader[PARAMETER_READER_ROLE]
            self.assertEqual(reader.image, parameter_bank_images(banks[bank])[role])
        selector, = (node for node in tree.nodes if node.get(PARAMETER_SELECTOR))
        value = (selector.outputs["Value"].default_value if tree.bl_idname == "ShaderNodeTree"
                 else selector.inputs[0].default_value)
        self.assertEqual(value, float(active))
        self.assert_local(instance)
        return banks

    def set_working_space(self, space):
        if bpy.data.colorspace.working_space != space:
            result = bpy.ops.wm.set_working_color_space(working_space=space)
            self.assertEqual(result, {"FINISHED"})
        self.assertEqual(bpy.data.colorspace.working_space, space)

    @staticmethod
    def color_socket(socket):
        return (getattr(socket, "type", None) == "RGBA"
                or getattr(socket, "bl_idname", None) == "NodeSocketColor")

    def test_manifest_covers_every_product_variant(self):
        expected = {
            f"grade:{tree_type}" for tree_type in TREE_TYPES
        } | {
            f"stack:{tree_type}" for tree_type in TREE_TYPES
        } | {f"wrapper:{tree_type}" for tree_type in TREE_TYPES} | {
            f"fallback:{mode}:{tree_type}:{vector}"
            for mode in ("pending", "error") for tree_type in TREE_TYPES
            for vector in ((0, 1) if tree_type == "ShaderNodeTree" else (0,))
        }
        self.assertEqual(len(expected), 12)
        manifest, records = node_templates.load_manifest()
        self.assertEqual(set(manifest["variants"]), expected)
        self.assertEqual(set(records), expected)

    def test_templates_accept_the_actual_working_space(self):
        """Blender converts color defaults while appending a library."""
        receipts = {"grade": {}, "stack": {}}
        for space in SPACES:
            with self.subTest(space=space):
                self.set_working_space(space)
                grade = {}
                stack = {}
                wrappers = {}
                try:
                    for tree_type in TREE_TYPES:
                        grade[tree_type] = node_templates.instantiate_grade(
                            complete_prepared(space), tree_type,
                        )
                        stack[tree_type] = node_templates.instantiate_stack(
                            stack_prepared(space, 33), tree_type,
                        )
                        receipts["grade"].setdefault(tree_type, set()).add(
                            node_templates.structure_digest(grade[tree_type].tree),
                        )
                        receipts["stack"].setdefault(tree_type, set()).add(
                            node_templates.structure_digest(stack[tree_type].tree),
                        )
                        wrappers[tree_type] = node_templates.TemplateInstance(
                            node_templates.instantiate_wrapper(
                                tree_type, grade[tree_type].tree,
                            )
                        )
                finally:
                    for instance in wrappers.values():
                        instance.dispose()
                    for instance in stack.values():
                        instance.dispose()
                    for instance in grade.values():
                        instance.dispose()
        for kind in receipts:
            for tree_type, values in receipts[kind].items():
                self.assertEqual(len(values), 1, (kind, tree_type, values))

    def test_fallback_templates_preserve_interfaces_and_alpha(self):
        for mode in ("pending", "error"):
            for tree_type in TREE_TYPES:
                vectors = (False, True) if tree_type == "ShaderNodeTree" else (False,)
                for vector in vectors:
                    with self.subTest(mode=mode, tree_type=tree_type, vector=vector):
                        before = (set(bpy.data.node_groups), set(bpy.data.images))
                        built = node_templates.instantiate_fallback(
                            mode, tree_type, vector=vector,
                        )
                        try:
                            tree = built.tree
                            self.assertTrue(node_templates.validate_fallback_instance(
                                tree, mode, vector=vector,
                            ))
                            self.assertFalse(node_templates.validate_fallback_instance(
                                tree, "error" if mode == "pending" else "pending",
                                vector=vector,
                            ))
                            self.assertFalse(node_templates.validate_fallback_instance(
                                tree, mode, vector=not vector,
                            ))
                            self.assertEqual(tree.get(node_templates.FALLBACK_KERNEL), 1)
                            self.assertEqual(tree.get(node_templates.FALLBACK_MODE), mode)
                            inputs = {item.name for item in tree.interface.items_tree
                                      if item.item_type == "SOCKET" and item.in_out == "INPUT"}
                            self.assertEqual("Vector" in inputs, vector)
                            output = next(item for item in tree.nodes
                                          if item.bl_idname == "NodeGroupOutput")
                            self.assertTrue(output.inputs["Color"].is_linked)
                            if tree_type == "ShaderNodeTree":
                                self.assertTrue(output.inputs["Alpha"].is_linked)
                            elif mode == "error":
                                self.assertTrue(any(
                                    node.bl_idname == "CompositorNodeSetAlpha"
                                    for node in tree.nodes
                                ))
                        finally:
                            built.dispose(unlink=True)
                        self.assertEqual((set(bpy.data.node_groups), set(bpy.data.images)), before)

    def test_fallback_validation_rejects_invalid_context_without_allocating_ids(self):
        before = (set(bpy.data.node_groups), set(bpy.data.images))
        self.assertFalse(node_templates.validate_fallback_instance(None, "pending"))
        for mode, tree_type, vector in (
                ("current", "ShaderNodeTree", False),
                ("pending", "CompositorNodeTree", True)):
            with self.subTest(constructor=(mode, tree_type, vector)):
                with self.assertRaises(node_templates.TemplateAssetError):
                    node_templates.instantiate_fallback(mode, tree_type, vector=vector)
                self.assertEqual((set(bpy.data.node_groups), set(bpy.data.images)), before)
        built = node_templates.instantiate_fallback("pending", "ShaderNodeTree")
        try:
            retained = (set(bpy.data.node_groups), set(bpy.data.images))
            for mode in (None, "", "current"):
                with self.subTest(mode=mode):
                    self.assertFalse(node_templates.validate_fallback_instance(built.tree, mode))
            built.tree[node_templates.FALLBACK_MODE] = "current"
            self.assertFalse(node_templates.validate_fallback_instance(built.tree, "current"))
            self.assertEqual((set(bpy.data.node_groups), set(bpy.data.images)), retained)
        finally:
            built.dispose(unlink=True)
        self.assertEqual((set(bpy.data.node_groups), set(bpy.data.images)), before)

    def test_fallback_validation_rejects_changed_markers_and_graph_contract(self):
        def change_interface(tree):
            socket = next(item for item in tree.interface.items_tree
                          if item.item_type == "SOCKET" and item.in_out == "INPUT"
                          and item.name == "Color")
            socket.name = "Changed Color"

        def change_interface_default(tree):
            socket = next(item for item in tree.interface.items_tree
                          if item.item_type == "SOCKET" and item.in_out == "INPUT"
                          and item.name == "Color")
            socket.default_value = (0.0, 0.0, 0.0, 0.5)

        def change_links(tree):
            tree.links.remove(next(iter(tree.links)))

        def change_topology(tree):
            tree.nodes.new("NodeReroute")

        def change_effective_default(tree):
            magenta = next(node for node in tree.nodes
                           if node.bl_idname in {"ShaderNodeCombineColor",
                                                 "CompositorNodeCombineColor"})
            magenta.inputs["Red"].default_value = 0.5

        marker_changes = {
            "missing_kernel_marker": (node_templates.FALLBACK_KERNEL, None),
            "wrong_kernel_marker": (node_templates.FALLBACK_KERNEL, 0),
            "wrong_mode": (node_templates.FALLBACK_MODE, "current"),
            "wrong_schema": (node_templates.TEMPLATE_SCHEMA, -1),
            "wrong_kind": (node_templates.TEMPLATE_KIND, "grade"),
            "wrong_variant": (node_templates.TEMPLATE_VARIANT, "invalid"),
            "wrong_template_mode": (node_templates.TEMPLATE_MODE, "current"),
            "wrong_template_vector": (node_templates.TEMPLATE_VECTOR, None),
        }
        for mode in ("pending", "error"):
            for tree_type in TREE_TYPES:
                vectors = (False, True) if tree_type == "ShaderNodeTree" else (False,)
                for vector in vectors:
                    changes = {
                        "interface": change_interface,
                        "interface_default": change_interface_default,
                        "links": change_links,
                        "topology": change_topology,
                    }
                    if mode == "error":
                        changes["effective_default"] = change_effective_default
                    for name, (key, value) in marker_changes.items():
                        if name == "missing_kernel_marker":
                            changes[name] = lambda tree, key=key: tree.__delitem__(key)
                        else:
                            value = not vector if name == "wrong_template_vector" else value
                            changes[name] = lambda tree, key=key, value=value: tree.__setitem__(
                                key, value,
                            )
                    for change, mutate in changes.items():
                        with self.subTest(mode=mode, tree_type=tree_type,
                                          vector=vector, change=change):
                            before = (set(bpy.data.node_groups), set(bpy.data.images))
                            built = node_templates.instantiate_fallback(
                                mode, tree_type, vector=vector,
                            )
                            try:
                                self.assertTrue(node_templates.validate_fallback_instance(
                                    built.tree, mode, vector=vector,
                                ))
                                mutate(built.tree)
                                retained = (set(bpy.data.node_groups), set(bpy.data.images))
                                self.assertFalse(node_templates.validate_fallback_instance(
                                    built.tree, mode, vector=vector,
                                ))
                                self.assertEqual((set(bpy.data.node_groups), set(bpy.data.images)),
                                                 retained)
                            finally:
                                built.dispose(unlink=True)
                            self.assertEqual((set(bpy.data.node_groups), set(bpy.data.images)),
                                             before)

    def test_receipt_uses_effective_defaults(self):
        prepared = complete_prepared()
        instance = node_templates.instantiate_grade(prepared, "ShaderNodeTree")
        try:
            tree = instance.tree
            baseline = node_templates.structure_digest(tree)
            converted = next(
                socket for node in tree.nodes for socket in node.inputs
                if self.color_socket(socket) and (
                    socket.is_linked or getattr(socket, "is_inactive", False)
                )
            )
            original_color = tuple(converted.default_value)
            converted.default_value = (0.123, 0.234, 0.345, 1.0)
            self.assertEqual(node_templates.structure_digest(tree), baseline)
            converted.default_value = original_color

            effective = next(
                socket for node in tree.nodes for socket in node.inputs
                if getattr(socket, "type", None) == "VALUE"
                and not socket.is_linked
                and not getattr(socket, "is_inactive", False)
                and hasattr(socket, "default_value")
            )
            original_value = effective.default_value
            if isinstance(original_value, (tuple, list)):
                mutated = tuple(float(value) + 0.125 for value in original_value)
            else:
                mutated = float(original_value) + 0.125
            effective.default_value = mutated
            self.assertNotEqual(node_templates.structure_digest(tree), baseline)
            effective.default_value = original_value

            color_input = next(
                item for item in tree.interface.items_tree
                if item.item_type == "SOCKET"
                and item.in_out == "INPUT"
                and item.name == "Color"
            )
            original_color_input = tuple(color_input.default_value)
            color_input.default_value = (0.125, 0.0, 0.0, 1.0)
            with self.assertRaisesRegex(
                    node_templates.TemplateAssetError,
                    "working-space-sensitive color input"):
                node_templates.structure_digest(tree)
            color_input.default_value = original_color_input
        finally:
            instance.dispose()

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
                        del manifest["variants"]["grade:ShaderNodeTree"]
                    else:
                        manifest["variants"]["grade:ShaderNodeTree"][
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
        record = records["grade:ShaderNodeTree"]
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
        bank_names = tuple(image.name for bank in banks
                           for image in parameter_bank_images(bank).values())
        try:
            self.assertEqual(tuple(second.tree[key] for key in PARAMETER_BANK_BINDINGS), banks)
            second.dispose()
            self.assertTrue(all(name in bpy.data.images for name in bank_names))
            self.assert_parameter_bindings(first, prepared, 0, 0)
        finally:
            first.dispose()

    def test_grade_parameters_are_packed_only_for_owned_banks(self):
        prepared = complete_prepared(adjusted=True)
        with patch.object(node_templates, "prepare_parameters",
                          wraps=prepare_parameters) as pack_parameters:
            first = node_templates.instantiate_grade(prepared, "ShaderNodeTree")
        pack_parameters.assert_called_once_with(prepared)
        banks = tuple(first.tree[key] for key in PARAMETER_BANK_BINDINGS)
        try:
            with patch.object(node_templates, "prepare_parameters",
                              side_effect=AssertionError("borrowed banks need no packing")):
                second = node_templates.instantiate_grade(
                    prepared, "CompositorNodeTree", parameter_images=banks,
                )
            try:
                self.assertEqual(
                    tuple(second.tree[key] for key in PARAMETER_BANK_BINDINGS), banks,
                )
                self.assert_parameter_bindings(second, prepared, 0, 0)
            finally:
                second.dispose()
        finally:
            first.dispose()

        cached = replace(prepared, parameters=prepare_parameters(prepared))
        with patch.object(node_templates, "prepare_parameters",
                          side_effect=AssertionError("cached parameters must be reused")):
            instance = node_templates.instantiate_grade(cached, "ShaderNodeTree")
        try:
            self.assert_parameter_bindings(instance, cached, 0, 0)
        finally:
            instance.dispose()

    def test_shared_stack_templates_bind_size_specific_runtime_images(self):
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
                            first_lut, first_basis, first_config = first.images
                            second_lut, second_basis, second_config = second.images
                            self.assertNotEqual(first_lut, second_lut)
                            self.assertNotEqual(first_basis, second_basis)
                            self.assertNotEqual(first_config, second_config)
                            self.assertTrue(node_templates.validate_stack_instance(first.tree))
                            expected = (prepared.cube.shader_pixels() if tree_type == "ShaderNodeTree"
                                        else prepared.cube.compositor_pixels())
                            np.testing.assert_array_equal(image_pixels(first_lut), expected)
                            expected_basis = basis_pixels(*basis(space))
                            np.testing.assert_array_equal(image_pixels(first_basis), expected_basis)
                            expected_config = stack_config_pixels(size)
                            np.testing.assert_array_equal(image_pixels(first_config), expected_config)
                            record = node_templates._STORE.record(
                                node_templates.TemplateVariant("stack", tree_type),
                            )
                            lut_readers = [first.tree.nodes[name] for name in
                                           record.slots[node_templates.SLOT_LUT]]
                            basis_readers = [first.tree.nodes[name] for name in
                                             record.slots[node_templates.SLOT_BASIS]]
                            config_readers = [first.tree.nodes[name] for name in
                                              record.slots[node_templates.SLOT_CONFIG]]
                            self.assertTrue(lut_readers)
                            self.assertTrue(basis_readers)
                            self.assertTrue(config_readers)
                            self.assertTrue(all(node.image == first_lut for node in lut_readers))
                            self.assertTrue(all(node.image == first_basis for node in basis_readers))
                            self.assertTrue(all(node.image == first_config for node in config_readers))
                        finally:
                            second.dispose()
                            first.dispose()

    def test_stack_validation_rejects_resolution_config_drift(self):
        instance = node_templates.instantiate_stack(stack_prepared(size=33), "ShaderNodeTree")
        try:
            self.assertTrue(node_templates.validate_stack_instance(instance.tree))
            instance.tree[node_templates.KERNEL_QUALITY] = "full"
            self.assertFalse(node_templates.validate_stack_instance(instance.tree))
        finally:
            instance.dispose()

    def test_grade_manifest_validation_rejects_changed_math_and_boundary_pixels(self):
        for tree_type in TREE_TYPES:
            with self.subTest(tree_type=tree_type):
                instance = node_templates.instantiate_grade(
                    complete_prepared(), tree_type,
                )
                try:
                    tree = instance.tree
                    self.assertTrue(node_templates.validate_grade_template(tree))
                    math_node = next(
                        node for node in tree.nodes
                        if hasattr(node, "operation") and not node.get(PARAMETER_SELECTOR)
                    )
                    original_operation = math_node.operation
                    math_node.operation = "MULTIPLY" if original_operation != "MULTIPLY" else "ADD"
                    self.assertFalse(node_templates.validate_grade_template(tree))
                    math_node.operation = original_operation
                    self.assertTrue(node_templates.validate_grade_template(tree))

                    record = node_templates._STORE.record(
                        node_templates.TemplateVariant("grade", tree_type),
                    )
                    boundary = tree.nodes[record.slots[node_templates.SLOT_BOUNDARY][0]].image
                    pixels = image_pixels(boundary)
                    pixels[0, 0, 0] += np.float32(0.125)
                    boundary.pixels.foreach_set(pixels.ravel())
                    boundary.pack()
                    self.assertFalse(node_templates.validate_grade_template(tree))
                finally:
                    instance.dispose()

    def test_stack_validation_rejects_packed_lut_pixel_changes(self):
        instance = node_templates.instantiate_stack(
            stack_prepared(size=33), "ShaderNodeTree",
        )
        try:
            self.assertTrue(node_templates.validate_stack_instance(instance.tree))
            lut_image = instance.images[0]
            pixels = image_pixels(lut_image)
            pixels[0, 0, 0] += np.float32(0.125)
            lut_image.pixels.foreach_set(pixels.ravel())
            lut_image.pack()
            self.assertFalse(node_templates.validate_stack_instance(instance.tree))
            self.assertTrue(node_templates.validate_stack_instance(
                instance.tree, deep=False,
            ))
        finally:
            instance.dispose()

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
            self.assertTrue(node_templates.validate_grade_template(restored))
            restored_banks = tuple(restored[key] for key in PARAMETER_BANK_BINDINGS)
            self.assertEqual(restored[PARAMETER_ACTIVE_BANK], 1)
            self.assertEqual(restored[PARAMETER_GENERATION], 9)
            for image in restored_banks:
                self.assertIsNone(image.library)
                self.assertIsNotNone(image.packed_file)
                for role, member in parameter_bank_images(image).items():
                    self.assertIsNone(member.library)
                    self.assertIsNotNone(member.packed_file)
                    np.testing.assert_array_equal(image_pixels(member),
                                                  prepare_parameters(prepared).roles[role])
            replacement = node_templates.instantiate_grade(prepared, "ShaderNodeTree")
            try:
                self.assertNotEqual(replacement.tree, restored)
                self.assertFalse(set(restored_banks).intersection(
                    replacement.tree[key] for key in PARAMETER_BANK_BINDINGS))
            finally:
                replacement.dispose()


if __name__ == "__main__":
    unittest.main()
