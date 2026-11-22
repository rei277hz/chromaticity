"""Async orchestration of bounded, latest-only value preparation."""

# pg-book: technical-report/en#next-policy.preparation

import asyncio
from collections import deque
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import dataclass
import json
import threading
from typing import Optional

from ..policy import preparation as preparation_policy


@dataclass(frozen=True)
class _Input:
    signature: str
    payload: object
    lane: str
    progressive: bool
    playback_session: Optional[int] = None

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
    playback_session: Optional[int] = None


@dataclass(frozen=True)
class _WorkResult:
    """Correlate a receipt with the request that supplied its prepared value."""

    job_key: tuple[str, str, bool]
    prepared: object
    error: Optional[Exception]
    playback_session: Optional[int]


@dataclass
class _Lane:
    prepare: object
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


class PreparationCoordinatorError(RuntimeError):
    """The coordinator can no longer accept or publish preparation work."""

    def __init__(self, cause):
        super().__init__(f"Preparation coordinator failed ({type(cause).__name__}): {cause}")
        self.__cause__ = cause


class PreparationRuntime:
    """Own scheduler state on an asyncio loop; workers receive opaque payloads.

    ``request`` and ``collect`` never wait for preparation. ``wait`` is the
    synchronous host bridge to ``wait_current``; neither waits for host-side
    installation. Source keys are opaque host-owned identities, never RNA.
    ``on_event(name, **fields)`` is an optional diagnostic observer. It receives
    plain values on the calling thread and cannot affect preparation outcomes.
    """

    def __init__(self, *, default_lane="default", on_event=None):
        if not isinstance(default_lane, str) or not default_lane:
            raise ValueError("Default lane name must be nonempty")
        self.default_lane = default_lane
        self.on_event = on_event
        self._lanes = {}
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
        self._failure_acknowledged = False
        self._shutdown_task = None
        self._ready = threading.Event()
        self._thread = threading.Thread(
            target=self._run, name="async-runtime-coordinator", daemon=True
        )
        self._thread.start()
        if not self._ready.wait(10):
            raise RuntimeError("Preparation coordinator did not start")
        self._raise_failure()

    @property
    def prepare(self):
        lane = self._lanes.get(self.default_lane)
        if lane is None:
            raise RuntimeError("The default lane is not registered")
        return lane.prepare

    @prepare.setter
    def prepare(self, value):
        lane = self._lanes.get(self.default_lane)
        if lane is None:
            raise RuntimeError("The default lane is not registered")
        lane.prepare = value

    def _run(self):
        try:
            asyncio.run(self._serve())
        except BaseException as error:
            self._fail(error)
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
            raise PreparationCoordinatorError(self._failure)

    def _observe(self, event, **fields):
        observer = self.on_event
        if observer is not None:
            try:
                observer(event, **fields)
            except Exception:
                # Diagnostics must not turn successful work into a Grade error.
                pass

    def register_async_lane(self, name, prepare_async):
        """Register an aggregate coroutine executed on the coordinator loop.

        The coroutine owns any worker fan-out it needs and must not call Blender
        APIs. This lane is final-only; host-polled work uses register_polled_lane.
        """
        if not isinstance(name, str) or not name:
            raise ValueError("Preparation lane name must be nonempty")
        if not callable(prepare_async):
            raise TypeError("Async preparation lane must be callable")
        with self._lock:
            self._raise_failure()
            if self.closed:
                raise RuntimeError("Preparation runtime is closed")
            if name in self._lanes:
                raise ValueError(f"Preparation lane already exists: {name}")
            self._lanes[name] = _Lane(prepare_async, False)

    def register_polled_lane(self, name, owner, *, progressive=False):
        """Register a lane whose transport advances only on the host thread.

        ``owner.create_job(payload, progressive)`` returns an
        object with ``advance()`` and ``close()`` methods. ``advance`` returns
        ``None`` or a (quality, prepared) receipt. All host lanes share one
        physical slot. A subprocess job's ``cancel`` withdraws interest while
        ``advance`` continues polling until physical retirement.
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
            self._lanes[name] = _Lane(None, bool(progressive), owner)

    @property
    def failure(self) -> Optional[BaseException]:
        with self._lock:
            return self._failure

    @property
    def pending_failure(self) -> Optional[BaseException]:
        with self._lock:
            return None if self._failure_acknowledged else self._failure

    def acknowledge_failure(self):
        """Finish host delivery after an admitted fail-closed update."""
        with self._lock:
            if self._failure is not None:
                self._failure_acknowledged = True

    @property
    def pending(self):
        with self._lock:
            pending = (bool(self._pending or self._publications)
                       if self._failure is None else not self._failure_acknowledged)
            with self._host_lock:
                return pending or bool(self._host_queue or self._host_active)

    def request(self, source, signature, payload, *, lane=None,
                progressive=None, playback_session: Optional[int] = None):
        """Replace this source's newest snapshot without queuing history.

        A playback session correlates delivery and leaves work identity unchanged.
        """
        if not isinstance(signature, str):
            raise TypeError("Preparation signature must be a string")
        if lane is None:
            lane = self.default_lane
        with self._lock:
            self._raise_failure()
            if self.closed:
                raise RuntimeError("Preparation runtime is closed")
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
            if self.on_event is not None:
                previous = subscription.latest
                self._observe(
                    "preparation_request", source_id=id(source),
                    subscription_id=id(subscription), signature=signature,
                    lane=lane, progressive=bool(progressive),
                    previous_signature=None if previous is None else previous.signature,
                    replaced_unconsumed=subscription.dirty,
                )
            mailbox = self._publications.get(subscription)
            if mailbox is not None:
                mailbox.pop("error", None)
                if not mailbox:
                    self._publications.pop(subscription, None)
            subscription.latest = _Input(
                signature, payload, lane, bool(progressive), playback_session
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
            if self.on_event is not None:
                self._observe(
                    "preparation_forget", source_id=id(source),
                    subscription_id=id(subscription),
                    signature=(None if subscription.latest is None
                               else subscription.latest.signature),
                )
            self._publications.pop(subscription, None)
            subscription.latest = None
            subscription.dirty = True
            self._pending.discard(subscription)
            self._discard_unwanted_host_work_locked()
            if not self.closed and self._failure is None:
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
                error=RuntimeError("Queued preparation is no longer demanded"),
            )

    def _schedule_locked(self, source):
        if not source.wake_pending:
            source.wake_pending = True
            self.loop.call_soon_threadsafe(self._wake, source)

    def _wake(self, source):
        try:
            with self._lock:
                source.wake_pending = False
                if self._failure is not None:
                    return
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
        if self.on_event is not None:
            self._observe(
                "preparation_input_sync", source_id=id(source.key),
                subscription_id=id(source),
                signature=None if snapshot is None else snapshot.signature,
                running_request_signature=record.state.running_signature,
                desired_request_signature=record.state.desired_signature,
                prepare_request_signature=effects.prepare_signature,
            )
        self._consume_locked(source, record, effects, snapshot)
        self._settled_locked(source, record)

    def _consume_locked(self, source, record, effects, snapshot, outcome=None):
        if effects.result_signature is not None:
            lane, signature, progressive = outcome.job_key
            request_signature = _request_signature(lane, signature, progressive)
            if request_signature != effects.result_signature:
                raise RuntimeError("Preparation effect does not match its result")
            if self._sources.get(source.key) is source:
                error = outcome.error
                if effects.error is None:
                    source.last_success = outcome.job_key
                    error = None
                elif error is None:
                    error = RuntimeError(effects.error)
                self._publish_locked(source, Publication(
                    source.key, signature, outcome.prepared, error, "full", lane,
                    progressive, outcome.playback_session,
                ))
        if effects.preview_signature is not None:
            if snapshot is None or snapshot.request_signature != effects.preview_signature:
                raise RuntimeError("Preview effect has no matching frozen input")
            if self._sources.get(source.key) is source:
                self._publish_locked(source, Publication(
                    source.key, snapshot.signature, outcome, None, "preview",
                    snapshot.lane, snapshot.progressive, snapshot.playback_session,
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
            if self.on_event is not None:
                previous = slots.get("error")
                self._observe(
                    "preparation_publication", source_id=id(source.key),
                    subscription_id=id(source), signature=publication.signature,
                    lane=publication.lane, quality=publication.quality,
                    progressive=publication.progressive, error=str(publication.error),
                    replaced_signature=None if previous is None else previous.signature,
                )
            slots["error"] = publication
            return
        previous = slots.get("success")
        if (previous is not None and previous.signature == publication.signature
                and previous.lane == publication.lane and previous.quality == "full"
                and publication.quality == "preview"):
            if self.on_event is not None:
                self._observe(
                    "preparation_publication_skipped", source_id=id(source.key),
                    subscription_id=id(source), signature=publication.signature,
                    lane=publication.lane, quality=publication.quality,
                    reason="full_result_already_queued",
                )
            return
        if self.on_event is not None:
            self._observe(
                "preparation_publication", source_id=id(source.key),
                subscription_id=id(source), signature=publication.signature,
                lane=publication.lane, quality=publication.quality,
                progressive=publication.progressive, error=None,
                replaced_signature=None if previous is None else previous.signature,
                replaced_quality=None if previous is None else previous.quality,
            )
        slots["success"] = publication

    async def _publish_preview(self, snapshot, prepared):
        with self._lock:
            if self.closed or self._failure is not None:
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
        if self.on_event is not None:
            self._observe(
                "preparation_execute_start", signature=snapshot.signature,
                lane=snapshot.lane, progressive=snapshot.progressive,
                backend="host" if lane.host_owner is not None else "async",
            )
        try:
            if lane.host_owner is not None:
                prepared = await self._execute_on_host(snapshot, lane)
            else:
                if snapshot.progressive:
                    raise RuntimeError("Async preparation lanes are final-only")
                prepared = await lane.prepare(snapshot.payload)
            result = _WorkResult(job_key, prepared, None, snapshot.playback_session)
            with self._lock:
                if self._failure is None:
                    self._prepared[job_key] = prepared
            if self.on_event is not None:
                self._observe(
                    "preparation_execute_finish", signature=snapshot.signature,
                    lane=snapshot.lane, progressive=snapshot.progressive, error=None,
                )
            return result
        except BaseException as error:
            if self.on_event is not None:
                self._observe(
                    "preparation_execute_finish", signature=snapshot.signature,
                    lane=snapshot.lane, progressive=snapshot.progressive,
                    error=str(error), error_type=type(error).__name__,
                )
            if not isinstance(error, Exception):
                raise
            return _WorkResult(job_key, None, error, snapshot.playback_session)
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
            self._raise_failure()
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
        with self._lock:
            failure = self._failure
            with self._host_lock:
                if self._host_active is None and failure is None and self._host_queue:
                    self._host_active = self._host_queue.popleft()
                work = self._host_active
        if work is None:
            return False

        lane = self._lanes[work.lane]
        try:
            if failure is not None and work.job is None:
                raise PreparationCoordinatorError(failure)
            if failure is not None or work.preview_emitted:
                with self._lock:
                    still_demanded = failure is None and self._has_host_demand_locked(
                        work.snapshot.request_signature
                    )
                if not still_demanded:
                    cancel = getattr(work.job, "cancel", None)
                    if callable(cancel):
                        cancel()
                    elif failure is None:
                        raise RuntimeError("Host preparation superseded after its preview")
            if work.job is None:
                work.job = lane.host_owner.create_job(
                    work.snapshot.payload,
                    work.snapshot.progressive,
                )
            receipt = work.job.advance()
            if receipt is None:
                return True
            quality, prepared = receipt
            if quality == "preview":
                if not work.snapshot.progressive:
                    raise RuntimeError("A final-only host job emitted a preview")
                if self.failure is None:
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

        try:
            self.loop.call_soon_threadsafe(finish)
        except RuntimeError:
            if not self.loop.is_closed():
                raise

    async def _prepare(self, source, record, snapshot):
        job_key = (snapshot.lane, snapshot.signature, snapshot.progressive)
        with self._lock:
            if self._failure is not None:
                return
            prepared = self._prepared.get(job_key)
            has_prepared = job_key in self._prepared
            job = self._jobs.get(job_key)
            if not has_prepared and job is None:
                job = self.loop.create_task(self._execute(snapshot))
                self._jobs[job_key] = job
            elif self.on_event is not None:
                self._observe(
                    "preparation_reuse", source_id=id(source.key),
                    subscription_id=id(source), signature=snapshot.signature,
                    lane=snapshot.lane, progressive=snapshot.progressive,
                    kind="cache" if has_prepared else "inflight",
                )
        if has_prepared:
            outcome = _WorkResult(job_key, prepared, None, snapshot.playback_session)
        else:
            outcome = await asyncio.shield(job)

        with self._lock:
            if self._failure is not None:
                return
            if self._records.get(source) is not record:
                if self.on_event is not None:
                    self._observe(
                        "preparation_result_skipped", source_id=id(source.key),
                        subscription_id=id(source), signature=snapshot.signature,
                        lane=snapshot.lane, reason="subscription_retired",
                    )
                return
            # Admit slider updates before completion chooses its successor.
            self._sync_locked(source)
            error = outcome.error
            record.state, effects = preparation_policy.step(record.state,
                preparation_policy.Event(
                "preparation_result", snapshot.request_signature,
                None if error is None else str(error),
            ))
            if self.on_event is not None:
                self._observe(
                    "preparation_result", source_id=id(source.key),
                    subscription_id=id(source), signature=snapshot.signature,
                    lane=snapshot.lane, progressive=snapshot.progressive,
                    error=None if error is None else str(error),
                    running_request_signature=record.state.running_signature,
                    desired_request_signature=record.state.desired_signature,
                    result_request_signature=effects.result_signature,
                    prepare_request_signature=effects.prepare_signature,
                )
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
            if self._failure is not None:
                return
            self._failure = error
            self._pending.clear()
            self._publications.clear()
            self._prepared.clear()
            with self._host_lock:
                queued = tuple(self._host_queue)
                self._host_queue.clear()
            loop = getattr(self, "loop", None)
            if loop is not None and loop.is_running():
                for work in queued:
                    self._finish_host_work(work, error=PreparationCoordinatorError(error))
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
                    if self.on_event is not None:
                        self._observe(
                            "preparation_collection_skipped", source_id=id(source.key),
                            subscription_id=id(source), signature=selected.signature,
                            lane=selected.lane, quality=selected.quality,
                            reason="preview_no_longer_requested",
                        )
                    continue
                if selected is not None:
                    if self.on_event is not None:
                        self._observe(
                            "preparation_collection", source_id=id(source.key),
                            subscription_id=id(source), signature=selected.signature,
                            lane=selected.lane, quality=selected.quality,
                            progressive=selected.progressive,
                            error=None if selected.error is None else str(selected.error),
                        )
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
        """Join current preparations; never await host-side installation."""
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
                if self._failure is None:
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
            # A completed task can remain registered until its done callback
            # runs; gathering it again is already complete and would not yield.
            await asyncio.sleep(0)
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
            failures = []
            if not self._thread.is_alive():
                for lane in self._lanes.values():
                    if lane.host_owner is not None:
                        try:
                            if threading.current_thread() is not threading.main_thread():
                                raise RuntimeError("Host preparation must close on the main thread")
                            lane.host_owner.close()
                        except Exception as error:
                            failures.append(error)
                        else:
                            lane.host_owner = None
                if failures:
                    raise ExceptionGroup("Preparation runtime cleanup failed", failures)
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
            except Exception as error:
                failures.append(error)
            finally:
                for lane in self._lanes.values():
                    if lane.host_owner is not None:
                        try:
                            lane.host_owner.close()
                        except Exception as error:
                            failures.append(error)
                        else:
                            lane.host_owner = None
                try:
                    self.loop.call_soon_threadsafe(self._stop.set)
                    self._thread.join()
                except Exception as error:
                    failures.append(error)
            if failures:
                raise ExceptionGroup("Preparation runtime cleanup failed", failures)
