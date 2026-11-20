"""Product files, localized controls and Resolve entry-point conventions."""
import re
import unittest

from tests.support import oracle
from tests.support.dctl import STAGES, LOCALES, body, controls, entry, filename

J_C = {f"tone{tone}{driver}To{receiver}" for tone in "SMWH" for receiver in "JC"
       for driver in ("Low", "High", "a", "b")}
WEB = {f"web{family}{tone}{handle}" for family in ("chroma", "hue", "scale")
       for tone in range(4) for handle in range(6)}
CENTER = {f"tone{tone}Adaptance{axis}" for tone in "SMWH" for axis in "AB"}


class InterfaceTests(unittest.TestCase):
    def test_product_contains_exactly_four_stages_per_locale(self):
        expected = {filename(stage, locale) for stage in STAGES for locale in LOCALES}
        self.assertEqual({path.name for path in oracle.STAGE_DIR.iterdir()}, expected)

    def test_locales_match_numerically_and_declare_unique_translated_controls(self):
        for stage in STAGES:
            english = oracle.source(stage)
            chinese = oracle.source(stage, "zh_HANS")
            with self.subTest(stage=stage):
                self.assertEqual(body(english), body(chinese))
                self.assertEqual(entry(english), entry(chinese))
                translated = controls(chinese)
                self.assertEqual(len(oracle.ui(stage)), len(translated))
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
        for stage in STAGES:
            for locale in LOCALES:
                with self.subTest(stage=stage, locale=locale):
                    source = oracle.source(stage, locale)
                    self.assertEqual(re.findall(r"transform\(([^)]*)\)", re.sub(r"\s+", "", source)),
                                     [expected])
                    self.assertRegex(entry(source), r"\breturn\s+make_float3\(")

    def test_controls_belong_to_their_stage(self):
        expected = {
            "linear": {"srcWhite", "globalExposure", "srcX", "srcY", "le", "be", "ls", "bs", "la", "ba"},
            "tone": {"inputBlack", "inputShadows", "inputMidtones", "inputWhite", "inputHighlights",
                     "remapFit", "peakNits"},
            "jc": J_C | {"lightnessFit", "chromaFit", "globalChromaGain", "peakNits"},
            "warp": WEB | CENTER | {"adaptanceHalfSaturation", "peakNits"},
        }
        for stage in STAGES:
            with self.subTest(stage=stage):
                records = {item["name"]: item for item in oracle.ui(stage)}
                self.assertEqual(records.keys(), expected[stage])
                self.assertLessEqual(sum(i["type"] == "DCTLUI_SLIDER_FLOAT" for i in records.values()), 64)
                if stage != "linear":
                    self.assertEqual(records["peakNits"]["default"], 1)
                    self.assertEqual(records["peakNits"]["options"][1],
                                     ["500 nits", "1000 nits", "2000 nits", "4000 nits"])

        jc = {item["name"]: item for item in oracle.ui("jc")}
        for name in J_C:
            self.assertEqual(jc[name]["type"], "DCTLUI_SLIDER_FLOAT")
            self.assertLess(jc[name]["step"], 1)
        warp = {item["name"]: item for item in oracle.ui("warp")}
        self.assertEqual(sum(item["type"] == "DCTLUI_SLIDER_FLOAT" for item in warp.values()), 57)
        for name in WEB:
            item = warp[name]
            if name.startswith("webhue"):
                self.assertEqual((item["type"], item["min"], item["max"], item["step"]),
                                 ("DCTLUI_SLIDER_INT", -360, 360, 1))
            else:
                self.assertEqual(item["type"], "DCTLUI_SLIDER_FLOAT")
