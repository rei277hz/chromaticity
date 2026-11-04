"""Scalar lifecycle regressions and their actual coordinator consumers."""
import unittest
from unittest.mock import patch

from color_tools.policy import gesture as policy
from color_tools.runtime import gesture_coordinator as runtime


class GestureDecisionTests(unittest.TestCase):
    def test_lost_observer_and_failed_replacement_cannot_resurrect_old_token(self):
        state, effects = policy.step(policy.State(5, 3, 5), policy.Event("lost", token=3))
        self.assertEqual((state, effects), (policy.State(5, None, 5), policy.Effects()))
        state, effects = policy.step(state, policy.Event("installed", token=5, success=False))
        self.assertEqual(state, policy.State(5))
        self.assertTrue(effects.report_failure)
        state, effects = policy.step(state, policy.Event("window_seen"))
        self.assertEqual((state, effects),
                         (policy.State(6, None, 6), policy.Effects(invoke_token=6)))

    def armed(self):
        state, _ = runtime.step(runtime.new(), runtime.Event(
            "press", window_id=1, undo_owner="adapter", targets=(runtime.Target(10, "before"),)))
        return state, runtime.current_gesture(state, 1)

    def test_coordinator_consumes_activation_and_release_permissions(self):
        state, token = self.armed()
        event = runtime.Event("activate", window_id=1, gesture_token=token)
        with patch.object(policy, "activation_allowed", return_value=False) as permission:
            self.assertEqual(runtime.step(state, event), (state, runtime.Effects()))
            permission.assert_called_once_with(token, token, "armed")
        state, _ = runtime.step(state, event)
        with patch.object(policy, "participant_finish", return_value=None) as permission:
            _, effects = runtime.step(state, runtime.Event(
                "finish", window_id=1, gesture_token=token,
                observed=(runtime.Target(10, "after"),)))
            self.assertEqual(effects, runtime.Effects())
            permission.assert_called_once_with("active", True, True, False)

    def test_coordinator_checkpoint_requires_scalar_permission(self):
        state, token = self.armed()
        with patch.object(policy, "manual_undo", return_value=False) as permission:
            _, effects = runtime.step(state, runtime.Event(
                "finish", window_id=1, gesture_token=token,
                observed=(runtime.Target(10, "after"),)))
            self.assertEqual(effects.actions, (runtime.Action("refresh", node_id=10),))
            self.assertIsNone(effects.undo_window)
            permission.assert_called_once_with("adapter", True)


if __name__ == "__main__":
    unittest.main()
