"""Fixed helper banks remain shared, selected, and pinned across lifecycles."""

import importlib
from importlib.resources import files
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
import zipfile

import numpy as np


class PixelBuffer:
    def __init__(self, values):
        self.values = np.asarray(values, dtype=np.float32).reshape((1, 512, 4))

    def foreach_get(self, output):
        output[:] = self.values.ravel()

    def foreach_set(self, values):
        self.values = np.asarray(values, dtype=np.float32).reshape((1, 512, 4)).copy()


class Image(dict):
    def __init__(self, pointer, *, schema, content_key, content_signature,
                 users=0, fake=False, fill=0.):
        super().__init__()
        self.pointer = pointer
        self.size = (512, 1)
        self.users = users
        self.use_fake_user = fake
        self.live = True
        self.raise_when_removed = False
        self.is_dirty = False
        self.packed_file = object()
        pixels = np.full((1, 512, 4), fill, dtype=np.float32)
        self.pixels = PixelBuffer(pixels)
        self["_perceptual_grade_parameter_schema"] = schema
        self[content_key] = content_signature(self.pixels.values)

    def as_pointer(self):
        if not self.live and self.raise_when_removed:
            raise ReferenceError("removed image wrapper")
        return self.pointer if self.live else 0

    def __eq__(self, other):
        return self is other


class Tree(dict):
    def __init__(self, tree_type, owner, banks, active=0, generation=1):
        super().__init__()
        self.bl_idname = tree_type
        self["_perceptual_grade_parameter_owner"] = owner
        self["_perceptual_grade_parameter_owner_node"] = None
        self["_perceptual_grade_working_space"] = "linear"
        self["_perceptual_grade_stage2_complete"] = True
        self["_perceptual_grade_parameter_bank_0"] = banks[0]
        self["_perceptual_grade_parameter_bank_1"] = banks[1]
        self["_perceptual_grade_parameter_active_bank"] = active
        self["_perceptual_grade_parameter_generation"] = generation
        selector = Node({"_perceptual_grade_parameter_selector": True})
        selector.bl_idname = ("ShaderNodeValue" if tree_type == "ShaderNodeTree"
                              else "ShaderNodeMath")
        selector.operation = "ADD"
        selector.outputs = {"Value": SimpleNamespace(default_value=float(active))}
        selector.inputs = {
            0: SimpleNamespace(default_value=float(active), is_linked=False),
            1: SimpleNamespace(default_value=0.0, is_linked=False),
            "Switch": SimpleNamespace(default_value=bool(active)),
        }
        self.nodes = [selector]
        for bank, image in enumerate(banks):
            reader = Node({
                "_perceptual_grade_parameter_reader": True,
                "_perceptual_grade_parameter_reader_bank": bank,
            })
            reader.image = image
            self.nodes.append(reader)


class Node(dict):
    pass


class BankedResourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix="grade-banked-resources-")
        root = Path(cls.directory.name)
        package = root / "grade_banked_resources_test"
        package.mkdir()
        with zipfile.ZipFile(files("tests.perceptual_grade_blender") / "extension.zip") as archive:
            archive.extractall(package)
        sys.path.insert(0, str(root))
        cls.module = importlib.import_module(
            "grade_banked_resources_test.runtime.grade_resources"
        )
        cls.stage2 = importlib.import_module(
            "grade_banked_resources_test.kernel.stage2_graph"
        )
        cls.schema = importlib.import_module(
            "grade_banked_resources_test.kernel.stage2_parameters"
        ).PARAMETER_SCHEMA
        stage2_parameters = importlib.import_module(
            "grade_banked_resources_test.kernel.stage2_parameters"
        )
        cls.content_key = stage2_parameters.PARAMETER_CONTENT_SIGNATURE
        cls.content_signature = staticmethod(stage2_parameters.parameter_content_signature)

    @classmethod
    def tearDownClass(cls):
        sys.path.remove(cls.directory.name)
        for name in tuple(sys.modules):
            if name == "grade_banked_resources_test" or name.startswith(
                    "grade_banked_resources_test."):
                del sys.modules[name]
        cls.directory.cleanup()

    def setUp(self):
        self.owner = SimpleNamespace(as_pointer=lambda: 31)
        self.node = SimpleNamespace(pg_grade=self.owner)
        self.first = Image(
            11, schema=self.schema, content_key=self.content_key,
            content_signature=self.content_signature, fill=0.,
        )
        self.second = Image(
            12, schema=self.schema, content_key=self.content_key,
            content_signature=self.content_signature, fill=1.,
        )
        self.shader = Tree("ShaderNodeTree", self.owner, (self.first, self.second))
        self.compositor = Tree("CompositorNodeTree", self.owner, (self.first, self.second))

        class Data:
            node_groups = [self.shader, self.compositor]

        self.cache = self.module.GradeResources(SimpleNamespace(data=Data()))
        self.quiescent = False
        self.cache.gate = SimpleNamespace(
            quiescent=lambda: self.quiescent,
            retirement_allowed=lambda: self.quiescent,
        )

    def test_load_adopts_same_banks_selector_and_generation_for_both_tree_types(self):
        resource = self.cache.resource(self.node, "linear")
        self.assertEqual(resource.banks, (self.first, self.second))
        self.assertEqual(resource.images, (self.first, self.second))
        self.assertIs(resource.image, self.first)
        self.assertEqual(resource.candidate_bank, 1)
        self.assertEqual(resource.generation, 1)
        self.assertEqual(set(resource.trees), {"ShaderNodeTree", "CompositorNodeTree"})

    def test_mismatched_kernel_selector_or_bank_pair_is_not_adopted(self):
        other = Image(
            13, schema=self.schema, content_key=self.content_key,
            content_signature=self.content_signature, fill=2.,
        )
        self.compositor[self.stage2.PARAMETER_BANK_BINDINGS[1]] = other
        self.compositor.nodes[2].image = other
        with self.assertRaisesRegex(RuntimeError, "disagree"):
            self.cache.resource(self.node, "linear")

    def test_fixed_bank_identity_and_generation_advance_only_after_selector_receipt(self):
        resource = self.cache.resource(self.node, "linear")
        next_generation = self.cache.next_generation(resource)
        self.assertEqual(next_generation, 2)
        self.cache.publish(resource, 1, next_generation)
        self.assertIs(resource.image, self.second)
        self.assertEqual(resource.candidate_bank, 0)
        self.assertEqual(resource.generation, 2)
        with self.assertRaisesRegex(RuntimeError, "fixed"):
            self.cache.set_banks(
                resource, (self.first, Image(
                    14, schema=self.schema, content_key=self.content_key,
                    content_signature=self.content_signature, fill=3.,
                )), 0, 2
            )

    def test_restore_reverts_selector_receipt_without_replacing_images(self):
        resource = self.cache.resource(self.node, "linear")
        self.cache.publish(resource, 1, self.cache.next_generation(resource))
        self.cache.restore(resource, 0, 1)
        self.assertEqual(resource.banks, (self.first, self.second))
        self.assertIs(resource.image, self.first)
        self.assertEqual(resource.generation, 1)

    def test_banks_stay_protected_while_any_tracked_kernel_exists(self):
        resource = self.cache.resource(self.node, "linear")
        self.assertTrue(self.cache.protected(self.first))
        self.assertTrue(self.cache.protected(self.second))
        self.quiescent = True
        removed = []
        self.assertEqual(self.cache.reclaim(resource, removed.append), ())
        self.assertEqual(removed, [])

    def test_orphan_banks_retire_only_when_quiescent_and_without_users(self):
        resource = self.cache.resource(self.node, "linear")
        resource.trees.clear()
        self.first.users = 1
        self.second.use_fake_user = True
        self.quiescent = True
        removed = []
        self.assertEqual(self.cache.reclaim(resource, removed.append), ())
        self.assertEqual(removed, [])

        self.first.users = 0
        self.second.use_fake_user = False

        def remove(image):
            removed.append(image)
            image.live = False

        self.assertEqual(self.cache.reclaim(resource, remove), ())
        self.assertEqual(removed, [self.first, self.second])
        self.assertIsNone(resource.banks)
        self.assertFalse(self.cache.protected(self.first))
        self.assertFalse(self.cache.protected(self.second))

    def test_reclaim_accepts_removed_native_wrappers(self):
        resource = self.cache.resource(self.node, "linear")
        resource.trees.clear()
        self.quiescent = True
        for image in resource.banks:
            image.raise_when_removed = True

        def remove(image):
            image.live = False

        self.assertEqual(self.cache.reclaim(resource, remove), ())
        self.assertIsNone(resource.banks)

    def test_clear_requires_quiescence_and_generation_serial_survives_reset(self):
        resource = self.cache.resource(self.node, "linear")
        self.assertEqual(self.cache.next_generation(resource), 2)
        with self.assertRaises(self.module.PublicationDeferred):
            self.cache.clear()
        self.quiescent = True
        self.cache.clear()
        replacement = self.module.GradeResource()
        self.assertEqual(self.cache.next_generation(replacement), 3)


if __name__ == "__main__":
    unittest.main()
