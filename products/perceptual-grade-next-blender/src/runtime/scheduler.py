"""Central host-thread scheduling for Grade, plots, Bake, and recovery."""

from dataclasses import dataclass
import logging
import threading
import time
from typing import Optional

from ..policy.scheduler import (
    Event, WorkPriority, admitted, is_task_kind, may_preempt, new, precedes,
    rank, retry_delay_ms, step,
)


_IDLE_INTERVAL = 0.008
_CORRECTNESS_KINDS = ("render", "lifecycle")
_LOG = logging.getLogger(__name__)


@dataclass
class _Task:
    key: object
    kind: str
    advance: object
    ready: object
    on_pause: object
    on_error: object
    editor: object
    prerequisites: tuple
    pause_group: object
    serial: int
    due: float
    attempts: int = 0
    retry_at: Optional[float] = None
    promotion_satisfied: object = None


class WorkScheduler:
    """Choose one host-thread work unit while features retain publication authority."""

    def __init__(self, *, clock=time.monotonic, on_wake=None):
        self._clock = clock
        self._on_wake = on_wake
        self._tasks = {}
        self._serial = 0
        self._state = new()
        self._foreground = None
        self._group_owners = {}
        self._group_last = {}
        self._running = None
        self._selecting = False

    @property
    def phase(self):
        return self._state.phase

    @property
    def active(self):
        return None if self._running is None else self._running.key

    def set_phase(self, phase):
        if phase not in {"ready", "starting", "recovering", "changing", "closed"}:
            raise ValueError("Unknown scheduler phase")
        self._state, _effects = step(self._state, Event(phase))
        self._wake()

    def focus(self, editor):
        self._foreground = editor

    def submit(self, key, kind, advance, *, ready=None, on_pause=None,
               on_error=None, editor=None, prerequisites=(), pause_group=None,
               promotion_satisfied=None):
        if not is_task_kind(kind):
            raise ValueError("Unknown scheduler task kind")
        if self.phase == "closed":
            raise RuntimeError("Scheduler is closed")
        if not callable(advance):
            raise TypeError("Scheduler task must be callable")
        self._serial += 1
        task = _Task(key, kind, advance, ready, on_pause, on_error, editor,
                     tuple(prerequisites), pause_group, self._serial, self._clock(),
                     promotion_satisfied=promotion_satisfied)
        previous = self._tasks.get(key)
        self._tasks[key] = task
        if previous is not None:
            self._pause(previous)
            current = self._tasks.get(key)
            if current is not task:
                return None if current is None else current.serial
        self._wake()
        return task.serial

    def withdraw(self, key):
        task = self._tasks.pop(key, None)
        if task is not None:
            self._pause(task)
            if self._group_last.get(task.pause_group) == key:
                self._group_last.pop(task.pause_group, None)
        return task is not None

    def discard_ordinary(self):
        """Withdraw work whose demand will be replaced after lifecycle recovery."""
        for key, task in tuple(self._tasks.items()):
            if task.kind not in _CORRECTNESS_KINDS and self._tasks.get(key) is task:
                self.withdraw(key)

    def wake(self, key):
        task = self._tasks.get(key)
        if task is not None:
            now = self._clock()
            task.due = now if task.retry_at is None else max(now, task.retry_at)
            self._wake()

    def _wake(self):
        if self._on_wake is not None:
            try:
                self._on_wake()
            except Exception:
                _LOG.exception("Could not wake work scheduler")

    def has(self, key):
        return key in self._tasks

    def has_work(self):
        return bool(self._tasks)

    def has_kind(self, kind):
        """Return whether an admitted or queued task has this work class."""
        if not is_task_kind(kind):
            raise ValueError("Unknown scheduler task kind")
        return any(task.kind == kind for task in self._tasks.values())

    def pending(self):
        return tuple(self._tasks)

    def is_promoted(self, key):
        """Whether a plot currently promotes this prerequisite key."""
        promoted = self._plot_prerequisites(tuple(self._tasks.values()))
        return key in promoted

    def _release_group(self, task):
        group = task.pause_group
        if group is not None and self._group_owners.get(group) is task:
            del self._group_owners[group]
            return True
        return False

    def _pause(self, task):
        if self._release_group(task) and task.on_pause is not None:
            try:
                task.on_pause()
            except Exception as error:
                self._report_failure(task, error)

    def _report_failure(self, task, error):
        if task.on_error is None:
            _LOG.error("Scheduled %s work failed", task.kind, exc_info=error)
            return
        try:
            task.on_error(error)
        except Exception:
            _LOG.exception("Could not report failure of scheduled %s work", task.kind)

    def _backoff(self, task, error):
        if self._tasks.get(task.key) is task:
            task.attempts += 1
            task.retry_at = self._clock() + retry_delay_ms(task.attempts) / 1000.0
            task.due = task.retry_at
            self._report_failure(task, error)

    def _priority(self, task, promoted):
        plot = promoted.get(task.key)
        if task.kind == "consistency" and plot is not None:
            return WorkPriority(task.kind, plot.serial, plot.foreground, True)
        foreground = task.editor is not None and task.editor == self._foreground
        return WorkPriority(task.kind, task.serial, foreground)

    def _plot_prerequisites(self, tasks):
        anchor = None
        pending = ()
        for task in tasks:
            if task.kind != "plot":
                continue
            dependencies = tuple(key for key in task.prerequisites if key in self._tasks)
            if not dependencies:
                continue
            priority = self._priority(task, {})
            if anchor is None or precedes(priority, anchor):
                anchor, pending = priority, dependencies

        promoted = {}
        pending = list(pending)
        while pending:
            key = pending.pop()
            if key in promoted:
                continue
            task = self._tasks.get(key)
            if task is not None:
                if self._promotion_satisfied(task):
                    continue
                promoted[key] = anchor
                pending.extend(task.prerequisites)
        return promoted

    def _promotion_satisfied(self, task):
        if task.promotion_satisfied is None:
            return False
        try:
            return bool(task.promotion_satisfied())
        except Exception as error:
            self._backoff(task, error)
            return False

    def _runnable(self, task, now):
        if task.due > now:
            return False
        if any(key in self._tasks for key in task.prerequisites):
            return False
        if task.ready is None:
            return True
        try:
            return bool(task.ready())
        except Exception as error:
            self._backoff(task, error)
            return False

    def _choice(self, now):
        tasks = tuple(task for task in self._tasks.values() if admitted(task.kind, self.phase))
        promoted = self._plot_prerequisites(tasks)
        selected = None
        best = None
        for task in tasks:
            if self._tasks.get(task.key) is not task or not self._runnable(task, now):
                continue
            priority = self._priority(task, promoted)
            owner = self._group_owners.get(task.pause_group)
            if owner is not None and owner is not task:
                if not self._can_pause(task, owner, priority,
                                       self._priority(owner, promoted)):
                    continue
            if best is None or self._prefer_group_turn(task, selected, priority, best):
                selected, best = task, priority
        return selected, best, promoted

    def _same_priority_class(self, left, right):
        return rank(left.kind, left.promoted) == rank(right.kind, right.promoted)

    def _can_pause(self, candidate, owner, candidate_priority, owner_priority):
        if may_preempt(candidate_priority, owner_priority):
            return True
        group = candidate.pause_group
        return (
            group is not None
            and group == owner.pause_group
            and candidate.kind == owner.kind == "consistency"
            and self._same_priority_class(candidate_priority, owner_priority)
            and candidate_priority.promoted == owner_priority.promoted
            and candidate_priority.foreground == owner_priority.foreground
            and self._group_last.get(group) == owner.key
        )

    def _prefer_group_turn(self, candidate, incumbent, candidate_priority,
                           incumbent_priority):
        if precedes(candidate_priority, incumbent_priority):
            return True
        if precedes(incumbent_priority, candidate_priority):
            return False
        if (candidate.pause_group is None
                or candidate.pause_group != incumbent.pause_group
                or candidate_priority.kind != incumbent_priority.kind
                or candidate_priority.promoted != incumbent_priority.promoted
                or candidate_priority.foreground != incumbent_priority.foreground):
            return False
        last = self._group_last.get(candidate.pause_group)
        if candidate.key != last and incumbent.key == last:
            return True
        if candidate.key == last and incumbent.key != last:
            return False
        return False

    def _admission_current(self, task):
        return self._tasks.get(task.key) is task and admitted(task.kind, self.phase)

    def _settle_phase(self, task, delay):
        if self._tasks.get(task.key) is not task:
            return
        if delay is None:
            self._release_group(task)
            del self._tasks[task.key]
        else:
            task.retry_at = None
            task.due = self._clock() + max(0.0, float(delay))

    def dispatch_render(self, key) -> bool:
        """Run a submitted render-preflight phase synchronously on the host thread.

        Return whether the preflight entered its callback. The caller owns
        failure delivery and cleanup when the dispatch is denied or raises.
        """
        if (threading.current_thread() is not threading.main_thread()
                or self._running is not None or self._selecting):
            return False
        task = self._tasks.get(key)
        if task is None or task.kind != "render" or not admitted(task.kind, self.phase):
            return False
        self._running = task
        try:
            if any(dependency in self._tasks for dependency in task.prerequisites):
                return False
            if task.ready is not None and not task.ready():
                return False
            if not self._admission_current(task):
                return False
            capture = self._group_owners.get("capture")
            if (capture is not None and capture is not task
                    and may_preempt(self._priority(task, {}), self._priority(capture, {}))):
                self._pause(capture)
            if not self._admission_current(task):
                return False
            self._settle_phase(task, task.advance())
            return True
        except Exception:
            self._settle_phase(task, None)
            raise
        finally:
            self._running = None

    def advance(self):
        """Run one bounded task phase and return the next timer interval."""
        if self._running is not None or self._selecting:
            return _IDLE_INTERVAL
        now = self._clock()
        self._selecting = True
        try:
            task = self._select_after_preemption(now)
        finally:
            self._selecting = False
        if task is None:
            return self._next_delay(now)

        if self._admission_current(task):
            self._running = task
            if task.pause_group is not None:
                self._group_owners[task.pause_group] = task
            try:
                self._settle_phase(task, task.advance())
            except Exception as error:
                self._pause(task)
                self._backoff(task, error)
            finally:
                if task.pause_group is not None:
                    self._group_last[task.pause_group] = task.key
                self._running = None
        return self._next_delay(self._clock())

    def _select_after_preemption(self, now):
        while True:
            task, priority, promoted = self._choice(now)
            if task is None:
                return None
            owners = (tuple(self._group_owners.values())
                      if task.kind in _CORRECTNESS_KINDS else
                      (self._group_owners.get(task.pause_group),))
            paused_owner = False
            for owner in owners:
                if (owner is not None and owner is not task
                        and self._can_pause(
                            task, owner, priority, self._priority(owner, promoted))):
                    self._pause(owner)
                    paused_owner = True
                    break
            if paused_owner:
                # A cancellation callback can enqueue retirement or recovery
                # work with a higher class. Re-select before dispatching more.
                continue
            return task

    def _next_delay(self, now):
        due = [task.due for task in self._tasks.values() if admitted(task.kind, self.phase)]
        return None if not due else max(_IDLE_INTERVAL, min(due) - now)

    def close(self):
        self.set_phase("closed")
        self._tasks.clear()
        self._group_owners.clear()
        self._group_last.clear()
