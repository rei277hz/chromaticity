import unittest

from color_tools.features.grade.policy.bank_publication import (
    Effects, Event, State, finish_save_packing, new,
    request_save_packing, step,
)


class BankPublicationPolicyTests(unittest.TestCase):
    def test_begin_requires_authorized_admission_and_valid_active_bank(self):
        for event in (
            Event("begin", active_bank=0, admitted=False, active_valid=True),
            Event("begin", active_bank=2, admitted=True, active_valid=True),
        ):
            with self.subTest(event=event):
                self.assertEqual(step(new(), event),
                                 (State("fail"), Effects("fail_closed")))

    def test_begin_derives_inactive_bank(self):
        for active in (0, 1):
            inactive = 1 - active
            self.assertEqual(
                step(new(), Event("begin", active_bank=active,
                                  admitted=True, active_valid=True)),
                (State("stage", active), Effects("stage", inactive)),
            )

    def test_selector_change_requires_clean_staging_receipt(self):
        state = State("stage", 0)
        for clean, failed in ((False, False), (True, True)):
            with self.subTest(clean=clean, failed=failed):
                next_state, effects = step(state, Event(
                    "staged", clean=clean, failed=failed,
                ))
                self.assertEqual((next_state.phase, effects.action),
                                 ("fail", "fail_closed"))
                self.assertEqual(effects.bank, 0)
        next_state, effects = step(state, Event("staged", clean=True))
        self.assertEqual(next_state, State("select", 0))
        self.assertEqual(effects, Effects("select", 1))

    def test_delivery_requires_selector_readback_for_candidate(self):
        state = State("select", 0)
        self.assertEqual(step(state, Event("selected", selected_bank=0)),
                         (State("restore_selector", 0),
                          Effects("restore_selector", 0)))
        self.assertEqual(step(state, Event("selected", selected_bank=1, failed=True)),
                         (State("restore_selector", 0),
                          Effects("restore_selector", 0)))
        self.assertEqual(step(state, Event("selected", selected_bank=1)),
                         (State("deliver", 0), Effects("deliver", 1)))

    def test_failed_delivery_restores_original_bank_and_fails_closed(self):
        state, effects = step(State("deliver", 0), Event("delivered", failed=True))
        self.assertEqual((state, effects),
                         (State("restore_selector", 0),
                          Effects("restore_selector", 0)))
        state, effects = step(state, Event("restored", failed=True))
        self.assertEqual((state, effects),
                         (State("fail", 0), Effects("fail_closed", 0)))
        state, effects = step(state, Event("closed", failed=True))
        self.assertEqual((state, effects),
                         (State("fail", 0, close_retried=True),
                          Effects("fail_closed", 0)))
        self.assertEqual(step(state, Event("closed", failed=True)),
                         (State("terminal"), Effects(outcome="indeterminate")))

    def test_clean_candidate_commits_only_on_delivery_receipt(self):
        state, effects = step(new(), Event("begin", active_bank=0,
                                           admitted=True, active_valid=True))
        self.assertEqual(effects, Effects("stage", 1))
        state, effects = step(state, Event("staged", clean=True))
        self.assertEqual(effects, Effects("select", 1))
        state, effects = step(state, Event("selected", selected_bank=1))
        self.assertEqual(effects, Effects("deliver", 1))
        state, effects = step(state, Event("delivered"))
        self.assertEqual((state, effects),
                         (State("terminal"), Effects(outcome="committed")))

    def test_damaged_active_bank_closes_before_repair(self):
        state, effects = step(new(), Event(
            "begin", active_bank=0, admitted=True, active_valid=False,
        ))
        self.assertEqual((state, effects),
                         (State("repair_gate", 0), Effects("fail_closed", 0)))

        state, effects = step(state, Event("closed", failed=True))
        self.assertEqual((state, effects),
                         (State("repair_gate", 0, close_retried=True),
                          Effects("fail_closed", 0)))
        state, effects = step(state, Event("closed"))
        self.assertEqual((state, effects), (State("stage", 0), Effects("repair", 1)))
        state, effects = step(state, Event("staged", clean=False))
        self.assertEqual((state, effects), (State("fail", 0), Effects("fail_closed", 0)))

    def test_repair_and_final_closure_have_independent_retry_limits(self):
        state, _ = step(new(), Event("begin", active_bank=1,
                                    admitted=True, active_valid=False))
        state, _ = step(state, Event("closed", failed=True))
        state, effects = step(state, Event("closed"))
        self.assertEqual(effects, Effects("repair", 0))
        state, effects = step(state, Event("staged", clean=False))
        self.assertEqual(effects, Effects("fail_closed", 1))
        state, effects = step(state, Event("closed", failed=True))
        self.assertEqual(effects, Effects("fail_closed", 1))
        state, effects = step(state, Event("closed"))
        self.assertEqual((state, effects),
                         (State("terminal"), Effects(outcome="failed_closed")))

    def test_save_packing_only_repairs_dirty_generated_images(self):
        for generated, dirty in ((False, False), (False, True),
                                 (True, False), (True, True)):
            self.assertEqual(request_save_packing(generated, dirty),
                             generated and dirty)

    def test_save_packing_requires_clean_receipt_and_preserves_native_error(self):
        self.assertIsNone(finish_save_packing(True, None))
        self.assertEqual(finish_save_packing(True, "native failure"),
                         "native failure")
        self.assertEqual(finish_save_packing(False, "native failure"),
                         "native failure")
        self.assertEqual(finish_save_packing(False, None),
                         "Grade parameter image could not be packed")

    def test_terminal_receipts_are_inert(self):
        for event in (Event("begin", active_bank=0, admitted=True, active_valid=True),
                      Event("staged", clean=True), Event("selected", selected_bank=1),
                      Event("delivered", failed=True), Event("closed")):
            self.assertEqual(step(State("terminal"), event),
                             (State("terminal"), Effects()))


if __name__ == "__main__":
    unittest.main()
