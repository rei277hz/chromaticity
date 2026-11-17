"""Native fallback acquisition reuses and retains safe node-group identities."""

import importlib
from importlib.resources import files
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import bpy

VARIANTS = tuple(
    (mode, tree_type, vector)
    for mode in ("pending", "error")
    for tree_type in ("ShaderNodeTree", "CompositorNodeTree")
    for vector in ((False, True) if tree_type == "ShaderNodeTree" else (False,))
)


class FallbackPoolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix="grade-fallback-pool-")
        root = Path(cls.directory.name)
        package = root / "grade_fallback_pool_test"
        package.mkdir()
        with zipfile.ZipFile(files("tests.perceptual_grade_blender") / "extension.zip") as archive:
            archive.extractall(package)
        sys.path.insert(0, str(root))
        cls.node_module = importlib.import_module("grade_fallback_pool_test.nodes")
        cls.node_templates = importlib.import_module("grade_fallback_pool_test.kernel.node_templates")

    @classmethod
    def tearDownClass(cls):
        sys.path.remove(cls.directory.name)
        for name in tuple(sys.modules):
            if name == "grade_fallback_pool_test" or name.startswith("grade_fallback_pool_test."):
                del sys.modules[name]
        cls.directory.cleanup()

    def setUp(self):
        bpy.ops.wm.read_factory_settings(use_empty=True)

    def tearDown(self):
        bpy.ops.wm.read_factory_settings(use_empty=True)

    @staticmethod
    def ids():
        return set(bpy.data.node_groups), set(bpy.data.images)

    def test_all_variants_reuse_preferred_and_scanned_instances(self):
        for mode, tree_type, vector in VARIANTS:
            with self.subTest(mode=mode, tree_type=tree_type, vector=vector):
                before = self.ids()
                first = self.node_module._acquire_fallback_kernel(
                    mode, tree_type, vector=vector,
                )
                try:
                    self.assertTrue(self.node_templates.validate_fallback_instance(
                        first, mode, vector=vector,
                    ))
                    self.assertTrue(first.use_fake_user)
                    native_identity = first.as_pointer(), int(first.session_uid)
                    preferred = self.node_module._acquire_fallback_kernel(
                        mode, tree_type, vector=vector, preferred=first,
                    )
                    scanned = self.node_module._acquire_fallback_kernel(
                        mode, tree_type, vector=vector,
                    )
                    self.assertEqual((preferred.as_pointer(), int(preferred.session_uid)),
                                     native_identity)
                    self.assertEqual((scanned.as_pointer(), int(scanned.session_uid)),
                                     native_identity)
                    self.assertEqual(self.ids(), (before[0] | {first}, before[1]))
                finally:
                    # Historical fallbacks are intentionally retained by the
                    # resource policy, even after their active reader leaves.
                    first.use_fake_user = False
                    self.assertEqual(self.node_module._retire_kernels((first,)), ())
                    self.assertTrue(first.use_fake_user)
                    self.assertIn(first, set(bpy.data.node_groups))

    def test_invalid_historical_fallback_gets_replaced_and_old_id_is_retained(self):
        for mode, tree_type, vector in VARIANTS:
            with self.subTest(mode=mode, tree_type=tree_type, vector=vector):
                old = self.node_module._acquire_fallback_kernel(
                    mode, tree_type, vector=vector,
                )
                old_pointer = old.as_pointer()
                old[self.node_templates.FALLBACK_MODE] = "invalid"
                replacement = self.node_module._acquire_fallback_kernel(
                    mode, tree_type, vector=vector,
                )
                try:
                    self.assertNotEqual(replacement.as_pointer(), old_pointer)
                    self.assertTrue(self.node_templates.validate_fallback_instance(
                        replacement, mode, vector=vector,
                    ))
                    self.assertTrue(old.use_fake_user)
                    old.use_fake_user = False
                    self.assertEqual(self.node_module._retire_kernels((old,)), ())
                    self.assertTrue(old.use_fake_user)
                    self.assertIn(old, set(bpy.data.node_groups))
                finally:
                    replacement.use_fake_user = False
                    self.assertEqual(self.node_module._retire_kernels((replacement,)), ())
                    self.assertTrue(replacement.use_fake_user)
                    old.use_fake_user = False
                    self.assertEqual(self.node_module._retire_kernels((old,)), ())
                    self.assertTrue(old.use_fake_user)

    def test_topology_corruption_is_replaced_without_deleting_history(self):
        for mode, tree_type, vector in VARIANTS:
            with self.subTest(mode=mode, tree_type=tree_type, vector=vector):
                old = self.node_module._acquire_fallback_kernel(
                    mode, tree_type, vector=vector,
                )
                old.nodes.new("NodeReroute")
                self.assertFalse(self.node_templates.validate_fallback_instance(
                    old, mode, vector=vector,
                ))
                replacement = self.node_module._acquire_fallback_kernel(
                    mode, tree_type, vector=vector,
                )
                try:
                    self.assertNotEqual(replacement, old)
                    self.assertTrue(self.node_templates.validate_fallback_instance(
                        replacement, mode, vector=vector,
                    ))
                    old.use_fake_user = False
                    self.assertEqual(self.node_module._retire_kernels((old,)), ())
                    self.assertTrue(old.use_fake_user)
                    self.assertIn(old, set(bpy.data.node_groups))
                finally:
                    replacement.use_fake_user = False
                    self.assertEqual(self.node_module._retire_kernels((replacement,)), ())
                    old.use_fake_user = False
                    self.assertEqual(self.node_module._retire_kernels((old,)), ())

    def test_legacy_marker_only_groups_are_retained_for_undo(self):
        for marker in (self.node_templates.FALLBACK_KERNEL,
                       self.node_module._IDENTITY_KERNEL_KIND,
                       self.node_module._ERROR_KERNEL_KIND):
            for tree_type in ("ShaderNodeTree", "CompositorNodeTree"):
                for value in (self.node_module._KERNEL_SCHEMA, 0, False):
                    with self.subTest(marker=marker, tree_type=tree_type, value=value):
                        tree = bpy.data.node_groups.new("Legacy fallback", tree_type)
                        tree[marker] = value
                        if marker != self.node_templates.FALLBACK_KERNEL:
                            self.assertNotIn(self.node_templates.FALLBACK_KERNEL, tree)
                        self.assertEqual(tree.users, 0)
                        self.assertEqual(self.node_module._retire_kernels((tree,)), ())
                        self.assertTrue(tree.use_fake_user)
                        self.assertIn(tree, set(bpy.data.node_groups))

    def test_linked_fallback_is_rejected_and_replaced_by_local_instance(self):
        tree = self.node_module._acquire_fallback_kernel("pending", "ShaderNodeTree")
        name = tree.name
        with tempfile.TemporaryDirectory(prefix="grade-linked-fallback-") as directory:
            path = Path(directory) / "fallback.blend"
            bpy.data.libraries.write(str(path), {tree})
            bpy.data.node_groups.remove(tree, do_unlink=True)
            del tree
            with bpy.data.libraries.load(str(path), link=True) as (_, selected):
                selected.node_groups = [name]
            linked, = selected.node_groups
            self.assertIsNotNone(linked.library)
            self.assertEqual(linked.get(self.node_templates.FALLBACK_KERNEL), 1)
            record = self.node_templates._STORE.record(self.node_templates.TemplateVariant(
                "fallback", "ShaderNodeTree", mode="pending", vector=False,
            ))
            self.node_templates._validate_tree(linked, record)
            self.assertFalse(self.node_templates.validate_fallback_instance(linked, "pending"))
            local = self.node_module._acquire_fallback_kernel(
                "pending", "ShaderNodeTree", preferred=linked,
            )
            self.assertIsNone(local.library)
            self.assertTrue(self.node_templates.validate_fallback_instance(local, "pending"))
            self.assertNotEqual(local, linked)
            self.assertTrue(local.use_fake_user)

    def test_failed_append_validation_cleans_all_native_ids(self):
        before = self.ids()
        with patch.object(self.node_module, "validate_fallback_instance", return_value=False):
            with self.assertRaises(RuntimeError):
                self.node_module._acquire_fallback_kernel(
                    "pending", "ShaderNodeTree", vector=False,
                )
        self.assertEqual(self.ids(), before)


if __name__ == "__main__":
    unittest.main()
