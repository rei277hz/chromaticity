"""The bundled Stack shader matches the build-time native equations."""

import asyncio
import re
import unittest

import numpy as np

from color_tools.kernel.settings import Settings
from color_tools.template_build.lut_shader_emitter import grade_source as emit_grade_source
from color_tools.lut_shader import grade_source
from color_tools.runtime.grade_preparation import GradePreparer


class LUTShaderTests(unittest.TestCase):
    def test_first_default_grade_loads_the_complete_compute_shader(self):
        preparer = GradePreparer()
        try:
            prepared = asyncio.run(preparer.prepare(Settings()))
            source = grade_source(prepared.boundary)
            expected = emit_grade_source(prepared.boundary)
            self.assert_shader_equivalent(expected, source)
        finally:
            preparer.close()
        self.assertIn("vec3 grade_value(vec3 input_value)", source)
        self.assertIn("texelFetch(grade_parameters", source)
        self.assertIn("sample_boundary", source)

    def assert_shader_equivalent(self, expected, actual):
        """Keep generated topology/text exact while allowing native float repr drift."""
        number = re.compile(
            r"(?<![A-Za-z0-9_])[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?(?![A-Za-z0-9_])"
        )
        expected_numbers = [float(value) for value in number.findall(expected)]
        actual_numbers = [float(value) for value in number.findall(actual)]
        self.assertEqual(
            number.sub("<number>", expected).strip(),
            number.sub("<number>", actual).strip(),
        )
        self.assertEqual(len(expected_numbers), len(actual_numbers))
        np.testing.assert_allclose(actual_numbers, expected_numbers, rtol=1e-12, atol=1e-15)

    def test_shader_comparison_keeps_identifier_and_operation_changes_visible(self):
        self.assert_shader_equivalent("float v17 = 0.0;", "float v17 = 2e-16;\n")
        for changed in ("float v18 = 0.0;", "float v17 = 1.0;",
                        "float v17 += 0.0;"):
            with self.subTest(changed=changed), self.assertRaises(AssertionError):
                self.assert_shader_equivalent("float v17 = 0.0;", changed)


if __name__ == "__main__":
    unittest.main()
