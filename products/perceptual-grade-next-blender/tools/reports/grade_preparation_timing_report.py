"""Formatting and summary helpers for Grade preparation timings."""

from math import ceil
from pathlib import Path
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


def summarize(report):
    samples = report.get("samples", ())
    components = sorted({
        name for sample in samples for name in sample.get("preparation", {})
    })
    result = {
        "preparation_" + name: summary(
            sample["preparation"][name]
            for sample in samples
            if sample.get("preparation", {}).get(name) is not None
        )
        for name in components
    }
    result["preparation_total"] = summary(
        sample["preparation_total_seconds"]
        for sample in samples
        if sample.get("preparation_total_seconds") is not None
    )
    for tree_type in ("ShaderNodeTree", "CompositorNodeTree"):
        result[tree_type + "_kernel_build"] = summary(
            sample["kernel_build"][tree_type]
            for sample in samples
            if sample.get("kernel_build", {}).get(tree_type) is not None
        )
    result["texture_upload"] = summary(
        upload["seconds"]
        for sample in samples
        for upload in sample.get("texture_uploads", ())
        if upload.get("seconds") is not None
    )
    return result


def write_report(output_dir, report):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    report["summary"] = summarize(report)
    (output_dir / "report.json").write_text(
        json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf8"
    )
    lines = [
        "# Grade preparation timing",
        "",
        f"Blender: `{report.get('blender', 'unknown')}`.",
        "",
        "This diagnostic measures product preparation components, aggregate join, packed-image uploads, "
        "and Shader/Compositor kernel builds. It applies no latency threshold.",
        "",
        "| Sample | Tone | Preparation components (s) | Total (s) | Shader build (s) | Compositor build (s) | Uploads |",
        "|---:|---|---|---:|---:|---:|---:|",
    ]
    for index, sample in enumerate(report.get("samples", ()), 1):
        components = ", ".join(
            f"{name} {seconds:.6f}"
            for name, seconds in sorted(sample.get("preparation", {}).items())
        ) or "-"
        builds = sample.get("kernel_build", {})
        lines.append(
            f"| {index} | {sample.get('tone', 'unknown')} | {components} | "
            f"{_format(sample.get('preparation_total_seconds'))} | "
            f"{_format(builds.get('ShaderNodeTree'))} | "
            f"{_format(builds.get('CompositorNodeTree'))} | "
            f"{len(sample.get('texture_uploads', ())) } |"
        )
    lines.extend(("", "## Summary", "", "| Measurement | Samples | p50 (s) | p95 (s) |", "|---|---:|---:|---:|"))
    for name, value in report["summary"].items():
        if value is not None:
            lines.append(
                f"| {name} | {value['count']} | {value['p50_seconds']:.6f} | "
                f"{value['p95_seconds']:.6f} |"
            )
    lines.extend(("", "No performance gate is applied.", ""))
    (output_dir / "report.md").write_text("\n".join(lines), encoding="utf8")


def _format(value):
    return "-" if value is None else f"{value:.6f}"


__all__ = ("summary", "summarize", "write_report")
