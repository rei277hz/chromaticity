"""Complete product Stage 2 trees, guarded pixel parity and alpha preservation."""

from dataclasses import replace
from functools import partial
import unittest
from unittest.mock import patch

import bpy
import numpy as np

from color_tools.kernel import ColorSettings, LinearSettings, ToneSettings, prepare, prepare_tone
from color_tools.kernel.boundary import prepare_boundary
from color_tools.template_build.graph import build_group
from color_tools.template_build.stage2_graph import build_stage2_group
from tools.perceptual_grade.reports import cases, oracle
from tools.perceptual_grade.reports.native import NativeFixture


def complete_prepared(linear=LinearSettings(), tone=ToneSettings(), space="Linear Rec.709"):
    base = prepare(linear, tone, space)
    return replace(base, tone=prepare_tone(tone, full_fields=True),
                   boundary=prepare_boundary(base.fl, base.aw, base.gamma))


class Stage2Tests(unittest.TestCase):
    def test_complete_reset_and_active_trees_preserve_the_product_interface(self):
        bpy.ops.wm.read_factory_settings(use_empty=True)
        for tone in (ToneSettings(), ToneSettings(input_nits=(0., 5., 45., 230., 1300.))):
            for tree_type in ("ShaderNodeTree", "CompositorNodeTree"):
                built = build_stage2_group(complete_prepared(tone=tone), tree_type)
                try:
                    expected = ["Color", "Alpha"] if tree_type == "ShaderNodeTree" else ["Color"]
                    inputs = [item.name for item in built.tree.interface.items_tree
                              if item.item_type == "SOCKET" and item.in_out == "INPUT"]
                    outputs = [item.name for item in built.tree.interface.items_tree
                               if item.item_type == "SOCKET" and item.in_out == "OUTPUT"]
                    self.assertEqual(inputs, expected)
                    self.assertEqual(outputs, expected)
                    self.assertTrue(built.tree["_perceptual_grade_stage2_complete"])
                    self.assertEqual(len(built.images), 3)
                    self.assertTrue(all(image.packed_file for image in built.images))
                    parameter_images = tuple(
                        image for image in built.images
                        if image.get("_perceptual_grade_parameter_schema")
                    )
                    self.assertEqual(len(parameter_images), 2)
                    self.assertTrue(any(node.label == "AP1 boundary root seed"
                                        for node in built.tree.nodes))
                finally:
                    built.dispose()

    def test_guarded_shader_and_compositor_match_independent_reference(self):
        values = cases.rgba(256)
        for space, linear, tone in (
            ("Linear Rec.709", LinearSettings(), ToneSettings()),
            ("ACEScg", LinearSettings(exposure=.5),
             ToneSettings(input_nits=(0., 5., 45., 230., 1300.))),
        ):
            prepared = complete_prepared(linear, tone, space)
            expected = oracle.evaluate_full(values[:, :3], linear, tone, ColorSettings(), space)
            for context in ("shader", "compositor"):
                with self.subTest(space=space, context=context):
                    baseline = NativeFixture(prepared, values, context, builder=build_group)
                    try:
                        baseline_actual = baseline.render()
                    finally:
                        baseline.close()
                    fixture = NativeFixture(prepared, values, context,
                        builder=partial(build_stage2_group, diagnostics=True))
                    try:
                        actual = fixture.render()
                        self.assertTrue(np.isfinite(actual["rgb"]).all())
                        metrics = oracle.metrics(actual["rgb"], expected["rgb"])
                        baseline_metrics = oracle.metrics(
                            baseline_actual["rgb"], expected["rgb"])
                        wrapper_metrics = oracle.metrics(
                            actual["rgb"], baseline_actual["rgb"])
                        self.assertLessEqual(metrics["max_normalized"], 1e-4,
                                             {"stage2": metrics, "baseline": baseline_metrics,
                                              "wrapper": wrapper_metrics})
                        # The complete Tone graph adds float32 operations even
                        # when Tone is reset. Keep this parity bound tight while
                        # allowing the measured few-ppm accumulation at HDR values.
                        self.assertLessEqual(wrapper_metrics["max_normalized"], 3e-6,
                                             {"wrapper": wrapper_metrics,
                                              "stage2": metrics, "baseline": baseline_metrics})
                        np.testing.assert_array_equal(actual["alpha"], values[:, 3])
                        np.testing.assert_array_equal(actual["valid"], baseline_actual["valid"])
                        np.testing.assert_array_equal(actual["saturated"], 0.)
                        np.testing.assert_array_equal(actual["saturated"], baseline_actual["saturated"])
                        if context == "compositor":
                            np.testing.assert_array_equal(actual["embedded_alpha"], values[:, 3])
                    finally:
                        fixture.close()

    def test_compositor_achromatic_handoff_preserves_energy_guard_diagnostics(self):
        values = cases.rgba(256)

        def energy_guard(graph, appearance):
            return graph.output_guard(graph.hk_guard(graph.guard_input(appearance)))

        # Exercise the smallest supported total Tone span and the opposite
        # anchor/fit/peak extremes, including signed and HDR source pixels.
        for tone in (
            ToneSettings(input_nits=(2., 2.1, 2.2, 10., 100.), fit=2., peak_nits=4000.),
            ToneSettings(input_nits=(0., 50., 250., 1000., 10000.), fit=-2., peak_nits=500.),
        ):
            linear = LinearSettings(exposure=6.)
            cases.assert_ui_settings(linear, tone)
            with self.subTest(tone=tone):
                prepared = complete_prepared(linear, tone)
                builder = partial(build_stage2_group, diagnostics=True)
                with patch("color_tools.template_build.stage2_graph.compositor_stage2_output_guard",
                           side_effect=energy_guard):
                    baseline = NativeFixture(prepared, values, "compositor", builder=builder)
                try:
                    expected = baseline.render()
                finally:
                    baseline.close()
                fixture = NativeFixture(prepared, values, "compositor", builder=builder)
                try:
                    actual = fixture.render()
                    self.assertLessEqual(oracle.metrics(actual["rgb"], expected["rgb"])
                                         ["max_normalized"], 3e-6)
                    for field in ("valid", "saturated", "alpha", "embedded_alpha"):
                        np.testing.assert_array_equal(actual[field], expected[field])
                    np.testing.assert_array_equal(actual["saturated"], 0.)
                    self.assertTrue(np.isfinite(actual["margin"]).all())
                    self.assertTrue(np.all(actual["margin"] > 0.))
                finally:
                    fixture.close()

    def test_incomplete_preparation_cannot_allocate_a_partial_tree(self):
        before_groups = {group.as_pointer() for group in bpy.data.node_groups}
        before_images = {image.as_pointer() for image in bpy.data.images}
        with self.assertRaisesRegex(ValueError, "complete Tone table and boundary"):
            build_stage2_group(prepare())
        self.assertEqual(before_groups, {group.as_pointer() for group in bpy.data.node_groups})
        self.assertEqual(before_images, {image.as_pointer() for image in bpy.data.images})


if __name__ == "__main__":
    unittest.main()
