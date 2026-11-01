"""Bake admission uses real generated contracts and actor-owned queue state."""
import unittest

from color_tools.invariant import Machine
from color_tools.blender_runtime import App
from color_tools.perceptual_grade_core.graph.coordinators import bake_queue as policy
from color_tools.perceptual_grade_core.graph.coordinators import _bake_queue_contracts


class BakeQueueTests(unittest.TestCase):
    def setUp(self):
        self.app = App(package='bake_queue_test', storage_name='bake_queue_test')
        self.addCleanup(self.app.close)
        self.store = self.app.store(machine=Machine(policy, contracts=_bake_queue_contracts,
            queries=('target_busy', 'lane_busy', 'destination_waits')))
        self.requests = {}

    def event(self, kind, slot=0, **values):
        return policy.Event(kind, **(dict(generation=1, slot=slot) | self.requests.get(slot, {}) | values))

    def send(self, kind, slot=0, **values):
        return self.store.dispatch(self.event(kind, slot, **values))

    def admit(self, slot, request, target, destination):
        self.requests[slot] = dict(request=request, target=target, destination=destination)
        self.assertEqual(self.send('admit', slot).action, 'freeze')
        self.assertEqual(self.send('frozen', slot, validated=True).action, 'queue')

    def start(self, slot, lane):
        self.assertEqual(self.send('start', slot, lane=lane, validated=True).action, 'dispatch')

    def test_two_workers_and_eight_requests_are_bounded(self):
        for slot in range(8):
            self.admit(slot, slot + 1, slot + 10, slot + 20)
        self.start(0, 1); self.start(1, 2)
        self.assertFalse(self.send('start', 2, lane=1, validated=True).accepted)
        self.assertFalse(self.send('start', 2, lane=2, validated=True).accepted)
        self.assertFalse(self.send('admit', 8, request=9, target=99, destination=99).accepted)
        self.assertFalse(self.send('admit', 0, request=9, target=99, destination=99).accepted)
        self.assertEqual(self.send('complete', 1, validated=True).action, 'stage')
        self.start(2, 2)
        self.assertEqual(self.store.state.entries[1].phase, 'ready')

    def test_target_is_reserved_until_terminal_publication(self):
        self.admit(0, 1, 10, 20)
        self.assertFalse(self.send('admit', 1, request=2, target=10, destination=30).accepted)
        self.start(0, 1)
        self.send('complete', 0, validated=True)
        self.assertFalse(self.send('finish', 0, validated=True).accepted)
        self.assertTrue(self.store.query('target_busy', target=10))
        self.assertEqual(self.send('publish', 0, validated=True).action, 'publish')
        self.assertEqual(self.send('finish', 0, validated=True).action, 'release')
        self.admit(0, 2, 10, 20)

    def test_shared_destination_waits_for_publication_not_worker_completion(self):
        self.admit(0, 1, 10, 20); self.admit(1, 2, 11, 20)
        self.admit(2, 3, 12, 21)
        self.start(0, 1)
        self.assertFalse(self.send('start', 1, lane=2, validated=True).accepted)
        self.start(2, 2)
        self.send('complete', 0, validated=True)
        self.assertFalse(self.send('start', 1, lane=1, validated=True).accepted)
        self.send('publish', 0, validated=True)
        self.assertFalse(self.send('start', 1, lane=1, validated=True).accepted)
        self.send('finish', 0, validated=True)
        self.start(1, 1)

    def test_cancel_keeps_worker_until_retirement_and_destination_until_rollback(self):
        self.admit(0, 1, 10, 20); self.admit(1, 2, 11, 20)
        self.start(0, 1)
        self.assertEqual(self.send('cancel', 0).action, 'cancel')
        self.assertFalse(self.send('finish', 0, validated=True).accepted)
        self.assertFalse(self.send('retired', 0).accepted)
        self.assertEqual(self.send('retired', 0, validated=True).action, 'retire')
        self.assertFalse(self.send('start', 1, lane=1, validated=True).accepted)
        self.send('finish', 0, validated=True)
        self.start(1, 1)

    def test_cancelled_queued_request_does_not_cancel_other_entries(self):
        self.admit(0, 1, 10, 20); self.admit(1, 2, 11, 21)
        self.start(0, 1)
        before=self.store.state.entries[0]
        self.send('cancel', 1); self.send('finish', 1, validated=True)
        self.assertEqual(self.store.state.entries[0], before)

    def test_frozen_snapshot_and_validated_current_receipts_are_required(self):
        self.requests[0] = dict(request=1, target=10, destination=20)
        self.send('admit')
        self.assertFalse(self.send('start', lane=1, validated=True).accepted)
        self.assertFalse(self.send('frozen').accepted)
        self.send('frozen', validated=True); self.start(0, 1)
        for kind in ('complete', 'retired', 'finish'):
            for values in ({'request': 2}, {'target': 11}, {'destination': 21}, {'generation': 2}):
                with self.subTest(kind=kind, values=values):
                    self.assertFalse(self.send(kind, validated=True, **values).accepted)
        self.assertFalse(self.send('complete').accepted)

    def test_close_cancels_all_without_releasing_physical_leases(self):
        self.admit(0, 1, 10, 20); self.admit(1, 2, 11, 21)
        self.start(0, 1); self.start(1, 2)
        self.assertEqual(self.send('close').action, 'cancel_all')
        self.assertTrue(self.store.state.closing)
        self.assertTrue(all(self.store.state.entries[i].physical for i in (0,1)))
        self.assertFalse(self.send('publish', validated=True).accepted)
        for slot in (0,1):
            self.send('retired', slot, validated=True); self.send('finish', slot, validated=True)
        self.assertFalse(any(entry.request for entry in self.store.state.entries))
        self.assertFalse(self.send('admit', 2, request=3, target=12, destination=22).accepted)

    def test_stale_receipt_cannot_release_reused_slot(self):
        self.admit(0, 1, 10, 20)
        receipt = self.store.event(self.event('finish', validated=True))
        self.send('cancel'); self.send('finish', validated=True)
        self.admit(0, 2, 11, 21)
        before=self.store.state
        self.assertFalse(self.store.dispatch(receipt).accepted)
        self.assertEqual(self.store.state,before)


if __name__ == '__main__':
    unittest.main()
