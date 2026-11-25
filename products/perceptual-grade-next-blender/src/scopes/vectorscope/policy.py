"""Demand and capture bookkeeping for transient vectorscopes."""

# pg-book: technical-report/en#next-policy.vectorscope

from dataclasses import dataclass, replace
from typing import Optional

from ...policy.vectorscope import display_current, publication, preview_current


@dataclass(frozen=True)
class Ticket:
    key: object
    generation: int
    capture_signature: str
    source_signature: str
    analysis_signature: str
    source_generation: int
    revision: int = 0


@dataclass(frozen=True)
class Display:
    key: object
    capture_generation: int
    current_generation: Optional[int]


@dataclass(frozen=True)
class Preview:
    key: object
    revision: int
    input_signature: str
    grade_signature: str
    status: str = "pending"
    error: Optional[str] = None


@dataclass(frozen=True)
class Failure:
    key: object
    revision: int
    error: str


@dataclass(frozen=True)
class PlotReadout:
    status: str
    error: Optional[str] = None
    show_plot: bool = False


@dataclass(frozen=True)
class EditorReadout:
    input: PlotReadout
    appearance: Optional[PlotReadout] = None


@dataclass(frozen=True)
class State:
    generation: int = 0
    desired: tuple = ()
    active: Optional[Ticket] = None
    queued: tuple = ()
    published: tuple = ()
    failures: tuple = ()
    waiting: frozenset = frozenset()
    previews: tuple = ()


@dataclass(frozen=True)
class Effects:
    start: Optional[Ticket] = None
    publish: Optional[Ticket] = None
    retain_samples: Optional[str] = None
    clear: tuple = ()
    cancel: Optional[Ticket] = None
    evaluate_preview: Optional[Preview] = None
    publish_preview: Optional[Preview] = None


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
    revision: int = 0
    preview: Optional[Preview] = None
    allow_lagging: bool = True


def _by_key(values, key):
    return next((value for value in values if value.key == key), None)


def _replace(values, value):
    for index, item in enumerate(values):
        if item.key == value.key:
            return values[:index] + (value,) + values[index + 1:]
    return values + (value,)


def _remove(values, key):
    return tuple(item for item in values if item.key != key)


def result_demand(state, ticket):
    if ticket is None or state.active != ticket:
        return None
    desired = _by_key(state.desired, ticket.key)
    if desired is None or desired.source_generation != ticket.source_generation:
        return None
    return desired


def demand_for(state, key):
    return _by_key(state.desired, key)


def preview_for(state, key):
    return _by_key(state.previews, key)


def step(state, event):
    """Apply one event and return all authorized external effects."""
    if event.kind == "request":
        waiting = (state.waiting - {event.key} if event.ready
                   else state.waiting | {event.key})
        previous = _by_key(state.desired, event.key)
        if (previous is not None
                and previous.capture_signature == event.capture_signature
                and previous.analysis_signature == event.analysis_signature
                and previous.source_signature == event.source_signature
                and previous.revision == event.revision):
            return replace(state, waiting=waiting,
                           previews=_remove(state.previews, event.key)), Effects()
        generation = state.generation + 1
        same_source = (previous is not None
                       and previous.source_signature == event.source_signature)
        demand = Ticket(event.key, generation, event.capture_signature,
                        event.source_signature, event.analysis_signature,
                        previous.source_generation if same_source else generation,
                        event.revision)
        clear = ((event.key,) if (previous is not None and not same_source
                                  or preview_for(state, event.key) is not None) else ())
        desired = _replace(state.desired, demand)
        published = state.published if same_source else _remove(state.published, event.key)
        failures = _remove(state.failures, event.key)
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
        return (State(generation, desired, active, queued, published, failures, waiting,
                      _remove(state.previews, event.key)),
                Effects(publish=publish, clear=clear))

    if event.kind == "preview_request":
        preview = event.preview
        if preview is None:
            return state, Effects()
        previous = preview_for(state, preview.key)
        if (previous is not None and previous.status in {"pending", "preview"}
                and previous.revision == preview.revision
                and previous.input_signature == preview.input_signature
                and previous.grade_signature == preview.grade_signature):
            return state, Effects()
        return replace(state, previews=_replace(state.previews, preview)), Effects(
            clear=(preview.key,), evaluate_preview=preview,
        )

    if event.kind == "preview_withdraw":
        if preview_for(state, event.key) is None:
            return state, Effects()
        return replace(state, previews=_remove(state.previews, event.key)), Effects(clear=(event.key,))

    if event.kind == "preview_result":
        pending = event.preview
        if (pending is None or preview_for(state, pending.key) != pending
                or not preview_current(pending.status == "pending",
                                       pending.revision == event.revision, event.ready)):
            return state, Effects()
        completed = replace(pending, status="preview" if event.success else "unavailable",
                            error=event.error)
        return replace(state, previews=_replace(state.previews, completed)), Effects(
            publish_preview=completed if event.success else None,
        )

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
        exact = (desired is not None and desired.capture_signature == ticket.capture_signature
                 and desired.revision == event.revision)
        same_source = (desired is not None and
                       (exact or event.allow_lagging))
        decision = publication(
            event.success, True, same_source, exact,
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
            failures = _replace(failures, Failure(
                ticket.key, event.revision, event.error or "Vectorscope capture failed",
            ))
        queued = tuple(item for item in state.queued if item != ticket)
        return replace(state, active=None, queued=queued, published=published,
                       failures=failures), Effects(
            publish=publish,
            retain_samples=ticket.capture_signature if event.success and same_source else None,
        )

    if event.kind in {"release", "unavailable"}:
        key = event.key
        desired = _remove(state.desired, key)
        failures = _remove(state.failures, key)
        if event.kind == "unavailable":
            failure = Failure(key, event.revision,
                              event.error or "Vectorscope source is unavailable")
            if failure in state.failures and desired == state.desired:
                return state, Effects()
            failures += (failure,)
        active = state.active
        cancel = (active if active is not None and active.key == key
                  and desired != state.desired else None)
        return replace(state, desired=desired, queued=_remove(state.queued, key),
                       published=_remove(state.published, key), failures=failures,
                       waiting=state.waiting - {key},
                       previews=_remove(state.previews, key)), Effects(clear=(key,), cancel=cancel)

    if event.kind == "reset":
        keys = tuple(item.key for item in (*state.desired, *state.previews))
        return State(generation=state.generation, active=state.active), Effects(
            clear=keys, cancel=state.active,
        )

    raise ValueError("Unknown Vectorscope event: " + str(event.kind))


def status(state, key, revision=None, *, source_valid=True):
    if not source_valid or key in state.waiting:
        return "updating", None
    desired = demand_for(state, key)
    if desired is not None and revision is not None and revision != desired.revision:
        return "updating", None
    failure = _by_key(state.failures, key)
    if failure is not None:
        if revision is not None and revision != failure.revision:
            return "updating", None
        return "error", failure.error
    if desired is None:
        return "idle", None
    published = _by_key(state.published, key)
    if display_current(published is not None and published.current_generation == desired.generation,
                       revision is None or revision == desired.revision, source_valid):
        return "current", None
    return "updating", None


def project(state, key, appearance_key, *, binding_matches, source_valid, tone, compatible,
            revision, appearance_revision, mode_matches, dragging, muted, baked):
    """Authorize readouts for a live editor binding, including lagging input."""
    if not binding_matches:
        return None
    input_status, input_error = status(state, key, revision, source_valid=source_valid)
    input_plot = PlotReadout(input_status, input_error,
                             compatible and input_status in {"current", "updating"})
    if not tone:
        return EditorReadout(input_plot)
    if muted:
        return EditorReadout(input_plot, PlotReadout(
            "unavailable", "Appearance requires an unmuted Grade",
        ))
    if baked:
        return EditorReadout(input_plot, PlotReadout("bake"))
    if not source_valid or not mode_matches:
        return EditorReadout(input_plot, PlotReadout("updating"))

    appearance_status, appearance_error = status(state, appearance_key, appearance_revision)
    if not dragging or appearance_status == "error":
        return EditorReadout(input_plot, PlotReadout(
            "updating" if appearance_status == "idle" else appearance_status,
            appearance_error, appearance_status == "current",
        ))
    preview = preview_for(state, appearance_key)
    if (preview is None or not preview_current(preview.status != "pending",
                                               preview.revision == appearance_revision,
                                               input_status == "current")):
        return EditorReadout(input_plot, PlotReadout("updating"))
    return EditorReadout(input_plot, PlotReadout(
        preview.status, preview.error, preview.status == "preview",
    ))


__all__ = ("Effects", "Event", "State", "Ticket", "project", "result_demand", "status", "step")
