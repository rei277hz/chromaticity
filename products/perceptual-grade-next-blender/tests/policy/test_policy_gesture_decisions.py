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

    def test_changed_auto_key_target_authorizes_keyframe_effect(self):
        state, _ = runtime.step(runtime.new(), runtime.Event(
            "press", window_id=1, undo_owner="native",
            frame=6.25, targets=(runtime.Target(10, "before"),)))
        token = runtime.current_gesture(state, 1)
        _state, effects = runtime.step(state, runtime.Event(
            "finish", window_id=1, gesture_token=token,
            observed=(runtime.Target(10, "after"),)))
        self.assertEqual(effects.actions, (
            runtime.Action("keyframe", gesture_token=token, node_id=10, frame=6.25),
            runtime.Action("refresh", node_id=10),
        ))

    def test_cancel_restores_pair_and_releases_without_keyframe_or_undo(self):
        state, _ = runtime.step(runtime.new(), runtime.Event(
            "press", window_id=1, undo_owner="adapter", frame=6.25,
            color_pair=True, targets=(runtime.Target(10, "before"),)))
        token = runtime.current_gesture(state, 1)
        state, _ = runtime.step(state, runtime.Event(
            "activate", window_id=1, gesture_token=token))
        moved, effects = runtime.step(state, runtime.Event(
            "edit_color_pair", window_id=1, gesture_token=token, color_values=(2.0, 0.5)))
        self.assertIs(moved, state)
        self.assertEqual(effects.actions, (
            runtime.Action("write_color_pair", gesture_token=token, color_values=(2.0, 0.5)),
        ))
        state, effects = runtime.step(state, runtime.Event(
            "cancel_color_pair", window_id=1, gesture_token=token,
            observed=(runtime.Target(10, "after"),)))
        self.assertEqual(effects.actions, (
            runtime.Action("restore_color_pair", gesture_token=token),
            runtime.Action("node_release", node_id=10),
        ))
        self.assertIsNone(effects.undo_window)
        self.assertIsNone(runtime.current_gesture(state, 1))

    def test_discard_pair_cancels_without_overwriting_destination_frame(self):
        state, _ = runtime.step(runtime.new(), runtime.Event(
            "press", window_id=1, undo_owner="adapter", color_pair=True,
            targets=(runtime.Target(10, "before"),)))
        token = runtime.current_gesture(state, 1)
        state, _ = runtime.step(state, runtime.Event(
            "activate", window_id=1, gesture_token=token))
        state, _ = runtime.step(state, runtime.Event(
            "edit_color_pair", window_id=1, gesture_token=token,
            color_values=(0.33, 0.44)))
        state, effects = runtime.step(state, runtime.Event(
            "discard_color_pair", window_id=1, gesture_token=token,
            observed=(runtime.Target(10, "after"),)))
        self.assertEqual(effects.actions, (runtime.Action("node_release", node_id=10),))
        self.assertIsNone(effects.undo_window)
        self.assertIsNone(runtime.current_gesture(state, 1))

    def test_native_observation_cannot_finish_color_edit(self):
        state, _ = runtime.step(runtime.new(), runtime.Event("window_seen", window_id=1))
        pending = runtime.pending_observer(state, 1)
        state, _ = runtime.step(state, runtime.Event(
            "press", window_id=1, undo_owner="adapter", color_pair=True,
            targets=(runtime.Target(10, "before"),)))
        token = runtime.current_gesture(state, 1)
        state, _ = runtime.step(state, runtime.Event(
            "activate", window_id=1, gesture_token=token))
        state, effects = runtime.step(state, runtime.Event(
            "observer_install_result", window_id=1, token=pending,
            success=True, gesture_token=token, latest="finish"))
        self.assertEqual(effects, runtime.Effects())
        for kind in ("press", "finish_requested"):
            self.assertEqual(runtime.step(state, runtime.Event(
                kind, window_id=1, token=pending, gesture_token=token,
            )), (state, runtime.Effects()))
        state, effects = runtime.step(state, runtime.Event(
            "window_gone", window_id=1, observed=(runtime.Target(10, "after"),)))
        self.assertEqual(effects.actions, (
            runtime.Action("restore_color_pair", gesture_token=token),
            runtime.Action("node_release", node_id=10),
        ))
        self.assertIsNone(effects.undo_window)


if __name__ == "__main__":
    unittest.main()
