"""Reducer for one GPU helper process and its single physical work slot."""

from dataclasses import dataclass
from typing import Literal, Optional


Phase = Literal["stopped", "starting", "probing", "ready", "closing", "failed", "closed"]


@dataclass(frozen=True)
class Action:
    kind: Literal[
        "launch",
        "dispatch",
        "publish_preview",
        "publish_result",
        "publish_failure",
        "publish_cancelled",
        "send_cancel",
        "send_shutdown",
        "terminate",
        "kill",
        "cleanup",
        "fail_queued",
        "cancel_queued",
    ]
    job_id: Optional[int] = None
    error: Optional[str] = None


@dataclass(frozen=True)
class State:
    phase: Phase
    generation: int
    probe_id: Optional[int]
    active_id: Optional[int]
    error: Optional[str]


@dataclass(frozen=True)
class Event:
    kind: Literal[
        "launch",
        "hello",
        "submit",
        "preview",
        "probe_result",
        "result",
        "cancelled",
        "cancel",
        "failure",
        "shutdown",
        "kill",
        "exited",
    ]
    generation: int
    job_id: Optional[int] = None
    next_id: Optional[int] = None
    success: bool = False
    error: Optional[str] = None


@dataclass(frozen=True)
class Effects:
    actions: tuple[Action, ...] = ()


def new() -> State:
    return State("stopped", 0, None, None, None)


def _dispatch_next(state: State, next_id: Optional[int]) -> tuple[State, tuple[Action, ...]]:
    if next_id is None:
        return State(state.phase, state.generation, state.probe_id, None, state.error), ()
    return (
        State(state.phase, state.generation, state.probe_id, next_id, state.error),
        (Action("dispatch", next_id),),
    )


def step(state: State, event: Event) -> tuple[State, Effects]:
    """Apply a helper lifecycle event; returned actions authorize all I/O."""
    if event.kind == "launch":
        if state.phase != "stopped" or event.generation <= state.generation:
            return state, Effects()
        if event.job_id is None:
            raise ValueError("A helper launch requires its GPU probe job")
        return (
            State("starting", event.generation, event.job_id, None, None),
            Effects((Action("launch", event.job_id),)),
        )

    if event.generation != state.generation:
        return state, Effects()

    if event.kind == "hello":
        if state.phase != "starting" or state.probe_id is None:
            return state, Effects()
        return (
            State("probing", state.generation, state.probe_id, state.probe_id, None),
            Effects((Action("dispatch", state.probe_id),)),
        )

    if event.kind == "submit":
        if state.phase != "ready" or event.job_id is None:
            return state, Effects()
        if state.active_id is not None:
            return state, Effects()
        return (
            State(state.phase, state.generation, state.probe_id, event.job_id, state.error),
            Effects((Action("dispatch", event.job_id),)),
        )

    if event.kind == "preview":
        if (state.phase != "ready" or state.active_id is None
                or event.job_id != state.active_id):
            return state, Effects()
        return state, Effects((Action("publish_preview", event.job_id),))

    if event.kind == "probe_result":
        if (state.phase != "probing" or event.job_id != state.probe_id
                or event.job_id != state.active_id):
            return state, Effects()
        if not event.success:
            return (
                State("closing", state.generation, state.probe_id, state.active_id,
                      event.error or "GPU probe failed"),
                Effects((Action("terminate", error=event.error or "GPU probe failed"),)),
            )
        updated = State("ready", state.generation, None, None, None)
        next_state, actions = _dispatch_next(updated, event.next_id)
        return (
            next_state,
            Effects((Action("publish_result", event.job_id),) + actions),
        )

    if event.kind == "result":
        if (state.phase != "ready" or event.job_id is None
                or event.job_id != state.active_id):
            return state, Effects()
        updated = State("ready", state.generation, state.probe_id, None, state.error)
        next_state, actions = _dispatch_next(updated, event.next_id)
        return (
            next_state,
            Effects((Action("publish_result", event.job_id),) + actions),
        )

    if event.kind == "cancelled":
        if state.phase not in ("probing", "ready") or event.job_id != state.active_id:
            return state, Effects()
        updated = State("ready", state.generation, state.probe_id, None, state.error)
        next_state, actions = _dispatch_next(updated, event.next_id)
        return (
            next_state,
            Effects((Action("publish_cancelled", event.job_id),) + actions),
        )

    if event.kind == "cancel":
        if event.job_id is None:
            return state, Effects()
        if event.job_id == state.active_id and state.phase in ("probing", "ready"):
            return state, Effects((Action("send_cancel", event.job_id),))
        if state.phase == "ready":
            return state, Effects((Action("publish_cancelled", event.job_id),))
        return state, Effects()

    if event.kind == "failure":
        if state.phase in ("starting", "probing", "ready"):
            active_id = state.active_id
            return (
                State("closing", state.generation, state.probe_id, active_id,
                      event.error or "GPU helper failed"),
                Effects((Action("terminate", active_id,
                                event.error or "GPU helper failed"),)),
            )
        if state.phase == "closing" and state.error is None:
            error = event.error or "GPU helper failed during shutdown"
            return (
                State("closing", state.generation, state.probe_id,
                      state.active_id, error),
                Effects((Action("terminate", state.active_id, error),)),
            )
        return state, Effects()

    if event.kind == "shutdown":
        if state.phase in ("closed", "closing"):
            return state, Effects()
        if state.phase in ("stopped", "failed"):
            return (
                State("closed", state.generation, None, None, state.error),
                Effects((Action("cleanup"),)),
            )
        return (
            State("closing", state.generation, state.probe_id, state.active_id,
                  state.error),
            Effects((Action("cancel_queued"),
                     Action("send_shutdown", state.active_id))),
        )

    if event.kind == "kill":
        if state.phase != "closing":
            return state, Effects()
        return state, Effects((Action("kill", state.active_id),))

    if event.kind == "exited":
        if state.phase == "closed":
            return state, Effects()
        planned = state.phase == "closing" and state.error is None and event.error is None
        error = state.error or event.error or "GPU helper exited unexpectedly"
        actions = [Action("cleanup")]
        if state.active_id is not None:
            actions.append(Action(
                "publish_cancelled" if planned else "publish_failure",
                state.active_id,
                None if planned else error,
            ))
        if not planned:
            actions.append(Action("fail_queued", error=error))
        return (
            State("closed" if planned else "failed", state.generation, None, None,
                  None if planned else error),
            Effects(tuple(actions)),
        )

    raise ValueError("Unknown helper event: " + event.kind)
