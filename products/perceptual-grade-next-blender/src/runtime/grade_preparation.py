"""Concurrent, host-free preparation of complete Linear and Tone Grades."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
import hashlib
import json
import threading
import time

from ..kernel.boundary import RESOURCE_SCHEMA, prepare_boundary
from ..kernel.color_prepare import prepare_color
from ..kernel.prepare import (
    GAMMA,
    PreparedGrade,
    prepare_linear,
    prepare_tone,
    viewing,
)
from ..kernel.settings import ColorSettings, Settings
from ..policy import preparation_join


PREPARATION_SCHEMA = 1


def preparation_signature(settings: Settings) -> str:
    """Correlate children with the complete immutable numerical input."""
    if not isinstance(settings, Settings):
        raise TypeError("Grade preparation requires frozen Settings")
    encoded = json.dumps(
        (PREPARATION_SCHEMA, RESOURCE_SCHEMA, asdict(settings)),
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class GradePreparer:
    """Own a bounded pool and immutable boundary cache for one lifecycle.

    ``prepare`` is awaited on its caller's loop; the owner retains no loop.
    ``on_timing(signature, component, started, finished)`` runs on that loop,
    after worker retirement. Its times use ``time.perf_counter``. ``join``
    covers the whole preparation, including neutral Color parameter assembly.
    Close only after callers have drained their aggregate preparations.
    """

    def __init__(self, workers=3, on_timing=None):
        if workers < 3:
            raise ValueError("Grade preparation needs at least three workers")
        self._executor = ThreadPoolExecutor(
            max_workers=workers, thread_name_prefix="grade-preparation"
        )
        self._lock = threading.RLock()
        self._cache_lock = threading.Lock()
        self._closed = False
        self._boundary_cache = {}
        self.on_timing = on_timing

    def _boundary(self, settings):
        if settings.tone.reference_nits != 203.0:
            raise ValueError("Grade preparation requires a 203-nit viewing reference")
        fl, aw = viewing(settings.tone.reference_nits)
        key = (RESOURCE_SCHEMA, fl, aw, GAMMA)
        with self._cache_lock:
            boundary = self._boundary_cache.get(key)
            if boundary is None:
                boundary = prepare_boundary(fl, aw, GAMMA)
                self._boundary_cache[key] = boundary
            return boundary

    @staticmethod
    def _tone_and_color(settings):
        tone = prepare_tone(settings.tone, full_fields=True)
        color = prepare_color(settings.color, tone, full_fields=False)
        return tone, color

    @staticmethod
    def _run(component, prepare):
        started = time.perf_counter()
        try:
            value = prepare()
        except Exception as error:
            return component, None, error, started, time.perf_counter()
        return component, value, None, started, time.perf_counter()

    def _trace(self, signature, component, started, finished):
        if self.on_timing is not None:
            self.on_timing(signature, component, started, finished)

    async def prepare(self, settings: Settings) -> PreparedGrade:
        """Launch every required component before awaiting any one of them."""
        signature = preparation_signature(settings)
        if settings.color != ColorSettings():
            raise ValueError("Grade preparation currently supports neutral Color only")
        started = time.perf_counter()
        state = preparation_join.new(signature)
        loop = asyncio.get_running_loop()
        components = (
            ("linear", lambda: prepare_linear(settings.linear, settings.space)),
            ("tone", lambda: self._tone_and_color(settings)),
            ("boundary", lambda: self._boundary(settings)),
        )
        with self._lock:
            if self._closed:
                raise RuntimeError("Grade preparer is closed")
            children = tuple(
                loop.run_in_executor(self._executor, self._run, name, prepare)
                for name, prepare in components
            )

        # Process receipts as each child retires. The group below retains the
        # aggregate slot until every worker has physically returned, including
        # when a child or a diagnostic callback fails.
        values = {}
        completion = preparation_join.Effects()
        first_error = None
        trace_error = None

        async def receive(name, child):
            nonlocal state, completion, first_error, trace_error
            component, value, error, child_started, child_finished = await child
            if component != name:
                raise RuntimeError("Preparation receipt has the wrong component")
            state, effects = preparation_join.step(
                state,
                preparation_join.Event(
                    signature, name, None if error is None else str(error)
                ),
            )
            if error is None:
                values[name] = value
            elif first_error is None:
                first_error = error
            if effects.completion_signature is not None:
                completion = effects
            try:
                self._trace(signature, name, child_started, child_finished)
            except Exception as error:
                if trace_error is None:
                    trace_error = error

        group = asyncio.gather(
            *(receive(name, child) for (name, _), child in zip(components, children)),
            return_exceptions=True,
        )
        try:
            failures = await asyncio.shield(group)
        except asyncio.CancelledError:
            # Cancellation withdraws the caller, but cannot claim a running
            # executor function has stopped. Keep our physical retirement fence.
            await asyncio.shield(group)
            raise
        for error in failures:
            if isinstance(error, BaseException):
                raise error

        # Only a terminal join effect authorizes the aggregate to be assembled.
        if completion.completion_signature != signature:
            raise RuntimeError("Preparation join did not authorize an aggregate")
        finished = time.perf_counter()
        self._trace(signature, "join", started, finished)
        if completion.error is not None:
            if first_error is None:
                raise RuntimeError("Preparation join recorded an error without a cause")
            raise first_error
        if trace_error is not None:
            raise trace_error
        if len(values) != 3:
            raise RuntimeError("Preparation join authorized an incomplete aggregate")
        linear, (tone, color), boundary = (
            values[name] for name in ("linear", "tone", "boundary")
        )
        if (boundary.fl, boundary.aw, boundary.gamma) != (tone.fl, tone.aw, tone.gamma):
            raise ValueError("Boundary geometry belongs to a different appearance context")
        prepared = PreparedGrade(linear, tone, settings.space, color, boundary, False)
        return prepared

    def close(self):
        """Fence new work and retire all pool writers before releasing caches."""
        with self._lock:
            self._closed = True
        self._executor.shutdown(wait=True)
        with self._cache_lock:
            self._boundary_cache.clear()
