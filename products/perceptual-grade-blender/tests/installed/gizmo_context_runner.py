"""Fresh GUI acceptance: Blender dispatches every hover and click itself."""
import importlib
import json
import os
from pathlib import Path
import sys
import time
import traceback

import addon_utils
import bpy


def main(repository, report_path):
    repository, report_path = Path(repository).resolve(), Path(report_path)
    assert not bpy.app.background and tuple(bpy.app.version) == (5, 2, 2)
    bpy.context.preferences.view.show_splash = False
    bpy.context.preferences.system.gpu_backend = 'METAL' if sys.platform == 'darwin' else 'OPENGL'
    bpy.context.preferences.extensions.repos.new(name='Gizmo context acceptance',
        module='pg_gizmo', custom_directory=str(repository))
    name = 'bl_ext.pg_gizmo.perceptual_grade'
    errors = []
    addon = addon_utils.enable(name, default_set=False, handle_error=errors.append)
    assert addon is not None and not errors, repr(errors)
    assert Path(addon.__file__).resolve() == repository / 'perceptual_grade/__init__.py'
    lifecycle = importlib.import_module(name + '.perceptual_grade_blender.integration.lifecycle')
    components = importlib.import_module(name + '.perceptual_grade_blender.integration.components')
    application = lifecycle.registered_session()
    nodes, diagram, sampling, capture = (application.component(part) for part in
        ('graph.nodes', 'ui.diagram', 'scopes.sampling', 'scopes.capture'))
    runtime = application.app.execution.get_runtime()
    report = dict(passed=False, blender=list(bpy.app.version), platform=sys.platform,
                  cases=[], automatic_cases=[], native_calls=dict(describe=0, acquire=0))
    started = time.monotonic()
    counts = dict(status=0, hover=0, keyframe=0)
    replaced = {}

    def observe_component(component_name, replacements):
        original = application.components[component_name]
        replaced[component_name] = original
        readers = {key: (lambda key=key: getattr(original, key))
                   for key, _ in components.component_items(original) if key not in replacements}
        application.components[component_name] = components.Component(replacements, readers=readers)

    original_status = sampling.scope_input_status
    def status(node, context=None):
        if isinstance(context, bpy.types.Context):
            counts['status'] += 1
        return original_status(node, context)
    observe_component('scopes.sampling', {'scope_input_status': status})
    def counted(label, action):
        def invoke(*args, **kwargs):
            report['native_calls'][label] += 1
            return action(*args, **kwargs)
        return invoke
    observe_component('scopes.capture', {label: counted(label, getattr(capture, label))
                                        for label in ('describe', 'acquire')})
    original_hover = diagram.hover_cursor
    def hover(*args, **kwargs):
        counts['hover'] += 1
        return original_hover(*args, **kwargs)
    diagram.hover_cursor = hover
    original_keyframe = diagram.keyframe_drag
    def keyframe(*args, **kwargs):
        counts['keyframe'] += 1
        return original_keyframe(*args, **kwargs)
    diagram.keyframe_drag = keyframe
    current_tree = None

    def record():
        report_path.write_text(json.dumps(report, indent=2), encoding='utf8')

    def editor():
        window = bpy.context.window_manager.windows[0]
        area = next(item for item in window.screen.areas if item.type == 'NODE_EDITOR')
        region = next(item for item in area.regions if item.type == 'WINDOW')
        return window, area, region

    def current():
        return current_tree.nodes['Grade']

    def setup():
        nonlocal current_tree
        material = bpy.data.materials.new('Gizmo context material')
        material.use_nodes = True
        current_tree = material.node_tree
        scene = bpy.context.scene
        scene.render.engine = 'BLENDER_EEVEE'
        scene.render.resolution_x = scene.render.resolution_y = 32
        scene.render.resolution_percentage = 100
        scene.render.compositor_device = 'CPU'
        obj = bpy.context.view_layer.objects.active
        obj.data.materials.clear()
        obj.data.materials.append(material)
        source = material.node_tree.nodes.new('ShaderNodeHueSaturation')
        source.name = 'Automatic source'
        grade = nodes.create_grade(material.node_tree)
        grade.name = 'Grade'
        material.node_tree.links.new(source.outputs['Color'], grade.inputs['Color'])
        for node in material.node_tree.nodes:
            node.select = node == grade
        material.node_tree.nodes.active = grade
        window = bpy.context.window_manager.windows[0]
        area = max(window.screen.areas, key=lambda item: item.width * item.height)
        with bpy.context.temp_override(window=window, area=area):
            area.type = 'NODE_EDITOR'
            area.ui_type = 'ShaderNodeTree'
            area.spaces.active.shader_type = 'OBJECT'
            area.spaces.active.show_region_ui = False
        wm = bpy.context.window_manager
        wm.pg_diagram_enabled = True
        wm.pg_stage = 'LINEAR'
        wm.pg_diagram_x = wm.pg_diagram_y = 24.
        area.tag_redraw()

    def compositor():
        nonlocal current_tree
        tree = bpy.data.node_groups.new('Gizmo compositor', 'CompositorNodeTree')
        bpy.context.scene.compositing_node_group = tree
        source = tree.nodes.new('CompositorNodeRGB')
        source.name = 'Automatic source'
        source.outputs[0].default_value = (.2, .4, .6, 1.)
        blur = tree.nodes.new('CompositorNodeBlur')
        tree.links.new(source.outputs[0], blur.inputs['Image'])
        grade = nodes.create_grade(tree)
        grade.name = 'Grade'
        tree.links.new(blur.outputs['Image'], grade.inputs['Color'])
        for node in tree.nodes:
            node.select = node == grade
        tree.nodes.active = grade
        current_tree = tree
        window, area, region = editor()
        with bpy.context.temp_override(window=window, area=area, region=region):
            area.ui_type = 'CompositorNodeTree'
        area.tag_redraw()

    def point(control):
        window, area, region = editor()
        with bpy.context.temp_override(window=window, area=area, region=region):
            box = diagram.layout(bpy.context)
            assert box is not None and nodes.active_grade(bpy.context) == current()
            if control == 'scope':
                rect = diagram.scope_status_target(bpy.context, current(), box)[0]
            else:
                rect = box[control]
            x, y, width, height = rect
            return round(region.x + x + width / 2), round(region.y + y + height / 2)

    def emit(kind, value='NOTHING', control='scope', delta=(0, 0)):
        window, _, _ = editor()
        x, y = point(control)
        x, y = x + delta[0], y + delta[1]
        assert 0 <= x < window.width and 0 <= y < window.height, (x, y)
        assert window.event_simulate(type=kind, value=value, unicode=None, x=x, y=y) is not None

    def turns(count=4):
        for _ in range(count):
            yield

    def wait_for(predicate, label):
        deadline = time.monotonic() + 90
        while not predicate():
            assert time.monotonic() < deadline, label
            yield

    def captured():
        window, area, region = editor()
        with bpy.context.temp_override(window=window, area=area, region=region):
            state = sampling.scope_input_status(current(), bpy.context)
            assert state['state'] != 'error', state
            return state.get('native') and state['state'] == 'ready' and not state.get('pending')

    def automatic_pages(editor_kind):
        for index,stage in enumerate(('LINEAR', 'REMAP', 'CHROMATIC')):
            bpy.context.window_manager.pg_stage = stage
            yield from turns(6)
            parameters = (nodes.read_parameters(current()), nodes.read_tone(current()),
                          nodes.read_chromatic(current()), current().pg_grade)
            before = counts.copy()
            native_before = report['native_calls']['acquire']
            source=current_tree.nodes['Automatic source']
            if editor_kind=='ShaderNodeTree':source.inputs['Color'].default_value=(.2+.1*index,.3,.6,1.)
            else:source.outputs[0].default_value=(.3+.1*index,.4,.6,1.)
            yield from wait_for(lambda: report['native_calls']['acquire']>native_before,
                                'Visible source edit did not acquire automatically')
            yield from wait_for(captured, 'Automatic native source did not become ready')
            # Invoke hover synchronously: it may query cached status but cannot
            # create a snapshot. Foreground acquisition runs on its own timer.
            native_before=report['native_calls'].copy()
            window,area,region=editor()
            with bpy.context.temp_override(window=window,area=area,region=region):
                box=diagram.layout(bpy.context)
                rect=diagram.scope_status_target(bpy.context,current(),box)[0]
                diagram.hover_cursor(bpy.context,current(),box,(rect[0]+rect[2]/2,rect[1]+rect[3]/2))
            assert report['native_calls']==native_before,'Hover authorized native acquisition'
            assert counts['keyframe'] == before['keyframe'], 'Automatic capture entered autokey handling'
            assert parameters == (nodes.read_parameters(current()), nodes.read_tone(current()),
                                  nodes.read_chromatic(current()), current().pg_grade)
            report['automatic_cases'].append(dict(editor=editor_kind, stage=stage,
                captured=True, hover_passive=True, parameters_unchanged=True, autokey=False))
            record()

    def scenario():
        setup()
        yield from turns(12)
        diagram.ensure_routers()
        assert not hasattr(diagram,'scope_refresh_hit')
        assert not hasattr(sampling,'refresh_scope_inputs')
        yield from wait_for(captured, 'Opening a visible scope did not capture its native source')
        report['initial_open_captured']=True
        for stage, tab, next_stage in (('LINEAR', 'tone_tab', 'REMAP'),
                                       ('REMAP', 'color_tab', 'CHROMATIC'),
                                       ('CHROMATIC', 'linear_tab', 'LINEAR')):
            bpy.context.window_manager.pg_stage = stage
            yield from turns()
            before = counts.copy()
            emit('MOUSEMOVE')
            yield from turns()
            assert counts['hover'] > before['hover'], 'Native hover router was not exercised'
            assert counts['status'] > before['status'], 'Hover did not query with real Blender context'
            emit('MOUSEMOVE', control='close')
            emit('LEFTMOUSE', 'PRESS', 'close')
            yield from turns()
            assert diagram._active_drags, 'Close press did not start a native modal operator'
            emit('LEFTMOUSE', 'RELEASE', 'close')
            yield from wait_for(lambda: not bpy.context.window_manager.pg_diagram_enabled,
                                'Close release did not hide the Gizmo')
            assert not diagram._active_drags, 'Closed Gizmo retained a modal gesture'
            window, area, region = editor()
            with bpy.context.temp_override(window=window, area=area, region=region):
                assert bpy.ops.perceptual_grade.toggle_diagram('EXEC_DEFAULT') == {'FINISHED'}
            del window, area, region
            assert bpy.context.window_manager.pg_diagram_enabled
            yield from turns()
            emit('MOUSEMOVE', control=tab)
            emit('LEFTMOUSE', 'PRESS', tab)
            yield from turns()
            emit('LEFTMOUSE', 'RELEASE', tab)
            yield from wait_for(lambda: bpy.context.window_manager.pg_stage == next_stage,
                                'Reopened Gizmo did not accept a tab click')
            assert not diagram._active_drags
            report['cases'].append(dict(stage=stage, closed=True, reopened=True, tab_changed=True,
                native_context_status_calls=counts['status'] - before['status'],
                hover_calls=counts['hover'] - before['hover']))
            record()

        bpy.context.scene.tool_settings.use_keyframe_insert_auto = True
        yield from automatic_pages('ShaderNodeTree')
        compositor()
        yield from turns(12)
        yield from wait_for(captured, 'Compositor scope did not capture on opening')
        yield from automatic_pages('CompositorNodeTree')

    sequence = scenario()
    def advance():
        try:
            assert time.monotonic() - started < 420, 'Gizmo GUI acceptance exceeded its budget'
            if getattr(bpy.context.window_manager, 'is_event_handling_break', False):
                return .016
            next(sequence)
            return .016
        except StopIteration:
            try:
                diagram.hover_cursor = original_hover
                diagram.keyframe_drag = original_keyframe
                for component_name, original in replaced.items():
                    application.components[component_name] = original
                addon.unregister()
                assert runtime.closed and runtime._shutdown_report.clean
                report.update(passed=True, cleanup_clean=True)
                record()
                assert bpy.ops.wm.quit_blender('EXEC_DEFAULT') == {'FINISHED'}
                return None
            except BaseException:
                fail()
        except BaseException:
            fail()

    def fail():
        report['error'] = traceback.format_exc()
        record()
        print(report['error'], file=sys.stderr, flush=True)
        os._exit(1)

    record()
    bpy.app.timers.register(advance, first_interval=.5)


if __name__ == '__main__':
    main(*sys.argv[sys.argv.index('--') + 1:])
