"""GPU-only helper process ownership with nonblocking, ordered joins."""

# pg-book: technical-report/en#next-policy.helper

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
from .transport import PROTOCOL, Channel
from . import host


class HelperError(RuntimeError):
    pass


@dataclass(frozen=True)
class _Action:
    kind: str
    job_id: Optional[int] = None
    error: Optional[str] = None
    stage: Optional[str] = None


def _actions_for(effects):
    """Translate scalar policy authorizations in their established order."""
    actions = []
    if effects.clear_deadline:
        actions.append(_Action("clear_deadline"))
    if effects.deadline_stage is not None:
        actions.append(_Action("deadline", stage=effects.deadline_stage))
    if effects.launch:
        actions.append(_Action("launch"))
    if effects.accept:
        actions.append(_Action("accept"))
    if effects.pump:
        actions.append(_Action("pump"))

    publish_kinds = {
        "preview": "publish_preview",
        "result": "publish_result",
        "failure": "publish_failure",
        "cancelled": "publish_cancelled",
    }
    if effects.publish_kind is not None:
        actions.append(_Action(
            publish_kinds[effects.publish_kind], effects.publish_id,
            effects.publish_error,
        ))
    if effects.dispatch_id is not None:
        actions.append(_Action("dispatch", effects.dispatch_id))
    if effects.send_cancel_id is not None:
        actions.append(_Action("send_cancel", effects.send_cancel_id))
    if effects.send_shutdown:
        actions.append(_Action("send_shutdown"))
    if effects.terminate:
        actions.append(_Action("terminate"))
    if effects.kill:
        actions.append(_Action("kill"))
    if effects.queue_kind == "fail":
        actions.append(_Action("fail_queued", error=effects.queue_error))
    elif effects.queue_kind == "cancel":
        actions.append(_Action("cancel_queued"))
    if effects.cleanup:
        actions.append(_Action("cleanup"))
    return tuple(actions)


@dataclass
class _Job:
    identity: int
    operation: str
    inputs: object
    probe: bool
    profile: bool = False
    timings: tuple = ()
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
        return None if self._job.error is not None else self._job.preview

    @property
    def timings(self):
        return self._job.timings if self.done() else ()

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
        self._deadline = None
        self._cleanup_error = None

    @property
    def phase(self):
        return self.state.phase

    @property
    def gpu_ready(self):
        return helper_policy.admitting(self.state)

    def start_probe(self):
        _require_main_thread()
        if self._probe is not None:
            return self._probe
        if self.state.phase != "stopped":
            raise HelperError("A failed helper runtime cannot be restarted")
        job = self._new_job("gpu_probe", {}, probe=True)
        self._probe = JobHandle(self, job)
        self._queue.append(job.identity)
        self._transition(helper_policy.Event("launch", job_id=job.identity))
        return self._probe

    def submit(self, operation, inputs, *, profile=False):
        _require_main_thread()
        if not self.gpu_ready:
            raise HelperError("GPU helper must pass its startup probe before work")
        if not isinstance(operation, str) or not operation:
            raise TypeError("Helper operation name must be a nonempty string")
        job = self._new_job(operation, inputs, probe=False, profile=profile)
        self._queue.append(job.identity)
        self._transition(helper_policy.Event("submit", job_id=job.identity))
        return JobHandle(self, job)

    def cancel(self, handle):
        _require_main_thread()
        self._require_handle(handle)
        job = handle._job
        if job.state == "finished":
            return False
        if job.identity != self.state.active_id and job.state != "queued":
            return False
        self._transition(helper_policy.Event(
            "cancel", job_id=job.identity,
            transport=self._transport(),
        ))
        return (job.state == "finished" or job.identity == self.state.active_id
                or job.identity == self.state.probe_id and self.state.close_requested)

    def _new_job(self, operation, inputs, *, probe, profile=False):
        identity = next(self._serial)
        job = _Job(identity, operation, inputs, probe, profile)
        self._jobs[identity] = job
        return job

    def _require_handle(self, handle):
        if (type(handle) is not JobHandle or handle.runtime is not self
                or self._jobs.get(handle._job.identity) not in (handle._job, None)):
            raise ValueError("Helper handle belongs to another runtime")

    def _transition(self, event):
        self.state, effects = helper_policy.step(self.state, event)
        for action in _actions_for(effects):
            self._apply(action)

    def _apply(self, action):
        if action.kind == "launch":
            try:
                self._launch()
            except Exception as error:
                self._transition(helper_policy.Event(
                    "failure",
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
        elif action.kind in ("terminate", "kill"):
            try:
                if self._process is not None and self._process.poll() is None:
                    getattr(self._process, action.kind)()
            except OSError as error:
                self._transition(helper_policy.Event(
                    "failure",
                    error=f"GPU helper process control failed: {error}",
                ))
        elif action.kind == "cleanup":
            try:
                self._cleanup()
            except Exception as error:
                self._cleanup_error = error
                self._transition(helper_policy.Event("cleanup_result", error=str(error)))
            else:
                self._cleanup_error = None
                self._transition(helper_policy.Event("cleanup_result", success=True))
        elif action.kind == "fail_queued":
            self._fail_queued(action.error)
        elif action.kind == "cancel_queued":
            self._cancel_queued()
        elif action.kind == "deadline":
            durations = {"starting": self.startup_seconds,
                         "stopping": self.SHUTDOWN_SECONDS,
                         "terminating": 0.5, "killing": 2.0}
            self._deadline = (action.stage, time.monotonic() + durations[action.stage])
        elif action.kind == "clear_deadline":
            self._deadline = None
        elif action.kind in ("accept", "pump"):
            try:
                if action.kind == "accept":
                    try:
                        sock, _address = self._listener.accept()
                    except BlockingIOError:
                        return
                    self._channel = Channel(sock)
                    self._listener.close()
                    self._listener = None
                else:
                    for message in self._channel.pump():
                        self._message(message)
            except EOFError as error:
                self._transition(helper_policy.Event(
                    "eof",
                    error=f"GPU helper protocol failed: {error}",
                ))
            except (OSError, ValueError, KeyError, TypeError, BufferError) as error:
                self._transition(helper_policy.Event(
                    "failure",
                    error=f"GPU helper protocol failed: {error}",
                ))
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
        self._process = subprocess.Popen(
            self.launcher(config),
            cwd=self.directory,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=self._log,
            stderr=subprocess.STDOUT,
            close_fds=True,
        )

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
            prefix = f"{self.role}-{identity}"
            value, files = self.payloads.encode(job.inputs, prefix=prefix)
            job.input_files = tuple(files)
            message = {
                "kind": "run",
                "job": identity,
                "operation": job.operation,
                "inputs": value,
            }
            if job.profile:
                message["profile"] = True
            self._send(message)
            job.state = "running"
        except Exception as error:
            job.error = HelperError(f"Could not dispatch helper operation: {error}")
            self._transition(helper_policy.Event("failure", error=str(job.error)))

    def _send(self, message):
        if self._channel is None:
            raise HelperError("GPU helper is not connected")
        self._channel.send(dict(message, session=self.session))

    def _send_or_fail(self, message):
        try:
            self._send(message)
        except Exception as error:
            self._transition(helper_policy.Event(
                "failure",
                error=f"Could not communicate with Blender GPU helper: {error}",
            ))

    def _next_queued(self):
        active_id = self.state.active_id
        return next((identity for identity in self._queue
                     if identity != active_id
                     and (job := self._jobs.get(identity)) is not None
                     and job.state == "queued"), None)

    def _transport(self):
        if self._channel is not None:
            return "channel"
        if self._listener is not None:
            return "listener"
        return None

    def _process_observation(self, kind):
        code = self._process.poll() if self._process is not None else None
        return helper_policy.Event(
            kind,
            transport=self._transport(),
            process_alive=self._process is not None and code is None,
            exit_code=code,
            error=f"GPU helper exited with status {code}" if code not in (None, 0) else None,
        )

    def poll(self):
        _require_main_thread()
        self._transition(self._process_observation("poll"))
        # Pumping may have observed a receipt and caused the child to exit.
        if self._process is not None and self._process.poll() is not None:
            self._process_exited()
        if self._deadline is not None:
            stage, deadline = self._deadline
            if time.monotonic() >= deadline:
                self._transition(helper_policy.Event("timeout", stage=stage))
        return self.gpu_ready

    def _message(self, message):
        if message.get("session") != self.session:
            self._release_message(message)
            return
        kind = message.get("kind")
        if kind == "hello":
            if message.get("protocol") != PROTOCOL or message.get("token") != self.token:
                raise ValueError("GPU helper handshake mismatch")
            self._transition(helper_policy.Event("hello"))
            return

        identity = message.get("job")
        job = self._jobs.get(identity)
        if job is None or identity != self.state.active_id:
            self._release_message(message)
            return
        files = tuple(message.get("files", ()))
        self._retain_files(files)
        if kind == "preview":
            job.pending_preview = self.payloads.decode(message["value"], copy=True)
            job.pending_files = files
            self._transition(helper_policy.Event("preview", job_id=identity))
        elif kind == "complete":
            started = time.perf_counter_ns() if job.profile else None
            value = self.payloads.decode(message["value"], copy=True)
            if started is not None:
                job.timings = (("helper_receive", started, time.perf_counter_ns(), "host"),
                               *message.get("timings", ()))
            job.pending_value = value
            job.pending_files = files
            if job.probe:
                expected_backend = {"NODE_TREE"} if self.role == "bake" else {"GPU"}
                valid = (isinstance(value, dict) and value.get("conformance") is True
                         and value.get("backend") in expected_backend)
                self._transition(helper_policy.Event(
                    "probe_result",
                    job_id=identity, success=valid,
                    error=None if valid else "Helper probe failed conformance",
                ))
            else:
                next_id = self._next_queued()
                self._transition(helper_policy.Event("result", job_id=identity, next_id=next_id))
        elif kind == "cancelled":
            next_id = self._next_queued()
            self._transition(helper_policy.Event(
                "cancelled", job_id=identity, next_id=next_id,
                transport=self._transport(),
            ))
        elif kind == "failed":
            self._transition(helper_policy.Event(
                "failure",
                error=message.get("error", "GPU helper operation failed"),
            ))
        else:
            raise ValueError("Unknown GPU helper response")

    def _retain_files(self, names):
        for name in names:
            if (not isinstance(name, str) or Path(name).name != name
                    or not name.startswith("array-")):
                raise ValueError("Invalid helper-owned array path")
            self.payloads.owned.add(self.directory / name)

    def _release_files(self, names):
        names = tuple(names)
        self._retain_files(names)
        try:
            self.payloads.release(names)
        except Exception as error:
            # The ownership ledger survives job completion for a close retry.
            self._cleanup_error = error

    def _release_message(self, message):
        self._release_files(message.get("files", ()))

    def _publish_preview(self, identity):
        job = self._jobs.get(identity)
        if job is None:
            return
        job.preview = job.pending_preview
        job.pending_preview = None
        self._release_files(job.pending_files)
        job.pending_files = ()

    def _finish_job(self, job):
        files = job.pending_files + job.input_files
        self._retain_files(files)
        job.pending_files = job.input_files = ()
        job.pending_value = job.pending_preview = None
        job.state = "finished"
        self._jobs.pop(job.identity, None)
        if job.identity in self._queue:
            self._queue.remove(job.identity)
        self._release_files(files)

    def _publish_result(self, identity):
        job = self._jobs.get(identity)
        if job is None:
            return
        job.value = job.pending_value
        self._finish_job(job)

    def _publish_failure(self, identity, error):
        job = self._jobs.get(identity)
        if job is None:
            return
        job.error = job.error or HelperError(error or "GPU helper failed")
        self._finish_job(job)

    def _publish_cancelled(self, identity):
        job = self._jobs.get(identity)
        if job is None:
            return
        job.error = CancelledError("GPU helper computation cancelled")
        self._finish_job(job)

    def _fail_queued(self, error):
        for identity in tuple(self._queue):
            self._publish_failure(identity, error)

    def _cancel_queued(self):
        active_id = self.state.active_id
        for identity in tuple(self._queue):
            if identity != active_id:
                self._publish_cancelled(identity)

    def _process_exited(self):
        self._transition(self._process_observation("exited"))

    def physical_terminal(self):
        return self._process is None or self._process.poll() is not None

    def close(self):
        _require_main_thread()
        self._transition(self._process_observation("shutdown"))
        while helper_policy.close_pending(self.state):
            self.poll()
            if helper_policy.close_pending(self.state):
                time.sleep(0.005)
        # A later close can finish a child that outlived the kill deadline.
        if self.state.phase == "unretired":
            self.poll()
        problem = helper_policy.close_problem(self.state)
        if problem is not None:
            raise RuntimeError(problem) from self._cleanup_error

    def _cleanup(self):
        failures = []
        for attribute in ("_channel", "_listener", "_log"):
            resource = getattr(self, attribute)
            if resource is not None:
                try:
                    resource.close()
                except Exception as error:
                    failures.append(error)
                else:
                    setattr(self, attribute, None)
        try:
            self.payloads.close()
        except Exception as error:
            failures.append(error)
        if self._temporary is not None:
            try:
                self._temporary.cleanup()
            except Exception as error:
                failures.append(error)
            else:
                self._temporary = None
        # PayloadStore deliberately retains paths when unlink fails. A returned
        # close call alone is therefore not evidence that storage was released.
        self.payloads.owned.difference_update(
            path for path in tuple(self.payloads.owned) if not path.exists())
        if self.payloads.owned:
            failures.append(RuntimeError("GPU helper still owns payload files"))
        if failures:
            raise ExceptionGroup("GPU helper cleanup failed", failures)


def _module_name(value):
    if (not isinstance(value, str) or not value
            or not all(part.isidentifier() for part in value.split("."))):
        raise ValueError("Helper worker module must be a relative dotted name")
    return value


def _require_main_thread():
    if threading.current_thread() is not threading.main_thread():
        raise RuntimeError("Blender helper transport must be polled on the main thread")
