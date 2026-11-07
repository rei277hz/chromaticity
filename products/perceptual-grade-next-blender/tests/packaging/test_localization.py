from types import SimpleNamespace
import unittest

from color_tools import localization


class LocalizationTests(unittest.TestCase):
    def test_locale_aliases_and_fallback(self):
        self.assertEqual(localization.resolve_locale("zh_CN"), "zh_HANS")
        self.assertEqual(localization.resolve_locale("zh_HANS"), "zh_HANS")
        self.assertEqual(localization.resolve_locale("zh_TW"), "en")
        self.assertEqual(localization.resolve_locale("fr_FR"), "en")

    def test_interface_and_tooltip_preferences_are_independent(self):
        view = SimpleNamespace(
            language="zh_CN",
            use_translate_interface=True,
            use_translate_tooltips=False,
        )
        translations = SimpleNamespace(locale="en_US")
        self.assertEqual(
            localization.language_for(view, translations, "use_translate_interface"),
            "zh_HANS",
        )
        self.assertEqual(
            localization.language_for(view, translations, "use_translate_tooltips"),
            "en",
        )
        view.use_translate_tooltips = True
        self.assertEqual(
            localization.language_for(view, translations, "use_translate_tooltips"),
            "zh_HANS",
        )
        view.language = "DEFAULT"
        translations.locale = "zh_CN"
        self.assertEqual(
            localization.language_for(view, translations, "use_translate_interface"),
            "zh_HANS",
        )

    def test_semantic_runtime_messages(self):
        self.assertEqual(localization.tr("node.grade.title", locale="en"), "Grade")
        self.assertEqual(localization.tr("node.grade.title", locale="zh_CN"), "调色")
        self.assertEqual(localization.tr("undo.gesture", locale="zh_CN"), "感知调色")
        self.assertEqual(
            localization.tr("status.waiting_compositor", locale="zh_HANS"),
            "正在更新 - 等待合成器结果",
        )
        with self.assertRaises(KeyError):
            localization.tr("status.not_a_real_message", locale="en")

    def test_blender_bridge_uses_context_and_default_tooltip_context(self):
        messages = localization.host_messages("zh_CN")
        self.assertEqual(messages[(localization.CONTEXT, "Exposure")], "曝光")
        self.assertEqual(messages[(localization.CONTEXT, "Grade")], "调色")
        self.assertEqual(
            messages[("*", "Exposure in stops. +1 doubles linear RGB values.")],
            "曝光量以档为单位。+1 会使线性 RGB 数值加倍。",
        )
        self.assertEqual(messages[("*", "Color")], "颜色")
        self.assertEqual(messages[("*", "Alpha")], "Alpha")


if __name__ == "__main__":
    unittest.main()
