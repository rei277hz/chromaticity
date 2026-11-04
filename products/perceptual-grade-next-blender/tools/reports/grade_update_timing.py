"""Measure installed Grade texture publications and UI responsiveness."""

from importlib.resources import files
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import zipfile

from .grade_update_timing_report import validate_profile, write_report
from .stack_lut_timing import blender_binary, software_display


def run(args):
    if sys.platform != "linux" or os.uname().machine not in ("x86_64", "amd64"):
        raise RuntimeError("Grade update timing currently requires Linux x86_64")
    resources = files(__package__)
    binary = blender_binary(resources / "blender")
    extension = Path(str(resources / "extension.zip")).resolve()
    runner = Path(str(resources / "grade_update_timing_runner.py")).resolve()
    fixture = Path(str(resources / "xvfb")).resolve()
    output = args.output_dir.expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="pg-grade-update-") as temporary:
        root = Path(temporary)
        repository = root / "repository"
        package = repository / "perceptual_grade"
        package.mkdir(parents=True)
        with zipfile.ZipFile(extension) as archive:
            archive.extractall(package)
        configuration = root / "configuration.json"
        result_path = root / "worker-report.json"
        config = {
            "repository": str(repository), "report": str(result_path),
            "stage": args.stage, "duration": args.duration,
            "viewport": args.viewport,
            "verify_render_preflight": args.verify_render_preflight,
            "interval_ms": args.interval_ms, "warmup": args.warmup,
            "timeout": args.timeout,
        }
        configuration.write_text(json.dumps(config, indent=2) + "\n", encoding="utf8")
        with software_display(fixture, root) as env:
            env.update(BLENDER_USER_CONFIG=str(root / "config"),
                       BLENDER_USER_EXTENSIONS=str(root / "extensions"))
            command = [str(binary), "--factory-startup", "--disable-autoexec",
                       "--window-geometry", "0", "0", "1280", "960",
                       "--python-exit-code", "1", "--python", str(runner), "--",
                       str(configuration)]
            started = time.perf_counter()
            with (output / "native.log").open("w", encoding="utf8") as log:
                process = subprocess.Popen(command, cwd=root, env=env, stdout=log,
                                           stderr=subprocess.STDOUT, start_new_session=True)
                try:
                    code = process.wait(timeout=args.timeout + 60)
                except subprocess.TimeoutExpired as error:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=10)
                    raise RuntimeError("Grade timing session timed out; see native.log") from error
            process_seconds = time.perf_counter() - started
        if not result_path.is_file():
            raise RuntimeError(f"Blender produced no report (exit {code}); see native.log")
        report = json.loads(result_path.read_text(encoding="utf8"))
        report.update(process_returncode=code, process_wall_seconds=process_seconds,
                      target="//products/perceptual-grade-next-blender/tools/reports:grade_update_timing")
        write_report(output, report)
        if code or not report.get("completed"):
            raise RuntimeError(f"Grade update timing failed; see {output / 'native.log'}")
    print(f"Wrote {output / 'report.json'} and {output / 'report.md'}")
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--stage", choices=("linear", "tone", "both"), default="linear")
    parser.add_argument("--viewport", choices=("rendered", "solid"), default="rendered",
                        help="Rendered measures viewport work too; solid isolates publication/UI throughput")
    parser.add_argument("--verify-render-preflight", action="store_true",
                        help="After measuring, invoke a render with pending Grade changes and verify foreground reconciliation")
    parser.add_argument("--duration", type=float, default=3., help="Continuous-drag duration in seconds")
    parser.add_argument("--interval-ms", type=float, default=0.,
                        help="Requested edit interval; zero requests every available timer turn")
    parser.add_argument("--warmup", type=float, default=2., help="Viewport warmup after initial Grade preparation")
    parser.add_argument("--timeout", type=float, default=180., help="Total Blender session deadline")
    args = parser.parse_args(argv)
    try:
        validate_profile(args.duration, args.interval_ms, args.warmup, args.timeout)
    except ValueError as error:
        parser.error(str(error))
    run(args)


if __name__ == "__main__":
    main()
