"""Check scheduling policies at their application API boundary."""

from dataclasses import fields
import unittest
from tests.blender_runtime.policy_fixture import bind_policy as Machine

from color_tools.blender_runtime import App, DomainError
from color_tools.perceptual_grade_core.graph import policies
from color_tools.perceptual_grade_core.graph.policies import lifecycle, exact, display


class SchedulingRuntimeTests(unittest.TestCase):
    def machine(self, name, queries=()):
        module = getattr(policies, name)
        return Machine(module, initializers=('new',),
                       queries=queries)

    def store(self, machine):
        app = App(package="scheduling_policies", storage_name="scheduling_policies")
        self.addCleanup(app.close)
        return app.store(machine=machine)

    def test_lifecycle_save_receipt_recovery_and_exact_action_tokens(self):
        machine = self.machine("lifecycle", ("lifecycle_admits",))
        store = self.store(machine)
        event = machine.event_type
        self.assertTrue(store.dispatch(event("save_begin")).accept)
        self.assertFalse(store.dispatch(event("save_done")).accept)
        self.assertTrue(store.state.dirty)
        self.assertTrue(store.dispatch(event("save_ready")).accept)
        self.assertTrue(store.dispatch(event("save_done")).accept)
        self.assertEqual(store.state.phase, 0)
        store.dispatch(event("recover"))
        for action in ("publish", "worker", 0, 10):
            self.assertFalse(store.query("lifecycle_admits", action=action))
        for action in ("timer", "rebind"):
            self.assertTrue(store.query("lifecycle_admits", action=action))
        with self.assertRaises(DomainError):
            store.query("lifecycle_admits", action=True)
        self.assertTrue(store.dispatch(event("recovered")).accept)
        self.assertTrue(store.query("lifecycle_admits", action="publish"))

    def test_exact_output_retains_native_lease_until_physical_stop(self):
        machine = self.machine("exact")
        store = self.store(machine)
        event = machine.event_type
        owner = dict(operation=11, session=3, revision=0, frame=0)
        self.assertTrue(store.dispatch(event("begin", **owner, key=7)).accept)
        self.assertFalse(store.dispatch(event("native_begin", **owner, key=7, token=19)).invoke)
        self.assertFalse(store.dispatch(event("validated", **owner, key=7, resolution=33)).accept)
        self.assertTrue(store.dispatch(event("validated", **owner, key=7, resolution=65)).accept)
        preview = store.preview(event("native_begin", **owner, key=7, token=19))
        self.assertTrue(preview.effects.invoke)
        self.assertEqual(store.state.lease, 0)
        self.assertTrue(store.dispatch(event("native_begin", **owner, key=7, token=19)).invoke)
        self.assertTrue(store.dispatch(event("native_result", **owner, token=19, outcome=1)).accept)
        self.assertFalse(store.dispatch(event("settled", **owner, token=19)).accept)
        self.assertEqual(store.state.lease, 19)
        self.assertTrue(store.dispatch(event("native_stopped", **owner, token=19)).accept)
        self.assertTrue(store.dispatch(event("settled", **owner, token=19)).accept)
        self.assertEqual(store.state.lease, 0)
        self.assertTrue(store.dispatch(event("next_frame", **owner, key=8)).advance)
        self.assertEqual((store.state.frame, store.state.revision), (1, 1))

    def test_display_retains_previous_components_without_mixing_current_results(self):
        machine = self.machine("display", ("scope_display_current", "scope_display_statistics_match"))
        store = self.store(machine)
        event = machine.event_type
        owner = dict(source=5, slot=2)
        store.dispatch(event("invalidate", **owner))
        store.dispatch(event("request", **owner, analysis=10, geometry=3, epoch=1))
        self.assertTrue(store.dispatch(event("visual", **owner, analysis=10, geometry=3,
                                             epoch=1, capture=21, validated=True)).replace_visual)
        self.assertFalse(store.query("scope_display_current", statistics_required=True))
        self.assertTrue(store.dispatch(event("statistics", **owner, analysis=10, geometry=3,
                                             epoch=1, capture=21, validated=True)).replace_statistics)
        self.assertTrue(store.query("scope_display_current", statistics_required=True))
        store.dispatch(event("request", **owner, analysis=11, geometry=3, epoch=2))
        self.assertTrue(store.state.visual_available)
        self.assertTrue(store.query("scope_display_statistics_match"))
        self.assertFalse(store.query("scope_display_current", statistics_required=False))
        store.dispatch(event("visual", **owner, analysis=11, geometry=3,
                             epoch=2, capture=22, validated=True))
        self.assertFalse(store.query("scope_display_statistics_match"))
        self.assertTrue(store.query("scope_display_current", statistics_required=False))
        self.assertFalse(store.query("scope_display_current", statistics_required=True))

    def test_policy_types_domains_and_frozen_records_are_accepted_by_machine(self):
        for name in ("lifecycle", "exact", "display"):
            machine = self.machine(name)
            store = self.store(machine)
            original = store.state
            self.assertIsNone(machine.validate_state(original))
            self.assertTrue(all(field.type in (bool, int) for field in fields(original)))
            with self.subTest(name=name), self.assertRaises(DomainError):
                store.dispatch(machine.event_type(kind="unknown"))
            self.assertIs(store.state, original)
            with self.subTest(name=name), self.assertRaises(DomainError):
                store.dispatch(machine.event_type(kind=True))
            self.assertIs(store.state, original)


if __name__ == "__main__":
    unittest.main()
