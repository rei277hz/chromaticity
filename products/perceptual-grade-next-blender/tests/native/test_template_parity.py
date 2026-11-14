"""Production template outputs agree with their build-time graph emitters."""

import unittest

import numpy as np

from color_tools.kernel.node_templates import instantiate_grade, instantiate_stack
from color_tools.template_build.stage2_graph import build_stage2_group
from color_tools.template_build.stack_graph import build_stack_group
from tools.perceptual_grade.reports import cases
from tools.perceptual_grade.reports.native import NativeFixture

from .template_support import (
    SPACES, complete_prepared, production_fixture_builder, stack_prepared,
)


class TemplateParityTests(unittest.TestCase):
    def assert_parity(self, prepared, context, emitter, instantiate, values):
        results = []
        for builder in (emitter, instantiate):
            fixture = NativeFixture(prepared, values, context,
                                    builder=production_fixture_builder(builder))
            try:
                results.append(fixture.render())
            finally:
                fixture.close()
        expected, actual = results
        np.testing.assert_allclose(actual["rgb"], expected["rgb"], rtol=2e-6, atol=2e-6)
        np.testing.assert_array_equal(actual["alpha"], values[:, 3])
        np.testing.assert_array_equal(actual["alpha"], expected["alpha"])
        if context == "compositor":
            np.testing.assert_array_equal(actual["embedded_alpha"], values[:, 3])

    def test_grade_production_rgb_and_alpha_match_emitter(self):
        values = cases.rgba(64)
        for space in SPACES:
            for adjusted in (False, True):
                prepared = complete_prepared(space, adjusted=adjusted)
                for context in ("shader", "compositor"):
                    with self.subTest(space=space, adjusted=adjusted, context=context):
                        self.assert_parity(prepared, context, build_stage2_group,
                                           instantiate_grade, values)

    def test_stack_production_rgb_and_alpha_match_emitter(self):
        values = cases.rgba(64)
        for space in SPACES:
            for size in (33, 65):
                prepared = stack_prepared(space, size, scale=0.8)
                for context in ("shader", "compositor"):
                    with self.subTest(space=space, size=size, context=context):
                        self.assert_parity(prepared, context, build_stack_group,
                                           instantiate_stack, values)


if __name__ == "__main__":
    unittest.main()
