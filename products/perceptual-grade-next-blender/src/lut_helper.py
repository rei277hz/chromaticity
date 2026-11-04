"""Foreground polling adapter for the process-owned Stack GPU baker."""

from concurrent.futures import CancelledError
from pathlib import Path
from threading import current_thread, main_thread

from .blender_runtime.execution.contracts import JobSpec, RuntimeProfile
from .lut_codec import freeze_settings, thaw_prepared


class StackHelperBackend:
    """One lifecycle-owned helper service; construction starts no process."""

    def __init__(self):
        self.owner = None
        self.runtime = None
        self.probe = None

    def _ensure_runtime(self):
        _require_main_thread()
        if self.runtime is not None:
            return
        from .blender_runtime.execution.host import create_runtime
        from .blender_runtime.execution.owner import ExecutionOwner

        self.owner = ExecutionOwner()
        self.runtime = create_runtime(
            self.owner,
            package=Path(__file__).resolve().parent,
            profile=RuntimeProfile(dispatcher="lut_worker"),
        )
        self.probe = self.runtime.join((self.runtime.retry_gpu(),))

    def create_job(self, settings, working_space, progressive):
        _require_main_thread()
        self._ensure_runtime()
        return HelperStackJob(self, settings, working_space, progressive)

    def close(self):
        _require_main_thread()
        if self.runtime is None:
            return
        report = self.runtime.shutdown()
        if not report.clean and not self.runtime.physical_terminal():
            raise RuntimeError("Stack GPU helper has not physically retired")
        self.owner.close()
        self.probe = self.runtime = self.owner = None


class HelperStackJob:
    """A nonblocking one-child join, replaceable by a composed operation later."""

    def __init__(self, backend, settings, working_space, progressive):
        self.backend = backend
        self.inputs = {
            "settings": freeze_settings(settings),
            "working_space": working_space,
            "progressive": bool(progressive),
        }
        self.group = None
        self.preview_emitted = False
        self.cancelled = False

    def advance(self):
        _require_main_thread()
        runtime = self.backend.runtime
        if self.group is None:
            if self.cancelled:
                raise CancelledError("Stack preparation superseded")
            if not self.backend.probe.poll():
                return None
            self.backend.probe.result()
            handle = runtime.submit(JobSpec(
                "stack_lut", self.inputs, lane="gpu", requires_gpu=True,
            ))
            self.group = runtime.join((handle,))
        finished = self.group.poll()
        if (self.inputs["progressive"] and not self.cancelled
                and not self.preview_emitted):
            preview = self.group.preview
            if preview is not None:
                self.preview_emitted = True
                return "preview", thaw_prepared(preview[0])
        if not finished:
            return None
        prepared, = self.group.result()
        return "full", thaw_prepared(prepared)

    def cancel(self):
        """Withdraw interest now; advance keeps polling until the writer retires."""
        _require_main_thread()
        self.cancelled = True
        if self.group is not None:
            self.group.cancel()

    def close(self):
        _require_main_thread()
        if self.group is not None and not self.group.retired():
            raise RuntimeError("Stack preparation closed before helper retirement")


def _require_main_thread():
    if current_thread() is not main_thread():
        raise RuntimeError("Stack helper transport must be polled on Blender's main thread")
