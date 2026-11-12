"""Host-free safety traces for helper process and cleanup ownership."""

import unittest

from policy import helper as policy


def transition(state, kind, **values):
    return policy.step(state, policy.Event(kind, state.generation, **values))


class HelperPolicyTests(unittest.TestCase):
    def probing(self):
        state, _effects = policy.step(policy.new(), policy.Event("launch", 1, job_id=1))
        state, _effects = transition(state, "hello")
        return state

    def ready(self):
        state, _effects = transition(self.probing(), "probe_result", job_id=1, success=True)
        return state

    def test_cancelled_probe_cannot_admit_work_or_accept_late_success(self):
        for kind in ("cancel", "cancelled"):
            with self.subTest(kind=kind):
                state, effects = transition(self.probing(), kind, job_id=1,
                                            transport="channel")
                self.assertEqual(state.phase, "stopping")
                self.assertFalse(policy.admitting(state))
                self.assertEqual(effects.deadline_stage, "stopping")
                self.assertTrue(effects.send_shutdown)
                late = transition(state, "probe_result", job_id=1, success=True)
                self.assertEqual(late, (state, policy.Effects()))
                self.assertEqual(transition(state, "submit", job_id=2),
                                 (state, policy.Effects()))

    def test_cancel_before_hello_retains_probe_until_exit(self):
        state, _ = policy.step(policy.new(), policy.Event("launch", 1, job_id=1))
        state, effects = transition(state, "cancel", job_id=1)
        self.assertEqual(state.phase, "terminating")
        self.assertEqual(state.probe_id, 1)
        self.assertEqual(effects.deadline_stage, "terminating")
        self.assertTrue(effects.terminate)
        state, effects = transition(state, "exited", exit_code=-15, error="signal")
        self.assertEqual(state.phase, "retiring")
        self.assertTrue(effects.clear_deadline)
        self.assertIsNone(effects.publish_kind)
        self.assertEqual(effects.probe_publish_kind, "cancelled")
        self.assertEqual(effects.probe_publish_id, 1)
        self.assertEqual(effects.queue_kind, "cancel")
        self.assertTrue(effects.cleanup)
        self.assertIsNone(state.probe_id)

    def test_failure_is_published_before_cleanup_and_cannot_be_republished(self):
        state, _ = transition(self.ready(), "submit", job_id=2)
        state, _ = transition(state, "failure", error="worker failed")
        state, effects = transition(state, "exited", error="signal", exit_code=-15)
        self.assertTrue(effects.clear_deadline)
        self.assertEqual(effects.publish_kind, "failure")
        self.assertEqual(effects.publish_id, 2)
        self.assertEqual(effects.publish_error, "worker failed")
        self.assertEqual(effects.queue_kind, "fail")
        self.assertEqual(effects.queue_error, "worker failed")
        self.assertTrue(effects.cleanup)
        self.assertEqual(transition(state, "exited"), (state, policy.Effects()))
        state, effects = transition(state, "cleanup_result", error="unlink failed")
        self.assertEqual(state.phase, "retiring")
        self.assertEqual(state.error, "worker failed")
        self.assertEqual(effects, policy.Effects())
        self.assertEqual(transition(state, "poll", transport="channel"),
                         (state, policy.Effects()))
        state, effects = transition(state, "shutdown")
        self.assertTrue(effects.cleanup)
        state, effects = transition(state, "cleanup_result", success=True)
        self.assertEqual(state.phase, "closed")
        self.assertEqual(state.error, "worker failed")
        self.assertEqual(transition(state, "cleanup_result", success=True),
                         (state, policy.Effects()))

    def test_normal_cancellation_keeps_slot_until_acknowledgement(self):
        state, _ = transition(self.ready(), "submit", job_id=2)
        cancelled, effects = transition(state, "cancel", job_id=2)
        self.assertEqual(cancelled, state)
        self.assertEqual(effects.send_cancel_id, 2)
        state, effects = transition(cancelled, "cancelled", job_id=2, next_id=3)
        self.assertEqual(state.active_id, 3)
        self.assertEqual(effects.publish_kind, "cancelled")
        self.assertEqual(effects.publish_id, 2)
        self.assertEqual(effects.dispatch_id, 3)

    def test_terminal_phases_never_poll_any_transport(self):
        for phase in ("retiring", "failed", "closed"):
            state = policy.State(phase, 1, None, None, "failure", phase == "closed")
            for transport in (None, "listener", "channel"):
                self.assertEqual(transition(state, "poll", transport=transport),
                                 (state, policy.Effects()))

    def test_shutdown_deadlines_advance_once_and_ignore_old_stages(self):
        state, effects = transition(self.ready(), "shutdown", transport="channel")
        self.assertEqual(state.phase, "stopping")
        self.assertEqual(transition(state, "shutdown"), (state, policy.Effects()))
        self.assertEqual(transition(state, "timeout", stage="starting"),
                         (state, policy.Effects()))
        state, effects = transition(state, "timeout", stage="stopping")
        self.assertEqual(state.phase, "terminating")
        self.assertEqual(effects.deadline_stage, "terminating")
        self.assertTrue(effects.terminate)
        state, effects = transition(state, "timeout", stage="terminating")
        self.assertEqual(state.phase, "killing")
        self.assertEqual(effects.deadline_stage, "killing")
        self.assertTrue(effects.kill)
        state, effects = transition(state, "timeout", stage="killing")
        self.assertEqual(state.phase, "unretired")
        self.assertTrue(effects.clear_deadline)
        self.assertIsNotNone(policy.close_problem(state))
        self.assertEqual(transition(state, "shutdown"), (state, policy.Effects()))

    def test_eof_is_only_ignored_during_process_shutdown(self):
        state, effects = transition(self.ready(), "eof", error="unexpected EOF")
        self.assertEqual(state.phase, "terminating")
        self.assertEqual(state.error, "unexpected EOF")
        self.assertEqual(transition(state, "eof", error="later"),
                         (state, policy.Effects()))

    def test_successful_hello_ends_startup_deadline(self):
        state, _ = policy.step(policy.new(), policy.Event("launch", 1, job_id=1))
        state, effects = transition(state, "hello")
        self.assertTrue(effects.clear_deadline)
        self.assertEqual(effects.dispatch_id, 1)
        self.assertEqual(transition(state, "timeout", stage="starting"),
                         (state, policy.Effects()))

    def test_stale_generation_cannot_mutate_lifecycle(self):
        state = self.probing()
        for event in (policy.Event("shutdown", 0), policy.Event("exited", 0),
                      policy.Event("probe_result", 0, job_id=1, success=True)):
            self.assertEqual(policy.step(state, event), (state, policy.Effects()))


if __name__ == "__main__":
    unittest.main()
