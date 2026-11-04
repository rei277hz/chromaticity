"""Scalar gesture permissions; collection bookkeeping belongs to the runtime."""

from dataclasses import dataclass
from typing import Literal, Optional


@dataclass(frozen=True)
class State:
    serial: int = 0
    current_token: Optional[int] = None
    pending_token: Optional[int] = None


@dataclass(frozen=True)
class Effects:
    invoke_token: Optional[int] = None
    installed: bool = False
    report_failure: bool = False
    clear_registry: bool = False


@dataclass(frozen=True)
class Event:
    kind: Literal["window_seen", "handoff", "installed", "lost", "reset"]
    token: Optional[int] = None
    success: bool = False
    gesture_token: Optional[int] = None
    current_gesture_token: Optional[int] = None
    phase: Optional[str] = None


def new() -> State:
    return State()


def allocate(serial: int) -> int:
    return serial + 1


def input_allowed(current_token: Optional[int], token: Optional[int]) -> bool:
    return token is None or token == current_token


def press_handoff(token: Optional[int]) -> bool:
    return token is not None


def observer_status(current_token: Optional[int], pending_token: Optional[int],
                    token: int) -> Literal["current", "pending", "stale"]:
    if token == current_token:
        return "current"
    if token == pending_token:
        return "pending"
    return "stale"


def handoff_allowed(current_token: Optional[int], captured_token: Optional[int],
                    phase: Optional[str]) -> bool:
    return (captured_token is not None and current_token == captured_token
            and phase in ("armed", "active"))


def step(state: State, event: Event) -> tuple[State, Effects]:
    if event.kind == "reset":
        return State(state.serial), Effects(clear_registry=True)
    if event.kind == "installed":
        if event.token is None or event.token != state.pending_token:
            return state, Effects()
        return (State(state.serial, event.token if event.success else state.current_token),
                Effects(installed=event.success, report_failure=not event.success))
    if event.kind == "lost":
        if event.token is None:
            return state, Effects()
        if event.token == state.pending_token:
            return State(state.serial, state.current_token), Effects()
        if event.token == state.current_token:
            return State(state.serial, None, state.pending_token), Effects()
        return state, Effects()
    if event.kind == "window_seen":
        if state.current_token is not None:
            return state, Effects()
    elif (event.token is None or not input_allowed(state.current_token, event.token)
          or not handoff_allowed(event.current_gesture_token, event.gesture_token, event.phase)):
        return state, Effects()
    if state.pending_token is not None:
        return state, Effects()
    token = allocate(state.serial)
    return State(token, state.current_token, token), Effects(invoke_token=token)


def after_install(current_token: Optional[int], captured_token: Optional[int],
                  phase: Optional[str], latest: Literal["none", "move", "finish"]) -> Optional[str]:
    if captured_token is not None and current_token == captured_token:
        if latest == "finish":
            return "finish"
        if latest == "move":
            return "move"
    elif current_token is not None and phase in ("armed", "active"):
        return "handoff"
    return None


def activation_allowed(current_token: int, token: Optional[int], phase: str) -> bool:
    return token == current_token and phase == "armed"


def crossed_threshold(press_x: int, press_y: int, x: int, y: int) -> bool:
    return (x - press_x >= 3 or press_x - x >= 3
            or y - press_y >= 3 or press_y - y >= 3)


def deferred_phase(current_token: int, token: Optional[int], phase: str) -> Optional[str]:
    if token != current_token:
        return None
    if phase == "armed":
        return "finishing_armed"
    if phase == "active":
        return "finishing_active"
    return None


def observation_allowed(phase: Optional[str]) -> bool:
    return phase in ("finishing_armed", "finishing_active")


def finish_allowed(current_token: int, token: Optional[int]) -> bool:
    return token is not None and token == current_token


def participant_begin(shared: bool) -> Literal["refresh", "node_begin"]:
    return "refresh" if shared else "node_begin"


def active_participant(phase: str) -> bool:
    return phase in ("active", "finishing_active")


def armed_participant(phase: str) -> bool:
    return phase in ("armed", "finishing_armed")


def participant_finish(phase: str, live: bool, changed: bool, shared: bool) -> Optional[str]:
    if live:
        if phase in ("armed", "finishing_armed") and changed:
            return "refresh"
        if phase in ("active", "finishing_active") and not shared:
            return "node_release"
    return None


def manual_undo(owner: Literal["native", "adapter"], changed: bool) -> bool:
    return owner == "adapter" and changed
