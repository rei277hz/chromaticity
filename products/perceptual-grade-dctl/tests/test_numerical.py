"""Float32 Resolve entry points against independent float64 reference stages."""
import unittest

import numpy as np
from color_tools.perceptual_grade_reference.grading import Color, ColorSettings, Tone, ToneSettings
from color_tools.perceptual_grade_reference.model import rgb_matrix
from tests.support import cone_reference as cone, dctl_reference as reference
from tests.support import jc_global_shape, jc_prototype, jc_surface, oracle
from tests.support.dctl import (
    ANCHOR_CENTER_PROTOTYPES, GAIN_PROTOTYPES, GLOBAL_SHAPE_PROTOTYPES, OVERLAP_PROTOTYPES,
    PROTOTYPES, STAGES, STANDALONE_STAGES, SURFACE_PROTOTYPES, TONE_FIT_LINEAR_GAIN_PROTOTYPES,
    TONE_FIT_PROTOTYPES, TONE_FIT_UNIFIED_CHROMA_PROTOTYPES, UNIFIED_CHROMA_STAGES,
    WARP_QUADRATIC_SCALE_PROTOTYPES,
)

SAMPLES = np.array([[.25, .18, .04], [.15, .07, .42], [.5, .8, .2], [3., 1., .8],
                    [-.09, -.07, -.04], [1.e-6, 2.e-6, 5.e-6]], dtype=np.float32)
JC_CONTROLS = dict(peakNits=2, globalChromaGain=.15, jSaturationCenter=.3,
                   jSaturationWidth=.65, cSaturationCenter=.7, cSaturationWidth=.15)
for row, j, c in zip("SMWH", (.15, -.8, 1.2, .25), (.15, .3, -.4, .1)):
    JC_CONTROLS[f"tone{row}JContrast"] = j
    JC_CONTROLS[f"tone{row}CContrast"] = c

WARP_CONTROLS = {f"web{family}{row}{handle}": value
                 for row in range(4) for handle in range(6)
                 for family, value in (("hue", 3 * (handle - 2) + row),
                                       ("chroma", .08 * (handle - 2) - row * .05),
                                       ("scale", .10 * (row - 1) + handle * .02))}
WARP_CONTROLS |= {f"tone{row}Adaptance{axis}": value for i, row in enumerate("SMWH")
                  for axis, value in (("A", i + 1.), ("B", -2.))}

class NumericalTests(unittest.TestCase):
    def assert_stage_close(self, actual, expected):
        ratio = np.max(abs(actual - expected), axis=-1) / reference.tolerance(expected)
        worst = np.argmax(ratio)
        self.assertLessEqual(ratio[worst], 1., (actual[worst], expected[worst], ratio[worst]))

    def compare(self, stage, inputs, controls):
        inputs = np.asarray(inputs, dtype=np.float32)
        expected = reference.apply(stage, inputs, controls)
        actual = oracle.run(stage, inputs, controls)
        self.assert_stage_close(actual, expected)
        return actual

    def test_reset_preserves_every_float_channel(self):
        pixels = np.asarray([[0., -0., 0.], [-2048, 3, 128], [-1, -2, -3], [2048, 1024, 4096],
                             [1.e-25, -1.e-25, 1.e12], [np.finfo("f4").max, 1., 0.]], dtype="f4")
        for stage in ("linear", *PROTOTYPES, *SURFACE_PROTOTYPES):
            with self.subTest(stage=stage):
                actual = oracle.run(stage, pixels)
                np.testing.assert_array_equal(actual.view("u4"), pixels.view("u4"))
        wire = np.array([[0., -0., 0.], [399., -399., 71.], [-1., -2., -3.],
                         [1.e-25, -1.e-25, 1.e-12]], dtype="f4")
        for stage in (*STANDALONE_STAGES, "warp", *OVERLAP_PROTOTYPES, *ANCHOR_CENTER_PROTOTYPES, *GAIN_PROTOTYPES,
                      *GLOBAL_SHAPE_PROTOTYPES, *TONE_FIT_PROTOTYPES, *TONE_FIT_LINEAR_GAIN_PROTOTYPES,
                      *UNIFIED_CHROMA_STAGES,
                      *WARP_QUADRATIC_SCALE_PROTOTYPES):
            with self.subTest(stage=stage):
                actual = oracle.run(stage, wire)
                np.testing.assert_array_equal(actual.view("u4"), wire.view("u4"))

    def test_active_stages_preserve_signed_and_hdr_domain(self):
        signed_hdr = np.array([-13., 2048.])[:, None] * reference.WHITE
        signed_hdr *= [1.02, 1., .98]
        for stage, controls in (("linear", {"globalExposure": 1}),
                                ("lgg", {"toneHCGain": .04, "toneHJGain": .02}),
                                ("lgg_nonlog", {"toneHCGain": .04, "toneHJGain": .02}),
                                ("lgg_pivot", {"toneHCGain": .04, "toneHJGain": .02,
                                                "saturationPivot": .2})):
            with self.subTest(stage=stage):
                actual = self.compare(stage, signed_hdr, controls)
                self.assertLess(np.max(actual[0]), 0.)
                self.assertGreater(np.min(actual[1]), 1024.)
                self.assertGreater(np.max(abs(actual - signed_hdr)), .01)

    def test_linear_and_signed_tone(self):
        self.compare("linear", SAMPLES, dict(srcWhite=3, globalExposure=.5,
                                             le=.15, be=-.2, ls=-30, bs=5, la=6, ba=-4))
        wire = np.vstack([cone.from_xyz(SAMPLES), [210., 238., 263.], [-341., -293., -314.]])
        for index in range(4):
            with self.subTest(peak=index):
                self.compare("tone", wire, dict(peakNits=index, inputShadows=4,
                                                 inputMidtones=42, remapFit=2))
        self.compare("tone", wire, dict(inputBlack=1., inputShadows=4.))

    def test_integrated_tone_matches_standalone_at_full_hk_with_c_reset(self):
        wire = np.vstack([cone.from_xyz(np.vstack([SAMPLES, 2048. * SAMPLES])),
                          [210., 238., 263.], [-341., -293., -314.]]).astype("f4")
        for peak in range(4):
            for calibration in ({}, dict(inputShadows=1.2, inputMidtones=57., inputWhite=180.,
                                         inputHighlights=1680., remapFit=2)):
                with self.subTest(peak=peak, calibration=calibration):
                    settings = dict(calibration, peakNits=peak)
                    actual = self.compare("jc_tone_fit_unified_chroma", wire, settings)
                    self.assert_stage_close(actual, oracle.run("tone", wire, settings))
                    np.testing.assert_array_equal(actual, oracle.run("jc_tone_fit", wire, settings))

    def test_standard_tone_jc_matches_unified_chroma_prototype(self):
        wire = np.vstack([cone.from_xyz(np.vstack([SAMPLES, 2048. * SAMPLES])),
                          cone.pack([-75., 55., 350.], [19., -65., 40.], [-4., 11., -90.]),
                          [11., -22., 0.], [389., 390., 388.]]).astype("f4")
        settings = dict(blackCompression=1.1, inputShadows=2.4, inputMidtones=42.,
                        inputWhite=225., inputHighlights=1600., remapFit=1, peakNits=2,
                        cMutedGain=-1.3, cVividGain=1.7, cSaturationCrossover=.22,
                        shadowChroma=1.5, highlightChroma=-1.3, cToneCrossover=.35)
        for direction in (0, 1):
            with self.subTest(direction=direction):
                controls = dict(settings, direction=direction)
                standard = self.compare("tone_jc", wire, controls)
                prototype = oracle.run("jc_tone_fit_unified_chroma", wire, controls)
                np.testing.assert_array_equal(standard, prototype)

    def test_integrated_tone_applies_global_chroma_first(self):
        wire = cone.from_xyz(np.vstack([SAMPLES, 20. * SAMPLES])).astype("f4")
        chroma = dict(cContrast=1.3, cPivot=.37, cMuted=.7, cVivid=-.5,
                      shadowChroma=-1.2, highlightChroma=1.5, cToneCrossover=33.)
        tone = dict(inputMidtones=72., inputWhite=203., inputHighlights=1600., remapFit=3)
        c_only = oracle.run("jc_global_shape", wire, chroma)
        self.assert_stage_close(self.compare("jc_tone_fit", wire, chroma), c_only)
        adjusted = self.compare("jc_tone_fit", wire, chroma | tone)
        self.assert_stage_close(adjusted, oracle.run("tone", c_only, tone))

    def test_unified_chroma_uses_corrected_lightness(self):
        stage = "tone_jc"
        tone = dict(blackCompression=.4, inputMidtones=62., inputHighlights=1630., remapFit=2)
        target_ja = np.array([24., 45., 80.])
        target = cone.pack(target_ja, [7., 8., 9.], [11., 12., 13.]).astype("f4")
        source = self.compare(stage, target, dict(tone, direction=1))
        chroma = dict(shadowChroma=-3., highlightChroma=3., cToneCrossover=.45)
        adjusted = self.compare(stage, source, tone | chroma)
        chart = cone.enter(adjusted)
        target_chart = cone.enter(target)
        np.testing.assert_allclose(chart.ja, target_ja, atol=2.e-4)
        target_chroma = np.linalg.norm(target_chart.q[:, 1:], axis=-1)
        output_chroma = np.linalg.norm(chart.q[:, 1:], axis=-1)
        self.assertLess(output_chroma[0], target_chroma[0])
        self.assertAlmostEqual(output_chroma[1], target_chroma[1], delta=.0002)
        self.assertGreater(output_chroma[2], target_chroma[2])

        gains = dict(chroma, cMutedGain=-.5, cVividGain=1.5, cSaturationCrossover=.5)
        adjusted = self.compare(stage, source, tone | gains)
        np.testing.assert_allclose(cone.enter(adjusted).ja, target_ja, atol=2.e-4)

    def test_integrated_tone_hk_influence_blends_ray_preserving_gains(self):
        wire = cone.pack([-50., -50., 44., 44.], [0., -32., 0., 44.], [0., 24., 0., -33.]).astype("f4")
        inputs = cone.enter(wire)
        settings = dict(inputShadows=1., inputMidtones=90., inputWhite=155.,
                        inputHighlights=1800., remapFit=2)
        outputs = []
        for influence in (0., .35, 1.):
            with self.subTest(influence=influence):
                after = cone.enter(self.compare("jc_tone_fit", wire, dict(settings, hkInfluence=influence)))
                np.testing.assert_array_equal(np.sign(after.ja), np.sign(inputs.ja))
                input_ray = np.column_stack([inputs.ja, inputs.q[:, 1:]])
                output_ray = np.column_stack([after.ja, after.q[:, 1:]])
                scale = np.linalg.norm(output_ray, axis=-1) / np.linalg.norm(input_ray, axis=-1)
                np.testing.assert_allclose(output_ray, input_ray * scale[:, None], atol=3.e-6, rtol=3.e-5)
                outputs.append(after.ja)
        j_only, mixed, full_hk = outputs
        np.testing.assert_allclose(j_only[::2], j_only[1::2], atol=3.e-4, rtol=0.)
        self.assertGreater(np.min(abs(full_hk[::2] - full_hk[1::2])), .05)
        np.testing.assert_allclose(mixed, .65 * j_only + .35 * full_hk, atol=3.e-4, rtol=0.)

        zero_j = cone.pack(0., 24., -32.).astype("f4").reshape(1, 3)
        zero_input = cone.enter(zero_j)
        for influence in (0., .35, 1.):
            zero_output = cone.enter(self.compare("jc_tone_fit", zero_j, dict(settings, hkInfluence=influence)))
            self.assertAlmostEqual(zero_output.ja[0], 0., delta=2.e-5)
            self.assertGreater(np.dot(zero_output.q[0, 1:], zero_input.q[0, 1:]), 0.)

    def test_integrated_black_compression_orders_dark_ramp_and_keeps_highlight_target(self):
        settings = dict(inputShadows=2., inputMidtones=28., inputWhite=195.,
                        inputHighlights=1500., peakNits=2, blackCompression=1.8)
        calibration = Tone(reference.tone_settings(settings))
        dark = np.geomspace(1.e-5, 12., 80)
        heights = np.r_[-100. * calibration.source[-1], -dark[::-1], 0., dark, 100. * calibration.source[-1]]
        wire = cone.pack(heights, 0., 0.).astype("f4")
        forward = self.compare("jc_tone_fit", wire, settings)
        result = cone.enter(forward).ja
        self.assertTrue(np.all(np.diff(result) > 0.))
        self.assertEqual(result[len(dark) + 1], 0.)
        np.testing.assert_allclose(result[[0, -1]], [-calibration.high, calibration.high], atol=3.e-4, rtol=0.)
        baseline = cone.enter(oracle.run("jc_tone_fit", wire, dict(settings, blackCompression=0.))).ja
        self.assertGreater(np.max(abs(result[1:-1] - baseline[1:-1])), .05)
        self.assert_stage_close(oracle.run("jc_tone_fit", forward, dict(settings, direction=1)), wire)

    def test_integrated_tone_round_trips_signed_hdr_and_zero_lightness(self):
        wire = np.vstack([cone.from_xyz(np.vstack([SAMPLES, 2048. * SAMPLES])),
                          cone.pack([-75., 55., 350.], [19., -65., 40.], [-4., 11., -90.]),
                          [11., -22., 0.], [389., 390., 388.]]).astype("f4")
        black = np.array([[0., -0., 0.]], dtype="f4")
        settings = dict(blackCompression=1.1, inputShadows=2.4, inputMidtones=42., inputWhite=225.,
                        inputHighlights=1600., remapFit=1, peakNits=2,
                        shadowChroma=1.5, highlightChroma=-1.3, cToneCrossover=35.)
        for stage in (*TONE_FIT_PROTOTYPES, *TONE_FIT_LINEAR_GAIN_PROTOTYPES, *TONE_FIT_UNIFIED_CHROMA_PROTOTYPES):
            if stage in TONE_FIT_UNIFIED_CHROMA_PROTOTYPES:
                shape = dict(cMutedGain=-1.3, cVividGain=1.7, cSaturationCrossover=.22,
                             cToneCrossover=.35)
                influences = ({},)
            else:
                shape = dict(cContrast=-1.3, cPivot=.22, cMuted=-.65, cVivid=.85)
                influences = tuple(dict(hkInfluence=value) for value in (0., .37, 1.))
            for influence in influences:
                with self.subTest(stage=stage, **influence):
                    forward_settings = dict(settings, **shape, **influence)
                    inverse_settings = dict(forward_settings, direction=1)
                    result = self.compare(stage, wire, forward_settings)
                    self.assert_stage_close(self.compare(stage, result, inverse_settings), wire)
                    restored = self.compare(stage, wire, inverse_settings)
                    self.assert_stage_close(self.compare(stage, restored, forward_settings), wire)
                    for active in (forward_settings, inverse_settings):
                        np.testing.assert_array_equal(oracle.run(stage, black, active).view("u4"), black.view("u4"))

    def test_unified_tone_hits_highlight_target_and_orders_signed_rays(self):
        stage = "jc_tone_fit_unified_chroma"
        calibration = dict(inputShadows=2.4, inputMidtones=42., inputWhite=225., inputHighlights=1600.)
        for peak in range(4):
            tone = Tone(reference.tone_settings(dict(calibration, peakNits=peak)))
            heights = 100. * tone.source[1:]
            neighbor_heights = (heights[:, None] * np.array([.9999, 1., 1.0001])).ravel()
            neutral = cone.pack(neighbor_heights, 0., 0.).astype("f4")
            fixed_ray = np.unique(np.r_[np.geomspace(1.e-4, 450., 80), heights])
            signed_j = np.r_[-fixed_ray[::-1], 0., fixed_ray]
            radius = .25 * abs(signed_j)
            chromatic = cone.pack(signed_j, .8 * radius, -.6 * radius).astype("f4")
            wire = np.vstack([neutral, chromatic])
            for fit in range(-2, 3):
                with self.subTest(peak=peak, fit=fit):
                    settings = dict(calibration, peakNits=peak, remapFit=fit, blackCompression=1.8)
                    forward = self.compare(stage, wire, settings)
                    output = cone.enter(forward)
                    mapped = output.ja[:len(neutral)]
                    self.assertAlmostEqual(mapped[-2], 100. * tone.target[-1], delta=3.e-4)
                    self.assertTrue(np.all(np.diff(mapped) > 0.))
                    ray_j = output.ja[len(neutral):]
                    self.assertTrue(np.all(np.diff(ray_j) > 0.))
                    np.testing.assert_allclose(output.q[len(neutral):, 1], .2 * abs(ray_j), rtol=4.e-5, atol=1.e-5)
                    np.testing.assert_allclose(output.q[len(neutral):, 2], -.15 * abs(ray_j), rtol=4.e-5, atol=1.e-5)
                    self.assert_stage_close(self.compare(stage, forward, dict(settings, direction=1)), wire)

    def test_unified_tone_rejects_out_of_range_fit(self):
        wire = cone.from_xyz(SAMPLES[:1])
        for fit in (-3, 3):
            for direction in (0, 1):
                with self.subTest(fit=fit, direction=direction):
                    settings = dict(remapFit=fit, direction=direction, inputMidtones=42.)
                    actual = oracle.run("jc_tone_fit_unified_chroma", wire, settings)
                    np.testing.assert_array_equal(actual, [[400., 0., 400.]])

    def test_integrated_linear_gain_changes_only_tonal_chroma_fade(self):
        stage = "jc_tone_fit_linear_gain"
        crossover = 30.
        for height in (0., -10., crossover, 2. * crossover):
            with self.subTest(height=height):
                knee = (35. / (75. * 9.)) * abs(height)
                chroma = np.array([0., .01, .1, 1., 3., 10., 30., 100.]) if knee == 0. else (
                    knee * np.array([0., .01, .1, 1., 10., 100.]))
                wire = cone.pack(height, chroma, 0.).astype("f4")
                shape = dict(cContrast=1.3, cPivot=.37, cMuted=.7, cVivid=-.5)
                np.testing.assert_array_equal(oracle.run(stage, wire, shape), oracle.run("jc_tone_fit", wire, shape))
                settings = dict(shadowChroma=-2., highlightChroma=2., cToneCrossover=crossover)
                adjusted = self.compare(stage, wire, settings)
                self.assert_stage_close(self.compare(stage, adjusted, dict(settings, direction=1)), wire)
                baseline = self.compare("jc_tone_fit", wire, settings)
                before = cone.enter(wire)
                result = cone.enter(adjusted)
                np.testing.assert_allclose(result.ja, height, atol=1.e-4, rtol=0.)
                input_chroma = np.linalg.norm(before.q[:, 1:], axis=-1)
                output_chroma = np.linalg.norm(result.q[:, 1:], axis=-1)
                offset = abs(height) / crossover - 1.
                amount = (-2. if offset < 0. else 2.) * jc_surface.smoothstep(abs(offset))
                fade = np.divide(input_chroma, input_chroma + knee,
                                 out=np.ones_like(input_chroma), where=input_chroma + knee > 0.)
                linear_expected = input_chroma * (1. + (np.exp2(amount) - 1.) * fade)
                log_expected = input_chroma * np.exp2(amount * fade)
                np.testing.assert_allclose(output_chroma, linear_expected, rtol=8.e-4, atol=2.e-5)
                baseline_chroma = np.linalg.norm(cone.enter(baseline).q[:, 1:], axis=-1)
                np.testing.assert_allclose(baseline_chroma, log_expected, rtol=8.e-4, atol=2.e-5)
                self.assertTrue(np.all(np.diff(output_chroma) > 0.))

    def test_integrated_linear_gain_matches_standalone_at_selected_highlight(self):
        height = 120.
        amount = 1.25
        crossover = 45.
        knee = (35. / (75. * 9.)) * height
        chroma = knee * np.array([0., .05, .25, 1., 4., 20.])
        wire = cone.pack(height, .8 * chroma, .6 * chroma).astype("f4")
        integrated = dict(highlightChroma=amount, cToneCrossover=crossover)
        standalone = {f"tone{row}CGain": amount for row in "SMWH"}
        combined = self.compare("jc_tone_fit_linear_gain", wire, integrated)
        separate = self.compare("jc_linear_gain", wire, standalone)
        self.assert_stage_close(combined, separate)
        np.testing.assert_allclose(cone.enter(combined).q, cone.enter(separate).q, rtol=3.e-4, atol=3.e-5)

    def test_unified_chroma_gain_at_crossover_and_tails(self):
        stage = "jc_tone_fit_unified_chroma"
        height = 75.
        for crossover, expected_ratio in ((None, .2625), (.99, 3.1907)):
            position = .5 if crossover is None else crossover
            saturation = jc_global_shape.saturation_at_position(position)
            self.assertAlmostEqual(saturation, expected_ratio, places=4)
            anchor = height * saturation
            radius = anchor * np.array([.001, .1, 1., 2., 10., 1000.])
            wire = cone.pack(height, .8 * radius, -.6 * radius).astype("f4")
            for muted, vivid in ((-1., 1.), (2., -2.), (.5, 1.5)):
                settings = dict(cMutedGain=muted, cVividGain=vivid)
                if crossover is not None:
                    settings["cSaturationCrossover"] = crossover
                forward = self.compare(stage, wire, settings)
                ab = cone.enter(forward).q[:, 1:]
                mapped = np.linalg.norm(ab, axis=-1)
                self.assertTrue(np.all(np.diff(mapped) > 0.))
                np.testing.assert_allclose(ab, mapped[:, None] * [.8, -.6], rtol=3.e-4, atol=.0003)
                np.testing.assert_allclose(mapped[[0, -1]] / radius[[0, -1]], np.exp2([muted, vivid]), rtol=.01)
                self.assertAlmostEqual(mapped[2], anchor * np.exp2((muted + vivid) / 2.), delta=.0003)
                if (muted, vivid) == (-1., 1.):
                    self.assertAlmostEqual(mapped[3], anchor * 2.5, delta=.0003)
                self.assert_stage_close(self.compare(stage, forward, dict(settings, direction=1)), wire)

    def test_unified_chroma_crossover_sweep(self):
        stage = "jc_tone_fit_unified_chroma"
        height = np.array([75., -42., 130., -600.])
        radius = abs(height) * [.4, 1., 2., 4.]
        wire = cone.pack(height, -.6 * radius, .8 * radius).astype("f4")
        for muted, vivid in ((-4., 4.), (4., -4.), (.75, .75)):
            settings = dict(cMutedGain=muted, cVividGain=vivid)
            sweep = np.stack([self.compare(stage, wire, dict(settings, cSaturationCrossover=p))
                              for p in np.linspace(0., .99, 21)])
            mapped = np.linalg.norm(cone.enter(sweep).q[..., 1:], axis=-1)
            if muted == vivid:
                np.testing.assert_allclose(mapped, np.broadcast_to(np.exp2(muted) * radius, mapped.shape),
                                           rtol=5.e-5)
                np.testing.assert_array_equal(sweep, np.broadcast_to(sweep[0], sweep.shape))
            else:
                self.assertTrue(np.all((muted - vivid) * np.diff(mapped, axis=0) > 0.))

    def test_unified_chroma_gray_zero_lightness_and_reset(self):
        stage = "jc_tone_fit_unified_chroma"
        gray = np.array([[0., -0., 0.], [22., 22., 22.], [-37., -37., -37.]], dtype="f4")
        axis = np.array([[11., -22., 0.], [-13., 26., 0.]], dtype="f4")
        wire = np.vstack([gray, axis, cone.from_xyz(SAMPLES)]).astype("f4")
        tone = dict(blackCompression=1.1, inputMidtones=55.,
                    shadowChroma=-1., highlightChroma=1.5)
        for pivot in (0., .99):
            settings = dict(cMutedGain=2., cVividGain=-1., cSaturationCrossover=pivot)
            for direction in (0, 1):
                active = dict(settings, direction=direction)
                result = self.compare(stage, axis, active)
                if pivot == 0.:
                    input_chart = cone.enter(axis)
                    gain = 2. if direction else .5
                    expected_axis = cone.pack(input_chart.ja, input_chart.q[:, 1] * gain,
                                              input_chart.q[:, 2] * gain).astype("f4")
                    self.assert_stage_close(result, expected_axis)
                else:
                    opposite = dict(settings, direction=1 - direction)
                    self.assert_stage_close(self.compare(stage, result, opposite), axis)
                np.testing.assert_array_equal(oracle.run(stage, gray, active).view("u4"), gray.view("u4"))
                shared = dict(tone, direction=direction)
                np.testing.assert_array_equal(
                    oracle.run(stage, wire, dict(shared, cSaturationCrossover=pivot)),
                    oracle.run(stage, wire, shared),
                )
        chromatic = cone.pack(np.array([65., -65.]), [4., 24.], [-10., 10.]).astype("f4")
        active = dict(cMutedGain=2., cVividGain=-1., cSaturationCrossover=0.)
        forward = self.compare(stage, chromatic, active)
        np.testing.assert_allclose(cone.enter(forward).q[:, 1:],
                                   .5 * cone.enter(chromatic).q[:, 1:], rtol=3.e-4, atol=.0003)
        self.assert_stage_close(self.compare(stage, forward, dict(active, direction=1)), chromatic)

        for value in (-4.01, 4.01):
            for name in ("cMutedGain", "cVividGain", "shadowChroma", "highlightChroma"):
                with self.subTest(control=name, value=value):
                    np.testing.assert_array_equal(oracle.run(stage, axis[:1], {name: value}),
                                                  [[400., 0., 400.]])
        for name, limits in (("cSaturationCrossover", (-.01, 1.)), ("cToneCrossover", (.09, 1.41))):
            for value in limits:
                with self.subTest(control=name, value=value):
                    np.testing.assert_array_equal(oracle.run(stage, axis[:1], {name: value}),
                                                  [[400., 0., 400.]])

    def test_unified_chroma_round_trips_combined_gain_limits(self):
        stage = "jc_tone_fit_unified_chroma"
        wire = cone.pack([8., -24., 45., -115., 160.],
                         [1.5, -8., 21., -38., 80.], [2., 3., -4., 25., -60.]).astype("f4")
        for stops, crossover in ((-4., .1), (4., 1.4)):
            with self.subTest(stops=stops, crossover=crossover):
                forward = dict(cMutedGain=stops, cVividGain=-stops, shadowChroma=stops,
                               highlightChroma=-stops, cSaturationCrossover=.5, cToneCrossover=crossover,
                               blackCompression=.3, inputMidtones=45.)
                inverse = dict(forward, direction=1)
                self.assert_stage_close(self.compare(stage, self.compare(stage, wire, forward), inverse), wire)
                self.assert_stage_close(self.compare(stage, self.compare(stage, wire, inverse), forward), wire)

    def test_input_output_keep_signed_hdr_and_use_the_physical_chart(self):
        neutral = np.array([[-2048.], [2048.]]) * reference.WHITE
        xyz = np.vstack([SAMPLES, neutral])
        wire = self.compare("input", xyz, {})
        output = self.compare("output", wire, {})
        self.assertLess(np.max(output[-2]), -1024.)
        self.assertGreater(np.min(output[-1]), 1024.)
        self.assert_stage_close(output[-2:], neutral)
        self.compare("output", [[210., 238., 263.], [-341., -293., -314.], [390., 389., 388.]], {})

    def test_output_repairs_final_signed_energy(self):
        wire = cone.pack([-30., -30., -5., 30.], [35., 0., 35., 35.], 0.).astype("f4")
        unguarded = cone.to_xyz(wire)
        output = self.compare("output", wire, {})
        self.assertTrue(np.all(np.max(abs(output[[0, 2]] - unguarded[[0, 2]]), axis=-1) > 1.e-4))
        self.assert_stage_close(output[[1, 3]], unguarded[[1, 3]])

        # Export repair would collapse negative energy here. Warp carries it through.
        warped = oracle.run("warp", wire[[0, 2]], {f"webchroma{i}{j}": 1. for i in range(4) for j in range(6)})
        self.assertTrue(np.all(warped != wire[[0, 2]]))
        np.testing.assert_allclose(cone.enter(warped).ja, [-30., -5.], atol=1.e-4)

    def test_output_saturation_compression_uses_repaired_physical_appearance(self):
        chromatic = cone.response([30., 30., -65., -5.], [2., 24., 16., 27.], [1., -18., -12., 21.])
        neutral = cone.from_xyz(np.array([-2048., 2048.])[:, None] * cone.WHITE)
        # The weighted achromatic response 2R + G + .05B is exactly zero.
        wire = np.vstack((chromatic, neutral, [1., -2., 0.], [0., 0., 0.])).astype("f4")
        baseline = self.compare("output", wire, {})
        settings = dict(saturationKnee=.2, saturationCeiling=.65)
        np.testing.assert_array_equal(self.compare("output", wire, settings), baseline)
        compressed = self.compare("output", wire, dict(settings, saturationCompression=1))
        unchanged = [0, 4, 5, 7]
        np.testing.assert_array_equal(compressed[unchanged], baseline[unchanged])
        np.testing.assert_array_equal(compressed[[3, 6]], np.zeros((2, 3)))
        self.assertTrue(np.all(np.max(abs(baseline[[3, 6]]), axis=-1) > 1.e-6))

        source = cone.appearance(wire[1:3])
        result = cone.appearance(cone.from_xyz(compressed[1:3]))
        before = np.linalg.norm(source.q[:, 1:], axis=-1)
        after = np.linalg.norm(result.q[:, 1:], axis=-1)
        np.testing.assert_allclose(result.ja, source.ja, atol=2.e-3)
        np.testing.assert_allclose(result.q[:, 1:] / after[:, None],
                                   source.q[:, 1:] / before[:, None], atol=2.e-4)
        self.assertTrue(np.all(after < before))
        self.assertTrue(np.all(after / abs(result.ja) < settings["saturationCeiling"]))

    def test_output_saturation_compression_diagnoses_invalid_controls(self):
        wire = cone.from_xyz(SAMPLES[:1])
        magenta = rgb_matrix("Linear Rec.709") @ [1., 0., 1.]
        for settings in ({"saturationKnee": float("nan")}, {"saturationCeiling": float("inf")},
                         {"saturationKnee": -.01}, {"saturationCeiling": 8.01},
                         {"saturationKnee": 1.}, {"saturationKnee": 2.},
                         {"saturationCompression": 2}):
            with self.subTest(settings=settings):
                np.testing.assert_allclose(oracle.run("output", wire, settings, x=60),
                                           magenta[None, :], rtol=1.e-6)

    def test_prototype_wheels_match_reference_at_every_peak(self):
        settings = {"lightnessFit": 2, "chromaFit": -1}
        for i, row in enumerate("SMWH", 1):
            settings.update({f"tone{row}JLift": (i - 2.5) * .8, f"tone{row}JGamma": i * -.06,
                             f"tone{row}JGain": i * .05, f"tone{row}CLift": i * -.04,
                             f"tone{row}CGamma": i * .08, f"tone{row}CGain": (i - 2.5) * .15})
        neutral = np.array([[-4.], [.18], [1.], [2048.]]) * reference.WHITE
        inputs = np.vstack((SAMPLES, .03 * SAMPLES, 20 * SAMPLES, neutral))
        for stage in PROTOTYPES:
            controls = settings | ({"saturationPivot": .2} if stage == "lgg_pivot" else {})
            for peak in range(4):
                with self.subTest(stage=stage, peak=peak):
                    self.compare(stage, inputs, dict(controls, peakNits=peak))

    def test_prototype_black_and_neutral_behavior(self):
        black = np.array([[0., -0., 0.]], dtype="f4")
        gray = np.array([[-.18], [.0155], [.18], [1.]]) * reference.WHITE
        for stage in PROTOTYPES:
            with self.subTest(stage=stage):
                both = {"toneSJLift": 9., "toneMCLift": .5, "toneMCGain": -.3}
                np.testing.assert_array_equal(oracle.run(stage, black, both).view("u4"), black.view("u4"))
                lightness = self.compare(stage, gray, {"toneMJLift": 5.})
                self.assertGreater(lightness[2, 1], gray[2, 1])
                chroma = self.compare(stage, gray, {"toneMCLift": 1., "toneMCGain": -.25})
                self.assert_stage_close(chroma, gray)

    def test_prototype_default_pivot_matches_and_variants_differ(self):
        controls = {"toneSCGain": .25, "toneWCGamma": -.5, "toneHJLift": 12.}
        samples = np.vstack((SAMPLES, 4 * SAMPLES))
        baseline = self.compare("lgg", samples, controls)
        pivot_default = self.compare("lgg_pivot", samples, controls)
        np.testing.assert_array_equal(pivot_default.view("u4"), baseline.view("u4"))
        for stage, settings in (("lgg_nonlog", controls),
                                ("lgg_pivot", dict(controls, saturationPivot=.08))):
            with self.subTest(stage=stage):
                actual = self.compare(stage, samples, settings)
                self.assertGreater(np.max(abs(actual - baseline)), .001)

    def test_prototype_chroma_order_at_fixed_lightness_and_weights(self):
        ja = 75.
        weights = (.1, .5, .35, .05)
        cases = (("lgg", jc_prototype.PIVOT), ("lgg_nonlog", jc_prototype.PIVOT),
                 ("lgg_pivot", .05), ("lgg_pivot", 2.))
        for stage, pivot in cases:
            with self.subTest(stage=stage, pivot=pivot):
                chroma = np.sort(np.r_[0., ja * pivot, ja * pivot * np.geomspace(1.e-5, 1.e5, 1024)])
                # Maximum Lift and Gamma produce the steepest downward gain slope.
                lift = gamma = (2., 2., 2., 2.)
                gain = (.4, -.8, .2, -.1)
                x, actual = oracle.chroma_curve(stage, chroma, ja, pivot, lift, gamma, gain, weights)
                expected_x = jc_prototype.axis(chroma, ja, pivot, stage == "lgg_nonlog")
                expected = chroma * jc_prototype.chroma_scale(expected_x, lift, gamma, gain, weights)
                np.testing.assert_allclose(x, expected_x, atol=2.e-7)
                np.testing.assert_allclose(actual, expected, rtol=3.e-6)
                self.assertTrue(np.all(np.diff(actual) > 0.))
                self.assertEqual(x[np.searchsorted(chroma, ja * pivot)], .5)
                x_on_axis, zero = oracle.chroma_curve(stage, [0., 1.], 0., pivot, lift, gamma, gain, weights)
                np.testing.assert_array_equal(x_on_axis, [0., 1.])
                self.assertEqual(zero[0], 0.)

    def test_prototype_midtones_chroma_gamma_and_gain_increase_contrast(self):
        ja, pivot = 55., jc_prototype.PIVOT
        chroma = ja * pivot * np.array([.05, 25.])
        zero = (0., 0., 0., 0.)
        for stage in PROTOTYPES:
            with self.subTest(stage=stage):
                _, adjusted = oracle.chroma_curve(stage, chroma, ja, pivot, zero, (0., -.4, 0., 0.),
                                                  (0., .12, 0., 0.), (0., 1., 0., 0.))
                self.assertLess(adjusted[0], chroma[0])
                self.assertGreater(adjusted[1], chroma[1])

    def test_surface_cubic_anchors_and_bounded_blends(self):
        amounts = np.array([-1., 2., -.5, .75])
        fractions = np.array([.25, .5, .75])
        for peak, nits in enumerate(reference.PEAKS):
            with self.subTest(peak=nits):
                anchors = 100. * Tone(ToneSettings(peak_nits=nits)).target[1:]
                intervals = anchors[:-1, None] + np.diff(anchors)[:, None] * fractions
                heights = np.r_[0., anchors, 2. * anchors[-1], intervals.flatten()]
                samples = [(height, 10., 75.) for height in heights]
                actual, _, _ = oracle.surface_response(samples, amounts, peak=peak)
                np.testing.assert_array_equal(actual[:6], np.r_[amounts[0], amounts, amounts[-1]])
                expected = jc_surface.anchor(heights, anchors, amounts)
                np.testing.assert_allclose(actual, expected, atol=3.e-6, rtol=0.)
                low = np.minimum(amounts[:-1], amounts[1:])[:, None]
                high = np.maximum(amounts[:-1], amounts[1:])[:, None]
                interior = actual[6:].reshape(intervals.shape)
                self.assertTrue(np.all((low < interior) & (interior < high)))

    def test_surface_ordered_chroma_maps_and_inverse(self):
        ja = 75.
        gain = .4
        ratios = np.sort(np.r_[np.geomspace(1.e-8, 1.e8, 1024), 1., 1. + np.linspace(-.001, .001, 101)[1::2]])
        for center, width in ((.05, .05), (.5, .5), (.95, 1.)):
            pivot = (35. / 75.) * ja * center / (1. - center)
            chroma = pivot * ratios
            samples = [(75., c, ja) for c in chroma]
            for amount in (-2., 2.):
                with self.subTest(center=center, width=width, amount=amount):
                    _, _, stops = oracle.surface_response(samples, [amount] * 4, center, width)
                    expected = jc_surface.c_response(chroma, np.full_like(chroma, ja), center, width,
                                                     np.full_like(chroma, amount))
                    np.testing.assert_allclose(stops, expected, atol=6.e-6, rtol=0.)
                    mapped = chroma * np.exp2(stops + gain)
                    self.assertTrue(np.all(np.diff(mapped) > 0.))
                    self.assertAlmostEqual(stops[np.searchsorted(ratios, 1.)], 0., places=5)
                    without_gain = mapped / np.exp2(gain)
                    _, _, inverse_stops = oracle.surface_response([(75., c, ja) for c in without_gain],
                                                                  [-amount] * 4, center, width)
                    np.testing.assert_allclose(without_gain * np.exp2(inverse_stops), chroma, rtol=5.e-6)

    def test_surface_gray_and_zero_achromatic_limits(self):
        _, j, c = oracle.surface_response([(75., 0., 0.), (75., 0., 75.), (75., 35., 0.),
                                           (75., 1.e-7, 75.)], [1.25] * 4)
        np.testing.assert_array_equal(j[:3], [0., 0., 1.])
        np.testing.assert_array_equal(c[:3], [0., 0., 1.25])
        self.assertLess(abs(j[3]), 1.e-12)
        self.assertLess(c[3], -1.2)

    def test_surface_shape_only_settings_and_active_black_pass_through(self):
        black = np.array([[0., -0., 0.]], dtype="f4")
        pixels = np.vstack((black, SAMPLES))
        controls = dict(peakNits=3, jSaturationCenter=.1, jSaturationWidth=.9,
                        cSaturationCenter=.8, cSaturationWidth=.05)
        np.testing.assert_array_equal(oracle.run("surface", pixels, controls).view("u4"), pixels.view("u4"))
        active = dict(controls, toneSJContrast=20., toneSCContrast=2., globalChromaGain=3.)
        np.testing.assert_array_equal(oracle.run("surface", black, active).view("u4"), black.view("u4"))

    def test_surface_signed_hdr_and_independent_families(self):
        controls = dict(peakNits=2, globalChromaGain=.08, jSaturationCenter=.25,
                        cSaturationCenter=.7, jSaturationWidth=.65, cSaturationWidth=.1)
        for row, j, c in zip("SMWH", (.15, -1.0, 1.0, .12), (.15, .2, -.12, .05)):
            controls[f"tone{row}JContrast"] = j
            controls[f"tone{row}CContrast"] = c
        hdr = (np.array([-13., 2048.])[:, None] * reference.WHITE * [1.02, 1., .98]).astype("f4")
        samples = np.vstack((SAMPLES, .03 * SAMPLES, 20. * SAMPLES, hdr))
        result = self.compare("surface", samples, controls)
        self.assertLess(np.max(result[-2]), 0.)
        self.assertGreater(np.min(result[-1]), 1024.)
        self.assertGreater(np.max(np.abs(result[-2:] - hdr)), .01)

        for active, inactive in (("J", "C"), ("C", "J")):
            with self.subTest(active=active):
                only_active = {name: value for name, value in controls.items()
                               if not name.endswith(f"{inactive}Contrast") and name != "globalChromaGain"}
                result = self.compare("surface", SAMPLES, only_active)
                inactive_shape = {f"{inactive.lower()}SaturationCenter": .55,
                                  f"{inactive.lower()}SaturationWidth": .75}
                same = oracle.run("surface", SAMPLES, only_active | inactive_shape)
                np.testing.assert_array_equal(same.view("u4"), result.view("u4"))
                for shape, value in (("Center", .55), ("Width", .8)):
                    changed = self.compare("surface", SAMPLES, only_active | {f"{active.lower()}Saturation{shape}": value})
                    self.assertGreater(np.max(np.abs(changed - result)), 1.e-6)

    def test_jc_j_stretch_keeps_signed_lightness_order(self):
        # The earlier additive contrast folded near the white/highlights blend.
        ja = np.r_[-np.linspace(62., 142., 401)[::-1], 0., np.linspace(62., 142., 401)]
        wire = cone.pack(ja, 50., 0.).astype("f4")
        controls = dict(peakNits=0, toneWJContrast=2., toneHJContrast=-2.,
                        jSaturationCenter=.05, jSaturationWidth=.05)
        adjusted = oracle.run("jc", wire, controls)
        chart = cone.enter(adjusted)
        self.assertTrue(np.all(np.diff(chart.ja) > 0.))
        self.assertGreater(np.max(abs(chart.ja - ja)), 2.)
        np.testing.assert_allclose(chart.q[:, 1:], cone.enter(wire).q[:, 1:], atol=1.e-4)
        self.assert_stage_close(oracle.run("jc", adjusted, dict(controls, direction=1)), wire)

    def test_jc_chroma_is_ordered_at_fixed_signed_ja(self):
        chroma = np.r_[0., np.geomspace(.02, 150., 500)]
        controls = dict(cSaturationCenter=.05, cSaturationWidth=.05, globalChromaGain=.3,
                        **{f"tone{row}CContrast": -2. for row in "SMWH"})
        for ja in (-75., 0., 75.):
            with self.subTest(ja=ja):
                wire = cone.pack(ja, chroma * .6, chroma * .8).astype("f4")
                adjusted = oracle.run("jc", wire, controls)
                chart = cone.enter(adjusted)
                np.testing.assert_allclose(chart.ja, ja, atol=1.e-3)
                self.assertTrue(np.all(np.diff(np.linalg.norm(chart.q[:, 1:], axis=-1)) > 0.))
                self.assert_stage_close(oracle.run("jc", adjusted, dict(controls, direction=1)), wire)

    def test_overlap_midtones_match_effective_j_and_c_at_each_anchor(self):
        anchors = 100. * Tone(ToneSettings()).target[1:]
        wire = cone.pack(np.r_[anchors, 1.5 * anchors, -anchors], 75., 15.).astype("f4")
        expected_midtones = {
            "jc_adjacent_overlap": (1 / 5, 2 / 3, 1 / 6, 0.),
            "jc_broad_overlap": (256 / 801, 16 / 33, 8 / 33, 32 / 801),
        }
        for stage, amounts in expected_midtones.items():
            for family in "JC":
                with self.subTest(stage=stage, family=family):
                    settings = {f"tone{row}{family}Contrast": amount for row, amount in zip("SMWH", amounts)}
                    expected = oracle.run("jc", wire, settings)
                    actual = oracle.run(stage, wire, {f"toneM{family}Contrast": 1.})
                    np.testing.assert_allclose(actual, expected, rtol=2.e-6, atol=2.e-5)

    def test_overlap_variants_preserve_uniform_contrast_and_validate_raw_sliders(self):
        ja = np.linspace(-145., 145., 161)
        wire = cone.pack(ja, .8 * np.abs(ja) + 3., -.25 * np.abs(ja)).astype("f4")
        for stage in OVERLAP_PROTOTYPES:
            with self.subTest(stage=stage):
                for amount in (-2., 2.):
                    uniform = {f"tone{row}{family}Contrast": amount
                               for row in "SMWH" for family in "JC"}
                    self.assert_stage_close(oracle.run(stage, wire, uniform),
                                           oracle.run("jc", wire, uniform))
                for name in ("toneMJContrast", "toneWCContrast"):
                    np.testing.assert_array_equal(oracle.run(stage, wire[:1], {name: 2.01}), [[400., 0., 400.]])

    def test_anchor_centers_match_broad_overlap_when_centers_are_equal(self):
        wire = np.vstack([cone.from_xyz(np.vstack([SAMPLES, 20. * SAMPLES])),
                          cone.pack([-35., 24., 57., 83., 125.], [15., 22., 46., 71., 89.],
                                    [4., -8., 9., -19., 24.])]).astype("f4")
        for j_center, c_center, width in ((.05, .95, .05), (.3, .3, .5), (.72, .41, .8), (.95, .05, 1.)):
            common = dict(peakNits=3, globalChromaGain=-.2, jSaturationWidth=width, cSaturationWidth=width,
                          toneSJContrast=-1.2, toneMJContrast=1.4, toneWJContrast=-.8, toneHJContrast=.6,
                          toneSCContrast=.7, toneMCContrast=-1.3, toneWCContrast=1.1, toneHCContrast=-.4)
            controls = common | {f"tone{row}{family}Center": value for row in "SMWH"
                                 for family, value in (("J", j_center), ("C", c_center))}
            broad = dict(common, jSaturationCenter=j_center, cSaturationCenter=c_center)
            with self.subTest(j_center=j_center, c_center=c_center, width=width):
                for direction in (0, 1):
                    actual = oracle.run("jc_anchor_centers", wire, dict(controls, direction=direction))
                    expected = oracle.run("jc_broad_overlap", wire, dict(broad, direction=direction))
                    np.testing.assert_array_equal(actual.view("u4"), expected.view("u4"))

    def test_anchor_c_centers_give_tone_specific_crossover_and_blend(self):
        anchors = 100. * Tone(ToneSettings(peak_nits=2000)).target[1:]
        ja = np.r_[anchors[1], anchors[2], .5 * (anchors[1] + anchors[2]), .5 * anchors[0],
                   1.5 * anchors[-1], anchors[:-1] + .25 * np.diff(anchors)]
        input_chroma = (35. / 75.) * ja
        wire = cone.pack(ja, input_chroma, 0.).astype("f4")
        controls = {f"tone{row}CContrast": 1. for row in "SMWH"}
        controls.update(peakNits=2, toneSCCenter=.08, toneMCCenter=.35,
                        toneWCCenter=.65, toneHCCenter=.94, cSaturationWidth=.5)
        actual = self.compare("jc_anchor_centers", wire, controls)
        chart = cone.enter(actual)
        output_chroma = np.linalg.norm(chart.q[:, 1:], axis=-1)
        self.assertGreater(output_chroma[0], input_chroma[0])
        self.assertLess(output_chroma[1], input_chroma[1])
        np.testing.assert_allclose(output_chroma[2], input_chroma[2], rtol=0., atol=2.e-4)

    def test_anchor_j_centers_drive_each_positive_local_slope(self):
        ja = np.r_[np.linspace(35., 120., 51), np.linspace(-120., -35., 51)]
        wire = cone.pack(ja, 62., 29.).astype("f4")
        controls = dict(jSaturationWidth=.35,
                        toneSJContrast=.4, toneMJContrast=-.7,
                        toneWJContrast=1.1, toneHJContrast=-.2,
                        toneSJCenter=.1, toneMJCenter=.35,
                        toneWJCenter=.65, toneHJCenter=.9)
        adjusted = self.compare("jc_anchor_centers", wire, controls)
        chart = cone.enter(adjusted)
        self.assertTrue(np.all(np.diff(chart.ja[:51]) > 0.))
        self.assertTrue(np.all(np.diff(chart.ja[51:]) > 0.))
        self.assertGreater(np.max(abs(chart.ja - ja)), .01)

    def test_anchor_centers_validate_raw_controls_and_round_trip(self):
        black = np.array([[0., -0., 0.]], dtype="f4")
        wire = np.vstack([cone.from_xyz(np.vstack([SAMPLES, 20. * SAMPLES])),
                          cone.pack([-55., 0., 47., 96.], [19., 26., -38., 77.],
                                    [-7., 14., 9., -21.])]).astype("f4")
        controls = dict(peakNits=1, globalChromaGain=.25,
                        jSaturationWidth=.9, cSaturationWidth=.1,
                        toneSJCenter=.12, toneMJCenter=.84,
                        toneWJCenter=.35, toneHJCenter=.72,
                        toneSCCenter=.88, toneMCCenter=.2,
                        toneWCCenter=.68, toneHCCenter=.31,
                        toneSJContrast=-1.7, toneMJContrast=1.8,
                        toneWJContrast=-1.2, toneHJContrast=1.5,
                        toneSCContrast=1.6, toneMCContrast=-1.8,
                        toneWCContrast=1.4, toneHCContrast=-1.3)
        for peak in range(4):
            forward_controls = dict(controls, peakNits=peak)
            inverse_controls = dict(forward_controls, direction=1)
            with self.subTest(peak=peak):
                forward = self.compare("jc_anchor_centers", wire, forward_controls)
                np.testing.assert_array_equal(
                    oracle.run("jc_anchor_centers", black, forward_controls).view("u4"), black.view("u4"))
                gray = cone.pack(np.array([-80., 0., 42., 106.]), 0., 0.).astype("f4")
                np.testing.assert_array_equal(
                    oracle.run("jc_anchor_centers", gray, forward_controls).view("u4"), gray.view("u4"))
                self.assert_stage_close(
                    oracle.run("jc_anchor_centers", forward, inverse_controls), wire)
                self.assert_stage_close(
                    oracle.run("jc_anchor_centers", oracle.run("jc_anchor_centers", wire, inverse_controls),
                               forward_controls), wire)

        for name in ("toneMJCenter", "toneWCCenter"):
            with self.subTest(invalid=name):
                np.testing.assert_array_equal(
                    oracle.run("jc_anchor_centers", wire[:1], {name: .96}), [[400., 0., 400.]])

    def test_gain_j_contrast_preserves_ray_and_lightness_order(self):
        ja = np.r_[-np.linspace(140., 8., 121), np.linspace(8., 140., 121)]
        controls = {f"tone{row}JContrast": amount for row, amount in zip("SMWH", (2., -2., 1.5, -.75))}
        fixed = np.array([[0., -0., 0.], [-42., -42., -42.], [90., 90., 90.],
                          [11., -22., 0.], [-13., 26., 0.]], dtype="f4")
        outputs = {}
        for stage in GAIN_PROTOTYPES:
            for saturation in (.04, .62):
                with self.subTest(stage=stage, saturation=saturation):
                    c = (35. / 75.) * abs(ja) * saturation / (1. - saturation)
                    wire = cone.pack(ja, .8 * c, -.6 * c).astype("f4")
                    before = cone.enter(wire)
                    actual = self.compare(stage, wire, controls)
                    after = cone.enter(actual)
                    self.assertTrue(np.all(np.diff(after.ja) > 0.))
                    self.assertGreater(np.max(abs(after.ja - before.ja)), .1)
                    np.testing.assert_allclose(after.q[:, 1:] / abs(after.ja[:, None]),
                                               before.q[:, 1:] / abs(before.ja[:, None]),
                                               rtol=2.e-4, atol=2.e-6)
                    if saturation in outputs:
                        np.testing.assert_array_equal(actual, outputs[saturation])
                    outputs[saturation] = actual
            for direction in (0, 1):
                actual = oracle.run(stage, fixed, dict(controls, direction=direction))
                np.testing.assert_array_equal(actual.view("u4"), fixed.view("u4"))

    def test_gain_c_curves_are_ordered_and_protect_near_gray(self):
        ja = 62.
        neutral = cone.pack([-ja, 0., ja], 0., 0.).astype("f4")
        saturation = np.r_[.002, np.linspace(.005, .095, 19), .10, np.linspace(.11, .99, 89)]
        c = (35. / 75.) * ja * saturation / (1. - saturation)
        wire = cone.pack(ja, .8 * c, .6 * c).astype("f4")
        before = cone.enter(wire)
        for stage in GAIN_PROTOTYPES:
            for amount in (-2., 2.):
                with self.subTest(stage=stage, amount=amount):
                    controls = {f"tone{row}CGain": amount for row in "SMWH"}
                    actual = self.compare(stage, wire, controls)
                    after = cone.enter(actual)
                    before_c = np.linalg.norm(before.q[:, 1:], axis=-1)
                    after_c = np.linalg.norm(after.q[:, 1:], axis=-1)
                    gain = after_c / before_c
                    half_gain = np.exp2(.5 * amount) if stage == "jc_log_gain" else .5 * (1. + np.exp2(amount))
                    self.assertAlmostEqual(gain[saturation == .10].item(), half_gain, places=3)
                    self.assertLess(abs(gain[0] - 1.), .06)
                    self.assertTrue(np.all(np.diff(after_c) > 0.))
                    np.testing.assert_allclose(after.ja, before.ja, rtol=2.e-4)
                    # Near gray, subtracting nearly equal float32 cones to recover
                    # opponent coordinates gives finite absolute error in a and b.
                    np.testing.assert_allclose(after.q[:, 1:], gain[:, None] * before.q[:, 1:],
                                               rtol=2.e-5, atol=3.e-5)
                    inverse = dict(controls, direction=1)
                    self.assert_stage_close(oracle.run(stage, actual, inverse), wire)
                    for settings in (controls, inverse):
                        gray = oracle.run(stage, neutral, settings)
                        np.testing.assert_array_equal(gray.view("u4"), neutral.view("u4"))
                    # These wire samples have exactly 2R + G + 0.05B = 0.
                    zero_ja = np.array([[11., -22., 0.], [-13., 26., 0.]], dtype="f4")
                    np.testing.assert_array_equal(cone.enter(zero_ja).ja, 0.)
                    vivid = cone.enter(self.compare(stage, zero_ja, controls))
                    np.testing.assert_allclose(vivid.q[:, 1:], cone.enter(zero_ja).q[:, 1:] * np.exp2(amount),
                                               rtol=2.e-5)

    def test_gain_combined_edits_preserve_post_c_saturation_and_round_trip(self):
        wire = np.vstack([cone.from_xyz(np.vstack([SAMPLES, 20. * SAMPLES])),
                          cone.pack([-55., 0., 47., 96.], [19., 26., -38., 77.], [-7., 14., 9., -21.]),
                          [210., 238., 263.], [-341., -293., -314.], [390., 389., 388.]]).astype("f4")
        j_controls = {f"tone{row}JContrast": amount for row, amount in zip("SMWH", (-1.7, 1.8, -1.2, 1.5))}
        c_controls = {f"tone{row}CGain": amount for row, amount in zip("SMWH", (1.6, -1.8, 1.4, -1.3))}
        for stage in GAIN_PROTOTYPES:
            for peak in range(4):
                with self.subTest(stage=stage, peak=peak):
                    forward = dict(j_controls | c_controls, peakNits=peak)
                    inverse = dict(forward, direction=1)
                    adjusted = self.compare(stage, wire, forward)
                    c_only = oracle.run(stage, wire, dict(c_controls, peakNits=peak))
                    self.assert_stage_close(adjusted, oracle.run(stage, c_only, dict(j_controls, peakNits=peak)))
                    self.assertGreater(np.max(abs(adjusted - c_only)), .01)
                    # Use the well-conditioned samples to compare saturation after C and after both edits.
                    c_chart = cone.enter(c_only[:len(SAMPLES)])
                    both_chart = cone.enter(adjusted[:len(SAMPLES)])
                    np.testing.assert_allclose(both_chart.q[:, 1:] / abs(both_chart.ja[:, None]),
                                               c_chart.q[:, 1:] / abs(c_chart.ja[:, None]),
                                               rtol=2.e-4, atol=2.e-6)
                    self.assert_stage_close(self.compare(stage, adjusted, inverse), wire)
                    self.assert_stage_close(oracle.run(stage, self.compare(stage, wire, inverse), forward), wire)

    def test_global_j_contrast_pivots_gray_and_color(self):
        stage = "jc_global_shape"
        for pivot, tones in ((45., [25., 45., 75.]), (80., [45., 80., 130.])):
            height = np.array(tones)
            for c_ratio in (0., .05, 1.):
                wire = cone.pack(height, .8 * c_ratio * height, -.6 * c_ratio * height).astype("f4")
                initial = cone.enter(wire)
                for contrast in (-2., 2.):
                    with self.subTest(pivot=pivot, c_ratio=c_ratio, contrast=contrast):
                        after = cone.enter(self.compare(stage, wire, dict(jContrast=contrast, jPivot=pivot)))
                        self.assertLess((after.ja[0] - height[0]) * contrast, 0.)
                        self.assertAlmostEqual(after.ja[1], pivot, delta=.0003)
                        self.assertGreater((after.ja[2] - height[2]) * contrast, 0.)
                        np.testing.assert_allclose(after.q[:, 1:] / after.ja[:, None],
                                                   initial.q[:, 1:] / initial.ja[:, None],
                                                   rtol=1.e-4, atol=2.e-6)

    def test_global_shape_independent_toe_shoulder_and_saturation_bias(self):
        stage = "jc_global_shape"
        wire = cone.pack([20., 45., 240.], 0., 0.).astype("f4")
        for settings, active in ((dict(jToe=1.), 0), (dict(jShoulder=1.), 2)):
            after = cone.enter(self.compare(stage, wire, settings)).ja
            self.assertGreater(after[active], [20., 45., 240.][active] + 1.)
            np.testing.assert_allclose(np.delete(after, active), np.delete([20., 45., 240.], active),
                                       rtol=2.e-5)
        wire = cone.pack(25., [0., 4., 120.], 0.).astype("f4")
        for bias in (-1., 0., 1.):
            after = cone.enter(self.compare(stage, wire, dict(jContrast=1.5, jSaturationBias=bias)))
            move = 25. - after.ja
            if bias == 0.:
                np.testing.assert_allclose(move, move[0], atol=3.e-4)
            else:
                self.assertTrue(np.all(bias * np.diff(move) > 0.))
                if bias == 1.:
                    self.assertAlmostEqual(move[0], 0., delta=2.e-4)

    def test_global_c_contrast_crossover_and_tail(self):
        stage = "jc_global_shape"
        height = 55.
        for pivot in (.25, .5, .75):
            s = np.array([pivot / 2., pivot, pivot + .25 * (1. - pivot)])
            c = (35. / 75.) * height * s / (1. - s)
            wire = cone.pack(height, .8 * c, -.6 * c).astype("f4")
            after = cone.enter(self.compare(stage, wire, dict(cContrast=2., cPivot=pivot)))
            radius = np.linalg.norm(after.q[:, 1:], axis=-1)
            self.assertLess(radius[0], c[0])
            self.assertAlmostEqual(radius[1], c[1], delta=.001)
            self.assertGreater(radius[2], c[2])
            np.testing.assert_allclose(after.ja, height, rtol=2.e-5)
            np.testing.assert_allclose(after.q[:, 1:], radius[:, None] * [.8, -.6], atol=.0003)

        c = (35. / 75.) * height * np.array([.25, 1., 10.])
        wire = cone.pack(height, .8 * c, -.6 * c).astype("f4")
        for settings, active in ((dict(cMuted=1.), 0), (dict(cVivid=1.), 2)):
            after = cone.enter(self.compare(stage, wire, dict(settings, cPivot=.25)))
            radius = np.linalg.norm(after.q[:, 1:], axis=-1)
            self.assertGreater(radius[active], 1.1 * c[active])
            np.testing.assert_allclose(np.delete(radius, active), np.delete(c, active), rtol=3.e-5)

        wire = cone.pack([10., 45., 90., 130.], 16., -12.).astype("f4")
        after = cone.enter(self.compare(stage, wire, dict(shadowChroma=1., highlightChroma=-1.)))
        radius = np.linalg.norm(after.q[:, 1:], axis=-1)
        self.assertGreater(radius[0], 20.)
        self.assertAlmostEqual(radius[1], 20., delta=.0003)
        self.assertTrue(np.all(radius[2:] < 20.))

        zero_ja = np.array([[11., -22., 0.], [-13., 26., 0.]], dtype="f4")
        initial = cone.enter(zero_ja)
        np.testing.assert_array_equal(initial.ja, 0.)
        settings = dict(cContrast=1., cMuted=-.5, cVivid=.8, shadowChroma=-1.2,
                        jToe=-.9, jContrast=2., jShoulder=.9)
        forward = self.compare(stage, zero_ja, settings)
        expected_gain = np.exp2(settings["cContrast"] + settings["cVivid"] + settings["shadowChroma"])
        np.testing.assert_allclose(cone.enter(forward).q[:, 1:], initial.q[:, 1:] * expected_gain, rtol=2.e-5)
        self.assert_stage_close(oracle.run(stage, forward, dict(settings, direction=1)), zero_ja)

    def test_global_c_pivot_sweep_is_ordered_with_muted_and_vivid_active(self):
        ja = np.array([55., -25., 42., -90., 120., 640., -480.])
        saturation = np.array([.5, .25, .65, .4, .83, .72, .61])
        chroma = (35. / 75.) * abs(ja) * saturation / (1. - saturation)
        wire = cone.pack(ja, .8 * chroma, -.6 * chroma).astype("f4")
        pivots = np.arange(5, 96) / 100.
        tone = dict(blackCompression=1.1, inputShadows=2.4, inputMidtones=42., inputWhite=225.,
                    inputHighlights=1600., peakNits=2, hkInfluence=.37, shadowChroma=1.5,
                    highlightChroma=-1.3, cToneCrossover=35.)
        for stage in (*GLOBAL_SHAPE_PROTOTYPES, *TONE_FIT_PROTOTYPES, *TONE_FIT_LINEAR_GAIN_PROTOTYPES):
            for contrast in (-2., 0., 2.):
                with self.subTest(stage=stage, contrast=contrast):
                    settings = dict(cContrast=contrast, cMuted=-1., cVivid=1.)
                    if stage != "jc_global_shape":
                        settings.update(tone)
                    sweep = np.stack([self.compare(stage, wire, dict(settings, cPivot=pivot)) for pivot in pivots])
                    if contrast == 0.:
                        np.testing.assert_array_equal(sweep, np.broadcast_to(sweep[0], sweep.shape))
                    else:
                        chart = cone.enter(sweep)
                        radius = np.linalg.norm(chart.q[..., 1:], axis=-1)
                        mapped = radius / (radius + (35. / 75.) * abs(chart.ja))
                        sweep_change = contrast * np.diff(mapped, axis=0)
                        self.assertTrue(np.all(sweep_change < 1.e-6))
                        self.assertTrue(np.all(contrast * (mapped[-1] - mapped[0]) < -1.e-4))
                    for pivot, adjusted in zip(pivots[::45], sweep[::45]):
                        forward = dict(settings, cPivot=pivot)
                        restored = oracle.run(stage, adjusted, dict(forward, direction=1))
                        self.assert_stage_close(restored, wire)

    def test_global_c_sweep_keeps_exact_gray(self):
        gray = np.array([[0., -0., 0.], [22., 22., 22.], [-37., -37., -37.]], dtype="f4")
        for stage in (*GLOBAL_SHAPE_PROTOTYPES, *TONE_FIT_PROTOTYPES, *TONE_FIT_LINEAR_GAIN_PROTOTYPES):
            with self.subTest(stage=stage):
                for pivot in (.05, .95):
                    settings = dict(cContrast=-2., cPivot=pivot, cMuted=-1., cVivid=1.,
                                    shadowChroma=2., highlightChroma=-2.)
                    for direction in (0, 1):
                        result = oracle.run(stage, gray, dict(settings, direction=direction))
                        np.testing.assert_array_equal(result.view("u4"), gray.view("u4"))

    def test_global_shape_extremes_keep_ramps_ordered(self):
        stage = "jc_global_shape"
        height = np.r_[-np.geomspace(600., .1, 121), 0., np.geomspace(.1, 600., 121)]
        j_wire = cone.pack(height, .3 * abs(height), -.4 * abs(height)).astype("f4")
        radius = np.geomspace(.01, 2200., 151)
        c_wire = cone.pack(55., -.6 * radius, .8 * radius).astype("f4")
        for pivot, contrast, lower, upper in ((10., -2., -1., 1.), (160., 2., 1., -1.)):
            with self.subTest(pivot=pivot):
                j_settings = dict(jPivot=pivot, jContrast=contrast, jToe=lower, jShoulder=upper)
                c_settings = dict(cPivot=.05 if pivot == 10. else .95, cContrast=contrast, cMuted=lower,
                                  cVivid=upper, shadowChroma=contrast, highlightChroma=-contrast,
                                  cToneCrossover=pivot)
                j_result = self.compare(stage, j_wire, j_settings)
                lightness = cone.enter(j_result).ja
                self.assertTrue(np.all(np.diff(lightness) > 0.))
                self.assert_stage_close(oracle.run(stage, j_result, dict(j_settings, direction=1)), j_wire)
                c_result = self.compare(stage, c_wire, c_settings)
                chroma = cone.enter(c_result).q[:, 1:]
                self.assertTrue(np.all(np.diff(np.linalg.norm(chroma, axis=-1)) > 0.))
                self.assert_stage_close(oracle.run(stage, c_result, dict(c_settings, direction=1)), c_wire)

    def test_global_shape_combined_round_trip(self):
        stage = "jc_global_shape"
        wire = np.vstack([cone.from_xyz(np.vstack([SAMPLES, 20. * SAMPLES])),
                          cone.pack([-55., 44., 130., 640.], [-.01, -38., 77., 25.], [0., 9., -21., -67.]),
                          [210., 238., 263.], [-341., -293., -314.], [390., 389., 388.]]).astype("f4")
        j_only = dict(jContrast=1.7, jSaturationBias=-.64, jToe=.83, jShoulder=-.75, jPivot=60.)
        c_only = dict(cContrast=-1.3, cMuted=-.68, cVivid=.94, cPivot=.22,
                      shadowChroma=1.5, highlightChroma=-1.8, cToneCrossover=35.)
        controls = j_only | c_only
        forward = self.compare(stage, wire, controls)
        c_result = oracle.run(stage, wire, c_only)
        self.assert_stage_close(forward, oracle.run(stage, c_result, j_only))
        inverse = dict(controls, direction=1)
        self.assert_stage_close(oracle.run(stage, forward, inverse), wire)
        self.assert_stage_close(oracle.run(stage, oracle.run(stage, wire, inverse), controls), wire)
        black = np.array([[0., -0., 0.]], dtype="f4")
        for settings in (controls, inverse):
            np.testing.assert_array_equal(oracle.run(stage, black, settings).view("u4"), black.view("u4"))
        for direction in (0, 1):
            selectors = dict(jPivot=160., cPivot=.05, cToneCrossover=10., jSaturationBias=1., direction=direction)
            np.testing.assert_array_equal(oracle.run(stage, wire, selectors).view("u4"), wire.view("u4"))

    def test_reversible_nodes_round_trip_including_extended_responses(self):
        black = np.array([[0., -0., 0.]], dtype="f4")
        wire = np.vstack([cone.from_xyz(np.vstack([SAMPLES, 20. * SAMPLES])),
                          cone.pack([-35., 0., 65.], [15., 20., -30.], [5., -6., 20.]),
                          [210., 238., 263.], [-341., -293., -314.], [390., 389., 388.]]).astype("f4")
        settings = {stage: JC_CONTROLS for stage in ("jc", *OVERLAP_PROTOTYPES)}
        settings.update({stage: WARP_CONTROLS for stage in ("warp", *WARP_QUADRATIC_SCALE_PROTOTYPES)})
        for stage, controls in settings.items():
            for peak in range(4):
                with self.subTest(stage=stage, peak=peak):
                    forward = dict(controls, peakNits=peak)
                    inverse = dict(forward, direction=1)
                    self.compare(stage, wire, forward)
                    for first, second in ((forward, inverse), (inverse, forward)):
                        np.testing.assert_array_equal(oracle.run(stage, black, first).view("u4"), black.view("u4"))
                        adjusted = oracle.run(stage, wire, first)
                        self.assertLess(np.max(abs(adjusted)), 400.)
                        self.assertGreater(np.max(abs(adjusted - wire)), .01)
                        self.assert_stage_close(oracle.run(stage, adjusted, second), wire)

    def test_warp_hue_and_chroma_hit_edited_handles_at_fixed_ja(self):
        for peak_index, peak in enumerate(reference.PEAKS):
            geometry = Color(ColorSettings(), Tone(ToneSettings(peak_nits=peak))).web.geometry
            for row, ja in enumerate(geometry.anchors):
                with self.subTest(peak=peak, row=row):
                    chroma, hue = geometry.radii[row], geometry.angles[row]
                    wire = cone.pack(ja, chroma * np.cos(hue), chroma * np.sin(hue))
                    controls = {name: value for name, value in WARP_CONTROLS.items()
                                if name.startswith(("webhue", "webchroma"))}
                    adjusted = cone.enter(oracle.run("warp", wire, dict(controls, peakNits=peak_index)))
                    expected_c = geometry.radii[row] * np.exp2([controls[f"webchroma{row}{i}"] for i in range(6)])
                    expected_h = hue + np.deg2rad([controls[f"webhue{row}{i}"] for i in range(6)])
                    np.testing.assert_allclose(adjusted.ja, ja, atol=1.e-3)
                    np.testing.assert_allclose(adjusted.q[:, 1:],
                                               np.column_stack([expected_c * np.cos(expected_h),
                                                                expected_c * np.sin(expected_h)]),
                                               rtol=3.e-4, atol=2.e-4)

    def test_warp_adaptance_moves_neutral_to_each_target_and_reach_reduces_shift(self):
        anchors = 100. * Tone(ToneSettings()).target[1:]
        targets = np.array([[2., -3.], [4., -2.], [-3., 3.], [2., 4.]])
        controls = {f"tone{row}Adaptance{axis}": targets[i, j]
                    for i, row in enumerate("SMWH") for j, axis in enumerate("AB")}
        wire = cone.pack(anchors, 0., 0.).astype("f4")
        adjusted = oracle.run("warp", wire, controls)
        np.testing.assert_allclose(cone.enter(adjusted).ja, anchors, atol=2.e-4)
        np.testing.assert_allclose(cone.enter(adjusted).q[:, 1:], targets, atol=2.e-4)
        self.assert_stage_close(oracle.run("warp", adjusted, dict(controls, direction=1)), wire)

        wire = cone.pack(anchors, 70., 10.).astype("f4")
        near = cone.enter(oracle.run("warp", wire, dict(controls, adaptanceHalfSaturation=.1)))
        far = cone.enter(oracle.run("warp", wire, dict(controls, adaptanceHalfSaturation=1.)))
        np.testing.assert_allclose(near.ja, anchors, atol=2.e-4)
        displacement = near.q[:, 1:] - cone.enter(wire).q[:, 1:]
        self.assertTrue(np.all(np.linalg.norm(displacement, axis=-1) <
                               np.linalg.norm(far.q[:, 1:] - cone.enter(wire).q[:, 1:], axis=-1)))
        np.testing.assert_allclose(displacement[:, 0] * targets[:, 1],
                                   displacement[:, 1] * targets[:, 0], atol=2.e-4)

    def test_warp_scale_keeps_ray_order_at_former_fold(self):
        ja = np.linspace(5., 140., 1000)
        wire = cone.pack(ja, .6795 * ja, 0.).astype("f4")
        controls = {f"webscale{row}{i}": stops for row, stops in enumerate((2., -2., 0., 0.))
                    for i in range(6)}
        adjusted = oracle.run("warp", wire, controls)
        chart = cone.enter(adjusted)
        self.assertTrue(np.all(np.diff(chart.ja) > 0.))
        np.testing.assert_allclose(chart.q[:, 1], .6795 * chart.ja, rtol=1.e-5)
        np.testing.assert_allclose(chart.q[:, 2], 0., atol=2.e-4)
        self.assert_stage_close(oracle.run("warp", adjusted, dict(controls, direction=1)), wire)

    def test_warp_quadratic_scale_keeps_anchors_and_ray_order(self):
        stage = "warp_quadratic_scale"
        chroma_ratio = .6795
        j_fraction = 1. / np.hypot(1., chroma_ratio)
        c_fraction = chroma_ratio * j_fraction
        controls = {f"webscale{row}{handle}": stops
                    for row, stops in enumerate((2., -2., 2., -2.)) for handle in range(6)}
        for peak_index, peak in enumerate(reference.PEAKS):
            with self.subTest(peak=peak):
                anchors = Color(ColorSettings(), Tone(ToneSettings(peak_nits=peak))).web.geometry.anchors
                radii = 2. * anchors ** 2 / (np.hypot(66. * c_fraction, 2. * anchors * j_fraction) + 66. * c_fraction)
                knots = radii * j_fraction
                at_knots = cone.pack(knots, chroma_ratio * knots, 0.)
                settings = dict(controls, peakNits=peak_index)
                self.assert_stage_close(oracle.run(stage, at_knots, settings), oracle.run("warp", at_knots, settings))

                heights = np.linspace(0., 1.2 * knots[-1], 501)
                wire = cone.pack(heights, chroma_ratio * heights, 0.).astype("f4")
                adjusted = self.compare(stage, wire, settings)
                chart = cone.enter(adjusted)
                self.assertTrue(np.all(np.diff(chart.ja) > 0.))
                np.testing.assert_allclose(chart.q[:, 1], chroma_ratio * chart.ja, rtol=1.e-5)
                baseline = self.compare("warp", wire, settings)
                self.assertGreater(np.max(abs(adjusted - baseline)), .01)
                self.assert_stage_close(oracle.run(stage, adjusted, dict(settings, direction=1)), wire)

                for index, (radius, stops) in enumerate(zip(radii, (2., -2., 2., -2.))):
                    delta = max(.1, radius * 1.e-3)
                    nearby = np.array([radius - delta, radius + delta])
                    samples = cone.pack(nearby * j_fraction, nearby * c_fraction, 0.).astype("f4")
                    output = cone.enter(oracle.run(stage, samples, settings))
                    mapped_radius = np.hypot(output.ja, np.linalg.norm(output.q[:, 1:], axis=-1))
                    derivative = (mapped_radius[1] - mapped_radius[0]) / (2. * delta)
                    expected_slope = np.exp2(stops * jc_surface.smoothstep(10. * c_fraction))
                    self.assertAlmostEqual(derivative, expected_slope, delta=2.e-2,
                                           msg=f"anchor {index}, peak {peak}")

    def test_warp_quadratic_scale_reset_matches_baseline_with_other_edits(self):
        settings = {name: value for name, value in WARP_CONTROLS.items() if not name.startswith("webscale")}
        wire = np.vstack([cone.from_xyz(np.vstack([SAMPLES, 32. * SAMPLES])),
                          cone.pack([-55., 0., 47., 96.], [19., 26., -38., 77.], [-7., 14., 9., -21.])]).astype("f4")
        for peak in range(4):
            with self.subTest(peak=peak):
                baseline = self.compare("warp", wire, dict(settings, peakNits=peak))
                quadratic = self.compare("warp_quadratic_scale", wire, dict(settings, peakNits=peak))
                self.assert_stage_close(quadratic, baseline)

    def test_five_node_chain_can_undo_color_before_export(self):
        tone_jc = dict(inputMidtones=40., cMutedGain=-.6, cVividGain=.8,
                       cSaturationCrossover=.55, shadowChroma=.2,
                       highlightChroma=-.1, cToneCrossover=.45)
        settings = {"linear": {"globalExposure": .25}, "tone_jc": tone_jc,
                    "warp": WARP_CONTROLS}
        edited = SAMPLES
        baseline = SAMPLES
        for stage in STAGES:
            edited = oracle.run(stage, edited, settings.get(stage))
            if stage in ("linear", "input"):
                baseline = reference.apply(stage, baseline, settings.get(stage, {}))
            if stage == "input":
                before_tone_jc = edited
            if stage == "warp":
                after_warp = edited
        expected = reference.apply("output", baseline, {})
        self.assertGreater(np.max(abs(edited - expected)), .001)
        restored = oracle.run("warp", after_warp, dict(WARP_CONTROLS, direction=1))
        restored = oracle.run("tone_jc", restored, dict(tone_jc, direction=1))
        self.assert_stage_close(restored, before_tone_jc)
        self.assert_stage_close(oracle.run("output", restored), expected)

    def test_invalid_hues_and_poles_propagate_to_output_diagnostic(self):
        wire = cone.from_xyz(SAMPLES[:3])
        marker = np.tile([400., 0., 400.], (len(wire), 1))
        np.testing.assert_array_equal(oracle.run("warp", wire, {"webhue20": 360}), marker)
        np.testing.assert_array_equal(oracle.run("warp", wire, {"toneSAdaptanceA": 1.e6}), marker)
        for stage in (*STANDALONE_STAGES, "tone_jc", "warp"):
            with self.subTest(stage=stage):
                invalid = np.array([[400., 0., 0.], [0., -400., 0.], [0., 0., np.inf]])
                invalid = oracle.run(stage, invalid)
                np.testing.assert_array_equal(invalid, marker)
        for x, magnitude in ((0, .06), (60, 1.)):
            magenta = rgb_matrix("Linear Rec.709") @ [magnitude, 0., magnitude]
            np.testing.assert_allclose(oracle.run("output", invalid, x=x),
                                       np.tile(magenta, (len(wire), 1)), rtol=1.e-6)
        np.testing.assert_array_equal(oracle.run("input", [[np.inf, 0., 0.]]), marker[:1])

    def test_nearest_representable_pole_and_finite_overflow(self):
        inner = np.nextafter(np.float32(400.), np.float32(0.))
        wire = np.array([[inner] * 3, [-inner] * 3], dtype="f4")
        output = self.compare("output", wire, {})
        np.testing.assert_array_equal(oracle.run("input", output), wire)
        self.assertGreater(np.min(output[0]), 1.e18)
        np.testing.assert_array_equal(oracle.run("input", [np.full(3, np.float32(1.e30))]),
                                      [[400., 0., 400.]])
        marker = np.array([[400., 0., 400.]], dtype="f4")
        # Strong positive gain can round a finite chart component onto a pole.
        probe = [[inner, -inner, 0.]]
        np.testing.assert_array_equal(oracle.run("jc", probe, {"globalChromaGain": 3.}), marker)
        np.testing.assert_array_equal(oracle.run("warp", probe, {f"webscale{i}{j}": 8.
                                                              for i in range(4) for j in range(6)}), marker)


class ToneOverlayTests(unittest.TestCase):
    stages = TONE_FIT_UNIFIED_CHROMA_PROTOTYPES

    def screen(self, x, y, frame):
        """Convert normalized J to pixels in the lower-left square."""
        width, height = frame
        size = min(width, height) // 3
        padding = max(3, size // 32)
        start = max(1, size // 24) + padding
        maximum = Tone(ToneSettings()).nits_to_j(4000.)
        span = (size - 1 - 2 * padding) / maximum
        return np.rint(start + x * span).astype(int), np.rint(height - 1 - start - y * span).astype(int)

    def render(self, stage, settings, x, y, frame, wire=(0., 0., 0.)):
        x, y = np.broadcast_arrays(x, y)
        return oracle.run(stage, np.broadcast_to(wire, (x.size, 3)), settings,
                          x=x.ravel(), y=y.ravel(), width=frame[0], height=frame[1])

    def orange(self, pixels):
        r, g, b = pixels.T
        return (r > g) & (g > b) & (r - b > 1.)

    def test_curve_tracks_graded_neutrals_in_both_directions(self):
        frame = (2160, 3840)
        calibration = dict(inputShadows=1., inputMidtones=18., inputWhite=330., inputHighlights=2400.,
                           peakNits=2, blackCompression=1.7)
        tone = Tone(reference.tone_settings(calibration))
        measured = tone.nits_to_j([6., 70., 130., 540., 1300.])
        neutrals = cone.pack(100. * measured, 0., 0.)
        for stage in self.stages:
            for fit in (-2, 1):
                for direction in (0, 1):
                    with self.subTest(stage=stage, fit=fit, direction=direction):
                        settings = dict(calibration, remapFit=fit, direction=direction)
                        mapped = cone.enter(oracle.run(stage, neutrals, settings)).ja / 100.
                        x, y = self.screen(measured, mapped, frame)
                        pixels = self.render(stage, dict(settings, showToneCurve=1), x, y, frame)
                        self.assertTrue(self.orange(pixels).all(), (x, y, pixels))

    def test_overlay_bounds_identity_backdrop_and_invalid_pixels(self):
        for stage in self.stages:
            for frame in ((1920, 1080), (1080, 1920)):
                with self.subTest(stage=stage, frame=frame):
                    # A nonzero scene makes the translucent background measurable.
                    wire = np.array([14., 14., 14.], dtype="f4")
                    size = min(frame) // 3
                    margin = size // 24
                    top = frame[1] - size - margin
                    x = [margin, margin - 1, margin + size, margin, margin]
                    y = [top, top, top, top - 1, top + size]
                    settings = dict(inputMidtones=50.)
                    before = self.render(stage, settings, x, y, frame, wire)
                    disabled = self.render(stage, dict(settings, showToneCurve=0), x, y, frame, wire)
                    np.testing.assert_array_equal(disabled.view("u4"), before.view("u4"))
                    enabled = self.render(stage, dict(settings, showToneCurve=1), x, y, frame, wire)
                    np.testing.assert_array_equal(enabled[1:].view("u4"), before[1:].view("u4"))
                    self.assertTrue(np.all((0. < enabled[0]) & (enabled[0] < before[0])))
                    on = dict(showToneCurve=1)
                    black = self.render(stage, on, x[0], y[0], frame)
                    self.assertTrue(np.all(enabled[0] > black[0]))
                    j = np.array([.3, .7, 1.4, 2.2])
                    cx, cy = self.screen(j, j, frame)
                    self.assertTrue(self.orange(self.render(stage, on, cx, cy, frame)).all())
                    self.assertFalse(self.orange(self.render(stage, on, cx, cy + 12, frame)).any())
                    invalid = self.render(stage, on, cx, cy, frame, (400., 0., 0.))
                    np.testing.assert_array_equal(invalid, np.tile([400., 0., 400.], (len(j), 1)))

    def test_declared_anchor_rings_and_fitted_dots(self):
        frame = (2160, 2160)
        scale = (min(frame) // 3) / 300.
        settings = dict(inputShadows=.2, inputMidtones=4., inputWhite=850., inputHighlights=3500.,
                        blackCompression=1., peakNits=2, remapFit=-2)
        tone = Tone(reference.tone_settings(settings))
        source, target = tone.source[1:], tone.target[1:]
        neutrals = cone.pack(100. * source, 0., 0.)
        angles = np.linspace(0., 2. * np.pi, 24, endpoint=False)
        for stage in self.stages:
            mapped = cone.enter(oracle.run(stage, neutrals, settings)).ja / 100.
            for direction in (0, 1):
                with self.subTest(stage=stage, direction=direction):
                    active = dict(settings, direction=direction, showToneCurve=1)
                    declared = (target, source) if direction else (source, target)
                    actual = (mapped, source) if direction else (source, mapped)
                    rx, ry = self.screen(*declared, frame)
                    dx, dy = self.screen(*actual, frame)
                    # The pale target ring is visible even when the dot and target coincide.
                    ring_x = rx[:, None] + np.rint(4.25 * scale * np.cos(angles)).astype(int)
                    ring_y = ry[:, None] + np.rint(4.25 * scale * np.sin(angles)).astype(int)
                    ring = self.render(stage, active, ring_x, ring_y, frame)
                    pale = (np.min(ring, axis=1) > 5.) & (np.ptp(ring, axis=1) < 1.)
                    self.assertTrue(np.all(pale.reshape(len(source), -1).sum(axis=1) >= 4))
                    # The soft fit can miss an interior target by more than the ring radius.
                    separation = np.hypot(dx - rx, dy - ry)
                    self.assertGreater(np.max(separation), 4.25 * scale)
                    dots = self.render(stage, active, dx, dy, frame)
                    self.assertTrue(self.orange(dots).all(), dots)

    def test_offscale_highlight_and_clipped_curve(self):
        frame = (1920, 1080)
        for stage in self.stages:
            for direction in (0, 1):
                with self.subTest(stage=stage, direction=direction):
                    settings = dict(showToneCurve=1, direction=direction, inputHighlights=10000., peakNits=2)
                    tone = Tone(reference.tone_settings(settings))
                    limit, peak = tone.nits_to_j([4000., 2000.])
                    tip = (peak, limit) if direction else (limit, peak)
                    cx, cy = self.screen(*tip, frame)
                    self.assertTrue(self.orange(self.render(stage, settings, cx, cy, frame))[0])
                    # A 4000-nit output peak reached early must not flatten against the edge.
                    short = dict(settings, inputHighlights=500., peakNits=3)
                    end = tone.nits_to_j(500.)
                    boundary = (limit, end) if direction else (end, limit)
                    cx, cy = self.screen(*boundary, frame)
                    self.assertTrue(self.orange(self.render(stage, short, cx, cy, frame))[0])
                    tail = tone.nits_to_j([2200., 3000.])
                    edge = (limit, tail) if direction else (tail, limit)
                    cx, cy = self.screen(*edge, frame)
                    self.assertFalse(self.orange(self.render(stage, short, cx, cy, frame)).any())
