"""Installed Shader baking, native editor controls and saved reader acceptance."""
import importlib
import json
import os
from pathlib import Path
import sys
import time
import traceback
from types import SimpleNamespace

import addon_utils
import bpy
import numpy as np


def main(repository, report_path):
    repository, report_path = Path(repository).resolve(), Path(report_path)
    package = repository / 'perceptual_grade'
    assert not bpy.app.background and tuple(bpy.app.version) == (5, 2, 2), bpy.app.version
    bpy.context.preferences.view.show_splash = False
    bpy.context.preferences.extensions.repos.new(name='Shader bake acceptance',
        module='pg_shader_bake', custom_directory=str(repository))
    name = 'bl_ext.pg_shader_bake.perceptual_grade'
    errors = []
    addon = addon_utils.enable(name, default_set=False, handle_error=errors.append)
    assert addon is not None and not errors, repr(errors)
    assert Path(addon.__file__).resolve() == package / '__init__.py'
    lifecycle = importlib.import_module(name + '.perceptual_grade_blender.integration.lifecycle')
    assert Path(lifecycle.__file__).resolve().is_relative_to(package)
    application = lifecycle.registered_session()
    nodes = application.component('graph.nodes')
    grades = application.component('graph.grades')
    bake = application.component('graph.bake')
    guard = application.component('graph.output_guard')
    stacks = application.component('graph.stacks')
    routes = application.component('scopes.bake_routes')
    sources = application.component('scopes.sources')
    capture = application.component('scopes.capture')
    runtime = application.app.execution.get_runtime()
    report = dict(passed=False, blender=list(bpy.app.version), route={}, image={}, reader={},
                  selector_path='native template_ID and pointer assignment')
    state = {'stage': 'setup', 'started': time.monotonic()}

    class RecordingLayout:
        def __init__(self, parent=None):
            self.enabled = True if parent is None else parent.enabled
            self.labels = [] if parent is None else parent.labels
            self.controls = [] if parent is None else parent.controls
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

    original_draw_action = bake.draw_action

    def observed_draw(layout, node, context=None):
        result = original_draw_action(layout, node, context)
        if isinstance(layout, bpy.types.UILayout):
            state.setdefault('drawn_nodes', set()).add((node.id_data.name, node.name))
        return result

    # Instrument the function called by registered Shader Grade/Stack draw
    # methods. Count only successful calls so the earlier UI KeyError fails.
    object.__getattribute__(application._component('graph.bake'), '_Component__exports')[
        'draw_action'] = observed_draw

    def editor():
        window = bpy.context.window_manager.windows[0]
        area = next((item for item in window.screen.areas if item.type == 'NODE_EDITOR'), None)
        if area is None:
            area = max(window.screen.areas, key=lambda item: item.width * item.height)
            with bpy.context.temp_override(window=window, area=area):
                area.type = 'NODE_EDITOR'
                area.ui_type = 'ShaderNodeTree'
        region = next(item for item in area.regions if item.type == 'WINDOW')
        return window, area, region

    def set_shader_editor(owner, shader_type):
        window, area, _region = editor()
        with bpy.context.temp_override(window=window, area=area):
            space = area.spaces.active
            space.shader_type = shader_type
            space.pin = False
            if shader_type == 'WORLD':
                bpy.context.scene.world = owner
            else:
                obj = bpy.data.objects['Cube']
                bpy.context.view_layer.objects.active = obj
                obj.select_set(True)
                obj.data.materials.clear()
                obj.data.materials.append(owner)
            area.tag_redraw()

    def set_active_node(tree, node):
        tree.nodes.active = node
        for item in tree.nodes:
            item.select = item == node

    def draw_action(node, context):
        layout = RecordingLayout()
        bake.draw_action(layout, node, context)
        assert any(name == 'pg_bake_image' for name, _enabled in layout.controls), layout.controls
        assert any(name == 'perceptual_grade.bake_compositor' for name, _enabled in layout.controls), \
            layout.controls
        assert any(text for text, _icon in layout.labels), layout.labels
        return layout

    def context(material):
        return SimpleNamespace(scene=bpy.context.scene, object=None,
            view_layer=bpy.context.scene.view_layers[0],
            space_data=SimpleNamespace(type='NODE_EDITOR', id=material,
                                       node_tree=material.node_tree, path=()))

    def graph_state(tree):
        return (tuple((node.name, node.bl_idname) for node in tree.nodes),
                tuple((link.from_node.name, link.from_socket.identifier,
                       link.to_node.name, link.to_socket.identifier) for link in tree.links))

    def control_state(node):
        return dict(kind=node.bl_idname,
            grade=None if node.pg_grade is None else node.pg_grade.name,
            entries=[None if item.grade is None else item.grade.name for item in node.pg_stack_entries],
            image=None if node.pg_bake_image is None else node.pg_bake_image.name,
            sockets=[(direction, socket.identifier, bool(socket.hide))
                for direction, sockets in (('INPUT', node.inputs), ('OUTPUT', node.outputs))
                for socket in sockets])

    def assert_reopened_controls(tree):
        window, area, region = editor()
        i18n = application.component('localization.i18n')
        for name, expected in state['saved_controls'].items():
            node = tree.nodes[name]
            assert control_state(node) == expected, (name, control_state(node), expected)
            assert node.show_options and node.bl_idname in ('PGShaderGrade', 'PGShaderStack')
            set_active_node(tree, node)
            with bpy.context.temp_override(window=window, area=area, region=region):
                layout = RecordingLayout()
                if node.bl_idname == 'PGShaderGrade':
                    grades.draw_selector(layout, node)
                    bake.draw_action(layout, node, bpy.context)
                else:
                    stacks.draw(layout, node, bpy.context)
                assert any(name == 'pg_bake_image' for name, _enabled in layout.controls), layout.controls
                assert any(name == 'perceptual_grade.bake_compositor'
                           for name, _enabled in layout.controls), layout.controls
                selector = 'pg_grade' if node.bl_idname == 'PGShaderGrade' else 'grade'
                assert any(name == selector for name, _enabled in layout.controls), layout.controls
                assert node.bl_rna.properties['pg_grade'].description == i18n.native('grade.selector.tooltip')
                assert node.bl_rna.properties['pg_bake_image'].description == i18n.native('bake.destination.tooltip')
                observation = bake.eligibility(node, bpy.context)
                expected_tip = i18n.tip('bake.blocked.' + observation['code']
                    if observation['code'] else 'bake.tooltip')
                assert expected_tip and bake.PG_OT_bake_compositor.description(bpy.context, None) == expected_tip

    def pixels(image):
        result = np.empty(len(image.pixels), dtype=np.float32)
        image.pixels.foreach_get(result)
        return result.reshape(image.size[1], image.size[0], image.channels)

    def write():
        report_path.write_text(json.dumps(report, indent=2), encoding='utf8')

    def fail(error):
        report['error'] = repr(error)
        report['traceback'] = __import__('traceback').format_exc()
        write()
        print(report['traceback'], flush=True)
        os._exit(1)

    def advance():
        try:
            assert time.monotonic() - state['started'] < 300, 'Installed Shader Bake exceeded five minutes'
            if state['stage'] == 'setup':
                scene = bpy.context.scene
                scene.render.engine = 'BLENDER_EEVEE'
                scene.render.resolution_x, scene.render.resolution_y = 4, 2
                scene.render.resolution_percentage = 100
                material = bpy.data.materials.new('Installed Shader Bake Material')
                material.use_nodes = True
                tree = material.node_tree
                source = tree.nodes.new('ShaderNodeTexImage')
                source.name = 'Still HDR Source'
                image = bpy.data.images.new('Installed Still HDR', width=4, height=2,
                                             alpha=True, float_buffer=True)
                image.colorspace_settings.name = 'Non-Color'
                image.alpha_mode = 'CHANNEL_PACKED'
                y, x = np.mgrid[:2, :4]
                rgba = np.stack((-.25 + x * .1, 1.5 + y * .2, .25 + x * .05,
                                 np.where((x + y) % 2, .25, .75)), axis=-1).astype(np.float32)
                image.pixels.foreach_set(rgba.ravel())
                image.update()
                image.pack()
                source.image = image
                grade = nodes.create_grade(tree)
                grade.name = 'Installed Shader Bake Grade'
                grades.new(grade)
                grade.location = (-150, 200)
                tree.links.new(source.outputs['Color'], grade.inputs['Color'])
                tree.links.new(source.outputs['Alpha'], grade.inputs['Alpha'])
                stack = stacks.create(tree)
                stack.name = 'Installed Shader Bake Stack'
                stack.location = (150, 200)
                with grades.guarded(stack):
                    entry = stack.pg_stack_entries.add()
                    entry.grade = grade.pg_grade
                    entry.key = 'installed-shader-grade'
                stacks.bind_dependencies(stack)
                stacks.refresh(stack, True)
                world = bpy.data.worlds.new('Installed Shader Bake World')
                world.use_nodes = True
                state.update(scene=scene, material=material, tree=tree, source=source,
                             source_image=image, grade=grade, stack=stack, world=world,
                             context=context(material),
                             source_graph=graph_state(tree))
                set_shader_editor(material, 'OBJECT')
                state['stage'] = 'material_add'
                write()
                return .02
            if state['stage'] == 'material_add':
                window, area, region = editor()
                with bpy.context.temp_override(window=window, area=area, region=region):
                    assert bpy.context.space_data.edit_tree == state['tree']
                    assert bpy.ops.perceptual_grade.add_bake.poll()
                    assert bpy.ops.perceptual_grade.add_bake() == {'FINISHED'}
                reader = state['tree'].nodes.active
                assert reader.bl_idname == 'PGShaderBake'
                reader.name = 'Installed Shader Reader'
                state['reader'] = reader
                report['material_add_operator'] = True
                set_shader_editor(state['world'], 'WORLD')
                state['stage'] = 'world_add'
                return .02
            if state['stage'] == 'world_add':
                window, area, region = editor()
                with bpy.context.temp_override(window=window, area=area, region=region):
                    assert bpy.context.space_data.edit_tree == state['world'].node_tree
                    assert bpy.ops.perceptual_grade.add_bake.poll()
                    assert bpy.ops.perceptual_grade.add_bake() == {'FINISHED'}
                assert state['world'].node_tree.nodes.active.bl_idname == 'PGShaderBake'
                report['world_add_operator'] = True
                set_shader_editor(state['material'], 'OBJECT')
                set_active_node(state['tree'], state['grade'])
                state['source_graph'] = graph_state(state['tree'])
                state['stage'] = 'wait_ready'
                return .02
            if state['stage'] == 'wait_ready':
                nodes.recovery_tick()
                nodes.poll_working_space()
                guard.reconcile()
                if nodes.recovery_status()['state'] not in {'completed', 'idle'}:
                    return .02
                if not nodes.resources_ready(state['grade']) or not guard.available():
                    return .02
                window, area, region = editor()
                area.tag_redraw()
                drawn = state.get('drawn_nodes', set())
                if not all((state['tree'].name, state[kind].name) in drawn for kind in ('grade', 'stack')):
                    with bpy.context.temp_override(window=window, area=area, region=region):
                        bpy.ops.node.view_all()
                    return .02
                grade_layout = draw_action(state['grade'], state['context'])
                stack_layout = draw_action(state['stack'], state['context'])
                if not bake.ready(state['grade'], state['context']):
                    return .02
                for layout in (grade_layout, stack_layout):
                    assert ('pg_bake_image', True) in layout.controls, layout.controls
                    assert not any(name in ('pg_bake_width', 'pg_bake_height')
                                   for name, _enabled in layout.controls), layout.controls
                report['native_shader_draws'] = True
                report['drawn_nodes'] = sorted(drawn)
                report['route_ui'] = dict(grade_labels=[text for text, _icon in grade_layout.labels],
                                          stack_labels=[text for text, _icon in stack_layout.labels])
                route = routes.describe(state['grade'], state['context'])
                assert route['shader_bake']['domain'] == 'IMAGE', route
                assert (route['shader_bake']['width'], route['shader_bake']['height']) == (4, 2), route
                assert route['engine'] == 'BLENDER_EEVEE', route
                state['route_before'] = route
                if not state.get('native_wait_checked'):
                    with bpy.context.temp_override(window=window, area=area, region=region):
                        assert bpy.ops.screen.animation_play() == {'FINISHED'}
                        guard.evaluation_started('shader-after-playback', 1)
                        bpy.ops.screen.animation_cancel(restore_frame=False)
                    assert not bake.playback_active()
                    waiting = application.component('localization.i18n').tip('bake.blocked.waiting')
                    before = set(bpy.data.images)
                    reports = []
                    op = SimpleNamespace(token='', report=lambda *args: reports.append(args))
                    for kind in ('grade', 'stack'):
                        node = state[kind]
                        set_active_node(state['tree'], node)
                        with bpy.context.temp_override(window=window, area=area, region=region):
                            layout = draw_action(node, bpy.context)
                            assert ('perceptual_grade.bake_compositor', False) in layout.controls
                            assert ('pg_bake_image', False) in layout.controls
                            assert (waiting, 'TIME') not in layout.labels
                            assert not bpy.ops.perceptual_grade.bake_compositor.poll()
                            assert bake.PG_OT_bake_compositor.description(bpy.context, None) == waiting
                            assert bake.PG_OT_bake_compositor._begin(op, bpy.context) == {'CANCELLED'}
                            assert bake.start(node, context=bpy.context) is None
                    assert not reports and not bake.states and not capture.bakes
                    assert set(bpy.data.images) == before
                    guard.evaluation_finished('shader-after-playback', 1)
                    assert not bake.ready(state['grade'], state['context'])
                    guard.reconcile()
                    set_active_node(state['tree'], state['grade'])
                    state['native_wait_checked'] = True
                    report['playback_stop_waits_for_native'] = report['native_wait_race_click'] = True
                    report['native_wait_tooltip'] = True
                    return .02
                state['token'] = bake.start(state['grade'], context=state['context'])
                assert state['token'] is not None
                state['stage'] = 'baking'
                return .02
            if state['stage'] == 'baking':
                capture.poll()
                bake.poll()
                artifact = bake.status(state['token'])
                if artifact is None:
                    return .02
                assert artifact['bake_domain'] == 'IMAGE', artifact
                assert (artifact['width'], artifact['height']) == (4, 2), artifact
                image = bake.finish(state['token'])
                assert image is not None
                values = pixels(image)
                assert image.is_float and image.channels == 4, (image.is_float, image.channels)
                assert tuple(image.size) == (4, 2), image.size[:]
                assert image.packed_file is not None and image.packed_file.size > 0
                assert not image.is_dirty
                assert image.get('_pg_bake_kind') == 'SHADER_IMAGE'
                assert tuple(image.get('_pg_bake_domain')) == (4, 2)
                assert np.isfinite(values).all() and np.max(np.abs(values)) > .01
                assert graph_state(state['tree']) == state['source_graph']
                state['image'] = image
                state['values'] = values.copy()
                report['route'] = dict(domain=state['route_before']['shader_bake']['domain'],
                                       width=state['route_before']['shader_bake']['width'],
                                       height=state['route_before']['shader_bake']['height'],
                                       source=state['route_before']['shader_bake']['source'])
                report['image'] = dict(name=image.name, kind=image['_pg_bake_kind'],
                                       size=list(image.size), channels=image.channels,
                                       packed_bytes=image.packed_file.size,
                                       dirty=image.is_dirty,
                                       finite=bool(np.isfinite(values).all()),
                                       alpha_min=float(values[..., 3].min()),
                                       alpha_max=float(values[..., 3].max()))
                state['stage'] = 'reader'
                return .02
            if state['stage'] == 'reader':
                # The standalone reader is deliberately wired manually. The
                # source resolver must identify its persisted Image and avoid
                # reapplying the live terminal Grade model.
                reader = state['reader']
                bake.set_baked_image(reader, state['image'])
                assert reader.pg_bake_image == state['image'] and bake.baked_image(reader) == state['image']
                assert tuple(socket.name for socket in reader.inputs) == ('Vector',)
                assert tuple(socket.name for socket in reader.outputs) == ('Color', 'Alpha')
                consumer = nodes.create_grade(state['tree'])
                state['tree'].links.new(reader.outputs['Color'], consumer.inputs['Color'])
                state['tree'].links.new(reader.outputs['Alpha'], consumer.inputs['Alpha'])
                route = sources.resolve(consumer, 'Color', state['context'])
                alpha_route = sources.resolve(consumer, 'Alpha', state['context'])
                assert route.kind == 'image', route
                assert alpha_route.kind == 'image', alpha_route
                assert route.source.name == state['image'].name, route.label
                assert alpha_route.source.name == state['image'].name, alpha_route.label
                assert route.source.channel == 'COLOR', route.source.channel
                assert alpha_route.source.channel == 'ALPHA', alpha_route.source.channel
                assert not route.steps and not alpha_route.steps
                report['reader'] = dict(kind=route.kind, source=route.source.name,
                                        label=route.label, steps=len(route.steps),
                                        alpha_kind=alpha_route.kind,
                                        alpha_source=alpha_route.source.name,
                                        alpha_channel=alpha_route.source.channel,
                                        alpha_steps=len(alpha_route.steps))
                current_graph = graph_state(state['tree'])
                report['reader_graph_extended'] = current_graph != state['source_graph']
                # The original Grade links are still present; only the explicit
                # reader/consumer nodes and links were added after publication.
                report['original_links_preserved'] = set(state['source_graph'][1]).issubset(
                    set(current_graph[1]))
                vector_description = next(item for item in reader.node_tree.interface.items_tree
                    if item.item_type == 'SOCKET' and item.in_out == 'INPUT' and item.name == 'Vector').description
                assert vector_description and 'baked' in vector_description.casefold(), vector_description
                assert 'Vector' in state['grade'].inputs
                grade_vector_description = next(item for item in state['grade'].node_tree.interface.items_tree
                    if item.item_type == 'SOCKET' and item.in_out == 'INPUT'
                    and item.name == 'Vector').description
                assert grade_vector_description and 'baked' in grade_vector_description.casefold(), \
                    grade_vector_description

                texcoord = state['tree'].nodes.new('ShaderNodeTexCoord')
                texcoord['_pg_test_vector_source'] = 1
                state['tree'].links.new(texcoord.outputs['UV'], reader.inputs['Vector'])
                state['tree'].links.new(texcoord.outputs['UV'], state['grade'].inputs['Vector'])
                bake.sync_coordinates()
                group_input = next(item for item in reader.node_tree.nodes
                                   if item.bl_idname == 'NodeGroupInput')
                reader_source = next(item for item in reader.node_tree.nodes
                                     if item.bl_idname == 'ShaderNodeTexImage')
                grade_group_input = next(item for item in state['grade'].node_tree.nodes
                                         if item.bl_idname == 'NodeGroupInput')
                grade_source = next(item for item in state['grade'].node_tree.nodes
                                    if item.get('_pg_baked_image'))
                assert any(link.from_node == group_input and link.from_socket.name == 'Vector'
                           for link in reader_source.inputs['Vector'].links)
                assert any(link.from_node == grade_group_input and link.from_socket.name == 'Vector'
                           for link in grade_source.inputs['Vector'].links)
                report['reader_vector'] = True
                report['grade_vector'] = True

                # This metadata and packed-payload shape matches a valid
                # Compositor bake; the selector must offer it on Shader nodes.
                compositor_image = bpy.data.images.new('Installed Compositor Bake', width=2, height=2,
                    alpha=True, float_buffer=True)
                compositor_image.pixels.foreach_set(np.tile(
                    np.array((.2, .4, .6, .8), dtype=np.float32), 4))
                compositor_image.update()
                compositor_image['_pg_bake_schema'] = 2; compositor_image['_pg_bake_storage'] = 'FLOAT_RGBA'
                compositor_image['_pg_bake_kind'] = 'COMPOSITOR'
                compositor_image.pack()
                assert bake.is_baked_image(compositor_image)
                arbitrary_image = bpy.data.images.new('Unmanaged Image', width=1, height=1,
                                                       alpha=True, float_buffer=True)
                arbitrary_image.pack()
                selector_grade = nodes.create_grade(state['tree'])
                selector_stack = stacks.create(state['tree'])
                choices = [image.name for image in bpy.data.images if bake.image_allowed(selector_grade, image)]
                assert compositor_image.name in choices, choices
                assert arbitrary_image.name not in choices, choices
                selector_grade.pg_bake_image = compositor_image
                selector_stack.pg_bake_image = compositor_image
                assert bake.baked_image(selector_grade) == compositor_image
                assert bake.baked_image(selector_stack) == compositor_image
                report['compositor_image_selector'] = True
                report['selector_image'] = dict(name=compositor_image.name,
                    kind='COMPOSITOR', search_match=compositor_image.name in choices,
                    grade_bound=bake.baked_image(selector_grade).name,
                    stack_bound=bake.baked_image(selector_stack).name)

                state['grade'].pg_bake_image = state['image']
                state['stack'].pg_bake_image = state['image']
                assert state['grade'].pg_bake_image == state['image']
                assert state['stack'].pg_bake_image == state['image']
                state['saved_controls'] = {state[kind].name: control_state(state[kind])
                                           for kind in ('grade', 'stack')}
                state['project_path'] = str(report_path.parent / 'shader-bake-vector.blend')
                assert bpy.ops.wm.save_as_mainfile(filepath=state['project_path']) == {'FINISHED'}
                state['stage'] = 'vector_reopen'
                return .02
            if state['stage'] == 'vector_reopen':
                assert bpy.ops.wm.open_mainfile(filepath=state['project_path'], load_ui=False,
                                                use_scripts=False) == {'FINISHED'}
                state['drawn_nodes'] = set()
                state['stage'] = 'vector_reopen_ready'
                return .02
            if state['stage'] == 'vector_reopen_ready':
                nodes.recovery_tick()
                nodes.poll_working_space()
                guard.reconcile()
                if nodes.recovery_status()['state'] not in {'completed', 'idle'} or not guard.available():
                    return .02
                material = bpy.data.materials['Installed Shader Bake Material']
                tree = material.node_tree
                set_shader_editor(material, 'OBJECT')
                window, area, region = editor()
                with bpy.context.temp_override(window=window, area=area, region=region):
                    bpy.ops.node.view_all()
                area.tag_redraw()
                if not all((tree.name, name) in state['drawn_nodes'] for name in state['saved_controls']):
                    return .02
                assert_reopened_controls(tree)
                report['reopened_controls_drawn'] = report['reopened_selections'] = True
                report['reopened_tooltips'] = True
                reader = tree.nodes['Installed Shader Reader']
                grade = tree.nodes['Installed Shader Bake Grade']
                bake.sync_coordinates()
                coords = next(item for item in tree.nodes if item.get('_pg_test_vector_source'))
                group_input = next(item for item in reader.node_tree.nodes
                                   if item.bl_idname == 'NodeGroupInput')
                reader_source = next(item for item in reader.node_tree.nodes
                                     if item.bl_idname == 'ShaderNodeTexImage')
                assert any(link.from_node == group_input and link.from_socket.name == 'Vector'
                           for link in reader_source.inputs['Vector'].links)
                assert reader.pg_bake_image is not None and reader.pg_bake_image.packed_file is not None
                report['vector_reopen'] = True
                reader_link = next(link for link in tuple(reader.inputs['Vector'].links)
                                   if link.from_node == coords)
                grade_link = next(link for link in tuple(grade.inputs['Vector'].links)
                                  if link.from_node == coords)
                tree.links.remove(reader_link)
                tree.links.remove(grade_link)
                bake.sync_coordinates()
                fallback = next(item for item in reader.node_tree.nodes
                    if item.bl_idname == 'ShaderNodeTexCoord' and item.get('_pg_bake_uv_fallback'))
                assert any(link.from_node == fallback and link.from_socket.name == 'UV'
                           for link in reader_source.inputs['Vector'].links)
                grade_fallback = next(item for item in grade.node_tree.nodes
                    if item.bl_idname == 'ShaderNodeTexCoord' and item.get('_pg_bake_uv_fallback'))
                grade_source = next(item for item in grade.node_tree.nodes
                                    if item.get('_pg_baked_image'))
                assert any(link.from_node == grade_fallback and link.from_socket.name == 'UV'
                           for link in grade_source.inputs['Vector'].links)
                report['vector_edit_after_reopen'] = True
                report['packed_reopen'] = reader.pg_bake_image.packed_file.size > 0
                report['passed'] = True
                write()
                addon.unregister()
                assert runtime.closed
                bpy.ops.wm.quit_blender('EXEC_DEFAULT')
                return None
            return .02
        except BaseException as error:
            fail(error)

    bpy.app.timers.register(advance, first_interval=.02, persistent=True)


if __name__ == '__main__':
    main(*sys.argv[sys.argv.index('--') + 1:])
