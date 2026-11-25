"""Scalar authorization for vectorscope capture publication."""

# pg-book: technical-report/en#next-policy.vectorscope

from dataclasses import dataclass


@dataclass(frozen=True)
class State:
    active: bool
    same_source: bool
    exact: bool
    display_newer: bool


@dataclass(frozen=True)
class Event:
    success: bool


@dataclass(frozen=True)
class Effects:
    publish: bool = False
    current: bool = False
    fail: bool = False


def new() -> State:
    return State(False, False, False, False)


def step(state: State, event: Event) -> tuple[State, Effects]:
    """Authorize a complete result against current demand and display."""
    if not state.active or not state.same_source:
        return state, Effects()
    if not event.success:
        return state, Effects(fail=state.exact)
    publish = state.exact or not state.display_newer
    return state, Effects(publish=publish, current=state.exact)


def publication(success: bool, active: bool, same_source: bool,
                exact: bool, display_newer: bool) -> Effects:
    """Authorize current results or a same-source lagging preview."""
    return step(State(active, same_source, exact, display_newer), Event(success))[1]


def display_current(published: bool, revision_matches: bool, source_valid: bool) -> bool:
    """Authorize a display as current only for the latest valid revision."""
    return published and revision_matches and source_valid


def preview_current(active: bool, revision_matches: bool, source_valid: bool) -> bool:
    """Authorize a preview completion only for its still-current demand."""
    return active and revision_matches and source_valid
