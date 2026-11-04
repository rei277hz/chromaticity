"""Whole-snapshot storage and numerical obligations for the Stage 2 atlas."""

from dataclasses import replace
import math
import unittest

import numpy as np

from color_tools.kernel import (
    ColorSettings, LinearSettings, ToneSettings, prepare, prepare_tone,
)
from color_tools.kernel.stage2_parameters import (
    MATRIX_BLUE_SLOT, MATRIX_NEUTRAL_SLOT, MATRIX_RED_SLOT,
    PARAMETER_SCHEMA, PARAMETER_SHAPE, PreparedParameters,
    TONE_DOMAIN_SLOT, TONE_JET_COUNT, TONE_SCALARS_SLOT, prepare_parameters,
)


def complete(linear=LinearSettings(), tone=ToneSettings()):
    prepared = prepare(linear, tone)
    return replace(prepared, tone=prepare_tone(tone, full_fields=True))


class Stage2ParameterTests(unittest.TestCase):
    def test_snapshot_owns_immutable_storage(self):
        result = prepare_parameters(complete())
        self.assertEqual(result.schema, PARAMETER_SCHEMA)
        self.assertEqual(result.pixels.shape, PARAMETER_SHAPE)
        self.assertEqual(result.pixels.nbytes, 8192)
        self.assertFalse(result.pixels.flags.writeable)
        with self.assertRaises(ValueError):
            result.pixels.flags.writeable = True
        source = result.pixels.copy()
        copied = PreparedParameters(source)
        source.fill(7.)
        np.testing.assert_array_equal(copied.pixels, result.pixels)

    def test_matrix_preserves_the_existing_neutral_decomposition(self):
        prepared = complete(LinearSettings(
            exposure=.7, source_xy=(.34567, .3585), balance=(.4, -.2),
            spread=(45., -50.), heading=(-38., 72.),
        ))
        pixels = prepare_parameters(prepared).pixels[0]
        matrix = prepared.linear_to_cones
        expected_columns = (matrix[:, 0], matrix[:, 2], tuple(
            math.fsum(float(value) for value in row) for row in matrix
        ))
        for slot, expected in zip(
                (MATRIX_RED_SLOT, MATRIX_BLUE_SLOT, MATRIX_NEUTRAL_SLOT), expected_columns):
            np.testing.assert_array_equal(pixels[slot, :3], np.asarray(expected, np.float32))
        neutrals = np.array((0., .001, .18, 1., 1024.), np.float32)
        native = (pixels[MATRIX_RED_SLOT, :3] * np.zeros((len(neutrals), 1), np.float32)
                  + pixels[MATRIX_BLUE_SLOT, :3] * np.zeros((len(neutrals), 1), np.float32)
                  + pixels[MATRIX_NEUTRAL_SLOT, :3] * neutrals[:, None])
        expected = np.asarray(expected_columns[-1], np.float32) * neutrals[:, None]
        np.testing.assert_array_equal(native, expected)

    def test_packed_tone_reproduces_existing_runtime_evaluation(self):
        settings = ToneSettings(input_nits=(.2, 8., 40., 235., 1150.), fit=2.)
        prepared = complete(tone=settings)
        pixels = prepare_parameters(prepared).pixels[0]
        table = replace(prepared.table, jets=pixels[:TONE_JET_COUNT, :3],
                        domain=float(pixels[TONE_DOMAIN_SLOT, 0]))
        black, span, slope, high = pixels[TONE_SCALARS_SLOT]
        h = np.r_[np.linspace(0., 600., 4097), np.geomspace(1e-8, 1e7, 257)].astype(np.float32)
        t = np.maximum(np.float32(0), (h / np.float32(100) - black) / span)
        z = np.minimum(t / np.float32(table.domain), np.float32(1))
        actual = np.float32(100) * (slope * t + table.evaluate(z))
        actual = np.where(t == np.float32(1), np.float32(100) * high, actual)
        np.testing.assert_array_equal(actual, prepared.tone.remap_table(h))

    def test_rejects_incomplete_or_incompatible_snapshot(self):
        prepared = complete()
        for invalid in (
            replace(prepared, tone=prepare_tone()),
            replace(prepared, tone=replace(prepared.tone, table=replace(prepared.table, cells=2048))),
            replace(prepared, linear=replace(prepared.linear, linear_to_cones=np.full((3, 3), np.inf))),
            replace(prepared, linear=replace(prepared.linear, linear_to_cones=np.full((3, 3), 2e38))),
            replace(prepared, color=replace(prepared.color, settings=ColorSettings(global_gain=.2))),
        ):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                prepare_parameters(invalid)
        pixels = prepare_parameters(prepared).pixels.copy()
        pixels[0, 0, 0] = np.nan
        with self.assertRaisesRegex(ValueError, "nonfinite"):
            PreparedParameters(pixels)
        pixels = prepare_parameters(prepared).pixels.copy()
        pixels[0, TONE_DOMAIN_SLOT, 3] = 0.
        with self.assertRaisesRegex(ValueError, "alpha"):
            PreparedParameters(pixels)
        pixels = prepare_parameters(prepared).pixels.copy()
        pixels[0, TONE_DOMAIN_SLOT + 1, 0] = 1.
        with self.assertRaisesRegex(ValueError, "reserved"):
            PreparedParameters(pixels)
        with self.assertRaisesRegex(ValueError, "schema"):
            PreparedParameters(prepare_parameters(prepared).pixels, schema=PARAMETER_SCHEMA + 1)


if __name__ == "__main__":
    unittest.main()
