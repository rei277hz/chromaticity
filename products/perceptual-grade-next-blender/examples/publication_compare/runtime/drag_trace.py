"""Bounded, host-free JSONL recording for opt-in drag diagnostics."""

from datetime import datetime, timezone
import json
import math
from pathlib import Path
from queue import Empty, Full, Queue
import threading
import time
from typing import Optional
from uuid import uuid4


def _snapshot(value):
    """Copy plain data only; the writer must never retain or inspect RNA."""
    kind = type(value)
    if value is None or kind in (str, bool, int):
        return value
    if kind is float:
        if not math.isfinite(value):
            raise ValueError("Trace numbers must be finite")
        return value
    if kind in (tuple, list):
        return [_snapshot(item) for item in value]
    if kind is dict:
        if any(type(key) is not str for key in value):
            raise TypeError("Trace field keys must be strings")
        return {key: _snapshot(item) for key, item in value.items()}
    raise TypeError("Trace fields must contain plain JSON data")


def _error_text(error):
    try:
        return type(error).__name__ + ": " + str(error)
    except Exception:
        return "Trace recording failed"


class Recorder:
    """Snapshot events quickly and serialize them on one background writer.

    ``emit`` never waits for queue capacity or disk IO. Its small lock orders
    sequence allocation and queue insertion across threads. Only ordinary
    Python data may be supplied; invalid payloads disable this recorder rather
    than escaping into Grade callbacks. ``close`` drains accepted events and
    returns a diagnostic error, if any. Callers remain responsible for showing
    that error and the absolute ``path`` to the user.
    """

    def __init__(self, directory=None, metadata=None, capacity=65536, flush_interval=0.25):
        if type(capacity) is not int or capacity < 1:
            raise ValueError("Trace queue capacity must be a positive integer")
        if not math.isfinite(flush_interval) or flush_interval <= 0:
            raise ValueError("Trace flush interval must be positive and finite")
        metadata = _snapshot({} if metadata is None else metadata)
        directory = (Path.home() / "perceptual-grade-drag-logs"
                     if directory is None else Path(directory))
        directory = directory.expanduser().resolve()
        directory.mkdir(parents=True, exist_ok=True)
        self.session_id = uuid4().hex
        started_at = datetime.now(timezone.utc)
        self.path = directory / (
            "drag-" + started_at.strftime("%Y%m%dT%H%M%S.%fZ")
            + "-" + self.session_id[:8] + ".jsonl"
        )
        self._lock = threading.Lock()
        self._close_lock = threading.Lock()
        self._queue = Queue(maxsize=capacity)
        self._stop = threading.Event()
        self._flush_interval = float(flush_interval)
        self._accepting = True
        self._error: Optional[str] = None
        self._next_seq = 1
        self._accepted = 0
        self._written = 0
        self._dropped = 0
        self._stream = self.path.open("x", encoding="utf8", newline="\n")
        self._thread = threading.Thread(
            target=self._run, name="grade-drag-trace", daemon=True,
        )
        try:
            self._write(self._row(0, "session_start", {
                "session_id": self.session_id,
                "started_at": started_at.isoformat(),
                "metadata": metadata,
                "queue_capacity": capacity,
                "flush_interval_seconds": self._flush_interval,
            }))
            self._stream.flush()
            self._thread.start()
        except Exception:
            self._stream.close()
            raise

    @staticmethod
    def _row(seq, event, fields):
        return {
            "schema": 1,
            "seq": seq,
            "monotonic_ns": time.perf_counter_ns(),
            "thread": threading.get_ident(),
            "event": event,
            "fields": fields,
        }

    @property
    def error(self) -> Optional[str]:
        with self._lock:
            return self._error

    @property
    def dropped(self) -> int:
        with self._lock:
            return self._dropped

    def _fail(self, error):
        detail = _error_text(error)
        with self._lock:
            if self._error is None:
                self._error = detail
            self._accepting = False
        self._stop.set()

    def emit(self, event, **fields):
        """Record an observation, or disable tracing if recording fails."""
        try:
            with self._lock:
                if not self._accepting:
                    return
            if type(event) is not str:
                raise TypeError("Trace event names must be strings")
            snapshot = _snapshot(fields)
            with self._lock:
                if not self._accepting:
                    return
                seq = self._next_seq
                self._next_seq += 1
                row = self._row(seq, event, snapshot)
                try:
                    self._queue.put_nowait(row)
                except Full:
                    self._dropped += 1
                else:
                    self._accepted += 1
        except Exception as error:
            self._fail(error)

    def _write(self, row):
        self._stream.write(json.dumps(row, separators=(",", ":"), allow_nan=False) + "\n")

    def _footer(self):
        with self._lock:
            return self._row(self._next_seq, "session_stop", {
                "session_id": self.session_id,
                "accepted": self._accepted,
                "written": self._written,
                "dropped": self._dropped,
                "error": self._error,
            })

    def _run(self):
        deadline = time.monotonic() + self._flush_interval
        try:
            while not self._stop.is_set() or not self._queue.empty():
                timeout = max(0.0, deadline - time.monotonic())
                try:
                    row = self._queue.get(timeout=timeout)
                except Empty:
                    pass
                else:
                    self._write(row)
                    self._written += 1
                if time.monotonic() >= deadline:
                    self._stream.flush()
                    deadline = time.monotonic() + self._flush_interval
            self._write(self._footer())
            self._stream.flush()
        except Exception as error:
            self._fail(error)
        finally:
            # Release queued snapshots even when the destination stops accepting
            # writes. No queued item contains a host object.
            while True:
                try:
                    self._queue.get_nowait()
                except Empty:
                    break
            try:
                self._stream.close()
            except Exception as error:
                self._fail(error)

    def close(self) -> Optional[str]:
        """Stop admission, drain accepted observations, and close once."""
        try:
            with self._close_lock:
                with self._lock:
                    self._accepting = False
                self._stop.set()
                if threading.current_thread() is not self._thread:
                    self._thread.join()
        except Exception as error:
            self._fail(error)
        return self.error
