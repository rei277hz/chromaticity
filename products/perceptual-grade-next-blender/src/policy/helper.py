"""Pure lifecycle decisions for one helper process and its physical work slot."""

# pg-book: technical-report/en#next-policy.helper

from dataclasses import dataclass
from typing import Literal, Optional


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
    deadline_stage: Optional[str] = None
    clear_deadline: bool = False
    launch: bool = False
    dispatch_id: Optional[int] = None
    publish_kind: Optional[str] = None
    publish_id: Optional[int] = None
    publish_error: Optional[str] = None
    probe_publish_kind: Optional[str] = None
    probe_publish_id: Optional[int] = None
    probe_publish_error: Optional[str] = None
    send_cancel_id: Optional[int] = None
    send_shutdown: bool = False
    terminate: bool = False
    kill: bool = False
    cleanup: bool = False
    queue_kind: Optional[str] = None
    queue_error: Optional[str] = None
    accept: bool = False
    pump: bool = False


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


def _dispatch_next(state: State, next_id: Optional[int]) -> State:
    return State(state.phase, state.generation, state.probe_id, next_id,
                 state.error, state.close_requested)


def _failure(state: State, error: Optional[str]) -> tuple[State, Effects]:
    failure = state.error if state.error is not None else error
    failure = failure if failure is not None else "GPU helper failed"
    if state.phase in ("starting", "probing", "ready", "stopping"):
        return (
            State("terminating", state.generation, state.probe_id, state.active_id,
                  failure, state.close_requested),
            Effects(deadline_stage="terminating", terminate=True),
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
            Effects(deadline_stage="stopping", send_shutdown=True),
        )
    return (
        State("terminating", state.generation, state.probe_id, state.active_id,
              state.error, True),
        Effects(deadline_stage="terminating", terminate=True),
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
    publish_kind = "cancelled" if planned else "failure"
    publish_error = None if planned else error
    publish_id = state.active_id
    probe_publish_kind = None
    probe_publish_id = None
    probe_publish_error = None
    if state.probe_id is not None and state.probe_id != state.active_id:
        probe_publish_kind = publish_kind
        probe_publish_id = state.probe_id
        probe_publish_error = publish_error
    return (
        State("retiring", state.generation, None, None,
              None if planned else error, state.close_requested),
        Effects(
            clear_deadline=True,
            publish_kind=publish_kind if publish_id is not None else None,
            publish_id=publish_id,
            publish_error=publish_error if publish_id is not None else None,
            probe_publish_kind=probe_publish_kind,
            probe_publish_id=probe_publish_id,
            probe_publish_error=probe_publish_error,
            queue_kind="cancel" if planned else "fail",
            queue_error=None if planned else error,
            cleanup=True,
        ),
    )


def _cancelled(state: State, event: Event) -> tuple[State, Effects]:
    if event.job_id is None or event.job_id != state.active_id:
        return state, Effects()
    if state.phase == "probing":
        return _shutdown(state, event.transport)
    if state.phase != "ready":
        return state, Effects()
    updated = State("ready", state.generation, None, None, state.error)
    next_state = _dispatch_next(updated, event.next_id)
    return next_state, Effects(
        publish_kind="cancelled", publish_id=event.job_id,
        dispatch_id=event.next_id,
    )



def step(state: State, event: Event) -> tuple[State, Effects]:
    """Returned effects exclusively authorize transport and process mutations."""
    if event.kind == "launch":
        if (state.phase != "stopped" or event.generation <= state.generation
                or event.job_id is None):
            return state, Effects()
        return (
            State("starting", event.generation, event.job_id, None, None),
            Effects(deadline_stage="starting", launch=True),
        )
    if event.generation != state.generation:
        return state, Effects()

    if event.kind == "poll":
        if state.phase in ("stopped", "retiring", "failed", "closed"):
            return state, Effects()
        if not event.process_alive:
            return _exited(state, event)
        if event.transport == "channel":
            return state, Effects(pump=True)
        if event.transport == "listener" and state.phase in ("starting", "stopping"):
            return state, Effects(accept=True)
        return state, Effects()

    if event.kind == "hello":
        if state.phase != "starting" or state.probe_id is None:
            return state, Effects()
        return (
            State("probing", state.generation, state.probe_id, state.probe_id, None),
            Effects(clear_deadline=True, dispatch_id=state.probe_id),
        )

    if event.kind == "submit":
        if not admitting(state) or event.job_id is None or state.active_id is not None:
            return state, Effects()
        return (
            State("ready", state.generation, None, event.job_id, state.error),
            Effects(dispatch_id=event.job_id),
        )

    if event.kind == "preview":
        if (state.phase != "ready" or state.active_id is None
                or event.job_id != state.active_id):
            return state, Effects()
        return state, Effects(publish_kind="preview", publish_id=event.job_id)

    if event.kind == "probe_result":
        if (state.phase != "probing" or event.job_id != state.probe_id
                or event.job_id != state.active_id):
            return state, Effects()
        if not event.success:
            error = event.error if event.error is not None else "GPU probe failed"
            return _failure(state, error)
        updated = State("ready", state.generation, None, None, None)
        next_state = _dispatch_next(updated, event.next_id)
        return next_state, Effects(
            publish_kind="result", publish_id=event.job_id,
            dispatch_id=event.next_id,
        )

    if event.kind == "result":
        if (state.phase != "ready" or event.job_id is None
                or event.job_id != state.active_id):
            return state, Effects()
        updated = State("ready", state.generation, None, None, state.error)
        next_state = _dispatch_next(updated, event.next_id)
        return next_state, Effects(
            publish_kind="result", publish_id=event.job_id,
            dispatch_id=event.next_id,
        )

    if event.kind == "cancelled":
        return _cancelled(state, event)

    if event.kind == "cancel":
        if event.job_id is None:
            return state, Effects()
        if event.job_id == state.probe_id and state.phase in ("starting", "probing"):
            return _shutdown(state, event.transport)
        if state.phase == "ready":
            if event.job_id == state.active_id:
                return state, Effects(send_cancel_id=event.job_id)
            return state, Effects(publish_kind="cancelled", publish_id=event.job_id)
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
                Effects(deadline_stage="killing", kill=True),
            )
        if state.phase == "killing":
            return (
                State("unretired", state.generation, state.probe_id, state.active_id,
                      state.error, state.close_requested),
                Effects(clear_deadline=True),
            )
        return state, Effects()

    if event.kind == "shutdown":
        if state.phase == "closed":
            return state, Effects()
        if state.phase == "failed":
            return State("closed", state.generation, None, None, state.error, True), Effects()
        if state.phase == "stopped":
            return (State("retiring", state.generation, None, None, state.error, True),
                    Effects(cleanup=True))
        if state.phase == "retiring":
            return (State("retiring", state.generation, None, None, state.error, True),
                    Effects(cleanup=True))
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
