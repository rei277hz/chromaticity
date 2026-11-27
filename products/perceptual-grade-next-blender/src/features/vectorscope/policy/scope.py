"""Scalar decisions for one transient Vectorscope scope."""

# pg-book: technical-report/en#grade-policy.vectorscope

from dataclasses import dataclass, replace
from typing import Literal, Optional


@dataclass(frozen=True)
class PublicationState:
    active: bool
    same_source: bool
    exact: bool
    display_newer: bool


@dataclass(frozen=True)
class PublicationEvent:
    success: bool


@dataclass(frozen=True)
class PublicationDecision:
    publish: bool
    current: bool
    fail: bool


@dataclass(frozen=True)
class PublicationTransition:
    state: PublicationState
    effects: PublicationDecision


def publication_step(state: PublicationState,
                     event: PublicationEvent) -> PublicationTransition:
    """Authorize a result against the current scalar receipts."""
    if not state.active or not state.same_source:
        return PublicationTransition(state, PublicationDecision(False, False, False))
    if not event.success:
        return PublicationTransition(state, PublicationDecision(False, False, state.exact))
    publish = state.exact or not state.display_newer
    return PublicationTransition(state, PublicationDecision(publish, state.exact, False))


def publication(success: bool, active: bool, same_source: bool,
                exact: bool, display_newer: bool) -> PublicationDecision:
    return publication_step(
        PublicationState(active, same_source, exact, display_newer),
        PublicationEvent(success),
    ).effects


def display_current(published: bool, revision_matches: bool, source_valid: bool) -> bool:
    return published and revision_matches and source_valid


def preview_current(active: bool, revision_matches: bool, source_valid: bool) -> bool:
    return active and revision_matches and source_valid


@dataclass(frozen=True)
class ScopeState:
    generation: int = 0
    desired_generation: Optional[int] = None
    capture_signature: Optional[str] = None
    source_signature: Optional[str] = None
    analysis_signature: Optional[str] = None
    source_generation: Optional[int] = None
    revision: Optional[int] = None
    queued_generation: Optional[int] = None
    active_generation: Optional[int] = None
    active_capture_signature: Optional[str] = None
    active_source_generation: Optional[int] = None
    waiting: bool = False
    published_capture_generation: Optional[int] = None
    published_current_generation: Optional[int] = None
    published_source_generation: Optional[int] = None
    failure_revision: Optional[int] = None
    failure_error: Optional[str] = None
    preview_revision: Optional[int] = None
    preview_input_signature: Optional[str] = None
    preview_published_input_signature: Optional[str] = None
    preview_grade_signature: Optional[str] = None
    preview_status: Literal["none", "pending", "preview", "unavailable"] = "none"


@dataclass(frozen=True)
class SchedulerState:
    busy: bool = False


@dataclass(frozen=True)
class State:
    scope: ScopeState
    scheduler: SchedulerState


@dataclass(frozen=True)
class Event:
    kind: Literal[
        "request", "schedule", "started", "deferred", "capture_result",
        "preview_request", "preview_result", "preview_withdraw",
        "release", "unavailable", "reset",
    ]
    capture_signature: Optional[str] = None
    source_signature: Optional[str] = None
    analysis_signature: Optional[str] = None
    cache_available: bool = False
    ticket_generation: Optional[int] = None
    success: bool = False
    error: Optional[str] = None
    ready: bool = True
    revision: int = 0
    preview_input_signature: Optional[str] = None
    preview_grade_signature: Optional[str] = None
    allow_lagging: bool = True
    resume: bool = False


@dataclass(frozen=True)
class Effects:
    enqueue: bool = False
    remove_queue: bool = False
    start: bool = False
    publish: bool = False
    retain_samples: bool = False
    clear: bool = False
    cancel: bool = False
    evaluate_preview: bool = False
    publish_preview: bool = False
    clear_preview: bool = False


@dataclass(frozen=True)
class Transition:
    state: State
    effects: Effects


@dataclass(frozen=True)
class Readout:
    status: str
    error: Optional[str]
    show_plot: bool


@dataclass(frozen=True)
class EditorReadout:
    visible: bool
    input_status: str
    input_error: Optional[str]
    input_show_plot: bool
    appearance_status: str
    appearance_error: Optional[str]
    appearance_show_plot: bool


def initial_state() -> State:
    return State(ScopeState(), SchedulerState())


def new_publication() -> PublicationState:
    return PublicationState(False, False, False, False)


def _clear_preview(state: ScopeState) -> ScopeState:
    return replace(
        state,
        preview_revision=None,
        preview_input_signature=None,
        preview_published_input_signature=None,
        preview_grade_signature=None,
        preview_status="none",
    )


def _withdraw_preview(state: ScopeState) -> ScopeState:
    return replace(
        state,
        preview_revision=None,
        preview_input_signature=state.preview_published_input_signature,
        preview_grade_signature=None,
        preview_status="none",
    )


def _clear_demand(state: ScopeState) -> ScopeState:
    return replace(
        state,
        desired_generation=None,
        capture_signature=None,
        source_signature=None,
        analysis_signature=None,
        source_generation=None,
        revision=None,
        queued_generation=None,
        waiting=False,
    )


def step(state: State, event: Event) -> Transition:
    """Apply one scoped event and return authorized effects."""
    scope = state.scope
    scheduler = state.scheduler

    if event.kind == "request":
        same_demand = (
            scope.desired_generation is not None
            and scope.capture_signature == event.capture_signature
            and scope.source_signature == event.source_signature
            and scope.analysis_signature == event.analysis_signature
            and scope.revision == event.revision
        )
        same_source = (
            scope.source_signature is not None
            and scope.source_signature == event.source_signature
        )
        if same_demand:
            scope = replace(scope, waiting=not event.ready)
            return Transition(State(scope, scheduler), Effects())

        generation = scope.generation + 1
        source_generation = (
            scope.source_generation
            if same_source and scope.source_generation is not None
            else generation
        )
        active_same_capture = (
            scope.active_generation is not None
            and scope.active_source_generation == source_generation
            and scope.active_capture_signature == event.capture_signature
        )
        remove_queue = scope.queued_generation is not None
        enqueue = False
        queued_generation = scope.queued_generation
        published_capture_generation = scope.published_capture_generation
        published_current_generation = scope.published_current_generation
        published_source_generation = scope.published_source_generation
        publish = False

        if event.cache_available:
            queued_generation = None
            published_capture_generation = generation
            published_current_generation = generation
            published_source_generation = source_generation
            publish = True
        elif active_same_capture:
            enqueue = False
        else:
            queued_generation = generation
            enqueue = True

        scope = replace(
            scope,
            generation=generation,
            desired_generation=generation,
            capture_signature=event.capture_signature,
            source_signature=event.source_signature,
            analysis_signature=event.analysis_signature,
            source_generation=source_generation,
            revision=event.revision,
            queued_generation=queued_generation,
            waiting=not event.ready,
            published_capture_generation=published_capture_generation,
            published_current_generation=published_current_generation,
            published_source_generation=published_source_generation,
            failure_revision=None,
            failure_error=None,
        )
        if publish:
            scope = _clear_preview(scope)
        return Transition(
            State(scope, scheduler),
            Effects(
                enqueue=enqueue,
                remove_queue=remove_queue and (event.cache_available or active_same_capture),
                publish=publish,
                clear_preview=publish,
            ),
        )

    if event.kind == "preview_request":
        same_preview = (
            (scope.preview_status == "pending" or scope.preview_status == "preview")
            and scope.preview_revision == event.revision
            and scope.preview_input_signature == event.preview_input_signature
            and scope.preview_grade_signature == event.preview_grade_signature
        )
        if same_preview:
            return Transition(state, Effects())
        scope = replace(
            scope,
            preview_revision=event.revision,
            preview_input_signature=event.preview_input_signature,
            preview_grade_signature=event.preview_grade_signature,
            preview_status="pending",
        )
        return Transition(State(scope, scheduler), Effects(evaluate_preview=True))

    if event.kind == "preview_withdraw":
        if scope.preview_status == "none":
            return Transition(state, Effects())
        return Transition(State(_withdraw_preview(scope), scheduler), Effects())

    if event.kind == "preview_result":
        matching_preview = (
            scope.preview_status == "pending"
            and scope.preview_revision == event.revision
            and scope.preview_input_signature == event.preview_input_signature
            and scope.preview_grade_signature == event.preview_grade_signature
        )
        if not matching_preview or not event.ready:
            return Transition(state, Effects())
        preview_status = "preview" if event.success else "unavailable"
        scope = replace(scope, preview_status=preview_status,
                        preview_published_input_signature=(
                            event.preview_input_signature if event.success
                            else scope.preview_published_input_signature
                        ))
        return Transition(
            State(scope, scheduler),
            Effects(publish_preview=event.success),
        )

    if event.kind == "schedule":
        if scheduler.busy or scope.waiting:
            return Transition(state, Effects())
        matching_queue = (
            event.ticket_generation is not None
            and scope.queued_generation == event.ticket_generation
            and scope.desired_generation == event.ticket_generation
        )
        if not matching_queue:
            remove_queue = (
                scope.queued_generation is not None
                and event.ticket_generation != scope.queued_generation
            )
            return Transition(state, Effects(remove_queue=remove_queue))
        scope = replace(
            scope,
            active_generation=event.ticket_generation,
            active_capture_signature=scope.capture_signature,
            active_source_generation=scope.source_generation,
        )
        scheduler = replace(scheduler, busy=True)
        return Transition(State(scope, scheduler), Effects(start=True))

    if event.kind == "started":
        if event.ticket_generation is None or scope.active_generation != event.ticket_generation:
            return Transition(state, Effects())
        remove_queue = scope.queued_generation == event.ticket_generation
        if remove_queue:
            scope = replace(scope, queued_generation=None)
        return Transition(State(scope, scheduler), Effects(remove_queue=remove_queue))

    if event.kind == "deferred":
        if event.ticket_generation is None or scope.active_generation != event.ticket_generation:
            return Transition(state, Effects())
        resume = (event.resume and scope.desired_generation is not None
                  and scope.queued_generation is None
                  and scope.published_current_generation != scope.desired_generation)
        scope = replace(
            scope,
            active_generation=None,
            active_capture_signature=None,
            active_source_generation=None,
            queued_generation=scope.desired_generation if resume else scope.queued_generation,
        )
        scheduler = replace(scheduler, busy=False)
        return Transition(State(scope, scheduler), Effects(enqueue=resume))

    if event.kind == "capture_result":
        if event.ticket_generation is None or scope.active_generation != event.ticket_generation:
            return Transition(state, Effects())
        exact = (
            scope.desired_generation is not None
            and scope.capture_signature == scope.active_capture_signature
            and scope.revision == event.revision
        )
        same_source = (
            scope.desired_generation is not None
            and scope.source_generation == scope.active_source_generation
            and (exact or event.allow_lagging)
        )
        display_newer = (
            scope.published_capture_generation is not None
            and scope.published_capture_generation > event.ticket_generation
        )
        decision = publication_step(
            PublicationState(True, same_source, exact, display_newer),
            PublicationEvent(event.success),
        ).effects
        published_capture_generation = scope.published_capture_generation
        published_current_generation = scope.published_current_generation
        published_source_generation = scope.published_source_generation
        if decision.publish:
            published_capture_generation = event.ticket_generation
            published_source_generation = scope.active_source_generation
            published_current_generation = (
                scope.desired_generation if decision.current else None
            )
        failure_revision = scope.failure_revision
        failure_error = scope.failure_error
        if decision.fail:
            failure_revision = event.revision
            failure_error = event.error if event.error is not None else "Vectorscope capture failed"
        remove_queue = scope.queued_generation == event.ticket_generation
        scope = replace(
            scope,
            active_generation=None,
            active_capture_signature=None,
            active_source_generation=None,
            queued_generation=None if remove_queue else scope.queued_generation,
            published_capture_generation=published_capture_generation,
            published_current_generation=published_current_generation,
            published_source_generation=published_source_generation,
            failure_revision=failure_revision,
            failure_error=failure_error,
        )
        clear_preview = decision.publish and decision.current and event.success
        if clear_preview:
            scope = _clear_preview(scope)
        scheduler = replace(scheduler, busy=False)
        return Transition(
            State(scope, scheduler),
            Effects(
                remove_queue=remove_queue,
                publish=decision.publish,
                retain_samples=event.success and same_source,
                clear_preview=clear_preview,
            ),
        )

    if event.kind == "release" or event.kind == "unavailable":
        unavailable = event.kind == "unavailable"
        failure_error = event.error if event.error is not None else "Vectorscope source is unavailable"
        if (
            unavailable
            and scope.desired_generation is None
            and scope.failure_revision == event.revision
            and scope.failure_error == failure_error
        ):
            return Transition(state, Effects())
        had_demand = scope.desired_generation is not None
        active_generation = scope.active_generation
        queued_generation = scope.queued_generation
        scope = _clear_demand(scope)
        scope = replace(
            scope,
            published_capture_generation=None,
            published_current_generation=None,
            published_source_generation=None,
            failure_revision=event.revision if unavailable else None,
            failure_error=failure_error if unavailable else None,
            active_generation=active_generation,
        )
        scope = _clear_preview(scope)
        return Transition(
            State(scope, scheduler),
            Effects(
                remove_queue=queued_generation is not None,
                clear=True,
                clear_preview=True,
                cancel=had_demand and active_generation is not None,
            ),
        )

    if event.kind == "reset":
        active_generation = scope.active_generation
        queued_generation = scope.queued_generation
        scope = _clear_demand(scope)
        scope = replace(
            scope,
            published_capture_generation=None,
            published_current_generation=None,
            published_source_generation=None,
            failure_revision=None,
            failure_error=None,
            active_generation=active_generation,
        )
        scope = _clear_preview(scope)
        return Transition(
            State(scope, scheduler),
            Effects(
                remove_queue=queued_generation is not None,
                clear=True,
                clear_preview=True,
                cancel=active_generation is not None,
            ),
        )

    raise ValueError("Unknown Vectorscope event")


def result_current(state: ScopeState, ticket_generation: int) -> bool:
    return (
        state.active_generation == ticket_generation
        and state.desired_generation is not None
        and state.source_generation == state.active_source_generation
    )


def status(state: ScopeState, revision: Optional[int], source_valid: bool) -> Readout:
    if not source_valid or state.waiting:
        return Readout("updating", None, False)
    if state.failure_error is not None:
        if revision is not None and revision != state.failure_revision:
            return Readout("updating", None, False)
        return Readout("error", state.failure_error, False)
    if state.desired_generation is None:
        return Readout("idle", None, False)
    if revision is not None and revision != state.revision:
        return Readout("updating", None, False)
    current = display_current(
        state.published_current_generation == state.desired_generation,
        revision is None or revision == state.revision,
        source_valid,
    )
    if current:
        return Readout("current", None, True)
    return Readout("updating", None, True)


def project(input_state: ScopeState, appearance_state: ScopeState,
            binding_matches: bool, source_valid: bool, tone: bool,
            compatible: bool, revision: Optional[int],
            appearance_revision: Optional[int], muted: bool, baked: bool) -> EditorReadout:
    input_readout = status(input_state, revision, source_valid)
    input_show_plot = (
        compatible
        and (input_readout.status == "current" or input_readout.status == "updating")
    )
    if not binding_matches:
        return EditorReadout(False, input_readout.status, input_readout.error,
                             False, "none", None, False)
    if not tone:
        return EditorReadout(True, input_readout.status, input_readout.error,
                             input_show_plot, "none", None, False)
    if muted:
        return EditorReadout(True, input_readout.status, input_readout.error,
                             input_show_plot, "unavailable",
                             "Appearance requires an unmuted Grade", False)
    if baked:
        return EditorReadout(True, input_readout.status, input_readout.error,
                             input_show_plot, "bake", None, False)
    retained_any = (appearance_state.published_capture_generation is not None
                    or appearance_state.preview_published_input_signature is not None)
    if not source_valid:
        return EditorReadout(True, input_readout.status, input_readout.error,
                             input_show_plot, "updating", None, retained_any)

    appearance_readout = status(appearance_state, appearance_revision, True)
    retained_capture = (
        appearance_state.published_capture_generation is not None
        and appearance_state.published_source_generation is not None
        and appearance_state.published_source_generation == appearance_state.source_generation
    )
    preview_retained = appearance_state.preview_published_input_signature is not None
    preview_matches_input = (preview_retained
                             and appearance_state.preview_published_input_signature
                             == input_state.capture_signature)
    retained_same_source = retained_capture or preview_matches_input
    active_preview = appearance_state.preview_status == "preview"
    preview_is_current = preview_current(
        active_preview and preview_matches_input,
        appearance_state.preview_revision == appearance_revision,
        input_readout.status == "current",
    )
    if input_readout.status == "error" or appearance_readout.status == "error":
        return EditorReadout(
            True, input_readout.status, input_readout.error, input_show_plot,
            "error", (appearance_readout.error if appearance_readout.error is not None
                      else input_readout.error), False,
        )
    if appearance_readout.status == "current":
        return EditorReadout(True, input_readout.status, input_readout.error,
                             input_show_plot, "current", None, True)
    if preview_is_current:
        return EditorReadout(True, input_readout.status, input_readout.error,
                             input_show_plot, "preview", None, True)
    appearance_status = "retained" if retained_same_source else "updating"
    return EditorReadout(True, input_readout.status, input_readout.error,
                         input_show_plot, appearance_status, None,
                         retained_any)
