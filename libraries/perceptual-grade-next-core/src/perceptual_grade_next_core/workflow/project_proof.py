"""Source-bound project owner admission and output receipt predicates.

The checked ledger is bounded to four owners. Blender's observation and native
resource validation remain adapter premises; admitted owner facts are checked
here before Save or Render may start.
"""
from dataclasses import dataclass, replace
from typing import Literal


def _identity(value: int | str) -> bool:
    return value != 0 and value != ""


@dataclass(frozen=True)
class ProjectState:
    generation: int = 0
    phase: Literal["active", "saving", "rendering"] = "active"
    revision: int = 0
    attempt: int = 0
    required_owners: tuple[int | str, ...] = ()
    required_evaluators: tuple[str, ...] = ()
    ready: tuple[bool, bool, bool, bool] = (False, False, False, False)
    ready_revisions: tuple[int, int, int, int] = (0, 0, 0, 0)
    ready_evaluators: tuple[str, str, str, str] = ("", "", "", "")
    ready_evaluator_ids: tuple[bool, bool, bool, bool] = (False, False, False, False)
    ready_manifest_ids: tuple[bool, bool, bool, bool] = (False, False, False, False)
    repair: tuple[bool, bool, bool, bool] = (False, False, False, False)
    bake_phase: Literal["idle", "evaluating", "staged", "publishing", "finished"] = "idle"
    bake_operation: int = 0
    bake_source_revision: int = 0
    bake_source_id: int | str = 0
    bake_evaluator: str = ""
    bake_evaluator_id: int | str = 0
    bake_manifest_id: int | str = 0
    save_operation: int = 0
    save_started: bool = False
    render_operation: int = 0
    render_started: bool = False
    publication_hold: bool = False


@dataclass(frozen=True)
class ProjectEvent:
    kind: str
    generation: int = 0
    operation: int = 0
    source_revision: int = 0
    source_id: int | str = 0
    evaluator: str = ""
    evaluator_id: int | str = 0
    manifest_id: int | str = 0
    result_id: int | str = 0
    committed: bool = False
    owners: tuple[int | str, ...] = ()
    evaluators: tuple[str, ...] = ()
    revision: int = 0
    attempt: int = 0
    owner: int | str = 0
    final_ready: bool = False


def new_project() -> ProjectState:
    return ProjectState()


def _identity_at(values: tuple[int | str, ...], index: int) -> int | str:
    if index == 0 and len(values) > 0: return values[0]
    if index == 1 and len(values) > 1: return values[1]
    if index == 2 and len(values) > 2: return values[2]
    if index == 3 and len(values) > 3: return values[3]
    return 0


def _int_at(values: tuple[int, ...], index: int) -> int:
    if index == 0 and len(values) > 0: return values[0]
    if index == 1 and len(values) > 1: return values[1]
    if index == 2 and len(values) > 2: return values[2]
    if index == 3 and len(values) > 3: return values[3]
    return 0


def _str_at(values: tuple[str, ...], index: int) -> str:
    if index == 0 and len(values) > 0: return values[0]
    if index == 1 and len(values) > 1: return values[1]
    if index == 2 and len(values) > 2: return values[2]
    if index == 3 and len(values) > 3: return values[3]
    return ""


def _bool_at(values: tuple[bool, ...], index: int) -> bool:
    if index == 0 and len(values) > 0: return values[0]
    if index == 1 and len(values) > 1: return values[1]
    if index == 2 and len(values) > 2: return values[2]
    if index == 3 and len(values) > 3: return values[3]
    return False


def _index(values: tuple[int | str, ...], value: int | str) -> int:
    if len(values) > 0 and values[0] == value: return 0
    if len(values) > 1 and values[1] == value: return 1
    if len(values) > 2 and values[2] == value: return 2
    if len(values) > 3 and values[3] == value: return 3
    return -1


def _unique(values: tuple[int | str, ...]) -> bool:
    count = len(values)
    if count > 4: return False
    if count < 2: return True
    if count == 2: return values[0] != values[1]
    if count == 3: return values[0] != values[1] and values[0] != values[2] and values[1] != values[2]
    return (values[0] != values[1] and values[0] != values[2]
            and values[0] != values[3] and values[1] != values[2]
            and values[1] != values[3] and values[2] != values[3])


def _owner_slot_valid(state: ProjectState, slot: int) -> bool:
    return (slot >= 0 and slot < len(state.required_owners)
            and slot < len(state.required_evaluators)
            and _identity(state.required_owners[slot])
            and state.required_evaluators[slot] in ("native_grade_graph", "stack_65_lut"))


def _owner_slot_ready(state: ProjectState, slot: int) -> bool:
    return (slot >= 0 and slot < 4
            and slot < len(state.required_owners)
            and slot < len(state.required_evaluators)
            and state.ready[slot] and not state.repair[slot]
            and state.ready_revisions[slot] == state.revision
            and state.ready_evaluators[slot] == state.required_evaluators[slot]
            and state.ready_evaluator_ids[slot]
            and state.ready_manifest_ids[slot])


def _repair_for(state: ProjectState, owner: int | str) -> bool:
    slot = _index(state.required_owners, owner)
    return slot >= 0 and _bool_at(state.repair, slot)


def _set_bool(values: tuple[bool, bool, bool, bool], index: int, value: bool) -> tuple[bool, bool, bool, bool]:
    if index == 0: return (value, values[1], values[2], values[3])
    if index == 1: return (values[0], value, values[2], values[3])
    if index == 2: return (values[0], values[1], value, values[3])
    if index == 3: return (values[0], values[1], values[2], value)
    return values


def _set_int(values: tuple[int, int, int, int], index: int, value: int) -> tuple[int, int, int, int]:
    if index == 0: return (value, values[1], values[2], values[3])
    if index == 1: return (values[0], value, values[2], values[3])
    if index == 2: return (values[0], values[1], value, values[3])
    if index == 3: return (values[0], values[1], values[2], value)
    return values


def _set_str(values: tuple[str, str, str, str], index: int, value: str) -> tuple[str, str, str, str]:
    if index == 0: return (value, values[1], values[2], values[3])
    if index == 1: return (values[0], value, values[2], values[3])
    if index == 2: return (values[0], values[1], value, values[3])
    if index == 3: return (values[0], values[1], values[2], value)
    return values


def _blank_bool() -> tuple[bool, bool, bool, bool]:
    return (False, False, False, False)


def _blank_int() -> tuple[int, int, int, int]:
    return (0, 0, 0, 0)


def _blank_str() -> tuple[str, str, str, str]:
    return ("", "", "", "")


def _owner_set_valid(state: ProjectState) -> bool:
    count = len(state.required_owners)
    if (count > 4 or not _unique(state.required_owners)
            or len(state.required_evaluators) != count):
        return False
    return ((count < 1 or _owner_slot_valid(state, 0))
            and (count < 2 or _owner_slot_valid(state, 1))
            and (count < 3 or _owner_slot_valid(state, 2))
            and (count < 4 or _owner_slot_valid(state, 3)))


def project_owners_ready(state: ProjectState) -> bool:
    count = len(state.required_owners)
    return (_owner_set_valid(state)
            and (count < 1 or _owner_slot_ready(state, 0))
            and (count < 2 or _owner_slot_ready(state, 1))
            and (count < 3 or _owner_slot_ready(state, 2))
            and (count < 4 or _owner_slot_ready(state, 3)))


def _save_matches(state: ProjectState, event: ProjectEvent) -> bool:
    return (state.phase == "saving" and state.save_started
            and event.operation == state.save_operation)


def bake_completion_matches(state: ProjectState, event: ProjectEvent) -> bool:
    """Production receipt predicate shared by the full project workflow."""
    return (state.bake_phase == "publishing" and event.operation == state.bake_operation
            and event.source_revision == state.bake_source_revision
            and event.source_id == state.bake_source_id and event.evaluator == state.bake_evaluator
            and event.evaluator_id == state.bake_evaluator_id and event.manifest_id == state.bake_manifest_id
            and _identity(event.result_id) and event.committed)


def save_completion_matches(state: ProjectState, event: ProjectEvent) -> bool:
    """Production Save terminal receipt predicate."""
    return _save_matches(state, event)


def render_completion_matches(state: ProjectState, event: ProjectEvent) -> bool:
    """Production Render terminal receipt predicate."""
    return (state.phase == "rendering" and state.render_started and state.publication_hold
            and event.operation == state.render_operation)


def project_step(state: ProjectState, event: ProjectEvent) -> tuple[ProjectState, bool]:
    if event.kind == "open":
        candidate = replace(state, generation=event.generation, required_owners=event.owners,
                            required_evaluators=event.evaluators)
        if (event.generation > state.generation and event.generation > 0 and _owner_set_valid(candidate)):
            return ProjectState(generation=event.generation, required_owners=event.owners,
                                 required_evaluators=event.evaluators, ready=_blank_bool(),
                                 ready_revisions=_blank_int(), ready_evaluators=_blank_str(),
                                 ready_evaluator_ids=_blank_bool(), ready_manifest_ids=_blank_bool(),
                                 repair=_blank_bool()), True
        return state, False
    if event.generation != state.generation or state.phase not in ("active", "saving", "rendering"):
        return state, False
    if event.kind == "intent":
        if event.revision > state.revision and event.revision > 0 and state.phase == "active":
            return replace(state, revision=event.revision, ready=_blank_bool(),
                           ready_revisions=_blank_int(), ready_evaluators=_blank_str(),
                           ready_evaluator_ids=_blank_bool(), ready_manifest_ids=_blank_bool(),
                           repair=_blank_bool()), True
        return state, False
    if event.kind == "prepare_begin":
        if event.revision == state.revision and event.attempt > state.attempt:
            return replace(state, attempt=event.attempt), True
        return state, False
    if event.kind == "owner_ready":
        slot = _index(state.required_owners, event.owner)
        if (slot < 0 or event.revision != state.revision or event.attempt != state.attempt
                or not event.final_ready or event.evaluator != _str_at(state.required_evaluators, slot)
                or _repair_for(state, event.owner) or not _identity(event.evaluator_id)
                or not _identity(event.manifest_id)):
            return state, False
        return replace(state, ready=_set_bool(state.ready, slot, True),
                       ready_revisions=_set_int(state.ready_revisions, slot, event.revision),
                       ready_evaluators=_set_str(state.ready_evaluators, slot, event.evaluator),
                       ready_evaluator_ids=_set_bool(state.ready_evaluator_ids, slot, _identity(event.evaluator_id)),
                       ready_manifest_ids=_set_bool(state.ready_manifest_ids, slot, _identity(event.manifest_id))), True
    if event.kind in ("owner_failed", "output_owner_failed"):
        slot = _index(state.required_owners, event.owner)
        phase_ok = state.phase == "active" if event.kind == "owner_failed" else state.phase in ("active", "saving", "rendering")
        if (slot < 0 or not phase_ok or event.revision != state.revision or event.attempt != state.attempt):
            return state, False
        return replace(state, ready=_set_bool(state.ready, slot, False), repair=_set_bool(state.repair, slot, True),
                       ready_revisions=_set_int(state.ready_revisions, slot, 0),
                       ready_evaluators=_set_str(state.ready_evaluators, slot, ""),
                       ready_evaluator_ids=_set_bool(state.ready_evaluator_ids, slot, False),
                       ready_manifest_ids=_set_bool(state.ready_manifest_ids, slot, False)), True
    if event.kind == "retry_owner":
        slot = _index(state.required_owners, event.owner)
        if (slot < 0 or event.revision != state.revision or event.attempt <= state.attempt
                or not _bool_at(state.repair, slot)):
            return state, False
        return replace(state, attempt=event.attempt, ready=_set_bool(state.ready, slot, False),
                       repair=_set_bool(state.repair, slot, False),
                       ready_revisions=_set_int(state.ready_revisions, slot, 0),
                       ready_evaluators=_set_str(state.ready_evaluators, slot, ""),
                       ready_evaluator_ids=_set_bool(state.ready_evaluator_ids, slot, False),
                       ready_manifest_ids=_set_bool(state.ready_manifest_ids, slot, False)), True
    if event.kind == "bake_request":
        ok = (state.phase == "active" and state.bake_phase == "idle" and event.operation > state.bake_operation
              and event.source_revision > 0 and _identity(event.source_id) and _identity(event.evaluator_id)
              and _identity(event.manifest_id))
        if not ok: return state, False
        return replace(state, bake_phase="evaluating", bake_operation=event.operation,
                       bake_source_revision=event.source_revision, bake_source_id=event.source_id,
                       bake_evaluator=event.evaluator, bake_evaluator_id=event.evaluator_id,
                       bake_manifest_id=event.manifest_id), True
    if event.kind == "bake_started":
        ok = state.bake_phase == "evaluating" and event.operation == state.bake_operation
        return (replace(state, bake_phase="staged"), True) if ok else (state, False)
    if event.kind == "bake_publishing":
        ok = state.bake_phase == "staged" and event.operation == state.bake_operation
        return (replace(state, bake_phase="publishing"), True) if ok else (state, False)
    if event.kind == "bake_complete":
        ok = bake_completion_matches(state, event)
        return (replace(state, bake_phase="finished"), True) if ok else (state, False)
    if event.kind == "save_request":
        ok = state.phase == "active" and event.operation > state.save_operation
        return (replace(state, phase="saving", save_operation=event.operation, publication_hold=True), True) if ok else (state, False)
    if event.kind == "save_ready":
        ok = state.phase == "saving" and event.operation == state.save_operation and project_owners_ready(state)
        return (replace(state, save_started=True), True) if ok else (state, False)
    if event.kind in ("save_complete", "save_failed"):
        ok = save_completion_matches(state, event)
        return (replace(state, phase="active", save_started=False, publication_hold=False), True) if ok else (state, False)
    if event.kind == "render_request":
        ok = state.phase == "active" and event.operation > state.render_operation
        return (replace(state, phase="rendering", render_operation=event.operation, publication_hold=True), True) if ok else (state, False)
    if event.kind == "render_started":
        ok = (state.phase == "rendering" and event.operation == state.render_operation
              and state.publication_hold and project_owners_ready(state))
        return (replace(state, render_started=True), True) if ok else (state, False)
    if event.kind in ("render_complete", "render_cancel", "render_failed"):
        ok = render_completion_matches(state, event)
        return (replace(state, phase="active", render_started=False, publication_hold=False), True) if ok else (state, False)
    return state, False
