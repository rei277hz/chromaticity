"""Native float32 saturation primitives, including inactive overflowing arms."""
import unittest
import numpy as np
import bpy
from color_tools.kernel import prepare
from color_tools.kernel.graph import Graph, BuiltGrade, count_nodes, FLOAT_MAX
from tools.perceptual_grade.reports.native import NativeFixture


def primitive_group(mode):
    def build(prepared, tree_type):
        tree = bpy.data.node_groups.new('Native saturation primitive probe', tree_type)
        g = Graph(tree, prepared)
        tree.interface.new_socket(name='Color', in_out='INPUT', socket_type='NodeSocketColor')
        if tree_type == 'ShaderNodeTree':
            tree.interface.new_socket(name='Alpha', in_out='INPUT', socket_type='NodeSocketFloat')
        tree.interface.new_socket(name='Color', in_out='OUTPUT', socket_type='NodeSocketColor')
        for name in ('Decode Valid', 'Pole Margin', 'Alpha'):
            tree.interface.new_socket(name=name, in_out='OUTPUT', socket_type='NodeSocketFloat')
        source, output = tree.nodes.new('NodeGroupInput'), tree.nodes.new('NodeGroupOutput')
        a, b, c = g.split(source.outputs['Color'])
        if mode == 'arithmetic':
            pairs = (g.sat_mul(a, b), g.sat_add(a, b), g.sat_power(a, c))
        else:
            overflow, flag = g.sat_mul(a, 4.)
            pairs = (g.sat_div(a, b), (g.safe_select(c, a, b), 0.),
                     (g.safe_select(c, overflow, .25), g.safe_select(c, flag, 0.)))
        g.connect(g.vector(tuple(value for value, _ in pairs)), output.inputs['Color'])
        for (_, flag), name in zip(pairs, ('Decode Valid', 'Pole Margin', 'Alpha')):
            g.connect(flag, output.inputs[name])
        return BuiltGrade(tree, (), (), prepared, count_nodes(tree))
    return build


class SaturationPrimitiveTests(unittest.TestCase):
    def test_constant_power_overflow_preserves_odd_negative_sign(self):
        tree = bpy.data.node_groups.new('Constant saturation probe', 'ShaderNodeTree')
        try:
            graph = Graph(tree, prepare())
            self.assertEqual(graph.sat_power(-FLOAT_MAX, 9), (-FLOAT_MAX, 1.))
            self.assertEqual(graph.sat_power(-FLOAT_MAX, 10), (FLOAT_MAX, 1.))
            self.assertEqual(graph.sat_power(FLOAT_MAX, 9), (FLOAT_MAX, 1.))
        finally:
            bpy.data.node_groups.remove(tree)

    def check_mode(self, mode, rows):
        source = np.asarray(rows, np.float32)
        source = np.resize(source, (256, 3))
        a, b, c = source.astype(float).T
        if mode == 'arithmetic':
            exact = np.column_stack((a*b, a+b, np.power(a, c)))
            flags = abs(exact) > FLOAT_MAX
            expected = np.clip(exact, -FLOAT_MAX, FLOAT_MAX).astype(np.float32)
        else:
            zero = b == 0
            division = np.divide(a, b, out=np.zeros_like(a), where=~zero)
            division = np.where(zero & (a != 0), np.sign(a)*np.inf, division)
            division = np.where(zero & (a == 0), 0., division)
            overflow = a*4
            expected = np.column_stack((np.clip(division, -FLOAT_MAX, FLOAT_MAX),
                                        np.where(c != 0, a, b),
                                        np.where(c != 0, np.clip(overflow, -FLOAT_MAX, FLOAT_MAX), .25))).astype(np.float32)
            flags = np.column_stack((abs(division) > FLOAT_MAX, np.zeros_like(a, bool),
                                     (c != 0) & (abs(overflow) > FLOAT_MAX)))
        values = np.column_stack((source, np.ones(256, np.float32)))
        for context in ('shader', 'compositor'):
            with self.subTest(mode=mode, context=context):
                fixture = NativeFixture(prepare(), values, context, builder=primitive_group(mode))
                try:
                    actual = fixture.render()
                finally:
                    fixture.close()
                self.assertTrue(np.isfinite(actual['rgb']).all())
                np.testing.assert_array_equal(actual['rgb'], expected)
                np.testing.assert_array_equal(np.column_stack((actual['valid'], actual['margin'], actual['alpha'])) > .5, flags)

    def test_signed_overflow_and_finite_maximum(self):
        f = FLOAT_MAX
        self.check_mode('arithmetic', ((f, 2, 2), (-f, 2, 3), (.75*f, .75*f, 1),
                                      (-.75*f, -.75*f, 1), (f, 0, 1), (-f, 0, 1),
                                      (0, 0, 1), (2, -3, 3), (-2, 3, 3), (-f, .5, 1)))

    def test_zero_division_safe_select_and_inactive_overflow(self):
        f = FLOAT_MAX
        self.check_mode('select', ((f, 0, 0), (-f, 0, 0), (0, 0, 0),
                                  (f, .5, 1), (-f, .5, 0), (f, -f, 0), (f, -f, 1),
                                  (-f, f, 0), (-f, f, 1), (0, 2, 1), (1, -0., 0)))


if __name__ == '__main__':
    unittest.main()
