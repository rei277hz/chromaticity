"""Validation and comparison for installed Compositor display timing."""

import json
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from tools.perceptual_grade.reports.compositor_display_timing_report import (
    compare_reports,
    summarize_report,
    write_report,
)


def capture(sample, start, end, previous_end=None):
    row = {
        "start_ns": start,
        "end_ns": end,
        "sample_id": sample["sample_id"],
        "signature": sample["signature"],
        "matches": True,
        "observed": [[12, 31, 72], [30, 56, 92], [79, 105, 133], [145, 164, 183]],
        "request_id": 1,
    }
    if previous_end is not None:
        row["previous_end_ns"] = previous_end
    return row


def make_report(*, context="compositor", scenario="drag", device="GPU",
                precision="AUTO", image_size=(438, 841), measurement=None):
    samples, captures, drags, evaluations = [], [], [], []
    sample_id = 0
    for control_index, control in enumerate(("exposure", "fit")):
        base = control_index * 1000
        first = {
            "control": control, "scenario": scenario, "sample_id": sample_id,
            "signature": f"{control}-endpoint-a", "requested_ns": base + 90,
            "injected_ns": base + 95, "accepted_ns": base + 100, "outcome": "superseded",
            "capture": None, "settings": {control: -.5},
        }
        sample_id += 1
        final = {
            "control": control, "scenario": scenario, "sample_id": sample_id,
            "signature": f"{control}-endpoint-final", "requested_ns": base + 190,
            "injected_ns": base + 195, "accepted_ns": base + 200, "outcome": "displayed",
            "settings": {control: .5},
        }
        receipt = {"signature": final["signature"], "settings": final["settings"],
                   "started_ns": base + 200, "finished_ns": base + 201,
                   "output_allowed": True}
        evaluations.append(deepcopy(receipt))
        shown = capture(final, base + 202, base + 205, base + 201)
        shown["compositor_evaluation"] = deepcopy(receipt)
        final["capture"] = shown
        settled = capture(final, base + 225, base + 230, base + 205)
        settled["compositor_evaluation"] = deepcopy(receipt)
        captures.extend((shown, settled))
        samples.extend((first, final))
        drags.append({
            "control": control, "started_ns": base + 80, "release_ns": base + 210,
            "final_capture_end_ns": base + 230, "final_capture": settled,
        })
        sample_id += 1
    profile = {
        "context": context,
        "scenarios": [scenario],
        "controls": ["pg_linear.exposure", "pg_tone.fit"],
        "compositor_device": device,
        "compositor_precision": precision,
        "image_size": list(image_size),
        "measurement_sha256": measurement or {"runner.py": "runner-hash"},
    }
    return {
        "schema": 1,
        "completed": True,
        "environment": {"blender": "5.2.2", "renderer": "llvmpipe"},
        "profile": profile,
        "source_sha256": {"extension": "grade-hash"},
        "sessions": [{"session": 0, "samples": samples, "captures": captures, "drags": drags,
                      "compositor_evaluations": evaluations}],
    }


class CompositorDisplayTimingReportTests(unittest.TestCase):
    def test_valid_drag_report_summarizes_both_grade_controls(self):
        report = make_report()
        result = summarize_report(report)
        self.assertTrue(result["valid"], result["errors"])
        self.assertEqual({(row["control"], row["scenario"]) for row in result["groups"]},
                         {("exposure", "drag"), ("fit", "drag")})
        for row in result["groups"]:
            self.assertEqual(row["counts"]["accepted"], 2)
            self.assertEqual(row["counts"]["displayed"], 1)
            self.assertEqual(row["counts"]["superseded"], 1)
        self.assertEqual(len(result["drags"]), 2)

    def test_report_rejects_wrong_context_or_non_drag_scenarios(self):
        for report in (make_report(context="shader"), make_report(scenario="isolated")):
            result = summarize_report(report)
            self.assertFalse(result["valid"])
        self.assertTrue(any("profile.context" in error
                            for error in summarize_report(make_report(context="shader"))["errors"]))
        self.assertTrue(any("profile.scenarios" in error
                            for error in summarize_report(make_report(scenario="isolated"))["errors"]))

    def test_report_requires_both_controls_in_each_session(self):
        report = make_report()
        report["sessions"][0]["samples"] = [
            row for row in report["sessions"][0]["samples"] if row["control"] == "exposure"
        ]
        report["sessions"][0]["drags"] = [
            row for row in report["sessions"][0]["drags"] if row["control"] == "exposure"
        ]
        result = summarize_report(report)
        self.assertFalse(result["valid"])
        self.assertTrue(any("exposure and fit" in error for error in result["errors"]))

    def test_bad_final_witness_invalidates_report(self):
        report = make_report()
        report["sessions"][0]["drags"][0]["final_capture"]["matches"] = False
        result = summarize_report(report)
        self.assertFalse(result["valid"])
        self.assertTrue(any("final palette witness" in error for error in result["errors"]))

    def test_displayed_sample_and_final_capture_require_logged_receipts(self):
        for witness in ("sample", "final"):
            report = make_report()
            session = report["sessions"][0]
            capture = (session["samples"][1]["capture"] if witness == "sample"
                       else session["drags"][0]["final_capture"])
            del capture["compositor_evaluation"]
            with self.subTest(witness=witness):
                result = summarize_report(report)
                self.assertFalse(result["valid"])
                self.assertTrue(any("no Compositor evaluation receipt" in error
                                    for error in result["errors"]))
        report = make_report()
        report["sessions"][0]["compositor_evaluations"] = []
        result = summarize_report(report)
        self.assertFalse(result["valid"])
        self.assertTrue(any("receipt is absent from the session log" in error
                            for error in result["errors"]))

    def test_cancelled_or_disallowed_evaluation_cannot_certify_pixels(self):
        for update, expected in (({"cancelled_ns": 202}, "receipt was cancelled"),
                                 ({"output_allowed": False}, "did not allow current Grade output")):
            report = make_report()
            session = report["sessions"][0]
            receipt = session["samples"][1]["capture"]["compositor_evaluation"]
            receipt.update(update)
            session["compositor_evaluations"].append(deepcopy(receipt))
            with self.subTest(update=update):
                result = summarize_report(report)
                self.assertFalse(result["valid"])
                self.assertTrue(any(expected in error for error in result["errors"]))

    def test_evaluation_signature_and_settings_must_match_acceptance(self):
        for update, expected in (({"signature": "old-grade"}, "signature does not match"),
                                 ({"settings": {"exposure": -.5}}, "settings do not match")):
            report = make_report()
            session = report["sessions"][0]
            receipt = session["samples"][1]["capture"]["compositor_evaluation"]
            receipt.update(update)
            session["compositor_evaluations"].append(deepcopy(receipt))
            with self.subTest(update=update):
                result = summarize_report(report)
                self.assertFalse(result["valid"])
                self.assertTrue(any(expected in error for error in result["errors"]))

    def test_evaluation_interval_must_fit_between_acceptance_and_capture(self):
        for update in ({"started_ns": 199}, {"started_ns": 202, "finished_ns": 201},
                       {"finished_ns": 203}, {"started_ns": True}):
            report = make_report()
            session = report["sessions"][0]
            receipt = session["samples"][1]["capture"]["compositor_evaluation"]
            receipt.update(update)
            session["compositor_evaluations"].append(deepcopy(receipt))
            with self.subTest(update=update):
                result = summarize_report(report)
                self.assertFalse(result["valid"])
                self.assertTrue(any("between acceptance and capture start" in error
                                    for error in result["errors"]))

    def test_comparison_rejects_context_device_precision_size_and_harness_changes(self):
        baseline = make_report()
        candidates = (
            make_report(context="shader"),
            make_report(device="CPU"),
            make_report(precision="FULL"),
            make_report(image_size=(320, 180)),
            make_report(measurement={"runner.py": "changed-runner-hash"}),
        )
        for candidate in candidates:
            with self.subTest(profile=candidate["profile"]):
                comparison = compare_reports(candidate, baseline)
                self.assertFalse(comparison["compatible"])
                self.assertTrue(any("profile differs" in reason
                                    for reason in comparison["reasons"]))
                self.assertEqual(comparison["comparisons"], [])

    def test_identical_compositor_profiles_compare_and_writer_uses_own_title(self):
        candidate, baseline = make_report(), make_report()
        comparison = compare_reports(candidate, baseline)
        self.assertTrue(comparison["compatible"], comparison["reasons"])
        with tempfile.TemporaryDirectory() as directory:
            result = write_report(directory, candidate, baseline)
            markdown = (Path(directory) / "report.md").read_text(encoding="utf8")
            saved = json.loads((Path(directory) / "report.json").read_text(encoding="utf8"))
        self.assertIn("# Installed Compositor Grade display timing", markdown)
        self.assertIn("separate workload from the Shader viewport benchmark", markdown)
        self.assertTrue(saved["comparison"]["compatible"])
        self.assertTrue(result["summary"]["valid"])


if __name__ == "__main__":
    unittest.main()
