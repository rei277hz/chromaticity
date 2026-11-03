"""Complete native Grade acceptance, independent reference and packed assets."""
import hashlib
from dataclasses import replace
from pathlib import Path
from unittest import mock
import unittest
import bpy
import numpy as np

from color_tools.perceptual_grade_nodes import prepare, prepare_linear, ColorSettings, WebSettings
from color_tools.perceptual_grade_nodes import graph as graph_module
from color_tools.perceptual_grade_nodes.graph import count_nodes, build_group, Graph, BuiltGrade
from color_tools.perceptual_grade_nodes.boundary import prepare_boundary
from tools.perceptual_grade_nodes import cases, full_cases, oracle
from tools.perceptual_grade_nodes.evaluate import assess
from tools.perceptual_grade_nodes.full_evaluate import _table_checks
from tools.perceptual_grade_nodes.native import NativeFixture


def image_receipt(image):
    return dict(size=tuple(image.size), colorspace=image.colorspace_settings.name,
                alpha_mode=image.alpha_mode, half_precision=image.use_half_precision,
                packed=bool(image.packed_file),
                pixels=hashlib.sha256(np.asarray(image.pixels[:], dtype=np.float32).tobytes()).hexdigest())


def parameter_row_group(prepared, tree_type):
    """Expose a selected Web parameter row at the constant first-height tail."""
    tree = bpy.data.node_groups.new('Parameter row isolation', tree_type)
    graph = Graph(tree, prepared)
    for name, direction, kind in (
            ('Color', 'INPUT', 'NodeSocketColor'), ('Alpha', 'INPUT', 'NodeSocketFloat'),
            ('Color', 'OUTPUT', 'NodeSocketColor'), ('Alpha', 'OUTPUT', 'NodeSocketFloat'),
            ('Decode Valid', 'OUTPUT', 'NodeSocketFloat'), ('Pole Margin', 'OUTPUT', 'NodeSocketFloat')):
        tree.interface.new_socket(name=name, in_out=direction, socket_type=kind)
    source, output = tree.nodes.new('NodeGroupInput'), tree.nodes.new('NodeGroupOutput')
    row = graph.split(source.outputs['Color'])[0]
    fields = graph.sample_field(prepared.color.web_table, 0., row)
    for value, name in ((graph.vector(fields[:3]), 'Color'), (fields[3], 'Alpha'),
                        (0., 'Decode Valid'), (0., 'Pole Margin')):
        graph.connect(value, output.inputs[name])
    return BuiltGrade(tree, tuple(graph.images), tuple(graph.helper_groups), prepared,
                      count_nodes(tree, graph.images))


class FullGradeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        context = prepare()
        cls.boundary = prepare_boundary(context.fl, context.aw, context.gamma)

    def test_diagnostic_precision_preserves_raw_failures_and_safety(self):
        diagnostic = dict(passed=False, scalar_gate_required=False, audit_complete=True, finite=True)
        required = dict(passed=True, scalar_gate_required=True, audit_complete=True, finite=True)
        checks = _table_checks([diagnostic, required])
        self.assertFalse(checks['raw_scalar_passed'])
        self.assertTrue(checks['required_scalar_passed'])
        self.assertTrue(checks['field_diagnostics_passed'])
        for key in ('finite', 'audit_complete'):
            self.assertFalse(_table_checks([dict(diagnostic, **{key: False})])['field_diagnostics_passed'])
        self.assertFalse(_table_checks([dict(required, passed=False)])['required_scalar_passed'])

    def test_parameter_rows_never_blend_unrelated_fields(self):
        prepared = prepare(color=ColorSettings(web=WebSettings(log_chroma=((16.,)*6,)*4,
                                                               log_scale=((8.,)*6,)*4)))
        rows = np.resize(np.arange(29, dtype=np.float32), 256)
        values = np.column_stack((rows, np.zeros((256, 2), np.float32), np.ones(256, np.float32)))
        expected = prepared.color.web_table.evaluate(0.)[rows.astype(int)]
        for context in ('shader', 'compositor'):
            with self.subTest(context=context):
                fixture = NativeFixture(prepared, values, context, builder=parameter_row_group)
                try:
                    actual = fixture.render()
                    np.testing.assert_array_equal(np.column_stack((actual['rgb'], actual['alpha'])), expected)
                finally:
                    fixture.close()

    def test_core_grades_all_spaces_shader_and_compositor(self):
        corpus = [row for row in full_cases.grades()
                  if row[0] in ('reset', 'all_active', 'saturation', 'all_active_saturation')]
        corpus += [row for row in full_cases.ui_boundaries()
                   if row[0] in ('all_families_max', 'all_families_max_active_tail')]
        prepared_grades = {name: prepare(linear, tone, color=color, boundary=self.boundary)
                           for name, linear, tone, color in corpus}
        for space in cases.SPACES:
            values = full_cases.rgba(space, 256)
            for name, linear, tone, color in corpus:
                prepared = replace(prepared_grades[name], linear=prepare_linear(linear, space), space=space)
                expected = oracle.evaluate_full(values[:, :3], linear, tone, color, space)
                for context in ('shader', 'compositor'):
                    with self.subTest(space=space, case=name, context=context):
                        fixture = NativeFixture(prepared, values, context)
                        try:
                            self.assertIs(fixture.built.prepared, prepared)
                            actual = fixture.render()
                            result = assess(actual, expected, values)
                            self.assertTrue(result['passed'], result)
                            self.assertEqual(actual['stats']['expanded_nodes'],
                                             count_nodes(fixture.built.tree).expanded_nodes)
                            for field in ('rgb', 'alpha', 'valid', 'margin', 'saturated'):
                                self.assertTrue(np.isfinite(actual[field]).all(), field)
                            np.testing.assert_array_equal(actual['alpha'], values[:, 3])
                            if context == 'compositor':
                                np.testing.assert_array_equal(actual['embedded_alpha'], values[:, 3])
                            np.testing.assert_array_equal(actual['rgb'][np.all(values[:, :3] == 0, axis=-1)], 0.)
                            if name == 'all_active':
                                self.assertGreaterEqual(len(fixture.built.images), 4)
                            if name in ('reset', 'all_active'):
                                np.testing.assert_array_equal(actual['saturated'], 0.)
                            if name == 'saturation':
                                # Four independently decoded source hues provoke
                                # finite raw energies beyond float32, of both signs.
                                self.assertTrue(np.all(abs(expected['color'].energy[-4:]) > np.finfo(np.float32).max))
                                self.assertTrue(np.all(actual['saturated'][-4:] > .5), actual['saturated'][-4:])
                                self.assertLessEqual(oracle.metrics(actual['rgb'][-4:], expected['rgb'][-4:])['max_normalized'], 1e-4)
                        finally:
                            fixture.close()

    def test_oversized_graphs_and_construction_cleanup(self):
        prepared = prepare(color=ColorSettings(web=WebSettings(hue_degrees=((1.,)*6,)*4)),
                           boundary=self.boundary)
        def resources():
            return ({item.as_pointer() for item in bpy.data.node_groups},
                    {item.as_pointer() for item in bpy.data.images})
        def oversized_count(tree, images=()):
            # Exercise the temporary admission policy without relying on a
            # particular graph remaining oversized after future optimization.
            actual = count_nodes(tree, images)
            return replace(actual, expanded_nodes=actual.expanded_nodes+1000)
        pack_image = Graph._packed_image
        def fail_after_image(graph, *args, **kwargs):
            pack_image(graph, *args, **kwargs)
            raise RuntimeError('Injected construction failure after image allocation')
        for context in ('ShaderNodeTree', 'CompositorNodeTree'):
            with self.subTest(context=context, outcome='oversized_allowed'):
                baseline = resources()
                with mock.patch.object(graph_module, 'count_nodes', side_effect=oversized_count) as counted:
                    built = build_group(prepared, context)
                try:
                    counted.assert_called_once()
                    self.assertIs(built.prepared, prepared)
                    self.assertEqual(built.stats.expanded_nodes,
                                     count_nodes(built.tree).expanded_nodes+1000)
                    current = resources()
                    self.assertEqual(current[0]-baseline[0],
                        {built.tree.as_pointer(), *(tree.as_pointer() for tree in built.helper_groups)})
                    self.assertEqual(current[1]-baseline[1], {image.as_pointer() for image in built.images})
                finally:
                    built.dispose()
                self.assertEqual(resources(), baseline)
            with self.subTest(context=context, outcome='construction_failure'):
                baseline = resources()
                with mock.patch.object(Graph, '_packed_image', fail_after_image):
                    with self.assertRaisesRegex(RuntimeError, 'Injected construction failure'):
                        build_group(prepared, context)
                self.assertEqual(resources(), baseline)

    def test_packed_full_grade_reopens_without_registration(self):
        _, linear, tone, color = next(row for row in full_cases.grades() if row[0] == 'all_active')
        values = full_cases.rgba(count=256)
        prepared = prepare(linear, tone, color=color, boundary=self.boundary)
        for context in ('shader', 'compositor'):
            with self.subTest(context=context):
                fixture = NativeFixture(prepared, values, context)
                try:
                    before = fixture.render()
                    name = fixture.built.tree.name
                    resources = {image.name: image_receipt(image) for image in fixture.built.images}
                    self.assertGreaterEqual(len(resources), 4)
                    self.assertTrue(all(receipt['packed'] for receipt in resources.values()))
                    fixture.input_image.pack()
                    filename = Path(fixture.directory.name)/'complete-native-grade.blend'
                    bpy.ops.wm.save_as_mainfile(filepath=str(filename))
                    bpy.ops.wm.open_mainfile(filepath=str(filename))
                    for image_name, receipt in resources.items():
                        self.assertEqual(image_receipt(bpy.data.images[image_name]), receipt)
                    reopened = bpy.data.node_groups[name]
                    self.assertEqual(count_nodes(reopened).expanded_nodes, before['stats']['expanded_nodes'])
                    after = fixture.render()
                    for field in ('rgb', 'alpha', 'valid', 'margin', 'saturated'):
                        np.testing.assert_array_equal(after[field], before[field])
                    expected = oracle.evaluate_full(values[:, :3], linear, tone, color, 'Linear Rec.709')
                    self.assertTrue(assess(after, expected, values)['passed'])
                finally:
                    fixture.close()


if __name__ == '__main__':
    unittest.main()
