"""Execution policies preserve the recorded transition scenarios."""
import dataclasses
from importlib import import_module
from importlib.resources import files
import json
import unittest


class ExecutionPolicyTests(unittest.TestCase):
    def test_baseline_transitions(self):
        root = files(__package__)
        fixture = json.loads((root / 'execution_baseline.json').read_text())
        machines = {name: import_module('color_tools.blender_runtime.policies.' + name)
                    for name in ('attempt', 'gpu', 'retry', 'startup')}
        for case in fixture['cases']:
            with self.subTest(machine=case['machine'], state=case['state'], event=case['event']):
                machine = machines[case['machine']]
                after, effects = machine.step(machine.State(**case['state']), machine.Event(**case['event']))
                self.assertEqual(dataclasses.asdict(after), case['after'])
                self.assertEqual(dataclasses.asdict(effects), case['effects'])


if __name__ == '__main__':
    unittest.main()
