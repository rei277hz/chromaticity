"""Proof exclusion is checked through dependencies before any action executes."""

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
        self.selection = {"builds": ["//:website"], "tests": ["//tests:smoke"]}
        self.closure = {"root" + label: {"buck.type": "alias"}
                        for label in check_targets.requested(self.selection)}
        self.closure["root//third_party:archive"] = {"buck.type": "http_archive"}
        self.output = io.StringIO()

    def check(self, closure=None, exit_code=0):
        result = subprocess.CompletedProcess([], exit_code, json.dumps(closure or self.closure), "query error" if exit_code else "")
        with patch.object(check_targets.subprocess, "run", return_value=result) as invocation:
            with redirect_stdout(self.output), redirect_stderr(self.output):
                status = check_targets.check(self.selection)
            command = invocation.call_args.args[0]
            self.assertEqual(command[:2], ["buck2", "uquery"])
            self.assertIn(check_targets.MAINTENANCE, command[2])
            self.assertNotIn("--allow-partial-graph", command)
            self.assertEqual(invocation.call_count, 1)
        return status

    def test_accepts_proof_free_closure_without_running_actions(self):
        self.assertEqual(self.check(), 0)

    def test_rejects_indirect_proof_rule_kinds(self):
        for kind in check_targets.FORBIDDEN_KINDS:
            with self.subTest(kind=kind):
                closure = {**self.closure, "root//indirect:proof": {"buck.type": kind}}
                self.assertEqual(self.check(closure), 1)
                self.assertIn("//indirect:proof", self.output.getvalue())

    def test_rejects_lean_proof_actions_declared_as_generic_generate(self):
        for label in check_targets.FORBIDDEN_LABELS:
            with self.subTest(label=label):
                closure = {**self.closure, "root" + label: {"buck.type": "generate"}}
                self.assertEqual(self.check(closure), 1)
                self.assertIn(label, self.output.getvalue())

    def test_allows_lean_distribution_used_as_compiler_tools(self):
        closure = {**self.closure, "root//tools/verification:lean": {"buck.type": "generate"}}
        self.assertEqual(self.check(closure), 0)

    def test_query_failure_is_not_a_clean_closure(self):
        self.assertEqual(self.check(exit_code=1), 1)

    def test_missing_target_or_rule_kind_is_not_a_clean_closure(self):
        closure = dict(self.closure)
        del closure["root//:website"]
        self.assertEqual(self.check(closure), 1)
        closure = {**self.closure, "root//indirect:unknown": {}}
        self.assertEqual(self.check(closure), 1)

    def test_invalid_json_and_timeout_fail_closed(self):
        with patch.object(check_targets.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, "{invalid", "")):
            with redirect_stderr(self.output):
                self.assertEqual(check_targets.check(self.selection), 1)
        with patch.object(check_targets.subprocess, "run", side_effect=subprocess.TimeoutExpired(["buck2"], 300)):
            with redirect_stderr(self.output):
                self.assertEqual(check_targets.check(self.selection), 1)

    def test_invalid_selection_never_invokes_buck(self):
        for labels in ([], ["//..."], ["//:a", "//:a"], ["//:a\") + deps(//:verify)"]):
            with self.subTest(labels=labels):
                with patch.object(check_targets.subprocess, "run") as invocation:
                    with redirect_stderr(self.output):
                        self.assertEqual(check_targets.check({"builds": labels, "tests": ["//:smoke"]}), 1)
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
