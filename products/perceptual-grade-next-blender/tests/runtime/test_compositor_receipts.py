import importlib
from importlib.resources import files
from pathlib import Path
import sys
import tempfile
import unittest
from types import SimpleNamespace
import zipfile


class CompositorReceiptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix="grade-compositor-receipts-")
        root = Path(cls.directory.name)
        package = root / "grade_compositor_receipts_test"
        package.mkdir()
        resource = files("tests.perceptual_grade_blender") / "extension.zip"
        with zipfile.ZipFile(resource) as archive:
            archive.extractall(package)
        sys.path.insert(0, str(root))
        cls.module = importlib.import_module(
            "grade_compositor_receipts_test.runtime.compositor_receipts")

    @classmethod
    def tearDownClass(cls):
        sys.path.remove(cls.directory.name)
        for name in tuple(sys.modules):
            if (name == "grade_compositor_receipts_test"
                    or name.startswith("grade_compositor_receipts_test.")):
                del sys.modules[name]
        cls.directory.cleanup()

    def receipt(self, scene, epoch, snapshot, successful=True):
        return SimpleNamespace(identity=scene, epoch=epoch,
                               snapshot=tuple(snapshot.items()), successful=successful)

    def test_completion_does_not_claim_a_newer_binding_is_displayed(self):
        receipts = self.module.CompositorReceipts()
        receipts.bind({7: (17,)}, 1)
        first = receipts.snapshot(7)
        receipts.bind({7: (17,)}, 2)
        self.assertEqual(first, {17: 1})
        receipts.completed(self.receipt(7, 11, first))
        receipts.collect()
        self.assertTrue(receipts.awaiting(17, (7,)))
        receipts.completed(self.receipt(7, 12, receipts.snapshot(7)))
        self.assertTrue(receipts.awaiting(17, (7,)))
        receipts.collect()
        self.assertFalse(receipts.awaiting(17, (7,)))

    def test_cancelled_and_unrelated_scene_receipts_cannot_clear_pending(self):
        receipts = self.module.CompositorReceipts()
        receipts.bind({7: (17,), 8: (17,)}, 1)
        receipts.completed(self.receipt(7, 11, {17: 1}, successful=False))
        receipts.completed(self.receipt(8, 12, {17: 1}))
        receipts.collect()
        self.assertTrue(receipts.awaiting(17, (7, 8)))
        self.assertFalse(receipts.awaiting(17, (8,)))
        self.assertFalse(receipts.awaiting(17, ()))

    def test_late_receipt_cannot_replace_a_more_recent_completed_snapshot(self):
        receipts = self.module.CompositorReceipts()
        receipts.bind({7: (17,)}, 2)
        receipts.completed(self.receipt(7, 12, {17: 2}))
        receipts.completed(self.receipt(7, 11, {17: 1}))
        receipts.collect()
        self.assertFalse(receipts.awaiting(17, (7,)))

    def test_every_visible_scene_must_cover_each_shared_node_binding(self):
        receipts = self.module.CompositorReceipts()
        receipts.bind({7: (17, 18), 8: (18,)}, 3)
        receipts.completed(self.receipt(7, 11, {17: 3, 18: 3}))
        receipts.completed(self.receipt(8, 12, {}))
        receipts.collect()
        self.assertFalse(receipts.awaiting(17, (7, 8)))
        self.assertTrue(receipts.awaiting(18, (7, 8)))

    def test_failed_publication_restores_prior_and_absent_binding_facts(self):
        receipts = self.module.CompositorReceipts()
        receipts.bind({7: (17,)}, 1)
        previous = receipts.bind({7: (17, 18), 8: (19,)}, 2)
        receipts.restore(previous)
        self.assertEqual(receipts.snapshot(7), {17: 1})
        self.assertEqual(receipts.snapshot(8), {})
        self.assertEqual(receipts.node_identities(), {17})

    def test_reset_drops_bindings_completed_and_queued_lifecycle_receipts(self):
        receipts = self.module.CompositorReceipts()
        receipts.bind({7: (17,)}, 1)
        receipts.completed(self.receipt(7, 11, {17: 1}))
        receipts.collect()
        receipts.completed(self.receipt(7, 12, {17: 2}))
        receipts.reset()
        receipts.bind({7: (17,)}, 2)
        receipts.collect()
        self.assertTrue(receipts.awaiting(17, (7,)))

    def test_disposed_node_pointer_cannot_reuse_a_completed_or_queued_receipt(self):
        receipts = self.module.CompositorReceipts()
        receipts.bind({7: (17, 18)}, 1)
        self.assertTrue(receipts.known(17))
        self.assertFalse(receipts.known(19))
        receipts.completed(self.receipt(7, 11, {17: 1, 18: 1}))
        receipts.collect()
        receipts.completed(self.receipt(7, 12, {17: 1, 18: 1}))
        receipts.forget(17)
        self.assertFalse(receipts.known(17))
        self.assertEqual(receipts.node_identities(), {18})
        receipts.bind({7: (17,)}, 1)
        receipts.collect()
        self.assertTrue(receipts.awaiting(17, (7,)))
        self.assertFalse(receipts.awaiting(18, (7,)))


if __name__ == "__main__":
    unittest.main()
