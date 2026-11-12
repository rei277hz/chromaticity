"""Native GUI fixtures shared by Blender acceptance tests."""

from contextlib import contextmanager
import os
from pathlib import Path
import selectors
import subprocess
import sys


def configure_software_graphics(resources, root, env):
    if sys.platform != "linux":
        return
    fixture = Path(str(resources / "xvfb")).resolve()
    library_dir = fixture / "usr/lib/x86_64-linux-gnu"
    library_path = str(library_dir)
    if env.get("LD_LIBRARY_PATH"):
        library_path += os.pathsep + env["LD_LIBRARY_PATH"]
    runtime = root / "xdg-runtime"
    runtime.mkdir(mode=0o700, exist_ok=True)
    env.update(
        XDG_RUNTIME_DIR=str(runtime),
        LD_LIBRARY_PATH=library_path,
        LIBGL_ALWAYS_SOFTWARE="1",
        GALLIUM_DRIVER="llvmpipe",
        LIBGL_DRIVERS_PATH=str(library_dir / "dri"),
    )
    env.pop("WAYLAND_DISPLAY", None)


@contextmanager
def virtual_display(resources, root, env):
    if sys.platform != "linux":
        yield
        return
    fixture = Path(str(resources / "xvfb")).resolve()
    child_env = dict(env)
    configure_software_graphics(resources, root, child_env)
    read_fd, write_fd = os.pipe()
    process = None
    with (root / "xvfb.log").open("w") as log:
        try:
            process = subprocess.Popen(
                [
                    str(fixture / "usr/bin/Xvfb"),
                    "-displayfd",
                    str(write_fd),
                    "-screen",
                    "0",
                    "1280x960x24",
                    "-nolisten",
                    "tcp",
                    "-ac",
                    "+iglx",
                    "-xkbdir",
                    str(fixture / "usr/share/X11/xkb"),
                ],
                cwd=fixture,
                env=child_env,
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
                raise RuntimeError("Xvfb startup failed: " + (root / "xvfb.log").read_text())
            env.update(
                child_env,
                DISPLAY=":" + display,
            )
            yield
        finally:
            os.close(read_fd)
            if write_fd is not None:
                os.close(write_fd)
            if process is not None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=10)

