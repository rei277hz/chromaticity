"""Runtime type/domain checks independent of source files and build evidence."""
from dataclasses import FrozenInstanceError, dataclass
import sys
from types import ModuleType
import unittest

from color_tools.blender_runtime import App, DomainError, Machine
from tests.blender_runtime.policy_fixture import bind_policy


SOURCE = '''from dataclasses import dataclass
from typing import Literal
@dataclass(frozen=True)
class Payload:
    enabled: bool
    identity: int | str
@dataclass(frozen=True)
class State:
    count: int
@dataclass(frozen=True)
class Event:
    kind: Literal['add', 'noop']
    value: int
    token: int | str
    pair: tuple[bool, int]
    values: tuple[int | str, ...]
    payload: Payload
@dataclass(frozen=True)
class Effects:
    accepted: bool
    values: tuple[int | str, ...]
    empty: tuple[()]
def new(count: int = 0) -> State:
    return State(count)
def zero() -> State:
    return State(0)
def state_valid(state: State) -> bool:
    return state.count >= 0
def event_valid(state: State, event: Event) -> bool:
    return event.value >= 0
def step(state: State, event: Event) -> tuple[State, Effects]:
    if fault == 'state':
        return State(-1), Effects(True, (), ())
    if fault == 'effect':
        return State(state.count + 1), Effects(1, (), ())
    if fault == 'shape':
        return [state, Effects(True, (), ())]
    return State(state.count + event.value), Effects(True, event.values, ())
def read(state: State) -> int:
    return state.count
def count(values: tuple[int | str, ...], selected: int | str) -> int:
    return sum(value == selected for value in values)
def bad_query() -> bool:
    return 1
fault = ''
'''


class MachineTests(unittest.TestCase):
    def module(self, source=SOURCE):
        module = ModuleType('_typed_fixture_' + str(id(self)))
        sys.modules[module.__name__] = module
        self.addCleanup(sys.modules.pop, module.__name__, None)
        exec(compile(source, '<typed fixture>', 'exec', dont_inherit=True), module.__dict__)
        return module

    def machine(self, module=None, **bindings):
        module = self.module() if module is None else module
        return bind_policy(module, initializers=('new', 'zero'),
                           queries=('read', 'count', 'bad_query'), **bindings)

    def store(self, machine=None, **initial):
        machine = self.machine() if machine is None else machine
        app = App(package='typed_fixture', storage_name='typed_fixture')
        self.addCleanup(app.close)
        return app.store(machine=machine, initial=dict(count=0, **initial))

    def event(self, machine, **changes):
        values = dict(kind='add', value=1, token=1, pair=(True, 2),
                      values=(1, 'a', 1), payload=machine.module.Payload(True, 'owner'))
        values.update(changes)
        return machine.event_type(**values)

    def test_descriptor_needs_no_files_and_captures_immutable_function_bindings(self):
        module = self.module()
        self.assertFalse(hasattr(module, '__file__'))
        machine = self.machine(module)
        store = self.store(machine)
        original_step = machine.step
        module.step = lambda state, event: (None, None)
        module.new = lambda **values: None
        self.assertIs(machine.step, original_step)
        self.assertEqual(store.dispatch(self.event(machine)).values, (1, 'a', 1))
        self.assertEqual(store.state.count, 1)
        with self.assertRaises(FrozenInstanceError):
            machine.event_type = object
        with self.assertRaises(TypeError):
            machine.queries['read'] = None
        with self.assertRaises(TypeError):
            machine._functions['read'] = None

    def test_exact_primitives_tokens_enums_records_and_tuple_shapes(self):
        machine = self.machine()
        store = self.store(machine)
        class Integer(int):
            pass
        class Text(str):
            pass
        @dataclass(frozen=True)
        class OtherPayload:
            enabled: bool
            identity: int | str
        invalid = (
            dict(value=True), dict(value=Integer(2)), dict(token=True), dict(token=None),
            dict(token=Text('owner')), dict(kind='unknown'), dict(kind=Text('add')),
            dict(pair=(1, 2)), dict(pair=(True,)), dict(pair=(True, 2, 3)), dict(pair=[True, 2]),
            dict(values=[1, 2]), dict(values=(1, False)), dict(values=(1, None)),
            dict(payload=OtherPayload(True, 1)), dict(payload=machine.module.Payload(1, 1)),
        )
        original = store.state
        for changes in invalid:
            with self.subTest(changes=changes), self.assertRaises(DomainError):
                store.dispatch(self.event(machine, **changes))
            self.assertIs(store.state, original)
        self.assertEqual(store.dispatch(self.event(machine, token='owner', values=())).values, ())
        self.assertEqual(store.dispatch(self.event(machine)).values, (1, 'a', 1))
        self.assertEqual(store.query('count', values=(1, 'a', 1), selected=1), 2)

    def test_initializers_require_complete_names_and_explicit_default_selection(self):
        machine = self.machine()
        app = App(package='typed_fixture', storage_name='typed_fixture')
        self.addCleanup(app.close)
        for initial in ({}, {'count': True}, {'count': 0, 'extra': 1}):
            with self.subTest(initial=initial), self.assertRaises(DomainError):
                app.store(machine=machine, initial=initial)
            self.assertEqual(len(app._stores), 0)
        # The initializer ran, then returned a state outside its contract.
        # This is a model fault, distinct from rejected input admission.
        from color_tools.invariant import ActorFailed
        failed = App(package='typed_fixture', storage_name='typed_fixture')
        self.addCleanup(failed.close)
        with self.assertRaises(ActorFailed):
            failed.store(machine=machine, initial={'count': -1})
        self.assertTrue(failed.fenced)
        self.assertEqual(len(failed._stores), 0)
        with self.assertRaises(DomainError):
            app.store(machine=machine, initializer='unknown')
        self.assertEqual(app.store(machine=machine, initializer='zero').state.count, 0)
        other = self.machine(machine.module, default_initializer='zero')
        self.assertEqual(app.store(machine=other).state.count, 0)
        with self.assertRaises(TypeError):
            self.machine(machine.module, default_initializer='read')

    def test_domains_and_bad_results_cannot_partially_commit(self):
        machine = self.machine()
        store = self.store(machine)
        original = store.state
        with self.assertRaises(DomainError):
            store.dispatch(self.event(machine, value=-1))
        self.assertIs(store.state, original)
        for failure in ('state', 'effect', 'shape'):
            machine.module.fault = failure
            from color_tools.invariant import Store as ActorStore
            actual = ActorStore(machine, arguments=dict(count=0))
            with self.subTest(failure=failure), self.assertRaises(DomainError):
                actual.dispatch(self.event(machine))
            self.assertEqual(actual.state.count, 0)
        machine.module.fault = ''
        with self.assertRaises(DomainError):
            actual.query('bad_query')
        with self.assertRaises(DomainError):
            store.query('read', state=original)
        with self.assertRaises(DomainError):
            store.query('read', extra=1)
        with self.assertRaises(DomainError):
            store.query('not_bound')
        self.assertEqual(store.query('read'), 0)

    def test_noncommitting_actor_faults_fence_only_their_host(self):
        for operation in ('preview', 'query'):
            with self.subTest(operation=operation):
                machine = self.machine()
                app = App(package='typed_fixture', storage_name='typed_fixture')
                peer = App(package='typed_fixture', storage_name='typed_fixture')
                self.addCleanup(app.close)
                self.addCleanup(peer.close)
                store = app.store(machine=machine, initial={'count': 0})
                with self.assertRaises(DomainError):
                    if operation == 'preview':
                        machine.module.fault = 'state'
                        store.preview(self.event(machine))
                    else:
                        store.query('bad_query')
                self.assertTrue(app.fenced)
                self.assertFalse(peer.fenced)

    def test_string_missing_and_mutable_annotations_are_rejected_without_evaluation(self):
        mutations = (
            ("count: int", "count: 'int'"),
            ("token: int | str", "token: list[int]"),
            ("pair: tuple[bool, int]", "pair: tuple"),
            ("values: tuple[int | str, ...]", "values: list[int]"),
            ("@dataclass(frozen=True)", "@dataclass"),
            ("def new(count: int = 0) -> State:", "def new(count = 0) -> State:"),
            ("def step(state: State, event: Event) -> tuple[State, Effects]:", "def step(state: State, event: Event) -> tuple[Event, Effects]:"),
        )
        for old, new in mutations:
            with self.subTest(annotation=new), self.assertRaises(TypeError):
                self.machine(self.module(SOURCE.replace(old, new)))
        module = self.module()
        module.new.__annotations__['count'] = "__import__('os').system('false')"
        with self.assertRaises(TypeError):
            self.machine(module)

    def test_non_module_functions_and_ambiguous_bindings_are_rejected(self):
        module = self.module()
        with self.assertRaises(TypeError):
            Machine(module, initializers=[module.new])
        with self.assertRaises(TypeError):
            Machine(module, initializers=(module.new, module.new))
        with self.assertRaises(TypeError):
            Machine(module, initializers=())
        with self.assertRaises(TypeError):
            Machine(module, initializers=(lambda count: module.State(count),))
        with self.assertRaises(TypeError):
            Machine(object(), initializers=())


if __name__ == '__main__':
    unittest.main()
