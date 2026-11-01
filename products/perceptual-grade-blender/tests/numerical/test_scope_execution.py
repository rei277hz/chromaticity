"""Helper DTO boundaries preserve numerical signatures and inspector views."""
from collections import OrderedDict
from collections.abc import Mapping
from dataclasses import replace
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

import numpy as np
from color_tools.perceptual_grade_core.jobs import codec
from color_tools.perceptual_grade_blender.jobs.handlers import scopes
from color_tools.blender_runtime.execution.payloads import PayloadStore
from color_tools.perceptual_grade_core.model import color, forward, linear, lut, pipeline, scope_analysis, scope_color, scope_reference, tone, transforms
from color_tools.color_core import modcam16 as responses


class ScopeExecutionTests(unittest.TestCase):
    def setUp(self):
        scopes._cache.clear()
        scopes._warp_results.clear()
        self.addCleanup(scopes._cache.clear)
        self.addCleanup(scopes._warp_results.clear)

    def snapshot(self):
        space = linear.GradeSpace('D65')
        parameters = tone.Parameters(input_midtones=42.)
        chromatic = color.Parameters(global_gain=.2)
        rgba = np.random.default_rng(917).uniform(.01, .8, (3, 4, 4))
        rgba[0, 0, 3] = 0
        rgba[0, 1, :3] = [-.01, .4, .7]
        cube = lut.Cube(lut.lattice(), 'captured-final', size=65)
        return dict(base_key=('base', parameters, space), key=('request', chromatic),
                    rgba=rgba, chain=(), label='Input', signal=(cube, np.eye(3), np.eye(3)),
                    comparison=(rgba.copy(), ()), stack=False, space='Linear Rec.709',
                    grading_space=space, params=chromatic, view=(2, True), tone=parameters,
                    linear=linear.Parameters(), matrix=np.eye(3), to_grade=np.eye(3),
                    _scope_provenance=(('captured-final', 65),))

    def cloud_snapshot(self, **changes):
        view = dict(key=('raster', 1), width=33, height=35, rect=(.25, .75, 32., 34.),
                    scale=1., bounds=((-1.12, -1.12, 1.12, 1.12),) * 4)
        snapshot = self.snapshot()
        snapshot.update(_warp_analysis_key=snapshot['key'], _warp_views=(view,),
                        _scope_evaluation=('analytic', 'cloud-v1'))
        snapshot.update(changes)
        return snapshot

    def test_warp_transport_omits_point_graph_and_preserves_all_cpu_statistics(self):
        """The fallback and GPU publication contract has no per-sample arrays."""
        from color_tools.perceptual_grade_blender.model import scope_cloud_gpu
        for stack in (False, True):
            for comparison in (False, True):
                with self.subTest(stack=stack, comparison=comparison):
                    scopes._cache.clear(); scopes._warp_results.clear()
                    snapshot = self.cloud_snapshot(stack=stack)
                    if not comparison: snapshot['comparison'] = None
                    oracle = scope_analysis.evaluate_snapshot(snapshot, OrderedDict())
                    result = codec.thaw_scope_result(scopes.warp(codec.freeze_scope_request(snapshot),
                                                       Mock(role='bulk')))
                    raster = result['_warp_clouds'][0]
                    self.assertEqual(raster['backend'], 'cpu')
                    self.assertEqual(raster['pixels'].shape, (2 if comparison else 1, 4, 35, 33))
                    self.assertEqual(raster['pixels'].dtype, np.uint8)
                    expected = scope_cloud_gpu.render(oracle, snapshot['_warp_views'], False)
                    np.testing.assert_array_equal(raster['pixels'], expected[0]['pixels'])
                    for field in ('before', 'after', 'linear_vectorscope'):
                        self.assert_display_value(result[field], oracle[field])
                    for index, (actual, wanted) in enumerate(zip(result['_colors'], oracle['_colors'])):
                        self.assertIs(actual['_base'], result)
                        self.assertIs(actual['_warp_clouds'], result['_warp_clouds'])
                        self.assertEqual(actual['_warp_tone'], index)
                        self.assertTrue({'weights', 'after_energy', 'bounded_saturation', 'after',
                                         'saturation', '_input', 'sample_indices'}.isdisjoint(actual))
                        for field in ('histograms', 'sectors', 'waveform_selected', 'waveform_outside',
                                      'vectorscope', 'saturation_excluded'):
                            self.assert_display_value(actual[field], wanted[field])
                        self.assert_display_value(actual['neutral'],
                            {name: value for name, value in wanted['neutral'].items() if name != 'sample_indices'})
                    if comparison:
                        self.assertEqual(set(result['_comparison']), {'distribution', 'vectorscope'})
                        for actual, wanted in zip(result['_comparisons_selected'], oracle['_comparisons_selected']):
                            self.assertEqual(set(actual), {'waveform', 'vectorscope', 'signal'})
                            self.assertIs(actual['signal'], result['_comparison'])
                            for field in ('waveform', 'vectorscope'):
                                self.assert_display_value(actual[field], wanted[field])

    def test_warp_view_only_request_reuses_analysis_but_never_stale_numerical_revision(self):
        snapshot = self.cloud_snapshot()
        context = Mock(role='bulk')
        first = codec.thaw_scope_result(scopes.warp(codec.freeze_scope_request(snapshot), context))
        cached = next(iter(scopes._warp_results.values()))
        cached_key = cached['_scope_key']
        view = dict(snapshot['_warp_views'][0], key=('resized',), width=47, height=49,
                    rect=(.5, .25, 46., 48.))
        changed = dict(snapshot, key=('resized-publication',), _warp_views=(view,), view=(3, True))
        with patch.object(scope_analysis, 'evaluate_snapshot', side_effect=AssertionError('p95 rerun on resize')):
            second = codec.thaw_scope_result(scopes.warp(codec.freeze_scope_request(changed), context))
        self.assertTrue(second['_warp_cpu_reused'])
        self.assertEqual(second['_scope_key'], changed['key'])
        self.assertEqual(cached['_scope_key'], cached_key)
        self.assertIs(second['_color'], second['_colors'][3])
        self.assertEqual(second['_warp_clouds'][0]['pixels'].shape, (2, 4, 49, 47))
        self.assert_display_value(second['_colors'][0]['neutral'], first['_colors'][0]['neutral'])
        changed.update(key=('different-controls',), _warp_analysis_key=('different-controls',),
                       params=replace(snapshot['params'], global_gain=.5))
        with patch.object(scope_analysis, 'evaluate_snapshot', wraps=scope_analysis.evaluate_snapshot) as evaluate:
            third = codec.thaw_scope_result(scopes.warp(codec.freeze_scope_request(changed), context))
        evaluate.assert_called_once()
        self.assertFalse(third['_warp_cpu_reused'])

    def test_warp_gpu_failure_then_bulk_retry_retains_texture_only_contract(self):
        from color_tools.perceptual_grade_blender.model import scope_cloud_gpu
        from color_tools.perceptual_grade_blender.jobs.handlers import bake
        snapshot = self.cloud_snapshot()
        payload = codec.freeze_scope_request(snapshot)
        with (patch.object(bake, '_device'),
              patch.object(scope_cloud_gpu, '_gpu_render', side_effect=RuntimeError('context lost'))):
            with self.assertRaisesRegex(RuntimeError, 'context lost'):
                scopes.warp(payload, Mock(role='gpu'))
        # The real runtime retries the same operation with a bulk role. It may
        # use a separate process and cache; either way the wire contract holds.
        scopes._warp_results.clear(); scopes._cache.clear()
        actual = codec.thaw_scope_result(scopes.warp(payload, Mock(role='bulk')))
        self.assertEqual(actual['_warp_clouds'][0]['backend'], 'cpu')
        self.assertNotIn('weights', actual['_color'])
        self.assertNotIn('bounded_saturation', actual['_comparison'])

    def test_model_roundtrip_preserves_core_and_endpoint_signatures(self):
        first = transforms.Settings(linear.I3, tone.Parameters(input_midtones=41.),
                                    color.Parameters(global_gain=.15), linear.GradeSpace('D65'))
        second = replace(first, matrix=((1.1, .02, 0.), (0., .9, .03), (.01, 0., 1.)))
        for entries, directions in (((), ()), ((first,), ('FORWARD',)),
                                    ((first, second, first), ('FORWARD', 'INVERSE', 'FORWARD'))):
            with self.subTest(directions=directions):
                original = transforms.Stack(entries, directions=directions)
                restored = codec.thaw_model(codec.freeze_model(original))
                self.assertEqual(original.cache_key, restored.cache_key)
                self.assertEqual(original.bake_key, restored.bake_key)
                self.assertEqual(lut.signature(original), lut.signature(restored))
                self.assertEqual(lut.signature(original, 33), lut.signature(restored, 33))
                np.testing.assert_array_equal(original.input_matrix, restored.input_matrix)
                np.testing.assert_array_equal(original.output_matrix, restored.output_matrix)
                self.assertIsNone(restored._prepared)

    def assert_display_value(self, actual, expected):
        if isinstance(expected, np.ndarray):
            np.testing.assert_array_equal(actual, expected)
            self.assertEqual(actual.dtype, expected.dtype)
            self.assertFalse(actual.flags.writeable)
        elif isinstance(expected, Mapping):
            self.assertEqual(set(actual), set(expected))
            for name in expected:
                self.assert_display_value(actual[name], expected[name])
            with self.assertRaises(TypeError):
                actual['__test_mutation__'] = None
        else:
            self.assertEqual(actual, expected)

    def assert_display_result(self, actual, expected):
        """Compare display consumers to independent rich numerical results."""
        base_fields = {'before', 'after', 'label', 'signature', '_scope_key',
                       '_scope_provenance', 'linear_vectorscope'}
        link_fields = {'model', '_colors', '_color', '_comparison',
                       '_comparisons_selected', '_comparison_selected'}
        self.assertEqual(set(actual), (base_fields | link_fields) & set(expected))
        for name in base_fields & set(expected):
            self.assert_display_value(actual[name], expected[name])
        self.assertEqual(actual['model'].params, expected['model'].params)
        self.assertEqual(actual['model'].space, expected['model'].space)
        selected_index = next(i for i, item in enumerate(expected['_colors'])
                              if item is expected['_color'])
        self.assertIs(actual['_color'], actual['_colors'][selected_index])
        self.assertEqual(len(actual['_colors']), 4)
        color_fields = {'weights', 'histograms', 'sectors', 'waveform_selected',
                        'waveform_outside', 'vectorscope', 'label', 'after_energy',
                        'bounded_saturation', 'saturation_excluded'}
        for selected, wanted in zip(actual['_colors'], expected['_colors']):
            self.assertEqual(set(selected), color_fields | {'model', 'neutral', '_base'})
            self.assertIs(selected['_base'], actual)
            self.assertIs(selected['model'].tone, actual['model'])
            self.assertIs(selected['model'], actual['_colors'][0]['model'])
            for name in ('after_energy', 'bounded_saturation'):
                self.assertIs(selected[name], actual['_colors'][0][name])
            for name in color_fields:
                self.assert_display_value(selected[name], wanted[name])
            neutral = wanted['neutral']
            self.assert_display_value(selected['neutral'], None if neutral is None else
                                      {key: value for key, value in neutral.items() if key != 'sample_indices'})
            np.testing.assert_array_equal(selected['model'].weights(np.array([10., 30.]), 4),
                                          wanted['model'].weights(np.array([10., 30.]), 4))
        comparison = expected['_comparison']
        self.assert_display_value(actual['_comparison'], None if comparison is None else
                                  {name: comparison[name] for name in
                                   ('distribution', 'vectorscope', 'bounded_saturation', 'energy')})
        if '_comparisons_selected' in expected:
            self.assertEqual(len(actual['_comparisons_selected']), 4)
            for selected, wanted in zip(actual['_comparisons_selected'], expected['_comparisons_selected']):
                self.assertEqual(set(selected), {'weights', 'waveform', 'vectorscope', 'signal'})
                self.assertIs(selected['signal'], actual['_comparison'])
                for name in ('weights', 'waveform', 'vectorscope'):
                    self.assert_display_value(selected[name], wanted[name])
            self.assertIs(actual['_comparison_selected'], actual['_comparisons_selected'][selected_index])
        else:
            self.assertIsNone(actual['_comparison_selected'])
        with self.assertRaises(TypeError):
            actual['_color']['new'] = 1

    @staticmethod
    def graph_records(root):
        """Snapshot container topology and arrays without copying model locks."""
        seen = set()
        records = []

        def visit(value):
            identity = id(value)
            if identity in seen:
                return
            seen.add(identity)
            if isinstance(value, np.ndarray):
                records.append(('array', identity, value.shape, value.dtype.str,
                                value.flags.writeable, value.tobytes()))
            elif isinstance(value, Mapping):
                records.append(('mapping', identity, tuple((name, id(child)) for name, child in value.items())))
                for child in value.values():
                    visit(child)
            elif isinstance(value, (tuple, list)):
                records.append(('sequence', identity, tuple(map(id, value))))
                for child in value:
                    visit(child)

        visit(root)
        return records

    def test_full_helper_roundtrip_preserves_display_arrays_aliases_and_all_views(self):
        for stack in (False, True):
            for comparison in (False, True):
                for selected in range(4):
                    with self.subTest(stack=stack, comparison=comparison, selected=selected):
                        scopes._cache.clear()
                        snapshot = dict(self.snapshot(), stack=stack, view=(selected, True))
                        if not comparison:
                            snapshot['comparison'] = None
                        expected = scope_analysis.evaluate_snapshot(snapshot, OrderedDict())
                        context = Mock()
                        wire = scopes.full(codec.freeze_scope_request(snapshot), context)
                        self.assert_display_result(codec.thaw_scope_result(wire), expected)
                        self.assertEqual(context.checkpoint.call_count, 2)

    def test_full_projection_preserves_worker_cache_and_omits_scratch_graph(self):
        snapshot = dict(self.snapshot(), comparison=None)
        cache = OrderedDict()
        result = scope_analysis.evaluate_snapshot(snapshot, cache)
        # Unknown future fields must not leak through the transport boundary.
        scratch = np.zeros((2, 3, 4))
        result['future_scratch'] = {'full_result': result, 'buffer': scratch}
        result['_colors'][0]['future_scratch'] = scratch
        roots = (result, cache)
        original = self.graph_records(roots)
        wire = codec.freeze_full_scope_result(result)
        self.assertEqual(self.graph_records(roots), original)
        actual = codec.thaw_scope_result(wire)
        self.assert_display_result(actual, result)
        # Exact allowlists above cover nested graph reachability, including each
        # color's _base link. The transport may not retain duplicated memberships.
        records = self.graph_records(actual)
        # One arithmetic-mean array per tone was removed from the display DTO.
        self.assertEqual(sum(record[0] == 'array' for record in records), 55)
        self.assertEqual(sum(record[0] == 'array' for record in self.graph_records(wire)), 55)
        self.assertIs(result['_colors'][0]['_input']['_base'], result)
        self.assertIn('sample_indices', result['_colors'][0]['neutral'])
        self.assertIn('stage2_appearance', cache[snapshot['base_key']])

    def test_full_projection_preserves_partial_comparison_failure(self):
        for stack in (False, True):
            for operation in ('evaluate', 'select'):
                with self.subTest(stack=stack, operation=operation):
                    scopes._cache.clear()
                    snapshot = dict(self.snapshot(), stack=stack)
                    with patch.object(scope_reference, operation, side_effect=ValueError('reference failed')):
                        with self.assertLogs(scope_analysis.__package__, level='WARNING'):
                            expected = scope_analysis.evaluate_snapshot(snapshot, OrderedDict())
                            wire = scopes.full(codec.freeze_scope_request(snapshot), Mock())
                    self.assert_display_result(codec.thaw_scope_result(wire), expected)
                    self.assertEqual(expected['_comparison'] is None, operation == 'evaluate')

    def test_stage_one_helper_preserves_reusable_source_and_final_provenance(self):
        space = linear.GradeSpace()
        rgba = np.array([[[.2, .4, -.1, 1.], [.3, .2, .5, .5]]])
        source = dict(key=('source', space), rgba=rgba, chain=(), to_grade=np.eye(3),
                      label='Input', _scope_provenance=())
        snapshot = dict(key=('matrix', linear.I3), source=source, comparison=source,
                        matrix=np.diag([1.1, .9, 1.]), scene_space='Linear Rec.709', space=space,
                        _scope_provenance=())
        restored = codec.thaw_scope_request(codec.freeze_scope_request(snapshot))
        self.assertIs(restored['source'], restored['comparison'])
        actual = codec.thaw_scope_result(scopes.linear(codec.freeze_scope_request(snapshot), Mock()))
        np.testing.assert_array_equal(actual['stage1_rgb'], rgba[..., :3] @ snapshot['matrix'].T)
        self.assertFalse(actual['_source']['rgb'].flags.writeable)
        self.assertEqual(actual['_scope_provenance'], ())
        cached = dict(snapshot, source=actual['_source'], comparison=actual['_comparison_source'])
        second = codec.thaw_scope_result(scopes.linear(codec.freeze_scope_request(cached), Mock()))
        np.testing.assert_array_equal(actual['linear_vectorscope']['density'],
                                      second['linear_vectorscope']['density'])

    def test_installed_scope_reuses_capacity_and_never_prepares_another_grade(self):
        for stack in (False, True):
            with self.subTest(stack=stack):
                snapshot = dict(self.snapshot(), stack=stack)
                base = scope_analysis.evaluate_snapshot(snapshot, OrderedDict())
                model = base['_color']['model']
                previous = base['_color']['_input']
                safe = previous['safe']
                # Capacity remains the driver oracle; DetMCD eligibility now
                # uses linear saturation independently of the boundary table.
                if stack:
                    from color_tools.perceptual_grade_core.model.forward import Model
                    signed = Model(model.tone, model).encode_cones(model.tone.cones(base['stack_output_rgb']))
                else:
                    signed = base['stage2_appearance']
                good = np.isfinite(signed.q).all(axis=-1) & (base['alpha'] > 0)
                ja = np.where(good, signed.ja, 0.)
                expected_drivers = model.drivers(safe, ja)
                from color_tools.perceptual_grade_core.model.saturation import project
                coordinates = project(safe, ja * abs(ja))
                expected_neutral = np.isfinite(coordinates).all(axis=-1) & (np.hypot(coordinates[..., 0], coordinates[..., 1]) < .1)
                with patch.object(model, 'capacity', wraps=model.capacity) as capacity, \
                     patch.object(pipeline, 'Prepared', side_effect=AssertionError('Recomputed a published grade')):
                    actual = scope_color.input_analysis(base, model)
                self.assertEqual(capacity.call_count, 1)
                np.testing.assert_array_equal(actual['drivers'], expected_drivers)
                np.testing.assert_array_equal(actual['near_neutral'], expected_neutral)
                for key in ('before', 'safe', 'H', 'tone_id', 'alpha', 'inside', 'yi', 'xi', 'waveform', 'bins'):
                    np.testing.assert_array_equal(actual[key], previous[key])

    def test_stage_three_param_edits_reuse_immutable_input_analysis(self):
        snapshot = dict(self.snapshot(), comparison=None)
        cache = OrderedDict()
        first = scope_analysis.evaluate_snapshot(snapshot, cache)
        changed = dict(snapshot, params=color.Parameters(global_gain=.8),
                       key=('request', 'changed'))
        with patch.object(scope_color, '_input_analysis',
                          wraps=scope_color._input_analysis) as inputs, \
             patch.object(scope_color, '_selection',
                          wraps=scope_color._selection) as selections:
            warm = scope_analysis.evaluate_snapshot(changed, cache)
        self.assertEqual(inputs.call_count, 0)
        self.assertEqual(selections.call_count, 0)
        cold = scope_analysis.evaluate_snapshot(changed, OrderedDict())
        for left, right in zip(warm['_colors'], cold['_colors']):
            for field in ('after', 'after_energy', 'saturation', 'bounded_saturation',
                          'waveform_selected', 'vectorscope'):
                if isinstance(left[field], dict):
                    for name in left[field]:
                        np.testing.assert_allclose(left[field][name], right[field][name], rtol=0, atol=0)
                else:
                    np.testing.assert_allclose(left[field], right[field], rtol=0, atol=0)
        self.assertIs(first['_input_cache'], warm['_input_cache'])

    def test_input_cache_is_acyclic_readonly_and_evicted_after_four_entries(self):
        cache = OrderedDict()
        snapshots = [dict(self.snapshot(), comparison=None,
                           base_key=('base', index)) for index in range(5)]
        for item in snapshots:
            scope_analysis.evaluate_snapshot(item, cache)
        self.assertEqual(len(cache), 4)
        self.assertNotIn(snapshots[0]['base_key'], cache)

        entry = cache[snapshots[-1]['base_key']]['_input_cache']
        seen = set()

        def visit(value):
            identity = id(value)
            self.assertNotIn(identity, seen, 'cache contains a reference cycle')
            if isinstance(value, np.ndarray):
                self.assertFalse(value.flags.writeable)
                return
            if isinstance(value, dict):
                seen.add(identity)
                self.assertNotIn('_base', value)
                self.assertNotIn('_input', value)
                self.assertNotIn('prepared', value)
                for child in value.values():
                    visit(child)
            elif isinstance(value, (tuple, list)):
                seen.add(identity)
                for child in value:
                    visit(child)

        visit(entry)

    def test_guarded_appearance_matches_rgb_oracle_for_signed_hdr_and_neutral(self):
        snapshot = self.snapshot()
        snapshot['rgba'] = np.array([[[0., 0., 0., 1.],
                                      [1., 1., 1., 1.],
                                      [-.01, .4, .7, 1.],
                                      [4., .5, .1, 1.]]])
        base = scope_analysis.evaluate_snapshot(snapshot, OrderedDict())
        model = color.model(snapshot['tone'], snapshot['params'], snapshot['grading_space'])
        engine = forward.Model(model.tone, model)
        guarded = engine.guarded_appearance(base['stage2_appearance'])
        self.assertIsNotNone(guarded)
        q, energy, native = guarded
        rgb = engine.from_native(native)
        oracle = pipeline.Prepared(base, model).apply(model)
        np.testing.assert_allclose(rgb, oracle, rtol=2e-12, atol=2e-12)
        reencoded = engine.encode_cones(model.tone.cones(rgb))
        np.testing.assert_allclose(q, reencoded.q, rtol=2e-12, atol=2e-12)
        np.testing.assert_allclose(energy, reencoded.ja * np.abs(reencoded.ja),
                                   rtol=2e-12, atol=2e-12)

    def test_guarded_appearance_preserves_tiny_fallback_and_extreme_controls(self):
        snapshot = dict(self.snapshot(), comparison=None)
        base = scope_analysis.evaluate_snapshot(snapshot, OrderedDict())
        extreme = color.model(snapshot['tone'], color.Parameters(global_gain=128.),
                               snapshot['grading_space'])
        engine = forward.Model(extreme.tone, extreme)
        guarded = engine.guarded_appearance(base['stage2_appearance'])
        self.assertIsNotNone(guarded)
        self.assertTrue(np.isfinite(np.asarray(guarded[0])).all())
        tiny = responses.Appearance(np.array([[[1e-250, 0., 0.]]]),
                                    np.array([[1e-250]]))
        self.assertIsNone(engine.guarded_appearance(tiny))

    def test_all_tone_waveforms_use_one_guarded_appearance(self):
        snapshot = dict(self.snapshot(), comparison=None)
        base = scope_analysis.evaluate_snapshot(snapshot, OrderedDict())
        model = color.model(snapshot['tone'], snapshot['params'], snapshot['grading_space'])
        engine = forward.Model(model.tone, model)
        q, energy, native = engine.guarded_appearance(base['stage2_appearance'])
        result = scope_color.evaluate_all(base, snapshot['params'], snapshot['grading_space'])
        for selected in result:
            expected = scope_color.output_waveform(q, selected['weights'], model.tone.plot_max * 100)
            np.testing.assert_array_equal(selected['waveform_selected'], expected['density'])
            self.assertEqual(selected['waveform_outside'], expected['outside'])

    def test_stage_two_distribution_is_independent_of_stage_three_controls(self):
        stage_two = dict(self.snapshot(), stage=2, comparison=None)
        stage_three = dict(stage_two, stage=3, params=color.Parameters(global_gain=.9),
                           key=('request', 'stage-three'))
        cache = OrderedDict()
        early = scope_analysis.evaluate_snapshot(stage_two, cache)
        later = scope_analysis.evaluate_snapshot(stage_three, cache)
        for field in ('density', 'histogram'):
            np.testing.assert_array_equal(early['before'][field], later['before'][field])
            np.testing.assert_array_equal(early['after'][field], later['after'][field])
        for field in ('invalid', 'above', 'below', 'count'):
            self.assertEqual(early['before'][field], later['before'][field])
            self.assertEqual(early['after'][field], later['after'][field])
        signed = later['stage2_appearance']
        magnitude = np.hypot(signed.ja,
                             np.sqrt(66*np.hypot(signed.q[..., 1], signed.q[..., 2])))/100
        expected = scope_analysis.distribution(magnitude, later['alpha'],
                                               later['model'].plot_max)
        for field in ('density', 'histogram'):
            np.testing.assert_array_equal(early['after'][field], expected[field])
        for field in ('invalid', 'above', 'below', 'count'):
            self.assertEqual(early['after'][field], expected[field])

    def test_scope_without_installed_output_still_evaluates_the_grade(self):
        from color_tools.color_core.modcam16 import encode_cones
        snapshot = self.snapshot()
        base = scope_analysis.evaluate_snapshot(snapshot, OrderedDict())
        model = color.model(snapshot['tone'], snapshot['params'], snapshot['grading_space'])
        rgb = pipeline.Prepared(base, model).apply(model)
        expected = encode_cones(model.tone.cones(rgb), model.tone.reference).q
        with patch.object(pipeline, 'Prepared', wraps=pipeline.Prepared) as prepared:
            actual = scope_color.evaluate_all(base, snapshot['params'], snapshot['grading_space'])
        # Analytic scopes use the guarded appearance state directly; no
        # temporary RGB preparation is needed on the hot path.
        self.assertEqual(prepared.call_count, 0)
        for selected in actual:
            np.testing.assert_allclose(selected['after'], expected, rtol=2e-12, atol=2e-12)
            self.assertNotIn('prepared', selected['_input'])

    def test_stage_two_publication_skips_chromatic_analysis_and_promotes_cache(self):
        snapshot = dict(self.snapshot(), stage=2, comparison=None)
        cache = OrderedDict()
        with patch.object(scope_color, 'input_analysis_cache',
                          side_effect=AssertionError('Stage 2 ran Stage 3 analysis')):
            stage_two = scope_analysis.evaluate_snapshot(snapshot, cache)
        self.assertNotIn('_input_cache', cache[snapshot['base_key']])
        self.assertNotIn('_colors', stage_two)
        self.assertIsNone(stage_two['_comparison_selected'])

        stage_three = dict(snapshot)
        stage_three.pop('stage')
        with patch.object(scope_color, 'input_analysis_cache',
                          wraps=scope_color.input_analysis_cache) as analysis:
            result = scope_analysis.evaluate_snapshot(stage_three, cache)
        self.assertEqual(analysis.call_count, 1)
        self.assertIn('_colors', result)
        self.assertIn('_input_cache', cache[snapshot['base_key']])

    def test_cube_roundtrip_preserves_prepared_output_variant(self):
        cube = lut.Cube(lut.lattice()[lut.refinement_indices()[0]], 'preview', size=33)
        cube.prepared_pixels = cube.packed_pixels()
        cube.diagnostics = {'backend': 'GPU', 'device': 'test'}
        actual = codec.thaw_cube(codec.freeze_cube(cube))
        self.assertEqual(actual.signature, cube.signature)
        self.assertEqual(actual.size, 33)
        np.testing.assert_array_equal(actual.prepared_pixels, cube.prepared_pixels)
        self.assertEqual(actual.diagnostics, cube.diagnostics)

    def test_real_array_transport_preserves_scope_and_model_contracts(self):
        snapshot = self.snapshot()
        expected = scope_analysis.evaluate_snapshot(snapshot, OrderedDict())
        with tempfile.TemporaryDirectory() as directory:
            store = PayloadStore(directory)
            try:
                inputs = store.decode(store.encode(codec.freeze_scope_request(snapshot), []), copy=True)
                result = scopes.full(inputs, Mock())
                actual = codec.thaw_scope_result(store.decode(store.encode(result, [])))
                self.assert_display_result(actual, expected)
                settings = transforms.Settings(linear.I3, snapshot['tone'], snapshot['params'],
                                               snapshot['grading_space'])
                model = transforms.Stack((settings,))
                restored = codec.thaw_model(store.decode(store.encode(codec.freeze_model(model), [])))
                self.assertEqual(lut.signature(model), lut.signature(restored))
            finally:
                store.close()

    def test_payload_rejects_arbitrary_objects_and_versions(self):
        with self.assertRaises(TypeError):
            codec.freeze_scope_request({'callback': lambda: None})
        with self.assertRaises(TypeError):
            codec.freeze_scope_request({'values': np.array([object()], dtype=object)})
        with self.assertRaises(ValueError):
            codec.thaw_scope_result({'version': -1})

    def test_rejected_preview_capture_does_not_poison_retry_analysis(self):
        scopes._cache.clear()
        self.addCleanup(scopes._cache.clear)
        snapshot = self.snapshot()
        invalid = dict(snapshot, rgba=np.zeros_like(snapshot['rgba']),
                       _scope_provenance=(('captured-final', 33),))
        rejected = codec.thaw_scope_result(scopes.full(codec.freeze_scope_request(invalid), Mock()))
        self.assertEqual(rejected['_scope_provenance'], (('captured-final', 33),))
        retried = codec.thaw_scope_result(scopes.full(codec.freeze_scope_request(snapshot), Mock()))
        expected = scope_analysis.evaluate_snapshot(snapshot, OrderedDict())
        self.assert_display_result(retried, expected)
        self.assertGreater(retried['before']['count'], rejected['before']['count'])

    def test_pure_scope_imports_do_not_load_foreground_adapters(self):
        code = '''import builtins, sys
original = builtins.__import__
def guarded(name, *args, **kwargs):
    if name.split('.')[0] in {'bpy', 'gpu', 'gpu_extras'}:
        raise AssertionError('Blender dependency in numerical helper: ' + name)
    return original(name, *args, **kwargs)
builtins.__import__ = guarded
from color_tools.perceptual_grade_blender.jobs.handlers import scopes
from color_tools.perceptual_grade_core.model import scope_color, scope_reference
assert not any(name.startswith(('color_tools.perceptual_grade_blender.graph', 'color_tools.perceptual_grade_blender.ui',
                                'color_tools.perceptual_grade_blender.scopes')) for name in sys.modules)
'''
        subprocess.run([sys.executable, '-c', code], check=True)
