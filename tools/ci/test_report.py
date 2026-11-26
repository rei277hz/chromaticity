"""Regression checks for target counts, timing, and partial runs."""

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


def event(label, status=1, configuration="linux#123", *, duration_us=250_000):
    package, name = label.split(":", 1)
    result = {
        "name": "root" + label, "status": status,
        "target_label": {"label": {"package": "root" + package, "name": name},
                         "configuration": {"full_name": configuration},
                         "execution_configuration": None},
        "details": "Ran 100 individual test cases.",
    }
    if duration_us is not None:
        result["duration_us"] = duration_us
    return {"Event": {"data": {"Instant": {"data": {"TestResult": result}}}}}


class ReportTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.selection = {
            "builds": ["//:a", "//:b"],
            "tests": ["//tests:one", "//tests:two"],
            "test_purposes": {
                "//tests:one": "Exercise the first suite.",
                "//tests:two": "Exercise the second suite.",
            },
        }
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
        self.assertEqual(summary["targets"][1]["attempts"], 0)
        self.assertIsNone(summary["targets"][1]["duration_us"])
        self.assertEqual((summary["passed"], summary["total"]), (1, 2))

    def test_skip_and_missing_results_keep_expected_denominator(self):
        for values, status in (([event("//tests:one"), event("//tests:two", 3, duration_us=None)], "skipped"),
                               ([event("//tests:one")], "not_run")):
            with self.subTest(status=status):
                self.events(values)
                summary = self.collect()["tests"]
                self.assertEqual((summary["passed"], summary["total"], summary["outcome"]), (1, 2, "incomplete"))
                self.assertEqual(summary["targets"][1]["status"], status)
                self.assertEqual(summary["targets"][1]["attempts"], 0)
                self.assertIsNone(summary["targets"][1]["duration_us"])
                self.assertEqual(summary["issues"], [])

    def test_skip_and_omission_durations_are_not_execution_attempts(self):
        for status in (3, 4):
            with self.subTest(status=status):
                self.events([
                    event("//tests:one"),
                    event("//tests:two", status, duration_us=900_000),
                ])
                row = self.collect()["tests"]["targets"][1]
                self.assertEqual(row["status"], "skipped")
                self.assertEqual(row["attempts"], 0)
                self.assertIsNone(row["duration_us"])

    def test_discovery_is_not_a_passing_test(self):
        self.events([event("//tests:one", 9), event("//tests:two", 10)])
        tests = self.collect()["tests"]
        self.assertEqual(tests["passed"], 0)
        self.assertEqual([row["attempts"] for row in tests["targets"]], [0, 0])
        self.assertEqual([row["duration_us"] for row in tests["targets"]], [None, None])

    def test_conflicting_or_multiple_configuration_outcomes_are_not_green(self):
        self.events([event("//tests:one", 3), event("//tests:one", 1), event("//tests:two")])
        self.assertEqual(self.collect()["tests"]["targets"][0]["status"], "unknown")
        self.events([event("//tests:one"), event("//tests:one", configuration="other#456"), event("//tests:two")])
        self.assertEqual(self.collect()["tests"]["targets"][0]["status"], "unknown")

    def test_successful_retry_does_not_hide_failure(self):
        self.events([
            event("//tests:one", 9, duration_us=800_000),
            event("//tests:one", 2, duration_us=300_000),
            event("//tests:one", 8, duration_us=None),
            event("//tests:one", 8, duration_us=900_000),
            event("//tests:one", 1, duration_us=500_000),
            event("//tests:two"),
        ])
        tests = self.collect()["tests"]
        self.assertEqual(tests["targets"][0], {
            "target": "//tests:one",
            "purpose": "Exercise the first suite.",
            "status": "failed",
            "duration_us": 1_700_000,
            "attempts": 3,
        })
        self.assertEqual(tests["outcome"], "failed")
        self.assertEqual(tests["issues"], [])

    def test_invalid_attempt_duration_never_looks_like_a_complete_total(self):
        for duration in (None, -1, True, 1.5, "200"):
            with self.subTest(duration=duration):
                self.events([
                    event("//tests:one", duration_us=0),
                    event("//tests:one", duration_us=duration),
                    event("//tests:two"),
                ])
                tests = self.collect()["tests"]
                row = tests["targets"][0]
                self.assertEqual(row["status"], "passed")
                self.assertEqual(row["attempts"], 2)
                self.assertIsNone(row["duration_us"])
                self.assertEqual(tests["outcome"], "incomplete")
                self.assertTrue(any(
                    "duration" in issue and "//tests:one" in issue for issue in tests["issues"]
                ), tests["issues"])

    def test_measured_zero_duration_is_available(self):
        self.events([event("//tests:one", duration_us=0), event("//tests:two")])
        tests = self.collect()["tests"]
        self.assertEqual(tests["outcome"], "passed")
        self.assertEqual(tests["targets"][0]["duration_us"], 0)
        self.assertEqual(tests["targets"][0]["attempts"], 1)

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
        saved = json.loads((output / "summary.json").read_text())
        self.assertEqual(saved, summary)
        self.assertEqual(saved["schema"], 1)

    def test_markdown_timing_catalog_sorts_measured_targets_before_missing_timings(self):
        self.events([
            event("//tests:one", duration_us=200_000),
            event("//tests:two", duration_us=64_250_000),
        ])
        catalog = report.markdown(self.collect())
        self.assertIn("| Test ID | Purpose | Result | Duration | Attempts |", catalog)
        self.assertIn("| `//tests:two` | Exercise the second suite. | passed | 01:04.25 | 1 |", catalog)
        self.assertIn("| `//tests:one` | Exercise the first suite. | passed | 00:00.20 | 1 |", catalog)
        self.assertLess(catalog.index("`//tests:two`"), catalog.index("`//tests:one`"))

        self.events([event("//tests:two", duration_us=64_250_000)])
        catalog = report.markdown(self.collect())
        self.assertLess(catalog.index("`//tests:two`"), catalog.index("`//tests:one`"))
        self.assertIn("| `//tests:one` | Exercise the first suite. |", catalog)

    def test_markdown_purpose_is_plain_text_inside_one_cell(self):
        self.selection["test_purposes"]["//tests:one"] = "Alpha | <beta> & gamma"
        catalog = report.markdown(self.collect())
        row = next(line for line in catalog.splitlines() if "`//tests:one`" in line)
        self.assertNotIn("<beta>", row)
        self.assertIn("&lt;beta&gt;", row)
        self.assertIn("&amp; gamma", row)
        self.assertEqual(len(row.replace(r"\|", "").split("|")), 7)

    def test_selection_must_be_nonempty_and_unique(self):
        for builds in ([], ["//:a", "//:a"]):
            self.save("targets.json", {**self.selection, "builds": builds})
            with self.assertRaises(ValueError):
                report.targets(self.directory / "targets.json")

    def test_selection_requires_one_usable_purpose_per_test(self):
        purposes = self.selection["test_purposes"]
        for invalid in (
            None,
            {},
            {**purposes, "//tests:extra": "Extra suite."},
            {**purposes, "//tests:one": " "},
            {**purposes, "//tests:one": "Line one\nLine two"},
            {**purposes, "//tests:one": 7},
        ):
            with self.subTest(purposes=invalid):
                self.save("targets.json", {**self.selection, "test_purposes": invalid})
                with self.assertRaises(ValueError):
                    report.targets(self.directory / "targets.json")
        self.save("targets.json", self.selection)
        self.assertEqual(report.targets(self.directory / "targets.json"), self.selection)

    def test_ci_manifest_covers_every_selected_test(self):
        selection = report.targets()
        self.assertEqual(set(selection["test_purposes"]), set(selection["tests"]))


if __name__ == "__main__":
    unittest.main()
