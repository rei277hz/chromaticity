import unittest

from color_tools.perceptual_grade_next_core.workflow.readiness import (
    BakeReceipt,
    BakeRequest,
    PreparationEvent,
    cancel_bake,
    complete_bake,
    expected_evaluator,
    final_ready,
    new_bake,
    new_preparation,
    preparation_step,
    preview_display_ready,
    start_bake,
    validate_ui_settings,
)


def begin(backend='grade', attempt=1, revision=1, plan_id='recipe'):
    return preparation_step(new_preparation(), dict_to_begin(
        backend=backend, attempt=attempt, revision=revision, plan_id=plan_id,
    ))


def dict_to_begin(*, backend, attempt, revision, plan_id):
    return PreparationEvent(
        'begin', owner='grade-a', revision=revision, attempt=attempt,
        backend=backend, plan_id=plan_id,
    )


class PreparationReadinessTests(unittest.TestCase):
    def test_grade_requires_complete_native_graph_descriptor(self):
        state, accepted = begin()
        self.assertTrue(accepted)
        event = _event(
            state, 'grade_ready', graph_id='graph', field_ids=('tone', 'color'),
            matrix_id='matrices', binding_id='bindings', verified=True,
        )
        state, accepted = preparation_step(state, event)
        self.assertTrue(accepted)
        self.assertTrue(final_ready(state))
        self.assertEqual(expected_evaluator(state), ('native_grade_graph', 'graph'))

    def test_duplicate_field_identity_does_not_certify_complete_graph(self):
        state, _ = begin()
        updated, accepted = preparation_step(state, _event(
            state, 'grade_ready', graph_id='graph', field_ids=('tone', 'tone'),
            matrix_id='matrices', binding_id='bindings', verified=True,
        ))
        self.assertFalse(accepted)
        self.assertEqual(updated, state)

    def test_preview_can_display_but_cannot_grant_final_or_bake_readiness(self):
        state, accepted = begin(backend='stack')
        self.assertTrue(accepted)
        state, accepted = preparation_step(state, _event(
            state, 'stack_preview', artifact_id='preview',
            source_lattice_id='recipe', verified=True,
        ))
        self.assertTrue(accepted)
        self.assertTrue(preview_display_ready(state))
        self.assertFalse(final_ready(state))
        self.assertIsNone(expected_evaluator(state))

    def test_stack_final_must_reuse_exact_preview_and_bind_full_lut(self):
        state, _ = begin(backend='stack')
        state, _ = preparation_step(state, _event(
            state, 'stack_preview', artifact_id='preview',
            source_lattice_id='recipe', verified=True,
        ))
        wrong, accepted = preparation_step(state, _event(
            state, 'stack_final', preview_id='other', artifact_id='lut',
            source_lattice_id='recipe', matrix_id='matrices', binding_id='bindings',
            preview_vertices_reused=True, verified=True,
        ))
        self.assertFalse(accepted)
        self.assertEqual(wrong, state)

        state, accepted = preparation_step(state, _event(
            state, 'stack_final', preview_id='preview', artifact_id='lut',
            source_lattice_id='recipe', matrix_id='matrices', binding_id='bindings',
            preview_vertices_reused=True, verified=True,
        ))
        self.assertTrue(accepted)
        self.assertTrue(final_ready(state))
        self.assertEqual(expected_evaluator(state), ('stack_65_lut', 'lut'))

    def test_final_rejects_unverified_even_vertex_reuse(self):
        state, _ = begin(backend='stack')
        state, _ = preparation_step(state, _event(
            state, 'stack_preview', artifact_id='preview',
            source_lattice_id='recipe', verified=True,
        ))
        updated, accepted = preparation_step(state, _event(
            state, 'stack_final', preview_id='preview', artifact_id='lut',
            source_lattice_id='recipe', matrix_id='matrices', binding_id='bindings',
            preview_vertices_reused=False, verified=True,
        ))
        self.assertFalse(accepted)
        self.assertEqual(updated, state)

    def test_final_cannot_alias_the_preview_resource(self):
        state, _ = begin(backend='stack')
        state, _ = preparation_step(state, _event(
            state, 'stack_preview', artifact_id='preview',
            source_lattice_id='recipe', verified=True,
        ))
        updated, accepted = preparation_step(state, _event(
            state, 'stack_final', preview_id='preview', artifact_id='preview',
            source_lattice_id='recipe', matrix_id='matrices', binding_id='bindings',
            preview_vertices_reused=True, verified=True,
        ))
        self.assertFalse(accepted)
        self.assertEqual(updated, state)

    def test_obsolete_attempt_receipt_cannot_certify_new_revision(self):
        state, _ = begin()
        newer, accepted = preparation_step(state, dict_to_begin(
            backend='grade', attempt=2, revision=2, plan_id='recipe-2',
        ))
        self.assertTrue(accepted)
        stale_receipt = _event(
            state, 'grade_ready', graph_id='old-graph', field_ids=('tone',),
            matrix_id='old-matrices', binding_id='old-bindings', verified=True,
        )
        stale, accepted = preparation_step(newer, stale_receipt)
        self.assertFalse(accepted)
        self.assertEqual(stale, newer)
        self.assertEqual(newer.phase, 'preparing')

    def test_cancelled_attempt_cannot_accept_late_receipt(self):
        state, _ = begin()
        state, accepted = preparation_step(state, _event(state, 'cancel'))
        self.assertTrue(accepted)
        updated, accepted = preparation_step(state, _event(
            state, 'grade_ready', graph_id='graph', field_ids=('tone',),
            matrix_id='matrices', binding_id='bindings', verified=True,
        ))
        self.assertFalse(accepted)
        self.assertEqual(updated.phase, 'cancelled')


class BakeReadinessTests(unittest.TestCase):
    def test_grade_bake_binds_native_graph_and_allows_native_helper_host(self):
        prep = _ready_grade()
        state, accepted = start_bake(new_bake(), prep, BakeRequest(
            operation=1, owner='grade-a', preparation_attempt=1, revision=1,
            source_revision=8, source_id='frozen-input', backend='grade',
            evaluator='native_grade_graph', evaluator_id='graph',
            execution_host='helper_process',
        ))
        self.assertTrue(accepted)
        self.assertEqual(state.execution_host, 'helper_process')
        receipt = BakeReceipt(
            operation=1, owner='grade-a', preparation_attempt=1, revision=1,
            source_revision=8, source_id='frozen-input', backend='grade',
            evaluator='native_grade_graph', evaluator_id='graph', result_id='bake-1',
            pixels_from_evaluator=True,
        )
        state, accepted = complete_bake(state, receipt)
        self.assertTrue(accepted)
        self.assertEqual(state.result_id, 'bake-1')

    def test_stack_bake_uses_final_lut_and_not_preview(self):
        prep = _ready_stack()
        base = dict(
            operation=1, owner='grade-a', preparation_attempt=1, revision=1,
            source_revision=8, source_id='frozen-input', backend='stack',
        )
        state, accepted = start_bake(new_bake(), prep, BakeRequest(
            **base, evaluator='stack_65_lut', evaluator_id='preview',
        ))
        self.assertFalse(accepted)
        self.assertEqual(state.phase, 'idle')

        state, accepted = start_bake(new_bake(), prep, BakeRequest(
            **base, evaluator='stack_65_lut', evaluator_id='lut',
        ))
        self.assertTrue(accepted)

    def test_cancelled_bake_rejects_late_native_receipt(self):
        prep = _ready_grade()
        state, _ = start_bake(new_bake(), prep, BakeRequest(
            operation=1, owner='grade-a', preparation_attempt=1, revision=1,
            source_revision=8, source_id='frozen-input', backend='grade',
            evaluator='native_grade_graph', evaluator_id='graph',
        ))
        state, accepted = cancel_bake(state, operation=1, owner='grade-a')
        self.assertTrue(accepted)
        state, accepted = complete_bake(state, BakeReceipt(
            operation=1, owner='grade-a', preparation_attempt=1, revision=1,
            source_revision=8, source_id='frozen-input', backend='grade',
            evaluator='native_grade_graph', evaluator_id='graph', result_id='late',
            pixels_from_evaluator=True,
        ))
        self.assertFalse(accepted)
        self.assertEqual(state.phase, 'cancelled')

    def test_result_from_other_input_or_evaluator_is_rejected(self):
        prep = _ready_grade()
        state, _ = start_bake(new_bake(), prep, BakeRequest(
            operation=1, owner='grade-a', preparation_attempt=1, revision=1,
            source_revision=8, source_id='input-a', backend='grade',
            evaluator='native_grade_graph', evaluator_id='graph',
        ))
        state_after, accepted = complete_bake(state, BakeReceipt(
            operation=1, owner='grade-a', preparation_attempt=1, revision=1,
            source_revision=8, source_id='input-b', backend='grade',
            evaluator='native_grade_graph', evaluator_id='graph', result_id='wrong',
            pixels_from_evaluator=True,
        ))
        self.assertFalse(accepted)
        self.assertEqual(state_after, state)


class UiDomainTests(unittest.TestCase):
    def test_supported_context_and_fit_endpoints(self):
        validate_ui_settings(
            grading_white='D65', reference_nits=203, working_space='ACEScg',
            source_white_xy=(0.3127, 0.329), tone_fit=-2,
            color_lightness_fit=-2, color_chroma_fit=6,
        )

    def test_rejects_unsupported_context_fit_and_space(self):
        base = dict(
            grading_white='D65', reference_nits=203, working_space='Linear Rec.709',
            source_white_xy=(0.3127, 0.329), tone_fit=0,
            color_lightness_fit=0, color_chroma_fit=0,
        )
        for overrides in (
            {'grading_white': 'D60'},
            {'reference_nits': 100},
            {'working_space': 'Display P3'},
            {'tone_fit': 2.0001},
            {'color_lightness_fit': -2.0001},
            {'color_chroma_fit': 6.0001},
            {'source_white_xy': (0.95, 0.4)},
        ):
            with self.subTest(overrides=overrides), self.assertRaises(ValueError):
                validate_ui_settings(**(base | overrides))


def _event(state, kind, **values):
    return PreparationEvent(
        kind, owner=state.owner, revision=state.revision,
        attempt=state.attempt, backend=state.backend, plan_id=state.plan_id,
        **values,
    )


def _ready_grade():
    state, _ = begin()
    state, _ = preparation_step(state, _event(
        state, 'grade_ready', graph_id='graph', field_ids=('tone', 'web'),
        matrix_id='matrices', binding_id='bindings', verified=True,
    ))
    return state


def _ready_stack():
    state, _ = begin(backend='stack')
    state, _ = preparation_step(state, _event(
        state, 'stack_preview', artifact_id='preview',
        source_lattice_id='recipe', verified=True,
    ))
    state, _ = preparation_step(state, _event(
        state, 'stack_final', preview_id='preview', artifact_id='lut',
        source_lattice_id='recipe', matrix_id='matrices', binding_id='bindings',
        preview_vertices_reused=True, verified=True,
    ))
    return state


if __name__ == '__main__':
    unittest.main()
