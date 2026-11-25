"""Concurrent, host-free preparation of complete Linear, Tone and Color Grades."""

# pg-book: technical-report/en#next-policy.preparation-join

import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace
import hashlib
import json
import threading
import time

from ...kernel.boundary import RESOURCE_SCHEMA, prepare_boundary
from ...kernel.color_prepare import prepare_color
from ...kernel.color_resolution import COLOR_RESOLUTION_SCHEMA
from ...kernel.prepare import (
    GAMMA,
    PreparedGrade,
    prepare_linear,
    prepare_tone,
    viewing,
)
from ...kernel.settings import Settings
from ...kernel.stage2_parameters import prepare_parameters


PREPARATION_SCHEMA = 2


def preparation_signature(settings: Settings) -> str:
    """Identify the complete immutable numerical input."""
    if not isinstance(settings, Settings):
        raise TypeError("Grade preparation requires frozen Settings")
    encoded = json.dumps(
        (PREPARATION_SCHEMA, COLOR_RESOLUTION_SCHEMA, RESOURCE_SCHEMA, asdict(settings)),
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
        color = prepare_color(settings.color, tone, full_fields=True)
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
        started = time.perf_counter()
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
        first_error = None
        trace_error = None

        async def receive(name, child):
            nonlocal first_error, trace_error
            component, value, error, child_started, child_finished = await child
            if component != name:
                raise RuntimeError("Preparation receipt has the wrong component")
            if error is not None and first_error is None:
                first_error = error
            try:
                self._trace(signature, name, child_started, child_finished)
            except Exception as error:
                if trace_error is None:
                    trace_error = error
            return value

        group = asyncio.gather(
            *(receive(name, child) for (name, _), child in zip(components, children)),
            return_exceptions=True,
        )
        try:
            results = await asyncio.shield(group)
        except asyncio.CancelledError:
            # Cancellation withdraws the caller, but cannot claim a running
            # executor function has stopped. Keep our physical retirement fence.
            await asyncio.shield(group)
            raise
        for result in results:
            if isinstance(result, BaseException):
                raise result

        if first_error is not None:
            self._trace(signature, "join", started, time.perf_counter())
            raise first_error
        if trace_error is not None:
            raise trace_error
        linear, (tone, color), boundary = results
        if (boundary.fl, boundary.aw, boundary.gamma) != (tone.fl, tone.aw, tone.gamma):
            raise ValueError("Boundary geometry belongs to a different appearance context")
        prepared = PreparedGrade(linear, tone, settings.space, color, boundary, True)
        # The small atlas assembly belongs to the complete snapshot's timing.
        # Shield its worker just as the parallel children: cancellation must
        # not release a scheduler slot before physical preparation retires.
        packing = loop.run_in_executor(self._executor, prepare_parameters, prepared)
        try:
            parameters = await asyncio.shield(packing)
        except asyncio.CancelledError:
            await asyncio.shield(packing)
            raise
        self._trace(signature, "join", started, time.perf_counter())
        return replace(prepared, parameters=parameters)

    def close(self):
        """Fence new work and retire all pool writers before releasing caches."""
        with self._lock:
            self._closed = True
        self._executor.shutdown(wait=True)
        with self._cache_lock:
            self._boundary_cache.clear()
