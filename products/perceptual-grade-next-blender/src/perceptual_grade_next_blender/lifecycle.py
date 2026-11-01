"""Small composition layer for the portable Next lifecycle machines.

These classes keep Blender effects at the edge: they produce checked value
events and never call RNA from a worker.  A host integration can feed the
returned events to its native/effect gateway and then acknowledge the exact
submission or operation.
"""

from dataclasses import dataclass

from ..perceptual_grade_next_core.workflow import (
    ProjectEvent, ScopeEvent, new_project, new_scope, project_ready,
    project_step, scope_has_current_input, scope_step,
)
from ..perceptual_grade_next_core.workflow.scope_view import (
    ScopeViewEvent, ScopeViewState, scope_view_step,
)
from ..perceptual_grade_next_core.workflow.restart import (
    RestartEvent, new_restart, restart_step,
)
from ..perceptual_grade_next_core.workflow.foreground import (
    ForegroundEvent, foreground_can_apply, foreground_step, new_foreground,
)


@dataclass(frozen=True)
class ViewDisplay:
    token: object
    owner: object
    view_epoch: int


class ViewAuthority:
    """Foreground adapter using the source-bound authority transition policy."""

    def __init__(self):
        self._state = new_foreground()
        self.display_token = None

    @property
    def owner(self):
        return self._state.owner if self._state.owner != 0 else None

    @property
    def view_epoch(self):
        return self._state.epoch

    @property
    def visible(self):
        return self._state.visible

    @property
    def state(self):
        return self._state

    def _step(self, kind, **values):
        values.setdefault("generation", self._state.generation)
        values.setdefault("owner", self._state.owner)
        values.setdefault("epoch", self._state.epoch)
        self._state, accepted = foreground_step(self._state, ForegroundEvent(kind, **values))
        return accepted

    def open(self, owner):
        if not _valid_identity(owner):
            raise ValueError("View owner must be a positive integer or nonempty string")
        if not self._step("open", owner=owner, generation=self._state.generation + 1,
                          epoch=self.view_epoch + 1):
            raise RuntimeError("Foreground policy rejected the new view")
        self.display_token = None
        return self.view_epoch

    def move(self, owner=None):
        if owner is not None:
            if not _valid_identity(owner):
                raise ValueError("View owner must be a positive integer or nonempty string")
        if not self._step("move", next_owner=0 if owner is None else owner,
                          epoch=self.view_epoch + 1):
            raise RuntimeError("Cannot move a closed view")
        self.display_token = None
        return self.view_epoch

    def close(self):
        self._step("close")
        self.display_token = None
        return self.view_epoch

    def issue(self, token, *, owner=None, view_epoch=None):
        owner = self.owner if owner is None else owner
        view_epoch = self.view_epoch if view_epoch is None else view_epoch
        if (not _valid_identity(token)
                or not self._step("issue", owner=owner, epoch=view_epoch, token=token)):
            raise RuntimeError("Cannot issue a display token for a closed view")
        display = ViewDisplay(token, owner, view_epoch)
        self.display_token = display
        return display

    def can_apply(self, display):
        return (isinstance(display, ViewDisplay) and display == self.display_token
                and foreground_can_apply(self._state, ForegroundEvent(
                    "apply", generation=self._state.generation, owner=display.owner,
                    epoch=display.view_epoch, token=display.token,
                )))

    def apply(self, display):
        """Consume the current foreground adoption receipt exactly once."""
        return self.can_apply(display) and self._step(
            "apply", owner=display.owner, epoch=display.view_epoch, token=display.token,
        )


def _issue_scope_view(actor, view, token):
    scope = actor.state
    foreground = view.state
    scope_event = ScopeEvent(
        "display_issued", generation=scope.generation, owner=scope.owner,
        view_epoch=scope.view_epoch, playback_epoch=scope.playback_epoch,
        request=scope.accepted_request, source_revision=scope.source_revision,
        source_id=scope.accepted_source, token=token,
    )
    view_event = ForegroundEvent(
        "issue", generation=foreground.generation, owner=foreground.owner,
        epoch=foreground.epoch, token=token,
    )
    next_state, accepted = scope_view_step(
        ScopeViewState(scope, foreground),
        ScopeViewEvent("issue", scope_event, view_event),
    )
    if accepted:
        actor.state = next_state.scope
        view._state = next_state.view
        view.display_token = ViewDisplay(token, view.owner, view.view_epoch)
    return accepted


def _apply_scope_view(actor, view, display):
    scope = actor.state
    foreground = view.state
    scope_event = ScopeEvent(
        "display_applied", generation=scope.generation, owner=scope.owner,
        view_epoch=scope.view_epoch, playback_epoch=scope.playback_epoch,
        request=scope.accepted_request, source_revision=scope.source_revision,
        source_id=scope.accepted_source, token=display.token,
    )
    view_event = ForegroundEvent(
        "apply", generation=foreground.generation, owner=display.owner,
        epoch=display.view_epoch, token=display.token,
    )
    next_state, accepted = scope_view_step(
        ScopeViewState(scope, foreground),
        ScopeViewEvent("apply", scope_event, view_event),
    )
    if accepted:
        actor.state = next_state.scope
        view._state = next_state.view
    return accepted


def _close_scope_view(actor, view):
    scope = actor.state
    foreground = view.state
    scope_event = ScopeEvent(
        "close", generation=scope.generation, owner=scope.owner,
    )
    view_event = ForegroundEvent(
        "close", generation=foreground.generation, owner=foreground.owner,
    )
    next_state, accepted = scope_view_step(
        ScopeViewState(scope, foreground),
        ScopeViewEvent("close", scope_event, view_event),
    )
    if accepted:
        actor.state = next_state.scope
        view._state = next_state.view
        view.display_token = None
    return accepted


def _move_scope_view(actor, view, owner, epoch):
    scope = actor.state
    foreground = view.state
    scope_event = ScopeEvent(
        "move", generation=scope.generation, owner=scope.owner,
        view_epoch=epoch,
    )
    view_event = ForegroundEvent(
        "move", generation=foreground.generation, owner=foreground.owner,
        epoch=epoch, next_owner=owner,
    )
    next_state, accepted = scope_view_step(
        ScopeViewState(scope, foreground),
        ScopeViewEvent("move", scope_event, view_event),
    )
    if accepted:
        actor.state = next_state.scope
        view._state = next_state.view
        view.display_token = None
    return accepted


def _open_scope_view(actor, view, generation, app_owner, view_owner):
    scope_event = ScopeEvent(
        "open", generation=generation, owner=app_owner,
        view_epoch=view.view_epoch + 1, playback_epoch=0,
    )
    view_event = ForegroundEvent(
        "open", generation=view.state.generation + 1, owner=view_owner,
        epoch=view.view_epoch + 1,
    )
    next_state, accepted = scope_view_step(
        ScopeViewState(actor.state, view.state),
        ScopeViewEvent("open", scope_event, view_event),
    )
    if accepted:
        actor.state = next_state.scope
        view._state = next_state.view
        view.display_token = None
    return accepted


@dataclass(frozen=True)
class ScopeSubmission:
    """Exact identity captured when a scope submission is admitted."""

    generation: int
    owner: object
    view_epoch: int
    playback_epoch: int
    request: int
    source_revision: int
    source_id: object
    submission: int


def _valid_identity(value):
    return ((type(value) is int and value > 0)
            or (type(value) is str and bool(value)))


class ScopeActor:
    """One global scope owner for an App."""

    def __init__(self):
        self.state = new_scope()
        self._demands = {}
        self._submissions = {}

    def _step(self, kind, **values):
        values.setdefault("generation", self.state.generation)
        values.setdefault("owner", self.state.owner)
        values.setdefault("view_epoch", self.state.view_epoch)
        values.setdefault("playback_epoch", self.state.playback_epoch)
        self.state, accepted = scope_step(self.state, ScopeEvent(kind, **values))
        return accepted

    def open(self, generation, owner, view_epoch=1, playback_epoch=0):
        self.state, accepted = scope_step(
            self.state, ScopeEvent("open", generation=generation, owner=owner,
                                   view_epoch=view_epoch, playback_epoch=playback_epoch)
        )
        return accepted

    def demand(self, request, source_revision, source_id):
        accepted = self._step("demand", request=request, source_revision=source_revision,
                              source_id=source_id)
        if accepted:
            self._demands[request] = ScopeSubmission(
                self.state.generation, self.state.owner, self.state.view_epoch,
                self.state.playback_epoch, request, source_revision, source_id, 0,
            )
        return accepted

    def begin(self, request, source_revision, source_id, submission):
        demand = self._demands.get(request)
        if (demand is None or demand.source_revision != source_revision
                or demand.source_id != source_id):
            return None
        accepted = scope_step(self.state, ScopeEvent(
            "begin", generation=demand.generation, owner=demand.owner,
            view_epoch=demand.view_epoch, playback_epoch=demand.playback_epoch,
            request=demand.request, source_revision=demand.source_revision,
            source_id=demand.source_id, submission=submission,
        ))
        self.state, ok = accepted
        if not ok:
            return None
        # A demand occurrence may allocate one physical submission only.  A
        # retry gets a new demand or explicit retry identity; repeated begin
        # calls for the same occurrence cannot create a second handle.
        self._demands.pop(request, None)
        ticket = ScopeSubmission(
            demand.generation, demand.owner, demand.view_epoch,
            demand.playback_epoch, demand.request, demand.source_revision,
            demand.source_id, submission,
        )
        self._submissions[submission] = ticket
        return ticket

    def complete(self, ticket):
        ticket = self._ticket(ticket)
        if ticket is None:
            return False
        self.state, accepted = scope_step(self.state, ScopeEvent(
            "complete", generation=ticket.generation, owner=ticket.owner,
            view_epoch=ticket.view_epoch, playback_epoch=ticket.playback_epoch,
            request=ticket.request, source_revision=ticket.source_revision,
            source_id=ticket.source_id, submission=ticket.submission,
        ))
        if accepted:
            self._submissions.pop(ticket.submission, None)
        return accepted

    def cancel(self, ticket):
        return self._submission_event("cancel", ticket)

    def fail(self, ticket):
        return self._submission_event("fail", ticket)

    def retire(self, ticket):
        ticket = self._ticket(ticket)
        if ticket is None:
            return False
        accepted = self._submission_event("retired", ticket)
        if accepted:
            self._submissions.pop(ticket.submission, None)
        return accepted

    def _ticket(self, ticket):
        if type(ticket) is int:
            ticket = self._submissions.get(ticket)
        if not isinstance(ticket, ScopeSubmission):
            return None
        return ticket if self._submissions.get(ticket.submission) == ticket else None

    def _submission_event(self, kind, ticket):
        ticket = self._ticket(ticket)
        if ticket is None:
            return False
        self.state, accepted = scope_step(self.state, ScopeEvent(
            kind, generation=ticket.generation, owner=ticket.owner,
            view_epoch=ticket.view_epoch, playback_epoch=ticket.playback_epoch,
            request=ticket.request, source_revision=ticket.source_revision,
            source_id=ticket.source_id, submission=ticket.submission,
        ))
        return accepted

    def close(self):
        return self._step("close")

    def move(self, view_epoch):
        return self._step("move", view_epoch=view_epoch)

    def playback_start(self, playback_epoch):
        return self._step("playback_start", playback_epoch=playback_epoch)

    def playback_stop(self):
        return self._step("playback_stop")

    def issue_display(self, token):
        """Admit a staged visual for the actor's current accepted input."""
        if not self.has_current_input() or not _valid_identity(token):
            return False
        self.state, accepted = scope_step(self.state, ScopeEvent(
            "display_issued", generation=self.state.generation,
            owner=self.state.owner, view_epoch=self.state.view_epoch,
            playback_epoch=self.state.playback_epoch,
            request=self.state.request, source_revision=self.state.source_revision,
            source_id=self.state.source_id, token=token,
        ))
        return accepted

    def apply_display(self, token):
        """Acknowledge foreground adoption of an issued visual."""
        if not _valid_identity(token):
            return False
        self.state, accepted = scope_step(self.state, ScopeEvent(
            "display_applied", generation=self.state.generation,
            owner=self.state.owner, view_epoch=self.state.view_epoch,
            playback_epoch=self.state.playback_epoch,
            request=self.state.request, source_revision=self.state.source_revision,
            source_id=self.state.source_id, token=token,
        ))
        return accepted

    def has_current_input(self):
        return scope_has_current_input(self.state)


class ProjectWorkflow:
    """Project-level preparation/Bake/Save/Render authority."""

    def __init__(self):
        self.state = new_project()

    def reset(self):
        """Begin a fresh document epoch without invalidating adapter handles."""
        self.state = new_project()
        return self.state

    def dispatch(self, kind, **values):
        values.setdefault("generation", self.state.generation)
        self.state, accepted = project_step(self.state, ProjectEvent(kind, **values))
        return accepted

    @property
    def ready(self):
        return project_ready(self.state)


class RestartSupervisor:
    """Extension-lifetime restart fence, independent of a failed App actor."""

    def __init__(self):
        self._state = new_restart()

    @property
    def generation(self):
        return self._state.generation

    @property
    def phase(self):
        return "restarting" if self._state.phase == "draining" else self._state.phase

    @property
    def required_cleanup(self):
        return frozenset(self._state.obligations)

    @property
    def cleanup_receipts(self):
        return frozenset(self._state.retired)

    def _dispatch(self, kind, **values):
        self._state, accepted = restart_step(
            self._state, RestartEvent(kind, generation=self.generation, **values),
        )
        return accepted

    def request(self, required=()):
        if self.phase not in {"active", "failed"}:
            return False
        required = tuple(required)
        if (any(not ((type(value) is int and value > 0)
                    or (type(value) is str and bool(value))) for value in required)
                or len(set(required)) != len(required)):
            return False
        generation = self.generation + 1
        self._state, accepted = restart_step(
            self._state,
            RestartEvent("request", generation=generation, obligations=required),
        )
        return generation if accepted else False

    def fail(self):
        return self._dispatch("fail")

    def receipt(self, identity):
        return self._dispatch("retire", identity=identity)

    def complete(self, required=None):
        if self.phase != "restarting":
            return False
        required = self.required_cleanup if required is None else frozenset(required)
        if required != self.required_cleanup:
            return False
        return self._dispatch("complete")


__all__ = (
    "ProjectWorkflow", "RestartSupervisor", "ScopeActor", "ScopeSubmission",
    "ViewAuthority", "ViewDisplay",
)
