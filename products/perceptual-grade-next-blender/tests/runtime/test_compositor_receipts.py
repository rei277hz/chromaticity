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
            "grade_compositor_receipts_test.features.grade.compositor_receipts")

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
        receipts.bind({7: (17,)})
        first = receipts.snapshot(7)
        receipts.bind({7: (17,)})
        self.assertNotEqual(first, receipts.snapshot(7))
        receipts.completed(self.receipt(7, 11, first))
        receipts.collect()
        self.assertTrue(receipts.awaiting(17, (7,)))
        receipts.completed(self.receipt(7, 12, receipts.snapshot(7)))
        self.assertTrue(receipts.awaiting(17, (7,)))
        receipts.collect()
        self.assertFalse(receipts.awaiting(17, (7,)))

    def test_cancelled_and_unrelated_scene_receipts_cannot_clear_pending(self):
        receipts = self.module.CompositorReceipts()
        receipts.bind({7: (17,), 8: (17,)})
        receipts.completed(self.receipt(7, 11, receipts.snapshot(7), successful=False))
        receipts.completed(self.receipt(8, 12, receipts.snapshot(8)))
        receipts.collect()
        self.assertTrue(receipts.awaiting(17, (7, 8)))
        self.assertFalse(receipts.awaiting(17, (8,)))
        self.assertFalse(receipts.awaiting(17, ()))

    def test_late_receipt_cannot_replace_a_more_recent_completed_snapshot(self):
        receipts = self.module.CompositorReceipts()
        receipts.bind({7: (17,)})
        previous = receipts.snapshot(7)
        receipts.bind({7: (17,)})
        receipts.completed(self.receipt(7, 12, receipts.snapshot(7)))
        receipts.completed(self.receipt(7, 11, previous))
        receipts.collect()
        self.assertFalse(receipts.awaiting(17, (7,)))

    def test_every_visible_scene_must_cover_each_shared_node_binding(self):
        receipts = self.module.CompositorReceipts()
        receipts.bind({7: (17, 18), 8: (18,)})
        receipts.completed(self.receipt(7, 11, receipts.snapshot(7)))
        receipts.completed(self.receipt(8, 12, {}))
        receipts.collect()
        self.assertFalse(receipts.awaiting(17, (7,)))
        self.assertTrue(receipts.awaiting(17, (7, 8)))
        self.assertTrue(receipts.awaiting(18, (7, 8)))

    def test_reconcile_preserves_unchanged_bindings_and_undoes_only_membership_changes(self):
        receipts = self.module.CompositorReceipts()
        receipts.bind({7: (17,), 8: (18,)})
        first = receipts.snapshot(7)
        removed = receipts.snapshot(8)
        receipts.completed(self.receipt(7, 11, first))
        receipts.collect()

        effects = receipts.reconcile({7: (17,), 8: (17,)})
        self.assertEqual(effects.previous, {(8, 17): None, (8, 18): removed[18]})
        self.assertEqual(effects.reevaluate_scenes, {8})
        self.assertEqual(receipts.snapshot(7), first)
        self.assertNotEqual(receipts.snapshot(8), first)
        self.assertFalse(receipts.awaiting(17, (7,)))
        self.assertTrue(receipts.awaiting(17, (7, 8)))
        unchanged = receipts.reconcile({7: (17,), 8: (17,)})
        self.assertEqual(unchanged.reevaluate_scenes, set())
        self.assertEqual(unchanged.previous, {})
        receipts.restore(effects.previous)
        self.assertEqual(receipts.snapshot(7), first)
        self.assertEqual(receipts.snapshot(8), removed)

    def test_completions_from_detached_scene_cannot_acknowledge_reattachment(self):
        receipts = self.module.CompositorReceipts()
        receipts.reconcile({8: (17,)})
        attached = receipts.snapshot(8)
        receipts.completed(self.receipt(8, 11, attached))
        receipts.collect()
        self.assertFalse(receipts.awaiting(17, (8,)))
        receipts.reconcile({})
        self.assertEqual(receipts.snapshot(8), {})
        self.assertFalse(receipts.awaiting(17, ()))

        receipts.reconcile({8: (17,)})
        self.assertTrue(receipts.awaiting(17, (8,)))
        receipts.completed(self.receipt(8, 12, attached))
        receipts.collect()
        self.assertTrue(receipts.awaiting(17, (8,)))
        receipts.completed(self.receipt(8, 13, receipts.snapshot(8)))
        receipts.collect()
        self.assertFalse(receipts.awaiting(17, (8,)))

    def test_failed_publication_restores_prior_and_absent_binding_facts(self):
        receipts = self.module.CompositorReceipts()
        receipts.bind({7: (17,)})
        first = receipts.snapshot(7)
        previous = receipts.bind({7: (17, 18), 8: (19,)})
        failed = receipts.snapshot(7)
        receipts.restore(previous)
        self.assertEqual(receipts.snapshot(7), first)
        self.assertEqual(receipts.snapshot(8), {})
        self.assertEqual(receipts.node_identities(), {17})
        receipts.bind({7: (17,)})
        receipts.completed(self.receipt(7, 12, failed))
        receipts.collect()
        self.assertTrue(receipts.awaiting(17, (7,)))

    def test_reset_drops_bindings_completed_and_queued_lifecycle_receipts(self):
        receipts = self.module.CompositorReceipts()
        receipts.bind({7: (17,)})
        receipts.completed(self.receipt(7, 11, receipts.snapshot(7)))
        receipts.collect()
        receipts.bind({7: (17,)})
        previous = receipts.snapshot(7)
        receipts.completed(self.receipt(7, 12, previous))
        receipts.reset()
        receipts.bind({7: (17,)})
        receipts.collect()
        self.assertTrue(receipts.awaiting(17, (7,)))
        receipts.completed(self.receipt(7, 13, previous))
        receipts.collect()
        self.assertTrue(receipts.awaiting(17, (7,)))

    def test_disposed_node_pointer_cannot_reuse_a_completed_or_queued_receipt(self):
        receipts = self.module.CompositorReceipts()
        receipts.bind({7: (17, 18)})
        self.assertTrue(receipts.known(17))
        self.assertFalse(receipts.known(19))
        snapshot = receipts.snapshot(7)
        receipts.completed(self.receipt(7, 11, snapshot))
        receipts.collect()
        receipts.completed(self.receipt(7, 12, snapshot))
        receipts.forget(17)
        self.assertFalse(receipts.known(17))
        self.assertEqual(receipts.node_identities(), {18})
        receipts.bind({7: (17,)})
        receipts.collect()
        self.assertTrue(receipts.awaiting(17, (7,)))
        self.assertFalse(receipts.awaiting(18, (7,)))

    def test_baked_evaluation_cannot_acknowledge_restored_live_output(self):
        receipts = self.module.CompositorReceipts()
        receipts.bind({7: (17,)})
        live = receipts.snapshot(7)
        previous = receipts.bind({}, baked_nodes=(17,))
        self.assertEqual(receipts.snapshot(7), {})
        receipts.restore(previous)
        self.assertEqual(receipts.snapshot(7), live)
        receipts.bind({}, baked_nodes=(17,))
        baked = receipts.snapshot(7)
        self.assertEqual(baked, {})
        receipts.bind({7: (17,)})
        for epoch, snapshot in enumerate((live, baked)):
            receipts.completed(self.receipt(7, epoch, snapshot))
            receipts.collect()
            self.assertTrue(receipts.awaiting(17, (7,)))
        receipts.completed(self.receipt(7, 2, receipts.snapshot(7)))
        receipts.collect()
        self.assertFalse(receipts.awaiting(17, (7,)))


if __name__ == "__main__":
    unittest.main()
