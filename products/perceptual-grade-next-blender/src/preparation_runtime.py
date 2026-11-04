"""Async orchestration of bounded, latest-only Grade preparation."""

import asyncio
from collections import deque
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from dataclasses import dataclass
from functools import partial
import json
import threading
from typing import Optional

from .policy import preparation as preparation_policy


@dataclass(frozen=True)
class _Input:
    signature: str
    settings: object
    working_space: str
    lane: str
    progressive: bool

    @property
    def request_signature(self):
        return _request_signature(self.lane, self.signature, self.progressive)


def _request_signature(lane, signature, progressive):
    return json.dumps((lane, bool(progressive), signature), separators=(",", ":"))


def _job_key(request_signature):
    lane, progressive, signature = json.loads(request_signature)
    return lane, signature, progressive


@dataclass(frozen=True)
class Publication:
    source: object
    signature: str
    prepared: object
    error: Optional[BaseException]
    quality: str
    lane: str
    progressive: bool


@dataclass
class _Lane:
    prepare: object
    executor: Optional[ThreadPoolExecutor]
    progressive: bool
    host_owner: Optional[object] = None


@dataclass
class _HostWork:
    lane: str
    snapshot: _Input
    future: asyncio.Future
    on_preview: object
    job: Optional[object] = None
    preview_emitted: bool = False


@dataclass(eq=False)
class _Source:
    """One subscription incarnation and its replaceable input mailbox."""

    key: object
    latest: Optional[_Input] = None
    dirty: bool = False
    wake_pending: bool = False
    last_success: Optional[tuple[str, str, bool]] = None


@dataclass
class _Record:
    state: object
    changed: asyncio.Event


class PreparationRuntime:
    """Own scheduler state on an asyncio loop; workers receive frozen inputs.

    ``request`` and ``collect`` never wait for preparation. ``wait`` is the
    synchronous render bridge to ``wait_current``; neither waits for Blender
    graph installation. Source keys are opaque host-owned identities, never RNA.
    """

    def __init__(self, prepare, *, workers=1):
        self.executor = ThreadPoolExecutor(max_workers=workers,
                                           thread_name_prefix="perceptual-grade-linear")
        self._lanes = {"linear": _Lane(prepare, self.executor, False)}
        self._host_lock = threading.Lock()
        self._host_queue = deque()
        self._host_active = None
        self.closed = False
        self._lock = threading.RLock()
        self._close_lock = threading.Lock()
        self._sources = {}
        self._pending = set()
        # One mailbox per source incarnation. Keep the newest successful result
        # and at most one current failure; delayed host timers never drain history.
        self._publications = {}
        self._records = {}
        self._jobs = {}
        self._prepared = {}
        self._tasks = set()
        self._failure = None
        self._shutdown_task = None
        self._ready = threading.Event()
        self._thread = threading.Thread(
            target=self._run, name="perceptual-grade-asyncio", daemon=True
        )
        self._thread.start()
        if not self._ready.wait(10):
            raise RuntimeError("Grade preparation coordinator did not start")
        self._raise_failure()

    @property
    def prepare(self):
        return self._lanes["linear"].prepare

    @prepare.setter
    def prepare(self, value):
        self._lanes["linear"].prepare = value

    def _run(self):
        try:
            asyncio.run(self._serve())
        except BaseException as error:
            with self._lock:
                self._failure = error
        finally:
            with self._lock:
                self.closed = True
            self._ready.set()

    async def _serve(self):
        self.loop = asyncio.get_running_loop()
        self._stop = asyncio.Event()
        self._ready.set()
        await self._stop.wait()

    def _raise_failure(self):
        if self._failure is not None:
            raise RuntimeError("Grade preparation coordinator failed") from self._failure

    def register_lane(self, name, prepare, *, workers=1, progressive=False):
        """Add an independent worker pool under the existing asyncio coordinator."""
        if not isinstance(name, str) or not name:
            raise ValueError("Preparation lane name must be nonempty")
        with self._lock:
            self._raise_failure()
            if self.closed:
                raise RuntimeError("Grade preparation runtime is closed")
            if name in self._lanes:
                raise ValueError(f"Preparation lane already exists: {name}")
            executor = ThreadPoolExecutor(
                max_workers=workers, thread_name_prefix=f"perceptual-grade-{name}"
            )
            self._lanes[name] = _Lane(prepare, executor, bool(progressive))

    def register_main_thread_lane(self, name, owner, *, progressive=False):
        """Register a cooperative lane whose owner advances only on the host thread.

        ``owner.create_job(settings, working_space, progressive)`` returns an
        object with ``advance()`` and ``close()`` methods. ``advance`` returns
        ``None`` or a (quality, prepared) receipt. All host lanes share one
        physical slot and therefore never overlap GPU resource use.
        """
        if not isinstance(name, str) or not name:
            raise ValueError("Preparation lane name must be nonempty")
        if not callable(getattr(owner, "create_job", None)):
            raise TypeError("Main-thread lane owner must create jobs")
        with self._lock:
            self._raise_failure()
            if self.closed:
                raise RuntimeError("Preparation runtime is closed")
            if name in self._lanes:
                raise ValueError(f"Preparation lane already exists: {name}")
            self._lanes[name] = _Lane(None, None, bool(progressive), owner)

    @property
    def pending(self):
        with self._lock:
            pending = bool(self._pending or self._publications or self._failure)
        with self._host_lock:
            return pending or bool(self._host_queue or self._host_active)

    def request(self, source, signature, settings, working_space, *, lane="linear",
                progressive=None):
        """Replace this source's one newest snapshot, without queuing history."""
        if not isinstance(signature, str):
            raise TypeError("Grade preparation signature must be a string")
        with self._lock:
            self._raise_failure()
            if self.closed:
                raise RuntimeError("Grade preparation runtime is closed")
            if lane not in self._lanes:
                raise ValueError(f"Unknown preparation lane: {lane}")
            lane_progressive = self._lanes[lane].progressive
            if progressive is None:
                progressive = lane_progressive
            if progressive and not lane_progressive:
                raise ValueError(f"Preparation lane does not support previews: {lane}")
            subscription = self._sources.get(source)
            if subscription is None:
                subscription = _Source(source)
                self._sources[source] = subscription
            mailbox = self._publications.get(subscription)
            if mailbox is not None:
                mailbox.pop("error", None)
                if not mailbox:
                    self._publications.pop(subscription, None)
            subscription.latest = _Input(
                signature, settings, working_space, lane, bool(progressive)
            )
            subscription.dirty = True
            self._pending.add(subscription)
            self._discard_unwanted_host_work_locked()
            self._schedule_locked(subscription)

    def forget(self, source):
        """Withdraw demand without cancelling an executing physical worker."""
        with self._lock:
            subscription = self._sources.pop(source, None)
            if subscription is None:
                return
            self._publications.pop(subscription, None)
            subscription.latest = None
            subscription.dirty = True
            self._pending.discard(subscription)
            self._discard_unwanted_host_work_locked()
            if not self.closed:
                self._schedule_locked(subscription)

    def _has_host_demand_locked(self, signature):
        return any(source.latest is not None
                   and source.latest.request_signature == signature
                   for source in self._sources.values())

    def _discard_unwanted_host_work_locked(self):
        with self._host_lock:
            retained = deque()
            discarded = []
            while self._host_queue:
                work = self._host_queue.popleft()
                if self._has_host_demand_locked(work.snapshot.request_signature):
                    retained.append(work)
                else:
                    discarded.append(work)
            self._host_queue = retained
        for work in discarded:
            self._jobs.pop(_job_key(work.snapshot.request_signature), None)
            self._finish_host_work(
                work,
                error=RuntimeError("Queued host preparation is no longer demanded"),
            )

    def _schedule_locked(self, source):
        if not source.wake_pending:
            source.wake_pending = True
            self.loop.call_soon_threadsafe(self._wake, source)

    def _wake(self, source):
        try:
            with self._lock:
                source.wake_pending = False
                self._sync_locked(source)
                self._prune_locked()
        except Exception as error:
            self._fail(error)

    def _sync_locked(self, source):
        if not source.dirty:
            return
        source.dirty = False
        snapshot = source.latest
        record = self._records.get(source)
        if record is None:
            if snapshot is None:
                return
            record = _Record(preparation_policy.new(), asyncio.Event())
            self._records[source] = record
        event = preparation_policy.Event(
            "request", None if snapshot is None else snapshot.request_signature
        )
        record.state, effects = preparation_policy.step(record.state, event)
        self._consume_locked(source, record, effects, snapshot)
        self._settled_locked(source, record)

    def _consume_locked(self, source, record, effects, snapshot, outcome=None):
        if effects.result_signature is not None:
            lane, signature, progressive, prepared, error = outcome
            request_signature = _request_signature(lane, signature, progressive)
            if request_signature != effects.result_signature:
                raise RuntimeError("Preparation effect does not match its result")
            if self._sources.get(source.key) is source:
                if effects.error is None:
                    source.last_success = (lane, signature, progressive)
                    error = None
                elif error is None:
                    error = RuntimeError(effects.error)
                self._publish_locked(source, Publication(
                    source.key, signature, prepared, error, "full", lane, progressive
                ))
        if effects.preview_signature is not None:
            if snapshot is None or snapshot.request_signature != effects.preview_signature:
                raise RuntimeError("Preview effect has no matching frozen input")
            if self._sources.get(source.key) is source:
                self._publish_locked(source, Publication(
                    source.key, snapshot.signature, outcome, None, "preview",
                    snapshot.lane, snapshot.progressive,
                ))
        if effects.prepare_signature is not None:
            if snapshot is None or snapshot.request_signature != effects.prepare_signature:
                raise RuntimeError("Preparation effect has no matching frozen input")
            task = self.loop.create_task(self._prepare(source, record, snapshot))
            self._tasks.add(task)
            task.add_done_callback(self._task_done)

    def _emit_preview(self, snapshot, prepared):
        future = asyncio.run_coroutine_threadsafe(
            self._publish_preview(snapshot, prepared), self.loop
        )
        return future.result()

    def _publish_locked(self, source, publication):
        """Coalesce effect-authorized receipts within one subscription lifetime."""
        slots = self._publications.setdefault(source, {})
        if publication.error is not None:
            slots["error"] = publication
            return
        previous = slots.get("success")
        if (previous is not None and previous.signature == publication.signature
                and previous.lane == publication.lane and previous.quality == "full"
                and publication.quality == "preview"):
            return
        slots["success"] = publication

    async def _publish_preview(self, snapshot, prepared):
        with self._lock:
            if self.closed:
                return
            for source in tuple(self._sources.values()):
                if source.dirty:
                    self._sync_locked(source)
                record = self._records.get(source)
                if (record is None or source.latest is None or not source.latest.progressive
                        or record.state.running_signature != snapshot.request_signature):
                    continue
                record.state, effects = preparation_policy.step(record.state,
                    preparation_policy.Event(
                    "preparation_preview", snapshot.request_signature
                ))
                self._consume_locked(source, record, effects, snapshot, prepared)
                self._settled_locked(source, record)

    async def _execute(self, snapshot):
        job_key = (snapshot.lane, snapshot.signature, snapshot.progressive)
        lane = self._lanes[snapshot.lane]
        try:
            if lane.host_owner is not None:
                prepared = await self._execute_on_host(snapshot, lane)
            else:
                call = partial(lane.prepare, snapshot.settings, snapshot.working_space)
                if snapshot.progressive:
                    def call_with_preview():
                        return lane.prepare(
                            snapshot.settings, snapshot.working_space,
                            lambda preview: self._emit_preview(snapshot, preview),
                        )
                    call = call_with_preview
                prepared = await self.loop.run_in_executor(lane.executor, call)
            with self._lock:
                self._prepared[job_key] = prepared
            return prepared
        finally:
            with self._lock:
                if self._jobs.get(job_key) is asyncio.current_task():
                    del self._jobs[job_key]

    async def _execute_on_host(self, snapshot, lane):
        future = self.loop.create_future()
        work = _HostWork(
            snapshot.lane,
            snapshot,
            future,
            (lambda prepared: self._emit_preview(snapshot, prepared))
            if snapshot.progressive else None,
        )
        with self._lock:
            if self.closed:
                raise RuntimeError("Preparation runtime is closed")
            if not self._has_host_demand_locked(snapshot.request_signature):
                raise RuntimeError("Host preparation is no longer demanded")
            with self._host_lock:
                self._host_queue.append(work)
        return await future

    def pump_main_thread(self):
        """Advance one authorized host-lane step; callers must be on main thread."""
        if threading.current_thread() is not threading.main_thread():
            raise RuntimeError("Host preparation must be pumped on the main thread")
        with self._host_lock:
            if self._host_active is None and self._host_queue:
                self._host_active = self._host_queue.popleft()
            work = self._host_active
        if work is None:
            return False

        lane = self._lanes[work.lane]
        try:
            if work.preview_emitted:
                with self._lock:
                    still_demanded = self._has_host_demand_locked(
                        work.snapshot.request_signature
                    )
                if not still_demanded:
                    self._retire_host_job(work)
                    self._finish_host_work(
                        work,
                        error=RuntimeError(
                            "Host preparation superseded after its preview"
                        ),
                    )
                    return True
            if work.job is None:
                work.job = lane.host_owner.create_job(
                    work.snapshot.settings,
                    work.snapshot.working_space,
                    work.snapshot.progressive,
                )
            receipt = work.job.advance()
            if receipt is None:
                return True
            quality, prepared = receipt
            if quality == "preview":
                if not work.snapshot.progressive:
                    raise RuntimeError("A final-only host job emitted a preview")
                work.on_preview(prepared)
                work.preview_emitted = True
                return True
            if quality != "full":
                raise RuntimeError(f"Unknown host preparation quality: {quality}")
        except Exception as error:
            try:
                self._retire_host_job(work)
            except Exception as cleanup_error:
                error = ExceptionGroup(
                    "Host preparation and cleanup both failed",
                    [error, cleanup_error],
                )
            self._finish_host_work(work, error=error)
            return True

        try:
            self._retire_host_job(work)
        except Exception as error:
            self._finish_host_work(work, error=error)
            return True
        self._finish_host_work(work, prepared=prepared)
        return True

    def _retire_host_job(self, work):
        try:
            if work.job is not None:
                work.job.close()
        finally:
            work.job = None
            with self._host_lock:
                if self._host_active is work:
                    self._host_active = None

    def _finish_host_work(self, work, *, prepared=None, error=None):
        def finish():
            if work.future.done():
                return
            if error is not None:
                work.future.set_exception(error)
            else:
                work.future.set_result(prepared)

        self.loop.call_soon_threadsafe(finish)

    async def _prepare(self, source, record, snapshot):
        job_key = (snapshot.lane, snapshot.signature, snapshot.progressive)
        try:
            with self._lock:
                prepared = self._prepared.get(job_key)
                has_prepared = job_key in self._prepared
                job = self._jobs.get(job_key)
                if not has_prepared and job is None:
                    job = self.loop.create_task(self._execute(snapshot))
                    self._jobs[job_key] = job
            if not has_prepared:
                prepared = await asyncio.shield(job)
        except Exception as error:
            outcome = (snapshot.lane, snapshot.signature, snapshot.progressive, None, error)
        else:
            outcome = (snapshot.lane, snapshot.signature, snapshot.progressive, prepared, None)

        with self._lock:
            if self._records.get(source) is not record:
                return
            # Admit slider updates before completion chooses its successor.
            self._sync_locked(source)
            error = outcome[4]
            record.state, effects = preparation_policy.step(record.state,
                preparation_policy.Event(
                "preparation_result", snapshot.request_signature,
                None if error is None else str(error),
            ))
            self._consume_locked(source, record, effects, source.latest, outcome)
            self._settled_locked(source, record)
            self._prune_locked()

    def _settled_locked(self, source, record):
        state = record.state
        if state.running_signature is None and not source.dirty:
            self._pending.discard(source)
        record.changed.set()
        if state.desired_signature is None and state.running_signature is None:
            self._records.pop(source, None)

    def _task_done(self, task):
        self._tasks.discard(task)
        if not task.cancelled():
            error = task.exception()
            if error is not None:
                self._fail(error)

    def _fail(self, error):
        with self._lock:
            if self._failure is None:
                self._failure = error
            for record in self._records.values():
                record.changed.set()

    def _prune_locked(self):
        wanted = set(self._jobs)
        for source in self._sources.values():
            if source.latest is not None:
                wanted.add((source.latest.lane, source.latest.signature,
                            source.latest.progressive))
            if source.last_success is not None:
                wanted.add(source.last_success)
        for record in self._records.values():
            if record.state.running_signature is not None:
                wanted.add(_job_key(record.state.running_signature))
        for slots in self._publications.values():
            for item in slots.values():
                wanted.add((item.lane, item.signature, item.progressive))
        for signature in tuple(self._prepared):
            if signature not in wanted:
                del self._prepared[signature]

    def collect(self):
        with self._lock:
            self._raise_failure()
            results = []
            for source, slots in tuple(self._publications.items()):
                if self._sources.get(source.key) is not source:
                    continue
                # A current failure revokes output directly, without installing
                # the successful result that preceded it in the same host turn.
                selected = slots.get("error") or slots.get("success")
                if (selected is not None and selected.quality == "preview"
                        and (source.latest is None or not source.latest.progressive)):
                    continue
                if selected is not None:
                    results.append(selected)
            self._publications.clear()
            return tuple(results)

    async def _wait_source(self, source):
        while True:
            with self._lock:
                self._raise_failure()
                self._sync_locked(source)
                record = self._records.get(source)
                if record is None or record.state.running_signature is None:
                    return
                record.changed.clear()
            await record.changed.wait()

    async def wait_current(self, sources=None):
        """Join current preparations; never await a Blender-side installation."""
        if asyncio.get_running_loop() is not self.loop:
            raise RuntimeError("Preparation barrier requires its coordinator loop")
        with self._lock:
            self._raise_failure()
            selected = tuple(self._sources.values()) if sources is None else tuple(
                self._sources[key] for key in dict.fromkeys(sources)
                if key in self._sources
            )
        await asyncio.gather(*(self._wait_source(source) for source in selected))
        return self.collect()

    def wait(self, sources=None):
        if threading.current_thread() is self._thread:
            raise RuntimeError("The coordinator cannot block on its own preparation")
        with self._lock:
            self._raise_failure()
            if self.closed:
                return ()
            if threading.current_thread() is not threading.main_thread():
                selected = tuple(self._sources.values()) if sources is None else tuple(
                    self._sources[key] for key in dict.fromkeys(sources)
                    if key in self._sources
                )
                if any(source.latest is not None
                       and self._lanes[source.latest.lane].host_owner is not None
                       for source in selected):
                    raise RuntimeError(
                        "Main-thread preparation cannot be drained from a worker"
                    )
            future = asyncio.run_coroutine_threadsafe(self.wait_current(sources), self.loop)
        if threading.current_thread() is threading.main_thread():
            while not future.done():
                self.pump_main_thread()
                try:
                    future.result(timeout=0.01)
                except FutureTimeout:
                    pass
        return future.result()

    async def aclose(self):
        """Fence admission and await physical retirement, without cancellation."""
        if asyncio.get_running_loop() is not self.loop:
            raise RuntimeError("Preparation shutdown requires its coordinator loop")
        if self._shutdown_task is None:
            self._shutdown_task = self.loop.create_task(self._shutdown())
        await asyncio.shield(self._shutdown_task)

    async def _shutdown(self):
        with self._lock:
            self.closed = True
            sources = set(self._sources.values()) | set(self._records)
            self._sources.clear()
            self._pending.clear()
            self._publications.clear()
            for source in sources:
                source.latest = None
                source.dirty = True
                self._sync_locked(source)
        with self._host_lock:
            queued = tuple(self._host_queue)
            self._host_queue.clear()
        for work in queued:
            if not work.future.done():
                work.future.set_exception(
                    RuntimeError("Preparation runtime is shutting down")
                )
        while self._tasks:
            await asyncio.gather(*tuple(self._tasks), return_exceptions=True)
        if self._jobs:
            await asyncio.gather(*tuple(self._jobs.values()), return_exceptions=True)
        with self._lock:
            self._records.clear()
            self._prepared.clear()
            self._jobs.clear()

    def close(self):
        if threading.current_thread() is self._thread:
            raise RuntimeError("The coordinator cannot join its own thread")
        with self._close_lock:
            if not self._thread.is_alive():
                for lane in self._lanes.values():
                    if lane.host_owner is not None:
                        if threading.current_thread() is not threading.main_thread():
                            raise RuntimeError("Host preparation must close on the main thread")
                        lane.host_owner.close()
                        lane.host_owner = None
                    if lane.executor is not None:
                        lane.executor.shutdown(wait=True)
                return
            if (threading.current_thread() is not threading.main_thread()
                    and any(lane.host_owner is not None for lane in self._lanes.values())):
                raise RuntimeError("Host preparation must close on the main thread")
            with self._lock:
                self.closed = True
                future = asyncio.run_coroutine_threadsafe(self.aclose(), self.loop)
            try:
                if any(lane.host_owner is not None for lane in self._lanes.values()):
                    if threading.current_thread() is not threading.main_thread():
                        raise RuntimeError("Host preparation must close on the main thread")
                    while not future.done():
                        self.pump_main_thread()
                        try:
                            future.result(timeout=0.01)
                        except FutureTimeout:
                            pass
                future.result()
            finally:
                for lane in self._lanes.values():
                    if lane.host_owner is not None:
                        lane.host_owner.close()
                        lane.host_owner = None
                self.loop.call_soon_threadsafe(self._stop.set)
                self._thread.join()
                for lane in self._lanes.values():
                    if lane.executor is not None:
                        lane.executor.shutdown(wait=True)
