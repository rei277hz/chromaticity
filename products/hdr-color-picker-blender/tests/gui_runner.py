"""Exercise native picker input and Image Editor preview in separate scenarios."""
import importlib
import json
import os
from pathlib import Path
import sys
import time
import traceback

import bpy
from mathutils import Color
import numpy as np


repository_path, report_file, scenario_name = sys.argv[sys.argv.index('--') + 1:]
repository, report_path = Path(repository_path), Path(report_file)
bpy.context.preferences.extensions.repos.new(
    name='Component package acceptance', module='picker_tests', custom_directory=str(repository))
bpy.context.preferences.view.show_splash = False
bpy.context.preferences.edit.use_global_undo = True
picker = importlib.import_module('bl_ext.picker_tests.hdr_color_picker')
picker.register()
from bl_ext.picker_tests.hdr_color_picker.hdr_color_picker_blender import display, registered_session

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


def prepare_paint():
    window, area, region = viewport()
    with bpy.context.temp_override(window=window, area=area, region=region):
        bpy.ops.object.grease_pencil_add(type='EMPTY')
        bpy.ops.object.mode_set(mode='PAINT_GREASE_PENCIL')
        bpy.context.tool_settings.gpencil_paint.color_mode = 'VERTEXCOLOR'
        bpy.context.tool_settings.gpencil_paint.brush.color = (.1, .2, .3)
        area.spaces.active.show_gizmo = True
        settings().visible = True
        settings().lightness, settings().x, settings().y = .8, .4, .4
    return window, area, region


def gizmo_scenario():
    window, area, region = prepare_paint()
    bpy.utils.register_class(HDRPICKERTEST_OT_scene_edit)
    with bpy.context.temp_override(window=window, area=area, region=region):
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
    bpy.utils.unregister_class(HDRPICKERTEST_OT_scene_edit)


def preview_scenario():
    window, area, region = prepare_paint()
    paint_scene = window.scene
    controller = registered_session().controller()
    native = controller.native_preview
    windows_before = len(bpy.context.window_manager.windows)
    images_before = {image.session_uid for image in bpy.data.images}
    devices = tuple(display._ocio().GetCurrentConfig().getDisplays())
    with bpy.context.temp_override(window=window, area=area, region=region):
        bpy.ops.wm.set_working_color_space(working_space='ACEScg')
        settings().x = settings().y = .5
        assert bpy.ops.hdr_color_picker.confirm() == {'FINISHED'}
        committed = brush_color()
        assert max(committed) > 1
        for device in devices:
            paint_scene.display_settings.display_device = device
            paint_scene.view_settings.view_transform = 'Standard'
            assert bpy.ops.hdr_color_picker.confirm() == {'FINISHED'}, device
            np.testing.assert_allclose(brush_color(), committed, atol=1e-6, rtol=0)
        if 'Rec.2100-HLG' in devices:
            paint_scene.display_settings.display_device = 'Rec.2100-HLG'
            paint_scene.view_settings.view_transform = 'Standard'
        assert bpy.ops.hdr_color_picker.open_native_preview() == {'FINISHED'}
    record('all_display_devices_committed_same_hdr_color')

    def preview_image():
        target = native.target(bpy.context.window_manager)
        return target[1].spaces.active.image if target is not None else None

    def check_pixels(working_space):
        image = preview_image()
        assert image.colorspace_settings.name == working_space
        expected = controller.slice_pixels[::-1].copy()
        sample = expected[expected.shape[0] // 2, expected.shape[1] // 2]
        actual = np.asarray(image.pixels[:]).reshape(expected.shape)
        np.testing.assert_array_equal(actual[..., 3], expected[..., 3])
        color = Color(sample[:3]).from_acescg_to_scene_linear()
        np.testing.assert_allclose(actual[expected.shape[0] // 2, expected.shape[1] // 2, :3],
                                   tuple(color), atol=1e-5, rtol=1e-5)

    yield from wait_for(preview_image, 'The native Image Editor never received a float preview')
    assert len(bpy.context.window_manager.windows) == windows_before + 1
    image = preview_image()
    assert image.source == 'FILE' and image.is_float and image.use_view_as_render
    assert not image.is_dirty
    path = Path(image.filepath)
    assert path.is_file() and max(image.pixels[:]) > 1
    check_pixels('ACEScg')
    first_uid = image.session_uid
    first_peak = max(image.pixels[:])
    with bpy.context.temp_override(window=window, area=area, region=region):
        assert bpy.ops.hdr_color_picker.open_native_preview() == {'FINISHED'}
        area.spaces.active.show_gizmo = False
        settings().lightness = .9
    yield from wait_for(
        lambda: preview_image() is not None and max(preview_image().pixels[:]) > first_peak,
        'Native preview did not refresh after lightness changed')
    assert len(bpy.context.window_manager.windows) == windows_before + 1
    assert preview_image().session_uid == first_uid
    with bpy.context.temp_override(window=window, area=area, region=region):
        bpy.ops.wm.set_working_color_space(working_space='Linear Rec.709')
    yield from wait_for(
        lambda: preview_image() is not None and
        preview_image().colorspace_settings.name == 'Linear Rec.709',
        'Native preview did not refresh after the working space changed')
    check_pixels('Linear Rec.709')
    del image
    with bpy.context.temp_override(window=window, area=area, region=region):
        bpy.ops.wm.save_as_mainfile(filepath=str(report_path.parent / 'preview-cleanup.blend'), copy=True)
    yield from wait_for(lambda: len(bpy.context.window_manager.windows) == windows_before,
                        'Saving did not close the temporary preview window')
    assert {image.session_uid for image in bpy.data.images} == images_before
    assert not path.exists()
    record('native_preview_reused_and_cleaned_on_save')


sequence = {'gizmo': gizmo_scenario, 'native_preview': preview_scenario}[scenario_name]()


def advance():
    try:
        if time.monotonic() - started > 120:
            raise TimeoutError(f'{scenario_name} scenario exceeded two minutes')
        if getattr(bpy.context.window_manager, 'is_event_handling_break', False):
            return .025
        next(sequence)
        return .025
    except StopIteration:
        picker.unregister()
        report['passed'] = True
        record('complete')
        bpy.ops.wm.quit_blender('EXEC_DEFAULT')
        return None
    except BaseException:
        report['error'] = traceback.format_exc()
        report['mode'] = bpy.context.mode
        paint = bpy.context.tool_settings.gpencil_paint
        if paint is not None and paint.brush is not None:
            report['color'] = tuple(paint.brush.color)
        report['settings'] = (settings().x, settings().y)
        record('failed')
        print(json.dumps(report), file=sys.stderr, flush=True)
        import ctypes
        ctypes.CDLL(None).fflush(None)
        os._exit(1)


bpy.app.timers.register(advance, first_interval=.5)
