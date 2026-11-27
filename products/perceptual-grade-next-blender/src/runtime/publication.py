"""Narrow host admission for publishing prepared Grade image data."""

# pg-book: technical-report/en#grade-policy.render-preflight

from contextlib import contextmanager
from collections import deque
from dataclasses import dataclass, field, replace
import threading
from typing import Optional

from ..policy import render_preflight


JOBS = ("RENDER", "RENDER_PREVIEW", "OBJECT_BAKE", "COMPOSITE",
        "SHADER_COMPILATION")
MODAL_READERS = frozenset({
    "OBJECT_OT_lightprobe_cache_bake",
    "OBJECT_OT_bake_image",
})


class PublicationDeferred(RuntimeError):
    """Host activity currently prevents publishing a prepared image."""


@dataclass(frozen=True)
class EvaluationReceipt:
    """Plain identities and generations captured at the evaluation boundary."""

    kind: str
    identity: int
    epoch: int
    snapshot: tuple[tuple[int, int], ...]
    successful: Optional[bool] = None


@dataclass(eq=False)
class RenderPreflightTicket:
    """Plain cross-thread rendezvous; it contains no Blender/RNA references."""

    state: render_preflight.State
    lease: Optional[EvaluationReceipt]
    _finished: threading.Event = field(default_factory=threading.Event)
    _error: Optional[BaseException] = None
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def _resolve(self, event, *, error=None):
        with self._lock:
            self.state, effects = render_preflight.step(self.state, event)
            if effects.action == "fail":
                self._error = (
                    error if error is not None
                    else RuntimeError(effects.error or "Render preflight failed")
                )
            return effects

    def fail(self, error):
        return self._resolve(render_preflight.Event("failed", error=str(error)),
                             error=error)

    @property
    def failure_authorized(self):
        with self._lock:
            return self.state.phase == "failed"

    def deliver(self):
        with self._lock:
            if self.state.phase in ("released", "failed"):
                self._finished.set()
                return True
            return False

    def wait(self):
        if threading.current_thread() is threading.main_thread():
            raise RuntimeError("The main thread cannot wait for its render preflight timer")
        self._finished.wait()
        if self._error is not None:
            raise self._error


class PublicationGate:
    """Observe a small set of Blender activities around main-thread writes.

    Callbacks only update local counters. ``commit`` and the narrowly scoped
    ``render_preflight`` authorize quiescent image writes. These contexts are
    not universal locks against native readers Blender does not expose.
    """

    def __init__(self, bpy):
        self._bpy = bpy
        self._lock = threading.Lock()
        self._callbacks = 0
        self._evaluations = {}
        self._epoch = 0
        self._committing = False
        self._preflight_queue = deque()
        self._preflight_active = None
        self._preflight_scope = None

    @contextmanager
    def callback(self):
        """Mark a render/compositor callback as active while it records events."""
        with self._lock:
            self._epoch += 1
            self._callbacks += 1
        try:
            yield
        finally:
            with self._lock:
                self._callbacks -= 1

    def evaluation_started(self, kind, identity=0, *, snapshot=None):
        """Latch a render or compositor evaluation until its terminal callback."""
        if kind not in ("render", "compositor"):
            raise ValueError("Evaluation kind must be render or compositor")
        key = kind, int(identity)
        frozen = tuple(snapshot.items()) if snapshot is not None else ()
        if any(type(identity) is not int or type(generation) is not int
               for identity, generation in frozen):
            raise TypeError("Evaluation snapshots must contain plain integer identities and generations")
        with self._lock:
            self._epoch += 1
            receipt = EvaluationReceipt(kind, key[1], self._epoch, frozen)
            self._evaluations.setdefault(key, deque()).append(receipt)
            return receipt.epoch

    def evaluation_finished(self, kind, identity=0, *, successful=True):
        """Release one matching start; unmatched finishes are ignored."""
        if kind not in ("render", "compositor"):
            raise ValueError("Evaluation kind must be render or compositor")
        key = kind, int(identity)
        with self._lock:
            receipts = self._evaluations.get(key)
            if not receipts:
                return None
            receipt = receipts.popleft()
            if not receipts:
                self._evaluations.pop(key, None)
            if kind == "render":
                self._invalidate_render_preflight_locked(receipt, successful)
            return replace(receipt, successful=bool(successful))

    def _invalidate_render_preflight_locked(self, lease, successful):
        tickets = []
        for _ in range(len(self._preflight_queue)):
            ticket = self._preflight_queue.popleft()
            if ticket.lease is lease:
                tickets.append(ticket)
            else:
                self._preflight_queue.append(ticket)
        active = self._preflight_active
        if active is not None and active.lease is lease:
            tickets.append(active)
            self._preflight_active = None
        message = ("Render ended before Grade preflight completed" if successful
                   else "Render was cancelled during Grade preflight")
        for ticket in tickets:
            ticket.fail(PublicationDeferred(message))
            ticket.deliver()

    def evaluation_active(self, kind, identity=0) -> bool:
        """Report whether this scene still has a matching native evaluation."""
        if kind not in ("render", "compositor"):
            raise ValueError("Evaluation kind must be render or compositor")
        key = kind, int(identity)
        with self._lock:
            return bool(self._evaluations.get(key))

    def _current_compositor_locked(self):
        if len(self._evaluations) != 1:
            return None
        key, receipts = next(iter(self._evaluations.items()))
        if key[0] != "compositor" or len(receipts) != 1:
            return None
        return key[1], receipts[0].epoch

    def _owns_render_lease_locked(self, ticket):
        receipts = self._evaluations.get(("render", ticket.state.scene_identity), ())
        return (len(self._evaluations) == 1 and len(receipts) == 1
                and receipts[0] is ticket.lease)

    def current_compositor(self):
        """Return the sole observed compositor scene and evaluation epoch."""
        with self._lock:
            return self._current_compositor_locked()

    def request_render_preflight(self, scene_identity, frame, subframe):
        """Queue one frame's demand for a correlated main-thread reconcile."""
        scene_identity = int(scene_identity)
        frame = int(frame)
        subframe = str(subframe)
        with self._lock:
            receipts = self._evaluations.get(("render", scene_identity), ())
            lease = receipts[0] if len(receipts) == 1 else None
            ticket = RenderPreflightTicket(
                render_preflight.new(scene_identity, frame, subframe), lease,
            )
            if lease is None:
                ticket.fail(PublicationDeferred(
                    "Render preflight requires one matching active render lease"))
            self._preflight_queue.append(ticket)
            return ticket

    def invalidate_render_preflights(self):
        """Fence tickets issued before Blender replaces the working scene IDs."""
        with self._lock:
            tickets = list(self._preflight_queue)
            if self._preflight_active is not None:
                tickets.append(self._preflight_active)
            for ticket in tickets:
                ticket.fail(PublicationDeferred(
                    "Render preflight was invalidated by host lifecycle reset"))

    def take_render_preflight(
            self, exact: Optional[RenderPreflightTicket] = None,
    ) -> Optional[RenderPreflightTicket]:
        """Claim the next worker ticket or the exact synchronous callback ticket."""
        if threading.current_thread() is not threading.main_thread():
            raise RuntimeError("Render preflight must be taken on Blender's main thread")
        with self._lock:
            if self._preflight_active is not None or not self._preflight_queue:
                return None
            if exact is None:
                ticket = self._preflight_queue.popleft()
            elif exact in self._preflight_queue:
                self._preflight_queue.remove(exact)
                ticket = exact
            else:
                return None
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
            if self._committing or self._callbacks or self._evaluations:
                raise PublicationDeferred(
                    "Cannot reset publication state during an active evaluation")
            self._epoch += 1
            epoch = self._epoch
            tickets = tuple(self._preflight_queue)
            self._preflight_queue.clear()
            if self._preflight_active is not None:
                tickets += (self._preflight_active,)
                self._preflight_active = None
            self._evaluations.clear()
        error = PublicationDeferred("Render preflight was invalidated by host lifecycle reset")
        for ticket in tickets:
            ticket.fail(error)
            ticket.deliver()
        return epoch

    def quiescent_since(self, epoch):
        """Check tracked activity since a reset already verified host quiescence."""
        if threading.current_thread() is not threading.main_thread():
            return False
        with self._lock:
            return (self._epoch == epoch and not self._committing and not self._callbacks
                    and not self._evaluations and not self._preflight_queue
                    and self._preflight_active is None)

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

    def quiescent(self) -> bool:
        """Observe reclaim readiness, including inside an ordinary commit.

        This query grants no permission to mutate host data. In particular an
        active render preflight is never a quiescent reclamation boundary.
        """
        if threading.current_thread() is not threading.main_thread():
            return False
        with self._lock:
            if self._callbacks or self._evaluations:
                return False
        if self._activity_reason() is not None:
            return False
        with self._lock:
            return not self._callbacks and not self._evaluations

    def retirement_allowed(self) -> bool:
        """Observe a quiescent or exclusively admitted render-preflight scope.

        A queued/taken ticket alone does not authorize retirement. The admitted
        scope records the expected render job only after preflight validation;
        the render worker is then parked behind its unfinished ticket.
        """
        if self.quiescent():
            return True
        if threading.current_thread() is not threading.main_thread():
            return False
        with self._lock:
            scope = self._preflight_scope
            if scope is None or not self._committing or self._callbacks:
                return False
            ticket, expected_job = scope
            if (self._preflight_active is not ticket or ticket._finished.is_set()
                    or not self._owns_render_lease_locked(ticket)):
                return False
        if self._activity_reason(render_preflight_job=expected_job) is not None:
            return False
        with self._lock:
            return (self._preflight_scope == scope and self._committing
                    and not self._callbacks and self._owns_render_lease_locked(ticket)
                    and self._preflight_active is ticket and not ticket._finished.is_set())

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
    def graph_commit(self):
        """Compose graph reconciliation with an admitted foreground scope.

        Normal publication and render preflight may invoke nested graph
        consumers.
        """
        if threading.current_thread() is not threading.main_thread():
            raise PublicationDeferred("Graph reconciliation requires Blender's main thread")
        with self._lock:
            composing = self._committing and not self._callbacks
        if composing:
            yield
        else:
            with self.commit():
                yield

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
    def render_preflight(self, ticket, *, defer=False, deliver_failure=True):
        """Commit only the main-thread reconcile requested by an active render.

        This scope exempts only that render's active lease and identified job,
        along with its interface lock. Other render jobs, modal bake operations
        and compositor leases still defer publication. A host adapter can defer
        failed-ticket delivery until it has applied the policy-authorized failure.
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
                if not self._owns_render_lease_locked(ticket):
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
                if not self._owns_render_lease_locked(ticket):
                    raise PublicationDeferred("Render evaluation changed during preflight")
                self._committing = True
                acquired = True

            reason = self._activity_reason(render_preflight_job=expected_job)
            if reason is not None:
                raise PublicationDeferred(reason)
            with self._lock:
                if self._callbacks or not self._owns_render_lease_locked(ticket):
                    raise PublicationDeferred("Another native evaluation became active")
                self._preflight_scope = ticket, expected_job
            entered = True
            yield
        except BaseException as failure:
            error = failure
            raise
        finally:
            with self._lock:
                if acquired:
                    self._preflight_scope = None
                    self._committing = False
                if claimed and self._preflight_active is ticket:
                    retry = defer and not entered and isinstance(error, PublicationDeferred)
                    if retry:
                        self._preflight_active = None
                        # Admission can race with a second host reader. Keep
                        # the request live for the next foreground timer turn;
                        # only failures after yielding are terminal.
                        self._preflight_queue.appendleft(ticket)
                    elif (deliver_failure or (error is None
                            and ticket.state.phase == "released")):
                        self._preflight_active = None
            if claimed and not retry:
                if error is not None:
                    ticket.fail(error)
                elif ticket.state.phase == "waiting":
                    ticket.fail(RuntimeError(
                        "Render preflight exited without an exact publication receipt"))
                if (deliver_failure or ticket.state.phase == "released"):
                    ticket.deliver()

    def publish_render_preflight(self, ticket, *, scene_identity, frame, subframe,
                                 signature, published_signature):
        """Resolve the admitted ticket from the main thread's observed frame."""
        if threading.current_thread() is not threading.main_thread():
            raise PublicationDeferred("Render preflight publication requires Blender's main thread")
        with self._lock:
            scope = self._preflight_scope
            if (self._preflight_active is not ticket or scope is None
                    or scope[0] is not ticket or not self._committing
                    or self._callbacks or ticket._finished.is_set()):
                raise PublicationDeferred("Render preflight ticket is outside its admitted scope")
            if not self._owns_render_lease_locked(ticket):
                raise PublicationDeferred("Another native evaluation became active")
            expected_job = scope[1]

        reason = self._activity_reason(render_preflight_job=expected_job)
        if reason is not None:
            raise PublicationDeferred(reason)

        with self._lock:
            if (self._preflight_active is not ticket
                    or self._preflight_scope != scope or not self._committing
                    or self._callbacks or ticket._finished.is_set()
                    or not self._owns_render_lease_locked(ticket)):
                raise PublicationDeferred("Render preflight authorization changed before publication")
            return ticket._resolve(render_preflight.Event(
                "published", scene_identity=scene_identity, frame=frame, subframe=subframe,
                signature=signature, published_signature=published_signature,
            ))

    def finish_render_preflight_failure(self, ticket):
        """Deliver a terminal failure after the host adapter revokes output."""
        if threading.current_thread() is not threading.main_thread():
            raise RuntimeError("Render preflight failure requires Blender's main thread")
        with self._lock:
            if ticket.state.phase != "failed":
                return False
            if self._preflight_active is ticket:
                self._preflight_active = None
            elif ticket in self._preflight_queue:
                self._preflight_queue.remove(ticket)
            else:
                return False
        return ticket.deliver()
