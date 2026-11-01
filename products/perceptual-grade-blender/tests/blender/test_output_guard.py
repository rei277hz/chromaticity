"""The host reader boundary cannot be bypassed by synchronous or forced output."""
from tests.support.session import component as _component, SessionTest, patch
import threading
from types import SimpleNamespace
from unittest.mock import Mock

import bpy

output = _component('graph.output'); guard = _component('graph.output_guard')

from color_tools.perceptual_grade_core.graph import scheduler_policy as policy
from tests.support.blender import BlenderTest


class OutputGuardTests(BlenderTest):
    def native_jobs(self, predicate, *, interface_locked=False, modal_readers=()):
        return patch.object(guard, 'bpy', SimpleNamespace(
            app=SimpleNamespace(is_job_running=predicate),
            data=SimpleNamespace(window_managers=[SimpleNamespace(
                is_interface_locked=interface_locked,
                windows=[SimpleNamespace(modal_operators=[
                    SimpleNamespace(bl_idname=name) for name in modal_readers])])])))

    def tearDown(self):
        output.clear()
        super().tearDown()

    def test_every_public_native_reader_job_blocks_publication(self):
        for job in guard.JOBS:
            with self.subTest(job=job), self.native_jobs(lambda value: value == job):
                self.assertIn(job, guard.reason())
                with self.assertRaises(guard.PublicationDeferred):
                    with guard.publication():
                        self.fail('Native reader overlapped publication')
        self.assertTrue(guard.available())

    def test_locked_interface_blocks_even_without_public_job_kind(self):
        with self.native_jobs(lambda _kind: False, interface_locked=True):
            self.assertIn('interface lock', guard.reason())
            with self.assertRaises(guard.PublicationDeferred):
                with guard.publication():
                    self.fail('Publication entered during an internal native job')
        self.assertTrue(guard.available())

    def test_internal_reader_jobs_are_observed_through_their_modal_owner(self):
        for name in guard.MODAL_READERS:
            with self.subTest(name=name), self.native_jobs(lambda _kind: False, modal_readers=(name,)):
                self.assertIn(name, guard.reason())
                with self.assertRaises(guard.PublicationDeferred):
                    with guard.publication():
                        self.fail('Publication entered during an internal native reader job')
        self.assertTrue(guard.available())

    def test_other_thread_never_queries_native_jobs(self):
        results = []
        with self.native_jobs(Mock(side_effect=AssertionError('bpy accessed off main thread'))):
            check = guard.reason  # Capture this exact Session callback on the main thread.
            thread = threading.Thread(target=lambda: results.append(check()))
            thread.start()
            thread.join()
        self.assertEqual(len(results), 1)
        self.assertIn('main thread', results[0])

    def test_nested_publication_and_native_invocation_are_rejected(self):
        with guard.publication():
            self.assertTrue(guard.publishing())
            with self.assertRaises(guard.PublicationDeferred):
                with guard.publication():
                    self.fail('Nested publication entered')
            with self.assertRaises(guard.PublicationDeferred):
                with guard.native_operation():
                    self.fail('Native evaluation entered during transfer')
        self.assertFalse(guard.publishing())
        self.assertTrue(guard.available())

    def test_callback_and_synchronous_operation_guards_release_on_failure(self):
        for boundary in (guard.native_callback, guard.native_operation, guard.publication):
            with self.subTest(boundary=boundary.__name__):
                with self.assertRaisesRegex(ValueError, 'injected'):
                    with boundary():
                        self.assertFalse(guard.available())
                        raise ValueError('injected')
                self.assertTrue(guard.available())

    def test_synchronous_evaluation_requires_paired_completion(self):
        guard.evaluation_started('composite', 7)
        try:
            self.assertFalse(guard.available())
            guard.evaluation_finished('composite', 8)
            self.assertFalse(guard.available())
        finally:
            guard.evaluation_finished('composite', 7)
        self.assertFalse(guard.available(), 'Unacknowledged completion unlocked admission')
        guard.reconcile()
        self.assertTrue(guard.available())

    def test_each_overlapping_start_retains_its_own_machine_lease(self):
        guard.evaluation_started('composite', 7)
        guard.evaluation_started('composite', 7)
        guard.evaluation_started('render', 8)
        guard.reconcile()
        self.assertEqual(len(guard.observation().tokens), 3)
        guard.evaluation_finished('composite', 7)
        guard.reconcile()
        self.assertEqual(len(guard.observation().tokens), 2)
        self.assertFalse(guard.available())
        guard.evaluation_finished('render', 8)
        guard.reconcile()
        self.assertEqual(len(guard.observation().tokens), 1)
        self.assertFalse(guard.available())
        guard.evaluation_finished('composite', 7)
        guard.reconcile()
        self.assertTrue(guard.available())
        guard.evaluation_finished('composite', 7)
        guard.reconcile()
        self.assertTrue(guard.available(), 'Unmatched terminal should preserve readiness')

    def test_native_callbacks_only_enqueue_and_passive_reads_never_wait_on_actors(self):
        before = guard.observation()
        with patch.object(self.session.app.actors, 'call', side_effect=AssertionError('Callback waited on actor')):
            with guard.native_callback():
                guard.evaluation_started('composite', 7)
                guard.evaluation_finished('composite', 7)
                self.assertFalse(guard.available())
                self.assertFalse(guard.reconcile())
                with self.assertRaises(guard.PublicationDeferred):
                    guard.require_available()
            self.assertEqual(guard.observation(), before)
            self.assertFalse(guard.available(), 'Pending start/finish pair bypassed acknowledgement')
        guard.reconcile()
        self.assertEqual(guard.observation().revision, before.revision + 2)
        self.assertTrue(guard.available())

    def test_explicit_publication_drains_completed_headless_observations(self):
        before = guard.observation()
        guard.evaluation_started('render', 7)
        guard.evaluation_finished('render', 7)
        # Passive reads cannot commit actors, even when both callbacks arrived.
        self.assertFalse(guard.available())
        self.assertEqual(guard.observation(), before)
        with guard.publication():
            self.assertTrue(guard.publishing())
            self.assertEqual(guard.observation().tokens, ())
            self.assertEqual(guard.observation().revision, before.revision + 2)
        self.assertTrue(guard.available())

    def test_background_callback_latches_without_native_or_actor_queries(self):
        guard.observation()
        started, finished = guard.evaluation_started, guard.evaluation_finished
        with self.native_jobs(Mock(side_effect=AssertionError('Callback queried native jobs'))), \
                patch.object(self.session.app.actors, 'call', side_effect=AssertionError('Callback waited on actor')):
            thread = threading.Thread(target=lambda: (started('render', 7), finished('render', 7)))
            thread.start();thread.join()
        self.assertFalse(guard.available())
        guard.reconcile()
        self.assertTrue(guard.available())

    def test_terminal_receipt_does_not_override_a_running_job(self):
        guard.evaluation_started('composite', 7)
        guard.reconcile()
        guard.evaluation_finished('composite', 7)
        with self.native_jobs(lambda kind: kind == 'COMPOSITE'):
            guard.reconcile()
            self.assertEqual(guard.observation().tokens, ())
            self.assertFalse(guard.available())
            self.assertIn('COMPOSITE', guard.reason())
        guard.reconcile()
        self.assertTrue(guard.available())

    def test_reader_arriving_during_physical_observation_revokes_readiness(self):
        started = []
        def observe(_kind):
            if not started:
                started.append(guard.evaluation_started('composite', 7))
            return False
        try:
            with self.native_jobs(observe):
                self.assertFalse(guard.available())
                with self.assertRaises(guard.PublicationDeferred):
                    with guard.publication():
                        self.fail('New ingress was ignored during admission')
        finally:
            guard.evaluation_finished('composite', 7)
            guard.reconcile()
        self.assertTrue(guard.available())

    def test_only_verified_replacement_releases_abandoned_native_leases(self):
        guard.evaluation_started('composite', 7)
        guard.reconcile()
        before = guard.observation()
        with self.native_jobs(lambda kind: kind == 'COMPOSITE'):
            with self.assertRaises(guard.PublicationDeferred):
                guard.reset_after_native_replacement()
        self.assertEqual(guard.observation(), before)
        guard.reset_after_native_replacement()
        self.assertEqual(guard.observation().generation, before.generation + 1)
        self.assertTrue(guard.available())
        # A reused scene identity must route to its fresh, current generation.
        guard.evaluation_started('composite', 7)
        guard.reconcile()
        self.assertFalse(guard.available())
        guard.evaluation_finished('composite', 7)
        guard.reconcile()
        self.assertTrue(guard.available())

    def test_fenced_cleanup_can_drain_terminal_observations(self):
        guard.evaluation_started('render', 7)
        guard.reconcile()
        guard.evaluation_finished('render', 7)
        with patch.object(self.session.app, 'fenced', True):
            self.assertFalse(guard.reconcile())
            self.assertFalse(guard.available(cleanup=True))
            self.assertTrue(guard.reconcile(cleanup=True))
            self.assertTrue(guard.available(cleanup=True))
            self.assertFalse(guard.available())

    def _pending_observation_reconciles_once(self, stage):
        """Hold an actual actor future through the host's real timeout path."""
        import asyncio

        before = guard.observation()
        host = self.session.app.actors
        original_call = host.call
        release = asyncio.Event()
        delayed = []
        calls = []

        def call(coroutine, operation):
            calls.append(operation.split(':', 1)[0])
            if not delayed and operation.startswith(stage + ':'):
                async def held():
                    await release.wait()
                    return await coroutine
                future = host.submit(held())
                delayed.append(future)
                # The future cannot complete before release. ActorHost.wait
                # retains this exact future and produces PendingTransitionError.
                with patch.object(host, 'timeout', 0):
                    return host.wait(future, operation)
            return original_call(coroutine, operation)

        try:
            with self.native_jobs(lambda _kind: False), \
                    patch.object(host, 'call', side_effect=call), \
                    patch.object(self.session.app, '_fence_admission') as fence:
                guard.evaluation_started('render', 7)
                self.assertFalse(guard.reconcile())
                fence.assert_called_once_with()
                self.assertEqual(len(delayed), 1)
                self.assertFalse(delayed[0].done())
                self.assertEqual(len(host.pending), 1)
                pending_token = next(iter(host.pending))
                self.assertIs(host.pending[pending_token][1], delayed[0])
                self.assertEqual(guard.observation(), before)

                # Model the host fence without retiring the test's shared
                # execution service. Only cleanup may reconcile its exact debt.
                with patch.object(self.session.app, 'fenced', True):
                    guard.evaluation_finished('render', 7)
                    second = guard.evaluation_started('composite', 8)
                    attempts = tuple(calls)
                    self.assertFalse(guard.reconcile())
                    self.assertFalse(guard.reconcile(cleanup=True))
                    self.assertEqual(tuple(calls), attempts, 'Pending work was resubmitted')
                    self.assertFalse(guard.available(cleanup=True))

                    host.loop.call_soon_threadsafe(release.set)
                    delayed[0].result(timeout=5)
                    self.assertFalse(guard.reconcile(cleanup=True))
                    self.assertEqual(host.pending, {})
                    self.assertIn(pending_token, host.reconciled)
                    self.assertEqual(guard.observation().revision, before.revision + 3)
                    self.assertEqual(guard.observation().tokens, (second[1],))
                    self.assertEqual(calls.count('dispatch'), 3)
                    self.assertEqual(calls.count('snapshot'), 3)

                    # An additional pump must neither replay the consumed
                    # receipt nor pop the next observation a second time.
                    attempts = tuple(calls)
                    self.assertFalse(guard.reconcile(cleanup=True))
                    self.assertEqual(tuple(calls), attempts)
                    guard.evaluation_finished('composite', 8)
                    self.assertTrue(guard.reconcile(cleanup=True))
                    self.assertEqual(guard.observation().revision, before.revision + 4)
                    self.assertEqual(guard.observation().tokens, ())
                    self.assertEqual(calls.count('dispatch'), 4)
                    self.assertEqual(calls.count('snapshot'), 4)
                    self.assertTrue(guard.available(cleanup=True))
                    self.assertFalse(guard.available())
            self.assertTrue(guard.available())
        finally:
            host.loop.call_soon_threadsafe(release.set)
            if delayed:
                delayed[0].result(timeout=5)
            guard.evaluation_finished('render', 7)
            guard.evaluation_finished('composite', 8)
            guard.reconcile(cleanup=True)

    def test_pending_dispatch_retains_original_future_and_ingress_order(self):
        self._pending_observation_reconciles_once('dispatch')

    def test_pending_snapshot_does_not_replay_committed_observation(self):
        self._pending_observation_reconciles_once('snapshot')

    def test_whole_render_remains_blocked_across_every_frame(self):
        nodes = _component('graph.nodes')
        scene = bpy.context.scene
        nodes.render_init_handler(scene)
        try:
            for _ in range(3):
                nodes.render_end_handler(scene)
                guard.reconcile()
                self.assertEqual(len(guard.observation().tokens), 1)
                self.assertFalse(guard.available())
        finally:
            nodes.render_complete_handler(scene)
        self.assertFalse(guard.available())
        guard.reconcile()
        self.assertTrue(guard.available())

    def test_busy_prepare_keeps_operation_retryable_without_invocation(self):
        operation = output.Operation('render', bpy.context.scene)
        try:
            with self.native_jobs(lambda kind: kind == 'COMPOSITE'), \
                    patch.object(output, 'prepare_render', side_effect=AssertionError('Premature preparation')):
                with self.assertRaises(guard.PublicationDeferred):
                    operation.prepare()
            self.assertEqual(operation.state.phase, policy.EXACT_PREPARING)
            self.assertIsNone(operation.error)
            self.assertEqual(operation.native_calls, 0)
            with patch.object(output, 'prepare_render', return_value=()), \
                    patch.object(output, 'snapshot', return_value=()):
                operation.prepare()
                def native():
                    self.assertFalse(guard.available())
                    with self.assertRaises(guard.PublicationDeferred):
                        with guard.publication():
                            self.fail('Synchronous native callback published')
                    return {'FINISHED'}
                operation.invoke(native)
            self.assertTrue(operation.settle())
        finally:
            operation.close()

    def test_native_handlers_never_force_payload_transfer(self):
        nodes = _component('graph.nodes')
        with patch.object(nodes, 'refresh_all', side_effect=AssertionError('Callback refreshed native graph')), \
                patch.object(nodes.cube_nodes, 'ensure', side_effect=AssertionError('Callback installed pixels')), \
                patch.object(output, 'snapshot', return_value=()):
            nodes.sync_handler()
            try:
                nodes.render_init_handler(bpy.context.scene)
                nodes.render_handler(bpy.context.scene)
                self.assertFalse(guard.available())
            finally:
                nodes.render_end_handler(bpy.context.scene)
                self.assertFalse(guard.available(), 'Frame post retired the whole render')
                nodes.render_complete_handler(bpy.context.scene)
        guard.reconcile()
        self.assertTrue(guard.available())

