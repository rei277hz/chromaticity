"""One lifecycle-owned helper lane for native Grade image captures."""

# pg-book: technical-report/en#next-policy.bake

from concurrent.futures import CancelledError
from pathlib import Path
from threading import current_thread, main_thread

from .execution import HelperRuntime


class BakeHelperBackend:
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
            worker_module="runtime.bake_worker",
            role="bake",
        )
        self.probe = self.runtime.start_probe()

    def create_job(self, inputs):
        _require_main_thread()
        self._ensure_runtime()
        return BakeHelperJob(self, inputs)

    def close(self):
        _require_main_thread()
        if self.runtime is None:
            return
        self.runtime.close()
        if not self.runtime.physical_terminal():
            raise RuntimeError("Bake helper has not physically retired")
        self.probe = self.runtime = None


class BakeHelperJob:
    def __init__(self, backend, inputs):
        self.backend = backend
        self.inputs = dict(inputs)
        self.group = None
        self.cancelled = False

    def advance(self):
        _require_main_thread()
        runtime = self.backend.runtime
        if self.cancelled and self.group is None:
            raise CancelledError("Bake was cancelled before helper submission")
        if self.group is None:
            if not self.backend.probe.poll():
                return None
            self.backend.probe.result()
            handle = runtime.submit("bake", self.inputs)
            self.group = runtime.join((handle,))
        if not self.group.poll():
            return None
        return self.group.result()[0]

    def cancel(self):
        _require_main_thread()
        self.cancelled = True
        if self.group is not None:
            self.group.cancel()

    def retired(self):
        _require_main_thread()
        return self.group is None or self.group.retired()


def _require_main_thread():
    if current_thread() is not main_thread():
        raise RuntimeError("Bake helper transport must be polled on Blender's main thread")
