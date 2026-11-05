"""Validate and summarize drag-only Compositor display timing observations."""

import json
from pathlib import Path

from .shader_display_timing_report import compare_reports as _compare_reports
from .shader_display_timing_report import summarize_report as _summarize_report


SCHEMA = 1
CONTROLS = ("exposure", "fit")


def _profile_errors(report):
    errors = []
    profile = report.get("profile")
    if not isinstance(profile, dict):
        return ["profile must be an object"]
    if profile.get("context") != "compositor":
        errors.append("profile.context must be 'compositor'")
    if profile.get("scenarios") != ["drag"]:
        errors.append("profile.scenarios must be exactly ['drag']")
    controls = profile.get("controls")
    if not isinstance(controls, (list, tuple)):
        errors.append("profile.controls must list both Grade controls")
    else:
        controls = [value.rsplit(".", 1)[-1] if isinstance(value, str) else value
                    for value in controls]
        if (not all(isinstance(value, str) for value in controls)
                or set(controls) != set(CONTROLS) or len(controls) != len(CONTROLS)):
            errors.append("profile.controls must contain exposure and fit exactly once")
    return errors


def _evaluation_errors(session, ordinal):
    errors = []
    evaluations = session.get("compositor_evaluations")
    if not isinstance(evaluations, list):
        errors.append(f"session {ordinal} compositor_evaluations must be a list")
        evaluations = []

    def validate(capture, sample, label):
        receipt = capture.get("compositor_evaluation") if isinstance(capture, dict) else None
        if not isinstance(receipt, dict):
            errors.append(label + " has no Compositor evaluation receipt")
            return
        if receipt not in evaluations:
            errors.append(label + " Compositor evaluation receipt is absent from the session log")
        if "cancelled_ns" in receipt:
            errors.append(label + " Compositor evaluation receipt was cancelled")
        if receipt.get("output_allowed") is not True:
            errors.append(label + " Compositor evaluation did not allow current Grade output")
        if receipt.get("signature") != sample.get("signature"):
            errors.append(label + " Compositor evaluation signature does not match the sample")
        settings = sample.get("settings")
        if not isinstance(settings, dict) or not settings or receipt.get("settings") != settings:
            errors.append(label + " Compositor evaluation settings do not match the accepted settings")
        bounds = (sample.get("accepted_ns"), receipt.get("started_ns"),
                  receipt.get("finished_ns"), capture.get("start_ns"))
        if (not all(type(value) is int and value >= 0 for value in bounds)
                or not bounds[0] <= bounds[1] <= bounds[2] <= bounds[3]):
            errors.append(label + " Compositor evaluation must finish between acceptance and capture start")

    samples = session.get("samples", [])
    latest = {}
    if isinstance(samples, list):
        for index, sample in enumerate(samples):
            if not isinstance(sample, dict):
                continue
            if sample.get("control") in CONTROLS and sample.get("scenario") == "drag":
                latest[sample["control"]] = sample
            if sample.get("outcome") == "displayed":
                validate(sample.get("capture"), sample, f"session {ordinal} sample {index} capture")
    drags = session.get("drags", [])
    if isinstance(drags, list):
        for index, drag in enumerate(drags):
            if isinstance(drag, dict) and drag.get("control") in latest:
                validate(drag.get("final_capture"), latest[drag["control"]],
                         f"session {ordinal} drag {index} final capture")
    return errors


def summarize_report(report):
    """Apply shared pixel/timing validation and require a Compositor drag corpus."""
    result = _summarize_report(report)
    errors = list(result["errors"])
    errors.extend(_profile_errors(report))
    expected = {(control, "drag") for control in CONTROLS}
    for session in result["sessions"]:
        present = {(row["control"], row["scenario"]) for row in session["groups"]}
        if present != expected:
            errors.append(f"session {session['session']} must contain drag samples for exposure and fit only")
    sessions = report.get("sessions", [])
    if isinstance(sessions, list):
        for ordinal, session in enumerate(sessions):
            if isinstance(session, dict):
                errors.extend(_evaluation_errors(session, ordinal))
    result["errors"] = list(dict.fromkeys(errors))
    result["valid"] = not result["errors"]
    return result


def compare_reports(report, baseline):
    """Compare only valid Compositor drag reports with identical profile/environment."""
    candidate_summary = summarize_report(report)
    baseline_summary = summarize_report(baseline)
    reasons = []
    if not candidate_summary["valid"]:
        reasons.append("Candidate Compositor timing observations are invalid")
    if not baseline_summary["valid"]:
        reasons.append("Baseline Compositor timing observations are invalid")
    for name in ("environment", "profile"):
        if json.dumps(report.get(name), sort_keys=True) != json.dumps(
                baseline.get(name), sort_keys=True):
            reasons.append(name + " differs")
    comparison = _compare_reports(report, baseline)
    reasons.extend(comparison["reasons"])
    reasons = list(dict.fromkeys(reasons))
    if reasons:
        return {"compatible": False, "reasons": reasons, "comparisons": [], "warnings": []}
    return comparison


def _milliseconds(metric, statistic):
    return "—" if metric is None else f"{1000 * metric[statistic]:.3f}"


def write_report(output_dir, report, baseline=None):
    """Write raw Compositor observations and a drag-focused Markdown summary."""
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    report["summary"] = summarize_report(report)
    if baseline is None:
        report.pop("comparison", None)
    else:
        report["comparison"] = compare_reports(report, baseline)
    (output / "report.json").write_text(
        json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf8")

    lines = [
        "# Installed Compositor Grade display timing", "",
        "This report measures accepted Grade slider settings until the first matching "
        "live Viewer pixels in Blender's Image Editor are captured. It is a separate workload from "
        "the Shader viewport benchmark.", "",
        "Session aggregates are medians of process-level p50, p95, and maximum values. "
        "p50 uses the median and p95 uses the nearest rank; raw observations remain in JSON.", "",
        f"Valid observations: `{report['summary']['valid']}`.", "",
        "| Control | Displayed / accepted | Accepted p50 / p95 (ms) | Injected p50 / p95 (ms) | "
        "Displayed gap p50 / p95 (ms) | Accepted / displayed / superseded per second | "
        "Displayed / superseded (%) |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for row in report["summary"]["groups"]:
        counts, rates = row["counts"], row["rates"]
        rate_text = "—" if rates is None else " / ".join(
            f"{rates[name]:.2f}" for name in
            ("accepted_per_second", "displayed_per_second", "superseded_per_second"))
        fractions = "—" if rates is None else " / ".join(
            f"{100 * rates[name]:.2f}" for name in ("displayed_fraction", "superseded_fraction"))
        lines.append(
            f"| {row['control']} | {counts['displayed']} / {counts['accepted']} | "
            f"{_milliseconds(row['accepted_to_capture'], 'p50_seconds')} / "
            f"{_milliseconds(row['accepted_to_capture'], 'p95_seconds')} | "
            f"{_milliseconds(row['injected_to_capture'], 'p50_seconds')} / "
            f"{_milliseconds(row['injected_to_capture'], 'p95_seconds')} | "
            f"{_milliseconds(row['displayed_update_gap'], 'p50_seconds')} / "
            f"{_milliseconds(row['displayed_update_gap'], 'p95_seconds')} | {rate_text} | {fractions} |")
    lines.extend(("", "Final settling after native drag release:", "",
                  "| Control | Release to capture p50 (ms) | p95 (ms) | Median session max (ms) | "
                  "Absolute max (ms) |", "|---|---:|---:|---:|---:|"))
    for row in report["summary"]["drags"]:
        settling = row["release_to_capture"]
        lines.append(f"| {row['control']} | {_milliseconds(settling, 'p50_seconds')} | "
                     f"{_milliseconds(settling, 'p95_seconds')} | "
                     f"{_milliseconds(settling, 'maximum_seconds')} | "
                     f"{_milliseconds(settling, 'absolute_maximum_seconds')} |")

    lines.extend(("", f"Captured {report['summary']['capture_count']} X11 samples; per-capture "
                  f"duration p50 / p95 / max: "
                  f"{_milliseconds(report['summary']['capture_duration'], 'p50_seconds')} / "
                  f"{_milliseconds(report['summary']['capture_duration'], 'p95_seconds')} / "
                  f"{_milliseconds(report['summary']['capture_duration'], 'maximum_seconds')} ms; "
                  f"within-request cadence gap p50 / p95: "
                  f"{_milliseconds(report['summary']['capture_gap'], 'p50_seconds')} / "
                  f"{_milliseconds(report['summary']['capture_gap'], 'p95_seconds')} ms.", "",
                  "Observer cadence diagnostic:", "",
                  "| Control | Mode | Sessions | Injected motions | Draws | Injected / s | Draws / s |",
                  "|---|---|---:|---:|---:|---:|---:|"))
    for row in report["summary"]["observer_cadence"]:
        lines.append(f"| {row['control']} | {row['mode']} | {row['session_count']} | "
                     f"{row['injected_motion_events']} | {row['draws']} | "
                     f"{row['injected_per_second']:.2f} | {row['draws_per_second']:.2f} |")

    if report["summary"]["errors"]:
        lines.extend(("", "Observation errors:", "",
                      *("- " + error for error in report["summary"]["errors"])))
    if baseline is not None:
        comparison = report["comparison"]
        lines.extend(("", f"Baseline compatible: `{comparison['compatible']}`. "
                      f"Timing warnings: {len(comparison['warnings'])}."))
        if comparison["reasons"]:
            lines.extend(("", *("- " + reason for reason in comparison["reasons"])))
        if comparison["comparisons"]:
            lines.extend(("", "| Control | Metric | Statistic | Signed change | Change (%) | "
                          "Warning threshold | Warning |", "|---|---|---|---:|---:|---:|---|"))
            for row in comparison["comparisons"]:
                if row["unit"] == "seconds":
                    change = f"{1000 * row['change_seconds']:+.3f} ms"
                    threshold = f"{1000 * row['warning_threshold_seconds']:.3f} ms"
                else:
                    suffix = "/s" if row["unit"] == "per_second" else ""
                    change = f"{row['change']:+.3f}{suffix}"
                    threshold = f"{row['warning_threshold']:.3f}{suffix}"
                percent = "—" if row["change_percent"] is None else f"{row['change_percent']:+.2f}"
                lines.append(f"| {row.get('control', 'all')} | {row['metric']} | "
                             f"{row['statistic']} | {change} | {percent} | {threshold} | "
                             f"{'yes' if row['warning'] else 'no'} |")
    lines.extend(("", "Capture completion is an upper observed latency that includes X11 "
                  "readback and sampling delay; it does not establish physical monitor scanout. "
                  "Comparisons require identical environment and Compositor profile, including "
                  "measurement-harness hashes. Product hashes identify the measured subject. "
                  "Only drag observations for both exposure and Fit are accepted by this report. "
                  "Each pixel witness requires a logged, completed Compositor evaluation of those "
                  "accepted settings with current Grade output allowed before capture starts. "
                  "Timing warnings require changes beyond baseline session variation and capture "
                  "uncertainty; they do not establish statistical confidence. Missing or mismatched "
                  "final pixels invalidate the run, while superseded intermediate updates are retained.", ""))
    (output / "report.md").write_text("\n".join(lines), encoding="utf8")
    return report


__all__ = ("SCHEMA", "summarize_report", "compare_reports", "write_report")
