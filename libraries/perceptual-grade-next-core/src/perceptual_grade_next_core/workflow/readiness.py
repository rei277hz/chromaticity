"""Value policies for static preparation, Bake evaluation, and authored UI."""

from dataclasses import dataclass, replace
from typing import Literal

from ..settings import ColorSettings, GradeSettings, LinearSettings, ToneSettings


Identity = int | str
Backend = Literal['grade', 'stack']
PreparationPhase = Literal[
    'idle', 'preparing', 'preview_ready', 'grade_ready', 'final_ready', 'failed', 'cancelled'
]
BakePhase = Literal['idle', 'running', 'complete', 'cancelled']
Evaluator = Literal['native_grade_graph', 'stack_65_lut']
ExecutionHost = Literal['blender', 'helper_process']

def _identity(value: Identity) -> bool:
    return (type(value) is int and value > 0) or (type(value) is str and bool(value))


def _ids(values: tuple[Identity, ...]) -> bool:
    return (
        type(values) is tuple
        and bool(values)
        and all(_identity(value) for value in values)
        and len(set(values)) == len(values)
    )


@dataclass(frozen=True)
class PreparationState:
    owner: Identity = 0
    revision: int = 0
    attempt: int = 0
    backend: Literal['none', 'grade', 'stack'] = 'none'
    plan_id: Identity = 0
    phase: PreparationPhase = 'idle'
    graph_id: Identity = 0
    field_ids: tuple[Identity, ...] = ()
    preview_id: Identity = 0
    final_lut_id: Identity = 0
    matrix_id: Identity = 0
    binding_id: Identity = 0


@dataclass(frozen=True)
class PreparationEvent:
    kind: Literal[
        'begin', 'grade_ready', 'stack_preview', 'stack_final', 'fail', 'cancel'
    ]
    owner: Identity = 0
    revision: int = 0
    attempt: int = 0
    backend: Literal['none', 'grade', 'stack'] = 'none'
    plan_id: Identity = 0
    graph_id: Identity = 0
    field_ids: tuple[Identity, ...] = ()
    artifact_id: Identity = 0
    preview_id: Identity = 0
    source_lattice_id: Identity = 0
    matrix_id: Identity = 0
    binding_id: Identity = 0
    verified: bool = False
    preview_vertices_reused: bool = False


def new_preparation() -> PreparationState:
    return PreparationState()


def preparation_matches(state: PreparationState, event: PreparationEvent) -> bool:
    return (
        event.owner == state.owner
        and event.revision == state.revision
        and event.attempt == state.attempt
        and event.backend == state.backend
        and event.plan_id == state.plan_id
    )


def final_ready(state: PreparationState) -> bool:
    if state.backend == 'grade':
        return (
            state.phase == 'grade_ready'
            and _identity(state.graph_id)
            and _ids(state.field_ids)
            and _identity(state.matrix_id)
            and _identity(state.binding_id)
        )
    if state.backend == 'stack':
        return (
            state.phase == 'final_ready'
            and _identity(state.preview_id)
            and _identity(state.final_lut_id)
            and _identity(state.matrix_id)
            and _identity(state.binding_id)
        )
    return False


def preview_display_ready(state: PreparationState) -> bool:
    return state.backend == 'stack' and state.phase in ('preview_ready', 'final_ready') and _identity(state.preview_id)


def preparation_step(
    state: PreparationState,
    event: PreparationEvent,
) -> tuple[PreparationState, bool]:
    if event.kind == 'begin':
        accepted = (
            _identity(event.owner)
            and event.revision > 0
            and event.attempt > state.attempt
            and event.backend in ('grade', 'stack')
            and _identity(event.plan_id)
            and (event.owner != state.owner or event.revision >= state.revision)
        )
        if accepted:
            return PreparationState(
                owner=event.owner,
                revision=event.revision,
                attempt=event.attempt,
                backend=event.backend,
                plan_id=event.plan_id,
                phase='preparing',
            ), True
        return state, False

    if not preparation_matches(state, event):
        return state, False

    if event.kind == 'grade_ready' and state.phase == 'preparing' and state.backend == 'grade':
        accepted = (
            _identity(event.graph_id)
            and _ids(event.field_ids)
            and _identity(event.matrix_id)
            and _identity(event.binding_id)
            and event.verified
        )
        if accepted:
            return replace(
                state,
                phase='grade_ready',
                graph_id=event.graph_id,
                field_ids=event.field_ids,
                matrix_id=event.matrix_id,
                binding_id=event.binding_id,
            ), True
        return state, False

    if event.kind == 'stack_preview' and state.phase == 'preparing' and state.backend == 'stack':
        accepted = (
            _identity(event.artifact_id)
            and event.source_lattice_id == state.plan_id
            and event.verified
        )
        if accepted:
            return replace(state, phase='preview_ready', preview_id=event.artifact_id), True
        return state, False

    if event.kind == 'stack_final' and state.phase == 'preview_ready' and state.backend == 'stack':
        accepted = (
            event.preview_id == state.preview_id
            and _identity(event.artifact_id)
            and event.artifact_id != state.preview_id
            and _identity(event.matrix_id)
            and _identity(event.binding_id)
            and event.source_lattice_id == state.plan_id
            and event.preview_vertices_reused
            and event.verified
        )
        if accepted:
            return replace(
                state,
                phase='final_ready',
                final_lut_id=event.artifact_id,
                matrix_id=event.matrix_id,
                binding_id=event.binding_id,
            ), True
        return state, False

    if event.kind == 'fail' and state.phase in ('preparing', 'preview_ready'):
        return replace(state, phase='failed'), True

    if event.kind == 'cancel' and state.phase in ('preparing', 'preview_ready', 'failed'):
        return replace(state, phase='cancelled'), True

    return state, False


@dataclass(frozen=True)
class BakeRequest:
    operation: int
    owner: Identity
    preparation_attempt: int
    revision: int
    source_revision: int
    source_id: Identity
    backend: Backend
    evaluator: Evaluator
    evaluator_id: Identity
    execution_host: ExecutionHost = 'blender'


@dataclass(frozen=True)
class BakeState:
    phase: BakePhase = 'idle'
    operation: int = 0
    owner: Identity = 0
    preparation_attempt: int = 0
    revision: int = 0
    source_revision: int = 0
    source_id: Identity = 0
    backend: Literal['none', 'grade', 'stack'] = 'none'
    evaluator: Literal['none', 'native_grade_graph', 'stack_65_lut'] = 'none'
    evaluator_id: Identity = 0
    execution_host: Literal['blender', 'helper_process'] = 'blender'
    result_id: Identity = 0


@dataclass(frozen=True)
class BakeReceipt:
    operation: int
    owner: Identity
    preparation_attempt: int
    revision: int
    source_revision: int
    source_id: Identity
    backend: Backend
    evaluator: Evaluator
    evaluator_id: Identity
    result_id: Identity
    pixels_from_evaluator: bool


def new_bake() -> BakeState:
    return BakeState()


def expected_evaluator(preparation: PreparationState) -> tuple[Evaluator, Identity] | None:
    if not final_ready(preparation):
        return None
    if preparation.backend == 'grade':
        return 'native_grade_graph', preparation.graph_id
    if preparation.backend == 'stack':
        return 'stack_65_lut', preparation.final_lut_id
    return None


def start_bake(
    state: BakeState,
    preparation: PreparationState,
    request: BakeRequest,
) -> tuple[BakeState, bool]:
    evaluator = expected_evaluator(preparation)
    accepted = (
        state.phase != 'running'
        and request.operation > state.operation
        and request.operation > 0
        and request.owner == preparation.owner
        and request.preparation_attempt == preparation.attempt
        and request.revision == preparation.revision
        and request.source_revision > 0
        and _identity(request.source_id)
        and request.backend == preparation.backend
        and evaluator is not None
        and request.evaluator == evaluator[0]
        and request.evaluator_id == evaluator[1]
        and request.execution_host in ('blender', 'helper_process')
    )
    if not accepted:
        return state, False
    return BakeState(
        phase='running',
        operation=request.operation,
        owner=request.owner,
        preparation_attempt=request.preparation_attempt,
        revision=request.revision,
        source_revision=request.source_revision,
        source_id=request.source_id,
        backend=request.backend,
        evaluator=request.evaluator,
        evaluator_id=request.evaluator_id,
        execution_host=request.execution_host,
    ), True


def cancel_bake(state: BakeState, operation: int, owner: Identity) -> tuple[BakeState, bool]:
    accepted = state.phase == 'running' and operation == state.operation and owner == state.owner
    if accepted:
        return replace(state, phase='cancelled'), True
    return state, False


def complete_bake(state: BakeState, receipt: BakeReceipt) -> tuple[BakeState, bool]:
    accepted = (
        state.phase == 'running'
        and receipt.operation == state.operation
        and receipt.owner == state.owner
        and receipt.preparation_attempt == state.preparation_attempt
        and receipt.revision == state.revision
        and receipt.source_revision == state.source_revision
        and receipt.source_id == state.source_id
        and receipt.backend == state.backend
        and receipt.evaluator == state.evaluator
        and receipt.evaluator_id == state.evaluator_id
        and _identity(receipt.result_id)
        and receipt.pixels_from_evaluator
    )
    if accepted:
        return replace(state, phase='complete', result_id=receipt.result_id), True
    return state, False


def validate_ui_settings(
    *,
    grading_white: str,
    reference_nits: float,
    working_space: str,
    source_white_xy: tuple[float, float],
    tone_fit: float,
    color_lightness_fit: float,
    color_chroma_fit: float,
) -> None:
    """Validate serialized/UI values through the canonical Next settings types."""
    GradeSettings(
        linear=LinearSettings(source_white_xy=source_white_xy),
        tone=ToneSettings(fit=tone_fit, reference_nits=reference_nits),
        color=ColorSettings(
            lightness_fit=color_lightness_fit,
            chroma_fit=color_chroma_fit,
        ),
        grading_white=grading_white,
        working_space=working_space,
    )
