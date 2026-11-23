"""Transient, latest-demand coordination for the Linear Gizmo vectorscope."""

# pg-book: technical-report/en#next-policy.vectorscope

from collections import OrderedDict
from contextlib import nullcontext
from dataclasses import dataclass
import hashlib
from itertools import count
import shutil
import threading
import time

from .. import vectorscope as analysis
from ..kernel.prepare import prepare_linear
from . import vectorscope_policy as policy
from .bake_helper import BakeHelperBackend
from . import bake_routes
from .vectorscope_capture import capture_loaded_image
from .publication import PublicationDeferred


MAX_CAPTURE_BYTES = 512 * 512 * 4 * 4
CACHE_LIMIT = 8
CACHE_BYTES = 64 * 1024 * 1024


@dataclass(frozen=True)
class _Payload:
    route: object
    matrix: object
    space: str
    source_epoch: int


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
    """Capture evaluated Grade inputs outside Blender's drawing callback."""

    def __init__(self, bpy, snapshot_scope, linear_settings, working_space,
                 backend=None, *, gate=None, upstream_ready=None):
        self.snapshot_scope = snapshot_scope
        self.backend = backend or BakeHelperBackend()
        self.linear_settings = linear_settings
        self.working_space = working_space
        self.gate = gate
        self.upstream_ready = upstream_ready
        self.state = policy.State()
        self.payloads = {}
        self.displays = {}
        self.samples = OrderedDict()
        self.sample_bytes = 0
        self.active = None
        self.source_epochs = {}
        self.epoch = count(1)
        self.dependencies = {}
        self.watches = {}
        self.targets = {}
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

    def _dispatch(self, event, *, samples=None, trace=None, timings=()):
        self.state, effects = policy.step(self.state, event)
        if timings:
            ticket = next(item for item in self.state.desired if item.key == event.key)
            now = self._clock()
            self._record_timing("request", now, now, ticket)
            for stage, started, finished in timings:
                self._record_timing(stage, started, finished, ticket)
        self._apply(effects, samples=samples, trace=trace, capture=event.ticket)

    def _apply(self, effects, *, samples=None, trace=None, capture=None):
        for key in effects.clear:
            self.displays.pop(key, None)
        if effects.retain_samples is not None:
            self._remember_samples(effects.retain_samples, samples)
        if effects.publish is not None:
            ticket = effects.publish
            started = self._clock()
            self.displays[ticket.key] = trace
            if started is not None:
                status, _error = policy.status(self.state, ticket.key)
                self._record_timing("publish", started, self._clock(), ticket, {
                    "current": status == "current",
                    "capture_generation": (ticket.generation if capture is None
                                           else capture.generation),
                })
        if effects.start is not None:
            self._start(effects.start)
        if effects.cancel is not None and self.active is not None:
            ticket, job, _root = self.active
            if ticket == effects.cancel:
                job.cancel()

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
            return bake_routes.vectorscope_mesh_witness(mesh)
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            return None

    def observe(self, node_editor_key, context, node, viewport):
        """Record one visible scope demand and return immutable display state."""
        if threading.current_thread() is not self._main_thread:
            raise RuntimeError("Vectorscope observation must run on Blender's main thread")
        key = self._key(node_editor_key)
        try:
            route_started = self._clock()
            dependencies = []
            upstream = []
            watch = {}
            route = bake_routes.describe_vectorscope(
                node, context, viewport, dependencies=dependencies,
                upstream_grades=upstream, watch=watch,
            )
            linear = self.linear_settings(node)
            space = self.working_space()
            selection = self._selection(node)
            pointers = frozenset(
                int(item.as_pointer()) for item in dependencies
                if getattr(item, "as_pointer", None) is not None
            )
            with self._observations:
                self.targets[key] = self._target(node)
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
            capture_signature = self._digest((route["capture_signature"],
                                              selection, epoch))
            analysis_signature = self._digest((capture_signature, linear, space))
            route_finished = self._clock()
            previous = next((item for item in self.state.desired if item.key == key), None)
            changed = (previous is None or previous.capture_signature != capture_signature
                       or previous.analysis_signature != analysis_signature
                       or previous.source_signature != source_signature)
            ready = self.upstream_ready is None or self.upstream_ready(tuple(upstream))
            if changed:
                linear_started = self._clock()
                matrix = prepare_linear(linear, space).rgb_matrix
                linear_finished = self._clock()
                samples = self.samples.get(capture_signature)
                lookup_finished = self._clock()
                trace = (None if samples is None
                         else analysis.analyze(samples, matrix, space))
                timings = ()
                if route_started is not None:
                    timings = (
                        ("route_signature", route_started, route_finished),
                        ("linear_prepare", linear_started, linear_finished),
                        ("cache_lookup", linear_finished, lookup_finished),
                    )
                    if samples is not None:
                        timings += (("cached_density", lookup_finished, self._clock()),)
                self.payloads[key] = _Payload(route, matrix, space, epoch)
                self._dispatch(policy.Event(
                    "request", key=key, capture_signature=capture_signature,
                    source_signature=source_signature, analysis_signature=analysis_signature,
                    cache_available=samples is not None, ready=ready,
                ), trace=trace, timings=timings)
            elif ready == (key in self.state.waiting):
                self._dispatch(policy.Event(
                    "request", key=key, capture_signature=capture_signature,
                    source_signature=source_signature, analysis_signature=analysis_signature,
                    ready=ready,
                ))
        except Exception as error:
            return self.unavailable(key, error)

        return self._display_state(key)

    def drag_capture(self, key, node):
        """Identify the input capture while Linear edits update its analysis."""
        key = self._key(key)
        demand = next((item for item in self.state.desired if item.key == key), None)
        payload = self.payloads.get(key)
        if demand is None or payload is None or key in self.state.waiting:
            return None
        with self._observations:
            if (self.targets.get(key) != self._target(node)
                    or self.source_epochs.get(key) != payload.source_epoch):
                return None
        linear, space = self.linear_settings(node), self.working_space()
        witness = self._digest((
            linear.exposure, linear.balance, linear.spread, linear.heading,
            linear.matrix, space,
        ))
        return demand.capture_signature, payload.source_epoch, witness

    def drag_inputs(self, key, node):
        """Expose the exact, immutable samples behind the current Linear plot."""
        key = self._key(key)
        capture = self.drag_capture(key, node)
        if capture is None or policy.status(self.state, key)[0] != "current":
            return None
        signature, _epoch, _witness = capture
        samples = self.samples.get(signature)
        if samples is None:
            return None
        linear, space = self.linear_settings(node), self.working_space()
        demand = next(item for item in self.state.desired if item.key == key)
        if demand.analysis_signature != self._digest((signature, linear, space)):
            return None
        return samples, linear, space

    def _display_state(self, key):
        status, error = policy.status(self.state, key)
        if status == "error":
            return None, status, error
        return self.displays.get(key), status, None

    def record_draw(self, key, trace):
        if self.timing is None or self.displays.get(key) is not trace:
            return
        status, _error = policy.status(self.state, key)
        if status != "current":
            return
        ticket = next((item for item in self.state.desired if item.key == key), None)
        if ticket is not None:
            now = self._clock()
            self._record_timing("draw", now, now, ticket)

    def _start(self, ticket):
        payload = self.payloads[ticket.key]
        root = None
        try:
            gate = None if self.gate is None else self.gate()
            with nullcontext() if gate is None else gate.commit():
                direct_started = self._clock()
                rgba = capture_loaded_image(payload.route)
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
                job = self.backend.create_job(inputs, operation="vectorscope_capture", **profile)
                self.active = (ticket, job, root)
                self._dispatch(policy.Event("started", ticket=ticket))
                return
            rgba = self._validated_samples(rgba)
            density_started = self._clock()
            trace = analysis.analyze(rgba, payload.matrix, payload.space)
            density_finished = self._clock()
            if density_started is not None:
                self._record_timing("result_density", density_started, density_finished, ticket,
                                    {"capture_width": rgba.shape[1],
                                     "capture_height": rgba.shape[0]})
            self._dispatch(policy.Event(
                "capture_result", ticket=ticket, success=True,
            ), samples=rgba, trace=trace)
        except PublicationDeferred:
            if root is not None:
                shutil.rmtree(root, ignore_errors=True)
            self._dispatch(policy.Event("deferred", ticket=ticket))
        except Exception as error:
            if root is not None:
                shutil.rmtree(root, ignore_errors=True)
            self.active = None
            self._dispatch(policy.Event(
                "capture_result", ticket=ticket, success=False, error=str(error),
            ))

    def poll(self):
        """Advance at most one helper response without waiting for its render."""
        if threading.current_thread() is not self._main_thread:
            raise RuntimeError("Vectorscope helper polling must run on Blender's main thread")
        if self.active is None:
            self._dispatch(policy.Event("schedule"))
            return self.active is not None or bool(self.state.queued)
        ticket, job, root = self.active
        rgba = trace = None
        try:
            poll_started = self._clock()
            result = job.advance()
            self._record_timing("helper_poll", poll_started, self._clock(), ticket)
            if result is None:
                return True
            if policy.result_demand(self.state, ticket) is not None:
                rgba = self._validated_samples(result["rgba"])
                payload = self.payloads[ticket.key]
                density_started = self._clock()
                trace = analysis.analyze(rgba, payload.matrix, payload.space)
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
        self._dispatch(policy.Event(
            "capture_result", ticket=ticket, success=failure is None,
            error=failure,
        ), samples=rgba, trace=trace)
        return bool(self.state.queued)

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
                    affected.append(key)
                if current_meshes != watch.mesh_witnesses:
                    self.watches[key] = _ScopeWatch(
                        watch.images, current_meshes, watch.input_tree_pointers,
                        watch.owner_pointer, watch.owner_tree_pointer,
                        watch.input_graph_covered, watch.coverage_invariant,
                        watch.owner_kind,
                        watch.has_render_layers,
                    )
        return tuple(affected)

    @staticmethod
    def _covered_shader_dependency(pointer, watch):
        return (watch.coverage_invariant and (
            pointer in watch.input_tree_pointers
            or pointer == watch.owner_pointer
            or pointer == watch.owner_tree_pointer
        ))

    def linear_changed(self, owner):
        try:
            pointer = int(owner.as_pointer())
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            return ()
        with self._observations:
            return tuple(key for key, target in self.targets.items()
                         if pointer in target)

    def _forget_observation(self, key):
        self.payloads.pop(key, None)
        with self._observations:
            self.dependencies.pop(key, None)
            self.watches.pop(key, None)
            self.source_epochs.pop(key, None)
            self.targets.pop(key, None)

    def unavailable(self, node_editor_key, error):
        key = self._key(node_editor_key)
        self._forget_observation(key)
        self._dispatch(policy.Event("unavailable", key=key, error=str(error)))
        return self._display_state(key)

    def release(self, node_editor_key):
        key = self._key(node_editor_key)
        self._forget_observation(key)
        self._dispatch(policy.Event("release", key=key))

    def reset(self):
        self._dispatch(policy.Event("reset"))
        self.payloads.clear()
        self.samples.clear()
        self.sample_bytes = 0
        with self._observations:
            self.dependencies.clear()
            self.watches.clear()
            self.source_epochs.clear()
            self.targets.clear()

    def close(self):
        self.reset()
        active = self.active
        self.backend.close()
        if active is not None:
            ticket, _job, root = active
            if root is not None:
                shutil.rmtree(root, ignore_errors=True)
            self.active = None
            self._dispatch(policy.Event("capture_result", ticket=ticket))


__all__ = ("ScopeRuntime",)
