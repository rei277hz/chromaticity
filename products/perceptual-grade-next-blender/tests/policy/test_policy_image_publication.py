import unittest

from policy.image_publication import (
    Effects, Event, State, finish_save_packing, new,
    request_save_packing, step,
)


class ImagePublicationPolicyTests(unittest.TestCase):
    def test_save_fallback_only_packs_dirty_generated_images(self):
        for generated, dirty in ((False, False), (False, True), (True, False), (True, True)):
            self.assertEqual(request_save_packing(generated, dirty),
                             generated and dirty)

    def test_save_packing_requires_clean_receipt_and_preserves_failure(self):
        self.assertIsNone(finish_save_packing(True, None))
        self.assertEqual(finish_save_packing(True, "native failure"),
                         "native failure")
        self.assertEqual(finish_save_packing(False, "native failure"),
                         "native failure")
        self.assertEqual(finish_save_packing(False, None),
                         "Grade parameter image could not be packed")

    def test_upload_pack_metadata_and_delivery_are_acknowledged_in_order(self):
        state = new()
        for event, action in ((Event(), "prepare"),
                              (Event(), "snapshot"),
                              (Event(), "upload"),
                              (Event(), "pack"),
                              (Event(clean=True), "commit"),
                              (Event(), "deliver"),
                              (Event(), "retire"),
                              (Event(), None)):
            state, effects = step(state, event)
            self.assertEqual(effects.action, action)
        self.assertEqual(state, State("terminal"))

    def test_only_matching_clean_image_can_skip_upload(self):
        for matching, clean, action in ((True, True, "commit"),
                                        (True, False, "upload"),
                                        (False, True, "upload"),
                                        (False, False, "upload")):
            with self.subTest(matching=matching, clean=clean):
                _state, effects = step(State("snapshot"), Event(
                    matching=matching, clean=clean))
                self.assertEqual(effects.action, action)

    def test_every_shared_mutation_failure_restores_and_then_fails_source(self):
        for phase in ("upload", "pack", "commit"):
            with self.subTest(phase=phase):
                state, effects = step(State(phase), Event(failed=True))
                self.assertEqual(effects.action, "restore_upload")
                for event, action in ((Event(), "restore_pack"),
                                      (Event(clean=True), "restore_metadata"),
                                      (Event(), "fail"),
                                      (Event(), "retire"),
                                      (Event(), None)):
                    state, effects = step(state, event)
                    self.assertEqual(effects.action, action)

    def test_silent_pack_failure_cannot_commit_metadata(self):
        state, effects = step(State("pack"), Event(clean=False))
        self.assertEqual(effects.action, "restore_upload")
        self.assertEqual(state.phase, "restore_upload")

    def test_failed_restoration_never_commits_restored_metadata(self):
        for phase in ("restore_upload", "restore_pack"):
            state, effects = step(State(phase), Event(failed=True))
            self.assertEqual((state, effects), (State("fail"), Effects("fail")))
        self.assertEqual(step(State("restore_pack"), Event()),
                         (State("fail"), Effects("fail")))

    def test_terminal_receipts_are_inert(self):
        state = State("terminal")
        for event in (Event(), Event(failed=True)):
            self.assertEqual(step(state, event), (state, Effects()))

    def test_failure_before_snapshot_has_no_restore_work(self):
        for phase in ("prepare", "snapshot"):
            state, effects = step(State(phase), Event(failed=True))
            self.assertEqual((state, effects), (State("fail"), Effects("fail")))


if __name__ == "__main__":
    unittest.main()
