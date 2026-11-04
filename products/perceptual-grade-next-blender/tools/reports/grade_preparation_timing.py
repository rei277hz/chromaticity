"""Measure complete Grade preparation and native kernel construction."""

from importlib.resources import files
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import zipfile

from .grade_preparation_timing_report import write_report


def blender_binary(resource):
    root = Path(str(resource)).resolve()
    candidates = (root / "blender", root / "Blender.app/Contents/MacOS/Blender")
    binary = next((path for path in candidates if path.is_file()), None)
    if binary is None:
        raise RuntimeError(f"Pinned Blender executable not found under {root}")
    return binary


def run(args):
    resources = files(__package__)
    binary = blender_binary(resources / "blender")
    extension = Path(str(resources / "extension.zip")).resolve()
    runner = Path(str(resources / "grade_preparation_timing_runner.py")).resolve()
    if not extension.is_file() or not runner.is_file():
        raise RuntimeError("Buck timing resources are incomplete")

    output = args.output_dir.expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="pg-grade-preparation-") as temporary:
        root = Path(temporary)
        package = root / "python" / "perceptual_grade"
        package.mkdir(parents=True)
        with zipfile.ZipFile(extension) as archive:
            archive.extractall(package)
        configuration = root / "configuration.json"
        result_path = root / "worker-report.json"
        configuration.write_text(json.dumps({
            "package_root": str(package.parent),
            "report": str(result_path),
            "samples": args.samples,
        }, indent=2) + "\n", encoding="utf8")
        env = {
            key: value for key, value in os.environ.items()
            if key not in {
                "PYTHONPATH", "PYTHONHOME", "BLENDER_USER_SCRIPTS",
                "BLENDER_SYSTEM_SCRIPTS", "BLENDER_SYSTEM_PYTHON",
            }
        }
        env.update(
            BLENDER_USER_CONFIG=str(root / "config"),
            BLENDER_USER_EXTENSIONS=str(root / "extensions"),
            PYTHONDONTWRITEBYTECODE="1",
        )
        fixture = Path(str(resources / "xvfb")).resolve()
        libraries = fixture / "usr/lib/x86_64-linux-gnu"
        env["LD_LIBRARY_PATH"] = os.pathsep.join(
            path for path in (str(libraries), env.get("LD_LIBRARY_PATH", "")) if path
        )
        env["LIBGL_DRIVERS_PATH"] = str(libraries / "dri")
        env["LIBGL_ALWAYS_SOFTWARE"] = "1"
        command = [
            str(binary), "--background", "--factory-startup", "--disable-autoexec",
            "--python-exit-code", "1", "--python", str(runner), "--",
            str(configuration),
        ]
        started = time.perf_counter()
        with (output / "native.log").open("w", encoding="utf8") as log:
            try:
                code = subprocess.run(
                    command, cwd=root, env=env, stdout=log,
                    stderr=subprocess.STDOUT, timeout=args.timeout, check=False,
                ).returncode
            except subprocess.TimeoutExpired as error:
                raise RuntimeError(
                    f"Blender timing session exceeded {args.timeout:.0f}s; see native.log"
                ) from error
        process_seconds = time.perf_counter() - started
        if not result_path.is_file():
            raise RuntimeError(f"Blender produced no report (exit {code}); see native.log")
        report = json.loads(result_path.read_text(encoding="utf8"))
        report["process_returncode"] = code
        report["process_wall_seconds"] = process_seconds
        report["target"] = "//products/perceptual-grade-next-blender/tools/reports:grade_preparation_timing"
        write_report(output, report)
        if code or not report.get("completed"):
            raise RuntimeError(f"Grade preparation timing failed; see {output / 'native.log'}")
    print(f"Wrote {output / 'report.json'} and {output / 'report.md'}")
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--samples", type=int, default=5)
    parser.add_argument("--timeout", type=float, default=300.0)
    args = parser.parse_args(argv)
    if args.samples < 1 or args.timeout <= 0:
        parser.error("samples and timeout must be positive")
    run(args)


if __name__ == "__main__":
    main()
