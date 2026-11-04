"""Measure Stack LUT publication after repeatable scripted slider gestures."""

from contextlib import contextmanager
from importlib.resources import files
import argparse
import json
import os
from pathlib import Path
import selectors
import signal
import subprocess
import sys
import tempfile
import time
import zipfile

from .stack_lut_timing_report import validate_profile, write_report


@contextmanager
def software_display(fixture, root):
    fixture = Path(fixture)
    libraries = fixture / "usr/lib/x86_64-linux-gnu"
    runtime = root / "xdg-runtime"
    runtime.mkdir(mode=0o700)
    library_paths = [str(libraries)]
    if os.environ.get("LD_LIBRARY_PATH"):
        library_paths.append(os.environ["LD_LIBRARY_PATH"])
    env = {
        key: value for key, value in os.environ.items()
        if key not in {
            "PYTHONPATH", "PYTHONHOME", "BLENDER_USER_SCRIPTS",
            "BLENDER_SYSTEM_SCRIPTS", "BLENDER_SYSTEM_PYTHON", "WAYLAND_DISPLAY",
        }
    }
    env.update(
        DISPLAY="",
        XDG_RUNTIME_DIR=str(runtime),
        LD_LIBRARY_PATH=os.pathsep.join(library_paths),
        LIBGL_DRIVERS_PATH=str(libraries / "dri"),
        LIBGL_ALWAYS_SOFTWARE="1",
        GALLIUM_DRIVER="llvmpipe",
        __GLX_VENDOR_LIBRARY_NAME="mesa",
        OPENBLAS_NUM_THREADS="1",
        OMP_NUM_THREADS="1",
        PYTHONDONTWRITEBYTECODE="1",
    )
    read_fd, write_fd = os.pipe()
    server = None
    try:
        with (root / "xvfb.log").open("w", encoding="utf8") as log:
            server = subprocess.Popen(
                [
                    str(fixture / "usr/bin/Xvfb"), "-displayfd", str(write_fd),
                    "-screen", "0", "1280x960x24", "-nolisten", "tcp", "-ac",
                    "+extension", "GLX", "+render", "-noreset", "-xkbdir",
                    str(fixture / "usr/share/X11/xkb"),
                ],
                cwd=fixture,
                env=env,
                pass_fds=(write_fd,),
                stdout=log,
                stderr=subprocess.STDOUT,
            )
            os.close(write_fd)
            write_fd = None
            with selectors.DefaultSelector() as ready:
                ready.register(read_fd, selectors.EVENT_READ)
                if not ready.select(timeout=30):
                    raise RuntimeError("Xvfb did not publish a display number")
                display = os.read(read_fd, 64).decode("ascii").strip()
            if not display.isdigit():
                raise RuntimeError("Xvfb initialization failed: " + (root / "xvfb.log").read_text())
            env["DISPLAY"] = ":" + display
            yield env
    finally:
        os.close(read_fd)
        if write_fd is not None:
            os.close(write_fd)
        if server is not None:
            server.terminate()
            try:
                server.wait(timeout=10)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait(timeout=10)


def blender_binary(resource):
    root = Path(str(resource)).resolve()
    candidates = (root / "blender", root / "Blender.app/Contents/MacOS/Blender")
    binary = next((path for path in candidates if path.is_file()), None)
    if binary is None:
        raise RuntimeError(f"Pinned Blender executable not found under {root}")
    return binary


def run(args):
    if sys.platform != "linux" or os.uname().machine not in ("x86_64", "amd64"):
        raise RuntimeError("Stack LUT timing currently requires Linux x86_64")

    resources = files(__package__)
    binary = blender_binary(resources / "blender")
    extension = Path(str(resources / "extension.zip")).resolve()
    runner = Path(str(resources / "stack_lut_timing_runner.py")).resolve()
    fixture = Path(str(resources / "xvfb")).resolve()
    if not extension.is_file() or not runner.is_file():
        raise RuntimeError("Buck timing resources are incomplete")

    output = args.output_dir.expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="pg-stack-lut-") as temporary:
        root = Path(temporary)
        repository = root / "repository"
        package = repository / "perceptual_grade"
        package.mkdir(parents=True)
        with zipfile.ZipFile(extension) as archive:
            archive.extractall(package)
        configuration = root / "configuration.json"
        result_path = root / "worker-report.json"
        config = {
            "repository": str(repository),
            "report": str(result_path),
            "output_dir": str(output),
            "node_tree": args.node_tree,
            "stage": args.stage,
            "grade_count": args.grade_count,
            "samples": args.samples,
            "updates": args.updates,
            "interval_ms": args.interval_ms,
            "preview_timeout": args.preview_timeout,
            "timeout": args.timeout,
        }
        configuration.write_text(json.dumps(config, indent=2) + "\n", encoding="utf8")
        env = dict(os.environ)
        with software_display(fixture, root) as env:
            env.update(
                BLENDER_USER_CONFIG=str(root / "config"),
                BLENDER_USER_EXTENSIONS=str(root / "extensions"),
            )
            command = [
                str(binary), "--factory-startup", "--disable-autoexec",
                "--window-geometry", "0", "0", "1280", "960",
                "--python-exit-code", "1", "--python", str(runner), "--",
                str(configuration),
            ]
            started = time.perf_counter()
            with (output / "native.log").open("w", encoding="utf8") as log:
                process = subprocess.Popen(
                    command,
                    cwd=root,
                    env=env,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                )
                try:
                    code = process.wait(timeout=args.timeout + 60)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=10)
                    raise RuntimeError(
                        f"Blender timing session exceeded {args.timeout + 60:.0f}s; see native.log"
                    )
            process_seconds = time.perf_counter() - started
        if not result_path.is_file():
            raise RuntimeError(f"Blender produced no report (exit {code}); see native.log")
        report = json.loads(result_path.read_text(encoding="utf8"))
        report["process_returncode"] = code
        report["process_wall_seconds"] = process_seconds
        report["target"] = "//products/perceptual-grade-next-blender/tools/reports:stack_lut_timing"
        report["profile"] = {key: value for key, value in config.items()
                              if key not in {"repository", "report", "output_dir"}}
        write_report(output, report)
        if code or not report.get("completed"):
            raise RuntimeError(f"Stack LUT timing session failed; see {output / 'native.log'}")
        print(f"Wrote {output / 'report.json'} and {output / 'report.md'}")
        return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--node-tree", choices=("shader", "compositor"), default="shader")
    parser.add_argument("--stage", choices=("linear", "tone"), default="tone",
                        help="Grade controls to exercise during the drag")
    parser.add_argument("--grade-count", type=int, default=3)
    parser.add_argument("--samples", type=int, default=3, help="Number of drags in one Blender session")
    parser.add_argument("--updates", type=int, default=20, help="Property changes per drag")
    parser.add_argument("--interval-ms", type=float, default=50.0, help="Interval between updates")
    parser.add_argument("--preview-timeout", type=float, default=3.0,
                        help="Maximum final-value hold while awaiting a matching preview")
    parser.add_argument("--timeout", type=float, default=900.0,
                        help="Blender session deadline in seconds")
    args = parser.parse_args(argv)
    try:
        validate_profile(args.grade_count, args.samples, args.updates,
                         args.interval_ms, args.preview_timeout, args.timeout)
    except ValueError as error:
        parser.error(str(error))
    run(args)


if __name__ == "__main__":
    main()
