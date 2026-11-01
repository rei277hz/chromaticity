"""Regression checks for target counts, partial runs, and safe badge rendering."""

import json
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET

import report


def build_report(labels, failed=()):
    return {"success": not failed, "results": {
        "root" + label: {"success": "FAIL" if label in failed else "SUCCESS", "errors": [],
                         "configured": {"linux#123": {"success": "FAIL" if label in failed else "SUCCESS",
                                                       "errors": []}}}
        for label in labels}}


def event(label, status=1, configuration="linux#123"):
    package, name = label.split(":", 1)
    return {"Event": {"data": {"Instant": {"data": {"TestResult": {
        "name": "root" + label, "status": status,
        "target_label": {"label": {"package": "root" + package, "name": name},
                         "configuration": {"full_name": configuration},
                         "execution_configuration": None},
        "details": "Ran 100 individual cases; these are still one Buck target."}}}}}}


class ReportTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.selection = {"builds": ["//:a", "//:b"], "tests": ["//tests:one", "//tests:two"]}
        self.save("build-report.json", build_report(self.selection["builds"]))
        self.save("test-build-report.json", build_report(self.selection["tests"]))
        self.save("exits.json", {"build": 0, "test": 0, "events": 0})
        self.events(event(label) for label in self.selection["tests"])

    def save(self, name, value):
        (self.directory / name).write_text(json.dumps(value))

    def events(self, values):
        (self.directory / "test-events.jsonl").write_text("\n".join(json.dumps(value) for value in values) + "\n")

    def collect(self):
        return report.collect(self.directory, self.selection, {})

    def test_counts_requested_targets_and_not_cases_or_synthetic_checks(self):
        self.events([event("//tests:one"), event("//tests:one"), event("//tests:two"),
                     event("//third_party:download"), event("//other:unselected")])
        summary = self.collect()
        for key in ("builds", "tests"):
            self.assertEqual((summary[key]["passed"], summary[key]["total"], summary[key]["outcome"]),
                             (2, 2, "passed"))

    def test_failed_test_does_not_pass_because_executable_built(self):
        self.events([event("//tests:one"), event("//tests:two", 2)])
        self.save("exits.json", {"build": 0, "test": 32, "events": 0})
        summary = self.collect()
        self.assertEqual(summary["tests"]["passed"], 1)
        self.assertEqual(summary["tests"]["outcome"], "failed")
        self.assertEqual(summary["builds"]["outcome"], "passed")

    def test_failed_executable_build_is_not_a_missing_pass(self):
        self.save("test-build-report.json", build_report(self.selection["tests"], ["//tests:two"]))
        self.events([event("//tests:one")])
        summary = self.collect()["tests"]
        self.assertEqual(summary["targets"][1]["status"], "failed")
        self.assertEqual((summary["passed"], summary["total"]), (1, 2))

    def test_skip_and_missing_results_keep_expected_denominator(self):
        for values, status in (([event("//tests:one"), event("//tests:two", 3)], "skipped"),
                               ([event("//tests:one")], "not_run")):
            with self.subTest(status=status):
                self.events(values)
                summary = self.collect()["tests"]
                self.assertEqual((summary["passed"], summary["total"], summary["outcome"]), (1, 2, "incomplete"))
                self.assertEqual(summary["targets"][1]["status"], status)

    def test_discovery_is_not_a_passing_test(self):
        self.events([event("//tests:one", 9), event("//tests:two", 10)])
        self.assertEqual(self.collect()["tests"]["passed"], 0)

    def test_conflicting_or_multiple_configuration_outcomes_are_not_green(self):
        self.events([event("//tests:one", 3), event("//tests:one", 1), event("//tests:two")])
        self.assertEqual(self.collect()["tests"]["targets"][0]["status"], "unknown")
        self.events([event("//tests:one"), event("//tests:one", configuration="other#456"), event("//tests:two")])
        self.assertEqual(self.collect()["tests"]["targets"][0]["status"], "unknown")

    def test_successful_retry_does_not_hide_failure(self):
        self.events([event("//tests:one", 2), event("//tests:one", 8), event("//tests:one", 1), event("//tests:two")])
        self.assertEqual(self.collect()["tests"]["targets"][0]["status"], "failed")

    def test_malformed_event_log_does_not_make_partial_success_green(self):
        with (self.directory / "test-events.jsonl").open("a") as stream:
            stream.write("{broken json\n")
        summary = self.collect()["tests"]
        self.assertEqual(summary["passed"], 2)
        self.assertEqual(summary["outcome"], "incomplete")

    def test_missing_all_reports_produces_unknown_report(self):
        for path in self.directory.iterdir():
            path.unlink()
        summary = self.collect()
        for key in ("builds", "tests"):
            self.assertEqual((summary[key]["passed"], summary[key]["total"], summary[key]["outcome"]),
                             (0, 2, "incomplete"))

    def test_failed_event_export_or_interrupted_command_cannot_be_green(self):
        for exits in ({"build": 0, "test": 0, "events": 1},
                      {"build": 0, "test": -15, "events": 0},
                      {"build": 0, "test": None, "events": 0},
                      {"build": 0, "test": False, "events": 0}):
            with self.subTest(exits=exits):
                self.save("exits.json", exits)
                self.assertNotEqual(self.collect()["tests"]["outcome"], "passed")

    def test_rejected_selection_cannot_reuse_passing_evidence(self):
        for selection in (1, None, False):
            with self.subTest(selection=selection):
                self.save("exits.json", {"selection": selection, "build": 0, "test": 0, "events": 0})
                summary = self.collect()
                for group in ("builds", "tests"):
                    self.assertNotEqual(summary[group]["outcome"], "passed")
                    self.assertIn("CI target selection was rejected or incomplete", summary[group]["issues"])

    def test_missing_build_record_does_not_validate_passing_test(self):
        self.save("test-build-report.json", build_report(["//tests:one"]))
        self.assertEqual(self.collect()["tests"]["targets"][1]["status"], "unknown")

    def test_build_report_failure_or_malformed_output_cannot_be_green(self):
        data = build_report(self.selection["builds"])
        data["success"] = False
        self.save("build-report.json", data)
        self.assertNotEqual(self.collect()["builds"]["outcome"], "passed")
        self.save("build-report.json", {"success": True, "results": []})
        self.assertEqual(self.collect()["builds"]["passed"], 0)

    def test_svg_escapes_text_and_output_files_are_self_contained(self):
        summary = self.collect()
        rendered = report.badge('builds <unsafe> & "text"', summary["builds"])
        root = ET.fromstring(rendered)
        self.assertEqual(root.attrib["aria-label"], 'builds <unsafe> & "text": 2/2 passed')
        output = self.directory / "badges"
        report.write(summary, output)
        self.assertEqual({p.name for p in output.iterdir()}, set(report.OUTPUTS))
        self.assertIn("not individual test cases", (output / "README.md").read_text())

    def test_selection_must_be_nonempty_and_unique(self):
        for selection in ({"builds": [], "tests": ["//test:a"]},
                          {"builds": ["//:a", "//:a"], "tests": ["//test:a"]}):
            self.save("targets.json", selection)
            with self.assertRaises(ValueError):
                report.targets(self.directory / "targets.json")


if __name__ == "__main__":
    unittest.main()
