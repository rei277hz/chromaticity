"""Current Grade kernels, gesture previews, and fail-closed output policy."""

from dataclasses import dataclass
from typing import Literal, Optional


@dataclass(frozen=True)
class State:
    desired_signature: Optional[str]
    applied_signature: Optional[str]
    applied_quality: Optional[str]
    gesture_active: bool
    error: Optional[str] = None


@dataclass(frozen=True)
class Event:
    kind: Literal[
        "request",
        "preparation_result",
        "installation_result",
        "gesture_begin",
        "gesture_release",
    ]
    signature: Optional[str] = None
    error: Optional[str] = None
    quality: str = "full"


@dataclass(frozen=True)
class Effects:
    """Commands and the resulting complete presentation/output policy."""

    output_mode: Literal["current", "preview", "pending", "error"]
    prepare_signature: Optional[str] = None
    build_signature: Optional[str] = None
    build_quality: Optional[str] = None
    error: Optional[str] = None


def new(
    desired_signature: Optional[str] = None,
    applied_signature: Optional[str] = None,
    applied_quality: Optional[str] = None,
    gesture_active: bool = False,
    error: Optional[str] = None,
) -> State:
    if applied_signature is None:
        if applied_quality is not None:
            raise ValueError("Applied quality requires an applied signature")
    elif applied_quality is None:
        applied_quality = "full"
    if applied_quality not in (None, "preview", "full"):
        raise ValueError("Applied quality must be preview or full")
    state = State(
        desired_signature,
        applied_signature,
        applied_quality,
        gesture_active,
        error,
    )
    if error is not None and applied_signature is not None:
        raise ValueError("An error cannot retain an applied kernel")
    if desired_signature is None and applied_signature is not None:
        raise ValueError("An applied kernel requires current demand")
    return state


def output_allowed(state: State) -> bool:
    """Only an installed full-quality result for current demand may render."""
    return (
        state.desired_signature is not None
        and state.desired_signature == state.applied_signature
        and state.applied_quality == "full"
        and state.error is None
    )


def output_mode(state: State) -> Literal["current", "preview", "pending", "error"]:
    if output_allowed(state):
        return "current"
    if state.error is not None:
        return "error"
    if state.applied_signature is None:
        return "pending"
    return "preview"


def _effects(
    state: State,
    prepare: Optional[str],
    build: Optional[str],
    build_quality: Optional[str],
) -> Effects:
    return Effects(
        output_mode(state),
        prepare_signature=prepare,
        build_signature=build,
        build_quality=build_quality,
        error=state.error,
    )


def step(state: State, event: Event) -> tuple[State, Effects]:
    """Accept current results and gesture-scoped stale completions for one source.

    The last applied kernel remains visible as a preview while replacements are
    pending, including after release. A stale completion may update that preview
    only during an active gesture. Preparation and installation receipts carry
    settings signature and quality, and the adapter fences source lifetimes,
    delivers receipts in order, and installs synchronously on the host thread.
    """
    if event.kind == "gesture_begin":
        next_state = State(
            state.desired_signature,
            state.applied_signature,
            state.applied_quality,
            True,
            state.error,
        )
        return next_state, _effects(next_state, None, None, None)

    if event.kind == "gesture_release":
        next_state = State(
            state.desired_signature,
            state.applied_signature,
            state.applied_quality,
            False,
            state.error,
        )
        return next_state, _effects(next_state, None, None, None)

    if event.kind == "request":
        keep_applied = (
            event.signature is not None
            and state.applied_signature is not None
        )
        next_state = State(
            event.signature,
            state.applied_signature if keep_applied else None,
            state.applied_quality if keep_applied else None,
            state.gesture_active,
        )
        prepare = (
            event.signature
            if event.signature is not None
            and (event.signature != state.desired_signature or not output_allowed(next_state))
            else None
        )
        return next_state, _effects(next_state, prepare, None, None)

    if event.error is not None:
        if event.signature is None or event.signature == state.desired_signature:
            next_state = State(
                state.desired_signature, None, None, state.gesture_active, event.error
            )
            return next_state, _effects(next_state, None, None, None)
        return state, _effects(state, None, None, None)

    if (event.signature is None or state.desired_signature is None
            or state.error is not None):
        return state, _effects(state, None, None, None)

    is_current = event.signature == state.desired_signature
    # During a continuous gesture, any complete result may be shown as a
    # pending preview. Its quality remains a fact of the installed payload;
    # output_mode keeps it from becoming current until the signature matches.
    accepts_stale = state.gesture_active
    if not is_current and not accepts_stale:
        return state, _effects(state, None, None, None)

    already_applied = (
        event.signature == state.applied_signature
        and event.quality == state.applied_quality
    )
    already_full = (
        event.signature == state.applied_signature
        and state.applied_quality == "full"
    )
    if event.kind == "preparation_result":
        if output_allowed(state) or already_applied or already_full:
            return state, _effects(state, None, None, None)
        return state, _effects(state, None, event.signature, event.quality)

    if event.kind == "installation_result":
        if output_allowed(state) or already_applied or already_full:
            return state, _effects(state, None, None, None)
        next_state = State(
            state.desired_signature,
            event.signature,
            event.quality,
            state.gesture_active,
        )
        return next_state, _effects(next_state, None, None, None)

    return state, _effects(state, None, None, None)
