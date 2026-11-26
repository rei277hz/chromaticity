"""Authorize a render frame only after its exact Grade signature is published."""

# pg-book: technical-report/en#grade-policy.render-preflight

from dataclasses import dataclass
from typing import Literal, Optional


@dataclass(frozen=True)
class State:
    phase: Literal["waiting", "released", "failed"]
    scene_identity: int
    frame: int
    subframe: str
    error: Optional[str] = None


@dataclass(frozen=True)
class Event:
    kind: Literal["published", "failed"]
    scene_identity: Optional[int] = None
    frame: Optional[int] = None
    subframe: Optional[str] = None
    signature: Optional[str] = None
    published_signature: Optional[str] = None
    error: Optional[str] = None


@dataclass(frozen=True)
class Effects:
    action: Optional[str] = None
    error: Optional[str] = None


def new(scene_identity: int, frame: int, subframe: str) -> State:
    return State("waiting", scene_identity, frame, subframe)


def step(state: State, event: Event) -> tuple[State, Effects]:
    if state.phase != "waiting":
        return state, Effects()
    if event.kind == "failed":
        error = (event.error if event.error is not None
                 else "Grade render preflight failed")
        failed = State("failed", state.scene_identity, state.frame,
                       state.subframe, error=error)
        return failed, Effects("fail", error)
    if event.kind != "published":
        return state, Effects()
    if (event.scene_identity != state.scene_identity
            or event.frame != state.frame or event.subframe != state.subframe):
        error = "Render preflight observation changed"
        failed = State("failed", state.scene_identity, state.frame,
                       state.subframe, error=error)
        return failed, Effects("fail", error)
    if (event.signature is None or event.error is not None
            or event.published_signature != event.signature):
        error = (event.error if event.error is not None
                 else "Published Grade does not match this render frame")
        failed = State("failed", state.scene_identity, state.frame,
                       state.subframe, error=error)
        return failed, Effects("fail", error)
    released = State("released", state.scene_identity, state.frame,
                     state.subframe)
    return released, Effects("release")
