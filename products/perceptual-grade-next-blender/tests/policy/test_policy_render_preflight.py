import unittest

from policy.render_preflight import Effects, Event, State, new, step


class RenderPreflightPolicyTests(unittest.TestCase):
    def setUp(self):
        self.scene_identity = 20
        self.frame = 17
        self.subframe = "0x0.0p+0"
        self.waiting = new(self.scene_identity, self.frame, self.subframe)

    def test_only_matching_exact_publication_releases(self):
        state, effects = step(self.waiting, Event(
            "published", scene_identity=self.scene_identity,
            frame=self.frame, subframe=self.subframe,
            signature="grade-17", published_signature="grade-17",
        ))
        self.assertEqual(state, State(
            "released", self.scene_identity, self.frame, self.subframe,
        ))
        self.assertEqual(effects, Effects("release"))

    def test_observed_scene_frame_or_subframe_mismatch_fails_closed(self):
        for event in (
            Event("published", signature="grade-17",
                  published_signature="grade-17"),
            Event("published", scene_identity=21, frame=self.frame,
                  subframe=self.subframe, signature="grade-17",
                  published_signature="grade-17"),
            Event("published", scene_identity=self.scene_identity,
                  frame=18, subframe=self.subframe, signature="grade-18",
                  published_signature="grade-18"),
            Event("published", scene_identity=self.scene_identity,
                  frame=self.frame, subframe="0x1.0p-1",
                  signature="grade-17", published_signature="grade-17"),
        ):
            state, effects = step(self.waiting, event)
            self.assertEqual(state.phase, "failed")
            self.assertEqual(effects.action, "fail")

    def test_unpublished_signature_and_explicit_failure_fail_closed(self):
        for event in (
            Event("published", scene_identity=self.scene_identity,
                  frame=self.frame, subframe=self.subframe,
                  signature="grade-17", published_signature="old-grade"),
            Event("failed", error="publish failed"),
        ):
            state, effects = step(self.waiting, event)
            self.assertEqual(state.phase, "failed")
            self.assertEqual(effects.action, "fail")

    def test_terminal_receipts_are_inert(self):
        released = State("released", self.scene_identity, self.frame, self.subframe)
        self.assertEqual(step(released, Event(
            "failed", error="late failure",
        )), (released, Effects()))


if __name__ == "__main__":
    unittest.main()
