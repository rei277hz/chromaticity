"""Exercise CI failure handling without invoking repository builds or Docker."""

import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("ci_run", HERE / "run.py")
ci_run = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ci_run)


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.calls = self.directory / "calls.jsonl"
        self.reports = self.directory / "reports"
        self.targets = {"builds": ["//:product"], "tests": ["//tests:smoke"]}
        selection_guard = patch.object(ci_run, "check_targets", return_value=0)
        self.guard = selection_guard.start()
        self.addCleanup(selection_guard.stop)
        fake = self.directory / "buck2"
        fake.write_text(f"#!{sys.executable}\n" + '''
import json, os, sys
from pathlib import Path
args = sys.argv[1:]
with open(os.environ["FAKE_CALLS"], "a") as stream:
    stream.write(json.dumps(args) + "\\n")
if args[0] == "build":
    print("building product", flush=True)
    sys.exit(int(os.environ.get("FAKE_BUILD_STATUS", "0")))
if args[0] == "test":
    print("running smoke", flush=True)
    if not os.environ.get("FAKE_NO_EVENTS"):
        Path(args[args.index("--event-log") + 1]).write_text("test event bytes")
    sys.exit(int(os.environ.get("FAKE_TEST_STATUS", "0")))
if args[:2] == ["log", "show"]:
    if not Path(args[2]).exists():
        print("missing test event log", file=sys.stderr)
        sys.exit(1)
    print(json.dumps({"Event": {"test_result": "fixture"}}))
''')
        fake.chmod(0o755)
        self.environment = {
            "PATH": str(self.directory) + os.pathsep + os.environ["PATH"],
            "FAKE_CALLS": str(self.calls),
        }

    def invoke(self, **environment):
        with patch.dict(os.environ, self.environment | environment), contextlib.redirect_stdout(io.StringIO()):
            return ci_run.run(self.reports, self.targets)

    def test_build_failure_still_runs_tests_and_retains_original_exit(self):
        self.assertEqual(self.invoke(FAKE_BUILD_STATUS="32"), 32)
        self.assertEqual(json.loads((self.reports / "exits.json").read_text()),
                         {"selection": 0, "build": 32, "test": 0, "events": 0})
        calls = [json.loads(line) for line in self.calls.read_text().splitlines()]
        self.assertEqual([command[0] for command in calls], ["build", "test", "log"])
        self.assertIn("building product", (self.reports / "build.log").read_text())
        self.assertIn("running smoke", (self.reports / "test.log").read_text())
        self.assertEqual(json.loads((self.reports / "test-events.jsonl").read_text()),
                         {"Event": {"test_result": "fixture"}})
        self.assertEqual(calls[2][2], str(self.reports / "test-events.pb.zst"))
        self.assertIn("--no-remote", calls[2])

    def test_missing_events_fail_and_old_evidence_is_removed(self):
        self.reports.mkdir()
        for name in ("build-report.json", "test-build-report.json", "test-events.pb.zst", "test-events.jsonl"):
            (self.reports / name).write_text("stale successful result")
        self.assertEqual(self.invoke(FAKE_NO_EVENTS="1"), 1)
        self.assertFalse((self.reports / "build-report.json").exists())
        self.assertFalse((self.reports / "test-build-report.json").exists())
        self.assertEqual((self.reports / "test-events.jsonl").read_text(), "")
        self.assertIn("missing test event log", (self.reports / "events-errors.log").read_text())
        self.assertEqual(json.loads((self.reports / "exits.json").read_text())["events"], 1)

    def test_test_failure_is_not_masked_by_event_collection(self):
        self.assertEqual(self.invoke(FAKE_TEST_STATUS="32"), 32)
        self.assertEqual(json.loads((self.reports / "exits.json").read_text()),
                         {"selection": 0, "build": 0, "test": 32, "events": 0})

    def test_interruption_records_incomplete_run_and_does_not_start_tests(self):
        with patch.object(ci_run, "execute", side_effect=ci_run.Interrupted(signal.SIGTERM)) as execute:
            self.assertEqual(ci_run.run(self.reports, self.targets), 143)
        self.assertEqual(execute.call_count, 1)
        self.assertEqual(json.loads((self.reports / "exits.json").read_text()),
                         {"selection": 0, "build": -15, "test": None, "events": None})

    def test_out_of_scope_selection_stops_before_any_build_or_test(self):
        self.guard.return_value = 1
        with patch.object(ci_run, "execute") as execute:
            self.assertEqual(ci_run.run(self.reports, self.targets), 1)
        execute.assert_not_called()
        self.assertEqual(json.loads((self.reports / "exits.json").read_text()),
                         {"selection": 1, "build": None, "test": None, "events": None})

    def test_rejects_empty_or_duplicate_selection(self):
        manifest = self.directory / "targets.json"
        for builds in ([], ["//:product", "//:product"], ["--help"]):
            manifest.write_text(json.dumps({"builds": builds, "tests": ["//tests:smoke"]}))
            with self.assertRaises(ValueError):
                ci_run.load_targets(manifest)


class RuntimeTests(unittest.TestCase):
    def test_refuses_checkout_without_disposable_marker(self):
        environment = dict(os.environ)
        environment.pop("CI_DISPOSABLE_CHECKOUT", None)
        result = subprocess.run(["bash", str(HERE / "runtime.sh"), "true"],
                                env=environment, capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn("disposable checkout", result.stderr)

    def test_runtime_preserves_command_arguments_and_limits_environment(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            source = base / "checkout"
            script = source / "tools/ci/runtime.sh"
            script.parent.mkdir(parents=True)
            shutil.copyfile(HERE / "runtime.sh", script)
            binaries = base / "bin"
            binaries.mkdir()
            calls = base / "docker-calls.jsonl"
            docker = binaries / "docker"
            docker.write_text(f"#!{sys.executable}\nimport json,sys\n"
                              f"with open({str(calls)!r}, 'a') as stream: stream.write(json.dumps(sys.argv[1:]) + '\\n')\n")
            docker.chmod(0o755)
            buck = binaries / "buck2"
            buck.write_text("#!/bin/sh\nexit 0\n")
            buck.chmod(0o755)
            environment = dict(os.environ, PATH=str(binaries) + os.pathsep + os.environ["PATH"],
                               CI_DISPOSABLE_CHECKOUT="1", CI_CACHE_DIR=str(base / "cache"),
                               CI_BUCK2_BINARY=str(buck), GITHUB_TOKEN="must-not-be-forwarded")
            result = subprocess.run(["bash", str(script), "python3", "command.py", "argument with spaces"],
                                    env=environment, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            commands = [json.loads(line) for line in calls.read_text().splitlines()]
            self.assertEqual(commands[0][0], "build")
            self.assertEqual(commands[0][commands[0].index("--target") + 1], "ci")
            run = commands[1]
            self.assertEqual(run[-3:], ["python3", "command.py", "argument with spaces"])
            self.assertEqual(run[run.index("--ulimit") + 1], "nofile=65536:65536")
            self.assertIn("BUCK_ISOLATION_DIR=ci", run)
            self.assertNotIn("GITHUB_TOKEN", " ".join(run))
            self.assertNotIn("must-not-be-forwarded", " ".join(run))
            self.assertIn("tools/ci/select_local.py /workspace", run[-5])


if __name__ == "__main__":
    unittest.main()
