"""Host-free timing checkpoints for the installed Blender regression."""

from contextlib import contextmanager
from functools import wraps
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time


TIMING_SECTIONS = (
    "extension startup",
    "node and ownership setup",
    "parameter and save/load recovery",
    "Stack builds and gestures",
    "concurrency and failure recovery",
    "undo and teardown",
)


def write_report(path, data):
    """Publish a whole report, retaining the previous checkpoint on failure."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf8", dir=path.parent,
                prefix="." + path.name + ".", suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(data, stream, indent=2, allow_nan=False)
            stream.write("\n")
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def read_report(path):
    try:
        data = json.loads(Path(path).read_text(encoding="utf8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _callsite():
    frame = sys._getframe(2)
    return f"{Path(frame.f_code.co_filename).name}:{frame.f_lineno}"


def _finish(row, now, status):
    row.update(
        finished_monotonic=now, seconds=now - row["started_monotonic"],
        status=status,
    )


class TimingRecorder:
    """Record section wall time and inclusive, possibly overlapping operations.

    Every section/operation start and end publishes an atomic checkpoint. A
    parent harness can extend unfinished spans to its process-termination
    timestamp because both processes use the same host monotonic clock.
    Operation totals are diagnostic subsets and must not be added to sections.
    No Blender state is read here, including from worker-thread callbacks.
    """

    def __init__(self, report_path, section_names, *, metadata=None,
                 clock=time.monotonic):
        names = tuple(section_names)
        if not names or len(set(names)) != len(names):
            raise ValueError("Timing sections must be nonempty and unique")
        self.path = Path(report_path)
        self.clock = clock
        self._lock = threading.RLock()
        self._parents = {}
        self._section = 0
        now = clock()
        self._data = {}
        self._merge_metadata(metadata)
        self._data["timings"] = {
            "schema": 2, "unit": "seconds", "complete": False,
            "status": "running", "started_monotonic": now,
            "finished_monotonic": None, "recorded_monotonic": now,
            "runner_seconds": 0.0,
            "sections": [
                {"name": name, "status": "unreached", "started_monotonic": None,
                 "finished_monotonic": None, "seconds": None}
                for name in names
            ],
            "operations": [],
        }
        self._data["timings"]["sections"][0].update(
            status="running", started_monotonic=now, seconds=0.0,
        )
        self._checkpoint(now)

    def _merge_metadata(self, metadata):
        if metadata is not None:
            if "timings" in metadata:
                raise ValueError("Timing metadata cannot replace the timings record")
            self._data.update(metadata)

    def _checkpoint(self, now):
        timings = self._data["timings"]
        timings["recorded_monotonic"] = now
        end = timings["finished_monotonic"]
        timings["runner_seconds"] = (
            now if end is None else end
        ) - timings["started_monotonic"]
        for row in (*timings["sections"], *timings["operations"]):
            if row["status"] == "running":
                row["seconds"] = now - row["started_monotonic"]
        write_report(self.path, self._data)

    def checkpoint(self, metadata=None):
        with self._lock:
            self._merge_metadata(metadata)
            self._checkpoint(self.clock())

    def start_section(self, name):
        with self._lock:
            timings = self._data["timings"]
            sections = timings["sections"]
            next_index = self._section + 1
            if (timings["complete"] or next_index >= len(sections)
                    or sections[next_index]["name"] != name):
                raise ValueError("Timing sections must start once in declared order")
            now = self.clock()
            _finish(sections[self._section], now, "complete")
            self._section = next_index
            sections[next_index].update(
                status="running", started_monotonic=now, seconds=0.0,
            )
            self._checkpoint(now)

    def operation(self, name, callsite=None):
        return self._operation(name, _callsite() if callsite is None else callsite)

    @contextmanager
    def _operation(self, name, callsite):
        thread = threading.get_ident()
        with self._lock:
            timings = self._data["timings"]
            if timings["complete"]:
                raise RuntimeError("Cannot record operations after completion")
            parents = self._parents.setdefault(thread, [])
            row = {
                "id": len(timings["operations"]),
                "parent_id": parents[-1] if parents else None,
                "section": timings["sections"][self._section]["name"],
                "name": name, "callsite": callsite,
                "thread": threading.current_thread().name,
                "thread_id": thread, "status": "running",
                "started_monotonic": self.clock(), "finished_monotonic": None,
                "seconds": 0.0,
            }
            timings["operations"].append(row)
            parents.append(row["id"])
            self._checkpoint(row["started_monotonic"])
        error = None
        try:
            yield
        except BaseException as caught:
            error = caught
            raise
        finally:
            with self._lock:
                _finish(row, self.clock(), "complete" if error is None else "error")
                if error is not None:
                    row["error"] = f"{type(error).__name__}: {error}"
                parents.pop()
                if not parents:
                    self._parents.pop(thread, None)
                self._checkpoint(row["finished_monotonic"])

    def timed(self, name):
        """Decorate a synchronous operation while retaining its caller location."""
        def decorate(function):
            @wraps(function)
            def wrapped(*args, **kwargs):
                with self.operation(name, callsite=_callsite()):
                    return function(*args, **kwargs)
            return wrapped
        return decorate

    def complete(self, metadata=None):
        with self._lock:
            timings = self._data["timings"]
            if self._parents:
                raise RuntimeError("Timing completion requires all operations to finish")
            if self._section != len(timings["sections"]) - 1:
                raise RuntimeError("Timing completion requires every section to be reached")
            self._merge_metadata(metadata)
            if not timings["complete"]:
                now = self.clock()
                _finish(timings["sections"][self._section], now, "complete")
                timings.update(complete=True, status="complete", finished_monotonic=now)
            self._checkpoint(self.clock())


def add_harness_timings(data, *, setup_seconds, process_seconds, total_seconds,
                       observed_monotonic, interrupted=False):
    """Finalize an interrupted checkpoint only after the process has retired."""
    timings = data.get("timings") if isinstance(data, dict) else None
    if not isinstance(timings, dict):
        return {
            "status": "unavailable", "harness_setup_seconds": setup_seconds,
            "blender_process_seconds": process_seconds,
            "test_total_seconds": total_seconds,
        }
    if interrupted and not timings.get("complete", False):
        recorded = timings["recorded_monotonic"]
        now = max(recorded, observed_monotonic)
        for row in (*timings["sections"], *timings["operations"]):
            if row["status"] == "running":
                _finish(row, now, "interrupted")
                row["duration_source"] = "harness_process_end"
        timings.update(
            status="interrupted", finished_monotonic=now,
            runner_seconds=now - timings["started_monotonic"],
            duration_source="harness_process_end",
            unreported_seconds=now - recorded,
        )
    timings.update(
        harness_setup_seconds=setup_seconds,
        blender_process_seconds=process_seconds,
        test_total_seconds=total_seconds,
    )
    process_started = observed_monotonic - process_seconds
    timings["blender_pre_runner_seconds"] = max(
        0.0, timings["started_monotonic"] - process_started,
    )
    if timings.get("complete", False):
        timings["blender_post_runner_seconds"] = max(
            0.0, observed_monotonic - timings["finished_monotonic"],
        )
    else:
        timings.pop("blender_post_runner_seconds", None)
    return timings


def format_timing_report(timings):
    if timings is None:
        return "No timing report was produced by Blender."
    lines = ["Installed test timings (seconds; operations are inclusive and may overlap):"]
    if timings.get("status") == "unavailable":
        lines.append("  No timing report was produced by Blender.")
    operations = timings.get("operations", ())
    for section in timings.get("sections", ()):
        status = section["status"]
        if status == "unreached":
            lines.append(f"  {section['name']}: not reached")
            continue
        lines.append(f"  {section['name']}: {section['seconds']:.3f} [{status}]")
        groups = {}
        for operation in operations:
            if operation["section"] == section["name"]:
                groups.setdefault(operation["name"], []).append(operation)
        for name, rows in groups.items():
            longest = max(rows, key=lambda row: row["seconds"])
            lines.append(
                f"    {name}: count={len(rows)} total={sum(row['seconds'] for row in rows):.3f}"
                f" max={longest['seconds']:.3f}"
            )
            for row in rows:
                if row["status"] in {"running", "interrupted", "error"}:
                    lines.append(
                        f"      {row['status']}: {row['callsite']} ({row['seconds']:.3f})"
                    )
            if longest["seconds"] >= 1.0 and longest["status"] == "complete":
                lines.append(f"      slowest completed call: {longest['callsite']}")
    for name in (
        "runner_seconds", "unreported_seconds", "blender_pre_runner_seconds",
        "blender_post_runner_seconds", "blender_process_seconds",
        "harness_setup_seconds", "test_total_seconds",
    ):
        if name in timings:
            lines.append(f"  {name}: {timings[name]:.3f}")
    if timings.get("status") == "interrupted":
        lines.append("  Interrupted durations extend the last checkpoint to observed process termination.")
    return "\n".join(lines)
