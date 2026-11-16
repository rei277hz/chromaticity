"""Cheap persisted Bake receipts and runtime source generations."""

import importlib
from importlib.resources import files
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
import zipfile


class Image:
    def __init__(self, session_uid, *, is_dirty=False):
        self.session_uid = session_uid
        self.is_dirty = is_dirty

    @property
    def pixels(self):
        raise AssertionError("Freshness read Image pixels")


class Mesh:
    def __init__(self, session_uid):
        self.session_uid = session_uid


class BakeFreshnessTests(unittest.TestCase):
    def test_retiring_last_reader_cannot_revalidate_an_old_request(self):
        tracker = self.module.BakeSources()
        image = SimpleNamespace(session_uid=77, is_dirty=True)
        captured = tracker.bind(1, (image,))
        tracker.invalidate((image,))
        tracker.forget(1)
        self.assertFalse(tracker.matches(captured))

    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix="grade-bake-freshness-")
        package = Path(cls.directory.name) / "bake_freshness_test"
        package.mkdir()
        with zipfile.ZipFile(files("tests.perceptual_grade_blender") / "extension.zip") as archive:
            archive.extractall(package)
        sys.path.insert(0, cls.directory.name)
        cls.module = importlib.import_module("bake_freshness_test.runtime.bake_freshness")

    @classmethod
    def tearDownClass(cls):
        sys.path.remove(cls.directory.name)
        for name in tuple(sys.modules):
            if name == "bake_freshness_test" or name.startswith("bake_freshness_test."):
                del sys.modules[name]
        cls.directory.cleanup()

    def setUp(self):
        self.sources = self.module.BakeSources()

    def test_receipt_roundtrip_is_strictly_versioned(self):
        receipt = self.module.BakeReceipt("stable-route-token")
        encoded = receipt.encode()
        self.assertEqual(json.loads(encoded), {
            "schema": self.module.RECEIPT_SCHEMA,
            "signature": "stable-route-token",
        })
        self.assertEqual(self.module.BakeReceipt.decode(encoded), receipt)

        invalid = (
            None, "", "not json", "[]", "{}",
            '{"schema":1}',
            '{"schema":1,"signature":""}',
            '{"schema":1,"signature":null}',
            '{"schema":true,"signature":"route"}',
            '{"schema":1.0,"signature":"route"}',
            '{"schema":"1","signature":"route"}',
            '{"schema":2,"signature":"route"}',
        )
        for value in invalid:
            with self.subTest(value=value):
                self.assertIsNone(self.module.BakeReceipt.decode(value))

    def test_unbound_node_has_no_bake_receipt(self):
        self.assertIsNone(self.module.BakeReceipt.decode(None))
        self.assertFalse(self.sources.changed(1, (Image(1),)))

    def test_only_referenced_ids_advance_on_dependency_events(self):
        image = Image(1)
        mesh = Mesh(2)
        unrelated = Image(3)
        self.sources.bind(10, (image, mesh))
        baseline = self.sources.bindings[10]

        self.assertEqual(self.sources.invalidate((unrelated,)), set())
        self.assertTrue(self.sources.matches(baseline))
        self.assertEqual(self.sources.invalidate((image,)), {10})
        self.assertFalse(self.sources.matches(baseline))
        self.assertEqual(self.sources.generations[self.module.source_key(image)], 1)

    def test_duplicate_id_in_one_event_advances_once(self):
        image = Image(1)
        self.sources.bind(10, (image,))

        self.assertEqual(self.sources.invalidate((image, image, image)), {10})
        self.assertEqual(self.sources.generations[self.module.source_key(image)], 1)

    def test_evaluated_id_update_uses_the_original_source_identity(self):
        image = Image(1)
        evaluated = SimpleNamespace(original=image, session_uid=99)
        self.sources.bind(10, (image,))

        self.assertEqual(self.sources.invalidate((evaluated, image)), {10})
        self.assertEqual(self.sources.generations[self.module.source_key(image)], 1)

    def test_clean_to_dirty_transition_invalidates_a_bound_snapshot(self):
        image = Image(1, is_dirty=False)
        baseline = self.sources.bind(10, (image,))
        image.is_dirty = True

        self.assertTrue(self.sources.changed(10, (image,)))
        self.assertTrue(self.sources.matches(baseline))

    def test_dependency_event_invalidates_even_when_source_was_already_dirty(self):
        image = Image(1, is_dirty=True)
        baseline = self.sources.bind(10, (image,))
        self.assertFalse(self.sources.changed(10, (image,)))

        affected = self.sources.invalidate((image,))
        self.assertEqual(affected, {10})
        self.assertTrue(self.sources.changed(10, (image,)))
        self.assertFalse(self.sources.matches(baseline))

    def test_sources_remain_indexed_for_a_node_while_bake_is_off(self):
        image = Image(1)
        self.sources.bind("inactive-node", (image,))

        self.assertIn("inactive-node", self.sources.readers[self.module.source_key(image)])
        self.assertEqual(self.sources.invalidate((image,)), {"inactive-node"})

    def test_forgetting_one_shared_reader_preserves_the_shared_generation(self):
        image = Image(1)
        self.sources.bind("first", (image,))
        self.sources.bind("second", (image,))
        self.assertEqual(self.sources.invalidate((image,)), {"first", "second"})
        key = self.module.source_key(image)
        self.assertEqual(self.sources.generations[key], 1)

        self.sources.forget("first")
        self.assertEqual(self.sources.generations[key], 1)
        self.assertEqual(self.sources.readers[key], {"second"})
        self.assertTrue(self.sources.changed("second", (image,)))

    def test_rebinding_an_existing_source_does_not_reset_its_generation(self):
        image = Image(1)
        self.sources.bind("node", (image,))
        self.sources.invalidate((image,))
        key = self.module.source_key(image)

        rebound = self.sources.bind("node", (image, image))
        self.assertEqual(self.sources.generations[key], 1)
        self.assertEqual(rebound, ((key, 1, False),))
        self.assertTrue(self.sources.matches(rebound))
        self.assertFalse(self.sources.changed("node", (image,)))

    def test_clear_then_restore_establishes_a_fresh_runtime_baseline(self):
        image = Image(1, is_dirty=True)
        self.sources.bind("node", (image,))
        self.sources.invalidate((image,))
        self.assertTrue(self.sources.changed("node", (image,)))

        self.sources.clear()
        self.assertEqual(self.sources.generations, {})
        self.assertEqual(self.sources.bindings, {})
        self.assertEqual(self.sources.readers, {})
        restored = self.sources.bind("node", (image,))

        self.assertTrue(self.sources.matches(restored))
        self.assertFalse(self.sources.changed("node", (image,)))
        self.assertEqual(restored, ((self.module.source_key(image), 0, True),))


if __name__ == "__main__":
    unittest.main()
