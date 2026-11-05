"""Pixel identity must come from the whole graded palette."""

from importlib.resources import files
import runpy
import unittest


HELPERS = runpy.run_path(str(files("tools.perceptual_grade.reports") /
                             "shader_display_timing_runner.py"))
palette_matches = HELPERS["palette_matches"]
classify_palette = HELPERS["classify_palette"]


class ShaderDisplayMatchTests(unittest.TestCase):
    def test_every_swatch_and_channel_must_match(self):
        wanted = [[8, 8, 8], [35, 35, 35], [91, 91, 91], [152, 152, 152]]
        observed = [[9, 8, 7], [35, 35, 35], [93, 91, 89], [152, 153, 154]]
        self.assertTrue(palette_matches(observed, wanted))
        observed[-1][-1] = 155
        self.assertFalse(palette_matches(observed, wanted))
        self.assertFalse(palette_matches(wanted[:3], wanted))
        self.assertFalse(palette_matches([[True, 8, 8], *wanted[1:]], wanted))
        self.assertFalse(palette_matches([[float("nan"), 8, 8], *wanted[1:]], wanted))

    def test_ambiguous_and_partial_palettes_cannot_identify_settings(self):
        first = [[20, 20, 20]] * 4
        second = [[40, 40, 40]] * 4
        self.assertEqual(classify_palette(first, {"first": first, "second": second}), "first")
        self.assertIsNone(classify_palette([*first[:2], *second[2:]],
                                          {"first": first, "second": second}))
        self.assertIsNone(classify_palette(first, {"first": first, "same_pixels": first}))
        self.assertIsNone(classify_palette(first, {}))


if __name__ == "__main__":
    unittest.main()
