"""Bounded immutable-image allocation and reversible binding transactions."""

from dataclasses import dataclass
from typing import Literal, Optional


@dataclass(frozen=True)
class State:
    phase: Literal["idle", "stage", "snapshot", "bind", "commit", "activate",
                   "deliver", "restore_bindings", "restore_metadata",
                   "restore_resource", "fail", "retire", "terminal"]


@dataclass(frozen=True)
class Event:
    failed: bool = False
    clean: bool = False


@dataclass(frozen=True)
class Effects:
    action: Optional[str] = None


def candidate_effect(count: int, available: bool, exposed: bool) -> Effects:
    if available:
        return Effects("reuse") if not exposed else Effects()
    if 0 <= count and count < 3:
        return Effects("allocate")
    return Effects()


def retirement_effect(live: bool, quiescent: bool, current: bool,
                      candidate: bool, users: int, protected: bool) -> Effects:
    if current or candidate:
        return Effects()
    if not live:
        return Effects("evict")
    if quiescent and users == 0 and not protected:
        return Effects("remove")
    return Effects()


def new() -> State:
    return State("idle")


def step(state: State, event: Event) -> tuple[State, Effects]:
    if state.phase == "idle":
        return State("stage"), Effects("stage")
    if state.phase == "stage":
        if event.failed or not event.clean:
            return State("fail"), Effects("fail")
        return State("snapshot"), Effects("snapshot")
    if state.phase == "snapshot":
        if event.failed:
            return State("fail"), Effects("fail")
        return State("bind"), Effects("bind")
    if state.phase in ("bind", "commit", "activate", "deliver"):
        if event.failed:
            return State("restore_bindings"), Effects("restore_bindings")
        if state.phase == "bind":
            return State("commit"), Effects("commit")
        if state.phase == "commit":
            return State("activate"), Effects("activate")
        if state.phase == "activate":
            return State("deliver"), Effects("deliver")
        return State("retire"), Effects("retire")
    # Every restoration is attempted even if an earlier restoration failed.
    # Fail-closed delivery is mandatory after a failed binding transaction.
    if state.phase == "restore_bindings":
        return State("restore_metadata"), Effects("restore_metadata")
    if state.phase == "restore_metadata":
        return State("restore_resource"), Effects("restore_resource")
    if state.phase == "restore_resource":
        return State("fail"), Effects("fail")
    if state.phase == "fail":
        return State("retire"), Effects("retire")
    if state.phase == "retire":
        return State("terminal"), Effects()
    return state, Effects()
