"""Verify the installed extension's Blender translation registration."""

import importlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import addon_utils
import bpy


repository, report = map(Path, sys.argv[sys.argv.index("--") + 1:])
bpy.context.preferences.extensions.repos.new(
    name="Perceptual Grade localization test",
    module="pg_grade_localization",
    custom_directory=str(repository),
)
extension = importlib.import_module(
    "bl_ext.pg_grade_localization.perceptual_grade"
)
addon_utils.enable(extension.__name__, default_set=False)
nodes = importlib.import_module(
    "bl_ext.pg_grade_localization.perceptual_grade.nodes"
)
localization = nodes.localization
assert localization._registered
assert localization.tr("node.grade.title", locale="zh_CN") == "调色"
assert localization.resolve_locale("zh_CN") == "zh_HANS"

view = bpy.context.preferences.view
old_language = view.language
old_interface = view.use_translate_interface
old_tooltips = view.use_translate_tooltips
try:
    language_ids = {
        item.identifier
        for item in view.bl_rna.properties["language"].enum_items
    }
    chinese_locale = next(
        (value for value in ("zh_CN", "zh_HANS") if value in language_ids), None
    )
    if chinese_locale is None:
        raise AssertionError("Blender does not expose a Simplified Chinese locale")
    view.language = chinese_locale
    view.use_translate_interface = True
    view.use_translate_tooltips = False
    assert bpy.app.translations.pgettext_iface(
        "Exposure", localization.CONTEXT
    ) == "曝光"
    assert bpy.app.translations.pgettext_iface("Color") == "颜色"
    assert bpy.app.translations.pgettext_iface("Perceptual Grade") == "感知调色"
    assert bpy.app.translations.pgettext_tip(
        "Exposure in stops. +1 doubles linear RGB values.", localization.CONTEXT
    ) == "Exposure in stops. +1 doubles linear RGB values."
    status_node = SimpleNamespace(get=lambda key: {
        nodes._NODE_PENDING: "status.showing_last_good",
        nodes._NODE_ERROR: True,
        nodes._NODE_ANIMATION_ERROR: True,
    }.get(key))
    assert nodes._pending_message(status_node) == "正在更新 - 显示上一个有效结果"
    assert nodes._kernel_error_text(status_node) == "调色输出为洋红色"
    assert nodes._animation_error_text(status_node) == "无法创建动画关键帧"

    view.use_translate_interface = False
    view.use_translate_tooltips = True
    assert bpy.app.translations.pgettext_iface(
        "Exposure", localization.CONTEXT
    ) == "Exposure"
    assert bpy.app.translations.pgettext_iface("Color") == "Color"
    assert bpy.app.translations.pgettext_tip(
        "Exposure in stops. +1 doubles linear RGB values.", localization.CONTEXT
    ) == "曝光量以档为单位。+1 会使线性 RGB 数值加倍。"
    assert nodes._pending_message(status_node) == "Updating - showing last-good result"
    assert nodes._kernel_error_text(status_node) == "Grade output is magenta"
    assert nodes._animation_error_text(status_node) == "Could not create an animation keyframe"
finally:
    view.language = old_language
    view.use_translate_interface = old_interface
    view.use_translate_tooltips = old_tooltips

addon_utils.disable(extension.__name__, default_set=False)
assert not localization._registered
assert not nodes.PGShaderGrade.is_registered
report.write_text(json.dumps({"registered": localization._registered}))
