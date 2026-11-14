"""Per-node Grade lifecycle, stack membership, and output policy."""

# pg-book: technical-report/en#next-policy.node-output

from dataclasses import dataclass, replace
from typing import Literal, Optional


@dataclass(frozen=True)
class State:
    desired_signature: Optional[str]
    applied_signature: Optional[str]
    applied_quality: Optional[str]
    gesture_active: bool
    error: Optional[str] = None
    desired_preparation_signature: Optional[str] = None


@dataclass(frozen=True)
class Event:
    kind: Literal[
        "request",
        "preparation_result",
        "installation_result",
        "recovery_result",
        "gesture_begin",
        "gesture_release",
        "stack_replace",
        "grade_changed",
        "presentation",
        "dispose",
    ]
    signature: Optional[str] = None
    error: Optional[str] = None
    quality: str = "full"
    preparation_signature: Optional[str] = None
    stack_changed: bool = False
    grade_referenced: bool = False


@dataclass(frozen=True)
class Effects:
    """Optional output policy and authorized adapter operations."""

    output_mode: Optional[str] = None
    prepare_signature: Optional[str] = None
    build_signature: Optional[str] = None
    build_quality: Optional[str] = None
    error: Optional[str] = None
    rebuild: bool = False
    dispose: bool = False


def new(
    desired_signature: Optional[str] = None,
    applied_signature: Optional[str] = None,
    applied_quality: Optional[str] = None,
    gesture_active: bool = False,
    error: Optional[str] = None,
    desired_preparation_signature: Optional[str] = None,
) -> State:
    if applied_signature is None:
        if applied_quality is not None:
            raise ValueError("Applied quality requires an applied signature")
    elif applied_quality is None:
        applied_quality = "full"
    if applied_quality not in (None, "preview", "full"):
        raise ValueError("Applied quality must be preview or full")
    if error is not None and applied_signature is not None:
        raise ValueError("An error cannot retain an applied kernel")
    if desired_signature is None and applied_signature is not None:
        raise ValueError("An applied kernel requires current demand")
    return State(
        desired_signature,
        applied_signature,
        applied_quality,
        gesture_active,
        error,
        desired_preparation_signature,
    )


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
    prepare: Optional[str] = None,
    build: Optional[str] = None,
    build_quality: Optional[str] = None,
    rebuild: bool = False,
) -> Effects:
    return Effects(
        prepare_signature=prepare,
        build_signature=build,
        build_quality=build_quality,
        error=state.error,
        rebuild=rebuild,
    )


def _transition(state: State, event: Event) -> tuple[State, Effects]:
    """Reduce node lifecycle and scalar Grade Stack observations."""
    if event.kind == "dispose":
        return new(), Effects(dispose=True)

    if event.kind == "presentation":
        return state, _effects(state)

    if event.kind == "stack_replace":
        return state, _effects(state, rebuild=event.stack_changed)

    if event.kind == "grade_changed":
        return state, _effects(state, rebuild=event.grade_referenced)

    if event.kind == "gesture_begin":
        next_state = State(
            state.desired_signature,
            state.applied_signature,
            state.applied_quality,
            True,
            state.error,
            state.desired_preparation_signature,
        )
        return next_state, _effects(next_state)

    if event.kind == "gesture_release":
        next_state = State(
            state.desired_signature,
            state.applied_signature,
            state.applied_quality,
            False,
            state.error,
            state.desired_preparation_signature,
        )
        return next_state, _effects(next_state)

    if event.kind == "request":
        keep_applied = event.signature is not None and state.applied_signature is not None
        preparation_signature = None
        if event.signature is not None:
            preparation_signature = (
                event.preparation_signature
                if event.preparation_signature is not None
                else event.signature
            )
        next_state = State(
            event.signature,
            state.applied_signature if keep_applied else None,
            state.applied_quality if keep_applied else None,
            state.gesture_active,
            desired_preparation_signature=preparation_signature,
        )
        prepare = (
            preparation_signature
            if event.signature is not None
            and (event.signature != state.desired_signature or not output_allowed(next_state))
            else None
        )
        return next_state, _effects(next_state, prepare=prepare)

    if event.error is not None:
        if event.kind == "preparation_result":
            preparation_signature = (
                event.preparation_signature
                if event.preparation_signature is not None
                else event.signature
            )
            current = (
                preparation_signature is not None
                and preparation_signature == state.desired_preparation_signature
            )
        else:
            current = event.signature is None or event.signature == state.desired_signature
        if current:
            next_state = State(
                state.desired_signature,
                None,
                None,
                state.gesture_active,
                event.error,
                state.desired_preparation_signature,
            )
            return next_state, _effects(next_state)
        return state, _effects(state)

    if event.kind == "recovery_result":
        recovery_signature_current = event.signature == state.desired_signature
        if (state.error is None or event.signature is None
                or not recovery_signature_current
                or event.quality != "full"):
            return state, _effects(state)
        next_state = State(
            state.desired_signature,
            event.signature,
            event.quality,
            state.gesture_active,
            desired_preparation_signature=state.desired_preparation_signature,
        )
        return next_state, _effects(next_state)

    if (event.signature is None or state.desired_signature is None
            or state.error is not None):
        return state, _effects(state)

    is_current = event.signature == state.desired_signature
    if event.kind == "preparation_result":
        preparation_signature = (
            event.preparation_signature
            if event.preparation_signature is not None
            else event.signature
        )
        if is_current and preparation_signature != state.desired_preparation_signature:
            return state, _effects(state)
    if not is_current and not state.gesture_active:
        return state, _effects(state)

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
            return state, _effects(state)
        return state, _effects(
            state, build=event.signature, build_quality=event.quality
        )

    if event.kind == "installation_result":
        if output_allowed(state) or already_applied or already_full:
            return state, _effects(state)
        next_state = State(
            state.desired_signature,
            event.signature,
            event.quality,
            state.gesture_active,
            desired_preparation_signature=state.desired_preparation_signature,
        )
        return next_state, _effects(next_state)

    return state, _effects(state)


def step(state: State, event: Event) -> tuple[State, Effects]:
    """Attach the resulting presentation policy to authorized work effects."""
    next_state, effects = _transition(state, event)
    if effects.dispose:
        return next_state, effects
    return next_state, replace(effects, output_mode=output_mode(next_state))
