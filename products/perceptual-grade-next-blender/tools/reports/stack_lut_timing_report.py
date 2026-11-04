"""Formatting and summary helpers for the Stack LUT timing diagnostic."""

from pathlib import Path
from math import ceil
import json


def summary(values):
    values = sorted(values)
    if not values:
        return None

    def nearest_rank(fraction):
        index = max(0, min(len(values) - 1, ceil(fraction * len(values)) - 1))
        return values[index]

    return {
        "count": len(values),
        "p50_seconds": nearest_rank(0.50),
        "p95_seconds": nearest_rank(0.95),
    }


def summarize_drags(drags):
    fields = (
        "gesture_seconds",
        "preview_request_to_phase_start_seconds",
        "preview_seconds_after_last_update",
        "release_to_full_seconds",
        "preview_setup_seconds",
        "preview_texture_allocation_seconds",
        "preview_dispatch_submission_seconds",
        "preview_inter_step_wait_seconds",
        "preview_readback_seconds",
        "preview_result_to_install_seconds",
        "preview_install_seconds",
        "preview_kernel_build_seconds",
        "preview_kernel_swap_seconds",
        "full_request_to_phase_start_seconds",
        "full_setup_seconds",
        "full_texture_allocation_seconds",
        "full_dispatch_submission_seconds",
        "full_inter_step_wait_seconds",
        "full_readback_seconds",
        "full_result_to_install_seconds",
        "full_install_seconds",
        "full_kernel_build_seconds",
        "full_kernel_swap_seconds",
    )
    return {
        field: summary(row[field] for row in drags if row.get(field) is not None)
        for field in fields
    }


def write_report(output_dir, report):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    report["summary"] = summarize_drags(report["drags"])
    (output_dir / "report.json").write_text(
        json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf8"
    )

    lines = [
        "# Grade Stack LUT publication timing",
        "",
        "This diagnostic runs the installed extension under Blender with Mesa llvmpipe. "
        "These measurements describe the software GPU path and are not physical-GPU timings.",
        "",
        f"Blender: `{report.get('blender', 'unknown')}`; renderer: "
        f"`{report.get('gpu', {}).get('renderer', 'unknown')}`; "
        f"node tree: `{report.get('node_tree', 'unknown')}`.",
        "",
        "GPU dispatch values are CPU-side submission time. Texture readback is synchronous "
        "and includes waiting for the queued GPU work to finish.",
        "",
        "Request-to-phase-start measures the delay from a matching LUT request to the first "
        "GPU dispatch for that 33³ or 65³ phase. Progressive jobs can run both phases, so "
        "the 65³ phase does not necessarily start a separate job.",
        "Inter-step wait is elapsed time between successive Blender main-thread bake ticks; "
        "it includes the configured timer delay and any other work between ticks.",
        "",
        "| Drag | Shader | Updates | LUT requests | Jobs | Unique requests without a job | Preview | "
        "Last update to preview (s) | Release to full install (s) |",
        "|---:|---|---:|---:|---:|---:|---|---:|---:|",
    ]
    for index, row in enumerate(report["drags"], 1):
        preview = "installed" if row.get("preview_installed") else "not observed"
        preview_seconds = row.get("preview_seconds_after_last_update")
        full_seconds = row.get("release_to_full_seconds")
        lines.append(
            f"| {index} | {'cold' if row.get('shader_was_cold') else 'warm'} | "
            f"{row.get('updates', 0)} | {row.get('lut_requests', 0)} | "
            f"{row.get('started_job_count', 0)} | {row.get('requests_without_started_job', 0)} | "
            f"{preview} | {format_seconds(preview_seconds)} | {format_seconds(full_seconds)} |"
        )
    lines.extend(("", "## Phase Summary", "", "| Phase | Samples | p50 (s) | p95 (s) |", "|---|---:|---:|---:|"))
    for name, result in report["summary"].items():
        if result is not None:
            lines.append(
                f"| {name} | {result['count']} | {result['p50_seconds']:.6f} | "
                f"{result['p95_seconds']:.6f} |"
            )
    lines.extend((
        "",
        "Each drag's JSON record includes request/job counts, dispatch batch counts, "
        "setup, readback, publication, and kernel build/install timings. No latency "
        "threshold is applied. A missing preview is reported as data; failure to "
        "install the final matching 65³ kernel fails the run.",
        "",
    ))
    (output_dir / "report.md").write_text("\n".join(lines), encoding="utf8")


def format_seconds(value):
    return "-" if value is None else f"{value:.6f}"


def validate_profile(grade_count, samples, updates, interval_ms, preview_timeout, timeout):
    if grade_count < 1 or samples < 1 or updates < 2:
        raise ValueError("grade count and samples must be positive; updates must be at least 2")
    if interval_ms <= 0 or preview_timeout < 0 or timeout <= 0:
        raise ValueError("interval must be positive and timeouts nonnegative")


__all__ = ("format_seconds", "summarize_drags", "summary", "validate_profile", "write_report")
