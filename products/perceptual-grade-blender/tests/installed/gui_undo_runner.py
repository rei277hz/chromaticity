"""Native GUI events against the installed ZIP; no simulated Python operators.

Run with --enable-event-simulate, without --background. The timer drives only
window events and assertions; Blender itself dispatches undo and recovery.
Never retain an RNA object in the scenario generator across a yield/undo.
"""
from dataclasses import asdict
import faulthandler
import gc
import importlib
import json
import os
from pathlib import Path
import signal
import sys
import time
import traceback

import addon_utils
import bpy
import gpu


def main(repository, report_path, cycles='50', blend=None, selected_node='Grade'):
    repository = Path(repository).resolve()
    package = repository / 'perceptual_grade'
    report_path = Path(report_path)
    cycles = int(cycles)
    assert cycles >= 2 and not bpy.app.background
    assert tuple(bpy.app.version) == (5, 2, 2), bpy.app.version
    faulthandler.enable(all_threads=True)
    bpy.context.preferences.view.show_splash = False
    bpy.context.preferences.system.gpu_backend = 'METAL' if sys.platform == 'darwin' else 'OPENGL'
    bpy.context.preferences.edit.use_global_undo = True
    bpy.context.preferences.edit.undo_steps = max(64, cycles * 3)
    bpy.context.preferences.extensions.repos.new(
        name='PG native GUI acceptance', module='pg_gui', custom_directory=str(repository))
    name = 'bl_ext.pg_gui.perceptual_grade'
    errors = []
    addon = addon_utils.enable(name, default_set=False, handle_error=errors.append)
    assert addon is not None and not errors, repr(errors)
    assert Path(addon.__file__).resolve() == package / '__init__.py'

    prefix = 'perceptual_grade_blender.'
    lifecycle = importlib.import_module(name + '.' + prefix + 'integration.lifecycle')
    registry = importlib.import_module(name + '.' + prefix + 'integration.registry')
    for value in (lifecycle, registry):
        assert Path(value.__file__).resolve().is_relative_to(package)
    application = lifecycle.registered_session()
    assert application is not None

    def module(suffix):
        value = importlib.import_module(name + '.' + suffix)
        assert Path(value.__file__).resolve().is_relative_to(package)
        component = suffix.removeprefix(prefix)
        if suffix.startswith(prefix) and component in registry.COMPONENTS:
            return application.component(component)
        return value

    nodes, lut = module('perceptual_grade_blender.graph.nodes'), module('perceptual_grade_blender.graph.lut')
    output_resources = module('perceptual_grade_blender.graph.output_resources')
    scheduler, diagram = module('perceptual_grade_blender.graph.scheduler'), module('perceptual_grade_blender.ui.diagram')
    color, runtime_module = module('perceptual_grade_blender.ui.color'), module('perceptual_grade_blender.services')
    scope_jobs = module('perceptual_grade_blender.scopes.jobs')
    sampling = module('perceptual_grade_blender.scopes.sampling')
    ownership = module('perceptual_grade_blender.ownership')
    material_name, node_name = 'PG GUI undo material', 'PG GUI undo Grade'
    started = time.monotonic()
    report = dict(blender=list(bpy.app.version), build=bpy.app.build_hash.decode(),
                  platform=sys.platform, backend=gpu.platform.backend_type_get(),
                  device=gpu.platform.renderer_get(), pid=os.getpid(), cycles=cycles,
                  passed=False, events=[], cases=[])
    stopped = set()
    scope_waits = 0
    analytic_captures = 0
    reset_cases = min(5, cycles)
    original_capture = scope_jobs._capture_effect
    actor_calls = {}
    actor_host = application.app.actors
    original_actor_call = actor_host.call

    def observe_actor_call(coroutine, operation):
        begin = time.monotonic()
        try:
            return original_actor_call(coroutine, operation)
        finally:
            kind = operation.split(':', 1)[0]
            entry = actor_calls.setdefault(kind, dict(count=0, seconds=0.))
            entry['count'] += 1
            entry['seconds'] += time.monotonic() - begin

    actor_host.call = observe_actor_call
    capture_timings = {}
    original_describe = module('perceptual_grade_blender.scopes.capture').describe
    capture_component = application.components['scopes.capture']
    component_types = module('perceptual_grade_blender.integration.components')

    def timed_capture(label, action):
        def measured(*args, **kwargs):
            begin = time.monotonic()
            try:
                return action(*args, **kwargs)
            finally:
                elapsed = time.monotonic() - begin
                entry = capture_timings.setdefault(label, dict(count=0, seconds=0., max_seconds=0.))
                entry['count'] += 1
                entry['seconds'] += elapsed
                entry['max_seconds'] = max(entry['max_seconds'], elapsed)
        return measured

    # Instrument adapter calls only in this acceptance process. The closures
    # retain functions and scalar totals, never arguments, frames, or RNA.
    measured_describe = timed_capture('describe', original_describe)
    capture_exports = {key: (lambda key=key: getattr(capture_component, key))
                       for key, _ in component_types.component_items(capture_component) if key != 'describe'}
    application.components['scopes.capture'] = component_types.Component(
        {'describe': measured_describe}, readers=capture_exports)
    startup_diagnostics = cycles == 2
    startup_trace = None
    if startup_diagnostics:
        startup_trace = report_path.with_suffix('.stacks.txt').open('w')
        faulthandler.dump_traceback_later(10, repeat=True, file=startup_trace)

    def observe_capture(spec, action):
        nonlocal scope_waits, analytic_captures
        try:
            result = original_capture(spec, action)
            if spec.get('_scope_evaluation', ('',))[0] == 'regular-grade-appearance':
                analytic_captures += 1
            return result
        except (ValueError, ReferenceError, RuntimeError, OSError, ArithmeticError) as error:
            if scope_jobs._preparing(error):
                scope_waits += 1
            raise

    # Call production capture unchanged; retain only a scalar expected-wait
    # counts, never its exception, traceback, capture closure, or RNA request.
    # Regular Grade scopes are analytic: a pending final LUT must not force
    # ScopePreparing. Successful capture while the LUT is pending exercises
    # the current contract; expecting a final-LUT wait here was a stale premise.
    scope_jobs._capture_effect = observe_capture

    def record(event, **values):
        report['events'].append(dict(event=event, seconds=time.monotonic() - started,
                                    actor_calls={key: dict(value) for key, value in actor_calls.items()},
                                    capture_timings={key: dict(value) for key, value in capture_timings.items()},
                                    **values))
        report_path.write_text(json.dumps(report, indent=2), encoding='utf8')
        print('PG_GUI_EVENT', json.dumps(report['events'][-1]), flush=True)

    original_recover = lut.adopt_native
    previous_profile = sys.getprofile()
    if blend is not None:
        watched = {getattr(lut, label).__code__: label for label in
                   ('adopt_native', '_output_snapshot', '_manifest', 'validate_output', 'read_cube')}

        def recovery_profile(frame, event, arg):
            # A Python return event precedes local-reference destruction. Never
            # store frame, arg, f_locals or returned RNA in the diagnostic log.
            label = watched.get(frame.f_code)
            if label is not None and event in {'call', 'return'}:
                record('recovery_' + ('call' if event == 'call' else 'return_requested'),
                       function=label, line=frame.f_lineno, instruction=frame.f_lasti)

        def observe_recovery(node,*args,**kwargs):
            record('recover_enter', node=node.name, tree=node.id_data.name)
            result = original_recover(node,*args,**kwargs)
            # If the last recorded event is return_requested but this marker
            # is absent, original_recover did not finish its frame teardown.
            record('recover_returned', adopted=lut.is_adopted(node))
            return result

        lut.adopt_native = observe_recovery
        sys.setprofile(recovery_profile)

    # Observe native handler dispatch without retaining any RNA wrappers.
    @bpy.app.handlers.persistent
    def native_undo_pre(_): record('native_undo_pre')
    @bpy.app.handlers.persistent
    def native_undo_post(_): record('native_undo_post', recovery_pending=bool(nodes.recovery_pending()))
    @bpy.app.handlers.persistent
    def native_redo_pre(_): record('native_redo_pre')
    @bpy.app.handlers.persistent
    def native_redo_post(_): record('native_redo_post', recovery_pending=bool(nodes.recovery_pending()))
    for event, callback in (('undo_pre', native_undo_pre), ('undo_post', native_undo_post),
                            ('redo_pre', native_redo_pre), ('redo_post', native_redo_post)):
        getattr(bpy.app.handlers, event).append(callback)

    def current():
        return bpy.data.materials[material_name].node_tree.nodes[node_name]

    def editor():
        window = bpy.context.window_manager.windows[0]
        area = next(a for a in window.screen.areas if a.type == 'NODE_EDITOR')
        region = next(r for r in area.regions if r.type == 'WINDOW')
        return window, area, region

    def setup():
        nonlocal material_name, node_name
        if blend is not None:
            # Keep only value locators after discovery. No fixture RNA may
            # survive into a yield or native undo boundary.
            candidates = [(material.name, node.name)
                          for material in bpy.data.materials if material.node_tree
                          for node in material.node_tree.nodes
                          if nodes.is_grade(node) and node.name == selected_node]
            if len(candidates) != 1:
                raise ValueError('Expected one material Grade named ' + repr(selected_node)
                                 + ', found ' + repr(candidates))
            material_name, node_name = candidates[0]
            material = bpy.data.materials[material_name]
            obj = next((obj for obj in bpy.context.view_layer.objects
                        if any(slot.material == material for slot in obj.material_slots)), None)
            if obj is None:
                raise ValueError('Selected Grade material has no object in the active view layer')
            bpy.context.view_layer.objects.active = obj
            obj.select_set(True)
            obj.active_material_index = next(index for index, slot in enumerate(obj.material_slots)
                                             if slot.material == material)
            node = current()
            record('project_target', material=material_name, node=node_name,
                   object=obj.name, saved_pending=bool(node.get(lut.INCOMPLETE)))
        else:
            material = bpy.data.materials.new(material_name)
            material.use_nodes = True
            material.use_fake_user = True
            obj = bpy.context.view_layer.objects.active
            assert obj is not None
            obj.data.materials.clear()
            obj.data.materials.append(material)
            node = nodes.create_grade(material.node_tree)
            node.name = node_name
            node.inputs['Color'].default_value = (.12, .24, .7, 1.)
            principled = next(n for n in material.node_tree.nodes if n.type == 'BSDF_PRINCIPLED')
            material.node_tree.links.new(node.outputs['Color'], principled.inputs['Base Color'])
        node.pg_chromatic.family = 'WARP'
        node.pg_chromatic.active_tone = 1
        node.pg_chromatic.active_handle = 4
        for item in material.node_tree.nodes:
            item.select = item == node
        material.node_tree.nodes.active = node
        window = bpy.context.window_manager.windows[0]
        area = max(window.screen.areas, key=lambda a: a.width * a.height)
        with bpy.context.temp_override(window=window, area=area):
            area.type = 'NODE_EDITOR'
            area.ui_type = 'ShaderNodeTree'
            area.spaces.active.shader_type = 'OBJECT'
            area.spaces.active.show_region_ui = False
        wm = bpy.context.window_manager
        wm.pg_diagram_enabled = True
        wm.pg_stage = 'CHROMATIC'
        wm.pg_color_width = 660
        wm.pg_diagram_x = wm.pg_diagram_y = 24.
        area.tag_redraw()

    def ready_editor():
        try:
            window, area, region = editor()
        except (IndexError, StopIteration):
            return False
        with bpy.context.temp_override(window=window, area=area, region=region):
            return nodes.active_grade(bpy.context) == current() and diagram.layout(bpy.context) is not None

    def values():
        return asdict(nodes.read_chromatic(current()))

    def final_ready():
        if nodes.recovery_pending():return False
        node = current()
        if getattr(lut,'is_adopted',lambda _:False)(node):return True
        image = lut.image_for(node)
        return bool(image is not None and not node.get(lut.INCOMPLETE) and
                    image.get('_pg_cube_size') == 65 and
                    image.get('_pg_cube_signature') == lut.cm.signature(nodes.bake_model(node)))

    def assert_final():
        node = current()
        if getattr(lut,'is_adopted',lambda _:False)(node):
            assert nodes.recovery_status()['state'] == 'completed'
        else:lut.validate_output(node, nodes.bake_model(node), final=True)
        output_edges()
        posts=[event for event in report['events'] if event['event'] in ('native_undo_post','native_redo_post')]
        done=sum(event['event']=='runtime_recovery_complete' for event in report['events'])
        if len(posts)>done:record('runtime_recovery_complete',native_event=posts[-1]['event'],ordinal=len(posts))

    def output_edges():
        node = current()
        kernel = node.node_tree
        live_images = {image.as_pointer() for image in bpy.data.images}
        live_trees = {tree.as_pointer() for tree in bpy.data.node_groups}
        assert kernel.as_pointer() in live_trees
        assert len(output_resources.bank_images(node)) == 4
        images, helpers = [], []
        for item in kernel.nodes:
            if item.get('_pg_cube_image'):
                pointer = item.image.as_pointer()
                assert pointer in live_images, 'Retained LUT link targets an absent Image'
                images.append((item.name, pointer))
            if item.get('_pg_cube_address'):
                pointer = item.node_tree.as_pointer()
                assert pointer in live_trees, 'Retained Address link targets an absent helper'
                helpers.append((item.name, pointer))
        return (kernel.as_pointer(), tuple(sorted(images)), tuple(sorted(helpers)),
                tuple(sorted((link.from_node.name, link.from_socket.identifier,
                              link.to_node.name, link.to_socket.identifier) for link in kernel.links)))

    def blue_point():
        window, area, region = editor()
        with bpy.context.temp_override(window=window, area=area, region=region):
            node = current()
            box = diagram.layout(bpy.context)
            assert box is not None
            _, model, _, plot = color.control_state(node, nodes.grading_space(node), box)
            x, y = plot.screen(model.guarded_saturation_targets(1)[5])
            action = color.hit(node, nodes.grading_space(node), box, (x, y))
            assert action and action['kind'] == 'warp_dot' and action['handle'] == 4, action
            return int(round(region.x + x)), int(round(region.y + y))

    def emit(kind, value='NOTHING', point=None, **modifiers):
        window, area, region = editor()
        x, y = point or (region.x + region.width // 2, region.y + region.height // 2)
        assert 0 <= x < window.width and 0 <= y < window.height, (kind, x, y)
        assert window.event_simulate(type=kind, value=value, unicode=None,
                                     x=x, y=y, **modifiers) is not None

    def active_blue():
        return any((getattr(ownership.resolve(ref), '_color_action', None) or {}).get('handle') == 4
                   for ref in diagram._active_drags.values())

    def scope_idle():
        runtime = runtime_module.current_runtime()
        runtime.poll(budget_ms=4)
        window, area, region = editor()
        with bpy.context.temp_override(window=window, area=area, region=region):
            state = scope_jobs._states.get(sampling.channel(current()))
        return bool(state is not None and state['completed'] == state['spec']['key'] and
                    not any(not job.finished for job in runtime.jobs.values()))

    def waiting_state():
        """Persist only scalar observations; never retain RNA across an event."""
        runtime = runtime_module.current_runtime()
        try:
            window, area, region = editor()
            with bpy.context.temp_override(window=window, area=area, region=region):
                channel = sampling.channel(current())
                state = scope_jobs._states.get(channel)
        except (IndexError, StopIteration, ReferenceError, RuntimeError) as error:
            return dict(scope_observation_error=str(error))
        return dict(channel=repr(channel), scope_found=state is not None,
                    scope_complete=bool(state and state['completed'] == state['spec']['key']),
                    scope_error='' if state is None else str(state.get('error', '')),
                    scope_channels=[repr(key) for key in scope_jobs._states],
                    jobs=[] if runtime is None else [dict(operation=job.spec.operation,
                        role=job.role, finished=job.finished) for job in runtime.jobs.values()
                        if not job.finished])

    def active_lut_receipt():
        runtime = runtime_module.current_runtime()
        runtime.poll(budget_ms=4)
        state = lut._states.get(current().as_pointer())
        if state is None:
            return None
        baker = state['baker']
        if baker.signature != lut.cm.signature(nodes.bake_model(current())):
            return None
        handle = getattr(baker, 'handle', None)
        if handle is None:
            return None
        job = handle._job
        helper = runtime.helpers.get(job.role)
        if (helper is None or helper.active is not job or job.finished or
                job.spec.operation != 'lut_bake' or not handle.running() or
                helper.process.pid not in stopped):
            return None
        return dict(attempt=job.state.identity, generation=job.state.generation,
                    pid=helper.process.pid, backend=job.role)

    def pause_helpers():
        runtime = runtime_module.current_runtime()
        assert runtime is not None
        for helper in runtime.helpers.values():
            if helper.process.poll() is None:
                os.kill(helper.process.pid, signal.SIGSTOP)
                stopped.add(helper.process.pid)
        assert stopped, 'Pending-output case must pause an already started helper'
        record('helpers_paused', pids=sorted(stopped))

    def resume_helpers():
        for pid in tuple(stopped):
            try:
                os.kill(pid, signal.SIGCONT)
            except ProcessLookupError:
                pass
            stopped.discard(pid)

    def push_baseline():
        window, area, region = editor()
        with bpy.context.temp_override(window=window, area=area, region=region):
            assert bpy.ops.ed.undo_push(message='PG GUI baseline') == {'FINISHED'}

    def turns(count=4):
        for _ in range(count):
            yield

    def wait_for(predicate, label, timeout=120):
        deadline = time.monotonic() + timeout
        observation_due = time.monotonic() + 10
        while not predicate():
            if time.monotonic() >= observation_due:
                record('waiting', label=label, **waiting_state())
                observation_due = time.monotonic() + 10
            if time.monotonic() >= deadline:
                raise TimeoutError(label)
            yield

    def undo_key(redo=False):
        # Bind the test's Ctrl-Z explicitly on macOS too; then use actual
        # keyboard events rather than directly calling bpy.ops.ed.undo().
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
        nonlocal startup_diagnostics
        if blend is not None:
            record('project_load_begin', path=str(Path(blend).resolve()))
            assert bpy.ops.wm.open_mainfile(filepath=str(Path(blend).resolve()),
                                            load_ui=False, use_scripts=False) == {'FINISHED'}
            record('project_load_complete')
            # Opening a file resets native window/context state. Finish that
            # WM event before configuring the editor on a subsequent timer turn.
            yield from turns(12)
        yield from wait_for(lambda: nodes.recovery_status()['state']=='completed' and not nodes.recovery_pending(), 'Initial runtime recovery')
        setup()
        record('setup_complete')
        yield from turns(12)
        yield from wait_for(ready_editor, 'Shader Editor did not expose the Grade')
        if startup_diagnostics:
            faulthandler.cancel_dump_traceback_later()
            startup_trace.close()
            startup_diagnostics = False
        record('editor_ready')
        diagram.ensure_routers()
        yield from wait_for(final_ready, 'Baseline final LUT did not complete')
        record('baseline_lut_ready')
        assert_final()
        # A factory-startup keymap is isolated from the user's configuration.
        keymap = bpy.context.window_manager.keyconfigs.addon.keymaps.new(name='Screen', space_type='EMPTY')
        keymap.keymap_items.new('ed.undo', 'Z', 'PRESS', ctrl=True)
        keymap.keymap_items.new('ed.redo', 'Z', 'PRESS', ctrl=True, shift=True)
        keymap.keymap_items.new('perceptual_grade.reset_stage', 'F8', 'PRESS')
        del keymap
        bpy.context.window_manager.keyconfigs.update()
        push_baseline()
        yield from turns()
        for cycle in range(cycles):
            # Undo fences the previous window router. Reinstall it before the
            # next mouse-down instead of racing the ordinary 350 ms poll.
            diagram.ensure_routers()
            yield from turns()
            pending = cycle % 2 == 0
            before = values()
            fixed_edges = output_edges()
            point = blue_point()
            record('drag_begin', cycle=cycle, pending=pending, point=point)
            wait_start = scope_waits
            capture_start = analytic_captures
            pending_captures = 0
            pending_waits = 0
            if pending:
                # Do not freeze an older scope job that would occupy the bulk
                # lane before this cycle's actual LUT attempt can dispatch.
                yield from wait_for(scope_idle, 'Baseline full scope did not settle')
                wait_start = scope_waits
                capture_start = analytic_captures
                assert gc.isenabled()
                # Expose old RNA retained by exception/closure cycles: its
                # destruction must remain safe after Blender restores undo.
                gc.disable()
                pause_helpers()
            emit('MOUSEMOVE', point=point)
            yield from turns()
            emit('LEFTMOUSE', 'PRESS', point)
            yield from wait_for(active_blue, 'Real blue Warp modal operator did not start', 10)
            moved = (point[0] + 7 + cycle, point[1] + 5)
            emit('MOUSEMOVE', point=moved)
            yield from turns()
            emit('LEFTMOUSE', 'RELEASE', moved)
            yield from wait_for(lambda: not diagram._active_drags, 'Real drag did not finish', 10)
            after = values()
            assert before != after, 'Blue Warp event did not change parameters'
            if pending:
                assert not final_ready(), 'Pending-output case unexpectedly reused a final LUT'
                yield from wait_for(lambda: active_lut_receipt() is not None,
                                    'Released LUT never dispatched to a paused helper', 10)
                yield from wait_for(lambda: analytic_captures > capture_start,
                                    'Analytic scopes did not capture while final LUT was pending', 10)
                pending_captures = analytic_captures - capture_start
                pending_waits = scope_waits - wait_start
                assert pending_waits == 0, 'Regular Grade scopes waited for a pending LUT'
                active_lut = active_lut_receipt()
                assert active_lut is not None
                record('pending_attempt', cycle=cycle, **active_lut,
                       analytic_captures=pending_captures, scope_preparing_waits=pending_waits)
            else:
                yield from wait_for(final_ready, 'Released final LUT did not complete')
                assert_final()
            assert output_edges() == fixed_edges, 'Routine publication changed native output links'
            record('undo_begin', cycle=cycle, pending=pending,
                   poll=bpy.ops.ed.undo.poll(),
                   operators=[op.bl_idname for op in bpy.context.window_manager.operators])
            yield from undo_key()
            collected = None
            if pending:
                gc.enable()
                collected = gc.collect()
                record('gc_after_native_undo', cycle=cycle, collected=collected)
            assert values() == before, ('Native undo did not restore the pre-drag settings',
                                       {key: [before[key], after[key], value]
                                        for key, value in values().items() if value != before[key]})
            assert not diagram._active_drags
            resume_helpers()
            yield from wait_for(final_ready, 'Undone final output did not recover')
            assert_final()
            yield from undo_key(redo=True)
            assert values() == after, 'Native redo did not restore the drag settings'
            yield from wait_for(final_ready, 'Redone final output did not recover')
            assert_final()
            if cycle < reset_cases:
                # Dispatch the same registered operator as the UI button via
                # WM events, including Blender's normal automatic undo push.
                # Calling it directly from this Python timer skips that push.
                emit('F8', 'PRESS')
                yield from turns()
                emit('F8', 'RELEASE')
                yield from turns()
                reset_values = values()
                assert reset_values != after, 'Stage reset did not change the edited Grade'
                record('reset_stage', cycle=cycle)
                yield from turns()
                yield from wait_for(final_ready, 'Reset final output did not complete')
                assert_final()
                yield from undo_key()
                assert values() == after, 'Undo did not restore pre-reset settings'
                yield from wait_for(final_ready, 'Undo-reset final output did not recover')
                assert_final()
                yield from undo_key(redo=True)
                assert values() == reset_values, 'Redo did not restore reset settings'
                yield from wait_for(final_ready, 'Redo-reset final output did not recover')
                assert_final()
                yield from undo_key()
                assert values() == after, 'Second undo-reset did not restore edited settings'
                yield from wait_for(final_ready, 'Second undo-reset output did not recover')
                assert_final()
                record('reset_chain_complete', cycle=cycle)
            yield from undo_key()
            assert values() == before
            yield from wait_for(final_ready, 'Second undo did not recover')
            assert_final()
            report['cases'].append(dict(cycle=cycle, pending=pending, runtime_reconciled=True,
                                        gc_deferred=pending, collected=collected,
                                        pending_analytic_captures=pending_captures,
                                        pending_scope_preparing_waits=pending_waits,
                                        fixed_native_links=True,
                                        reset_chain=cycle < reset_cases))
            record('cycle_complete', cycle=cycle)
        for event, expected in (('native_undo_pre', 2 * cycles + 2 * reset_cases),
                                ('native_undo_post', 2 * cycles + 2 * reset_cases),
                                ('native_redo_pre', cycles + reset_cases),
                                ('native_redo_post', cycles + reset_cases)):
            observed = sum(item['event'] == event for item in report['events'])
            assert observed == expected, (event, observed, expected)
        report['source_isolation'] = True
        report['fingerprint'] = runtime_module.current_runtime().fingerprint
        record('cycles_complete')

    sequence = scenario()
    handling_break_ticks = 0

    def fail():
        report['passed'] = False
        report['error'] = traceback.format_exc()
        try:
            record('failed')
            print(report['error'], file=sys.stderr, flush=True)
        finally:
            try:
                resume_helpers()
                gc.enable()
            finally:
                # A timer exception alone does not reliably fail the native process.
                import ctypes
                ctypes.CDLL(None).fflush(None)
                os._exit(1)

    def advance():
        nonlocal handling_break_ticks
        try:
            if time.monotonic() - started >= 1740:
                raise TimeoutError('Native GUI scenario exceeded its 29 minute budget')
            # Match Blender's UI simulation driver: leave ordinary WM turns
            # between injected events and do not advance through its break.
            if getattr(bpy.context.window_manager, 'is_event_handling_break', False):
                handling_break_ticks += 1
                if handling_break_ticks > 256:
                    raise RuntimeError('Event handling break persisted for 256 timer turns')
                return .016
            handling_break_ticks = 0
            next(sequence)
            if startup_diagnostics:
                print('PG_GUI_STARTUP_TURN', json.dumps(dict(
                    seconds=time.monotonic() - started, actor_calls=actor_calls,
                    capture_timings=capture_timings)), flush=True)
            return .016
        except StopIteration:
            try:
                resume_helpers()
                application.components['scopes.capture'] = capture_component
                scope_jobs._capture_effect = original_capture
                lut.adopt_native = original_recover
                if blend is not None:
                    sys.setprofile(previous_profile)
                runtime = runtime_module.current_runtime()
                helpers = tuple(runtime.helpers.values())
                addon.unregister()
                assert runtime.closed and runtime._shutdown_report.clean, 'Native teardown was not clean'
                assert all(helper.process.poll() is not None for helper in helpers), 'Native helpers survived teardown'
                report['cleanup_clean'] = True
                report['retired_helper_pids'] = [helper.process.pid for helper in helpers]
                report['passed'] = True
                record('complete')
                assert bpy.ops.wm.quit_blender('EXEC_DEFAULT') == {'FINISHED'}
            except BaseException:
                fail()
            return None
        except BaseException:
            fail()

    record('started')
    bpy.app.timers.register(advance, first_interval=.5, persistent=True)


if __name__ == '__main__':
    main(*sys.argv[sys.argv.index('--') + 1:])
