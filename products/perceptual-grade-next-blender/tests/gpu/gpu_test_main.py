"""Run the GPU tests under the repository's pinned software OpenGL fixture."""

from importlib.resources import files
import os
from pathlib import Path
import runpy
import selectors
import subprocess
import sys
import tempfile


def main():
    if sys.platform != "linux" or os.environ.get("PG_GPU_TEST_CHILD") == "1":
        if os.environ.get("PG_GPU_TEST_LIBRARY_PATH"):
            os.environ["LD_LIBRARY_PATH"] = os.environ["PG_GPU_TEST_LIBRARY_PATH"]
        runpy.run_module("__test_main__", run_name="__main__")
        return

    fixture = Path(str(files("tests.perceptual_grade_blender.gpu") / "xvfb")).resolve()
    libraries = fixture / "usr/lib/x86_64-linux-gnu"
    with tempfile.TemporaryDirectory(prefix="pg-lut-gpu-test-") as directory:
        root = Path(directory)
        runtime = root / "runtime"
        runtime.mkdir(mode=0o700)
        environment = dict(os.environ)
        environment.update(
            LD_LIBRARY_PATH=os.pathsep.join(filter(None, (
                str(libraries), environment.get("LD_LIBRARY_PATH"),
            ))),
            LIBGL_DRIVERS_PATH=str(libraries / "dri"),
            LIBGL_ALWAYS_SOFTWARE="1",
            GALLIUM_DRIVER="llvmpipe",
            __GLX_VENDOR_LIBRARY_NAME="mesa",
            XDG_RUNTIME_DIR=str(runtime),
            PG_GPU_TEST_CHILD="1",
        )
        environment.pop("WAYLAND_DISPLAY", None)
        environment["PG_GPU_TEST_LIBRARY_PATH"] = environment["LD_LIBRARY_PATH"]
        read_fd, write_fd = os.pipe()
        display_server = None
        with (root / "xvfb.log").open("w") as log:
            try:
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
                result = subprocess.run(
                    [sys.executable, *sys.orig_argv[1:]], env=environment,
                )
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
