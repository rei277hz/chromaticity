"""Shipped fixed Color topology agrees with the independent Grade oracle."""

import os
import unittest

import numpy as np

from color_tools.kernel import prepare
from color_tools.kernel.boundary import prepare_boundary
from color_tools.kernel.node_templates import instantiate_grade
from tools.perceptual_grade.reports import cases, full_cases, oracle
from tools.perceptual_grade.reports.native import NativeFixture

from .template_support import production_fixture_builder


class ColorTemplateTests(unittest.TestCase):
    def test_active_and_extreme_color_controls_in_every_working_space(self):
        context = os.environ["PG_COLOR_TEMPLATE_CONTEXT"]
        if context not in ("shader", "compositor"):
            raise ValueError("PG_COLOR_TEMPLATE_CONTEXT must select shader or compositor")
        corpus = [row for row in full_cases.grades()
                  if row[0] in ("all_active", "guard_before_scale", "saturation",
                                "all_active_saturation")]
        corpus += [row for row in full_cases.ui_boundaries()
                   if row[0] in ("all_families_max", "all_families_max_active_tail")]
        self.assertCountEqual([row[0] for row in corpus], (
            "all_active", "guard_before_scale", "saturation", "all_active_saturation",
            "all_families_max", "all_families_max_active_tail",
        ))
        defaults = prepare()
        boundary = prepare_boundary(defaults.fl, defaults.aw, defaults.gamma)
        builder = production_fixture_builder(instantiate_grade)
        for space in cases.SPACES:
            values = full_cases.rgba(space, 256)
            for name, linear, tone, color in corpus:
                with self.subTest(context=context, space=space, case=name):
                    prepared = prepare(linear, tone, space, color=color,
                                       boundary=boundary, full_fields=True)
                    fixture = NativeFixture(prepared, values, context, threads=2,
                                            builder=builder)
                    try:
                        actual = fixture.render()
                        expected = oracle.evaluate_full(values[:, :3], linear,
                                                        tone, color, space)
                        metrics = oracle.metrics(actual["rgb"], expected["rgb"])
                        self.assertLessEqual(metrics["max_normalized"], 1e-4, metrics)
                        self.assertTrue(np.isfinite(actual["rgb"]).all())
                        np.testing.assert_array_equal(actual["alpha"], values[:, 3])
                        if context == "compositor":
                            np.testing.assert_array_equal(actual["embedded_alpha"],
                                                          values[:, 3])
                        black = np.all(values[:, :3] == 0., axis=-1)
                        np.testing.assert_array_equal(actual["rgb"][black], 0.)
                    finally:
                        fixture.close()
        if context == "compositor":
            self.assert_nonfinite_inputs_fail_closed(boundary, builder)

    def assert_nonfinite_inputs_fail_closed(self, boundary, builder):
        values = np.asarray(((.2, .3, .4, .25), (np.inf, .3, .4, .5),
                             (.2, np.nan, .4, .75), (.2, .3, -np.inf, 1.),
                             (0., 0., 0., .125)), dtype=np.float32)
        prepared = prepare(boundary=boundary, full_fields=True)
        fixture = NativeFixture(prepared, values, "compositor", threads=2, builder=builder)
        try:
            actual = fixture.render()
        finally:
            fixture.close()
        np.testing.assert_array_equal(actual["rgb"][1:4],
                                      np.tile((1., 0., 1.), (3, 1)))
        np.testing.assert_array_equal(actual["alpha"], values[:, 3])
        np.testing.assert_array_equal(actual["embedded_alpha"], values[:, 3])
        np.testing.assert_array_equal(actual["rgb"][-1], 0.)
        self.assertTrue(np.isfinite(actual["rgb"]).all())
        expected = oracle.evaluate_full(values[:1, :3], prepared.linear.settings,
                                        prepared.tone.settings, prepared.color.settings,
                                        prepared.space)["rgb"]
        self.assertLessEqual(oracle.metrics(actual["rgb"][:1], expected)["max_normalized"],
                             1e-4)


if __name__ == "__main__":
    unittest.main()
