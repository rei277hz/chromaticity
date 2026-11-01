import unittest

from color_tools.perceptual_grade_next_core.workflow.scope import (
    ForegroundEvent, ScopeEvent, ScopeViewEvent, new_scope_view,
    scope_step, scope_view_step,
)


def opened_scope_view():
    state, accepted = scope_view_step(
        new_scope_view(),
        ScopeViewEvent(
            "open",
            ScopeEvent("open", generation=1, owner="app", view_epoch=1),
            ForegroundEvent("open", generation=1, owner="view-a", epoch=1),
        ),
    )
    assert accepted
    scope, accepted = scope_step(state.scope, ScopeEvent(
        "demand", generation=1, owner="app", view_epoch=1,
        playback_epoch=0, request=1, source_revision=1, source_id="source-a",
    ))
    assert accepted
    scope, accepted = scope_step(scope, ScopeEvent(
        "begin", generation=1, owner="app", view_epoch=1,
        playback_epoch=0, request=1, source_revision=1, source_id="source-a",
        submission=1,
    ))
    assert accepted
    scope, accepted = scope_step(scope, ScopeEvent(
        "complete", generation=1, owner="app", view_epoch=1,
        playback_epoch=0, request=1, source_revision=1, source_id="source-a",
        submission=1,
    ))
    assert accepted
    return type(state)(scope, state.view)


def issue(state, *, token="visual-1", view_owner="view-a", epoch=1):
    scope = state.scope
    return scope_view_step(state, ScopeViewEvent(
        "issue",
        ScopeEvent("display_issued", generation=1, owner="app", view_epoch=epoch,
                   playback_epoch=scope.playback_epoch,
                   request=scope.accepted_request,
                   source_revision=scope.source_revision,
                   source_id=scope.accepted_source, token=token),
        ForegroundEvent("issue", generation=1, owner=view_owner, epoch=epoch,
                        token=token),
    ))


def apply(state, *, token="visual-1", view_owner="view-a", epoch=1):
    scope = state.scope
    return scope_view_step(state, ScopeViewEvent(
        "apply",
        ScopeEvent("display_applied", generation=1, owner="app", view_epoch=epoch,
                   playback_epoch=scope.playback_epoch,
                   request=scope.accepted_request,
                   source_revision=scope.source_revision,
                   source_id=scope.accepted_source, token=token),
        ForegroundEvent("apply", generation=1, owner=view_owner, epoch=epoch,
                        token=token),
    ))


class ScopeViewCompositionTests(unittest.TestCase):
    def test_issue_and_adoption_commit_matching_scope_and_view_receipts_once(self):
        state, accepted = issue(opened_scope_view())
        self.assertTrue(accepted)
        self.assertEqual(state.scope.display_token, "visual-1")
        self.assertEqual(state.view.token, "visual-1")

        adopted, accepted = apply(state)
        self.assertTrue(accepted)
        self.assertEqual(adopted.scope.applied_token, "visual-1")
        self.assertEqual(adopted.view.applied_token, "visual-1")
        self.assertEqual(apply(adopted), (adopted, False))

    def test_view_rejection_cannot_partially_install_scope_token(self):
        state = opened_scope_view()
        rejected, accepted = issue(state, view_owner="wrong-view")
        self.assertFalse(accepted)
        self.assertEqual(rejected, state)
        self.assertEqual(state.scope.display_token, 0)

    def test_close_revokes_delayed_visual_from_both_policies(self):
        state, accepted = issue(opened_scope_view())
        self.assertTrue(accepted)
        closed, accepted = scope_view_step(state, ScopeViewEvent(
            "close",
            ScopeEvent("close", generation=1, owner="app"),
            ForegroundEvent("close", generation=1, owner="view-a"),
        ))
        self.assertTrue(accepted)
        self.assertFalse(closed.view.visible)
        self.assertEqual(closed.view.token, 0)
        self.assertEqual(apply(closed), (closed, False))

    def test_transfer_revokes_delayed_visual_and_requires_new_owner_issue(self):
        state, accepted = issue(opened_scope_view())
        self.assertTrue(accepted)
        moved, accepted = scope_view_step(state, ScopeViewEvent(
            "move",
            ScopeEvent("move", generation=1, owner="app", view_epoch=2),
            ForegroundEvent("move", generation=1, owner="view-a", epoch=2,
                            next_owner="view-b"),
        ))
        self.assertTrue(accepted)
        self.assertEqual(moved.view.owner, "view-b")
        self.assertEqual(moved.view.token, 0)
        self.assertEqual(apply(moved), (moved, False))
        self.assertEqual(issue(moved, token="visual-2", view_owner="view-b", epoch=2),
                         (moved, False))

        scope, accepted = scope_step(moved.scope, ScopeEvent(
            "demand", generation=1, owner="app", view_epoch=2,
            playback_epoch=0, request=2, source_revision=2,
            source_id="source-b",
        ))
        self.assertTrue(accepted)
        scope, accepted = scope_step(scope, ScopeEvent(
            "begin", generation=1, owner="app", view_epoch=2,
            playback_epoch=0, request=2, source_revision=2,
            source_id="source-b", submission=2,
        ))
        self.assertTrue(accepted)
        scope, accepted = scope_step(scope, ScopeEvent(
            "complete", generation=1, owner="app", view_epoch=2,
            playback_epoch=0, request=2, source_revision=2,
            source_id="source-b", submission=2,
        ))
        self.assertTrue(accepted)
        refreshed = type(moved)(scope, moved.view)
        issued, accepted = issue(refreshed, token="visual-2", view_owner="view-b", epoch=2)
        self.assertTrue(accepted)
        self.assertEqual(issued.view.token, "visual-2")


if __name__ == "__main__":
    unittest.main()
