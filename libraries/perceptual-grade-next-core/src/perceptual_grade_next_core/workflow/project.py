"""Portable admission policy for static preparation and native output."""
from dataclasses import dataclass, replace
from typing import Literal

from .project_proof import (
    bake_completion_matches,
    render_completion_matches,
    save_completion_matches,
)


def _identity(value: int | str) -> bool:
    return value != 0 and value != ""


def _contains(values: tuple[int | str, ...], value: int | str) -> bool:
    for item in values:
        if item == value:
            return True
    return False


def _count(values: tuple[int | str, ...], value: int | str) -> int:
    count_value = 0
    for item in values:
        if item == value:
            count_value = count_value + 1
    return count_value


def _unique(values: tuple[int | str, ...]) -> bool:
    for item in values:
        if _count(values, item) != 1:
            return False
    return True


def _same_members(left: tuple[int | str, ...], right: tuple[int | str, ...]) -> bool:
    if len(left) != len(right) or not _unique(left) or not _unique(right):
        return False
    for item in left:
        if not _contains(right, item):
            return False
    return True


def _without(values: tuple[int | str, ...], value: int | str) -> tuple[int | str, ...]:
    remaining = ()
    for item in values:
        if item != value:
            remaining = remaining + (item,)
    return remaining


def _add_unique(values: tuple[int | str, ...], value: int | str) -> tuple[int | str, ...]:
    if _contains(values, value):
        return values
    return values + (value,)


def _evaluator_for(
    values: tuple[tuple[int | str, str], ...], owner: int | str
) -> str:
    for item in values:
        if item[0] == owner:
            return item[1]
    return ""


def _artifact_index(
    values: tuple[tuple[int | str, int, str, int | str, int | str], ...],
    owner: int | str,
) -> int:
    index = 0
    for item in values:
        if item[0] == owner:
            return index
        index = index + 1
    return -1


def _preview_index(
    values: tuple[tuple[int | str, int, int | str, int | str], ...],
    owner: int | str,
) -> int:
    index = 0
    for item in values:
        if item[0] == owner:
            return index
        index = index + 1
    return -1


def _artifact_for(
    values: tuple[tuple[int | str, int, str, int | str, int | str], ...],
    owner: int | str,
) -> tuple[int | str, int, str, int | str, int | str]:
    for item in values:
        if item[0] == owner:
            return item
    return (0, 0, "", 0, 0)


def _preview_for(
    values: tuple[tuple[int | str, int, int | str, int | str], ...],
    owner: int | str,
) -> tuple[int | str, int, int | str, int | str]:
    for item in values:
        if item[0] == owner:
            return item
    return (0, 0, 0, 0)


def _append_artifact(
    values: tuple[tuple[int | str, int, str, int | str, int | str], ...],
    item: tuple[int | str, int, str, int | str, int | str],
) -> tuple[tuple[int | str, int, str, int | str, int | str], ...]:
    return _without_artifact(values, item[0]) + (item,)


def _append_preview(
    values: tuple[tuple[int | str, int, int | str, int | str], ...],
    item: tuple[int | str, int, int | str, int | str],
) -> tuple[tuple[int | str, int, int | str, int | str], ...]:
    return _without_preview(values, item[0]) + (item,)


def _without_artifact(
    values: tuple[tuple[int | str, int, str, int | str, int | str], ...],
    owner: int | str,
) -> tuple[tuple[int | str, int, str, int | str, int | str], ...]:
    remaining = ()
    for item in values:
        if item[0] != owner:
            remaining = remaining + (item,)
    return remaining


def _without_preview(
    values: tuple[tuple[int | str, int, int | str, int | str], ...],
    owner: int | str,
) -> tuple[tuple[int | str, int, int | str, int | str], ...]:
    remaining = ()
    for item in values:
        if item[0] != owner:
            remaining = remaining + (item,)
    return remaining


def _ready_artifact_owners(
    values: tuple[tuple[int | str, int, str, int | str, int | str], ...],
) -> tuple[int | str, ...]:
    owners = ()
    for item in values:
        owners = owners + (item[0],)
    return owners


def _artifacts_revision_bound(
    values: tuple[tuple[int | str, int, str, int | str, int | str], ...],
    revision: int,
) -> bool:
    for item in values:
        if item[1] != revision:
            return False
    return True

@dataclass(frozen=True)
class ProjectState:
    generation: int = 0
    phase: Literal["active", "saving", "rendering", "restarting", "closed"] = "active"
    intent_revision: int = 0
    required_owners: tuple[int | str, ...] = ()
    required_evaluators: tuple[tuple[int | str, str], ...] = ()
    ready_owners: tuple[int | str, ...] = ()
    ready_artifacts: tuple[tuple[int | str, int, str, int | str, int | str], ...] = ()
    preview_artifacts: tuple[tuple[int | str, int, int | str, int | str], ...] = ()
    repair_owners: tuple[int | str, ...] = ()
    preparation_attempt: int = 0
    bake_phase: Literal["idle", "waiting_for_final", "evaluating", "staged", "publishing", "finished", "cancelled", "failed"] = "idle"
    bake_physical: Literal["none", "live", "retiring"] = "none"
    bake_operation: int = 0
    bake_owner: int | str = 0
    bake_source_revision: int = 0
    bake_source_id: int | str = 0
    bake_evaluator: str = ""
    bake_evaluator_id: int | str = 0
    bake_manifest_id: int | str = 0
    bake_preview_id: int | str = 0
    bake_result_id: int | str = 0
    restart_obligations: tuple[int | str, ...] = ()
    restart_retired: tuple[int | str, ...] = ()
    publication_hold: bool = False
    save_operation: int = 0
    save_started: bool = False
    render_operation: int = 0
    render_started: bool = False

@dataclass(frozen=True)
class ProjectEvent:
    kind: str
    generation: int = 0
    revision: int = 0
    attempt: int = 0
    owner: int | str = 0
    owners: tuple[int | str, ...] = ()
    owner_evaluators: tuple[tuple[int | str, str], ...] = ()
    preview_id: int | str = 0
    evaluator: str = ""
    evaluator_id: int | str = 0
    manifest_id: int | str = 0
    obligations: tuple[int | str, ...] = ()
    source_revision: int = 0
    source_id: int | str = 0
    operation: int = 0
    result_id: int | str = 0
    final_ready: bool = False
    committed: bool = False

def new_project() -> ProjectState:
    return ProjectState()

def _owners(values: tuple[int | str, ...]) -> bool:
    if not _unique(values):
        return False
    for value in values:
        if not _identity(value):
            return False
    return True

def _evaluator_requirements(
    owners: tuple[int | str, ...], values: tuple[tuple[int | str, str], ...]
) -> bool:
    if len(values) != len(owners):
        return False
    seen = ()
    for item in values:
        owner = item[0]
        evaluator = item[1]
        if not _contains(owners, owner) or _contains(seen, owner):
            return False
        if evaluator != "native_grade_graph" and evaluator != "stack_65_lut":
            return False
        seen = seen + (owner,)
    return True

def _all_owners_ready(state: ProjectState) -> bool:
    return _all_owners_ready_unbounded(state)


def _all_owners_ready_unbounded(state: ProjectState) -> bool:
    from .project_unbounded import ReadinessState, owners_ready
    owners = state.required_owners
    if (not isinstance(owners, tuple)
            or any(type(owner) not in (int, str) or not _identity(owner)
                   for owner in owners)
            or len(set(owners)) != len(owners)
            or state.repair_owners != ()):
        return False

    def align(records, width):
        if not isinstance(records, tuple) or len(records) != len(owners):
            return None
        aligned = []
        for owner in owners:
            first = None
            for record in records:
                if not isinstance(record, tuple) or len(record) != width:
                    return None
                if record[0] == owner:
                    if first is not None:
                        return None
                    first = record
            if first is None:
                return None
            aligned.append(first)
        return tuple(aligned)

    def align_ids(values):
        if not isinstance(values, tuple) or len(values) != len(owners):
            return False
        for owner in owners:
            count = 0
            for value in values:
                if type(value) not in (int, str) or not _identity(value):
                    return False
                count += value == owner
            if count != 1:
                return False
        return True

    evaluators = align(state.required_evaluators, 2)
    artifacts = align(state.ready_artifacts, 5)
    if evaluators is None or artifacts is None or not align_ids(state.ready_owners):
        return False
    evaluator_values = tuple(item[1] for item in evaluators)
    if any(value not in ("native_grade_graph", "stack_65_lut")
           for value in evaluator_values):
        return False
    if any(type(item[1]) is not int or item[1] < 0
           or item[2] not in ("native_grade_graph", "stack_65_lut")
           or type(item[3]) not in (int, str) or not _identity(item[3])
           or type(item[4]) not in (int, str) or not _identity(item[4])
           for item in artifacts):
        return False
    return owners_ready(ReadinessState(
        revision=state.intent_revision,
        owners=owners,
        evaluator_owners=owners,
        evaluators=evaluator_values,
        ready_owners=owners,
        repair_owners=(),
        artifact_owners=owners,
        artifact_revisions=tuple(item[1] for item in artifacts),
        artifact_evaluators=tuple(item[2] for item in artifacts),
        artifact_ids=tuple(item[3] for item in artifacts),
        manifest_ids=tuple(item[4] for item in artifacts),
    ))


def project_proof_state(state: ProjectState):
    """Project up to four ordered owners into the checked scalar-slot kernel."""
    from .project_proof import ProjectState as ProofProjectState

    owners = state.required_owners
    artifacts = tuple(_artifact_for(state.ready_artifacts, owner) for owner in owners)
    return ProofProjectState(
        generation=state.generation,
        phase=state.phase,
        revision=state.intent_revision,
        attempt=state.preparation_attempt,
        required_owners=owners,
        required_evaluators=tuple(_evaluator_for(state.required_evaluators, owner)
                                  for owner in owners),
        ready=tuple(_contains(state.ready_owners, owner) for owner in owners)
              + (False,) * (4 - len(owners)),
        ready_revisions=tuple(item[1] for item in artifacts) + (0,) * (4 - len(owners)),
        ready_evaluators=tuple(item[2] for item in artifacts) + ("",) * (4 - len(owners)),
        ready_evaluator_ids=tuple(_identity(item[3]) for item in artifacts)
                            + (False,) * (4 - len(owners)),
        ready_manifest_ids=tuple(_identity(item[4]) for item in artifacts)
                          + (False,) * (4 - len(owners)),
        repair=tuple(_contains(state.repair_owners, owner) for owner in owners)
              + (False,) * (4 - len(owners)),
        bake_phase=state.bake_phase,
        bake_operation=state.bake_operation,
        bake_source_revision=state.bake_source_revision,
        bake_source_id=state.bake_source_id,
        bake_evaluator=state.bake_evaluator,
        bake_evaluator_id=state.bake_evaluator_id,
        bake_manifest_id=state.bake_manifest_id,
        save_operation=state.save_operation,
        save_started=state.save_started,
        render_operation=state.render_operation,
        render_started=state.render_started,
        publication_hold=state.publication_hold,
    )

def project_ready(state: ProjectState) -> bool:
    return state.generation > 0 and state.phase == "active" and _all_owners_ready(state)

def project_step(state: ProjectState, event: ProjectEvent) -> tuple[ProjectState, bool]:
    if event.kind == "open":
        if (event.generation > state.generation > -1 and _owners(event.owners)
                and _evaluator_requirements(event.owners, event.owner_evaluators)):
            return ProjectState(
                generation=event.generation,
                required_owners=event.owners,
                required_evaluators=event.owner_evaluators,
            ), True
        return state, False
    if event.kind == "restart":
        if event.generation <= state.generation or event.generation <= 0: return state, False
        if not _owners(event.obligations):
            return state, False
        obligations = event.obligations
        return replace(
            state, generation=event.generation, phase="restarting",
            bake_phase="cancelled", bake_physical=(
                "retiring" if state.bake_physical == "live" else state.bake_physical
            ), publication_hold=False, restart_obligations=obligations,
            restart_retired=(),
        ), True
    if event.kind == "restart_retired":
        if (state.phase == "restarting" and event.generation == state.generation
                and event.owner in state.restart_obligations):
            retired = _add_unique(state.restart_retired, event.owner)
            return replace(state, restart_retired=retired), True
        return state, False
    if event.kind == "bake_retired" and state.phase == "restarting":
        ok = (event.generation == state.generation and event.operation == state.bake_operation
              and state.bake_physical in ("live", "retiring"))
        return (replace(state, bake_physical="none"), True) if ok else (state, False)
    if event.kind == "restart_complete":
        if (state.phase == "restarting" and event.generation == state.generation
                and state.bake_physical == "none"
                and _same_members(state.restart_retired, state.restart_obligations)):
            return replace(state, phase="active", bake_phase="idle", ready_owners=(),
                           ready_artifacts=(), preview_artifacts=(), repair_owners=(),
                           restart_obligations=(), restart_retired=()), True
        return state, False
    if event.kind == "close":
        if event.generation == state.generation and state.phase != "closed":
            return replace(state, phase="closed", publication_hold=False), True
        return state, False
    if event.generation != state.generation or state.phase in ("closed", "restarting"): return state, False
    if event.kind == "intent":
        if (state.phase == "active" and event.revision > state.intent_revision
                and event.revision > 0):
            cancel_bake = state.bake_phase not in ("idle", "finished", "cancelled", "failed")
            return replace(
                state,
                intent_revision=event.revision,
                ready_owners=(),
                ready_artifacts=(),
                preview_artifacts=(),
                repair_owners=(),
                bake_phase="cancelled" if cancel_bake else state.bake_phase,
                bake_physical="retiring" if cancel_bake and state.bake_physical == "live" else state.bake_physical,
            ), True
        return state, False
    if event.kind == "prepare_begin":
        if (state.phase in ("active", "saving", "rendering")
                and event.revision == state.intent_revision
                and event.attempt > state.preparation_attempt):
            return replace(state, preparation_attempt=event.attempt), True
        return state, False
    if event.kind == "retry_owner":
        ok = (state.phase in ("active", "saving", "rendering")
              and event.revision == state.intent_revision
              and event.attempt > state.preparation_attempt
              and event.owner in state.repair_owners)
        if not ok:
            return state, False
        return replace(
            state,
            preparation_attempt=event.attempt,
            repair_owners=_without(state.repair_owners, event.owner),
            ready_owners=_without(state.ready_owners, event.owner),
            ready_artifacts=_without_artifact(state.ready_artifacts, event.owner),
            preview_artifacts=_without_preview(state.preview_artifacts, event.owner),
        ), True
    if event.kind == "owner_ready":
        expected = _evaluator_for(state.required_evaluators, event.owner)
        ok = (state.phase in ("active", "saving", "rendering")
              and event.revision == state.intent_revision
              and event.attempt == state.preparation_attempt
              and event.owner in state.required_owners
              and event.owner not in state.repair_owners
              and event.final_ready
              and (event.evaluator == "native_grade_graph" or event.evaluator == "stack_65_lut")
              and (expected == "" or event.evaluator == expected)
              and _identity(event.evaluator_id)
              and _identity(event.manifest_id))
        if not ok:
            return state, False
        artifact = (event.owner, event.revision, event.evaluator,
                    event.evaluator_id, event.manifest_id)
        ready_artifacts = _without_artifact(state.ready_artifacts, event.owner)
        return replace(
            state,
            ready_owners=_add_unique(state.ready_owners, event.owner),
            ready_artifacts=ready_artifacts + (artifact,),
        ), True
    if event.kind == "owner_preview":
        expected = _evaluator_for(state.required_evaluators, event.owner)
        ok = (state.phase in ("active", "saving", "rendering")
              and event.revision == state.intent_revision
              and event.attempt == state.preparation_attempt
              and event.owner in state.required_owners
              and expected == "stack_65_lut"
              and event.evaluator == "stack_33_lut"
              and _identity(event.evaluator_id)
              and _identity(event.manifest_id))
        if not ok:
            return state, False
        preview = (event.owner, event.revision, event.evaluator_id, event.manifest_id)
        previous = _without_preview(state.preview_artifacts, event.owner)
        return replace(state, preview_artifacts=previous + (preview,)), True
    if event.kind == "owner_failed":
        ok = (state.phase == "active" and event.owner in state.required_owners
              and event.revision == state.intent_revision
              and event.attempt == state.preparation_attempt)
        return (replace(state,
                        repair_owners=_add_unique(state.repair_owners, event.owner),
                        ready_owners=_without(state.ready_owners, event.owner),
                        ready_artifacts=_without_artifact(state.ready_artifacts, event.owner),
                        preview_artifacts=_without_preview(state.preview_artifacts, event.owner)), True) if ok else (state, False)
    if event.kind == "output_owner_failed":
        # Preparation can fail after an output gate has accepted the request.
        # Keep the gate held while recording repair debt so the caller must
        # retry the exact owner before Save/Render can proceed.
        ok = (state.phase in ("active", "saving", "rendering")
              and event.owner in state.required_owners
              and event.revision == state.intent_revision
              and event.attempt == state.preparation_attempt)
        return (replace(state,
                        repair_owners=_add_unique(state.repair_owners, event.owner),
                        ready_owners=_without(state.ready_owners, event.owner),
                        ready_artifacts=_without_artifact(state.ready_artifacts, event.owner),
                        preview_artifacts=_without_preview(state.preview_artifacts, event.owner)), True) if ok else (state, False)
    if event.kind == "bake_request":
        accepted_artifact = _artifact_for(state.ready_artifacts, event.owner)
        preview = _preview_for(state.preview_artifacts, event.owner)
        expected = _evaluator_for(state.required_evaluators, event.owner)
        common = (state.phase == "active" and state.generation > 0
                  and state.bake_phase in ("idle", "finished", "cancelled", "failed")
                  and state.bake_physical == "none"
                  and event.operation > state.bake_operation > -1
                  and event.owner in state.required_owners
                  and event.source_revision > 0 and _identity(event.source_id)
                  and event.evaluator == expected)
        final_match = (event.final_ready and _artifact_index(state.ready_artifacts, event.owner) >= 0
                       and accepted_artifact[2] == event.evaluator
                       and accepted_artifact[3] == event.evaluator_id
                       and accepted_artifact[4] == event.manifest_id)
        preview_wait = (not event.final_ready and expected == "stack_65_lut"
                        and _preview_index(state.preview_artifacts, event.owner) >= 0
                        and preview[2] == event.preview_id
                        and preview[3] == event.manifest_id)
        ok = (common and _identity(event.manifest_id)
              and ((event.evaluator == "native_grade_graph" and final_match)
                   or (event.evaluator == "stack_65_lut" and (final_match or preview_wait))))
        if not ok: return state, False
        phase = "evaluating" if final_match else "waiting_for_final"
        return replace(state, bake_phase=phase, bake_operation=event.operation,
                       bake_owner=event.owner, bake_source_revision=event.source_revision,
                       bake_source_id=event.source_id, bake_evaluator=event.evaluator,
                       bake_evaluator_id=event.evaluator_id if final_match else 0,
                       bake_manifest_id=event.manifest_id,
                       bake_preview_id=event.preview_id if preview_wait else 0,
                       bake_result_id=0), True
    if event.kind == "bake_wait":
        accepted_artifact = _artifact_for(state.ready_artifacts, state.bake_owner)
        ok = (state.bake_phase == "waiting_for_final"
              and event.operation == state.bake_operation and event.final_ready
              and event.evaluator == "stack_65_lut"
              and _artifact_index(state.ready_artifacts, state.bake_owner) >= 0
              and accepted_artifact[2] == event.evaluator
              and accepted_artifact[3] == event.evaluator_id
              and accepted_artifact[4] == state.bake_manifest_id
              and event.manifest_id == state.bake_manifest_id)
        return (replace(state, bake_phase="evaluating",
                        bake_evaluator_id=event.evaluator_id,
                        bake_preview_id=0), True) if ok else (state, False)
    if event.kind == "bake_started":
        ok = (event.operation == state.bake_operation and state.bake_phase == "evaluating"
              and state.bake_physical == "none" and not state.publication_hold)
        return (replace(state, bake_physical="live"), True) if ok else (state, False)
    if event.kind == "bake_retired":
        ok = (event.operation == state.bake_operation and state.bake_physical in ("live", "retiring"))
        return (replace(state, bake_physical="none"), True) if ok else (state, False)
    if event.kind == "bake_evaluating":
        ok = (event.operation == state.bake_operation and state.bake_phase == "waiting_for_final"
              and event.final_ready and not state.publication_hold)
        return (replace(state, bake_phase="evaluating"), True) if ok else (state, False)
    if event.kind == "bake_staged":
        ok = (event.operation == state.bake_operation and state.bake_phase == "evaluating"
              and state.bake_physical == "none")
        return (replace(state, bake_phase="staged"), True) if ok else (state, False)
    if event.kind == "bake_publishing":
        ok = (event.operation == state.bake_operation and state.bake_phase == "staged"
              and state.bake_physical == "none" and not state.publication_hold)
        return (replace(state, bake_phase="publishing", bake_physical="live"), True) if ok else (state, False)
    if event.kind == "bake_complete":
        ok = bake_completion_matches(state, event)
        return (replace(state, bake_phase="finished", bake_physical="none", bake_result_id=event.result_id), True) if ok else (state, False)
    if event.kind == "bake_cancel":
        ok = state.bake_phase not in ("idle", "finished", "cancelled") and event.operation == state.bake_operation
        return (replace(state, bake_phase="cancelled",
                        bake_physical="retiring" if state.bake_physical == "live" else "none"), True) if ok else (state, False)
    if event.kind == "save_request":
        ok = (state.generation > 0 and state.phase == "active"
              and event.operation > state.save_operation > -1)
        if not ok: return state, False
        # Save's acceptance barrier revokes unfinished explicit Bake
        # publication. The adapter still owes physical retirement receipts.
        cancel_bake = state.bake_phase not in ("idle", "finished", "cancelled", "failed")
        bake_phase = "cancelled" if cancel_bake else state.bake_phase
        physical = "retiring" if cancel_bake and state.bake_physical == "live" else state.bake_physical
        return replace(state, phase="saving", save_operation=event.operation, save_started=False,
                       bake_phase=bake_phase, bake_physical=physical,
                       publication_hold=True), True
    if event.kind == "save_ready":
        ok = (state.phase == "saving" and event.operation == state.save_operation
              and state.bake_physical == "none" and _all_owners_ready(state))
        return (replace(state, save_started=True), True) if ok else (state, False)
    if event.kind == "save_cancel":
        ok = (state.phase == "saving" and not state.save_started
              and event.operation == state.save_operation)
        return (replace(state, phase="active", publication_hold=False), True) if ok else (state, False)
    if event.kind == "save_complete":
        ok = save_completion_matches(state, event) and event.committed
        return (replace(state, phase="active", save_started=False,
                        publication_hold=False), True) if ok else (state, False)
    if event.kind == "save_failed":
        ok = save_completion_matches(state, event) and not event.committed
        return (replace(state, phase="active", save_started=False,
                        publication_hold=False), True) if ok else (state, False)
    if event.kind == "render_request":
        ok = (state.generation > 0 and state.phase == "active"
              and not state.publication_hold and state.bake_phase != "publishing"
              and event.operation > state.render_operation > -1)
        return (replace(state, phase="rendering", render_operation=event.operation,
                        render_started=False, publication_hold=True), True) if ok else (state, False)
    if event.kind == "render_started":
        ok = (state.phase == "rendering" and event.operation == state.render_operation
              and state.publication_hold and not state.render_started
              and _all_owners_ready(state))
        return (replace(state, render_started=True), True) if ok else (state, False)
    if event.kind == "render_cancel_before_start":
        ok = (state.phase == "rendering" and not state.render_started
              and event.operation == state.render_operation)
        return (replace(state, phase="active", publication_hold=False), True) if ok else (state, False)
    if event.kind == "render_complete":
        ok = render_completion_matches(state, event) and event.committed
        return (replace(state, phase="active", publication_hold=False,
                        render_started=False), True) if ok else (state, False)
    if event.kind in ("render_cancel", "render_failed"):
        ok = render_completion_matches(state, event) and not event.committed
        return (replace(state, phase="active", publication_hold=False,
                        render_started=False), True) if ok else (state, False)
    return state, False
