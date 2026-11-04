"""GPU-only helper process ownership with nonblocking, ordered joins."""

from concurrent.futures import CancelledError, InvalidStateError
from dataclasses import dataclass
from itertools import count
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import tempfile
import threading
import time
from typing import Optional
from uuid import uuid4

from ..policy import helper as helper_policy
from .payloads import PayloadStore
from .transport import Channel
from . import host


class HelperError(RuntimeError):
    pass


@dataclass
class _Job:
    identity: int
    operation: str
    inputs: object
    probe: bool
    state: str = "queued"
    value: object = None
    preview: object = None
    error: Optional[BaseException] = None
    pending_value: object = None
    pending_preview: object = None
    pending_files: tuple = ()
    input_files: tuple = ()


class JobHandle:
    def __init__(self, runtime, job):
        self.runtime = runtime
        self._job = job

    @property
    def preview(self):
        return self._job.preview

    def done(self):
        return self._job.state == "finished"

    def retired(self):
        return self.done()

    def poll(self):
        self.runtime.poll()
        return self.done()

    def cancel(self):
        return self.runtime.cancel(self)

    def exception(self):
        if not self.done():
            raise InvalidStateError("Helper computation has not retired")
        return self._job.error

    def result(self):
        error = self.exception()
        if error is not None:
            raise error
        return self._job.value


class JobGroup:
    """Nonblocking ordered join; failed groups retire every child before error."""

    def __init__(self, runtime, handles):
        self.runtime = runtime
        self.handles = tuple(handles)
        for handle in self.handles:
            runtime._require_handle(handle)
        self._failure = None
        self._cancelling = False

    def _reconcile(self):
        if self._failure is None:
            self._failure = next(
                (handle._job.error for handle in self.handles
                 if handle.done() and handle._job.error is not None),
                None,
            )
        if self._failure is not None and not self._cancelling:
            self._cancelling = True
            for handle in self.handles:
                if not handle.done():
                    handle.cancel()

    @property
    def preview(self):
        self._reconcile()
        if self._failure is not None or any(handle.preview is None for handle in self.handles):
            return None
        return tuple(handle.preview for handle in self.handles)

    def poll(self):
        self.runtime.poll()
        self._reconcile()
        return all(handle.done() for handle in self.handles)

    def done(self):
        return self.poll()

    def retired(self):
        return self.poll()

    def cancel(self):
        self._reconcile()
        if all(handle.done() for handle in self.handles):
            return False
        self._cancelling = True
        changed = False
        for handle in self.handles:
            if not handle.done():
                changed = handle.cancel() or changed
        return changed

    def exception(self):
        self._reconcile()
        if not all(handle.done() for handle in self.handles):
            raise InvalidStateError("Joined helper computations have not retired")
        return self._failure

    def result(self):
        error = self.exception()
        if error is not None:
            raise error
        return tuple(handle._job.value for handle in self.handles)


class HelperRuntime:
    """One persistent Blender helper with a single serialized GPU lane.

    Inputs and receipts are immutable values. Polling never waits for a child
    computation; shutdown is the only operation that waits for process exit.
    """

    STARTUP_SECONDS = 60.0
    SHUTDOWN_SECONDS = 2.0

    def __init__(self, package, worker_module, *, role="gpu", launcher=None,
                 directory=None, startup_seconds=STARTUP_SECONDS):
        _require_main_thread()
        self.package = Path(package).resolve(strict=True)
        self.worker_module = _module_name(worker_module)
        self.role = role
        self.launcher = launcher or host.launch_command
        self.startup_seconds = startup_seconds
        self._temporary = None
        if directory is None:
            self._temporary = tempfile.TemporaryDirectory(prefix="perceptual-grade-helper-")
            directory = self._temporary.name
        self.directory = Path(directory).resolve()
        self.directory.mkdir(parents=True, exist_ok=True)
        self.payloads = PayloadStore(self.directory)
        self.state = helper_policy.new()
        self.session = uuid4().hex
        self.token = secrets.token_hex(32)
        self._serial = count(1)
        self._jobs = {}
        self._queue = []
        self._probe = None
        self._listener = None
        self._channel = None
        self._process = None
        self._log = None
        self._log_path = None
        self._config_path = None
        self._started_at = None
        self._closed = False

    @property
    def phase(self):
        return self.state.phase

    @property
    def gpu_ready(self):
        return self.state.phase == "ready"

    def start_probe(self):
        _require_main_thread()
        if self._probe is not None:
            return self._probe
        if self.state.phase != "stopped":
            raise HelperError("A failed helper runtime cannot be restarted")
        job = self._new_job("gpu_probe", {}, probe=True)
        self._probe = JobHandle(self, job)
        self._queue.append(job.identity)
        self._transition(helper_policy.Event(
            "launch", generation=self.state.generation + 1, job_id=job.identity,
        ))
        return self._probe

    def submit(self, operation, inputs):
        _require_main_thread()
        if self._closed or self.state.phase in ("closing", "closed", "failed"):
            raise HelperError("GPU helper is unavailable")
        if not self.gpu_ready:
            raise HelperError("GPU helper must pass its startup probe before work")
        if not isinstance(operation, str) or not operation:
            raise TypeError("Helper operation name must be a nonempty string")
        job = self._new_job(operation, inputs, probe=False)
        self._queue.append(job.identity)
        self._transition(helper_policy.Event(
            "submit", generation=self.state.generation, job_id=job.identity,
        ))
        return JobHandle(self, job)

    def join(self, handles):
        return JobGroup(self, handles)

    def cancel(self, handle):
        _require_main_thread()
        self._require_handle(handle)
        job = handle._job
        if job.state == "finished":
            return False
        if job.identity != self.state.active_id and job.state != "queued":
            return False
        self._transition(helper_policy.Event(
            "cancel", generation=self.state.generation, job_id=job.identity,
        ))
        return job.state == "finished" or job.identity == self.state.active_id

    def _new_job(self, operation, inputs, *, probe):
        identity = next(self._serial)
        job = _Job(identity, operation, inputs, probe)
        self._jobs[identity] = job
        return job

    def _require_handle(self, handle):
        if (type(handle) is not JobHandle or handle.runtime is not self
                or self._jobs.get(handle._job.identity) not in (handle._job, None)):
            raise ValueError("Helper handle belongs to another runtime")

    def _transition(self, event):
        self.state, effects = helper_policy.step(self.state, event)
        for action in effects.actions:
            self._apply(action)

    def _apply(self, action):
        if action.kind == "launch":
            try:
                self._launch()
            except Exception as error:
                self._transition(helper_policy.Event(
                    "failure", generation=self.state.generation,
                    error=f"Could not launch Blender GPU helper: {error}",
                ))
                if self._process is None:
                    self._process_exited()
        elif action.kind == "dispatch":
            self._dispatch(action.job_id)
        elif action.kind == "publish_preview":
            self._publish_preview(action.job_id)
        elif action.kind == "publish_result":
            self._publish_result(action.job_id)
        elif action.kind == "publish_failure":
            self._publish_failure(action.job_id, action.error)
        elif action.kind == "publish_cancelled":
            self._publish_cancelled(action.job_id)
        elif action.kind == "send_cancel":
            self._send_or_fail({"kind": "cancel", "job": action.job_id})
        elif action.kind == "send_shutdown":
            self._send_or_fail({"kind": "shutdown"})
        elif action.kind == "terminate":
            if self._process is not None and self._process.poll() is None:
                self._process.terminate()
        elif action.kind == "kill":
            if self._process is not None and self._process.poll() is None:
                self._process.kill()
        elif action.kind == "cleanup":
            self._cleanup()
        elif action.kind == "fail_queued":
            self._fail_queued(action.error)
        elif action.kind == "cancel_queued":
            self._cancel_queued()
        else:
            raise RuntimeError("Unknown helper effect: " + action.kind)

    def _launch(self):
        self._listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._listener.bind(("127.0.0.1", 0))
        self._listener.listen(1)
        self._listener.setblocking(False)
        self._config_path = self.directory / "helper.json"
        self._log_path = self.directory / "helper.log"
        config = {
            "session": self.session,
            "generation": self.state.generation,
            "role": self.role,
            "token": self.token,
            "address": self._listener.getsockname(),
            "package": str(self.package),
            "worker_module": self.worker_module,
            "worker_entry": str(Path(__file__).with_name("worker_main.py").resolve()),
            "config_path": str(self._config_path),
            "directory": str(self.directory),
            "host_settings": self._host_settings(),
        }
        self._config_path.write_text(json.dumps(config), encoding="utf8")
        self._log = self._log_path.open("wb")
        environment = host.worker_environment()
        try:
            self._process = subprocess.Popen(
                self.launcher(config),
                cwd=self.directory,
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=self._log,
                stderr=subprocess.STDOUT,
                close_fds=True,
            )
        except BaseException:
            self._listener.close()
            self._listener = None
            self._log.close()
            self._log = None
            raise
        self._started_at = time.monotonic()

    def _host_settings(self):
        try:
            import bpy
            return {"gpu_backend": getattr(bpy.context.preferences.system, "gpu_backend", "")}
        except ImportError:
            return {}

    def _dispatch(self, identity):
        job = self._jobs.get(identity)
        if job is None or job.state != "queued":
            return
        try:
            prefix = f"{self.role}-{self.state.generation}-{identity}"
            value, files = self.payloads.encode(job.inputs, prefix=prefix)
            job.input_files = tuple(files)
            self._send({
                "kind": "run",
                "job": identity,
                "operation": job.operation,
                "inputs": value,
            })
            job.state = "running"
        except Exception as error:
            job.error = HelperError(f"Could not dispatch helper operation: {error}")
            self._transition(helper_policy.Event(
                "failure", generation=self.state.generation,
                job_id=identity, error=str(job.error),
            ))

    def _send(self, message):
        if self._channel is None:
            raise HelperError("GPU helper is not connected")
        self._channel.send(dict(message, session=self.session,
                                generation=self.state.generation))

    def _send_or_fail(self, message):
        try:
            self._send(message)
        except Exception as error:
            self._transition(helper_policy.Event(
                "failure", generation=self.state.generation,
                error=f"Could not communicate with Blender GPU helper: {error}",
            ))

    def _next_queued(self):
        active_id = self.state.active_id
        return next((identity for identity in self._queue
                     if identity != active_id
                     and (job := self._jobs.get(identity)) is not None
                     and job.state == "queued"), None)

    def poll(self):
        _require_main_thread()
        if self._process is None or self.state.phase == "closed":
            return False
        try:
            if self._channel is None:
                try:
                    sock, _address = self._listener.accept()
                except BlockingIOError:
                    sock = None
                if sock is not None:
                    self._channel = Channel(sock)
                    self._listener.close()
                    self._listener = None
            if self._channel is not None:
                for message in self._channel.pump():
                    self._message(message)
        except EOFError as error:
            if self.state.phase != "closing":
                self._transition(helper_policy.Event(
                    "failure", generation=self.state.generation,
                    error=f"GPU helper protocol failed: {error}",
                ))
        except (OSError, ValueError, KeyError, TypeError, BufferError) as error:
            self._transition(helper_policy.Event(
                "failure", generation=self.state.generation,
                error=f"GPU helper protocol failed: {error}",
            ))

        code = self._process.poll()
        if code is not None:
            self._process_exited()
            return self.state.phase == "ready"
        if (self.state.phase == "starting" and self._started_at is not None
                and time.monotonic() - self._started_at > self.startup_seconds):
            self._transition(helper_policy.Event(
                "failure", generation=self.state.generation,
                error="GPU helper startup timed out",
            ))
        return self.state.phase == "ready"

    def _message(self, message):
        if (message.get("session") != self.session
                or message.get("generation") != self.state.generation):
            self._release_message(message)
            return
        kind = message.get("kind")
        if kind == "hello":
            if message.get("protocol") != 1 or message.get("token") != self.token:
                raise ValueError("GPU helper handshake mismatch")
            self._transition(helper_policy.Event(
                "hello", generation=self.state.generation,
            ))
            return

        identity = message.get("job")
        job = self._jobs.get(identity)
        if job is None or identity != self.state.active_id:
            self._release_message(message)
            return
        files = tuple(message.get("files", ()))
        if kind == "preview":
            job.pending_preview = self.payloads.decode(message["value"], copy=True)
            job.pending_files = files
            self._transition(helper_policy.Event(
                "preview", generation=self.state.generation, job_id=identity,
            ))
        elif kind == "complete":
            value = self.payloads.decode(message["value"], copy=True)
            job.pending_value = value
            job.pending_files = files
            if job.probe:
                valid = (isinstance(value, dict) and value.get("conformance") is True
                         and value.get("backend") == "GPU")
                next_id = self._next_queued() if valid else None
                self._transition(helper_policy.Event(
                    "probe_result", generation=self.state.generation,
                    job_id=identity, success=valid,
                    error=None if valid else "GPU helper probe failed conformance",
                    next_id=next_id,
                ))
            else:
                next_id = self._next_queued()
                self._transition(helper_policy.Event(
                    "result", generation=self.state.generation,
                    job_id=identity, success=True, next_id=next_id,
                ))
        elif kind == "cancelled":
            next_id = self._next_queued()
            self._transition(helper_policy.Event(
                "cancelled", generation=self.state.generation,
                job_id=identity, next_id=next_id,
            ))
        elif kind == "failed":
            self._transition(helper_policy.Event(
                "failure", generation=self.state.generation,
                job_id=identity,
                error=message.get("error", "GPU helper operation failed"),
            ))
        else:
            raise ValueError("Unknown GPU helper response")

    def _release_message(self, message):
        self.payloads.release(message.get("files", ()))

    def _publish_preview(self, identity):
        job = self._jobs.get(identity)
        if job is None:
            return
        job.preview = job.pending_preview
        job.pending_preview = None
        self.payloads.release(job.pending_files)
        job.pending_files = ()

    def _publish_result(self, identity):
        job = self._jobs.get(identity)
        if job is None:
            return
        job.value = job.pending_value
        job.pending_value = None
        self.payloads.release(job.pending_files)
        job.pending_files = ()
        self.payloads.release(job.input_files)
        job.input_files = ()
        job.state = "finished"
        self._jobs.pop(identity, None)
        if job.identity in self._queue:
            self._queue.remove(job.identity)

    def _publish_failure(self, identity, error):
        job = self._jobs.get(identity)
        if job is None:
            return
        self.payloads.release(job.pending_files)
        self.payloads.release(job.input_files)
        job.pending_files = job.input_files = ()
        job.pending_value = job.pending_preview = None
        job.error = job.error or HelperError(error or "GPU helper failed")
        job.state = "finished"
        self._jobs.pop(identity, None)
        if identity in self._queue:
            self._queue.remove(identity)

    def _publish_cancelled(self, identity):
        job = self._jobs.get(identity)
        if job is None:
            return
        self.payloads.release(job.pending_files)
        self.payloads.release(job.input_files)
        job.pending_files = job.input_files = ()
        job.pending_value = job.pending_preview = None
        job.error = CancelledError("GPU helper computation cancelled")
        job.state = "finished"
        self._jobs.pop(identity, None)
        if identity in self._queue:
            self._queue.remove(identity)

    def _fail_queued(self, error):
        for identity in tuple(self._queue):
            job = self._jobs.pop(identity, None)
            if job is None:
                continue
            self.payloads.release(job.input_files)
            job.input_files = ()
            job.error = HelperError(error or "GPU helper failed")
            job.state = "finished"
        self._queue.clear()

    def _cancel_queued(self):
        active_id = self.state.active_id
        for identity in tuple(self._queue):
            if identity == active_id:
                continue
            job = self._jobs.pop(identity, None)
            if job is None:
                continue
            self.payloads.release(job.input_files)
            job.input_files = ()
            job.error = CancelledError("GPU helper shut down before dispatch")
            job.state = "finished"
        self._queue[:] = [identity for identity in self._queue
                          if identity == active_id]

    def _process_exited(self):
        error = self.state.error
        code = self._process.poll() if self._process is not None else 0
        if error is None and code not in (0, None):
            error = f"GPU helper exited with status {code}"
        self._transition(helper_policy.Event(
            "exited", generation=self.state.generation, error=error,
        ))

    def physical_terminal(self):
        return self._process is None or self._process.poll() is not None

    def close(self):
        _require_main_thread()
        if self._closed and self.physical_terminal():
            return
        self._closed = True
        if self._process is None:
            self._transition(helper_policy.Event(
                "shutdown", generation=self.state.generation,
            ))
            return
        if self._process.poll() is not None:
            if self.state.phase not in ("failed", "closed"):
                self._process_exited()
            if self.state.phase == "failed":
                self._transition(helper_policy.Event(
                    "shutdown", generation=self.state.generation,
                ))
            return
        self._transition(helper_policy.Event(
            "shutdown", generation=self.state.generation,
        ))
        deadline = time.monotonic() + self.SHUTDOWN_SECONDS
        while self._process.poll() is None and time.monotonic() < deadline:
            self.poll()
            time.sleep(0.005)
        if self._process.poll() is None:
            self._transition(helper_policy.Event(
                "failure", generation=self.state.generation,
                error=self.state.error or "GPU helper shutdown timed out",
            ))
            deadline = time.monotonic() + 0.5
            while self._process.poll() is None and time.monotonic() < deadline:
                self.poll()
                time.sleep(0.005)
        if self._process.poll() is None:
            self._transition(helper_policy.Event(
                "kill", generation=self.state.generation,
            ))
            try:
                self._process.wait(timeout=2)
            except subprocess.TimeoutExpired as error:
                raise RuntimeError("GPU helper did not physically retire") from error
        self._process_exited()
        if self.state.phase == "failed":
            self._transition(helper_policy.Event(
                "shutdown", generation=self.state.generation,
            ))

    def _cleanup(self):
        if self._channel is not None:
            self._channel.close()
            self._channel = None
        if self._listener is not None:
            self._listener.close()
            self._listener = None
        if self._log is not None:
            self._log.close()
            self._log = None
        self.payloads.close()
        if self._temporary is not None:
            self._temporary.cleanup()
            self._temporary = None


def _module_name(value):
    if (not isinstance(value, str) or not value
            or not all(part.isidentifier() for part in value.split("."))):
        raise ValueError("Helper worker module must be a relative dotted name")
    return value


def _require_main_thread():
    if threading.current_thread() is not threading.main_thread():
        raise RuntimeError("Blender helper transport must be polled on the main thread")
