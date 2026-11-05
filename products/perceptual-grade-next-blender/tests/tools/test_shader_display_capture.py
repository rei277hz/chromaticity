import ctypes
from contextlib import nullcontext
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import zipfile

from tools.perceptual_grade.reports import shader_display_capture as capture
from tools.perceptual_grade.reports import shader_display_timing as timing


class _Function:
    def __init__(self, callback):
        self.callback = callback

    def __call__(self, *args):
        return self.callback(*args)


class _FakeX11:
    def __init__(self, image=99):
        self.image = image
        self.calls = []
        self.closed = []
        self.XOpenDisplay = _Function(lambda _name: 1)
        self.XCloseDisplay = _Function(lambda display: self.closed.append(display))
        self.XDefaultScreen = _Function(lambda _display: 0)
        self.XRootWindow = _Function(lambda _display, _screen: 55)
        self.XDefaultDepth = _Function(lambda _display, _screen: 24)
        self.XDisplayWidth = _Function(lambda _display, _screen: 1280)
        self.XDisplayHeight = _Function(lambda _display, _screen: 960)
        self.XMatchVisualInfo = _Function(self._match_visual)
        self.XGetImage = _Function(self._get_image)
        self.XGetPixel = _Function(lambda _image, _x, _y: 0xD04020)
        self.XDestroyImage = _Function(lambda image: self.calls.append(("destroy", image)))
        self.XSync = _Function(lambda _display, _discard: None)

    def _match_visual(self, _display, _screen, _depth, _class_id, output):
        visual = ctypes.cast(output, ctypes.POINTER(capture._XVisualInfo)).contents
        visual.red_mask = 0xFF0000
        visual.green_mask = 0x00FF00
        visual.blue_mask = 0x0000FF
        return 1

    def _get_image(self, _display, drawable, x, y, width, height, plane_mask, format_id):
        self.calls.append(("image", drawable, x, y, width, height, plane_mask, format_id))
        return self.image


class ShaderDisplayCaptureTests(unittest.TestCase):
    def test_channel_masks_decode_rgb_independently_of_pixel_byte_order(self):
        pixel = 0xD04020
        self.assertEqual(capture._channel(pixel, 0xFF0000), 208)
        self.assertEqual(capture._channel(pixel, 0x00FF00), 64)
        self.assertEqual(capture._channel(pixel, 0x0000FF), 32)
        self.assertEqual(capture._channel(pixel, 0), 0)
        self.assertEqual(capture._channel(pixel, 0x0000FF),
                         capture._channel(0x2040D0, 0xFF0000))
        self.assertEqual(capture._channel(0x3FF, 0x3FF), 255)
        self.assertEqual(capture._channel(0x200, 0x3FF), 128)

    def test_pixel_average_reads_a_centered_five_by_five_region(self):
        x11 = _FakeX11()
        calls = []

        def pixel(image, x, y):
            calls.append((image, x, y))
            return (x * 10 << 16) | (y * 10 << 8) | 128

        x11.XGetPixel = _Function(pixel)
        self.assertEqual(capture._pixel_average(
            x11, 99, 3, 4, 0xFF0000, 0x00FF00, 0x0000FF,
        ), [30, 40, 128])
        self.assertEqual(calls, [(99, x, y) for y in range(2, 7) for x in range(1, 6)])

    def test_request_geometry_covers_all_five_by_five_rois(self):
        points = [[10, 10], [20, 15], [30, 20], [40, 25]]
        self.assertEqual(capture.validate_capture_request(
            {"enabled": True, "points": points}, 1280, 960,
        ), tuple(map(tuple, points)))
        edges = [[2, 2], [1277, 2], [2, 957], [1277, 957]]
        self.assertEqual(capture.validate_capture_request({"points": edges}, 1280, 960),
                         tuple(map(tuple, edges)))
        for bad_points in (
            [[1, 10], *points[1:]],
            [[10, 1], *points[1:]],
            [[1278, 10], *points[1:]],
            [[10, 958], *points[1:]],
            [[True, 10], *points[1:]],
            [[10.5, 10], *points[1:]],
            [[10, 10]],
        ):
            with self.subTest(points=bad_points), self.assertRaises(ValueError):
                capture.validate_capture_request({"points": bad_points}, 1280, 960)

    def test_capture_loop_records_roi_pixels_request_id_and_capture_geometry(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            request_path = root / "request.json"
            trace_path = root / "trace.jsonl"
            stop_path = root / "stop"
            points = [[10, 10], [20, 15], [30, 20], [40, 25]]
            request_path.write_text(json.dumps({
                "enabled": True, "request_id": "sample-7", "points": points,
            }))
            x11 = _FakeX11()

            def stop_after_sample(_seconds):
                stop_path.touch()

            with patch.object(capture.ctypes, "CDLL", return_value=x11), \
                    patch.object(capture.time, "sleep", side_effect=stop_after_sample):
                capture.capture_loop(root, ":8", request_path, trace_path, stop_path, 5.)
            row = json.loads(trace_path.read_text().strip())

        self.assertEqual(row["request_id"], "sample-7")
        self.assertEqual(row["observed"], [[208, 64, 32]] * 4)
        self.assertIsNone(row["previous_end_ns"])
        self.assertIsInstance(row["start_ns"], int)
        self.assertLessEqual(row["start_ns"], row["end_ns"])
        self.assertIn(("image", 55, 8, 8, 35, 20, 0xFFFFFFFF, 2), x11.calls)
        self.assertEqual(x11.closed, [1])

    def test_bad_capture_bounds_fail_before_xgetimage_and_close_display(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            request = root / "request.json"
            request.write_text(json.dumps({
                "enabled": True, "points": [[1, 10], [20, 15], [30, 20], [40, 25]],
            }))
            x11 = _FakeX11()
            with patch.object(capture.ctypes, "CDLL", return_value=x11):
                with self.assertRaisesRegex(ValueError, "outside"):
                    capture.capture_loop(root, ":8", request, root / "trace", root / "stop")
        self.assertFalse(any(call[0] == "image" for call in x11.calls))
        self.assertEqual(x11.closed, [1])

    def test_failed_xgetimage_is_reported_and_display_is_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            request = root / "request.json"
            request.write_text(json.dumps({
                "enabled": True, "points": [[10, 10], [20, 15], [30, 20], [40, 25]],
            }))
            x11 = _FakeX11(image=None)
            with patch.object(capture.ctypes, "CDLL", return_value=x11):
                with self.assertRaisesRegex(RuntimeError, "XGetImage failed"):
                    capture.capture_loop(root, ":8", request, root / "trace", root / "stop")
        self.assertEqual(x11.closed, [1])

    def test_invalid_capture_interval_is_rejected_before_loading_x11(self):
        for interval in (0., -1., float("inf"), float("nan")):
            with self.subTest(interval=interval), \
                    patch.object(capture.ctypes, "CDLL") as library, \
                    self.assertRaises(ValueError):
                capture.capture_loop("/missing", ":8", "/request", "/trace", "/stop", interval)
            library.assert_not_called()

    def test_missing_native_library_and_unopenable_display_report_errors(self):
        with patch.object(capture.ctypes, "CDLL", side_effect=OSError("missing libX11")):
            with self.assertRaisesRegex(RuntimeError, "bundled X11 dependency.*missing libX11"):
                capture.capture_loop("/missing", ":8", "/request", "/trace", "/stop")
        x11 = _FakeX11()
        x11.XOpenDisplay = _Function(lambda _display: None)
        with patch.object(capture.ctypes, "CDLL", return_value=x11):
            with self.assertRaisesRegex(RuntimeError, "Could not open"):
                capture.capture_loop("/missing", ":8", "/request", "/trace", "/stop")
        self.assertEqual(x11.closed, [])

    def test_fixture_dependencies_are_loaded_globally_before_x11(self):
        libraries = Path("/pinned/usr/lib/x86_64-linux-gnu")
        handles = [object() for _index in range(6)]
        with patch.object(capture.ctypes, "CDLL", side_effect=handles) as loader:
            self.assertEqual(capture._load_x11(libraries), handles)
        self.assertEqual([call.args[0] for call in loader.call_args_list], [
            str(libraries / name) for name in ("libmd.so.0", "libbsd.so.0", "libXau.so.6",
                                             "libXdmcp.so.6", "libxcb.so.1", "libX11.so.6")
        ])
        self.assertTrue(all(call.kwargs == {"mode": ctypes.RTLD_GLOBAL}
                            for call in loader.call_args_list))

    def test_missing_transitive_dependency_names_the_failure_without_host_fallback(self):
        def load(path, **_kwargs):
            if Path(path).name == "libxcb.so.1":
                raise OSError("dependency not found")
            return object()

        with patch.object(capture.ctypes, "CDLL", side_effect=load) as loader:
            with self.assertRaisesRegex(RuntimeError, "libxcb.so.1.*dependency not found"):
                capture._load_x11(Path("/pinned"))
        self.assertNotIn("libX11.so.6", [Path(call.args[0]).name for call in loader.call_args_list])

    def test_disabled_observer_waits_and_does_not_poll_pixels(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            request, stop = root / "request", root / "stop"
            request.write_text(json.dumps({"enabled": False}))
            x11 = _FakeX11()
            with patch.object(capture.ctypes, "CDLL", return_value=x11), \
                    patch.object(capture.time, "sleep", side_effect=lambda _duration: stop.touch()) as sleep:
                capture.capture_loop(root, ":8", request, root / "trace", stop, 5.)
        sleep.assert_called_once_with(.005)
        self.assertFalse(any(call[0] == "image" for call in x11.calls))


class ShaderDisplayControllerTests(unittest.TestCase):
    def profile(self, **changes):
        values = dict(sessions=5, samples=100, drag_duration=3., interval_ms=50.,
                      capture_interval_ms=5., warmup=2., timeout=1800.)
        values.update(changes)
        return SimpleNamespace(**values)

    def test_argument_validation_rejects_invalid_counts_and_timing_values(self):
        timing._validate(self.profile())
        timing._validate(self.profile(interval_ms=0., warmup=0.))
        for values in (
            {"sessions": 0}, {"samples": 0}, {"drag_duration": 0.},
            {"interval_ms": -1.}, {"capture_interval_ms": 0.}, {"warmup": -1.},
            {"timeout": 8.}, {"timeout": float("inf")}, {"interval_ms": float("nan")},
        ):
            with self.subTest(values=values), self.assertRaises(ValueError):
                timing._validate(self.profile(**values))

    def test_completed_session_requires_actual_metadata_and_rejects_drift(self):
        report = {"environment": {}, "profile": {}}
        result = {"completed": True}
        timing._merge_fixture(report, result)
        self.assertFalse(result["completed"])
        self.assertIn("no actual environment", result["orchestrator_errors"][0])
        first = {"completed": True, "environment": {"renderer": "GPU A"},
                 "profile": {"engine": "EEVEE"}}
        timing._merge_fixture(report, first)
        self.assertTrue(first["completed"])
        second = {"completed": True, "environment": {"renderer": "GPU B"},
                  "profile": {"engine": "EEVEE"}}
        timing._merge_fixture(report, second)
        self.assertFalse(second["completed"])
        self.assertIn("changed between timing sessions", second["orchestrator_errors"][0])

    def test_malformed_capture_trace_is_rejected_with_line_identity(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "captures.jsonl"
            path.write_text('{"start_ns": 1, "end_ns": 2}\n{"start_ns":')
            with self.assertRaisesRegex(ValueError, "captures.jsonl:2"):
                timing._read_captures(path)

    def test_sampler_failure_terminates_blender_and_is_retained(self):
        class ImmediateThread:
            def __init__(self, target, **_kwargs):
                self.target = target

            def start(self):
                self.target()

            def join(self, **_kwargs):
                pass

            def is_alive(self):
                return False

        process = SimpleNamespace(pid=777, returncode=None, poll=lambda: None)

        def wait(**_kwargs):
            process.returncode = -9
            return -9

        process.wait = Mock(side_effect=wait)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch.object(timing, "software_display", return_value=nullcontext({"DISPLAY": ":8"})), \
                    patch.object(timing, "capture_loop", side_effect=RuntimeError("native read failed")), \
                    patch.object(timing.threading, "Thread", ImmediateThread), \
                    patch.object(timing.subprocess, "Popen", return_value=process), \
                    patch.object(timing.os, "killpg") as kill:
                result = timing._run_session(self.profile(), root / "blender", root / "runner",
                                             root, root / "repository", root / "session", 0)
            self.assertTrue((root / "session" / "capture-stop").exists())
        kill.assert_called_once_with(777, timing.signal.SIGKILL)
        self.assertFalse(result["completed"])
        self.assertEqual(result["process_returncode"], -9)
        self.assertIn("native read failed", "\n".join(result["orchestrator_errors"]))

    def test_invalid_final_summary_fails_after_report_artifacts_are_written(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            resources = root / "resources"
            resources.mkdir()
            binary = resources / "blender"
            binary.write_bytes(b"fake-native-binary")
            (resources / "shader_display_timing_runner.py").write_text("# fixture")
            with zipfile.ZipFile(resources / "extension.zip", "w") as archive:
                archive.writestr("__init__.py", "# fixture")
            result = {"completed": True, "environment": {"renderer": "test"},
                      "profile": {"engine": "test"}, "samples": [], "drags": [], "captures": []}
            args = self.profile(sessions=1, samples=1, output_dir=root / "output", baseline=None)
            with patch.object(timing, "files", return_value=resources), \
                    patch.object(timing, "blender_binary", return_value=binary), \
                    patch.object(timing, "_source_hashes", return_value={"fixture": "hash"}), \
                    patch.object(timing, "_run_session", return_value=result):
                with self.assertRaisesRegex(RuntimeError, "observations are invalid"):
                    timing.run(args)
            saved = json.loads((args.output_dir / "report.json").read_text())
            self.assertTrue((args.output_dir / "report.md").is_file())
        self.assertFalse(saved["summary"]["valid"])
        self.assertIn("no accepted samples", "\n".join(saved["summary"]["errors"]))


if __name__ == "__main__":
    unittest.main()
