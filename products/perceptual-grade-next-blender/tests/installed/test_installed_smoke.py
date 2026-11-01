"""Run the packaged Next extension in a clean pinned Blender profile."""

from importlib.resources import files
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile


class InstalledSmokeTests(unittest.TestCase):
    def test_packaged_extension_registers_and_recovers_a_saved_grade(self):
        resources = files("tests.installed")
        binary_name = "Blender.app/Contents/MacOS/Blender" if sys.platform == "darwin" else "blender"
        blender = Path(str(resources / "blender" / binary_name)).resolve()
        runner = Path(str(resources / "runner.py")).resolve()
        with tempfile.TemporaryDirectory(prefix="pg-next-installed-") as directory:
            root = Path(directory)
            repository = root / "repository"
            package = repository / "perceptual_grade"
            package.mkdir(parents=True)
            with zipfile.ZipFile(str(resources / "extension.zip")) as archive:
                archive.extractall(package)

            environment = {
                key: value for key, value in os.environ.items()
                if key not in {
                    "PYTHONPATH", "PYTHONHOME", "BLENDER_USER_SCRIPTS",
                    "BLENDER_SYSTEM_SCRIPTS", "BLENDER_SYSTEM_PYTHON",
                }
            }
            environment.update(
                BLENDER_USER_CONFIG=str(root / "config"),
                BLENDER_USER_EXTENSIONS=str(root / "extensions"),
                OPENBLAS_NUM_THREADS="1",
                OMP_NUM_THREADS="1",
                PYTHONDONTWRITEBYTECODE="1",
            )
            if sys.platform == "linux":
                link_tree = Path(str(resources)).resolve().parents[1]
                abi = link_tree
                system_libraries = Path(str(resources / "xvfb")).resolve() / "usr/lib/x86_64-linux-gnu"
                existing = environment.get("LD_LIBRARY_PATH", "")
                paths = [str(abi), str(system_libraries)]
                if existing:
                    paths.append(existing)
                environment["LD_LIBRARY_PATH"] = os.pathsep.join(paths)
            boundaries = (
                "field_upload", "binding_only", "metadata_publication",
                "structural_replacement", "committed_replacement",
            )
            reopened = {}
            baseline = root / "installed-grade-baseline.blend"
            result = subprocess.run(
                [
                    str(blender), "--background", "--factory-startup",
                    "--disable-autoexec", "--python-exit-code", "1",
                    "--python", str(runner), "--", "create",
                    str(repository), str(baseline), str(root / "create.json"),
                ],
                cwd=root, env=environment, capture_output=True, text=True,
                timeout=900,
            )
            self.assertEqual(result.returncode, 0, result.stdout + "\n" + result.stderr)
            for boundary in boundaries:
                project = root / ("installed-grade-" + boundary + ".blend")
                report = root / (boundary + ".json")
                shutil.copyfile(baseline, project)
                for mode in ("crash_boundary", "reopen"):
                    result = subprocess.run(
                        [
                            str(blender), "--background", "--factory-startup",
                            "--disable-autoexec", "--python-exit-code", "1",
                            "--python", str(runner), "--", mode,
                            str(repository), str(project), str(report), boundary,
                        ],
                        cwd=root,
                        env=environment,
                        capture_output=True,
                        text=True,
                        timeout=900,
                    )
                    details = result.stdout + "\n" + result.stderr
                    if mode == "crash_boundary":
                        self.assertEqual(result.returncode, 99, details)
                        self.assertTrue(report.is_file(), details)
                        crash = json.loads(report.read_text())
                        self.assertEqual(crash.get("mode"), mode, details)
                        self.assertEqual(crash.get("boundary"), boundary, details)
                        if boundary == "field_upload":
                            self.assertTrue(crash.get("field_backups"), details)
                        if boundary in {"binding_only", "metadata_publication"}:
                            self.assertTrue(crash.get("grade_snapshot", {}).get("bindings"), details)
                        continue
                    if report.is_file():
                        details += "\nAcceptance report:\n" + report.read_text()
                    self.assertEqual(result.returncode, 0, details)
                    self.assertTrue(report.is_file(), details)
                    data = json.loads(report.read_text())
                    self.assertEqual(data.get("mode"), mode, details)
                    self.assertTrue(data.get("passed"), details)
                    if mode == "reopen":
                        self.assertEqual(data.get("crash_boundary"), boundary, details)
                        self.assertTrue(data["crash_rollback_verified"], details)
                        reopened[boundary] = data
            data = reopened["binding_only"]
            self.assertEqual(data["blender"], [5, 2, 2])
            self.assertTrue(data["recovery_complete"], data)
            self.assertGreater(data["packed_field_count"], 0, data)
            self.assertEqual(data["restart_result"], ["FINISHED"], data)
            self.assertEqual(data["restart_phase"], "active", data)
            self.assertEqual(data["project_phase"], "active", data)
            self.assertEqual(set(data["wrapped_menus"]), {"TOPBAR_MT_file", "TOPBAR_MT_render"}, data)
            self.assertTrue(data["grade_ready_after_restart"], data)
            self.assertEqual(data["packed_fields_retained"], data["packed_field_count"], data)
            self.assertTrue(data["restart_recovery_fault_observed"], data)
            self.assertTrue(data["restart_recovery_retry_succeeded"], data)
            self.assertEqual(data["packed_fields_retained_after_retry"],
                             data["packed_field_count"], data)
            self.assertTrue(data["extension_origin"].endswith("perceptual_grade/__init__.py"))
            stack_project = root / "installed-stack.blend"
            stack_report = root / "stack-replacement.json"
            for mode in (
                "create_stack", "crash_stack_replacement",
                "reopen_stack_replacement",
            ):
                result = subprocess.run(
                    [
                        str(blender), "--background", "--factory-startup",
                        "--disable-autoexec", "--python-exit-code", "1",
                        "--python", str(runner), "--", mode,
                        str(repository), str(stack_project), str(stack_report),
                    ],
                    cwd=root, env=environment, capture_output=True, text=True,
                    timeout=900,
                )
                details = result.stdout + "\n" + result.stderr
                if mode == "crash_stack_replacement":
                    self.assertEqual(result.returncode, 99, details)
                    self.assertTrue(stack_report.is_file(), details)
                    crash = json.loads(stack_report.read_text())
                    self.assertEqual(crash.get("mode"), mode, details)
                    continue
                self.assertEqual(result.returncode, 0, details)
                self.assertTrue(stack_report.is_file(), details)
                stack_data = json.loads(stack_report.read_text())
                self.assertEqual(stack_data.get("mode"), mode, details)
                self.assertTrue(stack_data.get("passed"), details)
                if mode == "reopen_stack_replacement":
                    self.assertTrue(stack_data["ready"], details)
                    self.assertEqual(stack_data["evaluator"], "stack_65_lut", details)
            print("Installed Next recovery boundaries:", json.dumps({
                "grade": {
                    key: value["crash_rollback_verified"] for key, value in reopened.items()
                },
                "stack_replacement": stack_data["ready"],
            }, sort_keys=True), flush=True)
