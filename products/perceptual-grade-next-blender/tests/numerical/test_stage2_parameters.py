"""Whole-snapshot storage and numerical obligations for Grade role bundles."""

from dataclasses import replace
import math
import unittest

import numpy as np

from color_tools.kernel import (
    ColorSettings, LinearSettings, ToneSettings, WebSettings, prepare,
    prepare_tone,
)
from color_tools.kernel.boundary import prepare_boundary
from color_tools.kernel.settings import SPACES
from color_tools.kernel.stage2_parameters import (
    ADAPTANCE_ANCHORS_SLOT, ADAPTANCE_SUPPORT_SLOT,
    MATRIX_BLUE_SLOT, MATRIX_NEUTRAL_SLOT, MATRIX_RED_SLOT,
    COLOR_FLAGS_SLOT, COLOR_ROLE_FIELDS, COLOR_SCALARS_SLOT, PARAMETER_BUNDLE_SIGNATURE,
    PARAMETER_CONTENT_SIGNATURE, PARAMETER_ROLE_SHAPES, PARAMETER_ROLES,
    PARAMETER_SCHEMA, PARAMETER_SHAPE, PreparedParameters,
    LAST_PARAMETER_SLOT, TONE_CHROMA_GAIN_SLOT, TONE_CHROMA_TONE_SLOT,
    TONE_DOMAIN_SLOT, TONE_JET_COUNT, TONE_SCALARS_SLOT,
    bind_parameter_bank, parameter_bundle_receipt_matches, parameter_bundle_signature,
    parameter_content_signature,
    parameter_image_matches,
    prepare_parameters, set_parameter_bundle_signature,
    OUTPUT_MATRIX_ROW_SLOTS,
)
from color_tools.kernel.stage2_bindings import (
    PARAMETER_IMAGE, PARAMETER_ROLE, PARAMETER_ROLE_BINDING,
)


def complete(linear=LinearSettings(), tone=ToneSettings(), space="Linear Rec.709",
             color=ColorSettings()):
    return prepare(linear, tone, space, color=color, full_fields=True)


class PixelBuffer:
    def __init__(self, values):
        self.values = np.asarray(values, dtype=np.float32)

    def foreach_get(self, output):
        output[:] = self.values.ravel()


class Image(dict):
    def __init__(self, pointer, role, values):
        super().__init__()
        self.pointer = pointer
        self.live = True
        self.is_dirty = False
        self.packed_file = object()
        self.values = np.asarray(values, dtype=np.float32)
        self.pixels = PixelBuffer(self.values)
        self.size = (self.values.shape[1], self.values.shape[0])
        self[PARAMETER_IMAGE] = PARAMETER_SCHEMA
        self[PARAMETER_ROLE] = role
        self[PARAMETER_CONTENT_SIGNATURE] = parameter_content_signature(self.values)

    def as_pointer(self):
        return self.pointer if self.live else 0


def image_bundle(start, offset):
    images = {
        role: Image(start + index, role, np.full(shape, offset + index, np.float32))
        for index, (role, shape) in enumerate(PARAMETER_ROLE_SHAPES.items())
    }
    primary = images["parameter"]
    for role, image in images.items():
        if role != "parameter":
            primary[PARAMETER_ROLE_BINDING + role] = image
    signatures = {role: image[PARAMETER_CONTENT_SIGNATURE]
                  for role, image in images.items()}
    bind_parameter_bank(images, signatures)
    return primary, images


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
        fields = {role: values.copy() for role, values in result.fields.items()}
        copied = PreparedParameters(source, fields=fields)
        source.fill(7.)
        np.testing.assert_array_equal(copied.pixels, result.pixels)
        for role, values in fields.items():
            values.fill(7.)
            np.testing.assert_array_equal(copied.fields[role], result.fields[role])
        with self.assertRaises(TypeError):
            copied.fields["web"] = fields["web"]

    def test_complete_role_bundle_is_owned_immutable_and_matches_authored_settings(self):
        settings = ColorSettings(
            adaptance=((1., -1.),) * 4,
            web=WebSettings(hue_degrees=((2.,) * 6,) * 4,
                            log_chroma=((.25,) * 6,) * 4,
                            log_scale=((-.5,) * 6,) * 4),
        )
        result = prepare_parameters(complete(color=settings))
        self.assertEqual(tuple(result.roles), PARAMETER_ROLES)
        self.assertEqual(set(result.fields), set(COLOR_ROLE_FIELDS))
        self.assertEqual(result.roles["parameter"].shape, PARAMETER_SHAPE)
        for role in PARAMETER_ROLES[1:]:
            values = result.roles[role]
            self.assertEqual(values.shape, PARAMETER_ROLE_SHAPES[role])
            self.assertEqual(values.dtype, np.float32)
            self.assertFalse(values.flags.writeable)
            with self.assertRaises(ValueError):
                values.flags.writeable = True
        flags = result.pixels[0, COLOR_FLAGS_SLOT]
        np.testing.assert_array_equal(flags, (0., 0., 1., 1.))
        scalars = result.pixels[0, COLOR_SCALARS_SLOT]
        np.testing.assert_array_equal(scalars[:2], (0., .25))
        self.assertGreater(float(result.roles["web"].max()), 0.)

    def test_prepared_parameters_rejects_missing_mixed_or_malformed_role_fields(self):
        result = prepare_parameters(complete())
        with self.assertRaisesRegex(ValueError, "every Color role"):
            PreparedParameters(result.pixels)
        missing = dict(result.fields)
        missing.pop("web_toe")
        with self.assertRaisesRegex(ValueError, "every Color role"):
            PreparedParameters(result.pixels, fields=missing)
        mixed = dict(result.fields)
        mixed["web"] = result.fields["web_toe"]
        with self.assertRaisesRegex(ValueError, "Invalid Grade parameter field: web"):
            PreparedParameters(result.pixels, fields=mixed)
        nonfinite = dict(result.fields)
        nonfinite["adaptance"] = np.array(result.fields["adaptance"], copy=True)
        nonfinite["adaptance"][0, 0, 0] = np.nan
        with self.assertRaisesRegex(ValueError, "Invalid Grade parameter field: adaptance"):
            PreparedParameters(result.pixels, fields=nonfinite)

    def test_adaptance_cardinal_support_is_packed_without_epsilon_thresholds(self):
        settings = ColorSettings(adaptance=((1e-20, 0.), (0., 0.), (0., -1.), (0., 0.)))
        prepared = complete(color=settings)
        pixels = prepare_parameters(prepared).pixels[0]
        np.testing.assert_array_equal(pixels[ADAPTANCE_ANCHORS_SLOT],
                                      np.asarray(prepared.color.anchors, np.float32))
        np.testing.assert_array_equal(pixels[ADAPTANCE_SUPPORT_SLOT], (1., 0., 1., 0.))

    def test_parameter_image_receipt_rejects_mixed_role_generation(self):
        first, first_roles = image_bundle(100, 0.)
        second, second_roles = image_bundle(200, 10.)
        self.assertTrue(parameter_image_matches(first))
        self.assertTrue(parameter_image_matches(second))

        first[PARAMETER_ROLE_BINDING + "web"] = second_roles["web"]
        self.assertFalse(parameter_image_matches(first))
        first[PARAMETER_ROLE_BINDING + "web"] = first_roles["web"]

        self.assertEqual(len(first[PARAMETER_BUNDLE_SIGNATURE]), 64)
        first_roles["web"][PARAMETER_CONTENT_SIGNATURE] = "0" * 64
        self.assertFalse(parameter_image_matches(first))

    def test_bundle_signature_update_stamps_all_roles_after_staging(self):
        primary, images = image_bundle(300, 0.)
        signatures = {role: image[PARAMETER_CONTENT_SIGNATURE]
                      for role, image in images.items()}
        receipt = set_parameter_bundle_signature(primary, signatures)
        self.assertEqual(primary[PARAMETER_BUNDLE_SIGNATURE], receipt)
        self.assertTrue(all(image[PARAMETER_BUNDLE_SIGNATURE] == receipt
                            for image in images.values()))
        for image in images.values():
            image.pixels.foreach_get = lambda _output: self.fail("metadata check read pixels")
        self.assertTrue(parameter_bundle_receipt_matches(primary))
        signatures["web"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "contents do not match"):
            set_parameter_bundle_signature(primary, signatures)

    def test_bundle_signature_is_ordered_by_role_and_requires_complete_receipts(self):
        signatures = {role: str(index) * 64
                      for index, role in enumerate(PARAMETER_ROLES)}
        expected = parameter_bundle_signature(signatures)
        self.assertEqual(parameter_bundle_signature(dict(reversed(tuple(signatures.items())))),
                         expected)
        signatures.pop("web_toe")
        with self.assertRaisesRegex(ValueError, "every role"):
            parameter_bundle_signature(signatures)

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

    def test_working_space_output_adapter_is_packed_as_three_rows(self):
        for space in SPACES:
            with self.subTest(space=space):
                prepared = complete(space=space)
                pixels = prepare_parameters(prepared).pixels[0]
                boundary = prepared.boundary or prepare_boundary(
                    prepared.fl, prepared.aw, prepared.gamma,
                )
                output_matrix = prepared.from_cones @ boundary.inverse
                np.testing.assert_array_equal(
                    pixels[OUTPUT_MATRIX_ROW_SLOTS, :3],
                    output_matrix.astype(np.float32),
                )

    def test_packed_tone_reproduces_existing_runtime_evaluation(self):
        settings = ToneSettings(input_nits=(8., 40., 235., 1150.), fit=2.)
        prepared = complete(tone=settings)
        pixels = prepare_parameters(prepared).pixels[0]
        table = replace(prepared.table, jets=pixels[:TONE_JET_COUNT, :3],
                        domain=float(pixels[TONE_DOMAIN_SLOT, 0]))
        black, span, slope, high = pixels[TONE_SCALARS_SLOT]
        h = np.r_[np.linspace(0., 600., 4097), np.geomspace(1e-8, 1e7, 257)].astype(np.float32)
        t = np.maximum(np.float32(0), h / np.float32(100) / span)
        z = np.minimum(t / np.float32(table.domain), np.float32(1))
        actual = np.float32(100) * (slope * t + table.evaluate(z))
        actual = np.where(t == np.float32(1), np.float32(100) * high, actual)
        np.testing.assert_array_equal(actual, prepared.tone.remap_table(h))

    def test_stage2_packs_unified_chroma_and_black_compression(self):
        tone = ToneSettings(black_compression_nits=.125, muted_gain=-1., vivid_gain=1.,
                            saturation_crossover=.2, shadow_chroma=-.75,
                            highlight_chroma=1.25, tone_crossover=52.)
        prepared = complete(tone=tone)
        pixels = prepare_parameters(prepared).pixels[0]
        self.assertGreater(float(pixels[TONE_SCALARS_SLOT, 0]), 0.)
        np.testing.assert_array_equal(pixels[TONE_CHROMA_GAIN_SLOT],
                                      np.float32((.5, 2., .4 / (35. / 75.), 1.)))
        np.testing.assert_array_equal(pixels[TONE_CHROMA_TONE_SLOT], (-.75, 1.25, 52., 1.))

    def test_raw_saturation_crossover_and_zero_knee(self):
        settings = ToneSettings(muted_gain=-1., vivid_gain=1.)
        self.assertEqual(settings.saturation_crossover, .45)
        ja = np.array((-70., 45.))
        for crossover in (0., .45, 1.):
            with self.subTest(crossover=crossover):
                prepared = complete(tone=replace(settings, saturation_crossover=crossover))
                low, high, knee, active = prepare_parameters(prepared).pixels[0, TONE_CHROMA_GAIN_SLOT]
                self.assertEqual((low, high, active), (.5, 2., 1.))
                self.assertAlmostEqual(float(knee) * (35. / 75.), 2. * crossover, places=6)
                chroma = np.abs(ja) * (crossover if crossover else .3)
                gain = prepared.tone.chroma_gain(ja, chroma)
                expected = 1. if crossover else 2.
                np.testing.assert_allclose(gain, expected, rtol=1e-14)
                output = chroma * gain
                np.testing.assert_allclose(output * prepared.tone.chroma_gain(ja, output, invert=True),
                                           chroma, rtol=1e-14)

    def test_rejects_incomplete_or_incompatible_snapshot(self):
        prepared = complete()
        for invalid in (
            replace(prepared, tone=prepare_tone()),
            replace(prepared, tone=replace(prepared.tone, table=replace(prepared.table, cells=2048))),
            replace(prepared, linear=replace(prepared.linear, linear_to_cones=np.full((3, 3), np.inf))),
            replace(prepared, linear=replace(prepared.linear, linear_to_cones=np.full((3, 3), 2e38))),
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
        pixels[0, LAST_PARAMETER_SLOT + 1, 0] = 1.
        with self.assertRaisesRegex(ValueError, "reserved"):
            PreparedParameters(pixels)
        with self.assertRaisesRegex(ValueError, "schema"):
            PreparedParameters(prepare_parameters(prepared).pixels, schema=PARAMETER_SCHEMA + 1)


if __name__ == "__main__":
    unittest.main()
