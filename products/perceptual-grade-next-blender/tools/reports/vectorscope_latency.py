"""Measure end-to-end vectorscope publication and draw latency."""

from importlib.resources import files
import argparse
import json
from math import isfinite
import os
from pathlib import Path
import platform
import signal
from statistics import median
import subprocess
import sys
import tempfile
import time
import traceback
import zipfile

from .stack_lut_timing import blender_binary, software_display


TARGET = "//products/perceptual-grade-next-blender/tools/reports:vectorscope_latency"
SCENARIOS = ("direct_image", "processed_compositor", "shader_viewport")
REDUCERS = ("cpu", "gpu", "shader-tree", "all")
AGGREGATE_STAGES = {"helper_round_trip", "helper_poll", "worker_dispatch"}


def _cpu_model():
    path = Path("/proc/cpuinfo")
    if path.is_file():
        for line in path.read_text(encoding="utf8", errors="replace").splitlines():
            if line.startswith("model name"):
                return line.split(":", 1)[1].strip()
    return platform.processor()


def _environment():
    return {
        "platform": platform.platform(),
        "machine": platform.machine(),
        "cpu_count": os.cpu_count(),
        "cpu_model": _cpu_model(),
        "display": "Xvfb",
        "renderer": "Mesa llvmpipe",
        "openblas_threads": 1,
        "omp_threads": 1,
    }


def _run_session(args, binary, runner, fixture, repository, root, scenario, ordinal):
    result_path = root / "worker-report.json"
    configuration = root / "configuration.json"
    configuration.write_text(json.dumps({
        "repository": str(repository), "report": str(result_path),
        "scenario": scenario, "sample_timeout": min(args.timeout, 90.),
        "reducer": args.reducer,
        "benchmark_import_path": str(root.parent / "benchmark-import"),
    }, indent=2) + "\n", encoding="utf8")
    command = [str(binary), "--factory-startup", "--disable-autoexec",
               "--enable-event-simulate", "--window-geometry", "0", "0", "1280", "960",
               "--python-exit-code", "1", "--python", str(runner), "--",
               str(configuration)]
    started = time.perf_counter()
    code = None
    error = None
    log_path = root / "native.log"
    with software_display(fixture, root) as env:
        env.update(BLENDER_USER_CONFIG=str(root / "config"),
                   BLENDER_USER_EXTENSIONS=str(root / "extensions"))
        with log_path.open("w", encoding="utf8") as log:
            process = subprocess.Popen(command, cwd=root, env=env, stdout=log,
                                       stderr=subprocess.STDOUT, start_new_session=True)
            try:
                code = process.wait(timeout=args.timeout + 60.)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                code = process.wait(timeout=10)
                error = f"Blender {scenario} session exceeded {args.timeout + 60:.0f}s"
    try:
        result = json.loads(result_path.read_text(encoding="utf8"))
    except (OSError, json.JSONDecodeError):
        result = {"completed": False, "error": traceback.format_exc()}
    result.update({
        "scenario": scenario, "session": ordinal, "process_returncode": code,
        "process_wall_seconds": time.perf_counter() - started,
    })
    if error is not None:
        result.setdefault("errors", []).append(error)
    if code != 0:
        result["completed"] = False
        result.setdefault("errors", []).append(f"Blender exited with status {code}")
    if not result.get("completed"):
        with log_path.open("rb") as log:
            log.seek(max(0, log_path.stat().st_size - 16000))
            result["native_log_tail"] = log.read().decode("utf8", errors="replace")
    return result


def _summary(samples):
    groups = {}
    for sample in samples:
        key = (sample["path"], sample["phase"])
        groups.setdefault(key, []).append(sample)
    summary = {}
    for (path, phase), values in groups.items():
        latencies = [item["latency_ms"] for item in values]
        draws = [item["draw_latency_ms"] for item in values]
        summary[f"{path}:{phase}"] = {
            "count": len(values),
            "median_latency_ms": median(latencies),
            "maximum_latency_ms": max(latencies),
            "median_draw_latency_ms": median(draws),
            "maximum_draw_latency_ms": max(draws),
        }
    return summary


def _format_ms(value):
    return f"{value:.3f}"


def _stage_summary(samples):
    groups = {}
    for sample in samples:
        phase = "Linear edit" if sample["trigger"] == "linear_exposure" else sample["phase"]
        intervals = {}
        for record in sample["timing_records"]:
            stage, clock = record["stage"], record["clock"]
            if stage not in {"request", "publish", "draw"}:
                key = (clock, stage)
                intervals[key] = intervals.get(key, 0.0) + record["duration_ms"]
            if stage == "route_signature":
                if record["ticket"]["generation"] == sample["generation"]:
                    intervals["host", "trigger_to_final_observation"] = (
                        record["start_ns"] - sample["trigger_ns"]) / 1e6
        intervals["host", "publication_to_draw"] = (sample["draw_ns"] - sample["publication_ns"]) / 1e6
        for (clock, stage), duration in intervals.items():
            groups.setdefault((sample["path"], phase, clock, stage), []).append(duration)
    return [
        {"path": path, "phase": phase, "clock": clock, "stage": stage,
         "count": len(values), "median_ms": median(values), "maximum_ms": max(values)}
        for (path, phase, clock, stage), values in sorted(groups.items())
    ]


def write_report(output, report):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    samples = report["samples"]
    controls = report["linear_controls"]
    report["summary"] = _summary(samples)
    report["stage_summary"] = _stage_summary((*samples, *controls))
    (output / "report.json").write_text(
        json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf8")
    lines = [
        "# Vectorscope latency",
        "",
        "Each capture path runs in a fresh Blender GUI session under Xvfb with Mesa llvmpipe, "
        "so the evaluated paths each measure a cold helper followed by warm captures.",
        "",
        f"Remote worker CPU `{report['environment']['cpu_model']}` with "
        f"{report['environment']['cpu_count']} logical CPUs.",
        "",
        "| Session | Blender | GPU backend | Renderer | Render engine | Compositor device | Scene size |",
        "|---|---|---|---|---|---|---|",
    ]
    for session in report["sessions"]:
        native = session.get("environment")
        if native:
            width, height = native["scene_dimensions"]
            lines.append(f"| {session['scenario']} | {native['blender']} | {native['gpu_backend']} | "
                         f"{native['gpu_renderer']} | {native['render_engine']} | "
                         f"{native['compositor_device']} | {width} x {height} |")
    lines.extend((
        "",
        "Each sample starts immediately before invoking a Blender operation or setting RNA. The scope "
        "runtime records the accepted demand and its matching publication. Draw latency ends at the first "
        "completed node editor callback drawing the matching current plot. These measurements capture the "
        "fixture's software GPU path through the draw callback. Physical presentation and hardware GPU "
        "timing require separate measurements.",
        "",
        "| Path | Phase | Samples | Publication p50 (ms) | Publication max (ms) | Draw p50 (ms) | Draw max (ms) |",
        "|---|---|---:|---:|---:|---:|---:|",
    ))
    for key, value in sorted(report["summary"].items()):
        path, phase = key.split(":", 1)
        lines.append(
            f"| {path} | {phase} | {value['count']} | "
            f"{_format_ms(value['median_latency_ms'])} | {_format_ms(value['maximum_latency_ms'])} | "
            f"{_format_ms(value['median_draw_latency_ms'])} | "
            f"{_format_ms(value['maximum_draw_latency_ms'])} |"
        )
    lines.extend(("", "| Path | Trigger | Capture size | Samples reused | Helper | Requests | Publication (ms) | Draw (ms) |",
                  "|---|---|---|---|---|---:|---:|---:|"))
    for row in (*samples, *controls):
        width, height = row["capture_dimensions"]
        helper = {None: "none", False: "started", True: "reused"}[row["helper_reused"]]
        reuse = "yes" if row["capture_reused"] else "no"
        lines.append(f"| {row['path']} | {row['trigger']} | {width} x {height} | {reuse} | {helper} | "
                     f"{len(row['requested_generations'])} | "
                     f"{_format_ms(row['latency_ms'])} | {_format_ms(row['draw_latency_ms'])} |")
    stages = report["stage_summary"]
    lines.extend(("", "## Timing stages", ""))
    for path, phase in dict.fromkeys((row["path"], row["phase"]) for row in stages):
        components = [row for row in stages if row["path"] == path and row["phase"] == phase
                      and row["stage"] not in AGGREGATE_STAGES]
        largest = sorted(components, key=lambda row: row["median_ms"], reverse=True)[:3]
        spans = ", ".join(f"`{row['stage']}` {_format_ms(row['median_ms'])} ms" for row in largest)
        lines.append(f"- `{path}` ({phase}) had its longest median spans in {spans}.")
    lines.extend((
        "",
        "The helper round trip includes worker processing, payload transfer, and time until the host polls "
        "the result. Worker dispatch includes snapshot restoration, setup, render, and readback. Probe wait "
        "includes host timer scheduling. The table covers the request and capture that produced the matching "
        "draw. The Linear edit diagnostics below include earlier attempts. Rows can overlap, and each duration "
        "uses its originating process clock. Repeated polls are summed per sample.",
        "",
        "| Path | Phase | Clock | Stage | Median (ms) | Maximum (ms) |",
        "|---|---|---|---|---:|---:|",
    ))
    for row in stages:
        lines.append(f"| {row['path']} | {row['phase']} | {row['clock']} | {row['stage']} | "
                     f"{_format_ms(row['median_ms'])} | {_format_ms(row['maximum_ms'])} |")
    lines.extend((
        "", "## Capture and reduction", "",
        "Evaluated sources export a foreground snapshot, restore it in the helper, render the selected input, "
        "read its EXR data, and return bounded scene-linear RGBA. A Shader capture reads color, alpha, and "
        "coverage AOVs. A Linear edit can compute density from retained RGBA when the capture signature "
        "stays current. When a source invalidation changes that signature, the edit waits for another capture. "
        "The sample table reports the behavior observed for each competing demand.", "",
        "The reducer comparison replays the same final warm source capture for each approach. "
        "Capture time runs from the source edit until its pixels are available to the live scope. "
        "Capture plus reduction adds this measured interval to the separately timed reducer call. "
        "The draw table above measures the live CPU path. No latency threshold is applied.", "",
    ))
    rows = report["reducers"]
    if rows:
        lines.extend(("## Scalar reducer comparison", "",
                      "All approaches reduce alpha mass on the same capture for each path. "
                      "The live scope's RGB energy and Gaussian splat timings are reported below.",
                      "",
                      "| Path | Reducer | Capture (ms) | Mapping (ms) | Accumulation (ms) | Upload (ms) | "
                      "Readback (ms) | Normalize (ms) | Reducer total (ms) | Capture + reduction (ms) | "
                      "Maximum bin error | Parity |",
                      "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|"))
        for row in rows:
            timings = " | ".join(
                _format_ms(row[field]) if field in row else "-" for field in (
                    "capture_ms", "mapping_ms", "accumulation_ms", "upload_ms", "readback_ms",
                    "normalization_ms", "total_ms", "capture_and_reduce_ms",
                )
            )
            lines.append(f"| {row['path']} | {row['name']} | {timings} | "
                         f"{row['maximum_bin_error']:.6g} | {'pass' if row['parity'] else 'FAIL'} |")
        lines.extend((
            "",
            "GPU mapping and accumulation columns time command submission. The histogram readback also "
            "waits for GPU work to finish. Shader Editor mapping includes temporary scene setup, the "
            "mapping render, and mapped-sample readback before GPU accumulation.", "",
        ))
    components = report["color_component_checks"]
    if components:
        lines.extend((
            "## Live CPU color reduction", "",
            "The CPU bins alpha mass and alpha-weighted Rec.709 RGB energy. Independent NumPy histograms "
            "check both quantities in each bin. The Gaussian splat preserves total mass and RGB energy.",
            "",
            "| Capture or fixture | Binning (ms) | Gaussian splat (ms) | "
            "Maximum mass bin error | Maximum RGB energy bin error | Parity |",
            "|---|---:|---:|---:|---:|---|",
        ))
        for row in components:
            label = row.get("path", row.get("fixture"))
            lines.append(f"| {label} | {_format_ms(row['binning_ms'])} | "
                         f"{_format_ms(row['splat_ms'])} | {row['maximum_mass_bin_error']:.6g} | "
                         f"{row['maximum_rgb_energy_bin_error']:.6g} | "
                         f"{'pass' if row['parity'] else 'FAIL'} |")
        lines.append("")
    diagnostics = [row for row in controls
                   if row.get("invalidations") or row.get("attempt_timing_records")]
    if diagnostics:
        lines.extend(("## Linear edit diagnostics", "",
                      "Linear edits in this fixture were traced without changing the runtime path. "
                      "The invalidation rows identify Blender IDs delivered to the vectorscope source "
                      "invalidation hook that matched the scope's captured dependencies. Request and "
                      "capture stages are grouped by ticket generation.", "",
                      "| Path | Source epochs (previous, then requests) | Route changed | Requests | "
                      "Capture starts | Worker renders | Matching invalidations |",
                      "|---|---|---|---|---|---|---|"))
        for row in diagnostics:
            attempt_records = row["attempt_timing_records"]
            request_records = [record for record in attempt_records if record["stage"] == "request"]
            requests = ", ".join(str(record["ticket"]["generation"])
                                  for record in request_records) or "none"
            captures = ", ".join(dict.fromkeys(
                str(record["ticket"]["generation"]) for record in attempt_records
                if record["stage"] == "direct_readback"
            )) or "none"
            render_ms = {}
            for record in attempt_records:
                if record["stage"] == "capture_render" and record["clock"] == "worker":
                    generation = record["ticket"]["generation"]
                    render_ms[generation] = render_ms.get(generation, 0.0) + record["duration_ms"]
            renders = (", ".join(f"{generation}: {_format_ms(duration)} ms"
                                  for generation, duration in render_ms.items()) or "none")
            if render_ms:
                renders += f" (sum {_format_ms(sum(render_ms.values()))} ms)"
            revisions = [row["previous_revision"], *(record["metadata"] for record in request_records)]
            epochs = ", ".join(str(revision["source_epoch"]) for revision in revisions)
            routes = {revision["route_signature"] for revision in revisions}
            route_changed = "unknown" if None in routes else "yes" if len(routes) > 1 else "no"
            identifiers = sorted({
                f"{identifier['type']} `{identifier['name']}`"
                for invalidation in row["invalidations"] if invalidation["affected_scope"]
                for identifier in invalidation["changed_ids"] if identifier["matches_dependency"]
            })
            lines.append(f"| {row['path']} | {epochs} | {route_changed} | {requests} | {captures} | "
                         f"{renders} | {', '.join(identifiers) or 'none'} |")
        lines.append("")
    (output / "report.md").write_text("\n".join(lines), encoding="utf8")


def run(args):
    if sys.platform != "linux" or platform.machine() not in ("x86_64", "amd64"):
        raise RuntimeError("Vectorscope latency currently requires Linux x86_64")
    resources = files(__package__)
    binary = blender_binary(resources / "blender")
    extension = Path(str(resources / "extension.zip")).resolve()
    runner = Path(str(resources / "vectorscope_latency_runner.py")).resolve()
    fixture = Path(str(resources / "xvfb")).resolve()
    output = args.output_dir.expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    report = {
        "schema": 2, "target": TARGET, "completed": False, "reducer_selection": args.reducer,
        "environment": _environment(), "sessions": [], "samples": [], "linear_controls": [],
        "reducers": [], "reducer_checks": [], "reducer_cleanup_checks": [],
        "color_component_checks": [],
    }
    with tempfile.TemporaryDirectory(prefix="pg-vectorscope-latency-") as temporary:
        root = Path(temporary)
        benchmark_root = root / "benchmark-import"
        benchmark_package = benchmark_root / "tools" / "perceptual_grade" / "reports"
        benchmark_package.mkdir(parents=True)
        for package in (benchmark_root / "tools",
                        benchmark_root / "tools" / "perceptual_grade", benchmark_package):
            (package / "__init__.py").write_text("", encoding="utf8")
        for name in ("vectorscope_gpu.py", "vectorscope_reducers.py", "vectorscope_shader_tree.py"):
            (benchmark_package / name).write_bytes((resources / name).read_bytes())
        repository = root / "repository"
        (repository / "perceptual_grade").mkdir(parents=True)
        with zipfile.ZipFile(extension) as archive:
            archive.extractall(repository / "perceptual_grade")
        for ordinal, scenario in enumerate(SCENARIOS):
            session_root = root / f"session-{ordinal:02d}"
            session_root.mkdir()
            result = _run_session(args, binary, runner, fixture, repository,
                                  session_root, scenario, ordinal)
            report["samples"].extend(result.pop("samples", ()))
            report["linear_controls"].extend(result.pop("linear_controls", ()))
            report["reducers"].extend(result.pop("reducers", ()))
            report["reducer_checks"].extend(result.pop("reducer_checks", ()))
            report["reducer_cleanup_checks"].extend(
                result.pop("reducer_cleanup_checks", ())
            )
            report["color_component_checks"].extend(
                result.pop("color_component_checks", ())
            )
            report["sessions"].append(result)
            if not result.get("completed"):
                write_report(output, report)
                details = [*result.get("errors", ()), result.get("error"), result.get("native_log_tail")]
                step = result.get("step", "startup")
                raise RuntimeError(f"Vectorscope {scenario} session failed at {step}\n" +
                                   "\n".join(detail for detail in details if detail))
    report["completed"] = len(report["sessions"]) == len(SCENARIOS) and all(
        session.get("completed") for session in report["sessions"])
    write_report(output, report)
    print(f"Wrote {output / 'report.json'} and {output / 'report.md'}")
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=300.,
                        help="Per-session Blender deadline in seconds")
    parser.add_argument("--reducer", choices=REDUCERS, default="all",
                        help="Histogram reducer to benchmark on the same captured samples")
    args = parser.parse_args(argv)
    if not isfinite(args.timeout) or args.timeout <= 0:
        parser.error("timeout must be finite and positive")
    run(args)


if __name__ == "__main__":
    main()
