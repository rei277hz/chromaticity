"""Describe uncapped installed-Grade updates without a performance gate."""

import json
from math import ceil, isfinite
from pathlib import Path


def summary(values):
    values = sorted(float(value) for value in values)
    if not values:
        return None
    return {
        "count": len(values),
        "p50_seconds": values[max(0, ceil(len(values) * .50) - 1)],
        "p95_seconds": values[max(0, ceil(len(values) * .95) - 1)],
        "maximum_seconds": values[-1],
    }


def validate_profile(duration, interval_ms, warmup, timeout):
    values = (duration, interval_ms, warmup, timeout)
    if not all(isfinite(value) for value in values):
        raise ValueError("Timing arguments must be finite")
    if duration <= 0 or interval_ms < 0 or warmup < 0 or timeout <= duration + warmup:
        raise ValueError("Duration must be positive, interval/warmup nonnegative, and timeout longer than the scenario")


def summarize_report(report):
    started, released = report.get("drag_started_at"), report.get("released_at")
    if started is None or released is None or released <= started:
        return {}
    duration = released - started
    groups = {
        "edits": report.get("edits", ()),
        "preparations": report.get("preparations", ()),
        "received_results": report.get("received_results", ()),
        "texture_publications": report.get("texture_publications", ()),
        "ui_heartbeats": report.get("ui_heartbeats", ()),
        "viewport_draws": report.get("viewport_draws", ()),
    }
    result = {"drag_seconds": duration}
    for name, events in groups.items():
        during_drag = [event for event in events if started <= event["at_seconds"] < released]
        count = len(during_drag)
        timestamps = [event["at_seconds"] for event in during_drag]
        rate = count / duration
        result[name] = {
            "count": count,
            "per_second": rate,
            "exceeds_60_per_second": rate > 60.,
            "gaps": summary(b - a for a, b in zip(timestamps, timestamps[1:])),
            "duration": summary(event["duration_seconds"] for event in during_drag
                                if event.get("duration_seconds") is not None),
        }
    settled = report.get("settled_at")
    if settled is not None:
        result["release_to_current_seconds"] = max(0., settled - released)
    return result


def write_report(output_dir, report):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    report["summary"] = summarize_report(report)
    (output_dir / "report.json").write_text(
        json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf8"
    )
    lines = [
        "# Installed Grade update timing", "",
        "The packaged extension runs in Blender's Shading workspace with a Shader Grade, "
        "sidebar, and a viewport. Scripted RNA edits use the production gesture and "
        "property callbacks; the product owns asynchronous polling and publication.", "",
        "No preview rate cap or performance threshold is applied. The default edit interval "
        "is zero, so the harness requests another edit at each available timer turn. "
        "Counts and rates below cover the continuous-drag interval only.", "",
        f"Blender: `{report.get('blender', 'unknown')}`; renderer: "
        f"`{report.get('gpu', {}).get('renderer', 'unknown')}`; "
        f"stage: `{report.get('profile', {}).get('stage', 'unknown')}`; viewport: "
        f"`{report.get('profile', {}).get('viewport', 'rendered')}`.", "",
        "| Measurement | Count | Per second | Exceeds 60/s | p95 gap (ms) | Maximum gap (ms) |",
        "|---|---:|---:|---|---:|---:|",
    ]
    for name, result in report["summary"].items():
        if not isinstance(result, dict):
            continue
        gaps = result["gaps"]
        p95 = "—" if gaps is None else f"{1000 * gaps['p95_seconds']:.3f}"
        maximum = "—" if gaps is None else f"{1000 * gaps['maximum_seconds']:.3f}"
        lines.append(
            f"| {name} | {result['count']} | {result['per_second']:.2f} | "
            f"{'yes' if result['exceeds_60_per_second'] else 'no'} | {p95} | {maximum} |"
        )
    lines.extend(("", "| Main-thread work | p50 (ms) | p95 (ms) | Maximum (ms) |",
                  "|---|---:|---:|---:|"))
    for name in ("edits", "received_results", "texture_publications"):
        result = report["summary"].get(name, {}).get("duration")
        if result is not None:
            lines.append(f"| {name} | {1000 * result['p50_seconds']:.3f} | "
                         f"{1000 * result['p95_seconds']:.3f} | "
                         f"{1000 * result['maximum_seconds']:.3f} |")
    settle = report["summary"].get("release_to_current_seconds")
    lines.extend(("", f"Resource identities preserved: `{report.get('resource_inventory_preserved')}`.",
                  f"Final signature current: `{report.get('final_current')}`.",
                  "Release to current: " + ("unavailable" if settle is None else f"{1000 * settle:.3f} ms"), "",
                  "Preparation counts are completed aggregate worker joins. Received results are "
                  "foreground completion deliveries; coalescing can make their count lower. "
                  "Texture publications are successful calls to the product's image pixel "
                  "write/update function. They do not imply one displayed frame per upload.", "",
                  "Viewport draws are POST_PIXEL callbacks on the actual viewport. They are UI "
                  "draw activity, not signature-verified rendered output or physical display "
                  "presentation. The report does not claim visible 60 fps from upload or draw counts.", "",
                  "The bundled Linux fixture uses Mesa llvmpipe; its GPU work runs on CPU cores. "
                  "Native viewport rendering, Python instrumentation, sidebar redraw, and the "
                  "unthrottled edit/heartbeat timers all contribute to these measurements.", ""))
    (output_dir / "report.md").write_text("\n".join(lines), encoding="utf8")


__all__ = ("summary", "summarize_report", "validate_profile", "write_report")
