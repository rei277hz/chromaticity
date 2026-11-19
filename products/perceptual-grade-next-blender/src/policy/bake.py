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


@dataclass(frozen=True)
class Event:
    kind: Literal[
        "request", "start", "completed", "publish", "published",
        "activated", "invalidate", "cancelled", "close",
    ]
    signature: Optional[str] = None
    current_signature: Optional[str] = None
    successful: bool = False
    error: Optional[str] = None


@dataclass(frozen=True)
class Effects:
    action: Optional[str] = None
    error: Optional[str] = None


@dataclass(frozen=True)
class Output:
    mode: Literal["live", "baked", "error"]
    error: Optional[str] = None
    revoke_receipt: bool = False


@dataclass(frozen=True)
class BindingEffects:
    receipt_signature: Optional[str] = None


def binding_policy(current_signature: Optional[str], artifact_valid: bool,
                   domains_match: bool) -> BindingEffects:
    """An explicit managed Image selection establishes this reader's baseline."""
    if artifact_valid and domains_match and current_signature is not None:
        return BindingEffects(current_signature)
    return BindingEffects()


def new() -> State:
    return State("idle")


def can_enqueue(accepted_count: int, node_busy: bool) -> bool:
    """Bound the caller-owned accepted-request queue and reserve one node."""
    return 0 <= accepted_count < MAX_ACCEPTED and not node_busy


def _current(state: State, event: Event) -> bool:
    return event.current_signature == state.signature


def step(state: State, event: Event) -> tuple[State, Effects]:
    """Authorize one request transition; the adapter executes its effects."""
    if state.phase == "terminal":
        return state, Effects()

    if event.kind == "request":
        if (state.phase != "idle"
                or event.signature is None or event.signature == ""):
            return state, Effects()
        queued = State("queued", event.signature)
        return queued, Effects("enqueue")

    if event.kind == "start":
        if state.phase != "queued":
            return state, Effects()
        running = State("running", state.signature)
        return running, Effects("start")

    if event.kind == "completed":
        if state.phase not in ("running", "cancelling"):
            return state, Effects()
        if state.phase == "cancelling":
            terminal = State("terminal")
            return terminal, Effects("discard", "Bake request cancelled")
        if not event.successful:
            error = ("Bake failed" if event.error is None else event.error)
            terminal = State("terminal")
            return terminal, Effects("retire", error)
        if not _current(state, event):
            terminal = State("terminal")
            return terminal, Effects("discard")
        ready = State("ready", state.signature)
        return ready, Effects()

    if event.kind == "publish":
        if state.phase != "ready":
            return state, Effects()
        if not _current(state, event):
            terminal = State("terminal")
            return terminal, Effects("discard")
        publishing = State("publishing", state.signature)
        return publishing, Effects("publish")

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
            terminal = State("terminal")
            return terminal, Effects("rollback", error)
        activating = State("activating", state.signature)
        return activating, Effects("activate")

    if event.kind == "activated":
        if state.phase != "activating":
            return state, Effects()
        if event.successful and _current(state, event):
            terminal = State("terminal")
            return terminal, Effects("retire")
        error = "Bake activation failed" if event.error is None else event.error
        terminal = State("terminal")
        return terminal, Effects("rollback", error)

    if event.kind == "invalidate":
        if event.current_signature == state.signature:
            return state, Effects()
        if state.phase == "running":
            cancelling = State("cancelling", state.signature)
            return cancelling, Effects("cancel")
        if state.phase in ("queued", "ready"):
            terminal = State("terminal")
            return terminal, Effects("discard")
        if state.phase in ("publishing", "activating"):
            # The transaction owns rollback once publication starts.
            return state, Effects()
        return state, Effects()

    if event.kind == "cancelled":
        if state.phase != "cancelling":
            return state, Effects()
        terminal = State("terminal")
        return terminal, Effects("retire")

    if event.kind == "close":
        if state.phase in ("queued", "ready"):
            terminal = State("terminal")
            return terminal, Effects("discard")
        if state.phase == "running":
            cancelling = State("cancelling", state.signature)
            return cancelling, Effects("cancel")
        return state, Effects()

    return state, Effects()


def bake_toggle_available(desired_signature: Optional[str],
                          artifact_signature: Optional[str],
                          artifact_valid: bool,
                          live_error: Optional[str] = None) -> bool:
    """Availability is independent of the user's persisted switch value."""
    return (live_error is None and artifact_valid
            and desired_signature is not None and artifact_signature is not None
            and desired_signature == artifact_signature)


def output_policy(use_bake: bool, desired_signature: Optional[str],
                  artifact_signature: Optional[str], artifact_valid: bool,
                  live_error: Optional[str] = None,
                  source_invalidated: bool = False) -> Output:
    """Select a node's current output while preserving image binding on bypass."""
    stale = (artifact_signature is not None
             and (source_invalidated or (desired_signature is not None
                                        and desired_signature != artifact_signature)))
    if live_error is not None:
        return Output("error", live_error, stale)
    if not use_bake:
        return Output("live", revoke_receipt=stale)
    if not artifact_valid:
        return Output("error", "Bound bake Image is unavailable or invalid", stale)
    if source_invalidated or not bake_toggle_available(
            desired_signature, artifact_signature, artifact_valid):
        return Output("live", revoke_receipt=stale)
    return Output("baked")


