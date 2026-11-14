"""Native stage handoffs, independent decoding, and failed-build cleanup."""
from unittest import TestCase, main, mock
import numpy as np
import bpy
from color_tools.kernel import prepare, ToneSettings
from color_tools.template_build.graph import (
    Graph, BuiltGrade, build_group, count_nodes,
)
from tools.perceptual_grade.reports import cases, oracle
from tools.perceptual_grade.reports.native import NativeFixture


def stage_builder(mode):
    """Use the public primitive API without relying on the RGB wrapper."""
    def build(prepared, tree_type):
        tree = bpy.data.node_groups.new('Stage interface probe', tree_type)
        graph = Graph(tree, prepared)
        tree.interface.new_socket(name='Color', in_out='INPUT', socket_type='NodeSocketColor')
        if tree_type == 'ShaderNodeTree':
            tree.interface.new_socket(name='Alpha', in_out='INPUT', socket_type='NodeSocketFloat')
        tree.interface.new_socket(name='Color', in_out='OUTPUT', socket_type='NodeSocketColor')
        for name in ('Alpha', 'Decode Valid', 'Pole Margin'):
            tree.interface.new_socket(name=name, in_out='OUTPUT', socket_type='NodeSocketFloat')
        source, output = tree.nodes.new('NodeGroupInput'), tree.nodes.new('NodeGroupOutput')
        state = graph.encode(graph.linear(source.outputs['Color']))
        if mode != 'encode':
            state = graph.tone(state)
        if mode == 'decode':
            decoded = graph.decode_coordinates(state.J_A, state.a, state.b)
            color, diagnostic_a, diagnostic_b = decoded.color, decoded.valid, decoded.pole_margin
        else:
            color, diagnostic_a, diagnostic_b = state.q, state.J_A, state.energy
        for value, name in ((color, 'Color'), (diagnostic_a, 'Decode Valid'),
                            (diagnostic_b, 'Pole Margin'), (state.chroma, 'Alpha')):
            graph.connect(value, output.inputs[name])
        return BuiltGrade(tree, tuple(graph.images), tuple(graph.helper_groups),
                          prepared, count_nodes(tree, graph.images))
    return build


class StageTests(TestCase):
    def test_appearance_handoffs_and_generic_decoder(self):
        values = cases.rgba(256)
        # Pure tone includes exact signed neutrals; combined exercises a separate
        # Linear->appearance handoff rather than the wrapper's fused matrix.
        selected=(row for row in cases.grades() if row[0] in ('tone', 'combined'))
        selected=tuple(selected)+tuple(row for row in cases.ui_boundaries() if row[0] == 'tone_minimum_gap_3')
        for name, linear, tone in selected:
            prepared = prepare(linear, tone)
            expected = oracle.evaluate(values[:, :3], linear, tone, 'Linear Rec.709')
            for context in ('shader', 'compositor'):
                for mode in ('encode', 'tone', 'decode'):
                    with self.subTest(case=name, context=context, stage=mode):
                        fixture = NativeFixture(prepared, values, context, builder=stage_builder(mode))
                        try:
                            actual = fixture.render()
                        finally:
                            fixture.close()
                        if mode == 'decode':
                            self.assertLessEqual(oracle.metrics(actual['rgb'], expected['rgb'],
                                                                expected['well_conditioned'])['max_normalized'], 1e-4)
                            np.testing.assert_array_equal(actual['valid'] > .5, expected['valid'])
                        else:
                            state = expected['encoded' if mode == 'encode' else 'tone']
                            self.assertLessEqual(oracle.metrics(actual['rgb'], state.q)['max_normalized'], 1e-4)
                            np.testing.assert_allclose(actual['valid'], state.ja, rtol=1e-4, atol=1e-5)
                            np.testing.assert_allclose(actual['margin'], state.ja*abs(state.ja), rtol=2e-4, atol=1e-5)
                            if name == 'tone':
                                neutral = np.all(values[:, :3] == values[:, :1], axis=1)
                                np.testing.assert_array_equal(actual['rgb'][neutral, 1:], 0.)
                            np.testing.assert_array_equal(actual['rgb'][np.all(values[:, :3] == 0, axis=1)], 0.)

    def test_failed_build_releases_packed_images_and_tree(self):
        bpy.ops.wm.read_factory_settings(use_empty=True)
        prepared = prepare(tone=ToneSettings(input_nits=(0, 8, 40, 235, 1150)))
        before_groups = {group.as_pointer() for group in bpy.data.node_groups}
        before_images = {image.as_pointer() for image in bpy.data.images}

        def fail_after_table(graph, state):
            self.assertEqual(len(graph.images), 1)
            self.assertIsNotNone(graph.images[0].packed_file)
            raise RuntimeError('Injected decode construction failure')

        for tree_type in ('ShaderNodeTree', 'CompositorNodeTree'):
            with mock.patch.object(Graph, 'decode', fail_after_table):
                with self.assertRaisesRegex(RuntimeError, 'Injected decode'):
                    build_group(prepared, tree_type, export=False)
            self.assertEqual(before_groups, {group.as_pointer() for group in bpy.data.node_groups})
            self.assertEqual(before_images, {image.as_pointer() for image in bpy.data.images})


if __name__ == '__main__':
    main()
