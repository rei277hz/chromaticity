"""Transient, latest-demand coordination for Grade Gizmo scopes."""

# pg-book: technical-report/en#grade-policy.vectorscope

from collections import OrderedDict, deque
from contextlib import nullcontext
from dataclasses import dataclass
import hashlib
from itertools import count
import shutil
import threading
import time

import numpy as np

from ...kernel.prepare import PreparedLinear, prepare_linear
from ...kernel.settings import ToneSettings
from ...policy.scheduler import admitted as task_admitted
from ...runtime.publication import PublicationDeferred
from . import analysis, appearance_scope, routes, tone_scope
from .appearance_preview import AppearancePreview, PreviewUnavailable
from .capture import capture_loaded_image
from .policy import scope as policy


MAX_CAPTURE_BYTES = 512 * 512 * 4 * 4
CACHE_LIMIT = 8
CACHE_BYTES = 64 * 1024 * 1024


@dataclass(frozen=True)
class _Payload:
    route: object
    linear: PreparedLinear
    source_epoch: int
    tone: ToneSettings | None

    @property
    def matrix(self):
        return self.linear.rgb_matrix

    @property
    def space(self):
        return self.linear.space

    def analyze(self, rgba):
        if self.tone is not None:
            return tone_scope.analyze(rgba, self.linear, self.tone)
        return analysis.analyze(rgba, self.linear.rgb_matrix, self.linear.space)


@dataclass(frozen=True)
class _AppearancePayload:
    route: object
    peak_j: float

    def analyze(self, rgba):
        return appearance_scope.analyze(rgba, self.peak_j)


@dataclass(frozen=True)
class _CaptureTicket:
    key: object
    generation: int
    capture_signature: str
    source_signature: str
    analysis_signature: str
    source_generation: int
    revision: int


@dataclass(frozen=True)
class _PreviewReceipt:
    key: object
    revision: int
    input_signature: str
    grade_signature: str


@dataclass(frozen=True)
class _AppearanceKey:
    editor: object


def _editor_key(key):
    return key.editor if isinstance(key, _AppearanceKey) else key


@dataclass(frozen=True)
class _Editor:
    binding: tuple
    frame: tuple
    stage: str


@dataclass(frozen=True)
class _AppearanceObservation:
    grade_signature: str
    changed_at: float


@dataclass(frozen=True)
class DisplayState:
    rgba: np.ndarray | None
    status: str
    error: str | None
    tone_histogram: np.ndarray | None = None
    appearance: appearance_scope.AppearanceScope | None = None
    appearance_status: str | None = None
    appearance_error: str | None = None

    @property
    def brightness(self):
        return None if self.rgba is None else self.rgba[..., 3]


@dataclass(frozen=True)
class WhiteDragReceipt:
    editor: object
    binding: tuple
    frame: tuple
    capture_signature: str
    source_generation: int
    source_epoch: int
    linear_witness: str


@dataclass(frozen=True)
class _ScopeWatch:
    images: frozenset
    mesh_witnesses: object
    input_tree_pointers: frozenset
    owner_pointer: object
    owner_tree_pointer: object
    input_graph_covered: bool
    coverage_invariant: bool
    owner_kind: str
    has_render_layers: bool


class ScopeRuntime:
    """Capture evaluated Grade inputs and appearance outside the draw callback."""

    def __init__(self, snapshot_scope, linear_settings, working_space, *, create_job,
                 gate=None, upstream_ready=None, grade_signature=None,
                 preview_roles=None, preview_backend=None,
                 appearance_settle_seconds=0.15, clock=time.monotonic,
                 scheduler=None, consistency_keys=None):
        self.snapshot_scope = snapshot_scope
        self.create_job = create_job
        self.linear_settings = linear_settings
        self.working_space = working_space
        self.gate = gate
        self.upstream_ready = upstream_ready
        self.grade_signature = grade_signature
        self.preview_roles = preview_roles
        self.preview_backend = preview_backend
        self.preview_unavailable = None
        self.appearance_settle_seconds = max(0., float(appearance_settle_seconds))
        self.clock = clock
        # The application scheduler owns ordering when supplied. The scalar
        # scope policy below still owns generation and publication decisions.
        self.coordinator = scheduler
        self.consistency_keys = consistency_keys
        self.scope_states = {}
        self.scheduler = policy.SchedulerState()
        self.demands = {}
        self.queue = deque()
        self.queued = {}
        self._plot_prerequisites = {}
        self._plot_grades = {}
        self._paused_capture = None
        self.on_display = None
        self.queue_tokens = count(1)
        self.payloads = {}
        self.displays = {}
        self.preview_displays = {}
        self.appearance_observations = {}
        self.samples = OrderedDict()
        self.sample_bytes = 0
        self.active = None
        self._shutting_down = False
        self.editors = {}
        self.revisions = {}
        self.source_epochs = {}
        self.epoch = count(1)
        self.dependencies = {}
        self.watches = {}
        self._observations = threading.Lock()
        self._main_thread = threading.main_thread()
        self.timing = None

    def _record_timing(self, stage, started, finished, ticket, metadata=None):
        callback = self.timing
        if callback is None or started is None:
            return
        try:
            payload = self.payloads.get(ticket.key)
            details = {"clock": "host", "operation": "vectorscope_capture",
                       "capture_generation": ticket.generation}
            if payload is not None:
                details["owner_kind"] = payload.route["owner_kind"]
            details.update(metadata or {})
            callback(stage, started, finished, ticket, details)
        except Exception:
            # Diagnostics must never make a scope unavailable.
            pass

    def _clock(self):
        return time.perf_counter_ns() if self.timing is not None else None

    def _revision(self, key):
        with self._observations:
            return self.revisions.get(key, 0)

    @staticmethod
    def _key(node_editor_key):
        if isinstance(node_editor_key, list):
            return tuple(node_editor_key)
        return node_editor_key

    @staticmethod
    def _digest(value):
        return hashlib.sha256(repr(value).encode("utf8")).hexdigest()

    @staticmethod
    def _selection(node):
        return (int(node.id_data.as_pointer()), int(node.as_pointer()))

    @staticmethod
    def _target(node):
        grade = getattr(node, "pg_grade", None)
        return int(node.as_pointer()), None if grade is None else int(grade.as_pointer())

    def _scope_state(self, key):
        return self.scope_states.get(key, policy.ScopeState())

    def _dispatch(self, key, event, *, samples=None, trace=None, capture=None, timings=()):
        previous = self._scope_state(key)
        transition = policy.step(policy.State(previous, self.scheduler), event)
        self.scope_states[key] = transition.state.scope
        self.scheduler = transition.state.scheduler
        effects = transition.effects
        if event.kind == "request":
            scope = transition.state.scope
            if scope.desired_generation is None:
                self.demands.pop(key, None)
            else:
                self.demands[key] = _CaptureTicket(
                    key, scope.desired_generation, scope.capture_signature,
                    scope.source_signature, scope.analysis_signature,
                    scope.source_generation, scope.revision,
                )
        elif event.kind in {"release", "unavailable", "reset"}:
            scope = transition.state.scope
            if scope.desired_generation is None:
                self.demands.pop(key, None)
        if (event.kind == "request" and self.coordinator is not None
                and previous.waiting and not transition.state.scope.waiting):
            self.coordinator.wake(self._task_key(key))
        if timings:
            ticket = self.demands[key]
            now = self._clock()
            self._record_timing("request", now, now, ticket)
            for stage, started, finished in timings:
                self._record_timing(stage, started, finished, ticket)
        self._apply(key, effects, event, samples=samples, trace=trace, capture=capture)
        if self.on_display is not None and (
                effects.publish or effects.publish_preview or effects.clear or previous.failure_error
                != transition.state.scope.failure_error):
            self.on_display((_editor_key(key),))
        return effects

    def _apply(self, key, effects, event, *, samples=None, trace=None, capture=None):
        if effects.clear:
            self.displays.pop(key, None)
        if effects.clear_preview:
            self.preview_displays.pop(key, None)
            self._withdraw_preview_task(key)
        if effects.remove_queue:
            self._remove_queued(key, event.ticket_generation,
                                 keep_task=event.kind == "started")
        if effects.enqueue:
            ticket = self.demands.get(key)
            if ticket is not None:
                self._enqueue(ticket, keep_priority=event.kind == "deferred")
        if effects.retain_samples and capture is not None:
            self._remember_samples(capture.capture_signature, samples)
        if effects.publish_preview:
            self.preview_displays[key] = trace
        if effects.publish:
            started = self._clock()
            self.displays[key] = trace
            if started is not None:
                demand = self.demands.get(key, capture)
                readout = policy.status(self._scope_state(key), self._revision(key), True)
                if demand is not None:
                    self._record_timing("publish", started, self._clock(), demand, {
                        "current": readout.status == "current",
                        "capture_generation": (
                            demand.generation if capture is None else capture.generation
                        ),
                    })
        if effects.start:
            queued = self.queued.get(key)
            if queued is not None and queued[1].generation == event.ticket_generation:
                self._start(queued[1])
        if effects.cancel and self.active is not None:
            ticket, job, _root = self.active
            if ticket.key == key and ticket.generation == self._scope_state(key).active_generation:
                if self.coordinator is None:
                    job.cancel()
                else:
                    self._pause_scheduled(key)

    def _enqueue(self, ticket, *, keep_priority=False):
        queued = self.queued.get(ticket.key)
        if queued is None:
            token = next(self.queue_tokens)
            self.queue.append((ticket.key, token))
        else:
            token, _previous = queued
        self.queued[ticket.key] = (token, ticket)
        if (keep_priority and self.coordinator is not None
                and self.coordinator.has(self._task_key(ticket.key))):
            self.coordinator.wake(self._task_key(ticket.key))
        else:
            self._register_task(ticket.key)

    @staticmethod
    def _task_key(key):
        return ("vectorscope_capture", key)

    @staticmethod
    def _preview_task_key(key):
        return ("vectorscope_preview", key)

    def _withdraw_preview_task(self, key):
        if self.coordinator is not None:
            self.coordinator.withdraw(self._preview_task_key(key))

    def focus(self, key):
        if self.coordinator is not None:
            self.coordinator.focus(key)

    def _register_task(self, key):
        if self.coordinator is None:
            return
        task_key = self._task_key(key)
        editor_key = _editor_key(key)
        prerequisites = self._plot_prerequisites.get(key, ())
        self.coordinator.submit(
            task_key,
            "plot",
            lambda key=key: self._advance_scheduled(key),
            on_pause=lambda key=key: self._pause_scheduled(key),
            on_error=lambda error, key=key: self._scheduled_error(key, error),
            pause_group="capture",
            ready=lambda key=key: self._task_ready(key),
            editor=editor_key,
            prerequisites=prerequisites,
        )

    def _task_ready(self, key):
        if self._paused_capture is not None:
            return False
        if self.active is not None and self.active[0].key == key:
            return True
        if key not in self.queued or self._scope_state(key).waiting:
            return False
        return (self.upstream_ready is None
                or self.upstream_ready(self._plot_grades.get(key, ())))

    def _pause_scheduled(self, key):
        active = self.active
        if (active is not None and active[0].key == key
                and self._paused_capture is None):
            self._paused_capture = active[0]
            active[1].cancel()
            if not self._shutting_down and self.coordinator.phase != "closed":
                self.coordinator.submit(
                    self._retirement_task_key(), "lifecycle", self._retire_paused_capture,
                    pause_group="capture",
                )

    def _retirement_task_key(self):
        return ("vectorscope_retirement", id(self))

    def _scheduled_error(self, key, error):
        if key in self.queued:
            self._unavailable(key, error, self._revision(key))

    def _retire_paused_capture(self):
        if self.active is None:
            return None
        ticket, job, root = self.active
        if self._paused_capture != ticket:
            return None
        try:
            if not job.retired():
                return 1 / 60
        except Exception as error:
            self._scheduled_error(ticket.key, error)
            raise
        if root is not None:
            shutil.rmtree(root, ignore_errors=True)
        self.active = None
        self._paused_capture = None
        self._dispatch_ticket(ticket, "deferred", resume=True)
        return None

    def _withdraw_task(self, key):
        if self.coordinator is not None:
            self.coordinator.withdraw(self._task_key(key))

    def _advance_scheduled(self, key):
        """Advance one capture phase for the coordinator's task slot."""
        queued = self.queued.get(key)
        active = self.active
        if active is None and queued is None:
            return None
        if self._paused_capture is not None:
            return 1 / 60
        if active is not None and active[0].key != key:
            return 1 / 60
        if active is None:
            ticket = queued[1]
            self._dispatch(key, policy.Event("schedule", ticket_generation=ticket.generation))
            active = self.active
            return 1 / 60 if active is not None or key in self.queued else None
        self._poll_active_once()
        return 1 / 60 if self.active is not None or key in self.queued else None

    def _remove_queued(self, key, generation=None, *, keep_task=False):
        queued = self.queued.get(key)
        if queued is None:
            return
        token, ticket = queued
        if generation is not None and ticket.generation != generation:
            return
        del self.queued[key]
        self.queue.remove((key, token))
        active = self.active
        if (self.coordinator is not None and not keep_task
                and (active is None or active[0].key != key)):
            self.coordinator.withdraw(self._task_key(key))

    def _dispatch_ticket(self, ticket, kind, *, samples=None, trace=None, **values):
        return self._dispatch(
            ticket.key,
            policy.Event(kind, ticket_generation=ticket.generation, **values),
            samples=samples,
            trace=trace,
            capture=ticket,
        )

    def _schedule_next(self):
        if self.coordinator is not None:
            return
        if self.active is not None or self.scheduler.busy:
            return
        for key, token in tuple(self.queue):
            queued = self.queued.get(key)
            if queued is None or queued[0] != token:
                continue
            ticket = queued[1]
            effects = self._dispatch(
                key,
                policy.Event("schedule", ticket_generation=ticket.generation),
            )
            if effects.start:
                return

    def _remember_samples(self, signature, rgba):
        rgba.setflags(write=False)
        previous = self.samples.pop(signature, None)
        if previous is not None:
            self.sample_bytes -= previous.nbytes
        self.samples[signature] = rgba
        self.sample_bytes += rgba.nbytes
        while (len(self.samples) > CACHE_LIMIT or self.sample_bytes > CACHE_BYTES):
            _key, removed = self.samples.popitem(last=False)
            self.sample_bytes -= removed.nbytes

    def _cached_samples(self, signature):
        samples = self.samples.get(signature)
        if samples is not None:
            self.samples.move_to_end(signature)
        return samples

    @staticmethod
    def _validated_samples(rgba):
        import numpy as np

        values = np.asarray(rgba, dtype=np.float32)
        if (values.ndim != 3 or values.shape[-1] != 4
                or values.size * values.dtype.itemsize > MAX_CAPTURE_BYTES
                or min(values.shape[:2]) < 1):
            raise ValueError("Vectorscope capture returned invalid or oversized RGBA pixels")
        return np.ascontiguousarray(values)

    @staticmethod
    def _mesh_witness(mesh):
        try:
            return routes.vectorscope_mesh_witness(mesh)
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            return None

    def has_editor(self, key):
        """Return whether the host still owns an observed editor binding."""
        key = self._key(key)
        with self._observations:
            return key in self.editors

    def observe_editor(self, key, context, node, viewport=None, *, frame, stage,
                       dragging, tone=None, viewport_for=None, tone_for=None):
        """Reconcile one editor's input and appearance demands on the host timer."""
        if self._shutting_down or (self.coordinator is not None
                                  and not task_admitted("plot", self.coordinator.phase)):
            return None
        key = self._key(key)
        editor = _Editor(self._target(node), frame, stage)
        with self._observations:
            previous = self.editors.get(key)
        if previous is not None and (previous.binding != editor.binding
                                     or previous.frame[0] != frame[0]):
            self.release(key)
        with self._observations:
            self.editors[key] = editor
        appearance = _AppearanceKey(key)
        appearance_enabled = (stage == "TONE" and not getattr(node, "pg_use_bake", False)
                              and not getattr(node, "mute", False))
        input_revision = self._revision(key)
        appearance_revision = self._revision(appearance)
        try:
            if viewport_for is not None:
                viewport = viewport_for()
            if tone_for is not None:
                tone = tone_for()
        except Exception as error:
            self._unavailable(key, error, input_revision)
            if appearance_enabled:
                self._unavailable(appearance, error, appearance_revision)
            return self.display_state(key, node, frame=frame, stage=stage)
        source = self._observe(key, context, node, viewport, tone)

        if not appearance_enabled:
            appearance_state = self._scope_state(appearance)
            if (appearance_state.desired_generation is not None
                    or appearance_state.preview_status != "none"):
                self._release(appearance)
        elif source is not None:
            try:
                self._observe_appearance(key, node, tone, source, dragging)
            except Exception as error:
                self._unavailable(appearance, error, appearance_revision)
        else:
            input_state = self._scope_state(key)
            if input_state.failure_error is not None:
                self._unavailable(appearance, input_state.failure_error, appearance_revision)
        return self.display_state(key, node, frame=frame, stage=stage)

    def _observe_appearance(self, editor, node, tone, source, dragging):
        key = _AppearanceKey(editor)
        route, upstream = source
        input_signature = self.demands[editor].capture_signature
        signature = None if self.grade_signature is None else self.grade_signature(node)
        if signature is None:
            raise RuntimeError("Could not read evaluated Grade settings")
        revision = self._revision(key)
        observation = self.appearance_observations.get(editor)
        if observation is None or observation.grade_signature != signature:
            observation = _AppearanceObservation(signature, self.clock())
            self.appearance_observations[editor] = observation
            self._dispatch(key, policy.Event("preview_withdraw"))
            self._withdraw_preview_task(key)
        state = self._scope_state(key)
        capture_signature = self._digest((input_signature, "appearance", signature))
        same_capture = state.capture_signature == capture_signature
        if same_capture and policy.status(state, revision, True).status == "current":
            if self.preview_roles is not None and not dragging:
                self._schedule_preview_warmup(key)
            return
        peak_j = tone_scope.peak_j(tone)
        source_recapture = state.source_signature != input_signature
        settled = self.clock() - observation.changed_at >= self.appearance_settle_seconds
        grades = (*upstream, node)
        ready = self.coordinator is not None or (
            not dragging
            and (settled or source_recapture or state.published_capture_generation is None)
            and (self.upstream_ready is None or self.upstream_ready(grades))
        )
        changed = not same_capture or state.revision != revision
        if changed or ready == state.waiting:
            self.payloads[key] = payload = _AppearancePayload(
                dict(route, scope_capture="appearance"), peak_j,
            )
            self._plot_grades[key] = grades
            if self.consistency_keys is not None:
                self._plot_prerequisites[key] = tuple(dict.fromkeys((
                    *self.consistency_keys(grades), self._task_key(editor),
                )))
            else:
                self._plot_prerequisites[key] = (self._task_key(editor),)
            samples = (self._cached_samples(capture_signature)
                       if self.coordinator is None and changed and ready else None)
            self._dispatch(key, policy.Event(
                "request", capture_signature=capture_signature,
                source_signature=input_signature, analysis_signature=capture_signature,
                cache_available=samples is not None, ready=ready, revision=revision,
            ), trace=None if samples is None else payload.analyze(samples))
            if samples is not None:
                return
        if self.preview_roles is not None:
            inputs = self._preview_inputs(editor, node)
            if inputs is not None:
                self._observe_appearance_preview(key, node, peak_j, inputs, signature, revision)

    def _observe_appearance_preview(self, key, node, peak_j, inputs, signature, revision):
        demand, samples = inputs
        state = self._scope_state(key)
        if (state.preview_input_signature == demand.capture_signature
                and state.preview_grade_signature == signature
                and state.preview_revision == revision):
            return
        roles = self.preview_roles(node, signature) if self.coordinator is None else None
        if self.coordinator is None and roles is None:
            return
        receipt = _PreviewReceipt(key, revision, demand.capture_signature, signature)
        effects = self._dispatch(key, policy.Event(
            "preview_request", revision=revision,
            preview_input_signature=receipt.input_signature,
            preview_grade_signature=receipt.grade_signature,
        ))
        if not effects.evaluate_preview:
            return
        if self.coordinator is None:
            self._evaluate_preview(receipt, demand, samples, roles, node, peak_j)
        else:
            # Current input samples are already available. Only exact capture
            # waits for the paired input plot task to finish.
            input_task = self._task_key(key.editor)
            prerequisites = tuple(
                task for task in self._plot_prerequisites.get(key, ()) if task != input_task
            )
            self.coordinator.submit(
                self._preview_task_key(key), "plot",
                lambda: self._advance_preview(receipt, demand, node, peak_j),
                editor=key.editor, prerequisites=prerequisites,
            )

    def _advance_preview(self, receipt, demand, node, peak_j):
        """Read validated parameter images and evaluate the current GPU preview."""
        current = self._preview_inputs(receipt.key.editor, node)
        if (current is None or current[0] != demand
                or self._revision(receipt.key) != receipt.revision
                or self.grade_signature(node) != receipt.grade_signature):
            self._dispatch(receipt.key, policy.Event("preview_withdraw"))
            return
        roles = self.preview_roles(node, receipt.grade_signature)
        if roles is not None:
            self._evaluate_preview(receipt, demand, current[1], roles, node, peak_j)
        else:
            self._dispatch(receipt.key, policy.Event(
                "preview_result", revision=receipt.revision,
                preview_input_signature=receipt.input_signature,
                preview_grade_signature=receipt.grade_signature,
            ))

    def _schedule_preview_warmup(self, key):
        if self.coordinator is None:
            self._warm_preview()
        elif (self.preview_backend is None
              and not self.coordinator.has(self._preview_task_key(key))):
            self.coordinator.submit(self._preview_task_key(key), "plot", self._warm_preview,
                                    editor=key.editor)

    def _evaluate_preview(self, receipt, demand, samples, roles, node, peak_j):
        started = self._clock()
        try:
            self._require_preview()
            pixels = self.preview_backend.evaluate(
                samples, roles, input_receipt=demand.capture_signature,
            )
            trace = appearance_scope.analyze(pixels, peak_j)
        except Exception:
            self._dispatch(receipt.key, policy.Event(
                "preview_result", revision=self._revision(receipt.key),
                preview_input_signature=receipt.input_signature,
                preview_grade_signature=receipt.grade_signature,
            ))
            return
        current = self._preview_inputs(receipt.key.editor, node)
        if (current is None or current[0] != demand
                or self.grade_signature(node) != receipt.grade_signature):
            self._dispatch(receipt.key, policy.Event("preview_withdraw"))
            return
        effects = self._dispatch(receipt.key, policy.Event(
            "preview_result", revision=self._revision(receipt.key),
            preview_input_signature=receipt.input_signature,
            preview_grade_signature=receipt.grade_signature,
            success=True,
        ), trace=trace)
        if effects.publish_preview:
            self._record_timing("appearance_preview", started, self._clock(), demand,
                                {"samples": pixels.size // 4})

    def _require_preview(self):
        if self.preview_unavailable is not None:
            raise PreviewUnavailable(self.preview_unavailable)
        if self.preview_backend is None:
            self.preview_backend = AppearancePreview()
        try:
            self.preview_backend.warm()
        except PreviewUnavailable as error:
            self.preview_unavailable = str(error)
            raise

    def _warm_preview(self):
        """Compile the optional preview backend outside pointer-motion handling."""
        try:
            self._require_preview()
        except Exception:
            # A drag reports evaluation failure against its own preview receipt.
            pass

    def _preview_inputs(self, editor, node):
        payload = self.payloads.get(editor)
        state = self._scope_state(editor)
        if (not isinstance(payload, _Payload) or payload.tone is None
                or state.desired_generation is None
                or state.published_source_generation != state.source_generation):
            return None
        with self._observations:
            observed = self.editors.get(editor)
            if (observed is None or observed.binding != self._target(node)
                    or self.source_epochs.get(editor) != payload.source_epoch):
                return None
        demand = self.demands.get(editor)
        if demand is None:
            return None
        samples = self._cached_samples(demand.capture_signature)
        return None if samples is None else (demand, samples)

    def _observe(self, key, context, node, viewport, tone):
        if threading.current_thread() is not self._main_thread:
            raise RuntimeError("Vectorscope observation must run on Blender's main thread")
        revision = self._revision(key)
        try:
            route_started = self._clock()
            dependencies = []
            upstream = []
            watch = {}
            route_options = {"dependencies": dependencies,
                             "upstream_grades": upstream, "watch": watch}
            route = routes.describe_vectorscope(node, context, viewport, **route_options)
            selection = self._selection(node), self._target(node)
            pointers = frozenset(
                int(item.as_pointer()) for item in dependencies
                if getattr(item, "as_pointer", None) is not None
            )
            with self._observations:
                self.dependencies[key] = pointers
                previous_watch = self.watches.get(key)
                epoch = self.source_epochs.get(key)
                if epoch is None:
                    epoch = next(self.epoch)
                    self.source_epochs[key] = epoch
            mesh_witnesses = {}
            needs_mesh_witnesses = (route["owner_kind"] in {"material", "world"}
                                    or route["owner_kind"] == "compositor"
                                    and route.get("has_render_layers", False))
            if needs_mesh_witnesses:
                previous_meshes = ({} if previous_watch is None
                                   else previous_watch.mesh_witnesses)
                for dependency in dependencies:
                    kind = str(getattr(getattr(dependency, "bl_rna", None),
                                       "identifier", type(dependency).__name__))
                    if kind != "Mesh":
                        continue
                    pointer = int(dependency.as_pointer())
                    if pointer in previous_meshes:
                        mesh_witnesses[pointer] = previous_meshes[pointer]
                    else:
                        mesh_witnesses[pointer] = self._mesh_witness(dependency)
            scope_watch = _ScopeWatch(
                frozenset(pointer for pointer, kind in (
                    (int(item.as_pointer()), str(getattr(
                        getattr(item, "bl_rna", None), "identifier", type(item).__name__)))
                    for item in dependencies
                    if getattr(item, "as_pointer", None) is not None
                ) if kind == "Image"),
                mesh_witnesses,
                frozenset(watch.get("input_tree_pointers", ())),
                watch.get("owner_pointer"), watch.get("owner_tree_pointer"),
                bool(watch.get("input_graph_covered", False)),
                bool(watch.get("coverage_invariant", False)),
                route["owner_kind"], bool(route.get("has_render_layers", False)),
            )
            with self._observations:
                self.watches[key] = scope_watch
            source_signature = self._digest((selection, route["source_signature"]))
            capture_identity = (route["capture_signature"], selection, epoch)
            linear = self.linear_settings(node)
            space = self.working_space()
            capture_signature = self._digest(capture_identity)
            analysis_signature = self._analysis_signature(capture_signature, linear, space, tone)
            route_finished = self._clock()
            previous = self.demands.get(key)
            changed = (previous is None or previous.capture_signature != capture_signature
                       or previous.analysis_signature != analysis_signature
                       or previous.source_signature != source_signature
                       or previous.revision != revision)
            grades = tuple(upstream)
            ready = (self.coordinator is not None or self.upstream_ready is None
                     or self.upstream_ready(grades))
            if changed:
                capture_started = self._clock()
                payload = _Payload(route, prepare_linear(linear, space), epoch, tone)
                capture_finished = self._clock()
                samples = (self._cached_samples(capture_signature)
                           if self.coordinator is None and ready else None)
                lookup_finished = self._clock()
                trace = None if samples is None else payload.analyze(samples)
                timings = ()
                if route_started is not None:
                    timings = (
                        ("route_signature", route_started, route_finished),
                        ("linear_prepare", capture_started, capture_finished),
                        ("cache_lookup", capture_finished, lookup_finished),
                    )
                    if samples is not None:
                        timings += (("cached_density", lookup_finished, self._clock()),)
                self.payloads[key] = payload
                self._plot_grades[key] = grades
                if self.consistency_keys is not None:
                    self._plot_prerequisites[key] = tuple(self.consistency_keys(grades))
                self._dispatch(key, policy.Event(
                    "request", capture_signature=capture_signature,
                    source_signature=source_signature, analysis_signature=analysis_signature,
                    cache_available=samples is not None, ready=ready, revision=revision,
                ), trace=trace, timings=timings)
            elif ready == self._scope_state(key).waiting:
                self._dispatch(key, policy.Event(
                    "request", capture_signature=capture_signature,
                    source_signature=source_signature, analysis_signature=analysis_signature,
                    ready=ready, revision=revision,
                ))
            return route, upstream
        except Exception as error:
            self._unavailable(key, error, revision)

    def _white_drag_receipt(self, key, node, frame):
        demand = self.demands.get(key)
        payload = self.payloads.get(key)
        if (demand is None or not isinstance(payload, _Payload) or payload.tone is not None
                or self._scope_state(key).waiting):
            return None
        with self._observations:
            editor = self.editors.get(key)
            if (editor is None or editor.frame != frame or editor.stage != "LINEAR"
                    or editor.binding != self._target(node)
                    or self.source_epochs.get(key) != payload.source_epoch):
                return None
        linear, space = self.linear_settings(node), self.working_space()
        witness = self._digest((
            linear.exposure, linear.balance, linear.spread, linear.heading,
            linear.matrix, space,
        ))
        return WhiteDragReceipt(key, self._target(node), frame, demand.capture_signature,
                                demand.source_generation, payload.source_epoch, witness)

    def begin_white_drag(self, key, node, *, frame):
        """Expose the exact, immutable samples behind the current Linear plot."""
        key = self._key(key)
        capture = self._white_drag_receipt(key, node, frame)
        if (capture is None
                or policy.status(self._scope_state(key), self._revision(key), True).status != "current"):
            return None
        signature = capture.capture_signature
        samples = self._cached_samples(signature)
        if samples is None:
            return None
        linear, space = self.linear_settings(node), self.working_space()
        demand = self.demands.get(key)
        if demand is None:
            return None
        if demand.analysis_signature != self._analysis_signature(signature, linear, space, None):
            return None
        return capture, samples, linear, space

    def white_drag_current(self, receipt, node, *, frame, stage):
        """Check the frozen source and controls while the drag edits source white."""
        return (stage == "LINEAR"
                and self._white_drag_receipt(receipt.editor, node, frame) == receipt)

    def _analysis_signature(self, capture_signature, linear, space, tone):
        return self._digest((capture_signature, linear, space, tone))

    def display_state(self, key, node, *, frame, stage):
        """Read display receipts against live context without resolving a route."""
        key = self._key(key)
        appearance = _AppearanceKey(key)
        with self._observations:
            editor = self.editors.get(key)
            revision = self.revisions.get(key, 0)
            appearance_revision = self.revisions.get(appearance, 0)
            source_epoch = self.source_epochs.get(key)
        plot = self.displays.get(key)
        payload = self.payloads.get(key)
        space_matches = (not isinstance(payload, _Payload)
                         or payload.space == self.working_space())
        epoch_matches = not isinstance(payload, _Payload) or payload.source_epoch == source_epoch
        tone = stage == "TONE"
        readout = policy.project(
            self._scope_state(key), self._scope_state(appearance),
            editor is not None and editor.binding == self._target(node)
            and editor.stage == stage and editor.frame[0] == frame[0],
            editor is not None and frame == editor.frame and space_matches and epoch_matches,
            tone, plot is not None and (plot.ndim == 1) == tone,
            revision, appearance_revision,
            getattr(node, "mute", False), getattr(node, "pg_use_bake", False),
        )
        if not readout.visible:
            return None
        plot = plot if readout.input_show_plot else None
        if readout.appearance_status == "none":
            return DisplayState(plot, readout.input_status, readout.input_error)
        trace = None
        if readout.appearance_show_plot:
            captures = (self.displays if readout.appearance_status == "current"
                        else self.preview_displays)
            trace = captures.get(appearance, self.displays.get(appearance))
        return DisplayState(None, readout.input_status, readout.input_error, plot, trace,
                            readout.appearance_status, readout.appearance_error)

    def record_draw(self, key, trace):
        if self.timing is None or self.displays.get(key) is not trace:
            return
        status = policy.status(self._scope_state(key), self._revision(key), True)
        if status.status != "current":
            return
        ticket = self.demands.get(key)
        if ticket is not None:
            now = self._clock()
            self._record_timing("draw", now, now, ticket)

    def _start(self, ticket):
        payload = self.payloads[ticket.key]
        root = None
        try:
            lookup_started = self._clock()
            samples = self._cached_samples(ticket.capture_signature)
            if samples is not None:
                lookup_finished = self._clock()
                trace = payload.analyze(samples)
                self._record_timing("cache_lookup", lookup_started, lookup_finished, ticket)
                self._record_timing("cached_density", lookup_finished, self._clock(), ticket)
                self._dispatch_ticket(ticket, "capture_result", success=True,
                                      revision=self._revision(ticket.key),
                                      samples=samples, trace=trace)
                return
            gate = None if self.gate is None else self.gate()
            with nullcontext() if gate is None else gate.commit():
                direct_started = self._clock()
                rgba = (None if isinstance(payload, _AppearancePayload)
                        else capture_loaded_image(payload.route))
                direct_finished = self._clock()
                if rgba is None:
                    snapshot_started = self._clock()
                    root, snapshot, images = self.snapshot_scope(payload.route)
                    snapshot_finished = self._clock()
            self._record_timing("direct_readback", direct_started, direct_finished, ticket)
            if rgba is None:
                self._record_timing("snapshot", snapshot_started, snapshot_finished, ticket)
                inputs = {"snapshot_path": str(snapshot), "images": images,
                          "route": payload.route}
                profile = {} if self.timing is None else {"profile": True}
                job = self.create_job(inputs, operation="vectorscope_capture", **profile)
                self.active = (ticket, job, root)
                self._dispatch_ticket(ticket, "started")
                return
            rgba = self._validated_samples(rgba)
            density_started = self._clock()
            trace = payload.analyze(rgba)
            density_finished = self._clock()
            if density_started is not None:
                self._record_timing("result_density", density_started, density_finished, ticket,
                                    {"capture_width": rgba.shape[1],
                                     "capture_height": rgba.shape[0]})
            self._dispatch_ticket(
                ticket, "capture_result", success=True,
                revision=self._revision(ticket.key),
                allow_lagging=self.coordinator is None and not isinstance(ticket.key, _AppearanceKey),
                samples=rgba, trace=trace,
            )
        except PublicationDeferred:
            if root is not None:
                shutil.rmtree(root, ignore_errors=True)
            self._dispatch_ticket(ticket, "deferred")
        except Exception as error:
            if root is not None:
                shutil.rmtree(root, ignore_errors=True)
            self.active = None
            self._dispatch_ticket(
                ticket, "capture_result", error=str(error),
                revision=self._revision(ticket.key),
            )

    def poll(self):
        """Advance at most one helper response without waiting for its render."""
        if threading.current_thread() is not self._main_thread:
            raise RuntimeError("Vectorscope helper polling must run on Blender's main thread")
        if self.coordinator is not None:
            return bool(self.active is not None or self.queued)
        if self.active is None:
            self._schedule_next()
            return self.active is not None or bool(self.queue)
        return self._poll_active_once()

    def _poll_active_once(self):
        ticket, job, root = self.active
        rgba = trace = None
        try:
            poll_started = self._clock()
            result = job.advance()
            self._record_timing("helper_poll", poll_started, self._clock(), ticket)
            if result is None:
                return True
            scope = self._scope_state(ticket.key)
            if (policy.result_current(scope, ticket.generation)
                    and (self.coordinator is None or scope.capture_signature == ticket.capture_signature)):
                rgba = self._validated_samples(result["rgba"])
                payload = self.payloads[ticket.key]
                density_started = self._clock()
                trace = payload.analyze(rgba)
                self._record_timing("result_density", density_started, self._clock(), ticket)
            if rgba is not None and self.timing is not None and job.timings:
                metadata = {"helper_reused": job.helper_reused,
                            "capture_width": rgba.shape[1], "capture_height": rgba.shape[0]}
                for stage, started, finished, clock in job.timings:
                    self._record_timing(stage, started, finished, ticket,
                                        dict(metadata, clock=clock))
        except Exception as error:
            failure = str(error)
        else:
            failure = None
        if root is not None:
            shutil.rmtree(root, ignore_errors=True)
        self.active = None
        self._dispatch_ticket(
            ticket, "capture_result", success=failure is None,
            error=failure, revision=self._revision(ticket.key),
            allow_lagging=self.coordinator is None and not isinstance(ticket.key, _AppearanceKey),
            samples=rgba, trace=trace,
        )
        return bool(self.queue)

    def invalidate(self, _scene=None, changed_ids=()):
        """Advance only source revisions whose captured dependencies changed."""
        identifiers = {}
        for value in changed_ids:
            try:
                pointer = int(value.as_pointer())
                kind = str(getattr(getattr(value, "bl_rna", None),
                                   "identifier", type(value).__name__))
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                continue
            if pointer:
                identifiers[pointer] = (kind, value)
        if not identifiers:
            return ()
        affected = []
        with self._observations:
            for key, dependencies in self.dependencies.items():
                watch = self.watches.get(key)
                if watch is None:
                    if dependencies & identifiers.keys():
                        self.source_epochs[key] = next(self.epoch)
                        self._mark_source_changed(key)
                        affected.append(key)
                    continue

                matching = {pointer: identifiers[pointer]
                            for pointer in dependencies & identifiers.keys()}
                invalidated = any(kind == "Image" and pointer in watch.images
                                  for pointer, (kind, _value) in matching.items())
                current_meshes = dict(watch.mesh_witnesses)
                for pointer, (kind, value) in matching.items():
                    if kind == "Image":
                        continue
                    if kind == "Mesh":
                        relevant = (watch.owner_kind in {"material", "world"}
                                    or watch.owner_kind == "compositor"
                                    and watch.has_render_layers)
                        if not relevant:
                            continue
                        previous = current_meshes.get(pointer)
                        if pointer not in current_meshes:
                            invalidated = True
                            continue
                        current = self._mesh_witness(value)
                        if previous is None or current is None or current != previous:
                            invalidated = True
                            current_meshes[pointer] = current
                        continue
                    if kind in {"Curve", "Curves", "PointCloud", "Volume"}:
                        if (watch.owner_kind in {"material", "world"}
                                or watch.owner_kind == "compositor"
                                and watch.has_render_layers):
                            invalidated = True
                        continue
                    if watch.owner_kind in {"material", "world"}:
                        if not self._covered_shader_dependency(pointer, watch):
                            invalidated = True
                    elif (watch.owner_kind == "compositor" and watch.has_render_layers
                          and not (watch.input_graph_covered
                                   and pointer in watch.input_tree_pointers)):
                        invalidated = True

                if invalidated:
                    self.source_epochs[key] = next(self.epoch)
                    self._mark_source_changed(key)
                    affected.append(key)
                if current_meshes != watch.mesh_witnesses:
                    self.watches[key] = _ScopeWatch(
                        watch.images, current_meshes, watch.input_tree_pointers,
                        watch.owner_pointer, watch.owner_tree_pointer,
                        watch.input_graph_covered, watch.coverage_invariant,
                        watch.owner_kind,
                        watch.has_render_layers,
                    )
        return tuple(dict.fromkeys(_editor_key(key) for key in affected))

    def _mark_source_changed(self, key):
        """Dirty the source receipt and its paired appearance receipt."""
        self.revisions[key] = self.revisions.get(key, 0) + 1
        if isinstance(key, _AppearanceKey):
            return
        appearance = _AppearanceKey(key)
        editor = self.editors.get(key)
        if editor is not None and editor.stage == "TONE":
            self.revisions[appearance] = self.revisions.get(appearance, 0) + 1

    def frame_changed(self, scene_pointer):
        """Invalidate all demands belonging to a scene before frame evaluation."""
        affected = []
        with self._observations:
            for key, editor in self.editors.items():
                if editor.frame[0] != scene_pointer:
                    continue
                self.source_epochs[key] = next(self.epoch)
                self._mark_source_changed(key)
                affected.append(_editor_key(key))
        return tuple(dict.fromkeys(affected))

    @staticmethod
    def _covered_shader_dependency(pointer, watch):
        return (watch.coverage_invariant and (
            pointer in watch.input_tree_pointers
            or pointer == watch.owner_pointer
            or pointer == watch.owner_tree_pointer
        ))

    def linear_changed(self, owner):
        return self._affected_editors(owner)

    def tone_changed(self, owner):
        return self._affected_editors(owner, tone_only=True)

    def appearance_changed(self, owner):
        return self._affected_editors(owner, appearance_only=True)

    def _affected_editors(self, owner, *, tone_only=False, appearance_only=False):
        try:
            pointer = int(owner.as_pointer())
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            return ()
        with self._observations:
            keys = []
            for key, editor in self.editors.items():
                if pointer not in editor.binding:
                    continue
                appearance = _AppearanceKey(key)
                tone = editor.stage == "TONE"
                input_changed = not appearance_only and (not tone_only or tone)
                if input_changed:
                    self.revisions[key] = self.revisions.get(key, 0) + 1
                if tone:
                    self.revisions[appearance] = self.revisions.get(appearance, 0) + 1
                if input_changed or tone:
                    keys.append(key)
            return tuple(keys)

    def _forget_observation(self, key, *, release_binding=False):
        self.payloads.pop(key, None)
        self._plot_prerequisites.pop(key, None)
        self._plot_grades.pop(key, None)
        with self._observations:
            self.dependencies.pop(key, None)
            self.watches.pop(key, None)
            self.source_epochs.pop(key, None)
            if release_binding:
                if not isinstance(key, _AppearanceKey):
                    self.editors.pop(key, None)
                self.revisions.pop(key, None)

    def _unavailable(self, node_editor_key, error, revision=None):
        key = self._key(node_editor_key)
        current_revision = self._revision(key) if revision is None else revision
        self._forget_observation(key)
        self._dispatch(key, policy.Event("unavailable", error=str(error),
                                         revision=current_revision))

    def release(self, node_editor_key):
        key = self._key(node_editor_key)
        self.release_appearance(key)
        self._release(key)

    def release_appearance(self, node_editor_key):
        editor = self._key(node_editor_key)
        self._release(_AppearanceKey(editor))

    def _release(self, key):
        if isinstance(key, _AppearanceKey):
            self.appearance_observations.pop(key.editor, None)
        self._forget_observation(key, release_binding=True)
        self._withdraw_task(key)
        self._dispatch(key, policy.Event("release"))

    def reset(self):
        for key in tuple(self.scope_states):
            self._dispatch(key, policy.Event("reset"))
            self._withdraw_task(key)
        self.payloads.clear()
        self._plot_prerequisites.clear()
        self._plot_grades.clear()
        self.samples.clear()
        self.appearance_observations.clear()
        self.sample_bytes = 0
        if self.preview_backend is not None:
            self.preview_backend.close()
            self.preview_backend = None
        self.preview_unavailable = None
        with self._observations:
            self.dependencies.clear()
            self.watches.clear()
            self.source_epochs.clear()
            self.editors.clear()
            self.revisions.clear()

    def begin_shutdown(self):
        """Withdraw all demand before the borrowed job owner is stopped."""
        if self._shutting_down:
            return
        self._shutting_down = True
        self.reset()

    def finish_shutdown(self):
        """Forget borrowed capture state after its owner has retired jobs."""
        if self.active is not None:
            ticket, job, root = self.active
            retired = getattr(job, "retired", None)
            if not callable(retired) or not retired():
                raise RuntimeError("Cannot finish scope shutdown before capture retirement")
            if root is not None:
                shutil.rmtree(root, ignore_errors=True)
            self.active = None
            self._paused_capture = None
            self._dispatch_ticket(
                ticket, "capture_result",
                allow_lagging=not isinstance(ticket.key, _AppearanceKey),
            )
        self.scope_states.clear()
        self.payloads.clear()
        self.displays.clear()
        self.preview_displays.clear()


__all__ = ("ScopeRuntime",)
