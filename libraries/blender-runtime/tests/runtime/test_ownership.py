"""Ownership and edge-effect runtime regressions."""
from dataclasses import replace
import unittest
from unittest.mock import Mock

from color_tools.blender_runtime.ownership import OwnershipConfig, arena
from tests.blender_runtime.test_app import MachineFixture


class OwnershipPolicyTests(MachineFixture, unittest.TestCase):
    def test_retry_rebind_preserves_generation_cells_and_revokes_observation(self):
        machine = self.machine('ownership')
        app = self.app(ownership=OwnershipConfig(machine, keys=lambda value: (None, None, None)))
        owner = app.ownership.arena()
        app.ownership.begin_boundary()
        tokens = app.ownership.native_replaced()
        value = object()
        reference = owner.retain(value, 'current rebind')
        with app.ownership.observation() as observed:
            self.assertIs(owner.resolve(reference, observed), value)
            app.ownership.fail()
            before = owner.state
            self.assertEqual(app.ownership.retry_recovery(tokens), tokens)
            self.assertEqual(owner.state, replace(before, phase=arena.REBIND))
            with self.assertRaises(ReferenceError):
                observed.check()
        self.assertIs(owner.resolve(reference), value)
        app.ownership.recovered(tokens)

    def test_retry_rejects_foreign_generation_borrows_and_unsafe_ownership(self):
        machine = self.machine('ownership')
        for fields in ({'token':1,'epoch':2}, {'borrows':1}, {'unsafe':True}, {'phase':arena.ACTIVE}):
            state = replace(machine.module.new(), phase=arena.FAILED, **fields) if 'phase' not in fields else machine.module.new()
            after, effects = machine.module.step(state, machine.module.Event(kind='retry', token=0))
            self.assertFalse(effects.accepted)
            self.assertEqual(after, state)

    def ownership(self):
        return self.app().store(machine=self.machine('ownership'))

    def event(self, store, kind, token=0):
        return store.dispatch(store.machine.module.Event(kind=kind, token=token)).accepted


    def test_nested_boundary_never_accepts_outer_recovery(self):
        store = self.ownership()
        self.event(store, 'begin')
        outer = store.state.token
        self.event(store, 'begin')
        inner = store.state.token
        self.event(store, 'detach')
        self.event(store, 'replace')
        self.assertTrue(self.event(store, 'recovered', inner))
        before = store.state
        self.assertFalse(self.event(store, 'recovered', outer))
        self.assertEqual(store.state, before)

    def test_cleanup_failure_cannot_veto_native_replacement(self):
        store = self.ownership()
        self.event(store, 'retain')
        self.event(store, 'borrow')
        for kind in ('begin', 'fail', 'detach', 'replace'):
            self.assertTrue(self.event(store, kind))
        self.assertTrue(store.state.unsafe)
        self.assertEqual(store.state.borrows, 1)
        self.event(store, 'release')
        for kind in ('begin', 'detach', 'replace', 'recovered'):
            self.event(store, kind, store.state.token)
        self.assertTrue(store.state.unsafe)
        self.assertFalse(store.query('admits', action='discover'))

    def test_partial_effect_multiplicity_and_failed_compensation(self):
        machine = self.machine('edge_effect')
        count = 2  # Multiplicity is observed by the trusted collection adapter.
        store = self.app().store(machine=machine, initial=dict(occurrence=7, before=count, after=1))
        def dispatch(kind, occurrence=7):
            store.dispatch(machine.module.Event(kind=kind, occurrence=occurrence))
        dispatch('ARM')
        self.assertFalse(store.state.known)
        dispatch('COMPENSATION_FAILED')
        self.assertFalse(store.preview(machine.module.Event(kind='COMMIT', occurrence=7)).state.retired)
        before = store.state
        dispatch('COMPENSATED', 99)
        self.assertEqual(store.state, before)
        dispatch('COMPENSATED')
        self.assertEqual(store.state.current, 2)
        self.assertTrue(store.state.retired)

    def test_unsafe_arena_cannot_acquire_or_project_native_identity(self):
        machine = self.machine('ownership')
        for phase in (arena.ACTIVE, arena.FENCED, arena.REBIND, arena.FAILED):
            # ACTIVE+unsafe is an adversarial valid state, but cannot be reached
            # from the checked initializer. Preserve that original pure case
            # without exposing an unchecked Store initializer to production.
            state = replace(machine.module.new(), phase=phase, unsafe=True)
            self.assertTrue(machine.module.state_valid(state))
            for kind in ('retain', 'borrow'):
                unchanged, effects = machine.module.step(state, machine.module.Event(kind=kind, token=0))
                self.assertFalse(effects.accepted)
                self.assertEqual(unchanged, state)
            if phase == arena.ACTIVE:
                continue
            project = Mock(return_value=(None, None, None))
            app = self.app(ownership=OwnershipConfig(machine, keys=project))
            owner = app.ownership.arena()
            reference = owner.retain(object(), 'fixture')
            with owner.borrow(reference):
                owner.begin()
                owner.native_replaced()
            if phase == arena.FENCED:
                owner.begin()
            elif phase == arena.FAILED:
                owner.fail()
            self.assertEqual(owner.state.phase, phase)
            self.assertTrue(owner.state.unsafe)
            project.reset_mock()
            project.side_effect = AssertionError('Native projection ran')
            with self.assertRaisesRegex(RuntimeError, 'rejected'):
                owner.retain(object(), 'fixture')
            project.assert_not_called()
            self.assertEqual(owner.physical_counts(), (0, 0))

    def test_nested_pre_defers_all_retention_until_outer_replacement(self):
        store = self.ownership()
        self.event(store, 'begin')
        outer = store.state.token
        for kind in ('begin', 'detach', 'replace', 'defer'):
            self.event(store, kind)
        self.assertNotEqual(store.state.token, outer)
        self.assertEqual(store.state.cells, 0)
        self.assertFalse(store.query('admits', action='rebind'))
        for kind in ('retain', 'borrow'):
            before = store.state
            self.assertFalse(self.event(store, kind))
            self.assertEqual(store.state, before)
        self.event(store, 'replace')
        self.assertTrue(self.event(store, 'recovered', store.state.token))
        self.assertEqual(store.state.phase, arena.ACTIVE)
        self.assertFalse(store.state.unsafe)
