import unittest

from policy.compositor_publication import Effects, Event, State, new, step


class CompositorPublicationPolicyTests(unittest.TestCase):
    def test_admission_effect_requires_snapshot_and_no_progress_fence(self):
        state, effects = step(new(), Event("admit", 7, 11, eligible=True))
        self.assertEqual(state, new())
        self.assertEqual(effects, Effects(11))
        for event in (Event("admit", 7, 11),
                      Event("admit", None, 11, eligible=True),
                      Event("admit", 0, 11, eligible=True),
                      Event("admit", 7, None, eligible=True),
                      Event("admit", 7, 0, eligible=True)):
            self.assertEqual(step(new(), event), (new(), Effects()))
        for state in (State(7, 11), State(7, None), State(None, 11)):
            self.assertEqual(step(state, Event("admit", 7, 12, eligible=True)),
                             (state, Effects()))

    def test_only_an_admitted_supersession_sets_protection(self):
        self.assertEqual(step(new(), Event("superseded", 7, 11)),
                         (new(), Effects()))
        state, effects = step(new(), Event("superseded", 7, 11, eligible=True))
        self.assertEqual((state, effects), (State(7, 11), Effects()))
        self.assertEqual(step(state, Event("superseded", 9, 19, eligible=True)),
                         (state, Effects()))

    def test_cancelled_unrelated_and_original_completion_keep_protection(self):
        state = State(7, 11)
        for event in (Event("finished", 7, 12),
                      Event("finished", 9, 12, successful=True),
                      Event("finished", 7, 11, successful=True),
                      Event("finished", 7, 10, successful=True),
                      Event("finished", 7, None, successful=True)):
            self.assertEqual(step(state, event), (state, Effects()))

    def test_successful_later_same_scene_completion_reopens_admission(self):
        state, effects = step(State(7, 11), Event("finished", 7, 12, successful=True))
        self.assertEqual((state, effects), (new(), Effects()))
        self.assertEqual(step(state, Event("admit", 7, 13, eligible=True)),
                         (new(), Effects(13)))

    def test_only_quiescent_lifecycle_reset_releases_protection(self):
        state = State(7, 11)
        self.assertEqual(step(state, Event("reset")), (state, Effects()))
        self.assertEqual(step(state, Event("reset", quiescent=True)),
                         (new(), Effects()))


if __name__ == "__main__":
    unittest.main()
