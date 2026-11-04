"""Pure lifecycle decisions for one helper process and its physical work slot."""

from dataclasses import dataclass
from typing import Literal, Optional


@dataclass(frozen=True)
class Action:
    kind: Literal[
        "launch", "dispatch", "publish_preview", "publish_result",
        "publish_failure", "publish_cancelled", "send_cancel", "send_shutdown",
        "terminate", "kill", "cleanup", "fail_queued", "cancel_queued",
        "accept", "pump", "deadline", "clear_deadline",
    ]
    job_id: Optional[int] = None
    error: Optional[str] = None
    stage: Optional[str] = None


@dataclass(frozen=True)
class State:
    phase: Literal[
        "stopped", "starting", "probing", "ready", "stopping", "terminating",
        "killing", "unretired", "retiring", "failed", "closed",
    ]
    generation: int
    probe_id: Optional[int]
    active_id: Optional[int]
    error: Optional[str]
    close_requested: bool = False


@dataclass(frozen=True)
class Event:
    kind: Literal[
        "launch", "hello", "submit", "preview", "probe_result", "result",
        "cancelled", "cancel", "failure", "shutdown", "exited", "poll",
        "eof", "timeout", "cleanup_result",
    ]
    generation: int
    job_id: Optional[int] = None
    next_id: Optional[int] = None
    success: bool = False
    error: Optional[str] = None
    transport: Optional[str] = None
    process_alive: bool = True
    stage: Optional[str] = None
    exit_code: Optional[int] = None


@dataclass(frozen=True)
class Effects:
    actions: tuple[Action, ...] = ()


def new() -> State:
    return State("stopped", 0, None, None, None)


def admitting(state: State) -> bool:
    return state.phase == "ready" and not state.close_requested


def close_pending(state: State) -> bool:
    return state.phase in ("starting", "probing", "ready", "stopping",
                           "terminating", "killing")


def close_problem(state: State) -> Optional[str]:
    if state.phase == "unretired":
        return "GPU helper did not physically retire"
    if state.phase == "retiring":
        return "GPU helper cleanup is incomplete"
    return None


def _dispatch_next(state: State, next_id: Optional[int]) -> tuple[State, tuple[Action, ...]]:
    return (
        State(state.phase, state.generation, state.probe_id, next_id,
              state.error, state.close_requested),
        () if next_id is None else (Action("dispatch", next_id),),
    )


def _failure(state: State, error: Optional[str]) -> tuple[State, Effects]:
    failure = state.error if state.error is not None else error
    failure = failure if failure is not None else "GPU helper failed"
    if state.phase in ("starting", "probing", "ready", "stopping"):
        return (
            State("terminating", state.generation, state.probe_id, state.active_id,
                  failure, state.close_requested),
            Effects((Action("deadline", stage="terminating"),
                     Action("terminate"))),
        )
    if state.phase in ("terminating", "killing", "unretired"):
        return State(state.phase, state.generation, state.probe_id, state.active_id,
                     failure, state.close_requested), Effects()
    return state, Effects()


def _shutdown(state: State, transport: Optional[str]) -> tuple[State, Effects]:
    if transport == "channel":
        return (
            State("stopping", state.generation, state.probe_id, state.active_id,
                  state.error, True),
            Effects((Action("deadline", stage="stopping"),
                     Action("send_shutdown"))),
        )
    return (
        State("terminating", state.generation, state.probe_id, state.active_id,
              state.error, True),
        Effects((Action("deadline", stage="terminating"),
                 Action("terminate"))),
    )


def _exited(state: State, event: Event) -> tuple[State, Effects]:
    if state.phase in ("stopped", "retiring", "failed", "closed"):
        return state, Effects()
    # A requested terminate/kill may report a negative signal exit status.
    planned = (state.close_requested and state.error is None
               and (event.error is None
                    or (state.phase in ("terminating", "killing", "unretired")
                        and event.exit_code is not None and event.exit_code < 0)))
    error = state.error if state.error is not None else event.error
    error = error if error is not None else "GPU helper exited unexpectedly"
    actions = (Action("clear_deadline"),)
    if state.active_id is not None:
        actions = actions + (Action(
            "publish_cancelled" if planned else "publish_failure",
            state.active_id, None if planned else error),)
    if state.probe_id is not None and state.probe_id != state.active_id:
        actions = actions + (Action(
            "publish_cancelled" if planned else "publish_failure",
            state.probe_id, None if planned else error),)
    actions = actions + (Action("cancel_queued" if planned else "fail_queued",
                                error=None if planned else error), Action("cleanup"))
    return (
        State("retiring", state.generation, None, None,
              None if planned else error, state.close_requested),
        Effects(actions),
    )


def _cancelled(state: State, event: Event) -> tuple[State, Effects]:
    if event.job_id is None or event.job_id != state.active_id:
        return state, Effects()
    if state.phase == "probing":
        return _shutdown(state, event.transport)
    if state.phase != "ready":
        return state, Effects()
    updated = State("ready", state.generation, None, None, state.error)
    next_state, actions = _dispatch_next(updated, event.next_id)
    return next_state, Effects((Action("publish_cancelled", event.job_id),) + actions)



def step(state: State, event: Event) -> tuple[State, Effects]:
    """Returned effects exclusively authorize transport and process mutations."""
    if event.kind == "launch":
        if (state.phase != "stopped" or event.generation <= state.generation
                or event.job_id is None):
            return state, Effects()
        return (
            State("starting", event.generation, event.job_id, None, None),
            Effects((Action("deadline", stage="starting"), Action("launch"))),
        )
    if event.generation != state.generation:
        return state, Effects()

    if event.kind == "poll":
        if state.phase in ("stopped", "retiring", "failed", "closed"):
            return state, Effects()
        if not event.process_alive:
            return _exited(state, event)
        if event.transport == "channel":
            return state, Effects((Action("pump"),))
        if event.transport == "listener" and state.phase in ("starting", "stopping"):
            return state, Effects((Action("accept"),))
        return state, Effects()

    if event.kind == "hello":
        if state.phase != "starting" or state.probe_id is None:
            return state, Effects()
        return (
            State("probing", state.generation, state.probe_id, state.probe_id, None),
            Effects((Action("clear_deadline"), Action("dispatch", state.probe_id))),
        )

    if event.kind == "submit":
        if not admitting(state) or event.job_id is None or state.active_id is not None:
            return state, Effects()
        return (
            State("ready", state.generation, None, event.job_id, state.error),
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
            error = event.error if event.error is not None else "GPU probe failed"
            return _failure(state, error)
        updated = State("ready", state.generation, None, None, None)
        next_state, actions = _dispatch_next(updated, event.next_id)
        return next_state, Effects((Action("publish_result", event.job_id),) + actions)

    if event.kind == "result":
        if (state.phase != "ready" or event.job_id is None
                or event.job_id != state.active_id):
            return state, Effects()
        updated = State("ready", state.generation, None, None, state.error)
        next_state, actions = _dispatch_next(updated, event.next_id)
        return next_state, Effects((Action("publish_result", event.job_id),) + actions)

    if event.kind == "cancelled":
        return _cancelled(state, event)

    if event.kind == "cancel":
        if event.job_id is None:
            return state, Effects()
        if event.job_id == state.probe_id and state.phase in ("starting", "probing"):
            return _shutdown(state, event.transport)
        if state.phase == "ready":
            if event.job_id == state.active_id:
                return state, Effects((Action("send_cancel", event.job_id),))
            return state, Effects((Action("publish_cancelled", event.job_id),))
        return state, Effects()

    if event.kind == "failure":
        return _failure(state, event.error)

    if event.kind == "eof":
        if state.phase in ("stopping", "terminating", "killing", "unretired"):
            return state, Effects()
        return _failure(state, event.error)

    if event.kind == "timeout":
        if event.stage != state.phase:
            return state, Effects()
        if state.phase == "starting":
            return _failure(state, "GPU helper startup timed out")
        if state.phase == "stopping":
            return _failure(state, "GPU helper shutdown timed out")
        if state.phase == "terminating":
            return (
                State("killing", state.generation, state.probe_id, state.active_id,
                      state.error, state.close_requested),
                Effects((Action("deadline", stage="killing"), Action("kill"))),
            )
        if state.phase == "killing":
            return (
                State("unretired", state.generation, state.probe_id, state.active_id,
                      state.error, state.close_requested),
                Effects((Action("clear_deadline"),)),
            )
        return state, Effects()

    if event.kind == "shutdown":
        if state.phase == "closed":
            return state, Effects()
        if state.phase == "failed":
            return State("closed", state.generation, None, None, state.error, True), Effects()
        if state.phase == "stopped":
            return (State("retiring", state.generation, None, None, state.error, True),
                    Effects((Action("cleanup"),)))
        if state.phase == "retiring":
            return (State("retiring", state.generation, None, None, state.error, True),
                    Effects((Action("cleanup"),)))
        if not event.process_alive:
            updated, effects = _exited(state, event)
            return (State(updated.phase, updated.generation, updated.probe_id,
                          updated.active_id, updated.error, True), effects)
        if state.phase in ("stopping", "terminating", "killing", "unretired"):
            return (State(state.phase, state.generation, state.probe_id, state.active_id,
                          state.error, True), Effects())
        return _shutdown(state, event.transport)

    if event.kind == "exited":
        return _exited(state, event)

    if event.kind == "cleanup_result":
        if state.phase != "retiring":
            return state, Effects()
        if not event.success:
            error = state.error if state.error is not None else event.error
            return State("retiring", state.generation, None, None, error,
                         state.close_requested), Effects()
        return (State("closed" if state.close_requested else "failed", state.generation,
                      None, None, state.error, state.close_requested), Effects())

    raise ValueError("Unknown helper event")
