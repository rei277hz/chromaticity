"""Measure installed Compositor Grade dragging against live Viewer window pixels."""

from importlib.resources import files
import argparse
import hashlib
import json
from math import isfinite
import os
from pathlib import Path
import platform
import sys
import tempfile
import zipfile

from .compositor_display_timing_report import write_report
from .shader_display_timing import _cpu_model, _host_snapshot, _merge_fixture, _run_session
from .stack_lut_timing import blender_binary


CONTROLS = ("pg_linear.exposure", "pg_tone.fit")
TARGET = "//products/perceptual-grade-next-blender/tools/reports:compositor_display_timing"


def _source_hashes(resources):
    names = ("compositor_display_timing.py", "compositor_display_timing_runner.py",
             "compositor_display_timing_report.py", "shader_display_timing.py",
             "shader_display_capture.py", "shader_display_timing_report.py",
             "stack_lut_timing.py", "extension.zip")
    return {name: hashlib.sha256((resources / name).read_bytes()).hexdigest()
            for name in names}


def _validate(args):
    if args.sessions < 1:
        raise ValueError("sessions must be positive")
    if not all(isfinite(value) for value in (args.drag_duration, args.interval_ms,
                                            args.capture_interval_ms, args.warmup, args.timeout)):
        raise ValueError("Timing arguments must be finite")
    if args.drag_duration <= 0 or args.interval_ms < 0 or args.capture_interval_ms <= 0:
        raise ValueError("drag duration and capture interval must be positive; input interval must be nonnegative")
    if args.warmup < 0 or args.timeout <= args.warmup + 4 * args.drag_duration:
        raise ValueError("timeout must cover warmup and observed/unobserved drags for both controls")


def run(args):
    _validate(args)
    if sys.platform != "linux" or platform.machine() not in ("x86_64", "amd64"):
        raise RuntimeError("Compositor display timing currently requires Linux x86_64")
    resources = files(__package__)
    binary = blender_binary(resources / "blender")
    extension = Path(str(resources / "extension.zip")).resolve()
    runner = Path(str(resources / "compositor_display_timing_runner.py")).resolve()
    fixture = Path(str(resources / "xvfb")).resolve()
    baseline = None
    if args.baseline is not None:
        baseline_path = args.baseline.expanduser().resolve()
        if baseline_path.is_dir():
            baseline_path /= "report.json"
        baseline_bytes = baseline_path.read_bytes()
        baseline = json.loads(baseline_bytes)
    output = args.output_dir.expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    sessions = output / "sessions"
    sessions.mkdir(exist_ok=True)
    if any(sessions.iterdir()):
        raise ValueError(f"Session output directory must be empty: {sessions}")
    hashes = _source_hashes(resources)
    report = {
        "schema": 1, "target": TARGET, "completed": False,
        "environment": {
            "platform": platform.platform(), "machine": platform.machine(),
            "cpu_count": os.cpu_count(), "cpu_model": _cpu_model(),
            "cpu_affinity": sorted(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else None,
            "display": "Xvfb", "renderer": "Mesa llvmpipe",
            "openblas_threads": 1, "omp_threads": 1,
            "llvmpipe_threads_requested": os.environ.get("LP_NUM_THREADS"),
            "mesa_glthread_requested": os.environ.get("mesa_glthread"),
            "mesa_override_version": os.environ.get("MESA_GL_VERSION_OVERRIDE"),
        },
        "profile": {
            "context": "compositor", "scenarios": ["drag"],
            "sessions": args.sessions, "controls": list(CONTROLS),
            "drag_duration_seconds": args.drag_duration,
            "update_interval_ms": args.interval_ms,
            "capture_interval_ms": args.capture_interval_ms,
            "warmup_seconds": args.warmup, "timeout_seconds": args.timeout,
            "window_size": [1280, 960],
            "measurement_sha256": {name: value for name, value in hashes.items() if name != "extension.zip"},
        },
        "source_sha256": hashes,
        "blender_binary_sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
        "host_start": _host_snapshot(), "sessions": [],
    }
    if baseline is not None:
        report["baseline_sha256"] = hashlib.sha256(baseline_bytes).hexdigest()
    # The existing launcher also accepts an isolated-sample count. This runner
    # deliberately measures only continuous dragging.
    args.samples = 0
    with tempfile.TemporaryDirectory(prefix="pg-compositor-display-") as temporary:
        repository = Path(temporary) / "repository"
        package = repository / "perceptual_grade"
        package.mkdir(parents=True)
        with zipfile.ZipFile(extension) as archive:
            archive.extractall(package)
        for ordinal in range(args.sessions):
            directory = sessions / f"session-{ordinal:02d}"
            result = _run_session(args, binary, runner, fixture, repository, directory, ordinal)
            _merge_fixture(report, result)
            report["sessions"].append(result)
            report["host_finish"] = _host_snapshot()
            report["sources_stable_during_run"] = hashes == _source_hashes(resources)
            report["completed"] = (
                len(report["sessions"]) == args.sessions
                and all(session["completed"] for session in report["sessions"])
                and report["sources_stable_during_run"]
            )
            write_report(output, report, baseline=baseline)
            if not result["completed"]:
                raise RuntimeError(f"Compositor display timing session {ordinal} failed; see {directory}")
            if not report["sources_stable_during_run"]:
                raise RuntimeError("Timing sources changed during the run; partial evidence was retained")
            if report["completed"] and not report["summary"]["valid"]:
                raise RuntimeError("Compositor display observations are invalid; see report.json")
            print(f"Session {ordinal + 1}/{args.sessions}: {len(result.get('samples', []))} edits, "
                  f"{len(result['captures'])} X11 captures", flush=True)
    print(f"Wrote {output / 'report.json'} and {output / 'report.md'}")
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, help="Prior compatible Compositor report or directory")
    parser.add_argument("--sessions", type=int, default=5)
    parser.add_argument("--drag-duration", type=float, default=3.)
    parser.add_argument("--interval-ms", type=float, default=50.)
    parser.add_argument("--capture-interval-ms", type=float, default=5.)
    parser.add_argument("--warmup", type=float, default=2.)
    parser.add_argument("--timeout", type=float, default=1800.)
    args = parser.parse_args(argv)
    try:
        _validate(args)
    except ValueError as error:
        parser.error(str(error))
    run(args)


if __name__ == "__main__":
    main()
