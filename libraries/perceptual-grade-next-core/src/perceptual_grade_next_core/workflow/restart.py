"""Pure restart policy used by the Blender restart adapter.

The adapter owns physical cleanup observations; this machine owns the
generation fence and the exact obligation ledger.
"""
from dataclasses import dataclass, replace
from typing import Literal


def _identity(value: int | str) -> bool:
    return value != 0 and value != ""


@dataclass(frozen=True)
class RestartState:
    generation: int = 0
    phase: Literal["active", "draining", "failed"] = "active"
    obligations: tuple[int | str, ...] = ()
    retired: tuple[int | str, ...] = ()


@dataclass(frozen=True)
class RestartEvent:
    kind: str
    generation: int = 0
    obligations: tuple[int | str, ...] = ()
    identity: int | str = 0


def new_restart() -> RestartState:
    return RestartState()


def _contains(values: tuple[int | str, ...], value: int | str) -> bool:
    count_value = len(values)
    if count_value > 4:
        return False
    if count_value == 0:
        return False
    if count_value == 1:
        return values[0] == value
    if count_value == 2:
        return values[0] == value or values[1] == value
    if count_value == 3:
        return values[0] == value or values[1] == value or values[2] == value
    return (values[0] == value or values[1] == value
            or values[2] == value or values[3] == value)


def _unique(values: tuple[int | str, ...]) -> bool:
    count_value = len(values)
    if count_value > 4:
        return False
    if count_value < 2:
        return True
    if count_value == 2:
        return values[0] != values[1]
    if count_value == 3:
        return (values[0] != values[1] and values[0] != values[2]
                and values[1] != values[2])
    return (values[0] != values[1] and values[0] != values[2]
            and values[0] != values[3] and values[1] != values[2]
            and values[1] != values[3] and values[2] != values[3])


def _retire(values: tuple[int | str, ...], value: int | str) -> tuple[int | str, ...]:
    if _contains(values, value):
        return values
    return values + (value,)


def _same_members(left: tuple[int | str, ...], right: tuple[int | str, ...]) -> bool:
    count_value = len(left)
    if count_value != len(right) or count_value > 4:
        return False
    if count_value == 0:
        return True
    if not _unique(left) or not _unique(right):
        return False
    if count_value == 1:
        return left[0] == right[0]
    if count_value == 2:
        return ((left[0] == right[0] or left[0] == right[1])
                and (left[1] == right[0] or left[1] == right[1]))
    if count_value == 3:
        return ((left[0] == right[0] or left[0] == right[1] or left[0] == right[2])
                and (left[1] == right[0] or left[1] == right[1] or left[1] == right[2])
                and (left[2] == right[0] or left[2] == right[1] or left[2] == right[2]))
    return ((left[0] == right[0] or left[0] == right[1] or left[0] == right[2] or left[0] == right[3])
            and (left[1] == right[0] or left[1] == right[1] or left[1] == right[2] or left[1] == right[3])
            and (left[2] == right[0] or left[2] == right[1] or left[2] == right[2] or left[2] == right[3])
            and (left[3] == right[0] or left[3] == right[1] or left[3] == right[2] or left[3] == right[3]))


def restart_step(state: RestartState, event: RestartEvent) -> tuple[RestartState, bool]:
    if event.kind == "request":
        accepted = (state.phase in ("active", "failed") and event.generation > state.generation
                    and event.generation > 0 and _unique(event.obligations))
        return (RestartState(event.generation, "draining", event.obligations, ()), True) if accepted else (state, False)
    if event.kind == "fail":
        return (replace(state, phase="failed"), True) if state.phase == "draining" and event.generation == state.generation else (state, False)
    if event.kind == "retire":
        accepted = (state.phase == "draining" and event.generation == state.generation
                    and _identity(event.identity) and _contains(state.obligations, event.identity))
        return (replace(state, retired=_retire(state.retired, event.identity)), True) if accepted else (state, False)
    if event.kind == "complete":
        accepted = (state.phase == "draining" and event.generation == state.generation
                    and _same_members(state.retired, state.obligations))
        return (replace(state, phase="active", obligations=(), retired=()), True) if accepted else (state, False)
    return state, False

