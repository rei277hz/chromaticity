"""Controllable helper completion receipts for foreground scheduling tests."""
from collections import OrderedDict
from concurrent.futures import Future
from contextlib import ExitStack
from threading import Event
from types import SimpleNamespace
from unittest.mock import patch
from color_tools.perceptual_grade_core.jobs import codec
from color_tools.perceptual_grade_blender.jobs.handlers import scopes as handlers
from color_tools.perceptual_grade_core.model import scope_analysis
from .blender import component


class DeferredResult(Future):
    def __init__(self, compute, gate=None, encode=codec.freeze_scope_result):
        super().__init__()
        self.compute, self.gate = compute, gate
        self.encode = encode
        self._preview = None
        self.set_running_or_notify_cancel()

    @property
    def preview(self):
        self._complete()
        return self._preview

    def publish_preview(self, value):
        self._preview = value

    def _complete(self):
        if super().done() or self.gate is not None and not self.gate.is_set():
            return
        try:
            self.set_result(self.encode(self.compute()))
        except Exception as error:
            self.set_exception(error)

    def done(self):
        self._complete()
        return super().done()

    def result(self, timeout=None):
        self._complete()
        return super().result(timeout)


class ScopeExecutor:
    """Run numerical functions only when a test releases their response gate.

    This models process messages, not Python worker threads. Numerical/process
    parity is covered independently by scope_execution and installed helpers.
    """
    def __init__(self, gates=None):
        self.gates = gates or {}
        operations=('scope_linear','scope_full','scope_register','scope_update')
        self.snapshots = {name:[] for name in operations}
        self.started = {name:Event() for name in operations}
        self.cache = OrderedDict()
        self.session = str(id(self))
        self._helper_session = None
        self._helper_caches = {}

    def __call__(self, operation, snapshot):
        captured = codec.thaw_scope_request(codec.freeze_scope_request(snapshot))
        captures = self.snapshots[operation]
        index = len(captures)
        captures.append(captured)
        gates = self.gates.get(operation, ())
        gate = gates[index] if index < len(gates) else None
        self.started[operation].set()
        if operation in ('scope_register','scope_update'):
            if self._helper_session != self.session:
                self._helper_session = self.session
                self._helper_caches = {name: OrderedDict() for name in
                    ('_cache', '_warp_results', '_sources', '_active_bases')}
            context=SimpleNamespace(role='bulk',generation=0,session=self.session,
                checkpoint=lambda:None,preview=lambda value:future.publish_preview(value))
            handler=handlers.register if operation=='scope_register' else handlers.update
            caches=self._helper_caches
            def compute():
                # Real helpers own these dictionaries inside separate processes.
                # Keep the synchronous fixture faithful across tests/restarts.
                with ExitStack() as stack:
                    for name,cache in caches.items():stack.enter_context(patch.object(handlers,name,cache))
                    return handler(codec.freeze_scope_request(captured),context)
            encode=lambda value:value
        else:
            compute = (lambda: scope_analysis.evaluate_linear(captured)) if operation == 'scope_linear' else (
                lambda: scope_analysis.evaluate_snapshot(captured, self.cache))
            encode = codec.freeze_scope_result if operation == 'scope_linear' else codec.freeze_full_scope_result
        future=DeferredResult(compute,gate,encode)
        return component('scopes.jobs').ScopeResult(future)
