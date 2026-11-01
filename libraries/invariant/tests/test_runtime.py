import asyncio
import threading
import time
import types
import unittest

from invariant import App, BackpressureError, ClosedError, ContractError, Machine, Store
from invariant import lifecycle, _lifecycle_contracts


class RuntimeTests(unittest.TestCase):
    def test_exact_tokens_and_unbounded_tuple_domains(self):
        from invariant.machine import validate
        class Number(int):
            pass
        class Text(str):
            pass
        values = tuple([1, 'same', 1] * 257)
        validate(values, tuple[int | str, ...])
        validate((), tuple[int | str, ...])
        validate((), tuple[()])
        for value in (True, Number(1), Text('same'), None):
            with self.subTest(value=value), self.assertRaises(ContractError):
                validate(value, int | str)
            with self.subTest(sequence=value), self.assertRaises(ContractError):
                validate((1, value), tuple[int | str, ...])

    def store(self):
        return Store(Machine(lifecycle, contracts=_lifecycle_contracts))

    def test_cancellation_and_terminal_keep_occupancy_until_quiescence(self):
        store = self.store()
        store.dispatch(lifecycle.Event('start', 1))
        store.dispatch(lifecycle.Event('cancel', 1))
        self.assertEqual(store.state.leases, 1)
        self.assertFalse(store.dispatch(lifecycle.Event('quiescent', 1)).reclaim)
        store.dispatch(lifecycle.Event('terminal', 1))
        self.assertEqual(store.state.leases, 1)
        self.assertTrue(store.dispatch(lifecycle.Event('quiescent', 1)).reclaim)
        self.assertEqual(store.state.leases, 0)
        self.assertFalse(store.dispatch(lifecycle.Event('quiescent', 1)).reclaim)

    def test_generation_and_close_fence_late_receipts(self):
        store = self.store()
        store.dispatch(lifecycle.Event('start', 1))
        store.dispatch(lifecycle.Event('died', 1))
        store.dispatch(lifecycle.Event('start', 2))
        before = store.state
        self.assertFalse(store.dispatch(lifecycle.Event('died', 1)).accepted)
        self.assertEqual(store.state, before)
        store.dispatch(lifecycle.Event('close', 2))
        self.assertFalse(store.dispatch(lifecycle.Event('start', 2)).accepted)
        self.assertEqual(store.state.leases, 1)
        store.dispatch(lifecycle.Event('died', 2))
        self.assertTrue(store.state.closed)

    def test_preview_and_exact_types(self):
        store = self.store()
        before = store.state
        candidate, effects = store.preview(lifecycle.Event('start', 1))
        self.assertTrue(effects.start)
        self.assertTrue(candidate.busy)
        self.assertEqual(store.state, before)
        with self.assertRaises(ContractError):
            store.dispatch(lifecycle.Event('start', True))
        self.assertEqual(store.state, before)

    def test_wrong_thread_cannot_read_or_dispatch_store(self):
        store = self.store()
        failures = []
        def access():
            for operation in (lambda: store.state, lambda: store.dispatch(lifecycle.Event('start', 1))):
                try:
                    operation()
                except RuntimeError:
                    failures.append(True)
        thread = threading.Thread(target=access)
        thread.start()
        thread.join()
        self.assertEqual(len(failures), 2)
        self.assertFalse(store.state.busy)

    def test_invalid_postcondition_cannot_commit(self):
        module = types.ModuleType('bad_transition')
        exec('''from dataclasses import dataclass
@dataclass(frozen=True)
class State:
    value: int
@dataclass(frozen=True)
class Event:
    value: int
@dataclass(frozen=True)
class Effects:
    changed: bool
def new() -> State:
    return State(0)
def step(state: State, event: Event) -> tuple[State, Effects]:
    return State(True), Effects(True)
''', module.__dict__)
        store = Store(Machine(module))
        with self.assertRaises(ContractError):
            store.dispatch(module.Event(1))
        self.assertEqual(store.state.value, 0)

    def test_app_admission_polling_and_shutdown_do_not_run_service_on_caller(self):
        started, release = threading.Event(), threading.Event()
        threads = []
        seen = []
        class Service:
            def __init__(self, emit):
                self.emit = emit
            async def start(self):
                threads.append(threading.get_ident())
                started.set()
            async def handle(self, command):
                seen.append(command)
                while not release.is_set():
                    await asyncio.sleep(0.001)
            async def tick(self):
                pass
            async def close(self):
                self.emit({'kind': 'cleaned'})
        app = App(Service, capacity=1)
        try:
            self.assertTrue(started.wait(2))
            with self.assertRaises(TypeError):
                app.post(None)
            command = {'kind': 'held', 'color': [1, 2, 3]}
            app.post(command)
            command['color'][0] = 99
            with self.assertRaises(BackpressureError):
                app.post({'kind': 'overflow'})
            self.assertEqual(app.poll(), ())
            self.assertNotEqual(threads[0], threading.get_ident())
            release.set()
            deadline = time.monotonic() + 2
            events = []
            while time.monotonic() < deadline and not any(e['kind'] == 'ack' for e in events):
                events.extend(app.poll())
                time.sleep(0.005)
            self.assertTrue(any(e['kind'] == 'ack' for e in events))
            self.assertEqual(seen[0]['color'], [1, 2, 3])
            app._emit({'kind': 'snapshot', 'document': 1, 'phase': 'complete'})
            app._emit({'kind': 'document_closed', 'document': 1})
            closed_events = app.poll()
            self.assertTrue(any(e['kind'] == 'document_closed' for e in closed_events))
            self.assertFalse(any(e['kind'] == 'snapshot' for e in closed_events))
            notification = {'kind': 'snapshot', 'document': 2, 'options': {'color': [1, 2, 3]}}
            app._emit(notification)
            received = next(event for event in app.poll() if event['kind'] == 'snapshot')
            received['options']['color'][0] = 99
            self.assertEqual(notification['options']['color'], [1, 2, 3])
            notification['options']['color'][1] = 88
            self.assertEqual(received['options']['color'], [99, 2, 3])
            app.post({'kind': 'another'})
        finally:
            release.set()
            self.assertTrue(app.close_async().wait(2))
        with self.assertRaises(ClosedError):
            app.post({'kind': 'late'})
        self.assertTrue(any(e['kind'] == 'cleaned' for e in app.poll()))


if __name__ == '__main__':
    unittest.main()
