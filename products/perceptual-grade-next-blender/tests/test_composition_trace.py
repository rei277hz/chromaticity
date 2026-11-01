import unittest

from color_tools.perceptual_grade_next_blender.lifecycle import (
    ProjectWorkflow, RestartSupervisor, ScopeActor,
)
from color_tools.perceptual_grade_next_blender.output_gateway import OutputGateway
from color_tools.perceptual_grade_next_blender.project_readiness import ProjectReadiness
from color_tools.perceptual_grade_next_blender.restart import RestartController
from color_tools.perceptual_grade_next_core.workflow.restart import (
    RestartEvent, new_restart, restart_step,
)
from color_tools.perceptual_grade_next_core.workflow.composed import (
    ComposedEvent, composed_step, new_composed,
)


class CompositionTraceTests(unittest.TestCase):
    def test_restart_supervisor_replays_the_checked_core_transition(self):
        supervisor = RestartSupervisor()
        core = new_restart()
        generation = supervisor.request(("scope", "updates"))
        core, accepted = restart_step(core, RestartEvent(
            "request", generation=generation, obligations=("scope", "updates"),
        ))
        self.assertTrue(accepted)
        self.assertEqual(supervisor.phase, core.phase.replace("draining", "restarting"))
        for identity in ("updates", "scope"):
            self.assertEqual(supervisor.receipt(identity),
                             restart_step(core, RestartEvent(
                                 "retire", generation=generation, identity=identity,
                             ))[1])
            core, _accepted = restart_step(core, RestartEvent(
                "retire", generation=generation, identity=identity,
            ))
        core, core_accepted = restart_step(
            core, RestartEvent("complete", generation=generation),
        )
        self.assertTrue(core_accepted)
        self.assertTrue(supervisor.complete())
        self.assertEqual(supervisor.phase, core.phase.replace("draining", "restarting"))

    def test_output_gateway_tracks_the_readiness_workflow_across_document_reset(self):
        readiness = ProjectReadiness()
        gateway = OutputGateway(readiness.workflow)
        original = gateway.workflow
        readiness.begin_document()
        self.assertIs(gateway.workflow, original)
        self.assertIs(gateway.workflow, readiness.workflow)

    def test_restart_fences_project_and_requires_the_same_cleanup_receipts(self):
        workflow = ProjectWorkflow()
        self.assertTrue(workflow.dispatch(
            "open", generation=1, owners=(), owner_evaluators=(),
        ))
        controller = RestartController(
            begin=lambda _generation, obligations: (
                workflow.dispatch("restart", generation=2, obligations=obligations)
                and workflow.state.generation
            ),
            on_receipt=lambda generation, identity: workflow.dispatch(
                "restart_retired", generation=generation, owner=identity,
            ),
            on_complete=lambda generation: workflow.dispatch(
                "restart_complete", generation=generation,
            ),
        )
        self.assertEqual(controller.request(("scope", "updates")).phase, "draining")
        self.assertEqual(workflow.state.phase, "restarting")
        self.assertFalse(controller.receipt("old-scope"))
        self.assertTrue(controller.receipt("updates"))
        self.assertTrue(controller.receipt("scope"))
        self.assertEqual(controller.status.phase, "active")
        self.assertEqual(workflow.state.phase, "active")

    def test_restart_observations_settle_once_without_recursive_polling(self):
        observed = []
        recovered = []
        controller = RestartController(
            observe=lambda identity: observed.append(identity) or True,
            recover=lambda generation: recovered.append(generation),
        )

        status = controller.request(("scope", "updates"))

        self.assertEqual(status.phase, "active")
        self.assertEqual(set(observed), {"scope", "updates"})
        self.assertEqual(recovered, [status.generation])

    def test_late_scope_completion_does_not_mutate_project_workflow(self):
        scope = ScopeActor()
        workflow = ProjectWorkflow()
        self.assertTrue(scope.open(1, "app", view_epoch=1))
        self.assertTrue(scope.demand(1, 1, "source-a"))
        ticket = scope.begin(1, 1, "source-a", 1)
        self.assertIsNotNone(ticket)
        self.assertTrue(workflow.dispatch(
            "open", generation=1, owners=(), owner_evaluators=(),
        ))
        before = workflow.state
        self.assertTrue(scope.close())
        self.assertTrue(scope.complete(ticket))
        self.assertEqual(workflow.state, before)

    def test_scope_retirement_keeps_original_identity_across_restart(self):
        state, accepted = composed_step(
            new_composed(), ComposedEvent("open", generation=1, epoch=1),
        )
        self.assertTrue(accepted)
        state, accepted = composed_step(state, ComposedEvent(
            "scope_begin", generation=1, owner="scope", request=4,
            submission="submission-1", resource="resource-1",
        ))
        self.assertTrue(accepted)
        state, accepted = composed_step(state, ComposedEvent(
            "restart", generation=2, obligations=("scope", "updates"),
        ))
        self.assertTrue(accepted)
        self.assertEqual(state.scope_generation, 1)
        self.assertEqual(state.scope_submission, "submission-1")

        wrong, accepted = composed_step(state, ComposedEvent(
            "scope_retired", generation=2, owner="scope", request=4,
            submission="submission-1", resource="resource-1",
        ))
        self.assertFalse(accepted)
        self.assertEqual(wrong, state)

        retired, accepted = composed_step(state, ComposedEvent(
            "scope_retired", generation=1, owner="scope", request=4,
            submission="submission-1", resource="resource-1",
        ))
        self.assertTrue(accepted)
        self.assertEqual(retired.scope_physical, "none")
        self.assertFalse(composed_step(retired, ComposedEvent(
            "scope_retired", generation=1, owner="scope", request=4,
            submission="submission-1", resource="resource-1",
        ))[1])
        state, accepted = composed_step(state, ComposedEvent(
            "scope_retired", generation=1, owner="scope", request=4,
            submission="submission-1", resource="resource-1",
        ))
        self.assertTrue(accepted)
        state, accepted = composed_step(state, ComposedEvent(
            "obligation_retired", generation=2, identity="scope",
        ))
        self.assertTrue(accepted)
        state, accepted = composed_step(state, ComposedEvent(
            "obligation_retired", generation=2, identity="updates",
        ))
        self.assertTrue(accepted)
        state, accepted = composed_step(state, ComposedEvent(
            "restart_complete", generation=2,
        ))
        self.assertTrue(accepted)
        self.assertEqual(state.phase, "active")

    def test_bake_terminal_receipt_is_bound_to_original_generation_and_identity(self):
        state, accepted = composed_step(
            new_composed(), ComposedEvent("open", generation=1, epoch=1),
        )
        self.assertTrue(accepted)
        state, accepted = composed_step(state, ComposedEvent(
            "bake_start", generation=1, identity="bake-submission",
        ))
        self.assertTrue(accepted)
        state, accepted = composed_step(state, ComposedEvent(
            "restart", generation=2, obligations=("bake",),
        ))
        self.assertTrue(accepted)
        self.assertFalse(composed_step(state, ComposedEvent(
            "bake_retired", generation=2, identity="bake-submission",
        ))[1])
        retired, accepted = composed_step(state, ComposedEvent(
            "bake_retired", generation=1, identity="bake-submission",
        ))
        self.assertTrue(accepted)
        self.assertEqual(retired.bake_physical, "none")

    def test_restart_composes_project_and_scope_terminal_receipts(self):
        scope = ScopeActor()
        workflow = ProjectWorkflow()
        self.assertTrue(scope.open(1, "scope-owner", view_epoch=1))
        self.assertTrue(scope.demand(1, 1, "source-a"))
        ticket = scope.begin(1, 1, "source-a", 1)
        self.assertIsNotNone(ticket)
        self.assertTrue(workflow.dispatch(
            "open", generation=1, owners=(), owner_evaluators=(),
        ))

        def on_receipt(generation, identity):
            if identity == "scope" and not scope.retire(ticket):
                return False
            return workflow.dispatch(
                "restart_retired", generation=generation, owner=identity,
            )

        controller = RestartController(
            begin=lambda _generation, obligations: (
                workflow.dispatch("restart", generation=2, obligations=obligations)
                and workflow.state.generation
            ),
            drain=lambda _generation, _obligations: scope.close(),
            on_receipt=on_receipt,
            on_complete=lambda generation: workflow.dispatch(
                "restart_complete", generation=generation,
            ),
        )
        self.assertEqual(controller.request(("scope",)).phase, "draining")
        self.assertEqual(scope.state.physical, "retiring")
        self.assertEqual(workflow.state.phase, "restarting")
        self.assertTrue(controller.receipt("scope"))
        self.assertEqual(scope.state.physical, "none")
        self.assertEqual(workflow.state.phase, "active")
        self.assertFalse(controller.receipt("scope"))


if __name__ == "__main__":
    unittest.main()
