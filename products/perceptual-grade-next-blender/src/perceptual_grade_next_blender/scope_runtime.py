"""Foreground composition for the single Next scope and Gizmo.

The portable scope machine owns semantic demand and physical receipts.  This
module owns the extension-lifetime foreground authority and forwards only
checked, value-only events to that machine.  Blender access is limited to the
optional Gizmo registration at the bottom of the module.
"""

from dataclasses import dataclass
import math
from types import SimpleNamespace

from .lifecycle import (
    ScopeActor, ScopeSubmission, ViewAuthority, ViewDisplay,
    _apply_scope_view, _close_scope_view, _issue_scope_view, _move_scope_view,
    _open_scope_view,
)


_SCOPE_PAGES = ("histogram", "waveform", "vectorscope")
_SCOPE_PAGE_LABELS = {
    "histogram": "Histogram",
    "waveform": "Waveform",
    "vectorscope": "Vectorscope",
}


@dataclass(frozen=True)
class ScopeDemand:
    """A logical demand occurrence admitted by the foreground."""

    request: int
    source_revision: int
    source_id: object
    frame: object = None


@dataclass(frozen=True)
class ScopeVisual:
    """A staged visual and its exact foreground display identity."""

    token: ViewDisplay
    request: int
    source_revision: int
    source_id: object
    payload: object = None


@dataclass(frozen=True)
class ScopeFailure:
    """Local capture failure retained until an explicit retry succeeds."""

    request: int
    source_revision: int
    source_id: object
    message_key: str
    diagnostic: str


@dataclass(frozen=True)
class ScopePresentation:
    """Value snapshot for a scope UI, including its last applied result."""

    status: str
    displayed: ScopeVisual | None
    result_stale: bool
    failure: ScopeFailure | None
    can_retry: bool
    has_current_input: bool
    selected_page: str


def _identity(value):
    return ((type(value) is int and value > 0)
            or (type(value) is str and bool(value)))


def _pointer(value):
    try:
        result = value.as_pointer()
        return int(result) if result else 0
    except (AttributeError, ReferenceError, TypeError, ValueError):
        return 0


def context_owner(context):
    """Return a stable foreground owner key for one Blender editor instance."""
    window = getattr(context, "window", None)
    area = getattr(context, "area", None)
    window_id = _pointer(window)
    area_id = _pointer(area)
    if not window_id:
        window_id = id(window) if window is not None else 0
    if not area_id:
        area_id = id(area) if area is not None else 0
    if not window_id or not area_id:
        return "context:unknown"
    return "view:%d:%d" % (window_id, area_id)


class ScopeRuntime:
    """One global ScopeActor plus one foreground ViewAuthority per App.

    ``observe`` is intentionally value-only: a caller supplies a frozen source
    revision/id and this object allocates a fresh request occurrence only when
    the semantic source changes.  During playback or native evaluation the
    newest source is retained and serviced after the barrier is released.
    """

    def __init__(self):
        self.actor = ScopeActor()
        self.view = ViewAuthority()
        self.generation = 0
        self._app_owner = None
        self.target_owner = None
        self._request = 0
        self._submission = 0
        self._display = 0
        self._observed = None
        self._pending = None
        self._native_ready = True
        self._playing = False
        self._displayed = None
        self._staged_visual = None
        self._failure = None
        self._selected_page = "histogram"
        self._capture_rendering = False

    def _refresh_ui(self):
        if globals().get("_RUNTIME") is self:
            _tag_view_redraw()

    @property
    def visible(self):
        return self.view.visible

    @property
    def playing(self):
        return self._playing

    @property
    def native_ready(self):
        return self._native_ready

    @property
    def selected_page(self):
        return self._selected_page

    def select_page(self, page):
        """Change only the visible chart; this does not create capture demand."""
        if page not in _SCOPE_PAGES:
            return False
        if page == self._selected_page:
            return True
        self._selected_page = page
        self._refresh_ui()
        return True

    def set_capture_rendering(self, active):
        self._capture_rendering = bool(active)

    @property
    def state(self):
        return self.actor.state

    @property
    def displayed_visual(self):
        """Last applied result, hidden immediately when the foreground closes."""
        if (not self.view.visible or self._displayed is None
                or self._displayed.token.view_epoch != self.view.view_epoch
                or self._displayed.token.owner != self.view.owner):
            return None
        return self._displayed

    @property
    def presentation(self):
        state = self.actor.state
        displayed = self.displayed_visual
        result_stale = bool(
            displayed is not None
            and (displayed.request != state.request
                 or displayed.source_revision != state.source_revision
                 or displayed.source_id != state.source_id)
        )
        has_input = self.actor.has_current_input()
        if not self.view.visible:
            status = "closed"
        elif self._playing:
            status = "paused"
        elif state.phase == "failed":
            status = "failed"
        elif state.phase in {"capturing", "analyzing"}:
            status = state.phase
        elif state.phase == "retiring":
            status = "retiring_after_failure" if self._failure else "retiring"
        elif not self._native_ready:
            status = "waiting_for_evaluation"
        elif has_input and displayed is not None and not result_stale:
            status = "ready"
        elif has_input:
            status = "result_ready"
        elif state.request == 0:
            status = "idle"
        else:
            status = "waiting"
        can_retry = bool(
            self.view.visible and not self._playing and self._native_ready
            and state.phase == "failed" and state.physical == "none"
            and self._observed is not None
        )
        return ScopePresentation(
            status=status,
            displayed=displayed,
            result_stale=result_stale,
            failure=(self._failure
                     if state.phase in {"failed", "retiring"} else None),
            can_retry=can_retry,
            has_current_input=has_input,
            selected_page=self._selected_page,
        )

    def open(self, owner, *, generation=None, app_owner=None, target_owner=None):
        if not _identity(owner):
            raise ValueError("View owner must be a positive integer or nonempty string")
        if generation is None:
            generation = self.generation + 1
        if type(generation) is not int or generation <= self.generation:
            raise ValueError("Scope generation must increase on reopen")
        if self.actor.state.phase not in {"idle", "closed"} or self.actor.state.physical != "none":
            raise RuntimeError("Previous scope obligations have not reached retirement")
        if app_owner is None:
            app_owner = "scope-app-%d" % generation
        if not _identity(app_owner):
            raise ValueError("App owner must be a positive integer or nonempty string")
        if not _open_scope_view(self.actor, self.view, generation, app_owner, owner):
            raise RuntimeError("Scope/view policy rejected the new generation")
        view_epoch = self.view.view_epoch
        self.generation = generation
        self._app_owner = app_owner
        self.target_owner = target_owner
        self._playing = False
        self._native_ready = True
        self._observed = None
        self._pending = None
        self._displayed = None
        self._staged_visual = None
        self._failure = None
        self._selected_page = "histogram"
        self._refresh_ui()
        return view_epoch

    def open_context(self, context, *, generation=None, app_owner=None, target_owner=None):
        """Open or transfer the singleton foreground view for a Blender context."""
        owner = context_owner(context)
        if self.view.visible:
            if self.view.owner == owner:
                if target_owner is not None:
                    self.target_owner = target_owner
                return self.view.view_epoch
            self.move(owner)
            if target_owner is not None:
                self.target_owner = target_owner
            return self.view.view_epoch
        return self.open(owner, generation=generation, app_owner=app_owner,
                         target_owner=target_owner)

    def close(self):
        """Revoke foreground drawing before asking the actor to retire work."""
        if not self.view.visible:
            return False
        accepted = _close_scope_view(self.actor, self.view)
        if accepted:
            self._staged_visual = None
        self._refresh_ui()
        return accepted

    def move(self, owner):
        """Transfer the singleton Gizmo to a new editor incarnation."""
        if not self.view.visible or not _identity(owner):
            return False
        accepted = _move_scope_view(
            self.actor, self.view, owner, self.view.view_epoch + 1,
        )
        if accepted:
            self._staged_visual = None
        self._refresh_ui()
        return accepted

    def set_native_ready(self, ready, *, source_revision=None, source_id=None,
                         frame=None):
        """Set the native-evaluation barrier and service a retained source."""
        self._native_ready = bool(ready)
        if source_revision is not None and source_id is not None:
            self._pending = (source_revision, source_id, frame)
        if not self._native_ready or self._playing:
            self._refresh_ui()
            return None
        demand = self._service_pending()
        self._refresh_ui()
        return demand

    def observe(self, source_revision, source_id, *, frame=None):
        """Observe a frozen source; equal observations do not allocate work."""
        if (type(source_revision) is not int or source_revision <= 0
                or not _identity(source_id)):
            raise ValueError("Scope source must have a positive revision and identity")
        observed = (source_revision, source_id, frame)
        if observed == self._observed and self._pending is None:
            return None
        self._observed = observed
        self._pending = observed
        demand = self._service_pending()
        self._refresh_ui()
        return demand

    def _service_pending(self):
        if (self._pending is None or self._playing or not self._native_ready
                or not self.view.visible):
            return None
        source_revision, source_id, frame = self._pending
        if ((self.actor.state.request == self.actor.state.accepted_request
             and self.actor.state.accepted_source == source_id
             and self.actor.state.source_revision == source_revision)
                or (self.actor.state.request > 0
                    and self.actor.state.source_id == source_id
                    and self.actor.state.source_revision == source_revision
                    and self.actor.state.pending_request == 0
                    and self.actor.state.phase in ("capturing", "analyzing"))):
            self._pending = None
            return None
        self._request += 1
        if not self.actor.demand(self._request, source_revision, source_id):
            return None
        self._pending = None
        self._failure = None
        return ScopeDemand(self._request, source_revision, source_id, frame)

    def begin_capture(self):
        state = self.actor.state
        if self._playing or not self._native_ready or not self.view.visible:
            return None
        if state.request <= 0 or state.source_revision <= 0:
            return None
        self._submission += 1
        ticket = self.actor.begin(state.request, state.source_revision,
                                  state.source_id, self._submission)
        if ticket is not None:
            self._refresh_ui()
        return ticket

    def complete_capture(self, ticket: ScopeSubmission):
        """Settle a native capture; stale view results remain accounting-only."""
        if not self.actor.complete(ticket):
            return False
        current = self.actor.has_current_input()
        if current and self.actor.state.accepted_request == ticket.request:
            self._failure = None
        self._refresh_ui()
        return current

    def fail_capture(self, ticket: ScopeSubmission, diagnostic=""):
        """Record a local failure while retaining its physical retirement debt."""
        if not self.actor.fail(ticket):
            return False
        diagnostic = str(diagnostic).strip().replace("\x00", " ")[:512]
        self._failure = ScopeFailure(
            ticket.request,
            ticket.source_revision,
            ticket.source_id,
            "PERCEPTUAL_GRADE_SCOPE_CAPTURE_FAILED",
            diagnostic,
        )
        self._refresh_ui()
        return True

    def cancel_capture(self, ticket: ScopeSubmission):
        accepted = self.actor.cancel(ticket)
        if accepted:
            self._refresh_ui()
        return accepted

    def retire_capture(self, ticket: ScopeSubmission):
        accepted = self.actor.retire(ticket)
        if accepted:
            self._refresh_ui()
        return accepted

    def retry(self):
        """Retry a settled local capture failure as a new demand occurrence."""
        state = self.actor.state
        if (not self.view.visible or self._playing or not self._native_ready
                or state.phase != "failed" or state.physical != "none"
                or self._observed is None):
            return None
        self._pending = self._observed
        demand = self._service_pending()
        if demand is not None:
            self._failure = None
            self._refresh_ui()
        return demand

    def stage_display(self, payload=None):
        if (self._playing or not self.view.visible
                or not self.actor.has_current_input()):
            return None
        self._display += 1
        token = "scope-display-%d" % self._display
        if not _issue_scope_view(self.actor, self.view, token):
            return None
        display = self.view.display_token
        state = self.actor.state
        visual = ScopeVisual(display, state.request, state.source_revision,
                             state.source_id, payload)
        self._staged_visual = visual
        return visual

    def apply_display(self, visual: ScopeVisual):
        if (not isinstance(visual, ScopeVisual)
                or visual is not self._staged_visual
                or not self.view.can_apply(visual.token)
                or self._playing
                or visual.request != self.actor.state.request
                or visual.source_revision != self.actor.state.source_revision
                or visual.source_id != self.actor.state.source_id):
            return False
        if not _apply_scope_view(self.actor, self.view, visual.token):
            return False
        self._displayed = visual
        self._staged_visual = None
        self._failure = None
        self._refresh_ui()
        return True

    def playback_start(self, playback_epoch=None):
        if not self.view.visible or self._playing:
            return False
        if playback_epoch is None:
            playback_epoch = self.actor.state.playback_epoch + 1
        self._playing = True
        accepted = self.actor.playback_start(playback_epoch)
        if not accepted:
            self._playing = False
        else:
            self._staged_visual = None
            self._refresh_ui()
        return accepted

    def playback_stop(self):
        if not self._playing:
            return False
        # Keep the barrier until the actor has retired any cancelled capture.
        if self.actor.state.physical != "none":
            return False
        self._playing = False
        accepted = self.actor.playback_stop()
        if accepted:
            self._service_pending()
            self._refresh_ui()
        return accepted


# Compatibility names make the boundary discoverable to host integrations.
ScopeContext = ScopeRuntime
GizmoScopeRuntime = ScopeRuntime


_RUNTIME = ScopeRuntime()
_GIZMO_CLASS = None
_CLOSE_OPERATOR_CLASS = None
_OPEN_OPERATOR_CLASS = None
_RETRY_OPERATOR_CLASS = None
_SELECT_SCOPE_PAGE_OPERATOR_CLASS = None
_SCOPE_PANEL_CLASS = None
_SCOPE_DRAW_HANDLER = None
_SCOPE_LAST_DRAWN = None
_HANDLERS = {}
_SCENE_REVISIONS = {}
_SOURCE_REVISION = 0
_SOURCE_KEY = None
_DEPSGRAPH_SETTLED = True
_DEPSGRAPH_IN_FLIGHT = {}
_TIMER_REGISTERED = False
_LAST_VIEW_AREA_BY_WINDOW = {}


def runtime():
    return _RUNTIME


def _scene_key(scene):
    pointer = _pointer(scene)
    return pointer if pointer else id(scene)


def _scene_source(scene):
    key = _scene_key(scene)
    frame = int(getattr(scene, "frame_current", 0))
    previous = _SCENE_REVISIONS.get(key)
    if previous is None or previous[1] != frame:
        revision = (previous[0] + 1) if previous is not None else 1
        _SCENE_REVISIONS[key] = (revision, frame)
    else:
        revision = previous[0]
    return revision, "scene:%s:frame:%d" % (key, frame), frame


def _pointer_tuple(value):
    pointer = _pointer(value)
    return pointer if pointer else 0


def _view_area_candidates(window):
    screen = getattr(window, "screen", None)
    areas = getattr(screen, "areas", ()) if screen is not None else ()
    return tuple(area for area in areas
                 if getattr(area, "type", None) == "VIEW_3D")


def _choose_view_area(window, last_used_pointer=0):
    """Choose a live viewport, preferring the last observed one in this window."""
    candidates = _view_area_candidates(window)
    if not candidates:
        return None
    if last_used_pointer:
        for area in candidates:
            if _pointer_tuple(area) == last_used_pointer:
                return area
    return max(
        candidates,
        key=lambda area: max(0, int(getattr(area, "width", 0)))
                         * max(0, int(getattr(area, "height", 0))),
    )


def _view_context(window, area):
    view_layer = getattr(window, "view_layer", None)
    scene = getattr(window, "scene", None)
    return SimpleNamespace(
        window=window, area=area, scene=scene, view_layer=view_layer,
        active_object=getattr(getattr(view_layer, "objects", None), "active", None),
    )


def _remember_view_area(context):
    window = getattr(context, "window", None)
    area = getattr(context, "area", None)
    if window is None or area is None or getattr(area, "type", None) != "VIEW_3D":
        return
    window_id = _pointer_tuple(window)
    area_id = _pointer_tuple(area)
    if window_id and area_id:
        _LAST_VIEW_AREA_BY_WINDOW[window_id] = area_id


def _scope_window_pointer(owner):
    try:
        prefix, window_id, _area_id = owner.split(":")
        if prefix == "view":
            return int(window_id)
    except (AttributeError, TypeError, ValueError):
        pass
    return 0


def _project_node_trees(bpy):
    """Enumerate standalone and datablock-owned trees without duplicates."""
    data = getattr(bpy, "data", None)
    candidates = list(getattr(data, "node_groups", ()))
    for collection_name in ("materials", "worlds", "lights", "cameras", "scenes"):
        for owner in getattr(data, collection_name, ()):
            for name in ("node_tree", "compositing_node_group"):
                tree = getattr(owner, name, None)
                if tree is not None:
                    candidates.append(tree)
    seen = set()
    for tree in candidates:
        identity = _pointer(tree) or id(tree)
        if identity in seen:
            continue
        seen.add(identity)
        yield tree


def _matrix_values(matrix):
    try:
        return tuple(round(float(value), 8) for row in matrix for value in row)
    except (TypeError, ValueError, ReferenceError):
        return ()


def _effective_shading_source(scene, shading):
    """Freeze only lighting controls that affect the active viewport mode."""
    mode = str(getattr(shading, "type", ""))
    use_scene_world = bool(getattr(shading, "use_scene_world", False))
    use_scene_lights = bool(getattr(shading, "use_scene_lights", False))
    material_preview = mode == "MATERIAL"
    scene_rendered = mode == "RENDERED"
    studio_active = (
        mode in {"SOLID", "WIREFRAME"}
        or (material_preview and not use_scene_world)
    )
    studio = (
        str(getattr(shading, "light", "")),
        str(getattr(shading, "studio_light", "")),
        round(float(getattr(shading, "studiolight_rotate_z", 0.0)), 8),
        round(float(getattr(shading, "studiolight_intensity", 0.0)), 8),
    ) if studio_active else ("", "", 0.0, 0.0)
    if scene_rendered:
        engine = str(getattr(getattr(scene, "render", None), "engine", ""))
    elif material_preview:
        engine = "BLENDER_EEVEE_NEXT"
    else:
        engine = ""
    return (mode, engine, studio, use_scene_world, use_scene_lights)


def _viewport_source(context):
    scene = getattr(context, "scene", None)
    area = getattr(context, "area", None)
    window = getattr(context, "window", None)
    if scene is None or area is None or getattr(area, "type", None) != "VIEW_3D":
        return None
    space = getattr(getattr(area, "spaces", None), "active", None)
    shading = getattr(space, "shading", None)
    region_3d = getattr(space, "region_3d", None)
    object_value = getattr(context, "active_object", None)
    material = getattr(object_value, "active_material", None)
    world = getattr(scene, "world", None)
    source = (
        _pointer_tuple(window), _pointer_tuple(area), _pointer_tuple(scene),
        _pointer_tuple(getattr(context, "view_layer", None)),
        _pointer_tuple(object_value), _pointer_tuple(material),
        _pointer_tuple(world), _pointer_tuple(getattr(scene, "camera", None)),
        int(getattr(scene, "frame_current", 0)),
        _effective_shading_source(scene, shading),
        _matrix_values(getattr(region_3d, "view_matrix", ())),
        _matrix_values(getattr(region_3d, "perspective_matrix", ())),
    )
    return source


def _target_source(bpy, identity):
    """Return the installed evaluator identity for the scope's selected owner."""
    if identity is None:
        return None
    try:
        tree_id, node_id = (int(value) for value in identity.removeprefix("node:").split(":"))
    except (AttributeError, TypeError, ValueError):
        return None
    for tree in _project_node_trees(bpy):
        if _pointer(tree) != tree_id:
            continue
        for node in getattr(tree, "nodes", ()):
            if _pointer(node) != node_id:
                continue
            backend = node.get("perceptual_grade_next_backend", "")
            if backend not in {"native_grade_graph", "native_stack_lut"}:
                return None
            return (
                tree_id, node_id, backend,
                int(node.get("perceptual_grade_next_applied_revision", 0)),
                str(node.get("perceptual_grade_next_stack_quality_tier", "")),
                str(node.get("perceptual_grade_next_stack_evaluator", "")),
                _pointer(getattr(node, "node_tree", None)),
            )
    return None


def _observe_active_view():
    global _SOURCE_KEY, _SOURCE_REVISION
    try:
        import bpy
        context = _owned_view_context(bpy)
    except (ImportError, AttributeError, RuntimeError):
        return
    if context is None or not _RUNTIME.visible:
        return
    viewport_source = _viewport_source(context)
    if viewport_source is None:
        return
    # The scope follows the output actually installed in the viewport. A
    # desired edit does not change provenance until its evaluator is accepted.
    source = (viewport_source, _target_source(bpy, _RUNTIME.target_owner))
    if source != _SOURCE_KEY:
        _SOURCE_KEY = source
        _SOURCE_REVISION += 1
    scene = getattr(context, "scene", None)
    frame = int(getattr(scene, "frame_current", 0))
    source_id = "viewport:" + repr(source)
    _RUNTIME.observe(_SOURCE_REVISION, source_id, frame=frame)


def _owned_view_context(bpy):
    manager = getattr(getattr(bpy, "context", None), "window_manager", None)
    if manager is None:
        return None
    for window in getattr(manager, "windows", ()):
        screen = getattr(window, "screen", None)
        view_layer = getattr(window, "view_layer", None)
        scene = getattr(window, "scene", None)
        for area in getattr(screen, "areas", ()):
            if getattr(area, "type", None) != "VIEW_3D":
                continue
            context = _view_context(window, area)
            if context_owner(context) == _RUNTIME.view.owner:
                return context
    return None


def _recover_owned_view_context(bpy):
    """Transfer to a surviving viewport in the same window after area loss."""
    owner = _RUNTIME.view.owner
    window_id = _scope_window_pointer(owner)
    manager = getattr(getattr(bpy, "context", None), "window_manager", None)
    if manager is None or not window_id:
        return None
    window = next((candidate for candidate in getattr(manager, "windows", ())
                   if _pointer_tuple(candidate) == window_id), None)
    if window is None:
        return None
    preferred = _LAST_VIEW_AREA_BY_WINDOW.get(window_id, 0)
    area = _choose_view_area(window, preferred)
    if area is None:
        return None
    context = _view_context(window, area)
    next_owner = context_owner(context)
    if next_owner != owner and not _RUNTIME.move(next_owner):
        return None
    _LAST_VIEW_AREA_BY_WINDOW[window_id] = _pointer_tuple(area)
    try:
        area.spaces.active.show_gizmo = True
    except (AttributeError, ReferenceError, RuntimeError):
        pass
    _tag_view_redraw(window)
    return context


def _frame_change_pre(scene):
    global _DEPSGRAPH_SETTLED
    if not _RUNTIME.visible:
        return
    revision, source_id, frame = _scene_source(scene)
    _DEPSGRAPH_SETTLED = False
    _RUNTIME.set_native_ready(False, source_revision=revision,
                              source_id=source_id, frame=frame)


def _frame_change_post(scene):
    global _DEPSGRAPH_SETTLED
    if not _RUNTIME.visible:
        return
    revision, source_id, frame = _scene_source(scene)
    # Blender can finish dependency updates before frame_change_post. Preserve
    # the barrier only when a dependency update is still in flight; otherwise
    # the timer may service this settled frame immediately.
    _RUNTIME.observe(revision, source_id, frame=frame)
    _DEPSGRAPH_SETTLED = not _DEPSGRAPH_IN_FLIGHT


def _depsgraph_update_pre(_scene, _depsgraph):
    global _DEPSGRAPH_SETTLED
    key = _scene_key(_scene)
    _DEPSGRAPH_SETTLED = False
    _DEPSGRAPH_IN_FLIGHT[key] = _DEPSGRAPH_IN_FLIGHT.get(key, 0) + 1
    if _RUNTIME.visible:
        _RUNTIME.set_native_ready(False)


def _depsgraph_update_post(scene, _depsgraph):
    global _DEPSGRAPH_SETTLED
    key = _scene_key(scene)
    count = _DEPSGRAPH_IN_FLIGHT.get(key, 0)
    if count <= 1:
        _DEPSGRAPH_IN_FLIGHT.pop(key, None)
    else:
        _DEPSGRAPH_IN_FLIGHT[key] = count - 1
    _DEPSGRAPH_SETTLED = not _DEPSGRAPH_IN_FLIGHT


def _native_readers_idle():
    """Conservatively reject capture while Blender reports native readers."""
    try:
        import bpy
    except ImportError:
        return False
    manager = getattr(bpy.context, "window_manager", None)
    if manager is not None and getattr(manager, "is_interface_locked", False):
        return False
    job_probe = getattr(getattr(bpy, "app", None), "is_job_running", None)
    if job_probe is not None:
        for job in ("RENDER", "RENDER_PREVIEW", "OBJECT_BAKE", "COMPOSITE"):
            try:
                if job_probe(job):
                    return False
            except (TypeError, RuntimeError):
                return False
    for window in getattr(manager, "windows", ()) if manager is not None else ():
        for operator in getattr(window, "modal_operators", ()):
            if getattr(operator, "bl_idname", "") in {
                    "OBJECT_OT_lightprobe_cache_bake", "OBJECT_OT_bake_image"}:
                return False
    return True


def _animation_playback_pre(_scene):
    if _RUNTIME.visible:
        _RUNTIME.playback_start()


def _animation_playback_post(_scene):
    if _RUNTIME.visible:
        _poll_playback()


def _poll_playback():
    if not _RUNTIME.visible:
        return
    try:
        import bpy
        playing = any(getattr(window.screen, "is_animation_playing", False)
                      for manager in bpy.data.window_managers
                      for window in manager.windows)
    except (ImportError, AttributeError, ReferenceError, RuntimeError):
        return
    if playing and not _RUNTIME.playing:
        _RUNTIME.playback_start()
    elif not playing and _RUNTIME.playing:
        _RUNTIME.playback_stop()


def _poll_timer():
    global _TIMER_REGISTERED
    if not _TIMER_REGISTERED:
        return None
    from .scope_capture import service_pending_releases

    service_pending_releases()
    _poll_playback()
    if _RUNTIME.visible:
        try:
            import bpy
            if not _target_exists(bpy, _RUNTIME.target_owner):
                _RUNTIME.close()
                _tag_view_redraw()
                return 0.1
            if _owned_view_context(bpy) is None:
                if _recover_owned_view_context(bpy) is None:
                    _RUNTIME.close()
                    _tag_view_redraw()
                    return 0.1
        except (ImportError, AttributeError, ReferenceError, RuntimeError):
            _RUNTIME.close()
            return 0.1
    if _RUNTIME.visible and not _RUNTIME.playing and _DEPSGRAPH_SETTLED:
        if _native_readers_idle():
            _RUNTIME.set_native_ready(True)
            _observe_active_view()
            _capture_pending_view(bpy)
    return 0.1


def _target_exists(bpy, identity):
    if identity is None:
        return True
    try:
        tree_id, node_id = (int(value) for value in identity.removeprefix("node:").split(":"))
    except (AttributeError, TypeError, ValueError):
        return False
    for tree in _project_node_trees(bpy):
        if _pointer(tree) != tree_id:
            continue
        for node in getattr(tree, "nodes", ()):
            if _pointer(node) == node_id:
                return node.get("perceptual_grade_next_backend") in {
                    "native_grade_graph", "native_stack_lut",
                }
    return False


def _tag_view_redraw(window=None):
    try:
        import bpy
        windows = (window,) if window is not None else tuple(bpy.context.window_manager.windows)
    except (ImportError, AttributeError, RuntimeError):
        return
    for current_window in windows:
        for area in getattr(getattr(current_window, "screen", None), "areas", ()):
            if getattr(area, "type", None) == "VIEW_3D":
                try:
                    area.tag_redraw()
                except (AttributeError, ReferenceError, RuntimeError):
                    pass


def _scope_status_label(status):
    return {
        "closed": "Scope closed",
        "idle": "Waiting for a source",
        "waiting": "Waiting for capture",
        "waiting_for_evaluation": "Waiting for Blender evaluation",
        "capturing": "Capturing scope input",
        "analyzing": "Analyzing scope input",
        "result_ready": "New result ready to display",
        "ready": "Scope result current",
        "retiring": "Waiting for native cleanup",
        "retiring_after_failure": "Capture failed; waiting for native cleanup",
        "failed": "Capture failed",
        "paused": "Paused during playback",
    }.get(status, "Scope status unavailable")


def _draw_scope_panel(layout, _context=None):
    presentation = _RUNTIME.presentation
    layout.label(text=_scope_status_label(presentation.status))
    if presentation.displayed is not None:
        displayed = presentation.displayed
        layout.label(text="Last result: request %d" % displayed.request)
        layout.label(text="Source revision %d" % displayed.source_revision)
        if presentation.result_stale:
            layout.label(text="Previous result retained", icon="INFO")
        else:
            layout.label(text="Result is current", icon="CHECKMARK")
        page_row = layout.row(align=True)
        for page in _SCOPE_PAGES:
            page_row.operator(
                "view3d.pg_next_scope_page",
                text=_SCOPE_PAGE_LABELS[page],
                depress=presentation.selected_page == page,
            ).page = page
        analysis = displayed.payload
        statistics = getattr(analysis, "statistics", analysis)
        if all(hasattr(statistics, name) for name in (
                "width", "height", "sample_count", "minimum", "mean", "maximum")):
            layout.label(
                text="%d x %d | %d pixels" % (
                    statistics.width, statistics.height,
                    statistics.sample_count,
                )
            )
            for label, values in (
                    ("Minimum", statistics.minimum),
                    ("Mean", statistics.mean),
                    ("Maximum", statistics.maximum)):
                layout.label(
                    text="%s RGB: %.6g  %.6g  %.6g" % ((label,) + values)
                )
    else:
        layout.label(text="No displayed result yet")
    if presentation.failure is not None:
        layout.label(text="Capture failed", icon="ERROR")
        if presentation.failure.diagnostic:
            layout.label(text="Details: " + presentation.failure.diagnostic[:120])
    row = layout.row(align=True)
    if presentation.can_retry:
        row.operator("view3d.pg_next_retry_scope", text="Retry", icon="FILE_REFRESH")
    row.operator("view3d.pg_next_close_scope", text="Close", icon="CANCEL")


def _draw_triangles(shader, vertices, color):
    if not vertices:
        return
    from gpu_extras.batch import batch_for_shader

    batch = batch_for_shader(shader, "TRIS", {"pos": vertices})
    shader.bind()
    shader.uniform_float("color", color)
    batch.draw(shader)


def _rect_vertices(x0, y0, x1, y1):
    return ((x0, y0), (x1, y0), (x1, y1),
            (x0, y0), (x1, y1), (x0, y1))


def _draw_density_cells(shader, values, width, height, x0, y0, chart_width,
                        chart_height, color, *, peak=None, column_major=False):
    peak = max(values, default=0) if peak is None else peak
    if peak <= 0:
        return
    buckets = [[] for _ in range(8)]
    cell_width = chart_width / width
    cell_height = chart_height / height
    for y in range(height):
        for x in range(width):
            index = x * height + y if column_major else y * width + x
            value = values[index]
            if value <= 0:
                continue
            bucket = min(7, max(0, (value * 8 - 1) // peak))
            left = x0 + x * cell_width
            bottom = y0 + y * cell_height
            buckets[bucket].extend(_rect_vertices(
                left, bottom, left + cell_width + 0.2, bottom + cell_height + 0.2,
            ))
    for bucket, vertices in enumerate(buckets):
        if vertices:
            alpha = 0.14 + 0.12 * bucket
            _draw_triangles(shader, vertices, (*color, alpha))


def _draw_scope_overlay():
    """Render the selected immutable chart over the owning 3D View region."""
    global _SCOPE_LAST_DRAWN
    try:
        import bpy
        _remember_view_area(bpy.context)
    except (ImportError, AttributeError, ReferenceError, RuntimeError):
        return
    if not _RUNTIME.visible or _RUNTIME._capture_rendering:
        return
    blend = depth = None
    gpu_module = None
    changed_gpu_state = False
    try:
        import blf
        import gpu
        gpu_module = gpu
        from gpu_extras.batch import batch_for_shader

        context = bpy.context
        if (context_owner(context) != _RUNTIME.view.owner
                or getattr(getattr(context, "area", None), "type", None) != "VIEW_3D"
                or getattr(getattr(context, "region", None), "type", None) != "WINDOW"):
            return
        visual = _RUNTIME.displayed_visual
        analysis = getattr(visual, "payload", None)
        if visual is None or not hasattr(analysis, "histogram_rgb"):
            return

        region = context.region
        if region.width < 160 or region.height < 160:
            return
        margin = 18
        chart_width = max(96, min(360, region.width - margin * 2))
        chart_height = max(96, min(220, region.height - margin * 2))
        x0 = margin
        y0 = region.height - margin - chart_height
        x1 = x0 + chart_width
        y1 = y0 + chart_height
        blend = gpu.state.blend_get()
        depth = gpu.state.depth_test_get()
        changed_gpu_state = True
        gpu.state.blend_set("ALPHA")
        gpu.state.depth_test_set("NONE")
        shader = gpu.shader.from_builtin("UNIFORM_COLOR")
        background = _rect_vertices(x0 - 10, y0 - 34, x1 + 10, y1 + 10)
        _draw_triangles(shader, background, (0.025, 0.03, 0.035, 0.82))
        chart_x = x0 + 36
        chart_y = y0 + 26
        plot_width = chart_width - 50
        plot_height = chart_height - 55
        if _RUNTIME.selected_page == "vectorscope":
            plot_width = plot_height = min(plot_width, plot_height)

        grid = []
        for tick in range(5):
            y = chart_y + plot_height * tick / 4
            grid.extend(((chart_x, y), (chart_x + plot_width, y)))
        batch = batch_for_shader(shader, "LINES", {"pos": grid})
        shader.bind()
        shader.uniform_float("color", (0.72, 0.76, 0.8, 0.22))
        batch.draw(shader)

        if _RUNTIME.selected_page == "histogram":
            peak = max(max(channel, default=0) for channel in analysis.histogram_rgb)
            colors = ((1.0, 0.18, 0.12), (0.15, 0.92, 0.22), (0.2, 0.45, 1.0))
            for channel, color in zip(analysis.histogram_rgb, colors):
                vertices = []
                bar_width = plot_width / analysis.histogram_bins
                for index, count in enumerate(channel):
                    top = chart_y + (count / peak * plot_height if peak else 0)
                    vertices.extend(_rect_vertices(
                        chart_x + index * bar_width, chart_y,
                        chart_x + (index + 1) * bar_width, top,
                    ))
                _draw_triangles(shader, vertices, (*color, 0.46))
            x_labels = ("%.4g" % analysis.value_minimum,
                        "%.4g" % ((analysis.value_minimum + analysis.value_maximum) / 2),
                        "%.4g" % analysis.value_maximum)
            y_labels = (str(peak), "0")
        elif _RUNTIME.selected_page == "waveform":
            peak = max(max(channel, default=0) for channel in analysis.waveform_rgb)
            colors = ((1.0, 0.18, 0.12), (0.15, 0.92, 0.22), (0.2, 0.45, 1.0))
            for channel, color in zip(analysis.waveform_rgb, colors):
                _draw_density_cells(
                    shader, channel, analysis.waveform_width,
                    analysis.waveform_height, chart_x, chart_y, plot_width,
                    plot_height, color, peak=peak, column_major=True,
                )
            x_labels = ("0", "image x", str(analysis.statistics.width))
            y_labels = ("%.4g" % analysis.value_maximum,
                        "%.4g" % analysis.value_minimum)
        else:
            size = analysis.vectorscope_size
            _draw_density_cells(
                shader, analysis.vectorscope_rg_bg, size, size, chart_x, chart_y,
                plot_width, plot_height, (0.95, 0.28, 0.76),
            )
            center_x = chart_x + plot_width / 2
            center_y = chart_y + plot_height / 2
            radius_x = plot_width * 0.48
            radius_y = plot_height * 0.48
            circle = []
            for index in range(64):
                angle0 = index * 2.0 * math.pi / 64
                angle1 = (index + 1) * 2.0 * math.pi / 64
                circle.extend((
                    (center_x + radius_x * math.cos(angle0),
                     center_y + radius_y * math.sin(angle0)),
                    (center_x + radius_x * math.cos(angle1),
                     center_y + radius_y * math.sin(angle1)),
                ))
            batch = batch_for_shader(shader, "LINES", {"pos": circle})
            shader.bind()
            shader.uniform_float("color", (0.9, 0.9, 0.92, 0.5))
            batch.draw(shader)
            axis_vertices = (
                (center_x, chart_y), (center_x, chart_y + plot_height),
                (chart_x, center_y), (chart_x + plot_width, center_y),
            )
            batch = batch_for_shader(shader, "LINES", {"pos": axis_vertices})
            shader.bind()
            shader.uniform_float("color", (0.9, 0.9, 0.92, 0.38))
            batch.draw(shader)
            x_labels = ("-%.3g" % analysis.vectorscope_axis_limit,
                        "R-G", "%.3g" % analysis.vectorscope_axis_limit)
            y_labels = ("%.3g" % analysis.vectorscope_axis_limit,
                        "-%.3g" % analysis.vectorscope_axis_limit)

        font_id = 0
        blf.size(font_id, 12)
        freshness = "Updating" if _RUNTIME.presentation.result_stale else "Current"
        title = "%s | %s | request %d | source %d" % (
            _SCOPE_PAGE_LABELS[_RUNTIME.selected_page], freshness,
            visual.request, visual.source_revision,
        )
        blf.position(font_id, x0, y1 - 20, 0)
        blf.color(font_id, 0.95, 0.96, 0.98, 1.0)
        blf.draw(font_id, title)
        for position, text in zip((chart_x, chart_x + plot_width / 2, chart_x + plot_width),
                                  x_labels):
            blf.position(font_id, position - 18, chart_y - 17, 0)
            blf.draw(font_id, text)
        for position, text in zip((chart_y + plot_height - 5, chart_y - 4), y_labels):
            blf.position(font_id, x0 + 2, position, 0)
            blf.draw(font_id, text)
        if _RUNTIME.selected_page == "vectorscope":
            blf.position(font_id, chart_x, chart_y + plot_height + 3, 0)
            blf.draw(font_id, "B-G")
        else:
            blf.position(font_id, chart_x, chart_y + plot_height + 3, 0)
            blf.draw(font_id, "RGB" if _RUNTIME.selected_page == "histogram"
                     else "scene-linear RGB")
        _SCOPE_LAST_DRAWN = (visual.token.token, _RUNTIME.selected_page)
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return
    finally:
        if changed_gpu_state:
            try:
                gpu_module.state.blend_set(blend)
                gpu_module.state.depth_test_set(depth)
            except (AttributeError, ReferenceError, RuntimeError):
                pass


def _capture_pending_view(bpy):
    """Run the one synchronous native capture for the newest unstarted demand."""
    state = _RUNTIME.state
    if (not _RUNTIME.visible or _RUNTIME.playing or not _RUNTIME.native_ready
            or state.phase != "healthy" or state.request <= state.begun_request):
        return None
    from .scope_capture import capture_viewport

    return capture_viewport(_RUNTIME, bpy_module=bpy)


def _load_pre(*_args):
    global _SOURCE_KEY
    _RUNTIME.close()
    _SOURCE_KEY = None
    _tag_view_redraw()


def _register_handler(name, callback):
    import bpy
    handlers = getattr(getattr(bpy, "app", None), "handlers", None)
    target = getattr(handlers, name, None)
    if target is None:
        return
    if name in _HANDLERS:
        if _HANDLERS[name] not in target:
            target.append(_HANDLERS[name])
        return
    persistent = getattr(handlers, "persistent", None)
    registered = persistent(callback) if persistent is not None else callback
    try:
        registered._bpy_persistent = True
    except (AttributeError, TypeError):
        pass
    if registered not in target:
        target.append(registered)
    _HANDLERS[name] = registered


def _unregister_handlers():
    try:
        import bpy
    except ImportError:
        bpy = None
    handlers = getattr(getattr(bpy, "app", None), "handlers", None)
    for name, callback in tuple(_HANDLERS.items()):
        target = getattr(handlers, name, None) if handlers is not None else None
        if target is not None:
            while callback in target:
                target.remove(callback)
    _HANDLERS.clear()


def register():
    """Register the one global Gizmo group when Blender exposes the API."""
    global _CLOSE_OPERATOR_CLASS, _GIZMO_CLASS, _OPEN_OPERATOR_CLASS
    global _RETRY_OPERATOR_CLASS
    global _SELECT_SCOPE_PAGE_OPERATOR_CLASS
    global _SCOPE_PANEL_CLASS
    if _GIZMO_CLASS is not None:
        return _GIZMO_CLASS
    try:
        import bpy
    except ImportError:
        return None
    gizmo_group = getattr(getattr(bpy, "types", None), "GizmoGroup", None)
    operator_type = getattr(getattr(bpy, "types", None), "Operator", None)
    panel_type = getattr(getattr(bpy, "types", None), "Panel", None)
    if gizmo_group is None or operator_type is None or panel_type is None:
        return None

    class PGNEXT_OT_close_scope(operator_type):
        bl_idname = "view3d.pg_next_close_scope"
        bl_label = "Close Perceptual Grade Scope"

        def execute(self, context):
            _RUNTIME.close()
            _tag_view_redraw()
            return {"FINISHED"}

    class PGNEXT_OT_open_scope(operator_type):
        bl_idname = "node.pg_next_open_scope"
        bl_label = "Open Perceptual Grade Scope"

        @classmethod
        def poll(cls, context):
            node = getattr(getattr(context, "space_data", None), "edit_tree", None)
            active = getattr(getattr(node, "nodes", None), "active", None)
            return bool(active and active.get("perceptual_grade_next_backend") in {
                "native_grade_graph", "native_stack_lut",
            })

        def execute(self, context):
            tree = context.space_data.edit_tree
            node = tree.nodes.active
            window = getattr(context, "window", None)
            window_id = _pointer_tuple(window)
            area = _choose_view_area(
                window, _LAST_VIEW_AREA_BY_WINDOW.get(window_id, 0),
            )
            if window is None or area is None:
                self.report({"WARNING"}, "Open a 3D View in this window first")
                return {"CANCELLED"}
            try:
                tree_id = int(tree.as_pointer())
                node_id = int(node.as_pointer())
                if not tree_id or not node_id:
                    raise RuntimeError("The selected Grade owner is no longer available")
                owner = "node:%d:%d" % (tree_id, node_id)
                view_context = SimpleNamespace(window=window, area=area)
                _RUNTIME.open_context(view_context, target_owner=owner)
                _LAST_VIEW_AREA_BY_WINDOW[window_id] = _pointer_tuple(area)
                try:
                    area.spaces.active.show_gizmo = True
                except (AttributeError, ReferenceError, RuntimeError):
                    pass
                _tag_view_redraw(window)
                _observe_active_view()
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError) as error:
                self.report({"WARNING"}, str(error))
                return {"CANCELLED"}
            return {"FINISHED"}

    class PGNEXT_OT_retry_scope(operator_type):
        bl_idname = "view3d.pg_next_retry_scope"
        bl_label = "Retry Scope Capture"

        @classmethod
        def poll(cls, _context):
            return _RUNTIME.presentation.can_retry

        def execute(self, _context):
            if _RUNTIME.retry() is None:
                return {"CANCELLED"}
            _tag_view_redraw()
            return {"FINISHED"}

    class PGNEXT_OT_select_scope_page(operator_type):
        bl_idname = "view3d.pg_next_scope_page"
        bl_label = "Select Scope Page"

        page: bpy.props.EnumProperty(
            name="Scope",
            items=tuple((page, _SCOPE_PAGE_LABELS[page], "") for page in _SCOPE_PAGES),
            default="histogram",
        )

        def execute(self, _context):
            if not _RUNTIME.select_page(self.page):
                return {"CANCELLED"}
            _tag_view_redraw()
            return {"FINISHED"}

    class PGNEXT_PT_scope_panel(panel_type):
        bl_idname = "VIEW3D_PT_pg_next_scope"
        bl_label = "Perceptual Grade Scope"
        bl_space_type = "VIEW_3D"
        bl_region_type = "UI"
        bl_category = "Perceptual Grade"

        @classmethod
        def poll(cls, context):
            return bool(
                _RUNTIME.visible
                and _RUNTIME.view.owner == context_owner(context)
            )

        def draw(self, _context):
            _draw_scope_panel(self.layout, _context)

    registered = []
    try:
        for registered_class in (
                PGNEXT_OT_open_scope, PGNEXT_OT_close_scope,
                PGNEXT_OT_retry_scope, PGNEXT_OT_select_scope_page):
            bpy.utils.register_class(registered_class)
            registered.append(registered_class)
    except (AttributeError, RuntimeError):
        for registered_class in reversed(registered):
            try:
                bpy.utils.unregister_class(registered_class)
            except (AttributeError, RuntimeError):
                pass
        return None
    _OPEN_OPERATOR_CLASS = PGNEXT_OT_open_scope
    _CLOSE_OPERATOR_CLASS = PGNEXT_OT_close_scope
    _RETRY_OPERATOR_CLASS = PGNEXT_OT_retry_scope
    _SELECT_SCOPE_PAGE_OPERATOR_CLASS = PGNEXT_OT_select_scope_page

    class PGNEXT_GGT_scope(gizmo_group):
        bl_idname = "PGNEXT_GGT_scope"
        bl_label = "Perceptual Grade Scope"
        bl_space_type = "VIEW_3D"
        bl_region_type = "WINDOW"
        bl_options = {"PERSISTENT", "SHOW_MODAL_ALL"}

        @classmethod
        def poll(cls, context):
            return bool(_RUNTIME.visible and not _RUNTIME.actor.state.closing
                        and _RUNTIME.view.owner == context_owner(context))

        def setup(self, context):
            self._scope_runtime = _RUNTIME
            # A button gizmo gives Blender a real, dismissible foreground
            # handle while all semantic authority remains in ScopeRuntime.
            try:
                self._dismiss = self.gizmos.new("GIZMO_GT_button_2d")
                self._dismiss.draw_options = {"BACKDROP", "OUTLINE"}
                self._dismiss.color = (0.15, 0.15, 0.15)
                self._dismiss.alpha = 0.65
                self._dismiss.scale_basis = 8
                self._dismiss.icon = "X"
                self._dismiss.target_set_operator("view3d.pg_next_close_scope")
                self._retry = self.gizmos.new("GIZMO_GT_button_2d")
                self._retry.draw_options = {"BACKDROP", "OUTLINE"}
                self._retry.color = (0.15, 0.15, 0.15)
                self._retry.alpha = 0.85
                self._retry.scale_basis = 8
                self._retry.icon = "FILE_REFRESH"
                self._retry.target_set_operator("view3d.pg_next_retry_scope")
            except (AttributeError, RuntimeError):
                self._dismiss = None
                self._retry = None

        def draw_prepare(self, context):
            if self._dismiss is None:
                return
            self._dismiss.hide = not _RUNTIME.visible
            self._retry.hide = not _RUNTIME.presentation.can_retry
            try:
                from mathutils import Matrix
                region = context.region
                self._dismiss.matrix_basis = Matrix.Translation(
                    (region.width - 20, region.height - 20, 0.0)
                )
                self._retry.matrix_basis = Matrix.Translation(
                    (region.width - 42, region.height - 20, 0.0)
                )
            except (ImportError, AttributeError, ReferenceError, RuntimeError):
                pass

        def invoke(self, context, event):
            _RUNTIME.close()
            return {"FINISHED"}

    try:
        bpy.utils.register_class(PGNEXT_GGT_scope)
    except (AttributeError, RuntimeError):
        for registered_class in reversed(registered):
            try:
                bpy.utils.unregister_class(registered_class)
            except (AttributeError, RuntimeError):
                pass
        _CLOSE_OPERATOR_CLASS = None
        _OPEN_OPERATOR_CLASS = None
        _RETRY_OPERATOR_CLASS = None
        _SELECT_SCOPE_PAGE_OPERATOR_CLASS = None
        return None
    _GIZMO_CLASS = PGNEXT_GGT_scope
    try:
        bpy.utils.register_class(PGNEXT_PT_scope_panel)
    except (AttributeError, RuntimeError):
        bpy.utils.unregister_class(_GIZMO_CLASS)
        _GIZMO_CLASS = None
        for registered_class in reversed(registered):
            try:
                bpy.utils.unregister_class(registered_class)
            except (AttributeError, RuntimeError):
                pass
        _CLOSE_OPERATOR_CLASS = None
        _OPEN_OPERATOR_CLASS = None
        _RETRY_OPERATOR_CLASS = None
        _SELECT_SCOPE_PAGE_OPERATOR_CLASS = None
        return None
    _SCOPE_PANEL_CLASS = PGNEXT_PT_scope_panel
    global _SCOPE_DRAW_HANDLER
    try:
        _SCOPE_DRAW_HANDLER = bpy.types.SpaceView3D.draw_handler_add(
            _draw_scope_overlay, (), "WINDOW", "POST_PIXEL",
        )
    except (AttributeError, RuntimeError):
        _SCOPE_DRAW_HANDLER = None
    _register_handler("frame_change_pre", _frame_change_pre)
    _register_handler("frame_change_post", _frame_change_post)
    _register_handler("depsgraph_update_pre", _depsgraph_update_pre)
    _register_handler("depsgraph_update_post", _depsgraph_update_post)
    _register_handler("animation_playback_pre", _animation_playback_pre)
    _register_handler("animation_playback_post", _animation_playback_post)
    _register_handler("load_pre", _load_pre)
    global _TIMER_REGISTERED
    _TIMER_REGISTERED = True
    try:
        if not bpy.app.timers.is_registered(_poll_timer):
            bpy.app.timers.register(_poll_timer, first_interval=0.1)
    except (AttributeError, RuntimeError):
        pass
    return _GIZMO_CLASS


def unregister():
    global _CLOSE_OPERATOR_CLASS, _GIZMO_CLASS, _OPEN_OPERATOR_CLASS, _TIMER_REGISTERED
    global _RETRY_OPERATOR_CLASS
    global _SELECT_SCOPE_PAGE_OPERATOR_CLASS
    global _SCOPE_PANEL_CLASS
    global _SCOPE_DRAW_HANDLER
    global _SCOPE_LAST_DRAWN
    try:
        import bpy
    except ImportError:
        bpy = None
    _unregister_handlers()
    _TIMER_REGISTERED = False
    if _SCOPE_DRAW_HANDLER is not None and bpy is not None:
        try:
            bpy.types.SpaceView3D.draw_handler_remove(_SCOPE_DRAW_HANDLER, "WINDOW")
        except (AttributeError, ReferenceError, RuntimeError):
            pass
    _SCOPE_DRAW_HANDLER = None
    _SCOPE_LAST_DRAWN = None
    if bpy is not None:
        try:
            if bpy.app.timers.is_registered(_poll_timer):
                bpy.app.timers.unregister(_poll_timer)
        except (AttributeError, RuntimeError):
            pass
    if _GIZMO_CLASS is not None and bpy is not None:
        try:
            bpy.utils.unregister_class(_GIZMO_CLASS)
        except (AttributeError, RuntimeError):
            pass
    if _SCOPE_PANEL_CLASS is not None and bpy is not None:
        try:
            bpy.utils.unregister_class(_SCOPE_PANEL_CLASS)
        except (AttributeError, RuntimeError):
            pass
    if _CLOSE_OPERATOR_CLASS is not None and bpy is not None:
        try:
            bpy.utils.unregister_class(_CLOSE_OPERATOR_CLASS)
        except (AttributeError, RuntimeError):
            pass
    if _OPEN_OPERATOR_CLASS is not None and bpy is not None:
        try:
            bpy.utils.unregister_class(_OPEN_OPERATOR_CLASS)
        except (AttributeError, RuntimeError):
            pass
    if _RETRY_OPERATOR_CLASS is not None and bpy is not None:
        try:
            bpy.utils.unregister_class(_RETRY_OPERATOR_CLASS)
        except (AttributeError, RuntimeError):
            pass
    if _SELECT_SCOPE_PAGE_OPERATOR_CLASS is not None and bpy is not None:
        try:
            bpy.utils.unregister_class(_SELECT_SCOPE_PAGE_OPERATOR_CLASS)
        except (AttributeError, RuntimeError):
            pass
    _GIZMO_CLASS = None
    _CLOSE_OPERATOR_CLASS = None
    _OPEN_OPERATOR_CLASS = None
    _RETRY_OPERATOR_CLASS = None
    _SELECT_SCOPE_PAGE_OPERATOR_CLASS = None
    _SCOPE_PANEL_CLASS = None
    _RUNTIME.close()


__all__ = (
    "GizmoScopeRuntime", "ScopeContext", "ScopeDemand", "ScopeFailure",
    "ScopePresentation", "ScopeRuntime", "ScopeVisual", "context_owner",
    "_draw_scope_overlay", "_draw_scope_panel",
    "register", "runtime", "unregister",
)
