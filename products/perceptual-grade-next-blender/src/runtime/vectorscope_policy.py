"""Demand and capture bookkeeping for transient vectorscopes."""

# pg-book: technical-report/en#next-policy.vectorscope

from dataclasses import dataclass
from typing import Optional

from ..policy.vectorscope import publication


@dataclass(frozen=True)
class Ticket:
    key: object
    generation: int
    capture_signature: str
    source_signature: str
    analysis_signature: str
    source_generation: int


@dataclass(frozen=True)
class Display:
    key: object
    capture_generation: int
    current_generation: Optional[int]


@dataclass(frozen=True)
class State:
    generation: int = 0
    desired: tuple = ()
    active: Optional[Ticket] = None
    queued: tuple = ()
    published: tuple = ()
    failures: tuple = ()


@dataclass(frozen=True)
class Effects:
    start: Optional[Ticket] = None
    publish: Optional[Ticket] = None
    retain_samples: Optional[str] = None
    clear: tuple = ()


@dataclass(frozen=True)
class Event:
    kind: str
    key: Optional[object] = None
    capture_signature: Optional[str] = None
    source_signature: Optional[str] = None
    analysis_signature: Optional[str] = None
    cache_available: bool = False
    ticket: Optional[Ticket] = None
    success: bool = False
    error: Optional[str] = None


def _by_key(values, key):
    return next((value for value in values if value.key == key), None)


def _replace(values, value):
    return tuple(item for item in values if item.key != value.key) + (value,)


def _remove(values, key):
    return tuple(item for item in values if item.key != key)


def _without_failure(failures, key):
    return tuple(item for item in failures if item[0] != key)


def result_demand(state, ticket):
    if ticket is None or state.active != ticket:
        return None
    desired = _by_key(state.desired, ticket.key)
    if desired is None or desired.source_generation != ticket.source_generation:
        return None
    return desired


def step(state, event):
    """Apply one event and return all authorized external effects."""
    if event.kind == "request":
        previous = _by_key(state.desired, event.key)
        if (previous is not None
                and previous.capture_signature == event.capture_signature
                and previous.analysis_signature == event.analysis_signature
                and previous.source_signature == event.source_signature):
            return state, Effects()
        generation = state.generation + 1
        same_source = (previous is not None
                       and previous.source_signature == event.source_signature)
        demand = Ticket(event.key, generation, event.capture_signature,
                        event.source_signature, event.analysis_signature,
                        previous.source_generation if same_source else generation)
        clear = (event.key,) if previous is not None and not same_source else ()
        desired = _replace(state.desired, demand)
        queued = _remove(state.queued, event.key)
        published = state.published if same_source else _remove(state.published, event.key)
        failures = _without_failure(state.failures, event.key)
        active = state.active
        if event.cache_available:
            published = _replace(published, Display(event.key, generation, generation))
            return (State(generation, desired, active, queued, published, failures),
                    Effects(publish=demand, clear=clear))
        if (active is not None and active.key == event.key
                and active.source_generation == demand.source_generation
                and active.capture_signature == demand.capture_signature):
            return (State(generation, desired, active, queued, published, failures),
                    Effects(clear=clear))
        if active is None:
            return (State(generation, desired, demand, queued, published, failures),
                    Effects(start=demand, clear=clear))
        return (State(generation, desired, active, queued + (demand,), published, failures),
                Effects(clear=clear))

    if event.kind == "capture_result":
        ticket = event.ticket
        if ticket is None or state.active != ticket:
            return state, Effects()
        desired = result_demand(state, ticket)
        displayed = _by_key(state.published, ticket.key)
        exact = desired is not None and desired.capture_signature == ticket.capture_signature
        decision = publication(
            event.success, True, desired is not None, exact,
            displayed is not None and displayed.capture_generation > ticket.generation,
        )
        publish = None
        published = state.published
        failures = state.failures
        if decision.publish:
            publish = desired
            published = _replace(published, Display(
                desired.key,
                desired.generation if decision.current else ticket.generation,
                desired.generation if decision.current else None,
            ))
        if decision.fail:
            failures = _without_failure(failures, ticket.key) + ((
                ticket.key, event.error or "Vectorscope capture failed",
            ),)
        start = state.queued[0] if state.queued else None
        return State(state.generation, state.desired, start, state.queued[1:],
                     published, failures), Effects(
            start=start, publish=publish,
            retain_samples=ticket.capture_signature if event.success and desired else None,
        )

    if event.kind == "unavailable":
        failure = (event.key, event.error or "Vectorscope source is unavailable")
        if failure in state.failures and _by_key(state.desired, event.key) is None:
            return state, Effects()
        return (State(state.generation, _remove(state.desired, event.key), state.active,
                      _remove(state.queued, event.key), _remove(state.published, event.key),
                      _without_failure(state.failures, event.key) + (failure,)),
                Effects(clear=(event.key,)))

    if event.kind == "release":
        return (State(state.generation, _remove(state.desired, event.key), state.active,
                      _remove(state.queued, event.key), _remove(state.published, event.key),
                      _without_failure(state.failures, event.key)), Effects(clear=(event.key,)))

    if event.kind == "reset":
        keys = tuple(item.key for item in state.desired)
        return (State(state.generation, (), state.active),
                Effects(clear=keys))

    raise ValueError("Unknown Vectorscope event: " + str(event.kind))


def status(state, key):
    failure = next((item[1] for item in state.failures if item[0] == key), None)
    if failure is not None:
        return "error", failure
    desired = _by_key(state.desired, key)
    if desired is None:
        return "idle", None
    published = _by_key(state.published, key)
    if published is not None and published.current_generation == desired.generation:
        return "current", None
    return "updating", None


__all__ = ("Effects", "Event", "State", "Ticket", "result_demand", "status", "step")
