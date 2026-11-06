"""Drag recording remains useful under bursts and harmless under failures."""

import importlib
from importlib.resources import files
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import zipfile


class DragTraceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix="grade-drag-trace-package-")
        root = Path(cls.directory.name)
        package = root / "grade_drag_trace_test"
        package.mkdir()
        with zipfile.ZipFile(files("tests.perceptual_grade_blender") / "extension.zip") as archive:
            archive.extractall(package)
        sys.path.insert(0, str(root))
        cls.module = importlib.import_module("grade_drag_trace_test.runtime.drag_trace")

    @classmethod
    def tearDownClass(cls):
        sys.path.remove(cls.directory.name)
        for name in tuple(sys.modules):
            if name == "grade_drag_trace_test" or name.startswith("grade_drag_trace_test."):
                del sys.modules[name]
        cls.directory.cleanup()

    def recorder(self, **kwargs):
        directory = tempfile.TemporaryDirectory(prefix="grade-drag-trace-")
        self.addCleanup(directory.cleanup)
        recorder = self.module.Recorder(directory.name, **kwargs)
        self.addCleanup(recorder.close)
        return recorder

    def rows(self, recorder):
        return [json.loads(line) for line in recorder.path.read_text().splitlines()]

    def test_threaded_events_preserve_order_and_correlated_snapshots(self):
        recorder = self.recorder(metadata={"workspace": "Shading"})
        start = threading.Barrier(5)

        def emit(producer):
            start.wait()
            for index in range(100):
                fields = {"signature": f"{producer}:{index}", "values": [index]}
                recorder.emit("preparation", producer=producer, snapshot=fields)
                fields["values"][0] = -1

        threads = [threading.Thread(target=emit, args=(index,)) for index in range(4)]
        for thread in threads:
            thread.start()
        start.wait()
        for thread in threads:
            thread.join()
        self.assertIsNone(recorder.close())
        rows = self.rows(recorder)
        self.assertEqual([row["seq"] for row in rows], list(range(402)))
        self.assertEqual(rows[0]["fields"]["metadata"], {"workspace": "Shading"})
        self.assertEqual(rows[-1]["fields"]["accepted"], 400)
        self.assertEqual(rows[-1]["fields"]["written"], 400)
        self.assertEqual(rows[-1]["fields"]["dropped"], 0)
        for producer in range(4):
            events = [row for row in rows if row["event"] == "preparation"
                      and row["fields"]["producer"] == producer]
            self.assertEqual([row["fields"]["snapshot"]["signature"] for row in events],
                             [f"{producer}:{index}" for index in range(100)])
            self.assertEqual([row["fields"]["snapshot"]["values"] for row in events],
                             [[index] for index in range(100)])

    def test_overflow_does_not_wait_for_writer_and_is_explicit_at_stop(self):
        recorder = self.recorder(capacity=2)
        entered, release, producer_done = (threading.Event() for _ in range(3))
        original_write = recorder._write

        def blocked_write(row):
            if row["event"] == "blocked":
                entered.set()
                if not release.wait(5):
                    raise RuntimeError("Test did not release the writer")
            original_write(row)

        def burst():
            for index in range(9):
                recorder.emit("value", index=index)
            producer_done.set()

        with patch.object(recorder, "_write", side_effect=blocked_write):
            recorder.emit("blocked")
            self.assertTrue(entered.wait(5))
            producer = threading.Thread(target=burst)
            producer.start()
            try:
                self.assertTrue(producer_done.wait(1), "Diagnostic queue blocked a producer")
                self.assertEqual(recorder.dropped, 7)
            finally:
                release.set()
                producer.join(5)
                recorder.close()
        rows = self.rows(recorder)
        self.assertEqual(rows[-1]["fields"]["accepted"], 3)
        self.assertEqual(rows[-1]["fields"]["written"], 3)
        self.assertEqual(rows[-1]["fields"]["dropped"], 7)
        self.assertEqual(rows[-1]["seq"], 11)

    def test_writer_failure_disables_diagnostics_without_escaping_to_caller(self):
        recorder = self.recorder()
        with patch.object(recorder, "_write", side_effect=OSError("disk full")):
            recorder.emit("property_callback", value=1.25)
            self.assertIn("disk full", recorder.close())
        recorder.emit("ignored", value=2.5)
        self.assertIn("disk full", recorder.error)
        self.assertIn("disk full", recorder.close())
        self.assertFalse(recorder._thread.is_alive())

    def test_invalid_payload_never_reaches_background_writer(self):
        recorder = self.recorder()
        recorder.emit("callback", host_object=object())
        self.assertIn("plain JSON data", recorder.close())
        rows = self.rows(recorder)
        self.assertEqual([row["event"] for row in rows], ["session_start", "session_stop"])
        self.assertIn("plain JSON data", rows[-1]["fields"]["error"])

    def test_batches_flush_before_stop_and_close_is_idempotent(self):
        recorder = self.recorder(flush_interval=0.02)
        recorder.emit("gesture_release", token=17)
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline and len(self.rows(recorder)) < 2:
            time.sleep(0.01)
        self.assertEqual(self.rows(recorder)[1]["event"], "gesture_release")
        self.assertIsNone(recorder.close())
        before = recorder.path.read_bytes()
        recorder.emit("after_stop")
        self.assertIsNone(recorder.close())
        self.assertEqual(recorder.path.read_bytes(), before)

    def test_new_capture_uses_a_different_file_and_session(self):
        first = self.recorder()
        second = self.module.Recorder(first.path.parent)
        self.addCleanup(second.close)
        self.assertNotEqual(first.path, second.path)
        self.assertNotEqual(first.session_id, second.session_id)
        self.assertTrue(first.path.is_absolute())


if __name__ == "__main__":
    unittest.main()
