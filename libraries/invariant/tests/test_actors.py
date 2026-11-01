import asyncio
import threading
import types
import unittest

from invariant import AdmissionError, ActorFailed, ActorSystem, ClosedError, Machine, Store


def fixture():
    module = types.ModuleType('actor_fixture')
    exec('''from dataclasses import dataclass, replace
from typing import Literal
@dataclass(frozen=True)
class State:
    count: int = 0
    busy: bool = False
    damaged: bool = False
    closing: bool = False
    closed: bool = False
@dataclass(frozen=True)
class Event:
    kind: Literal['add', 'start', 'success', 'failed', 'close', 'bad']
    amount: int = 1
@dataclass(frozen=True)
class Effects:
    launch: bool = False
def new() -> State:
    return State()
def count(state: State) -> int:
    return state.count
def step(state: State, event: Event) -> tuple[State, Effects]:
    if event.kind == 'bad':
        return State(True), Effects()
    if event.kind == 'close':
        return replace(state, closing=True, closed=not state.busy), Effects()
    if event.kind == 'success' or event.kind == 'failed':
        return replace(state, busy=False, damaged=event.kind == 'failed', closed=state.closing), Effects()
    if state.closing:
        return state, Effects()
    if event.kind == 'start':
        return replace(state, busy=True, damaged=True), Effects(launch=True)
    return replace(state, count=state.count + event.amount), Effects()
''', module.__dict__)
    return module, Machine(module, queries=('count',))


class ActorTests(unittest.IsolatedAsyncioTestCase):
    async def test_invalid_initializer_is_admission_failure_and_shutdown_still_drains(self):
        module, machine = fixture()
        system = ActorSystem()
        rejected = system.spawn('invalid-input', machine, arguments={'unknown': 1})
        with self.assertRaises(AdmissionError):
            await rejected.ready()
        peer = system.spawn('valid-input', machine)
        await peer.ready()
        await peer.dispatch(module.Event('add', 2))
        self.assertEqual(await peer.query('count'), 2)
        self.assertEqual(system.faults, [])
        await system.close()

    async def test_rejected_input_and_precondition_leave_actor_available(self):
        module, _ = fixture()
        class Contracts:
            def bind(self, module):
                return self
            def validate_before(self, name, arguments):
                if name == 'step' and arguments['event'].amount < 0:
                    raise ValueError('negative increment is not admitted')
            def validate_after(self, name, arguments, result):
                pass
            def validate_state(self, state):
                pass
        machine = Machine(module, contracts=Contracts(), queries=('count',))
        system = ActorSystem()
        actor = system.spawn('admission', machine)
        await actor.ready()
        for event in (module.Event('add', True), module.Event('add', -1)):
            with self.assertRaises(AdmissionError):
                await actor.dispatch(event)
            self.assertEqual(await actor.query('count'), 0)
        await actor.dispatch(module.Event('add', 3))
        self.assertEqual(await actor.query('count'), 3)
        self.assertEqual(system.faults, [])
        await system.close()

    async def test_each_actor_owns_a_task_and_preview_queries_do_not_commit(self):
        module, machine = fixture()
        system = ActorSystem()
        tasks = {}
        def routed(ref, effects, state):
            tasks[ref.name] = asyncio.current_task()
        left = system.spawn('left', machine, on_effects=routed)
        right = system.spawn('right', machine, on_effects=routed)
        await asyncio.gather(left.ready(), right.ready())
        candidate, _ = await left.preview(module.Event('add', 9))
        self.assertEqual(candidate.count, 9)
        self.assertEqual((await left.snapshot()).count, 0)
        await asyncio.gather(left.dispatch(module.Event('add', 2)), right.dispatch(module.Event('add', 4)))
        self.assertEqual(await left.query('count'), 2)
        self.assertEqual(await right.query('count'), 4)
        self.assertIsNot(tasks['left'], tasks['right'])
        self.assertIsNot(tasks['left'], asyncio.current_task())
        await system.close()
        self.assertTrue(left.closed)

    async def test_store_rejects_other_task_but_sync_store_remains_compatible(self):
        _, machine = fixture()
        owned = Store(machine, owner_task=asyncio.current_task())
        ordinary = Store(machine)
        async def peer():
            with self.assertRaisesRegex(RuntimeError, 'owning actor task'):
                _ = owned.state
            return ordinary.state
        self.assertEqual((await asyncio.create_task(peer())).count, 0)

    async def test_threadsafe_submission_snapshot_and_preview(self):
        module, machine = fixture()
        system = ActorSystem()
        actor = system.spawn('native-bridge', machine)
        await actor.ready()
        owner = threading.get_ident()
        def native_callback():
            self.assertNotEqual(threading.get_ident(), owner)
            actor.tell(module.Event('add', 3)).result(timeout=2)
            candidate, _ = actor.preview_threadsafe(module.Event('add', 4)).result(timeout=2)
            return candidate.count, actor.snapshot_threadsafe().result(timeout=2).count
        self.assertEqual(await asyncio.to_thread(native_callback), (7, 3))
        await system.close()
        with self.assertRaises(ClosedError):
            actor.tell(module.Event('add')).result(timeout=1)

    async def test_cancelled_acknowledgment_does_not_discard_submitted_event(self):
        module, machine = fixture()
        system = ActorSystem()
        actor = system.spawn('cancelled-acknowledgment', machine)
        acknowledgment = actor.tell(module.Event('add', 8))
        acknowledgment.cancel()
        self.assertEqual((await actor.snapshot()).count, 8)
        await system.close()

    async def test_rejected_effect_registration_closes_unstarted_coroutine(self):
        module, machine = fixture()
        system = ActorSystem()
        actor = system.spawn('closed', machine)
        await system.close()
        async def work():
            return 1
        pending = work()
        with self.assertRaises(ClosedError):
            system.run_effect(actor, pending, success=lambda value: module.Event('success'),
                              failure=lambda error: module.Event('failed'))
        self.assertIsNone(pending.cr_frame)

    async def test_individual_close_drains_effect_receipt_and_reclaims_actor(self):
        module, machine = fixture()
        system = ActorSystem()
        release = asyncio.Event()
        completed = []
        async def work():
            await release.wait()
        def route(ref, effects, state):
            if effects.launch:
                system.run_effect(ref, work(), success=lambda value: module.Event('success'),
                                  failure=lambda error: module.Event('failed'))
            if state.closed:
                completed.append(state)
        actor = system.spawn('retiring', machine, on_effects=route,
                             close_event=module.Event('close'), is_closed=lambda state: state.closed)
        peer = system.spawn('peer', machine)
        await actor.dispatch(module.Event('start'))
        retired = asyncio.create_task(actor.close())
        await peer.dispatch(module.Event('add'))
        self.assertFalse(retired.done())
        release.set()
        await asyncio.wait_for(retired, 2)
        self.assertEqual(len(completed), 1)
        self.assertNotIn('retiring', system._actors)
        self.assertFalse(peer.closed)
        with self.assertRaises(ClosedError):
            await actor.dispatch(module.Event('add'))
        await system.close()

    async def test_threadsafe_actor_close_and_system_close_can_overlap(self):
        _, machine = fixture()
        system = ActorSystem()
        actor = system.spawn('shared-close', machine)
        await asyncio.gather(asyncio.to_thread(lambda: actor.close_threadsafe().result(timeout=2)),
                             system.close())
        self.assertTrue(actor.closed)
        self.assertFalse(system._actors)

    async def test_system_close_joins_individual_retirement_after_cancelled_waiter(self):
        module, machine = fixture()
        system = ActorSystem()
        release = asyncio.Event()
        receipts = []
        async def work():
            await release.wait()
        def route(ref, effects, state):
            if effects.launch:
                system.run_effect(ref, work(), success=lambda value: module.Event('success'),
                                  failure=lambda error: module.Event('failed'))
            if state.closed:
                receipts.append(ref.name)
        actors = [system.spawn(name, machine, on_effects=route,
                               close_event=module.Event('close'), is_closed=lambda state: state.closed)
                  for name in ('first', 'second')]
        await asyncio.gather(*(actor.dispatch(module.Event('start')) for actor in actors))
        abandoned = asyncio.create_task(actors[0].close())
        await asyncio.sleep(0)
        abandoned.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await abandoned
        acknowledgment = actors[1].close_threadsafe()
        shutdown = asyncio.create_task(system.close())
        await asyncio.sleep(0)
        self.assertFalse(shutdown.done())
        self.assertFalse(acknowledgment.done())
        release.set()
        await asyncio.wait_for(shutdown, 2)
        self.assertTrue(acknowledgment.done())
        self.assertEqual(sorted(receipts), ['first', 'second'])
        self.assertTrue(all(actor.closed for actor in actors))
        self.assertFalse(system._actors)
        self.assertFalse(system._retirements)

    async def test_peer_receipts_and_timers_do_not_require_user_messages(self):
        module, machine = fixture()
        system = ActorSystem()
        delivered = asyncio.Event()
        right = system.spawn('receiver', machine, on_effects=lambda *_: delivered.set())
        left = system.spawn('sender', machine,
                            on_effects=lambda *_: right.tell(module.Event('add', 6)))
        system.schedule(left, module.Event('add'), 0.001)
        await asyncio.wait_for(delivered.wait(), 2)
        self.assertEqual((await right.snapshot()).count, 6)
        await system.close()

    async def test_mailbox_flood_yields_to_peers_and_never_drops_events(self):
        module, machine = fixture()
        system = ActorSystem()
        seen = []
        left = system.spawn('flood', machine, on_effects=lambda ref, effects, state: seen.append(ref.name))
        right = system.spawn('peer', machine, on_effects=lambda ref, effects, state: seen.append(ref.name))
        pending = [left.tell(module.Event('add')) for _ in range(80)]
        await right.dispatch(module.Event('add'))
        self.assertLess(seen.index('peer'), 80)
        await asyncio.gather(*(asyncio.wrap_future(item) for item in pending))
        self.assertEqual((await left.snapshot()).count, 80)
        await system.close()

    async def test_routing_failure_becomes_explicit_event_after_conservative_commit(self):
        module, machine = fixture()
        system = ActorSystem()
        def route(ref, effects, state):
            if effects.launch:
                self.assertTrue(state.damaged)
                raise OSError('executor admission failed')
        actor = system.spawn('failure', machine, on_effects=route,
                             on_failure=lambda ref, event, effects, error: module.Event('failed'))
        with self.assertRaisesRegex(OSError, 'admission failed'):
            await actor.dispatch(module.Event('start'))
        state = await actor.snapshot()
        self.assertTrue(state.damaged)
        self.assertFalse(state.busy)
        self.assertFalse(system.faults)
        await system.close()

    async def test_worker_failure_receipt_and_shutdown_wait_for_registered_work(self):
        module, machine = fixture()
        system = ActorSystem()
        release = asyncio.Event()
        async def work():
            await release.wait()
            raise OSError('partially written pixels')
        def route(ref, effects, state):
            if effects.launch:
                system.run_effect(ref, work(), success=lambda value: module.Event('success'),
                                  failure=lambda error: module.Event('failed'))
        actor = system.spawn('writer', machine, on_effects=route,
                             close_event=module.Event('close'), is_closed=lambda state: state.closed)
        await actor.dispatch(module.Event('start'))
        closing = asyncio.create_task(system.close())
        await asyncio.sleep(0.01)
        self.assertFalse(closing.done())
        self.assertTrue((await actor.snapshot()).busy)
        release.set()
        await asyncio.wait_for(closing, 2)
        self.assertTrue(actor.closed)
        self.assertFalse(system.faults)

    async def test_success_does_not_stop_processing_other_mailbox_messages(self):
        module, machine = fixture()
        system = ActorSystem()
        release = asyncio.Event()
        async def work():
            await release.wait()
            return 7
        def route(ref, effects, state):
            if effects.launch:
                system.run_effect(ref, work(), success=lambda value: module.Event('success'),
                                  failure=lambda error: module.Event('failed'))
        actor = system.spawn('writer', machine, on_effects=route)
        await actor.dispatch(module.Event('start'))
        await asyncio.wait_for(actor.dispatch(module.Event('add', 2)), 1)
        self.assertEqual((await actor.snapshot()).count, 2)
        release.set()
        await system.close()
        self.assertFalse(system.faults)

    async def test_invalid_transition_fences_actor_and_supervises_without_affecting_peer(self):
        module, machine = fixture()
        observed = []
        system = ActorSystem(on_fault=observed.append)
        actor = system.spawn('invalid', machine)
        peer = system.spawn('valid', machine)
        with self.assertRaises(ValueError):
            await actor.dispatch(module.Event('bad'))
        with self.assertRaises(ActorFailed):
            await actor.snapshot()
        await peer.dispatch(module.Event('add', 5))
        self.assertEqual((await peer.snapshot()).count, 5)
        self.assertEqual([fault.actor.name for fault in observed], ['invalid'])
        await system.close()

    async def test_failure_mapping_fault_fences_actor_instead_of_recursive_recovery(self):
        module, machine = fixture()
        observed = []
        system = ActorSystem(on_fault=observed.append)
        def route(*arguments):
            raise OSError('routing unavailable')
        actor = system.spawn('broken-recovery', machine, on_effects=route,
                             on_failure=lambda *arguments: module.Event('failed'))
        with self.assertRaises(OSError):
            await actor.dispatch(module.Event('start'))
        await asyncio.sleep(0.01)
        self.assertEqual(len(observed), 1)
        await system.close()


if __name__ == '__main__':
    unittest.main()
