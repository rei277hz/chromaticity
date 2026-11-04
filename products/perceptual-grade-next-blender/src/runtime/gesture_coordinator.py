"""Trusted gesture collection bookkeeping; scalar policy authorizes transitions."""

from dataclasses import dataclass, replace
from typing import Literal, Optional

from ..policy import gesture as policy


@dataclass(frozen=True)
class Target:
    node_id: int
    signature: Optional[str]


@dataclass(frozen=True)
class Observer:
    window_id: int
    current_token: Optional[int]
    pending_token: Optional[int]


@dataclass(frozen=True)
class Gesture:
    window_id: int
    token: int
    phase: Literal["armed", "active", "finishing_armed", "finishing_active"]
    press_x: int
    press_y: int
    undo_owner: Literal["native", "adapter"]
    targets: tuple[Target, ...]


@dataclass(frozen=True)
class State:
    serial: int
    observers: tuple[Observer, ...]
    gestures: tuple[Gesture, ...]


@dataclass(frozen=True)
class Action:
    kind: Literal[
        "invoke_observer", "schedule_handoff", "schedule_finish", "node_begin",
        "node_release", "refresh", "forget_node", "clear_registry",
        "report_install_failure",
    ]
    window_id: Optional[int] = None
    token: Optional[int] = None
    gesture_token: Optional[int] = None
    node_id: Optional[int] = None


@dataclass(frozen=True)
class Effects:
    """Node begin includes refresh; the optional checkpoint follows all actions."""
    actions: tuple[Action, ...] = ()
    undo_window: Optional[int] = None


@dataclass(frozen=True)
class Event:
    kind: Literal[
        "window_seen", "window_gone", "observer_install_result", "observer_lost",
        "press", "move", "activate", "finish", "finish_requested", "finish_observed",
        "handoff_due", "node_disposed", "reset",
    ]
    window_id: Optional[int] = None
    token: Optional[int] = None
    gesture_token: Optional[int] = None
    node_id: Optional[int] = None
    x: int = 0
    y: int = 0
    undo_owner: Literal["native", "adapter"] = "native"
    targets: tuple[Target, ...] = ()
    observed: tuple[Target, ...] = ()
    success: bool = False
    latest: Literal["none", "move", "finish"] = "none"


def new() -> State:
    return State(policy.new().serial, (), ())


def has_target(targets: tuple[Target, ...], node_id: int) -> bool:
    found = False
    for target in targets:
        found = found or target.node_id == node_id
    return found


def signature_for(targets: tuple[Target, ...], node_id: int) -> Optional[str]:
    signature: Optional[str] = None
    for target in targets:
        if target.node_id == node_id:
            signature = target.signature
    return signature


def active_for(state: State, node_id: int) -> bool:
    active = False
    for gesture in state.gestures:
        active = active or (policy.active_participant(gesture.phase)
                            and has_target(gesture.targets, node_id))
    return active


def armed_for(state: State, node_id: int) -> bool:
    armed = False
    for gesture in state.gestures:
        armed = armed or (policy.armed_participant(gesture.phase)
                          and has_target(gesture.targets, node_id))
    return armed


def current_observer(state: State, window_id: int) -> Optional[int]:
    token: Optional[int] = None
    for observer in state.observers:
        if observer.window_id == window_id:
            token = observer.current_token
    return token


def pending_observer(state: State, window_id: int) -> Optional[int]:
    token: Optional[int] = None
    for observer in state.observers:
        if observer.window_id == window_id:
            token = observer.pending_token
    return token


def observer_status(state: State, window_id: int, token: int) -> Literal["current", "pending", "stale"]:
    return policy.observer_status(current_observer(state, window_id),
                                  pending_observer(state, window_id), token)


def current_gesture(state: State, window_id: int) -> Optional[int]:
    token: Optional[int] = None
    for gesture in state.gestures:
        if gesture.window_id == window_id:
            token = gesture.token
    return token


def gesture_index(gestures: tuple[Gesture, ...], window_id: int) -> Optional[int]:
    selected: Optional[int] = None
    for index in range(len(gestures)):
        if gestures[index].window_id == window_id:
            selected = index
    return selected


def replace_gesture(gestures: tuple[Gesture, ...], index: int, gesture: Gesture) -> tuple[Gesture, ...]:
    if index < 0 or index >= len(gestures):
        return gestures
    return gestures[:index] + (gesture,) + gestures[index + 1:]


def gesture_phase(state: State, window_id: int) -> Optional[str]:
    phase: Optional[str] = None
    for gesture in state.gestures:
        if gesture.window_id == window_id:
            phase = gesture.phase
    return phase


def gesture_targets(state: State, window_id: int) -> tuple[Target, ...]:
    targets: tuple[Target, ...] = ()
    for gesture in state.gestures:
        if gesture.window_id == window_id:
            targets = gesture.targets
    return targets


def without_observer(observers: tuple[Observer, ...], window_id: int) -> tuple[Observer, ...]:
    selected: Optional[int] = None
    for index in range(len(observers)):
        if observers[index].window_id == window_id:
            selected = index
    if selected is None:
        return observers
    return observers[:selected] + observers[selected + 1:]


def without_gesture(gestures: tuple[Gesture, ...], window_id: int) -> tuple[Gesture, ...]:
    index = gesture_index(gestures, window_id)
    if index is None:
        return gestures
    return gestures[:index] + gestures[index + 1:]


def without_target(targets: tuple[Target, ...], node_id: int) -> tuple[Target, ...]:
    selected: Optional[int] = None
    for index in range(len(targets)):
        if targets[index].node_id == node_id:
            selected = index
    if selected is None:
        return targets
    return targets[:selected] + targets[selected + 1:]


def put_observer(state: State, observer: Observer) -> State:
    return replace(state, observers=without_observer(state.observers, observer.window_id)
                   + (observer,))


def _observer_event(state: State, event: Event) -> tuple[State, Effects]:
    window = event.window_id
    kind = {"window_seen": "window_seen", "handoff_due": "handoff",
            "observer_install_result": "installed", "observer_lost": "lost"}[event.kind]
    before = policy.State(state.serial, current_observer(state, window),
                          pending_observer(state, window))
    observed, effects = policy.step(before, policy.Event(
        kind, token=event.token, success=event.success, gesture_token=event.gesture_token,
        current_gesture_token=current_gesture(state, window), phase=gesture_phase(state, window)))
    updated = state
    if observed != before:
        updated = put_observer(replace(state, serial=observed.serial),
                               Observer(window, observed.current_token, observed.pending_token))
    actions = ()
    if effects.invoke_token is not None:
        actions += (Action("invoke_observer", window, effects.invoke_token,
                           current_gesture(updated, window)),)
    if effects.report_failure:
        actions += (Action("report_install_failure", window, event.token),)
    if effects.installed:
        replay = policy.after_install(current_gesture(updated, window), event.gesture_token,
                                      gesture_phase(updated, window), event.latest)
        if replay == "finish":
            return request_finish(updated, window, event.gesture_token)
        if replay == "move":
            return move(updated, window, event.gesture_token, event.x, event.y)
        if replay == "handoff":
            actions += (Action("schedule_handoff", window, event.token,
                               current_gesture(updated, window)),)
    return updated, Effects(actions)


def activate(state: State, window_id: int, token: Optional[int]) -> tuple[State, Effects]:
    index = gesture_index(state.gestures, window_id)
    if index is None:
        return state, Effects()
    gesture = state.gestures[index]
    if not policy.activation_allowed(gesture.token, token, gesture.phase):
        return state, Effects()
    gestures = replace_gesture(state.gestures, index, replace(gesture, phase="active"))
    return replace(state, gestures=gestures), Effects(activation_actions(state, gesture))


def activation_actions(state: State, gesture: Gesture) -> tuple[Action, ...]:
    actions: tuple[Action, ...] = ()
    for target in gesture.targets:
        kind = policy.participant_begin(active_for(state, target.node_id))
        actions = actions + (Action(kind, node_id=target.node_id),)
    return actions


def move(state: State, window_id: int, token: Optional[int], x: int, y: int) -> tuple[State, Effects]:
    index = gesture_index(state.gestures, window_id)
    if index is None:
        return state, Effects()
    gesture = state.gestures[index]
    if policy.crossed_threshold(gesture.press_x, gesture.press_y, x, y):
        return activate(state, window_id, token)
    return state, Effects()


def request_finish(state: State, window_id: int, token: Optional[int]) -> tuple[State, Effects]:
    index = gesture_index(state.gestures, window_id)
    if index is None:
        return state, Effects()
    gesture = state.gestures[index]
    phase = policy.deferred_phase(gesture.token, token, gesture.phase)
    if phase is None:
        return state, Effects()
    gestures = replace_gesture(state.gestures, index, replace(gesture, phase=phase))
    return replace(state, gestures=gestures), Effects((
        Action("schedule_finish", window_id, gesture_token=gesture.token),))


def finish_actions(after: State, gesture: Gesture, observed: tuple[Target, ...]) -> Effects:
    actions: tuple[Action, ...] = ()
    changed = False
    for target in gesture.targets:
        target_changed = target.signature != signature_for(observed, target.node_id)
        action = policy.participant_finish(gesture.phase, has_target(observed, target.node_id),
                                           target_changed, active_for(after, target.node_id))
        if action is not None:
            actions += (Action(action, node_id=target.node_id),)
            changed = changed or target_changed
    return Effects(actions, gesture.window_id if policy.manual_undo(gesture.undo_owner, changed) else None)


def finish(state: State, window_id: int, token: Optional[int], observed: tuple[Target, ...]) -> tuple[State, Effects]:
    index = gesture_index(state.gestures, window_id)
    if index is None:
        return state, Effects()
    gesture = state.gestures[index]
    if not policy.finish_allowed(gesture.token, token):
        return state, Effects()
    updated = replace(state, gestures=without_gesture(state.gestures, window_id))
    return updated, finish_actions(updated, gesture, observed)


def dispose_target(state: State, node_id: int) -> tuple[State, Effects]:
    gestures: tuple[Gesture, ...] = ()
    for gesture in state.gestures:
        targets = without_target(gesture.targets, node_id)
        if len(targets) != 0:
            gestures = gestures + (replace(gesture, targets=targets),)
    return replace(state, gestures=gestures), Effects((Action("forget_node", node_id=node_id),))


def step(state: State, event: Event) -> tuple[State, Effects]:
    if event.kind == "reset":
        reset, effects = policy.step(policy.State(state.serial), policy.Event("reset"))
        actions = (Action("clear_registry"),) if effects.clear_registry else ()
        return State(reset.serial, (), ()), Effects(actions)
    if event.kind == "node_disposed":
        if event.node_id is None:
            return state, Effects()
        return dispose_target(state, event.node_id)
    if event.window_id is None:
        return state, Effects()
    window = event.window_id
    if event.kind in ("window_seen", "observer_install_result", "observer_lost"):
        return _observer_event(state, event)
    if event.kind == "window_gone":
        updated, effects = finish(state, window, current_gesture(state, window), event.observed)
        return replace(updated, observers=without_observer(updated.observers, window)), effects
    if event.kind == "finish_observed":
        if not policy.observation_allowed(gesture_phase(state, window)):
            return state, Effects()
        return finish(state, window, event.gesture_token, event.observed)
    if event.kind == "finish":
        return finish(state, window, event.gesture_token, event.observed)
    if event.kind == "activate":
        return activate(state, window, event.gesture_token)
    if event.kind in ("press", "move", "finish_requested", "handoff_due"):
        if not policy.input_allowed(current_observer(state, window), event.token):
            return state, Effects()
        if event.kind == "press":
            updated, effects = finish(state, window, current_gesture(state, window), event.observed)
            if len(event.targets) == 0:
                return updated, effects
            token = policy.allocate(updated.serial)
            gesture = Gesture(window, token, "armed", event.x, event.y,
                              event.undo_owner, event.targets)
            updated = replace(updated, serial=token, gestures=updated.gestures + (gesture,))
            actions = effects.actions
            if policy.press_handoff(event.token):
                actions = actions + (Action("schedule_handoff", window, event.token, token),)
            return updated, replace(effects, actions=actions)
        if event.kind == "move":
            return move(state, window, event.gesture_token, event.x, event.y)
        if event.kind == "finish_requested":
            return request_finish(state, window, event.gesture_token)
        return _observer_event(state, event)
    return state, Effects()
