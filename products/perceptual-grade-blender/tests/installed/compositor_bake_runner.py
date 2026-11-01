"""Generated scenes and actual WM events against the installed extension ZIP.

Only scalar names and immutable values cross native load/undo boundaries.
All projects, reference renders and extension files belong to the test tempdir.
"""
import importlib
import hashlib
import json
import os
from pathlib import Path
import signal
import sys
import time
import traceback
from types import SimpleNamespace

import addon_utils
import bpy
import numpy as np


def main(repository, report_path):
    repository, report_path = Path(repository).resolve(), Path(report_path)
    assert not bpy.app.background and tuple(bpy.app.version) == (5, 2, 2)
    bpy.context.preferences.view.show_splash = False
    bpy.context.preferences.edit.use_global_undo = True
    bpy.context.preferences.edit.undo_steps = 64
    bpy.context.preferences.system.gpu_backend = 'METAL' if sys.platform == 'darwin' else 'OPENGL'
    bpy.context.preferences.extensions.repos.new(name='Compositor bake acceptance',
        module='pg_bake', custom_directory=str(repository))
    name = 'bl_ext.pg_bake.perceptual_grade'
    errors = []
    addon = addon_utils.enable(name, default_set=False, handle_error=errors.append)
    assert addon is not None and not errors, repr(errors)
    assert Path(addon.__file__).resolve() == repository / 'perceptual_grade/__init__.py'
    lifecycle = importlib.import_module(name + '.perceptual_grade_blender.integration.lifecycle')
    projection = importlib.import_module(name + '.perceptual_grade_core.model.export')
    assert Path(lifecycle.__file__).resolve().is_relative_to(repository / 'perceptual_grade')
    application = lifecycle.registered_session()
    nodes, grades, stacks, lut, bake, capture, output, guard = (
        application.component(part) for part in ('graph.nodes', 'graph.grades', 'graph.stacks',
        'graph.lut', 'graph.bake', 'scopes.capture', 'graph.output', 'graph.output_guard'))
    runtime = application.app.execution.get_runtime()
    assert runtime.session.path.is_relative_to(report_path.parent)
    report = dict(passed=False, blender=list(bpy.app.version), build=bpy.app.build_hash.decode(),
                  events=[], snapshots={}, rebakes=[])
    started = time.monotonic()
    stopped = set()
    disable_pending = {}
    original_submit = runtime.submit
    capture_starts = 0
    def counted_submit(spec):
        nonlocal capture_starts
        if spec.operation == 'compositor_bake':
            capture_starts += 1
        return original_submit(spec)
    runtime.submit = counted_submit
    drawn_nodes = set()
    original_draw_action = bake.draw_action

    def observed_draw(layout, node, context=None):
        result = original_draw_action(layout, node, context)
        if isinstance(layout, bpy.types.UILayout):
            drawn_nodes.add((node.id_data.name, node.name))
        return result

    object.__getattribute__(application._component('graph.bake'), '_Component__exports')[
        'draw_action'] = observed_draw

    class RecordingLayout:
        def __init__(self, parent=None):
            self.enabled = True if parent is None else parent.enabled
            self.controls = [] if parent is None else parent.controls
            self.labels = [] if parent is None else parent.labels
        def row(self, **_kwargs):
            return RecordingLayout(self)
        column = row
        box = row
        def template_ID(self, _node, name, **_kwargs):
            self.controls.append((name, self.enabled))
        def context_pointer_set(self, *_args):
            pass
        def prop(self, _value, name, **_kwargs):
            self.controls.append((name, self.enabled))
        def operator(self, name, **_kwargs):
            self.controls.append((name, self.enabled))
            return SimpleNamespace()
        def label(self, *, text='', icon=None):
            self.labels.append((text, icon))

    def assert_bake_controls(enabled):
        window, area, region = editor()
        waiting = application.component('localization.i18n').tip('bake.blocked.waiting')
        for label in ('Grade', 'Stack'):
            setup_editor(label)
            with bpy.context.temp_override(window=window, area=area, region=region):
                layout = RecordingLayout()
                bake.draw_action(layout, current(label), bpy.context)
                assert ('pg_bake_image', enabled) in layout.controls, layout.controls
                assert ('perceptual_grade.bake_compositor', enabled) in layout.controls, layout.controls
                assert bpy.ops.perceptual_grade.bake_compositor.poll() == enabled
                assert (waiting, 'TIME') not in layout.labels, layout.labels
                if not enabled:
                    assert bake.PG_OT_bake_compositor.description(bpy.context, None) == waiting

    def control_state(node):
        return dict(kind=node.bl_idname,
            grade=None if node.pg_grade is None else node.pg_grade.name,
            entries=[(None if item.grade is None else item.grade.name, item.enabled, item.direction, item.key)
                     for item in node.pg_stack_entries],
            image=None if node.pg_bake_image is None else node.pg_bake_image.name,
            sockets=[(direction, socket.identifier, bool(socket.hide))
                for direction, sockets in (('INPUT', node.inputs), ('OUTPUT', node.outputs))
                for socket in sockets])

    def assert_reopened_controls(saved_controls):
        setup_editor('Grade')
        window, area, region = editor()
        with bpy.context.temp_override(window=window, area=area, region=region):
            bpy.ops.node.view_all()
        area.tag_redraw()
        yield from wait(lambda: all(('Bake source graph', label) in drawn_nodes
                                   for label in saved_controls),
                        'Reopened Grade/Stack did not draw native Bake controls', timeout=10)
        i18n = application.component('localization.i18n')
        for label, expected in saved_controls.items():
            node = current(label)
            assert control_state(node) == expected, (label, control_state(node), expected)
            assert node.show_options and node.bl_idname in ('PGCompositorGrade', 'PGCompositorStack')
            setup_editor(label)
            with bpy.context.temp_override(window=window, area=area, region=region):
                layout = RecordingLayout()
                if label == 'Grade':
                    grades.draw_selector(layout, node)
                    bake.draw_action(layout, node, bpy.context)
                else:
                    stacks.draw(layout, node, bpy.context)
                selector = 'pg_grade' if label == 'Grade' else 'grade'
                for name in (selector, 'pg_bake_image', 'perceptual_grade.bake_compositor'):
                    assert any(control == name for control, _enabled in layout.controls), layout.controls
                assert node.bl_rna.properties['pg_grade'].description == i18n.native('grade.selector.tooltip')
                assert node.bl_rna.properties['pg_bake_image'].description == i18n.native('bake.destination.tooltip')
                observation = bake.eligibility(node, bpy.context)
                expected_tip = i18n.tip('bake.blocked.' + observation['code']
                    if observation['code'] else 'bake.tooltip')
                assert expected_tip and bake.PG_OT_bake_compositor.description(bpy.context, None) == expected_tip
        report['reopened_controls_drawn'] = report['reopened_selections'] = True
        report['reopened_tooltips'] = True

    def record(event, **values):
        report['events'].append(dict(event=event, seconds=round(time.monotonic() - started, 3), **values))
        report_path.write_text(json.dumps(report, indent=2), encoding='utf8')
        print('PG_COMPOSITOR_BAKE', json.dumps(report['events'][-1]), flush=True)

    def pixels(image):
        result = np.empty(len(image.pixels), dtype=np.float32)
        image.pixels.foreach_get(result)
        return result.reshape(image.size[1], image.size[0], image.channels)

    def graph_state():
        tree = bpy.data.node_groups['Bake source graph']
        return (tuple(sorted((node.name, node.bl_idname,
                       getattr(getattr(node, 'node_tree', None), 'name', None)) for node in tree.nodes)),
                tuple(sorted((link.from_node.name, link.from_socket.identifier,
                       link.to_node.name, link.to_socket.identifier) for link in tree.links)),
                tree.nodes['Transform'].inputs['X'].default_value)

    def settings():
        scene = bpy.context.scene
        return (scene.name, scene.frame_current, scene.frame_subframe, scene.render.engine,
                scene.render.resolution_x, scene.render.resolution_y,
                scene.render.resolution_percentage, scene.render.filepath,
                scene.render.image_settings.file_format, scene.render.image_settings.color_depth)

    def render(label):
        path = report_path.parent / (label + '.exr')
        output.guarded_render()
        bpy.data.images['Render Result'].save_render(str(path), scene=bpy.context.scene)
        image = bpy.data.images.load(str(path), check_existing=False)
        try:
            image.colorspace_settings.name = 'Non-Color'
            image.alpha_mode = 'CHANNEL_PACKED'
            return pixels(image).copy()
        finally:
            bpy.data.images.remove(image)
            path.unlink()

    def fill_source(width, height, phase=0):
        image = bpy.data.images['Generated signed HDR source']
        if tuple(image.size) != (width, height):
            image.scale(width, height)
        y, x = np.mgrid[:height, :width]
        rgba = np.stack((-.2513 + x * .0137 + phase * .021,
                         2.013 + y * .0271 + phase * .037,
                         .5137 + x * .0093,
                         np.where((x + y) % 2, .375, .75)), axis=-1).astype(np.float32)
        image.pixels.foreach_set(rgba.ravel()); image.update(); image.pack()

    def analytic(label, rgba):
        model = nodes.bake_model(current(label))
        before, after = lut.scope_rows(current(label), model)
        native = projection.input_repair(
            rgba[..., :3].astype(np.float64) @ before.T, lut.cm.AP1_Y).astype(np.float32)
        core = model.prepare().bake_native(native)[..., :3]
        expected = rgba.copy()
        expected[..., :3] = (core.astype(np.float64) @ after.T).astype(np.float32)
        return expected

    def render_socket(label, socket, width, height):
        scene = bpy.context.scene
        tree = bpy.data.node_groups['Bake source graph']
        final = tree.nodes['Output'].inputs['Image']
        old = tuple((link.from_node.name, link.from_socket.identifier) for link in final.links)
        dimensions = scene.render.resolution_x, scene.render.resolution_y
        try:
            scene.render.resolution_x, scene.render.resolution_y = width, height
            tree.links.new(tree.nodes[label].outputs[socket], final)
            return render('native-reference')
        finally:
            for link in tuple(final.links):
                tree.links.remove(link)
            for node_name, identifier in old:
                tree.links.new(tree.nodes[node_name].outputs[identifier], final)
            scene.render.resolution_x, scene.render.resolution_y = dimensions

    def expected_current(label):
        width, height = bpy.data.images['Generated signed HDR source'].size
        upstream = render_socket('Transform', 'Image', width, height)
        return analytic(label, upstream)

    def setup():
        scene = bpy.context.scene
        scene.name = 'Generated compositor bake'
        for obj in tuple(scene.objects):
            bpy.data.objects.remove(obj, do_unlink=True)
        camera = bpy.data.objects.new('Bake reference camera', bpy.data.cameras.new('Bake reference camera'))
        scene.collection.objects.link(camera)
        scene.camera = camera
        scene.render.engine = 'CYCLES'
        scene.cycles.device = 'CPU'
        scene.cycles.samples = 1
        scene.cycles.use_denoising = False
        scene.render.resolution_x, scene.render.resolution_y = 32, 16
        scene.render.resolution_percentage = 100
        scene.render.compositor_device = 'CPU'
        scene.render.image_settings.file_format = 'OPEN_EXR'
        scene.render.image_settings.color_mode = 'RGBA'
        scene.render.image_settings.color_depth = '32'
        scene.render.image_settings.color_management = 'OVERRIDE'
        scene.render.image_settings.linear_colorspace_settings.name = 'scene_linear'
        scene.frame_set(27, subframe=.25)
        tree = bpy.data.node_groups.new('Bake source graph', 'CompositorNodeTree')
        tree.interface.new_socket(name='Image', in_out='OUTPUT', socket_type='NodeSocketColor')
        scene.compositing_node_group = tree
        image = bpy.data.images.new('Generated signed HDR source', width=32, height=16,
                                    alpha=True, float_buffer=True)
        image.colorspace_settings.name = 'Non-Color'
        image.alpha_mode = 'CHANNEL_PACKED'
        fill_source(32, 16)
        source = tree.nodes.new('CompositorNodeImage'); source.image = image
        transform = tree.nodes.new('CompositorNodeTransform'); transform.name = 'Transform'
        transform.inputs['X'].default_value = 2
        transform.inputs['Interpolation'].default_value = 'Nearest'
        tree.links.new(source.outputs['Image'], transform.inputs['Image'])
        grade = nodes.create_grade(tree); grade.name = 'Grade'
        grade.location = (0, 0)
        nodes.write_values(grade, {'exposure': .35})
        nodes.write_chromatic(grade, {'global_gain': .1})
        lut.ensure(grade, nodes.bake_model(grade), force=True)
        tree.links.new(transform.outputs['Image'], grade.inputs['Color'])
        stack = stacks.create(tree); stack.name = 'Stack'
        stack.location = (320, 0)
        with grades.guarded(stack):
            for index in range(2):
                entry = stack.pg_stack_entries.add(); entry.grade = grade.pg_grade; entry.key = str(index)
        stacks.bind_dependencies(stack); stacks.refresh(stack, True)
        lut.ensure(stack, nodes.bake_model(stack), force=True)
        tree.links.new(transform.outputs['Image'], stack.inputs['Color'])
        final = tree.nodes.new('NodeGroupOutput'); final.name = 'Output'; final.is_active_output = True
        tree.interface.new_socket(name='Stack Color', in_out='OUTPUT', socket_type='NodeSocketColor')
        tree.links.new(grade.outputs['Color'], final.inputs['Image'])
        tree.links.new(stack.outputs['Color'], final.inputs['Stack Color'])
        upstream = render_socket('Transform', 'Image', 32, 16)
        expected = {}
        for node in (grade, stack):
            expected[node.name] = analytic(node.name, upstream)
            interpolated = render_socket(node.name, 'Color', 32, 16)
            difference = float(np.max(np.abs(interpolated[..., :3] - expected[node.name][..., :3])))
            assert difference > 1e-6, ('Fixture must distinguish analytic evaluation from LUT interpolation', difference)
            report['snapshots'][node.name] = dict(analytic_lut_difference=difference)
            assert 'Baked Color' in node.outputs and bake.baked_image(node) is None
        # Existing live Color links remain in place throughout baking. The
        # upstream image domain is deliberately larger than the scene canvas.
        scene.render.resolution_x, scene.render.resolution_y = 16, 8
        scene['_pg_test_intervening_edit'] = 0
        return expected

    def current(node='Grade'):
        return bpy.data.node_groups['Bake source graph'].nodes[node]

    def image_names():
        return {image.name for image in bpy.data.images if image.get('_pg_bake_kind') == 'COMPOSITOR'}

    def snapshot_directories():
        return tuple(path for pattern in ('capture-*', 'bake-*')
                     for path in runtime.session.path.glob(pattern))

    def metadata(image):
        return {key: (list(value) if key == '_pg_bake_domain' else value)
                for key, value in image.items() if key.startswith('_pg_bake_')}

    def assert_image(image, expected):
        assert image.is_float and image.channels == 4 and tuple(image.size) == expected.shape[1::-1]
        assert image.packed_file is not None and image.packed_file.size > 0 and not image.is_dirty
        assert image.colorspace_settings.name == 'Non-Color' and image.alpha_mode == 'CHANNEL_PACKED'
        actual = pixels(image)
        np.testing.assert_allclose(actual, expected, rtol=0, atol=3e-6)
        assert actual[..., :3].min() < 0 and actual[..., :3].max() > 1
        assert np.any(np.isclose(actual[..., 3], .375)) and np.any(np.isclose(actual[..., 3], .75))
        return float(np.max(np.abs(actual - expected)))

    def editor():
        window = bpy.context.window_manager.windows[0]
        area = next(area for area in window.screen.areas if area.type == 'NODE_EDITOR')
        region = next(region for region in area.regions if region.type == 'WINDOW')
        return window, area, region

    def setup_editor(label='Grade'):
        window = bpy.context.window_manager.windows[0]
        area = max(window.screen.areas, key=lambda area: area.width * area.height)
        with bpy.context.temp_override(window=window, area=area):
            area.type = 'NODE_EDITOR'; area.ui_type = 'CompositorNodeTree'
            area.spaces.active.pin = True
            area.spaces.active.node_tree = bpy.data.node_groups['Bake source graph']
        tree = bpy.data.node_groups['Bake source graph']
        tree.nodes.active = current(label)
        for node in tree.nodes:
            node.select = node == current(label)

    class PGTEST_OT_intervening_edit(bpy.types.Operator):
        bl_idname = 'pgtest.intervening_edit'
        bl_label = 'Bake acceptance intervening edit'
        bl_options = {'REGISTER', 'UNDO'}
        def execute(self, context):
            context.scene['_pg_test_intervening_edit'] += 1
            return {'FINISHED'}

    def emit(kind, value='PRESS', **modifiers):
        window, area, region = editor()
        window.event_simulate(type=kind, value=value, unicode=None,
            x=region.x + region.width // 2, y=region.y + region.height // 2, **modifiers)

    def turns(count=5):
        for _ in range(count):
            yield

    def key(kind, **modifiers):
        emit(kind, **modifiers); yield from turns()
        emit(kind, 'RELEASE', **modifiers); yield from turns()
        if kind == 'Z' and modifiers.get('ctrl'):
            yield from wait(lambda:nodes.recovery_status()['state'] in ('completed','failed'),
                            'Native replacement reconciliation did not finish', timeout=10)

    def wait(predicate, label, timeout=180):
        deadline = time.monotonic() + timeout
        while not predicate():
            assert time.monotonic() < deadline, label
            yield

    def pause_capture():
        helper = runtime.helpers['bake_0']
        assert helper.process.poll() is None
        os.kill(helper.process.pid, signal.SIGSTOP)
        stopped.add(helper.process.pid)

    def resume():
        for pid in tuple(stopped):
            try:
                os.kill(pid, signal.SIGCONT)
            except ProcessLookupError:
                pass
            stopped.discard(pid)

    def playback(active):
        window, area, region = editor()
        with bpy.context.temp_override(window=window, area=area, region=region):
            if active:
                assert bpy.ops.screen.animation_play() == {'FINISHED'}
            elif window.screen.is_animation_playing:
                bpy.ops.screen.animation_cancel(restore_frame=False)

    def push_baseline(label):
        window, area, region = editor()
        with bpy.context.temp_override(window=window, area=area, region=region):
            assert bpy.ops.perceptual_grade.bake_compositor.poll()
            assert bpy.ops.ed.undo_push(message=label) == {'FINISHED'}

    def create_replay_nodes(saved):
        replay = bpy.data.node_groups.new('Bake replay graph', 'CompositorNodeTree')
        replay.use_fake_user = True
        replay.interface.new_socket(name='Image', in_out='OUTPUT', socket_type='NodeSocketColor')
        replay.nodes.new('NodeGroupOutput').name = 'Output'
        for label, value in saved.items():
            for suffix in ('A', 'B'):
                node = bake.create_node(replay)
                node.name = label + ' ' + suffix
                node.pg_bake_image = bpy.data.images[value['name']]

    def assert_shared(label, name, expected, saved_metadata=None):
        image = bpy.data.images[name]
        assert bake.baked_image(current(label)) == image
        assert current(label).pg_bake_image == image
        assert 'Baked Color' in current(label).outputs
        replay = bpy.data.node_groups.get('Bake replay graph')
        if replay is not None:
            for suffix in ('A', 'B'):
                node = replay.nodes[label + ' ' + suffix]
                assert node.bl_idname == 'PGCompositorBake' and node.pg_bake_image == image
        error = assert_image(image, expected)
        if saved_metadata is not None:
            assert metadata(image) == saved_metadata
        return error

    def render_shared(label, expected):
        before_graph, before_settings = graph_state(), settings()
        height, width = expected.shape[:2]
        actual = render_socket(label, 'Baked Color', width, height)
        np.testing.assert_allclose(actual, expected, rtol=0, atol=3e-6)
        scene = bpy.context.scene
        source_tree = scene.compositing_node_group
        dimensions = scene.render.resolution_x, scene.render.resolution_y
        replay = bpy.data.node_groups['Bake replay graph']
        try:
            scene.compositing_node_group = replay
            scene.render.resolution_x, scene.render.resolution_y = width, height
            for suffix in ('A', 'B'):
                replay.links.new(replay.nodes[label + ' ' + suffix].outputs['Color'],
                                 replay.nodes['Output'].inputs['Image'])
                np.testing.assert_allclose(render('standalone-replay'), expected, rtol=0, atol=3e-6)
        finally:
            scene.compositing_node_group = source_tree
            scene.render.resolution_x, scene.render.resolution_y = dimensions
        assert graph_state() == before_graph and settings() == before_settings

    def scenario():
        yield from wait(lambda:nodes.recovery_status()['state']=='completed',
                        'Initial native state adoption did not finish', timeout=10)
        expected = setup()
        before_graph, before_settings = graph_state(), settings()
        saved = {}
        token = bake.start(current('Grade'))
        yield from wait(lambda: bake.status(token) is not None, 'Grade bake did not become ready')
        artifact = bake.status(token)
        path = artifact['path']
        assert artifact['evaluation'] == 'ANALYTIC' and artifact['analytic_signature']
        image = bake.finish(token)
        assert image is not None and image.use_fake_user
        error = assert_shared('Grade', image.name, expected['Grade'])
        saved['Grade'] = dict(name=image.name, metadata=metadata(image))
        assert tuple(image['_pg_bake_domain']) == (32, 16)
        assert image['_pg_bake_scene'] == bpy.context.scene.name
        assert image['_pg_bake_node'] == 'Grade' and image['_pg_bake_frame'] == 27
        assert image['_pg_bake_subframe'] == .25 and image['_pg_bake_engine'] == 'CYCLES'
        assert image['_pg_bake_evaluation'] == 'ANALYTIC'
        assert not Path(path).exists() and not Path(path).parent.exists()
        report['snapshots']['Grade'].update(domain=[32, 16], canvas=[16, 8], maximum_error=error)
        del image, artifact
        assert graph_state() == before_graph and settings() == before_settings
        record('analytic_grade_bound')

        # The first Stack bake runs through WM, covering image creation and its
        # source binding in one native undo action after an intervening edit.
        setup_editor('Stack')
        bpy.utils.register_class(PGTEST_OT_intervening_edit)
        keymap = bpy.context.window_manager.keyconfigs.addon.keymaps.new(name='Screen', space_type='EMPTY')
        for operator, key_name, modifiers in (
            ('perceptual_grade.bake_compositor', 'F6', {}),
            ('pgtest.intervening_edit', 'F7', {}),
            ('ed.undo', 'Z', {'ctrl': True}), ('ed.redo', 'Z', {'ctrl': True, 'shift': True})):
            keymap.keymap_items.new(operator, key_name, 'PRESS', **modifiers)
        del keymap
        bpy.context.window_manager.keyconfigs.update()
        yield from turns(12)
        push_baseline('Before first Stack image')
        original_images = image_names()
        pause_capture()
        yield from key('F6')
        yield from wait(bake.busy, 'WM did not start the Stack bake')
        yield from key('F7')
        assert image_names() == original_images and bake.baked_image(current('Stack')) is None
        resume()
        yield from wait(lambda: not bake.busy(), 'Modal Stack bake did not finish')
        yield from turns()
        added = image_names() - original_images
        assert len(added) == 1, (added, bake.last_error)
        stack_image = next(iter(added))
        error = assert_shared('Stack', stack_image, expected['Stack'])
        saved['Stack'] = dict(name=stack_image, metadata=metadata(bpy.data.images[stack_image]))
        report['snapshots']['Stack'].update(domain=[32, 16], canvas=[16, 8], maximum_error=error)
        count = capture_starts
        yield from key('Z', ctrl=True)
        assert image_names() == original_images and bake.baked_image(current('Stack')) is None
        assert bpy.context.scene['_pg_test_intervening_edit'] == 1
        yield from key('Z', ctrl=True, shift=True)
        assert_shared('Stack', stack_image, expected['Stack'], saved['Stack']['metadata'])
        assert capture_starts == count and not bake.busy()
        assert bpy.context.scene['_pg_test_intervening_edit'] == 1
        report['first_bake_undo_redo'] = True
        assert graph_state() == before_graph and settings() == before_settings
        report['source_graph_unchanged'] = report['settings_unchanged'] = True
        record('first_stack_native_undo_redo')

        # The selector derives its value from the existing native binding;
        # choosing a saved bake changes only this node's Baked Color source.
        original_bindings = {label: current(label).pg_bake_image.name for label in saved}
        choices = {image.name for image in bpy.data.images if bake.image_allowed(current('Grade'), image)}
        assert choices == set(original_bindings.values())
        current('Grade').pg_bake_image = bpy.data.images[original_bindings['Stack']]
        assert bake.baked_image(current('Grade')) == bpy.data.images[original_bindings['Stack']]
        assert current('Stack').pg_bake_image.name == original_bindings['Stack']
        current('Grade').pg_bake_image = None
        assert bake.baked_image(current('Grade')) is None
        current('Grade').pg_bake_image = bpy.data.images[original_bindings['Grade']]
        report['destination_selection'] = True

        # Distinct destinations compute in separate native processes. Pause
        # the first worker so the second publication must overtake it.
        bpy.context.scene.frame_set(28)
        push_baseline('Before concurrent compositor publications')
        pause_capture()
        setup_editor('Grade');yield from key('F6')
        yield from wait(lambda:bake.busy(current('Grade')),'First parallel bake was not admitted')
        setup_editor('Stack');yield from key('F6')
        yield from wait(lambda:not bake.busy(current('Stack')),'Second worker did not publish independently')
        assert bake.busy(current('Grade'))
        assert bake.baked_image(current('Stack'))['_pg_bake_frame'] == 28
        assert bake.baked_image(current('Grade'))['_pg_bake_frame'] == 27
        assert runtime.helpers['bake_0'].process.pid != runtime.helpers['bake_1'].process.pid
        resume();yield from wait(lambda:not bake.busy(),'First parallel bake did not finish')
        assert bake.baked_image(current('Grade'))['_pg_bake_frame'] == 28
        count=capture_starts
        yield from key('Z',ctrl=True)
        assert bake.baked_image(current('Grade'))['_pg_bake_frame'] == 27
        assert bake.baked_image(current('Stack'))['_pg_bake_frame'] == 28
        yield from key('Z',ctrl=True)
        assert bake.baked_image(current('Stack'))['_pg_bake_frame'] == 27
        yield from key('Z',ctrl=True,shift=True)
        yield from key('Z',ctrl=True,shift=True)
        assert all(bake.baked_image(current(label))['_pg_bake_frame'] == 28 for label in saved)
        assert capture_starts == count
        yield from key('Z',ctrl=True);yield from key('Z',ctrl=True)
        report['parallel_bakes'] = report['parallel_publication_undo'] = True

        # Deliberately shared storage follows click order, even with an idle
        # second worker. The queued request already owns its frozen snapshot.
        current('Stack').pg_bake_image=bpy.data.images[original_bindings['Grade']]
        bpy.context.scene.frame_set(29)
        push_baseline('Before shared-destination compositor publications')
        pause_capture()
        setup_editor('Grade');yield from key('F6')
        setup_editor('Stack');yield from key('F6')
        yield from wait(lambda:len(bake.states)==2,'Shared destination request was not queued')
        assert sorted(entry.phase for entry in bake.queue.state.entries if entry.request)==['queued','running']
        assert sum(state['handle'] is not None for state in capture.bakes.values())==1
        resume();yield from wait(lambda:not bake.busy(),'Shared destination queue did not drain')
        shared=bake.baked_image(current('Grade'))
        assert shared==bake.baked_image(current('Stack'))
        assert shared['_pg_bake_node']=='Stack' and shared['_pg_bake_frame']==29
        assert_image(shared,expected['Stack']);del shared
        count=capture_starts
        yield from key('Z',ctrl=True)
        assert_image(bake.baked_image(current('Grade')),expected['Grade'])
        assert bake.baked_image(current('Grade'))['_pg_bake_node']=='Grade'
        yield from key('Z',ctrl=True)
        assert bake.baked_image(current('Grade'))['_pg_bake_frame']==27
        assert capture_starts==count
        current('Stack').pg_bake_image=bpy.data.images[original_bindings['Stack']]
        bpy.context.scene.frame_set(27,subframe=.25)
        report['shared_destination_queue']=True
        for label,value in saved.items():
            assert_shared(label,value['name'],expected[label],value['metadata'])
        record('concurrent_native_publications')

        create_replay_nodes(saved)
        project = report_path.parent / 'packed-bakes.blend'
        assert not snapshot_directories() and not tuple(report_path.parent.glob('*.exr'))
        report['temporary_exrs_removed'] = True
        saved_controls = {label: control_state(current(label)) for label in saved}
        assert bpy.ops.wm.save_as_mainfile(filepath=str(project), check_existing=False) == {'FINISHED'}
        assert bpy.ops.wm.open_mainfile(filepath=str(project), load_ui=False, use_scripts=False) == {'FINISHED'}
        drawn_nodes.clear()
        yield from wait(lambda:nodes.recovery_status()['state']=='completed',
                        'Reopened native graph adoption did not finish',timeout=10)
        assert graph_state() == before_graph, 'Recovery changed the saved graph'
        yield from assert_reopened_controls(saved_controls)
        for label, value in saved.items():
            assert_shared(label, value['name'], expected[label], value['metadata'])
            render_shared(label, expected[label])
        assert graph_state() == before_graph and settings() == before_settings
        report['packed_reopen'] = report['bake_node_replay'] = report['source_baked_color'] = True
        report['shared_image_consumers'] = True
        record('reopened_shared_bakes_without_exrs')

        setup_editor('Grade')
        yield from turns(12)
        grade_image = saved['Grade']['name']
        for case in ('same_dimensions', 'changed_dimensions'):
            untouched_image = bpy.data.images[saved['Stack']['name']]
            untouched = (bytes(untouched_image.packed_file.data), metadata(untouched_image),
                         pixels(untouched_image).copy())
            del untouched_image
            old_expected = expected['Grade']
            old_metadata = metadata(bpy.data.images[grade_image])
            old_packed = hashlib.sha256(bytes(bpy.data.images[grade_image].packed_file.data)).hexdigest()
            if case == 'same_dimensions':
                nodes.write_values(current('Grade'), {'exposure': .6})
                nodes.write_chromatic(current('Grade'), {'global_gain': .21})
            else:
                fill_source(24, 12, phase=1)
                bpy.context.scene.frame_set(29, subframe=.5)
            new_expected = expected_current('Grade')
            external = report_path.parent / 'old-shared-image.exr'
            if case == 'same_dimensions':
                external.write_bytes(bytes(bpy.data.images[grade_image].packed_file.data))
                bpy.data.images[grade_image].filepath_raw = str(external)
            before_graph, before_settings = graph_state(), settings()
            push_baseline('Before rebake ' + case)
            original_images = image_names()
            pointer = bpy.data.images[grade_image].as_pointer()
            old_edit = bpy.context.scene['_pg_test_intervening_edit']
            pause_capture()
            yield from key('F6')
            yield from wait(bake.busy, 'WM did not start ' + case)
            yield from key('F7')
            assert_shared('Grade', grade_image, old_expected, old_metadata)
            resume()
            yield from wait(lambda: not bake.busy(), 'WM rebake did not finish ' + case)
            yield from turns()
            assert not bake.last_error,bake.last_error
            assert image_names() == original_images, 'Rebake allocated a replacement Image'
            assert bpy.data.images[grade_image].as_pointer() == pointer, 'Rebake replaced the shared Image ID'
            assert bpy.data.images[grade_image].get('_pg_bake_operation')!=old_metadata.get('_pg_bake_operation')
            error = assert_shared('Grade', grade_image, new_expected)
            new_metadata = metadata(bpy.data.images[grade_image])
            new_packed = hashlib.sha256(bytes(bpy.data.images[grade_image].packed_file.data)).hexdigest()
            untouched_image = bpy.data.images[saved['Stack']['name']]
            assert bytes(untouched_image.packed_file.data) == untouched[0]
            assert metadata(untouched_image) == untouched[1]
            np.testing.assert_array_equal(pixels(untouched_image), untouched[2])
            del untouched_image
            report['other_destination_untouched'] = True
            assert new_metadata != old_metadata
            if case == 'same_dimensions':
                assert hashlib.sha256(external.read_bytes()).hexdigest() == old_packed
                external.unlink()
                report['external_image_untouched'] = True
            count = capture_starts
            render_shared('Grade', new_expected)
            yield from key('Z', ctrl=True)
            record('rebake_undo_observed', case=case,
                   old_packed=old_packed, new_packed=new_packed,
                   actual_packed=hashlib.sha256(bytes(bpy.data.images[grade_image].packed_file.data)).hexdigest(),
                   old_metadata_restored=metadata(bpy.data.images[grade_image]) == old_metadata)
            assert_shared('Grade', grade_image, old_expected, old_metadata)
            assert bpy.context.scene['_pg_test_intervening_edit'] == old_edit + 1
            render_shared('Grade', old_expected)
            yield from key('Z', ctrl=True, shift=True)
            assert_shared('Grade', grade_image, new_expected, new_metadata)
            render_shared('Grade', new_expected)
            assert capture_starts == count and not bake.busy()
            assert bpy.context.scene['_pg_test_intervening_edit'] == old_edit + 1
            assert graph_state() == before_graph and settings() == before_settings
            if case == 'same_dimensions':
                # Native undo can restore packed bytes while keeping the newer
                # compositor ImBuf. An interrupted cache invalidation must remain pending
                # until retry, without discarding another Image's dirty buffer.
                dirty_name = saved['Stack']['name']
                dirty_expected = pixels(bpy.data.images[dirty_name]).copy()
                dirty_expected.flat[0] += np.float32(.3125)
                bpy.data.images[dirty_name].pixels.foreach_set(dirty_expected.ravel())
                bpy.data.images[dirty_name].update()
                dirty_packed = hashlib.sha256(bytes(bpy.data.images[dirty_name].packed_file.data)).hexdigest()
                grade_uid = int(bpy.data.images[grade_image].session_uid)

                def assert_dirty_preserved():
                    image = bpy.data.images[dirty_name]
                    assert image.is_dirty
                    assert hashlib.sha256(bytes(image.packed_file.data)).hexdigest() == dirty_packed
                    assert metadata(image) == saved['Stack']['metadata']
                    np.testing.assert_array_equal(pixels(image), dirty_expected)

                failures = []
                original_checkpoint = bake.publication_checkpoint
                def fail_recovery_once(phase):
                    original_checkpoint(phase)
                    if phase == 'recovery_invalidated' and not failures:
                        failures.append(phase)
                        raise RuntimeError('Installed bake cache invalidation interrupted')

                assert_dirty_preserved()
                assert not snapshot_directories() and not tuple(report_path.parent.glob('*.exr'))
                bake.publication_checkpoint = fail_recovery_once
                try:
                    yield from key('Z', ctrl=True)
                finally:
                    bake.publication_checkpoint = original_checkpoint
                assert failures == ['recovery_invalidated'], failures
                assert nodes.recovery_pending(), 'Failed image recovery admitted normal work'
                assert grade_uid in bake.recovery_states, 'Failed image recovery lost its retry obligation'
                recovery_state = bake.recovery_states[grade_uid]['store'].state
                assert recovery_state.phase == 'failed' and recovery_state.pending
                assert not bake.recovery_states[grade_uid]['store'].query('settled')
                assert metadata(bpy.data.images[grade_image]) == old_metadata
                assert_dirty_preserved()
                report['recovery_failure_retained'] = True
                nodes.reset_cache_handler()
                yield from wait(lambda:not nodes.recovery_pending(),'Image recovery retry did not resume normal work')
                assert grade_uid not in bake.recovery_states, 'Settled image retained a recovery obligation'
                assert_shared('Grade', grade_image, old_expected, old_metadata)
                assert_dirty_preserved()
                render_shared('Grade', old_expected)
                yield from key('Z', ctrl=True, shift=True)
                assert_shared('Grade', grade_image, new_expected, new_metadata)
                assert_dirty_preserved()
                render_shared('Grade', new_expected)
                assert capture_starts == count and not bake.busy()
                assert bpy.context.scene['_pg_test_intervening_edit'] == old_edit + 1
                assert graph_state() == before_graph and settings() == before_settings
                report['recovery_retry_no_recapture'] = report['dirty_image_preserved'] = True
                # The dirty pixels belong only to this acceptance fixture. Drop
                # that buffer so subsequent persistence checks use its old pack.
                bpy.data.images[dirty_name].buffers_free()
                assert_shared('Stack', dirty_name, expected['Stack'], saved['Stack']['metadata'])
                record('native_recovery_failure_retry', failures=len(failures),
                       no_recapture=True, unrelated_dirty_preserved=True)
            expected['Grade'] = new_expected
            saved['Grade']['metadata'] = new_metadata
            report['rebakes'].append(dict(case=case, same_image=True,
                domain=list(new_expected.shape[1::-1]), maximum_error=error,
                undo_redo=True, consumers=3, no_recapture=True))
            record('shared_rebake_undo_redo', case=case)
        report['native_modal_undo_redo'] = report['intervening_edit_preserved'] = report['redo_no_recapture'] = True
        assert not snapshot_directories() and not tuple(report_path.parent.glob('*.exr'))
        saved_controls = {label: control_state(current(label)) for label in saved}
        assert bpy.ops.wm.save_as_mainfile(filepath=str(project), check_existing=False) == {'FINISHED'}
        assert bpy.ops.wm.open_mainfile(filepath=str(project), load_ui=False, use_scripts=False) == {'FINISHED'}
        drawn_nodes.clear()
        yield from wait(lambda:nodes.recovery_status()['state']=='completed',
                        'Reopened rebake graph adoption did not finish', timeout=10)
        yield from assert_reopened_controls(saved_controls)
        for label, value in saved.items():
            assert_shared(label, value['name'], expected[label], value['metadata'])
            render_shared(label, expected[label])
        report['rebake_packed_reopen'] = True
        setup_editor('Grade')
        yield from turns(12)

        # Change the assigned Grade and its own parameter while a native worker
        # is running. A different active node is only an editor selection and
        # must leave that request alive until an actual Bake dependency changes.
        original_images = image_names()
        original_grade = current('Grade').pg_grade.name
        grades.new(current('Grade'), duplicate=False)
        alternate_grade = current('Grade').pg_grade.name
        assert alternate_grade != original_grade
        current('Grade').pg_grade = bpy.data.node_groups[original_grade]
        yield from wait(guard.available, 'Initial Grade selection did not settle')
        original_exposure = current('Grade').pg_linear.exposure
        for change in ('grade_selection', 'grade_parameter'):
            setup_editor('Grade')
            yield from wait(lambda: bake.ready(current('Grade')), 'Changed Grade did not become Bake-ready')
            before_bytes = bytes(bpy.data.images[grade_image].packed_file.data)
            unchanged_metadata = metadata(bpy.data.images[grade_image])
            pause_capture()
            yield from key('F6')
            yield from wait(lambda: bake.busy(current('Grade')), 'Input-change bake did not start')
            token = next(iter(bake.states))
            handle = capture.bakes[token]['handle']
            directory = Path(capture.bakes[token]['directory'])
            setup_editor('Stack')
            yield from turns(12)
            assert bake.busy(current('Grade')), 'Changing the active node cancelled its unrelated bake'
            if change == 'grade_selection':
                current('Grade').pg_grade = bpy.data.node_groups[alternate_grade]
                assert current('Grade').pg_grade.name == alternate_grade
            else:
                nodes.write_values(current('Grade'), {'exposure': original_exposure + .25})
            yield from wait(lambda: token not in bake.states,
                            'A changed Grade did not cancel its running bake')
            outcome = application.component('integration.outcomes').get(current('Grade'), 'bake')
            assert outcome is not None and outcome.code == 'bake.inputs_changed', outcome
            assert handle.retired() or directory.exists(), 'Cancellation removed a live helper input'
            assert image_names() == original_images
            assert current('Grade').pg_bake_image.name == grade_image
            assert bytes(bpy.data.images[grade_image].packed_file.data) == before_bytes
            assert metadata(bpy.data.images[grade_image]) == unchanged_metadata
            resume()
            yield from wait(lambda: handle.retired() and not bake.busy(current('Grade'))
                                    and not snapshot_directories(),
                            'Input-change cancellation did not retire its native snapshot')
            if change == 'grade_selection':
                current('Grade').pg_grade = bpy.data.node_groups[original_grade]
            else:
                nodes.write_values(current('Grade'), {'exposure': original_exposure})
            yield from wait(guard.available, 'Restored Grade evaluation did not finish')
            report[change + '_cancels_bake'] = True
            record('cancelled_changed_bake_input', change=change)
            del handle
        report['editor_selection_keeps_bake'] = True
        setup_editor('Grade')
        yield from turns(12)

        # A native-reader gate holds a completed EXR before publication. Escape
        # must cancel this ready result without creating an Image or undo step.
        original_images = image_names()
        unchanged_metadata = metadata(bpy.data.images[grade_image])
        pause_capture()
        yield from key('F6')
        yield from wait(bake.busy, 'Cancellation bake did not start')
        token = next(iter(bake.states))
        guard.evaluation_started('bake-acceptance-publication', 1)
        resume()
        yield from wait(lambda: bake.status(token) is not None, 'Cancellation artifact did not finish')
        path = bake.status(token)['path']
        assert Path(path).exists() and image_names() == original_images
        yield from key('ESC')
        guard.evaluation_finished('bake-acceptance-publication', 1)
        guard.reconcile()
        yield from wait(lambda: not bake.busy(), 'Escape did not cancel the ready bake')
        yield from wait(lambda: not Path(path).exists(), 'Cancelled snapshot lease was not released')
        assert not Path(path).parent.exists()
        assert image_names() == original_images and not capture.bakes
        assert_shared('Grade', grade_image, expected['Grade'], unchanged_metadata)
        report['cancel_ready_without_image'] = True
        assert not snapshot_directories()
        report['snapshot_leases_released'] = True
        record('cancelled_ready_artifact')

        # Native playback entry cancels both a live helper and its queued
        # shared-destination successor. Logical cancellation cannot remove the
        # live helper's input files; playback must never publish either result.
        saved_frame = bpy.context.scene.frame_current, bpy.context.scene.frame_subframe
        stack_binding = current('Stack').pg_bake_image.name
        current('Stack').pg_bake_image = bpy.data.images[grade_image]
        before_bytes = bytes(bpy.data.images[grade_image].packed_file.data)
        pause_capture()
        setup_editor('Grade'); yield from key('F6')
        yield from wait(bake.busy, 'Playback cancellation bake did not start')
        running = next(iter(bake.states))
        setup_editor('Stack'); yield from key('F6')
        yield from wait(lambda: len(bake.states) == 2, 'Playback successor was not queued')
        handle = capture.bakes[running]['handle']
        directory = Path(capture.bakes[running]['directory'])
        count = capture_starts
        playback(True)
        yield from wait(lambda: bake.playback_active() and not bake.busy(),
                        'Native playback did not cancel all unfinished bakes')
        assert not bake.timers
        assert handle.retired() or directory.exists(), 'Playback removed a live helper input'
        assert bake.start(current('Grade')) is None
        assert capture_starts == count and image_names() == original_images
        # Hold the final native reader past timeline stop. Deliver an actual WM
        # Bake event in that interval, rather than waiting around the race.
        guard.evaluation_started('bake-acceptance-after-playback', 1)
        playback(False)
        assert not bake.playback_active()
        assert_bake_controls(False)
        reports = []
        op = SimpleNamespace(token='', report=lambda *args: reports.append(args))
        window, area, region = editor()
        with bpy.context.temp_override(window=window, area=area, region=region):
            assert bake.PG_OT_bake_compositor._begin(op, bpy.context) == {'CANCELLED'}
            assert bake.start(current('Stack'), context=bpy.context) is None
        yield from key('F6')
        assert not reports and not bake.busy() and capture_starts == count
        assert image_names() == original_images
        assert_bake_controls(False)
        guard.evaluation_finished('bake-acceptance-after-playback', 1)
        assert_bake_controls(False)  # Completion still awaits actor acknowledgement.
        guard.reconcile()
        resume()
        yield from wait(lambda: handle.retired() and not snapshot_directories(),
                        'Playback cancellation did not retire helper snapshots')
        yield from wait(guard.available, 'Native playback readers did not finish')
        assert_bake_controls(True)
        report['playback_stop_waits_for_native'] = report['native_wait_tooltip'] = True
        report['native_wait_race_click'] = True
        bpy.context.scene.frame_set(saved_frame[0], subframe=saved_frame[1])
        yield from wait(guard.available, 'Restored frame readers did not finish')
        current('Stack').pg_bake_image = bpy.data.images[stack_binding]
        assert bytes(bpy.data.images[grade_image].packed_file.data) == before_bytes
        assert_shared('Grade', grade_image, expected['Grade'], unchanged_metadata)
        assert_shared('Stack', stack_binding, expected['Stack'], saved['Stack']['metadata'])
        del handle
        report['playback_cancel_running_queued'] = report['playback_no_new_request'] = True
        record('playback_cancel_running_queued')

        # A finished artifact waiting for native readers is still unfinished
        # Bake work and must also be discarded when playback starts.
        setup_editor('Grade')
        pause_capture(); yield from key('F6')
        yield from wait(bake.busy, 'Playback ready-result bake did not start')
        token = next(iter(bake.states))
        guard.evaluation_started('bake-acceptance-playback', 1)
        resume()
        yield from wait(lambda: bake.status(token) is not None, 'Playback artifact did not become ready')
        path = Path(bake.status(token)['path'])
        playback(True)
        yield from wait(lambda: not bake.busy(), 'Playback did not cancel the ready artifact')
        playback(False)
        guard.evaluation_finished('bake-acceptance-playback', 1)
        guard.reconcile()
        yield from wait(lambda: not path.exists(), 'Playback retained its ready artifact')
        yield from wait(guard.available, 'Playback readers did not finish after ready cancellation')
        bpy.context.scene.frame_set(saved_frame[0], subframe=saved_frame[1])
        yield from wait(guard.available, 'Restored frame readers did not finish after ready cancellation')
        assert image_names() == original_images
        assert bytes(bpy.data.images[grade_image].packed_file.data) == before_bytes
        assert_shared('Grade', grade_image, expected['Grade'], unchanged_metadata)
        report['playback_cancel_ready'] = True
        record('playback_cancel_ready')

        # Loading replaces native datablocks while a helper still owns its
        # input snapshot. Logical cancellation cannot retire that physical lease.
        pause_capture()
        yield from key('F6')
        yield from wait(bake.busy, 'Load-boundary bake did not start')
        token = next(iter(bake.states))
        handle = capture.bakes[token]['handle']
        directory = Path(capture.bakes[token]['directory'])
        assert directory.exists() and not handle.retired()
        assert bpy.ops.wm.open_mainfile(filepath=str(project), load_ui=False, use_scripts=False) == {'FINISHED'}
        assert not bake.busy() and not bake.timers
        assert handle.retired() or directory.exists(), 'Load removed a live helper input'
        resume()
        yield from wait(lambda: handle.retired() and not directory.exists(),
                        'Load cancellation did not retire its helper lease')
        assert image_names() == {value['name'] for value in saved.values()}
        assert not snapshot_directories()
        report['pending_load_cancelled'] = True
        del handle
        record('pending_load_cancelled')

        setup_editor()
        yield from turns(12)
        pause_capture()
        yield from key('F6')
        yield from wait(bake.busy, 'Disable-boundary bake did not start')
        token = next(iter(bake.states))
        disable_pending.update(handle=capture.bakes[token]['handle'],
                               directory=Path(capture.bakes[token]['directory']))
        assert disable_pending['directory'].exists() and not disable_pending['handle'].retired()
        helper = runtime.helpers['bake_0']
        report['helper_is_native'] = Path(helper.process.args[0]).resolve() == Path(bpy.app.binary_path).resolve()
        assert report['helper_is_native']
        del helper
        record('active_disable_started')

    sequence = scenario()
    def advance():
        try:
            assert time.monotonic() - started < 840, 'Installed bake exceeded 14 minutes'
            if getattr(bpy.context.window_manager, 'is_event_handling_break', False):
                return .016
            next(sequence)
            return .016
        except StopIteration:
            try:
                runtime.submit = original_submit
                helpers = tuple(runtime.helpers.values())
                bpy.utils.unregister_class(PGTEST_OT_intervening_edit)
                addon.unregister()
                assert disable_pending['handle'].retired()
                assert not disable_pending['directory'].exists(), 'Disable retained a retired helper snapshot'
                assert not bake.busy() and not bake.timers, 'Disable retained bake state or WM timers'
                report['active_disable_retired'] = True
                resume()
                report['helper_exited'] = all(helper.process.poll() is not None for helper in helpers)
                report['cleanup_clean'] = runtime.closed and runtime._shutdown_report.clean
                assert report['helper_exited'] and report['cleanup_clean']
                report['passed'] = True
                record('complete')
                bpy.ops.wm.quit_blender('EXEC_DEFAULT')
                return None
            except BaseException:
                report['error'] = traceback.format_exc()
        except BaseException:
            report['error'] = traceback.format_exc()
        record('failed')
        print(report['error'], flush=True)
        resume()
        os._exit(1)

    record('started')
    bpy.app.timers.register(advance, first_interval=.5, persistent=True)


if __name__ == '__main__':
    main(*sys.argv[sys.argv.index('--') + 1:])
