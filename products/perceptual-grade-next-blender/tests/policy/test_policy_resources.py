import unittest
from dataclasses import replace

from policy.resources import (
    Adoption, Effects, Event, State, may_adopt, new_disposal, new_retirement, step,
)


class ResourcePolicyTests(unittest.TestCase):
    def test_adoption_requires_every_native_contract(self):
        valid = Adoption(True, True, True, True, True, True)
        self.assertTrue(may_adopt(valid))
        for field in valid.__dataclass_fields__:
            with self.subTest(field=field):
                self.assertFalse(may_adopt(replace(valid, **{field: False})))

    def test_disposal_fences_before_detaching_and_checks_fresh_users(self):
        state = new_disposal()
        for event, expected in ((Event(), "fence"),
                                (Event(), "detach"),
                                (Event(), "observe")):
            state, effects = step(state, event)
            self.assertEqual(effects.action, expected)
        state, effects = step(state, Event(live=True, owned=True, users=1))
        self.assertEqual((state, effects), (State("terminal"), Effects()))

    def test_retirement_requires_eviction_and_a_second_observation(self):
        state, _ = step(new_retirement(), Event())
        state, effects = step(state, Event(live=True, owned=True))
        self.assertEqual(effects.action, "evict")
        state, effects = step(state, Event())
        self.assertEqual(effects.action, "recheck")
        state, effects = step(state, Event(live=True, owned=True))
        self.assertEqual(effects.action, "remove")
        state, effects = step(state, Event())
        self.assertEqual((state, effects), (State("terminal"), Effects()))
        self.assertEqual(step(state, Event()), (state, Effects()))

    def test_changed_user_count_or_protection_cancels_removal(self):
        for observation in ({"users": 1}, {"protected": True}, {"owned": False}):
            with self.subTest(observation=observation):
                fields = {"live": True, "owned": True, **observation}
                state, effects = step(State("recheck"), Event(**fields))
                self.assertEqual((state, effects), (State("terminal"), Effects()))

    def test_removed_wrapper_only_evicts_cache(self):
        state, effects = step(State("observe"), Event(live=False))
        self.assertEqual(effects.action, "evict")
        state, _ = step(state, Event())
        state, effects = step(state, Event(live=False))
        self.assertEqual((state, effects), (State("terminal"), Effects()))

    def test_fence_or_eviction_failure_prohibits_destructive_followup(self):
        for phase in ("fence", "evict", "observe", "recheck"):
            with self.subTest(phase=phase):
                state, effects = step(State(phase), Event(failed=True))
                self.assertEqual((state, effects), (State("terminal"), Effects()))

    def test_partial_detach_can_still_reclaim_an_unused_resource(self):
        state, effects = step(State("detach"), Event(failed=True))
        self.assertEqual(effects.action, "observe")
        state, _ = step(state, Event(live=True, owned=True))
        state, _ = step(state, Event())
        state, _ = step(state, Event(live=True, owned=True))
        state, effects = step(state, Event(failed=True))
        self.assertEqual((state, effects), (State("terminal"), Effects()))


if __name__ == "__main__":
    unittest.main()
