"""Concrete storage/CPython premises for the symbolic ownership reducer."""
import gc
import unittest
import weakref
import threading
from unittest.mock import patch

from color_tools.blender_runtime.ownership import OwnedField, OwnershipConfig, bind_holder
from color_tools.blender_runtime.execution.diagnostics import log_exception
from .test_app import MachineFixture
import logging


class Native:
    pass


class ArenaTests(MachineFixture, unittest.TestCase):
    def setUp(self):
        self.application = self.app(ownership=OwnershipConfig(self.machine('ownership')))
        self.ownership = self.application.ownership

    def test_observation_reuses_actor_snapshot_without_retaining_native_values(self):
        value = Native()
        raw = weakref.ref(value)
        ref = self.ownership.retain(value, 'observed')
        del value
        with self.ownership.observation() as observation:
            with patch.object(self.application.actors, 'call', wraps=self.application.actors.call) as calls:
                for _ in range(20):
                    self.assertIs(self.ownership.resolve(ref), raw())
                    self.assertEqual(self.ownership.generation_key(), observation.generation_key())
                snapshots = [call for call in calls.call_args_list if call.args[1].startswith('snapshot:')]
                self.assertEqual(len(snapshots), 1)
            self.ownership.release(ref)
            self.assertIsNone(raw())
            self.assertIsNone(observation.resolve(ref))
        with self.assertRaisesRegex(ReferenceError, 'closed'):
            observation.resolve(ref)

    def test_observation_handles_current_cell_membership_and_new_retention(self):
        first = self.ownership.retain(Native(), 'first')
        with self.ownership.observation() as observation:
            self.assertIsNotNone(observation.resolve(first))
            second = self.ownership.retain(Native(), 'second')
            self.ownership.release(first)
            self.assertIsNone(observation.resolve(first))
            self.assertIsNotNone(observation.resolve(second))
            with self.ownership.borrow(second):
                self.assertIsNotNone(observation.resolve(second))
            self.assertIsNotNone(observation.resolve(second))

    def test_boundary_revokes_observation_before_new_generation_is_visible(self):
        ref = self.ownership.retain(Native(), 'old')
        with self.ownership.observation() as observation:
            self.assertIsNotNone(observation.resolve(ref))
            self.ownership.begin_boundary()
            with self.assertRaisesRegex(ReferenceError, 'revoked'):
                observation.resolve(ref)
            tokens = self.ownership.native_replaced()
            with self.assertRaisesRegex(ReferenceError, 'revoked'):
                self.ownership.generation_key()
        with self.ownership.observation() as rebound:
            replacement = self.ownership.retain(Native(), 'replacement')
            self.assertIsNone(rebound.resolve(ref))
            self.assertIsNotNone(rebound.resolve(replacement))
        self.ownership.recovered(tokens)

    def test_failed_and_detached_arenas_revoke_observations(self):
        for action in ('detach', 'fail'):
            with self.subTest(action=action):
                app = self.app(ownership=OwnershipConfig(self.machine('ownership')))
                context = app.ownership
                ref = context.retain(Native(), action)
                with context.observation() as observation:
                    self.assertIsNotNone(observation.resolve(ref))
                    getattr(context.default, action)()
                    with self.assertRaisesRegex(ReferenceError, 'revoked'):
                        observation.resolve(ref)

    def test_observation_rejects_foreign_refs_and_terminal_app(self):
        from color_tools.blender_runtime import ClosedError, ForeignOwnerError
        other = self.app(ownership=OwnershipConfig(self.machine('ownership')))
        foreign = other.ownership.retain(Native(), 'foreign')
        ref = self.ownership.retain(Native(), 'local')
        with self.ownership.observation() as observation:
            with self.assertRaises(ForeignOwnerError):
                observation.resolve(foreign)
            self.application.close()
            with self.assertRaises(ClosedError):
                observation.resolve(ref)

    def test_nested_observations_close_without_reopening_revoked_parent(self):
        ref = self.ownership.retain(Native(), 'nested')
        with self.ownership.observation() as outer:
            with self.ownership.observation() as inner:
                self.assertIs(inner.resolve(ref), outer.resolve(ref))
                self.ownership.begin_boundary()
            with self.assertRaisesRegex(ReferenceError, 'revoked'):
                outer.resolve(ref)
        tokens = self.ownership.native_replaced()
        self.ownership.recovered(tokens)

    def test_observation_requires_entered_scope_on_its_original_thread(self):
        ref=self.ownership.retain(Native(),'thread')
        observation=self.ownership.observation()
        with self.assertRaisesRegex(RuntimeError,'not been entered'):
            observation.resolve(ref)
        failures=[]
        def other_thread():
            try:observation.resolve(ref)
            except RuntimeError as exc:failures.append(str(exc))
        with observation:
            thread=threading.Thread(target=other_thread)
            thread.start();thread.join()
            self.assertEqual(failures,['Native ownership observation belongs to another thread'])
            self.assertIsNotNone(observation.resolve(ref))

    def test_detach_revokes_before_reentrant_native_destruction(self):
        failures=[]
        with self.ownership.observation() as observation:
            class ReentrantNative:
                def __del__(self):
                    try:observation.check()
                    except ReferenceError as exc:failures.append(str(exc))
            ref=self.ownership.retain(ReentrantNative(),'destructor')
            self.assertIsNotNone(observation.resolve(ref))
            self.ownership.default.detach()
            self.assertEqual(failures,['Native ownership observation was revoked'])

    def test_detach_physically_releases_with_gc_disabled(self):
        arena = self.ownership.arena()
        value = Native()
        observed = weakref.ref(value)
        ref = arena.retain(value, 'fixture')
        cycle = [ref]
        cycle.append(cycle)
        del value, ref
        was_enabled = gc.isenabled()
        gc.disable()
        try:
            token = arena.begin()
            self.assertIsNone(observed())
            self.assertEqual(arena.physical_counts(), (0, 0))
            arena.native_replaced()
            arena.recovered(token)
        finally:
            if was_enabled: gc.enable()

    def test_unconditional_replacement_observes_live_borrow(self):
        arena = self.ownership.arena()
        ref = arena.retain(Native(), 'fixture')
        with arena.borrow(ref):
            token = arena.begin()
            self.assertEqual(arena.physical_counts(), (0, 1))
            arena.native_replaced()
            self.assertTrue(arena.state.unsafe)
            with self.assertRaises(RuntimeError): arena.recovered(token)
        self.assertEqual(arena.state.borrows, 0)
        self.assertTrue(arena.state.unsafe)

    def test_late_finalizer_cannot_release_new_cell(self):
        arena = self.ownership.arena()
        old = arena.retain(Native(), 'old')
        token = arena.begin()
        arena.native_replaced()
        new_value = Native()
        new = arena.retain(new_value, 'new')
        del old
        self.assertIs(arena.resolve(new), new_value)
        self.assertEqual(arena.physical_counts(), (1, 0))
        arena.recovered(token)

    def test_nested_recovery_does_not_consume_new_receipt(self):
        arena = self.ownership.arena()
        outer = arena.begin()
        arena.native_replaced()
        inner = arena.begin()
        arena.native_replaced()
        arena.recovered(inner)
        with self.assertRaises(RuntimeError): arena.recovered(outer)
        self.assertEqual(arena.state.phase, 0)

    def test_nested_pre_waits_for_outer_replacement_before_rebuilding(self):
        self.ownership.begin_boundary()
        self.ownership.begin_boundary()
        self.ownership.native_replaced()
        self.assertTrue(self.ownership.defer_pending_replacement())
        with self.assertRaisesRegex(RuntimeError, 'rejected'):
            self.ownership.retain(Native(), 'premature.inner.rebind')
        receipt = self.ownership.native_replaced()
        self.assertFalse(self.ownership.defer_pending_replacement())
        self.ownership.recovered(receipt)
        self.assertTrue(self.ownership.admits('discover'))
        value = Native()
        ref = self.ownership.retain(value, 'outer.rebind')
        self.assertIs(self.ownership.resolve(ref), value)

    def test_outer_replacement_cannot_hide_premature_inner_raw_cells(self):
        self.ownership.begin_boundary()
        self.ownership.begin_boundary()
        self.ownership.native_replaced()
        raw = self.ownership.retain(Native(), 'injected.unsafe.inner.rebind')
        receipt = self.ownership.native_replaced()
        with self.assertRaisesRegex(RuntimeError, 'unsafe'):
            self.ownership.recovered(receipt)
        self.assertTrue(any(arena.state.unsafe for arena in self.ownership.snapshots()))
        self.assertIsNone(self.ownership.resolve(raw))

    def test_descriptor_backing_field_has_no_native_object(self):
        class Holder:
            value = OwnedField('fixture.value')
        holder = Holder()
        bind_holder(holder, self.ownership)
        raw = Native()
        holder.value = raw
        self.assertIs(holder.value, raw)
        self.assertNotIn(raw, holder.__dict__.values())
        holder.value = None
        self.assertIsNone(holder.value)

    def test_fresh_session_fences_old_controller_against_late_retention(self):
        retired = self.ownership.snapshots()
        self.application.close()
        self.application = self.app(ownership=OwnershipConfig(self.machine('ownership')))
        self.ownership = self.application.ownership
        for arena in retired:
            with self.assertRaisesRegex(RuntimeError, 'rejected'):
                arena.retain(Native(), 'stale.module.callback')
        self.assertTrue(self.ownership.admits('discover'))

    def test_log_records_contain_diagnostic_text_only(self):
        logger = logging.getLogger('ownership-contract')
        with self.assertLogs(logger) as recorded:
            try:
                raise RuntimeError('native caller failed')
            except RuntimeError:
                log_exception(logger, 'failure in %s', 'fixture')
        record = recorded.records[0]
        self.assertIsNone(record.exc_info)
        self.assertIsNone(record.exc_text)
        self.assertTrue(all(type(arg) is str for arg in record.args))
        self.assertIn('native caller failed', record.getMessage())
