"""CI requires product proofs and rejects unrelated validation dependencies."""

from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import check_targets


class TargetGuardTests(unittest.TestCase):
    def setUp(self):
        self.selection = {
            "builds": [check_targets.REQUIRED_PROOFS,
                       check_targets.PRODUCT + ":extension"],
            "tests": [check_targets.PRODUCT + "/tests:policy_node"],
        }
        self.closure = {"root" + label: {"buck.type": "alias"}
                        for label in check_targets.requested(self.selection)}
        self.closure["root" + check_targets.REQUIRED_PROOFS] = {
            "buck.type": "verification_group"}
        self.closure["root" + check_targets.PRODUCT + ":proof_node"] = {
            "buck.type": "invariant_proof"}
        self.closure["root//libraries/invariant:verifier"] = {
            "buck.type": "python_binary"}
        self.output = io.StringIO()

    def check(self, closure=None, exit_code=0):
        result = subprocess.CompletedProcess(
            [], exit_code, json.dumps(self.closure if closure is None else closure), "query failed" if exit_code else "")
        with patch.object(check_targets.subprocess, "run", return_value=result) as invocation:
            with redirect_stderr(self.output), redirect_stdout(self.output):
                status = check_targets.check(self.selection)
            command = invocation.call_args.args[0]
            self.assertEqual(command[:2], ["buck2", "uquery"])
            self.assertNotIn("//tools/rust-build:distribution", command[2])
            self.assertEqual(invocation.call_count, 1)
        return status

    def test_accepts_product_proofs_and_ordinary_shared_build_dependencies(self):
        closure = dict(self.closure)
        for root in check_targets.EXCLUDED_PROJECTS:
            closure["root" + root + ":model_code"] = {"buck.type": "python_library"}
        self.assertEqual(self.check(closure), 0)

    def test_rejects_indirect_foreign_test_and_proof_rules(self):
        for kind in (*check_targets.VALIDATION_KINDS, "python_test", "rust_test", "sh_test"):
            with self.subTest(kind=kind):
                closure = {**self.closure, "root//other:check": {"buck.type": kind}}
                self.assertEqual(self.check(closure), 1)
                self.assertIn("//other:check", self.output.getvalue())

    def test_rejects_excluded_projects_even_through_generic_actions(self):
        for root in check_targets.EXCLUDED_PROJECTS:
            for label, kind in ((root + ":check", "generate"),
                                (root + "/proofs:check", "generate")):
                with self.subTest(label=label):
                    closure = {**self.closure, "root" + label: {"buck.type": kind}}
                    self.assertEqual(self.check(closure), 1)
                    self.assertIn(label, self.output.getvalue())

    def test_rejects_reference_proof_namespace_through_generic_actions(self):
        for label in (
            check_targets.REFERENCE_PROOFS + ":color_model",
            check_targets.REFERENCE_PROOFS + ":color_model[report]",
            check_targets.REFERENCE_PROOFS + "/color_model:proof",
        ):
            for kind in ("generate", "source_tree"):
                with self.subTest(label=label, kind=kind):
                    closure = {**self.closure, "root" + label: {"buck.type": kind}}
                    self.assertEqual(self.check(closure), 1)
                    self.assertIn(label, self.output.getvalue())

    def test_accepts_reference_source_and_resource_dependencies(self):
        reference = "root//libraries/perceptual-grade-reference"
        closure = {**self.closure, **{
            reference + suffix: {"buck.type": kind}
            for suffix, kind in (
                (":numerical_oracle_for_tests", "python_library"),
                (":sources", "source_tree"),
                (":documentation", "export_file"),
                (":generated_resource", "generate"),
                ("/proofs-support:resources", "source_tree"),
            )
        }}
        self.assertEqual(self.check(closure), 0)

    def test_proof_gate_cannot_be_replaced_by_an_alias_or_empty_group(self):
        closure = dict(self.closure)
        closure["root" + check_targets.REQUIRED_PROOFS] = {"buck.type": "alias"}
        self.assertEqual(self.check(closure), 1)
        closure = dict(self.closure)
        del closure["root" + check_targets.PRODUCT + ":proof_node"]
        self.assertEqual(self.check(closure), 1)

    def test_query_failure_is_not_a_clean_closure(self):
        self.assertEqual(self.check(exit_code=1), 1)

    def test_missing_target_or_rule_kind_is_not_a_clean_closure(self):
        closure = dict(self.closure)
        del closure["root" + check_targets.PRODUCT + ":extension"]
        self.assertEqual(self.check(closure), 1)
        closure = {**self.closure, "root//dependency:unknown": {}}
        self.assertEqual(self.check(closure), 1)

    def test_invalid_json_and_timeout_fail_closed(self):
        with patch.object(check_targets.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, "{invalid", "")):
            with redirect_stderr(self.output):
                self.assertEqual(check_targets.check(self.selection), 1)
        with patch.object(check_targets.subprocess, "run", side_effect=subprocess.TimeoutExpired(["buck2"], 300)):
            with redirect_stderr(self.output):
                self.assertEqual(check_targets.check(self.selection), 1)

    def test_out_of_scope_or_missing_proofs_never_invokes_buck(self):
        for label in ("//:verify", "//libraries/invariant:tests",
                      "//products/perceptual-grade-next-blender-old:verify",
                      "//products/perceptual-grade-blender:verify"):
            for group in ("builds", "tests"):
                with self.subTest(label=label, group=group):
                    selection = {key: list(value) for key, value in self.selection.items()}
                    selection[group].append(label)
                    with patch.object(check_targets.subprocess, "run") as invocation:
                        with redirect_stderr(self.output):
                            self.assertEqual(check_targets.check(selection), 1)
                        invocation.assert_not_called()
        selection = {**self.selection, "builds": [check_targets.PRODUCT + ":extension"]}
        with patch.object(check_targets.subprocess, "run") as invocation:
            with redirect_stderr(self.output):
                self.assertEqual(check_targets.check(selection), 1)
            invocation.assert_not_called()

    def test_invalid_selection_never_invokes_buck(self):
        for labels in ([], ["//..."], [check_targets.REQUIRED_PROOFS] * 2,
                       ["//:a\") + deps(//:verify)"]):
            with self.subTest(labels=labels):
                with patch.object(check_targets.subprocess, "run") as invocation:
                    with redirect_stderr(self.output):
                        self.assertEqual(check_targets.check({**self.selection, "builds": labels}), 1)
                    invocation.assert_not_called()

    def test_cli_reads_selected_manifest(self):
        with tempfile.TemporaryDirectory() as temporary:
            manifest = Path(temporary) / "targets.json"
            manifest.write_text(json.dumps(self.selection))
            with patch("sys.argv", ["check_targets.py", "--manifest", str(manifest)]):
                with patch.object(check_targets, "check", return_value=0) as check:
                    self.assertEqual(check_targets.main(), 0)
                    check.assert_called_once_with(self.selection)


if __name__ == "__main__":
    unittest.main()
