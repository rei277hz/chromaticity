"""Adversarial observation ordering for native and adapter-owned gestures."""
import unittest

from color_tools.runtime import gesture_coordinator as p


class GesturePolicyTests(unittest.TestCase):
    def setUp(self):
        self.state = p.new()

    def send(self, kind, **kwargs):
        self.state, effects = p.step(self.state, p.Event(kind, **kwargs))
        self.effects = effects
        return effects.actions

    def observer(self, window=1):
        actions = self.send("window_seen", window_id=window)
        self.assertEqual([a.kind for a in actions], ["invoke_observer"])
        token = p.pending_observer(self.state, window)
        self.send("observer_install_result", window_id=window, token=token, success=True)
        return token

    def press(self, window=1, owner="native", targets=None, observer=None):
        if targets is None:
            targets = (p.Target(10, "before"),)
        self.send("press", window_id=window, token=observer, x=100, y=200,
                  undo_owner=owner, targets=targets)
        return p.current_gesture(self.state, window)

    def test_replacement_preserves_other_windows_and_invalid_indices(self):
        self.press(window=1)
        self.press(window=2)
        gestures = self.state.gestures
        replacement = p.Gesture(3, 9, "active", 0, 0, "native", ())
        self.assertEqual(p.replace_gesture(gestures, 0, replacement),
                         (replacement, gestures[1]))
        self.assertEqual(p.replace_gesture(gestures, 1, replacement),
                         (gestures[0], replacement))
        for index in (-1, 2):
            self.assertEqual(p.replace_gesture(gestures, index, replacement), gestures)
        self.assertEqual(p.replace_gesture((), 0, replacement), ())

    def test_removal_preserves_other_records_and_missing_keys(self):
        targets = (p.Target(10, "before"), p.Target(20, None), p.Target(30, "after"))
        observers = (p.Observer(10, 1, None), p.Observer(20, 2, 4), p.Observer(30, 3, None))
        gestures = tuple(p.Gesture(window, window, "armed", 0, 0, "native", targets)
                         for window in (10, 20, 30))
        for remove, records in ((p.without_target, targets),
                                (p.without_observer, observers),
                                (p.without_gesture, gestures)):
            for key, expected in ((10, (records[1], records[2])),
                                  (20, (records[0], records[2])),
                                  (30, (records[0], records[1])),
                                  (99, records)):
                with self.subTest(remove=remove.__name__, key=key):
                    self.assertEqual(remove(records, key), expected)
            self.assertEqual(remove((), 10), ())

    def test_real_handoff_move_deferred_finish_never_pushes_manual_undo(self):
        observer = self.observer()
        token = self.press(observer=observer)
        self.send("handoff_due", window_id=1, token=observer, gesture_token=token)
        replacement = p.pending_observer(self.state, 1)
        self.assertEqual(p.current_observer(self.state, 1), observer)
        actions = self.send("observer_install_result", window_id=1, token=replacement,
                            gesture_token=token, success=True, latest="move", x=103, y=200)
        self.assertEqual([a.kind for a in actions], ["node_begin"])
        self.assertTrue(p.active_for(self.state, 10))
        actions = self.send("finish_requested", window_id=1, token=replacement,
                            gesture_token=token)
        self.assertEqual([a.kind for a in actions], ["schedule_finish"])
        self.assertTrue(p.active_for(self.state, 10))
        self.assertEqual(self.send("finish_requested", window_id=1, token=replacement,
                                   gesture_token=token), ())
        actions = self.send("finish_observed", window_id=1, gesture_token=token,
                            observed=(p.Target(10, "after"),))
        self.assertEqual([a.kind for a in actions], ["node_release"])
        self.assertFalse(p.active_for(self.state, 10))
        self.assertIsNone(self.effects.undo_window)
        self.assertEqual(self.send("finish_observed", window_id=1, gesture_token=token,
                                   observed=(p.Target(10, "after"),)), ())

    def test_quick_release_observed_during_installation(self):
        observer = self.observer()
        token = self.press(observer=observer)
        self.send("handoff_due", window_id=1, token=observer, gesture_token=token)
        candidate = p.pending_observer(self.state, 1)
        actions = self.send("observer_install_result", window_id=1, token=candidate,
                            gesture_token=token, success=True, latest="finish")
        self.assertEqual([a.kind for a in actions], ["schedule_finish"])
        self.assertEqual(p.gesture_phase(self.state, 1), "finishing_armed")
        actions = self.send("finish_observed", window_id=1, gesture_token=token,
                            observed=(p.Target(10, "after"),))
        self.assertEqual([a.kind for a in actions], ["refresh"])

    def test_failed_install_preserves_old_observer_and_gesture(self):
        observer = self.observer()
        token = self.press(observer=observer)
        self.send("handoff_due", window_id=1, token=observer, gesture_token=token)
        candidate = p.pending_observer(self.state, 1)
        self.send("observer_install_result", window_id=1, token=candidate, success=False)
        self.assertEqual(p.current_observer(self.state, 1), observer)
        self.assertEqual(p.current_gesture(self.state, 1), token)
        self.assertIsNone(p.pending_observer(self.state, 1))
        before = self.state
        self.assertEqual(self.send("observer_install_result", window_id=1,
                                   token=candidate, success=True, latest="finish",
                                   gesture_token=token), ())
        self.assertEqual(self.state, before)

    def test_duplicate_ack_cannot_replay_or_remove_committed_observer(self):
        observer = self.observer()
        token = self.press(observer=observer)
        self.send("handoff_due", window_id=1, token=observer, gesture_token=token)
        candidate = p.pending_observer(self.state, 1)
        self.send("observer_install_result", window_id=1, token=candidate, success=True)
        before = self.state
        for success in (True, False):
            self.assertEqual(self.send("observer_install_result", window_id=1,
                                       token=candidate, success=success, latest="finish",
                                       gesture_token=token), ())
            self.assertEqual(self.state, before)
        self.assertEqual(self.send("observer_lost", window_id=1, token=observer), ())

    def test_lost_observer_and_failed_candidate_retry_without_resurrection(self):
        observer = self.observer()
        token = self.press(observer=observer)
        self.send("handoff_due", window_id=1, token=observer, gesture_token=token)
        candidate = p.pending_observer(self.state, 1)
        self.send("observer_lost", window_id=1, token=observer)
        self.send("observer_install_result", window_id=1, token=candidate, success=False)
        self.assertIsNone(p.current_observer(self.state, 1))
        actions = self.send("window_seen", window_id=1)
        self.assertEqual([a.kind for a in actions], ["invoke_observer"])
        self.assertNotIn(p.pending_observer(self.state, 1), (observer, candidate))

    def test_old_observer_remains_admitted_until_ack(self):
        observer = self.observer()
        token = self.press(observer=observer)
        self.send("handoff_due", window_id=1, token=observer, gesture_token=token)
        actions = self.send("move", window_id=1, token=observer, gesture_token=token,
                            x=104, y=200)
        self.assertEqual([a.kind for a in actions], ["node_begin"])

    def test_observer_loss_waits_for_a_fresh_live_window_observation(self):
        observer = self.observer()
        self.assertEqual(self.send("observer_lost", window_id=1, token=observer), ())
        self.assertIsNone(p.current_observer(self.state, 1))
        self.assertIsNone(p.pending_observer(self.state, 1))
        self.assertEqual(self.send("observer_lost", window_id=1, token=observer), ())
        actions = self.send("window_seen", window_id=1)
        self.assertEqual([action.kind for action in actions], ["invoke_observer"])
        self.assertGreater(p.pending_observer(self.state, 1), observer)

    def test_stale_input_cannot_finish_new_gesture(self):
        observer = self.observer()
        old = self.press(observer=observer)
        current = self.press(observer=observer)
        before = self.state
        self.assertEqual(self.send("finish_requested", window_id=1, token=observer,
                                   gesture_token=old), ())
        self.assertEqual(self.state, before)
        self.assertEqual(p.current_gesture(self.state, 1), current)

    def test_press_during_installation_reissues_handoff_for_new_gesture(self):
        observer = self.observer()
        old = self.press(observer=observer)
        self.send("handoff_due", window_id=1, token=observer, gesture_token=old)
        pending = p.pending_observer(self.state, 1)
        current = self.press(observer=observer)
        actions = self.send("observer_install_result", window_id=1, token=pending,
                            success=True, gesture_token=old, latest="finish")
        self.assertEqual(actions, (p.Action("schedule_handoff", 1, pending, current),))
        self.assertEqual(p.gesture_phase(self.state, 1), "armed")
        self.assertEqual(self.send("handoff_due", window_id=1, token=observer,
                                   gesture_token=current), ())
        actions = self.send("handoff_due", window_id=1, token=pending,
                            gesture_token=current)
        self.assertEqual([a.kind for a in actions], ["invoke_observer"])

    def test_threshold_and_cancel_restore_are_observed_before_finish(self):
        token = self.press(owner="adapter")
        self.assertEqual(self.send("move", window_id=1, gesture_token=token,
                                   x=102, y=202), ())
        self.send("move", window_id=1, gesture_token=token, x=97, y=200)
        self.send("finish_requested", window_id=1, gesture_token=token)
        actions = self.send("finish_observed", window_id=1, gesture_token=token,
                            observed=(p.Target(10, "before"),))
        self.assertEqual([a.kind for a in actions], ["node_release"])
        self.assertIsNone(self.effects.undo_window)

    def test_adapter_owned_checkpoint_once(self):
        token = self.press(owner="adapter")
        actions = self.send("finish", window_id=1, gesture_token=token,
                            observed=(p.Target(10, "after"),))
        self.assertEqual([a.kind for a in actions], ["refresh"])
        self.assertEqual(self.effects.undo_window, 1)
        self.assertEqual(self.send("finish", window_id=1, gesture_token=token,
                                   observed=(p.Target(10, "after"),)), ())
        self.assertIsNone(self.effects.undo_window)

    def test_only_final_window_releases_shared_participation(self):
        first = self.press(window=1, owner="adapter")
        self.send("activate", window_id=1, gesture_token=first)
        second = self.press(window=2, owner="adapter")
        actions = self.send("activate", window_id=2, gesture_token=second)
        self.assertEqual([a.kind for a in actions], ["refresh"])
        self.assertEqual(self.send("finish", window_id=1, gesture_token=first,
                                   observed=(p.Target(10, "after"),)), ())
        self.assertTrue(p.active_for(self.state, 10))
        actions = self.send("finish", window_id=2, gesture_token=second,
                            observed=(p.Target(10, "after"),))
        self.assertEqual([a.kind for a in actions], ["node_release"])
        self.assertEqual(self.effects.undo_window, 2)

    def test_disposal_preserves_shared_survivors(self):
        token = self.press(targets=(p.Target(10, "a"), p.Target(20, "b")))
        self.send("activate", window_id=1, gesture_token=token)
        self.send("node_disposed", node_id=10)
        self.assertFalse(p.active_for(self.state, 10))
        self.assertTrue(p.active_for(self.state, 20))
        self.assertEqual(p.current_gesture(self.state, 1), token)
        actions = self.send("finish", window_id=1, gesture_token=token,
                            observed=(p.Target(20, "c"), p.Target(30, "a")))
        self.assertEqual([(a.kind, a.node_id) for a in actions], [("node_release", 20)])

    def test_disposal_removes_empty_windows_and_keeps_other_targets(self):
        for window, targets in ((1, (p.Target(10, "a"), p.Target(20, "b"))),
                                (2, (p.Target(10, "a"), p.Target(30, "c"))),
                                (3, (p.Target(10, "a"),))):
            token = self.press(window=window, targets=targets)
            self.send("activate", window_id=window, gesture_token=token)
        self.send("node_disposed", node_id=10)
        self.assertEqual([gesture.window_id for gesture in self.state.gestures], [1, 2])
        self.assertEqual(p.gesture_targets(self.state, 1), (p.Target(20, "b"),))
        self.assertEqual(p.gesture_targets(self.state, 2), (p.Target(30, "c"),))
        self.assertFalse(p.active_for(self.state, 10))
        self.assertTrue(p.active_for(self.state, 20))
        self.assertTrue(p.active_for(self.state, 30))

    def test_finish_releases_each_live_unshared_target_once(self):
        first = self.press(owner="adapter", targets=(p.Target(10, "a"), p.Target(20, "b"),
                                                    p.Target(30, "c"), p.Target(40, "d")))
        self.send("activate", window_id=1, gesture_token=first)
        second = self.press(window=2, owner="adapter", targets=(p.Target(20, "b"),))
        self.send("activate", window_id=2, gesture_token=second)
        actions = self.send("finish", window_id=1, gesture_token=first,
                            observed=(p.Target(10, "changed"), p.Target(20, "changed"),
                                      p.Target(30, "c")))
        self.assertEqual(actions, (p.Action("node_release", node_id=10),
                                   p.Action("node_release", node_id=30)))
        self.assertEqual(self.effects.undo_window, 1)
        self.assertTrue(p.active_for(self.state, 20))
        actions = self.send("finish", window_id=2, gesture_token=second,
                            observed=(p.Target(20, "changed"),))
        self.assertEqual(actions, (p.Action("node_release", node_id=20),))
        self.assertEqual(self.effects.undo_window, 2)

    def test_reset_invalidates_delayed_receipts_without_reusing_ids(self):
        observer = self.observer()
        gesture = self.press(observer=observer)
        serial = self.state.serial
        self.send("reset")
        self.assertEqual(self.state.serial, serial)
        replacement = self.observer()
        self.assertGreater(replacement, gesture)
        current = self.press(observer=replacement)
        before = self.state
        for event in (p.Event("handoff_due", window_id=1, token=observer, gesture_token=gesture),
                      p.Event("finish_observed", window_id=1, gesture_token=gesture),
                      p.Event("observer_install_result", window_id=1, token=observer, success=True)):
            self.assertEqual(p.step(self.state, event), (before, p.Effects()))
        self.assertEqual(p.current_gesture(self.state, 1), current)


if __name__ == "__main__":
    unittest.main()
