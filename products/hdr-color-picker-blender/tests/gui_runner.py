"""Native WM events exercise the persistent picker and unrelated undo dispatch."""
import importlib
import json
import os
from pathlib import Path
import sys
import time
import traceback

import bpy


repository, report_path = map(Path, sys.argv[sys.argv.index('--') + 1:])
bpy.context.preferences.extensions.repos.new(
    name='Component package acceptance', module='picker_tests', custom_directory=str(repository))
bpy.context.preferences.view.show_splash = False
bpy.context.preferences.edit.use_global_undo = True
picker = importlib.import_module('bl_ext.picker_tests.hdr_color_picker')
picker.register()
report = {'passed': False, 'events': []}
started = time.monotonic()
_PROBE = 'hdr_picker_native_undo_probe'


class HDRPICKERTEST_OT_scene_edit(bpy.types.Operator):
    bl_idname = 'hdr_picker_test.scene_edit'
    bl_label = 'Native picker shortcut regression'
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        context.scene[_PROBE] += 1
        return {'FINISHED'}


bpy.utils.register_class(HDRPICKERTEST_OT_scene_edit)


def record(event):
    report['events'].append(event)
    report_path.write_text(json.dumps(report, indent=2))


def viewport():
    window = bpy.context.window_manager.windows[0]
    area = next(area for area in window.screen.areas if area.type == 'VIEW_3D')
    region = next(region for region in area.regions if region.type == 'WINDOW')
    return window, area, region


def settings():
    return bpy.context.window_manager.hdr_color_picker_settings


def brush_color():
    return tuple(bpy.context.tool_settings.gpencil_paint.brush.color)


def emit(kind, value='NOTHING', point=(.5, .5), **modifiers):
    window, area, region = viewport()
    x, y = (region.x + 24 + int(240 * point[0]),
            region.y + 64 + int(240 * point[1]))
    assert window.event_simulate(type=kind, value=value, unicode=None,
                                 x=x, y=y, **modifiers) is not None


def turns(count=8):
    for _ in range(count):
        yield


def wait_for(predicate, message):
    deadline = time.monotonic() + 30
    while not predicate():
        if time.monotonic() > deadline:
            raise TimeoutError(message)
        yield


def undo_key(*, redo=False):
    # Run while highlighted: the picker must leave unrelated shortcuts usable.
    emit('LEFT_CTRL', 'PRESS', ctrl=True)
    if redo:
        emit('LEFT_SHIFT', 'PRESS', ctrl=True, shift=True)
    emit('Z', 'PRESS', ctrl=True, shift=redo)
    yield from turns()
    emit('Z', 'RELEASE', ctrl=True, shift=redo)
    if redo:
        emit('LEFT_SHIFT', 'RELEASE', ctrl=True)
    emit('LEFT_CTRL', 'RELEASE')
    yield from turns()


def scenario():
    window, area, region = viewport()
    with bpy.context.temp_override(window=window, area=area, region=region):
        bpy.ops.object.grease_pencil_add(type='EMPTY')
        bpy.ops.object.mode_set(mode='PAINT_GREASE_PENCIL')
        bpy.context.tool_settings.gpencil_paint.color_mode = 'VERTEXCOLOR'
        bpy.context.tool_settings.gpencil_paint.brush.color = (.1, .2, .3)
        area.spaces.active.show_gizmo = True
        settings().visible = True
        settings().lightness, settings().x, settings().y = .8, .4, .4
        original = brush_color()
        bpy.context.scene[_PROBE] = 0
        bpy.ops.ed.undo_push(message='HDR picker baseline')
    keymap = bpy.context.window_manager.keyconfigs.addon.keymaps.new(name='Screen', space_type='EMPTY')
    keymap.keymap_items.new('ed.undo', 'Z', 'PRESS', ctrl=True)
    keymap.keymap_items.new('ed.redo', 'Z', 'PRESS', ctrl=True, shift=True)
    keymap.keymap_items.new('hdr_picker_test.scene_edit', 'F8', 'PRESS')
    bpy.context.window_manager.keyconfigs.update()
    del keymap
    # Give the real viewport time to compile/draw and register gizmo hit testing.
    yield from turns(40)
    from bl_ext.picker_tests.hdr_color_picker.hdr_color_picker_blender import registered_session
    assert registered_session().current_controller() is not None, 'Viewport never drew the picker'
    assert not registered_session().current_controller().message, registered_session().current_controller().message
    emit('MOUSEMOVE')
    yield from turns()
    emit('LEFTMOUSE', 'PRESS')
    yield from wait_for(lambda: abs(settings().x - .5) < 1e-5,
                        'Native mouse press did not invoke the picker gizmo')
    assert brush_color() == original, 'Press wrote the brush before confirmation'
    emit('MOUSEMOVE', point=(.55, .5))
    yield from turns()
    assert brush_color() == original, 'Preview drag wrote the brush'
    emit('ESC', 'PRESS')
    yield from turns()
    emit('ESC', 'RELEASE')
    emit('LEFTMOUSE', 'RELEASE')
    yield from turns()
    assert brush_color() == original, 'Escape changed the brush'
    assert abs(settings().x - .4) < 1e-5 and abs(settings().y - .4) < 1e-5
    record('cancel_left_brush_unchanged')
    emit('MOUSEMOVE')
    yield from turns()
    emit('LEFTMOUSE', 'PRESS')
    yield from wait_for(lambda: abs(settings().x - .5) < 1e-5,
                        'Second press did not enter picker preview')
    emit('LEFTMOUSE', 'RELEASE')
    yield from wait_for(lambda: max(brush_color()) > 1,
                        'Native mouse release did not commit an HDR brush color')
    committed = brush_color()
    record('release_committed_hdr')
    # Brush settings deliberately bypass Blender's memfile undo. Exercise a
    # normal undoable scene edit to check keyboard events still pass through.
    emit('F8', 'PRESS')
    yield from wait_for(lambda: bpy.context.scene[_PROBE] == 1,
                        'Picker swallowed an unrelated scene-edit shortcut')
    emit('F8', 'RELEASE')
    yield from turns()
    yield from undo_key()
    assert bpy.context.scene[_PROBE] == 0, 'Picker swallowed native undo'
    assert brush_color() == committed, 'Brush bypassed its native non-undo contract'
    record('undo_restored_scene')
    yield from undo_key(redo=True)
    assert bpy.context.scene[_PROBE] == 1, 'Picker swallowed native redo'
    assert brush_color() == committed, 'Redo changed the independent brush setting'
    record('redo_restored_scene')
    settings().visible = False
    assert registered_session().current_controller().arena.physical_counts() == (0, 0)
    record('hide_released_preview')


sequence = scenario()


def advance():
    try:
        if time.monotonic() - started > 120:
            raise TimeoutError('Native gizmo scenario exceeded two minutes')
        if getattr(bpy.context.window_manager, 'is_event_handling_break', False):
            return .025
        next(sequence)
        return .025
    except StopIteration:
        picker.unregister()
        bpy.utils.unregister_class(HDRPICKERTEST_OT_scene_edit)
        report['passed'] = True
        record('complete')
        bpy.ops.wm.quit_blender('EXEC_DEFAULT')
        return None
    except BaseException:
        report['error'] = traceback.format_exc()
        report['mode'] = bpy.context.mode
        report['color'] = brush_color()
        report['settings'] = (settings().x, settings().y)
        record('failed')
        print(json.dumps(report), file=sys.stderr, flush=True)
        import ctypes
        ctypes.CDLL(None).fflush(None)
        os._exit(1)


bpy.app.timers.register(advance, first_interval=.5)
