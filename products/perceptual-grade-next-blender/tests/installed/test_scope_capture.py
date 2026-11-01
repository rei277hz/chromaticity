"""Installed GUI acceptance for actual Next viewport pixel capture."""

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
def _virtual_display(resources, root, environment):
    if sys.platform != "linux":
        yield
        return
    fixture = Path(str(resources / "xvfb")).resolve()
    abi = Path(str(resources / "bpy_abi")).resolve()
    runtime = root / "xdg-runtime"
    runtime.mkdir(mode=0o700)
    library_path = os.pathsep.join((
        str(fixture / "usr/lib/x86_64-linux-gnu"),
        str(abi / "usr/lib/x86_64-linux-gnu"),
    ))
    child_environment = dict(
        environment,
        LD_LIBRARY_PATH=library_path,
        LIBGL_ALWAYS_SOFTWARE="1",
        LIBGL_DRIVERS_PATH=str(fixture / "usr/lib/x86_64-linux-gnu/dri"),
        GALLIUM_DRIVER="llvmpipe",
    )
    read_fd, write_fd = os.pipe()
    with (root / "xvfb.log").open("w") as log:
        process = None
        try:
            process = subprocess.Popen(
                [str(fixture / "usr/bin/Xvfb"), "-displayfd", str(write_fd),
                 "-screen", "0", "1280x960x24", "-nolisten", "tcp", "-ac",
                 "+extension", "GLX", "+render", "-noreset",
                 "-xkbdir", str(fixture / "usr/share/X11/xkb")],
                cwd=fixture,
                env=child_environment,
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
            environment.update(
                DISPLAY=":" + display,
                XDG_RUNTIME_DIR=str(runtime),
                LIBGL_ALWAYS_SOFTWARE="1",
                LIBGL_DRIVERS_PATH=str(fixture / "usr/lib/x86_64-linux-gnu/dri"),
                GALLIUM_DRIVER="llvmpipe",
                LD_LIBRARY_PATH=library_path,
            )
            environment.pop("WAYLAND_DISPLAY", None)
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


class InstalledScopeCaptureTests(unittest.TestCase):
    def test_visible_grade_capture_uses_native_viewport_pixels(self):
        resources = files("tests.installed")
        blender = Path(str(resources / "blender/blender")).resolve()
        with tempfile.TemporaryDirectory(prefix="pg-next-scope-capture-") as directory:
            root = Path(directory)
            repository = root / "repository"
            package = repository / "perceptual_grade"
            package.mkdir(parents=True)
            with zipfile.ZipFile(str(resources / "extension.zip")) as archive:
                archive.extractall(package)
            environment = {
                key: value for key, value in os.environ.items()
                if key not in {
                    "PYTHONPATH", "PYTHONHOME", "BLENDER_USER_SCRIPTS",
                    "BLENDER_SYSTEM_SCRIPTS", "BLENDER_SYSTEM_PYTHON",
                }
            }
            environment.update(
                BLENDER_USER_CONFIG=str(root / "config"),
                BLENDER_USER_EXTENSIONS=str(root / "extensions"),
                OPENBLAS_NUM_THREADS="1",
                OMP_NUM_THREADS="1",
            )
            report = root / "report.json"
            with _virtual_display(resources, root, environment):
                process = subprocess.Popen(
                    [str(blender), "--factory-startup", "--disable-autoexec",
                     "--enable-event-simulate", "--window-geometry", "0", "0",
                     "1280", "960", "--python-exit-code", "1", "--python",
                     str(resources / "scope_capture_runner.py"), "--",
                     str(repository), str(report)],
                    cwd=root,
                    env=environment,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    start_new_session=True,
                )
                try:
                    output, _ = process.communicate(timeout=240)
                except subprocess.TimeoutExpired:
                    for action in (signal.SIGCONT, signal.SIGKILL):
                        try:
                            os.killpg(process.pid, action)
                        except ProcessLookupError:
                            pass
                    output, _ = process.communicate(timeout=10)
                    self.fail("Installed scope capture timed out\n" + output[-16000:])
                finally:
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
            data = json.loads(report.read_text()) if report.exists() else {}
            detail = output[-16000:] + "\n" + json.dumps(data, indent=2)
            self.assertEqual(process.returncode, 0, detail)
            self.assertTrue(data.get("passed"), detail)
            self.assertTrue(data.get("capture_started"), detail)
            self.assertTrue(data.get("graph_unchanged"), detail)
            self.assertTrue(data.get("viewport_unchanged"), detail)
            self.assertTrue(data.get("render_result_unchanged"), detail)
            self.assertGreater(data.get("sample_count", 0), 0, detail)
            self.assertEqual(data.get("chart_sizes", {}).get("histogram_bins"), 64, detail)
            self.assertEqual(data.get("chart_sizes", {}).get("waveform"), [128, 64], detail)
            self.assertEqual(data.get("chart_sizes", {}).get("vectorscope"), 64, detail)
            self.assertTrue(all(
                count == data["sample_count"]
                for count in data.get("chart_counts", {}).values()
            ), detail)
            self.assertEqual(data.get("selected_pages"),
                             ["histogram", "waveform", "vectorscope"], detail)
            self.assertTrue(data.get("page_switch_kept_display"), detail)
            self.assertTrue(data.get("overlay_handler_registered"), detail)
            stopped = data.get("stopped_frame_capture", {})
            self.assertEqual(stopped.get("frame"), 50, detail)
            self.assertGreater(stopped.get("request", 0),
                               stopped.get("prior_request", 0), detail)
            self.assertTrue(stopped.get("new_visual"), detail)
            playback = data.get("playback", {})
            self.assertGreaterEqual(len(playback.get("frames", [])), 2, detail)
            self.assertGreater(playback.get("resumed_request", 0),
                               playback.get("prior_request", 0), detail)
            self.assertTrue(playback.get("held_visual_during_playback"), detail)
            self.assertTrue(playback.get("no_capture_during_playback"), detail)
            self.assertTrue(playback.get("new_visual_after_stop"), detail)
            self.assertTrue(playback.get("animated_input_changed_pixels"), detail)
            self.assertTrue(all(item.get("completed") for item in
                                data["capture_observations"]), detail)
            self.assertEqual(data["capture_observations"][-1]["frame"],
                             playback.get("stopped_frame"), detail)
            self.assertFalse(any(item["playing"]
                                 for item in data["capture_observations"]), detail)
            self.assertTrue(all(value == value for value in data["minimum"]
                                + data["mean"] + data["maximum"]), detail)
            print("Installed Next viewport capture:", json.dumps(data, sort_keys=True), flush=True)


if __name__ == "__main__":
    unittest.main()
