"""Opt-in Blender observations; these never authorize or change Grade work."""

from dataclasses import asdict
from functools import wraps
import hashlib
from pathlib import Path
import platform
import threading
import time

from .drag_trace import Recorder


def observational(method):
    """A diagnostic failure must not become a Grade preparation failure."""
    @wraps(method)
    def observe(self, *args, **kwargs):
        if self.closed or self.recorder.error is not None:
            return None
        try:
            return method(self, *args, **kwargs)
        except Exception as error:
            self.emit("diagnostic_error", operation=method.__name__, error=str(error))
            return None
    return observe


def state_fields(state):
    return {name: getattr(state, name) for name in (
        "desired_signature", "applied_signature", "applied_quality",
        "desired_preparation_signature", "gesture_active", "error",
    )}


class Capture:
    """Own one capture and its temporary observers, using plain data off-thread."""

    def __init__(self, nodes, directory=None):
        self.nodes = nodes
        self.bpy = nodes.bpy
        self.closed = False
        self.draw_handlers = []
        self.known_nodes = set()
        self.last_context = None
        self.last_heartbeat = None
        self.reported_error = False
        self.runtime = nodes._preparation_runtime
        self.preparer = nodes._grade_preparer
        self.previous_observer = self.runtime.on_event
        self.previous_timing = self.preparer.on_timing
        root = Path(nodes.__file__).parent
        sources = [root / "nodes.py", *sorted((root / "runtime").glob("*.py")),
                   *sorted((root / "policy").glob("*.py"))]
        metadata = {
            "blender_version": self.bpy.app.version_string,
            "blender_build": self.bpy.app.build_hash.decode("ascii", errors="replace"),
            "platform": platform.platform(),
            "source_sha256": {str(path.relative_to(root)): hashlib.sha256(
                path.read_bytes()).hexdigest() for path in sources},
            "heartbeat_interval_seconds": .05,
            "draw_evidence": "Draw callbacks do not establish changed display pixels.",
        }
        try:
            import gpu
            metadata["gpu"] = {
                "backend": gpu.platform.backend_type_get(),
                "renderer": gpu.platform.renderer_get(),
                "vendor": gpu.platform.vendor_get(),
                "version": gpu.platform.version_get(),
            }
        except Exception as error:
            metadata["gpu_error"] = str(error)
        self.recorder = Recorder(directory=directory, metadata=metadata)

        def runtime_observer(event, **fields):
            try:
                if self.previous_observer is not None:
                    self.previous_observer(event, **fields)
            finally:
                self.emit(event, **fields)

        def timing_observer(signature, component, started, finished):
            try:
                if self.previous_timing is not None:
                    self.previous_timing(signature, component, started, finished)
            finally:
                self.emit("preparation_component", signature=signature, component=component,
                          started_ns=int(started * 1e9), finished_ns=int(finished * 1e9))

        self.runtime_observer = runtime_observer
        self.timing_observer = timing_observer
        # Keep the exact bound timer object for registration and removal.
        self.timer = self.heartbeat
        try:
            self.runtime.on_event = runtime_observer
            self.preparer.on_timing = timing_observer
            for space, label in ((self.bpy.types.SpaceView3D, "VIEW_3D"),
                                 (self.bpy.types.SpaceImageEditor, "IMAGE_EDITOR")):
                handle = space.draw_handler_add(self.draw, (label,), "WINDOW", "POST_PIXEL")
                self.draw_handlers.append((space, handle))
            self.bpy.app.timers.register(self.timer, first_interval=0.0, persistent=True)
            self.observe_heartbeat()
        except Exception:
            self.close()
            raise

    def emit(self, event, **fields):
        if not self.closed:
            self.recorder.emit(event, **fields)

    def context(self, context=None):
        context = self.bpy.context if context is None else context
        window = getattr(context, "window", None)
        area = getattr(context, "area", None)
        workspace = getattr(context, "workspace", None)
        space = getattr(context, "space_data", None)
        tree = getattr(space, "edit_tree", None)
        return {
            "window_id": window.as_pointer() if window is not None else None,
            "workspace": workspace.name if workspace is not None else None,
            "area_id": area.as_pointer() if area is not None else None,
            "area_type": area.type if area is not None else None,
            "tree_type": tree.bl_idname if tree is not None else None,
        }

    def values(self, settings):
        fields = (self.nodes._LINEAR_FIELDS if hasattr(settings, "exposure")
                  else self.nodes._TONE_FIELDS)
        return {field: getattr(settings, field) for field in fields}

    def node_fields(self, node, record=None):
        pointer = node.as_pointer()
        record = self.nodes._node_stores.get(pointer) if record is None else record
        grade = getattr(node, "pg_grade", None)
        if grade is None and self.nodes._is_stack_node(node):
            grade = self.nodes._stack_active_grade(node)
        fields = {
            "node_id": pointer, "tree_id": node.id_data.as_pointer(),
            "tree_type": node.id_data.bl_idname,
            "grade_id": grade.as_pointer() if grade is not None else None,
            "source_id": id(record["source"]) if record and record.get("source") is not None else None,
        }
        if pointer not in self.known_nodes:
            self.known_nodes.add(pointer)
            self.emit("node_identity", **fields, node_name=node.name, tree_name=node.id_data.name,
                      grade_name=grade.name if grade is not None else None)
        return fields

    @observational
    def node_event(self, event, node, record=None, **fields):
        if threading.current_thread() is not threading.main_thread():
            self.emit(event, **fields, observation="RNA omitted off main thread")
            return
        self.emit(event, **self.node_fields(node, record), **fields)

    @observational
    def request_kernel_validation(self, node, record, started_ns, finished_ns,
                                  current, full_validation):
        self.emit(
            "request_kernel_validation", **self.node_fields(node, record),
            started_ns=started_ns, finished_ns=finished_ns,
            duration_ns=max(0, finished_ns - started_ns),
            current=current, full_validation=full_validation,
        )

    @observational
    def grade_changed(self, grade, started_ns, finished_ns, matched_nodes,
                      refreshed_nodes):
        self.emit(
            "grade_changed_timing", grade_id=grade.as_pointer(),
            started_ns=started_ns, finished_ns=finished_ns,
            duration_ns=max(0, finished_ns - started_ns),
            matched_nodes=matched_nodes, refreshed_nodes=refreshed_nodes,
        )

    @observational
    def transition(self, node, record, event, before, after, effects):
        self.node_event("node_transition", node, record, event_kind=event.kind,
                        event_signature=event.signature,
                        event_preparation_signature=event.preparation_signature,
                        event_error=event.error, before=state_fields(before),
                        after=state_fields(after), effects=asdict(effects))

    @observational
    def property_callback(self, callback, settings, context):
        started = time.perf_counter_ns()
        if threading.current_thread() is not threading.main_thread():
            self.emit("property_callback", callback=callback,
                      observation="RNA omitted off main thread")
            return
        owner = settings.id_data
        self.emit("property_callback", callback=callback, callback_started_ns=started,
                  settings_id=settings.as_pointer(), owner_id=owner.as_pointer(),
                  syncing=settings.as_pointer() in self.nodes._syncing,
                  values=self.values(settings), context=self.context(context))

    @observational
    def property_skip(self, callback, settings, reason):
        if threading.current_thread() is not threading.main_thread():
            self.emit("property_skipped", callback=callback, reason=reason,
                      observation="RNA omitted off main thread")
            return
        self.emit("property_skipped", callback=callback, settings_id=settings.as_pointer(),
                  reason=reason)

    @observational
    def ui_event(self, router, context, event, entry):
        if event.type not in {"MOUSEMOVE", "INBETWEEN_MOUSEMOVE", "LEFTMOUSE", "RIGHTMOUSE",
                              "ESC", "LEFT_SHIFT", "RIGHT_SHIFT", "WINDOW_DEACTIVATE"}:
            return
        window_id = getattr(router, "window_key", None)
        token = getattr(router, "token", None)
        policy = self.nodes.gesture_policy
        fields = {
            "entry": entry, "type": event.type, "value": event.value,
            "x": event.mouse_x, "y": event.mouse_y, "shift": event.shift,
            "ctrl": event.ctrl, "alt": event.alt, "window_id": window_id,
            "observer_token": token,
            "gesture_token": policy.current_gesture(self.nodes._gesture_state, window_id),
            "gesture_phase": policy.gesture_phase(self.nodes._gesture_state, window_id),
            "observer_status": policy.observer_status(self.nodes._gesture_state, window_id, token),
            "context": self.context(context),
        }
        if event.type == "LEFTMOUSE" and event.value == "PRESS":
            target = self.nodes._gesture_target_at(context.window, event.mouse_x, event.mouse_y)
            fields["target"] = self.node_fields(target) if target is not None else None
        self.emit("ui_event", **fields)

    @observational
    def gesture(self, event, before, after, effects):
        policy = self.nodes.gesture_policy
        self.emit("gesture_transition", gesture_event=asdict(event), effects=asdict(effects),
                  before_phase=policy.gesture_phase(before, event.window_id),
                  after_phase=policy.gesture_phase(after, event.window_id),
                  before_token=policy.current_gesture(before, event.window_id),
                  after_token=policy.current_gesture(after, event.window_id))

    @observational
    def draw(self, space_type):
        self.emit("draw", space_type=space_type, context=self.context())

    @observational
    def evaluation(self, event):
        # Native evaluation callbacks may run on a render worker. Policy state
        # and subscription identities are plain Python; do not inspect RNA.
        samples = [{"node_id": pointer,
                    "source_id": id(record["source"]) if record.get("source") is not None else None,
                    "state": state_fields(record["state"])}
                   for pointer, record in tuple(self.nodes._node_stores.items())]
        self.emit(event, nodes=samples)

    @observational
    def reset_identities(self):
        self.evaluation("runtime_reset")
        self.known_nodes.clear()
        self.last_context = None

    def heartbeat(self):
        if self.closed:
            return None
        if self.recorder.error is not None:
            if not self.reported_error:
                self.reported_error = True
                print("Perceptual Grade drag trace disabled:", self.recorder.error)
            return .05
        self.observe_heartbeat()
        return .05

    @observational
    def observe_heartbeat(self):
        now = time.perf_counter_ns()
        windows = []
        for window in self.bpy.context.window_manager.windows:
            areas = []
            for area in window.screen.areas:
                if area.type not in {"NODE_EDITOR", "IMAGE_EDITOR", "VIEW_3D"}:
                    continue
                space = area.spaces.active
                row = {"area_id": area.as_pointer(), "type": area.type}
                if area.type == "NODE_EDITOR":
                    tree = space.edit_tree
                    row["tree_type"] = tree.bl_idname if tree else None
                    row["tree_id"] = tree.as_pointer() if tree else None
                    active = tree.nodes.active if tree else None
                    if self.nodes._is_output_node(active):
                        row["active_node"] = self.node_fields(active)
                elif area.type == "IMAGE_EDITOR":
                    image = space.image
                    row["image"] = ({"id": image.as_pointer(), "name": image.name,
                                     "type": image.type, "source": image.source,
                                     # Even Image.size acquires a host buffer in
                                     # Blender and can download Viewer pixels.
                                     "size": None,
                                     "size_observation": "Omitted to avoid native buffer acquisition"}
                                    if image else None)
                    region = next((region for region in area.regions if region.type == "WINDOW"), None)
                    row["display_region_size"] = [region.width, region.height] if region else None
                else:
                    row["shading"] = space.shading.type
                areas.append(row)
            scene = window.scene
            windows.append({
                "window_id": window.as_pointer(), "workspace": window.workspace.name,
                "modal_operators": [operator.bl_idname for operator in window.modal_operators],
                "scene_id": scene.as_pointer(), "render_engine": scene.render.engine,
                "compositor_device": scene.render.compositor_device,
                "compositor_precision": scene.render.compositor_precision,
                "resolution": [scene.render.resolution_x, scene.render.resolution_y,
                               scene.render.resolution_percentage], "areas": areas,
            })
        if windows != self.last_context:
            self.emit("context", windows=windows)
            self.last_context = windows
        samples = []
        for pointer, record in tuple(self.nodes._node_stores.items()):
            if pointer not in self.known_nodes:
                continue
            try:
                node = record["node"]
                fields = self.node_fields(node, record)
                grade = getattr(node, "pg_grade", None)
                if grade is None and self.nodes._is_stack_node(node):
                    grade = self.nodes._stack_active_grade(node)
                samples.append({**fields, "state": state_fields(record["state"]),
                                "linear": self.values(grade.pg_linear) if grade else None,
                                "tone": self.values(grade.pg_tone) if grade else None})
            except (ReferenceError, AttributeError):
                continue
        gate = self.nodes._grade_resources.gate if self.nodes._grade_resources else None
        self.emit("heartbeat", interval_ns=None if self.last_heartbeat is None else now-self.last_heartbeat,
                  samples=samples, gate_reason=gate.reason() if gate else None,
                  pending_publications=len(self.nodes._grade_resources.pending)
                  if self.nodes._grade_resources else 0,
                  gesture_observers=asdict(self.nodes._gesture_state),
                  gesture_router_timer_registered=self.bpy.app.timers.is_registered(
                      self.nodes._gesture_router_tick),
                  preparation_timer_registered=self.bpy.app.timers.is_registered(
                      self.nodes._preparation_tick))
        self.last_heartbeat = now

    def wrap_publication(self, operations, source):
        """Measure the existing effect consumer without authorizing any operation."""
        def measured(name, operation):
            def invoke(*args, **kwargs):
                started = time.perf_counter_ns()
                error_text = None
                try:
                    return operation(*args, **kwargs)
                except BaseException as error:
                    error_text = str(error)
                    raise
                finally:
                    self.emit("publication_stage", source_id=id(source), stage=name,
                              started_ns=started, finished_ns=time.perf_counter_ns(), error=error_text)
            return invoke
        return {name: measured(name, operation) for name, operation in operations.items()}

    def close(self):
        if self.closed:
            return self.recorder.error
        self.closed = True
        if self.runtime.on_event is self.runtime_observer:
            self.runtime.on_event = self.previous_observer
        if self.preparer.on_timing is self.timing_observer:
            self.preparer.on_timing = self.previous_timing
        errors = []
        try:
            if self.bpy.app.timers.is_registered(self.timer):
                self.bpy.app.timers.unregister(self.timer)
        except Exception as error:
            errors.append(str(error))
        for space, handle in self.draw_handlers:
            try:
                space.draw_handler_remove(handle, "WINDOW")
            except Exception as error:
                errors.append(str(error))
        self.draw_handlers.clear()
        if errors:
            self.recorder.emit("diagnostic_cleanup_error", errors=errors)
        error = self.recorder.close()
        return error or ("; ".join(errors) if errors else None)
