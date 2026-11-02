"""Exercise gesture undo boundaries in a native Blender window."""

from contextlib import contextmanager
from importlib.resources import files
import json
import os
from pathlib import Path
import selectors
import signal
import subprocess
import sys
import tempfile
import unittest
import zipfile


@contextmanager
def virtual_display(resources, root, env):
    if sys.platform != "linux":
        yield
        return
    fixture = Path(str(resources / "xvfb")).resolve()
    library_dir = fixture / "usr/lib/x86_64-linux-gnu"
    library_path = str(library_dir)
    if env.get("LD_LIBRARY_PATH"):
        library_path += os.pathsep + env["LD_LIBRARY_PATH"]
    runtime = root / "xdg-runtime"
    runtime.mkdir(mode=0o700)
    driver_path = str(library_dir / "dri")
    child_env = dict(
        env,
        LD_LIBRARY_PATH=library_path,
        LIBGL_ALWAYS_SOFTWARE="1",
        GALLIUM_DRIVER="llvmpipe",
        LIBGL_DRIVERS_PATH=driver_path,
    )
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
                DISPLAY=":" + display,
                XDG_RUNTIME_DIR=str(runtime),
                LD_LIBRARY_PATH=library_path,
                LIBGL_ALWAYS_SOFTWARE="1",
                GALLIUM_DRIVER="llvmpipe",
                LIBGL_DRIVERS_PATH=driver_path,
            )
            env.pop("WAYLAND_DISPLAY", None)
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


class GestureUndoGuiTests(unittest.TestCase):
    def test_gesture_pushes_independent_undo_states(self):
        resources = files("tests.perceptual_grade_blender")
        blender_root = Path(str(resources / "blender")).resolve()
        blender = next(
            (path for path in (blender_root / "Blender.app/Contents/MacOS/Blender",
                               blender_root / "blender") if path.is_file()),
            None,
        )
        self.assertIsNotNone(blender, "Pinned native Blender artifact missing")
        runner = Path(str(resources / "gesture_undo_runner.py")).resolve()
        with tempfile.TemporaryDirectory(prefix="pg-gesture-undo-") as directory:
            root = Path(directory)
            repository = root / "repository"
            package = repository / "perceptual_grade"
            package.mkdir(parents=True)
            with zipfile.ZipFile(str(resources / "extension.zip")) as archive:
                archive.extractall(package)

            env = {
                key: value
                for key, value in os.environ.items()
                if key not in {
                    "PYTHONPATH",
                    "PYTHONHOME",
                    "BLENDER_USER_SCRIPTS",
                    "BLENDER_SYSTEM_SCRIPTS",
                    "BLENDER_SYSTEM_PYTHON",
                }
            }
            env.update(
                BLENDER_USER_CONFIG=str(root / "config"),
                BLENDER_USER_EXTENSIONS=str(root / "extensions"),
                OPENBLAS_NUM_THREADS="1",
                OMP_NUM_THREADS="1",
            )
            with virtual_display(resources, root, env):
                report = root / "report.json"
                command = [
                    str(blender),
                    "--factory-startup",
                    "--disable-autoexec",
                    "--window-geometry",
                    "0",
                    "0",
                    "1280",
                    "960",
                    "--python-exit-code",
                    "1",
                    "--python",
                    str(runner),
                    "--",
                    str(repository),
                    str(report),
                ]
                process = subprocess.Popen(
                    command,
                    cwd=root,
                    env=env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    start_new_session=True,
                )
                try:
                    output, _ = process.communicate(timeout=300)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    output, _ = process.communicate(timeout=10)
                    self.fail("Native gesture undo test timed out\n" + output[-16000:])
                data = json.loads(report.read_text()) if report.exists() else {}
                details = output[-16000:] + "\n" + json.dumps(data, indent=2)
                if (root / "xvfb.log").exists():
                    details += "\nXvfb:\n" + (root / "xvfb.log").read_text()[-8000:]
                self.assertEqual(process.returncode, 0, details)
                self.assertTrue(data.get("passed"), details)
                self.assertEqual(data.get("push_results"), [True, True, True], details)
                self.assertEqual(data.get("undo_states"), [
                    {"grade": "present", "exposure": 0.0},
                    {"grade": "present", "exposure": 0.625},
                    {"grade": "present", "exposure": 0.0},
                ], details)


if __name__ == "__main__":
    unittest.main()
