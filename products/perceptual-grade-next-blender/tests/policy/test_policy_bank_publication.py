import unittest

from policy.bank_publication import Effects, Event, State, new, step


class BankPublicationPolicyTests(unittest.TestCase):
    def test_begin_only_authorizes_the_valid_inactive_bank(self):
        for active in (0, 1):
            inactive = 1 - active
            self.assertEqual(
                step(new(), Event("begin", active_bank=active,
                                  candidate_bank=inactive)),
                (State("stage", active, inactive), Effects("stage", inactive)),
            )
        for active, candidate in ((0, 0), (1, 1), (0, 2), (-1, 1), (None, 1)):
            with self.subTest(active=active, candidate=candidate):
                state, effects = step(new(), Event(
                    "begin", active_bank=active, candidate_bank=candidate,
                ))
                self.assertEqual(state.phase, "fail")
                self.assertEqual(effects.action, "fail_closed")

    def test_selector_change_requires_clean_staging_receipt(self):
        state = State("stage", 0, 1)
        for clean, failed in ((False, False), (True, True)):
            with self.subTest(clean=clean, failed=failed):
                next_state, effects = step(state, Event(
                    "staged", clean=clean, failed=failed,
                ))
                self.assertEqual((next_state.phase, effects.action), ("fail", "fail_closed"))
                self.assertEqual(effects.bank, 0)
        next_state, effects = step(state, Event("staged", clean=True))
        self.assertEqual(next_state, State("select", 0, 1))
        self.assertEqual(effects, Effects("select", 1))

    def test_delivery_requires_selector_readback_for_candidate(self):
        state = State("select", 0, 1)
        self.assertEqual(step(state, Event("selected", selected_bank=0)),
                         (State("restore_selector", 0, 1), Effects("restore_selector", 0)))
        self.assertEqual(step(state, Event("selected", selected_bank=1, failed=True)),
                         (State("restore_selector", 0, 1), Effects("restore_selector", 0)))
        self.assertEqual(step(state, Event("selected", selected_bank=1)),
                         (State("deliver", 0, 1), Effects("deliver", 1)))

    def test_failed_delivery_restores_original_bank_and_fails_closed(self):
        state, effects = step(State("deliver", 0, 1), Event("delivered", failed=True))
        self.assertEqual((state, effects),
                         (State("restore_selector", 0, 1), Effects("restore_selector", 0)))
        state, effects = step(state, Event("restored", failed=True))
        self.assertEqual((state, effects),
                         (State("fail", 0, 1), Effects("fail_closed", 0)))
        self.assertEqual(step(state, Event("closed", failed=True)),
                         (state, Effects("fail_closed", 0)))
        self.assertEqual(step(state, Event("closed")),
                         (State("terminal"), Effects()))

    def test_clean_candidate_commits_before_delivery(self):
        state = new()
        sequence = (
            (Event("begin", active_bank=0, candidate_bank=1), "stage", 1),
            (Event("staged", clean=True), "select", 1),
            (Event("selected", selected_bank=1), "deliver", 1),
            (Event("delivered"), None, None),
        )
        for event, action, bank in sequence:
            state, effects = step(state, event)
            self.assertEqual(effects, Effects(action, bank))
        self.assertEqual(state, State("terminal"))

    def test_terminal_receipts_are_inert(self):
        for event in (Event("begin", active_bank=0, candidate_bank=1),
                      Event("staged", clean=True), Event("selected", selected_bank=1),
                      Event("delivered", failed=True), Event("closed")):
            self.assertEqual(step(State("terminal"), event),
                             (State("terminal"), Effects()))


if __name__ == "__main__":
    unittest.main()
