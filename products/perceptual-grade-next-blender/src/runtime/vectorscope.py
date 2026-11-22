"""Transient, latest-demand coordination for the Linear Gizmo vectorscope."""

# pg-book: technical-report/en#next-policy.vectorscope

from collections import OrderedDict
from contextlib import nullcontext
from dataclasses import dataclass
import hashlib
from itertools import count
import shutil
import threading

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
        self.pending_start = None
        self.waiting = set()
        self.source_epochs = {}
        self.epoch = count(1)
        self.dependencies = {}
        self.targets = {}
        self._observations = threading.Lock()
        self._main_thread = threading.main_thread()

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

    def _dispatch(self, event, *, samples=None, brightness=None):
        self.state, effects = policy.step(self.state, event)
        self._apply(effects, samples=samples, brightness=brightness)

    def _apply(self, effects, *, samples=None, brightness=None):
        for key in effects.clear:
            self.displays.pop(key, None)
        if effects.retain_samples is not None:
            self._remember_samples(effects.retain_samples, samples)
        if effects.publish is not None:
            self.displays[effects.publish.key] = brightness
        if effects.start is not None:
            self._start(effects.start)

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

    def observe(self, node_editor_key, context, node, viewport):
        """Record one visible scope demand and return immutable display state."""
        if threading.current_thread() is not self._main_thread:
            raise RuntimeError("Vectorscope observation must run on Blender's main thread")
        key = self._key(node_editor_key)
        try:
            dependencies = []
            upstream = []
            route = bake_routes.describe_vectorscope(
                node, context, viewport, dependencies=dependencies,
                upstream_grades=upstream,
            )
            linear = self.linear_settings(node)
            space = self.working_space()
            selection = self._selection(node)
            pointers = frozenset(
                int(item.as_pointer()) for item in dependencies
                if getattr(item, "as_pointer", None) is not None
            )
            with self._observations:
                self.targets[key] = int(node.as_pointer())
                self.dependencies[key] = pointers
                epoch = self.source_epochs.get(key)
                if epoch is None:
                    epoch = next(self.epoch)
                    self.source_epochs[key] = epoch
            source_signature = self._digest((selection, route["source_signature"]))
            capture_signature = self._digest((route["capture_signature"],
                                              selection, epoch))
            analysis_signature = self._digest((capture_signature, linear, space))
            previous = next((item for item in self.state.desired if item.key == key), None)
            changed = (previous is None or previous.capture_signature != capture_signature
                       or previous.analysis_signature != analysis_signature
                       or previous.source_signature != source_signature)
            ready = self.upstream_ready is None or self.upstream_ready(tuple(upstream))
            if not ready:
                self.waiting.add(key)
            else:
                self.waiting.discard(key)
            if changed:
                matrix = prepare_linear(linear, space).rgb_matrix
                samples = self.samples.get(capture_signature) if ready else None
                brightness = (None if samples is None
                              else analysis.density(samples, matrix, space))
                self.payloads[key] = _Payload(route, matrix, space)
                self._dispatch(policy.Event(
                    "request", key=key, capture_signature=capture_signature,
                    source_signature=source_signature, analysis_signature=analysis_signature,
                    cache_available=samples is not None,
                ), brightness=brightness)
        except Exception as error:
            self.waiting.discard(key)
            self.payloads.pop(key, None)
            with self._observations:
                self.dependencies.pop(key, None)
                self.source_epochs.pop(key, None)
            self._dispatch(policy.Event("unavailable", key=key, error=str(error)))

        return self._display_state(key)

    def _display_state(self, key):
        status, error = policy.status(self.state, key)
        if key in self.waiting:
            return self.displays.get(key), "updating", None
        if status == "error":
            return None, status, error
        return self.displays.get(key), status, None

    def _start(self, ticket):
        self.pending_start = None
        desired = policy.result_demand(self.state, ticket)
        if desired is None or desired.capture_signature != ticket.capture_signature:
            self._dispatch(policy.Event(
                "capture_result", ticket=ticket,
            ))
            return
        if ticket.key in self.waiting:
            self.pending_start = ticket
            return
        payload = self.payloads[ticket.key]
        root = None
        try:
            gate = None if self.gate is None else self.gate()
            with nullcontext() if gate is None else gate.commit():
                rgba = capture_loaded_image(payload.route)
                if rgba is None:
                    root, snapshot, images = self.snapshot_scope(payload.route)
            if rgba is None:
                inputs = {"snapshot_path": str(snapshot), "images": images,
                          "route": payload.route}
                job = self.backend.create_job(inputs, operation="vectorscope_capture")
                self.active = (ticket, job, root)
                return
            rgba = self._validated_samples(rgba)
            brightness = analysis.density(rgba, payload.matrix, payload.space)
            self._dispatch(policy.Event(
                "capture_result", ticket=ticket, success=True,
            ), samples=rgba, brightness=brightness)
        except PublicationDeferred:
            if root is not None:
                shutil.rmtree(root, ignore_errors=True)
            self.pending_start = ticket
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
        if self.active is None and self.pending_start is not None:
            self._start(self.pending_start)
        if self.active is None:
            return self.pending_start is not None
        ticket, job, root = self.active
        rgba = brightness = None
        try:
            result = job.advance()
            if result is None:
                return True
            rgba = self._validated_samples(result["rgba"])
            desired = policy.result_demand(self.state, ticket)
            if desired is not None:
                payload = self.payloads[ticket.key]
                brightness = analysis.density(rgba, payload.matrix, payload.space)
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
        ), samples=rgba, brightness=brightness)
        return self.active is not None or self.pending_start is not None

    def invalidate(self, _scene=None, changed_ids=()):
        """Advance only source revisions whose captured dependencies changed."""
        pointers = set()
        for value in changed_ids:
            try:
                pointers.add(int(value.as_pointer()))
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                continue
        if not pointers:
            return ()
        affected = []
        with self._observations:
            for key, dependencies in self.dependencies.items():
                if dependencies & pointers:
                    self.source_epochs[key] = next(self.epoch)
                    affected.append(key)
        return tuple(affected)

    def linear_changed(self, node):
        try:
            pointer = int(node.as_pointer())
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            return ()
        with self._observations:
            return tuple(key for key, target in self.targets.items()
                         if target == pointer)

    def release(self, node_editor_key):
        key = self._key(node_editor_key)
        self._dispatch(policy.Event("release", key=key))
        self.payloads.pop(key, None)
        self.waiting.discard(key)
        with self._observations:
            self.dependencies.pop(key, None)
            self.source_epochs.pop(key, None)
            self.targets.pop(key, None)

    def reset(self):
        self._dispatch(policy.Event("reset"))
        self.payloads.clear()
        self.samples.clear()
        self.sample_bytes = 0
        self.waiting.clear()
        with self._observations:
            self.dependencies.clear()
            self.source_epochs.clear()
            self.targets.clear()
        if self.active is not None:
            self.active[1].cancel()

    def close(self):
        self.reset()
        active = self.active
        if active is not None:
            active[1].cancel()
        self.backend.close()
        if active is not None:
            shutil.rmtree(active[2], ignore_errors=True)
            self.active = None


__all__ = ("ScopeRuntime",)
