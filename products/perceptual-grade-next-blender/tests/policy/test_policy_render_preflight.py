import unittest

from policy.render_preflight import Effects, Event, State, new, step


class RenderPreflightPolicyTests(unittest.TestCase):
    def setUp(self):
        self.waiting = new(10, 20, 17, "0x0.0p+0", 4)

    def test_only_matching_exact_publication_releases(self):
        state, effects = step(self.waiting, Event(
            "published", 10, 20, 17, "0x0.0p+0", 4,
            signature="grade-17", published_signature="grade-17",
        ))
        self.assertEqual(state, State(
            "released", 10, 20, 17, "0x0.0p+0", 4, signature="grade-17",
        ))
        self.assertEqual(effects, Effects("release"))

    def test_stale_generation_is_ignored(self):
        event = Event("published", 10, 20, 17, "0x0.0p+0", 3,
                      signature="grade-17", published_signature="grade-17")
        self.assertEqual(step(self.waiting, event), (self.waiting, Effects()))

    def test_wrong_scene_frame_or_subframe_fails_closed(self):
        for event in (
            Event("published", 10, 21, 17, "0x0.0p+0", 4,
                  signature="grade-17", published_signature="grade-17"),
            Event("published", 10, 20, 18, "0x0.0p+0", 4,
                  signature="grade-18", published_signature="grade-18"),
            Event("published", 10, 20, 17, "0x1.0p-1", 4,
                  signature="grade-17", published_signature="grade-17"),
        ):
            state, effects = step(self.waiting, event)
            self.assertEqual(state.phase, "failed")
            self.assertEqual(effects.action, "fail")

    def test_unpublished_signature_and_explicit_failure_fail_closed(self):
        for event in (
            Event("published", 10, 20, 17, "0x0.0p+0", 4,
                  signature="grade-17", published_signature="old-grade"),
            Event("failed", 10, 20, 17, "0x0.0p+0", 4, error="publish failed"),
        ):
            state, effects = step(self.waiting, event)
            self.assertEqual(state.phase, "failed")
            self.assertEqual(effects.action, "fail")

    def test_terminal_receipts_are_inert(self):
        released = State("released", 10, 20, 17, "0x0.0p+0", 4,
                         signature="grade-17")
        self.assertEqual(step(released, Event(
            "failed", 10, 20, 17, "0x0.0p+0", 4, error="late failure",
        )), (released, Effects()))


if __name__ == "__main__":
    unittest.main()
