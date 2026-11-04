"""Generate a populated Stack shader through the shared native equations."""

import asyncio
import unittest

from color_tools.kernel.settings import Settings
from color_tools.lut_shader import grade_source
from color_tools.runtime.grade_preparation import GradePreparer


class LUTShaderTests(unittest.TestCase):
    def test_first_default_grade_generates_the_complete_compute_shader(self):
        preparer = GradePreparer()
        try:
            prepared = asyncio.run(preparer.prepare(Settings()))
            source = grade_source(prepared.boundary)
        finally:
            preparer.close()
        self.assertIn("vec3 grade_value(vec3 input_value)", source)
        self.assertIn("texelFetch(grade_parameters", source)
        self.assertIn("sample_boundary", source)


if __name__ == "__main__":
    unittest.main()
