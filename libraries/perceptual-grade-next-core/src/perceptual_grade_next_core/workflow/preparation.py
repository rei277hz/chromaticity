"""Pure static-preparation admission and crash ledger policy."""
from dataclasses import dataclass, replace


def _identity(value: int | str) -> bool:
    return value != 0 and value != ""


@dataclass(frozen=True)
class PreparationState:
    owner: int | str = 0
    revision: int = 0
    attempt: int = 0
    stage: str = "idle"
    prior: int | str = 0
    candidate: int | str = 0
    manifest: int | str = 0
    repair: bool = False


@dataclass(frozen=True)
class PreparationEvent:
    kind: str
    owner: int | str = 0
    revision: int = 0
    attempt: int = 0
    prior: int | str = 0
    candidate: int | str = 0
    manifest: int | str = 0
    validated: bool = False


def new_preparation() -> PreparationState:
    return PreparationState()


def preparation_step(state: PreparationState, event: PreparationEvent) -> tuple[PreparationState, bool]:
    if event.kind == "begin":
        accepted = (_identity(event.owner) and event.revision > state.revision and event.attempt > state.attempt
                    and _identity(event.prior) and _identity(event.candidate)
                    and event.candidate != event.prior)
        return (PreparationState(event.owner, event.revision, event.attempt, "staging", event.prior, event.candidate, 0, False), True) if accepted else (state, False)
    if event.kind == "validated":
        accepted = (state.stage == "staging" and event.owner == state.owner and event.revision == state.revision
                    and event.attempt == state.attempt and event.candidate == state.candidate
                    and event.validated and _identity(event.manifest))
        return (replace(state, stage="validated", manifest=event.manifest), True) if accepted else (state, False)
    if event.kind == "commit":
        accepted = (state.stage == "validated" and event.owner == state.owner and event.revision == state.revision
                    and event.attempt == state.attempt and event.candidate == state.candidate
                    and event.manifest == state.manifest)
        return (replace(state, stage="ready"), True) if accepted else (state, False)
    if event.kind == "fail":
        accepted = (state.stage in ("staging", "validated") and event.owner == state.owner
                    and event.revision == state.revision and event.attempt == state.attempt)
        return (replace(state, stage="repair", repair=True), True) if accepted else (state, False)
    if event.kind == "recover":
        accepted = (state.stage == "repair" and event.owner == state.owner and event.revision == state.revision
                    and event.prior == state.prior)
        return (replace(state, stage="idle", candidate=0, manifest=0, repair=False), True) if accepted else (state, False)
    return state, False

