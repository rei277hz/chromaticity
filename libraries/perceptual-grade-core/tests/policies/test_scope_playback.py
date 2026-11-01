"""Latest-available animated scopes retain exact publication and lifecycle fences."""
from dataclasses import replace
import unittest

from color_tools.invariant import Machine
from color_tools.blender_runtime import App, ForeignOwnerError
from color_tools.perceptual_grade_core.graph import scheduler_policy
from color_tools.perceptual_grade_core.graph.policies import channel, _channel_contracts


class ScopePlaybackTests(unittest.TestCase):
    def setUp(self):
        self.machine = Machine(channel, contracts=_channel_contracts, initializers=('initial',))
        self.app = App(package='scope_playback', storage_name='scope_playback')
        self.addCleanup(self.app.close)
        self.store = self.channel()
        self.send('signal', signal=41)

    def channel(self, *, scope=True, linear=False):
        return self.app.store(machine=self.machine, initial=dict(
            owner=7, key=0, session=3, scope=scope, linear=linear))

    def event(self, kind, **values):
        return channel.Event(kind, **(dict(owner=7, session=3) | values))

    def send(self, kind, **values):
        return self.store.dispatch(self.event(kind, **values))

    def request(self, key, *, history=True, provenance=101):
        self.send('request', key=key, provenance=provenance, history=history)
        return self.store.state.epoch

    def candidate(self, key, epoch, *, history=True, **values):
        return self.event('publish', **(dict(key=key, epoch=epoch, signal=41,
            quality=2, provenance=101, resolution=65, history=history) | values))

    def test_finished_old_frame_can_display_while_current_request_stays_pending(self):
        old = self.request(11)
        current = self.request(12)
        self.assertTrue(self.store.dispatch(self.candidate(11, old)).accept)
        state = self.store.state
        self.assertEqual((state.display_key, state.display_epoch), (11, old))
        self.assertEqual((state.requested, state.epoch, state.quality, state.publications),
                         (12, current, 0, 0))
        self.assertFalse(state.dragging)

    def test_old_frame_does_not_clear_newer_decode_or_analysis_error(self):
        old = self.request(11)
        current = self.request(12)
        self.assertTrue(self.send('fail', key=12).failed)
        self.assertTrue(self.store.dispatch(self.candidate(11, old)).accept)
        self.assertTrue(self.store.state.error)
        self.assertEqual(self.store.state.error_key, 12)
        self.assertEqual(self.store.state.quality, 0)
        self.assertTrue(self.store.dispatch(self.candidate(12, current)).accept)
        self.assertFalse(self.store.state.error)
        self.assertEqual(self.store.state.quality, 2)

    def test_both_frozen_receipt_and_current_request_must_authorize_history(self):
        old = self.request(11)
        self.request(12)
        before = self.store.state
        self.assertFalse(self.store.dispatch(self.candidate(11, old, history=False)).accept)
        self.assertEqual(self.store.state, before)
        self.request(13, history=False)
        before = self.store.state
        self.assertFalse(self.store.dispatch(self.candidate(11, old)).accept)
        self.assertEqual(self.store.state, before)

    def test_later_finished_frame_prevents_display_regression(self):
        first = self.request(11)
        second = self.request(12)
        self.request(13)
        self.assertTrue(self.store.dispatch(self.candidate(12, second)).accept)
        before = self.store.state
        self.assertFalse(self.store.dispatch(self.candidate(11, first)).accept)
        self.assertEqual(self.store.state, before)

    def test_history_keeps_owner_session_signal_epoch_and_final_provenance_checks(self):
        old = self.request(11)
        self.request(12)
        receipt = self.candidate(11, old)
        for changes in (dict(owner=8), dict(session=4), dict(signal=42),
                        dict(epoch=self.store.state.epoch+1), dict(provenance=0),
                        dict(resolution=33), dict(quality=0)):
            with self.subTest(changes=changes):
                before = self.store.state
                self.assertFalse(self.store.dispatch(replace(receipt, **changes)).accept)
                self.assertEqual(self.store.state, before)
        self.send('ready', ready=False)
        self.assertFalse(self.store.dispatch(receipt).accept)

    def test_current_frame_still_requires_current_provenance(self):
        epoch = self.request(11, provenance=102)
        self.assertFalse(self.store.dispatch(self.candidate(11, epoch, provenance=101)).accept)
        self.assertTrue(self.store.dispatch(self.candidate(11, epoch, provenance=102)).accept)

    def test_looped_frame_key_keeps_old_epoch_historical_and_preserves_current_error(self):
        first = self.request(11)
        self.request(12)
        current = self.request(11)
        self.send('fail', key=11)
        self.assertTrue(self.store.dispatch(self.candidate(11, first)).accept)
        state = self.store.state
        self.assertEqual((state.display_key, state.display_epoch), (11, first))
        self.assertEqual((state.epoch, state.quality, state.error_key), (current, 0, 11))
        self.assertTrue(state.error)
        self.assertTrue(self.store.dispatch(self.candidate(11, current)).accept)
        self.assertFalse(self.store.state.error)

    def test_looped_frame_key_cannot_bypass_history_authority(self):
        first = self.request(11)
        self.request(12)
        self.request(11)
        self.assertFalse(self.store.dispatch(self.candidate(11, first, history=False)).accept)
        self.request(12, history=False)
        self.request(11, history=False)
        self.assertFalse(self.store.dispatch(self.candidate(11, first)).accept)

    def test_recovery_and_owner_invalidation_reject_frozen_old_receipts(self):
        old = self.request(11)
        receipt = self.store.event(self.candidate(11, old))
        self.send('recover')
        self.assertEqual((self.store.state.owner, self.store.state.session), (8, 4))
        self.assertFalse(self.store.dispatch(receipt).accept)
        self.assertFalse(self.store.state.display_available)
        other = self.channel()
        with self.assertRaises(ForeignOwnerError):
            other.dispatch(receipt)

    def test_non_scope_request_cannot_enable_historical_bake_publication(self):
        store = self.channel(scope=False)
        store.dispatch(self.event('signal', signal=41))
        store.dispatch(self.event('request', key=11, history=True))
        old = store.state.epoch
        store.dispatch(self.event('request', key=12, history=True))
        self.assertFalse(store.state.history)
        self.assertFalse(store.dispatch(self.candidate(11, old)).accept)

    def test_historical_worker_admission_requires_explicit_history_and_final_lut(self):
        old = self.request(11)
        self.request(12)
        start = self.event('start', key=11, epoch=old, token=71, provenance=101, resolution=65, history=True)
        for changes in (dict(history=False), dict(owner=8), dict(session=4),
                        dict(provenance=0), dict(resolution=33)):
            with self.subTest(changes=changes):
                self.assertFalse(self.store.dispatch(replace(start, **changes)).start)
        self.assertTrue(self.store.dispatch(start).start)
        self.assertFalse(self.store.dispatch(replace(start, token=72)).start)
        self.assertTrue(self.send('complete', token=71).accept)

    def test_looped_worker_key_cannot_bypass_history_authority(self):
        first = self.request(11)
        self.request(12)
        self.request(11)
        start = self.event('start', key=11, epoch=first, token=71, provenance=101, resolution=65)
        self.assertFalse(self.store.dispatch(start).start)
        self.assertTrue(self.store.dispatch(replace(start, history=True)).start)

    def test_history_cycle_finishes_current_work_then_dispatches_newest_pending(self):
        running = scheduler_policy.scope_cycle(True, True, False, False,
                                               preview=True, pending=True, history=True)
        self.assertTrue(running.keep and running.publish)
        self.assertFalse(running.cancel or running.retire or running.dispatch)
        retired = scheduler_policy.scope_cycle(True, True, False, False,
                                               retired=True, pending=True, history=True)
        self.assertTrue(retired.collect and retired.retire and retired.dispatch)
        self.assertFalse(retired.cancel or retired.advance)
        for wanted, compatible, history in ((False, True, True), (True, False, True), (True, True, False)):
            decision = scheduler_policy.scope_cycle(wanted, compatible, False, False,
                                                    preview=True, history=history)
            self.assertTrue(decision.cancel)
            self.assertFalse(decision.keep or decision.publish)

    def test_history_never_substitutes_for_helper_seed_backend_or_generation_ack(self):
        for index in range(5):
            facts = [True] * 5
            facts[index] = False
            ack = scheduler_policy.scope_ack_admissible(*facts)
            self.assertFalse(ack)
            cycle = scheduler_policy.scope_cycle(True, True, False, False,
                                                  retired=True, control=True, ack=ack, history=True)
            self.assertFalse(cycle.advance)
        self.assertTrue(scheduler_policy.scope_cycle(True, True, False, False,
            retired=True, control=True, ack=True, history=True).advance)


if __name__ == '__main__':
    unittest.main()
