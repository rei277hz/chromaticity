import unittest

from color_tools.perceptual_grade_next_core.workflow.preflight import (
    PreflightEvent,
    new_preflight,
    preflight_ready,
    preflight_step,
)


def ev(state, kind, **values):
    fields = {
        "owner": state.owner,
        "incarnation": state.incarnation,
        "source_revision": state.source_revision,
        "source_id": state.source_id,
        "check_id": state.active_check_id,
    }
    fields.update(values)
    return PreflightEvent(kind, **fields)


class BakePreflightTests(unittest.TestCase):
    def _open(self):
        state, accepted = preflight_step(
            new_preflight(), PreflightEvent("open", owner=7, incarnation=1)
        )
        self.assertTrue(accepted)
        return state

    def _checking(self, source=11, check=4):
        state = self._open()
        state, accepted = preflight_step(state, ev(state, "hint"))
        self.assertTrue(accepted)
        state, accepted = preflight_step(state, ev(state, "observed", source_id=source))
        self.assertTrue(accepted)
        state, accepted = preflight_step(state, ev(state, "start", check_id=check))
        self.assertTrue(accepted)
        return state

    def test_completion_requires_exact_check_and_source(self):
        state = self._checking()
        stale, accepted = preflight_step(
            state, ev(state, "complete", source_revision=99, allowed=True)
        )
        self.assertFalse(accepted)
        self.assertEqual(stale, state)
        state, accepted = preflight_step(state, ev(state, "complete", allowed=True))
        self.assertTrue(accepted)
        self.assertTrue(preflight_ready(state))

    def test_a_b_a_gets_new_logical_source_revisions(self):
        state = self._open()
        for source, revision in ((11, 1), (22, 2), (11, 3)):
            state, _ = preflight_step(state, ev(state, "hint"))
            state, accepted = preflight_step(state, ev(state, "observed", source_id=source))
            self.assertTrue(accepted)
            self.assertEqual(state.source_revision, revision)

    def test_source_change_waits_for_exact_old_check_to_retire(self):
        state = self._checking(source=11, check=4)
        state, _ = preflight_step(state, ev(state, "hint"))
        state, accepted = preflight_step(state, ev(state, "observed", source_id=22))
        self.assertTrue(accepted)
        self.assertEqual(state.active_check_id, 4)
        self.assertEqual(state.source_revision, 2)
        stale_receipt = ev(
            state,
            "complete",
            source_revision=state.active_source_revision,
            source_id=state.active_source_id,
            check_id=state.active_check_id,
            allowed=True,
        )
        state, accepted = preflight_step(state, stale_receipt)
        self.assertTrue(accepted)
        self.assertEqual(state.verdict, "CHECKING")
        self.assertEqual(state.active_check_id, 0)
        state, accepted = preflight_step(state, ev(state, "start", check_id=5))
        self.assertTrue(accepted)
        self.assertEqual(state.active_source_revision, 2)
        self.assertEqual(state.active_source_id, 22)

    def test_equal_hint_and_observation_do_not_retry_failed_source(self):
        state = self._checking(source=11, check=4)
        state, _ = preflight_step(state, ev(state, "fail", reason="reader"))
        state, accepted = preflight_step(state, ev(state, "hint"))
        self.assertTrue(accepted)
        state, accepted = preflight_step(state, ev(state, "observed", source_id=11))
        self.assertTrue(accepted)
        self.assertEqual(state.verdict, "FAILED")
        self.assertEqual(state.active_check_id, 0)

    def test_retry_is_explicit_and_old_receipt_cannot_settle_new_check(self):
        state = self._checking(source=11, check=4)
        state, _ = preflight_step(state, ev(state, "fail"))
        state, accepted = preflight_step(state, ev(state, "retry", check_id=5))
        self.assertTrue(accepted)
        stale, accepted = preflight_step(state, ev(state, "complete", check_id=4, allowed=True))
        self.assertFalse(accepted)
        self.assertEqual(stale, state)
        state, accepted = preflight_step(state, ev(state, "complete", allowed=False))
        self.assertTrue(accepted)
        self.assertEqual(state.verdict, "BLOCKED")

    def test_close_fences_late_receipts_and_new_incarnation_reopens_unknown(self):
        state = self._checking()
        state, accepted = preflight_step(state, ev(state, "close"))
        self.assertTrue(accepted)
        late, accepted = preflight_step(state, ev(state, "complete", allowed=True))
        self.assertTrue(accepted)
        self.assertEqual(late.verdict, "CLOSED")
        self.assertEqual(late.active_check_id, 0)
        reopened, accepted = preflight_step(
            late, PreflightEvent("open", owner=7, incarnation=2)
        )
        self.assertTrue(accepted)
        self.assertEqual(reopened.verdict, "UNKNOWN")


if __name__ == "__main__":
    unittest.main()
