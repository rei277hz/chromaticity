"""Summarize signature-matched Shader framebuffer timing observations."""

import json
from math import ceil, isfinite
from pathlib import Path
from statistics import median


SCHEMA = 1
CONTROLS = ("exposure", "fit")
SCENARIOS = ("isolated", "drag")
METRICS = ("accepted_to_capture", "injected_to_capture")
GROUP_METRICS = (*METRICS, "displayed_update_gap", "capture_gap")
STATISTICS = ("p50_seconds", "p95_seconds", "maximum_seconds")
COMPARISON_STATISTICS = (*STATISTICS, "absolute_maximum_seconds")
RATE_NAMES = ("accepted_per_second", "displayed_per_second", "superseded_per_second",
              "displayed_fraction", "superseded_fraction")


def summary(values):
    """Describe finite nonnegative seconds; p95 uses the nearest rank."""
    values = sorted(float(value) for value in values)
    if not values:
        return None
    if any(not isfinite(value) or value < 0 for value in values):
        raise ValueError("Timing samples must be finite and nonnegative")
    return {
        "count": len(values),
        "p50_seconds": median(values),
        "p95_seconds": values[ceil(.95 * len(values)) - 1],
        "maximum_seconds": values[-1],
    }


def _timestamp(value, label, errors):
    if type(value) is not int or value < 0:
        errors.append(label + " must be a nonnegative integer nanosecond timestamp")
        return None
    return value


def _finite_pixels(values):
    if not isinstance(values, (list, tuple)) or not values:
        return False
    for value in values:
        if isinstance(value, (list, tuple)):
            if not _finite_pixels(value):
                return False
        elif isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value):
            return False
    return True


def _capture_interval(capture, label, errors):
    if not isinstance(capture, dict):
        errors.append(label + " is missing")
        return None
    start = _timestamp(capture.get("start_ns"), label + ".start_ns", errors)
    end = _timestamp(capture.get("end_ns"), label + ".end_ns", errors)
    if start is None or end is None:
        return None
    if end < start:
        errors.append(label + " ends before it starts")
        return None
    return start, end


def _aggregate_metrics(rows, metric):
    values = [row[metric] for row in rows if row.get(metric) is not None]
    if not values:
        return None
    return {
        "session_count": len(values),
        **{name: median(value[name] for value in values) for name in STATISTICS},
        "absolute_maximum_seconds": max(value["maximum_seconds"] for value in values),
    }


def _observer_cadence(session, prefix, errors):
    rows = []
    for mode in ("observer_on", "observer_off"):
        controls = session.get(mode, {})
        if not isinstance(controls, dict):
            errors.append(prefix + " " + mode + " must be an object")
            continue
        for control, value in controls.items():
            label = f"{prefix} {mode} {control}"
            if control not in CONTROLS or not isinstance(value, dict):
                errors.append(label + " is not a supported control observation")
                continue
            duration = value.get("duration_seconds")
            draws, inputs = value.get("draws"), value.get("injected_motion_events")
            if (isinstance(duration, bool) or not isinstance(duration, (int, float))
                    or not isfinite(duration) or duration <= 0
                    or type(draws) is not int or draws < 0
                    or type(inputs) is not int or inputs < 0):
                errors.append(label + " requires a positive duration and nonnegative event/draw counts")
                continue
            rows.append({"control": control, "mode": mode, "duration_seconds": duration,
                         "injected_motion_events": inputs, "draws": draws,
                         "injected_per_second": inputs / duration,
                         "draws_per_second": draws / duration})
    return rows


def _session_summary(session, ordinal, errors):
    prefix = f"session {ordinal}"
    if not isinstance(session, dict):
        errors.append(prefix + " must be an object")
        return {"session": ordinal, "groups": [], "drags": [], "capture_gap": None,
                "capture_duration": None, "capture_count": 0, "observer_cadence": []}
    captures = session.get("captures", [])
    samples = session.get("samples", [])
    drags = session.get("drags", [])
    if not isinstance(captures, list) or not isinstance(samples, list) or not isinstance(drags, list):
        errors.append(prefix + " samples, captures, and drags must be lists")
        return {"session": ordinal, "groups": [], "drags": [], "capture_gap": None,
                "capture_duration": None, "capture_count": 0, "observer_cadence": []}
    if not samples:
        errors.append(prefix + " has no accepted samples")
    capture_intervals, capture_set, capture_rows = [], set(), []
    for index, capture in enumerate(captures):
        interval = _capture_interval(capture, f"{prefix} capture {index}", errors)
        if interval is not None:
            if capture_intervals and interval[0] < capture_intervals[-1][1]:
                errors.append(prefix + " captures overlap or are out of order")
            if interval in capture_set:
                errors.append(prefix + " reuses a capture interval")
            capture_intervals.append(interval)
            capture_set.add(interval)
            capture_rows.append((capture, interval))
    gaps, continuous_captures = [], set()
    for (left, left_interval), (right, right_interval) in zip(capture_rows, capture_rows[1:]):
        if left.get("request_id") == right.get("request_id"):
            gaps.append((right_interval[1] - left_interval[1]) / 1e9)
            continuous_captures.add(right_interval)
    capture_requests = {interval: row.get("request_id") for row, interval in capture_rows}
    groups, identities, assigned_captures, displayed = {}, set(), set(), set()
    latest_drag = {}
    for index, sample in enumerate(samples):
        label = f"{prefix} sample {index}"
        if not isinstance(sample, dict):
            errors.append(label + " must be an object")
            continue
        control, scenario = sample.get("control"), sample.get("scenario")
        if control not in CONTROLS or scenario not in SCENARIOS:
            errors.append(label + " has an unsupported control or scenario")
            continue
        group = groups.setdefault((control, scenario), {
            "control": control, "scenario": scenario,
            "counts": {"accepted": 0, "displayed": 0, "superseded": 0, "missing": 0},
            **{name: [] for name in GROUP_METRICS},
            "_accepted": [], "_displayed": [],
        })
        group["counts"]["accepted"] += 1
        sample_id = sample.get("sample_id")
        if (type(sample_id) is not int or sample_id < 0) and not (
                isinstance(sample_id, str) and sample_id):
            errors.append(label + " has no valid occurrence identity")
        elif sample_id in identities:
            errors.append(label + " reuses a sample identity")
        else:
            identities.add(sample_id)
        if not isinstance(sample.get("signature"), str) or not sample["signature"]:
            errors.append(label + " has no settings signature")
        requested = _timestamp(sample.get("requested_ns"), label + ".requested_ns", errors)
        injected = _timestamp(sample.get("injected_ns"), label + ".injected_ns", errors)
        accepted = _timestamp(sample.get("accepted_ns"), label + ".accepted_ns", errors)
        if None not in (requested, injected, accepted) and not requested <= injected <= accepted:
            errors.append(label + " input timestamps are out of order")
        outcome = sample.get("outcome")
        if outcome not in ("displayed", "superseded", "missing"):
            errors.append(label + " has no terminal outcome")
            continue
        group["counts"][outcome] += 1
        if accepted is not None:
            group["_accepted"].append((accepted, outcome))
        if scenario == "drag":
            latest_drag[control] = sample
        if outcome != "displayed":
            if sample.get("capture") is not None:
                errors.append(label + " has a capture without a displayed outcome")
            if scenario == "isolated":
                errors.append(label + " isolated update was not displayed")
            continue
        capture = sample.get("capture")
        interval = _capture_interval(capture, label + " capture", errors)
        if interval is None:
            continue
        start, end = interval
        if interval in assigned_captures:
            errors.append(label + " reuses another sample's capture")
        assigned_captures.add(interval)
        if interval not in capture_set:
            errors.append(label + " capture is absent from the session capture log")
        for key in ("sample_id", "signature"):
            if capture.get(key) != sample.get(key):
                errors.append(label + " capture " + key + " does not match")
        if not _finite_pixels(capture.get("observed")):
            errors.append(label + " capture has no finite pixel witness")
        if capture.get("matches") is not True:
            errors.append(label + " palette witness does not match expected pixels")
        previous = capture.get("previous_end_ns")
        if previous is not None:
            previous = _timestamp(previous, label + " capture.previous_end_ns", errors)
            if previous is not None:
                if previous > start:
                    errors.append(label + " previous capture ends after capture start")
                elif capture_requests.get(interval) is None or interval in continuous_captures:
                    group["capture_gap"].append((end - previous) / 1e9)
        if accepted is None or injected is None or accepted > start or injected > accepted:
            errors.append(label + " capture precedes input acceptance")
            continue
        group["accepted_to_capture"].append((end - accepted) / 1e9)
        group["injected_to_capture"].append((end - injected) / 1e9)
        group["_displayed"].append(end)
        displayed.add((control, scenario, end))
    drag_groups, drag_windows = {}, {}
    for index, drag in enumerate(drags):
        label = f"{prefix} drag {index}"
        if not isinstance(drag, dict) or drag.get("control") not in CONTROLS:
            errors.append(label + " has an unsupported control")
            continue
        control = drag["control"]
        release = _timestamp(drag.get("release_ns"), label + ".release_ns", errors)
        final = _timestamp(drag.get("final_capture_end_ns"), label + ".final_capture_end_ns", errors)
        drag_groups.setdefault(control, [])
        if release is None or final is None:
            continue
        accepted_times = [at for at, _outcome in groups.get((control, "drag"), {}).get("_accepted", [])]
        started = drag.get("started_ns", min(accepted_times) if accepted_times else None)
        started = _timestamp(started, label + ".started_ns", errors)
        if started is not None:
            if started >= release:
                errors.append(label + " release must follow drag start")
            else:
                drag_windows.setdefault(control, []).append((started, release))
        final_capture = drag.get("final_capture")
        if final_capture is not None:
            interval = _capture_interval(final_capture, label + " final capture", errors)
            latest = latest_drag.get(control, {})
            if interval is not None:
                if interval not in capture_set:
                    errors.append(label + " final capture is absent from the session capture log")
                if interval[0] < release or interval[1] != final:
                    errors.append(label + " final capture bounds do not match release and completion")
            for key in ("sample_id", "signature"):
                if not isinstance(final_capture, dict) or final_capture.get(key) != latest.get(key):
                    errors.append(label + " final capture " + key + " does not match final demand")
            if not isinstance(final_capture, dict) or not _finite_pixels(final_capture.get("observed")):
                errors.append(label + " final capture has no finite pixel witness")
            if not isinstance(final_capture, dict) or final_capture.get("matches") is not True:
                errors.append(label + " final palette witness does not match expected pixels")
        if final < release:
            errors.append(label + " final capture precedes release")
        elif final_capture is None and (control, "drag", final) not in displayed:
            errors.append(label + " final capture does not identify a displayed drag sample")
        else:
            drag_groups[control].append((final - release) / 1e9)
    for control, sample in latest_drag.items():
        if sample.get("outcome") != "displayed":
            errors.append(prefix + " final " + control + " drag sample was not displayed")
        if control not in drag_groups:
            errors.append(prefix + " has no final " + control + " drag observation")
    rows = []
    for group in groups.values():
        ends = sorted(group.pop("_displayed"))
        group["displayed_update_gap"] = [(right - left) / 1e9 for left, right in zip(ends, ends[1:])]
        accepted = group.pop("_accepted")
        rates, duration = None, None
        if group["scenario"] == "drag" and group["control"] in drag_windows:
            windows = drag_windows[group["control"]]
            duration = sum(release - started for started, release in windows) / 1e9
            active = [(at, outcome) for at, outcome in accepted
                      if any(started <= at < release for started, release in windows)]
            active_displays = sum(any(started <= end < release for started, release in windows) for end in ends)
            rates = {
                "accepted_per_second": len(active) / duration,
                "displayed_per_second": active_displays / duration,
                "superseded_per_second": sum(outcome == "superseded" for _at, outcome in active) / duration,
                "displayed_fraction": group["counts"]["displayed"] / len(accepted) if accepted else 0.,
                "superseded_fraction": group["counts"]["superseded"] / len(accepted) if accepted else 0.,
            }
        rows.append({**group, **{name: summary(group[name]) for name in GROUP_METRICS},
                     "drag_seconds": duration, "rates": rates})
    return {
        "session": ordinal,
        "groups": rows,
        "drags": [{"control": control, "release_to_capture": summary(values)}
                  for control, values in drag_groups.items()],
        "capture_gap": summary(gaps),
        "capture_duration": summary((end - start) / 1e9 for start, end in capture_intervals),
        "capture_count": len(capture_intervals),
        "observer_cadence": _observer_cadence(session, prefix, errors),
    }


def summarize_report(report):
    """Validate observations and keep process-level statistics independent."""
    errors = []
    if report.get("schema") != SCHEMA:
        errors.append("Unsupported Shader display timing schema")
    if report.get("completed") is not True:
        errors.append("Timing run did not complete")
    for name in ("environment", "profile"):
        if not isinstance(report.get(name), dict) or not report[name]:
            errors.append(name + " must be a nonempty object")
    sessions = report.get("sessions", [])
    if not isinstance(sessions, list):
        errors.append("sessions must be a list")
        sessions = []
    if not sessions:
        errors.append("Timing run has no sessions")
    results = [_session_summary(session, index, errors) for index, session in enumerate(sessions)]
    profile = report.get("profile", {})
    if isinstance(profile, dict) and "controls" in profile:
        expected_controls = profile["controls"]
        expected_scenarios = profile.get("scenarios", SCENARIOS)
        if not isinstance(expected_controls, (list, tuple)) or not expected_controls:
            errors.append("profile.controls must be a nonempty list")
        elif not isinstance(expected_scenarios, (list, tuple)) or not expected_scenarios:
            errors.append("profile.scenarios must be a nonempty list")
        else:
            expected_controls = [control.rsplit(".", 1)[-1] if isinstance(control, str) else control
                                 for control in expected_controls]
            if any(control not in CONTROLS for control in expected_controls):
                errors.append("profile.controls contains an unsupported control")
            if any(scenario not in SCENARIOS for scenario in expected_scenarios):
                errors.append("profile.scenarios contains an unsupported scenario")
            for result in results:
                present = {(row["control"], row["scenario"]) for row in result["groups"]}
                for control in expected_controls:
                    if control not in CONTROLS:
                        continue
                    for scenario in expected_scenarios:
                        if scenario not in SCENARIOS:
                            continue
                        if (control, scenario) not in present:
                            errors.append(f"session {result['session']} has no {control}/{scenario} samples")
    groups = [group for result in results for group in result["groups"]]
    aggregated = []
    cadence_rows = [row for result in results for row in result["observer_cadence"]]
    observer_cadence = []
    for control in CONTROLS:
        for mode in ("observer_on", "observer_off"):
            selected = [row for row in cadence_rows
                        if row["control"] == control and row["mode"] == mode]
            if selected:
                observer_cadence.append({
                    "control": control, "mode": mode, "session_count": len(selected),
                    "injected_motion_events": sum(row["injected_motion_events"] for row in selected),
                    "draws": sum(row["draws"] for row in selected),
                    "duration_seconds": sum(row["duration_seconds"] for row in selected),
                    "injected_per_second": median(row["injected_per_second"] for row in selected),
                    "draws_per_second": median(row["draws_per_second"] for row in selected),
                })
    for control in CONTROLS:
        for scenario in SCENARIOS:
            selected = [row for row in groups if (row["control"], row["scenario"]) == (control, scenario)]
            if not selected:
                continue
            aggregated.append({
                "control": control, "scenario": scenario, "session_count": len(selected),
                "counts": {name: sum(row["counts"][name] for row in selected)
                           for name in ("accepted", "displayed", "superseded", "missing")},
                **{name: _aggregate_metrics(selected, name) for name in GROUP_METRICS},
                "rates": {name: median(row["rates"][name] for row in selected if row.get("rates") is not None)
                          for name in RATE_NAMES} if any(row.get("rates") is not None for row in selected) else None,
            })
    return {
        "valid": not errors, "errors": errors, "sessions": results, "groups": aggregated,
        "drags": [{"control": control, "release_to_capture": _aggregate_metrics(
            [row for result in results for row in result["drags"] if row["control"] == control],
            "release_to_capture")}
            for control in CONTROLS
            if any(row["control"] == control for result in results for row in result["drags"])],
        "capture_gap": _aggregate_metrics(results, "capture_gap"),
        "capture_duration": _aggregate_metrics(results, "capture_duration"),
        "capture_count": sum(result["capture_count"] for result in results),
        "observer_cadence": observer_cadence,
        "capture_duration": _aggregate_metrics(results, "capture_duration"),
    }


def compare_reports(report, baseline):
    """Warn only when a compatible run's increase exceeds observation noise."""
    candidate_summary, baseline_summary = summarize_report(report), summarize_report(baseline)
    reasons = []
    for name in ("environment", "profile"):
        if json.dumps(report.get(name), sort_keys=True) != json.dumps(baseline.get(name), sort_keys=True):
            reasons.append(name + " differs")
    if not candidate_summary["valid"]:
        reasons.append("Candidate timing observations are invalid")
    if not baseline_summary["valid"]:
        reasons.append("Baseline timing observations are invalid")
    if {(row["control"], row["scenario"]) for row in candidate_summary["groups"]} != {
            (row["control"], row["scenario"]) for row in baseline_summary["groups"]}:
        reasons.append("Observed control/scenario groups differ")
    comparisons, warnings = [], []
    if not reasons:
        for collection, metrics in (("groups", (*METRICS, "displayed_update_gap")),
                                    ("drags", ("release_to_capture",))):
            for current in candidate_summary[collection]:
                identity = {name: current[name] for name in ("control", "scenario") if name in current}
                previous = next((row for row in baseline_summary[collection]
                                 if all(row.get(name) == value for name, value in identity.items())), None)
                if previous is None:
                    reasons.append("Baseline has no " + "/".join(identity.values()) + " samples")
                    continue
                for metric in metrics:
                    if current.get(metric) is None or previous.get(metric) is None:
                        if metric == "displayed_update_gap":
                            continue
                        reasons.append("Missing " + metric + " samples for " + "/".join(identity.values()))
                        continue
                    for statistic in COMPARISON_STATISTICS:
                        per_session = [row[metric].get(statistic, row[metric]["maximum_seconds"])
                                       for session in baseline_summary["sessions"]
                                       for row in session[collection]
                                       if all(row.get(name) == value for name, value in identity.items())
                                       and row.get(metric) is not None]
                        spread = max(per_session) - min(per_session)
                        candidate_gap = candidate_summary["capture_gap"]
                        baseline_gap = baseline_summary["capture_gap"]
                        if candidate_gap is None or baseline_gap is None:
                            reasons.append("Capture cadence is unavailable")
                            continue
                        cadence = candidate_gap["p95_seconds"] + baseline_gap["p95_seconds"]
                        candidate_value = current[metric].get(
                            statistic, current[metric]["maximum_seconds"])
                        baseline_value = previous[metric].get(
                            statistic, previous[metric]["maximum_seconds"])
                        increase = candidate_value - baseline_value
                        threshold = max(spread, cadence)
                        row = {**identity, "metric": metric, "statistic": statistic,
                               "unit": "seconds",
                               "baseline_seconds": baseline_value,
                               "candidate_seconds": candidate_value,
                               "increase_seconds": increase, "baseline_spread_seconds": spread,
                               "change_seconds": increase,
                               "change_percent": (100 * increase / baseline_value
                                                  if baseline_value else None),
                               "capture_uncertainty_seconds": cadence, "warning_threshold_seconds": threshold,
                               "warning": increase > threshold}
                        comparisons.append(row)
                        if row["warning"]:
                            warnings.append(row)
                if current.get("rates") is not None and previous.get("rates") is not None:
                    selected = [row for session in baseline_summary["sessions"] for row in session["groups"]
                                if all(row.get(name) == value for name, value in identity.items())
                                and row.get("rates") is not None]
                    candidate_rows = [row for session in candidate_summary["sessions"] for row in session["groups"]
                                      if all(row.get(name) == value for name, value in identity.items())
                                      and row.get("rates") is not None]
                    gaps = (baseline_summary["capture_gap"], candidate_summary["capture_gap"])
                    if not all(value is not None for value in gaps):
                        reasons.append("Capture cadence is unavailable")
                        continue
                    cadence = sum(value["p95_seconds"] for value in gaps)
                    for metric in RATE_NAMES:
                        old, new = previous["rates"][metric], current["rates"][metric]
                        spread = max(row["rates"][metric] for row in selected) - min(
                            row["rates"][metric] for row in selected)
                        duration = min(row["drag_seconds"] for row in (*selected, *candidate_rows))
                        if metric.endswith("fraction"):
                            quantization = max(1 / row["counts"]["accepted"] for row in (*selected, *candidate_rows))
                            uncertainty = max(quantization, cadence / duration)
                            unit = "fraction"
                        else:
                            uncertainty = max(1 / duration, cadence * max(abs(old), abs(new)) / duration)
                            unit = "per_second"
                        threshold = max(spread, uncertainty)
                        direction = "increase" if metric.startswith("superseded") else "decrease"
                        change = new - old
                        row = {**identity, "metric": metric, "statistic": "median_session_rate",
                               "unit": unit, "baseline_value": old, "candidate_value": new,
                               "change": change, "change_percent": 100 * change / old if old else None,
                               "baseline_spread": spread, "capture_uncertainty": uncertainty,
                               "warning_threshold": threshold, "regression_direction": direction,
                               "warning": (change if direction == "increase" else -change) > threshold}
                        comparisons.append(row)
                        if row["warning"]:
                            warnings.append(row)
    if reasons:
        comparisons, warnings = [], []
    return {"compatible": not reasons, "reasons": list(dict.fromkeys(reasons)),
            "comparisons": comparisons, "warnings": warnings}


def _milliseconds(value, statistic):
    return "—" if value is None else f"{1000 * value[statistic]:.3f}"


def write_report(output_dir, report, baseline=None):
    """Preserve raw observations, validated summaries, and optional comparison."""
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    report["summary"] = summarize_report(report)
    if baseline is not None:
        report["comparison"] = compare_reports(report, baseline)
    else:
        report.pop("comparison", None)
    (output / "report.json").write_text(
        json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf8")
    lines = ["# Installed Shader display timing", "",
             "Latency runs from accepted slider settings to completion of the first matching "
             "viewport framebuffer capture. Native event injection is reported separately.", "",
             "Session aggregates are medians of process-level p50, p95, and maximum values; "
             "p50 uses the median and p95 uses the nearest rank. Raw samples remain in JSON.", "",
             f"Valid observations: `{report['summary']['valid']}`.", "",
             "| Control | Scenario | Displayed / accepted | Accepted p50 (ms) | Accepted p95 (ms) | "
             "Median session max (ms) | Absolute max (ms) | Injected p50 (ms) |",
             "|---|---|---:|---:|---:|---:|---:|---:|"]
    for row in report["summary"]["groups"]:
        counts = row["counts"]
        lines.append(f"| {row['control']} | {row['scenario']} | {counts['displayed']} / {counts['accepted']} | "
                     f"{_milliseconds(row['accepted_to_capture'], 'p50_seconds')} | "
                     f"{_milliseconds(row['accepted_to_capture'], 'p95_seconds')} | "
                     f"{_milliseconds(row['accepted_to_capture'], 'maximum_seconds')} | "
                     f"{_milliseconds(row['accepted_to_capture'], 'absolute_maximum_seconds')} | "
                     f"{_milliseconds(row['injected_to_capture'], 'p50_seconds')} |")
    lines.extend(("", "| Control | Scenario | Displayed update gap p50 / p95 (ms) | "
                  "Accepted / displayed / superseded per second | Displayed / superseded (%) |",
                  "|---|---|---:|---:|---:|"))
    for row in report["summary"]["groups"]:
        rates = row["rates"]
        rate_text = "—" if rates is None else " / ".join(
            f"{rates[name]:.2f}" for name in RATE_NAMES[:3])
        fraction_text = "—" if rates is None else " / ".join(
            f"{100 * rates[name]:.2f}" for name in RATE_NAMES[3:])
        lines.append(f"| {row['control']} | {row['scenario']} | "
                     f"{_milliseconds(row['displayed_update_gap'], 'p50_seconds')} / "
                     f"{_milliseconds(row['displayed_update_gap'], 'p95_seconds')} | "
                     f"{rate_text} | {fraction_text} |")
    for row in report["summary"]["drags"]:
        lines.extend(("", f"{row['control']} release to final capture p50 / p95: "
                      f"{_milliseconds(row['release_to_capture'], 'p50_seconds')} / "
                      f"{_milliseconds(row['release_to_capture'], 'p95_seconds')} ms."))
    lines.extend(("", f"Captured {report['summary']['capture_count']} X11 samples; capture duration "
                  f"p50 / p95 / max: {_milliseconds(report['summary']['capture_duration'], 'p50_seconds')} / "
                  f"{_milliseconds(report['summary']['capture_duration'], 'p95_seconds')} / "
                  f"{_milliseconds(report['summary']['capture_duration'], 'maximum_seconds')} ms; "
                  f"within-request cadence gap p50 / p95: "
                  f"{_milliseconds(report['summary']['capture_gap'], 'p50_seconds')} / "
                  f"{_milliseconds(report['summary']['capture_gap'], 'p95_seconds')} ms.", "",
                  "Observer cadence diagnostic (draw rate is viewport draw callbacks per second):", "",
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
            lines.extend(("", "| Control | Scenario | Metric | Statistic | Signed change | Change (%) | "
                          "Noise bound | Warning |", "|---|---|---|---|---:|---:|---:|---|"))
            for row in comparison["comparisons"]:
                if row["unit"] == "seconds":
                    change = f"{1000 * row['change_seconds']:+.3f} ms"
                    threshold = f"{1000 * row['warning_threshold_seconds']:.3f} ms"
                else:
                    suffix = "/s" if row["unit"] == "per_second" else ""
                    change = f"{row['change']:+.3f}{suffix}"
                    threshold = f"{row['warning_threshold']:.3f}{suffix}"
                percent = "—" if row["change_percent"] is None else f"{row['change_percent']:+.2f}"
                lines.append(f"| {row['control']} | {row.get('scenario', 'release')} | {row['metric']} | "
                             f"{row['statistic']} | {change} | {percent} | {threshold} | "
                             f"{'yes' if row['warning'] else 'no'} |")
    lines.extend(("", "Captures bound observation time and include readback overhead. They do not "
                  "measure physical monitor presentation. Superseded drag updates are counted, "
                  "and missing isolated updates or a missing final drag display invalidate the run.", "",
                  "Performance comparisons require equal environment and profile values. Source and "
                  "package hashes are provenance; measurement-harness identity is part of the profile. "
                  "A warning requires an increase "
                  "greater than both the baseline session spread and the sum of the two runs' p95 capture "
                  "gaps. Drag rates use the active interval up to release; displayed rates exclude later "
                  "captures, while displayed fractions include final observations. Rate warnings convert "
                  "capture cadence to the metric's units and allow one update of quantization. Warnings "
                  "do not fail correctness or establish population confidence.", ""))
    (output / "report.md").write_text("\n".join(lines), encoding="utf8")
    return report


__all__ = ("SCHEMA", "summary", "summarize_report", "compare_reports", "write_report")
