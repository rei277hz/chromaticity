"""Admission and ordering policy for deferred Grade work."""

# pg-book: technical-report/en#grade-policy.scheduler

from dataclasses import dataclass
from typing import Literal, Optional


@dataclass(frozen=True)
class WorkPriority:
    """Stable ordering facts for one admitted task."""

    kind: str
    serial: int
    foreground: bool = False
    promoted: bool = False


def is_task_kind(kind: str) -> bool:
    return (kind == "render" or kind == "lifecycle" or kind == "plot"
            or kind == "consistency" or kind == "bake")


def rank(kind: str, promoted: bool) -> int:
    """Return the effective priority class without a mutable rank table."""
    if kind == "render":
        return 0
    if kind == "lifecycle":
        return 1
    if kind == "plot" or kind == "consistency" and promoted:
        return 2
    if kind == "consistency":
        return 3
    return 4


def precedes(candidate: WorkPriority, incumbent: WorkPriority) -> bool:
    """Return whether candidate should be selected before incumbent."""
    candidate_rank = rank(candidate.kind, candidate.promoted)
    incumbent_rank = rank(incumbent.kind, incumbent.promoted)
    if candidate_rank != incumbent_rank:
        return candidate_rank < incumbent_rank
    if candidate.kind == "plot" or candidate.promoted:
        if candidate.foreground != incumbent.foreground:
            return candidate.foreground
        return candidate.serial > incumbent.serial
    return candidate.serial < incumbent.serial


def may_preempt(candidate: WorkPriority, incumbent: WorkPriority) -> bool:
    """Authorize a cancellation request at the next worker checkpoint."""
    if rank(candidate.kind, candidate.promoted) < rank(incumbent.kind, incumbent.promoted):
        return True
    return ((candidate.kind == "plot" or candidate.promoted)
            and precedes(candidate, incumbent))


def retry_delay_ms(attempt: int) -> int:
    """Bounded retry delay in milliseconds for an owner-local failure."""
    if attempt < 1:
        raise ValueError("Retry attempt must be positive")
    if attempt == 1:
        return 200
    if attempt == 2:
        return 400
    if attempt == 3:
        return 800
    if attempt == 4:
        return 1600
    return 3200


@dataclass(frozen=True)
class State:
    phase: Literal["ready", "starting", "changing", "recovering", "closed"]


@dataclass(frozen=True)
class Event:
    kind: Literal["ready", "starting", "changing", "recovering", "closed", "admit"]
    task_kind: Optional[str] = None


@dataclass(frozen=True)
class Effects:
    admit: bool = False


def new() -> State:
    return State("ready")


def step(state: State, event: Event) -> tuple[State, Effects]:
    """Allow ordinary dispatch only after lifecycle recovery completes."""
    if state.phase == "closed":
        return state, Effects()
    if event.kind == "ready":
        return new(), Effects()
    if event.kind == "starting":
        return State("starting"), Effects()
    if event.kind == "changing":
        return State("changing"), Effects()
    if event.kind == "recovering":
        return State("recovering"), Effects()
    if event.kind == "closed":
        return State("closed"), Effects()
    if event.task_kind is None or not is_task_kind(event.task_kind):
        return state, Effects()
    if state.phase == "changing":
        return state, Effects()
    admit = (state.phase == "ready" or event.task_kind == "render"
             or event.task_kind == "lifecycle"
             or state.phase == "starting" and event.task_kind == "consistency")
    return state, Effects(admit=admit)


def admitted(kind: str, phase: Literal[
        "ready", "starting", "changing", "recovering", "closed"]) -> bool:
    """Return whether a task class may enter the scheduler phase."""
    return step(State(phase), Event("admit", kind))[1].admit

