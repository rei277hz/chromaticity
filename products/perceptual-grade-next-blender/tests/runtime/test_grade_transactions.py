"""Policy consumers exercise native-like failures without importing Blender."""

import importlib
from importlib.resources import files
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile

import numpy as np


class Pixels:
    def __init__(self, values):
        self.values = np.asarray(values, dtype=np.float32)

    def __len__(self):
        return len(self.values)

    def foreach_get(self, target):
        target[:] = self.values

    def foreach_set(self, values):
        self.values[:] = values


class Image(dict):
    def __init__(self):
        super().__init__(signature="old")
        self.pixels = Pixels((0.1, 0.2, 0.3, 1.0))
        self.packed_file = object()
        self.is_dirty = False
        self.tags = []
        self.tag_error = None

    def update(self):
        self.is_dirty = True

    def pack(self):
        self.is_dirty = False
        self.packed_file = object()

    def update_tag(self):
        self.tags.append((self.get("signature"), self.is_dirty))
        if self.tag_error is not None:
            raise self.tag_error


class Metadata(dict):
    fail_key = None

    def __setitem__(self, key, value):
        if self.fail_key == key:
            self.fail_key = None
            raise RuntimeError("second tree metadata failed")
        super().__setitem__(key, value)


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

    def retirement(self, *, failure=None, fresh_users=0, invalid=False, disposal=False):
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
                            "users": fresh_users if name == "recheck" else 0}
                if name == "evict":
                    cache.clear()
                if name == "remove":
                    self.assertFalse(cache)
                    removed.append("tree")
            return invoke

        errors = self.resources.run_resource_lifecycle(
            {name: operation(name) for name in
             ("fence", "detach", "observe", "evict", "recheck", "remove")},
            disposal=disposal,
        )
        return calls, cache, removed, errors

    def test_resource_consumer_cannot_remove_before_cache_eviction(self):
        calls, cache, removed, errors = self.retirement(disposal=True)
        self.assertEqual(calls, ["fence", "detach", "observe", "evict", "recheck", "remove"])
        self.assertFalse(cache)
        self.assertEqual(removed, ["tree"])
        self.assertEqual(errors, ())

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
        image, other, spare = object(), object(), object()
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

    def publish(self, *, failure=None, rollback_failure=None, matching=False,
                clean=True, second_tree_failure=False, silent_pack=False,
                tag_failure=False):
        image = Image()
        image.is_dirty = not clean
        if tag_failure:
            image.tag_error = RuntimeError("image invalidation failed")
        old_pixels = image.pixels.values.copy()
        trees = [Metadata(kernel="old-shader"), Metadata(kernel="old-compositor")]
        if second_tree_failure:
            trees[1].fail_key = "kernel"
        if matching:
            image["signature"] = "new"
        metadata = ((image, "signature", "new"),
                    (trees[0], "kernel", "new-shader"), (trees[0], "signature", "new"),
                    (trees[1], "kernel", "new-compositor"), (trees[1], "signature", "new"))
        calls, failed_users, delivered = [], [], []
        snapshots = []

        def snapshot():
            snapshots.append(self.publication.ImageSnapshot.capture(image, metadata))
            return {"matching": matching, "clean": not image.is_dirty}

        def upload():
            image.pixels.foreach_set((0.9, 0.8, 0.7, 1.0))
            image.update()

        def restore_upload():
            image.pixels.foreach_set(snapshots[0].pixels)
            image.update()

        def pack():
            image.pack()
            return {"clean": not image.is_dirty}

        def deliver():
            image.update_tag()
            self.assertEqual(image.tags, [("new", False)])
            self.assertEqual(trees[1]["kernel"], "new-compositor")
            delivered.append("authorized")

        def operation(name, function):
            def invoke(errors):
                calls.append(name)
                if name in (failure, rollback_failure):
                    if name == "upload":
                        upload()  # A native write may fail after changing bytes.
                    raise RuntimeError(name + " failed")
                if name == "pack" and silent_pack:
                    return {"clean": False}
                if name == "fail":
                    self.assertTrue(errors)
                return function()
            return invoke

        callbacks = {
            "prepare": lambda: None, "snapshot": snapshot, "upload": upload, "pack": pack,
            "commit": lambda: self.publication.write_metadata(metadata),
            "restore_upload": restore_upload, "restore_pack": pack,
            "restore_metadata": lambda: self.publication.write_metadata(snapshots[0].metadata),
            "deliver": deliver,
            "fail": lambda: failed_users.extend(("authorized", "shared", "lagging")),
            "retire": lambda: None,
        }
        errors = self.publication.run_image_publication(
            {name: operation(name, function) for name, function in callbacks.items()})
        return calls, image, old_pixels, trees, failed_users, delivered, errors

    def test_publication_consumer_commits_only_after_clean_packing(self):
        calls, image, _old, trees, failed, delivered, errors = self.publish()
        self.assertEqual(calls, ["prepare", "snapshot", "upload", "pack", "commit", "deliver", "retire"])
        self.assertFalse(image.is_dirty)
        self.assertEqual(image["signature"], "new")
        self.assertEqual(trees[1]["kernel"], "new-compositor")
        self.assertFalse(failed)
        self.assertTrue(delivered)
        self.assertFalse(errors)
        self.assertEqual(image.tags, [("new", False)])

    def test_image_invalidation_failure_fails_source_without_delivery_receipt(self):
        calls, image, _old, _trees, failed, delivered, errors = self.publish(tag_failure=True)
        self.assertEqual(calls, ["prepare", "snapshot", "upload", "pack", "commit",
                                 "deliver", "fail", "retire"])
        self.assertEqual(image.tags, [("new", False)])
        self.assertFalse(delivered)
        self.assertEqual(failed, ["authorized", "shared", "lagging"])
        self.assertEqual([str(error) for error in errors], ["image invalidation failed"])

    def test_clean_matching_fast_path_skips_upload_and_pack(self):
        calls, _image, _old, _trees, _failed, delivered, errors = self.publish(matching=True)
        self.assertEqual(calls, ["prepare", "snapshot", "commit", "deliver", "retire"])
        self.assertTrue(delivered)
        self.assertFalse(errors)
        dirty = self.publish(matching=True, clean=False)
        self.assertIn("upload", dirty[0])
        self.assertIn("pack", dirty[0])

    def test_mutation_failures_restore_image_and_fail_all_source_users(self):
        for failure in ("upload", "pack", "commit"):
            with self.subTest(failure=failure):
                calls, image, old, trees, failed, delivered, errors = self.publish(failure=failure)
                np.testing.assert_array_equal(image.pixels.values, old)
                self.assertEqual(image["signature"], "old")
                self.assertEqual(trees, [{"kernel": "old-shader"}, {"kernel": "old-compositor"}])
                self.assertFalse(image.is_dirty)
                self.assertEqual(failed, ["authorized", "shared", "lagging"])
                self.assertFalse(delivered)
                self.assertEqual(str(errors[0]), failure + " failed")
                self.assertEqual(calls[-5:], ["restore_upload", "restore_pack", "restore_metadata", "fail", "retire"])

    def test_second_tree_metadata_failure_restores_partial_commit(self):
        calls, image, old, trees, failed, delivered, errors = self.publish(second_tree_failure=True)
        np.testing.assert_array_equal(image.pixels.values, old)
        self.assertEqual(image["signature"], "old")
        self.assertEqual(trees, [{"kernel": "old-shader"}, {"kernel": "old-compositor"}])
        self.assertFalse(image.is_dirty)
        self.assertEqual(str(errors[0]), "second tree metadata failed")
        self.assertEqual(failed, ["authorized", "shared", "lagging"])
        self.assertFalse(delivered)
        self.assertEqual(calls[-1], "retire")

    def test_failed_restoration_preserves_error_and_still_fails_source(self):
        for rollback in ("restore_upload", "restore_pack", "restore_metadata"):
            with self.subTest(rollback=rollback):
                calls, _image, _old, _trees, failed, delivered, errors = self.publish(
                    failure="upload", rollback_failure=rollback)
                self.assertEqual([str(error) for error in errors], ["upload failed", rollback + " failed"])
                self.assertEqual(failed, ["authorized", "shared", "lagging"])
                self.assertFalse(delivered)
                self.assertEqual(calls[-2:], ["fail", "retire"])
                if rollback != "restore_metadata":
                    self.assertNotIn("restore_metadata", calls)

    def test_silent_pack_failure_restores_and_fails_without_commit(self):
        calls, image, old, _trees, failed, delivered, errors = self.publish(silent_pack=True)
        self.assertNotIn("commit", calls)
        self.assertFalse(delivered)
        self.assertTrue(failed)
        self.assertIn("could not be packed", str(errors[0]))
        np.testing.assert_array_equal(image.pixels.values, old)
        self.assertFalse(image.is_dirty)

    def test_preparation_snapshot_and_failure_handler_failures_still_retire(self):
        for failure in ("prepare", "snapshot"):
            calls, _image, _old, _trees, failed, delivered, errors = self.publish(failure=failure)
            self.assertNotIn("upload", calls)
            self.assertNotIn("restore_upload", calls)
            self.assertTrue(failed)
            self.assertFalse(delivered)
            self.assertEqual(str(errors[0]), failure + " failed")
        calls, _image, _old, _trees, _failed, _delivered, errors = self.publish(
            failure="upload", rollback_failure="fail")
        self.assertEqual(calls[-1], "retire")
        self.assertEqual([str(error) for error in errors], ["upload failed", "fail failed"])

    def test_retirement_failure_is_returned_after_success_or_prior_failure(self):
        success = self.publish(failure="retire")
        self.assertTrue(success[5])
        self.assertEqual([str(error) for error in success[6]], ["retire failed"])
        failed = self.publish(failure="upload", rollback_failure="retire")
        self.assertFalse(failed[5])
        self.assertEqual(failed[4], ["authorized", "shared", "lagging"])
        self.assertEqual([str(error) for error in failed[6]], ["upload failed", "retire failed"])


if __name__ == "__main__":
    unittest.main()
