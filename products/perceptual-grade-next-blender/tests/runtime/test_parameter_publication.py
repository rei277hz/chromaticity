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
    def __init__(self, values, shape):
        self.values = np.asarray(values, dtype=np.float32).reshape(shape)

    def foreach_get(self, output):
        output[:] = self.values.ravel()

    def foreach_set(self, values):
        self.values = np.asarray(values, dtype=np.float32).reshape(self.values.shape).copy()


class Image(dict):
    def __init__(self, pointer, *, schema, content_key, content_signature,
                 role_key, role, shape, users=0, fake=False, fill=0.):
        super().__init__()
        self.pointer = pointer
        self.size = (shape[1], shape[0])
        self.users = users
        self.use_fake_user = fake
        self.live = True
        self.raise_when_removed = False
        self.is_dirty = False
        self.packed_file = object()
        pixels = np.full(shape, fill, dtype=np.float32)
        self.pixels = PixelBuffer(pixels, shape)
        self["_perceptual_grade_parameter_schema"] = schema
        self[content_key] = content_signature(self.pixels.values)
        self[role_key] = role

    def as_pointer(self):
        if not self.live and self.raise_when_removed:
            raise ReferenceError("removed image wrapper")
        return self.pointer if self.live else 0

    def get(self, *args):
        if not self.live and self.raise_when_removed:
            raise ReferenceError("removed image wrapper")
        return super().get(*args)

    def __eq__(self, other):
        return self is other

    __hash__ = object.__hash__


class Tree(dict):
    def __init__(self, tree_type, owner, banks, active=0, generation=1,
                 roles=(), bank_images=None):
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
        for bank, _primary in enumerate(banks):
            images = bank_images[bank]
            for role in roles:
                reader = Node({
                    "_perceptual_grade_parameter_reader": True,
                    "_perceptual_grade_parameter_reader_bank": bank,
                    "_perceptual_grade_parameter_reader_role": role,
                })
                reader.image = images[role]
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
            "grade_banked_resources_test.kernel.stage2_bindings"
        )
        cls.schema = importlib.import_module(
            "grade_banked_resources_test.kernel.stage2_parameters"
        )
        cls.parameter_roles = cls.schema.PARAMETER_ROLES
        cls.role_shapes = cls.schema.PARAMETER_ROLE_SHAPES
        cls.role_binding = cls.stage2.PARAMETER_ROLE_BINDING
        stage2_parameters = importlib.import_module(
            "grade_banked_resources_test.kernel.stage2_parameters"
        )
        cls.content_key = stage2_parameters.PARAMETER_CONTENT_SIGNATURE
        cls.content_signature = staticmethod(stage2_parameters.parameter_content_signature)
        cls.bind_parameter_bank = staticmethod(stage2_parameters.bind_parameter_bank)

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
        self.first, self.first_images = self._make_bank(11, 0.)
        self.second, self.second_images = self._make_bank(21, 1.)
        self.banks = (self.first, self.second)
        self.bank_images = (self.first_images, self.second_images)
        self.alternate, self.alternate_images = self._make_bank(31, 2.)
        self.shader = Tree("ShaderNodeTree", self.owner, self.banks,
                           roles=self.parameter_roles,
                           bank_images=self.bank_images)
        self.compositor = Tree("CompositorNodeTree", self.owner, self.banks,
                               roles=self.parameter_roles,
                               bank_images=self.bank_images)

        class Data:
            node_groups = [self.shader, self.compositor]

        self.cache = self.module.GradeResources(SimpleNamespace(data=Data()))
        self.quiescent = False
        self.cache.gate = SimpleNamespace(
            quiescent=lambda: self.quiescent,
            retirement_allowed=lambda: self.quiescent,
        )

    def _make_bank(self, pointer, fill):
        images = {
            role: Image(
                pointer + index, schema=self.schema.PARAMETER_SCHEMA,
                content_key=self.content_key, content_signature=self.content_signature,
                role_key=self.stage2.PARAMETER_ROLE, role=role,
                shape=self.role_shapes[role], fill=fill,
            )
            for index, role in enumerate(self.parameter_roles)
        }
        primary = self.bind_parameter_bank(images, {
            role: image[self.content_key] for role, image in images.items()
        })
        return primary, images

    def test_load_adopts_same_banks_selector_and_generation_for_both_tree_types(self):
        resource = self.cache.resource(self.node, "linear")
        self.assertEqual(resource.banks, self.banks)
        self.assertEqual(resource.images, tuple(
            image for bank in self.bank_images for image in bank.values()))
        self.assertIs(resource.image, self.first)
        self.assertEqual(resource.candidate_bank, 1)
        self.assertEqual(resource.generation, 1)
        self.assertEqual(set(resource.trees), {"ShaderNodeTree", "CompositorNodeTree"})

    def test_mismatched_kernel_selector_or_bank_pair_is_not_adopted(self):
        other = self.alternate
        self.compositor[self.stage2.PARAMETER_BANK_BINDINGS[1]] = other
        for reader in self.compositor.nodes:
            if (reader.get(self.stage2.PARAMETER_READER_BANK) == 1):
                role = reader.get(self.stage2.PARAMETER_READER_ROLE)
                reader.image = self.alternate_images[role]
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
                resource, (self.first, self.alternate), 0, 2
            )

    def test_restore_reverts_selector_receipt_without_replacing_images(self):
        resource = self.cache.resource(self.node, "linear")
        self.cache.publish(resource, 1, self.cache.next_generation(resource))
        self.cache.restore(resource, 0, 1)
        self.assertEqual(resource.banks, self.banks)
        self.assertIs(resource.image, self.first)
        self.assertEqual(resource.generation, 1)

    def test_missing_or_mixed_role_bundle_is_not_adopted(self):
        role = self.parameter_roles[-1]
        self.first[self.role_binding + role] = None
        resource = self.cache.resource(self.node, "linear")
        self.assertIsNone(resource.banks)
        self.first[self.role_binding + role] = self.first_images[role]
        for tree in (self.shader, self.compositor):
            reader = next(item for item in tree.nodes
                          if item.get(self.stage2.PARAMETER_READER_BANK) == 0
                          and item.get(self.stage2.PARAMETER_READER_ROLE) == role)
            reader.image = self.second_images[role]
        self.assertIsNone(self.cache.resource(self.node, "linear").banks)

    def test_mixed_generation_bundle_receipt_is_not_adopted(self):
        role_image = self.first_images[self.parameter_roles[-1]]
        role_image[self.schema.PARAMETER_BUNDLE_SIGNATURE] = "0" * 64
        self.assertFalse(self.module.GradeResources._valid_bundle(self.first))
        self.assertIsNone(self.cache.resource(self.node, "linear").banks)

    def test_bank_pair_rejects_shared_role_image(self):
        role = self.parameter_roles[-1]
        self.second[self.role_binding + role] = self.first_images[role]
        with self.assertRaisesRegex(ValueError, "two valid banks"):
            self.cache.set_banks(self.module.GradeResource(), self.banks, 0, 0)

    def test_retirement_retries_preserve_role_identities_after_primary_removal(self):
        resource = self.cache.resource(self.node, "linear")
        resource.trees.clear()
        self.quiescent = True
        delayed = self.first_images[self.parameter_roles[-1]]
        delayed.users = 1

        def remove(image):
            image.live = False
            image.raise_when_removed = True

        self.assertEqual(self.cache.reclaim(resource, remove), ())
        self.assertTrue(delayed.live)
        self.assertIsNotNone(resource.banks)
        delayed.users = 0
        self.assertEqual(self.cache.reclaim(resource, remove), ())
        self.assertFalse(delayed.live)
        self.assertIsNone(resource.banks)

    def test_banks_stay_protected_while_any_tracked_kernel_exists(self):
        resource = self.cache.resource(self.node, "linear")
        self.assertTrue(all(self.cache.protected(image)
                            for bank in self.bank_images for image in bank.values()))
        self.quiescent = True
        removed = []
        self.assertEqual(self.cache.reclaim(resource, removed.append), ())
        self.assertEqual(removed, [])

    def test_orphan_banks_retire_only_when_quiescent_and_without_users(self):
        resource = self.cache.resource(self.node, "linear")
        resource.trees.clear()
        for image in resource.images:
            image.users = 1
        self.second.use_fake_user = True
        self.quiescent = True
        removed = []
        self.assertEqual(self.cache.reclaim(resource, removed.append), ())
        self.assertEqual(removed, [])

        for image in resource.images:
            image.users = 0
        self.second.use_fake_user = False

        def remove(image):
            removed.append(image)
            image.live = False

        self.assertEqual(self.cache.reclaim(resource, remove), ())
        self.assertEqual(set(removed), {
            image for bank in self.bank_images for image in bank.values()
        })
        self.assertIsNone(resource.banks)
        self.assertFalse(any(self.cache.protected(image)
                             for bank in self.bank_images for image in bank.values()))

    def test_reclaim_accepts_removed_native_wrappers(self):
        resource = self.cache.resource(self.node, "linear")
        resource.trees.clear()
        self.quiescent = True
        for image in resource.images:
            image.raise_when_removed = True

        def remove(image):
            image.live = False

        self.assertEqual(self.cache.reclaim(resource, remove), ())
        self.assertIsNone(resource.banks)

    def test_external_primary_removal_does_not_poison_other_image_retirement(self):
        resource = self.cache.resource(self.node, "linear")
        self.first.live = False
        self.first.raise_when_removed = True
        self.assertEqual(resource.images, (self.first, *self.second_images.values()))
        self.assertTrue(self.cache.protected(self.second))
        self.assertFalse(self.cache.protected(self.alternate))
        self.assertIsNone(self.cache.resource(self.node, "linear").banks)

    def test_clear_requires_quiescence_and_generation_serial_survives_reset(self):
        resource = self.cache.resource(self.node, "linear")
        self.assertEqual(self.cache.next_generation(resource), 2)
        with self.assertRaises(self.module.PublicationDeferred):
            self.cache.clear()
        self.quiescent = True
        self.cache.clear()
        replacement = self.module.GradeResource()
        self.assertEqual(self.cache.next_generation(replacement), 3)

    def test_load_fences_resources_and_pins_all_roles_across_repeated_restores(self):
        original = self.cache.resource(self.node, "linear")
        self.cache.pending[object()] = object()
        self.cache.invalidate()
        self.assertFalse(self.cache.pending)
        self.assertTrue(all(self.cache.protected(image) for image in original.images))
        restored = self.cache.resource(self.node, "linear")
        self.assertIsNot(original, restored)
        self.assertEqual(original.images, restored.images)
        self.cache.invalidate()

        # An exclusive preflight may retire ordinary banks, but shared image
        # identities from the old lifecycle stay pinned until actual quiescence.
        self.cache.gate.retirement_allowed = lambda: True
        current = self.cache.resource(self.node, "linear")
        current.trees.clear()
        removed = []
        self.assertEqual(self.cache.reclaim(current, removed.append), ())
        self.assertFalse(removed)
        with self.assertRaises(self.module.PublicationDeferred):
            self.cache.release_lifecycle_images()
        self.quiescent = True
        self.cache.release_lifecycle_images()
        self.assertIs(current, self.cache.resource(self.node, "linear"))
        self.assertTrue(all(self.cache.protected(image) for image in current.images))


if __name__ == "__main__":
    unittest.main()
