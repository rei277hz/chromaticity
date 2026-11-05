"""Validation and summaries for installed Shader framebuffer latency."""

import json
from pathlib import Path
import tempfile
import unittest

from tools.perceptual_grade.reports.shader_display_timing_report import (
    compare_reports,
    summarize_report,
    summary,
    write_report,
)


def capture(sample_id, signature, start, end, previous_end=None, request_id=None):
    result = {
        "start_ns": start,
        "end_ns": end,
        "sample_id": sample_id,
        "signature": signature,
        "matches": True,
        "observed": [[0.125, 0.25, 0.5, 1.0]],
    }
    if previous_end is not None:
        result["previous_end_ns"] = previous_end
    if request_id is not None:
        result["request_id"] = request_id
    return result


def sample(sample_id, accepted, outcome="displayed", *, scenario="isolated",
           injected=None, interval=None):
    signature = f"settings-{sample_id}"
    injected = accepted - 2 if injected is None else injected
    start, end = interval or (accepted + 2, accepted + 5)
    return {
        "control": "exposure",
        "scenario": scenario,
        "sample_id": sample_id,
        "signature": signature,
        "requested_ns": accepted - 3,
        "injected_ns": injected,
        "accepted_ns": accepted,
        "outcome": outcome,
        "capture": (capture(sample_id, signature, start, end, start - 1)
                    if outcome == "displayed" else None),
    }


def make_report(session_samples, *, session=0, environment=None, profile=None):
    captures = [row["capture"] for row in session_samples if row.get("capture") is not None]
    drag_samples = [row for row in session_samples if row["scenario"] == "drag"]
    drags = []
    if drag_samples:
        final = drag_samples[-1]
        if final.get("outcome") == "displayed":
            drags.append({
                "control": final["control"],
                "started_ns": drag_samples[0]["accepted_ns"] - 1,
                "release_ns": final["accepted_ns"] + 1,
                "final_capture_end_ns": final["capture"]["end_ns"],
            })
    return {
        "schema": 1,
        "completed": True,
        "environment": environment or {"gpu": "Test GPU", "driver": "1"},
        "profile": profile or {"resolution": [1280, 720], "samples": 2},
        "source_sha256": {"extension": "source-hash"},
        "sessions": [{"session": session, "samples": session_samples,
                       "captures": [{"start_ns": row["start_ns"], "end_ns": row["end_ns"],
                                     **({"request_id": row["request_id"]}
                                        if "request_id" in row else {})}
                                    for row in captures],
                       "drags": drags}],
    }


def make_drag_report(*, drop_intermediate=False):
    started, released = 1_000_000_000, 2_000_000_000
    rows = [sample(index, started + index * 100_000_000,
                   outcome=("superseded" if drop_intermediate and index < 9 else "displayed"),
                   scenario="drag", interval=(started + index * 100_000_000 + 5_000_000,
                                              started + index * 100_000_000 + 10_000_000))
            for index in range(10)]
    report = make_report(rows)
    final = rows[-1]
    final_capture = capture(final["sample_id"], final["signature"],
                            released + 5_000_000, released + 10_000_000, released)
    report["sessions"][0]["drags"] = [{
        "control": "exposure", "started_ns": started, "release_ns": released,
        "final_capture_end_ns": final_capture["end_ns"], "final_capture": final_capture,
    }]
    report["sessions"][0]["captures"] = [
        {"start_ns": started + index * 10_000_000 + 5_000_000,
         "end_ns": started + index * 10_000_000 + 10_000_000}
        for index in range(101)
    ]
    return report


class ShaderDisplayTimingReportTests(unittest.TestCase):
    def test_summary_uses_median_and_nearest_rank_p95(self):
        self.assertIsNone(summary([]))
        self.assertEqual(summary(range(1, 101)), {
            "count": 100,
            "p50_seconds": 50.5,
            "p95_seconds": 95.0,
            "maximum_seconds": 100.0,
        })

    def test_acceptance_capture_injection_and_session_cadence_are_separate(self):
        samples = [
            sample(1, 100, interval=(102, 106)),
            sample(2, 200, interval=(203, 211)),
        ]
        report = make_report(samples)
        result = summarize_report(report)
        self.assertTrue(result["valid"], result["errors"])
        row, = result["groups"]
        self.assertEqual(row["counts"], {
            "accepted": 2, "displayed": 2, "superseded": 0, "missing": 0,
        })
        self.assertEqual(row["accepted_to_capture"]["session_count"], 1)
        self.assertEqual(result["sessions"][0]["groups"][0]["accepted_to_capture"]["count"], 2)
        self.assertEqual(row["accepted_to_capture"]["p50_seconds"], 8.5e-9)
        self.assertAlmostEqual(row["injected_to_capture"]["p50_seconds"], 10.5e-9, places=15)
        self.assertEqual(result["capture_gap"]["p95_seconds"], 105e-9)
        self.assertEqual(row["capture_gap"]["p95_seconds"], 9e-9)

    def test_capture_cadence_excludes_gaps_across_request_boundaries(self):
        first = sample(1, 100, interval=(102, 106))
        second = sample(2, 200, interval=(10_000_203, 10_000_211))
        first["capture"]["request_id"] = 1
        second["capture"]["request_id"] = 3
        report = make_report([first, second])
        result = summarize_report(report)
        self.assertTrue(result["valid"], result["errors"])
        self.assertIsNone(result["capture_gap"])
        self.assertIsNone(result["groups"][0]["capture_gap"])
        self.assertEqual(result["sessions"][0]["capture_duration"]["count"], 2)
        self.assertEqual(result["capture_count"], 2)

    def test_capture_cadence_includes_gaps_within_one_request(self):
        first = sample(1, 100, interval=(102, 106))
        second = sample(2, 200, interval=(203, 211))
        first["capture"]["request_id"] = 4
        second["capture"]["request_id"] = 4
        result = summarize_report(make_report([first, second]))
        self.assertTrue(result["valid"], result["errors"])
        self.assertEqual(result["sessions"][0]["capture_gap"]["count"], 1)
        self.assertEqual(result["capture_gap"]["p50_seconds"], 105e-9)

    def test_writer_reports_capture_cost_and_observer_cadence(self):
        report = make_report([sample(1, 100), sample(2, 200)])
        report["sessions"][0]["observer_on"] = {
            "exposure": {"duration_seconds": 2., "draws": 30,
                         "injected_motion_events": 20},
        }
        report["sessions"][0]["observer_off"] = {
            "exposure": {"duration_seconds": 2., "draws": 40,
                         "injected_motion_events": 24},
        }
        with tempfile.TemporaryDirectory() as directory:
            write_report(directory, report)
            markdown = (Path(directory) / "report.md").read_text()
        self.assertIn("capture duration p50 / p95 / max", markdown)
        self.assertIn("Observer cadence diagnostic", markdown)
        self.assertIn("| exposure | observer_on | 1 | 20 | 30 | 10.00 | 15.00 |", markdown)
        self.assertIn("| exposure | observer_off | 1 | 24 | 40 | 12.00 | 20.00 |", markdown)

    def test_reused_sample_identity_and_mismatched_capture_signature_are_invalid(self):
        first = sample(1, 100)
        second = sample(1, 200)
        second["capture"]["signature"] = "stale-signature"
        report = make_report([first, second])
        result = summarize_report(report)
        self.assertFalse(result["valid"])
        self.assertTrue(any("reuses a sample identity" in error for error in result["errors"]))
        self.assertTrue(any("capture signature does not match" in error for error in result["errors"]))

    def test_capture_must_follow_acceptance_and_be_in_session_capture_log(self):
        row = sample(1, 100, interval=(99, 105))
        report = make_report([row])
        report["sessions"][0]["captures"] = []
        result = summarize_report(report)
        self.assertFalse(result["valid"])
        self.assertTrue(any("capture is absent" in error for error in result["errors"]))
        self.assertTrue(any("capture precedes input acceptance" in error
                            for error in result["errors"]))

    def test_capture_must_match_expected_palette(self):
        row = sample(1, 100)
        row["capture"]["matches"] = False
        result = summarize_report(make_report([row]))
        self.assertFalse(result["valid"])
        self.assertTrue(any("palette witness does not match" in error
                            for error in result["errors"]))

    def test_missing_isolated_sample_invalidates_timing_run(self):
        row = sample(1, 100, outcome="missing")
        row["capture"] = None
        result = summarize_report(make_report([row]))
        self.assertFalse(result["valid"])
        self.assertTrue(any("isolated update was not displayed" in error
                            for error in result["errors"]))

    def test_duplicate_capture_cannot_certify_two_accepted_occurrences(self):
        first = sample(1, 100, interval=(202, 205))
        second = sample(2, 200, interval=(202, 205))
        result = summarize_report(make_report([first, second]))
        self.assertFalse(result["valid"])
        self.assertTrue(any("reuses another sample's capture" in error
                            for error in result["errors"]))

    def test_aggregate_uses_medians_of_session_statistics_not_pooled_samples(self):
        report = make_report([sample(1, 100, interval=(101, 102))])
        other = make_report([sample(2, 100, interval=(101, 120)),
                             sample(3, 200, interval=(201, 220)),
                             sample(4, 300, interval=(301, 320))])
        report["sessions"].append(other["sessions"][0])
        result = summarize_report(report)
        self.assertTrue(result["valid"], result["errors"])
        row = result["groups"][0]
        self.assertEqual(row["accepted_to_capture"]["session_count"], 2)
        self.assertAlmostEqual(row["accepted_to_capture"]["p50_seconds"], 11e-9, places=15)
        self.assertNotEqual(row["accepted_to_capture"]["p50_seconds"], 20e-9)

    def test_drag_reports_superseded_updates_and_requires_final_matching_capture(self):
        rows = [
            sample(1, 100, scenario="drag", outcome="superseded"),
            sample(2, 200, scenario="drag", outcome="displayed"),
        ]
        result = summarize_report(make_report(rows))
        self.assertTrue(result["valid"], result["errors"])
        group, = result["groups"]
        self.assertEqual(group["counts"]["superseded"], 1)
        self.assertEqual(result["drags"][0]["control"], "exposure")
        self.assertAlmostEqual(group["rates"]["accepted_per_second"], 2e9 / 102)
        self.assertAlmostEqual(group["rates"]["superseded_per_second"], 1e9 / 102)
        self.assertEqual(group["rates"]["displayed_fraction"], .5)

        report = make_report(rows)
        report["sessions"][0]["drags"] = []
        failed = summarize_report(report)
        self.assertFalse(failed["valid"])
        self.assertTrue(any("no final exposure drag observation" in error
                            for error in failed["errors"]))

        missing = make_report(rows)
        missing["sessions"][0]["samples"][-1]["outcome"] = "missing"
        missing["sessions"][0]["samples"][-1]["capture"] = None
        failed = summarize_report(missing)
        self.assertFalse(failed["valid"])
        self.assertTrue(any("final exposure drag sample was not displayed" in error
                            for error in failed["errors"]))

    def test_comparison_requires_same_environment_and_profile(self):
        values = [sample(1, 100), sample(2, 200)]
        baseline = make_report(values)
        candidate = make_report([sample(3, 100), sample(4, 200)],
                                environment={"gpu": "Other GPU", "driver": "1"})
        result = compare_reports(candidate, baseline)
        self.assertFalse(result["compatible"])
        self.assertIn("environment differs", result["reasons"])
        self.assertEqual(result["comparisons"], [])

        candidate = make_report([sample(3, 100), sample(4, 200)],
                                profile={"resolution": [640, 480], "samples": 2})
        self.assertIn("profile differs", compare_reports(candidate, baseline)["reasons"])

    def test_comparison_warns_only_above_baseline_spread_and_capture_noise(self):
        baseline_sessions = [
            make_report([sample(1, 100, interval=(102, 106)),
                         sample(2, 200, interval=(203, 211))], session=0)["sessions"][0],
            make_report([sample(3, 100, interval=(102, 106)),
                         sample(4, 200, interval=(203, 211))], session=1)["sessions"][0],
        ]
        baseline = make_report([], environment={"gpu": "Test GPU", "driver": "1"})
        baseline["sessions"] = baseline_sessions
        fast = make_report([sample(5, 100, interval=(102, 106)),
                            sample(6, 200, interval=(203, 211))])
        fast["sessions"][0]["captures"] = [
            {"start_ns": 102, "end_ns": 106}, {"start_ns": 203, "end_ns": 211},
        ]
        result = compare_reports(fast, baseline)
        self.assertTrue(result["compatible"], result["reasons"])
        self.assertFalse(result["warnings"])

        slow = make_report([sample(7, 100, interval=(200_000_102, 200_000_106)),
                            sample(8, 200, interval=(200_000_203, 200_000_211))])
        slow["sessions"][0]["captures"] = [
            {"start_ns": 200_000_102, "end_ns": 200_000_106},
            {"start_ns": 200_000_203, "end_ns": 200_000_211},
        ]
        regression = compare_reports(slow, baseline)
        self.assertTrue(regression["compatible"], regression["reasons"])
        self.assertTrue(regression["warnings"])
        self.assertTrue(all(row["increase_seconds"] > row["warning_threshold_seconds"]
                            for row in regression["warnings"]))

    def test_comparison_includes_signed_change_percent_and_absolute_maximum(self):
        baseline_sessions = [
            make_report([sample(1, 100, interval=(102, 106)),
                         sample(2, 200, interval=(203, 211))], session=0)["sessions"][0],
            make_report([sample(3, 100, interval=(102, 106)),
                         sample(4, 200, interval=(203, 211))], session=1)["sessions"][0],
        ]
        baseline = make_report([], environment={"gpu": "Test GPU", "driver": "1"})
        baseline["sessions"] = baseline_sessions
        candidate = make_report([sample(5, 100, interval=(112, 116)),
                                 sample(6, 200, interval=(213, 221))])
        result = compare_reports(candidate, baseline)
        self.assertTrue(result["compatible"], result["reasons"])
        timing = next(row for row in result["comparisons"]
                      if row["metric"] == "accepted_to_capture"
                      and row["statistic"] == "p50_seconds")
        self.assertGreater(timing["change_seconds"], 0)
        self.assertGreater(timing["change_percent"], 0)
        summary_row = summarize_report(candidate)["groups"][0]["accepted_to_capture"]
        self.assertEqual(summary_row["absolute_maximum_seconds"], 21e-9)

    def test_baseline_session_spread_can_exceed_capture_uncertainty(self):
        baseline = make_report([sample(1, 100, interval=(109, 110)),
                                sample(2, 200, interval=(209, 210))])
        other = make_report([sample(3, 100, interval=(129, 130)),
                             sample(4, 200, interval=(229, 230))])
        baseline["sessions"].append(other["sessions"][0])
        candidate = make_report([sample(5, 100, interval=(134, 135)),
                                 sample(6, 200, interval=(234, 235))])
        for report in (baseline, candidate):
            for session in report["sessions"]:
                intervals = {(row["start_ns"], row["end_ns"]) for row in session["captures"]}
                intervals.update((end - 1, end) for end in range(2, 252, 2))
                session["captures"] = [{"start_ns": start, "end_ns": end}
                                       for start, end in sorted(intervals)]
        result = compare_reports(candidate, baseline)
        self.assertTrue(result["compatible"], result["reasons"])
        row = next(row for row in result["comparisons"] if row["metric"] == "accepted_to_capture"
                   and row["statistic"] == "p50_seconds")
        self.assertAlmostEqual(row["change_seconds"], 15e-9, places=15)
        self.assertAlmostEqual(row["baseline_spread_seconds"], 20e-9, places=15)
        self.assertGreater(row["baseline_spread_seconds"], row["capture_uncertainty_seconds"])
        self.assertFalse(row["warning"])

    def test_dropping_drag_displays_warns_even_with_low_displayed_sample_latency(self):
        baseline, candidate = make_drag_report(), make_drag_report(drop_intermediate=True)
        baseline_summary, candidate_summary = summarize_report(baseline), summarize_report(candidate)
        self.assertTrue(baseline_summary["valid"], baseline_summary["errors"])
        self.assertTrue(candidate_summary["valid"], candidate_summary["errors"])
        self.assertAlmostEqual(baseline_summary["groups"][0]["rates"]["displayed_per_second"], 10.)
        self.assertAlmostEqual(candidate_summary["groups"][0]["rates"]["displayed_per_second"], 1.)
        result = compare_reports(candidate, baseline)
        self.assertTrue(result["compatible"], result["reasons"])
        warnings = {row["metric"]: row for row in result["warnings"]}
        self.assertIn("displayed_per_second", warnings)
        self.assertIn("superseded_fraction", warnings)
        self.assertAlmostEqual(warnings["displayed_per_second"]["change_percent"], -90.)
        self.assertNotIn("accepted_to_capture", warnings)

    def test_global_maximum_is_not_confused_with_median_session_maxima(self):
        report = make_report([sample(1, 100, interval=(101, 102))])
        other = make_report([sample(2, 100, interval=(101, 120))])
        report["sessions"].append(other["sessions"][0])
        metric = summarize_report(report)["groups"][0]["accepted_to_capture"]
        self.assertAlmostEqual(metric["maximum_seconds"], 11e-9, places=15)
        self.assertAlmostEqual(metric["absolute_maximum_seconds"], 20e-9, places=15)

    def test_profile_requires_each_expected_control_and_scenario_per_session(self):
        report = make_report([sample(1, 100)])
        report["profile"]["controls"] = ["pg_linear.exposure", "pg_tone.fit"]
        report["profile"]["scenarios"] = ["isolated", "drag"]
        result = summarize_report(report)
        self.assertFalse(result["valid"])
        self.assertTrue(any("has no fit/isolated samples" in error for error in result["errors"]))
        self.assertTrue(any("has no exposure/drag samples" in error for error in result["errors"]))

    def test_post_release_final_capture_may_reobserve_current_signature(self):
        rows = [sample(1, 100, scenario="drag")]
        report = make_report(rows)
        drag = report["sessions"][0]["drags"][0]
        drag["release_ns"] = rows[-1]["accepted_ns"] + 10
        drag["final_capture_end_ns"] = rows[-1]["accepted_ns"] + 20
        drag["final_capture"] = capture(
            rows[-1]["sample_id"], rows[-1]["signature"],
            rows[-1]["accepted_ns"] + 15, rows[-1]["accepted_ns"] + 20,
            rows[-1]["accepted_ns"] + 10,
        )
        report["sessions"][0]["captures"].append({
            "start_ns": drag["final_capture"]["start_ns"],
            "end_ns": drag["final_capture"]["end_ns"],
        })
        result = summarize_report(report)
        self.assertTrue(result["valid"], result["errors"])
        self.assertAlmostEqual(result["drags"][0]["release_to_capture"]["p50_seconds"], 10e-9)

    def test_provenance_hash_does_not_affect_environment_compatibility(self):
        baseline = make_report([sample(1, 100), sample(2, 200)])
        candidate = make_report([sample(3, 100), sample(4, 200)])
        candidate["source_sha256"] = {"extension": "new-source-hash"}
        result = compare_reports(candidate, baseline)
        self.assertTrue(result["compatible"], result["reasons"])

    def test_writer_preserves_raw_samples_and_emits_summary_and_comparison(self):
        baseline = make_report([sample(1, 100), sample(2, 200)])
        report = make_report([sample(3, 100), sample(4, 200)])
        raw = json.loads(json.dumps(report))
        with tempfile.TemporaryDirectory() as directory:
            result = write_report(directory, report, baseline)
            saved = json.loads((Path(directory) / "report.json").read_text())
            markdown = (Path(directory) / "report.md").read_text()
        self.assertEqual(saved["sessions"][0]["samples"], raw["sessions"][0]["samples"])
        self.assertTrue(saved["summary"]["valid"])
        self.assertTrue(saved["comparison"]["compatible"])
        self.assertIn("Accepted p95", markdown)
        self.assertIn("physical monitor presentation", markdown)
        self.assertIs(result, report)


if __name__ == "__main__":
    unittest.main()
