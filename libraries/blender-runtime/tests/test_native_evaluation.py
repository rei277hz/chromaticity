"""Ordered native observations retain exact leases until validated retirement."""
from dataclasses import replace
import unittest

from color_tools.blender_runtime import native_evaluation as policy


class NativeEvaluationTests(unittest.TestCase):
    def setUp(self):
        self.state = policy.new()

    def event(self, kind, **values):
        state = self.state
        arguments = dict(generation=state.generation, revision=state.revision + 1)
        arguments.update(values)
        self.state, effects = policy.step(self.state, policy.Event(kind, **arguments))
        return effects

    def begin(self):
        state = self.state
        lease = state.serial + 1
        self.assertTrue(self.event('begin', lease=lease,
                                   proposed_tokens=state.tokens + (lease,)).accepted)
        return lease

    def finish(self, lease):
        state = self.state
        index = state.tokens.index(lease)
        return self.event('finish', lease=lease, index=index, validated=True,
                          proposed_tokens=state.tokens[:index] + state.tokens[index + 1:])

    def ready(self, **values):
        state = self.state
        arguments = dict(generation=state.generation, revision=state.revision, native_busy=False)
        arguments.update(values)
        return policy.available(self.state, **arguments)

    def test_overlapping_and_nested_readers_release_independently(self):
        first, nested, other = self.begin(), self.begin(), self.begin()
        self.assertFalse(self.ready())
        self.assertTrue(self.finish(nested).accepted)
        self.assertEqual(self.state.tokens, (first, other))
        self.assertFalse(self.ready())
        self.assertTrue(self.finish(first).accepted)
        self.assertFalse(self.ready())
        self.assertTrue(self.finish(other).accepted)
        self.assertTrue(self.ready())

    def test_pending_ingress_and_native_jobs_revoke_ready_snapshot(self):
        self.assertTrue(self.ready())
        self.assertFalse(self.ready(revision=1))
        self.assertFalse(self.ready(generation=2))
        self.assertFalse(self.ready(native_busy=True))

    def test_unmatched_and_duplicate_completions_advance_without_release(self):
        first, second = self.begin(), self.begin()
        self.assertTrue(self.finish(first).accepted)
        revision = self.state.revision
        for lease in (first, 99999):
            effects = self.event('finish', lease=lease, index=0, proposed_tokens=(), validated=True)
            self.assertTrue(effects.consumed)
            self.assertFalse(effects.accepted)
            self.assertEqual(self.state.tokens, (second,))
            self.assertFalse(self.state.failed)
        self.assertEqual(self.state.revision, revision + 2)
        self.assertTrue(self.finish(second).accepted)
        self.assertTrue(self.ready())

    def test_out_of_order_and_replayed_observations_cannot_change_state(self):
        self.begin()
        before = self.state
        for revision in (before.revision, before.revision + 2, 0):
            effects = self.event('replace', revision=revision, validated=True)
            self.assertFalse(effects.consumed)
            self.assertEqual(self.state, before)

    def test_replacement_consumes_late_old_generation_without_new_lease_loss(self):
        old = self.begin()
        old_generation = self.state.generation
        self.assertTrue(self.event('replace', validated=True).accepted)
        self.assertEqual(self.state.generation, old_generation + 1)
        current = self.begin()
        before = self.state
        effects = self.event('finish', generation=old_generation, lease=old,
                             index=0, proposed_tokens=(), validated=True)
        self.assertTrue(effects.consumed)
        self.assertFalse(effects.accepted)
        self.assertEqual(self.state, replace(before, revision=before.revision + 1))
        self.assertGreater(current, old)
        self.assertTrue(self.finish(current).accepted)
        self.assertTrue(self.ready())

    def test_unvalidated_or_inexact_release_fences_without_dropping_leases(self):
        first, second = self.begin(), self.begin()
        before = self.state
        effects = self.event('finish', lease=first, index=0, proposed_tokens=(second,))
        self.assertFalse(effects.accepted)
        self.assertTrue(self.state.failed)
        self.assertEqual(self.state.tokens, before.tokens)
        self.assertTrue(self.finish(first).accepted)
        self.assertTrue(self.finish(second).accepted)
        self.assertFalse(self.ready())
        self.assertFalse(self.event('replace', validated=False).accepted)
        self.assertFalse(self.ready())
        self.assertTrue(self.event('replace', validated=True).accepted)
        self.assertTrue(self.ready())

    def test_candidate_cannot_remove_other_readers_or_reuse_a_lease(self):
        first, second = self.begin(), self.begin()
        for values in (
                dict(kind='finish', lease=first, index=0, proposed_tokens=(), validated=True),
                dict(kind='finish', lease=first, index=1, proposed_tokens=(second,), validated=True),
                dict(kind='begin', lease=second, proposed_tokens=(first, second, second)),
                dict(kind='begin', lease=second + 1, proposed_tokens=(second + 1,))):
            effects = self.event(**values)
            self.assertFalse(effects.accepted)
            self.assertTrue(self.state.failed)
            self.assertEqual(self.state.tokens, (first, second))

    def test_close_keeps_lease_debt_and_cannot_reopen(self):
        lease = self.begin()
        self.assertTrue(self.event('close').accepted)
        self.assertFalse(self.event('replace', validated=True).accepted)
        self.assertFalse(self.event('finish', lease=lease, index=0,
                                    proposed_tokens=(), validated=True).accepted)
        self.assertEqual(self.state.tokens, (lease,))
        self.assertFalse(self.ready())

    def test_explicit_failure_preserves_exact_ledger(self):
        lease = self.begin()
        self.assertTrue(self.event('fail').accepted)
        self.assertEqual(self.state.tokens, (lease,))
        self.assertFalse(self.ready())

    def test_large_ledgers_preserve_exact_append_and_middle_removal(self):
        for count in (0, 1, 65, 1025):
            before = tuple(range(1, count + 1))
            original = policy.State(serial=count, tokens=before)
            after, effects = policy.step(original, policy.Event(
                'begin', revision=1, lease=count + 1,
                proposed_tokens=before + (count + 1,)))
            self.assertTrue(effects.accepted)
            self.assertEqual(after.tokens, before + (count + 1,))
            for index in {0, count // 2, count - 1}:
                if 0 <= index < count:
                    tokens = before[:index] + before[index + 1:]
                    after, effects = policy.step(original, policy.Event(
                        'finish', revision=1, lease=before[index], index=index,
                        proposed_tokens=tokens, validated=True))
                    self.assertTrue(effects.accepted)
                    self.assertEqual(after.tokens, tokens)
                    retained, effects = policy.step(original, policy.Event(
                        'finish', revision=1, lease=before[index], index=index,
                        proposed_tokens=(), validated=True))
                    if count != 1:
                        self.assertFalse(effects.accepted)
                        self.assertEqual(retained.tokens, before)

    def test_missing_retirement_index_retains_exact_ledger(self):
        lease = self.begin()
        effects = self.event('finish', lease=lease, validated=True)
        self.assertFalse(effects.accepted)
        self.assertTrue(self.state.failed)
        self.assertEqual(self.state.tokens, (lease,))


if __name__ == '__main__':
    unittest.main()
