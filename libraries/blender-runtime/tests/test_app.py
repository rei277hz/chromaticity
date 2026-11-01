"""Same-import App isolation using the framework policy modules."""
from dataclasses import FrozenInstanceError
import gc
from importlib import import_module
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
import weakref
from unittest.mock import patch

from color_tools.blender_runtime import App, ClosedError, DomainError, ExecutionConfig, ForeignOwnerError, Machine, PendingTransitionError
from color_tools.blender_runtime.blender import BlenderConfig


class MachineFixture:
    def machine(self, name):
        cache = self.__dict__.setdefault('_machines', {})
        if name not in cache:
            module = import_module('color_tools.blender_runtime.policies.' + name)
            queries = {
                'attempt': ('occupied', 'can_clean', 'can_admit'),
                'gpu': ('gpu_available',), 'retry': (), 'startup': (),
                'ownership': ('admits', 'resolves'), 'edge_effect': ('edge_count',),
            }
            from color_tools.blender_runtime.machines import policy_machine
            cache[name] = policy_machine(name, queries=queries[name])
        return cache[name]

    def app(self, **settings):
        app = App(package='test_product', storage_name='test_product', **settings)
        self.addCleanup(app.close)
        return app


class AppTests(MachineFixture, unittest.TestCase):
    def test_retirement_callbacks_retry_before_registration_and_actor_shutdown(self):
        from color_tools.blender_runtime.machines import coordinator_machine
        events = []
        runtime = SimpleNamespace(closed=False, fenced=False,
            shutdown=lambda: (events.append('helper-exit') or SimpleNamespace(clean=True)))
        app = self.app(execution=ExecutionConfig(lambda owner: runtime), blender=BlenderConfig(),
                       lifecycle=coordinator_machine('lifecycle'))
        app.execution.get_runtime()
        store = app.store(machine=self.machine('startup'), initial=dict(failures=0))
        attempts = []
        def retire():
            events.append('retire')
            attempts.append(store._dispatch_cleanup(store.machine.event_type('failed')))
            if len(attempts) == 1:
                raise RuntimeError('pending retirement')
        app.on_retired(retire)
        app.blender.registration.defer(lambda: events.append('registration'))
        with self.assertRaises(ExceptionGroup):
            app.close()
        self.assertFalse(app.closed)
        self.assertTrue(app.actors.thread.is_alive())
        self.assertEqual(app.lifecycle.state.phase, 'repair_needed')
        self.assertEqual(events, ['helper-exit', 'retire'])
        app.close()
        self.assertEqual(events, ['helper-exit', 'retire', 'helper-exit', 'retire', 'registration'])
        self.assertEqual(len(attempts), 2)
        self.assertFalse(app.actors.thread.is_alive())

    def test_timed_out_dispatch_is_reconciled_once_before_terminal_close(self):
        app = self.app()
        store = app.store(machine=self.machine('startup'), initial=dict(failures=0))
        entered, release = threading.Event(), threading.Event()
        def hold_actor_loop():
            entered.set()
            release.wait(2)
        app.actors.loop.call_soon_threadsafe(hold_actor_loop)
        self.assertTrue(entered.wait(1))
        app.actors.timeout = .01
        try:
            with self.assertRaises(PendingTransitionError) as pending:
                store.dispatch(store.machine.event_type('failed'))
            self.assertTrue(app.fenced)
            token = pending.exception.token
            self.assertIn(token, app.actors.pending)
            self.assertFalse(app.actors.pending[token][1].cancelled())
        finally:
            release.set()
            app.actors.timeout = 2
        receipt = app.reconcile(token)
        self.assertTrue(receipt.accepted)
        self.assertIs(app.reconcile(token), receipt)
        self.assertEqual(store.state.failures, 1)
        self.assertEqual(app.actors.pending, {})
        app.close()
        self.assertTrue(app.closed)

    def test_construction_is_inert_and_execution_is_optional_lazy(self):
        calls = []
        def factory(app):
            calls.append(app)
            return SimpleNamespace(closed=False, fenced=False, shutdown=lambda: SimpleNamespace(clean=True))
        first = self.app(execution=ExecutionConfig(factory))
        second = self.app()
        self.assertEqual(calls, [])
        self.assertIsNone(first.execution.current_runtime())
        self.assertIsNone(second.execution)
        self.assertIsNone(second.ownership)
        self.assertIsNone(second.blender)
        runtime = first.execution.get_runtime()
        self.assertIs(runtime, first.execution.get_runtime())
        self.assertEqual(calls, [first])
        first.close()
        self.assertTrue(runtime.fenced)
        with self.assertRaises(ClosedError):
            first.execution.get_runtime()

    def test_stores_preview_and_commit_independently_with_colliding_ids(self):
        machine = self.machine('attempt')
        first, second = self.app(), self.app()
        left = first.store(machine=machine, initial=dict(identity=1, generation=0, interests=1))
        right = second.store(machine=machine, initial=dict(identity=1, generation=0, interests=1))
        self.assertEqual(left.identity, right.identity)
        event = machine.module.Event(kind='start', identity=1, generation=0)
        preview = left.preview(event)
        self.assertEqual(preview.state.phase, 1)
        self.assertEqual(left.state.phase, 0)
        self.assertTrue(left.dispatch(event).accepted)
        self.assertEqual(left.state.phase, 1)
        self.assertEqual(right.state.phase, 0)
        self.assertTrue(left.query('occupied'))
        self.assertFalse(right.query('occupied'))
        with self.assertRaises(FrozenInstanceError):
            left.state.phase = 0
        with self.assertRaises(ForeignOwnerError):
            second.require_store(left)
        with self.assertRaises(ForeignOwnerError):
            right.dispatch(left.event(event))
        peer_store = first.store(machine=machine, initial=dict(identity=1, generation=0, interests=1))
        with self.assertRaises(ForeignOwnerError):
            peer_store.dispatch(left.event(event))
        first.close()
        with self.assertRaises(ClosedError):
            left.dispatch(event)
        self.assertTrue(right.dispatch(event).accepted)
        fresh = self.app()
        self.assertNotIn(fresh.identity, (first.identity, second.identity))

    def test_rejected_effect_still_commits_valid_transition(self):
        machine = self.machine('startup')
        store = self.app().store(machine=machine, initial=dict(failures=1))
        event = machine.module.Event(kind='failed')
        self.assertFalse(store.preview(event).effects.accepted)
        self.assertEqual(store.state.failures, 1)
        self.assertFalse(store.dispatch(event).accepted)
        self.assertEqual(store.state.failures, 2)

    def test_receipt_reduces_against_current_state_after_reentry(self):
        machine = self.machine('startup')
        store = self.app().store(machine=machine, initial=dict(failures=0))
        receipt = store.event(machine.module.Event(kind='failed'))
        store.dispatch(machine.module.Event(kind='failed'))
        self.assertFalse(store.dispatch(receipt).accepted)
        self.assertEqual(store.state.failures, 2)

    def test_invalid_initializer_and_event_cannot_partially_commit(self):
        machine = self.machine('attempt')
        app = self.app()
        with self.assertRaises(DomainError):
            app.store(machine=machine, initial=dict(identity=True, generation=0, interests=1))
        with self.assertRaises(ValueError):
            app.store(machine=machine, initial=dict(identity=0, generation=0, interests=1))
        self.assertEqual(len(app._stores), 0)
        store = app.store(machine=machine, initial=dict(identity=1, generation=0, interests=1))
        original = store.state
        for event in (machine.module.Event(kind='unknown', identity=1, generation=0),
                      machine.module.Event(kind='start', identity=True, generation=0),
                      {'kind': 'start', 'identity': 1, 'generation': 0}):
            with self.subTest(event=event), self.assertRaises(DomainError):
                store.dispatch(event)
            self.assertIs(store.state, original)
        with self.assertRaises(TypeError):
            app.store(machine=lambda state, event: (state, ()))

    def test_two_apps_registration_and_timer_failure_isolation(self):
        timers, handlers, calls = set(), [], []
        host = SimpleNamespace(app=SimpleNamespace(timers=SimpleNamespace(
            is_registered=lambda callback: callback in timers,
            register=lambda callback, **settings: timers.add(callback), unregister=timers.remove)))
        first, second = self.app(blender=BlenderConfig()), self.app(blender=BlenderConfig())
        left, right = lambda: None, lambda: None
        def broken():
            calls.append('broken')
            if len(calls) == 1:
                raise RuntimeError('fixture cleanup failure')
        with patch.dict(sys.modules, {'bpy': host}):
            first.blender.registration.handler(handlers, left)
            second.blender.registration.handler(handlers, right)
            first.blender.registration.timer(left)
            second.blender.registration.timer(right)
            first.blender.registration.defer(broken)
            with self.assertRaises(ExceptionGroup):
                first.close()
            self.assertFalse(first.closed)
            self.assertTrue(first.fenced)
            self.assertEqual(calls, ['broken'])
            self.assertEqual(handlers, [right])
            self.assertEqual(timers, {right})
            first.close()
            self.assertEqual(calls, ['broken', 'broken'])
            second.close()
        self.assertEqual(handlers, [])
        self.assertEqual(timers, set())


class RuntimeTests(MachineFixture, unittest.TestCase):
    def setUp(self):
        from color_tools import blender_runtime as invariant
        from color_tools import invariant as actor_runtime
        from color_tools.blender_runtime.execution.machines import ExecutionMachines
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.package = self.root / 'private'
        self.package.mkdir()
        shutil.copytree(Path(invariant.__file__).parent, self.package / 'blender_runtime',
                        ignore=shutil.ignore_patterns('__pycache__'))
        shutil.copytree(Path(actor_runtime.__file__).parent, self.package / 'invariant',
                        ignore=shutil.ignore_patterns('__pycache__'))
        (self.package / 'operations.py').write_text('''from pathlib import Path
import os
def dispatch(operation, inputs, context):
    context.checkpoint()
    if operation == 'crash_once':
        marker = Path(context.payloads.path) / 'crashed_once'
        if not marker.exists():
            marker.write_text('crashed')
            os._exit(23)
    return inputs['value']
''')
        self.machines = ExecutionMachines(*(self.machine(name) for name in ('attempt', 'gpu', 'retry', 'startup')))

    def execution_app(self, name):
        from color_tools.blender_runtime.execution.contracts import RuntimeLimits, RuntimeProfile
        from color_tools.blender_runtime.execution.runtime import ExecutionRuntime
        profile = RuntimeProfile(lanes=('cpu',), gpu_probes=(), fallback_lane='cpu', dispatcher='operations')
        def factory(app):
            return ExecutionRuntime(self.root / name, app=app, machines=self.machines, package=self.package,
                profile=profile, limits=RuntimeLimits(startup_seconds=10., shutdown_seconds=.2),
                environment=dict(os.environ, PYTHONPATH=os.pathsep.join(sys.path)))
        return self.app(execution=ExecutionConfig(factory))

    def test_same_import_runtimes_reject_foreign_handles_and_close_independently(self):
        from color_tools.blender_runtime.execution.contracts import JobSpec
        first, second = self.execution_app('first'), self.execution_app('second')
        left, right = first.execution.get_runtime(), second.execution.get_runtime()
        a = left.submit(JobSpec('value', {'value': 11}, lane='cpu'))
        b = right.submit(JobSpec('value', {'value': 22}, lane='cpu'))
        self.assertEqual(a.identity, b.identity)
        with self.assertRaises(ForeignOwnerError):
            left.cancel(b)
        with self.assertRaises(ForeignOwnerError):
            right.wait_exact([a])
        self.assertFalse(a.cancelled())
        self.assertFalse(b.cancelled())
        self.assertEqual(a.result(timeout=15), 11)
        self.assertEqual(b.result(timeout=15), 22)
        first.close()
        self.assertTrue(left.closed)
        self.assertFalse(right.closed)
        self.assertEqual(right.submit(JobSpec('value', {'value': 33}, lane='cpu')).result(timeout=15), 33)

    def test_dirty_terminal_runtime_preserves_journal_and_allows_fresh_recovery(self):
        first = self.execution_app('dirty')
        runtime = first.execution.get_runtime()
        identity = runtime.session.path.name
        runtime.cleanup_blocked = True
        first.close()
        self.assertTrue(first.closed)
        self.assertTrue(runtime.physical_terminal())
        self.assertFalse(runtime._shutdown_report.clean)
        self.assertFalse(json.loads((runtime.session.path / 'journal.json').read_text())['clean'])
        successor = self.execution_app('dirty').execution.get_runtime()
        self.assertIn((identity, False), successor.session.recovered)

    def test_unconfirmed_helper_exit_retains_lease_and_retries_physical_retirement(self):
        from color_tools.blender_runtime.execution.contracts import JobSpec
        application = self.execution_app('retry_shutdown')
        runtime = application.execution.get_runtime()
        self.assertEqual(runtime.submit(JobSpec('value', {'value': 7}, lane='cpu')).result(timeout=15), 7)
        helper = runtime.helpers['cpu']
        with patch.object(runtime, '_send', return_value=None), \
             patch.object(helper, 'kill', side_effect=OSError('Injected process retirement failure')):
            with self.assertRaises(ExceptionGroup):
                application.close()
        self.assertTrue(application.fenced)
        self.assertFalse(application.closed)
        self.assertFalse(runtime.physical_terminal())
        self.assertFalse(runtime.session.lease.file.closed)
        self.assertIs(runtime.helpers['cpu'], helper)
        dirty = runtime._shutdown_report
        self.assertFalse(dirty.clean)
        application.close()
        self.assertTrue(application.closed)
        self.assertTrue(runtime.physical_terminal())
        self.assertIsNotNone(helper.process.poll())
        self.assertFalse(runtime._shutdown_report.clean)
        self.assertEqual(runtime._shutdown_report.errors, dirty.errors)
        self.assertFalse(json.loads((runtime.session.path / 'journal.json').read_text())['clean'])

    def test_active_crash_consumes_only_its_retry_budget(self):
        from color_tools.blender_runtime.execution.contracts import JobSpec
        app = self.execution_app('crash')
        runtime = app.execution.get_runtime()
        active = runtime.submit(JobSpec('crash_once', {'value': 'active'}, lane='cpu'))
        peers = [runtime.submit(JobSpec('value', {'value': index}, lane='cpu')) for index in range(3)]
        self.assertEqual(active.result(timeout=20), 'active')
        self.assertEqual(runtime.wait_exact(peers), [0, 1, 2])
        self.assertEqual(active._job.retries, 1)
        self.assertEqual([handle._job.retries for handle in peers], [0, 0, 0])
        self.assertEqual([handle._job.order for handle in peers], sorted(handle._job.order for handle in peers))
        self.assertTrue(all(not handle.cancelled() for handle in peers))


class OwnershipTests(MachineFixture, unittest.TestCase):
    def ownership_app(self, **settings):
        from color_tools.blender_runtime.ownership import OwnershipConfig
        return self.app(ownership=OwnershipConfig(self.machine('ownership')), **settings)

    def test_actor_thread_finalizer_retains_native_value_until_foreground_drain(self):
        app=self.ownership_app()
        arena=app.ownership.default
        destroyed=[]
        class NativeValue:
            def __del__(self):destroyed.append(threading.get_ident())
        value=NativeValue()
        held=[arena.retain(value,'thread.finalizer')]
        del value
        released=threading.Event()
        def collect_on_actor():
            held.clear()
            gc.collect()
            released.set()
        app.actors.loop.call_soon_threadsafe(collect_on_actor)
        self.assertTrue(released.wait(2))
        self.assertEqual(destroyed,[])
        self.assertEqual(arena.physical_counts(),(1,0))
        app.drain_finalizers()
        self.assertEqual(destroyed,[threading.get_ident()])
        self.assertEqual(arena.physical_counts(),(0,0))

    def test_queued_finalizer_cannot_drop_a_replacement_or_query_a_closed_actor(self):
        app=self.ownership_app()
        arena=app.ownership.default
        held=[arena.retain(object(),'old.generation')]
        released=threading.Event()
        def collect_on_actor():
            held.clear()
            released.set()
        app.actors.loop.call_soon_threadsafe(collect_on_actor)
        self.assertTrue(released.wait(2))
        token=arena.begin()
        arena.native_replaced()
        arena.recovered(token)
        value=object()
        replacement=arena.retain(value,'new.generation')
        app.drain_finalizers()
        self.assertIs(arena.resolve(replacement),value)
        self.assertEqual(arena.physical_counts(),(1,0))
        app.close()
        del replacement
        gc.collect()
        app.drain_finalizers()
        self.assertEqual(arena.physical_counts(),(0,0))

    def test_same_import_arena_domains_reject_colliding_foreign_references(self):
        first, second = self.ownership_app(), self.ownership_app()
        left, right = object(), object()
        a, b = first.ownership.retain(left, 'left'), second.ownership.retain(right, 'right')
        self.assertEqual((a.arena, a.cell), (b.arena, b.cell))
        self.assertNotEqual(a.domain, b.domain)
        for operation in (first.ownership.resolve, first.ownership.release, first.ownership.borrow):
            with self.subTest(operation=operation), self.assertRaises(ForeignOwnerError):
                operation(b)
        tokens = first.ownership.begin_boundary()
        with self.assertRaises(ForeignOwnerError):
            second.ownership.recovered(tokens)
        first.ownership.recovered(first.ownership.native_replaced())
        self.assertIsNone(first.ownership.resolve(a))
        self.assertIs(second.ownership.resolve(b), right)
        first.close()
        self.assertIs(second.ownership.resolve(b), right)

    def test_terminal_cleanup_preserves_original_borrow_accounting(self):
        app = self.ownership_app()
        arena = app.ownership.arena()
        value = object()
        ref = arena.retain(value, 'borrow')
        with arena.borrow(ref) as borrowed:
            with self.assertRaises(ExceptionGroup):
                app.close()
            self.assertFalse(app.closed)
            self.assertTrue(app.fenced)
            self.assertIs(borrowed, value)
            self.assertEqual(arena.physical_counts(), (0, 1))
            self.assertEqual(arena.state.borrows, 1)
            self.assertIsNone(arena.resolve(ref))
        self.assertEqual(arena.physical_counts(), (0, 0))
        self.assertEqual(arena.state.borrows, 0)
        app.close()
        self.assertTrue(app.closed)

    def test_new_arena_cannot_bypass_pending_native_boundary(self):
        from color_tools.blender_runtime.ownership import Arena
        app = self.ownership_app()
        context = app.ownership
        first, second = Arena(context), context.arena()
        self.assertIsNot(first, second)
        self.assertIsNone(context._default)
        context.begin_boundary()
        original = context.snapshots()
        self.assertIsNotNone(context._default)
        for create in (lambda: Arena(context), context.arena):
            with self.assertRaisesRegex(RuntimeError, 'pending ownership boundary'):
                create()
            self.assertEqual(context.snapshots(), original)
        receipt = context.native_replaced()
        self.assertFalse(context._boundaries)
        for create in (lambda: Arena(context), context.arena):
            with self.assertRaisesRegex(RuntimeError, 'pending ownership boundary'):
                create()
            self.assertEqual(context.snapshots(), original)
        context.recovered(receipt)
        next_arena = Arena(context)
        self.assertEqual(next_arena.state.phase, 0)
        self.assertIsNotNone(next_arena.retain(object(), 'after-recovery'))

    def test_active_borrow_keeps_native_registration_until_retry(self):
        stopped = []
        app = self.ownership_app(blender=BlenderConfig(),
            execution=ExecutionConfig(lambda app: SimpleNamespace(
                closed=False, fenced=False,
                shutdown=lambda: stopped.append(app.identity) or SimpleNamespace(clean=True))))
        app.execution.get_runtime()
        callbacks = []
        callback = lambda: None
        app.blender.registration.handler(callbacks, callback)
        arena = app.ownership.arena()
        ref = arena.retain(object(), 'native-reader')
        with arena.borrow(ref):
            with self.assertRaises(ExceptionGroup):
                app.close()
            self.assertFalse(app.closed)
            self.assertTrue(app.fenced)
            self.assertEqual(callbacks, [callback])
            self.assertTrue(app.blender.registration)
            self.assertEqual(stopped, [app.identity])
        app.close()
        self.assertTrue(app.closed)
        self.assertEqual(callbacks, [])
        self.assertFalse(app.blender.registration)

    def test_finalizer_uses_original_weak_arena_after_registry_replacement(self):
        app = self.ownership_app()
        original, peer = app.ownership.arena(), app.ownership.arena()
        ref = original.retain(object(), 'original')
        peer_value = object()
        peer_ref = peer.retain(peer_value, 'peer')
        with patch.object(app.ownership, '_arenas', {original.identity: peer}):
            del ref
            gc.collect()
        self.assertEqual(original.physical_counts(), (0, 0))
        self.assertIs(peer.resolve(peer_ref), peer_value)
        observed = weakref.ref(original)
        late = original.retain(object(), 'late')
        original.close()
        del original
        gc.collect()
        self.assertIsNone(observed())
        self.assertIsNone(app.ownership.resolve(late))

    def test_reloaded_module_keeps_original_contexts_and_new_holder_bindings(self):
        import importlib
        from color_tools.blender_runtime.ownership import OwnedField, bind_holder
        module = importlib.import_module('color_tools.blender_runtime.ownership.arena')
        first = self.ownership_app()
        value = object()
        retained = first.ownership.retain(value, 'original')
        original_arena = first.ownership.default
        importlib.reload(module)
        self.assertIs(first.ownership.resolve(retained), value)
        self.assertIs(first.ownership.default, original_arena)
        del retained
        gc.collect()
        self.assertEqual(original_arena.physical_counts(), (0, 0))

        # Package-level exports deliberately remain the original imported
        # classes. Descriptors created after reload must still bind to them.
        second = self.ownership_app()
        class Holder:
            value = OwnedField('after.reload')
        left, right = Holder(), Holder()
        with self.assertRaises(TypeError):
            bind_holder(left, None)
        with self.assertRaises(TypeError):
            left.value = object()
        bind_holder(left, first.ownership)
        bind_holder(right, second.ownership)
        left.value, right.value = object(), object()
        right_value = right.value
        first.close()
        self.assertIsNone(left.value)
        self.assertIs(right.value, right_value)

    def test_owned_field_remains_bound_to_original_context(self):
        from color_tools.blender_runtime.ownership import OwnedField, bind_holder
        class Holder:
            value = OwnedField('fixture.value')
        first, second = self.ownership_app(), self.ownership_app()
        holder = bind_holder(Holder(), first.ownership)
        native = object()
        holder.value = native
        self.assertIs(holder.value, native)
        with self.assertRaises(ForeignOwnerError):
            bind_holder(holder, second.ownership)
        first.close()
        self.assertIsNone(holder.value)
        with self.assertRaises(ClosedError):
            holder.value = object()
        self.assertIsNotNone(second.ownership.retain(object(), 'peer'))

    def test_owned_field_binding_does_not_invoke_holder_attribute_forwarding(self):
        from color_tools.blender_runtime.ownership import OwnedField, bind_holder
        class Holder:
            value = OwnedField('forwarding.value')

            def __getattr__(self, name):
                return getattr(self.value, name)

        app = self.ownership_app()
        holder = Holder()
        with self.assertRaises(TypeError):
            holder.value = object()
        bind_holder(holder, app.ownership)
        native = object()
        holder.value = native
        self.assertIs(holder.value, native)
        app.close()
        self.assertIsNone(holder.value)

    def test_owned_cells_detach_before_registration_teardown(self):
        app = self.ownership_app(blender=BlenderConfig())
        ref = app.ownership.retain(object(), 'registered')
        arena = app.ownership.default
        observed = []
        app.blender.registration.defer(lambda: observed.append(arena.physical_counts()))
        app.close()
        self.assertEqual(observed, [(0, 0)])
        self.assertIsNone(app.ownership.resolve(ref))


if __name__ == '__main__':
    unittest.main()
