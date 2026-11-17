"""Single-handle ownership permissions for reversible Color authoring."""

# pg-book: technical-report/en#next-policy.color-authoring

from dataclasses import dataclass
from typing import Literal, Optional


@dataclass(frozen=True)
class State:
    origin_handle: Optional[int] = None


@dataclass(frozen=True)
class Event:
    kind: Literal["manual", "push", "restore", "clear"]
    origin_handle: Optional[int] = None
    at_baseline: bool = False


@dataclass(frozen=True)
class Effects:
    action: Optional[str] = None


def new() -> State:
    return State()


def step(state: State, event: Event) -> tuple[State, Effects]:
    if event.kind in ("manual", "clear"):
        if state.origin_handle is None:
            return state, Effects()
        return State(), Effects("clear")
    if event.kind == "push":
        if event.origin_handle is None or not 0 <= event.origin_handle < 6:
            return state, Effects()
        if state.origin_handle == event.origin_handle:
            return state, Effects()
        return State(event.origin_handle), Effects("capture")
    if (event.kind == "restore" and state.origin_handle is not None
            and event.origin_handle == state.origin_handle and event.at_baseline):
        return State(), Effects("clear")
    return state, Effects()
