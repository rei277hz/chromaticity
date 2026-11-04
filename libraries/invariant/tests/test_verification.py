import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import z3

from invariant.verification.checker import Checker, verify, verify_receipt
from invariant.verification.model import Source, Type, VerificationError
from invariant.verification.symbolic import Interpreter, Sequence, OPTIONALS, TEXT, equal, integer, boolean, modulo


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

    def verify(self, source=SOURCE, requirements=None, output=False, timeout_ms=5000):
        (self.root / "machine.py").write_text(source)
        (self.root / "requirements.inv").write_text(json.dumps(REQUIREMENTS if requirements is None else requirements))
        return verify(self.root / "machine.py", self.root / "requirements.inv", self.root / "proof" if output else None, timeout_ms=timeout_ms)

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

    def test_transition_properties_do_not_require_a_redundant_state_invariant(self):
        requirements = copy.deepcopy(REQUIREMENTS)
        requirements['invariants'] = {}
        report = self.verify(requirements=requirements)
        self.assertTrue(report['ok'], report)
        self.assertTrue(report['mutations'][0]['ok'])
        requirements['properties'] = []
        with self.assertRaisesRegex(VerificationError, 'named invariant or property'):
            self.verify(requirements=requirements)

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

    def test_optional_string_none_semantics(self):
        source = '''from dataclasses import dataclass
from typing import Optional

@dataclass(frozen=True)
class State:
    signature: Optional[str]

@dataclass(frozen=True)
class Event:
    signature: Optional[str]

@dataclass(frozen=True)
class Effects:
    pass

def new() -> State:
    return State(None)

def absent(state: State) -> bool:
    return state.signature is None

def step(state: State, event: Event) -> tuple[State, Effects]:
    if event.signature is None:
        return state, Effects()
    return State(event.signature), Effects()
'''
        requirements = {
            "version": 1,
            "state": "State",
            "event": "Event",
            "initializers": ["new"],
            "step": "step",
            "invariants": {"signature_is_optional": "state.signature is None or state.signature is not None"},
            "contracts": {"new": {"ensures": ["result.signature is None"]}},
            "properties": [
                {
                    "name": "none_branch_is_absent",
                    "variables": {"state": "State"},
                    "assume": ["state.signature is None"],
                    "assert": "absent(state)",
                },
                {
                    "name": "string_branch_is_present",
                    "variables": {"state": "State"},
                    "assume": ["state.signature is not None"],
                    "assert": "not absent(state)",
                },
            ],
            "witnesses": [],
            "mutations": [],
        }
        report = self.verify(source, requirements, output=True)
        self.assertTrue(report["ok"], report)
        self.assertFalse((self.root / "proof" / "validators.py").exists())

        for scalar in ("int", "bool"):
            with self.subTest(scalar=scalar):
                report = self.verify(source.replace("Optional[str]", "Optional[" + scalar + "]"), requirements)
                self.assertTrue(report["ok"], report)
        with self.assertRaises(VerificationError):
            Source(source.replace("Optional[str]", "Optional[tuple[int, ...]]"))

    def test_optional_scalars_preserve_empty_values_and_replay_counterexamples(self):
        for scalar, present in (("str", "''"), ("int", "0"), ("bool", "False")):
            source = '''from dataclasses import dataclass
from typing import Optional

@dataclass(frozen=True)
class State:
    value: Optional[SCALAR]

@dataclass(frozen=True)
class Event:
    value: Optional[SCALAR]

@dataclass(frozen=True)
class Effects:
    pass

def new() -> State:
    return State(None)

def step(state: State, event: Event) -> tuple[State, Effects]:
    return State(event.value), Effects()
'''.replace('SCALAR', scalar)
            requirements = {
                "version": 1, "state": "State", "event": "Event",
                "initializers": ["new"], "step": "step", "invariants": {"optional_value": "state.value is None or state.value is not None"},
                "properties": [{"name": "present_value_is_preserved",
                    "variables": {"event": "Event"},
                    "assume": ["event.value == " + present],
                    "assert": "step(new(), event)[0].value == event.value and step(new(), event)[0].value is not None"}],
                "witnesses": [{"name": "empty_value_is_present", "variables": {"event": "Event"},
                    "assert": "event.value == " + present + " and event.value is not None"}],
                "mutations": [{"name": "drop_present_value", "function": "step",
                    "target": "State(event.value)", "replacement": "State(None)",
                    "detects": ["property.present_value_is_preserved"]}],
            }
            with self.subTest(scalar=scalar):
                report = self.verify(source, requirements, output=True)
                self.assertTrue(report["ok"], report)
                self.assertTrue(report["mutations"][0]["replay"]["ok"])

    def test_nested_record_sequences_preserve_members_and_replay_mutations(self):
        source = '''from dataclasses import dataclass
from typing import Literal, Optional

@dataclass(frozen=True)
class Item:
    identity: Optional[int]
    labels: tuple[str, ...]
    status: Literal["ready", "done"] = "ready"

@dataclass(frozen=True)
class State:
    items: tuple[Item, ...]

@dataclass(frozen=True)
class Event:
    item: Item
    append: bool

@dataclass(frozen=True)
class Effects:
    items: tuple[Item, ...] = ()

def new() -> State:
    return State(())

def step(state: State, event: Event) -> tuple[State, Effects]:
    if event.append:
        return State(state.items + (event.item,)), Effects((event.item,))
    return state, Effects()
'''
        requirements = {
            "version": 1, "state": "State", "event": "Event",
            "initializers": ["new"], "step": "step", "invariants": {"nonnegative_length": "len(state.items) >= 0"},
            "properties": [{"name": "append_retains_nested_item",
                "variables": {"state": "State", "event": "Event"},
                "assume": ["event.append"], "lets": {"result": "step(state, event)"},
                "assert": "len(result[0].items) == len(state.items) + 1 and result[0].items[len(state.items)] == event.item and result[1].items == (event.item,)"}],
            "witnesses": [{"name": "nested_optional_is_not_absent",
                "variables": {"event": "Event"},
                "assert": "event.append and event.item.identity == 0 and event.item.labels == ('', 'x') and event.item.status == 'done'"}],
            "mutations": [{"name": "drop_nested_effect", "function": "step",
                "target": "Effects((event.item,))", "replacement": "Effects()",
                "detects": ["property.append_retains_nested_item"]}],
        }
        report = self.verify(source, requirements, output=True)
        self.assertTrue(report["ok"], report)
        self.assertTrue(report["mutations"][0]["replay"]["ok"])
        invalid_source = source.replace('state.items + (event.item,)',
                                        'state.items + (Item(event.item.identity, event.item.labels, "invalid"),)')
        invalid_requirements = copy.deepcopy(requirements)
        invalid_requirements['mutations'] = []
        invalid_report = self.verify(invalid_source, invalid_requirements)
        self.assertFalse(invalid_report['ok'])

    def test_mixed_optional_and_record_storage_smt_is_standalone(self):
        source = Source(SOURCE.replace('from typing import Literal',
                                      'from typing import Literal, Optional') + '''
@dataclass(frozen=True)
class Item:
    number: Optional[int]
    text: Optional[str]
    enabled: Optional[bool]
    states: tuple[State, ...]
''')
        interpreter = Interpreter(source, {})
        items = interpreter.symbol('items', Type('sequence', (Type('record', ('Item',)),)))
        item = items.at(0)
        solver = z3.Solver()
        solver.add(*interpreter.domains, items.length == 1,
                   equal(item.fields['number'], None),
                   equal(item.fields['text'], ''),
                   equal(item.fields['enabled'], False))
        self.assertEqual(solver.check(), z3.sat)
        replay = z3.Solver()
        replay.add(z3.parse_smt2_string(solver.to_smt2()))
        self.assertEqual(replay.check(), z3.sat)

    def test_optional_integer_narrowing_requires_presence(self):
        source = SOURCE.replace('from typing import Literal', 'from typing import Literal, Optional') + '''
def increment(value: Optional[int]) -> int:
    if value is None:
        return 0
    return value + 1

def prepend(value: Optional[int], values: tuple[int, ...]) -> tuple[int, ...]:
    if value is None:
        return values
    return (value,) + values
'''
        requirements = copy.deepcopy(REQUIREMENTS)
        requirements['mutations'] = []
        self.assertTrue(self.verify(source, requirements)['ok'])
        for guard in ('    if value is None:\n        return 0\n',
                      '    if value is None:\n        return values\n'):
            with self.subTest(guard=guard):
                report = self.verify(source.replace(guard, ''), requirements)
                self.assertFalse(report['ok'])
                self.assertTrue(any(not obligation['ok'] and obligation['name'].startswith('defined.')
                                    for obligation in report['obligations']))


    def test_sequence_equality_ignores_storage_outside_tuple_length(self):
        interpreter = Interpreter(Source(SOURCE), {})
        zeroes = z3.K(z3.IntSort(), z3.IntVal(0))
        baseline = Sequence(z3.IntVal(1), zeroes, Type('int'), interpreter)
        outside = Sequence(z3.IntVal(1), z3.Store(zeroes, 4, 9), Type('int'), interpreter)
        inside = Sequence(z3.IntVal(1), z3.Store(zeroes, 0, 9), Type('int'), interpreter)
        longer = Sequence(z3.IntVal(2), zeroes, Type('int'), interpreter)
        boolean_zero = Sequence(z3.IntVal(1), z3.K(z3.IntSort(), z3.BoolVal(False)),
                                Type('bool'), interpreter)
        for other, expected in ((outside, True), (inside, False), (longer, False),
                                (boolean_zero, True)):
            with self.subTest(expected=expected, element=other.element):
                solver = z3.Solver()
                solver.add(equal(baseline, other) != expected)
                self.assertEqual(solver.check(), z3.unsat)

    def test_python_division_and_modulo_match_concrete_execution(self):
        source = Source(SOURCE + "\ndef divmod_pair(a: int, b: int) -> tuple[int, int]:\n    return a // b, a % b\n")
        for a in (-7, -1, 0, 1, 7):
            for b in (-3, -1, 1, 3):
                interpreter = Interpreter(source, {})
                value = interpreter.call("divmod_pair", [a, b], {})
                self.assertEqual(tuple(z3.simplify(x).as_long() for x in value), (a // b, a % b))

    def test_structural_optional_text_typing_preserves_unicode_domain(self):
        interpreter = Interpreter(Source(SOURCE), {})
        text = Type('str')
        optional_text = Type('optional', (text,))
        sort = OPTIONALS['str']
        unknown = z3.Const('untrusted.text', TEXT)
        wrapped = interpreter.typed(sort.optional_some(unknown), optional_text)
        for codepoint in (-1, 0x110000):
            solver = z3.Solver()
            solver.add(unknown == z3.Unit(z3.IntVal(codepoint)), wrapped)
            self.assertEqual(solver.check(), z3.unsat)
        for codepoint in (0, 0xd800, 0x10ffff):
            unit = z3.Unit(z3.IntVal(codepoint))
            self.assertTrue(z3.is_true(z3.simplify(interpreter.typed(unit, text))))
        concatenated = z3.Concat(z3.Unit(z3.IntVal(65)), unknown)
        solver = z3.Solver()
        solver.add(unknown == z3.Unit(z3.IntVal(-1)), interpreter.typed(concatenated, text))
        self.assertEqual(solver.check(), z3.unsat)
        self.assertTrue(z3.is_true(interpreter.typed(z3.Empty(TEXT), text)))
        self.assertTrue(z3.is_true(interpreter.typed(sort.optional_none, optional_text)))

    def test_action_sequences_preserve_optional_and_constant_error_text(self):
        source = '''from dataclasses import dataclass
from typing import Literal, Optional

@dataclass(frozen=True)
class Action:
    kind: Literal['failure', 'cleanup']
    error: Optional[str]

@dataclass(frozen=True)
class State:
    error: Optional[str]

@dataclass(frozen=True)
class Event:
    error: Optional[str]
    cleanup: bool

@dataclass(frozen=True)
class Effects:
    actions: tuple[Action, ...]

def new() -> State:
    return State(None)

def step(state: State, event: Event) -> tuple[State, Effects]:
    actions = (Action('failure', event.error),)
    if event.cleanup:
        actions = actions + (Action('cleanup', 'GPU helper exited unexpectedly'),)
    return State(event.error), Effects(actions)
'''
        requirements = {
            'version': 1, 'state': 'State', 'event': 'Event',
            'initializers': ['new'], 'step': 'step',
            'invariants': {'optional_error': 'state.error is None or state.error is not None'},
            'properties': [{
                'name': 'failure_text_survives_action_encoding',
                'variables': {'event': 'Event'}, 'lets': {'result': 'step(new(), event)'},
                'assert': "result[0].error == event.error and result[1].actions[0].error == event.error and len(result[1].actions) == (2 if event.cleanup else 1)",
            }],
            'witnesses': [{
                'name': 'empty_text_is_not_absence', 'variables': {},
                'assert': "step(new(), Event('', True))[1].actions == (Action('failure', ''), Action('cleanup', 'GPU helper exited unexpectedly'))",
            }],
        }
        report = self.verify(source, requirements)
        self.assertTrue(report['ok'], [item for item in report['obligations'] if not item['ok']])


    def test_bounded_modulo_rewrite_is_exact_for_every_integer_divisor(self):
        dividend, divisor = z3.Ints('rewrite.dividend rewrite.divisor')
        solver = z3.Solver()
        solver.set(timeout=5000)
        # This also checks zero: no shortcut guard may apply there. The source
        # interpreter separately rejects division by zero before using a result.
        solver.add(modulo(dividend, divisor) != dividend % divisor)
        self.assertEqual(solver.check(), z3.unsat)

        source = Source(SOURCE + '\ndef remainder(a: int, b: int) -> int:\n    return a % b\n')
        for b in (-7, -1, 1, 7):
            for a in (-2 * abs(b), -abs(b), -1, 0, abs(b) - 1, abs(b), 2 * abs(b)):
                interpreter = Interpreter(source, {})
                result = interpreter.call('remainder', [a, b], {})
                self.assertEqual(z3.simplify(result).as_long(), a % b)
        interpreter = Interpreter(source, {})
        interpreter.call('remainder', [1, 0], {})
        solver = z3.Solver()
        solver.add(*(condition for _reason, condition in interpreter.safety))
        self.assertEqual(solver.check(), z3.unsat)

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

    def test_conjunction_proofs_preserve_nested_guards_and_original_artifact(self):
        value = z3.Int('conjunction.value')
        premises = value >= 0
        conclusion = z3.Implies(value > 2, z3.And(
            value >= 0, z3.Implies(value > 3, z3.And(value > 2, value >= 4))))
        checker = Checker(Source(SOURCE), REQUIREMENTS, self.root / 'split')
        result = checker.prove('guarded', premises, conclusion)
        self.assertTrue(result['ok'])
        self.assertEqual([part['actual'] for part in result['components']], ['unsat'] * 3)
        artifact = z3.And(*z3.parse_smt2_file(str(self.root / 'split' / result['smt2'])))
        solver = z3.Solver()
        solver.add(artifact != z3.And(premises, z3.Not(conclusion)))
        self.assertEqual(solver.check(), z3.unsat)
        # A false antecedent must not turn its consequence into a premise or
        # an unconditional proof obligation.
        guarded = checker.prove('unreachable', value == 0,
                                z3.Implies(value > 0, z3.And(value < 0, value > 1)))
        self.assertTrue(guarded['ok'])

    def test_later_conjunction_counterexample_satisfies_complete_obligation(self):
        value = z3.Int('conjunction.invalid.value')
        premises = value >= 0
        conclusion = z3.And(value >= 0,
                            z3.Implies(value >= 1, z3.And(value >= 0, value >= 2)))
        checker = Checker(Source(SOURCE), REQUIREMENTS, self.root / 'invalid-split')
        result = checker.prove('later_clause', premises, conclusion)
        self.assertFalse(result['ok'])
        self.assertEqual([part['actual'] for part in result['components']],
                         ['unsat', 'unsat', 'sat'])
        original = z3.And(premises, z3.Not(conclusion))
        self.assertTrue(z3.is_true(checker.models['later_clause'].eval(original)))
        artifact = z3.And(*z3.parse_smt2_file(str(self.root / 'invalid-split' / result['smt2'])))
        solver = z3.Solver()
        solver.add(artifact != original)
        self.assertEqual(solver.check(), z3.unsat)

    def test_unknown_conjunction_component_cannot_hide_failure_or_prove_success(self):
        actual_solver = z3.Solver
        value = z3.Int('conjunction.unknown.value')
        for invalid_last in (False, True):
            created = []

            class OneUnknownSolver:
                def __init__(self):
                    self.index = len(created)
                    created.append(self)
                    self.delegate = actual_solver()

                def set(self, **kwargs):
                    self.delegate.set(**kwargs)

                def add(self, *args):
                    self.delegate.add(*args)

                def check(self):
                    return z3.unknown if self.index == 1 else self.delegate.check()

                def model(self):
                    return self.delegate.model()

                def reason_unknown(self):
                    return 'controlled timeout'

            with self.subTest(invalid_last=invalid_last):
                checker = Checker(Source(SOURCE), REQUIREMENTS)
                conclusion = z3.And(value >= 0, value >= 1,
                                    value > 2 if invalid_last else value >= 2)
                with patch('invariant.verification.checker.z3.Solver', OneUnknownSolver):
                    result = checker.prove('unknown_component', value >= 2, conclusion)
                self.assertFalse(result['ok'])
                self.assertEqual(result['actual'], 'sat' if invalid_last else 'unknown')
                self.assertEqual(len(result['components']), 3)
                self.assertEqual(result['components'][1]['actual'], 'unknown')
                if invalid_last:
                    self.assertTrue(z3.is_true(checker.models['unknown_component'].eval(
                        z3.And(value >= 2, z3.Not(conclusion)))))
                else:
                    self.assertEqual(result['reason'], 'controlled timeout')

    def test_component_deduplication_preserves_indices_and_counterexample(self):
        value = z3.Int('dedup.value')
        impossible = z3.And(value >= 2, value < 1)
        possible = value == 3
        queries = [z3.BoolVal(False), impossible, impossible, possible, possible]
        checker = Checker(Source(SOURCE), REQUIREMENTS)
        with patch('invariant.verification.checker.z3.Solver', wraps=z3.Solver) as solver:
            result = checker.solve('dedup', z3.Or(*queries), components=queries)
        self.assertEqual(solver.call_count, 2)
        self.assertEqual([part['index'] for part in result['components']], list(range(5)))
        self.assertEqual([part['actual'] for part in result['components']],
                         ['unsat', 'unsat', 'unsat', 'sat', 'sat'])
        self.assertFalse(result['ok'])
        self.assertTrue(z3.is_true(checker.models['dedup'].eval(z3.Or(*queries))))

    def test_duplicate_unknown_components_remain_unknown(self):
        value = z3.Int('dedup.unknown.value')
        query = value > 0
        checker = Checker(Source(SOURCE), REQUIREMENTS)
        with patch('invariant.verification.checker.z3.Solver') as solver:
            solver.return_value.check.return_value = z3.unknown
            solver.return_value.reason_unknown.return_value = 'controlled timeout'
            result = checker.solve('dedup_unknown', query, components=[query] * 3)
        self.assertEqual(solver.call_count, 1)
        self.assertFalse(result['ok'])
        self.assertEqual(result['actual'], 'unknown')
        self.assertEqual(result['reason'], 'controlled timeout')
        self.assertEqual(result['components'], [
            {'index': index, 'actual': 'unknown', 'reason': 'controlled timeout'}
            for index in range(3)
        ])

    def test_later_conjunction_contract_mutation_replays(self):
        source = SOURCE + '''
def pair(value: int) -> tuple[int, int]:
    return value, value + 1
'''
        requirements = copy.deepcopy(REQUIREMENTS)
        requirements['contracts']['pair'] = {
            'ensures': ['result[0] == value and result[1] == value + 1'],
        }
        requirements['mutations'] = [{
            'name': 'break_second_result', 'function': 'pair',
            'target': 'value + 1', 'replacement': 'value',
            'detects': ['contract.pair.0'],
        }]
        report = self.verify(source, requirements, output=True)
        self.assertTrue(report['ok'], report)
        mutation = report['mutations'][0]
        self.assertTrue(mutation['replay']['ok'])
        failed = next(row for row in mutation['obligations'] if row['name'] == 'contract.pair.0')
        self.assertEqual(failed['components'][-1]['actual'], 'sat')
        self.assertTrue(all(part['actual'] == 'unsat' for part in failed['components'][:-1]))

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


    def test_required_witness_and_mutation_inventory_and_concrete_replay(self):
        self.assertTrue(self.verify(output=True)['ok'])
        report = verify(self.root / 'machine.py', self.root / 'requirements.inv',
                        required_witnesses=['retry_possible'], required_mutations=['skip_retry'])
        self.assertTrue(report['mutations'][0]['replay']['ok'])
        for argument in ('required_witnesses', 'required_mutations'):
            with self.assertRaisesRegex(VerificationError, 'Missing required'):
                verify(self.root / 'machine.py', self.root / 'requirements.inv', **{argument: ['missing']})


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
        ]}
        report = self.verify(source, requirements)
        self.assertTrue(report['ok'], [row for row in report['obligations'] if not row['ok']])

        namespace = {}
        exec(source, namespace)
        for values, value in (((), 1), ((1, 'a'), 'b'), (('x',), 2)):
            self.assertEqual(namespace['append'](values, value), values + (value,))


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


    def test_collection_proof_features_are_rejected(self):
        for name in ('forall_range', 'exists_range', 'sum_range'):
            with self.subTest(name=name):
                requirements = copy.deepcopy(REQUIREMENTS)
                requirements['properties'].append({
                    'name': 'removed_collection_claim',
                    'assert': name + '(i, 0, 3, i == 0)',
                })
                with self.assertRaisesRegex(VerificationError, 'Only source-defined'):
                    self.verify(requirements=requirements)
        with self.assertRaisesRegex(VerificationError, 'Collection slices'):
            Source(SOURCE + "\ndef remove_first(values: tuple[int, ...]) -> tuple[int, ...]:\n    return values[1:]\n")
        with self.assertRaisesRegex(VerificationError, 'Unsupported statement: For'):
            Source(SOURCE + "\ndef scan(values: tuple[int, ...]) -> int:\n    total = 0\n    for value in values:\n        total = total + value\n    return total\n")
        requirements = copy.deepcopy(REQUIREMENTS)
        requirements['loops'] = []
        with self.assertRaisesRegex(VerificationError, 'unknown requirements fields'):
            self.verify(requirements=requirements)


if __name__ == "__main__":
    unittest.main()
