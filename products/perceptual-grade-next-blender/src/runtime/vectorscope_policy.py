"""Demand and capture bookkeeping for transient vectorscopes."""

# pg-book: technical-report/en#next-policy.vectorscope

from dataclasses import dataclass, replace
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
    waiting: frozenset = frozenset()


@dataclass(frozen=True)
class Effects:
    start: Optional[Ticket] = None
    publish: Optional[Ticket] = None
    retain_samples: Optional[str] = None
    clear: tuple = ()
    cancel: Optional[Ticket] = None


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
    ready: bool = True


def _by_key(values, key):
    return next((value for value in values if value.key == key), None)


def _replace(values, value):
    for index, item in enumerate(values):
        if item.key == value.key:
            return values[:index] + (value,) + values[index + 1:]
    return values + (value,)


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
        waiting = (state.waiting - {event.key} if event.ready
                   else state.waiting | {event.key})
        previous = _by_key(state.desired, event.key)
        if (previous is not None
                and previous.capture_signature == event.capture_signature
                and previous.analysis_signature == event.analysis_signature
                and previous.source_signature == event.source_signature):
            return replace(state, waiting=waiting), Effects()
        generation = state.generation + 1
        same_source = (previous is not None
                       and previous.source_signature == event.source_signature)
        demand = Ticket(event.key, generation, event.capture_signature,
                        event.source_signature, event.analysis_signature,
                        previous.source_generation if same_source else generation)
        clear = (event.key,) if previous is not None and not same_source else ()
        desired = _replace(state.desired, demand)
        published = state.published if same_source else _remove(state.published, event.key)
        failures = _without_failure(state.failures, event.key)
        active = state.active
        publish = None
        if event.cache_available:
            queued = _remove(state.queued, event.key)
            published = _replace(published, Display(event.key, generation, generation))
            publish = demand
        elif (active is not None and active.key == event.key
              and active.source_generation == demand.source_generation
              and active.capture_signature == demand.capture_signature):
            queued = (state.queued if active in state.queued
                      else _remove(state.queued, event.key))
        else:
            queued = _replace(state.queued, demand)
        return (State(generation, desired, active, queued, published, failures, waiting),
                Effects(publish=publish, clear=clear))

    if event.kind == "schedule":
        if state.active is not None:
            return state, Effects()
        ticket = next((item for item in state.queued if item.key not in state.waiting), None)
        if ticket is None:
            return state, Effects()
        return replace(state, active=ticket), Effects(start=ticket)

    if event.kind == "started":
        ticket = event.ticket
        if ticket is None or state.active != ticket:
            return state, Effects()
        return replace(state, queued=tuple(item for item in state.queued if item != ticket)), Effects()

    if event.kind == "deferred":
        ticket = event.ticket
        if ticket is None or state.active != ticket:
            return state, Effects()
        return replace(state, active=None), Effects()

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
        queued = tuple(item for item in state.queued if item != ticket)
        return replace(state, active=None, queued=queued, published=published,
                       failures=failures), Effects(
            publish=publish,
            retain_samples=ticket.capture_signature if event.success and desired else None,
        )

    if event.kind in {"release", "unavailable"}:
        key = event.key
        desired = _remove(state.desired, key)
        failures = _without_failure(state.failures, key)
        if event.kind == "unavailable":
            failure = (key, event.error or "Vectorscope source is unavailable")
            if failure in state.failures and desired == state.desired:
                return state, Effects()
            failures += (failure,)
        active = state.active
        cancel = (active if active is not None and active.key == key
                  and desired != state.desired else None)
        return replace(state, desired=desired, queued=_remove(state.queued, key),
                       published=_remove(state.published, key), failures=failures,
                       waiting=state.waiting - {key}), Effects(clear=(key,), cancel=cancel)

    if event.kind == "reset":
        keys = tuple(item.key for item in state.desired)
        return State(generation=state.generation, active=state.active), Effects(
            clear=keys, cancel=state.active,
        )

    raise ValueError("Unknown Vectorscope event: " + str(event.kind))


def status(state, key):
    if key in state.waiting:
        return "updating", None
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
