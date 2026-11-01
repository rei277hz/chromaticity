import ast
import copy
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import z3

from invariant.verification.checker import Checker, verify, verify_receipt
from invariant.verification.model import Source, VerificationError
from invariant.verification.symbolic import Interpreter, integer, boolean


SOURCE = '''from dataclasses import dataclass, replace
from typing import Literal

@dataclass(frozen=True)
class State:
    retries: int
    active: bool

@dataclass(frozen=True)
class Event:
    kind: Literal["start", "crash", "done"]

@dataclass(frozen=True)
class Effects:
    launch: bool = False

def initial() -> State:
    return State(0, False)

def remaining(n: int) -> int:
    return 1 - n

def step(state: State, event: Event) -> tuple[State, Effects]:
    if event.kind == "start" and not state.active:
        return replace(state, active=True), Effects(True)
    if event.kind == "crash" and state.active:
        if state.retries == 0:
            return replace(state, retries=state.retries + 1), Effects(True)
        return replace(state, active=False), Effects(False)
    if event.kind == "done":
        return replace(state, active=False), Effects(False)
    return state, Effects(False)
'''


REQUIREMENTS = {
    "version": 1,
    "state": "State", "event": "Event", "initializers": ["initial"], "step": "step",
    "invariants": {"retry_bound": "0 <= state.retries <= 1"},
    "contracts": {"remaining": {"requires": ["0 <= n <= 1"], "ensures": ["0 <= result <= 1"]}},
    "properties": [
        {"name": "consume_retry", "variables": {"state": "State"}, "assume": ["state.retries == 0", "state.active"], "lets": {"next": "step(state, Event('crash'))"}, "assert": "next[0].retries == 1 and next[1].launch"},
        {"name": "two_crashes_stop", "lets": {"started": "step(initial(), Event('start'))[0]", "retried": "step(started, Event('crash'))[0]", "stopped": "step(retried, Event('crash'))"}, "assert": "not stopped[0].active and not stopped[1].launch"},
    ],
    "witnesses": [{"name": "retry_possible", "variables": {"state": "State"}, "assume": ["state.retries == 0"], "assert": "state.active and step(state, Event('crash'))[1].launch"}],
    "mutations": [{"name": "skip_retry", "function": "step", "target": "state.retries + 1", "replacement": "state.retries", "detects": ["property.consume_retry"]}],
}


class VerificationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)

    def verify(self, source=SOURCE, requirements=None, output=False):
        (self.root / "machine.py").write_text(source)
        (self.root / "requirements.inv").write_text(json.dumps(REQUIREMENTS if requirements is None else requirements))
        return verify(self.root / "machine.py", self.root / "requirements.inv", self.root / "proof" if output else None)

    def test_handwritten_source_properties_mutation_and_artifacts(self):
        report = self.verify(output=True)
        self.assertTrue(report["ok"], report)
        self.assertTrue(report["mutations"][0]["ok"])
        names = {item["name"] for item in report["obligations"]}
        self.assertTrue({"preserve.start.retry_bound", "preserve.crash.retry_bound", "preserve.done.retry_bound", "init.initial.retry_bound", "property.two_crashes_stop"} <= names)
        self.assertTrue(list((self.root / "proof" / "obligations").glob("*.smt2")))
        receipt = self.root / "proof" / "receipt.json"
        self.assertTrue(verify_receipt(self.root / "machine.py", self.root / "requirements.inv", receipt))
        with (self.root / "machine.py").open("a") as f:
            f.write("\n# edited\n")
        self.assertFalse(verify_receipt(self.root / "machine.py", self.root / "requirements.inv", receipt))

    def test_bad_initializer_fails_automatically(self):
        report = self.verify(SOURCE.replace("return State(0, False)", "return State(-1, False)"))
        self.assertFalse(report["ok"])
        self.assertTrue(any(x["name"] == "init.initial.retry_bound" and x["actual"] == "sat" for x in report["obligations"]))

    def test_rare_event_preservation_is_not_property_dependent(self):
        requirements = copy.deepcopy(REQUIREMENTS)
        requirements.update(properties=[], witnesses=[], mutations=[])
        source = SOURCE.replace('return replace(state, active=False), Effects(False)', 'return replace(state, retries=-1, active=False), Effects(False)')
        report = self.verify(source, requirements)
        self.assertFalse(report["ok"])
        self.assertTrue(any(x["name"] == "preserve.done.retry_bound" and not x["ok"] for x in report["obligations"]))

    def test_contradictory_premises_and_impossible_witness_fail(self):
        for kind in ("properties", "witnesses"):
            requirements = copy.deepcopy(REQUIREMENTS)
            requirements[kind] = [{"name": "impossible", "variables": {"x": "int"}, "assume": ["x > 0", "x < 0"], "assert": "True"}]
            requirements["mutations"] = []
            report = self.verify(requirements=requirements)
            self.assertFalse(report["ok"])
        requirements = copy.deepcopy(REQUIREMENTS)
        requirements["witnesses"] = [{"name": "false", "assert": "False"}]
        self.assertFalse(self.verify(requirements=requirements)["ok"])

    def test_unsupported_even_unreachable_source_rejected(self):
        source = SOURCE.replace("return State(0, False)", "return State(0, False)\n    print('unreachable')")
        with self.assertRaises(VerificationError):
            self.verify(source)
        for source in (SOURCE + "\nimport os\n", SOURCE.replace("retries: int", "retries: float"), SOURCE.replace("return 1 - n", "return remaining(n)")):
            with self.assertRaises(VerificationError):
                self.verify(source)

    def test_python_local_scoping_does_not_fall_back_to_globals(self):
        source = SOURCE + "\nLIMIT = 1\n\ndef local(flag: bool) -> int:\n    if flag:\n        LIMIT = 2\n    return LIMIT\n"
        with self.assertRaisesRegex(VerificationError, "Unbound local"):
            self.verify(source)
        source = SOURCE + "\nLIMIT = 1\n\ndef default(LIMIT: int = LIMIT) -> int:\n    return LIMIT\n"
        self.assertTrue(self.verify(source)["ok"])

    def test_imports_and_declarations_match_python_binding_order(self):
        for source in (SOURCE.replace("dataclass, replace", "dataclass"), SOURCE.replace("from typing import Literal", ""), SOURCE + "\ndef premature(n: int = LATER) -> int:\n    return n\n\nLATER = 1\n", SOURCE + "\nfrom __future__ import annotations\n"):
            with self.assertRaises(VerificationError):
                self.verify(source)

    def test_return_coverage_type_and_finite_literal_checks(self):
        requirements = copy.deepcopy(REQUIREMENTS)
        requirements["mutations"] = []
        for source in (SOURCE.replace("return 1 - n", "if n > 0:\n        return 1 - n"),):
            self.assertFalse(self.verify(source, requirements)["ok"])
        with self.assertRaises(VerificationError):
            self.verify(SOURCE.replace("return 1 - n", "return True"), requirements)
        requirements["properties"].append({"name": "invalid_event", "assert": "step(initial(), Event('unknown'))[0].retries == 0"})
        self.assertFalse(self.verify(requirements=requirements)["ok"])

    def test_short_circuit_and_guarded_helper_preconditions(self):
        base = SOURCE + '''
def divide(n: int) -> int:
    return 10 // n

def guarded(n: int) -> bool:
    return n == 0 or divide(n) == 10 // n

def conditional(n: int) -> int:
    if n != 0:
        return divide(n)
    return 0

def chained(n: int) -> bool:
    return 0 < n < divide(n)
'''
        requirements = copy.deepcopy(REQUIREMENTS)
        requirements["contracts"]["divide"] = {"requires": ["n != 0"]}
        self.assertTrue(self.verify(base, requirements)["ok"])
        self.assertFalse(self.verify(base.replace("n == 0 or divide(n)", "n != 0 or divide(n)"), requirements)["ok"])

    def test_preconditions_and_premises_cannot_hide_undefined_calls(self):
        source = SOURCE + "\ndef divide(n: int) -> int:\n    return 10 // n\n"
        requirements = copy.deepcopy(REQUIREMENTS)
        requirements["contracts"]["divide"] = {"requires": ["n != 0"]}
        requirements["properties"] = [{"name": "partial_premise", "variables": {"n": "int"}, "assume": ["divide(n) > 0"], "assert": "True"}]
        requirements["mutations"] = []
        self.assertFalse(self.verify(source, requirements)["ok"])
        requirements["properties"][0]["assume"].insert(0, "n != 0")
        self.assertTrue(self.verify(source, requirements)["ok"])

    def test_concrete_and_symbolic_branch_semantics_agree(self):
        namespace = {}
        exec(compile(SOURCE, "fixture", "exec"), namespace)
        source = Source(SOURCE)
        interpreter = Interpreter(source, REQUIREMENTS)
        for retries in (0, 1):
            for active in (False, True):
                for event in ("start", "crash", "done"):
                    state = interpreter.expr(source.expression(f"State({retries}, {active})"), {}, z3.BoolVal(True))
                    symbolic = interpreter.call("step", [state, interpreter.expr(source.expression(f"Event('{event}')"), {}, z3.BoolVal(True))], {})
                    actual = namespace["step"](namespace["State"](retries, active), namespace["Event"](event))
                    self.assertEqual(z3.simplify(integer(symbolic[0].fields["retries"])).as_long(), actual[0].retries)
                    self.assertEqual(z3.is_true(z3.simplify(boolean(symbolic[0].fields["active"]))), actual[0].active)
                    self.assertEqual(z3.is_true(z3.simplify(boolean(symbolic[1].fields["launch"]))), actual[1].launch)

    def test_python_division_and_modulo_match_concrete_execution(self):
        source = Source(SOURCE + "\ndef divmod_pair(a: int, b: int) -> tuple[int, int]:\n    return a // b, a % b\n")
        for a in (-7, -1, 0, 1, 7):
            for b in (-3, -1, 1, 3):
                interpreter = Interpreter(source, {})
                value = interpreter.call("divmod_pair", [a, b], {})
                self.assertEqual(tuple(z3.simplify(x).as_long() for x in value), (a // b, a % b))

    def test_nested_record_fixed_tuple_and_unpacking(self):
        source = SOURCE + '''
@dataclass(frozen=True)
class Pair:
    state: State
    values: tuple[int, bool]

def nested(pair: Pair) -> Pair:
    n, flag = pair.values
    return replace(pair, values=(n + 1, not flag))
'''
        requirements = copy.deepcopy(REQUIREMENTS)
        requirements["contracts"]["nested"] = {"ensures": ["result.values[0] == pair.values[0] + 1", "result.values[1] != pair.values[1]", "result.state == pair.state"]}
        self.assertTrue(self.verify(source, requirements)["ok"])

    def test_mutation_requires_unique_selector_and_real_counterexample(self):
        requirements = copy.deepcopy(REQUIREMENTS)
        requirements["mutations"][0]["replacement"] = "state.retries + 1"
        self.assertFalse(self.verify(requirements=requirements)["ok"])
        requirements["mutations"][0]["target"] = "state"
        with self.assertRaises(VerificationError):
            self.verify(requirements=requirements)
        requirements["mutations"][0]["target"] = "state.retries + 1"
        requirements["mutations"][0]["replacement"] = "missing()"
        with self.assertRaises(VerificationError):
            self.verify(requirements=requirements)

    def test_unknown_solver_result_fails_closed(self):
        class UnknownSolver:
            def set(self, **kwargs):
                pass
            def add(self, *args):
                pass
            def check(self):
                return z3.unknown
            def reason_unknown(self):
                return "timeout"
        checker = Checker(Source(SOURCE), REQUIREMENTS)
        with patch("invariant.verification.checker.z3.Solver", UnknownSolver):
            result = checker.solve("timeout", True)
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "timeout")

    def test_generated_runtime_validators_have_no_z3_dependency(self):
        self.assertTrue(self.verify(output=True)["ok"])
        def load(name, path):
            spec = importlib.util.spec_from_file_location(name, path)
            module = importlib.util.module_from_spec(spec)
            sys.modules[name] = module
            spec.loader.exec_module(module)
            self.addCleanup(sys.modules.pop, name, None)
            return module
        machine = load("verified_fixture", self.root / "machine.py")
        validators = load("fixture_validators", self.root / "proof" / "validators.py").bind(machine)
        validators.validate_state(machine.initial())
        validators.validate_before("remaining", {"n": 0})
        validators.validate_after("remaining", {"n": 0}, 1)
        for callback in (lambda: validators.validate_state(machine.State(-1, False)), lambda: validators.validate_before("remaining", {"n": True}), lambda: validators.validate_before("remaining", {"n": 2}), lambda: validators.validate_after("remaining", {"n": 0}, 2)):
            with self.assertRaises(ValueError):
                callback()
        # Inspect the import boundary rather than relying on this process, which
        # necessarily imports the solver to exercise the verification itself.
        from invariant.verification import runtime_contracts
        tree = ast.parse(Path(runtime_contracts.__file__).read_text())
        imports = [node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
        imports += [item.name for node in ast.walk(tree) if isinstance(node, ast.Import) for item in node.names]
        self.assertFalse(any(name and name.startswith("z3") for name in imports))

    def test_generated_contracts_accept_relocated_binder_without_global_alias(self):
        self.assertTrue(self.verify(output=True)["ok"])
        from invariant import Machine
        from invariant.verification import runtime_contracts
        import builtins
        original_import = builtins.__import__
        def private_only(name, *arguments, **keywords):
            if name == "invariant" or name.startswith("invariant."):
                raise ImportError("global invariant package is unavailable")
            return original_import(name, *arguments, **keywords)
        fixture_module = importlib.util.module_from_spec(importlib.util.spec_from_file_location(
            "relocated_automaton", self.root / "machine.py"))
        sys.modules[fixture_module.__name__] = fixture_module
        self.addCleanup(sys.modules.pop, fixture_module.__name__, None)
        fixture_module.__spec__.loader.exec_module(fixture_module)
        generated = {}
        with patch("builtins.__import__", private_only):
            exec((self.root / "proof" / "validators.py").read_text(), generated)
            bindings = generated["bind"](fixture_module, binder=runtime_contracts.bind)
            bindings.validate_state(fixture_module.initial())
            contracts = type("Contracts", (), {"bind": staticmethod(generated["bind"])})
            bound = Machine(fixture_module, contracts=contracts, initializers=("initial",))
            bound.validate_state(fixture_module.initial())

    def test_failed_recheck_removes_success_receipt(self):
        self.assertTrue(self.verify(output=True)["ok"])
        self.assertFalse(self.verify(SOURCE.replace("return State(0, False)", "return State(-1, False)"), output=True)["ok"])
        self.assertFalse((self.root / "proof" / "receipt.json").exists())
        self.assertFalse((self.root / "proof" / "validators.py").exists())
        self.assertTrue(self.verify(output=True)["ok"])
        with self.assertRaises(VerificationError):
            self.verify(SOURCE + "\nimport os\n", output=True)
        self.assertFalse((self.root / "proof" / "receipt.json").exists())

    def test_missing_build_required_property_rejects_receipt(self):
        self.assertTrue(self.verify(output=True)["ok"])
        source = self.root / "machine.py"
        requirements_path = self.root / "requirements.inv"
        output = self.root / "proof"
        report = verify(source, requirements_path, output, required_properties=["consume_retry", "two_crashes_stop"])
        self.assertEqual(report["required_properties"], ["consume_retry", "two_crashes_stop"])
        requirements = copy.deepcopy(REQUIREMENTS)
        requirements["properties"] = [claim for claim in requirements["properties"] if claim["name"] != "two_crashes_stop"]
        requirements_path.write_text(json.dumps(requirements))
        with self.assertRaisesRegex(VerificationError, "Missing required properties: two_crashes_stop"):
            verify(source, requirements_path, output, required_properties=["consume_retry", "two_crashes_stop"])
        self.assertFalse((output / "receipt.json").exists())
        self.assertFalse((output / "validators.py").exists())

    def test_exact_unicode_union_and_dynamic_tuple_index(self):
        source = '"""Arbitrary Unicode documentation: 😀."""\n' + SOURCE + '''
def same(a: int | str, b: int | str) -> bool:
    return a == b

def at(values: tuple[int | str, ...], index: int) -> int | str:
    if not -len(values) <= index < len(values):
        raise ValueError('index out of range')
    return values[index]
'''
        requirements = copy.deepcopy(REQUIREMENTS)
        requirements['mutations'] = []
        requirements['contracts']['at'] = {'requires': ['-len(values) <= index < len(values)']}
        texts = [('😀', r'\u{1f600}'), ('\U00040000', r'\u{40000}'), ('\ud800', r'\ud800'), ('\0', '')]
        for index, (a, b) in enumerate(texts):
            requirements['properties'].append({'name': 'unicode_' + str(index), 'assert': f'not same({a!r}, {b!r})'})
        requirements['properties'].extend([
            {'name': 'tagged_identity', 'assert': "not same(1, '1')"},
            {'name': 'negative_index', 'assert': "at((1, '1'), -1) == '1'"},
            {'name': 'identity_reflexive', 'variables': {'value': 'int | str'}, 'assert': 'same(value, value)'},
        ])
        self.assertTrue(self.verify(source, requirements)['ok'])

    def test_admission_preconditions_gate_event_induction_and_raise_paths(self):
        source = SOURCE.replace('kind: Literal["start", "crash", "done"]', 'kind: Literal["start", "crash", "done"]\n    budget: int = 0')
        source = source.replace('if event.kind == "start" and not state.active:', 'if event.budget < 0:\n        raise ValueError("negative budget")\n    if event.kind == "start" and not state.active:')
        requirements = copy.deepcopy(REQUIREMENTS)
        requirements['contracts']['step'] = {'requires': ['event.budget >= 0']}
        self.assertTrue(self.verify(source, requirements)['ok'])
        requirements['contracts'].pop('step')
        self.assertFalse(self.verify(source, requirements)['ok'])

    def loop_fixture(self):
        source = SOURCE + '''
def count(values: tuple[int, ...], selected: int) -> int:
    total = 0
    for item in values:
        total = total + (1 if item == selected else 0)
    return total

def all_final(values: tuple[int, ...]) -> bool:
    total = True
    for item in values:
        total = total and item == 65
    return total

def first(values: tuple[bool, ...], start: int) -> int:
    length = len(values)
    if length == 0:
        return -1
    cursor = start % length
    for offset in range(length):
        index = (cursor + offset) % length
        if values[index]:
            return index
    return -1
'''
        requirements = copy.deepcopy(REQUIREMENTS)
        requirements['mutations'] = []
        requirements['contracts'].update({
            'count': {'ensures': ['result == sum_range(i,0,len(values),1 if values[i] == selected else 0)']},
            'all_final': {'ensures': ['result == forall_range(i,0,len(values),values[i] == 65)']},
            'first': {'ensures': ['(result == -1) == forall_range(i,0,len(values),not values[i])', 'result == -1 or (0 <= result < len(values) and values[result])', 'result == -1 or forall_range(i,0,len(values),(i-start)%len(values) >= (result-start)%len(values) or not values[i])']},
        })
        requirements['loops'] = [
            {'name': 'count_prefix', 'function': 'count', 'target': 'item', 'iter': 'values', 'cursor': 'processed', 'invariants': ['total == sum_range(i,0,processed,1 if values[i] == selected else 0)'], 'decreases': 'len(values)-processed'},
            {'name': 'all_prefix', 'function': 'all_final', 'target': 'item', 'iter': 'values', 'cursor': 'processed', 'invariants': ['total == forall_range(i,0,processed,values[i] == 65)'], 'decreases': 'len(values)-processed'},
            {'name': 'first_prefix', 'function': 'first', 'target': 'offset', 'iter': 'range(length)', 'cursor': 'processed', 'invariants': ['length == len(values)', 'length > 0', 'cursor == start % length', '0 <= cursor < length', 'forall_range(i,0,length,(i-start)%length >= processed or not values[i])'], 'decreases': 'length-processed'},
        ]
        return source, requirements

    def test_unbounded_loops_are_inductive_with_early_return_and_empty_inputs(self):
        source, requirements = self.loop_fixture()
        report = self.verify(source, requirements)
        self.assertTrue(report['ok'], [x for x in report['obligations'] if not x['ok']])
        names = [x['name'] for x in report['obligations']]
        self.assertTrue(any('.preserve.' in name for name in names))
        self.assertTrue(any('.decrease.' in name for name in names))
        namespace = {}
        exec(source, namespace)
        for length in (0, 1, 13, 1001):
            values = tuple(i % 7 for i in range(length))
            self.assertEqual(namespace['count'](values, 3), values.count(3))
            self.assertEqual(namespace['all_final']((65,) * length), True)
            eligible = tuple(i == length - 1 for i in range(length))
            for start in (-10**30, -1, 0, 10**30):
                self.assertEqual(namespace['first'](eligible, start), length - 1)

    def test_false_loop_invariant_bad_body_and_non_decrease_fail_closed(self):
        source, requirements = self.loop_fixture()
        for mutation in ('base', 'body', 'variant', 'missing'):
            candidate = copy.deepcopy(requirements)
            changed = source
            if mutation == 'base':
                candidate['loops'][0]['invariants'] = ['total == 1']
            elif mutation == 'body':
                changed = source.replace('total + (1 if item == selected else 0)', 'total + 1')
            elif mutation == 'variant':
                candidate['loops'][0]['decreases'] = 'processed'
            else:
                candidate['loops'].pop()
                with self.assertRaises(VerificationError):
                    self.verify(changed, candidate)
                continue
            report = self.verify(changed, candidate)
            self.assertFalse(report['ok'], mutation)

    def test_required_witness_and_mutation_inventory_and_concrete_replay(self):
        self.assertTrue(self.verify(output=True)['ok'])
        report = verify(self.root / 'machine.py', self.root / 'requirements.inv',
                        required_witnesses=['retry_possible'], required_mutations=['skip_retry'])
        self.assertTrue(report['mutations'][0]['replay']['ok'])
        for argument in ('required_witnesses', 'required_mutations'):
            with self.assertRaisesRegex(VerificationError, 'Missing required'):
                verify(self.root / 'machine.py', self.root / 'requirements.inv', **{argument: ['missing']})

    def test_mutation_replay_covers_loop_and_contract_counterexamples(self):
        source = SOURCE + '''
def all_valid(values: tuple[int, ...]) -> bool:
    valid = True
    for item in values:
        valid = valid and item >= 0
    return valid

def agrees(left: int, right: int) -> bool:
    return left == right
'''
        requirements = copy.deepcopy(REQUIREMENTS)
        requirements['contracts'].update({
            'all_valid': {'ensures': [
                'result == forall_range(i,0,len(values),values[i] >= 0)',
            ]},
            'agrees': {'ensures': ['result == (left == right)']},
        })
        requirements['properties'] = []
        requirements['witnesses'] = []
        requirements['mutations'] = [
            {'name': 'accept_invalid_item', 'function': 'all_valid',
             'target': 'item >= 0', 'replacement': 'True',
             'detects': ['loop.all_valid.4.all_valid.all_valid_prefix.preserve.0']},
            {'name': 'never_agree', 'function': 'agrees',
             'target': 'left == right', 'replacement': 'False',
             'detects': ['contract.agrees.0']},
        ]
        requirements['loops'] = [{
            'name': 'all_valid_prefix', 'function': 'all_valid',
            'target': 'item', 'iter': 'values', 'cursor': 'processed',
            'invariants': [
                'valid == forall_range(i,0,processed,values[i] >= 0)',
            ],
            'decreases': 'len(values)-processed',
        }]
        report = self.verify(source, requirements)
        self.assertTrue(report['ok'], report)
        self.assertTrue(all(mutation['ok'] and mutation['replay']['ok']
                            for mutation in report['mutations']))

    def test_helper_memo_preserves_path_and_type_obligations(self):
        source = SOURCE + '''
def divide(value: int) -> int:
    return 10 // value

def later(value: int) -> int:
    if value != 0:
        first = divide(value)
    else:
        first = 0
    return first + divide(value)
'''
        requirements = copy.deepcopy(REQUIREMENTS)
        requirements['mutations'] = []
        requirements['contracts']['divide'] = {'requires': ['value != 0']}
        report = self.verify(source, requirements)
        self.assertTrue(any(row['name'] == 'defined.later' and row['actual'] == 'sat' for row in report['obligations']))
        source = SOURCE + '''
def identity(value: int | str) -> int | str:
    return value
'''
        requirements = copy.deepcopy(REQUIREMENTS)
        requirements['mutations'] = []
        requirements['properties'].append({'name': 'wrong_identity_type', 'assert': 'identity(True) == True'})
        report = self.verify(source, requirements)
        self.assertTrue(any(row['name'] == 'defined.property.wrong_identity_type' and row['actual'] == 'sat' for row in report['obligations']))

    def test_sequence_equality_and_modulo_lowering_match_python(self):
        source = Source(SOURCE + '''
def compare(a: tuple[int, ...], b: tuple[bool, ...]) -> bool:
    return a == b

def rotate(a: int, b: int, n: int) -> int:
    return ((a % n + b) % n - a) % n
''')
        for a in (-1001, -1, 0, 1, 1001):
            for b in (-13, 0, 17):
                for n in (-7, -1, 1, 13):
                    interpreter = Interpreter(source, {})
                    actual = interpreter.call('rotate', [a, b, n], {})
                    self.assertEqual(z3.simplify(integer(actual)).as_long(), ((a % n + b) % n - a) % n)
        interpreter = Interpreter(source, {})
        a = interpreter.symbol('a', source.signatures['compare'][0]['a'])
        b = interpreter.symbol('b', source.signatures['compare'][0]['b'])
        result = interpreter.call('compare', [a, b], {})
        solver = z3.Solver()
        solver.add(*interpreter.domains, a.length == 1, b.length == 1, a.values[0] == 1, b.values[0], z3.Not(result))
        self.assertEqual(solver.check(), z3.unsat)

    def test_dynamic_sequence_appends_fixed_tuple(self):
        source = SOURCE + '''
def append(values: tuple[int | str, ...], value: int | str) -> tuple[int | str, ...]:
    return values + (value,)
'''
        requirements = copy.deepcopy(REQUIREMENTS)
        requirements['mutations'] = []
        requirements['contracts']['append'] = {'ensures': [
            'len(result) == len(values) + 1',
            'result[len(values)] == value',
            'forall_range(i, 0, len(values), result[i] == values[i])',
        ]}
        report = self.verify(source, requirements)
        self.assertTrue(report['ok'], [row for row in report['obligations'] if not row['ok']])

        namespace = {}
        exec(source, namespace)
        for values, value in (((), 1), ((1, 'a'), 'b'), (('x',), 2)):
            self.assertEqual(namespace['append'](values, value), values + (value,))

    def test_range_aggregates_reject_transitive_loop_summaries(self):
        source = Source(SOURCE + '''
def looped(value: int) -> int:
    total = 0
    for item in (value,):
        total = total + item
    return total

def wrapped(value: int) -> int:
    return looped(value)

def contract_wrapped(value: int) -> int:
    return value
''')
        requirements = copy.deepcopy(REQUIREMENTS)
        requirements['contracts']['contract_wrapped'] = {
            'ensures': ['result == looped(value)'],
        }
        expressions = (
            'forall_range(i, 0, 2, looped(i) == 0)',
            'exists_range(i, 0, 2, wrapped(i) == 0)',
            'sum_range(i, 0, 2, contract_wrapped(i))',
            'forall_range(i, 0, 2, exists_range(j, 0, 2, wrapped(i + j) == 0))',
        )
        for expression in expressions:
            with self.subTest(expression=expression):
                interpreter = Interpreter(source, requirements, summaries={'looped'})
                with self.assertRaisesRegex(VerificationError, 'Looping helper calls'):
                    interpreter.expression(expression, {})

    def test_range_aggregates_preserve_inline_loop_free_helpers(self):
        source = Source(SOURCE + '''
def scalar(value: int) -> int:
    return value + 1
''')
        requirements = copy.deepcopy(REQUIREMENTS)
        requirements['mutations'] = []
        requirements['contracts']['scalar'] = {
            'requires': ['value >= 0'],
            'ensures': ['result == value + 1'],
        }
        interpreter = Interpreter(source, requirements, summaries={'scalar'})
        result = boolean(interpreter.expression(
            'forall_range(i, 0, 3, scalar(i) == i + 1)', {},
        ))
        solver = z3.Solver()
        solver.add(z3.Not(result))
        self.assertEqual(solver.check(), z3.unsat)
        self.assertTrue(interpreter.safety)
        self.assertTrue(any(z3.is_quantifier(condition)
                            for _reason, condition in interpreter.safety))

    def test_range_aggregate_rejects_binder_dependent_normalization_assumption(self):
        source = Source(SOURCE)
        interpreter = Interpreter(source, {})
        divisor = interpreter.symbol('divisor', source.signatures['remaining'][0]['n'])
        interpreter.nonnegative.add(divisor.get_id())
        with self.assertRaisesRegex(VerificationError, 'assumptions cannot escape'):
            interpreter.expression('sum_range(i, 1, 5, (divisor + i) % i)',
                                   {'divisor': divisor})

    def test_concrete_identity_sequence_trace_preserves_declared_type(self):
        source = SOURCE + '''
@dataclass(frozen=True)
class Ledger:
    entries: tuple[int | str, ...] = ()

def append_entry(ledger: Ledger, value: int | str) -> Ledger:
    return replace(ledger, entries=ledger.entries + (value,)) if value != '' else ledger
'''
        requirements = copy.deepcopy(REQUIREMENTS)
        requirements['mutations'] = []
        requirements['witnesses'].append({
            'name': 'mixed_identity_ledger',
            'lets': {'first': "append_entry(Ledger(), 'scope')",
                     'second': 'append_entry(first, 7)'},
            'assert': "second.entries == ('scope', 7)",
        })
        report = self.verify(source, requirements)
        self.assertTrue(report['ok'], [row for row in report['obligations'] if not row['ok']])

    def test_empty_tuple_index_still_requires_an_unreachable_guard(self):
        for guard in (True, False):
            interpreter = Interpreter(Source(SOURCE), {})
            interpreter.index((), z3.IntVal(0), z3.BoolVal(guard))
            condition = z3.simplify(z3.And(*(value for _reason, value in interpreter.safety)))
            self.assertEqual(z3.is_true(condition), not guard)



if __name__ == "__main__":
    unittest.main()
