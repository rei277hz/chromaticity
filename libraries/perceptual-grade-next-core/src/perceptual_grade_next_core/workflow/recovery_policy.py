"""Pure reopen policy: fresh authority, no replay of transient operations."""
from dataclasses import dataclass, replace


@dataclass(frozen=True)
class RecoveryState:
    generation: int = 0
    phase: str = "closed"
    queued: bool = False
    replay: bool = False


@dataclass(frozen=True)
class RecoveryEvent:
    kind: str
    generation: int = 0
    derived_valid: bool = False


def new_recovery() -> RecoveryState:
    return RecoveryState()


def recovery_step(state: RecoveryState, event: RecoveryEvent) -> tuple[RecoveryState, bool]:
    if event.kind == "open":
        accepted = event.generation > state.generation and event.generation > 0
        return (RecoveryState(event.generation, "inspecting", False, False), True) if accepted else (state, False)
    if event.kind == "reuse":
        accepted = state.phase == "inspecting" and event.generation == state.generation and event.derived_valid
        return (replace(state, phase="ready", queued=False, replay=False), True) if accepted else (state, False)
    if event.kind == "queue":
        accepted = state.phase == "inspecting" and event.generation == state.generation
        return (replace(state, phase="preparing", queued=True, replay=False), True) if accepted else (state, False)
    if event.kind == "discard":
        accepted = (state.phase in ("inspecting", "preparing")
                    and state.generation == event.generation)
        return (replace(state, replay=False), True) if accepted else (state, False)
    if event.kind == "ready":
        accepted = state.phase == "preparing" and event.generation == state.generation
        return (replace(state, phase="ready", queued=False, replay=False), True) if accepted else (state, False)
    return state, False

