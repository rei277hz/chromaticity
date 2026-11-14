"""Completed and interrupted native-test timings without a Blender process."""

from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from . import timing


class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class TimingTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="pg-installed-timing-")
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "report.json"
        self.clock = Clock()

    def recorder(self, sections=("startup", "work", "teardown")):
        return timing.TimingRecorder(
            self.path, sections, metadata={"registered": True}, clock=self.clock,
        )

    def report(self):
        return timing.read_report(self.path)

    def test_sections_account_for_wall_time_without_adding_nested_operations(self):
        recorder = self.recorder()
        initial = self.report()["timings"]
        self.assertEqual([row["status"] for row in initial["sections"]],
                         ["running", "unreached", "unreached"])
        self.assertIsNone(initial["sections"][1]["started_monotonic"])
        self.assertIsNone(initial["sections"][1]["seconds"])
        self.clock.advance(2)
        recorder.start_section("work")
        with recorder.operation("drain", "runner.py:25"):
            self.clock.advance(1)
            with recorder.operation("build", "runner.py:30"):
                self.clock.advance(3)
            self.clock.advance(1)
        recorder.start_section("teardown")
        self.clock.advance(1)
        recorder.complete({"registered": False})
        data = self.report()
        measured = data["timings"]
        self.assertFalse(data["registered"])
        self.assertTrue(measured["complete"])
        self.assertEqual(measured["status"], "complete")
        self.assertEqual([row["seconds"] for row in measured["sections"]], [2, 5, 1])
        self.assertEqual(measured["runner_seconds"], 8)
        self.assertEqual(sum(row["seconds"] for row in measured["sections"]), 8)
        outer, inner = measured["operations"]
        self.assertEqual((outer["seconds"], inner["seconds"]), (5, 3))
        self.assertIsNone(outer["parent_id"])
        self.assertEqual(inner["parent_id"], outer["id"])
        self.assertEqual(inner["section"], "work")

    def test_operation_start_survives_until_a_timeout_without_an_end_checkpoint(self):
        recorder = self.recorder()
        self.clock.advance(4)
        recorder.start_section("work")
        with recorder.operation("preparation drain", "runner.py:42"):
            # Keep the file snapshot taken before the operation's finalizer.
            checkpoint = self.report()
        measured = checkpoint["timings"]
        self.assertEqual(measured["operations"][0]["status"], "running")
        self.assertEqual(measured["operations"][0]["seconds"], 0)
        timing.add_harness_timings(
            checkpoint, setup_seconds=2, process_seconds=542, total_seconds=544,
            observed_monotonic=640, interrupted=True,
        )
        self.assertFalse(measured["complete"])
        self.assertEqual(measured["status"], "interrupted")
        self.assertEqual(measured["runner_seconds"], 540)
        startup, active, unreached = measured["sections"]
        self.assertEqual((startup["seconds"], startup["status"]), (4, "complete"))
        self.assertEqual((active["seconds"], active["status"]), (536, "interrupted"))
        self.assertEqual(unreached["status"], "unreached")
        operation, = measured["operations"]
        self.assertEqual(operation["seconds"], 536)
        self.assertEqual(operation["duration_source"], "harness_process_end")
        self.assertEqual(measured["unreported_seconds"], 536)
        self.assertNotIn("blender_post_runner_seconds", measured)
        self.assertEqual(measured["blender_pre_runner_seconds"], 2)
        rendered = timing.format_timing_report(measured)
        self.assertIn("work: 536.000 [interrupted]", rendered)
        self.assertIn("interrupted: runner.py:42 (536.000)", rendered)
        self.assertIn("teardown: not reached", rendered)

    def test_completed_report_keeps_its_measurement_after_process_exit(self):
        recorder = self.recorder(("work",))
        self.clock.advance(3)
        recorder.complete()
        data = self.report()
        measured = timing.add_harness_timings(
            data, setup_seconds=2, process_seconds=5, total_seconds=7,
            observed_monotonic=104, interrupted=True,
        )
        self.assertEqual(measured["runner_seconds"], 3)
        self.assertEqual(measured["finished_monotonic"], 103)
        self.assertEqual(measured["status"], "complete")
        self.assertEqual(measured["blender_pre_runner_seconds"], 1)
        self.assertEqual(measured["blender_post_runner_seconds"], 1)
        self.assertEqual(measured["blender_pre_runner_seconds"]
                         + measured["runner_seconds"]
                         + measured["blender_post_runner_seconds"],
                         measured["blender_process_seconds"])
        self.assertNotIn("unreported_seconds", measured)
        self.assertNotIn("blender_unattributed_seconds", measured)

    def test_exception_records_finished_failure_and_preserves_the_exception(self):
        recorder = self.recorder(("work",))
        failure = RuntimeError("deliberate failed recovery")
        with self.assertRaises(RuntimeError) as raised:
            with recorder.operation("recovery"):
                self.clock.advance(2)
                raise failure
        self.assertIs(raised.exception, failure)
        row, = self.report()["timings"]["operations"]
        self.assertEqual(row["status"], "error")
        self.assertEqual(row["seconds"], 2)
        self.assertIn("deliberate failed recovery", row["error"])
        self.assertRegex(row["callsite"], r"test_timing\.py:\d+")
        recorder.complete()

    def test_concurrent_operations_have_independent_parent_stacks(self):
        recorder = self.recorder(("work",))
        failures = []

        def worker():
            try:
                with recorder.operation("worker join"):
                    with recorder.operation("worker child"):
                        recorder.checkpoint()
            except BaseException as error:
                failures.append(error)

        with recorder.operation("main wait"):
            thread = threading.Thread(target=worker, name="timing-worker")
            thread.start()
            thread.join(timeout=10)
            self.assertFalse(thread.is_alive())
        self.assertFalse(failures, failures)
        recorder.complete()
        main, worker_row, child = self.report()["timings"]["operations"]
        self.assertIsNone(main["parent_id"])
        self.assertIsNone(worker_row["parent_id"])
        self.assertEqual(child["parent_id"], worker_row["id"])
        self.assertNotEqual(worker_row["thread_id"], main["thread_id"])
        self.assertEqual(worker_row["thread"], "timing-worker")

    def test_sync_decorator_preserves_return_value_and_caller(self):
        recorder = self.recorder(("work",))

        @recorder.timed("sample operation")
        def sample(value):
            self.clock.advance(1)
            return value + 2

        self.assertEqual(sample(3), 5)
        self.assertEqual(sample.__name__, "sample")
        row, = self.report()["timings"]["operations"]
        self.assertEqual(row["name"], "sample operation")
        self.assertEqual(row["seconds"], 1)
        self.assertRegex(row["callsite"], r"test_timing\.py:\d+")

    def test_failed_atomic_publication_retains_previous_valid_report(self):
        self.recorder()
        before = self.path.read_bytes()
        with patch.object(timing.os, "replace", side_effect=OSError("replace failed")):
            with self.assertRaisesRegex(OSError, "replace failed"):
                timing.write_report(self.path, {"changed": True})
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(tuple(self.path.parent.iterdir()), (self.path,))

    def test_checkpoint_updates_active_duration_without_finishing_the_operation(self):
        recorder = self.recorder(("work",))
        with recorder.operation("wait"):
            self.clock.advance(4)
            recorder.checkpoint({"registered": False})
            data = self.report()
            self.assertFalse(data["registered"])
            row, = data["timings"]["operations"]
            self.assertEqual(row["seconds"], 4)
            self.assertEqual(row["status"], "running")
            self.assertIsNone(row["finished_monotonic"])
            with self.assertRaisesRegex(RuntimeError, "operations"):
                recorder.complete()
        recorder.complete()
        self.clock.advance(4)
        recorder.checkpoint()
        self.assertEqual(self.report()["timings"]["runner_seconds"], 4)

    def test_missing_and_invalid_reports_are_reported_as_absent(self):
        self.assertIsNone(timing.read_report(self.path))
        self.path.write_text("not json")
        self.assertIsNone(timing.read_report(self.path))
        self.path.write_text("[]")
        self.assertIsNone(timing.read_report(self.path))
        self.assertEqual(timing.format_timing_report(None),
                         "No timing report was produced by Blender.")
        measured = timing.add_harness_timings(
            None, setup_seconds=3, process_seconds=540, total_seconds=543,
            observed_monotonic=600, interrupted=True,
        )
        rendered = timing.format_timing_report(measured)
        self.assertIn("No timing report was produced by Blender.", rendered)
        self.assertIn("blender_process_seconds: 540.000", rendered)
        self.assertIn("harness_setup_seconds: 3.000", rendered)
        self.assertIn("test_total_seconds: 543.000", rendered)


if __name__ == "__main__":
    unittest.main()
