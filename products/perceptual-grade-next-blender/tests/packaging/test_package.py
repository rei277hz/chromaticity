from importlib.resources import files
import ast
import importlib.util
import json
import tomllib
import unittest
import zipfile


EMITTER_MODULES = frozenset({
    "kernel.graph", "kernel.color_graph", "kernel.guard_graph",
    "kernel.stage2_graph", "kernel.persistent", "kernel.lut_graph",
    "kernel.stack_graph", "kernel.wrapper_graph", "kernel.lut_shader_emitter",
    "kernel.parameter_color", "kernel.compositor_output",
})


class PackageTests(unittest.TestCase):
    def test_archive_contains_grade_runtime_and_linear_node_library(self):
        resource = files("tests.perceptual_grade_blender") / "extension.zip"
        with zipfile.ZipFile(resource) as archive:
            names = set(archive.namelist())
            expected = {
                "__init__.py",
                "lut_gpu.py",
                "lut_codec.py",
                "lut_helper.py",
                "lut_worker.py",
                "runtime/__init__.py",
                "runtime/preparation.py",
                "runtime/resource_lifecycle.py",
                "runtime/image_publication.py",
                "runtime/capture_graph.py",
                "runtime/capture_helper.py",
                "runtime/capture_host.py",
                "runtime/capture_images.py",
                "runtime/capture_snapshot.py",
                "runtime/capture_worker.py",
                "runtime/effective_grade_graph.py",
                "host/__init__.py",
                "host/callbacks.py",
                "features/__init__.py",
                "features/bake/__init__.py",
                "features/bake/controller.py",
                "features/bake/freshness.py",
                "features/bake/graph.py",
                "features/bake/images.py",
                "features/bake/manager.py",
                "features/bake/policy.py",
                "features/bake/routes.py",
                "features/bake/worker.py",
                "features/grade/__init__.py",
                "features/grade/host.py",
                "features/grade/appearance_endpoint.py",
                "features/grade/bank_publication.py",
                "features/grade/color_authoring.py",
                "features/grade/compositor_receipts.py",
                "features/grade/conversion.py",
                "features/grade/preparation.py",
                "features/grade/publisher.py",
                "features/grade/resources.py",
                "features/grade/stack_observations.py",
                "features/interaction/__init__.py",
                "features/interaction/policy.py",
                "features/interaction/runtime.py",
                "features/vectorscope/__init__.py",
                "features/vectorscope/authority.py",
                "features/vectorscope/capture.py",
                "features/vectorscope/routes.py",
                "runtime/execution.py",
                "runtime/host.py",
                "runtime/payloads.py",
                "runtime/transport.py",
                "runtime/worker.py",
                "runtime/worker_main.py",
                "localization/__init__.py",
                "localization/locales/en.json",
                "localization/locales/zh_HANS.json",
                "localization/locales/en/LC_MESSAGES/perceptual_grade.mo",
                "localization/locales/zh_HANS/LC_MESSAGES/perceptual_grade.mo",
                "blender_manifest.toml",
                "LICENSE",
                "README.md",
                "policy/__init__.py",
                "policy/helper.py",
                "policy/resources.py",
                "policy/preparation.py",
                "policy/render_preflight.py",
                "features/grade/policy/__init__.py",
                "features/grade/policy/bank_publication.py",
                "features/grade/policy/color_authoring.py",
                "features/grade/policy/node.py",
                "kernel/__init__.py",
                "kernel/prepare.py",
                "kernel/lut.py",
                "kernel/stage2_bindings.py",
                "kernel/node_templates.py",
                "kernel/node_templates.blend",
                "kernel/node_templates.json",
                "kernel/grade_stack.glsl",
                "color_core/__init__.py",
                "color_core/linear.py",
            }
            self.assertTrue(expected.issubset(names), sorted(expected - names))
            self.assertFalse(any(name.startswith("blender_runtime/") for name in names))
            self.assertFalse(any(name.startswith("perceptual_grade_blender/")
                                 for name in names))
            self.assertNotIn("perceptual_grade_core/registration.py", names)
            self.assertFalse(any(name.startswith("perceptual_grade_core/") for name in names))
            self.assertFalse(any(name.startswith("src/") for name in names))
            self.assertFalse(any(name.startswith("template_build/") for name in names))
            self.assertFalse({name.replace(".", "/") + ".py"
                              for name in EMITTER_MODULES}.intersection(names))
            self.assertFalse(any(name in {
                "policy/compositor_publication.py",
                "policy/image_publication.py",
                "policy/parameter_publication.py",
                "runtime/drag_trace.py",
                "runtime/drag_diagnostics.py",
                "runtime/parameter_publication.py",
            } for name in names))
            self.assertNotIn("runtime/bake_diagnostics.py", names)
            self.assertFalse({
                "technical-report-audit.json",
                "technical_report_audit.py",
                "product_build/technical_report_audit.py",
            }.intersection(names))
            nodes_source = archive.read("features/grade/host.py")
            self.assertNotIn(b"PG_OT_bake_diagnostics", nodes_source)
            self.assertNotIn(b"perceptual_grade.bake_diagnostics", nodes_source)
            self.assertNotIn(b"PG_OT_start_drag_trace", nodes_source)
            self.assertNotIn(b"PG_OT_stop_drag_trace", nodes_source)
            self.assertNotIn(b"draw_trace_menu", nodes_source)
            self.assertIn("kernel/output_boundary.npz", names)
            manifest = tomllib.loads(archive.read("blender_manifest.toml").decode())
            self.assertEqual(manifest["id"], "perceptual_grade")
            self.assertEqual(manifest["name"], "Perceptual Grade")
            self.assertEqual(manifest["blender_version_min"], "5.2.0")
            self.assertEqual(manifest["license"], ["SPDX:GPL-3.0-or-later"])
            self.assertFalse(any(name.startswith("invariant/") for name in names))
            self.assertFalse(any(name.endswith("_contracts.py") for name in names))
            catalogs = {
                locale: json.loads(archive.read(
                    f"localization/locales/{locale}.json"
                ))
                for locale in ("en", "zh_HANS")
            }
            self.assertEqual(catalogs["en"].keys(), catalogs["zh_HANS"].keys())
            self.assertEqual(
                {name for name in names if name.endswith(".json")},
                {"localization/locales/en.json", "localization/locales/zh_HANS.json",
                 "kernel/node_templates.json"},
            )

    def test_runtime_imports_cannot_reach_procedural_emitters(self):
        """The installed product must work without development-only builders."""
        resource = files("tests.perceptual_grade_blender") / "extension.zip"
        with zipfile.ZipFile(resource) as archive:
            for name in archive.namelist():
                if not name.endswith(".py"):
                    continue
                source = ast.parse(archive.read(name), filename=name)
                package = "extension"
                if "/" in name:
                    package += "." + name.rsplit("/", 1)[0].replace("/", ".")
                for node in ast.walk(source):
                    if isinstance(node, ast.Import):
                        imports = [alias.name for alias in node.names]
                    elif isinstance(node, ast.ImportFrom):
                        target = node.module or ""
                        if node.level:
                            target = importlib.util.resolve_name(
                                "." * node.level + target, package
                            )
                        imports = [target, *(target + "." + alias.name
                                             for alias in node.names)]
                    else:
                        continue
                    for target in imports:
                        relative = target.removeprefix("extension.").removeprefix("color_tools.")
                        self.assertNotIn(relative, EMITTER_MODULES, (name, target))
                        self.assertNotIn("template_build", relative.split("."), (name, target))

    def test_external_proof_report_covers_every_shipped_policy(self):
        root = files("tests.perceptual_grade_blender")
        report = json.loads((root / "package-report.json").read_text())
        proved = {entry["runtime_source"] for entry in report["machine_proofs"].values()}
        with zipfile.ZipFile(root / "extension.zip") as archive:
            shipped = {
                name for name in archive.namelist()
                if name.endswith(".py") and name.rsplit("/", 1)[-1] != "__init__.py"
                and (name.startswith("policy/") or "/policy/" in name
                     or name in {"features/bake/policy.py",
                                 "features/interaction/policy.py",
                                 "features/vectorscope/authority.py"})
            }
        self.assertEqual(proved, shipped)


if __name__ == "__main__":
    unittest.main()
