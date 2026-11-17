"""Audit pinned-template receipts after native Blender library append."""

from dataclasses import replace
from difflib import unified_diff
from importlib import resources
import json
import unittest
from unittest.mock import patch

import bpy

from color_tools.kernel import node_templates
from color_tools.kernel.boundary import prepare_boundary
from color_tools.kernel.prepare import prepare


class TemplateReceiptTests(unittest.TestCase):
    def setUp(self):
        bpy.ops.wm.read_factory_settings(use_empty=True)
        self.report = json.loads(resources.files("tests.perceptual_grade_blender").joinpath(
            "template_generation.json").read_text(encoding="utf-8"))

    def tearDown(self):
        bpy.ops.wm.read_factory_settings(use_empty=True)

    def assert_receipt(self, tree, key):
        expected = json.dumps(self.report["structure_receipts"][key],
                              sort_keys=True, indent=2)
        actual = json.dumps(node_templates.structure_receipt(tree),
                            sort_keys=True, indent=2)
        difference = "\n".join(unified_diff(
            expected.splitlines(), actual.splitlines(),
            fromfile=f"generated {self.report['blender_version']}",
            tofile=f"appended {list(bpy.app.version)}", n=3,
        ))
        if difference:
            self.fail(f"{key}\n{difference}")

    def test_template_literals_do_not_require_float32_subnormals(self):
        def inspect(value, path):
            if isinstance(value, dict):
                for key, item in value.items():
                    inspect(item, f"{path}.{key}")
            elif isinstance(value, list):
                for index, item in enumerate(value):
                    inspect(item, f"{path}[{index}]")
            elif isinstance(value, str) and value.startswith(("0x", "-0x")):
                literal = abs(float.fromhex(value))
                self.assertTrue(literal == 0. or literal >= 2.**-126,
                                f"Subnormal template literal at {path}: {value}")

        for key, receipt in self.report["structure_receipts"].items():
            with self.subTest(variant=key):
                inspect(receipt, key)

    def test_all_template_receipts_survive_native_append(self):
        store = node_templates.TemplateStore()
        manifest, records = store._contract()
        self.assertEqual(self.report["asset_sha256"]["node_templates.blend"],
                         manifest["blend_sha256"])
        receipts = self.report["structure_receipts"]
        self.assertEqual(set(receipts), set(records))
        for key, record in records.items():
            with self.subTest(variant=key):
                with store._blend_path() as path:
                    with bpy.data.libraries.load(str(path), link=False) as (_, selected):
                        selected.node_groups = [record.name]
                tree, = selected.node_groups
                try:
                    self.assert_receipt(tree, key)
                    self.assertEqual(node_templates.structure_digest(tree),
                                     record.structure_sha256)
                finally:
                    bpy.data.node_groups.remove(tree, do_unlink=True)

    def test_grade_receipts_survive_runtime_bindings(self):
        original_validate = node_templates._validate_tree

        def audit_validate(tree, record, **kwargs):
            self.assert_receipt(tree, record.key)
            original_validate(tree, record, **kwargs)

        with patch.object(node_templates, "_validate_tree", audit_validate):
            for space in ("Linear Rec.709", "Linear Rec.2020", "ACEScg"):
                bpy.ops.wm.set_working_color_space(working_space=space)
                prepared = prepare(space=space, full_fields=True)
                prepared = replace(prepared, boundary=prepare_boundary(
                    prepared.fl, prepared.aw, prepared.gamma))
                for tree_type in node_templates.TREE_TYPES:
                    with self.subTest(space=space, tree_type=tree_type):
                        instance = node_templates.instantiate_grade(prepared, tree_type)
                        instance.dispose()


if __name__ == "__main__":
    unittest.main()
