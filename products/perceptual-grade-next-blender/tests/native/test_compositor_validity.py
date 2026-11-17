"""Exercise finite-result routing in final renders without Grade math.

Blender promotes requested AUTO precision to Full for final renders. Live
Viewer acceptance separately checks actual half-image materialization.
"""

import os
import unittest

import bpy
import numpy as np

from color_tools.kernel import prepare
from color_tools.template_build.compositor_output import finite_color
from color_tools.template_build.graph import BuiltGrade, Graph, count_nodes
from tools.perceptual_grade.reports.native import NativeFixture


def finite_selector_builder(prepared, tree_type, *, observe_state=False):
    tree = bpy.data.node_groups.new("Finite output selector", tree_type)
    graph = Graph(tree, prepared)
    tree.interface.new_socket(name="Color", in_out="INPUT", socket_type="NodeSocketColor")
    tree.interface.new_socket(name="Color", in_out="OUTPUT", socket_type="NodeSocketColor")
    for name in ("Alpha", "Decode Valid", "Pole Margin"):
        tree.interface.new_socket(name=name, in_out="OUTPUT", socket_type="NodeSocketFloat")
    source = tree.nodes.new("NodeGroupInput")
    output = tree.nodes.new("NodeGroupOutput")
    if observe_state:
        selected, valid = finite_color(
            graph, graph.vector((.2, .3, .4)),
            observed=graph.split(source.outputs["Color"]),
        )
    else:
        selected, valid = finite_color(graph, source.outputs["Color"])
    separate = graph.node("CompositorNodeSeparateColor")
    separate.mode = "RGB"
    graph.connect(source.outputs["Color"], separate.inputs["Image"])
    alpha = separate.outputs["Alpha"]
    restore = graph.node("CompositorNodeSetAlpha")
    restore.inputs["Type"].default_value = "Replace Alpha"
    graph.connect(selected, restore.inputs["Image"])
    graph.connect(alpha, restore.inputs["Alpha"])
    for name, value in (("Color", restore.outputs["Image"]), ("Alpha", alpha),
                        ("Decode Valid", valid), ("Pole Margin", 1.)):
        graph.connect(value, output.inputs[name])
    return BuiltGrade(tree, (), (), prepared, count_nodes(tree, ()))


class CompositorValidityTests(unittest.TestCase):
    def assert_outputs(self, values, expected, *, observe_state=False):
        modes = [("CPU", "FULL")]
        if os.environ.get("PG_COMPOSITOR_VALIDITY_GPU") == "1":
            import gpu
            bpy.context.preferences.system.gpu_backend = "OPENGL"
            gpu.init()
            # AUTO is a final-render request here; effective precision is Full.
            modes += [("GPU", "FULL"), ("GPU", "AUTO")]
        for device, precision in modes:
            with self.subTest(device=device, precision=precision):
                fixture = NativeFixture(prepare(), values, "compositor",
                                        device=device, precision=precision,
                                        builder=lambda prepared, tree_type: finite_selector_builder(
                                            prepared, tree_type, observe_state=observe_state))
                try:
                    actual = fixture.render()
                finally:
                    fixture.close()
                np.testing.assert_array_equal(actual["rgb"], expected)
                np.testing.assert_array_equal(actual["valid"], (1., 0., 0., 0., 1.))
                np.testing.assert_array_equal(actual["alpha"], values[:, 3])

    def test_invalid_pixels_return_magenta_and_preserve_alpha(self):
        values = np.asarray(((.2, .3, .4, .25), (np.inf, .3, .4, .5),
                             (.2, np.nan, .4, .75), (.2, .3, -np.inf, 1.),
                             (0., 0., 0., .125)), dtype=np.float32)
        expected = values[:, :3].copy()
        expected[1:4] = (1., 0., 1.)
        self.assert_outputs(values, expected)

    def test_invalid_observed_state_cannot_publish_a_finite_projection(self):
        values = np.asarray(((1., 2., 3., .25), (np.inf, 2., 3., .5),
                             (1., np.nan, 3., .75), (1., 2., -np.inf, 1.),
                             (0., 0., 0., .125)), dtype=np.float32)
        expected = np.tile(np.asarray((.2, .3, .4), dtype=np.float32), (5, 1))
        expected[1:4] = (1., 0., 1.)
        self.assert_outputs(values, expected, observe_state=True)


if __name__ == "__main__":
    unittest.main()
