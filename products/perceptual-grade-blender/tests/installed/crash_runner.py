"""Native parent crash checkpoints, using only the extracted extension ZIP."""
import importlib
import json
import os
from pathlib import Path
import shutil
import signal
import sys
import time

import addon_utils
import bpy
import numpy as np


def main(repository, mode, project, report_path, prior_report=''):
    package = Path(repository).resolve() / 'perceptual_grade'
    bpy.context.preferences.system.gpu_backend = 'OPENGL'
    bpy.context.preferences.extensions.repos.new(
        name='PG crash acceptance', module='pg_crash', custom_directory=repository)
    name = 'bl_ext.pg_crash.perceptual_grade'
    errors = []
    addon = addon_utils.enable(name, default_set=False, handle_error=errors.append)
    assert addon is not None and not errors, errors
    assert Path(addon.__file__).resolve() == package / '__init__.py'
    def module(suffix):
        value = importlib.import_module(name + '.' + suffix)
        assert Path(value.__file__).resolve().is_relative_to(package), value.__file__
        return value
    application = module('perceptual_grade_blender.integration.lifecycle').registered_session()
    assert application is not None
    lut, nodes, grades, output = (application.component('graph.' + part)
                                  for part in ('lut', 'nodes', 'grades', 'output'))
    runtime = application.app.execution.get_runtime()
    contracts, codec = module('blender_runtime.execution.contracts'), module('perceptual_grade_core.jobs.codec')
    prior = json.loads(Path(prior_report).read_text()) if prior_report else None
    data = dict(mode=mode, session=runtime.session.path.name, directory=str(runtime.session.path),
                recovered=runtime.session.recovered, pid=os.getpid())

    def report(**values):
        data.update(values)
        # os._exit and SIGKILL must not lose the evidence through buffered I/O.
        module('blender_runtime.execution.journal').durable_json(report_path, data)

    def helpers():
        return [dict(pid=helper.process.pid,
                     start=Path(f'/proc/{helper.process.pid}/stat').read_text().split()[21])
                for helper in runtime.helpers.values()]

    if mode == 'probe_lease':
        assert prior and Path(prior['directory']).is_dir()
        assert prior['session'] not in {entry[0] for entry in runtime.session.recovered}
        report(lease_preserved=True)
        addon.unregister()
        return
    if prior:
        assert (prior['session'], False) in runtime.session.recovered, runtime.session.recovered
        assert not Path(prior['directory']).exists()

    observations = []
    transfers = []
    resources = application.component('graph.output_resources')
    original_transfer = resources.transfer_payload
    def transfer(image, *args, **kwargs):
        transfers.append(image.name)
        return original_transfer(image, *args, **kwargs)
    resources.transfer_payload = transfer
    original_recover = lut.adopt_native
    recovery_depth = 0
    def observe(node, intent):
        nonlocal recovery_depth
        pending = bool(node.get(lut.INCOMPLETE))
        recovery_depth += 1
        try:
            result = original_recover(node, intent)
            accepted = lut.is_adopted(node)
        finally:
            recovery_depth -= 1
        if recovery_depth == 0:
            observations.append(dict(tree=node.id_data.bl_idname, wrapper=node.bl_idname,
                                     pending=pending, accepted=accepted))
        return result
    lut.adopt_native = observe
    if mode in ('seed', 'seed_payloads'):
        bpy.context.scene.world.use_nodes = True
        node = nodes.create_grade(bpy.context.scene.world.node_tree)
        nodes.write_chromatic(node, {'global_gain': .1})
        if mode == 'seed_payloads':
            compositor = bpy.data.node_groups.new('Crash recovery compositor', 'CompositorNodeTree')
            compositor.use_fake_user = True
            second = nodes.create_grade(compositor)
            nodes.write_chromatic(second, {'global_gain': .1})
        assert output.guarded_save(project) == {'FINISHED'}
        node = next(nodes.all_nodes())
    else:
        if mode == 'verify_payloads_autosave':
            assert bpy.ops.wm.recover_auto_save(filepath=project, use_scripts=False) == {'FINISHED'}
        else:
            assert bpy.ops.wm.open_mainfile(filepath=project) == {'FINISHED'}
        deadline = time.monotonic() + 30
        while nodes.recovery_pending():
            assert time.monotonic() < deadline, nodes.recovery_status()
            nodes.recovery_tick()
            time.sleep(.001)
        node = next(nodes.all_nodes())

    if mode in ('recover_pending', 'recover_valid'):
        expected_pending = mode == 'recover_pending'
        assert observations and all(item['accepted'] for item in observations), observations
        assert lut.is_adopted(node)
        expected_wrappers = {current.id_data.bl_idname:
            {'ShaderNodeTree': 'PGShaderGrade', 'CompositorNodeTree': 'PGCompositorGrade'}[
                current.id_data.bl_idname] for current in nodes.all_nodes()}
        assert {item['tree']: item['wrapper'] for item in observations
                if item['wrapper'] in expected_wrappers.values()} == expected_wrappers, observations
        assert {current.bl_idname for current in nodes.all_nodes()} == set(expected_wrappers.values())
        before = lut._graph_snapshot(node)
        lut.ensure(node, nodes.bake_model(node), force=True)
        assert lut._graph_snapshot(node) == before and not transfers
        if expected_pending:
            assert node.get(lut.INCOMPLETE), 'Adoption preserves the pending native marker'
            nodes.write_chromatic(node, {'global_gain': nodes.read_chromatic(node).global_gain + .01})
            lut.ensure(node, nodes.bake_model(node), force=True)
            lut.validate_output(node, nodes.bake_model(node), final=True)
            assert not node.get(lut.INCOMPLETE)
        assert output.guarded_save(project) == {'FINISHED'}
        report(pending_before=expected_pending, adopted=True, preserved_before_edit=True,
               rebuilt_after_edit=expected_pending, observed=observations)
        addon.unregister()
        assert runtime._shutdown_report.clean
        return

    if mode.startswith('fixture_'):
        # These are explicit persistence-fault fixtures, not a claim that native
        # autosave can run inside an in-progress Image.pixels.foreach_set.
        kind = mode.removeprefix('fixture_')
        assert kind in ('writing', 'edited', 'autosave'), kind
        damaged = []
        for current in tuple(nodes.all_nodes()):
            lut.ensure(current, nodes.bake_model(current), force=True)
            # Adoption preserves native selection without granting a producer
            # receipt. This fixture deliberately edits the selected native bank.
            image = resources.bank_images(current)[resources.selected_index(current)]
            values = np.empty(len(image.pixels), np.float32)
            image.pixels.foreach_get(values)
            original = values.copy()
            prefix = (values.size // 8) * 4
            values[:prefix].reshape(-1, 4)[:, :3] *= .5
            assert np.any(values[:prefix] != original[:prefix])
            assert np.array_equal(values[prefix:], original[prefix:])
            resources.validate_pixels(image, values)
            payload = json.loads(image[resources.RECORD])
            assert payload['phase'] == 'COMPLETE', payload
            image.pixels.foreach_set(values)
            image.update()
            if kind in ('writing', 'autosave'):
                payload['phase'] = 'WRITING'
            # The edited case retains producer history over externally changed pixels.
            image[resources.RECORD] = json.dumps(payload, sort_keys=True)
            if lut.INCOMPLETE in current:
                del current[lut.INCOMPLETE]
            # Packing only serializes this deliberately damaged fixture. No
            # production repair, exception, or save-pre callback creates it.
            image.pack()
            damaged.append(dict(tree=current.node_tree.bl_idname, phase=payload['phase'],
                                prefix=prefix, values=values.size,
                                before_digest=resources.pixel_digest(original),
                                actual_digest=resources.pixel_digest(values)))
        assert len(damaged) == 2, damaged
        destination = Path(report_path).parent / (mode + '.blend')
        save_pre_calls = []
        def saved(_): save_pre_calls.append(True)
        bpy.app.handlers.save_pre.append(saved)
        native_autosave = None
        if kind == 'autosave':
            temp_root = Path(os.environ['TMPDIR']).resolve()
            assert temp_root.is_relative_to(Path(report_path).parent.resolve())
            before = {p: p.stat().st_mtime_ns for p in temp_root.rglob('*.blend')}
            assert bpy.ops.wm.save_auto_save() == {'FINISHED'}
            candidates = [p for p in temp_root.rglob('*.blend')
                          if p not in before or p.stat().st_mtime_ns != before[p]]
            assert len(candidates) == 1, candidates
            native_autosave = str(candidates[0])
            shutil.copyfile(candidates[0], destination)
            assert not save_pre_calls, 'Native autosave unexpectedly invoked save_pre'
        else:
            handlers = {key: list(getattr(bpy.app.handlers, key))
                        for key in ('save_pre', 'save_post', 'save_post_fail')}
            try:
                for key in handlers: getattr(bpy.app.handlers, key).clear()
                assert bpy.ops.wm.save_as_mainfile(filepath=str(destination),
                    check_existing=False) == {'FINISHED'}
            finally:
                for key, values in handlers.items():
                    getattr(bpy.app.handlers, key).extend(values)
        bpy.app.handlers.save_pre.remove(saved)
        report(fixture=str(destination), damaged=damaged,
               native_autosave=native_autosave, save_pre_calls=len(save_pre_calls),
               fixture_kind='explicit persisted mixed-buffer state')
        addon.unregister()
        return

    if mode in ('verify_payloads_valid', 'verify_payloads_damaged', 'verify_payloads_autosave',
                'verify_payloads_render'):
        rebuild = mode == 'verify_payloads_render'
        current_nodes = tuple(nodes.all_nodes())
        assert len(current_nodes) == 2
        assert observations and all(item['accepted'] for item in observations), observations
        expected_wrappers = {'ShaderNodeTree': 'PGShaderGrade',
                             'CompositorNodeTree': 'PGCompositorGrade'}
        assert {item['tree']: item['wrapper'] for item in observations
                if item['wrapper'] in expected_wrappers.values()} == expected_wrappers, observations
        assert {current.bl_idname for current in current_nodes} == set(expected_wrappers.values())
        assert not transfers, 'Load adoption must not rewrite native payloads'
        validations = []
        for current in current_nodes:
            assert lut.is_adopted(current)
            state = resources.record(current.node_tree, current)['state']
            assert not state.graph_valid and not any(slot.valid for slot in state.slots)
            before = lut._graph_snapshot(current)
            pixels_before = {index: np.asarray(image.pixels[:], dtype=np.float32)
                             for index, image in resources.bank_images(current).items()}
            lut.ensure(current, nodes.bake_model(current), force=True)
            assert lut._graph_snapshot(current) == before
            for index, image in resources.bank_images(current).items():
                np.testing.assert_array_equal(np.asarray(image.pixels[:], dtype=np.float32), pixels_before[index])
            if not rebuild:
                continue
            nodes.write_chromatic(current, {'global_gain': nodes.read_chromatic(current).global_gain + .01})
            model = nodes.bake_model(current)
            lut.ensure(current, model, force=True)
            manifest = lut.validate_output(current, model, final=True)
            image = lut.image_for(current)
            pixels = np.asarray(image.pixels[:], dtype=np.float32)
            payload = json.loads(image[resources.RECORD])
            assert payload['phase'] == 'COMPLETE'
            rgba = pixels.reshape(-1, 4)[:65 ** 3]
            actual = (lut.cm.unpack_rgbe(rgba) if image.get('_pg_cube_encoding') == 'RGBE_DIFFERENCES'
                      else rgba[:, :3])
            indices = np.linspace(0, 65 ** 3 - 1, 19, dtype=int)
            expected = model.bake_native(lut.cm.lattice()[indices])
            scale = np.maximum(.001 * np.max(np.abs(expected), axis=-1), 1e-7)
            error = np.max(np.abs(actual[indices] - expected), axis=-1)
            assert np.all(error <= scale)
            validations.append(dict(tree=current.node_tree.bl_idname, signature=manifest['signature']))
        if rebuild:
            assert len(transfers) >= len(current_nodes), transfers
        else:
            assert not transfers, 'Unchanged adopted output must remain untouched'
        rendered = []
        if mode == 'verify_payloads_render':
            # Real native evaluation after explicit grading edits, using
            # only this disposable scene and temporary EXR readbacks.
            scene = bpy.context.scene
            for item in tuple(scene.objects):
                if item.type != 'CAMERA':
                    bpy.data.objects.remove(item, do_unlink=True)
            scene.render.engine = 'CYCLES'
            scene.cycles.device = 'CPU'
            scene.cycles.samples = 1
            scene.cycles.use_denoising = False
            scene.render.threads_mode = 'FIXED'
            scene.render.threads = 2
            scene.render.resolution_x = scene.render.resolution_y = 8
            scene.render.resolution_percentage = 100
            scene.render.image_settings.file_format = 'OPEN_EXR'
            scene.render.image_settings.color_mode = 'RGBA'
            scene.render.image_settings.color_depth = '32'
            scene.render.image_settings.color_management = 'OVERRIDE'
            scene.render.image_settings.linear_colorspace_settings.name = 'scene_linear'
            scene.render.compositor_device = 'CPU'
            probe = np.array((.12, .2, .31), dtype=np.float32)
            for kind in ('shader', 'compositor'):
                tree_type = 'ShaderNodeTree' if kind == 'shader' else 'CompositorNodeTree'
                current = next(item for item in current_nodes if item.node_tree.bl_idname == tree_type)
                current.inputs['Color'].default_value = (*probe, 1.)
                if kind == 'shader':
                    scene.compositing_node_group = None
                    current.id_data.links.new(current.outputs['Color'],
                                              current.id_data.nodes['Background'].inputs['Color'])
                else:
                    tree = current.id_data
                    tree.interface.new_socket(name='Image', in_out='OUTPUT', socket_type='NodeSocketColor')
                    target = tree.nodes.new('NodeGroupOutput')
                    target.is_active_output = True
                    source = tree.nodes.new('CompositorNodeImage')
                    probe_image = bpy.data.images.new('Recovery render probes', width=8, height=8,
                                                       float_buffer=True, alpha=True)
                    probe_image.colorspace_settings.name = 'Non-Color'
                    probe_image.alpha_mode = 'PREMUL'
                    values = np.tile(np.append(probe, np.float32(1.)), 64).astype(np.float32)
                    probe_image.pixels.foreach_set(values)
                    probe_image.update()
                    source.image = probe_image
                    tree.links.new(source.outputs['Image'], current.inputs['Color'])
                    tree.links.new(current.outputs['Color'], target.inputs['Image'])
                    scene.compositing_node_group = tree
                expected = nodes.bake_model(current).apply(probe.astype(float))
                assert output.guarded_render() == {'FINISHED'}
                render_path = Path(report_path).parent / ('recovered-' + kind + '.exr')
                bpy.data.images['Render Result'].save_render(str(render_path), scene=scene)
                readback = bpy.data.images.load(str(render_path), check_existing=False)
                try:
                    readback.colorspace_settings.name = 'Non-Color'
                    actual = np.asarray(readback.pixels[:]).reshape(-1, 4)
                    assert np.isfinite(actual).all()
                    np.testing.assert_allclose(actual[:, :3], np.tile(expected, (len(actual), 1)),
                                               rtol=.003, atol=5e-5)
                    np.testing.assert_allclose(actual[:, 3], 1., rtol=0, atol=1e-7)
                finally:
                    bpy.data.images.remove(readback)
                lut.validate_output(current, nodes.bake_model(current), final=True)
                rendered.append(kind)
        report(adopted=True, observed=observations, transfers=len(transfers),
               preserved_before_edit=True, rebuilt_after_edit=rebuild, validations=validations,
               native_autosave_recovery=mode == 'verify_payloads_autosave', rendered=rendered)
        addon.unregister()
        return

    if mode in ('work_bulk', 'work_gpu'):
        role = mode.removeprefix('work_')
        linear, tone, color, transforms = (module('perceptual_grade_core.model.' + part)
                                          for part in ('linear', 'tone', 'color', 'transforms'))
        model = transforms.Stack((transforms.Settings(
            linear.I3, tone.Parameters(input_midtones=45.),
            color.Parameters(global_gain=.25), linear.GradeSpace('D65')),))
        # Observe real progress from the installed numerical handler. Pausing
        # its process keeps the lease held across parent death deterministically.
        original_message = runtime._message
        def progress(helper, message):
            original_message(helper, message)
            if helper.role == role and message.get('kind') == 'progress' and 0 < message['value'] < 1:
                assert helper.active is not None and helper.process.poll() is None
                os.kill(helper.process.pid, signal.SIGSTOP)
                deadline = time.monotonic() + 10
                while Path(f'/proc/{helper.process.pid}/stat').read_text().split()[2] not in ('T', 't'):
                    assert time.monotonic() < deadline
                    time.sleep(.001)
                report(helpers=helpers(), role=role, progress=message['value'],
                       attempt=message['attempt'], helper_stopped=helper.process.pid)
                os.kill(os.getpid(), signal.SIGKILL)
        runtime._message = progress
        handle = runtime.submit(contracts.JobSpec('lut_bake', dict(
            model=codec.freeze_model(model), progressive=True, encoded=False, stack=False), lane=role))
        handle.result(timeout=120)
        raise AssertionError('No intermediate numerical progress was observed')

    if mode in ('publication', 'repair'):
        if mode == 'publication':
            nodes.write_chromatic(node, {'global_gain': .35})
        else:
            assert observations and all(item['accepted'] for item in observations)
            assert node.get(lut.INCOMPLETE)
            nodes.write_chromatic(node, {'global_gain': nodes.read_chromatic(node).global_gain + .01})
        original_restore = lut._restore_graph
        def checkpoint(phase):
            if phase == 'rows':
                raise RuntimeError('Interrupted graph commit before completed output selection')
        def failed_restore(*args):
            raise RuntimeError('Interrupted graph repair')
        lut._publication_checkpoint = checkpoint
        lut._restore_graph = failed_restore
        try:
            lut.ensure(node, nodes.bake_model(node), force=True)
        except RuntimeError as exc:
            assert 'Interrupted' in str(exc), str(exc)
        else:
            raise AssertionError('Publication checkpoint was not reached')
        finally:
            lut._restore_graph = original_restore
        assert node.get(lut.INCOMPLETE)
        controller = resources.record(node.node_tree, node)
        assert controller['state'].graph_debt and controller.get('repair_selection')
        assert not application.component('graph.output_guard').publishing()
        # Persist the interrupted current-generation publication. Restart adopts
        # its native state; another explicit grading edit starts new production.
        for image in resources.bank_images(node).values():
            record = resources.payload_record(image)
            if record and record.get('source') == lut.cm.signature(nodes.bake_model(node)):
                record['phase'] = 'WRITING'
                image[resources.RECORD] = json.dumps(record, sort_keys=True)
        pids = helpers()
        # Serialize after unwinding the write lease. The failed compensation
        # leaves a real pending/repair obligation, without reentrant save during
        # the payload callback. This models an interrupted recovery autosave.
        resources.pack_output(node)
        grades.prepare_save()
        assert any(item.get(lut.INCOMPLETE) for item in nodes.all_nodes())
        for key in ('save_pre', 'save_post', 'save_post_fail'):
            getattr(bpy.app.handlers, key).clear()
        assert bpy.ops.wm.save_as_mainfile(filepath=project, check_existing=False) == {'FINISHED'}
        report(helpers=pids, checkpoint='failed_graph_repair', pending_saved=True)
        os._exit(75 if mode == 'publication' else 76)

    if mode == 'shutdown':
        # Ensure shutdown has real child and payload resources to retire.
        inputs = dict(model=codec.freeze_model(nodes.bake_model(node)), progressive=True,
                      encoded=False, stack=False)
        result = runtime.submit(contracts.JobSpec('lut_bake', inputs, lane='bulk')).result(timeout=120)
        assert result['size'] == 65
        pids = helpers()
        del result
        def before_clean(clean):
            assert clean and runtime.fenced
            assert not runtime.helpers and not runtime.jobs and not runtime.payloads.owned
            assert not json.loads((runtime.session.path / 'journal.json').read_text())['clean']
            report(helpers=pids, checkpoint='before_clean_commit', retired=True)
            os._exit(77)
        runtime.session.close = before_clean
        addon.unregister()
        raise AssertionError('Shutdown checkpoint was not reached')

    assert mode in ('seed', 'seed_payloads'), mode
    assert lut.is_adopted(node)
    report(saved_native=True)
    addon.unregister()
    assert runtime._shutdown_report.clean


if __name__ == '__main__':
    main(*sys.argv[sys.argv.index('--') + 1:])
