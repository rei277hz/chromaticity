"""Real generated contracts, actor envelopes and one-shot scope input leases."""
from dataclasses import replace
import unittest

from color_tools.invariant import Machine
from color_tools.blender_runtime import App, DomainError, ForeignOwnerError
from color_tools.perceptual_grade_core.graph.coordinators import scope_input as policy
from color_tools.perceptual_grade_core.graph.coordinators import _scope_input_contracts


class ScopeInputTests(unittest.TestCase):
    def setUp(self):
        self.machine = Machine(policy, contracts=_scope_input_contracts)
        self.app = App(package='scope_input_test', storage_name='scope_input_test')
        self.addCleanup(self.app.close)
        self.store = self.app.store(machine=self.machine, initial={'generation': 1})
        self.identity = dict(generation=1, request=1, source=17, target=23)

    def event(self, kind, **values):
        return policy.Event(kind, **(self.identity | values))

    def dispatch(self, kind, **values):
        return self.store.dispatch(self.event(kind, **values))

    def start(self):
        self.assertEqual(self.dispatch('request').action, 'prepare')
        self.assertEqual(self.dispatch('start').action, 'capture')

    def test_automatic_acquisition_never_grants_native_authority(self):
        self.assertEqual(self.dispatch('automatic').action, 'sample')
        self.assertFalse(self.store.state.authority)
        self.assertFalse(self.dispatch('start').accepted)
        self.assertEqual(self.dispatch('captured', payload=31, validated=True).action, 'publish')
        self.assertEqual(self.store.state.phase, 'ready')
        self.assertFalse(self.store.state.physical)
        self.assertFalse(self.dispatch('retired', validated=True).accepted)

    def test_native_candidate_publication_does_not_retire_snapshot(self):
        self.start()
        self.assertFalse(self.store.state.authority)
        effect = self.dispatch('captured', payload=31, validated=True)
        self.assertEqual((effect.action, effect.request, effect.source, effect.target, effect.payload),
                         ('publish', 1, 17, 23, 31))
        self.assertTrue(self.store.state.physical)
        self.assertEqual(self.store.state.phase, 'retiring')
        self.assertFalse(self.dispatch('retired').accepted)
        self.assertEqual(self.dispatch('retired', validated=True).action, 'release')
        self.assertEqual(self.store.state.phase, 'ready')
        self.assertFalse(self.store.state.physical)
        self.assertFalse(self.dispatch('retired', validated=True).accepted)

    def test_request_is_one_shot_and_cannot_replace_pending_work(self):
        self.dispatch('request')
        for request in (1, 2):
            self.assertFalse(self.dispatch('request', request=request).accepted)
        self.assertEqual(self.dispatch('start').action, 'capture')
        self.assertFalse(self.dispatch('start').accepted)
        self.assertFalse(self.dispatch('request', request=2).accepted)
        self.assertFalse(self.dispatch('automatic', request=2).accepted)

    def test_invalidated_authority_cannot_capture_revised_source(self):
        self.dispatch('request')
        receipt = self.store.event(self.event('start'))
        self.dispatch('invalidate')
        self.assertEqual(self.store.state.phase, 'stale')
        self.assertFalse(self.store.dispatch(receipt).accepted)
        self.assertFalse(self.dispatch('start', source=19).accepted)
        self.assertFalse(self.dispatch('request', source=19).accepted)
        self.assertEqual(self.dispatch('request', request=2, source=19).action, 'prepare')
        self.assertEqual(self.dispatch('start', request=2, source=19).action, 'capture')

    def test_invalidation_during_capture_rejects_candidate_but_retains_lease(self):
        self.start()
        result = self.store.event(self.event('captured', payload=31, validated=True))
        retired = self.store.event(self.event('retired', validated=True))
        self.assertEqual(self.dispatch('invalidate').action, 'cancel')
        self.assertFalse(self.store.dispatch(result).accepted)
        self.assertTrue(self.store.state.physical)
        self.assertEqual(self.store.dispatch(retired).action, 'release')
        self.assertEqual(self.store.state.phase, 'stale')
        self.assertFalse(self.store.dispatch(result).accepted)

    def test_invalidation_after_candidate_revokes_ready_outcome(self):
        self.start()
        self.dispatch('captured', payload=31, validated=True)
        self.dispatch('invalidate')
        self.dispatch('retired', validated=True)
        self.assertEqual(self.store.state.phase, 'stale')
        self.assertFalse(self.dispatch('captured', payload=31, validated=True).accepted)

    def test_admission_failure_requires_new_request(self):
        self.dispatch('request')
        self.dispatch('failed')
        self.assertEqual(self.store.state.phase, 'failed')
        self.assertFalse(self.store.state.authority or self.store.state.physical)
        self.assertFalse(self.dispatch('start').accepted)
        self.assertFalse(self.dispatch('request').accepted)
        self.assertEqual(self.dispatch('request', request=2).action, 'prepare')

    def test_worker_failure_cannot_retry_until_retired_and_requested_again(self):
        self.start()
        self.assertEqual(self.dispatch('failed').action, 'cancel')
        self.assertTrue(self.store.state.physical)
        self.assertFalse(self.dispatch('request', request=2).accepted)
        self.assertFalse(self.dispatch('captured', payload=31, validated=True).accepted)
        self.dispatch('retired', validated=True)
        self.assertEqual(self.store.state.phase, 'failed')
        self.assertFalse(self.dispatch('start').accepted)
        self.assertEqual(self.dispatch('request', request=2).action, 'prepare')
        self.assertEqual(self.dispatch('start', request=2).action, 'capture')

    def test_foreign_source_target_request_or_generation_cannot_publish_or_release(self):
        self.start()
        for change in ({'source': 18}, {'target': 24}, {'request': 2}, {'generation': 2}):
            with self.subTest(change=change):
                before = self.store.state
                self.assertFalse(self.dispatch('captured', payload=31, validated=True, **change).accepted)
                self.assertFalse(self.dispatch('retired', validated=True, **change).accepted)
                self.assertEqual(self.store.state, before)

    def test_unvalidated_or_nonpositive_candidates_are_rejected(self):
        self.start()
        for values in ({'payload': 31}, {'payload': 0, 'validated': True},
                       {'payload': -1, 'validated': True}):
            self.assertFalse(self.dispatch('captured', **values).accepted)
        self.assertEqual(self.store.state.phase, 'capturing')

    def test_duplicate_candidate_is_not_published_twice(self):
        self.start()
        receipt = self.store.event(self.event('captured', payload=31, validated=True))
        self.assertEqual(self.store.dispatch(receipt).action, 'publish')
        self.assertFalse(self.store.dispatch(receipt).accepted)

    def test_close_awaits_exact_retirement_and_cannot_admit_or_publish(self):
        self.start()
        self.assertEqual(self.dispatch('close').action, 'cancel')
        for kind in ('request', 'automatic', 'start', 'captured'):
            self.assertFalse(self.dispatch(kind, payload=31, validated=True).accepted)
        self.assertTrue(self.store.state.physical)
        self.assertFalse(self.dispatch('retired', source=18, validated=True).accepted)
        self.assertFalse(self.dispatch('retired').accepted)
        self.assertEqual(self.dispatch('retired', validated=True).action, 'release')
        self.assertEqual(self.store.state.phase, 'closed')
        self.assertFalse(self.dispatch('request', request=2).accepted)

    def test_unstarted_close_needs_no_physical_retirement(self):
        self.dispatch('request')
        self.assertEqual(self.dispatch('close').action, 'none')
        self.assertEqual(self.store.state.phase, 'closed')
        self.assertFalse(self.store.state.authority)

    def test_retirement_without_success_preserves_stale_status(self):
        self.start()
        self.assertEqual(self.dispatch('retired', validated=True).action, 'release')
        self.assertEqual(self.store.state.phase, 'stale')
        self.assertFalse(self.dispatch('captured', payload=31, validated=True).accepted)

    def test_source_envelopes_cannot_cross_primary_reference_actor_or_app(self):
        self.dispatch('request')
        receipt = self.store.event(self.event('start'))
        reference = self.app.store(machine=self.machine, initial={'generation': 1})
        reference.dispatch(self.event('request'))
        with self.assertRaises(ForeignOwnerError):
            reference.dispatch(receipt)
        peer = App(package='scope_input_peer', storage_name='scope_input_peer')
        self.addCleanup(peer.close)
        foreign = peer.store(machine=self.machine, initial={'generation': 1})
        foreign.dispatch(self.event('request'))
        with self.assertRaises(ForeignOwnerError):
            foreign.dispatch(receipt)
        self.assertEqual(self.store.dispatch(receipt).action, 'capture')

    def test_custom_generation_rejects_old_generation_without_consuming_request(self):
        store = self.app.store(machine=self.machine, initial={'generation': 7})
        self.assertFalse(store.dispatch(self.event('request')).accepted)
        self.assertEqual(store.dispatch(self.event('request', generation=7)).action, 'prepare')

    def test_runtime_contracts_reject_bad_generation_and_event_types(self):
        with self.assertRaises(DomainError):
            self.app.store(machine=self.machine, initial={'generation': 0})
        for event in (replace(self.event('request'), kind='refresh'),
                      replace(self.event('request'), validated=1),
                      replace(self.event('request'), request=True)):
            with self.assertRaises(DomainError):
                self.store.dispatch(event)
        self.assertEqual(self.store.state, policy.new())


if __name__ == '__main__':
    unittest.main()
