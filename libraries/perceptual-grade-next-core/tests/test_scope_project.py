import unittest
from dataclasses import replace

from color_tools.perceptual_grade_next_core.workflow import (
    ProjectEvent, ScopeEvent, new_project, new_scope, project_ready, project_step,
    scope_has_current_input, scope_step,
)


def _owner_ready(owner, evaluator, evaluator_id, manifest_id):
    return ProjectEvent(
        "owner_ready", generation=1, revision=1, attempt=1, owner=owner,
        evaluator=evaluator, evaluator_id=evaluator_id, manifest_id=manifest_id,
        final_ready=True,
    )


class ScopeTests(unittest.TestCase):
    def test_cancelled_work_requires_retirement_and_cannot_publish(self):
        state, ok = scope_step(new_scope(), ScopeEvent("open", generation=1, owner="app", view_epoch=1))
        self.assertTrue(ok)
        state, ok = scope_step(state, ScopeEvent("demand", generation=1, owner="app", view_epoch=1,
                                                request=1, source_revision=1, source_id="image", playback_epoch=0))
        self.assertTrue(ok)
        state, ok = scope_step(state, ScopeEvent("begin", generation=1, owner="app", view_epoch=1,
                                                request=1, source_revision=1, source_id="image", submission=1,
                                                playback_epoch=0))
        self.assertTrue(ok)
        state, ok = scope_step(state, ScopeEvent("cancel", generation=1, owner="app", view_epoch=1, submission=1))
        self.assertTrue(ok)
        self.assertEqual(state.phase, "retiring")
        state, ok = scope_step(state, ScopeEvent("retired", generation=1, owner="app", view_epoch=1, submission=1))
        self.assertTrue(ok)
        self.assertEqual(state.phase, "healthy")
        stale, ok = scope_step(state, ScopeEvent("complete", generation=1, owner="app", view_epoch=1,
                                                 request=1, source_revision=1, source_id="image", submission=1))
        self.assertFalse(ok)
        self.assertEqual(stale, state)
        replayed, ok = scope_step(state, ScopeEvent(
            "begin", generation=1, owner="app", view_epoch=1,
            request=1, source_revision=1, source_id="image", submission=2,
        ))
        self.assertFalse(ok)
        self.assertEqual(replayed, state)
        state, ok = scope_step(state, ScopeEvent(
            "demand", generation=1, owner="app", view_epoch=1,
            request=2, source_revision=1, source_id="image",
        ))
        self.assertTrue(ok)
        state, ok = scope_step(state, ScopeEvent(
            "begin", generation=1, owner="app", view_epoch=1,
            request=2, source_revision=1, source_id="image", submission=2,
        ))
        self.assertTrue(ok)

    def test_view_move_revokes_result_but_keeps_retirement_debt(self):
        state, _ = scope_step(new_scope(), ScopeEvent("open", generation=1, owner="app", view_epoch=1))
        state, _ = scope_step(state, ScopeEvent("demand", generation=1, owner="app", view_epoch=1,
                                                request=1, source_revision=1, source_id="source", playback_epoch=0))
        state, _ = scope_step(state, ScopeEvent("begin", generation=1, owner="app", view_epoch=1,
                                               request=1, source_revision=1, source_id="source", submission=1,
                                               playback_epoch=0))
        state, ok = scope_step(state, ScopeEvent("move", generation=1, owner="app", view_epoch=2,
                                                 request=1, source_revision=1, source_id="source"))
        self.assertTrue(ok)
        self.assertEqual(state.phase, "retiring")
        late, ok = scope_step(state, ScopeEvent("complete", generation=1, owner="app", view_epoch=1,
                                                request=1, source_revision=1, source_id="source", submission=1))
        self.assertTrue(ok)
        self.assertEqual(late.physical, "none")
        self.assertFalse(scope_has_current_input(late))

    def test_current_completion_and_applied_display_are_distinct(self):
        state, _ = scope_step(new_scope(), ScopeEvent("open", generation=1, owner="app", view_epoch=1))
        state, _ = scope_step(state, ScopeEvent("demand", generation=1, owner="app", view_epoch=1,
                                                request=1, source_revision=1, source_id="source", playback_epoch=0))
        state, _ = scope_step(state, ScopeEvent("begin", generation=1, owner="app", view_epoch=1,
                                               request=1, source_revision=1, source_id="source", submission=1,
                                               playback_epoch=0))
        state, ok = scope_step(state, ScopeEvent("complete", generation=1, owner="app", view_epoch=1,
                                                 request=1, source_revision=1, source_id="source", submission=1))
        self.assertTrue(ok)
        self.assertTrue(scope_has_current_input(state))
        state, _ = scope_step(state, ScopeEvent("display_issued", generation=1, owner="app", view_epoch=1,
                                                request=1, source_id="source", token="token"))
        self.assertNotEqual(state.display_token, state.applied_token)
        state, _ = scope_step(state, ScopeEvent("display_applied", generation=1, owner="app", view_epoch=1,
                                                request=1, source_id="source", token="token"))
        self.assertEqual(state.display_token, state.applied_token)


class ProjectTests(unittest.TestCase):
    def ready_project(self):
        state, _ = project_step(new_project(), ProjectEvent(
            "open", generation=1, owners=("grade", "stack"),
            owner_evaluators=(("grade", "native_grade_graph"), ("stack", "stack_65_lut")),
        ))
        state, _ = project_step(state, ProjectEvent("intent", generation=1, revision=1))
        state, _ = project_step(state, ProjectEvent("prepare_begin", generation=1, revision=1, attempt=1))
        state, _ = project_step(state, _owner_ready("grade", "native_grade_graph", "grade-graph", "grade-manifest"))
        state, _ = project_step(state, _owner_ready("stack", "stack_65_lut", "stack-lut-65", "stack-manifest"))
        self.assertTrue(project_ready(state))
        return state

    def test_all_required_owners_must_be_ready_and_repair_debt_blocks(self):
        state, _ = project_step(new_project(), ProjectEvent(
            "open", generation=1, owners=("grade", "stack"),
            owner_evaluators=(("grade", "native_grade_graph"), ("stack", "stack_65_lut")),
        ))
        state, _ = project_step(state, ProjectEvent("intent", generation=1, revision=1))
        state, _ = project_step(state, ProjectEvent("prepare_begin", generation=1, revision=1, attempt=1))
        state, _ = project_step(state, _owner_ready("grade", "native_grade_graph", "grade-graph", "grade-manifest"))
        self.assertFalse(project_ready(state))
        state, _ = project_step(state, _owner_ready("stack", "stack_65_lut", "stack-lut-65", "stack-manifest"))
        state, _ = project_step(state, ProjectEvent("owner_failed", generation=1, revision=1,
                                                    attempt=1, owner="stack"))
        self.assertFalse(project_ready(state))

    def test_owner_evaluator_slots_are_exact_and_reject_duplicates(self):
        duplicate, accepted = project_step(new_project(), ProjectEvent(
            "open", generation=1, owners=("grade", "grade"),
            owner_evaluators=(("grade", "native_grade_graph"),),
        ))
        self.assertFalse(accepted)
        self.assertEqual(duplicate, new_project())

        unpaired, accepted = project_step(new_project(), ProjectEvent(
            "open", generation=1, owners=("grade", "stack"),
            owner_evaluators=(("grade", "native_grade_graph"),),
        ))
        self.assertFalse(accepted)
        self.assertEqual(unpaired, new_project())

        state, accepted = project_step(new_project(), ProjectEvent(
            "open", generation=1, owners=("grade", "stack"),
            owner_evaluators=(
                ("stack", "stack_65_lut"), ("grade", "native_grade_graph"),
            ),
        ))
        self.assertTrue(accepted)
        state, _ = project_step(state, ProjectEvent("intent", generation=1, revision=1))
        state, _ = project_step(state, ProjectEvent(
            "prepare_begin", generation=1, revision=1, attempt=1,
        ))
        unchanged, accepted = project_step(state, _owner_ready(
            "grade", "stack_65_lut", "wrong-evaluator", "manifest",
        ))
        self.assertFalse(accepted)
        self.assertEqual(unchanged, state)

        invalid_worklists = (
            ((0,), ((0, "native_grade_graph"),)),
            (("grade",), (("grade", "unknown_evaluator"),)),
        )
        for owners, owner_evaluators in invalid_worklists:
            with self.subTest(owners=owners):
                unchanged, accepted = project_step(new_project(), ProjectEvent(
                    "open", generation=1, owners=owners,
                    owner_evaluators=owner_evaluators,
                ))
                self.assertFalse(accepted)
                self.assertEqual(unchanged, new_project())

    def test_four_owner_project_uses_complete_readiness_projection(self):
        owners = ("grade_a", "stack_a", "grade_b", "stack_b")
        evaluator_by_owner = (
            ("grade_a", "native_grade_graph"),
            ("stack_a", "stack_65_lut"),
            ("grade_b", "native_grade_graph"),
            ("stack_b", "stack_65_lut"),
        )
        state, accepted = project_step(new_project(), ProjectEvent(
            "open", generation=1, owners=owners,
            owner_evaluators=evaluator_by_owner,
        ))
        self.assertTrue(accepted)
        state, accepted = project_step(state, ProjectEvent(
            "intent", generation=1, revision=1,
        ))
        self.assertTrue(accepted)
        state, accepted = project_step(state, ProjectEvent(
            "prepare_begin", generation=1, revision=1, attempt=1,
        ))
        self.assertTrue(accepted)
        for index, (owner, evaluator) in enumerate(evaluator_by_owner):
            state, accepted = project_step(state, ProjectEvent(
                "owner_ready", generation=1, revision=1, attempt=1,
                owner=owner, evaluator=evaluator,
                evaluator_id=f"evaluator-{index}",
                manifest_id=f"manifest-{index}", final_ready=True,
            ))
            self.assertTrue(accepted)
        self.assertTrue(project_ready(state))

    def test_more_than_four_owners_use_unbounded_readiness_fallback(self):
        owners = ("grade_a", "stack_a", "grade_b", "stack_b", "grade_c")
        evaluator_by_owner = (
            ("grade_a", "native_grade_graph"),
            ("stack_a", "stack_65_lut"),
            ("grade_b", "native_grade_graph"),
            ("stack_b", "stack_65_lut"),
            ("grade_c", "native_grade_graph"),
        )
        state, accepted = project_step(new_project(), ProjectEvent(
            "open", generation=1, owners=owners,
            owner_evaluators=evaluator_by_owner,
        ))
        self.assertTrue(accepted)
        state, accepted = project_step(state, ProjectEvent(
            "intent", generation=1, revision=1,
        ))
        self.assertTrue(accepted)
        state, accepted = project_step(state, ProjectEvent(
            "prepare_begin", generation=1, revision=1, attempt=1,
        ))
        self.assertTrue(accepted)
        for index, (owner, evaluator) in enumerate(evaluator_by_owner):
            state, accepted = project_step(state, ProjectEvent(
                "owner_ready", generation=1, revision=1, attempt=1,
                owner=owner, evaluator=evaluator,
                evaluator_id=f"evaluator-{index}",
                manifest_id=f"manifest-{index}", final_ready=True,
            ))
            self.assertTrue(accepted)
        self.assertTrue(project_ready(state))

    def test_unified_readiness_accepts_reordered_records_and_rejects_bad_conversion(self):
        owners = tuple(f"owner_{index}" for index in range(17))
        evaluators = tuple((owner, "native_grade_graph" if index % 2 == 0
                            else "stack_65_lut") for index, owner in enumerate(owners))
        state, accepted = project_step(new_project(), ProjectEvent(
            "open", generation=1, owners=owners, owner_evaluators=evaluators,
        ))
        self.assertTrue(accepted)
        state, _ = project_step(state, ProjectEvent("intent", generation=1, revision=1))
        state, _ = project_step(state, ProjectEvent(
            "prepare_begin", generation=1, revision=1, attempt=1,
        ))
        for owner, evaluator in reversed(evaluators):
            state, accepted = project_step(state, ProjectEvent(
                "owner_ready", generation=1, revision=1, attempt=1,
                owner=owner, evaluator=evaluator,
                evaluator_id="eval-" + owner, manifest_id="manifest-" + owner,
                final_ready=True,
            ))
            self.assertTrue(accepted)
        self.assertTrue(project_ready(state))

        duplicated = replace(
            state, ready_artifacts=(state.ready_artifacts[0],) * len(owners),
        )
        self.assertFalse(project_ready(duplicated))
        missing = replace(state, ready_owners=state.ready_owners[:-1])
        self.assertFalse(project_ready(missing))
        unpaired = replace(state, required_evaluators=state.required_evaluators[:-1])
        self.assertFalse(project_ready(unpaired))

    def test_output_owner_repair_preserves_other_readiness_until_fresh_receipt(self):
        state = self.ready_project()
        state, accepted = project_step(state, ProjectEvent(
            "save_request", generation=1, operation=1,
        ))
        self.assertTrue(accepted)
        state, accepted = project_step(state, ProjectEvent(
            "output_owner_failed", generation=1, revision=1, attempt=1,
            owner="grade",
        ))
        self.assertTrue(accepted)
        self.assertIn("stack", state.ready_owners)
        self.assertIn("grade", state.repair_owners)
        self.assertFalse(project_ready(state))
        unchanged, accepted = project_step(state, ProjectEvent(
            "save_ready", generation=1, operation=1,
        ))
        self.assertFalse(accepted)
        self.assertEqual(unchanged, state)

        state, accepted = project_step(state, ProjectEvent(
            "retry_owner", generation=1, revision=1, attempt=2, owner="grade",
        ))
        self.assertTrue(accepted)
        self.assertIn("stack", state.ready_owners)
        self.assertNotIn("grade", state.ready_owners)
        self.assertFalse(project_ready(state))
        stale, accepted = project_step(state, _owner_ready(
            "grade", "native_grade_graph", "old-graph", "old-manifest",
        ))
        self.assertFalse(accepted)
        self.assertEqual(stale, state)

        state, accepted = project_step(state, ProjectEvent(
            "prepare_begin", generation=1, revision=1, attempt=3,
        ))
        self.assertTrue(accepted)
        state, accepted = project_step(state, ProjectEvent(
            "owner_ready", generation=1, revision=1, attempt=3, owner="grade",
            evaluator="native_grade_graph", evaluator_id="new-graph",
            manifest_id="new-manifest", final_ready=True,
        ))
        self.assertTrue(accepted)
        self.assertFalse(project_ready(state))
        state, accepted = project_step(state, ProjectEvent(
            "save_ready", generation=1, operation=1,
        ))
        self.assertTrue(accepted)

    def test_render_start_requires_every_current_owner_artifact(self):
        state, accepted = project_step(new_project(), ProjectEvent(
            "open", generation=1, owners=("grade", "stack"),
            owner_evaluators=(
                ("grade", "native_grade_graph"), ("stack", "stack_65_lut"),
            ),
        ))
        self.assertTrue(accepted)
        state, _ = project_step(state, ProjectEvent("intent", generation=1, revision=1))
        state, _ = project_step(state, ProjectEvent(
            "prepare_begin", generation=1, revision=1, attempt=1,
        ))
        state, accepted = project_step(state, ProjectEvent(
            "owner_ready", generation=1, revision=1, attempt=1, owner="grade",
            evaluator="native_grade_graph", evaluator_id="graph", manifest_id="grade-m",
            final_ready=True,
        ))
        self.assertTrue(accepted)
        state, accepted = project_step(state, ProjectEvent(
            "render_request", generation=1, operation=1,
        ))
        self.assertTrue(accepted)
        unchanged, accepted = project_step(state, ProjectEvent(
            "render_started", generation=1, operation=1,
        ))
        self.assertFalse(accepted)
        self.assertEqual(unchanged, state)
        state, accepted = project_step(state, ProjectEvent(
            "owner_ready", generation=1, revision=1, attempt=1, owner="stack",
            evaluator="stack_65_lut", evaluator_id="lut", manifest_id="stack-m",
            final_ready=True,
        ))
        self.assertTrue(accepted)
        state, accepted = project_step(state, ProjectEvent(
            "render_started", generation=1, operation=1,
        ))
        self.assertTrue(accepted)

    def test_bake_binds_exact_65_lut_and_render_holds_publication(self):
        state = self.ready_project()
        wrong, ok = project_step(state, ProjectEvent("bake_request", generation=1, operation=1, owner="stack",
            source_revision=4, source_id="frozen", evaluator="stack_65_lut", evaluator_id="preview33",
            manifest_id="stack-manifest", final_ready=True))
        self.assertFalse(ok)
        self.assertEqual(wrong, state)
        state, ok = project_step(state, ProjectEvent("bake_request", generation=1, operation=1, owner="stack",
            source_revision=4, source_id="frozen", evaluator="stack_65_lut", evaluator_id="stack-lut-65",
            manifest_id="stack-manifest", final_ready=True))
        self.assertTrue(ok)
        state, ok = project_step(state, ProjectEvent("bake_started", generation=1, operation=1))
        self.assertTrue(ok)
        state, ok = project_step(state, ProjectEvent("bake_retired", generation=1, operation=1))
        self.assertTrue(ok)
        state, _ = project_step(state, ProjectEvent("bake_staged", generation=1, operation=1))
        state, _ = project_step(state, ProjectEvent("bake_publishing", generation=1, operation=1))
        wrong, ok = project_step(state, ProjectEvent("bake_complete", generation=1, operation=1,
            source_revision=4, source_id="frozen", evaluator="stack_65_lut", evaluator_id="preview33",
            manifest_id="stack-manifest", result_id="image", committed=True))
        self.assertFalse(ok)
        self.assertEqual(wrong, state)
        state, ok = project_step(state, ProjectEvent("bake_complete", generation=1, operation=1,
            source_revision=4, source_id="frozen", evaluator="stack_65_lut", evaluator_id="stack-lut-65",
            manifest_id="stack-manifest", result_id="image", committed=True))
        self.assertTrue(ok)
        state, ok = project_step(state, ProjectEvent("render_request", generation=1, operation=1))
        self.assertTrue(ok)
        self.assertTrue(state.publication_hold)
        premature, ok = project_step(
            state, ProjectEvent("render_complete", generation=1, operation=1, committed=True),
        )
        self.assertFalse(ok)
        self.assertEqual(premature, state)
        state, ok = project_step(state, ProjectEvent("render_started", generation=1, operation=1))
        self.assertTrue(ok)
        state, ok = project_step(state, ProjectEvent(
            "render_complete", generation=1, operation=1, committed=True,
        ))
        self.assertTrue(ok)
        self.assertFalse(state.publication_hold)

    def test_accepted_save_cancels_bake_and_waits_for_retirement(self):
        state = self.ready_project()
        state, _ = project_step(state, ProjectEvent("bake_request", generation=1, operation=1,
            owner="stack", source_revision=4, source_id="frozen", evaluator="stack_65_lut",
            evaluator_id="stack-lut-65", manifest_id="stack-manifest", final_ready=True))
        state, _ = project_step(state, ProjectEvent("bake_started", generation=1, operation=1))
        state, ok = project_step(state, ProjectEvent("save_request", generation=1, operation=1))
        self.assertTrue(ok)
        self.assertEqual(state.bake_phase, "cancelled")
        self.assertEqual(state.bake_physical, "retiring")
        blocked, ok = project_step(state, ProjectEvent("save_ready", generation=1, operation=1))
        self.assertFalse(ok)
        self.assertEqual(blocked, state)
        state, ok = project_step(state, ProjectEvent("bake_retired", generation=1, operation=1))
        self.assertTrue(ok)
        state, ok = project_step(state, ProjectEvent("save_ready", generation=1, operation=1))
        self.assertTrue(ok)
        state, ok = project_step(state, ProjectEvent("save_complete", generation=1, operation=1, committed=True))
        self.assertTrue(ok)
        self.assertEqual(state.phase, "active")

    def test_intent_invalidates_readiness_and_old_receipts_are_rejected(self):
        state = self.ready_project()
        state, _ = project_step(state, ProjectEvent("intent", generation=1, revision=2))
        self.assertFalse(project_ready(state))
        old, ok = project_step(state, _owner_ready("grade", "native_grade_graph", "grade-graph", "grade-manifest"))
        self.assertFalse(ok)
        self.assertEqual(old, state)

    def test_old_attempt_failure_cannot_poison_successful_retry(self):
        state, _ = project_step(new_project(), ProjectEvent(
            "open", generation=1, owners=("grade",),
            owner_evaluators=(("grade", "native_grade_graph"),),
        ))
        state, _ = project_step(state, ProjectEvent("intent", generation=1, revision=1))
        state, _ = project_step(state, ProjectEvent("prepare_begin", generation=1, revision=1, attempt=1))
        state, _ = project_step(state, ProjectEvent("prepare_begin", generation=1, revision=1, attempt=2))
        stale, accepted = project_step(state, ProjectEvent(
            "owner_failed", generation=1, revision=1, attempt=1, owner="grade",
        ))
        self.assertFalse(accepted)
        self.assertEqual(stale, state)
        state, accepted = project_step(state, ProjectEvent(
            "owner_ready", generation=1, revision=1, attempt=2, owner="grade",
            evaluator="native_grade_graph", evaluator_id="grade-graph",
            manifest_id="grade-manifest", final_ready=True,
        ))
        self.assertTrue(accepted)
        self.assertTrue(project_ready(state))

    def test_save_and_render_gates_freeze_preparation_intent(self):
        state = self.ready_project()
        state, accepted = project_step(state, ProjectEvent("save_request", generation=1, operation=1))
        self.assertTrue(accepted)
        self.assertTrue(state.publication_hold)
        changed, accepted = project_step(state, ProjectEvent("intent", generation=1, revision=2))
        self.assertFalse(accepted)
        self.assertEqual(changed, state)
        changed, accepted = project_step(state, ProjectEvent(
            "owner_failed", generation=1, revision=1, attempt=1, owner="grade",
        ))
        self.assertFalse(accepted)
        self.assertEqual(changed, state)
        state, accepted = project_step(state, ProjectEvent("save_ready", generation=1, operation=1))
        self.assertTrue(accepted)

        state, accepted = project_step(state, ProjectEvent("save_complete", generation=1,
                                                            operation=1, committed=True))
        self.assertTrue(accepted)
        self.assertFalse(state.publication_hold)
        state, accepted = project_step(state, ProjectEvent("render_request", generation=1,
                                                           operation=1))
        self.assertTrue(accepted)
        changed, accepted = project_step(state, ProjectEvent("intent", generation=1, revision=2))
        self.assertFalse(accepted)
        self.assertEqual(changed, state)

    def test_render_publication_hold_requires_matching_native_terminal_receipt(self):
        state = self.ready_project()
        state, accepted = project_step(state, ProjectEvent(
            "render_request", generation=1, operation=1,
        ))
        self.assertTrue(accepted)
        wrong, accepted = project_step(state, ProjectEvent(
            "render_started", generation=1, operation=2,
        ))
        self.assertFalse(accepted)
        self.assertEqual(wrong, state)
        state, accepted = project_step(state, ProjectEvent(
            "render_started", generation=1, operation=1,
        ))
        self.assertTrue(accepted)
        wrong, accepted = project_step(state, ProjectEvent(
            "render_cancel", generation=1, operation=2,
        ))
        self.assertFalse(accepted)
        self.assertEqual(wrong, state)
        state, accepted = project_step(state, ProjectEvent(
            "render_cancel", generation=1, operation=1,
        ))
        self.assertTrue(accepted)
        self.assertFalse(state.publication_hold)

    def test_failed_native_save_releases_only_its_accepted_gate(self):
        state = self.ready_project()
        state, accepted = project_step(state, ProjectEvent(
            "save_request", generation=1, operation=1,
        ))
        self.assertTrue(accepted)
        state, accepted = project_step(state, ProjectEvent(
            "save_ready", generation=1, operation=1,
        ))
        self.assertTrue(accepted)
        wrong, accepted = project_step(state, ProjectEvent(
            "save_failed", generation=1, operation=2,
        ))
        self.assertFalse(accepted)
        self.assertEqual(wrong, state)
        state, accepted = project_step(state, ProjectEvent(
            "save_failed", generation=1, operation=1,
        ))
        self.assertTrue(accepted)
        self.assertEqual(state.phase, "active")

    def test_save_acceptance_holds_publication_while_owner_preparation_finishes(self):
        state, accepted = project_step(new_project(), ProjectEvent(
            "open", generation=1, owners=("grade",),
            owner_evaluators=(("grade", "native_grade_graph"),),
        ))
        self.assertTrue(accepted)
        state, accepted = project_step(state, ProjectEvent("intent", generation=1, revision=1))
        self.assertTrue(accepted)
        state, accepted = project_step(state, ProjectEvent(
            "prepare_begin", generation=1, revision=1, attempt=1,
        ))
        self.assertTrue(accepted)
        state, accepted = project_step(state, ProjectEvent(
            "save_request", generation=1, operation=1,
        ))
        self.assertTrue(accepted)
        self.assertTrue(state.publication_hold)
        unchanged, accepted = project_step(state, ProjectEvent(
            "save_ready", generation=1, operation=1,
        ))
        self.assertFalse(accepted)
        self.assertEqual(unchanged, state)
        state, accepted = project_step(state, ProjectEvent(
            "owner_ready", generation=1, revision=1, attempt=1, owner="grade",
            evaluator="native_grade_graph", evaluator_id="graph",
            manifest_id="manifest", final_ready=True,
        ))
        self.assertTrue(accepted)
        state, accepted = project_step(state, ProjectEvent(
            "save_ready", generation=1, operation=1,
        ))
        self.assertTrue(accepted)

    def test_render_acceptance_holds_publication_until_owner_preparation_finishes(self):
        state, accepted = project_step(new_project(), ProjectEvent(
            "open", generation=1, owners=("grade",),
            owner_evaluators=(("grade", "native_grade_graph"),),
        ))
        self.assertTrue(accepted)
        state, accepted = project_step(state, ProjectEvent("intent", generation=1, revision=1))
        self.assertTrue(accepted)
        state, accepted = project_step(state, ProjectEvent(
            "prepare_begin", generation=1, revision=1, attempt=1,
        ))
        self.assertTrue(accepted)
        state, accepted = project_step(state, ProjectEvent(
            "render_request", generation=1, operation=1,
        ))
        self.assertTrue(accepted)
        self.assertTrue(state.publication_hold)
        unchanged, accepted = project_step(state, ProjectEvent(
            "render_started", generation=1, operation=1,
        ))
        self.assertFalse(accepted)
        self.assertEqual(unchanged, state)
        state, accepted = project_step(state, ProjectEvent(
            "owner_ready", generation=1, revision=1, attempt=1, owner="grade",
            evaluator="native_grade_graph", evaluator_id="graph",
            manifest_id="manifest", final_ready=True,
        ))
        self.assertTrue(accepted)
        state, accepted = project_step(state, ProjectEvent(
            "render_started", generation=1, operation=1,
        ))
        self.assertTrue(accepted)

    def test_output_wait_records_owner_failure_and_requires_exact_retry(self):
        state = self.ready_project()
        state, accepted = project_step(state, ProjectEvent(
            "save_request", generation=1, operation=1,
        ))
        self.assertTrue(accepted)
        state, accepted = project_step(state, ProjectEvent(
            "output_owner_failed", generation=1, revision=1, attempt=1,
            owner="grade",
        ))
        self.assertTrue(accepted)
        unchanged, accepted = project_step(state, ProjectEvent(
            "save_ready", generation=1, operation=1,
        ))
        self.assertFalse(accepted)
        self.assertEqual(unchanged, state)
        state, accepted = project_step(state, ProjectEvent(
            "retry_owner", generation=1, revision=1, attempt=2, owner="grade",
        ))
        self.assertTrue(accepted)
        state, accepted = project_step(state, ProjectEvent(
            "prepare_begin", generation=1, revision=1, attempt=3,
        ))
        self.assertTrue(accepted)
        state, accepted = project_step(state, ProjectEvent(
            "owner_ready", generation=1, revision=1, attempt=3, owner="grade",
            evaluator="native_grade_graph", evaluator_id="grade-graph-2",
            manifest_id="grade-manifest-2", final_ready=True,
        ))
        self.assertTrue(accepted)
        state, accepted = project_step(state, ProjectEvent(
            "save_ready", generation=1, operation=1,
        ))
        self.assertTrue(accepted)

    def test_preview_can_queue_stack_bake_but_cannot_start_evaluation_or_save(self):
        state, accepted = project_step(new_project(), ProjectEvent(
            "open", generation=1, owners=("stack",),
            owner_evaluators=(("stack", "stack_65_lut"),),
        ))
        self.assertTrue(accepted)
        state, _ = project_step(state, ProjectEvent("intent", generation=1, revision=1))
        state, _ = project_step(state, ProjectEvent("prepare_begin", generation=1, revision=1, attempt=1))
        state, accepted = project_step(state, ProjectEvent(
            "owner_preview", generation=1, revision=1, attempt=1, owner="stack",
            evaluator="stack_33_lut", evaluator_id="preview33", manifest_id="recipe1",
        ))
        self.assertTrue(accepted)
        self.assertFalse(project_ready(state))
        state, accepted = project_step(state, ProjectEvent(
            "bake_request", generation=1, operation=1, owner="stack",
            source_revision=4, source_id="frozen", evaluator="stack_65_lut",
            preview_id="preview33", manifest_id="recipe1", final_ready=False,
        ))
        self.assertTrue(accepted)
        self.assertEqual(state.bake_phase, "waiting_for_final")
        unchanged, accepted = project_step(state, ProjectEvent(
            "bake_wait", generation=1, operation=1, evaluator="stack_65_lut",
            evaluator_id="wrong-lut", manifest_id="recipe1", final_ready=True,
        ))
        self.assertFalse(accepted)
        self.assertEqual(unchanged, state)
        self.assertFalse(project_ready(state))
        state, accepted = project_step(state, ProjectEvent(
            "owner_ready", generation=1, revision=1, attempt=1, owner="stack",
            evaluator="stack_65_lut", evaluator_id="lut65", manifest_id="recipe1",
            final_ready=True,
        ))
        self.assertTrue(accepted)
        state, accepted = project_step(state, ProjectEvent(
            "bake_wait", generation=1, operation=1, evaluator="stack_65_lut",
            evaluator_id="lut65", manifest_id="recipe1", final_ready=True,
        ))
        self.assertTrue(accepted)
        self.assertEqual(state.bake_phase, "evaluating")
        self.assertEqual(state.bake_evaluator_id, "lut65")
        self.assertTrue(project_ready(state))

    def test_restart_waits_for_exact_cleanup_receipts_and_live_bake_retirement(self):
        state = self.ready_project()
        state, _ = project_step(state, ProjectEvent(
            "bake_request", generation=1, operation=1, owner="stack",
            source_revision=4, source_id="frozen", evaluator="stack_65_lut",
            evaluator_id="stack-lut-65", manifest_id="stack-manifest", final_ready=True,
        ))
        state, _ = project_step(state, ProjectEvent("bake_started", generation=1, operation=1))
        state, accepted = project_step(state, ProjectEvent(
            "restart", generation=2, obligations=("worker-1", "reader-1"),
        ))
        self.assertTrue(accepted)
        unchanged, accepted = project_step(state, ProjectEvent(
            "restart_complete", generation=2,
        ))
        self.assertFalse(accepted)
        self.assertEqual(unchanged, state)
        state, accepted = project_step(state, ProjectEvent(
            "restart_retired", generation=2, owner="worker-1",
        ))
        self.assertTrue(accepted)
        unchanged, accepted = project_step(state, ProjectEvent(
            "restart_retired", generation=2, owner="unrelated",
        ))
        self.assertFalse(accepted)
        self.assertEqual(unchanged, state)
        state, accepted = project_step(state, ProjectEvent(
            "restart_retired", generation=2, owner="reader-1",
        ))
        self.assertTrue(accepted)
        unchanged, accepted = project_step(state, ProjectEvent(
            "restart_complete", generation=2,
        ))
        self.assertFalse(accepted)
        self.assertEqual(unchanged, state)
        state, accepted = project_step(state, ProjectEvent(
            "bake_retired", generation=2, operation=1,
        ))
        self.assertTrue(accepted)
        state, accepted = project_step(state, ProjectEvent(
            "restart_complete", generation=2,
        ))
        self.assertTrue(accepted)
        self.assertEqual(state.phase, "active")


if __name__ == "__main__":
    unittest.main()
