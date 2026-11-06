"""Permit one live supersession, then protect a later compositor result."""

from dataclasses import dataclass
from typing import Literal, Optional


@dataclass(frozen=True)
class State:
    scene_id: Optional[int] = None
    epoch: Optional[int] = None


@dataclass(frozen=True)
class Event:
    kind: Literal["admit", "superseded", "finished", "reset"]
    scene_id: Optional[int] = None
    epoch: Optional[int] = None
    eligible: bool = False
    successful: bool = False
    quiescent: bool = False


@dataclass(frozen=True)
class Effects:
    publish_epoch: Optional[int] = None


def new() -> State:
    return State()


def step(state: State, event: Event) -> tuple[State, Effects]:
    if event.kind == "reset":
        if event.quiescent:
            return new(), Effects()
        return state, Effects()
    if event.kind == "finished":
        if (event.successful and state.scene_id is not None
                and event.scene_id == state.scene_id and state.epoch is not None
                and event.epoch is not None and event.epoch > state.epoch):
            return new(), Effects()
        return state, Effects()
    if (not event.eligible or event.scene_id is None or event.scene_id <= 0
            or event.epoch is None or event.epoch <= 0
            or state.scene_id is not None or state.epoch is not None):
        return state, Effects()
    if event.kind == "admit":
        return state, Effects(event.epoch)
    if event.kind == "superseded":
        return State(event.scene_id, event.epoch), Effects()
    return state, Effects()
