"""Complete parameterized Grade trees, guarded parity and alpha preservation."""

from dataclasses import replace
from functools import partial
import os
import unittest
from unittest import mock

import bpy
import numpy as np

from color_tools.kernel import ColorSettings, LinearSettings, ToneSettings, prepare, prepare_tone
from color_tools.kernel.boundary import prepare_boundary
from color_tools.template_build import graph as graph_module
from color_tools.template_build.graph import Graph, build_group
from color_tools.template_build.guard_graph import compositor_stage2_output_guard
from color_tools.template_build.stage2_graph import build_stage2_group
from tools.perceptual_grade.reports import cases, full_cases, oracle
from tools.perceptual_grade.reports.native import NativeFixture


def complete_prepared(linear=LinearSettings(), tone=ToneSettings(), space="Linear Rec.709",
                      color=ColorSettings()):
    base = prepare(linear, tone, space, color=color)
    return replace(base, tone=prepare_tone(tone, full_fields=True),
                   boundary=prepare_boundary(base.fl, base.aw, base.gamma))


class ProtectedCompositorGraph(Graph):
    """Isolate parameter binding from the choice of arithmetic/carrier path."""

    _color_source_squares_safe = False
    _color_safe = False
    _color_energy_scale = 4096.

    def _color_bounded(self, *_names, **_kwargs):
        return False

    def output_guard(self, state):
        return compositor_stage2_output_guard(self, state)


def build_protected_compositor_group(prepared, tree_type):
    if tree_type != "CompositorNodeTree":
        raise ValueError("Protected parity baseline requires a Compositor tree")
    with mock.patch.object(graph_module, "Graph", ProtectedCompositorGraph):
        return build_group(prepared, tree_type)


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
                    self.assertEqual(len(built.images), 11)
                    self.assertTrue(all(image.packed_file for image in built.images))
                    parameter_images = tuple(
                        image for image in built.images
                        if image.get("_perceptual_grade_parameter_schema")
                    )
                    self.assertEqual(len(parameter_images), 10)
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
            selected = os.environ.get("PG_STAGE2_SECTION")
            contexts = (selected,) if selected in {"shader", "compositor"} else ("shader", "compositor")
            for context in contexts:
                with self.subTest(space=space, context=context):
                    baseline = NativeFixture(prepared, values, context, threads=2,
                                             builder=build_group)
                    try:
                        baseline_actual = baseline.render()
                    finally:
                        baseline.close()
                    fixture = NativeFixture(prepared, values, context, threads=2,
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

    def test_compositor_extreme_tone_parameter_graph_matches_generic_full_graph(self):
        values = full_cases.rgba(count=256)
        color = full_cases.guard_before_scale_grade()
        # Exercise both ends of the Tone operating range on a varying signed
        # and HDR source, comparing both graph adapters with the independent
        # complete-grade oracle.
        for tone in (
            ToneSettings(input_nits=(2., 2.1, 2.2, 10., 100.), fit=2., peak_nits=4000.),
            ToneSettings(input_nits=(0., 50., 250., 1000., 10000.), fit=-2., peak_nits=500.),
        ):
            linear = LinearSettings(exposure=6.)
            cases.assert_ui_settings(linear, tone)
            with self.subTest(tone=tone):
                prepared = complete_prepared(linear, tone, color=color)
                builder = partial(build_stage2_group, diagnostics=True)
                expected = oracle.evaluate_full(
                    values[:, :3], linear, tone, color, "Linear Rec.709",
                )
                baseline = NativeFixture(prepared, values, "compositor", threads=2,
                                         builder=build_group)
                try:
                    reference = baseline.render()
                finally:
                    baseline.close()
                # The generic emitter specializes bounded settings, whereas
                # the fixed parameter tree always uses protected arithmetic
                # and a scaled energy carrier. Compare binding precision on
                # the same arithmetic path; independently gate all three
                # outputs against the reference below.
                protected_fixture = NativeFixture(
                    prepared, values, "compositor", threads=2,
                    builder=build_protected_compositor_group)
                try:
                    protected = protected_fixture.render()
                finally:
                    protected_fixture.close()
                fixture = NativeFixture(prepared, values, "compositor", threads=2,
                                        builder=builder)
                try:
                    actual = fixture.render()
                    result = oracle.metrics(actual["rgb"], expected["rgb"])
                    baseline_result = oracle.metrics(reference["rgb"], expected["rgb"])
                    protected_result = oracle.metrics(protected["rgb"], expected["rgb"])
                    wrapper_result = oracle.metrics(actual["rgb"], protected["rgb"])
                    evidence = {"parameterized": result, "generic": baseline_result,
                                "protected": protected_result, "parity": wrapper_result}
                    for metrics in (result, baseline_result, protected_result):
                        self.assertLessEqual(metrics["max_normalized"], 1e-4, evidence)
                    self.assertLessEqual(wrapper_result["max_normalized"], 5e-6,
                                         evidence)
                    for field in ("valid", "saturated", "alpha", "embedded_alpha"):
                        np.testing.assert_array_equal(actual[field], reference[field])
                        np.testing.assert_array_equal(actual[field], protected[field])
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


def load_tests(loader, _tests, _pattern):
    # Full fixed-topology graphs compile much more slowly than active-only
    # reference graphs. Preserve every method across bounded Buck actions.
    sections = {
        "interface": (
            "test_complete_reset_and_active_trees_preserve_the_product_interface",
            "test_incomplete_preparation_cannot_allocate_a_partial_tree",
        ),
        "shader": ("test_guarded_shader_and_compositor_match_independent_reference",),
        "compositor": ("test_guarded_shader_and_compositor_match_independent_reference",),
        "extreme": (
            "test_compositor_extreme_tone_parameter_graph_matches_generic_full_graph",
        ),
    }
    selected = os.environ.get("PG_STAGE2_SECTION", "interface")
    if selected not in sections:
        raise ValueError("Unknown parameterized Grade test section: " + selected)
    if set(loader.getTestCaseNames(Stage2Tests)) != {
            name for methods in sections.values() for name in methods}:
        raise AssertionError("Every parameterized Grade test must belong to a Buck section")
    return unittest.TestSuite(Stage2Tests(name) for name in sections[selected])


if __name__ == "__main__":
    unittest.main()
