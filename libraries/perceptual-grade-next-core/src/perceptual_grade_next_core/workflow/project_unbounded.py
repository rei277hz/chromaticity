"""Source-bound scalar worklist projection for unbounded owner readiness."""

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class ReadinessState:
    revision: int = 0
    owners: tuple[int | str, ...] = ()
    evaluator_owners: tuple[int | str, ...] = ()
    evaluators: tuple[str, ...] = ()
    ready_owners: tuple[int | str, ...] = ()
    repair_owners: tuple[int | str, ...] = ()
    artifact_owners: tuple[int | str, ...] = ()
    artifact_revisions: tuple[int, ...] = ()
    artifact_evaluators: tuple[str, ...] = ()
    artifact_ids: tuple[int | str, ...] = ()
    manifest_ids: tuple[int | str, ...] = ()


@dataclass(frozen=True)
class ReadinessEvent:
    kind: Literal["check"]


def _identity(value: int | str) -> bool:
    return value != 0 and value != ""


def _count(values: tuple[int | str, ...], value: int | str) -> int:
    total = 0
    for item in values:
        if item == value:
            total = total + 1
    return total


def _unique(values: tuple[int | str, ...]) -> bool:
    seen: tuple[int | str, ...] = ()
    for item in values:
        if item in seen:
            return False
        seen = seen + (item,)
    return True


def _index(values: tuple[int | str, ...], value: int | str) -> int:
    index = 0
    for item in values:
        if item == value:
            return index
        index = index + 1
    return -1


def _artifact_valid(state: ReadinessState, owner: int | str) -> bool:
    index = _index(state.artifact_owners, owner)
    if (index < 0 or index >= len(state.artifact_revisions)
            or index >= len(state.artifact_evaluators)
            or index >= len(state.artifact_ids) or index >= len(state.manifest_ids)):
        return False
    evaluator = state.artifact_evaluators[index]
    return (state.artifact_revisions[index] == state.revision
            and (evaluator == "native_grade_graph" or evaluator == "stack_65_lut")
            and _identity(state.artifact_ids[index])
            and _identity(state.manifest_ids[index]))


def _owner_artifact_matches(state: ReadinessState, owner: int | str) -> bool:
    evaluator_index = _index(state.evaluator_owners, owner)
    artifact_index = _index(state.artifact_owners, owner)
    if (evaluator_index < 0 or evaluator_index >= len(state.evaluators)
            or artifact_index < 0 or artifact_index >= len(state.artifact_evaluators)):
        return False
    return state.artifact_evaluators[artifact_index] == state.evaluators[evaluator_index]


def _ready_entry_matches(
    owner: int | str,
    evaluator: str,
    artifact_revision: int,
    artifact_evaluator: str,
    artifact_id: int | str,
    manifest_id: int | str,
    revision: int,
) -> bool:
    return (owner != 0 and owner != ""
            and evaluator in ("native_grade_graph", "stack_65_lut")
            and artifact_revision == revision
            and artifact_evaluator == evaluator
            and artifact_id != 0 and artifact_id != ""
            and manifest_id != 0 and manifest_id != "")


def owners_ready(state: ReadinessState) -> bool:
    count = len(state.owners)
    if (not _unique(state.owners)
            or state.evaluator_owners != state.owners
            or len(state.evaluators) != len(state.evaluator_owners)
            or state.ready_owners != state.owners
            or state.artifact_owners != state.owners
            or len(state.artifact_revisions) != len(state.artifact_owners)
            or len(state.artifact_evaluators) != len(state.artifact_owners)
            or len(state.artifact_ids) != len(state.artifact_owners)
            or len(state.manifest_ids) != len(state.artifact_owners)
            or state.repair_owners != ()):
        return False
    for index in range(count):
        owner = state.owners[index]
        evaluator = state.evaluators[index]
        if not _ready_entry_matches(
                owner, evaluator, state.artifact_revisions[index],
                state.artifact_evaluators[index], state.artifact_ids[index],
                state.manifest_ids[index], state.revision):
            return False
    return True


def new_readiness() -> ReadinessState:
    return ReadinessState()


def readiness_step(state: ReadinessState, event: ReadinessEvent) -> tuple[ReadinessState, bool]:
    return (state, owners_ready(state)) if event.kind == "check" else (state, False)
