"""Checked product gateway for native Bake, Save, and Render operations.

The portable project machine owns semantic admission.  This adapter binds its
receipts to the installed native evaluator and keeps native invocation at the
edge.  In particular, a Stack preview can wait for its final LUT but can never
be used as a pixel evaluator.
"""

from dataclasses import dataclass

from .bake import (
    BakeResult, FrozenBakeInput, capture_grade, capture_stack, freeze_bake_input,
)
from .image_publication import ImagePublication
from .lifecycle import ProjectWorkflow


@dataclass(frozen=True)
class OutputRequest:
    """The immutable source/evaluator identity for one explicit Bake."""

    operation: int
    owner: object
    source_revision: int
    source_id: object
    evaluator: str
    evaluator_id: object
    manifest_id: object
    preview_id: object = 0
    final_ready: bool = True
    route_id: object = ""


@dataclass(frozen=True)
class EvaluatorBinding:
    """Identity-carrying adapter around an installed native evaluator."""

    evaluator: object
    evaluator_id: object
    manifest_id: object

    def evaluate_native(self, pixels):
        callback = getattr(self.evaluator, "evaluate_native", self.evaluator)
        if not callable(callback):
            raise TypeError("Native evaluator binding is not callable")
        return callback(pixels)

    @property
    def size(self):
        return getattr(self.evaluator, "size", None)

    def apply(self, values):
        callback = getattr(self.evaluator, "apply", self.evaluator)
        if not callable(callback):
            raise TypeError("Stack evaluator binding has no apply method")
        return callback(values)


class OutputGateway:
    """Drive checked project transitions around native host effects.

    The gateway does not grade pixels itself.  ``capture_grade`` must receive
    the installed node-tree output, while ``capture_stack`` accepts only the
    committed 65^3 LUT.  Native callers acknowledge each physical stage with
    the matching operation identity.
    """

    def __init__(self, workflow=None):
        self.workflow = workflow or ProjectWorkflow()
        self._bake_requests = {}
        self._bake_results = {}
        self._frozen_inputs = {}
        self._image_publications = {}
        self._native_operations = set()

    @property
    def state(self):
        return self.workflow.state

    @property
    def ready(self):
        return self.workflow.ready

    def dispatch(self, kind, **values):
        return self.workflow.dispatch(kind, **values)

    def request_bake(self, request: OutputRequest):
        accepted = self.dispatch(
            "bake_request", operation=request.operation, owner=request.owner,
            source_revision=request.source_revision, source_id=request.source_id,
            evaluator=request.evaluator, evaluator_id=request.evaluator_id,
            manifest_id=request.manifest_id, preview_id=request.preview_id,
            final_ready=request.final_ready,
        )
        if not accepted:
            raise RuntimeError("Bake request is stale, blocked, or not final-ready")
        self._bake_requests[request.operation] = request
        self._bake_results.pop(request.operation, None)
        return self.state

    def final_ready(self, request: OutputRequest):
        """Admit a matching final Stack receipt for a queued Bake."""
        original = self._bake_requests.get(request.operation)
        if (original is None or request.owner != original.owner
                or request.source_revision != original.source_revision
                or request.source_id != original.source_id
                or request.evaluator != original.evaluator
                or request.manifest_id != original.manifest_id
                or request.final_ready is not True):
            raise RuntimeError("Final evaluator receipt does not match the frozen Bake source")
        accepted = self.dispatch(
            "bake_wait", operation=request.operation, evaluator=request.evaluator,
            evaluator_id=request.evaluator_id, manifest_id=request.manifest_id,
            final_ready=True,
        )
        if not accepted:
            raise RuntimeError("Final evaluator receipt does not match the Bake")
        self._bake_requests[request.operation] = request
        return self.state

    def _assert_capture_authority(self, request):
        state = self.state
        expected = (
            state.bake_phase == "evaluating"
            and state.bake_physical == "live"
            and state.bake_operation == request.operation
            and state.bake_owner == request.owner
            and state.bake_source_revision == request.source_revision
            and state.bake_source_id == request.source_id
            and state.bake_evaluator == request.evaluator
            and state.bake_evaluator_id == request.evaluator_id
            and state.bake_manifest_id == request.manifest_id
        )
        if not expected:
            raise RuntimeError("Bake capture is not authorized by the current frozen request")

    def start_bake(self, operation):
        if not self.dispatch("bake_started", operation=operation):
            raise RuntimeError("Bake cannot start while its evaluator or reader is unavailable")
        return self.state

    def retire_bake_reader(self, operation):
        if not self.dispatch("bake_retired", operation=operation):
            raise RuntimeError("Bake reader retirement receipt is stale")
        return self.state

    def stage_bake(self, operation, result: BakeResult):
        request = self._bake_requests.get(operation)
        if request is None or self._bake_results.get(operation) is not result:
            raise RuntimeError("Bake result was not captured for this operation")
        source = result.source
        if (source.source_revision != request.source_revision
                or source.source_id != request.source_id
                or source.evaluator_id != request.evaluator_id
                or source.manifest_id != request.manifest_id
                or (request.route_id and source.route_id != request.route_id)):
            raise RuntimeError("Bake result does not match its frozen evaluator receipt")
        if not self.dispatch("bake_staged", operation=operation):
            raise RuntimeError("Bake has no staged native result")
        return self.state

    def publish_bake(self, operation):
        if not self.dispatch("bake_publishing", operation=operation):
            raise RuntimeError("Bake publication is blocked by a live hold or receipt")
        return self.state

    def complete_bake(self, request: OutputRequest, result_id):
        if self._bake_requests.get(request.operation) != request:
            raise RuntimeError("Bake completion does not match the admitted request")
        result = self._bake_results.get(request.operation)
        if result is None or result.result_id != result_id:
            raise RuntimeError("Bake result was not captured and staged for this request")
        publication = self._image_publications.get(request.operation)
        if publication is None or not publication.committed:
            raise RuntimeError("Bake Image has no verified native publication receipt")
        accepted = self.dispatch(
            "bake_complete", operation=request.operation,
            source_revision=request.source_revision, source_id=request.source_id,
            evaluator=request.evaluator, evaluator_id=request.evaluator_id,
            manifest_id=request.manifest_id, result_id=result_id, committed=True,
        )
        if not accepted:
            raise RuntimeError("Bake completion receipt does not match its request")
        publication = self._image_publications.get(request.operation)
        if publication is not None:
            publication.finalize()
            self._image_publications.pop(request.operation, None)
        self._bake_requests.pop(request.operation, None)
        self._bake_results.pop(request.operation, None)
        self._frozen_inputs.pop(request.operation, None)
        return self.state

    def cancel_bake(self, operation):
        publication = self._image_publications.get(operation)
        if publication is not None and publication.committed:
            raise RuntimeError("A verified native Image publication cannot be cancelled")
        if not self.dispatch("bake_cancel", operation=operation):
            raise RuntimeError("Bake cancellation receipt is stale")
        self._bake_requests.pop(operation, None)
        self._bake_results.pop(operation, None)
        self._frozen_inputs.pop(operation, None)
        publication = self._image_publications.pop(operation, None)
        if publication is not None and not publication.committed:
            publication.restore()
        return self.state

    def freeze_bake_source(self, request: OutputRequest, route, facts, pixels):
        """Freshly validate and freeze source samples for the admitted request."""
        if self._bake_requests.get(request.operation) != request:
            raise RuntimeError("Bake source does not match the admitted request")
        if request.operation in self._frozen_inputs:
            raise RuntimeError("Bake source was already frozen for this operation")
        state = self.state
        if not (state.bake_operation == request.operation
                and state.bake_phase == "evaluating"
                and state.bake_physical == "none"
                and state.bake_source_revision == request.source_revision
                and state.bake_source_id == request.source_id
                and not state.publication_hold):
            raise RuntimeError("Bake source is not authorized by the current request")
        if (route.evaluator != request.evaluator
                or route.source_revision != request.source_revision
                or route.source_id != request.source_id
                or (request.route_id and route.route_id != request.route_id)):
            raise RuntimeError("Bake route does not match the frozen request")
        frozen = freeze_bake_input(route, facts, pixels)
        self._frozen_inputs[request.operation] = frozen
        return frozen

    def capture_grade(self, *, native_evaluator, request: OutputRequest,
                      result_id, frozen_input: FrozenBakeInput):
        """Capture the installed native Grade output, then return its result."""
        if request.evaluator != "native_grade_graph" or not request.final_ready:
            raise TypeError("Grade capture requires the accepted native Grade graph")
        self._assert_capture_authority(request)
        self._assert_frozen_input(request, frozen_input)
        self._assert_evaluator_binding(native_evaluator, request)
        result = capture_grade(
            native_evaluator=self._callable_evaluator(native_evaluator),
            frozen_input=frozen_input,
            source_revision=request.source_revision, source_id=request.source_id,
            evaluator_id=request.evaluator_id, manifest_id=request.manifest_id,
            route_id=request.route_id,
            result_id=result_id,
        )
        self._assert_frozen_route(result, request)
        self._bake_results[request.operation] = result
        return result

    def capture_stack(self, *, lut, request: OutputRequest, result_id,
                      frozen_input: FrozenBakeInput):
        """Capture only through the accepted final Stack LUT."""
        if request.evaluator != "stack_65_lut" or not request.final_ready:
            raise TypeError("Stack capture requires the accepted 65^3 LUT")
        self._assert_capture_authority(request)
        self._assert_frozen_input(request, frozen_input)
        self._assert_evaluator_binding(lut, request)
        result = capture_stack(
            lut=lut, frozen_input=frozen_input, source_revision=request.source_revision,
            source_id=request.source_id, evaluator_id=request.evaluator_id,
            manifest_id=request.manifest_id, route_id=request.route_id,
            result_id=result_id,
        )
        self._bake_results[request.operation] = result
        return result

    @staticmethod
    def _assert_frozen_route(result, request):
        if request.route_id and result.source.route_id != request.route_id:
            raise RuntimeError("Bake result route does not match the frozen request")

    def _assert_frozen_input(self, request, frozen_input):
        if self._frozen_inputs.get(request.operation) is not frozen_input:
            raise RuntimeError("Bake capture does not use this operation's frozen source")
        route = frozen_input.route
        if (route.source_revision != request.source_revision
                or route.source_id != request.source_id
                or route.evaluator != request.evaluator
                or (request.route_id and route.route_id != request.route_id)):
            raise RuntimeError("Frozen source route does not match the Bake request")

    @staticmethod
    def freeze_input(route, facts, pixels):
        """Freshly validate and detach source samples before native capture."""
        return freeze_bake_input(route, facts, pixels)

    def publish_bake_image(self, operation, result: BakeResult, publication: ImagePublication):
        """Commit a captured result to a Blender Image after checked staging."""
        request = self._bake_requests.get(operation)
        if request is None or self._bake_results.get(operation) is not result:
            raise RuntimeError("Bake result was not captured for this operation")
        self._assert_frozen_route(result, request)
        if self.state.bake_phase != "publishing":
            raise RuntimeError("Bake Image publication is outside its native publication phase")
        if operation in self._image_publications:
            raise RuntimeError("Bake Image publication was already committed for this operation")
        if publication.operation not in (None, operation):
            raise RuntimeError("Image publication belongs to a different Bake operation")
        # Blender Image pixels are a flat RGBA buffer even when the captured
        # evaluator returned a height x width x 4 array.
        publication.stage(result.rgba.reshape(-1))
        publication.commit()
        self._image_publications[operation] = publication
        self.retire_bake_reader(operation)
        return True

    @staticmethod
    def _assert_evaluator_binding(evaluator, request):
        if (getattr(evaluator, "evaluator_id", None) != request.evaluator_id
                or getattr(evaluator, "manifest_id", None) != request.manifest_id):
            raise RuntimeError("Native evaluator object does not match the frozen Bake request")

    @staticmethod
    def _callable_evaluator(evaluator):
        callback = getattr(evaluator, "evaluate_native", None)
        if callable(callback):
            return callback
        if callable(evaluator):
            return evaluator
        raise TypeError("Grade evaluator binding has no native pixel capture adapter")

    def request_save(self, operation):
        if not self.dispatch("save_request", operation=operation):
            raise RuntimeError("Save is blocked until all required native outputs are ready")
        return self.state

    def save_ready(self, operation):
        if not self.dispatch("save_ready", operation=operation):
            raise RuntimeError("Save still has live Bake readers or incomplete preparation")
        return self.state

    def complete_save(self, operation, *, committed=True):
        if ("save", operation) not in self._native_operations:
            raise RuntimeError("Save terminal receipt has no matching native invocation")
        kind = "save_complete" if committed else "save_failed"
        if not self.dispatch(kind, operation=operation, committed=committed):
            raise RuntimeError("Save completion receipt is stale")
        self._native_operations.discard(("save", operation))
        return self.state

    def cancel_save_wait(self, operation):
        if not self.dispatch("save_cancel", operation=operation):
            raise RuntimeError("Save wait cancellation receipt is stale")
        return self.state

    def invoke_save(self, operation, native):
        """Run one already-admitted native Save and acknowledge its receipt.

        The host owns confirmation and destination selection.  This method
        only supplies the one-shot execution boundary after the checked gate.
        """
        if not callable(native):
            raise TypeError("native Save callback must be callable")
        if self.state.phase == "active":
            self.request_save(operation)
        elif self.state.phase != "saving" or self.state.save_operation != operation:
            raise RuntimeError("Save operation is stale or not admitted")
        if ("save", operation) in self._native_operations:
            raise RuntimeError("Native Save was already invoked for this operation")
        self.save_ready(operation)
        self._native_operations.add(("save", operation))
        try:
            result = native()
        except BaseException:
            self.complete_save(operation, committed=False)
            raise
        if _operator_succeeded(result):
            self.complete_save(operation, committed=True)
        elif _operator_cancelled(result) or not _operator_running(result):
            self.complete_save(operation, committed=False)
        return result

    def request_render(self, operation):
        if not self.dispatch("render_request", operation=operation):
            raise RuntimeError("Render is blocked until all required native outputs are ready")
        return self.state

    def start_render(self, operation):
        if not self.dispatch("render_started", operation=operation):
            raise RuntimeError("Render start receipt is stale")
        return self.state

    def complete_render(self, operation, *, committed=True):
        if ("render", operation) not in self._native_operations:
            raise RuntimeError("Render terminal receipt has no matching native invocation")
        kind = "render_complete" if committed else "render_cancel"
        if not self.dispatch(kind, operation=operation, committed=committed):
            raise RuntimeError("Render completion receipt is stale")
        self._native_operations.discard(("render", operation))
        return self.state

    def cancel_render_wait(self, operation):
        if not self.dispatch("render_cancel_before_start", operation=operation):
            raise RuntimeError("Render wait cancellation receipt is stale")
        return self.state

    def invoke_render(self, operation, native):
        """Run one native Render operation, including animation as one hold."""
        if not callable(native):
            raise TypeError("native Render callback must be callable")
        if self.state.phase == "active":
            self.request_render(operation)
        elif self.state.phase != "rendering" or self.state.render_operation != operation:
            raise RuntimeError("Render operation is stale or not admitted")
        self.start_render(operation)
        if ("render", operation) in self._native_operations:
            raise RuntimeError("Native Render was already invoked for this operation")
        self._native_operations.add(("render", operation))
        try:
            result = native()
        except BaseException:
            self.complete_render(operation, committed=False)
            raise
        if _operator_succeeded(result):
            self.complete_render(operation, committed=True)
        elif _operator_cancelled(result) or not _operator_running(result):
            self.complete_render(operation, committed=False)
        return result


def _operator_status(result):
    if isinstance(result, str):
        return {result}
    try:
        return set(result)
    except TypeError:
        return set()


def _operator_succeeded(result):
    return "FINISHED" in _operator_status(result)


def _operator_cancelled(result):
    return "CANCELLED" in _operator_status(result)


def _operator_running(result):
    return "RUNNING_MODAL" in _operator_status(result)


__all__ = ("EvaluatorBinding", "OutputGateway", "OutputRequest")
