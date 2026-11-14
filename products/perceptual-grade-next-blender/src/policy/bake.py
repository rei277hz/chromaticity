"""Serialized bake requests and per-node baked-output policy."""

# pg-book: technical-report/en#next-policy.bake

from dataclasses import dataclass
from typing import Literal, Optional


MAX_ACCEPTED = 8


@dataclass(frozen=True)
class State:
    phase: Literal[
        "idle", "queued", "running", "cancelling", "ready",
        "publishing", "activating", "terminal",
    ]
    signature: Optional[str] = None
    generation: Optional[int] = None
    error: Optional[str] = None


@dataclass(frozen=True)
class Event:
    kind: Literal[
        "request", "start", "completed", "publish", "published",
        "activated", "invalidate", "cancelled", "close",
    ]
    signature: Optional[str] = None
    generation: Optional[int] = None
    current_signature: Optional[str] = None
    admitted: bool = False
    successful: bool = False
    error: Optional[str] = None


@dataclass(frozen=True)
class Effects:
    action: Optional[str] = None
    signature: Optional[str] = None
    generation: Optional[int] = None
    error: Optional[str] = None


@dataclass(frozen=True)
class Output:
    mode: Literal["live", "baked", "error"]
    use_bake: bool
    error: Optional[str] = None


def new() -> State:
    return State("idle")


def can_enqueue(accepted_count: int, node_busy: bool, admitted: bool) -> bool:
    """Bound the caller-owned accepted-request queue and reserve one node."""
    return (0 <= accepted_count < MAX_ACCEPTED and not node_busy and admitted)


def _matches(state: State, event: Event) -> bool:
    return (state.signature is not None and state.generation is not None
            and event.signature == state.signature
            and event.generation == state.generation)


def _current(state: State, event: Event) -> bool:
    return event.current_signature == state.signature


def _effects(state: State, action: Optional[str] = None,
             error: Optional[str] = None) -> Effects:
    if action is None:
        return Effects(error=state.error if error is None else error)
    return Effects(action, state.signature, state.generation,
                   state.error if error is None else error)


def step(state: State, event: Event) -> tuple[State, Effects]:
    """Authorize one request transition; the adapter executes its effects."""
    if state.phase == "terminal":
        return state, Effects()

    if event.kind == "request":
        if (state.phase != "idle" or not event.admitted
                or event.signature is None or event.signature == ""
                or event.generation is None or event.generation < 1):
            return state, Effects()
        queued = State("queued", event.signature, event.generation)
        return queued, _effects(queued, "enqueue")

    if not _matches(state, event):
        return state, Effects()

    if event.kind == "start":
        if state.phase != "queued" or not event.admitted:
            return state, Effects()
        running = State("running", state.signature, state.generation)
        return running, _effects(running, "start")

    if event.kind == "completed":
        if state.phase not in ("running", "cancelling"):
            return state, Effects()
        if state.phase == "cancelling":
            terminal = State("terminal", error="Bake request cancelled")
            return terminal, _effects(state, "discard", terminal.error)
        if not event.successful:
            error = ("Bake failed" if event.error is None else event.error)
            terminal = State("terminal", error=error)
            return terminal, _effects(state, "retire", terminal.error)
        if not _current(state, event):
            terminal = State("terminal")
            return terminal, _effects(state, "discard")
        ready = State("ready", state.signature, state.generation)
        return ready, Effects()

    if event.kind == "publish":
        if state.phase != "ready":
            return state, Effects()
        if not event.admitted:
            return state, Effects()
        if not _current(state, event):
            terminal = State("terminal")
            return terminal, _effects(state, "discard")
        publishing = State("publishing", state.signature, state.generation)
        return publishing, _effects(publishing, "publish")

    if event.kind == "published":
        if state.phase != "publishing":
            return state, Effects()
        if not event.successful or not _current(state, event):
            if event.error is not None:
                error = event.error
            elif not event.successful:
                error = "Bake publication failed"
            else:
                error = "Bake inputs changed before publication"
            terminal = State("terminal", error=error)
            return terminal, _effects(state, "rollback", error)
        activating = State("activating", state.signature, state.generation)
        return activating, _effects(activating, "activate")

    if event.kind == "activated":
        if state.phase != "activating":
            return state, Effects()
        if event.successful and _current(state, event):
            terminal = State("terminal")
            return terminal, _effects(state, "retire")
        error = "Bake activation failed" if event.error is None else event.error
        terminal = State("terminal", error=error)
        return terminal, _effects(state, "rollback", error)

    if event.kind == "invalidate":
        if event.current_signature == state.signature:
            return state, Effects()
        if state.phase == "running":
            cancelling = State("cancelling", state.signature, state.generation)
            return cancelling, _effects(cancelling, "cancel")
        if state.phase in ("queued", "ready"):
            terminal = State("terminal")
            return terminal, _effects(state, "discard")
        if state.phase in ("publishing", "activating"):
            # The transaction owns rollback once publication starts.
            return state, Effects()
        return state, Effects()

    if event.kind == "cancelled":
        if state.phase != "cancelling":
            return state, Effects()
        terminal = State("terminal")
        return terminal, _effects(state, "retire")

    if event.kind == "close":
        if state.phase in ("queued", "ready"):
            terminal = State("terminal")
            return terminal, _effects(state, "discard")
        if state.phase == "running":
            cancelling = State("cancelling", state.signature, state.generation)
            return cancelling, _effects(cancelling, "cancel")
        return state, Effects()

    return state, Effects()


def output_policy(use_bake: bool, desired_signature: Optional[str],
                  artifact_signature: Optional[str], artifact_valid: bool,
                  live_error: Optional[str] = None) -> Output:
    """Select a node's current output while preserving image binding on bypass."""
    if live_error is not None:
        return Output("error", False, live_error)
    if not use_bake:
        return Output("live", False)
    if not artifact_valid:
        return Output("error", False, "Bound bake Image is unavailable or invalid")
    if (desired_signature is None or artifact_signature is None
            or desired_signature != artifact_signature):
        return Output("live", False)
    return Output("baked", True)


