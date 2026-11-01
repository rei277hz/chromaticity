"""Owned Save/Render entry points for the Next Blender product.

The controller keeps the user confirmation phase outside the portable project
machine.  Once confirmation is accepted, the checked gateway owns preparation
and invokes Blender exactly once.  Blender callbacks remain at this module's
edge so the core and product tests can exercise the policy without importing
``bpy``.
"""

from dataclasses import dataclass, field, replace
import os

from .output_gateway import OutputGateway


@dataclass(frozen=True)
class SaveOptions:
    filepath: str = ""
    check_existing: bool = True
    save_as: bool = False
    use_compression: bool = True
    save_modified_images: bool = True
    copy: bool = False
    relative_remap: bool = True
    diagnostics: "SaveDiagnostics" = field(default_factory=lambda: SaveDiagnostics(), compare=False, repr=False)


@dataclass
class SaveDiagnostics:
    unsaved_images: tuple = ()


def modified_image_warning(names):
    names = tuple(names)
    if not names:
        return ""
    preview = ", ".join(names[:3])
    remainder = len(names) - min(len(names), 3)
    if remainder:
        preview += f", and {remainder} more"
    return f"Project saved, but {len(names)} modified Image(s) could not be saved: {preview}"


def _image_destination_snapshot(bpy, image):
    if getattr(image, "packed_file", None) is not None:
        return None
    packed_files = getattr(image, "packed_files", ())
    if packed_files:
        return None
    raw_path = getattr(image, "filepath_raw", "") or getattr(image, "filepath", "")
    if not raw_path:
        return None
    try:
        path = bpy.path.abspath(raw_path)
    except (AttributeError, RuntimeError, TypeError, ValueError):
        path = raw_path
    try:
        stat = os.stat(path)
        signature = (stat.st_mtime_ns, stat.st_size, stat.st_ino)
    except OSError:
        signature = None
    return path, signature


@dataclass(frozen=True)
class RenderOptions:
    animation: bool = False
    scene: str = ""
    write_still: bool = False
    use_viewport: bool = False


class OutputActionController:
    """Coordinate owned confirmation and checked native output operations."""

    def __init__(self, gateway=None, *, confirm=None, refresh=None):
        self.gateway = gateway or OutputGateway()
        self.confirm = confirm or (lambda _kind, _options: True)
        self.refresh = refresh
        self._next_operation = 1
        self._pending_save = {}
        self._pending_render = {}
        self._active_render = None
        self._active_render_scene = None

    def _operation(self):
        operation = max(
            self._next_operation,
            self.gateway.state.save_operation + 1,
            self.gateway.state.render_operation + 1,
        )
        self._next_operation = operation + 1
        return operation

    def _prepare_gate(self):
        if self.refresh is not None:
            return self.refresh() is not False
        return True

    def _refresh_waiting_output(self, kind, operation):
        pending = self._pending_save if kind == "save" else self._pending_render
        phase = "saving" if kind == "save" else "rendering"
        operation_field = "save_operation" if kind == "save" else "render_operation"
        started_field = "save_started" if kind == "save" else "render_started"
        try:
            ready = self._prepare_gate()
        except Exception:
            state = self.gateway.state
            if (state.phase == phase and getattr(state, operation_field) == operation
                    and not getattr(state, started_field)):
                try:
                    if kind == "save":
                        self.cancel_save_wait(operation)
                    else:
                        self.cancel_render_wait(operation)
                except RuntimeError:
                    pass
            pending.pop(operation, None)
            raise

        state = self.gateway.state
        if (state.phase != phase or getattr(state, operation_field) != operation
                or getattr(state, started_field)):
            pending.pop(operation, None)
            return {"CANCELLED"}
        return None if ready else {"RUNNING_MODAL"}

    def _accepted(self, kind, options):
        # Confirmation happens before any gateway event, so cancelling a
        # destination or modified-Image dialog leaves explicit Bakes intact.
        return bool(self.confirm(kind, options))

    def save(self, native, options=None):
        options = options or SaveOptions()
        if not self._accepted("save", options):
            return {"CANCELLED"}
        # Refresh the adapter reference before admitting the operation.  The
        # refresh is an observation only; the gateway transition below still
        # happens before the readiness wait and revokes unfinished Bakes.
        ready = self._prepare_gate()
        if not ready and self.gateway.state.repair_owners:
            raise RuntimeError("Perceptual Grade preparation failed during output")
        operation = self._operation()
        self.gateway.request_save(operation)
        self._pending_save[operation] = (native, options)
        return self.continue_save(operation)

    def save_as(self, native, options=None):
        options = replace(options or SaveOptions(), save_as=True)
        return self.save(native, options)

    def continue_save(self, operation=None):
        if operation is None:
            if len(self._pending_save) != 1:
                raise RuntimeError("No unique Save operation is pending")
            operation = next(iter(self._pending_save))
        pending = self._pending_save.get(operation)
        if pending is None:
            raise RuntimeError("Save operation is stale or not admitted")
        waiting = self._refresh_waiting_output("save", operation)
        if waiting is not None:
            return waiting
        native, options = pending
        try:
            result = self.gateway.invoke_save(operation, lambda: native(options))
        except RuntimeError:
            if (self.gateway.state.phase == "saving"
                    and self.gateway.state.save_operation == operation):
                return {"RUNNING_MODAL"}
            self._pending_save.pop(operation, None)
            raise
        except BaseException:
            self._pending_save.pop(operation, None)
            raise
        self._pending_save.pop(operation, None)
        return result

    def render(self, native, options=None):
        options = options or RenderOptions()
        if not self._accepted("render_animation" if options.animation else "render_image", options):
            return {"CANCELLED"}
        ready = self._prepare_gate()
        if not ready and self.gateway.state.repair_owners:
            raise RuntimeError("Perceptual Grade preparation failed during output")
        operation = self._operation()
        self.gateway.request_render(operation)
        self._pending_render[operation] = (native, options)
        return self.continue_render(operation)

    def continue_render(self, operation=None):
        if operation is not None and self._active_render == operation:
            return {"RUNNING_MODAL"}
        if operation is None:
            if len(self._pending_render) != 1:
                raise RuntimeError("No unique Render operation is pending")
            operation = next(iter(self._pending_render))
        pending = self._pending_render.get(operation)
        if pending is None:
            raise RuntimeError("Render operation is stale or not admitted")
        waiting = self._refresh_waiting_output("render", operation)
        if waiting is not None:
            return waiting
        native, options = pending
        if not options.scene:
            try:
                import bpy
                options = replace(options, scene=bpy.context.scene.name)
            except (ImportError, AttributeError, ReferenceError):
                pass
        try:
            result = self.gateway.invoke_render(operation, lambda: native(options))
            self._pending_render.pop(operation, None)
            self._active_render = operation
            self._active_render_scene = options.scene
            return result
        except RuntimeError:
            if (self.gateway.state.phase == "rendering"
                    and self.gateway.state.render_operation == operation
                    and not self.gateway.state.render_started):
                return {"RUNNING_MODAL"}
            self._pending_render.pop(operation, None)
            raise
        except BaseException:
            self._pending_render.pop(operation, None)
            raise

    def complete_render(self, *, committed=True, operation=None):
        operation = self._active_render if operation is None else operation
        if operation is None:
            raise RuntimeError("No native Render operation is active")
        state = self.gateway.complete_render(operation, committed=committed)
        self._active_render = None
        self._active_render_scene = None
        return state

    @property
    def pending_save_operation(self):
        return next(iter(self._pending_save), None)

    @property
    def pending_render_operation(self):
        return next(iter(self._pending_render), None)

    @property
    def active_render_operation(self):
        return self._active_render

    @property
    def active_render_scene(self):
        return self._active_render_scene

    def cancel_save_wait(self, operation):
        if operation not in self._pending_save:
            raise RuntimeError("Save is no longer waiting for preparation")
        self.gateway.cancel_save_wait(operation)
        self._pending_save.pop(operation, None)

    def cancel_render_wait(self, operation):
        if operation not in self._pending_render:
            raise RuntimeError("Render is no longer waiting for preparation")
        self.gateway.cancel_render_wait(operation)
        self._pending_render.pop(operation, None)


def modified_images_choice(preference, ask_value):
    """Resolve Blender's Always/Ask/Never preference without changing it."""
    preference = str(preference).upper()
    if preference == "ALWAYS":
        return True
    if preference == "NEVER":
        return False
    if preference == "ASK":
        return bool(ask_value)
    raise ValueError(f"Unknown modified-Image preference: {preference}")


_CONTROLLER = None
_MENU_WRAPPERS = []
_CLASSES = ()
_KEYMAP_REDIRECTS = []
_KEYMAP_ITEMS = []


def native_render_terminal(*, committed, scene=None):
    if _CONTROLLER is None or _CONTROLLER._active_render is None:
        return False
    if (scene is not None and _CONTROLLER.active_render_scene
            and getattr(scene, "name", scene) != _CONTROLLER.active_render_scene):
        return False
    try:
        _CONTROLLER.complete_render(committed=committed)
        return True
    except RuntimeError:
        if _CONTROLLER.gateway.workflow.state.phase == "restarting":
            operation = _CONTROLLER._active_render
            _CONTROLLER._active_render = None
            _CONTROLLER._active_render_scene = None
            _CONTROLLER.gateway._native_operations.discard(("render", operation))
            from .restart import receipt
            return receipt("output:%s" % operation)
        return False


def _refresh_blender_gateway(controller):
    """Refresh the gateway's workflow from the current authored owners."""
    import bpy
    from .project_readiness import project_readiness_runtime, refresh_project_readiness
    from .scope_runtime import _project_node_trees

    refresh_project_readiness(tuple(_project_node_trees(bpy)))
    runtime = project_readiness_runtime()
    controller.gateway.workflow = runtime.workflow
    return runtime.snapshot.ready


def _native_save(options):
    import bpy

    values = {"show_save_modified_images_dialog": False}
    if options.filepath:
        values.update(
            filepath=options.filepath,
            check_existing=options.check_existing,
            copy=options.copy,
            relative_remap=options.relative_remap,
        )
    else:
        values["relative_remap"] = options.relative_remap
    # Compression is a native file option.  Do not mutate Blender's remembered
    # default; the accepted design allows that default to differ after reopen.
    if hasattr(options, "use_compression"):
        values["compress"] = options.use_compression
    if options.save_modified_images:
        image_save = getattr(getattr(bpy.ops, "image", None), "save_all_modified", None)
        if image_save is None:
            raise RuntimeError("Blender does not expose its modified-Image save operation")
        modified = tuple(
            (image, _image_destination_snapshot(bpy, image))
            for image in bpy.data.images
            if getattr(image, "is_dirty", False)
        )
        try:
            image_result = image_save("EXEC_DEFAULT")
        except RuntimeError:
            image_result = {"CANCELLED"}
        unsaved = []
        for image, before in modified:
            if before is None:
                continue
            path, old_signature = before
            try:
                stat = os.stat(path)
                new_signature = (stat.st_mtime_ns, stat.st_size, stat.st_ino)
            except OSError:
                new_signature = None
            if new_signature is None or (
                    old_signature is not None and new_signature == old_signature):
                unsaved.append(getattr(image, "name", "Image"))
            elif image_result != {"FINISHED"}:
                unsaved.append(getattr(image, "name", "Image"))
        options.diagnostics.unsaved_images = tuple(unsaved)
    operator = bpy.ops.wm.save_as_mainfile if options.filepath else bpy.ops.wm.save_mainfile
    return operator("EXEC_DEFAULT", **values)


def _native_render(options):
    import bpy

    values = {
        "animation": options.animation,
        "write_still": options.write_still,
        "use_viewport": options.use_viewport,
    }
    if options.scene:
        values["scene"] = options.scene
    return bpy.ops.render.render("INVOKE_DEFAULT", **values)


def _controller():
    global _CONTROLLER
    if _CONTROLLER is None:
        _CONTROLLER = OutputActionController(refresh=lambda: _refresh_blender_gateway(_CONTROLLER))
    return _CONTROLLER


def _copy_key_event(source, target):
    for name in (
        "type", "value", "shift", "ctrl", "alt", "oskey", "key_modifier",
        "repeat", "direction", "any", "head", "tail",
    ):
        if hasattr(source, name) and hasattr(target, name):
            try:
                setattr(target, name, getattr(source, name))
            except (AttributeError, TypeError, ValueError):
                pass


def _redirect_target(operator_id, *, animation=False, incremental=False,
                     copy=False, sequencer_scene=False):
    if operator_id == "wm.save_mainfile":
        return None if incremental else "wm.pg_next_save"
    if operator_id == "wm.save_as_mainfile":
        return None if copy else "wm.pg_next_save_as"
    if operator_id == "render.render":
        if sequencer_scene:
            return None
        return "render.pg_next_render_animation" if animation else "render.pg_next_render_image"
    return None


def _menu_redirect_target(operator_id, *, text):
    """Select only the four ordinary File/Render menu entries in Blender 5.2."""
    if operator_id == "wm.save_mainfile" and text == "Save":
        return "wm.pg_next_save", {"show_save_modified_images_dialog"}
    if operator_id == "wm.save_as_mainfile" and text == "Save As...":
        return "wm.pg_next_save_as", {"show_save_modified_images_dialog"}
    if operator_id == "render.render" and text == "Render Image":
        return "render.pg_next_render_image", set()
    if operator_id == "render.render" and text == "Render Animation":
        return "render.pg_next_render_animation", {"animation"}
    return None


class _OperatorPropertiesProxy:
    """Adapt native menu assignments to the owned operator's available options."""

    def __init__(self, properties, ignored):
        object.__setattr__(self, "_properties", properties)
        object.__setattr__(self, "_ignored", ignored)

    def __getattr__(self, name):
        return getattr(self._properties, name)

    def __setattr__(self, name, value):
        if name not in self._ignored:
            setattr(self._properties, name, value)


class _RedirectingMenuLayout:
    """Forward layout calls, changing only the selected native operator ids."""

    def __init__(self, layout):
        object.__setattr__(self, "_layout", layout)

    def __getattr__(self, name):
        return getattr(self._layout, name)

    def __setattr__(self, name, value):
        if name == "_layout":
            object.__setattr__(self, name, value)
        else:
            setattr(self._layout, name, value)

    def operator(self, operator_id, *args, **kwargs):
        target = _menu_redirect_target(operator_id, text=kwargs.get("text"))
        if target is None:
            return self._layout.operator(operator_id, *args, **kwargs)
        target_id, ignored = target
        previous_context = self._layout.operator_context
        try:
            # The native saved-file Save entry executes immediately. The owned
            # operator must run its confirmation dialog before it can save.
            self._layout.operator_context = "INVOKE_AREA"
            properties = self._layout.operator(target_id, *args, **kwargs)
        finally:
            self._layout.operator_context = previous_context
        return _OperatorPropertiesProxy(properties, ignored)


class _MenuDrawProxy:
    __slots__ = ("_menu", "layout")

    def __init__(self, menu, layout):
        self._menu = menu
        self.layout = layout

    def __getattr__(self, name):
        return getattr(self._menu, name)


def _install_menu_wrapper(menu):
    original = menu.draw

    def draw(menu_instance, context):
        layout = _RedirectingMenuLayout(menu_instance.layout)
        return original(_MenuDrawProxy(menu_instance, layout), context)

    draw.__name__ = getattr(original, "__name__", "draw")
    draw.__doc__ = getattr(original, "__doc__", None)
    draw.__module__ = getattr(original, "__module__", __name__)
    draw_funcs = getattr(original, "_draw_funcs", [])
    # Blender's append/remove API owns this mutable list. Keeping the same
    # object preserves callback identity, order and later add-on changes.
    draw._draw_funcs = draw_funcs
    menu.draw = draw
    _MENU_WRAPPERS.append((menu, original, draw, hasattr(original, "_draw_funcs")))


def _install_keymap_redirects():
    """Redirect native shortcuts through owned operators when keymaps allow it."""
    global _KEYMAP_REDIRECTS, _KEYMAP_ITEMS
    try:
        import bpy
        window_manager = bpy.context.window_manager
        user = window_manager.keyconfigs.user
        addon = window_manager.keyconfigs.addon
    except (ImportError, AttributeError, ReferenceError):
        return
    if user is None or addon is None:
        return
    for keymap in getattr(user, "keymaps", ()):
        for item in tuple(getattr(keymap, "keymap_items", ())):
            target_id = _redirect_target(
                item.idname,
                animation=getattr(getattr(item, "properties", None), "animation", False),
                incremental=getattr(getattr(item, "properties", None), "incremental", False),
                copy=getattr(getattr(item, "properties", None), "copy", False),
                sequencer_scene=getattr(getattr(item, "properties", None), "use_sequencer_scene", False),
            )
            if target_id is None or not getattr(item, "active", True):
                continue
            try:
                target_map = addon.keymaps.get(keymap.name)
                if target_map is None:
                    target_map = addon.keymaps.new(
                        name=keymap.name,
                        space_type=keymap.space_type,
                        region_type=keymap.region_type,
                    )
                redirect = target_map.keymap_items.new(
                    target_id, item.type, item.value,
                    shift=item.shift, ctrl=item.ctrl, alt=item.alt,
                    oskey=item.oskey, key_modifier=item.key_modifier,
                )
                _copy_key_event(item, redirect)
                original = item.active
                item.active = False
                _KEYMAP_REDIRECTS.append((item, original, target_id))
                _KEYMAP_ITEMS.append((target_map, redirect))
            except (AttributeError, RuntimeError, TypeError, ValueError):
                continue


def _remove_keymap_redirects():
    while _KEYMAP_REDIRECTS:
        item, active, _target_id = _KEYMAP_REDIRECTS.pop()
        try:
            item.active = active
        except (AttributeError, ReferenceError, RuntimeError):
            pass
    while _KEYMAP_ITEMS:
        keymap, item = _KEYMAP_ITEMS.pop()
        try:
            keymap.keymap_items.remove(item)
        except (AttributeError, ReferenceError, RuntimeError, ValueError):
            pass


def register():
    global _CLASSES, _MENU_WRAPPERS
    if _CLASSES:
        return _CLASSES
    import bpy

    controller = _controller()

    class _OutputWaitModal:
        def _report_save_warning(self, result):
            options = getattr(self, "_pg_save_options", None)
            if options is None or result != {"FINISHED"}:
                return
            warning = modified_image_warning(options.diagnostics.unsaved_images)
            if warning:
                self.report({"WARNING"}, warning)

        def _begin_wait(self, context, operation, kind):
            if getattr(context, "window", None) is None:
                if kind == "save":
                    controller.cancel_save_wait(operation)
                elif controller.pending_render_operation == operation:
                    controller.cancel_render_wait(operation)
                self.report({"ERROR"}, "This output action needs an interactive Blender window to wait for preparation")
                return {"CANCELLED"}
            self._pg_wait_operation = operation
            self._pg_wait_kind = kind
            self._pg_wait_window_manager = context.window_manager
            self._pg_wait_timer = context.window_manager.event_timer_add(
                0.1, window=context.window,
            )
            context.window_manager.modal_handler_add(self)
            return {"RUNNING_MODAL"}

        def _end_wait(self):
            manager = getattr(self, "_pg_wait_window_manager", None)
            timer = getattr(self, "_pg_wait_timer", None)
            if manager is not None and timer is not None:
                try:
                    manager.event_timer_remove(timer)
                except (ReferenceError, RuntimeError):
                    pass
            self._pg_wait_timer = None

        def modal(self, context, event):
            operation = self._pg_wait_operation
            kind = self._pg_wait_kind
            if kind == "save":
                if event.type == "ESC":
                    controller.cancel_save_wait(operation)
                    self._end_wait()
                    return {"CANCELLED"}
                if event.type != "TIMER":
                    return {"PASS_THROUGH"}
                try:
                    result = controller.continue_save(operation)
                    pending = controller._pending_save.get(operation)
                    if pending is not None:
                        self._pg_save_options = pending[1]
                except Exception as error:
                    self.report({"ERROR"}, str(error))
                    if controller.pending_save_operation == operation:
                        controller.cancel_save_wait(operation)
                    self._end_wait()
                    return {"CANCELLED"}
                if result == {"RUNNING_MODAL"}:
                    return {"PASS_THROUGH"}
                self._report_save_warning(result)
                self._end_wait()
                return result

            if event.type == "ESC" and controller.pending_render_operation == operation:
                controller.cancel_render_wait(operation)
                self._end_wait()
                return {"CANCELLED"}
            if event.type != "TIMER":
                return {"PASS_THROUGH"}
            if controller.pending_render_operation == operation:
                try:
                    result = controller.continue_render(operation)
                except Exception as error:
                    self.report({"ERROR"}, str(error))
                    if controller.pending_render_operation == operation:
                        controller.cancel_render_wait(operation)
                    self._end_wait()
                    return {"CANCELLED"}
                if result == {"RUNNING_MODAL"}:
                    return {"PASS_THROUGH"}
                if result == {"CANCELLED"}:
                    self._end_wait()
                    return result
            if controller.active_render_operation == operation:
                return {"PASS_THROUGH"}
            self._end_wait()
            return {"FINISHED"}

    class PGNEXT_OT_save(_OutputWaitModal, bpy.types.Operator):
        bl_idname = "wm.pg_next_save"
        bl_label = "Save"
        bl_description = "Prepare Perceptual Grade and save the current file"
        bl_options = {"REGISTER"}

        check_existing: bpy.props.BoolProperty(default=True, options={"HIDDEN"})
        use_compression: bpy.props.BoolProperty(default=True)
        save_modified_images: bpy.props.BoolProperty(name="Save Modified Images", default=True)
        image_preference: bpy.props.StringProperty(default="ASK", options={"HIDDEN"})

        def invoke(self, context, event):
            import bpy
            if not bpy.data.filepath:
                return bpy.ops.wm.pg_next_save_as("INVOKE_DEFAULT")
            try:
                preference = context.preferences.filepaths.save_modified_images
                self.save_modified_images = modified_images_choice(preference, True)
                self.image_preference = str(preference).upper()
            except (AttributeError, TypeError):
                self.save_modified_images = True
                self.image_preference = "ASK"
            return context.window_manager.invoke_props_dialog(self)

        def draw(self, context):
            if self.image_preference == "ASK":
                self.layout.prop(self, "save_modified_images")

        def execute(self, context):
            try:
                save_modified_images = modified_images_choice(
                    getattr(self, "image_preference", "ASK"),
                    self.save_modified_images,
                )
                options = SaveOptions(
                    check_existing=self.check_existing,
                    use_compression=self.use_compression,
                    save_modified_images=save_modified_images,
                )
                self._pg_save_options = options
                result = controller.save(_native_save, options)
                if result == {"RUNNING_MODAL"}:
                    return self._begin_wait(context, controller.pending_save_operation, "save")
                self._report_save_warning(result)
                return result
            except (RuntimeError, TypeError, ValueError) as error:
                self.report({"ERROR"}, str(error))
                return {"CANCELLED"}

    class PGNEXT_OT_save_as(_OutputWaitModal, bpy.types.Operator):
        bl_idname = "wm.pg_next_save_as"
        bl_label = "Save As"
        bl_description = "Choose a destination, prepare Perceptual Grade, and save"
        bl_options = {"REGISTER"}

        filepath: bpy.props.StringProperty(subtype="FILE_PATH", default="")
        check_existing: bpy.props.BoolProperty(default=True)
        use_compression: bpy.props.BoolProperty(default=True)
        save_modified_images: bpy.props.BoolProperty(name="Save Modified Images", default=True)
        image_preference: bpy.props.StringProperty(default="ASK", options={"HIDDEN"})
        copy: bpy.props.BoolProperty(name="Save Copy", default=False)
        relative_remap: bpy.props.BoolProperty(name="Remap Relative Paths", default=True)
        filter_glob: bpy.props.StringProperty(default="*.blend", options={"HIDDEN"})

        def invoke(self, context, event):
            self.filepath = bpy.data.filepath or "Untitled.blend"
            try:
                preference = context.preferences.filepaths.save_modified_images
                self.save_modified_images = modified_images_choice(preference, True)
                self.image_preference = str(preference).upper()
            except (AttributeError, TypeError):
                self.save_modified_images = True
                self.image_preference = "ASK"
            context.window_manager.fileselect_add(self)
            return {"RUNNING_MODAL"}

        def draw(self, context):
            if self.image_preference == "ASK":
                self.layout.prop(self, "save_modified_images")

        def check(self, context):
            path = bpy.path.ensure_ext(self.filepath, ".blend")
            changed = path != self.filepath
            self.filepath = path
            return changed

        def execute(self, context):
            try:
                import bpy
                if self.filepath:
                    self.filepath = bpy.path.ensure_ext(self.filepath, ".blend")
                save_modified_images = modified_images_choice(
                    getattr(self, "image_preference", "ASK"),
                    self.save_modified_images,
                )
                options = SaveOptions(
                    filepath=self.filepath,
                    check_existing=self.check_existing,
                    use_compression=self.use_compression,
                    save_modified_images=save_modified_images,
                    copy=self.copy,
                    relative_remap=self.relative_remap,
                )
                self._pg_save_options = options
                result = controller.save_as(_native_save, options)
                if result == {"RUNNING_MODAL"}:
                    return self._begin_wait(context, controller.pending_save_operation, "save")
                self._report_save_warning(result)
                return result
            except (RuntimeError, TypeError, ValueError) as error:
                self.report({"ERROR"}, str(error))
                return {"CANCELLED"}

    class _RenderBase(_OutputWaitModal):
        animation = False

        def invoke(self, context, event):
            return self.execute(context)

        def execute(self, context):
            try:
                result = controller.render(_native_render, RenderOptions(
                    animation=self.animation, scene=self.scene,
                    write_still=self.write_still,
                    use_viewport=self.use_viewport,
                ))
                if result == {"RUNNING_MODAL"}:
                    operation = (controller.pending_render_operation
                                 or controller.active_render_operation)
                    return self._begin_wait(context, operation, "render")
                return result
            except (RuntimeError, TypeError, ValueError) as error:
                self.report({"ERROR"}, str(error))
                return {"CANCELLED"}

    class PGNEXT_OT_render_image(_RenderBase, bpy.types.Operator):
        bl_idname = "render.pg_next_render_image"
        bl_label = "Render Image"
        bl_description = "Prepare Perceptual Grade and render one image"
        bl_options = {"REGISTER"}
        write_still: bpy.props.BoolProperty(default=False)
        scene: bpy.props.StringProperty(default="", options={"HIDDEN"})
        use_viewport: bpy.props.BoolProperty(default=False, options={"HIDDEN"})

    class PGNEXT_OT_render_animation(_RenderBase, bpy.types.Operator):
        bl_idname = "render.pg_next_render_animation"
        bl_label = "Render Animation"
        bl_description = "Prepare Perceptual Grade and render the animation"
        bl_options = {"REGISTER"}
        write_still: bpy.props.BoolProperty(default=False)
        scene: bpy.props.StringProperty(default="", options={"HIDDEN"})
        use_viewport: bpy.props.BoolProperty(default=False, options={"HIDDEN"})
        animation = True

    classes = (PGNEXT_OT_save, PGNEXT_OT_save_as,
               PGNEXT_OT_render_image, PGNEXT_OT_render_animation)
    for cls in classes:
        bpy.utils.register_class(cls)
    _CLASSES = classes
    _install_keymap_redirects()

    for name in ("TOPBAR_MT_file", "TOPBAR_MT_render"):
        menu = getattr(bpy.types, name, None)
        if menu is not None:
            _install_menu_wrapper(menu)
    return _CLASSES


def unregister():
    global _CLASSES, _CONTROLLER
    try:
        import bpy
    except ImportError:
        _CLASSES = ()
        _CONTROLLER = None
        return
    while _MENU_WRAPPERS:
        menu, original, wrapper, had_draw_funcs = _MENU_WRAPPERS.pop()
        try:
            if menu.draw is wrapper:
                draw_funcs = wrapper._draw_funcs
                if had_draw_funcs or draw_funcs:
                    original._draw_funcs = draw_funcs
                elif hasattr(original, "_draw_funcs"):
                    del original._draw_funcs
                menu.draw = original
        except (AttributeError, ReferenceError, RuntimeError, TypeError):
            pass
    _remove_keymap_redirects()
    for cls in reversed(_CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except (AttributeError, RuntimeError):
            pass
    _CLASSES = ()
    _CONTROLLER = None


__all__ = ("OutputActionController", "SaveOptions", "RenderOptions",
           "SaveDiagnostics", "modified_images_choice", "modified_image_warning",
           "register", "unregister")
