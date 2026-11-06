"""Decision policy for fixed two-bank helper-image publication."""

from dataclasses import dataclass
from typing import Literal, Optional


@dataclass(frozen=True)
class State:
    phase: Literal["idle", "stage", "select", "deliver", "restore_selector",
                   "fail", "terminal"]
    active_bank: Optional[int] = None
    candidate_bank: Optional[int] = None


@dataclass(frozen=True)
class Event:
    kind: Literal["begin", "staged", "selected", "delivered", "restored", "closed"]
    active_bank: Optional[int] = None
    candidate_bank: Optional[int] = None
    selected_bank: Optional[int] = None
    clean: bool = False
    failed: bool = False


@dataclass(frozen=True)
class Effects:
    action: Optional[str] = None
    bank: Optional[int] = None


def _valid_bank(index: Optional[int]) -> bool:
    return index in (0, 1)


def new() -> State:
    return State("idle")


def step(state: State, event: Event) -> tuple[State, Effects]:
    """Authorize staging, activation, and delivery in that order."""
    if state.phase == "idle":
        if event.kind != "begin":
            return state, Effects()
        if (event.failed or not _valid_bank(event.active_bank)
                or not _valid_bank(event.candidate_bank)
                or event.active_bank == event.candidate_bank):
            return State("fail"), Effects("fail_closed")
        return (State("stage", event.active_bank, event.candidate_bank),
                Effects("stage", event.candidate_bank))

    if state.phase == "stage":
        if event.kind != "staged":
            return state, Effects()
        if event.failed or not event.clean:
            return (State("fail", state.active_bank, state.candidate_bank),
                    Effects("fail_closed", state.active_bank))
        return (State("select", state.active_bank, state.candidate_bank),
                Effects("select", state.candidate_bank))

    if state.phase == "select":
        if event.kind != "selected":
            return state, Effects()
        if (event.failed or event.selected_bank != state.candidate_bank):
            return (State("restore_selector", state.active_bank, state.candidate_bank),
                    Effects("restore_selector", state.active_bank))
        return (State("deliver", state.active_bank, state.candidate_bank),
                Effects("deliver", state.candidate_bank))

    if state.phase == "deliver":
        if event.kind == "delivered" and event.failed:
            return (State("restore_selector", state.active_bank, state.candidate_bank),
                    Effects("restore_selector", state.active_bank))
        if event.kind != "delivered":
            return state, Effects()
        return State("terminal"), Effects()

    if state.phase == "restore_selector":
        if event.kind != "restored":
            return state, Effects()
        return (State("fail", state.active_bank, state.candidate_bank),
                Effects("fail_closed", state.active_bank))

    if state.phase == "fail":
        if event.kind == "closed":
            if event.failed:
                return state, Effects("fail_closed", state.active_bank)
            return State("terminal"), Effects()
        return state, Effects()

    return state, Effects()
