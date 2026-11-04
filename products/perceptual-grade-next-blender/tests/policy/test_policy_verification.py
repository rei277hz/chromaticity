"""Assumption-aware verification of the product's helper lifecycle policy."""

import ast
import copy
from importlib.resources import files
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import z3

from color_tools.invariant.verification.checker import Checker, verify
from color_tools.invariant.verification.model import Source, Type
from color_tools.invariant.verification.symbolic import Interpreter, boolean, integer


SOURCE = '''from dataclasses import dataclass
from typing import Literal, Optional

@dataclass(frozen=True)
class State:
    value: int

@dataclass(frozen=True)
class Event:
    kind: Literal["change", "keep"]

@dataclass(frozen=True)
class Effects:
    changed: bool = False

def new() -> State:
    return State(0)

def step(state: State, event: Event) -> tuple[State, Effects]:
    return state, Effects()

def divide(n: int) -> int:
    return 10 // n

def present(value: Optional[int]) -> int:
    return value + 1

def precondition(n: int) -> int:
    return n

def left() -> int:
    return 10

def right() -> int:
    return 20

def select(flag: bool) -> int:
    if flag:
        return left()
    return right()

def conditional(flag: bool) -> int:
    return left() if flag else right()

def nested(flag: bool) -> int:
    return conditional(flag)

def truth() -> bool:
    return True

def both(flag: bool) -> bool:
    return flag and truth()

def either(flag: bool) -> bool:
    return flag or truth()
'''

REQUIREMENTS = {
    "version": 1,
    "state": "State",
    "event": "Event",
    "initializers": ["new"],
    "step": "step",
    "invariants": {"nonnegative": "state.value >= 0"},
    "contracts": {
        "divide": {"requires": ["n != 0"]},
        "present": {"requires": ["value is not None"]},
    },
}


class RecordingInterpreter(Interpreter):
    def __init__(self, source, requirements):
        super().__init__(source, requirements)
        self.expanded = []

    def _call(self, name, *args, **kwargs):
        self.expanded.append(name)
        return super()._call(name, *args, **kwargs)


class PolicyVerificationTests(unittest.TestCase):
    def verify_claims(self, *, properties=(), witnesses=(), contracts=None):
        requirements = copy.deepcopy(REQUIREMENTS)
        requirements.update(properties=list(properties), witnesses=list(witnesses))
        if contracts:
            requirements["contracts"].update(contracts)
        return Checker(Source(SOURCE), requirements).run()

    def assert_all_pass(self, checks):
        self.assertEqual([(item["name"], item["actual"]) for item in checks
                          if not item["ok"]], [])

    def assert_failed(self, checks, name, actual="sat"):
        item = next(item for item in checks if item["name"] == name)
        self.assertFalse(item["ok"], item)
        self.assertEqual(item["actual"], actual)

    def assert_under(self, guard, condition):
        solver = z3.Solver()
        solver.set(timeout=5000)
        solver.add(guard, z3.Not(boolean(condition)))
        self.assertEqual(solver.check(), z3.unsat)

    def test_helper_claims_prune_unrelated_event_bodies(self):
        resources = files("tests.perceptual_grade_blender") / "helper_inputs"
        source = Source((resources / "source.py").read_text())
        requirements = json.loads((resources / "requirements.inv").read_text())
        selected = {
            "terminal_poll_never_touches_transport",
            "stale_generation_is_ignored",
            "stale_stage_timeout_has_no_effects",
        }
        checker = Checker(source, requirements)
        unguarded = RecordingInterpreter(source, requirements)
        state = unguarded.symbol("baseline.state", Type("record", ("State",)))
        event = unguarded.symbol("baseline.event", Type("record", ("Event",)))
        unguarded.call("step", [state, event], {})
        baseline_safety = len(unguarded.safety)
        self.assertGreater(baseline_safety, 0)
        for claim in requirements["properties"]:
            if claim["name"] not in selected:
                continue
            with self.subTest(claim=claim["name"]):
                interpreter = RecordingInterpreter(source, requirements)
                env = {name: interpreter.symbol(
                    name, source.annotation(ast.parse(typ, mode="eval").body))
                    for name, typ in claim["variables"].items()}
                premises = []
                for expression in claim["assume"]:
                    premises.append(boolean(interpreter.expression(
                        expression, env, z3.And(*premises))))
                guard = z3.And(*interpreter.domains, *premises)
                interpreter.safety.clear()
                for name, expression in claim["lets"].items():
                    env[name] = interpreter.expression(expression, env, guard)
                conclusion = interpreter.expression(claim["assert"], env, guard)
                safety = checker.safety(claim["name"], interpreter, guard)
                self.assertTrue(safety["ok"], safety)
                # These claims previously generated about 12,820 components
                # each. Require substantial structural reduction, not a clock
                # threshold that depends on the worker running this test.
                self.assertLess(len(safety["components"]), 12820 // 4)
                self.assertLess(len(interpreter.safety), baseline_safety // 2)
                self.assertTrue(set(interpreter.expanded) <= {"step"},
                                interpreter.expanded)
                self.assert_under(guard, conclusion)

    def test_reachable_division_index_and_optional_errors_are_not_pruned(self):
        claims = [
            {"name": "divide", "variables": {"n": "int"},
             "assume": ["n == 0"], "lets": {"out": "divide(n)"},
             "assert": "True"},
            {"name": "index", "variables": {"n": "int"},
             "assume": ["n == 2"], "lets": {"out": "(3, 4)[n]"},
             "assert": "True"},
            {"name": "optional", "variables": {"value": "Optional[int]"},
             "assume": ["value is None"], "lets": {"out": "present(value)"},
             "assert": "True"},
        ]
        checks = self.verify_claims(properties=claims)
        for claim in claims:
            self.assert_failed(checks, "defined.property." + claim["name"])

    def test_later_assumption_cannot_make_an_unsafe_earlier_assumption_safe(self):
        claim = {"name": "ordered", "variables": {"n": "int"},
                 "assume": ["divide(n) > 0", "n != 0"], "assert": "True"}
        self.assert_failed(self.verify_claims(properties=[claim]),
                           "defined.premise.property.ordered")
        claim["assume"].reverse()
        self.assert_all_pass(self.verify_claims(properties=[claim]))

    def test_later_precondition_cannot_hide_undefined_evaluation(self):
        contract = {"requires": ["divide(n) > 0", "n != 0"]}
        checks = self.verify_claims(contracts={"precondition": contract})
        self.assert_failed(checks, "defined.premise.precondition")
        contract["requires"].reverse()
        self.assert_all_pass(self.verify_claims(contracts={"precondition": contract}))

    def test_assumption_selecting_only_raise_or_fallthrough_keeps_safety_failure(self):
        for body in ('raise ValueError("failed")', 'pass'):
            with self.subTest(body=body):
                source = SOURCE + ('\ndef partial(flag: bool) -> int:\n'
                                   '    if flag:\n        return 1\n'
                                   '    ' + body + '\n')
                requirements = copy.deepcopy(REQUIREMENTS)
                requirements["properties"] = [{
                    "name": "partial", "variables": {"flag": "bool"},
                    "assume": ["not flag"], "lets": {"out": "partial(flag)"},
                    "assert": "True",
                }]
                checks = Checker(Source(source), requirements).run()
                self.assert_failed(checks, "defined.property.partial")

    def test_contradictory_property_and_witness_premises_fail(self):
        claim = {"name": "impossible", "variables": {"n": "int"},
                 "assume": ["n == 0", "n != 0"],
                 "lets": {"out": "divide(n)"}, "assert": "True"}
        for kind in ("properties", "witnesses"):
            with self.subTest(kind=kind):
                checks = self.verify_claims(**{kind: [claim]})
                prefix = "property" if kind == "properties" else "witness"
                self.assert_failed(checks, f"premise.{prefix}.impossible", "unsat")

    def test_same_call_under_opposite_guards_does_not_reuse_specialized_result(self):
        interpreter = RecordingInterpreter(Source(SOURCE), REQUIREMENTS)
        flag = interpreter.symbol("flag", Type("bool"))
        yes = interpreter.call("select", [flag], {}, flag)
        no = interpreter.call("select", [flag], {}, z3.Not(flag))
        both = interpreter.call("select", [flag], {})
        self.assert_under(flag, integer(yes) == 10)
        self.assert_under(z3.Not(flag), integer(no) == 20)
        self.assert_under(flag, integer(both) == 10)
        self.assert_under(z3.Not(flag), integer(both) == 20)
        self.assertIn("left", interpreter.expanded)
        self.assertIn("right", interpreter.expanded)

    def test_separate_claims_do_not_leak_assumptions_or_assume_their_assertions(self):
        claims = [
            {"name": "yes", "variables": {"flag": "bool"},
             "assume": ["flag"], "assert": "select(flag) == 10"},
            {"name": "no", "variables": {"flag": "bool"},
             "assume": ["not flag"], "assert": "select(flag) == 20"},
            {"name": "unrestricted", "variables": {"flag": "bool"},
             "assert": "select(flag) == 10"},
        ]
        checks = self.verify_claims(properties=claims)
        self.assert_failed(checks, "property.unrestricted")
        self.assertTrue(all(item["ok"] for item in checks
                            if item["name"] != "property.unrestricted"))

    def test_checker_uses_premises_for_lets_assertions_and_witnesses(self):
        for kind in ("properties", "witnesses"):
            for use_let in (False, True):
                with self.subTest(kind=kind, use_let=use_let):
                    base = {"variables": {"flag": "bool"}}
                    if use_let:
                        base["lets"] = {"out": "select(flag)"}
                    expression = "out" if use_let else "select(flag)"
                    claims = [
                        {**base, "name": "all", "assert": f"{expression} in (10, 20)"},
                        {**base, "name": "yes", "assume": ["flag"],
                         "assert": f"{expression} == 10"},
                        {**base, "name": "no", "assume": ["not flag"],
                         "assert": f"{expression} == 20"},
                    ]
                    checks = self.verify_claims(**{kind: claims})
                    self.assert_all_pass(checks)
                    prefix = "property" if kind == "properties" else "witness"
                    counts = {item["name"]: len(item.get("components", []))
                              for item in checks}
                    baseline = counts[f"defined.{prefix}.all"]
                    for name in ("yes", "no"):
                        self.assertLess(counts[f"defined.{prefix}.{name}"], baseline)

    def test_conditionals_short_circuit_and_nested_calls_skip_only_dead_arms(self):
        for function, positive, expected, skipped in (
            ("conditional", True, 10, "right"),
            ("conditional", False, 20, "left"),
            ("nested", True, 10, "right"),
            ("both", False, False, "truth"),
            ("either", True, True, "truth"),
        ):
            with self.subTest(function=function, positive=positive):
                interpreter = RecordingInterpreter(Source(SOURCE), REQUIREMENTS)
                flag = interpreter.symbol("flag", Type("bool"))
                guard = flag if positive else z3.Not(flag)
                result = interpreter.call(function, [flag], {}, guard)
                self.assertNotIn(skipped, interpreter.expanded)
                value = boolean(result) if type(expected) is bool else integer(result)
                self.assert_under(guard, value == expected)

    def test_inconclusive_or_interrupted_pruning_keeps_the_branch(self):
        for interrupted in (False, True):
            with self.subTest(interrupted=interrupted):
                interpreter = RecordingInterpreter(Source(SOURCE), REQUIREMENTS)
                flag = interpreter.symbol("flag", Type("bool"))
                kwargs = ({"side_effect": z3.Z3Exception("canceled")}
                          if interrupted else
                          {"return_value": z3.Tactic("skip")(z3.BoolVal(True))})
                with patch.object(interpreter, "_reachability_simplifier", **kwargs):
                    self.assertFalse(interpreter.is_unreachable(flag))
                    result = interpreter.call("select", [flag], {})
                self.assertIn("left", interpreter.expanded)
                self.assertIn("right", interpreter.expanded)
                self.assert_under(flag, integer(result) == 10)
                self.assert_under(z3.Not(flag), integer(result) == 20)

    def test_impossible_premise_cannot_leave_a_success_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, requirements, output = root / "policy.py", root / "policy.inv", root / "proof"
            source.write_text(SOURCE)
            data = copy.deepcopy(REQUIREMENTS)
            requirements.write_text(json.dumps(data))
            self.assertTrue(verify(source, requirements, output)["ok"])
            self.assertTrue((output / "receipt.json").exists())
            data["properties"] = [{"name": "impossible", "assume": ["False"],
                                   "assert": "True"}]
            requirements.write_text(json.dumps(data))
            self.assertFalse(verify(source, requirements, output)["ok"])
            self.assertFalse((output / "receipt.json").exists())
