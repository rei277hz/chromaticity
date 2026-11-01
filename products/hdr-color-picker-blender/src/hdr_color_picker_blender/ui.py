"""Persistent viewport picker; edits stay in preview until explicit confirmation."""
import bpy
from bpy.app.handlers import persistent
from bpy.props import BoolProperty, EnumProperty, FloatProperty
from . import brush, display
from .. import hdr_color_picker_core as model

_PROPERTY = 'hdr_color_picker_settings'


from types import SimpleNamespace


def create_ui(session):
    def _settings(context):
        return getattr(context.window_manager, _PROPERTY)


    def _redraw(self, context):
        if context.screen is not None:
            for area in context.screen.areas:
                if area.type == 'VIEW_3D':
                    area.tag_redraw()


    def _visibility(self, context):
        if not self.visible:
            session.reset()
        _redraw(self, context)


    def _applicable(context):
        try:
            brush.capture(context)
            return True
        except (brush.BrushUnavailable, AttributeError, ReferenceError):
            return False


    class HDRPickerSettings(bpy.types.PropertyGroup):
        visible: BoolProperty(name='Show Color Picker', default=False, update=_visibility)
        lightness: FloatProperty(name='J′', description='Normalized HK lightness', default=model.REFERENCE_WHITE_J,
                                 min=0, max=1, update=_redraw)
        x: FloatProperty(name='x′', default=.5, min=0, max=1, update=_redraw)
        y: FloatProperty(name='y′', default=.5, min=0, max=1, update=_redraw)
        full_rec2020: BoolProperty(name='Rec.2020 gamut', description='Disable to restrict authoring to P3',
                                  default=True, update=_redraw)


    class HDRPICKER_OT_confirm(bpy.types.Operator):
        bl_idname = 'hdr_color_picker.confirm'
        bl_label = 'Apply Brush Color'
        bl_description = 'Apply the preview to the active Grease Pencil Draw brush'
        # Native Brush settings deliberately bypass Blender's memfile undo.
        bl_options = {'REGISTER'}

        @classmethod
        def poll(cls, context):
            return _applicable(context)

        def execute(self, context):
            settings = _settings(context)
            try:
                # Fidelity is a gate for both interaction and writing.
                session.controller().require_view(context.scene)
                pick = model.evaluate(settings.lightness, settings.x, settings.y, settings.full_rec2020)
                if not pick.valid:
                    raise brush.BrushUnavailable('Choose a color inside the authoring gamut')
                brush.commit(context, brush.capture(context), pick.acescg)
            except (brush.BrushUnavailable, display.DisplayUnavailable) as exc:
                self.report({'WARNING'}, str(exc))
                return {'CANCELLED'}
            return {'FINISHED'}


    class HDRPICKER_OT_preset(bpy.types.Operator):
        bl_idname = 'hdr_color_picker.preset'
        bl_label = 'Picker Preset'
        preset: EnumProperty(items=[('WHITE','Diffuse White',''), ('BLACK','Black',''), ('BRUSH','Current Brush','')])

        def execute(self, context):
            settings = _settings(context)
            if self.preset == 'BRUSH':
                try:
                    code, valid = model.from_acescg(brush.current_acescg(context))
                    if not valid:
                        self.report({'WARNING'}, 'The brush color is outside the picker domain')
                        return {'CANCELLED'}
                except brush.BrushUnavailable as exc:
                    self.report({'WARNING'}, str(exc))
                    return {'CANCELLED'}
            else:
                code = (model.REFERENCE_WHITE_J if self.preset == 'WHITE' else 0., .5, .5)
            settings.lightness, settings.x, settings.y = code
            return {'FINISHED'}


    class HDRPICKER_GT_slice(bpy.types.Gizmo):
        bl_idname = 'HDRPICKER_GT_slice'

        def setup(self):
            self.use_draw_modal = True
            self.use_draw_scale = False
            self.use_draw_offset_scale = False
            self._origin = (24, 64)
            self._size = (240, 240)

        def draw(self, context):
            settings = _settings(context)
            if not session.controller().draw(context.scene, settings, self._origin, self._size):
                return
            # Selected coordinate marker uses the ordinary UI shader; the slice
            # itself always uses the active scene display processor.
            import gpu
            from gpu_extras.batch import batch_for_shader
            x = self._origin[0] + settings.x*self._size[0]
            y = self._origin[1] + settings.y*self._size[1]
            shader = gpu.shader.from_builtin('UNIFORM_COLOR')
            vertices = [(x-7,y), (x+7,y), (x,y-7), (x,y+7)]
            batch = batch_for_shader(shader, 'LINES', {'pos': vertices})
            shader.bind()
            shader.uniform_float('color', (1,1,1,1))
            batch.draw(shader)

        def test_select(self, context, location):
            x, y = location
            ox, oy = self._origin
            w, h = self._size
            return 0 if ox <= x <= ox+w and oy <= y <= oy+h else -1

        def _preview(self, context, event):
            settings = _settings(context)
            ox, oy = self._origin
            w, h = self._size
            settings.x = min(1, max(0, (event.mouse_region_x-ox)/w))
            settings.y = min(1, max(0, (event.mouse_region_y-oy)/h))
            context.area.tag_redraw()

        def invoke(self, context, event):
            settings = _settings(context)
            self._initial = (settings.x, settings.y)
            self._active = False
            try:
                self._brush = brush.capture(context)
                self._view = display.signature(context.scene)
                session.controller().require_view(context.scene)
            except (brush.BrushUnavailable, display.DisplayUnavailable):
                return {'CANCELLED'}
            self._active = True
            self._preview(context, event)
            return {'RUNNING_MODAL'}

        def modal(self, context, event, tweak):
            try:
                if brush.capture(context) != self._brush or display.signature(context.scene) != self._view:
                    return {'CANCELLED'}
            except (brush.BrushUnavailable, display.DisplayUnavailable):
                return {'CANCELLED'}
            self._preview(context, event)
            return {'RUNNING_MODAL'}

        def exit(self, context, cancel):
            if not getattr(self, '_active', False):
                return
            self._active = False
            settings = _settings(context)
            if cancel:
                settings.x, settings.y = self._initial
            else:
                try:
                    if brush.capture(context) != self._brush or display.signature(context.scene) != self._view:
                        return
                    bpy.ops.hdr_color_picker.confirm('EXEC_DEFAULT')
                except (brush.BrushUnavailable, display.DisplayUnavailable):
                    pass


    class HDRPICKER_GGT_picker(bpy.types.GizmoGroup):
        bl_idname = 'HDRPICKER_GGT_picker'
        bl_label = 'HDR Color Picker'
        bl_space_type = 'VIEW_3D'
        bl_region_type = 'WINDOW'
        bl_options = {'PERSISTENT', 'SHOW_MODAL_ALL'}

        @classmethod
        def poll(cls, context):
            return _settings(context).visible and _applicable(context)

        def setup(self, context):
            self.gizmos.new('HDRPICKER_GT_slice')


    class HDRPICKER_PT_panel(bpy.types.Panel):
        bl_idname = 'HDRPICKER_PT_panel'
        bl_label = 'HDR Color Picker'
        bl_space_type = 'VIEW_3D'
        bl_region_type = 'UI'
        bl_category = 'HDR Color'

        def draw(self, context):
            layout = self.layout
            settings = _settings(context)
            layout.prop(settings, 'visible')
            layout.prop(settings, 'lightness')
            row = layout.row(align=True)
            row.prop(settings, 'x')
            row.prop(settings, 'y')
            layout.prop(settings, 'full_rec2020')
            row = layout.row(align=True)
            for preset, label in [('WHITE','White'), ('BLACK','Black'), ('BRUSH','Brush')]:
                row.operator('hdr_color_picker.preset', text=label).preset = preset
            pick = model.evaluate(settings.lightness, settings.x, settings.y, settings.full_rec2020)
            if pick.valid:
                layout.label(text='ACEScg  ' + '  '.join(f'{v:.4g}' for v in pick.acescg))
            else:
                layout.label(text='Outside authoring gamut', icon='ERROR')
            row = layout.row()
            row.enabled = pick.valid and _applicable(context)
            row.operator('hdr_color_picker.confirm')
            message = session.controller().message
            if message:
                layout.label(text=message, icon='INFO')
            if not _applicable(context):
                layout.label(text='Use GP Draw in Color Attribute mode')


    _CLASSES = (HDRPickerSettings, HDRPICKER_OT_confirm, HDRPICKER_OT_preset,
                HDRPICKER_GT_slice, HDRPICKER_GGT_picker, HDRPICKER_PT_panel)
    _registered = session.app.blender.registration


    @persistent
    def _boundary(*args):
        session.reset()


    def _tick():
        if session.closed or not _registered:
            return None
        instance = session.current_controller()
        preparing = instance is not None and instance.pending is not None
        runtime = session.app.execution.current_runtime()
        if runtime is not None and not runtime.closed:
            runtime.poll()
        if preparing:
            areas = []
            for window in bpy.context.window_manager.windows:
                if _settings(bpy.context).visible:
                    for area in window.screen.areas:
                        if area.type == 'VIEW_3D' and area.spaces.active.show_gizmo:
                            region = next((r for r in area.regions if r.type == 'WINDOW'), None)
                            if region is not None:
                                with bpy.context.temp_override(window=window, area=area, region=region):
                                    if _applicable(bpy.context):
                                        areas.append(area)
            if not areas:
                instance.reset()
            for area in areas:
                area.tag_redraw()
        return .1


    def register():
        try:
            for cls in _CLASSES:
                _registered.register_class(cls)
            _registered.property(bpy.types.WindowManager, _PROPERTY,
                                 bpy.props.PointerProperty(type=HDRPickerSettings))
            for name in ('undo_pre', 'redo_pre', 'load_pre'):
                _registered.handler(getattr(bpy.app.handlers, name), _boundary)
            _registered.timer(_tick, first_interval=.1, persistent=True)
        except Exception:
            session.close()
            raise



    def stop():
        if bpy.app.timers.is_registered(_tick):
            bpy.app.timers.unregister(_tick)
        for name in ('undo_pre', 'redo_pre', 'load_pre'):
            handlers = getattr(bpy.app.handlers, name)
            if _boundary in handlers:
                handlers.remove(_boundary)

    return SimpleNamespace(classes=_CLASSES, register=register, stop=stop, tick=_tick,
                           HDRPickerSettings=HDRPickerSettings, HDRPICKER_GT_slice=HDRPICKER_GT_slice,
                           HDRPICKER_OT_confirm=HDRPICKER_OT_confirm)
