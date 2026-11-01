"""Small proof boundary for the scope, project, foreground and restart bridge.

This value machine records only identities and physical obligations. Blender
observation and grant transport remain adapter facts, checked by trace tests.
"""
from dataclasses import dataclass, replace
from typing import Literal


@dataclass(frozen=True)
class ComposedState:
    generation: int = 0
    phase: Literal["active", "restarting", "closed"] = "closed"
    view_visible: bool = False
    view_epoch: int = 0
    scope_physical: Literal["none", "live", "retiring"] = "none"
    scope_generation: int = 0
    scope_owner: int | str = 0
    scope_request: int = 0
    scope_submission: int | str = 0
    scope_resource: int | str = 0
    publication_hold: bool = False
    bake_physical: Literal["none", "live", "retiring"] = "none"
    bake_generation: int = 0
    bake_identity: int | str = 0
    restart_obligations: tuple[int | str, ...] = ()
    restart_retired: tuple[int | str, ...] = ()


@dataclass(frozen=True)
class ComposedEvent:
    kind: str
    generation: int = 0
    epoch: int = 0
    identity: int | str = 0
    obligations: tuple[int | str, ...] = ()
    owner: int | str = 0
    request: int = 0
    submission: int | str = 0
    resource: int | str = 0


def new_composed() -> ComposedState:
    return ComposedState()


def _identity(value: int | str) -> bool:
    return value != 0 and value != ""


def _contains(values: tuple[int | str, ...], value: int | str) -> bool:
    count_value = len(values)
    if count_value > 4:
        return False
    if count_value == 0:
        return False
    if count_value == 1:
        return values[0] == value
    if count_value == 2:
        return values[0] == value or values[1] == value
    if count_value == 3:
        return values[0] == value or values[1] == value or values[2] == value
    return (values[0] == value or values[1] == value
            or values[2] == value or values[3] == value)


def _unique(values: tuple[int | str, ...]) -> bool:
    count_value = len(values)
    if count_value > 4:
        return False
    if count_value < 2:
        return True
    if count_value == 2:
        return values[0] != values[1]
    if count_value == 3:
        return (values[0] != values[1] and values[0] != values[2]
                and values[1] != values[2])
    return (values[0] != values[1] and values[0] != values[2]
            and values[0] != values[3] and values[1] != values[2]
            and values[1] != values[3] and values[2] != values[3])


def _same_members(left: tuple[int | str, ...], right: tuple[int | str, ...]) -> bool:
    count_value = len(left)
    if count_value != len(right) or count_value > 4:
        return False
    if count_value == 0:
        return True
    if not _unique(left) or not _unique(right):
        return False
    if count_value == 1:
        return left[0] == right[0]
    if count_value == 2:
        return ((left[0] == right[0] or left[0] == right[1])
                and (left[1] == right[0] or left[1] == right[1]))
    if count_value == 3:
        return ((left[0] == right[0] or left[0] == right[1] or left[0] == right[2])
                and (left[1] == right[0] or left[1] == right[1] or left[1] == right[2])
                and (left[2] == right[0] or left[2] == right[1] or left[2] == right[2]))
    return ((left[0] == right[0] or left[0] == right[1] or left[0] == right[2] or left[0] == right[3])
            and (left[1] == right[0] or left[1] == right[1] or left[1] == right[2] or left[1] == right[3])
            and (left[2] == right[0] or left[2] == right[1] or left[2] == right[2] or left[2] == right[3])
            and (left[3] == right[0] or left[3] == right[1] or left[3] == right[2] or left[3] == right[3]))


def _retired(values: tuple[int | str, ...], identity: int | str) -> tuple[int | str, ...]:
    if _contains(values, identity):
        return values
    return values + (identity,)


def composed_step(state: ComposedState, event: ComposedEvent) -> tuple[ComposedState, bool]:
    if event.kind == "open":
        accepted = (
            event.generation > state.generation and event.generation > 0
            and state.phase in ("active", "closed")
            and state.scope_physical == "none" and state.bake_physical == "none"
        )
        return (ComposedState(event.generation, "active", True, event.epoch), True) if accepted else (state, False)
    if event.kind == "scope_begin":
        accepted = (state.phase == "active" and event.generation > 0
                    and event.generation == state.generation
                    and state.scope_physical == "none" and _identity(event.owner)
                    and event.request > 0 and _identity(event.submission)
                    and _identity(event.resource))
        return (replace(
            state, scope_physical="live", scope_generation=event.generation,
            scope_owner=event.owner, scope_request=event.request,
            scope_submission=event.submission, scope_resource=event.resource,
        ), True) if accepted else (state, False)
    if event.kind == "scope_close":
        accepted = state.phase == "active" and event.generation == state.generation
        return (replace(state, view_visible=False, view_epoch=state.view_epoch + 1,
                        scope_physical="retiring" if state.scope_physical == "live" else state.scope_physical), True) if accepted else (state, False)
    if event.kind == "scope_retired":
        accepted = (
            state.scope_physical == "retiring"
            and event.generation == state.scope_generation
            and event.owner == state.scope_owner
            and event.request == state.scope_request
            and event.submission == state.scope_submission
            and event.resource == state.scope_resource
        )
        return (replace(
            state, scope_physical="none", scope_generation=0, scope_owner=0,
            scope_request=0, scope_submission=0, scope_resource=0,
        ), True) if accepted else (state, False)
    if event.kind == "publication_hold":
        accepted = state.phase == "active" and event.generation == state.generation
        return (replace(state, publication_hold=True), True) if accepted else (state, False)
    if event.kind == "bake_start":
        accepted = (state.phase == "active" and event.generation > 0
                    and event.generation == state.generation
                    and not state.publication_hold and state.bake_physical == "none"
                    and _identity(event.identity))
        return (replace(
            state, bake_physical="live", bake_generation=event.generation,
            bake_identity=event.identity,
        ), True) if accepted else (state, False)
    if event.kind == "bake_retired":
        accepted = (
            state.bake_physical in ("live", "retiring")
            and event.generation == state.bake_generation
            and event.identity == state.bake_identity
        )
        return (replace(
            state, bake_physical="none", bake_generation=0, bake_identity=0,
        ), True) if accepted else (state, False)
    if event.kind == "restart":
        accepted = (event.generation > state.generation and event.generation > 0
                    and state.phase in ("active", "closed") and _unique(event.obligations))
        return (replace(state, generation=event.generation, phase="restarting", view_visible=False,
                        view_epoch=state.view_epoch + 1,
                        scope_physical="retiring" if state.scope_physical == "live" else state.scope_physical,
                        bake_physical="retiring" if state.bake_physical == "live" else state.bake_physical,
                        publication_hold=False, restart_obligations=event.obligations,
                        restart_retired=()), True) if accepted else (state, False)
    if event.kind == "obligation_retired":
        accepted = (state.phase == "restarting" and event.generation == state.generation
                    and _identity(event.identity) and event.identity in state.restart_obligations)
        return (replace(state, restart_retired=_retired(state.restart_retired, event.identity)), True) if accepted else (state, False)
    if event.kind == "restart_complete":
        accepted = (state.phase == "restarting" and event.generation == state.generation
                    and _same_members(state.restart_retired, state.restart_obligations)
                    and state.scope_physical == "none" and state.bake_physical == "none")
        return (replace(state, phase="active", restart_obligations=(), restart_retired=()), True) if accepted else (state, False)
    if event.kind == "close":
        accepted = event.generation == state.generation and state.phase != "closed"
        return (replace(state, phase="closed", view_visible=False, view_epoch=state.view_epoch + 1,
                        publication_hold=False), True) if accepted else (state, False)
    return state, False

