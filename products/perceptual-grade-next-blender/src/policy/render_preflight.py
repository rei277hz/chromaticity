"""Authorize a render frame only after its exact Grade signature is published."""

from dataclasses import dataclass
from typing import Literal, Optional


@dataclass(frozen=True)
class State:
    phase: Literal["waiting", "released", "failed"]
    render_identity: int
    scene_identity: int
    frame: int
    subframe: str
    generation: int
    signature: Optional[str] = None
    error: Optional[str] = None


@dataclass(frozen=True)
class Event:
    kind: Literal["published", "failed"]
    render_identity: int
    scene_identity: int
    frame: int
    subframe: str
    generation: int
    signature: Optional[str] = None
    published_signature: Optional[str] = None
    error: Optional[str] = None


@dataclass(frozen=True)
class Effects:
    action: Optional[str] = None
    error: Optional[str] = None


def new(render_identity: int, scene_identity: int, frame: int,
        subframe: str, generation: int) -> State:
    return State("waiting", render_identity, scene_identity, frame, subframe,
                 generation)


def step(state: State, event: Event) -> tuple[State, Effects]:
    if state.phase != "waiting":
        return state, Effects()
    if event.generation != state.generation:
        return state, Effects()
    if (event.render_identity != state.render_identity
            or event.scene_identity != state.scene_identity
            or event.frame != state.frame or event.subframe != state.subframe):
        failed = State("failed", state.render_identity, state.scene_identity,
                       state.frame, state.subframe, state.generation,
                       error="Render preflight correlation changed")
        return failed, Effects("fail", failed.error)
    if event.kind == "failed":
        error = (event.error if event.error is not None
                 else "Grade render preflight failed")
        failed = State("failed", state.render_identity, state.scene_identity,
                       state.frame, state.subframe, state.generation, error=error)
        return failed, Effects("fail", error)
    if event.kind != "published":
        return state, Effects()
    if (event.signature is None or event.error is not None
            or event.published_signature != event.signature):
        error = (event.error if event.error is not None
                 else "Published Grade does not match this render frame")
        failed = State("failed", state.render_identity, state.scene_identity,
                       state.frame, state.subframe, state.generation,
                       signature=event.signature, error=error)
        return failed, Effects("fail", error)
    released = State("released", state.render_identity, state.scene_identity,
                     state.frame, state.subframe, state.generation,
                     signature=event.signature)
    return released, Effects("release")
