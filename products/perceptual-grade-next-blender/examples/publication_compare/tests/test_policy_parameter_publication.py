import unittest

from policy.parameter_publication import (
    Effects, Event, State, candidate_effect, new, retirement_effect, step,
)


class ParameterPublicationPolicyTests(unittest.TestCase):
    def test_pool_allocation_is_bounded_and_exposed_candidates_cannot_be_reused(self):
        for count in range(5):
            self.assertEqual(candidate_effect(count, False, False),
                             Effects("allocate") if count < 3 else Effects())
            self.assertEqual(candidate_effect(count, True, False), Effects("reuse"))
            self.assertEqual(candidate_effect(count, True, True), Effects())

    def test_retirement_requires_quiescence_and_no_native_or_fake_users(self):
        for quiescent in (False, True):
            for users in (0, 1, 5):
                for protected in (False, True):
                    with self.subTest(quiescent=quiescent, users=users, protected=protected):
                        expected = Effects("remove") if quiescent and users == 0 and not protected else Effects()
                        self.assertEqual(retirement_effect(True, quiescent, False, False,
                                                           users, protected), expected)
        for current, candidate in ((True, False), (False, True)):
            self.assertEqual(retirement_effect(True, True, current, candidate, 0, False), Effects())
        self.assertEqual(retirement_effect(False, False, False, False, 0, False), Effects("evict"))

    def test_complete_candidate_precedes_snapshot_binding_commit_and_delivery(self):
        state = new()
        for event, action in ((Event(), "stage"),
                              (Event(clean=True), "snapshot"),
                              (Event(), "bind"),
                              (Event(), "commit"),
                              (Event(), "activate"),
                              (Event(), "deliver"),
                              (Event(), "retire"),
                              (Event(), None)):
            state, effects = step(state, event)
            self.assertEqual(effects.action, action)
        self.assertEqual(state, State("terminal"))

    def test_dirty_candidate_and_snapshot_failure_never_bind(self):
        for phase, event in (("stage", Event()), ("stage", Event(failed=True, clean=True)),
                             ("snapshot", Event(failed=True))):
            self.assertEqual(step(State(phase), event), (State("fail"), Effects("fail")))

    def test_partial_binding_metadata_and_delivery_failures_restore_every_component(self):
        for phase in ("bind", "commit", "activate", "deliver"):
            with self.subTest(phase=phase):
                state, effects = step(State(phase), Event(failed=True))
                self.assertEqual(effects.action, "restore_bindings")
                # A failure in one restore must not suppress the other restores.
                for action in ("restore_metadata", "restore_resource", "fail", "retire", None):
                    state, effects = step(state, Event(failed=True))
                    self.assertEqual(effects.action, action)
                self.assertEqual(state, State("terminal"))

    def test_terminal_receipts_are_inert(self):
        for event in (Event(), Event(failed=True), Event(clean=True)):
            self.assertEqual(step(State("terminal"), event), (State("terminal"), Effects()))


if __name__ == "__main__":
    unittest.main()
