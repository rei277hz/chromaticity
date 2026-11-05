"""Measure installed Shader Grade edits against independently captured X11 pixels."""

from importlib.resources import files
import argparse
import hashlib
import json
from math import isfinite
import os
from pathlib import Path
import platform
import signal
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import zipfile

from .shader_display_capture import capture_loop
from .shader_display_timing_report import write_report
from .stack_lut_timing import blender_binary, software_display


CONTROLS = ("pg_linear.exposure", "pg_tone.fit")
TARGET = "//products/perceptual-grade-next-blender/tools/reports:shader_display_timing"


def _source_hashes(resources):
    names = ("shader_display_timing.py", "shader_display_timing_runner.py",
             "shader_display_capture.py", "shader_display_timing_report.py",
             "stack_lut_timing.py", "extension.zip")
    return {name: hashlib.sha256((resources / name).read_bytes()).hexdigest()
            for name in names}


def _cpu_model():
    cpuinfo = Path("/proc/cpuinfo")
    if cpuinfo.is_file():
        for line in cpuinfo.read_text(encoding="utf8").splitlines():
            if line.startswith("model name"):
                return line.split(":", 1)[1].strip()
    return platform.processor()


def _host_snapshot():
    result = {"at_unix_ns": time.time_ns()}
    if hasattr(os, "getloadavg"):
        result["load_average"] = list(os.getloadavg())
    for name in ("cpu", "io", "memory"):
        path = Path("/proc/pressure") / name
        if path.is_file():
            result[name + "_pressure"] = path.read_text(encoding="utf8")
    return result


def _merge_fixture(report, result):
    if not result["completed"]:
        return
    for name, source in (("environment", "native"), ("profile", "fixture")):
        value = result.get(name)
        if not isinstance(value, dict) or not value:
            result["completed"] = False
            result.setdefault("orchestrator_errors", []).append(
                f"Completed Blender session has no actual {name} metadata")
            continue
        destination = report[name]
        if source not in destination:
            destination[source] = value
        elif destination[source] != value:
            result["completed"] = False
            result.setdefault("orchestrator_errors", []).append(
                f"Actual Blender {name} changed between timing sessions")


def _read_captures(path):
    if not path.is_file():
        return []
    records = []
    with path.open(encoding="utf8") as source:
        for number, line in enumerate(source, 1):
            if line.strip():
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError as error:
                    raise ValueError(f"Invalid X11 capture record {path}:{number}") from error
    return records


def _profile(args):
    return {
        "sessions": args.sessions,
        "samples": args.samples,
        "controls": list(CONTROLS),
        "drag_duration_seconds": args.drag_duration,
        "update_interval_ms": args.interval_ms,
        "capture_interval_ms": args.capture_interval_ms,
        "warmup_seconds": args.warmup,
        "timeout_seconds": args.timeout,
        "window_size": [1280, 960],
    }


def _validate(args):
    if args.sessions < 1 or args.samples < 1:
        raise ValueError("sessions and isolated samples per control must be positive")
    values = (args.drag_duration, args.interval_ms, args.capture_interval_ms,
              args.warmup, args.timeout)
    if not all(isfinite(value) for value in values):
        raise ValueError("Timing arguments must be finite")
    if args.drag_duration <= 0 or args.interval_ms < 0 or args.capture_interval_ms <= 0:
        raise ValueError("drag duration and capture interval must be positive; update interval must be nonnegative")
    if args.warmup < 0 or args.timeout <= args.warmup + len(CONTROLS) * args.drag_duration:
        raise ValueError("warmup must be nonnegative and timeout must cover warmup and both drags")


def _run_session(args, binary, runner, fixture, repository, directory, ordinal):
    directory.mkdir()
    result_path = directory / "worker-report.json"
    capture_request = directory / "capture-request.json"
    capture_trace = directory / "captures.jsonl"
    capture_stop = directory / "capture-stop"
    config = {
        "repository": str(repository),
        "report": str(result_path),
        "output_dir": str(directory),
        "capture_request": str(capture_request),
        "capture_trace": str(capture_trace),
        "capture_stop": str(capture_stop),
        "import_paths": [str(Path(path).resolve()) for path in sys.path
                         if path and Path(path).is_dir()],
        "session": ordinal,
        "controls": list(CONTROLS),
        "samples": args.samples,
        "drag_duration": args.drag_duration,
        "interval_ms": args.interval_ms,
        "capture_interval_ms": args.capture_interval_ms,
        "warmup": args.warmup,
        "timeout": args.timeout,
    }
    configuration = directory / "configuration.json"
    configuration.write_text(json.dumps(config, indent=2) + "\n", encoding="utf8")
    command = [str(binary), "--factory-startup", "--disable-autoexec", "--enable-event-simulate",
               "--window-geometry", "0", "0", "1280", "960",
               "--python-exit-code", "1", "--python", str(runner), "--",
               str(configuration)]
    errors = []
    capture_errors = []
    code = None
    started = time.perf_counter()
    with software_display(fixture, directory) as env:
        env.update(BLENDER_USER_CONFIG=str(directory / "config"),
                   BLENDER_USER_EXTENSIONS=str(directory / "extensions"))

        def capture():
            try:
                capture_loop(fixture, env["DISPLAY"], capture_request,
                             capture_trace, capture_stop, args.capture_interval_ms)
            except BaseException:
                capture_errors.append(traceback.format_exc())

        sampler = threading.Thread(target=capture, name="shader-display-capture", daemon=True)
        sampler.start()
        try:
            with (directory / "native.log").open("w", encoding="utf8") as log:
                process = subprocess.Popen(command, cwd=directory, env=env, stdout=log,
                                           stderr=subprocess.STDOUT, start_new_session=True)
                try:
                    deadline = time.monotonic() + args.timeout + 60.
                    while process.poll() is None:
                        if capture_errors:
                            raise RuntimeError("X11 capture sampler failed")
                        if time.monotonic() >= deadline:
                            raise TimeoutError("Shader display timing session exceeded its deadline")
                        try:
                            process.wait(timeout=.1)
                        except subprocess.TimeoutExpired:
                            pass
                except BaseException:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=10)
                    raise
                finally:
                    code = process.returncode
        except Exception:
            errors.append(traceback.format_exc())
        finally:
            capture_stop.touch()
            sampler.join(timeout=10)
            if sampler.is_alive():
                errors.append("X11 capture sampler did not terminate after the stop request")
    errors.extend(capture_errors)
    try:
        result = json.loads(result_path.read_text(encoding="utf8"))
    except (OSError, json.JSONDecodeError):
        result = {"completed": False, "error": traceback.format_exc()}
    try:
        result["captures"] = _read_captures(capture_trace)
    except ValueError:
        errors.append(traceback.format_exc())
        result["captures"] = []
    result.update(session=ordinal, command=command, process_returncode=code,
                  process_wall_seconds=time.perf_counter() - started,
                  report_path=str(result_path), capture_trace_path=str(capture_trace))
    if errors:
        result["orchestrator_errors"] = errors
    result["completed"] = bool(result.get("completed") and code == 0 and not errors)
    return result


def run(args):
    _validate(args)
    if sys.platform != "linux" or platform.machine() not in ("x86_64", "amd64"):
        raise RuntimeError("Shader display timing currently requires Linux x86_64")
    resources = files(__package__)
    binary = blender_binary(resources / "blender")
    extension = Path(str(resources / "extension.zip")).resolve()
    runner = Path(str(resources / "shader_display_timing_runner.py")).resolve()
    fixture = Path(str(resources / "xvfb")).resolve()
    if not extension.is_file() or not runner.is_file():
        raise RuntimeError("Buck Shader display timing resources are incomplete")
    baseline = None
    baseline_sha256 = None
    if args.baseline is not None:
        baseline_path = args.baseline.expanduser().resolve()
        if baseline_path.is_dir():
            baseline_path /= "report.json"
        baseline_bytes = baseline_path.read_bytes()
        baseline = json.loads(baseline_bytes)
        baseline_sha256 = hashlib.sha256(baseline_bytes).hexdigest()
    output = args.output_dir.expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    sessions = output / "sessions"
    sessions.mkdir(exist_ok=True)
    if any(sessions.iterdir()):
        raise ValueError(f"Session output directory must be empty: {sessions}")
    hashes = _source_hashes(resources)
    report = {
        "schema": 1,
        "target": TARGET,
        "completed": False,
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
        "profile": _profile(args),
        "source_sha256": hashes,
        "blender_binary_sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
        "host_start": _host_snapshot(),
        "sessions": [],
    }
    report["profile"]["measurement_sha256"] = {
        name: value for name, value in hashes.items() if name != "extension.zip"
    }
    if baseline_sha256 is not None:
        report["baseline_sha256"] = baseline_sha256
    with tempfile.TemporaryDirectory(prefix="pg-shader-display-") as temporary:
        repository = Path(temporary) / "repository"
        package = repository / "perceptual_grade"
        package.mkdir(parents=True)
        with zipfile.ZipFile(extension) as archive:
            archive.extractall(package)
        for ordinal in range(args.sessions):
            directory = sessions / f"session-{ordinal:02d}"
            result = _run_session(args, binary, runner, fixture,
                                  repository, directory, ordinal)
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
                raise RuntimeError(f"Shader display timing session {ordinal} failed; see {directory}")
            if not report["sources_stable_during_run"]:
                raise RuntimeError("Timing sources changed during the run; partial evidence was retained")
            if report["completed"] and not report["summary"]["valid"]:
                raise RuntimeError("Shader display timing observations are invalid; see report.json")
            print(f"Session {ordinal + 1}/{args.sessions}: {len(result.get('samples', []))} edits, "
                  f"{len(result['captures'])} X11 captures", flush=True)
    print(f"Wrote {output / 'report.json'} and {output / 'report.md'}")
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--baseline", type=Path,
                        help="Prior report.json or report directory for a compatible comparison")
    parser.add_argument("--sessions", type=int, default=5,
                        help="Fresh Blender processes; each exercises both controls")
    parser.add_argument("--samples", type=int, default=100,
                        help="Isolated updates per control in each fresh process")
    parser.add_argument("--drag-duration", type=float, default=3.,
                        help="Continuous drag duration per control in seconds")
    parser.add_argument("--interval-ms", type=float, default=50.,
                        help="Requested edit interval; zero uses each available timer turn")
    parser.add_argument("--capture-interval-ms", type=float, default=5.,
                        help="Requested X11 capture interval; actual intervals are retained")
    parser.add_argument("--warmup", type=float, default=2.,
                        help="Viewport warmup after initial Grade setup in seconds")
    parser.add_argument("--timeout", type=float, default=1800.,
                        help="Deadline for each Blender session in seconds")
    args = parser.parse_args(argv)
    try:
        _validate(args)
    except ValueError as error:
        parser.error(str(error))
    run(args)


if __name__ == "__main__":
    main()
