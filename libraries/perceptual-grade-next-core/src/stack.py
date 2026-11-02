"""Pure policy for the evaluation-relevant entries of an ordered Grade Stack."""

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class State:
    """Active Grade identities in occurrence order; repeated identities matter."""

    grade_ids: tuple[int, ...]


@dataclass(frozen=True)
class Event:
    kind: Literal["replace", "select", "grade_changed"]
    grade_ids: tuple[int, ...]
    grade_id: int


@dataclass(frozen=True)
class Effects:
    rebuild: bool = False


def new() -> State:
    return State(())


def step(state: State, event: Event) -> tuple[State, Effects]:
    """Apply a host-observed change to ordered, enabled, assigned Grade IDs.

    The Blender adapter filters disabled and unassigned occurrences before
    dispatch. It emits ``select`` only for sidebar focus changes and
    ``grade_changed`` when a referenced shared Grade's settings change.
    """
    if event.kind == "select":
        return state, Effects()
    if event.kind == "grade_changed":
        return state, Effects(event.grade_id in state.grade_ids)
    return State(event.grade_ids), Effects(state.grade_ids != event.grade_ids)
