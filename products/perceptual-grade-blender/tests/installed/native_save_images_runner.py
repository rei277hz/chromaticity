"""Exercise native Save's modified-image decision before save_pre runs.

Use the real GUI invocation and the same hidden property as Blender's File
menu. EXEC_DEFAULT and the default false property would miss this warning.
Only this process's disposable project and user-image fixture are modified.
"""
import hashlib
import importlib
import json
import os
from pathlib import Path
import sys
import time
import traceback

import addon_utils
import bpy
import numpy as np


def main(repository, destination):
    repository, destination = Path(repository).resolve(), Path(destination)
    assert not bpy.app.background and tuple(bpy.app.version) in {(5, 2, 4), (5, 3, 0)}
    bpy.context.preferences.view.show_splash = False
    bpy.context.preferences.system.gpu_backend = 'METAL' if sys.platform == 'darwin' else 'OPENGL'
    bpy.context.preferences.filepaths.save_modified_images = 'ASK'
    project = destination.with_suffix('.blend')
    # Establish a filepath in this process, avoiding both a file browser and
    # any overwrite warning associated with externally changed projects.
    assert bpy.ops.wm.save_as_mainfile(filepath=str(project), check_existing=False) == {'FINISHED'}
    bpy.context.preferences.extensions.repos.new(
        name='Native image-save acceptance', module='pg_save_images', custom_directory=str(repository))
    name = 'bl_ext.pg_save_images.perceptual_grade'
    errors = []
    addon = addon_utils.enable(name, default_set=False, handle_error=errors.append)
    assert addon is not None and not errors, errors

    prefix = 'perceptual_grade_blender.'
    lifecycle = importlib.import_module(name + '.' + prefix + 'integration.lifecycle')
    registry = importlib.import_module(name + '.' + prefix + 'integration.registry')
    for value in (lifecycle, registry):
        assert Path(value.__file__).resolve().is_relative_to(repository / 'perceptual_grade')
    application = lifecycle.registered_session()
    assert application is not None

    def module(suffix):
        value = importlib.import_module(name + '.' + suffix)
        assert Path(value.__file__).resolve().is_relative_to(repository / 'perceptual_grade')
        component = suffix.removeprefix(prefix)
        if suffix.startswith(prefix) and component in registry.COMPONENTS:
            return application.component(component)
        return value

    nodes, lut, resources = (module('perceptual_grade_blender.graph.' + part)
                             for part in ('nodes', 'lut', 'output_resources'))
    runtime = module('perceptual_grade_blender.services').get_runtime()
    started = time.monotonic()
    report = dict(passed=False, build=bpy.app.build_hash.decode(), events=[], saves=[],
                  transfers=[], save_pre=[], dirty_user_preserved=False,
                  native_user_warning=False, cancelled_without_save=False)
    user_name = 'Unrelated user paint image'
    case = ''
    serialized_output = {}

    def record(event, **values):
        report['events'].append(dict(event=event, seconds=round(time.monotonic() - started, 3), **values))
        destination.write_text(json.dumps(report, indent=2), encoding='utf8')
        print('PG_NATIVE_SAVE_EVENT', json.dumps(report['events'][-1]), flush=True)

    def bank_summary():
        values = []
        for current in nodes.all_nodes():
            for index, image in resources.bank_images(current).items():
                values.append(dict(tree=current.node_tree.bl_idname, index=index,
                    name=image.name, pointer=image.as_pointer(), dirty=image.is_dirty,
                    packed=bool(image.packed_file)))
        assert len(values) == 8, values
        return sorted(values, key=lambda item: (item['tree'], item['index']))

    def clean_banks(values):
        assert all(not item['dirty'] and item['packed'] for item in values), values

    def save_pre(*_):
        # Run before the production save_pre handler so that its packing
        # cannot conceal whether normal publication already cleared dirty.
        report['save_pre'].append(dict(case=case, banks=bank_summary()))
    bpy.app.handlers.save_pre.insert(0, save_pre)

    def output_snapshot():
        return {current.id_data.bl_idname: dict(
            kernel=current.node_tree.name, graph=lut._graph_snapshot(current),
            banks={index: (image.name, hashlib.sha256(image.packed_file.data).hexdigest())
                   for index, image in resources.bank_images(current).items()})
            for current in nodes.all_nodes()}

    def prepared_save(*_):
        # Capture the prepared native bytes after the production save_pre.
        # Restoring a UI wrapper adopts this output without creating a producer
        # receipt, so compare the actual serialized graph and bank bytes.
        serialized_output.clear()
        serialized_output.update(output_snapshot())
    bpy.app.handlers.save_pre.append(prepared_save)

    original_transfer = resources.transfer_payload
    def transfer(image, pixels, cube, diagnostics, **kwargs):
        result = original_transfer(image, pixels, cube, diagnostics, **kwargs)
        report['transfers'].append(dict(case=case, size=cube.size,
            index=image[resources.SLOT], encoding=image['_pg_cube_encoding'],
            dirty=image.is_dirty, packed=bool(image.packed_file)))
        return result
    resources.transfer_payload = transfer

    def save(label):
        nonlocal case
        case = label
        before = bank_summary()
        count = len(report['save_pre'])
        assert bpy.context.preferences.filepaths.save_modified_images == 'ASK'
        result = bpy.ops.wm.save_mainfile('INVOKE_DEFAULT', show_save_modified_images_dialog=True)
        report['saves'].append(dict(case=label, result=sorted(result), banks_before=before,
                                   handlers_before=count, handlers_after=len(report['save_pre'])))
        record('native_save_returned', case=label, result=sorted(result))
        # The warning returns INTERFACE synchronously, before any save_pre.
        assert result == {'FINISHED'}, report['saves'][-1]
        assert len(report['save_pre']) == count + 1, report['save_pre']
        clean_banks(before)
        clean_banks(report['save_pre'][-1]['banks'])
        after = bank_summary()
        clean_banks(after)
        assert [(item['name'], item['pointer']) for item in after] == [
            (item['name'], item['pointer']) for item in before]
        assert output_snapshot() == serialized_output
        for current in nodes.all_nodes():
            assert lut.is_adopted(current)
            assert current.bl_idname in ('PGShaderGrade', 'PGCompositorGrade')

    def edit(value, label):
        nonlocal case
        case = label
        for current in tuple(nodes.all_nodes()):
            nodes.write_chromatic(current, {'global_gain': value})
            lut.ensure(current, nodes.bake_model(current), force=True)
            lut.validate_output(current, nodes.bake_model(current), final=True)
        clean_banks(bank_summary())
        record('published', case=label, value=value)

    def user_state():
        image = bpy.data.images[user_name]
        pixels = np.empty(len(image.pixels), np.float32)
        image.pixels.foreach_get(pixels)
        return dict(dirty=image.is_dirty, packed=bool(image.packed_file), source=image.source,
                    filepath=image.filepath, digest=hashlib.sha256(pixels.tobytes()).hexdigest())

    def scenario():
        # Initial recovery is scheduled, so a fixed timer delay cannot prove
        # readiness when other native acceptance processes share the machine.
        while nodes.recovery_pending():
            yield
        bpy.context.scene.world.use_nodes = True
        nodes.create_grade(bpy.context.scene.world.node_tree)
        compositor = bpy.data.node_groups.new('Native save compositor', 'CompositorNodeTree')
        compositor.use_fake_user = True
        nodes.create_grade(compositor)
        del compositor
        # This catches all newly allocated banks, including unused storage,
        # before save_pre can bake and pack the requested final output.
        save('initialized')
        yield
        for value, label in ((.1, 'first_update'), (.25, 'reused_banks')):
            edit(value, label)
            save(label)
            yield

        image = bpy.data.images.new(user_name, width=4, height=4, float_buffer=True)
        image.pixels.foreach_set(np.tile(np.array((.25, .5, .75, 1.), np.float32), 16))
        image.update()
        del image
        original_user = user_state()
        assert original_user['dirty'] and not original_user['packed'], original_user
        # Publish AFTER the user edit: accidentally packing all bpy Images
        # instead of only owned LUT storage must fail this positive control.
        edit(.4, 'user_image_present')
        assert user_state() == original_user
        report['dirty_user_preserved'] = True
        count = len(report['save_pre'])
        original_project = hashlib.sha256(project.read_bytes()).hexdigest()
        result = bpy.ops.wm.save_mainfile('INVOKE_DEFAULT', show_save_modified_images_dialog=True)
        assert result == {'INTERFACE'}, result
        assert len(report['save_pre']) == count
        assert hashlib.sha256(project.read_bytes()).hexdigest() == original_project
        assert user_state() == original_user
        report['native_user_warning'] = True
        record('native_user_warning', result=sorted(result), save_pre_unchanged=True)
        yield
        yield
        window = bpy.context.window_manager.windows[0]
        window.event_simulate(type='ESC', value='PRESS', unicode=None)
        window.event_simulate(type='ESC', value='RELEASE', unicode=None)
        del window
        for _ in range(5):
            yield
        assert len(report['save_pre']) == count
        assert hashlib.sha256(project.read_bytes()).hexdigest() == original_project
        assert user_state() == original_user
        report['cancelled_without_save'] = True
        bpy.data.images.remove(bpy.data.images[user_name])
        save('after_user_warning_cancel')
        assert len(report['transfers']) >= 8, report['transfers']
        assert all(not item['dirty'] and item['packed'] for item in report['transfers'])
        assert {item['encoding'] for item in report['transfers']} == {'RGB', 'RGBE_DIFFERENCES'}

    sequence = scenario()
    def advance():
        try:
            if time.monotonic() - started > 150:
                raise TimeoutError('Native image-save acceptance exceeded 150 seconds')
            if getattr(bpy.context.window_manager, 'is_event_handling_break', False):
                return .05
            next(sequence)
            return .05
        except StopIteration:
            try:
                bpy.app.handlers.save_pre.remove(save_pre)
                bpy.app.handlers.save_pre.remove(prepared_save)
                resources.transfer_payload = original_transfer
                addon.unregister()
                report['cleanup_clean'] = runtime._shutdown_report.clean
                assert report['cleanup_clean']
                report['passed'] = True
                record('complete')
                bpy.ops.wm.quit_blender('EXEC_DEFAULT')
            except BaseException:
                report['error'] = traceback.format_exc()
                record('failed_teardown')
                os._exit(1)
            return None
        except BaseException:
            report['error'] = traceback.format_exc()
            record('failed')
            print(report['error'], flush=True)
            os._exit(1)

    record('started')
    bpy.app.timers.register(advance, first_interval=.5)


if __name__ == '__main__':
    main(*sys.argv[sys.argv.index('--') + 1:])
