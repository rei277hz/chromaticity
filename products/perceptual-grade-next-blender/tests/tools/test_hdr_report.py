"""Coverage, checkpoint and candidate-image accounting for the HDR runner."""
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import numpy as np

from tools.perceptual_grade.reports import hdr_report


class HdrReportTests(unittest.TestCase):
    def test_sweep_contains_every_halving_and_combined_web(self):
        specs = hdr_report.selection()
        self.assertEqual(len(specs), 37)
        self.assertNotIn('Adaptance interior parameters', hdr_report.ROLES)
        self.assertEqual(len({row['id'] for row in specs}), len(specs))
        self.assertEqual([r['cells'] for r in specs if r['role']=='Tone'], [256,128,64,32])
        self.assertEqual([r['cells'] for r in specs if r['role']=='Web parameters'], [16384,8192,4096,2048])
        self.assertEqual([r['cells'] for r in specs if r['role']=='Web toes'],
                         [262144,131072,65536,32768,16384,8192,4096,2048,1792,1536,1280,1024,768,512,256])
        self.assertEqual([r['id'] for r in hdr_report.selection(candidate_ids=['Combined Web/4096+32768'])],
                         ['Combined Web/4096+32768'])
        self.assertEqual([r['id'] for r in hdr_report.selection(candidate_ids=['Combined Color/16384+8192'])],
                         ['Combined Color/16384+8192'])
        with self.assertRaises(ValueError):
            hdr_report.selection(candidate_ids=['Tone/7'])

    def test_field_candidate_requires_explicit_cell_sizes_and_changes_only_two_fields(self):
        first, second, other = object(), object(), object()

        class PreparedColor:
            def __init__(self, tables):
                self.tables = tables
                self.settings = object()

        class Prepared:
            def __init__(self, color):
                self.color = color

        base = Prepared(PreparedColor((first, second, other)))
        color_result, compact_result = object(), object()

        def candidate(prepared, role, cells):
            self.assertIn((role, cells), (('Color coefficients', 16384), ('Adaptance parameters', 8192)))
            tables = list(prepared.color.tables)
            tables[0 if role == 'Color coefficients' else 1] = color_result if role == 'Color coefficients' else compact_result
            return Prepared(PreparedColor(tuple(tables))), dict(name=role, cells=cells)

        spec = next(row for row in hdr_report.selection() if row['role'] == 'Combined Color')
        with patch.object(hdr_report, 'color_candidate', side_effect=candidate):
            combined, metadata = hdr_report._make_candidate(base, spec, {})
        self.assertIs(combined.color.tables[0], color_result)
        self.assertIs(combined.color.tables[1], compact_result)
        self.assertIs(combined.color.tables[2], other)
        self.assertEqual([row['name'] for row in metadata], list(hdr_report.HDR_FIELD_ROLES))
        self.assertEqual(hdr_report._required_roles(spec), hdr_report.HDR_FIELD_ROLES)

    def test_journal_retains_committed_rows_and_discards_interrupted_tail(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'candidates.jsonl'
            hdr_report._append_journal(path, {'candidate':'Tone/256', 'status':'measured'})
            committed = path.read_bytes()
            path.write_bytes(committed+b'{"candidate":"Tone/128"')
            self.assertEqual(hdr_report._load_journal(path), [{'candidate':'Tone/256', 'status':'measured'}])
            self.assertEqual(path.read_bytes(), committed)
            path.write_bytes(committed+b'broken\n')
            with self.assertRaises(ValueError):
                hdr_report._load_journal(path)

    def test_inventory_uses_payload_not_human_facing_image_name(self):
        data = np.arange(24, dtype=np.float32).reshape(2,3,4)
        class Pixels:
            def foreach_get(self, target):
                target[:] = data.ravel()
        class Image:
            name = 'Perceptual Grade coefficients'
            size = (3,2)
            pixels = Pixels()
        class Built:
            images = (Image(),)
        class Fixture:
            built = Built()
        with patch.object(hdr_report, '_payloads', return_value={'Web parameters':data, 'Web toes':None}):
            result = hdr_report._inventory(Fixture(), None)
        self.assertEqual(set(result), {'Web parameters'})
        self.assertTrue(result['Web parameters']['verified'])
        self.assertEqual(result['Web parameters']['bytes'], data.nbytes)

    def test_case_shards_are_stable_balanced_and_cover_the_corpus(self):
        names = [f'case-{index}' for index in range(17)]
        first = hdr_report.case_shards(names, 8)
        self.assertEqual(first, hdr_report.case_shards(names, 8))
        self.assertEqual(sorted(map(len, first)), [2, 2, 2, 2, 2, 2, 2, 3])
        assigned = [name for shard in first for name in shard]
        self.assertEqual(set(assigned), set(names))
        self.assertEqual(len(assigned), len(names))
        with self.assertRaises(ValueError):
            hdr_report.case_shards(names, 0)
        with self.assertRaises(ValueError):
            hdr_report.case_shards(names, 18)

    def test_report_axes_reject_empty_or_duplicate_values(self):
        for spaces, contexts in (((), ('shader',)), (('ACEScg', 'ACEScg'), ('shader',)),
                                 (('ACEScg',), ()), (('ACEScg',), ('shader', 'shader'))):
            with self.subTest(spaces=spaces, contexts=contexts), self.assertRaises(ValueError):
                hdr_report._validate_axes(spaces, contexts)

    def test_markdown_reports_independent_worsening_code_and_percentage_maxima(self):
        candidate = 'Web toes/1536'
        def row(code, percentage):
            return dict(candidate=candidate, status='measured', texture_metadata=[],
                hdr=dict(candidate=dict(error=dict(pixel_peak=dict(max=.5)),
                                        movement=dict(pixel_peak=dict(max=code)),
                                        worsening=dict(max=code, percentage=dict(max=percentage)))))
        report = dict(complete=True, scope='test', baselines=[],
            request=dict(candidates=[dict(id=candidate)]),
            rows=[row(.04, .02), row(.03, .15)])
        markdown = hdr_report._markdown(report)
        self.assertIn('Worsening max (% reference peak)', markdown)
        self.assertIn('| Web toes/1536 | 2 | 0.5 | 0.04 | 0.04 | 0.15 | 0 |', markdown)

    def test_baseline_override_regenerates_only_toe_without_dense_audit(self):
        @dataclass
        class Table:
            name: str
            cells: int
        @dataclass
        class Color:
            web_toe_table: object
            other: object
            @property
            def tables(self):
                return self.web_toe_table, self.other
        @dataclass
        class Grade:
            color: object
        old, other = Table('Web toes', 1024), Table('Web parameters', 32768)
        new = Table('Web toes', 524288)
        base = Grade(Color(old, other))
        def prepare_tables(color, *, builder):
            return Color(builder('Web toes'), builder('Web parameters'))
        with patch.object(hdr_report, '_prepare_tables', side_effect=prepare_tables), \
                patch.object(hdr_report, '_generate_field', return_value=new) as generate, \
                patch.object(hdr_report, 'color_candidate', side_effect=AssertionError('No dense audit')):
            result = hdr_report._with_baseline_toe(base, 524288)
            generate.assert_called_once_with('Web toes', cells=524288)
        self.assertIs(result.color.web_toe_table, new)
        self.assertIs(result.color.other, other)
        self.assertIs(base.color.web_toe_table, old)
        self.assertIs(hdr_report._with_baseline_toe(base, 1024), base)
        with self.assertRaises(ValueError):
            hdr_report._with_baseline_toe(base, 7)

    def _toe_admission_fixture(self):
        names = [row[0] for row in list(hdr_report.full_cases.grades()) + list(hdr_report.full_cases.ui_boundaries())]
        specs = [dict(id=f'Web toes/{cells}', role='Web toes', cells=cells)
                 for cells in hdr_report.TOE_ADMISSION_CELLS]
        request = dict(samples=1024, spaces=list(hdr_report.cases.SPACES),
                       contexts=['shader', 'compositor'], cases=names, case_universe=names,
                       baseline_toe_cells=524288, candidates=specs)
        baseline, rows = [], []
        for name in names:
            for space in request['spaces']:
                for context in request['contexts']:
                    axes = dict(case=name, space=space, context=context)
                    baseline.append(dict(**axes, status='measured', final_rgb_passed=True,
                                         image_receipts={'Web toes':{'verified':True}}))
                    for spec in specs:
                        cells = spec['cells']
                        worsening = .06 if cells < 1024 or cells == 1280 else .04
                        rows.append(dict(**axes, candidate=spec['id'], status='measured',
                            final_rgb_passed=True, containment_max_normalized=0.,
                            changed_validity_pixels=0, changed_saturation_pixels=0,
                            image_receipts={'Web toes':dict(verified=True, size=[cells+1, 1], bytes=(cells+1)*16)},
                            texture_metadata=[dict(name='Web toes', cells=cells, shape=[1, cells+1, 4],
                                bytes=(cells+1)*16, field_passed=False, audit_complete=True)],
                            hdr=dict(candidate=dict(worsening=dict(max=worsening),
                                                    movement=dict(pixel_peak=dict(max=.08))))))
        return dict(complete=True, sources_stable_during_run=True, request=request,
                    identity=dict(request=request), baselines=baseline, rows=rows)

    def test_toe_admission_selects_smallest_grid_despite_scalar_failures_and_nonmonotonic_errors(self):
        report = self._toe_admission_fixture()
        admission = hdr_report.toe_admission(report)
        self.assertEqual(admission['selected_cells'], 1024)
        self.assertTrue(admission['selection_grid_complete'])
        selected = next(row for row in admission['candidates'] if row['cells'] == 1024)
        self.assertEqual(selected['scalar_failure_rows'], len(report['baselines']))
        self.assertEqual(selected['max_worsening_codes'], .04)
        self.assertEqual(selected['max_movement_codes'], .08)
        self.assertFalse(next(row for row in admission['candidates'] if row['cells'] == 1280)['passed'])

    def test_toe_admission_rejects_missing_flags_failures_and_incorrect_native_layout(self):
        mutations = (
            ('final_rgb_passed', False), ('changed_validity_pixels', 1),
            ('changed_saturation_pixels', 1), ('containment_max_normalized', 9e-6),
            ('status', 'nonfinite'), ('status', 'not_sampled'),
            ('image_receipts', {'Web toes':dict(verified=True, size=[7, 1], bytes=112)}),
            ('hdr', dict(candidate=dict(worsening=dict(max=float('nan')),
                                       movement=dict(pixel_peak=dict(max=.08))))),
        )
        report = self._toe_admission_fixture()
        target = next(row for row in report['rows'] if row['candidate'] == 'Web toes/1024')
        for key, value in mutations:
            original = target[key]
            with self.subTest(key=key, value=value):
                target[key] = value
                admission = hdr_report.toe_admission(report)
                selected = next(row for row in admission['candidates'] if row['cells'] == 1024)
                self.assertFalse(selected['passed'])
                self.assertEqual(admission['selected_cells'], 1536)
            target[key] = original

    def test_toe_admission_requires_original_baseline_full_corpus_and_all_eight_sizes(self):
        report = self._toe_admission_fixture()
        report['request']['baseline_toe_cells'] = 32768
        self.assertIsNone(hdr_report.toe_admission(report)['selected_cells'])
        report['request']['baseline_toe_cells'] = 524288
        report['request']['candidates'] = report['request']['candidates'][1:]
        admission = hdr_report.toe_admission(report)
        self.assertFalse(admission['selection_grid_complete'])
        self.assertIsNone(admission['selected_cells'])
        report['request']['candidates'].insert(0, dict(id='Web toes/256', role='Web toes', cells=256))
        report['rows'].pop()
        result = next(row for row in hdr_report.toe_admission(report)['candidates'] if row['cells'] == 2048)
        self.assertFalse(result['passed'])
        report['request']['case_shard'] = dict(index=0, count=2)
        self.assertIsNone(hdr_report.toe_admission(report)['selected_cells'])

    def _field_admission_fixture(self):
        names = [row[0] for row in (*hdr_report.full_cases.grades(), *hdr_report.full_cases.ui_boundaries())]
        specs = [dict(id='Color coefficients/16384', role='Color coefficients', cells=16384),
                 dict(id='Adaptance parameters/8192', role='Adaptance parameters', cells=8192),
                 dict(id='Combined Color/16384+8192', role='Combined Color',
                      color_cells=16384, compact_adaptance_cells=8192)]
        request = dict(samples=1024, spaces=list(hdr_report.cases.SPACES),
            contexts=['shader', 'compositor'], cases=names, case_universe=names,
            baseline_color_cells=131072, baseline_compact_adaptance_cells=16384,
            graph_builder='persistent', candidates=specs)
        baselines, rows = [], []

        def image(role, cells):
            shape = hdr_report._field_shape(role, cells)
            digest = hashlib.sha256(f'{role}/{cells}'.encode()).hexdigest()
            return dict(verified=True, size=[shape[1], shape[0]], bytes=shape[0]*shape[1]*16,
                        pixels_sha256=digest)

        for case in names:
            for space in request['spaces']:
                for context in request['contexts']:
                    axes = dict(case=case, space=space, context=context)
                    baseline_images = {role:image(role, cells) for role, cells in (
                        ('Color coefficients', 131072), ('Adaptance parameters', 16384))}
                    baselines.append(dict(**axes, status='measured', final_rgb_passed=True,
                        containment_max_normalized=0., node_budget_passed=True,
                        image_receipts=baseline_images))
                    for spec in specs:
                        changed = hdr_report._required_roles(spec)
                        sizes = ({'Color coefficients': spec['color_cells'],
                                  'Adaptance parameters': spec['compact_adaptance_cells']}
                                 if spec['role'] == 'Combined Color' else {spec['role']:spec['cells']})
                        metadata = []
                        receipts = {}
                        for role in changed:
                            cells = sizes[role]
                            shape = hdr_report._field_shape(role, cells)
                            receipt = image(role, cells)
                            receipts[role] = receipt
                            metadata.append(dict(name=role, cells=cells, shape=shape,
                                bytes=shape[0]*shape[1]*16, pixels_sha256=receipt['pixels_sha256'],
                                field_passed=False, audit_complete=True, probes=196631,
                                max_conditioned_error=2e-5, max_pointwise_error=3e-5,
                                max_mapper_error=1e-7, relative_interpolation_error=0.,
                                absolute_interpolation_error=0., relative_interpolation_limit=0.,
                                absolute_interpolation_limit=0.,
                                witness=dict(conditioned=dict(coordinate=.25, channel=0,
                                    expected=1., actual=1.00002, error=2e-5))))
                        rows.append(dict(**axes, candidate=spec['id'], changed_roles=list(changed),
                            sampled_roles=list(changed), status='measured', final_rgb_passed=True,
                            containment_max_normalized=0., changed_validity_pixels=0,
                            changed_saturation_pixels=0, node_budget_passed=True,
                            texture_metadata=metadata, image_receipts=receipts,
                            hdr=dict(candidate=dict(worsening=dict(max=.04, percentage=dict(max=.02)),
                                                   movement=dict(pixel_peak=dict(max=.08))))))
        return dict(complete=True, sources_stable_during_run=True, request=request,
                    identity=dict(request=request), baselines=baselines, rows=rows)

    def test_field_admission_accepts_hdr_budget_with_scalar_failures_diagnostic(self):
        report = self._field_admission_fixture()
        admission = hdr_report.field_admission(report)
        self.assertEqual(admission['baseline_color_cells'], 131072)
        self.assertEqual(admission['baseline_compact_adaptance_cells'], 16384)
        self.assertEqual(admission['max_worsening_codes'], .05)
        self.assertEqual(len(admission['admitted_candidates']), 3)
        for row in admission['candidates']:
            self.assertTrue(row['passed'], row['rejection_reasons'])
            self.assertEqual(row['max_worsening_codes'], .04)
            self.assertGreater(row['scalar_failure_rows'], 0)
            self.assertEqual(row['new_node_budget_failure_rows'], 0)

    def test_field_admission_rejects_coverage_flags_payload_and_new_budget_failures(self):
        mutations = (
            ('coverage', lambda row: row.__setitem__('candidate', 'missing-candidate')),
            ('validity', lambda row: row.__setitem__('changed_validity_pixels', 1)),
            ('saturation', lambda row: row.__setitem__('changed_saturation_pixels', 1)),
            ('payload', lambda row: row['image_receipts']['Color coefficients'].__setitem__('size', [1, 1])),
            ('payload_hash', lambda row: row['image_receipts']['Color coefficients'].__setitem__('pixels_sha256', '0'*64)),
            ('overbudget', lambda row: row.__setitem__('node_budget_passed', False)),
            ('hdr_budget', lambda row: row['hdr']['candidate']['worsening'].__setitem__('max', .0500001)),
            ('incomplete_scalar', lambda row: row['texture_metadata'][0].__setitem__('audit_complete', False)),
        )
        for label, mutate in mutations:
            report = self._field_admission_fixture()
            target = next(row for row in report['rows'] if row['candidate'] == 'Combined Color/16384+8192')
            with self.subTest(label=label):
                mutate(target)
                result = hdr_report.field_admission(report)
                candidate = next(row for row in result['candidates']
                                 if row['id'] == 'Combined Color/16384+8192')
                self.assertFalse(candidate['passed'])
        report = self._field_admission_fixture()
        report['request'].pop('baseline_color_cells')
        result = hdr_report.field_admission(report)
        self.assertTrue(all(not row['passed'] for row in result['candidates']))
        report = self._field_admission_fixture()
        report['request']['graph_builder'] = 'specialized'
        self.assertEqual(hdr_report.field_admission(report)['admitted_candidates'], [])

    def test_field_admission_rejects_missing_nonfinite_or_malformed_scalar_diagnostics(self):
        mutations = []
        for key in ('max_conditioned_error', 'max_pointwise_error', 'max_mapper_error',
                    'relative_interpolation_error', 'absolute_interpolation_error'):
            mutations += [(f'missing_{key}', lambda field, key=key: field.pop(key)),
                          (f'nonfinite_{key}', lambda field, key=key: field.__setitem__(key, float('nan')))]
        mutations += [
            ('missing_probes', lambda field: field.pop('probes')),
            ('zero_probes', lambda field: field.__setitem__('probes', 0)),
            ('noninteger_probes', lambda field: field.__setitem__('probes', 1.5)),
            ('missing_witness', lambda field: field.pop('witness')),
            ('missing_conditioned_witness', lambda field: field.__setitem__('witness', {})),
            ('nonfinite_witness', lambda field: field['witness']['conditioned'].__setitem__('actual', float('inf'))),
            ('missing_absolute_witness', lambda field: field.__setitem__('absolute_interpolation_limit', 3e-6)),
            ('missing_field_status', lambda field: field.pop('field_passed')),
        ]
        for label, mutate in mutations:
            report = self._field_admission_fixture()
            target = next(row for row in report['rows'] if row['candidate'] == 'Combined Color/16384+8192')
            with self.subTest(label=label):
                mutate(target['texture_metadata'][0])
                candidate = next(row for row in hdr_report.field_admission(report)['candidates']
                                 if row['id'] == target['candidate'])
                self.assertFalse(candidate['passed'])
                self.assertIn('Complete scalar diagnostics are missing', candidate['rejection_reasons'])

    def test_field_admission_keeps_matching_inherited_node_budget_failures_separate(self):
        report = self._field_admission_fixture()
        baseline = report['baselines'][0]
        candidate = next(row for row in report['rows'] if row['case'] == baseline['case']
                         and row['space'] == baseline['space'] and row['context'] == baseline['context']
                         and row['candidate'] == 'Combined Color/16384+8192')
        baseline['node_budget_passed'] = False
        candidate['node_budget_passed'] = False
        result = hdr_report.field_admission(report)
        selected = next(row for row in result['candidates'] if row['id'] == candidate['candidate'])
        self.assertEqual(result['baseline_node_budget_failure_rows'], 1)
        self.assertEqual(selected['node_budget_failure_rows'], 1)
        self.assertEqual(selected['new_node_budget_failure_rows'], 0)
        self.assertTrue(selected['passed'])

    def _write_shard(self, directory, *, case, shard_index, source='source-a'):
        candidate = 'Tone/256'
        request = dict(samples=256, spaces=['ACEScg'], contexts=['shader'], cases=[case],
                       case_universe=['case-a', 'case-b'], case_shard=dict(index=shard_index, count=2),
                       baseline_color_cells=131072, baseline_compact_adaptance_cells=16384,
                       graph_builder='persistent',
                       candidates=[dict(id=candidate, role='Tone', cells=256)])
        identity = dict(sources={'tool': source}, display={'view': 'pinned'},
                        blender='Blender test', request=request)
        baseline = dict(case=case, space='ACEScg', context='shader', status='measured',
                        hdr=dict(current=dict(pixel_peak=dict(max=0.2))))
        row = dict(case=case, space='ACEScg', context='shader', candidate=candidate,
                   status='measured', texture_metadata=[],
                   hdr=dict(candidate=dict(error=dict(pixel_peak=dict(max=0.1)),
                                           movement=dict(pixel_peak=dict(max=0.1)),
                                           worsening=dict(max=0.0))))
        report = dict(schema=1, identity=identity, request=request, complete=True,
                      sources_stable_during_run=True, session_seconds=1.0,
                      scope='test scope', limitations=[], baselines=[baseline], rows=[row],
                      coverage=dict(expected_baselines=1, actual_baselines=1,
                                    expected_candidate_rows=1, actual_candidate_rows=1,
                                    status_counts=dict(measured=1, not_sampled=0,
                                                       generation_failed=0, render_failed=0,
                                                       nonfinite=0)))
        directory.mkdir()
        (directory/'report.json').write_text(json.dumps(report))
        (directory/'checkpoint.json').write_text(json.dumps(dict(
            schema=1, identity=identity, complete=True, baseline_rows=1, candidate_rows=1)))
        hdr_report._write_journal(directory/'baselines.jsonl', [baseline])
        hdr_report._write_journal(directory/'candidates.jsonl', [row])
        return report

    def test_merge_validates_shards_and_emits_resumable_combined_report(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shard_a, shard_b = root/'shard-a', root/'shard-b'
            self._write_shard(shard_a, case='case-a', shard_index=0)
            self._write_shard(shard_b, case='case-b', shard_index=1)
            output = root/'combined'
            report = hdr_report.merge_shards(output, [shard_a, shard_b])
            self.assertTrue(report['complete'])
            self.assertEqual(report['request']['cases'], ['case-a', 'case-b'])
            self.assertNotIn('case_shard', report['request'])
            self.assertEqual(report['request']['baseline_color_cells'], 131072)
            self.assertEqual(report['request']['baseline_compact_adaptance_cells'], 16384)
            self.assertEqual(report['request']['graph_builder'], 'persistent')
            self.assertEqual([row['case'] for row in report['baselines']], ['case-a', 'case-b'])
            self.assertEqual(report['coverage']['expected_candidate_rows'], 2)
            self.assertTrue((output/'report.md').exists())
            self.assertTrue(json.loads((output/'checkpoint.json').read_text())['complete'])
            self.assertEqual(len(hdr_report._load_journal(output/'candidates.jsonl')), 2)

    def test_merge_rejects_nonidentical_source_identities_and_duplicate_cases(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shard_a, shard_b = root/'shard-a', root/'shard-b'
            self._write_shard(shard_a, case='case-a', shard_index=0)
            self._write_shard(shard_b, case='case-b', shard_index=1, source='source-b')
            with self.assertRaisesRegex(ValueError, 'non-case identity'):
                hdr_report.merge_shards(root/'identity-failure', [shard_a, shard_b])

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shard_a, shard_b = root/'shard-a', root/'shard-b'
            self._write_shard(shard_a, case='case-a', shard_index=0)
            self._write_shard(shard_b, case='case-a', shard_index=1)
            with self.assertRaisesRegex(ValueError, 'overlaps'):
                hdr_report.merge_shards(root/'overlap', [shard_a, shard_b])


class HdrBackendTests(unittest.TestCase):
    def test_parameter_baseline_override_reuses_toe_and_other_fields(self):
        @dataclass
        class Table:
            name: str
            cells: int
        @dataclass
        class Color:
            web_table: object
            web_toe_table: object
            @property
            def tables(self):
                return self.web_table, self.web_toe_table
        @dataclass
        class Grade:
            color: object
        current, toe = Table('Web parameters', 4096), Table('Web toes', 1536)
        previous = Table('Web parameters', 32768)
        base = Grade(Color(current, toe))
        def prepare_tables(color, *, builder):
            return Color(builder('Web parameters'), builder('Web toes'))
        with patch.object(hdr_report, '_prepare_tables', side_effect=prepare_tables), \
                patch.object(hdr_report, '_generate_field', return_value=previous) as generate, \
                patch.object(hdr_report, 'color_candidate', side_effect=AssertionError('No dense audit')):
            result = hdr_report._with_baseline_parameters(base, 32768)
            generate.assert_called_once_with('Web parameters', cells=32768)
        self.assertIs(result.color.web_table, previous)
        self.assertIs(result.color.web_toe_table, toe)
        self.assertIs(base.color.web_table, current)
        self.assertIs(hdr_report._with_baseline_parameters(base, 4096), base)
        with self.assertRaises(ValueError):
            hdr_report._with_baseline_parameters(base, 7)

    def test_backend_and_threads_are_validated_before_native_work(self):
        for backend, threads in (('cuda', 1), ('cpu', 0), ('cpu', -1),
                                 ('cpu', True), ('software-gpu', 1.5)):
            with self.subTest(backend=backend, threads=threads), self.assertRaises(ValueError):
                hdr_report._backend_threads(backend, threads)
        self.assertIsNone(hdr_report._backend_threads('cpu', None))
        with patch('tools.perceptual_grade.reports.benchmark.available_threads', return_value=12):
            self.assertEqual(hdr_report._backend_threads('software-gpu', None), 12)

    def test_render_uses_requested_engine_device_and_records_native_settings(self):
        actual = dict(rgb=np.zeros((1, 3)), alpha=np.ones(1), valid=np.ones(1),
                      margin=np.ones(1), saturated=np.zeros(1), stats=dict(expanded_nodes=10),
                      seconds=.1, readback_seconds=.02)
        backend_info = dict(renderer='llvmpipe', software=True)
        for context, backend, engine, device in (
                ('shader', 'cpu', 'CYCLES', 'CPU'),
                ('shader', 'software-gpu', 'BLENDER_EEVEE', 'GPU'),
                ('compositor', 'software-gpu', 'CYCLES', 'GPU')):
            with self.subTest(context=context, backend=backend):
                render = SimpleNamespace(engine=engine, compositor_device=device,
                    compositor_precision='FULL', threads=12, threads_mode='FIXED')
                fixture = Mock(scene=SimpleNamespace(render=render))
                fixture.render.return_value = actual
                with patch('tools.perceptual_grade.reports.native.NativeFixture', return_value=fixture) as factory, \
                        patch.object(hdr_report, '_inventory', return_value={}), \
                        patch.object(hdr_report, 'assess', return_value=dict(passed=True)):
                    _, measured = hdr_report._render(None, np.zeros((1, 4)), context,
                        dict(to_scene=np.eye(3)), backend=backend, threads=12,
                        render_backend=backend_info if backend == 'software-gpu' else None)
                factory.assert_called_once_with(None, unittest.mock.ANY, context, engine=engine,
                    device=device, precision='FULL', threads=12, builder=None)
                self.assertEqual((measured['engine'], measured['compositor_device']), (engine, device))
                self.assertEqual((measured['native_threads'], measured['native_threads_mode']), (12, 'FIXED'))
                fixture.close.assert_called_once()

    def test_cli_forwards_explicit_baselines_and_launches_software_gpu(self):
        with patch.object(hdr_report, 'run') as run:
            hdr_report.main(['--output-dir', '/tmp/hdr-cpu', '--baseline-parameter-cells', '32768',
                             '--baseline-toe-cells', '1536', '--baseline-color-cells', '131072',
                             '--baseline-compact-adaptance-cells', '16384', '--graph-builder', 'persistent',
                             '--candidate-ids', 'Web parameters/4096'])
        self.assertEqual(run.call_args.kwargs['baseline_parameter_cells'], 32768)
        self.assertEqual(run.call_args.kwargs['baseline_toe_cells'], 1536)
        self.assertEqual(run.call_args.kwargs['baseline_color_cells'], 131072)
        self.assertEqual(run.call_args.kwargs['baseline_compact_adaptance_cells'], 16384)
        self.assertEqual(run.call_args.kwargs['graph_builder'], 'persistent')
        self.assertEqual(run.call_args.kwargs['backend'], 'cpu')
        with patch.object(hdr_report, '_launch_software_gpu') as launch, \
                patch.object(hdr_report, 'run') as run:
            arguments = ['--output-dir', '/tmp/hdr-gpu', '--backend', 'software-gpu',
                         '--threads', '12', '--xvfb', '/pinned/xvfb']
            hdr_report.main(arguments)
        run.assert_not_called()
        launch.assert_called_once_with(Path('/tmp/hdr-gpu'), arguments,
                                       xvfb=Path('/pinned/xvfb'), threads=12)

    def test_persistent_render_receives_the_real_builder(self):
        from color_tools.kernel.persistent import build_persistent
        actual = dict(rgb=np.zeros((1, 3)), alpha=np.ones(1), valid=np.ones(1),
                      margin=np.ones(1), saturated=np.zeros(1), stats=dict(expanded_nodes=1500),
                      seconds=.1, readback_seconds=.02)
        fixture = Mock(scene=SimpleNamespace(render=SimpleNamespace(engine='CYCLES', compositor_device='CPU',
            compositor_precision='FULL', threads=8, threads_mode='FIXED')))
        fixture.render.return_value = actual
        with patch('tools.perceptual_grade.reports.native.NativeFixture', return_value=fixture) as factory, \
                patch.object(hdr_report, '_inventory', return_value={}), \
                patch.object(hdr_report, 'assess', return_value=dict(passed=True)):
            _, result = hdr_report._render(None, np.zeros((1,4)), 'compositor',
                dict(to_scene=np.eye(3)), threads=8, graph_builder='persistent')
        self.assertIs(factory.call_args.kwargs['builder'], build_persistent)
        self.assertEqual(result['graph_builder'], 'persistent')
        self.assertFalse(result['node_budget_passed'])
        fixture.close.assert_called_once()

    def test_resume_identity_pins_both_color_baselines_and_graph_builder(self):
        names = [row[0] for row in (*hdr_report.full_cases.grades(), *hdr_report.full_cases.ui_boundaries())]
        options = dict(samples=256, spaces=['ACEScg'], contexts=['shader'], cases=['reset'],
            case_universe=['reset'], candidates=hdr_report.selection(candidate_ids=['Color coefficients/16384']),
            baseline_toe_cells=1536, baseline_parameter_cells=4096, baseline_color_cells=131072,
            baseline_compact_adaptance_cells=16384, backend='cpu', threads=8,
            case_shard=None, graph_builder='persistent')
        request = hdr_report._request(**options)
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            # Stop before preparation. The committed identity is a real resume
            # boundary, so altered baselines/builders must reject before render.
            with patch.object(hdr_report, 'identities', return_value={'test':'source'}), \
                    patch.object(hdr_report, 'HDRDisplay', return_value=SimpleNamespace(metadata={'view':'test'})), \
                    patch.object(hdr_report, 'prepare', side_effect=RuntimeError('stop before native work')):
                run_options = dict(samples=256, spaces=['ACEScg'], contexts=['shader'], selected=['reset'],
                    candidate_ids=['Color coefficients/16384'], baseline_toe_cells=1536,
                    baseline_parameter_cells=4096, baseline_color_cells=131072,
                    baseline_compact_adaptance_cells=16384, threads=8, graph_builder='persistent')
                with self.assertRaisesRegex(RuntimeError, 'stop before native work'):
                    hdr_report.run(directory, **run_options)
                identity = json.loads((directory/'checkpoint.json').read_text())['identity']
                self.assertEqual(identity['request'], request)
                for key, value in (('baseline_color_cells',16384),
                                   ('baseline_compact_adaptance_cells',8192),
                                   ('graph_builder','specialized')):
                    with self.subTest(key=key), self.assertRaisesRegex(ValueError, 'Cannot resume'):
                        hdr_report.run(directory, resume=True, **dict(run_options, **{key:value}))
                with self.assertRaisesRegex(RuntimeError, 'stop before native work'):
                    hdr_report.run(directory, resume=True, **run_options)

    def test_cli_rejects_bad_color_baselines_before_launching(self):
        for argument in ('--baseline-color-cells', '--baseline-compact-adaptance-cells'):
            with self.subTest(argument=argument), patch.object(hdr_report, 'run') as run:
                with self.assertRaises(SystemExit):
                    hdr_report.main(['--output-dir','/tmp/hdr-invalid',argument,'7'])
                run.assert_not_called()


if __name__ == '__main__':
    unittest.main()
