"""One active Grade preparation, one latest demand, and staged results."""

from dataclasses import dataclass
from typing import Literal, Optional


@dataclass(frozen=True)
class State:
    desired_signature: Optional[str]
    running_signature: Optional[str]


@dataclass(frozen=True)
class Event:
    kind: Literal["request", "preparation_preview", "preparation_result"]
    signature: Optional[str] = None
    error: Optional[str] = None


@dataclass(frozen=True)
class Effects:
    prepare_signature: Optional[str] = None
    preview_signature: Optional[str] = None
    result_signature: Optional[str] = None
    error: Optional[str] = None


def new() -> State:
    return State(None, None)


def step(state: State, event: Event) -> tuple[State, Effects]:
    """Finish active work before starting the latest requested replacement.

    A preview receipt publishes an intermediate result while the active job
    remains demanded. A cooperative host job may be retired after preview when
    its request is superseded; its stale failure then starts the latest request.
    Otherwise the final receipt retires the job and starts the latest request.
    A superseded final success can be delivered as a pending preview. Only a
    failure of current demand is delivered. Withdrawing demand does not claim
    that the physical worker has stopped; its final receipt retires it. The
    owning runtime fences source lifetimes before dispatching receipts.
    """
    if event.kind == "request":
        prepare_signature = event.signature if state.running_signature is None else None
        running_signature = (
            prepare_signature if state.running_signature is None else state.running_signature
        )
        return State(event.signature, running_signature), Effects(
            prepare_signature=prepare_signature,
        )

    if event.kind == "preparation_preview":
        if (event.signature is not None
                and event.signature == state.running_signature
                and event.error is None):
            return state, Effects(preview_signature=event.signature)
        return state, Effects()

    if event.signature is None or event.signature != state.running_signature:
        return state, Effects()

    prepare_signature = (
        state.desired_signature if state.desired_signature != event.signature else None
    )
    result_signature = (
        event.signature
        if state.desired_signature is not None
        and (event.error is None or event.signature == state.desired_signature)
        else None
    )
    return State(state.desired_signature, prepare_signature), Effects(
        prepare_signature=prepare_signature,
        result_signature=result_signature,
        error=event.error if result_signature is not None else None,
    )
