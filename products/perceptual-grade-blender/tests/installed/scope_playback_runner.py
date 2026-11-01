"""Real timeline and compositor jobs against an isolated installed package."""
import importlib
import json
import os
from pathlib import Path
import struct
import sys
import time
import traceback
import zlib

import addon_utils
import bpy


def main(repository, report_path):
    repository, report_path = Path(repository), Path(report_path)
    bpy.context.preferences.view.show_splash = False
    bpy.context.preferences.extensions.repos.new(name='Scope playback acceptance',
        module='pg_playback', custom_directory=str(repository))
    name = 'bl_ext.pg_playback.perceptual_grade'
    addon = addon_utils.enable(name, default_set=False)
    assert addon is not None and not bpy.app.background
    app = importlib.import_module(name + '.perceptual_grade_blender.integration.lifecycle').registered_session()
    nodes, lut, jobs, sampling, guard = (app.component(part) for part in
        ('graph.nodes', 'graph.lut', 'scopes.jobs', 'scopes.sampling', 'graph.output_guard'))
    runtime = app.app.execution.get_runtime()
    capture=app.component('scopes.capture')
    capture.enable_diagnostics(True)
    report = dict(passed=False, cases=[], cold_paused_while_playing=False)
    started = time.monotonic()

    def save():
        report_path.write_text(json.dumps(report, indent=2))

    def editor():
        window = bpy.context.window_manager.windows[0]
        area = next(item for item in window.screen.areas if item.type == 'NODE_EDITOR')
        return window, area, next(item for item in area.regions if item.type == 'WINDOW')

    def setup():
        def chunk(kind, data):
            return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data) & 0xffffffff)
        width, height = 640, 360
        pixels = b''.join(b'\0' + bytes((40 + (y % 64) * 3, 100, 180, 255)) * width for y in range(height))
        data = b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>2I5B', width, height, 8, 6, 0, 0, 0))
        path = report_path.with_suffix('.png')
        path.write_bytes(data + chunk(b'IDAT', zlib.compress(pixels)) + chunk(b'IEND', b''))
        image = bpy.data.images.load(str(path)); image.pack()
        tree = bpy.data.node_groups.new('Playback source', 'CompositorNodeTree')
        tree.interface.new_socket(name='Image', in_out='OUTPUT', socket_type='NodeSocketColor')
        scene = bpy.context.scene
        scene.compositing_node_group = tree
        scene.render.compositor_device = 'CPU'
        scene.render.resolution_x, scene.render.resolution_y = width, height
        scene.render.resolution_percentage = 100
        scene.frame_start, scene.frame_end, scene.render.fps = 1, 120, 12
        source = tree.nodes.new('CompositorNodeImage'); source.image = image
        transform = tree.nodes.new('CompositorNodeTransform')
        tree.links.new(source.outputs['Image'], transform.inputs['Image'])
        grade = nodes.create_grade(tree); grade.name = 'Grade'
        lut.ensure(grade, nodes.bake_model(grade))
        native = tree.nodes.new('CompositorNodeBlur')
        tree.links.new(transform.outputs['Image'],native.inputs['Image'])
        tree.links.new(native.outputs['Image'],grade.inputs['Color'])
        output = tree.nodes.new('NodeGroupOutput'); output.is_active_output = True
        tree.links.new(grade.outputs['Color'], output.inputs['Image'])
        viewer = tree.nodes.new('CompositorNodeViewer')
        tree.links.new(grade.outputs['Color'], viewer.inputs['Image'])
        tree.nodes.active = grade
        for node in tree.nodes:node.select = node == grade
        window = bpy.context.window_manager.windows[0]
        area = max(window.screen.areas, key=lambda item: item.width * item.height)
        area.type = 'NODE_EDITOR'; area.ui_type = 'CompositorNodeTree'
        area.spaces.active.pin = True; area.spaces.active.node_tree = tree
        area.spaces.active.show_backdrop = True
        area.spaces.active.show_region_ui = False
        bpy.context.window_manager.pg_stage = 'LINEAR'
        bpy.context.window_manager.pg_diagram_enabled = False
        scene.frame_set(1)

    def current():
        return bpy.data.node_groups['Playback source'].nodes['Grade']

    def playback(play):
        window, area, region = editor()
        with bpy.context.temp_override(window=window, area=area, region=region):
            if play:bpy.ops.screen.animation_play()
            else:bpy.ops.screen.animation_cancel(restore_frame=False)

    def state(kind):
        window, area, region = editor()
        with bpy.context.temp_override(window=window, area=area, region=region):
            node = current()
            return jobs.status(node, kind, channel=sampling.channel(node,bpy.context))

    def published_result(kind):
        window, area, region = editor()
        with bpy.context.temp_override(window=window, area=area, region=region):
            channel = sampling.channel(current(), bpy.context)
            states = jobs._linear_states if kind == 'linear' else jobs._states
            return states.get(channel, {}).get('result')

    def turns(seconds):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:yield

    def scenario():
        deadline=time.monotonic()+15
        while nodes.recovery_status()['state']!='completed' or nodes.recovery_pending():
            assert time.monotonic()<deadline, nodes.recovery_status()
            yield
        setup()
        yield from turns(.5)
        playback(True)
        yield from turns(.5)
        bpy.context.window_manager.pg_diagram_enabled = True
        initial=published_result('linear')
        acquired=sum(item['event']=='request_created' for item in capture.diagnostics())
        deadline=time.monotonic()+1.5
        frames=set()
        while time.monotonic()<deadline:
            assert editor()[0].screen.is_animation_playing
            frames.add(bpy.context.scene.frame_current)
            assert published_result('linear') is initial,'Cold scope published during playback'
            assert sum(item['event']=='request_created' for item in capture.diagnostics())==acquired
            yield
        assert len(frames)>1,'Timeline did not advance'
        report['cold_paused_while_playing']=True
        save()
        playback(False)
        stopped=bpy.context.scene.frame_current
        deadline=time.monotonic()+45
        while state('linear')['state']!='current' or state('linear').get('scene_frame')!=stopped or not guard.available():
            assert time.monotonic()<deadline,('Cold scope did not resume at stopped frame',stopped,state('linear'),guard.reason())
            yield
        report['cold_resumed_frame']=stopped
        # Production keyframing drives the selected Grade without a drag lease.
        bpy.context.scene.frame_set(1)
        nodes.write_values(current(), {'exposure': 0.})
        nodes.keyframe_parameter(current(), 'exposure')
        bpy.context.scene.frame_set(120)
        nodes.write_values(current(), {'exposure': 1.})
        nodes.keyframe_parameter(current(), 'exposure')
        for stage in ('LINEAR', 'REMAP', 'CHROMATIC'):
            bpy.context.scene.frame_set(1)
            bpy.context.window_manager.pg_stage = stage
            kind = 'linear' if stage == 'LINEAR' else 'full'
            deadline=time.monotonic()+45
            while state(kind)['state']!='current' or state(kind).get('scene_frame')!=1 or not guard.available():
                assert time.monotonic()<deadline,('Scope did not become current before playback',stage,state(kind),guard.reason())
                yield
            retained=published_result(kind)
            assert retained is not None
            acquired=sum(item['event']=='request_created' for item in capture.diagnostics())
            playback(True)
            frames=set();compositor_busy_samples=0
            deadline=time.monotonic()+2.
            while time.monotonic()<deadline:
                assert editor()[0].screen.is_animation_playing
                frames.add(bpy.context.scene.frame_current)
                compositor_busy_samples+=bpy.app.is_job_running('COMPOSITE')
                assert published_result(kind) is retained,('Scope published during playback',stage,state(kind))
                assert sum(item['event']=='request_created' for item in capture.diagnostics())==acquired
                yield
            assert len(frames)>1,('Timeline did not advance',stage)
            playback(False)
            stopped=bpy.context.scene.frame_current
            deadline=time.monotonic()+45
            while state(kind)['state']!='current' or state(kind).get('scene_frame')!=stopped or not guard.available():
                assert time.monotonic()<deadline,('Scope did not resume newest stopped frame',stage,stopped,state(kind),guard.reason())
                yield
            assert published_result(kind) is not retained,('Stopped frame did not produce a new scope',stage)
            report['cases'].append(dict(stage=stage,playing_frames=sorted(frames),
                compositor_busy_samples=compositor_busy_samples,publication_paused=True,
                acquisition_paused=True,resumed_frame=stopped,native_acknowledged=True))
            save()

        # Loading restores the saved Grade controls around the adopted native
        # output, including the live dependency's pre-save mute state. A later
        # frame change is new animation intent and must resume updates.
        def dependency_muted():
            node=current()
            path=node.path_from_id()+'["_pg_grade_dependency"]'
            curve=node.id_data.animation_data.drivers.find(path)
            return bool(curve.mute)
        project=report_path.with_suffix('.blend')
        saved_mute=dependency_muted()
        editor()[1].spaces.active.show_backdrop=False
        yield from turns(.5)
        deadline=time.monotonic()+15
        while True:
            assert time.monotonic()<deadline,('Save did not reach a safe boundary',guard.reason())
            try:
                app.component('graph.output').guarded_save(str(project))
                break
            except guard.PublicationDeferred:yield
        saved_graph=lut._graph_snapshot(current())
        bpy.ops.wm.open_mainfile(filepath=str(project))
        deadline=time.monotonic()+15
        while nodes.recovery_status()['state']!='completed' or nodes.recovery_pending():
            assert time.monotonic()<deadline, nodes.recovery_status()
            yield
        yield from turns(.5)
        assert lut.is_adopted(current())
        assert current().bl_idname == 'PGCompositorGrade', current().bl_idname
        assert dependency_muted() == saved_mute, 'Load did not restore the Grade dependency mute state'
        assert lut._graph_snapshot(current())==saved_graph,'Control restoration changed native output'
        restored=dict(native_preserved=True, controls_restored=True,
                      dependency_mute_restored=True, frames=[])
        report['loaded_animation']=restored;save()
        bpy.context.window_manager.pg_stage='LINEAR'
        bpy.context.window_manager.pg_diagram_enabled=True
        for frame,expected in ((120,1.),(1,0.)):
            bpy.context.scene.frame_set(frame)
            deadline=time.monotonic()+15
            while True:
                exposure=nodes.read_parameters(current()).exposure
                value=state('linear')
                actual_rows=lut._graph_snapshot(current())['rows']
                expected_rows=lut._checked_rows(*lut.scope_rows(current()))
                if (abs(exposure-expected)<1e-5 and value.get('scene_frame')==frame
                        and value['state']=='current' and actual_rows==expected_rows):break
                assert time.monotonic()<deadline,('Loaded animation did not resume',frame,exposure,value,dependency_muted())
                yield
            restored['frames'].append(dict(frame=frame,exposure=exposure,scope_frame=value['scene_frame'],native_rows_current=True))
            save()

    sequence = scenario()
    def advance():
        try:
            assert time.monotonic() - started < 360, 'Playback acceptance exceeded its budget'
            next(sequence)
            return .02
        except StopIteration:
            try:
                addon.unregister()
                report['runtime_closed'] = runtime.closed
                shutdown = runtime._shutdown_report
                report['shutdown_errors'] = list(shutdown.errors) if shutdown is not None else []
                assert runtime.closed and runtime._shutdown_report.clean
                report.update(passed=True, cleanup_clean=True)
                save();bpy.ops.wm.quit_blender('EXEC_DEFAULT')
                return None
            except BaseException:fail()
        except BaseException:fail()

    def fail():
        report['error'] = traceback.format_exc();save()
        print(report['error'], flush=True)
        os._exit(1)

    bpy.app.timers.register(advance, first_interval=.2,persistent=True)


if __name__ == '__main__':
    main(*sys.argv[sys.argv.index('--') + 1:])
