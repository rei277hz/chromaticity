"""Policy consumers exercise native-like failures without importing Blender."""

import importlib
from importlib.resources import files
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
import zipfile

class Image:
    def __init__(self):
        self.packed_file = object()
        self.is_dirty = False

    def pack(self):
        self.is_dirty = False
        self.packed_file = object()


class GradeTransactionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix="grade-transactions-")
        root = Path(cls.directory.name)
        package = root / "grade_transaction_test"
        package.mkdir()
        with zipfile.ZipFile(files("tests.perceptual_grade_blender") / "extension.zip") as archive:
            archive.extractall(package)
        sys.path.insert(0, str(root))
        cls.resources = importlib.import_module("grade_transaction_test.runtime.resource_lifecycle")
        cls.publication = importlib.import_module("grade_transaction_test.runtime.image_publication")
        cls.cache = importlib.import_module("grade_transaction_test.runtime.grade_resources")

    @classmethod
    def tearDownClass(cls):
        sys.path.remove(cls.directory.name)
        for name in tuple(sys.modules):
            if name == "grade_transaction_test" or name.startswith("grade_transaction_test."):
                del sys.modules[name]
        cls.directory.cleanup()

    def retirement(self, *, failure=None, fresh_users=0, invalid=False, disposal=False,
                   retain_for_undo=False):
        calls = []
        cache = {"tree"}
        removed = []

        def operation(name):
            def invoke():
                calls.append(name)
                if name == failure:
                    raise RuntimeError(name + " failed")
                if name in ("observe", "recheck"):
                    return {"live": not invalid, "owned": True,
                            "users": fresh_users if name == "recheck" else 0,
                            "retain_for_undo": retain_for_undo}
                if name == "evict":
                    cache.clear()
                if name == "remove":
                    self.assertFalse(cache)
                    removed.append("tree")
            return invoke

        errors = self.resources.run_resource_lifecycle(
            {name: operation(name) for name in
             ("fence", "detach", "observe", "retain", "evict", "recheck", "remove")},
            disposal=disposal,
        )
        return calls, cache, removed, errors

    def test_resource_consumer_cannot_remove_before_cache_eviction(self):
        calls, cache, removed, errors = self.retirement(disposal=True)
        self.assertEqual(calls, ["fence", "detach", "observe", "evict", "recheck", "remove"])
        self.assertFalse(cache)
        self.assertEqual(removed, ["tree"])
        self.assertEqual(errors, ())

    def test_undo_retention_never_evicts_or_removes_even_when_retention_fails(self):
        for failure in (None, "retain"):
            with self.subTest(failure=failure):
                calls, cache, removed, errors = self.retirement(
                    retain_for_undo=True, failure=failure)
                self.assertEqual(calls, ["observe", "retain"])
                self.assertEqual(cache, {"tree"})
                self.assertFalse(removed)
                self.assertEqual(tuple(map(str, errors)),
                                 ("retain failed",) if failure else ())

    def test_resource_failure_and_late_survivor_retain_native_resource(self):
        for failure in ("fence", "evict", "recheck"):
            with self.subTest(failure=failure):
                calls, _cache, removed, errors = self.retirement(failure=failure, disposal=True)
                self.assertFalse(removed)
                self.assertEqual(str(errors[0]), failure + " failed")
                if failure == "fence":
                    self.assertEqual(calls, ["fence"])
        _calls, cache, removed, errors = self.retirement(fresh_users=1)
        self.assertFalse(cache)
        self.assertFalse(removed)
        self.assertFalse(errors)

    def test_partial_detach_and_failed_remove_keep_first_error_and_evicted_cache(self):
        calls, cache, removed, errors = self.retirement(failure="detach", disposal=True)
        self.assertEqual(str(errors[0]), "detach failed")
        self.assertEqual(calls[-1], "remove")
        self.assertFalse(cache)
        self.assertTrue(removed)
        _calls, cache, removed, errors = self.retirement(failure="remove")
        self.assertFalse(cache)
        self.assertFalse(removed)
        self.assertEqual(str(errors[0]), "remove failed")

    def test_removed_wrapper_evicts_without_native_removal(self):
        calls, cache, removed, errors = self.retirement(invalid=True)
        self.assertEqual(calls, ["observe", "evict", "recheck"])
        self.assertFalse(cache)
        self.assertFalse(removed)
        self.assertFalse(errors)

    def test_image_eviction_removes_every_dependent_cache_entry(self):
        cache = self.cache.GradeResources(None)

        def bank():
            primary = SimpleNamespace()
            roles = {
                "_perceptual_grade_parameter_role_" + role: SimpleNamespace()
                for role in ("web", "web_toe", "adaptance")
            }
            primary.get = roles.get
            return primary

        image, other, spare = bank(), bank(), bank()
        first = self.cache.GradeResource(
            banks=(image, other), active_bank=0, generation=1,
            trees={"shader": object()})
        second = self.cache.GradeResource(
            banks=(spare, image), active_bank=1, generation=2,
            trees={"compositor": object()})
        survivor = self.cache.GradeResource(
            banks=(other, spare), active_bank=0, generation=3,
            trees={"shader": object()})
        cache._resources = {1: first, 2: second, 3: survivor}
        cache.retire_image(image)
        self.assertIsNone(first.image)
        self.assertIsNone(second.image)
        self.assertIsNone(first.banks)
        self.assertIsNone(second.banks)
        self.assertFalse(first.trees)
        self.assertFalse(second.trees)
        self.assertIs(survivor.image, other)
        self.assertTrue(survivor.trees)

    def test_save_fallback_preserves_dirty_user_images_and_skips_clean_images(self):
        calls = []
        image = Image()
        image.is_dirty = True
        self.publication.pack_image_for_save(image, generated=False, pack=calls.append)
        self.assertTrue(image.is_dirty)
        self.assertEqual(calls, [])
        image.is_dirty = False
        self.publication.pack_image_for_save(image, generated=True, pack=calls.append)
        self.assertEqual(calls, [])

    def test_save_fallback_checks_packing_receipts_and_preserves_native_error(self):
        image = Image()
        image.is_dirty = True
        self.publication.pack_image_for_save(image, generated=True, pack=lambda target: target.pack())
        self.assertFalse(image.is_dirty)
        image.is_dirty = True
        with self.assertRaisesRegex(RuntimeError, "could not be packed"):
            self.publication.pack_image_for_save(image, generated=True, pack=lambda target: None)
        failure = OSError("native pack failed")

        def fail(_image):
            raise failure

        with self.assertRaises(OSError) as raised:
            self.publication.pack_image_for_save(image, generated=True, pack=fail)
        self.assertIs(raised.exception, failure)

    def test_save_fallback_rejects_clean_image_without_packed_file(self):
        image = Image()
        image.is_dirty = True
        image.packed_file = None

        def clear_dirty_only(target):
            target.is_dirty = False

        with self.assertRaisesRegex(RuntimeError, "could not be packed"):
            self.publication.pack_image_for_save(image, generated=True, pack=clear_dirty_only)


if __name__ == "__main__":
    unittest.main()
