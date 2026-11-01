"""Checked Bake eligibility observation policy."""

from dataclasses import dataclass, replace
from typing import Literal


@dataclass(frozen=True)
class PreflightState:
    """Value-only state for one owner incarnation."""

    owner: int = 0
    incarnation: int = 0
    source_revision: int = 0
    source_id: int = 0
    verdict: Literal["UNKNOWN", "CHECKING", "READY", "BLOCKED", "FAILED", "CLOSED"] = "UNKNOWN"
    check_serial: int = 0
    active_check_id: int = 0
    active_source_revision: int = 0
    active_source_id: int = 0
    observation_pending: bool = False
    reason: str = ""


@dataclass(frozen=True)
class PreflightEvent:
    """Observation, check receipt, or lifecycle event."""

    kind: Literal[
        "open", "hint", "observed", "start", "complete", "fail", "retry", "close"
    ]
    owner: int = 0
    incarnation: int = 0
    source_revision: int = 0
    source_id: int = 0
    check_id: int = 0
    allowed: bool = False
    reason: str = ""


def new_preflight() -> PreflightState:
    return PreflightState()


def preflight_step(
    state: PreflightState, event: PreflightEvent
) -> tuple[PreflightState, bool]:
    """Apply one event; accepted check receipts settle only their own attempt."""
    if event.kind == "open":
        accepted = (
            event.owner > 0
            and event.incarnation > state.incarnation
            and (state.verdict == "UNKNOWN" or state.verdict == "CLOSED")
            and state.active_check_id == 0
        )
        if accepted:
            return PreflightState(owner=event.owner, incarnation=event.incarnation), True
        return state, False

    if event.kind == "close":
        if state.verdict == "CLOSED":
            return state, False
        if event.owner == state.owner and event.incarnation == state.incarnation:
            return replace(state, verdict="CLOSED", observation_pending=False, reason="closed"), True
        return state, False

    if event.kind in ("complete", "fail"):
        exact_active = (
            event.owner == state.owner
            and event.incarnation == state.incarnation
            and event.check_id == state.active_check_id
            and event.source_revision == state.active_source_revision
            and event.source_id == state.active_source_id
            and state.active_check_id > 0
        )
        if not exact_active:
            return state, False
        settled = replace(
            state,
            active_check_id=0,
            active_source_revision=0,
            active_source_id=0,
        )
        closed_receipt = state.verdict == "CLOSED" and event.kind in ("complete", "fail")
        if closed_receipt:
            return replace(settled, verdict="CLOSED"), True
        if event.source_revision != state.source_revision or event.source_id != state.source_id:
            return settled, True
        if event.kind == "fail":
            if event.reason != "":
                return replace(settled, verdict="FAILED", reason=event.reason), True
            return replace(settled, verdict="FAILED", reason="preflight failed"), True
        if event.allowed:
            return replace(settled, verdict="READY", reason=event.reason), True
        if event.reason != "":
            return replace(settled, verdict="BLOCKED", reason=event.reason), True
        return replace(settled, verdict="BLOCKED", reason="route is unsupported"), True

    if state.verdict == "CLOSED":
        return state, False
    if event.owner != state.owner or event.incarnation != state.incarnation:
        return state, False

    if event.kind == "hint":
        if state.observation_pending:
            return state, True
        return replace(state, observation_pending=True), True

    if event.kind == "observed":
        if not state.observation_pending or event.source_id <= 0:
            return state, False
        if state.source_id == event.source_id and state.source_revision > 0:
            return replace(state, observation_pending=False), True
        return replace(
            state,
            source_revision=state.source_revision + 1,
            source_id=event.source_id,
            verdict="CHECKING",
            observation_pending=False,
            reason="",
        ), True

    if event.kind == "retry":
        if (
            state.verdict != "FAILED"
            or state.active_check_id != 0
            or event.check_id <= state.check_serial
            or state.owner <= 0
            or state.incarnation <= 0
            or state.source_revision <= 0
            or state.source_id <= 0
            or event.owner != state.owner
            or event.incarnation != state.incarnation
        ):
            return state, False
        return replace(
            state,
            verdict="CHECKING",
            check_serial=event.check_id,
            active_check_id=event.check_id,
            active_source_revision=state.source_revision,
            active_source_id=state.source_id,
            reason="",
        ), True

    if event.kind == "start":
        accepted = (
            state.verdict == "CHECKING"
            and state.active_check_id == 0
            and state.source_revision > 0
            and state.source_id > 0
            and state.owner > 0
            and state.incarnation > 0
            and event.owner == state.owner
            and event.incarnation == state.incarnation
            and event.check_id > state.check_serial
        )
        if accepted:
            return replace(
                state,
                check_serial=event.check_id,
                active_check_id=event.check_id,
                active_source_revision=state.source_revision,
                active_source_id=state.source_id,
            ), True
        return state, False

    return state, False


def preflight_ready(state: PreflightState) -> bool:
    """Return whether the current source has a READY certificate."""
    return state.verdict == "READY" and state.source_revision > 0 and state.source_id > 0
