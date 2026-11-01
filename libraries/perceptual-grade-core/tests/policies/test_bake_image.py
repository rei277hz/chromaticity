"""Runtime receipts for native-authoritative Image reconciliation."""
import unittest
from color_tools.invariant import Machine
from color_tools.blender_runtime import App, DomainError, ForeignOwnerError
from color_tools.perceptual_grade_core.graph.policies import bake_image as policy
from color_tools.perceptual_grade_core.graph.policies import _bake_image_contracts


class BakeImagePolicyTests(unittest.TestCase):
    def store(self):
        app=App(package='bake_image_policy',storage_name='bake_image_policy')
        self.addCleanup(app.close)
        return app.store(machine=Machine(policy,contracts=_bake_image_contracts,
            initializers=('new',),queries=('settled','recovery_required')))

    def test_unchanged_dirty_and_legacy_images_settle_without_inspection(self):
        for managed,dirty,changed in ((True,False,False),(True,True,True),(False,False,True)):
            s=self.store();s.dispatch(policy.Event('begin',generation=1))
            e=s.dispatch(policy.Event('observe',generation=1,managed=managed,dirty=dirty,changed=changed))
            self.assertTrue(e.preserve and e.settled);self.assertFalse(e.invalidate)
            self.assertTrue(s.query('settled'));self.assertFalse(s.query('recovery_required'))

    def test_changed_managed_clean_revision_needs_completed_invalidation(self):
        s=self.store();s.dispatch(policy.Event('begin',generation=1))
        self.assertTrue(s.dispatch(policy.Event('observe',generation=1,managed=True,changed=True)).invalidate)
        self.assertFalse(s.dispatch(policy.Event('invalidated',generation=1)).accepted)
        self.assertTrue(s.query('recovery_required'))
        self.assertTrue(s.dispatch(policy.Event('invalidated',generation=1,matched=True)).settled)
        self.assertEqual(s.state.phase,'settled_invalidated')

    def test_failed_operation_retries_without_requiring_content_readback(self):
        s=self.store()
        for e in (policy.Event('begin',generation=1),policy.Event('observe',generation=1,managed=True,changed=True),policy.Event('failed',generation=1)):
            s.dispatch(e)
        s.dispatch(policy.Event('begin',generation=2))
        self.assertTrue(s.dispatch(policy.Event('observe',generation=2,managed=True)).invalidate)
        self.assertTrue(s.dispatch(policy.Event('invalidated',generation=2,matched=True)).settled)

    def test_external_edit_settles_old_debt_without_discarding_pixels(self):
        s=self.store()
        for e in (policy.Event('begin',generation=1),policy.Event('observe',generation=1,managed=True,changed=True),policy.Event('failed',generation=1),policy.Event('begin',generation=2)):
            s.dispatch(e)
        e=s.dispatch(policy.Event('observe',generation=2,managed=True,dirty=True))
        self.assertTrue(e.preserve and e.settled);self.assertFalse(s.state.pending)

    def test_repeated_pre_carries_unfinished_managed_change(self):
        s=self.store();s.dispatch(policy.Event('begin',generation=1))
        s.dispatch(policy.Event('observe',generation=1,managed=True,changed=True))
        s.dispatch(policy.Event('begin',generation=2))
        self.assertTrue(s.dispatch(policy.Event('observe',generation=2,managed=True)).invalidate)

    def test_stale_and_foreign_receipts_cannot_settle_new_observation(self):
        s=self.store();s.dispatch(policy.Event('begin',generation=1))
        s.dispatch(policy.Event('observe',generation=1,managed=True,changed=True))
        receipt=s.event(policy.Event('invalidated',generation=1,matched=True))
        s.dispatch(policy.Event('begin',generation=2))
        s.dispatch(policy.Event('observe',generation=2,managed=True,changed=True))
        self.assertFalse(s.dispatch(receipt).accepted)
        with self.assertRaises(ForeignOwnerError):self.store().dispatch(receipt)

    def test_removed_image_settles_without_a_native_effect(self):
        s=self.store();s.dispatch(policy.Event('begin',generation=1))
        e=s.dispatch(policy.Event('observe',generation=1,present=False))
        self.assertTrue(e.settled);self.assertFalse(e.invalidate);self.assertEqual(s.state.phase,'removed')

    def test_typed_boundary_rejects_unknown_events(self):
        s=self.store()
        for e in (policy.Event('verified'),policy.Event('observe',dirty=1)):
            with self.assertRaises(DomainError):s.dispatch(e)


if __name__=='__main__':unittest.main()
