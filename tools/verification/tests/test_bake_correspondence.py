"""Differential regression of the shared source model against production Python."""
from dataclasses import asdict, fields
from importlib.resources import files
from itertools import product
import json
import sys
from types import ModuleType
from typing import get_args
import unittest

import z3
from color_tools.invariant.verification.model import Record, Source, Type
from color_tools.invariant.verification.symbolic import Interpreter, Label, equal, label_sort


SOURCE = files(__package__).joinpath('bake_image.py').read_text()
REQUIREMENTS = json.loads(files(__package__).joinpath('bake_image.inv').read_text())


def values(record):
    domains = [(False, True) if field.type is bool else (0, 1, 2) if field.type is int else get_args(field.type) for field in fields(record)]
    return tuple(record(*items) for items in product(*domains))


def concrete(value):
    if isinstance(value, tuple):
        return tuple(concrete(item) for item in value)
    if hasattr(value, '__dataclass_fields__'):
        return Record(type(value).__name__, asdict(value))
    return value


def substitutions(symbolic, native):
    result = []
    for name, value in asdict(native).items():
        expression = symbolic.fields[name]
        if isinstance(expression, Label):
            result.append((expression.value, label_sort(expression.alternatives)[1][expression.alternatives.index(value)]))
        else:
            result.append((expression, z3.BoolVal(value) if type(value) is bool else z3.IntVal(value)))
    return tuple(result)


class BakeCorrespondenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = Source(SOURCE)
        cls.native = ModuleType('_shared_bake_correspondence')
        sys.modules[cls.native.__name__] = cls.native
        exec(compile(SOURCE, '<bake correspondence>', 'exec'), cls.native.__dict__)

    @classmethod
    def tearDownClass(cls):
        sys.modules.pop(cls.native.__name__, None)

    def test_native_and_symbolic_transitions_match_boundary_observations(self):
        interpreter = Interpreter(self.source, {})
        state = interpreter.symbol('before', Type('record', ('State',)))
        event = interpreter.symbol('incoming', Type('record', ('Event',)))
        unary = {name: z3.simplify(interpreter.call(name, [state], {}))
                 for name in ('settled', 'recovery_required')}
        transition = interpreter.call('step', [state, event], {})
        self.assertTrue(z3.is_true(z3.simplify(equal(interpreter.call('new', [], {}), concrete(self.native.new())))))
        # All finite fields and zero/current/new observation generations. The
        # inductive proof covers unbounded generation values separately.
        states, events = values(self.native.State), values(self.native.Event)
        checked = 0
        for before in states:
            before_values = substitutions(state, before)
            for name, expression in unary.items():
                result = z3.simplify(z3.substitute(expression, *before_values))
                self.assertEqual(result, z3.BoolVal(getattr(self.native, name)(before)))
            for incoming in events:
                inputs = before_values + substitutions(event, incoming)
                result = equal(transition, concrete(self.native.step(before, incoming)))
                self.assertTrue(z3.is_true(z3.simplify(z3.substitute(result, *inputs))), (before, incoming))
                checked += 1
        self.assertEqual(checked, len(states) * len(events))

    def test_native_authority_claims_have_required_mutation_controls(self):
        names = {item['name'] for item in REQUIREMENTS['properties']}
        self.assertIn('dirty_or_unknown_observation_preserves_native_data', names)
        self.assertIn('completion_requires_current_invalidation_receipt', names)
        self.assertIn('foreign_observation_cannot_settle', names)
        self.assertNotIn('only_verified_readback_clears_recovery_obligation', names)
        self.assertEqual(len(REQUIREMENTS['mutations']), 3)
        for mutation in REQUIREMENTS['mutations']:
            self.assertTrue(mutation['detects'])
            self.assertTrue(all(name.removeprefix('property.') in names for name in mutation['detects']))

    def test_each_mutation_changes_its_native_boundary_counterexample(self):
        cases = {
            'dirty_image_is_invalidated': (dict(phase='observing', generation=1),
                dict(kind='observe', generation=1, managed=True, dirty=True, changed=True)),
            'invalidation_ignores_receipt': (dict(phase='invalidating', generation=1, pending=True, managed=True),
                dict(kind='invalidated', generation=1)),
            'foreign_generation_is_accepted': (dict(phase='observing', generation=2),
                dict(kind='observe', generation=1, managed=True, changed=True)),
        }
        for mutation in REQUIREMENTS['mutations']:
            with self.subTest(mutation=mutation['name']):
                target, replacement = mutation['target'], mutation['replacement']
                self.assertEqual(SOURCE.count(target), 1)
                mutated = ModuleType('_bake_mutation')
                sys.modules[mutated.__name__] = mutated
                try:
                    exec(compile(SOURCE.replace(target, replacement), '<bake mutation>', 'exec'), mutated.__dict__)
                    before, incoming = cases[mutation['name']]
                    expected = concrete(self.native.step(self.native.State(**before), self.native.Event(**incoming)))
                    actual = concrete(mutated.step(mutated.State(**before), mutated.Event(**incoming)))
                    self.assertNotEqual(actual, expected)
                finally:
                    sys.modules.pop(mutated.__name__, None)
