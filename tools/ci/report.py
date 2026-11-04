#!/usr/bin/env python3
"""Report selected Buck target outcomes without conflating builds and tests."""

import argparse
from collections import Counter
from datetime import datetime, timezone
from html import escape
import json
import os
from pathlib import Path
import re


MANIFEST = Path(__file__).with_name("targets.json")
STATUS = {1: "passed", 2: "failed", 3: "skipped", 4: "skipped", 5: "failed",
          6: "failed", 7: "unknown", 8: "not_run", 11: "failed"}
OUTPUTS = ("summary.json", "builds.svg", "tests.svg", "README.md")


def targets(path=MANIFEST):
    data = json.loads(Path(path).read_text())
    for group in ("builds", "tests"):
        labels = data.get(group)
        if (not isinstance(labels, list) or not labels
                or any(not isinstance(label, str) or not re.fullmatch(r"//[^\s:]*:[^\s]+", label)
                       for label in labels)
                or len(labels) != len(set(labels))):
            raise ValueError(f"Invalid or empty {group} selection")
    return data


def read_object(path, issues):
    try:
        data = json.loads(path.read_text())
        if not isinstance(data, dict):
            raise ValueError("expected an object")
        return data
    except (OSError, UnicodeError, ValueError) as error:
        issues.append(f"{path.name}: {error}")
        return {}


def normalize(label):
    if isinstance(label, str):
        return label.removeprefix("root") if label.startswith("root//") else label
    return None


def build_results(path, issues):
    report = read_object(path, issues)
    results = report.get("results")
    if not isinstance(results, dict):
        issues.append(f"{path.name}: missing target results")
        return {}
    if report.get("success") is not True:
        issues.append(f"{path.name}: the build command did not report complete success")
    normalized = {}
    for label, entry in results.items():
        label = normalize(label)
        if label in normalized:
            issues.append(f"{path.name}: duplicate target {label}")
            normalized[label] = {"success": "UNKNOWN"}
        else:
            normalized[label] = entry
    return normalized


def build_status(entry):
    if entry is None:
        return "not_run"
    if not isinstance(entry, dict):
        return "unknown"
    if entry.get("success") == "FAIL" or entry.get("errors"):
        return "failed"
    if entry.get("success") != "SUCCESS":
        return "unknown"
    configured = entry.get("configured", {})
    if not isinstance(configured, dict):
        return "unknown"
    for value in configured.values():
        if not isinstance(value, dict):
            return "unknown"
        if value.get("success") == "FAIL" or value.get("errors"):
            return "failed"
        if value.get("success") != "SUCCESS":
            return "unknown"
    return "passed"


def event_label(result):
    """The pinned Buck protobuf JSON encodes a configured target as nested objects."""
    configured = result.get("target_label")
    if not isinstance(configured, dict):
        return None, None
    label = configured.get("label")
    config = configured.get("configuration")
    if not isinstance(label, dict) or not isinstance(config, dict):
        return None, None
    package, name, configuration = label.get("package"), label.get("name"), config.get("full_name")
    if not all(isinstance(value, str) and value for value in (package, name, configuration)):
        return None, None
    return normalize(f"{package}:{name}"), configuration


def test_results(path, selection, issues):
    observations = {label: {} for label in selection}
    try:
        stream = path.open()
    except OSError as error:
        issues.append(f"{path.name}: {error}")
        return observations
    with stream:
        try:
            for number, line in enumerate(stream, 1):
                if not line.strip():
                    continue
                try:
                    event = json.loads(line)
                    if not isinstance(event, dict):
                        raise ValueError("expected an object")
                    node = event
                    for key in ("Event", "data", "Instant", "data"):
                        node = node.get(key, {})
                        if not isinstance(node, dict):
                            raise ValueError(f"invalid {key} object")
                    result = node.get("TestResult")
                    if result is None:
                        continue
                    if not isinstance(result, dict):
                        raise ValueError("invalid TestResult")
                    label, config = event_label(result)
                    if label is None:
                        raise ValueError("invalid TestResult target_label")
                    if label not in observations:
                        continue
                    status = result.get("status")
                    if type(status) is not int:
                        raise ValueError(f"invalid status for {label}")
                    if status in (9, 10):  # Test discovery is not a test run.
                        continue
                    observations[label].setdefault(config, set()).add(STATUS.get(status, "unknown"))
                except (ValueError, AttributeError) as error:
                    issues.append(f"{path.name}:{number}: {error}")
        except UnicodeError as error:
            issues.append(f"{path.name}: {error}")
    return observations


def test_status(observations, built, label, issues):
    if build_status(built) == "failed":
        return "failed"
    if not observations:
        return "not_run"
    if len(observations) != 1:
        issues.append(f"{label}: multiple configurations in a single-platform selection")
        return "unknown"
    statuses = next(iter(observations.values()))
    if "failed" in statuses:
        return "failed"  # A later success must not hide a failed attempt.
    if "unknown" in statuses:
        return "unknown"
    terminal = statuses - {"not_run"}
    if len(terminal) > 1:
        issues.append(f"{label}: conflicting terminal test results")
        return "unknown"
    if terminal == {"passed"} and build_status(built) != "passed":
        issues.append(f"{label}: passing test has no successful executable build record")
        return "unknown"
    return next(iter(terminal), "not_run")


def aggregate(rows, exit_code, issues):
    counts = Counter(row["status"] for row in rows)
    if exit_code is not None and type(exit_code) is not int:
        issues.append("invalid command exit code")
        exit_code = None
    if exit_code is None:
        issues.append("command exit code was not recorded")
    if counts["failed"] or (exit_code is not None and exit_code != 0):
        outcome = "failed"
    elif issues or counts["passed"] != len(rows):
        outcome = "incomplete"
    else:
        outcome = "passed"
    return {"passed": counts["passed"], "total": len(rows), "outcome": outcome,
            "exit_code": exit_code, "counts": dict(sorted(counts.items())),
            "issues": issues, "targets": rows}


def metadata(env):
    repository = env.get("GITHUB_REPOSITORY", "local")
    run_id = env.get("GITHUB_RUN_ID", "")
    server = env.get("GITHUB_SERVER_URL", "https://github.com").rstrip("/")
    def integer(name):
        value = env.get(name, "0")
        return int(value) if value.isdecimal() else 0
    return {"repository": repository, "commit": env.get("GITHUB_SHA", "unknown"),
            "run_id": run_id, "run_number": integer("GITHUB_RUN_NUMBER"),
            "run_attempt": integer("GITHUB_RUN_ATTEMPT"),
            "run_url": f"{server}/{repository}/actions/runs/{run_id}" if run_id else "",
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds")}


def collect(directory, selection, env):
    exit_issues = []
    exits = read_object(directory / "exits.json", exit_issues)
    if "selection" in exits and (type(exits["selection"]) is not int or exits["selection"] != 0):
        exit_issues.append("CI target selection was rejected or incomplete")
    build_issues = list(exit_issues)
    builds = build_results(directory / "build-report.json", build_issues)
    build_rows = [{"target": label, "status": build_status(builds.get(label))}
                  for label in selection["builds"]]
    test_issues = list(exit_issues)
    test_builds = build_results(directory / "test-build-report.json", test_issues)
    if type(exits.get("events")) is not int or exits["events"] != 0:
        test_issues.append("test event-log export did not complete successfully")
    observations = test_results(directory / "test-events.jsonl", selection["tests"], test_issues)
    test_rows = [{"target": label, "status": test_status(observations[label], test_builds.get(label),
                                                        label, test_issues)}
                 for label in selection["tests"]]
    return {"schema": 1, "metadata": metadata(env),
            "builds": aggregate(build_rows, exits.get("build"), build_issues),
            "tests": aggregate(test_rows, exits.get("test"), test_issues)}


def badge(label, section):
    message = f'{section["passed"]}/{section["total"]} passed'
    if section["outcome"] != "passed":
        message += " (run failed)" if section["outcome"] == "failed" else " (incomplete)"
    color = {"passed": "#2e7d32", "failed": "#c62828", "incomplete": "#946200"}[section["outcome"]]
    left, right = max(80, 7 * len(label) + 16), max(80, 7 * len(message) + 16)
    total = left + right
    title = escape(f"{label}: {message}")
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{total}" height="20" role="img" aria-label="{title}">
  <title>{title}</title>
  <rect width="{total}" height="20" rx="3" fill="#555"/>
  <path d="M{left} 0H{total - 3}Q{total} 0 {total} 3V17Q{total} 20 {total - 3} 20H{left}Z" fill="{color}"/>
  <g fill="#fff" text-anchor="middle" font-family="Verdana,DejaVu Sans,sans-serif" font-size="11">
    <text x="{left / 2}" y="14">{escape(label)}</text>
    <text x="{left + right / 2}" y="14">{escape(message)}</text>
  </g>
</svg>
'''


def markdown(summary):
    meta = summary["metadata"]
    lines = ["# Linux build and test results", "",
             f'- Commit: `{meta["commit"]}`', f'- Recorded at: {meta["timestamp"]}',
             f'- Run: {meta["run_url"] or "local validation"}', "",
             "Counts represent the selected build targets and smoke suites, not individual test cases or the full monorepo suite.", ""]
    for key, label in (("builds", "Linux build targets"), ("tests", "Linux smoke suites")):
        group = summary[key]
        lines += [f'## {label}: {group["passed"]}/{group["total"]} passed', "",
                  f'Run outcome: **{group["outcome"]}**. Command exit: `{group["exit_code"]}`.', "",
                  "| Target | Result |", "| --- | --- |"]
        lines += [f'| `{row["target"]}` | {row["status"]} |' for row in group["targets"]]
        lines += [""]
        if group["issues"]:
            lines += ["Reporting notes:", ""]
            lines += ["- " + issue.replace("\n", " ") for issue in group["issues"]]
            lines += [""]
    return "\n".join(lines)


def write(summary, directory):
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    for key, label in (("builds", "Linux build targets"), ("tests", "Linux smoke suites")):
        (directory / f"{key}.svg").write_text(badge(label, summary[key]))
    (directory / "README.md").write_text(markdown(summary))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    summary = collect(args.report_dir, targets(), os.environ)
    write(summary, args.output_dir)
    for name in ("builds", "tests"):
        group = summary[name]
        print(f'{name}: {group["passed"]}/{group["total"]} passed; {group["outcome"]}')


if __name__ == "__main__":
    main()
