"""Lifecycle-owned helper lane for isolated Bake and scope captures."""

# pg-book: technical-report/en#next-policy.bake

from concurrent.futures import CancelledError
from pathlib import Path
from threading import current_thread, main_thread
from time import perf_counter_ns

from .execution import HelperRuntime


class CaptureHelperBackend:
    """Create capture jobs bound to the runtime that accepted each request."""

    def __init__(self):
        self.runtime = None
        self.probe = None

    def _ensure_runtime(self):
        _require_main_thread()
        if self.runtime is not None:
            if not self.runtime.physical_terminal():
                return
            self.runtime.close()
            self.runtime = None
            self.probe = None
        self.runtime = HelperRuntime(
            package=Path(__file__).resolve().parent.parent,
            worker_module="runtime.capture_worker",
            role="bake",
        )
        self.probe = self.runtime.start_probe()

    def create_job(self, inputs, *, operation="bake", profile=False):
        _require_main_thread()
        previous = self.runtime
        started = perf_counter_ns() if profile else None
        self._ensure_runtime()
        job = CaptureHelperJob(self.runtime, self.probe, inputs, operation, profile=profile)
        if profile:
            job.helper_reused = self.runtime is previous and self.runtime.gpu_ready
            job.probe_started = perf_counter_ns()
            job.record("helper_start", started, job.probe_started)
        return job

    def close(self):
        _require_main_thread()
        if self.runtime is None:
            return
        self.runtime.close()
        if not self.runtime.physical_terminal():
            raise RuntimeError("Capture helper has not physically retired")
        self.probe = self.runtime = None


class CaptureHelperJob:
    def __init__(self, runtime, probe, inputs, operation="bake", *, profile=False):
        self.runtime = runtime
        self.probe = probe
        self.inputs = dict(inputs)
        self.operation = operation
        self.handle = None
        self.cancelled = False
        self.timings = [] if profile else None
        self.helper_reused = None
        self.probe_started = None
        self.submit_started = None

    def record(self, stage, started, finished):
        self.timings.append((stage, started, finished, "host"))

    def advance(self):
        _require_main_thread()
        if self.cancelled and self.handle is None:
            raise CancelledError("Capture was cancelled before helper submission")
        if self.handle is None:
            if not self.probe.poll():
                return None
            self.probe.result()
            if self.timings is None:
                self.handle = self.runtime.submit(self.operation, self.inputs)
            else:
                self.submit_started = perf_counter_ns()
                self.record("helper_probe_wait", self.probe_started, self.submit_started)
                self.handle = self.runtime.submit(self.operation, self.inputs, profile=True)
                self.record("helper_submit", self.submit_started, perf_counter_ns())
        if not self.handle.poll():
            return None
        if self.timings is not None:
            self.record("helper_round_trip", self.submit_started, perf_counter_ns())
            self.timings.extend(self.handle.timings)
        return self.handle.result()

    def cancel(self):
        _require_main_thread()
        self.cancelled = True
        if self.handle is not None:
            self.handle.cancel()

    def retired(self):
        _require_main_thread()
        return self.handle is None or self.handle.poll()


def _require_main_thread():
    if current_thread() is not main_thread():
        raise RuntimeError("Capture helper transport must be polled on Blender's main thread")


__all__ = ("CaptureHelperBackend", "CaptureHelperJob")
