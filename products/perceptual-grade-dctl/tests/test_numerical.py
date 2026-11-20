"""Float32 Resolve entry points against independent float64 reference stages."""
import unittest

import numpy as np
from color_tools.perceptual_grade_reference.appearance import decode, encode
from color_tools.perceptual_grade_reference.grading import Color, Tone, ToneSettings
from color_tools.perceptual_grade_reference.model import rgb_matrix
from color_tools.perceptual_grade_reference.responses import State, signed_hk
from tests.support import dctl_reference as reference, oracle
from tests.support.dctl import STAGES

SAMPLES = np.array([[.25, .18, .04], [.15, .07, .42], [.5, .8, .2], [3., 1., .8],
                    [-.09, -.07, -.04], [1.e-6, 2.e-6, 5.e-6]], dtype=np.float32)


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
        for stage in STAGES:
            with self.subTest(stage=stage):
                actual = oracle.run(stage, pixels)
                np.testing.assert_array_equal(actual.view("u4"), pixels.view("u4"))

    def test_active_stages_preserve_signed_and_hdr_domain(self):
        signed_hdr = np.array([-13., 2048.])[:, None] * reference.WHITE
        signed_hdr *= [1.02, 1., .98]
        for stage, controls in (("linear", {"globalExposure": 1}),
                                ("tone", {"inputMidtones": 34.}),
                                ("jc", {"globalChromaGain": .08}),
                                ("warp", {f"webscale{i}{j}": .1 for i in range(4) for j in range(6)})):
            with self.subTest(stage=stage):
                actual = self.compare(stage, signed_hdr, controls)
                self.assertLess(np.max(actual[0]), 0.)
                self.assertGreater(np.min(actual[1]), 1024.)
                self.assertGreater(np.max(abs(actual - signed_hdr)), .01)

    def test_linear_and_signed_tone(self):
        self.compare("linear", SAMPLES, dict(srcWhite=3, globalExposure=.5,
                                             le=.15, be=-.2, ls=-30, bs=5, la=6, ba=-4))
        for index in range(4):
            with self.subTest(peak=index):
                self.compare("tone", SAMPLES, dict(peakNits=index, inputShadows=4,
                                                   inputMidtones=42, remapFit=2))

    def test_all_tonal_coefficients_including_fractional_highlights(self):
        controls = {"lightnessFit": 3, "chromaFit": -1, "globalChromaGain": .03}
        for i, tone in enumerate("SMWH"):
            for j, driver in enumerate(("Low", "High", "a", "b")):
                controls[f"tone{tone}{driver}ToJ"] = (i - 1.5) * (j + 1) * .2
                controls[f"tone{tone}{driver}ToC"] = (j - 1.5) * (i + 1) * .02
        self.compare("jc", np.vstack((SAMPLES, 20 * SAMPLES)), controls)

    def test_signed_low_high_crossover(self):
        ja = np.array([-75., 75., -75., 75.])
        chroma = np.full(4, 35.)
        q = np.stack((signed_hk(ja, chroma), [35., 35., 0., 0.], [0., 0., 35., 35.]), axis=-1)
        xyz = decode(q, ja * abs(ja), reference.WHITE)
        low = self.compare("jc", xyz, {f"tone{tone}LowToJ": 2. for tone in "SMWH"})
        high = self.compare("jc", xyz, {f"tone{tone}HighToJ": 2. for tone in "SMWH"})
        self.assert_stage_close(low, high)

    def test_web_rays_and_interpolated_rows_on_every_peak(self):
        controls = {}
        for row in range(4):
            for handle in range(6):
                controls[f"webhue{row}{handle}"] = 3 * (handle - 2) + row
                controls[f"webchroma{row}{handle}"] = .08 * (handle - 2) - row * .05
                controls[f"webscale{row}{handle}"] = .10 * (row - 1) + handle * .02
        for index, peak in enumerate(reference.PEAKS):
            with self.subTest(peak=peak):
                color = Color(reference.color_settings({}), Tone(ToneSettings(peak_nits=peak)))
                geometry = color.web.geometry
                rays = decode(geometry.q, geometry.energy, reference.WHITE).reshape(-1, 3)
                self.compare("warp", np.vstack((rays, rays * .7, SAMPLES)),
                             dict(controls, peakNits=index))

    def test_selective_adaptance_and_repair_before_scale(self):
        web = {f"web{family}{i}{j}": value for i in range(4) for j in range(6)
               for family, value in (("chroma", 1.5), ("scale", .75))}
        for i, tone in enumerate("SMWH"):
            web[f"tone{tone}AdaptanceA"] = i + 1
            web[f"tone{tone}AdaptanceB"] = -2
        web["adaptanceHalfSaturation"] = .5
        xyz = np.vstack((SAMPLES, reference.WHITE, .18 * reference.WHITE))
        self.compare("warp", xyz, web)
        state = encode(SAMPLES, reference.WHITE)
        color = Color(reference.color_settings(web), Tone(ToneSettings()))
        raw = color.pre_repair_warp_state(State(state.q, state.ja * abs(state.ja)))
        self.assertTrue(np.any((raw.q[:, 0] > 0) & (raw.energy < 0)))

    def test_adaptance_moves_neutral_at_all_tonal_centers(self):
        controls = {f"tone{tone}Adaptance{axis}": value for i, tone in enumerate("SMWH")
                    for axis, value in (("A", i + 1.), ("B", -2.))}
        nits = np.array(ToneSettings().input_nits[1:])
        xyz = (nits / 203.)[:, None] * reference.WHITE
        actual = self.compare("warp", xyz, controls)
        self.assertTrue(np.all(np.max(abs(actual - xyz), axis=-1) > 1.e-6))

    def test_sequential_nodes_resample_their_own_selectors(self):
        settings = {
            "linear": {"globalExposure": .25},
            "tone": {"inputMidtones": 40.},
            "jc": {"globalChromaGain": .6, "toneWHighToJ": -20.},
            "warp": {"webhue00": -25, "webhue10": 25, "webhue20": -20,
                     "webscale04": -.5, "webscale14": .5, "webscale24": -.5,
                     "toneMAdaptanceB": 7.},
        }
        actual = expected = SAMPLES[:4]
        for stage in STAGES:
            actual = oracle.run(stage, actual, settings[stage])
            expected = reference.apply(stage, expected, settings[stage])
            if stage == "tone":
                after_tone = expected
        self.assert_stage_close(actual, expected)
        appearance = encode(after_tone, reference.WHITE)
        combined = Color(reference.color_settings(settings["jc"] | settings["warp"]), Tone(ToneSettings()))
        state = combined.apply_state(State(appearance.q, appearance.ja * abs(appearance.ja)))
        single_pass = decode(state.q, state.energy, reference.WHITE)
        self.assertGreater(np.max(abs(single_pass - expected)), .001)

    def test_invalid_hues_adaptance_and_response_pole_display_diagnostic(self):
        xyz = SAMPLES[:3]
        invalid = {"webhue20": 360}
        diagnostic = oracle.run("warp", xyz, invalid)
        np.testing.assert_array_equal(diagnostic, np.repeat(diagnostic[:1], len(xyz), axis=0))
        magenta_xyz = rgb_matrix("Linear Rec.709") @ [.06, 0., .06]
        np.testing.assert_allclose(diagnostic[0], magenta_xyz, rtol=1e-6)
        np.testing.assert_array_equal(oracle.run("warp", xyz, {"toneSAdaptanceA": 1.e6}), diagnostic)

        controls = {f"webscale{i}{j}": 8. for i in range(4) for j in range(6)}
        target = np.array([[.4, .2, .1]], dtype="f4")
        with self.assertRaisesRegex(ValueError, "response magnitudes"):
            reference.apply("warp", target, controls)
        np.testing.assert_array_equal(oracle.run("warp", target, controls), diagnostic[:1])
