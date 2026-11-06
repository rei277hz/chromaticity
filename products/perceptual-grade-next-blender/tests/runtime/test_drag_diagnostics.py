"""Drag observations do not acquire image buffers or inspect RNA off-thread."""

import importlib
from importlib.resources import files
from dataclasses import make_dataclass
import json
from pathlib import Path
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
import zipfile


class RecorderSpy:
    error = None

    def __init__(self):
        self.events = []

    def emit(self, event, **fields):
        # Exercise the recorder's plain-data boundary without a writer thread.
        self.events.append((event, json.loads(json.dumps(fields, allow_nan=False))))


class DragDiagnosticsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix="grade-drag-diagnostics-package-")
        root = Path(cls.directory.name)
        package = root / "grade_drag_diagnostics_test"
        package.mkdir()
        with zipfile.ZipFile(files("tests.perceptual_grade_blender") / "extension.zip") as archive:
            archive.extractall(package)
        sys.path.insert(0, str(root))
        cls.module = importlib.import_module("grade_drag_diagnostics_test.runtime.drag_diagnostics")

    @classmethod
    def tearDownClass(cls):
        sys.path.remove(cls.directory.name)
        for name in tuple(sys.modules):
            if name == "grade_drag_diagnostics_test" or name.startswith("grade_drag_diagnostics_test."):
                del sys.modules[name]
        cls.directory.cleanup()

    def capture(self):
        capture = self.module.Capture.__new__(self.module.Capture)
        capture.closed = False
        capture.recorder = RecorderSpy()
        capture.known_nodes = set()
        capture.last_context = None
        capture.last_heartbeat = None
        capture.nodes = SimpleNamespace(_node_stores={}, _grade_resources=None)
        return capture

    def test_viewer_heartbeat_does_not_acquire_native_image_buffer(self):
        accesses = []

        class ViewerImage:
            name = "Viewer Node"
            type = "COMPOSITING"
            source = "VIEWER"

            def as_pointer(self):
                return 57

            @property
            def size(self):
                accesses.append("size")
                raise AssertionError("Image.size would acquire the native host buffer")

            @property
            def pixels(self):
                accesses.append("pixels")
                raise AssertionError("Image.pixels would download GPU data")

        capture = self.capture()
        area = SimpleNamespace(
            type="IMAGE_EDITOR", as_pointer=lambda: 71,
            spaces=SimpleNamespace(active=SimpleNamespace(image=ViewerImage())),
            regions=[SimpleNamespace(type="WINDOW", width=640, height=480)],
        )
        render = SimpleNamespace(
            engine="BLENDER_EEVEE", compositor_device="GPU", compositor_precision="AUTO",
            resolution_x=1920, resolution_y=1080, resolution_percentage=100,
        )
        window = SimpleNamespace(
            as_pointer=lambda: 89, workspace=SimpleNamespace(name="Compositing"),
            modal_operators=[],
            screen=SimpleNamespace(areas=[area]),
            scene=SimpleNamespace(as_pointer=lambda: 97, render=render),
        )
        capture.bpy = SimpleNamespace(
            context=SimpleNamespace(window_manager=SimpleNamespace(windows=[window])),
            app=SimpleNamespace(timers=SimpleNamespace(is_registered=lambda callback: False)),
        )
        capture.nodes._gesture_state = make_dataclass("GestureState", [])()
        capture.nodes._gesture_router_tick = lambda: None
        capture.nodes._preparation_tick = lambda: None

        capture.observe_heartbeat()

        self.assertEqual(accesses, [])
        events = dict(capture.recorder.events)
        self.assertNotIn("diagnostic_error", events)
        self.assertIn("heartbeat", events)
        recorded_area = events["context"]["windows"][0]["areas"][0]
        self.assertEqual(recorded_area["image"]["id"], 57)
        self.assertIsNone(recorded_area["image"]["size"])
        self.assertEqual(recorded_area["display_region_size"], [640, 480])

    def test_worker_observations_keep_plain_state_without_touching_rna(self):
        accesses = []

        class ForbiddenRNA:
            def __getattr__(self, name):
                accesses.append(name)
                raise AssertionError("Worker inspected RNA: " + name)

        capture = self.capture()
        rna = ForbiddenRNA()
        capture.bpy = rna
        capture.nodes._node_stores[43] = {
            "node": rna,
            "source": object(),
            "state": SimpleNamespace(
                desired_signature="latest", applied_signature="previous",
                applied_quality="full", desired_preparation_signature="prepare-latest",
                gesture_active=True, error=None,
            ),
        }
        failures = []

        def observe():
            try:
                capture.property_callback("linear", rna, rna)
                capture.property_skip("linear", rna, "syncing")
                capture.evaluation("compositor_pre")
            except BaseException as error:
                failures.append(error)

        worker = threading.Thread(target=observe)
        worker.start()
        worker.join(5)

        self.assertFalse(worker.is_alive())
        self.assertEqual(failures, [])
        self.assertEqual(accesses, [])
        events = dict(capture.recorder.events)
        self.assertNotIn("diagnostic_error", events)
        for name in ("property_callback", "property_skipped"):
            self.assertIn("omitted", events[name]["observation"])
            self.assertNotIn("settings_id", events[name])
        evaluation = events["compositor_pre"]["nodes"][0]
        self.assertEqual(evaluation["node_id"], 43)
        self.assertEqual(evaluation["state"]["desired_signature"], "latest")
        self.assertEqual(evaluation["state"]["applied_signature"], "previous")

    def test_invalidated_rna_is_diagnostic_and_does_not_interrupt_later_observations(self):
        class RemovedSettings:
            @property
            def id_data(self):
                raise ReferenceError("Grade was removed")

        capture = self.capture()
        capture.property_callback("linear", RemovedSettings(), None)
        capture.evaluation("compositor_post")

        events = dict(capture.recorder.events)
        self.assertEqual(events["diagnostic_error"]["operation"], "property_callback")
        self.assertIn("Grade was removed", events["diagnostic_error"]["error"])
        self.assertIn("compositor_post", events)
        self.assertIsNone(capture.recorder.error)


if __name__ == "__main__":
    unittest.main()
