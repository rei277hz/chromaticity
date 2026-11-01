"""Extension-lifetime Restart action for the Next Blender product.

Restart is deliberately outside the normal preparation App.  It revokes the
foreground scope, cancels queued preparation work, and waits for any native
operation to publish its terminal receipt before a fresh recovery pass starts.
The controller is host-independent so the transition can be tested without
creating Blender datablocks.
"""

from dataclasses import dataclass

from .lifecycle import RestartSupervisor


@dataclass(frozen=True)
class RestartStatus:
    phase: str
    generation: int
    required: tuple = ()
    retired: tuple = ()
    error: str = ""


class RestartController:
    """Own one restart occurrence and its exact cleanup ledger."""

    def __init__(self, supervisor=None, *, drain=None, recover=None, observe=None,
                 begin=None, on_receipt=None, on_complete=None):
        self.supervisor = supervisor or RestartSupervisor()
        self.drain = drain
        self.recover = recover
        self.observe = observe
        self.begin = begin
        self.on_receipt = on_receipt
        self.on_complete = on_complete
        self.project_generation = 0
        self._status = RestartStatus("active", 0)

    @property
    def status(self):
        return self._status

    def request(self, obligations=()):
        required = tuple(obligations)
        generation = self.supervisor.request(required)
        if generation is False:
            return self._status
        self._status = RestartStatus("draining", generation, required)
        try:
            if self.begin is not None:
                project_generation = self.begin(generation, required)
                if type(project_generation) is not int or project_generation <= 0:
                    raise RuntimeError("Project workflow rejected Restart")
                self.project_generation = project_generation
            if self.drain is not None:
                self.drain(generation, required)
            self.poll()
        except BaseException as error:
            self.supervisor.fail()
            self._status = RestartStatus(
                "failed", generation, required,
                tuple(sorted(self.supervisor.cleanup_receipts)), str(error),
            )
        return self._status

    def receipt(self, identity):
        return self._accept_receipt(identity)

    def _accept_receipt(self, identity, *, repoll=True):
        if not self.supervisor.receipt(identity):
            return False
        if self.on_receipt is not None:
            if self.on_receipt(self.project_generation, identity) is False:
                self.supervisor.fail()
                self._status = RestartStatus(
                    "failed", self.supervisor.generation,
                    tuple(sorted(self.supervisor.required_cleanup)),
                    tuple(sorted(self.supervisor.cleanup_receipts)),
                    "Project workflow rejected a cleanup receipt",
                )
                return False
        self._status = RestartStatus(
            "draining", self.supervisor.generation,
            tuple(sorted(self.supervisor.required_cleanup)),
            tuple(sorted(self.supervisor.cleanup_receipts)),
        )
        if repoll:
            self.poll()
        return True

    def poll(self):
        if self.supervisor.phase != "restarting":
            return self._status
        if self.observe is not None:
            for identity in tuple(self.supervisor.required_cleanup):
                if (identity not in self.supervisor.cleanup_receipts
                        and self.observe(identity)):
                    self._accept_receipt(identity, repoll=False)
                    if self.supervisor.phase == "failed":
                        return self._status
        if (self.supervisor.phase == "restarting"
                and self.supervisor.cleanup_receipts == self.supervisor.required_cleanup):
            try:
                if self.on_complete is not None and not self.on_complete(self.project_generation):
                    raise RuntimeError("Project workflow rejected Restart completion")
                if not self.supervisor.complete():
                    return self._status
                if self.recover is not None:
                    self.recover(self.supervisor.generation)
                self._status = RestartStatus("active", self.supervisor.generation)
            except BaseException as error:
                self.supervisor.fail()
                self._status = RestartStatus(
                    "failed", self.supervisor.generation,
                    tuple(sorted(self.supervisor.required_cleanup)),
                    tuple(sorted(self.supervisor.cleanup_receipts)),
                    error=str(error),
                )
        elif self.supervisor.phase == "restarting":
            self._status = RestartStatus(
                "draining", self.supervisor.generation,
                tuple(sorted(self.supervisor.required_cleanup)),
                tuple(sorted(self.supervisor.cleanup_receipts)),
            )
        return self._status

    def retry(self):
        if self._status.phase != "failed":
            return self._status
        obligations = (
            tuple(sorted(self.supervisor.required_cleanup))
            if self.supervisor.phase == "failed" else ()
        )
        return self.request(obligations)


_CONTROLLER = None
_CLASSES = ()
_MENU_ENTRIES = []
_UPDATE_FUTURES = ()


def _runtime_obligations():
    """Return only work that needs a terminal physical receipt."""
    obligations = []
    try:
        from . import scope_runtime, updates
        if scope_runtime.runtime().actor.state.physical != "none":
            obligations.append("scope")
        if updates._PENDING or updates._JOBS:
            obligations.append("updates")
    except (AttributeError, ImportError, RuntimeError):
        pass
    try:
        from . import bake_operators
        gateway = bake_operators._GATEWAY
        if gateway is not None and gateway.state.bake_physical != "none":
            obligations.append("bake:%s" % gateway.state.bake_operation)
    except (AttributeError, ImportError, RuntimeError):
        pass
    try:
        from . import output_operators
        controller = output_operators._CONTROLLER
        if controller is not None:
            operation = (controller.active_render_operation
                         or controller.pending_render_operation
                         or controller.pending_save_operation)
            if operation is not None:
                obligations.append("output:%s" % operation)
    except (AttributeError, ImportError, RuntimeError):
        pass
    return tuple(dict.fromkeys(obligations))


def _drain_blender(generation, obligations):
    global _UPDATE_FUTURES
    from . import scope_runtime, updates
    from . import output_operators

    # Foreground visibility is revoked synchronously.  A live native capture
    # remains an obligation and can only retire through its own receipt.
    scope_runtime.runtime().close()
    _UPDATE_FUTURES = tuple(job[0] for job in updates._JOBS.values())
    updates.cancel_pending_updates(clear_holds=True)
    output = output_operators._CONTROLLER
    if output is not None:
        output._pending_save.clear()
        output._pending_render.clear()


def _begin_project_restart(_generation, obligations):
    from .project_readiness import project_readiness_runtime

    workflow = project_readiness_runtime().workflow
    if workflow.state.phase == "restarting":
        if frozenset(workflow.state.restart_obligations) != frozenset(obligations):
            return 0
        return workflow.state.generation
    generation = workflow.state.generation + 1
    if not workflow.dispatch(
            "restart", generation=generation, obligations=tuple(obligations)):
        return 0
    return generation


def _retire_project_restart(generation, identity):
    from .project_readiness import project_readiness_runtime

    workflow = project_readiness_runtime().workflow
    state = workflow.state
    if identity.startswith("bake:") and state.bake_physical in {"live", "retiring"}:
        if not workflow.dispatch(
                "bake_retired", generation=generation,
                operation=state.bake_operation):
            return False
    return workflow.dispatch(
        "restart_retired", generation=generation, owner=identity)


def _complete_project_restart(generation):
    from .project_readiness import project_readiness_runtime

    return project_readiness_runtime().workflow.dispatch(
        "restart_complete", generation=generation)


def _observe_blender(identity):
    if identity == "scope":
        try:
            from . import scope_runtime
            return scope_runtime.runtime().actor.state.physical == "none"
        except (AttributeError, ImportError, RuntimeError):
            return False
    if identity == "updates":
        return all(future.done() for future in _UPDATE_FUTURES)
    if identity.startswith("bake:"):
        try:
            from . import bake_operators
            gateway = bake_operators._GATEWAY
            if gateway is None:
                return False
            operation = int(identity.split(":", 1)[1])
            return (gateway.state.bake_operation != operation
                    or gateway.state.bake_physical == "none")
        except (AttributeError, ImportError, RuntimeError, ValueError):
            return False
    if identity.startswith("output:"):
        try:
            from . import output_operators
            active = output_operators._CONTROLLER
            if active is None:
                return False
            operation = identity.split(":", 1)[1]
            return (str(active.active_render_operation) != operation
                    and str(active.pending_render_operation) != operation
                    and str(active.pending_save_operation) != operation)
        except (AttributeError, ImportError, RuntimeError):
            return False
    return False


def _recover_blender(_generation):
    import bpy
    from .recovery import recover_document
    from .scope_runtime import _project_node_trees
    recover_document(tuple(_project_node_trees(bpy)))


def controller():
    global _CONTROLLER
    if _CONTROLLER is None:
        _CONTROLLER = RestartController(
            recover=_recover_blender, observe=_observe_blender,
            begin=_begin_project_restart,
            on_receipt=_retire_project_restart,
            on_complete=_complete_project_restart,
        )
    return _CONTROLLER


def request_restart():
    action = controller()
    # The drain callback needs the global controller to acknowledge work that
    # was already idle, so install it only after construction.
    if action.drain is None:
        action.drain = _drain_blender
    if action.status.phase == "failed":
        status = action.retry()
    else:
        status = action.request(_runtime_obligations())
    return action.poll()


def receipt(identity):
    action = controller()
    return action.receipt(identity)


def register():
    global _CLASSES, _MENU_ENTRIES
    if _CLASSES:
        return _CLASSES
    import bpy

    class PGNEXT_OT_restart(bpy.types.Operator):
        bl_idname = "wm.pg_next_restart"
        bl_label = "Restart Perceptual Grade"
        bl_description = "Drain the current session and rebuild Perceptual Grade state"
        bl_options = {"REGISTER"}

        def execute(self, _context):
            status = request_restart()
            if status.phase == "failed":
                self.report({"ERROR"}, status.error or "Perceptual Grade restart failed")
                return {"CANCELLED"}
            if status.phase == "draining":
                self.report({"INFO"}, "Perceptual Grade is waiting for native work to retire")
                return {"RUNNING_MODAL"}
            return {"FINISHED"}

        def invoke(self, context, _event):
            status = request_restart()
            if status.phase == "failed":
                self.report({"ERROR"}, status.error or "Perceptual Grade restart failed")
                return {"CANCELLED"}
            if status.phase == "active":
                return {"FINISHED"}
            self._pg_restart_timer = context.window_manager.event_timer_add(
                0.1, window=context.window,
            )
            self._pg_restart_manager = context.window_manager
            context.window_manager.modal_handler_add(self)
            return {"RUNNING_MODAL"}

        def modal(self, context, event):
            if event.type == "ESC":
                self.report({"WARNING"}, "Restart cannot be abandoned after cleanup begins")
                return {"PASS_THROUGH"}
            if event.type != "TIMER":
                return {"PASS_THROUGH"}
            status = controller().poll()
            if status.phase == "active":
                _remove_timer(self)
                return {"FINISHED"}
            if status.phase == "failed":
                _remove_timer(self)
                self.report({"ERROR"}, status.error or "Restart failed; invoke Restart to retry")
                return {"CANCELLED"}
            return {"PASS_THROUGH"}

        def cancel(self, _context):
            _remove_timer(self)


    def _remove_timer(operator):
        manager = getattr(operator, "_pg_restart_manager", None)
        timer = getattr(operator, "_pg_restart_timer", None)
        if manager is not None and timer is not None:
            try:
                manager.event_timer_remove(timer)
            except (AttributeError, ReferenceError, RuntimeError):
                pass
        operator._pg_restart_timer = None

    bpy.utils.register_class(PGNEXT_OT_restart)
    _CLASSES = (PGNEXT_OT_restart,)

    def file_menu(self, _context):
        self.layout.separator()
        self.layout.operator("wm.pg_next_restart", icon="FILE_REFRESH")

    menu = getattr(bpy.types, "TOPBAR_MT_file", None)
    if menu is not None:
        menu.append(file_menu)
        _MENU_ENTRIES.append((menu, file_menu))
    return _CLASSES


def unregister():
    global _CLASSES, _CONTROLLER
    try:
        import bpy
    except ImportError:
        _CLASSES = ()
        _CONTROLLER = None
        return
    while _MENU_ENTRIES:
        menu, callback = _MENU_ENTRIES.pop()
        try:
            menu.remove(callback)
        except (AttributeError, ReferenceError, ValueError):
            pass
    for cls in reversed(_CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except (AttributeError, ReferenceError, RuntimeError):
            pass
    _CLASSES = ()
    _CONTROLLER = None


__all__ = (
    "RestartController", "RestartStatus", "controller", "receipt",
    "request_restart", "register", "unregister",
)
