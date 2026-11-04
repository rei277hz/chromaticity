"""Run GPU tests in pinned Blender under the repository's software X server."""

from importlib.resources import files
import json
import os
from pathlib import Path
import selectors
import subprocess
import sys
import tempfile


def _resource(name):
    return Path(str(files("tests.perceptual_grade_blender.gpu") / name)).resolve()


def _blender_binary():
    root = _resource("blender")
    candidates = (root / "blender", root / "Blender.app/Contents/MacOS/Blender")
    binary = next((path for path in candidates if path.is_file()), None)
    if binary is None:
        raise RuntimeError(f"Pinned Blender executable not found under {root}")
    return binary


def main():
    if sys.platform != "linux":
        raise RuntimeError("The native GPU test target currently requires Linux")

    fixture = _resource("xvfb")
    libraries = fixture / "usr/lib/x86_64-linux-gnu"
    with tempfile.TemporaryDirectory(prefix="pg-lut-gpu-test-") as directory:
        root = Path(directory)
        runtime = root / "runtime"
        runtime.mkdir(mode=0o700)
        environment = {
            key: value for key, value in os.environ.items()
            if key not in {
                "PYTHONPATH", "PYTHONHOME", "BLENDER_USER_SCRIPTS",
                "BLENDER_SYSTEM_SCRIPTS", "BLENDER_SYSTEM_PYTHON", "WAYLAND_DISPLAY",
            }
        }
        environment.update(
            LD_LIBRARY_PATH=os.pathsep.join(filter(None, (
                str(libraries), environment.get("LD_LIBRARY_PATH"),
            ))),
            LIBGL_DRIVERS_PATH=str(libraries / "dri"),
            LIBGL_ALWAYS_SOFTWARE="1",
            GALLIUM_DRIVER="llvmpipe",
            __GLX_VENDOR_LIBRARY_NAME="mesa",
            XDG_RUNTIME_DIR=str(runtime),
            OPENBLAS_NUM_THREADS="1",
            OMP_NUM_THREADS="1",
            PYTHONDONTWRITEBYTECODE="1",
        )

        read_fd, write_fd = os.pipe()
        display_server = None
        try:
            with (root / "xvfb.log").open("w", encoding="utf8") as log:
                display_server = subprocess.Popen(
                    [str(fixture / "usr/bin/Xvfb"), "-displayfd", str(write_fd),
                     "-screen", "0", "1280x960x24", "-nolisten", "tcp", "-ac",
                     "+extension", "GLX", "+render", "-noreset",
                     "-xkbdir", str(fixture / "usr/share/X11/xkb")],
                    cwd=fixture, env=environment, pass_fds=(write_fd,),
                    stdout=log, stderr=subprocess.STDOUT,
                )
                os.close(write_fd)
                write_fd = None
                with selectors.DefaultSelector() as ready:
                    ready.register(read_fd, selectors.EVENT_READ)
                    if not ready.select(timeout=30):
                        raise RuntimeError("Xvfb did not publish a display number")
                    display = os.read(read_fd, 64).decode("ascii").strip()
                if not display.isdigit():
                    raise RuntimeError("Xvfb startup failed: " + (root / "xvfb.log").read_text())

            environment["DISPLAY"] = ":" + display
            runner = _resource("native_runner.py")
            config = root / "configuration.json"
            config.write_text(json.dumps({
                "python_paths": [path for path in sys.path
                                 if path and Path(path).exists()],
                "test_module": "tests.perceptual_grade_blender.gpu.test_lut_gpu",
            }), encoding="utf8")
            command = [
                str(_blender_binary()), "--background", "--factory-startup",
                "--disable-autoexec", "--python-exit-code", "1",
                "--python", str(runner), "--", str(config),
            ]
            result = subprocess.run(
                command, cwd=root, env=environment,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, timeout=900, check=False,
            )
            sys.stdout.write(result.stdout)
            if result.returncode:
                raise SystemExit(result.returncode)
        finally:
            os.close(read_fd)
            if write_fd is not None:
                os.close(write_fd)
            if display_server is not None:
                display_server.terminate()
                try:
                    display_server.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    display_server.kill()
                    display_server.wait(timeout=10)


if __name__ == "__main__":
    main()
