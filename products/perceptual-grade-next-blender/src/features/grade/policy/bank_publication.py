"""Decision policy for fixed two-bank helper-image publication."""

# pg-book: technical-report/en#next-policy.bank-publication

from dataclasses import dataclass
from typing import Literal, Optional


@dataclass(frozen=True)
class State:
    phase: Literal["idle", "repair_gate", "stage", "select",
                   "deliver", "restore_selector", "fail", "terminal"]
    active_bank: Optional[int] = None
    close_retried: bool = False


@dataclass(frozen=True)
class Event:
    kind: Literal["begin", "staged", "selected", "delivered", "restored", "closed"]
    active_bank: Optional[int] = None
    selected_bank: Optional[int] = None
    clean: bool = False
    failed: bool = False
    admitted: bool = False
    active_valid: bool = False


@dataclass(frozen=True)
class Effects:
    action: Optional[str] = None
    bank: Optional[int] = None
    outcome: Optional[str] = None


def _inactive_bank(active_bank: Optional[int]) -> Optional[int]:
    return None if active_bank is None else 1 - active_bank


def request_save_packing(generated: bool, dirty: bool) -> bool:
    return generated and dirty


def finish_save_packing(clean: bool, error: Optional[str]) -> Optional[str]:
    if error is not None:
        return error
    if not clean:
        return "Grade parameter image could not be packed"
    return None


def new() -> State:
    return State("idle")


def step(state: State, event: Event) -> tuple[State, Effects]:
    """Authorize staging, activation, and delivery in that order."""
    if state.phase == "idle":
        if event.kind != "begin":
            return state, Effects()
        if event.failed or not event.admitted or event.active_bank not in (0, 1):
            return State("fail"), Effects("fail_closed")
        if not event.active_valid:
            return (State("repair_gate", event.active_bank),
                    Effects("fail_closed", event.active_bank))
        return (State("stage", event.active_bank),
                Effects("stage", _inactive_bank(event.active_bank)))

    if state.phase in ("repair_gate", "fail"):
        if event.kind != "closed":
            return state, Effects()
        if event.failed:
            if state.close_retried:
                return State("terminal"), Effects(outcome="indeterminate")
            return (State(state.phase, state.active_bank, close_retried=True),
                    Effects("fail_closed", state.active_bank))
        if state.phase == "repair_gate":
            return (State("stage", state.active_bank),
                    Effects("repair", _inactive_bank(state.active_bank)))
        return State("terminal"), Effects(outcome="failed_closed")

    if state.phase == "stage":
        if event.kind != "staged":
            return state, Effects()
        if event.failed or not event.clean:
            return (State("fail", state.active_bank),
                    Effects("fail_closed", state.active_bank))
        return (State("select", state.active_bank),
                Effects("select", _inactive_bank(state.active_bank)))

    if state.phase == "select":
        if event.kind != "selected":
            return state, Effects()
        candidate_bank = _inactive_bank(state.active_bank)
        if event.failed or event.selected_bank != candidate_bank:
            return (State("restore_selector", state.active_bank),
                    Effects("restore_selector", state.active_bank))
        return State("deliver", state.active_bank), Effects("deliver", candidate_bank)

    if state.phase == "deliver":
        if event.kind == "delivered" and event.failed:
            return (State("restore_selector", state.active_bank),
                    Effects("restore_selector", state.active_bank))
        if event.kind == "delivered":
            return State("terminal"), Effects(outcome="committed")

    if state.phase == "restore_selector":
        if event.kind != "restored":
            return state, Effects()
        return (State("fail", state.active_bank),
                Effects("fail_closed", state.active_bank))

    return state, Effects()
