"""Checked value policy for the one global scope actor."""
from dataclasses import dataclass, replace
from typing import Literal

def _identity(value: int | str) -> bool:
    return value != 0 and value != ""

@dataclass(frozen=True)
class ScopeState:
    generation: int = 0
    owner: int | str = 0
    view_epoch: int = 0
    playback_epoch: int = 0
    phase: Literal["idle", "healthy", "capturing", "analyzing", "retiring", "failed", "closed"] = "idle"
    physical: Literal["none", "live", "retiring"] = "none"
    playing: bool = False
    request: int = 0
    begun_request: int = 0
    source_revision: int = 0
    source_id: int | str = 0
    submission: int = 0
    accepted_request: int = 0
    accepted_source: int | str = 0
    pending_request: int = 0
    pending_source: int | str = 0
    closing: bool = False
    cancelled: bool = False
    failure_pending: bool = False
    display_token: int | str = 0
    applied_token: int | str = 0

@dataclass(frozen=True)
class ScopeEvent:
    kind: str
    generation: int = 0
    owner: int | str = 0
    view_epoch: int = 0
    playback_epoch: int = 0
    request: int = 0
    source_revision: int = 0
    source_id: int | str = 0
    submission: int = 0
    token: int | str = 0

def new_scope() -> ScopeState:
    return ScopeState()

def _current(state: ScopeState, event: ScopeEvent, view: bool = False) -> bool:
    return (state.phase != "closed" and event.generation == state.generation and event.owner == state.owner
            and (not view or event.view_epoch == state.view_epoch))

def _has_live_submission(state: ScopeState) -> bool:
    return state.submission > 0 and state.physical in ("live", "retiring")

def _same_submission(state: ScopeState, event: ScopeEvent) -> bool:
    return (event.generation == state.generation and event.owner == state.owner
            and event.submission == state.submission)

def scope_step(state: ScopeState, event: ScopeEvent) -> tuple[ScopeState, bool]:
    if event.kind == "open":
        if _identity(event.owner) and event.generation > state.generation and event.view_epoch > state.view_epoch:
            return ScopeState(generation=event.generation, owner=event.owner, view_epoch=event.view_epoch,
                              playback_epoch=event.playback_epoch, phase="healthy"), True
        return state, False
    if event.kind == "move":
        if not _current(state, event) or event.view_epoch <= state.view_epoch: return state, False
        live = _has_live_submission(state)
        return replace(state, view_epoch=event.view_epoch,
                       phase="retiring" if live else state.phase,
                       physical="retiring" if live else "none",
                       cancelled=state.cancelled or state.phase in ("capturing", "analyzing"),
                       accepted_request=0, accepted_source=0), True
    if event.kind == "close":
        if not _current(state, event): return state, False
        if _has_live_submission(state):
            return replace(state, phase="retiring", physical="retiring", closing=True, cancelled=True), True
        return replace(state, phase="closed", closing=True), True
    if event.kind == "playback_start":
        if not _current(state, event) or event.playback_epoch <= state.playback_epoch: return state, False
        if state.phase in ("capturing", "analyzing") and _has_live_submission(state):
            return replace(state, phase="retiring", playback_epoch=event.playback_epoch,
                           physical="retiring", playing=True, cancelled=True,
                           display_token=0, applied_token=0), True
        return replace(state, playback_epoch=event.playback_epoch, playing=True,
                       display_token=0, applied_token=0), True
    if event.kind == "playback_stop":
        if not _current(state, event) or event.playback_epoch != state.playback_epoch: return state, False
        if state.phase == "retiring" and state.physical == "none" and not state.closing:
            return replace(state, phase="healthy", cancelled=False, playing=False), True
        if state.phase == "healthy" and state.playing:
            return replace(state, playing=False), True
        return state, False
    # Physical completion belongs to the original generation/submission even
    # when a view move has already advanced the foreground epoch.
    if event.kind == "retired":
        if (state.phase != "retiring" or state.physical != "retiring"
                or not _same_submission(state, event)):
            return state, False
        if state.closing:
            return replace(state, phase="closed", physical="none", submission=0), True
        if state.failure_pending:
            return replace(state, phase="failed", physical="none", submission=0,
                           failure_pending=False), True
        return replace(state, phase="healthy", physical="none", submission=0, cancelled=False), True
    if event.kind == "complete":
        active = (state.phase in ("capturing", "analyzing", "retiring")
                  and state.physical in ("live", "retiring")
                  and state.submission > 0
                  and event.generation == state.generation
                  and event.owner == state.owner
                  and event.submission == state.submission)
        if not active: return state, False
        if state.closing:
            return replace(state, phase="closed", physical="none", submission=0), True
        if state.failure_pending:
            return replace(state, phase="failed", physical="none", submission=0), True
        current = (not state.cancelled and event.request > 0 and event.source_revision > 0
                   and _identity(event.source_id) and event.view_epoch == state.view_epoch
                   and event.request == state.request and event.source_revision == state.source_revision
                   and event.source_id == state.source_id)
        if current:
            return replace(state, phase="healthy", physical="none", submission=0,
                           accepted_request=event.request, accepted_source=event.source_id), True
        return replace(state, phase="healthy", physical="none", submission=0, cancelled=False), True
    if event.kind == "fail":
        ok = (state.phase in ("capturing", "analyzing") and state.physical == "live"
              and state.submission > 0 and _same_submission(state, event))
        return (replace(state, phase="retiring", physical="retiring", cancelled=True,
                        failure_pending=True), True) if ok else (state, False)
    if event.kind == "cancel":
        ok = (state.phase in ("capturing", "analyzing") and state.physical == "live"
              and state.submission > 0 and _same_submission(state, event))
        return (replace(state, phase="retiring", physical="retiring", cancelled=True,
                        failure_pending=False), True) if ok else (state, False)
    if not _current(state, event, view=True): return state, False
    if event.kind == "demand":
        if (state.closing or state.playing or event.playback_epoch != state.playback_epoch or event.request <= state.request
                or event.source_revision <= 0 or not _identity(event.source_id)): return state, False
        live = _has_live_submission(state)
        return replace(state, phase="retiring" if live else "healthy",
                       physical="retiring" if live else "none",
                       request=event.request, source_revision=event.source_revision, source_id=event.source_id,
                       pending_request=event.request if live else 0,
                       pending_source=event.source_id if live else 0,
                       cancelled=state.cancelled if live else False,
                       display_token=0, applied_token=0), True
    if event.kind == "begin":
        ok = (not state.closing and not state.playing and not state.cancelled
              and state.phase == "healthy" and state.physical == "none"
              and event.request > 0 and event.request == state.request
              and event.request > state.begun_request
              and event.source_revision > 0 and _identity(event.source_id)
              and event.source_id == state.source_id and event.source_revision == state.source_revision
              and event.submission > state.submission and event.submission > 0
              and event.playback_epoch == state.playback_epoch)
        return (replace(state, phase="capturing", physical="live", submission=event.submission,
                        begun_request=event.request,
                        cancelled=False, failure_pending=False,
                        pending_request=0, pending_source=0), True) if ok else (state, False)
    if event.kind == "retry":
        ok = state.phase == "failed" and state.physical == "none" and not state.closing and event.submission > state.submission
        return (replace(state, phase="healthy", submission=event.submission), True) if ok else (state, False)
    if event.kind == "display_issued":
        ok = (_identity(event.token) and scope_has_current_input(state) and not state.playing
              and event.request == state.accepted_request and event.source_id == state.accepted_source
              and event.token != state.display_token)
        return (replace(state, display_token=event.token), True) if ok else (state, False)
    if event.kind == "display_applied":
        ok = (_identity(event.token) and event.token == state.display_token
              and event.token != state.applied_token and scope_has_current_input(state)
              and not state.playing and event.request == state.accepted_request
              and event.source_id == state.accepted_source)
        return (replace(state, applied_token=event.token), True) if ok else (state, False)
    return state, False

def scope_has_current_input(state: ScopeState) -> bool:
    return state.phase == "healthy" and state.accepted_request == state.request and state.accepted_source == state.source_id and _identity(state.accepted_source)


@dataclass(frozen=True)
class ForegroundState:
    generation: int = 0
    owner: int | str = 0
    epoch: int = 0
    visible: bool = False
    token: int | str = 0
    applied_token: int | str = 0


@dataclass(frozen=True)
class ForegroundEvent:
    kind: str
    generation: int = 0
    owner: int | str = 0
    epoch: int = 0
    token: int | str = 0
    next_owner: int | str = 0


def new_foreground() -> ForegroundState:
    return ForegroundState()


def foreground_can_apply(state: ForegroundState, event: ForegroundEvent) -> bool:
    return (state.visible and event.generation == state.generation and event.owner == state.owner
            and event.epoch == state.epoch and event.token == state.token and _identity(event.token)
            and event.token != state.applied_token)


def foreground_step(state: ForegroundState, event: ForegroundEvent) -> tuple[ForegroundState, bool]:
    if event.kind == "open":
        accepted = (_identity(event.owner) and event.generation > state.generation
                    and event.epoch > state.epoch)
        return (ForegroundState(event.generation, event.owner, event.epoch, True, 0), True) if accepted else (state, False)
    if event.kind == "move":
        accepted = (state.visible and event.generation == state.generation
                    and event.owner == state.owner and event.epoch > state.epoch
                    and (event.next_owner == 0 or _identity(event.next_owner)))
        owner = state.owner if event.next_owner == 0 else event.next_owner
        return (replace(state, owner=owner, epoch=event.epoch, token=0, applied_token=0), True) if accepted else (state, False)
    if event.kind == "close":
        accepted = state.visible and event.generation == state.generation and event.owner == state.owner
        return (replace(state, visible=False, epoch=state.epoch + 1, token=0, applied_token=0), True) if accepted else (state, False)
    if event.kind == "issue":
        accepted = (state.visible and event.generation == state.generation and event.owner == state.owner
                    and event.epoch == state.epoch and _identity(event.token)
                    and event.token != state.token)
        return (replace(state, token=event.token), True) if accepted else (state, False)
    if event.kind == "apply":
        accepted = foreground_can_apply(state, event)
        return (replace(state, applied_token=event.token), True) if accepted else (state, False)
    return state, False


def scope_view_issue(scope: ScopeState, view: ForegroundState,
                     scope_event: ScopeEvent,
                     view_event: ForegroundEvent) -> tuple[ScopeState, ForegroundState, bool]:
    """Commit issue to both production policies or leave both unchanged."""
    compatible = (scope_event.kind == "display_issued" and view_event.kind == "issue"
                  and scope_event.token == view_event.token
                  and scope_event.generation == scope.generation
                  and scope_event.owner == scope.owner
                  and scope_event.view_epoch == view_event.epoch
                  and scope_event.view_epoch == scope.view_epoch
                  and scope_event.playback_epoch == scope.playback_epoch
                  and scope_event.request == scope.request
                  and scope_event.source_revision == scope.source_revision
                  and scope_event.source_id == scope.source_id
                  and view_event.generation == view.generation
                  and view_event.owner == view.owner)
    if not compatible:
        return scope, view, False
    next_scope, scope_ok = scope_step(scope, scope_event)
    next_view, view_ok = foreground_step(view, view_event)
    if not scope_ok or not view_ok:
        return scope, view, False
    return next_scope, next_view, True


def scope_view_apply(scope: ScopeState, view: ForegroundState,
                     scope_event: ScopeEvent,
                     view_event: ForegroundEvent) -> tuple[ScopeState, ForegroundState, bool]:
    """Commit adoption to both production policies or leave both unchanged."""
    compatible = (scope_event.kind == "display_applied" and view_event.kind == "apply"
                  and scope_event.token == view_event.token
                  and scope_event.generation == scope.generation
                  and scope_event.owner == scope.owner
                  and scope_event.view_epoch == view_event.epoch
                  and scope_event.view_epoch == scope.view_epoch
                  and scope_event.playback_epoch == scope.playback_epoch
                  and scope_event.request == scope.accepted_request
                  and scope_event.source_revision == scope.source_revision
                  and scope_event.source_id == scope.accepted_source
                  and view_event.generation == view.generation
                  and view_event.owner == view.owner)
    if not compatible:
        return scope, view, False
    next_scope, scope_ok = scope_step(scope, scope_event)
    next_view, view_ok = foreground_step(view, view_event)
    if not scope_ok or not view_ok:
        return scope, view, False
    return next_scope, next_view, True


def scope_view_close(scope: ScopeState, view: ForegroundState,
                     scope_event: ScopeEvent,
                     view_event: ForegroundEvent) -> tuple[ScopeState, ForegroundState, bool]:
    compatible = (scope_event.kind == "close" and view_event.kind == "close"
                  and scope_event.generation == scope.generation
                  and scope_event.owner == scope.owner
                  and view_event.generation == view.generation
                  and view_event.owner == view.owner)
    if not compatible:
        return scope, view, False
    next_scope, scope_ok = scope_step(scope, scope_event)
    next_view, view_ok = foreground_step(view, view_event)
    if not scope_ok or not view_ok:
        return scope, view, False
    return next_scope, next_view, True


def scope_view_move(scope: ScopeState, view: ForegroundState,
                    scope_event: ScopeEvent,
                    view_event: ForegroundEvent) -> tuple[ScopeState, ForegroundState, bool]:
    compatible = (scope_event.kind == "move" and view_event.kind == "move"
                  and scope_event.generation == scope.generation
                  and scope_event.owner == scope.owner
                  and view_event.generation == view.generation
                  and view_event.owner == view.owner
                  and scope_event.view_epoch == view_event.epoch
                  and scope_event.view_epoch > view.epoch)
    if not compatible:
        return scope, view, False
    next_scope, scope_ok = scope_step(scope, scope_event)
    next_view, view_ok = foreground_step(view, view_event)
    if not scope_ok or not view_ok:
        return scope, view, False
    return next_scope, next_view, True


def scope_view_open(scope: ScopeState, view: ForegroundState,
                    scope_event: ScopeEvent,
                    view_event: ForegroundEvent) -> tuple[ScopeState, ForegroundState, bool]:
    compatible = (scope_event.kind == "open" and view_event.kind == "open"
                  and scope_event.view_epoch == view_event.epoch)
    if not compatible:
        return scope, view, False
    next_scope, scope_ok = scope_step(scope, scope_event)
    next_view, view_ok = foreground_step(view, view_event)
    if not scope_ok or not view_ok:
        return scope, view, False
    return next_scope, next_view, True


@dataclass(frozen=True)
class ScopeViewState:
    scope: ScopeState
    view: ForegroundState


@dataclass(frozen=True)
class ScopeViewEvent:
    kind: Literal["open", "close", "move", "issue", "apply"]
    scope_event: ScopeEvent
    view_event: ForegroundEvent


def new_scope_view() -> ScopeViewState:
    return ScopeViewState(new_scope(), new_foreground())


def scope_view_step(state: ScopeViewState, event: ScopeViewEvent) -> tuple[ScopeViewState, bool]:
    if event.kind == "open":
        scope, view, accepted = scope_view_open(
            state.scope, state.view, event.scope_event, event.view_event,
        )
    elif event.kind == "close":
        scope, view, accepted = scope_view_close(
            state.scope, state.view, event.scope_event, event.view_event,
        )
    elif event.kind == "move":
        scope, view, accepted = scope_view_move(
            state.scope, state.view, event.scope_event, event.view_event,
        )
    elif event.kind == "issue":
        scope, view, accepted = scope_view_issue(
            state.scope, state.view, event.scope_event, event.view_event,
        )
    elif event.kind == "apply":
        scope, view, accepted = scope_view_apply(
            state.scope, state.view, event.scope_event, event.view_event,
        )
    else:
        return state, False
    return (ScopeViewState(scope, view), True) if accepted else (state, False)
