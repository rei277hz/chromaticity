"""Float32 Resolve entry points against independent float64 reference stages."""
import unittest

import numpy as np
from color_tools.perceptual_grade_reference.grading import Color, ColorSettings, Tone, ToneSettings
from color_tools.perceptual_grade_reference.model import rgb_matrix
from tests.support import cone_reference as cone, dctl_reference as reference, jc_prototype, jc_surface, oracle
from tests.support.dctl import PROTOTYPES, STAGES, SURFACE_PROTOTYPES

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
        for stage in ("tone", "jc", "warp"):
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

    def test_reversible_nodes_round_trip_including_extended_responses(self):
        black = np.array([[0., -0., 0.]], dtype="f4")
        wire = np.vstack([cone.from_xyz(np.vstack([SAMPLES, 20. * SAMPLES])),
                          cone.pack([-35., 0., 65.], [15., 20., -30.], [5., -6., 20.]),
                          [210., 238., 263.], [-341., -293., -314.], [390., 389., 388.]]).astype("f4")
        for stage, controls in (("jc", JC_CONTROLS), ("warp", WARP_CONTROLS)):
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

    def test_six_node_chain_can_undo_color_before_export(self):
        settings = {"linear": {"globalExposure": .25}, "tone": {"inputMidtones": 40.},
                    "jc": JC_CONTROLS, "warp": WARP_CONTROLS}
        edited = baseline = SAMPLES
        for stage in STAGES:
            edited = oracle.run(stage, edited, settings.get(stage))
            if stage == "warp":
                after_warp = edited
            if stage in ("jc", "warp"):
                continue
            baseline = reference.apply(stage, baseline, settings.get(stage, {}))
            if stage == "tone":
                after_tone = edited
        self.assertGreater(np.max(abs(edited - baseline)), .001)
        restored = oracle.run("warp", after_warp, dict(WARP_CONTROLS, direction=1))
        restored = oracle.run("jc", restored, dict(JC_CONTROLS, direction=1))
        self.assert_stage_close(restored, after_tone)
        self.assert_stage_close(oracle.run("output", restored), baseline)

    def test_invalid_hues_and_poles_propagate_to_output_diagnostic(self):
        wire = cone.from_xyz(SAMPLES[:3])
        marker = np.tile([400., 0., 400.], (len(wire), 1))
        np.testing.assert_array_equal(oracle.run("warp", wire, {"webhue20": 360}), marker)
        np.testing.assert_array_equal(oracle.run("warp", wire, {"toneSAdaptanceA": 1.e6}), marker)
        invalid = np.array([[400., 0., 0.], [0., -400., 0.], [0., 0., np.inf]])
        for stage in ("tone", "jc", "warp"):
            with self.subTest(stage=stage):
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
