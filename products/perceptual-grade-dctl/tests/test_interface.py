"""Product files, localized controls and Resolve entry-point conventions."""
import re
import unittest

from tests.support import oracle
from tests.support.dctl import ALL_STAGES, LOCALES, PROTOTYPES, STAGES, SURFACE_PROTOTYPES, body, controls, entry, filename

J_C = {f"tone{tone}{receiver}Contrast" for tone in "SMWH" for receiver in "JC"}
SHAPE = {f"{family}Saturation{parameter}" for family in "jc" for parameter in ("Center", "Width")}
LGG = {f"tone{tone}{receiver}{wheel}" for tone in "SMWH" for receiver in "JC"
       for wheel in ("Lift", "Gamma", "Gain")}
WEB = {f"web{family}{tone}{handle}" for family in ("chroma", "hue", "scale")
       for tone in range(4) for handle in range(6)}
CENTER = {f"tone{tone}Adaptance{axis}" for tone in "SMWH" for axis in "AB"}


class InterfaceTests(unittest.TestCase):
    def test_product_contains_exactly_six_stages_per_locale(self):
        self.assertEqual(tuple(STAGES), ("linear", "input", "tone", "jc", "warp", "output"))
        expected = {filename(stage, locale) for stage in STAGES for locale in LOCALES}
        self.assertEqual({path.name for path in oracle.STAGE_DIR.iterdir()}, expected)

    def test_prototype_artifact_contains_exactly_three_choices_per_locale(self):
        expected = {filename(stage, locale) for stage in PROTOTYPES for locale in LOCALES}
        self.assertEqual({path.name for path in oracle.PROTOTYPE_DIR.iterdir()}, expected)

    def test_surface_artifact_and_controls(self):
        expected = {filename(stage, locale) for stage in SURFACE_PROTOTYPES for locale in LOCALES}
        self.assertEqual({path.name for path in oracle.SURFACE_DIR.iterdir()}, expected)

        records = {item["name"]: item for item in oracle.ui("surface")}
        peak = next(item for item in oracle.ui("jc") if item["name"] == "peakNits")
        self.assertEqual(records.pop("peakNits"), peak)
        self.assertEqual(len(records), 13)
        ranges = {"globalChromaGain": (0., -3., 3., .01)}
        for row in "SMWH":
            ranges[f"tone{row}JContrast"] = (0., -20., 20., .1)
            ranges[f"tone{row}CContrast"] = (0., -2., 2., .01)
        for family in "jc":
            ranges[f"{family}SaturationCenter"] = (.5, .05, .95, .01)
            ranges[f"{family}SaturationWidth"] = (.5, .05, 1., .01)
        self.assertEqual(records.keys(), ranges.keys())
        for name, item in records.items():
            self.assertEqual(item["type"], "DCTLUI_SLIDER_FLOAT")
            self.assertEqual(tuple(item[key] for key in ("default", "min", "max", "step")), ranges[name])

    def test_locales_match_numerically_and_declare_unique_translated_controls(self):
        for stage in ALL_STAGES:
            english = oracle.source(stage)
            chinese = oracle.source(stage, "zh_HANS")
            with self.subTest(stage=stage):
                self.assertEqual(body(english), body(chinese))
                self.assertEqual(entry(english), entry(chinese))
                translated = controls(chinese)
                self.assertEqual(len(oracle.ui(stage)), len(translated))
                if translated:
                    self.assertTrue(any(left["label"] != right["label"] for left, right in
                                        zip(oracle.ui(stage), translated)))
                for left, right in zip(oracle.ui(stage), translated):
                    self.assertEqual({k: v for k, v in left.items() if k not in ("label", "options")},
                                     {k: v for k, v in right.items() if k not in ("label", "options")})
                    if "options" in left:
                        self.assertEqual(left["options"][0], right["options"][0])
                for source in (english, chinese):
                    ui = controls(source)
                    self.assertEqual(len({item["label"] for item in ui}), len(ui))
                    self.assertEqual(len(re.findall(r"^DEFINE_UI_TOOLTIP\(", source, re.M)), len(ui))

    def test_public_transform_signature_and_return(self):
        expected = "intp_Width,intp_Height,intp_X,intp_Y,floatp_R,floatp_G,floatp_B"
        for stage in ALL_STAGES:
            for locale in LOCALES:
                with self.subTest(stage=stage, locale=locale):
                    source = oracle.source(stage, locale)
                    self.assertEqual(re.findall(r"transform\(([^)]*)\)", re.sub(r"\s+", "", source)),
                                     [expected])
                    self.assertRegex(entry(source), r"\breturn\s+make_float3\(")

    def test_hk_repair_is_only_bundled_into_xyz_output(self):
        for stage in STAGES:
            with self.subTest(stage=stage):
                self.assertEqual("pg_guard(" in body(oracle.source(stage)), stage == "output")

    def test_controls_belong_to_their_stage(self):
        expected = {
            "linear": {"srcWhite", "globalExposure", "srcX", "srcY", "le", "be", "ls", "bs", "la", "ba"},
            "input": set(),
            "tone": {"inputBlack", "inputShadows", "inputMidtones", "inputWhite", "inputHighlights",
                     "remapFit", "peakNits"},
            "jc": J_C | SHAPE | {"globalChromaGain", "peakNits", "direction"},
            "warp": WEB | CENTER | {"adaptanceHalfSaturation", "peakNits", "direction"},
            "output": set(),
        }
        for stage in STAGES:
            with self.subTest(stage=stage):
                records = {item["name"]: item for item in oracle.ui(stage)}
                self.assertEqual(records.keys(), expected[stage])
                self.assertLessEqual(sum(i["type"] == "DCTLUI_SLIDER_FLOAT" for i in records.values()), 64)
                if "peakNits" in records:
                    self.assertEqual(records["peakNits"]["default"], 1)
                    self.assertEqual(records["peakNits"]["options"][1],
                                     ["500 nits", "1000 nits", "2000 nits", "4000 nits"])
                if "direction" in records:
                    self.assertEqual(records["direction"]["type"], "DCTLUI_COMBO_BOX")
                    self.assertEqual(records["direction"]["default"], 0)
                    self.assertEqual(records["direction"]["options"][1], ["Forward", "Inverse"])

        jc = {item["name"]: item for item in oracle.ui("jc")}
        surface = {item["name"]: item for item in oracle.ui("surface")}
        for name in J_C | SHAPE | {"globalChromaGain"}:
            keys = ("type", "default", "min", "max", "step")
            expected = ("DCTLUI_SLIDER_FLOAT", 0., -2., 2., .01) if name in J_C else tuple(
                surface[name][key] for key in keys)
            self.assertEqual(tuple(jc[name][key] for key in keys), expected)
        warp = {item["name"]: item for item in oracle.ui("warp")}
        self.assertEqual(sum(item["type"] == "DCTLUI_SLIDER_FLOAT" for item in warp.values()), 57)
        for name in WEB:
            item = warp[name]
            if name.startswith("webhue"):
                self.assertEqual((item["type"], item["min"], item["max"], item["step"]),
                                 ("DCTLUI_SLIDER_INT", -360, 360, 1))
            else:
                self.assertEqual(item["type"], "DCTLUI_SLIDER_FLOAT")

    def test_prototype_control_ranges_and_defaults(self):
        common = {"lightnessFit", "chromaFit", "peakNits"}
        baseline = {item["name"]: item for item in oracle.ui("lgg")}
        for stage in PROTOTYPES:
            with self.subTest(stage=stage):
                records = {item["name"]: item for item in oracle.ui(stage)}
                expected = LGG | common
                if stage == "lgg_pivot":
                    expected.add("saturationPivot")
                    pivot = records["saturationPivot"]
                    self.assertEqual((pivot["type"], pivot["min"], pivot["max"], pivot["step"]),
                                     ("DCTLUI_SLIDER_FLOAT", .05, 2., .01))
                    self.assertAlmostEqual(pivot["default"], 35. / 75., places=10)
                self.assertEqual(records.keys(), expected)
                for name in common:
                    self.assertEqual(records[name], baseline[name])
                for name in LGG:
                    item = records[name]
                    limit, step = (20, .1) if name.endswith("JLift") else (2, .01)
                    self.assertEqual((item["type"], item["default"], item["min"], item["max"], item["step"]),
                                     ("DCTLUI_SLIDER_FLOAT", 0, -limit, limit, step))
