"""Output authority, partial writes, and receipt fencing regressions."""
import unittest

from color_tools.perceptual_grade_core.graph import output_policy as policy
from color_tools.perceptual_grade_core.graph.policies import output


def step(state, event, **kwargs):
    updated, effects = output.step(state, output.OutputEvent(kind=event, **kwargs))
    return updated, effects.accepted


class OutputResourceTests(unittest.TestCase):
    def advance(self, state, event, **kwargs):
        updated, accepted = step(state, event, incarnation=state.incarnation, **kwargs)
        self.assertTrue(accepted, event)
        return updated

    def finish_graph(self, state, slot, source, output_key='whole-output'):
        state = self.advance(state, 'graph_begin', slot=slot, source=source,
                             output_key=output_key, reader_excluded=True)
        token = dict(slot=slot, source=source, output_key=output_key,
                     operation=state.graph_operation, validated=True, reader_excluded=True)
        for event in ('fallback', 'rows', 'select' if slot >= 0 else 'fallback_done'):
            state = self.advance(state, event, **token)
        return state

    def publish(self, state, slot, source):
        state = self.advance(state, 'reserve', slot=slot, source=source, reader_excluded=True)
        receipt = dict(slot=slot, source=source, operation=state.operation,
                       validated=True, reader_excluded=True)
        state = self.advance(state, 'armed', **receipt)
        state = self.advance(state, 'packed', clean=True, **receipt)
        state = self.advance(state, 'transferred', **receipt)
        return self.finish_graph(state, slot, source)

    def test_native_adoption_preserves_selection_without_claiming_completion(self):
        state = self.publish(policy.establish(7), 2, 'old')
        state = self.advance(state, 'adopt_native', slot=3, intent='restored-controls')
        self.assertTrue(state.adopted)
        self.assertEqual(state.protected, 3)
        self.assertEqual(state.selected, -1)
        self.assertFalse(state.graph_valid)
        self.assertTrue(all(not slot.valid and not slot.debt and
                            slot.readability == policy.EXTERNAL for slot in state.slots))
        for event in ('reserve', 'inspect', 'certify', 'graph_begin', 'adopt'):
            after, accepted = step(state, event, incarnation=7, slot=0,
                source='old', validated=True, certified=True, readable=True,
                reader_excluded=True)
            self.assertFalse(accepted, event)
            self.assertEqual(after, state)

    def test_only_changed_or_explicit_intent_leaves_native_adoption(self):
        state = self.advance(policy.establish(1), 'adopt_native', slot=2, intent='current')
        after, accepted = step(state, 'intent', incarnation=1, intent='current')
        self.assertFalse(accepted)
        self.assertEqual(after, state)
        for intent, explicit in (('changed', False), ('current', True)):
            after = self.advance(state, 'intent', intent=intent, explicit=explicit)
            self.assertFalse(after.adopted)
            self.assertEqual(after.protected, 2)
            self.assertFalse(any(slot.valid for slot in after.slots))

    def test_resumed_producer_cannot_overwrite_native_selected_bank(self):
        state = self.advance(policy.establish(1), 'adopt_native', slot=2, intent='current')
        state = self.advance(state, 'intent', intent='new')
        after, accepted = step(state, 'reserve', incarnation=1, slot=2,
                              source='new', reader_excluded=True)
        self.assertFalse(accepted)
        self.assertEqual(after, state)
        state = self.publish(state, 3, 'new')
        self.assertTrue(policy.output_complete(state, 'whole-output'))
        self.assertEqual(state.selected, 3)

    def test_native_adoption_and_resume_reject_foreign_generation(self):
        state = self.advance(policy.establish(4, session=8), 'adopt_native',
                             session=8, slot=2, intent='current')
        for kind in ('adopt_native', 'intent', 'protect'):
            after, accepted = step(state, kind, incarnation=3, session=8, slot=3,
                                  intent='changed', explicit=True, reader_excluded=True)
            self.assertFalse(accepted)
            self.assertEqual(after, state)

    def test_failed_overwrite_preserves_last_complete_and_requires_new_receipt(self):
        state = self.publish(policy.establish(7), 0, 'first')
        first = state.slots[0]
        state = self.advance(state, 'reserve', slot=1, source='second', reader_excluded=True)
        old_operation = state.operation
        state = self.advance(state, 'fail', slot=1, source='second', operation=old_operation)
        self.assertEqual(state.selected, 0)
        self.assertEqual(state.slots[0], first)
        self.assertTrue(state.slots[1].debt)
        state = self.advance(state, 'reserve', slot=1, source='second', reader_excluded=True)
        unchanged, accepted = step(state, 'transferred', incarnation=7, slot=1, source='second',
                                         operation=old_operation, validated=True, reader_excluded=True)
        self.assertFalse(accepted)
        self.assertEqual(unchanged, state)
        state = self.advance(state, 'armed', slot=1, source='second', operation=state.operation,
                             validated=True, reader_excluded=True)
        state = self.advance(state, 'packed', slot=1, source='second', operation=state.operation,
                             validated=True, clean=True, reader_excluded=True)
        state = self.advance(state, 'transferred', slot=1, source='second', operation=state.operation,
                             validated=True, reader_excluded=True)
        state = self.finish_graph(state, 1, 'second')
        self.assertEqual(state.selected, 1)
        self.assertFalse(state.slots[1].debt)

    def test_selected_or_unexcluded_storage_cannot_be_reserved(self):
        state = self.publish(policy.establish(3), 2, 'complete')
        for slot, excluded in ((2, True), (3, False)):
            unchanged, accepted = step(state, 'reserve', incarnation=3, slot=slot,
                                             source='next', reader_excluded=excluded)
            self.assertFalse(accepted)
            self.assertEqual(unchanged, state)

    def test_undo_discards_completion_even_when_metadata_is_restored(self):
        state = self.publish(policy.establish(3), 2, 'same-manifest')
        state = self.advance(state, 'reserve', slot=3, source='partial', reader_excluded=True)
        operation = state.operation
        state, accepted = step(state, 'invalidate')
        self.assertTrue(accepted)
        self.assertEqual(state.incarnation, 4)
        self.assertEqual(state.selected, -1)
        self.assertFalse(any(slot.valid for slot in state.slots))
        self.assertTrue(all(s.debt and s.readability == policy.UNKNOWN for s in state.slots))
        self.assertFalse(policy.complete(state, 2, 'same-manifest'))
        unchanged, accepted = step(state, 'transferred', incarnation=3, slot=3,
                                         source='partial', operation=operation,
                                         validated=True, reader_excluded=True)
        self.assertFalse(accepted)
        self.assertEqual(unchanged, state)

    def test_failed_repair_retains_debt(self):
        state = self.advance(policy.establish(1), 'reserve', slot=0, source='partial', reader_excluded=True)
        state = self.advance(state, 'fail', slot=0, source='partial', operation=state.operation)
        for validated, excluded in ((False, True), (True, False)):
            unchanged, accepted = step(state, 'repair', incarnation=1, slot=0,
                                             validated=validated, reader_excluded=excluded)
            self.assertFalse(accepted)
            self.assertEqual(unchanged, state)
            self.assertTrue(unchanged.slots[0].debt)
        state = self.advance(state, 'repair', slot=0, validated=True, reader_excluded=True)
        self.assertFalse(state.slots[0].debt)
        self.assertFalse(state.slots[0].valid)

    def test_reacquired_storage_starts_uncertain_without_adopting_saved_metadata(self):
        state = policy.establish(99, uncertain=True)
        self.assertEqual(state.selected, -1)
        self.assertTrue(all(slot.debt and not slot.valid for slot in state.slots))
        state = self.publish(state, 0, 'reconstructed')
        self.assertTrue(policy.complete(state, 0, 'reconstructed'))
        self.assertTrue(all(slot.debt for slot in state.slots[1:]))

    def test_foreign_source_or_incomplete_payload_cannot_be_selected(self):
        state = self.advance(policy.establish(1), 'reserve', slot=0, source='wanted', reader_excluded=True)
        for source in ('wanted', 'foreign'):
            unchanged, accepted = step(state, 'select', incarnation=1, slot=0,
                                             source=source, operation=state.operation)
            self.assertFalse(accepted)
            self.assertEqual(unchanged, state)

    def test_readability_is_not_payload_or_graph_certification(self):
        state = policy.establish(1, uncertain=True)
        state = self.advance(state, 'inspect', slot=2, readable=True)
        self.assertFalse(state.slots[2].debt)
        self.assertFalse(state.slots[2].valid)
        self.assertEqual(state.slots[2].readability, policy.READABLE)
        self.assertFalse(policy.output_complete(state, 'wanted'))
        state = self.advance(state, 'certify', slot=2, source='payload', certified=True, validated=True)
        self.assertTrue(policy.complete(state, 2, 'payload'))
        self.assertFalse(policy.output_complete(state, 'wanted'))
        state = self.advance(state, 'observe_packing', slot=2, operation=state.operation,
                             clean=True, reader_excluded=True)
        state = self.advance(state, 'adopt', slot=2, source='payload', output_key='wanted', validated=True)
        self.assertTrue(policy.output_complete(state, 'wanted'))
        self.assertEqual(state.operation, 0, 'read-only restore must not reserve an overwrite')
        self.assertTrue(all(state.slots[i].debt for i in (0, 1, 3)))

    def test_old_session_receipt_cannot_revive_after_restart(self):
        old = policy.establish(1, session=10)
        old, _ = step(old, 'reserve', incarnation=1, session=10, slot=0,
                             source='payload', reader_excluded=True)
        fresh = policy.establish(1, uncertain=True, session=11)
        after, accepted = step(fresh, 'armed', incarnation=1, session=10,
                                      slot=0, source='payload', operation=old.operation,
                                      validated=True, reader_excluded=True)
        self.assertFalse(accepted)
        self.assertEqual(fresh, after)

    def test_complete_transfer_requires_armed_record(self):
        state = self.advance(policy.establish(1), 'reserve', slot=0, source='payload', reader_excluded=True)
        after, accepted = step(state, 'transferred', incarnation=1, slot=0,
            source='payload', operation=state.operation, validated=True, reader_excluded=True)
        self.assertFalse(accepted)
        self.assertEqual(state, after)

    def test_transfer_requires_packing_and_failed_retirement_keeps_clean_observation(self):
        state = self.advance(policy.establish(1), 'reserve', slot=0, source='payload', reader_excluded=True)
        token = dict(slot=0, source='payload', operation=state.operation,
                     validated=True, reader_excluded=True)
        state = self.advance(state, 'armed', **token)
        after, accepted = step(state, 'transferred', incarnation=1, **token)
        self.assertFalse(accepted)
        self.assertEqual(state, after)
        state = self.advance(state, 'packed', clean=True, **token)
        state = self.advance(state, 'fail', **token)
        self.assertEqual(state.slots[0].packing, policy.PACK_CLEAN)
        self.assertFalse(state.slots[0].valid)

    def test_packing_failure_reuses_verified_pixels_without_reservation_or_bake(self):
        state = self.publish(policy.establish(1), 0, 'previous')
        previous = state.slots[0]
        state = self.advance(state, 'reserve', slot=1, source='new', reader_excluded=True)
        token = dict(slot=1, source='new', operation=state.operation)
        state = self.advance(state, 'armed', **token, validated=True, reader_excluded=True)
        state = self.advance(state, 'pack_failed', **token)
        state = self.advance(state, 'fail', **token)
        state = self.advance(state, 'inspect', slot=1, readable=True)
        state = self.advance(state, 'certify', slot=1, source='new', certified=True, validated=True)
        self.assertTrue(policy.complete(state, 1, 'new'))
        self.assertTrue(policy.output_complete(state, 'whole-output'))
        self.assertEqual(state.slots[0], previous)
        after, accepted = step(state, 'adopt', incarnation=1, slot=1,
            source='new', output_key='current', validated=True)
        self.assertFalse(accepted)
        self.assertEqual(after, state)
        writes = state.operation
        state = self.advance(state, 'packed', slot=1, operation=writes,
                             clean=True, validated=True, reader_excluded=True)
        state = self.finish_graph(state, 1, 'new', 'current')
        self.assertTrue(policy.output_complete(state, 'current'))
        self.assertEqual(state.operation, writes)

    def test_clean_packing_observation_is_not_numerical_evidence(self):
        state = self.advance(policy.establish(1), 'observe_packing', slot=3,
                             operation=0, clean=True, reader_excluded=True)
        self.assertTrue(policy.packing_clean(state, 3))
        self.assertFalse(policy.complete(state, 3, 'any'))
        self.assertFalse(state.graph_valid)
        state = self.advance(state, 'observe_packing', slot=3,
                             operation=0, clean=False, reader_excluded=True)
        self.assertEqual(state.slots[3].packing, policy.PACK_PENDING)

    def test_stale_packing_receipts_cannot_clear_new_write_or_replacement(self):
        state = self.publish(policy.establish(1), 0, 'previous')
        old_operation = state.operation
        state = self.advance(state, 'reserve', slot=1, source='new', reader_excluded=True)
        state = self.advance(state, 'armed', slot=1, source='new', operation=state.operation,
                             validated=True, reader_excluded=True)
        for event in ('observe_packing', 'packed', 'pack_failed'):
            after, accepted = step(state, event, incarnation=1, slot=1, source='new',
                operation=old_operation, clean=True, validated=True, reader_excluded=True)
            self.assertFalse(accepted, event)
            self.assertEqual(after, state)
        state, _ = step(state, 'invalidate')
        self.assertTrue(all(slot.packing == policy.PACK_UNKNOWN for slot in state.slots))
        after, accepted = step(state, 'packed', incarnation=1, slot=1,
            operation=state.operation, clean=True, validated=True, reader_excluded=True)
        self.assertFalse(accepted)
        self.assertEqual(after, state)

    def test_packing_failure_does_not_invalidate_selected_numerical_output(self):
        state = self.publish(policy.establish(1), 0, 'previous')
        before = state
        state = self.advance(state, 'pack_failed', slot=0, operation=state.operation)
        self.assertTrue(policy.output_complete(state, 'whole-output'))
        self.assertEqual(state.slots[0].packing, policy.PACK_PENDING)
        self.assertEqual(state.slots[1:], before.slots[1:])
        self.assertEqual(state.output_key, before.output_key)

    def test_packing_readable_storage_preserves_active_graph_repair(self):
        state = self.publish(policy.establish(1), 0, 'previous')
        state = self.advance(state, 'graph_begin', slot=0, source='previous',
                             output_key='new-rows', reader_excluded=True)
        graph_token = dict(slot=0, source='previous', output_key='new-rows',
                           operation=state.graph_operation)
        state = self.advance(state, 'fallback', **graph_token, validated=True, reader_excluded=True)
        state = self.advance(state, 'graph_fail', **graph_token)
        prior = state
        state = self.advance(state, 'observe_packing', slot=0, operation=state.operation,
                             clean=True, reader_excluded=True)
        state = self.advance(state, 'pack_failed', slot=1, operation=state.operation)
        state = self.advance(state, 'packed', slot=1, operation=state.operation,
                             clean=True, validated=True, reader_excluded=True)
        self.assertTrue(state.graph_debt)
        self.assertEqual(state.graph_phase, policy.GRAPH_REPAIR)
        self.assertEqual(state.graph_operation, prior.graph_operation)
        self.assertEqual(state.graph_output, prior.graph_output)
        self.assertEqual(state.selected, prior.selected)
        self.assertEqual(state.slots[0], prior.slots[0])
        self.assertTrue(policy.complete(state, 0, 'previous'))
        self.assertFalse(state.slots[1].valid)
        self.assertEqual(state.slots[1].packing, policy.PACK_CLEAN)

    def test_matrix_only_commit_preserves_certified_bytes_and_write_sequence(self):
        state = self.publish(policy.establish(1), 0, 'payload')
        old_slots, old_operation = state.slots, state.operation
        state = self.finish_graph(state, 0, 'payload', 'new-endpoint-rows')
        self.assertEqual(state.slots, old_slots)
        self.assertEqual(state.operation, old_operation)
        self.assertTrue(policy.output_complete(state, 'new-endpoint-rows'))

    def test_rows_require_verified_fallback_and_graph_fail_needs_repair(self):
        state = self.publish(policy.establish(1), 0, 'payload')
        state = self.advance(state, 'graph_begin', slot=0, source='payload',
                             output_key='new-rows', reader_excluded=True)
        token = dict(slot=0, source='payload', output_key='new-rows', operation=state.graph_operation)
        unchanged, accepted = step(state, 'rows', incarnation=1, **token,
                                          validated=True, reader_excluded=True)
        self.assertFalse(accepted)
        self.assertEqual(unchanged, state)
        state = self.advance(state, 'graph_fail', **token)
        self.assertTrue(state.graph_debt)
        self.assertFalse(state.graph_valid)
        self.assertTrue(policy.complete(state, 0, 'payload'))
        state = self.advance(state, 'graph_repair', **token, validated=True, reader_excluded=True)
        self.assertFalse(state.graph_debt)
        self.assertTrue(state.graph_valid)

    def test_failed_recovery_finishes_target_without_claiming_old_graph_restored(self):
        state = self.advance(policy.establish(1, uncertain=True), 'inspect', slot=2, readable=True)
        state = self.advance(state, 'certify', slot=2, source='current', certified=True, validated=True)
        state = self.advance(state, 'observe_packing', slot=2, operation=state.operation,
                             clean=True, reader_excluded=True)
        state = self.advance(state, 'graph_begin', slot=2, source='current',
                             output_key='target', reader_excluded=True)
        token = dict(slot=2, source='current', output_key='target', operation=state.graph_operation)
        state = self.advance(state, 'fallback', **token, validated=True, reader_excluded=True)
        state = self.advance(state, 'graph_fail', **token)
        self.assertFalse(state.graph_previous_valid)
        self.assertTrue(state.graph_debt)
        slots, writes = state.slots, state.operation
        state = self.advance(state, 'adopt', slot=2, source='current', output_key='target', validated=True)
        self.assertTrue(policy.output_complete(state, 'target'))
        self.assertFalse(state.graph_debt)
        self.assertEqual(state.slots, slots)
        self.assertEqual(state.operation, writes)

    def test_fallback_only_commit_does_not_claim_exact_output(self):
        state = self.finish_graph(policy.establish(1), -1, 0)
        self.assertEqual(state.selected, -1)
        self.assertFalse(state.graph_valid)
        self.assertEqual(state.graph_phase, policy.GRAPH_IDLE)

    def test_layout_failure_requires_structural_repair(self):
        state = self.advance(policy.establish(1), 'inspect', slot=0, readable=False, layout_valid=False)
        for event in ('reserve', 'repair', 'certify'):
            after, accepted = step(state, event, incarnation=1, slot=0,
                source='payload', validated=True, certified=True, reader_excluded=True)
            self.assertFalse(accepted, event)
            self.assertEqual(after, state)

    def test_local_digest_mismatch_revokes_only_affected_output(self):
        state = self.publish(policy.establish(1), 0, 'payload')
        state = self.advance(state, 'inspect', slot=1, readable=True)
        state = self.advance(state, 'certify', slot=1, source='other', certified=True, validated=True)
        unaffected = state.slots[1:]
        state = self.advance(state, 'uncertify', slot=0)
        self.assertEqual(state.slots[1:], unaffected)
        self.assertFalse(state.slots[0].valid)
        self.assertFalse(state.slots[0].debt)
        self.assertFalse(state.graph_valid)
        self.assertEqual(state.selected, -1)

