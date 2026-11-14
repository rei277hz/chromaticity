"""Installed native reader probe: all banks are read, regardless of selection."""
import importlib
import hashlib
import json
from pathlib import Path
import sys
import threading
import time
import traceback

import addon_utils
import bpy
import numpy as np


def main(repository, report_path):
    repository, report_path = Path(repository).resolve(), Path(report_path)
    assert not bpy.app.background
    assert tuple(bpy.app.version) in {(5, 2, 4), (5, 3, 0)}, bpy.app.version
    bpy.context.preferences.view.show_splash = False
    bpy.context.preferences.extensions.repos.new(
        name='PG output reader acceptance', module='pg_reader', custom_directory=str(repository))
    name = 'bl_ext.pg_reader.perceptual_grade'
    failures = []
    addon = addon_utils.enable(name, default_set=False, handle_error=failures.append)
    assert addon is not None and not failures, repr(failures)
    lifecycle = importlib.import_module(name + '.perceptual_grade_blender.integration.lifecycle')
    assert Path(lifecycle.__file__).resolve().is_relative_to(repository / 'perceptual_grade')
    application = lifecycle.registered_session()
    assert application is not None
    guard, resources, lut = (application.component('graph.' + part)
                             for part in ('output_guard', 'output_resources', 'lut'))
    for component in (guard, resources, lut):
        assert Path(component.__file__).resolve().is_relative_to(repository / 'perceptual_grade')
    report = dict(passed=False, version=list(bpy.app.version), build=bpy.app.build_hash.decode(),
                  publications=0, failed_transfers=0, view_reads=0, render_reads=0,
                  blocked_render_attempts=0, blocked_light_bake_attempts=0,
                  light_bake_without_public_job=0, reads_by_bank=[0, 0, 0, 0], events=[],
                  render_reader_off_main=False, render_publication_acknowledged=False)
    expected = {}
    initial_links = ()
    started = time.monotonic()
    phase, turn, waiting_view = 'publish', 0, 0
    native_started = False
    light_event_timer = None
    render_reader_started = threading.Event()
    render_publication_attempted = threading.Event()

    def owner():
        return bpy.data.node_groups['PG reader owner'].nodes['Reader']

    class CreateResources(bpy.types.Operator):
        bl_idname = 'perceptual_grade.reader_resources'
        bl_label = 'Create reader probe resources'
        bl_options = {'UNDO'}

        def execute(self, context):
            tree = bpy.data.node_groups.new('PG reader owner', 'ShaderNodeTree')
            tree.use_fake_user = True
            node = tree.nodes.new('ShaderNodeGroup')
            node.name = 'Reader'
            node.node_tree = lut.make_kernel('ShaderNodeTree')
            return {'FINISHED'}

    bpy.utils.register_class(CreateResources)
    assert bpy.ops.perceptual_grade.reader_resources() == {'FINISHED'}
    for index, image in resources.bank_images(owner()).items():
        values = np.empty(len(image.pixels), np.float32)
        image.pixels.foreach_get(values)
        resources.validate_pixels(image, values)
        expected[index] = values
    initial_links = tuple((index, image.as_pointer())
                          for index, image in sorted(resources.bank_images(owner()).items()))

    def read_all(kind):
        assert not guard.publishing(), 'Native read overlapped payload transfer'
        if kind == 'view':
            assert threading.current_thread() is threading.main_thread()
        images = resources.bank_images(owner())
        assert tuple((index, image.as_pointer()) for index, image in sorted(images.items())) == initial_links
        for index, image in images.items():
            values = np.empty(len(image.pixels), np.float32)
            image.pixels.foreach_get(values)
            resources.validate_pixels(image, values)
            np.testing.assert_array_equal(values, expected[index])
            report['reads_by_bank'][index] += 1
        report[kind + '_reads'] += 1

    class ReaderEngine(bpy.types.RenderEngine):
        bl_idname = 'PG_HOST_READER_CONTRACT'
        bl_label = 'PG host reader contract'
        bl_use_preview = True

        def view_update(self, context, depsgraph):
            try:
                read_all('view')
            except BaseException:
                failures.append(traceback.format_exc())

        def view_draw(self, context, depsgraph):
            return None

        def render(self, depsgraph):
            try:
                assert threading.current_thread() is not threading.main_thread(), \
                    'The asynchronous render reader must run off the main thread'
                report['render_reader_off_main'] = True
                read_all('render')
                # The WM render job remains a native reader while the main
                # thread's timer attempts publication. No bpy runs in this wait.
                render_reader_started.set()
                if not render_publication_attempted.wait(10):
                    raise TimeoutError('Main thread did not acknowledge publication exclusion during RENDER')
                read_all('render')
                result = self.begin_result(0, 0, 8, 8)
                result.layers[0].passes['Combined'].rect = [[.1, .2, .3, 1.]] * 64
                self.end_result(result)
            except BaseException:
                failures.append(traceback.format_exc())

    bpy.utils.register_class(ReaderEngine)
    scene = bpy.context.scene
    scene.render.engine = ReaderEngine.bl_idname
    scene.render.resolution_x = scene.render.resolution_y = 8
    scene.render.resolution_percentage = 100
    scene.render.use_lock_interface = False
    if scene.camera is None:
        camera = bpy.data.objects.new('Reader camera', bpy.data.cameras.new('Reader camera'))
        scene.collection.objects.link(camera)
        scene.camera = camera
    for area in bpy.context.screen.areas:
        if area.type == 'VIEW_3D':
            area.spaces.active.shading.type = 'RENDERED'
            area.tag_redraw()

    def request_view():
        scene.update_tag()
        owner().node_tree.update_tag()
        for window in bpy.context.window_manager.windows:
            for area in window.screen.areas:
                if area.type == 'VIEW_3D':
                    area.tag_redraw()

    def install(number):
        node = owner()
        size = 33 if number % 4 < 2 else 65
        cube = lut.cm.Cube(np.full((size, size, size, 3), .05 + number * .01, np.float32),
                           hashlib.sha256(('native-reader-' + str(number)).encode()).hexdigest(), size=size)
        with guard.publication():
            reservation = resources.reserve(node, size, cube.signature)
            index = reservation['index']
            image = resources.bank_images(node)[index]
            resources.arm(node, reservation, image)
            if number == 5:
                # This controlled partial transfer leaves bounded whole floats.
                # The runtime retains an unfinished producer receipt and leaves
                # these bytes alone; only this independent reader probe reads them.
                values = expected[index].copy()
                values[:len(values) // 2] = cube.pixels().ravel()[:len(values) // 2]
                resources.validate_pixels(image, values)
                image.pixels.foreach_set(values)
                image.update()
                expected[index] = values
                old_selector = resources.selected_index(node)
                resources.receipt(node, 'fail', reservation)
                assert resources.selected_index(node) == old_selector
                slot = resources.record(node.node_tree, node)['state'].slots[index]
                assert slot.readability == resources.policy.UNKNOWN and slot.debt and not slot.valid
                assert resources.payload_record(image)['phase'] == 'WRITING'
                report['failed_transfers'] += 1
            else:
                values = cube.pixels().ravel()
                resources.transfer_payload(image, values, cube, {}, node=node, reservation=reservation)
                expected[index] = values.copy()
                resources.receipt(node, 'transferred', reservation, validated=True)
                lut._install_graph(node, index, lut._checked_rows(np.eye(3), np.eye(3)))
                lut.validate_output(node)
                report['publications'] += 1
            image.update_tag()
        request_view()

    def start_light_bake():
        nonlocal light_event_timer
        # Connect the production banks to a material used by the native bake.
        tree = owner().id_data
        tree.interface.new_socket(name='Color', in_out='OUTPUT', socket_type='NodeSocketColor')
        group_output = tree.nodes.new('NodeGroupOutput')
        tree.links.new(owner().outputs['Color'], group_output.inputs['Color'])
        material = bpy.data.materials.new('Reader bake material')
        material.use_nodes = True
        group = material.node_tree.nodes.new('ShaderNodeGroup')
        group.node_tree = tree
        material.node_tree.links.new(group.outputs['Color'],
                                    material.node_tree.nodes['Principled BSDF'].inputs['Base Color'])
        bpy.data.objects['Cube'].data.materials.clear()
        bpy.data.objects['Cube'].data.materials.append(material)
        probe = bpy.data.lightprobes.new('Reader bake probe', 'VOLUME')
        probe.resolution_x = probe.resolution_y = probe.resolution_z = 2
        probe.bake_samples = 16
        obj = bpy.data.objects.new('Reader bake probe', probe)
        scene.collection.objects.link(obj)
        scene.render.engine = 'BLENDER_EEVEE'
        for area in bpy.context.screen.areas:
            if area.type == 'VIEW_3D':
                area.spaces.active.shading.type = 'SOLID'
        assert bpy.ops.object.lightprobe_cache_bake('INVOKE_DEFAULT', subset='ALL') == {'RUNNING_MODAL'}
        # The operator retires when it next handles an event after its worker
        # finishes. Application timers alone do not supply a window event.
        light_event_timer = bpy.context.window_manager.event_timer_add(.05, window=bpy.context.window)

    def blocked_light_bake():
        names = [operator.bl_idname for manager in bpy.data.window_managers
                 for window in manager.windows for operator in window.modal_operators]
        if 'OBJECT_OT_lightprobe_cache_bake' not in names:
            return False
        assert not guard.available()
        assert 'OBJECT_OT_lightprobe_cache_bake' in guard.reason()
        try:
            with guard.publication():
                raise AssertionError('Publication entered during native light bake')
        except guard.PublicationDeferred:
            report['blocked_light_bake_attempts'] += 1
        if not any(bpy.app.is_job_running(job) for job in guard.JOBS):
            report['light_bake_without_public_job'] += 1
        return True

    def finish(error=None):
        # Release the worker on harness failure too. Only the successful main
        # thread exclusion assertion sets render_publication_acknowledged.
        render_publication_attempted.set()
        if light_event_timer is not None:
            bpy.context.window_manager.event_timer_remove(light_event_timer)
        report['elapsed'] = time.monotonic() - started
        report['failures'] = list(failures)
        if error:
            report['error'] = error
        report['passed'] = not error and not failures
        report_path.write_text(json.dumps(report, indent=2), encoding='utf8')
        print('PG_OUTPUT_READER', json.dumps(report), flush=True)
        bpy.ops.wm.quit_blender()

    def tick():
        nonlocal phase, turn, waiting_view, native_started
        try:
            if failures:
                raise AssertionError('\n'.join(failures))
            if time.monotonic() - started > 90:
                raise TimeoutError('Native output reader probe timed out: ' + phase)
            if phase == 'publish':
                if report['view_reads'] <= waiting_view:
                    request_view()
                    return .05
                if not guard.available():
                    return .05
                if turn < 12:
                    waiting_view = report['view_reads']
                    install(turn)
                    turn += 1
                    return .05
                phase = 'render'
                assert bpy.ops.render.render('INVOKE_DEFAULT') == {'RUNNING_MODAL'}
                return .01
            if phase == 'render':
                if bpy.app.is_job_running('RENDER'):
                    if render_reader_started.is_set() and not render_publication_attempted.is_set():
                        native_started = True
                        assert threading.current_thread() is threading.main_thread()
                        assert not guard.available()
                        reason = guard.reason()
                        try:
                            with guard.publication():
                                raise AssertionError('Publication entered during native render')
                        except guard.PublicationDeferred as error:
                            report['blocked_render_attempts'] += 1
                            report['events'].append(dict(event='render_publication_rejected',
                                seconds=time.monotonic() - started, native_job='RENDER',
                                job_running=True, main_thread=True, reader_started=True,
                                reason=reason, rejection=str(error)))
                        report['render_publication_acknowledged'] = True
                        render_publication_attempted.set()
                    return .01
                if not native_started:
                    return .01
                assert report['render_reads'] == 2
                assert report['blocked_render_attempts'] > 0
                assert report['view_reads'] >= 13
                assert all(value >= 15 for value in report['reads_by_bank'])
                assert report['failed_transfers'] == 1
                start_light_bake()
                assert blocked_light_bake()
                phase = 'light_bake'
                return .01
            if phase == 'light_bake':
                if blocked_light_bake():
                    return .01
                assert report['blocked_light_bake_attempts'] > 0
                assert report['light_bake_without_public_job'] > 0
                finish()
                return None
        except BaseException:
            finish(traceback.format_exc())
            return None

    bpy.app.timers.register(tick, first_interval=.1)


if __name__ == '__main__':
    main(*sys.argv[sys.argv.index('--') + 1:])
