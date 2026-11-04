"""Narrow host admission for publishing prepared Grade image data."""

from contextlib import contextmanager
from collections import deque
from dataclasses import dataclass, field
import threading
from typing import Optional


JOBS = ("RENDER", "RENDER_PREVIEW", "OBJECT_BAKE", "COMPOSITE",
        "SHADER_COMPILATION")
MODAL_READERS = frozenset({
    "OBJECT_OT_lightprobe_cache_bake",
    "OBJECT_OT_bake_image",
})


class PublicationDeferred(RuntimeError):
    """Host activity currently prevents publishing a prepared image."""


@dataclass(eq=False)
class RenderPreflightTicket:
    """Plain cross-thread rendezvous; it contains no Blender/RNA references."""

    render_identity: int
    _finished: threading.Event = field(default_factory=threading.Event)
    _error: Optional[BaseException] = None

    def wait(self):
        if threading.current_thread() is threading.main_thread():
            raise RuntimeError("The main thread cannot wait for its render preflight timer")
        self._finished.wait()
        if self._error is not None:
            raise self._error


class PublicationGate:
    """Observe a small set of Blender activities around main-thread writes.

    Callbacks only update local counters. ``commit`` and the narrowly scoped
    ``render_preflight`` are the only contexts in which callers should mutate
    Blender image data; neither is a universal lock against native readers
    Blender does not expose.
    """

    def __init__(self, bpy):
        self._bpy = bpy
        self._lock = threading.Lock()
        self._callbacks = 0
        self._evaluations = {}
        self._committing = False
        self._preflight_queue = deque()
        self._preflight_active = None

    @contextmanager
    def callback(self):
        """Mark a render/compositor callback as active while it records events."""
        with self._lock:
            self._callbacks += 1
        try:
            yield
        finally:
            with self._lock:
                self._callbacks -= 1

    def evaluation_started(self, kind, identity=0):
        """Latch a render or compositor evaluation until its terminal callback."""
        if kind not in ("render", "compositor"):
            raise ValueError("Evaluation kind must be render or compositor")
        key = kind, int(identity)
        with self._lock:
            self._evaluations[key] = self._evaluations.get(key, 0) + 1

    def evaluation_finished(self, kind, identity=0):
        """Release one matching start; unmatched finishes are ignored."""
        if kind not in ("render", "compositor"):
            raise ValueError("Evaluation kind must be render or compositor")
        key = kind, int(identity)
        with self._lock:
            count = self._evaluations.get(key, 0)
            if count <= 1:
                self._evaluations.pop(key, None)
            else:
                self._evaluations[key] = count - 1

    def request_render_preflight(self, identity):
        """Queue an exact render's demand for a main-thread reconcile."""
        identity = int(identity)
        with self._lock:
            if not self._evaluations.get(("render", identity), 0):
                raise PublicationDeferred("Render preflight has no active render lease")
            ticket = RenderPreflightTicket(identity)
            self._preflight_queue.append(ticket)
            return ticket

    def take_render_preflight(self) -> Optional[RenderPreflightTicket]:
        """Take one request on the main thread; a timer should poll this method."""
        if threading.current_thread() is not threading.main_thread():
            raise RuntimeError("Render preflight must be taken on Blender's main thread")
        with self._lock:
            if self._preflight_active is not None or not self._preflight_queue:
                return None
            ticket = self._preflight_queue.popleft()
            self._preflight_active = ticket
            return ticket

    @property
    def has_render_preflight(self) -> bool:
        with self._lock:
            return bool(self._preflight_queue or self._preflight_active)

    def reset(self):
        """Clear lifecycle receipts after load/undo once host work is quiescent."""
        if threading.current_thread() is not threading.main_thread():
            raise RuntimeError("Publication gate reset requires Blender's main thread")
        reason = self._activity_reason()
        if reason is not None:
            raise PublicationDeferred(reason)
        with self._lock:
            if self._committing or self._callbacks:
                raise PublicationDeferred("Cannot reset publication state during a callback")
            tickets = tuple(self._preflight_queue)
            self._preflight_queue.clear()
            if self._preflight_active is not None:
                tickets += (self._preflight_active,)
                self._preflight_active = None
            self._evaluations.clear()
        error = PublicationDeferred("Render preflight was invalidated by host lifecycle reset")
        for ticket in tickets:
            ticket._error = error
            ticket._finished.set()

    def _activity_reason(self, *, render_preflight_job=None) -> Optional[str]:
        try:
            managers = tuple(self._bpy.data.window_managers)
            if (render_preflight_job is None
                    and any(manager.is_interface_locked for manager in managers)):
                return "Blender interface is locked"
            for manager in managers:
                for window in tuple(manager.windows):
                    for operator in tuple(window.modal_operators):
                        if operator.bl_idname in MODAL_READERS:
                            return "Blender bake operation is active"
            for job in JOBS:
                if job == render_preflight_job:
                    continue
                if self._bpy.app.is_job_running(job):
                    return "Blender job is active: " + job
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError) as error:
            return "Could not inspect Blender publication state: " + str(error)
        return None

    def _observation_reason(self) -> Optional[str]:
        with self._lock:
            if self._committing:
                return "An image publication is already active"
            if self._callbacks:
                return "Image publication is deferred from a native callback"
            if self._evaluations:
                return "Blender render or compositor evaluation is active"
        return None

    def reason(self) -> Optional[str]:
        """Return why publication is blocked, or ``None`` when admitted."""
        if threading.current_thread() is not threading.main_thread():
            return "Image publication requires Blender's main thread"
        reason = self._observation_reason()
        if reason is not None:
            return reason
        reason = self._activity_reason()
        if reason is not None:
            return reason
        # A callback may have started while host job state was inspected.
        return self._observation_reason()

    def blocked(self) -> bool:
        return self.reason() is not None

    @contextmanager
    def commit(self):
        """Admit one synchronous image publication or raise Deferred."""
        reason = self.reason()
        if reason is not None:
            raise PublicationDeferred(reason)

        with self._lock:
            if self._committing or self._callbacks or self._evaluations:
                raise PublicationDeferred("Blender evaluation became active")
            self._committing = True
        try:
            reason = self._activity_reason()
            if reason is not None:
                raise PublicationDeferred(reason)
            with self._lock:
                if self._callbacks or self._evaluations:
                    raise PublicationDeferred("Blender evaluation became active")
            yield
        finally:
            with self._lock:
                self._committing = False

    @contextmanager
    def render_preflight(self, ticket, *, defer=False):
        """Commit only the main-thread reconcile requested by an active render.

        This scope exempts only that render's active lease and identified job,
        along with its interface lock. Other render jobs, modal bake operations
        and compositor leases still defer publication.
        """
        error = None
        claimed = False
        acquired = False
        entered = False
        retry = False
        try:
            if threading.current_thread() is not threading.main_thread():
                raise PublicationDeferred("Render preflight requires Blender's main thread")
            with self._lock:
                if self._preflight_active is not ticket:
                    raise PublicationDeferred("Render preflight ticket is not active")
                claimed = True
                if self._committing or self._callbacks:
                    raise PublicationDeferred("Another host callback or publication is active")
                render_key = "render", ticket.render_identity
                if self._evaluations.get(render_key) != 1:
                    raise PublicationDeferred("Render preflight lost its render lease")
                if any(key != render_key and count
                       for key, count in self._evaluations.items()):
                    raise PublicationDeferred("Another native evaluation is active")

            render_jobs = tuple(job for job in ("RENDER", "RENDER_PREVIEW")
                                if self._bpy.app.is_job_running(job))
            if len(render_jobs) > 1:
                raise PublicationDeferred("Could not identify one expected render job")
            # Synchronous/background renders may have no Window Manager job.
            expected_job = render_jobs[0] if render_jobs else None

            with self._lock:
                if self._committing or self._callbacks:
                    raise PublicationDeferred("Another host callback or publication is active")
                if self._evaluations.get(render_key) != 1 or any(
                        key != render_key and count
                        for key, count in self._evaluations.items()):
                    raise PublicationDeferred("Render evaluation changed during preflight")
                self._committing = True
                acquired = True

            reason = self._activity_reason(render_preflight_job=expected_job)
            if reason is not None:
                raise PublicationDeferred(reason)
            with self._lock:
                if (self._callbacks or self._evaluations.get(render_key) != 1 or any(
                        key != render_key and count
                        for key, count in self._evaluations.items())):
                    raise PublicationDeferred("Another native evaluation became active")
            entered = True
            yield
        except BaseException as failure:
            error = failure
            raise
        finally:
            with self._lock:
                if acquired:
                    self._committing = False
                if claimed and self._preflight_active is ticket:
                    self._preflight_active = None
                    retry = defer and not entered and isinstance(error, PublicationDeferred)
                    if retry:
                        # Admission can race with a second host reader. Keep
                        # the request live for the next foreground timer turn;
                        # only failures after yielding are terminal.
                        self._preflight_queue.appendleft(ticket)
            if claimed and not retry:
                ticket._error = error
                ticket._finished.set()
