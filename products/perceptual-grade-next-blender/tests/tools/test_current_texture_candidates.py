"""Current-baseline isolation and smaller-only sensitivity contract."""
from dataclasses import replace
import unittest
from unittest.mock import patch

import numpy as np

from color_tools.kernel import prepare
from color_tools.kernel.boundary import prepare_boundary
from color_tools.kernel.layouts import FIELD_CELLS, LAYOUT_SCHEMA
from tools.perceptual_grade.reports import current_texture_candidates as candidates
from tools.perceptual_grade.reports import full_cases


class CurrentTextureCandidatesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _, linear, tone, color = next(row for row in full_cases.grades() if row[0] == 'all_active')
        base = prepare(linear, tone, color=color, full_fields=True)
        cls.base = replace(base, boundary=prepare_boundary(base.fl, base.aw, base.gamma))

    def test_baseline_is_current_and_selection_only_reduces(self):
        layout = candidates.baseline_layout(self.base)
        self.assertEqual({key: value for key, value in layout.items() if key != 'Output boundary'},
                         {'Tone':256, 'Color coefficients':8192, 'Web parameters':4096,
                          'Web toes':1536, 'Adaptance parameters':3072})
        self.assertEqual((layout['Output boundary']['width'], layout['Output boundary']['height']), (513,321))
        specs = candidates.selection()
        self.assertEqual(len(specs), 9)
        self.assertEqual(len({s['id'] for s in specs}), 9)
        for spec in specs:
            candidates.validate_spec(spec)
            if spec['role'] != 'Output boundary':
                self.assertLess(spec['cells'], layout[spec['role']])
        self.assertEqual([s['cells'] for s in specs if s['role']=='Web toes'], [1280,1024,768])

    def test_invalid_or_same_size_requests_are_rejected(self):
        for spec in ({'role':'Tone','cells':256}, {'role':'Tone','cells':True},
                     {'role':'Color coefficients','cells':32768},
                     {'role':'Web parameters','cells':1024},
                     {'role':'Adaptance interior parameters','cells':2048},
                     {'role':'Output boundary','low_cells':128,'high_cells':192,'hue_cells':512}):
            with self.subTest(spec=spec), self.assertRaises(ValueError):
                candidates.candidate(self.base, spec)
        with self.assertRaises(ValueError):
            candidates.selection(['Color coefficients/16384'])
        with self.assertRaises(ValueError):
            candidates.selection(['Tone/128','Tone/128'])

    def test_each_color_reduction_preserves_all_unrelated_payloads(self):
        selected = ['Color coefficients/4096','Web parameters/2048','Web toes/1280','Adaptance parameters/2048']
        for spec in candidates.selection(selected):
            with self.subTest(role=spec['role']):
                changed, metadata = candidates.candidate(self.base, spec)
                attr = candidates.ATTRIBUTES[spec['role']]
                table = getattr(changed.color, attr)
                self.assertEqual(table.schema, LAYOUT_SCHEMA)
                self.assertEqual(table.cells, spec['cells'])
                self.assertEqual(metadata['baseline']['cells'], FIELD_CELLS[spec['role']])
                self.assertGreater(metadata['saved_bytes'], 0)
                self.assertEqual(metadata['scalar_audit'], 'not_run')
                self.assertIsNone(metadata['field_passed'])
                self.assertIs(changed.tone, self.base.tone)
                self.assertIs(changed.boundary, self.base.boundary)
                for other in candidates.ATTRIBUTES.values():
                    if other != attr:
                        self.assertIs(getattr(changed.color, other), getattr(self.base.color, other))
                with self.assertRaises(ValueError):
                    candidates.candidate(changed, spec)

    def test_tone_actual_packing_and_isolation(self):
        changed, metadata = candidates.candidate(self.base, candidates.selection(['Tone/128'])[0])
        self.assertIs(changed.color, self.base.color)
        self.assertIs(changed.boundary, self.base.boundary)
        self.assertEqual(changed.table.cells, 128)
        self.assertEqual(metadata['shape'], [1,129,4])
        self.assertEqual(metadata['bytes'], 129*16)
        self.assertEqual(metadata['baseline']['bytes'], 8192)
        self.assertEqual(metadata['scalar_audit'], 'complete')

    def test_boundary_cache_is_caller_owned_and_only_boundary_changes(self):
        spec = candidates.selection(['Output boundary/129x81'])[0]
        replacement = replace(self.base.boundary, pixels=np.zeros((81,129,4),np.float32),
                              seed_low_cells=32, seed_high_cells=48, seed_hue_cells=128)
        cache = {}
        with patch.object(candidates, 'generate_boundary', return_value=replacement) as generate:
            first, metadata = candidates.candidate(self.base, spec, cache)
            second, repeated = candidates.candidate(self.base, spec, cache)
        self.assertEqual(generate.call_count, 1)
        self.assertIs(first.boundary, second.boundary)
        self.assertIs(first.color, self.base.color)
        self.assertIs(first.tone, self.base.tone)
        self.assertEqual(metadata, repeated)
        self.assertEqual(metadata['bytes'], 81*129*16)
        self.assertIs(generate.call_args.kwargs['enforce_accuracy'], False)

    def test_collect_evaluators_does_not_generate_color_payloads(self):
        with patch.object(candidates, '_generate_field', side_effect=AssertionError('No generation')):
            specs = candidates.collect_evaluators(self.base)
        self.assertEqual(set(specs), set(candidates.ATTRIBUTES))
        for name, (args, kwargs) in specs.items():
            self.assertEqual(args[0], name)
            self.assertTrue(callable(args[1]))
            self.assertNotIn('cells', kwargs)


if __name__ == '__main__':
    unittest.main()
