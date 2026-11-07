"""Observational JSONL capture for the publication comparison example."""

import hashlib
import platform
import time
from pathlib import Path

from .drag_trace import Recorder


def _receipt(value):
    if type(value) is not dict:
        return None
    return {key: item for key, item in value.items()
            if type(item) in (str, bool, int, float, type(None))}


class Capture:
    """Record slider and publication behavior without changing its effects."""

    def __init__(self, nodes, directory=None):
        self.nodes = nodes
        self.bpy = nodes.bpy
        self.closed = False
        self._last_status = None
        root = Path(nodes.__file__).parent
        sources = [root / "nodes.py", *sorted((root / "runtime").glob("*.py")),
                   *sorted((root / "policy").glob("*.py"))]
        metadata = {
            "blender_version": self.bpy.app.version_string,
            "blender_build": self.bpy.app.build_hash.decode("ascii", errors="replace"),
            "platform": platform.platform(),
            "source_sha256": {
                str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in sources if path.is_file()
            },
            "capture_interval_seconds": 0.1,
        }
        directory = (Path.home() / "perceptual-grade-publication-compare-logs"
                     if directory is None else directory)
        self.recorder = Recorder(directory=directory, metadata=metadata)
        self.timer = self.heartbeat
        self.emit("capture_started", output_path=str(self.recorder.path))
        try:
            self.bpy.app.timers.register(self.timer, first_interval=0.0, persistent=True)
            self.heartbeat()
        except Exception:
            self.close()
            raise

    def emit(self, event, **fields):
        if not self.closed:
            self.recorder.emit(event, **fields)

    @staticmethod
    def _tree_fields(tree):
        return {
            "tree_id": int(tree.as_pointer()),
            "tree_type": str(tree.bl_idname),
            "variant": str(tree.get("_pg_publication_variant", "unknown")),
        }

    def property_callback(self, tree, exposure, context, phase, **fields):
        try:
            payload = {
                **self._tree_fields(tree),
                "exposure": float(exposure),
                "phase": phase,
                **fields,
            }
            if context is not None:
                window = getattr(context, "window", None)
                area = getattr(context, "area", None)
                payload["window_id"] = int(window.as_pointer()) if window else None
                payload["area_id"] = int(area.as_pointer()) if area else None
                payload["area_type"] = str(area.type) if area else None
            self.emit("slider_callback", **payload)
        except Exception as error:
            self.emit("diagnostic_error", operation="property_callback", error=str(error))

    def wrap_operations(self, tree, operations):
        fields = self._tree_fields(tree)
        wrapped = {}
        for action, operation in operations.items():
            def measured(*args, _action=action, _operation=operation, **kwargs):
                started = time.perf_counter_ns()
                bank = args[0] if args and type(args[0]) is int else None
                self.emit("publication_stage_started", **fields, stage=_action, bank=bank,
                          started_ns=started)
                try:
                    result = _operation(*args, **kwargs)
                except BaseException as error:
                    self.emit("publication_stage_finished", **fields, stage=_action,
                              bank=bank, started_ns=started,
                              finished_ns=time.perf_counter_ns(), error=str(error))
                    raise
                self.emit("publication_stage_finished", **fields, stage=_action,
                          bank=bank, started_ns=started,
                          finished_ns=time.perf_counter_ns(), receipt=_receipt(result),
                          failed=(bool(args and isinstance(args[-1], tuple) and args[-1])
                                  or isinstance(result, dict)
                                  and (result.get("clean") is False
                                       or result.get("matching") is False)))
                return result
            wrapped[action] = measured
        return wrapped

    def lifecycle(self, event, tree, **fields):
        try:
            self.emit(event, **self._tree_fields(tree), **fields)
        except Exception as error:
            self.emit("diagnostic_error", operation="lifecycle", error=str(error))

    def heartbeat(self):
        if self.closed:
            return None
        try:
            samples = []
            for pointer, tree in tuple(self.nodes._pending.items()):
                if not pointer:
                    continue
                sample = {
                    **self._tree_fields(tree),
                    "exposure": float(tree.pg_publication.exposure),
                    "published_exposure": float(tree.get(self.nodes._SIGNATURE, 0.0)),
                    "pending": True,
                    "current": bool(self.nodes._tree_is_current(tree)),
                    "error": str(tree.get("_pg_publication_error", "")),
                    "active_bank": (self.nodes._active_bank(tree)
                                    if tree.get(self.nodes._VARIANT) == "banked" else None),
                }
                samples.append(sample)
            snapshot = tuple(tuple(sorted(sample.items())) for sample in samples)
            if snapshot != self._last_status:
                self.emit("publication_status", samples=samples)
                self._last_status = snapshot
        except Exception as error:
            self.emit("diagnostic_error", operation="heartbeat", error=str(error))
        return 0.1

    def close(self):
        if self.closed:
            return self.recorder.error
        try:
            if self.bpy.app.timers.is_registered(self.timer):
                self.bpy.app.timers.unregister(self.timer)
        except Exception as error:
            self.emit("diagnostic_cleanup_error", error=str(error))
        self.emit("capture_stopping", output_path=str(self.recorder.path))
        self.closed = True
        return self.recorder.close()
