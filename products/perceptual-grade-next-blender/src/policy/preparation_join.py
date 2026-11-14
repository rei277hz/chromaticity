"""Authorize one complete Grade only after its three preparations retire."""

# pg-book: technical-report/en#next-policy.preparation-join

from dataclasses import dataclass
from typing import Literal, Optional


@dataclass(frozen=True)
class State:
    signature: str
    linear_pending: bool
    tone_pending: bool
    boundary_pending: bool
    error: Optional[str] = None


@dataclass(frozen=True)
class Event:
    signature: str
    component: Literal["linear", "tone", "boundary"]
    error: Optional[str] = None


@dataclass(frozen=True)
class Effects:
    completion_signature: Optional[str] = None
    error: Optional[str] = None


def new(signature: str) -> State:
    return State(signature, True, True, True)


def step(state: State, event: Event) -> tuple[State, Effects]:
    """Errors retain the slot until every physical child has retired.

    Payloads stay with the operation owner. A duplicate or stale receipt can
    neither replace that owner's payload nor authorize another completion.
    """
    if event.signature != state.signature:
        return state, Effects()
    linear = state.linear_pending
    tone = state.tone_pending
    boundary = state.boundary_pending
    if event.component == "linear":
        if not linear:
            return state, Effects()
        linear = False
    elif event.component == "tone":
        if not tone:
            return state, Effects()
        tone = False
    elif event.component == "boundary":
        if not boundary:
            return state, Effects()
        boundary = False
    else:
        return state, Effects()
    error = state.error if state.error is not None else event.error
    updated = State(state.signature, linear, tone, boundary, error)
    if linear or tone or boundary:
        return updated, Effects()
    return updated, Effects(state.signature, error)
