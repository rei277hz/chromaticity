"""Foreground polling adapter for the process-owned Stack GPU baker."""

from concurrent.futures import CancelledError
from pathlib import Path
from threading import current_thread, main_thread

from .kernel.settings import split_stack_entries, stack_directions
from .lut_codec import freeze_settings, thaw_prepared
from .runtime.execution import HelperRuntime


class StackHelperBackend:
    """One lifecycle-owned helper service; construction starts no process."""

    def __init__(self):
        self.runtime = None
        self.probe = None

    def _ensure_runtime(self):
        _require_main_thread()
        if self.runtime is not None:
            if not self.runtime.physical_terminal():
                return
            if self.runtime.phase not in ("failed", "closed"):
                self.runtime.poll()
            if self.runtime.phase not in ("retiring", "failed", "closed"):
                return
            self.runtime.close()
            self.runtime = None
            self.probe = None
        self.runtime = HelperRuntime(
            package=Path(__file__).resolve().parent,
            worker_module="lut_worker",
            role="gpu",
        )
        self.probe = self.runtime.start_probe()

    def create_job(self, payload, progressive):
        _require_main_thread()
        self._ensure_runtime()
        return HelperStackJob(self, payload, progressive)

    def close(self):
        _require_main_thread()
        if self.runtime is None:
            return
        self.runtime.close()
        if not self.runtime.physical_terminal():
            raise RuntimeError("Stack GPU helper has not physically retired")
        self.probe = self.runtime = None


class HelperStackJob:
    """Poll one Stack computation through preview and physical retirement."""

    def __init__(self, backend, payload, progressive):
        entries, working_space = payload
        settings, directions = split_stack_entries(entries)
        self.backend = backend
        self.inputs = {
            "settings": freeze_settings(settings),
            "directions": stack_directions(len(settings), directions),
            "working_space": working_space,
            "progressive": bool(progressive),
        }
        self.handle = None
        self.preview_emitted = False
        self.cancelled = False

    def advance(self):
        _require_main_thread()
        runtime = self.backend.runtime
        if self.handle is None:
            if self.cancelled:
                raise CancelledError("Stack preparation superseded")
            if not self.backend.probe.poll():
                return None
            self.backend.probe.result()
            self.handle = runtime.submit("stack_lut", self.inputs)
        finished = self.handle.poll()
        if (self.inputs["progressive"] and not self.cancelled
                and not self.preview_emitted):
            preview = self.handle.preview
            if preview is not None:
                self.preview_emitted = True
                return "preview", thaw_prepared(preview)
        if not finished:
            return None
        return "full", thaw_prepared(self.handle.result())

    def cancel(self):
        """Withdraw interest now; advance keeps polling until the writer retires."""
        _require_main_thread()
        if self.cancelled:
            return
        self.cancelled = True
        if self.handle is not None:
            self.handle.cancel()

    def close(self):
        _require_main_thread()
        if self.handle is not None and not self.handle.poll():
            raise RuntimeError("Stack preparation closed before helper retirement")


def _require_main_thread():
    if current_thread() is not main_thread():
        raise RuntimeError("Stack helper transport must be polled on Blender's main thread")
