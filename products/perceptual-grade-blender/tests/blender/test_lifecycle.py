"""Restricted registration, rollback, cleanup and Blender extension imports."""
from tests.support.session import component as _component, SessionTest, patch
import importlib.util
import json
import os
import subprocess
import shutil
import tempfile
import time
from pathlib import Path
import sys
from types import ModuleType
import unittest
pass
import bpy
import addon_utils
import _bpy_restrict_state as restricted
from color_tools import perceptual_grade_blender as addon
nodes = _component('graph.nodes'); spaces = _component('graph.spaces'); lut = _component('graph.lut'); stacks = _component('graph.stacks'); scheduler = _component('graph.scheduler'); editing = _component('graph.editing'); grades = _component('graph.grades')
panel = _component('ui.panel'); diagram = _component('ui.diagram'); warp_edit = _component('ui.warp_edit')
jobs = _component('scopes.jobs'); sampling = _component('scopes.sampling')
from tests.support.blender import sequence


class LifecycleTests(SessionTest):
    def finish_recovery(self):
        deadline=time.monotonic()+10
        while nodes.recovery_status()['state'] not in ('completed','failed','superseded'):
            self.assertLess(time.monotonic(),deadline,nodes.recovery_status())
            nodes.recovery_tick()
            time.sleep(.001)
        self.assertEqual(nodes.recovery_status()['state'],'completed',nodes.recovery_status())
        self.assertFalse(nodes.recovery_pending())

    def test_successful_disable_finishes_arena_receipts_before_actor_exit(self):
        from color_tools.perceptual_grade_blender.integration import lifecycle
        addon.register()
        app=self.session.app
        ref=app.ownership.retain(bpy.context.scene,'terminal.cleanup.fixture')
        arena=app.ownership.snapshots()[0]
        with self.assertNoLogs(lifecycle.LOG,level='ERROR'):
            addon.unregister()
        self.assertTrue(app.closed)
        self.assertFalse(app.actors.thread.is_alive())
        self.assertEqual(arena.physical_counts(),(0,0))
        self.assertIsNone(app.ownership.resolve(ref))

    def test_cancelled_lut_interest_keeps_actor_host_until_physical_retirement(self):
        from color_tools.perceptual_grade_blender.integration import lifecycle
        addon.register()
        app=self.session.app
        class PendingPhysicalWork:
            physical=False
            def done(self):return True
            def retired(self):return self.physical
            def cancel(self):return True
        pending=PendingPhysicalWork()
        self.addCleanup(setattr,pending,'physical',True)
        ticket=scheduler.scope_bake_request('retirement.fixture')
        self.assertTrue(scheduler.scope_start(ticket))
        lut._retired.add(pending)
        lut._retirements[ticket]=(pending,)
        lut.clear()
        self.assertIn(ticket,lut._retirements)
        self.assertFalse(lut.collect_retired())
        with self.assertLogs(lifecycle.LOG,level='ERROR'):
            addon.unregister()
        self.assertFalse(app.closed)
        self.assertTrue(app.actors.thread.is_alive())
        pending.physical=True
        self.assertTrue(self.session.close())
        self.assertTrue(app.closed)
        self.assertFalse(lut._retired)
        self.assertFalse(lut._retirements)

    def test_module_ownership_requires_this_private_component_namespace(self):
        from color_tools.perceptual_grade_blender.integration import lifecycle
        own = nodes.__name__
        suffix = '.graph.nodes'
        self.assertTrue(lifecycle.owned_module(own))
        self.assertTrue(lifecycle.owned(nodes.PGLinearSettings))
        for foreign in ('unrelated' + suffix, 'peer._vendor.perceptual_grade_blender' + suffix,
                        'peer.perceptual_grade_blender' + suffix,
                        'prefix.' + own, own + '.nested', lifecycle.PACKAGE + '.services'):
            self.assertFalse(lifecycle.owned_module(foreign), foreign)

    def test_disable_waits_for_unrelated_native_readers_before_packing(self):
        output_guard = _component('graph.output_guard')
        from color_tools.perceptual_grade_blender.integration import lifecycle
        addon.register()
        with patch.object(output_guard, 'available', return_value=False), \
                patch.object(grades, 'prepare_disable') as prepare:
            self.assertFalse(lifecycle.cleanup())
            self.assertTrue(nodes._registered)
            self.assertEqual(_component('integration.lifecycle').finish_native_cleanup(), .05)
            prepare.assert_not_called()
        _component('integration.lifecycle').finish_native_cleanup()
        self.assert_clean()

    def test_disable_packs_existing_banks_without_calculating_new_output(self):
        output_guard = _component('graph.output_guard'); output_resources = _component('graph.output_resources')
        addon.register()
        tree = bpy.data.node_groups.new('Disable preserved output', 'CompositorNodeTree')
        node = nodes.create_grade(tree)
        nodes.write_chromatic(node, {'global_gain': .25})
        lut.ensure(node, nodes.bake_model(node))
        name = node.name
        identities = {image.as_pointer() for image in output_resources.bank_images(node).values()}
        self.assertTrue(all(image.packed_file is not None and not image.is_dirty
                            for image in output_resources.bank_images(node).values()))
        # Simulate readable unfinished work on an inactive bank. Normal writes
        # already pack themselves; disable remains a scoped persistence backstop.
        index = next(index for index in range(4) if index != output_resources.selected_index(node))
        image = output_resources.bank_images(node)[index]
        with output_guard.publication():
            image.pixels[0] = .125
            image.update()
        before = output_resources.pixel_digest(output_resources.read_pixels(image))
        self.assertTrue(image.is_dirty)
        del image
        del node
        with patch.object(lut, 'ensure', side_effect=AssertionError('Disable computed new output')), \
                patch.object(output_resources, 'transfer_payload', side_effect=AssertionError('Disable rewrote output')):
            addon.unregister()
        self.assertEqual(tree.nodes[name].bl_idname, 'CompositorNodeGroup')
        self.assertEqual({image.as_pointer() for image in output_resources.bank_images(tree.nodes[name]).values()}, identities)
        self.assertTrue(output_resources.bank_images(tree.nodes[name])[index].is_dirty)
        image = output_resources.bank_images(tree.nodes[name])[index]
        self.assertEqual(output_resources.pixel_digest(output_resources.read_pixels(image)), before)

    def test_disable_drains_capture_files_only_after_runtime_retirement(self):
        addon.register()
        runtime = _component('services').get_runtime()
        capture = _component('scopes.capture')
        with tempfile.TemporaryDirectory(prefix='pg-disable-capture-') as temporary:
            directory = Path(temporary) / 'bake-retiring'
            directory.mkdir()
            (directory / 'scene.blend').write_bytes(b'leased native helper input')

            class RetiringHandle:
                def retired(self):
                    return runtime.physical_terminal()

            capture.bake_retiring.append(dict(handle=RetiringHandle(), directory=directory))
            shutdown = runtime.shutdown
            def retire(*args, **kwargs):
                if not runtime.closed:
                    self.assertTrue(directory.exists(), 'Live helper input was deleted early')
                return shutdown(*args, **kwargs)
            with patch.object(runtime, 'shutdown', side_effect=retire):
                addon.unregister()
            self.assertTrue(runtime.physical_terminal())
            self.assertFalse(directory.exists(), 'Retired capture input survived disable')
            self.assertFalse(capture.bake_retiring)
        self.assert_clean()

    def test_duplicate_legacy_keymap_receipts_are_consumed_before_removal(self):
        from color_tools.perceptual_grade_blender.integration import lifecycle
        config=bpy.context.window_manager.keyconfigs.addon
        self.assertIsNotNone(config)
        keymap=config.keymaps.new(name='Perceptual Grade retirement fixture',space_type='NODE_EDITOR')
        item=keymap.keymap_items.new('perceptual_grade.diagram_drag','LEFTMOUSE','PRESS')
        # Native collection lookup may create a second Python wrapper for the
        # same item; scalar native identities must drive deduplication.
        candidates=[(keymap,item),(keymap,keymap.keymap_items[0]),(keymap,item)]
        removed=[]
        real_remove=_component('integration.lifecycle').remove_keymap_item
        def remove(owner,target):
            self.assertFalse(candidates)
            removed.append((int(owner.as_pointer()),int(target.as_pointer())))
            real_remove(owner,target)
        try:
            with patch.object(_component('integration.lifecycle'),'remove_keymap_item',side_effect=remove):
                _component('integration.lifecycle')._remove_keymap_items(candidates)
            self.assertEqual(len(removed),1)
            self.assertEqual(len(keymap.keymap_items),0)
        finally:
            config.keymaps.remove(keymap)

    def tearDown(self):
        if nodes._registered:
            addon.unregister()
        bpy.ops.wm.read_factory_settings(use_empty=True)

    def assert_clean(self):
        self.assertFalse(hasattr(bpy.types.Node, 'pg_linear'))
        self.assertFalse(nodes._registered or nodes._class_registered)
        self.assertFalse(bpy.app.timers.is_registered(nodes.poll_working_space))
        self.assertFalse(panel._classes or panel._keymaps or panel._menu_registered)
        self.assertFalse(bpy.app.timers.is_registered(jobs.linear_tick))
        self.assertFalse(bpy.app.timers.is_registered(jobs.probe_tick))
        self.assertFalse(jobs._consumers)
        self.assertFalse(jobs._linear_states or jobs._linear_pending or jobs._linear_sources)
        self.assertIsNone(jobs._linear_running)
        pass
        runtime = _component('services').current_runtime()
        self.assertTrue(runtime is None or runtime.closed)
        if runtime is not None:self.assertFalse(runtime.helpers)
        self.assertFalse(scheduler._timers or scheduler._records or scheduler._gestures)
        self.assertFalse(scheduler._updates or scheduler._frames or scheduler._frame_signals)
        for event in ('depsgraph_update_pre', 'depsgraph_update_post', 'frame_change_pre', 'frame_change_post', 'render_pre', 'load_post', 'undo_post', 'redo_post',
                      'composite_pre','composite_post','composite_cancel', 'load_pre', 'undo_pre', 'redo_pre'):
            self.assertFalse(any(getattr(fn, '__module__', '').startswith(addon.__name__ + '.') for fn in getattr(bpy.app.handlers, event)))

    def test_restricted_enable_disable_and_reenable(self):
        real_register = nodes.register
        errors = []
        def observe():
            self.assertEqual(type(bpy.data).__name__, '_RestrictData')
            with patch.object(nodes, 'refresh_all', side_effect=AssertionError('Early data scan')):
                real_register()
        with patch.object(restricted, '_bpy', bpy):
            with patch.object(nodes, 'register', observe):
                result = addon_utils.enable(addon.__name__, default_set=False, handle_error=lambda exc: errors.append(str(exc)))
            self.assertIs(result, addon)
            self.assertFalse(errors)
            with restricted.RestrictBlend():
                self.assertEqual(nodes.poll_working_space(), .1)
            tree = bpy.data.node_groups.new('Lifecycle', 'CompositorNodeTree')
            node = nodes.create_grade(tree)
            node.pg_linear.exposure = 1
            self.assertEqual(tuple(nodes.linear_matrix(node)[0]),(2,0,0))
            name = node.name
            socket=spaces.LUT_INPUT_ROWS[0]
            expected=spaces.read_rows(node)[0]
            addon_utils.disable(addon.__name__, default_set=False)
            self.assert_clean()
            spaces.write_rows(tree.nodes[name],((0,0,0),*spaces.read_rows(tree.nodes[name])[1:]))
            with restricted.RestrictBlend():
                addon.register()
                self.assertEqual(spaces.read_rows(tree.nodes[name])[0],(0,0,0))
            nodes.poll_working_space();self.finish_recovery()
            self.assertEqual(spaces.read_rows(tree.nodes[name])[0],(0,0,0))
            self.assertTrue(lut.is_adopted(tree.nodes[name]))
            addon.unregister()
            self.assert_clean()

    def test_registration_failures_roll_back_and_retry(self):
        for target, method in ((bpy.app.timers, 'register'), (diagram, 'register')):
            if self.session.closed:
                self.prepare_session()
            with self.subTest(method=method, target=target):
                with patch.object(restricted, '_bpy', bpy), patch.object(target, method, side_effect=RuntimeError('Injected registration failure')):
                    with self.assertRaisesRegex(RuntimeError, 'Injected registration failure'):
                        with restricted.RestrictBlend():
                            addon.register()
                self.assert_clean()
                addon.register()
                self.assertTrue(nodes._registered)
                addon.unregister()
                self.assert_clean()

    def test_cleanup_reclaims_retained_and_reloaded_timer_registries(self):
        addon.register()
        def before_reload():return None
        def after_reload():return None
        scheduler.wake(before_reload,60.)
        before_native=scheduler.timer_callback(before_reload)
        previous=scheduler._timers
        # Explicit replacement of a test seam must not lose previously owned
        # callbacks; the Session retains both exact timer registries.
        with patch.object(scheduler,'_timers',set()):
            scheduler.wake(after_reload,60.)
            after_native=scheduler.timer_callback(after_reload)
            addon.unregister()
            self.assert_clean()
        self.assertFalse(previous)
        self.assertFalse(bpy.app.timers.is_registered(before_native))
        self.assertFalse(bpy.app.timers.is_registered(after_native))

    def test_deferred_native_cleanup_retains_actual_timers_across_reload(self):
        output = _component('graph.output')
        from color_tools.perceptual_grade_blender.integration import lifecycle
        pass
        addon.register()
        runtime = _component('services').get_runtime()
        operation = output.Operation('render', bpy.context.scene)
        self.addCleanup(output.clear)
        with patch.object(output, 'prepare_render', return_value=()), \
                patch.object(output, 'snapshot', return_value=()):
            operation.prepare()
            operation.invoke(lambda: {'RUNNING_MODAL'})
        with patch.object(output, 'native_running', return_value=True):
            self.assertFalse(lifecycle.cleanup())
            previous = _component('integration.lifecycle').finish_native_cleanup
            registry = _component('integration.lifecycle')._cleanup_timers
            self.assertTrue(bpy.app.timers.is_registered(previous))
            self.assertIn(previous, registry)
            self.assertTrue(runtime.fenced and runtime.cleanup_blocked)
            self.assertFalse(runtime.closed)
            self.assertTrue(nodes._registered)
            self.assertFalse(json.loads((runtime.session.path / 'journal.json').read_text())['clean'])
            importlib.reload(lifecycle)
            self.assertIs(_component('integration.lifecycle')._cleanup_timers, registry)
            self.assertIs(previous, _component('integration.lifecycle').finish_native_cleanup)
            self.assertFalse(lifecycle.cleanup())
            current = _component('integration.lifecycle').finish_native_cleanup
            self.assertEqual(registry, {previous})
            self.assertTrue(bpy.app.timers.is_registered(current))
            self.assertEqual(previous(), .05)
            self.assertFalse(runtime.closed)
        # Reload retains the original Session and its one actual timer.
        # That callback resumes cleanup after the native reader releases RNA.
        self.assertIsNone(previous())
        self.assertFalse(bpy.app.timers.is_registered(previous))
        self.assertFalse(bpy.app.timers.is_registered(current))
        self.assertFalse(registry or _component('integration.lifecycle')._cleanup_pending or output.busy())
        self.assertTrue(runtime.closed and runtime._shutdown_report.clean)
        self.assertFalse(bpy.context.scene.render.use_lock_interface)
        self.assert_clean()

    def test_foreground_cleanup_failure_keeps_session_journal_unclean(self):
        pass
        from color_tools.perceptual_grade_blender.integration import lifecycle
        real_resource = bpy.utils.user_resource
        with tempfile.TemporaryDirectory() as directory:
            def resource(kind, *, path='', create=False):
                if kind == 'CONFIG' and path == 'perceptual_grade/execution':
                    return directory
                return real_resource(kind, path=path, create=create)
            with patch.object(bpy.utils, 'user_resource', side_effect=resource):
                addon.register()
                runtime = _component('services').get_runtime()
                journal = runtime.session.path / 'journal.json'
                session = runtime.session.path.name
                timer = scheduler.timer_callback(nodes.poll_working_space)
                real_unregister = bpy.app.timers.unregister
                def fail_owned_timer(callback):
                    if callback is timer:
                        raise RuntimeError('Injected foreground timer cleanup failure')
                    return real_unregister(callback)
                with self.assertLogs(lifecycle.LOG, level='ERROR'), \
                        patch.object(bpy.app.timers, 'unregister', side_effect=fail_owned_timer):
                    addon.unregister()
                try:
                    self.assertTrue(runtime.closed)
                    self.assertFalse(runtime._shutdown_report.clean)
                    self.assertTrue(runtime.cleanup_blocked)
                    self.assertFalse(json.loads(journal.read_text())['clean'])
                    self.assertTrue(bpy.app.timers.is_registered(timer))
                finally:
                    if bpy.app.timers.is_registered(timer):
                        real_unregister(timer)
                # A later startup observes an abandoned unclean session. Its
                # own successful cleanup can then produce a clean receipt.
                addon.register()
                fresh = _component('services').get_runtime()
                self.assertIn((session, False), fresh.session.recovered)
                self.assertNotEqual(fresh.session.identity, runtime.session.identity)
                addon.unregister()
                self.assertTrue(fresh._shutdown_report.clean)
                self.assert_clean()

    def test_native_deletion_invalidates_policy_and_drag_lifetimes(self):
        addon.register()
        tree=bpy.data.node_groups.new('Deleted scheduler owner','CompositorNodeTree')
        grade=nodes.create_grade(tree)
        stack=sequence(tree,[grades.ensure(grade)])
        target=editing.Target(stack,stack.pg_stack_entries[0])
        for node in (grade,target):
            with self.subTest(kind='target' if editing.is_target(node) else 'grade'):
                owner=scheduler.output(node)
                spec=sampling.describe(node,nodes.grading_space(node))
                ticket=scheduler.scope_request(node,'full',spec)
                token=scheduler.begin(node)
                self.assertTrue(scheduler.scope_start(ticket))
                pointer=owner.as_pointer()
                pass
                scheduler._updates[pointer]=(_component('ownership').retain(owner, "fixture.update"),False)
                tree.nodes.remove(owner)
                self.assertNotIn(ticket.channel,scheduler._records)
                self.assertNotIn(token,scheduler._gestures)
                self.assertNotIn(pointer,scheduler._updates)
                scheduler.scope_complete(ticket)
                self.assertFalse(scheduler.scope_publish(ticket))
                scheduler.end(token)

    def test_refresh_prunes_removed_stack_entry_without_reusing_its_lifetime(self):
        addon.register()
        tree=bpy.data.node_groups.new('Deleted scheduler target','CompositorNodeTree')
        grade=nodes.create_grade(tree)
        stack=sequence(tree,[grades.ensure(grade)])
        target=editing.Target(stack,stack.pg_stack_entries[0])
        ticket=scheduler.scope_request(target,'full',sampling.describe(target,nodes.grading_space(target)))
        token=scheduler.begin(target)
        stack.pg_stack_entries.remove(0)
        nodes.refresh_all()
        self.assertNotIn(ticket.channel,scheduler._records)
        self.assertNotIn(token,scheduler._gestures)
        self.assertFalse(scheduler.scope_publish(ticket))
        fresh=scheduler.lut_request(stack,nodes.bake_model(stack))
        self.assertNotEqual(fresh.owner,ticket.owner)
        scheduler.end(token)

    def test_shared_helpers_exist_before_first_preview_and_final_publication(self):
        addon.register()
        first=None
        for tree_type in ('CompositorNodeTree','ShaderNodeTree'):
            with self.subTest(tree_type=tree_type):
                tree=bpy.data.node_groups.new('Prepared helpers',tree_type)
                node=nodes.create_grade(tree)
                helpers={size:next(g for g in bpy.data.node_groups if g.bl_idname==tree_type
                    and g.get('_pg_cube_op')==f'{lut.SCHEMA}:Address:{size}') for size in (33,65)}
                bindings={item.as_pointer():item.node_tree.as_pointer() for item in node.node_tree.nodes
                          if item.get('_pg_cube_address')}
                with patch.object(lut.Graph,'coordinates',side_effect=AssertionError('Late helper construction')):
                    nodes.create_grade(tree);stacks.create(tree)
                    nodes.write_chromatic(node,{'global_gain':.1})
                    if first is not None:
                        # The final cube from the Compositor can be reused, but
                        # its four-plane prepared image cannot serve a Shader.
                        lut.ensure(node,nodes.bake_model(node))
                        self.assertEqual(lut.image_for(node)['_pg_cube_encoding'],'RGB')
                        nodes.write_chromatic(node,{'global_gain':.2})
                    baker=lut._states[node.as_pointer()]['baker'];baker.finish()
                    for preview,size in ((True,33),(False,65)):
                        self.assertTrue(lut.publish(node,baker,force=True,preview=preview))
                        self.assertEqual(bindings,{item.as_pointer():item.node_tree.as_pointer()
                            for item in node.node_tree.nodes if item.get('_pg_cube_address')})
                        self.assertEqual({item.node_tree.as_pointer() for item in node.node_tree.nodes
                            if item.get('_pg_cube_address')},{helper.as_pointer() for helper in helpers.values()})
                    if first is None:first=node
                    else:
                        nodes.write_chromatic(first,{'global_gain':.2})
                        self.assertEqual(lut.image_for(first)['_pg_cube_encoding'],'RGBE_DIFFERENCES')
                for size,helper in helpers.items():
                    self.assertEqual([g for g in bpy.data.node_groups if g.bl_idname==tree_type
                        and g.get('_pg_cube_op')==f'{lut.SCHEMA}:Address:{size}'],[helper])

    def test_missing_preview_helpers_reject_edits_without_rebuilding(self):
        addon.register()
        tree=bpy.data.node_groups.new('Incomplete helpers','CompositorNodeTree')
        node=nodes.create_grade(tree)
        kernel=node.node_tree
        tag=f'{lut.SCHEMA}:Address:33'
        bpy.data.node_groups.remove(next(g for g in bpy.data.node_groups if g.get('_pg_cube_op')==tag))
        nodes.reset_cache_handler();self.finish_recovery()
        self.assertFalse(any(g.get('_pg_cube_op')==tag for g in bpy.data.node_groups))
        self.assertEqual(nodes.resource_action(node),'invalid')
        with self.assertRaisesRegex(ValueError,'Unsupported or incomplete'):
            nodes.prepare_output_resources(node)
        self.assertEqual(node.node_tree,kernel)
        self.assertFalse(nodes.resources_ready(node))
        self.assertFalse(any(g.get('_pg_cube_op')==tag for g in bpy.data.node_groups))

    def test_cleanup_continues_after_independent_adapter_failure(self):
        addon.register()
        with patch.object(diagram, 'cleanup_hover_cursors', side_effect=RuntimeError('Injected cleanup failure')):
            addon.unregister()
        self.assert_clean()
        addon.register()
        self.assertTrue(nodes._registered)

    def test_failed_cleanup_debt_scan_still_retires_old_controllers(self):
        ownership = _component('ownership')
        transactions = _component('ownership.transactions')
        from color_tools.perceptual_grade_blender.integration import lifecycle
        pass
        addon.register()
        retired = ownership.snapshots()
        ref = ownership.retain(bpy.context.scene, 'cleanup.failure.fixture')
        runtime = _component('services').get_runtime()
        try:
            with patch.object(transactions, 'pending', side_effect=RuntimeError('Injected debt scan failure')):
                with self.assertRaisesRegex(RuntimeError, 'Injected debt scan failure'):
                    lifecycle.cleanup()
            self.assertIsNone(ownership.resolve(ref))
            for arena in retired:
                self.assertEqual(arena.physical_counts(), (0, 0))
                with self.assertRaisesRegex(RuntimeError, 'rejected'):
                    arena.retain(bpy.context.scene, 'old.module.callback')
            self.assertFalse(runtime.closed)
            self.assertFalse(json.loads((runtime.session.path / 'journal.json').read_text())['clean'])
        finally:
            lifecycle.cleanup()
        self.assert_clean()
        addon.register()
        self.assertTrue(ownership.admits('discover'))

    def test_recovery_clears_busy_flags_and_fences_sidebar_callbacks(self):
        addon.register()
        tree = bpy.data.node_groups.new('Recover sidebar', 'CompositorNodeTree')
        node = nodes.create_grade(tree)
        edit = warp_edit.begin(node)
        warp_edit.edit_sidebar(node, 'web_chroma_1_0', .2)
        before = scheduler.session()
        grades._saving = grades._converting = True
        grades._busy.add(node.as_pointer())
        nodes._updating.add(node.as_pointer())
        nodes.suspend_handler()
        self.assertNotEqual(scheduler.session(), before)
        self.assertFalse(grades._saving or grades._converting or grades._busy or nodes._updating)
        self.assertFalse(warp_edit._edits or warp_edit._pending)
        nodes.write_chromatic(node, {'web_chroma_1_0': .5})
        warp_edit.defer_finish(edit, False)
        warp_edit.flush()
        self.assertAlmostEqual(nodes.read_chromatic(node).web_chroma_1_0, .5)
        # Recovery is valid repeatedly, regardless of the old transient phase.
        nodes.reset_cache_handler()
        nodes.reset_cache_handler()
        self.assertAlmostEqual(nodes.read_chromatic(node).web_chroma_1_0, .5)

    def test_undo_pre_clears_old_rna_and_fences_automatic_callbacks(self):
        addon.register()
        tree = bpy.data.node_groups.new('Synchronous undo', 'CompositorNodeTree')
        node = nodes.create_grade(tree)
        warp_edit.begin(node)
        warp_edit.edit_sidebar(node, 'web_chroma_1_0', .2)
        ticket = scheduler.scope_request(node, 'full', sampling.describe(node, nodes.grading_space(node)))
        scheduler.begin(node)
        before = scheduler.session()
        generation = sampling._generation
        with patch.object(nodes, 'all_nodes', side_effect=AssertionError('pre handler scanned RNA')):
            nodes.undo_redo_pre_handler()
        self.assertTrue(nodes.recovery_pending())
        self.assertEqual(scheduler._lifecycle_store.state.phase, 3)
        self.assertNotEqual(scheduler.session(), before)
        self.assertGreater(sampling._generation, generation)
        self.assertFalse(warp_edit._edits or warp_edit._pending)
        self.assertFalse(lut._states or nodes._signatures)
        self.assertFalse(scheduler._gestures or scheduler._records)
        self.assertFalse(scheduler.scope_publish(ticket))
        with patch.object(grades, 'representations', side_effect=AssertionError('refresh scanned RNA')), \
             patch.object(jobs, '_sync_consumers', side_effect=AssertionError('scope discovery ran')), \
             patch.object(nodes, 'all_nodes', side_effect=AssertionError('callback scanned RNA')):
            self.assertIsNone(nodes.refresh_all(force=True))
            self.assertEqual(nodes.poll_working_space(), .1)
            self.assertIsNone(nodes.active_grade(object()))
            self.assertEqual(diagram.scope_consumers(), {})
            self.assertIsNone(diagram.ensure_routers())
            self.assertIsNone(jobs.refresh_visible())
            self.assertIsNone(jobs.request(object(), object(), ui=True))
            self.assertIsNone(jobs.request_linear(object(), object(), ui=True))
            self.assertIsNone(jobs.tick())
            self.assertIsNone(jobs.linear_tick())
            self.assertIsNone(jobs.probe_tick())
            self.assertIsNone(nodes.changed(object(), object()))
            self.assertIsNone(nodes.refresh_node(object()))
            self.assertIsNone(nodes.render_end_handler())
            self.assertIsNone(nodes.scope_render_handler(object()))
        # Complete the simulated native boundary before unregister packs output.
        # All pre-handler fence assertions above run before this recovery.
        nodes.reset_cache_handler()
        self.finish_recovery()
        self.assertFalse(nodes.recovery_pending())

    def test_post_adopts_saved_output_without_rewriting_or_certifying_it(self):
        addon.register()
        tree=bpy.data.node_groups.new('Restored outputs','CompositorNodeTree')
        good=nodes.create_grade(tree)
        lut.ensure(good,nodes.bake_model(good),force=True)
        image=lut.image_for(good)
        bad=nodes.create_grade(tree)
        nodes.write_chromatic(bad,{'global_gain':.25})
        bad[lut.INCOMPLETE]=True
        interrupted=nodes.create_grade(tree)
        lut.ensure(interrupted,nodes.bake_model(interrupted),force=True)
        interrupted[lut.INCOMPLETE]=True
        resources=_component('graph.output_resources')
        before=tuple(lut._graph_snapshot(node) for node in (good,bad,interrupted))
        with patch.object(lut,'ensure',side_effect=AssertionError('Recovery baked output')), \
             patch.object(lut,'validate_output',side_effect=AssertionError('Recovery certified output')), \
             patch.object(resources,'read_pixels',side_effect=AssertionError('Recovery read pixels')), \
             patch.object(resources,'pixel_digest',side_effect=AssertionError('Recovery hashed pixels')), \
             patch.object(nodes,'refresh_all',side_effect=AssertionError('Recovery refreshed native output')):
            nodes.undo_redo_pre_handler()
            nodes.reset_cache_handler()
            self.assertTrue(nodes.recovery_pending())
            self.finish_recovery()
        self.assertEqual(before,tuple(lut._graph_snapshot(node) for node in (good,bad,interrupted)))
        self.assertIn(image,resources.bank_images(good).values())
        for node in (good,bad,interrupted):
            self.assertTrue(lut.is_adopted(node))
            self.assertNotIn(node.as_pointer(),lut._states)
            state=resources.record(node.node_tree,node)['state']
            self.assertFalse(state.graph_valid)
            self.assertFalse(any(slot.valid for slot in state.slots))
        self.assertTrue(bad.get(lut.INCOMPLETE))
        self.assertTrue(interrupted.get(lut.INCOMPLETE))

    def test_pre_handler_fences_before_cancellation_and_cleanup_failure_stays_dirty(self):
        addon.register()
        def failed_cleanup():
            self.assertTrue(nodes.recovery_pending())
            self.assertFalse(scheduler.lifecycle_admits('publish'))
            raise RuntimeError('Old RNA cleanup failed')
        with patch.object(diagram,'cleanup_drag_timers',side_effect=failed_cleanup), \
             self.assertLogs(nodes.LOG,level='ERROR'):
            nodes.undo_redo_pre_handler()
        self.assertEqual(scheduler._lifecycle_store.state.phase,4)
        self.assertTrue(scheduler._lifecycle_store.state.dirty)
        self.assertEqual(nodes.recovery_status()['state'],'failed')
        nodes.reset_cache_handler()
        self.finish_recovery()

    def test_recovery_failure_keeps_callbacks_fenced_until_successful_retry(self):
        addon.register()
        tree=bpy.data.node_groups.new('Interrupted recovery','CompositorNodeTree')
        node=nodes.create_grade(tree)
        nodes.undo_redo_pre_handler();nodes.reset_cache_handler()
        with patch.object(lut,'adopt_native',side_effect=RuntimeError('Invalid RNA read')), \
             self.assertLogs(nodes.LOG,level='ERROR'):
            for _ in range(10):
                nodes.recovery_tick()
                if nodes.recovery_status()['state']=='failed':break
        self.assertEqual(nodes.recovery_status()['state'],'failed')
        self.assertEqual(scheduler._lifecycle_store.state.phase,4)
        self.assertTrue(nodes.recovery_pending())
        with patch.object(nodes,'all_nodes',side_effect=AssertionError('Failed recovery discovered RNA')):
            nodes.refresh_all();nodes.poll_working_space()
        self.assertTrue(nodes.retry_recovery())
        self.finish_recovery()
        self.assertTrue(lut.is_adopted(node))

    def test_direct_node_and_sidebar_draws_respect_recovery_and_failure_fences(self):
        addon.register()
        class ForbiddenRNA:
            def __getattribute__(self, name):
                raise AssertionError('RNA or layout accessed: ' + name)
            def __setattr__(self, name, value):
                raise AssertionError('RNA or layout accessed: ' + name)
        sentinel = ForbiddenRNA()
        draws = (
            lambda: grades.GradeNode.draw_buttons(sentinel, sentinel, sentinel),
            lambda: grades.GradeNode.draw_buttons_ext(sentinel, sentinel, sentinel),
            lambda: stacks.StackNode.draw_buttons(sentinel, sentinel, sentinel),
            lambda: stacks.StackNode.draw_buttons_ext(sentinel, sentinel, sentinel),
        )
        for event in ('recover', 'fail'):
            scheduler.lifecycle_event(event)
            for draw in draws:
                self.assertIsNone(draw())
        scheduler.lifecycle_event('recover')
        scheduler.lifecycle_event('recovered')
        # The same entry points resume their normal layout/RNA work only once
        # the lifecycle has accepted the successful recovery receipt.
        for draw in draws:
            with self.assertRaisesRegex(AssertionError, 'RNA or layout accessed'):
                draw()

    def test_grade_and_stack_callbacks_do_not_discover_rna_during_recovery(self):
        addon.register()
        class ForbiddenRNA:
            def __getattribute__(self, name):
                raise AssertionError('Callback accessed RNA: ' + name)
        sentinel = ForbiddenRNA()
        callbacks = (
            lambda: stacks.changed(sentinel, sentinel),
            lambda: stacks.focus_changed(sentinel, sentinel),
            lambda: stacks.publish(sentinel),
            lambda: stacks.refresh(sentinel),
            lambda: grades.changed(sentinel),
            lambda: grades.selection_changed(sentinel, sentinel),
            lambda: grades.publish(sentinel),
            lambda: nodes.tone_callback('input_black')(sentinel, sentinel),
        )
        with patch.object(nodes, 'all_nodes', side_effect=AssertionError('Callback accessed RNA: discovery')):
            for event in ('recover', 'fail'):
                scheduler.lifecycle_event(event)
                for callback in callbacks:
                    self.assertIsNone(callback())
            scheduler.lifecycle_event('recover')
            scheduler.lifecycle_event('recovered')
            for callback in callbacks:
                with self.assertRaisesRegex(AssertionError, 'Callback accessed RNA'):
                    callback()

    def test_recovery_adopts_stacks_without_refresh_or_certification(self):
        addon.register()
        tree=bpy.data.node_groups.new('Restored Stacks','CompositorNodeTree')
        source=nodes.create_grade(tree)
        nodes.write_values(source,{'exposure':.25})
        good=sequence(tree,[source.pg_grade]);interrupted=sequence(tree,[source.pg_grade])
        lut.ensure(good,nodes.bake_model(good),force=True)
        lut.ensure(interrupted,nodes.bake_model(interrupted),force=True)
        interrupted[lut.INCOMPLETE]=True
        before=tuple(lut._graph_snapshot(node) for node in (good,interrupted))
        with patch.object(stacks,'refresh',side_effect=AssertionError('Recovery refreshed Stack')), \
             patch.object(lut,'ensure',side_effect=AssertionError('Recovery baked Stack')):
            nodes.undo_redo_pre_handler();nodes.reset_cache_handler();self.finish_recovery()
        self.assertEqual(before,tuple(lut._graph_snapshot(node) for node in (good,interrupted)))
        self.assertTrue(lut.is_adopted(good) and lut.is_adopted(interrupted))
        self.assertTrue(interrupted.get(lut.INCOMPLETE))
        self.assertFalse(lut._states)

    def test_load_undo_redo_register_the_same_bounded_recovery(self):
        addon.register()
        for name in ('load_pre','undo_pre','redo_pre'):
            self.assertIn(self.session._handler_boundaries[(name,nodes.undo_redo_pre_handler)],
                          getattr(bpy.app.handlers,name))
        for name in ('load_post','undo_post','redo_post'):
            self.assertIn(self.session._handler_boundaries[(name,nodes.reset_cache_handler)],
                          getattr(bpy.app.handlers,name))
        nodes.undo_redo_pre_handler()
        with patch.object(nodes,'refresh_all',side_effect=AssertionError('Native post refreshed output')):
            nodes.reset_cache_handler()
            self.assertTrue(nodes.recovery_pending())
            self.finish_recovery()

    def test_save_after_undo_preserves_adopted_output_through_portable_conversion(self):
        addon.register()
        tree=bpy.data.node_groups.new('Save after undo','CompositorNodeTree')
        node=nodes.create_grade(tree)
        nodes.write_chromatic(node,{'global_gain':.25})
        resources=_component('graph.output_resources')
        images={image.as_pointer() for image in resources.bank_images(node).values()}
        node[lut.MANIFEST]='authored metadata'
        nodes.undo_redo_pre_handler();nodes.reset_cache_handler();self.finish_recovery()
        with patch.object(lut,'ensure',side_effect=AssertionError('Save rebaked adopted output')), \
             patch.object(lut,'validate_output',side_effect=AssertionError('Save certified adopted output')):
            nodes.save_handler()
            self.assertEqual(scheduler._lifecycle_store.state.phase,2)
            nodes.save_finished_handler()
        current=next(n for n in tree.nodes if nodes.is_grade(n))
        self.assertTrue(lut.is_adopted(current))
        self.assertAlmostEqual(nodes.read_chromatic(current).global_gain,.25)
        self.assertEqual(current.get(lut.MANIFEST),'authored metadata')
        self.assertEqual(images,{image.as_pointer() for image in resources.bank_images(current).values()})

    def test_guarded_render_after_undo_preserves_adopted_native_output(self):
        addon.register()
        tree=bpy.data.node_groups.new('Render after undo','CompositorNodeTree')
        bpy.context.scene.compositing_node_group=tree
        node=nodes.create_grade(tree)
        nodes.write_chromatic(node,{'global_gain':.3})
        node[lut.MANIFEST]='authored render metadata'
        nodes.undo_redo_pre_handler();nodes.reset_cache_handler();self.finish_recovery()
        output=_component('graph.output')
        try:
            with patch.object(lut,'ensure',side_effect=AssertionError('Render baked adopted output')), \
                 patch.object(lut,'validate_output',side_effect=AssertionError('Render certified adopted output')):
                output.prepare_render(bpy.context.scene);nodes.render_handler()
            self.assertTrue(lut.is_adopted(node))
            self.assertAlmostEqual(nodes.read_chromatic(node).global_gain,.3)
            self.assertEqual(node.get(lut.MANIFEST),'authored render metadata')
        finally:nodes.render_end_handler()

    def test_reload_cleanup_reclaims_retained_callback_registry(self):
        addon.register()
        original_registry = scheduler._timers
        def retired_callback():
            return None
        scheduler.wake(retired_callback, 1000.)
        native_callback=scheduler.timer_callback(retired_callback)
        with patch.object(scheduler, '_timers', set()):
            addon.unregister()
            self.assert_clean()
        self.assertFalse(original_registry)
        self.assertFalse(bpy.app.timers.is_registered(native_callback))

    def test_lifecycle_receipts_match_native_save_and_restore_failures(self):
        addon.register()
        tree = bpy.data.node_groups.new('Lifecycle receipts', 'CompositorNodeTree')
        node = nodes.create_grade(tree)
        nodes.write_values(node, {'exposure': .2})
        real = grades.representations
        def fail_portable(portable=False, **kwargs):
            if portable:
                raise RuntimeError('Injected save receipt failure')
            return real(portable, **kwargs)
        with patch.object(grades, 'representations', side_effect=fail_portable):
            with self.assertRaisesRegex(RuntimeError, 'Injected save receipt failure'):
                nodes.save_handler()
        self.assertEqual(scheduler._lifecycle_store.state.phase, 4)
        self.assertTrue(scheduler._lifecycle_store.state.dirty)
        self.assertFalse(grades._saving or grades._converting)
        self.assertEqual(nodes.recovery_status()['state'],'failed')
        self.assertTrue(nodes.retry_recovery())
        self.finish_recovery()
        nodes.save_handler()
        self.assertEqual(scheduler._lifecycle_store.state.phase, 2)
        self.assertFalse(scheduler._lifecycle_store.state.dirty)
        grades.resume_after_save()
        self.assertEqual(scheduler._lifecycle_store.state.phase, 0)
        self.assertFalse(scheduler._lifecycle_store.state.dirty)
        # A delayed completion does not replay conversion or alter the phase.
        nodes.save_finished_handler()
        self.assertEqual(scheduler._lifecycle_store.state.phase, 0)

    def test_abrupt_process_exit_saved_output_is_adopted_on_reopen(self):
        """A committed .blend carries intent; no Python worker survives exit."""
        paths = [str(Path(__file__).parents[2]), *sys.path]
        env = dict(os.environ, PYTHONPATH=os.pathsep.join(paths))
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / 'abrupt.blend')
            child = """import os, bpy; from color_tools import perceptual_grade_blender as addon
from color_tools.perceptual_grade_blender.integration.lifecycle import registered_session
addon.register()
application=registered_session()
nodes,lut=application.component('graph.nodes'),application.component('graph.lut')
tree=bpy.data.node_groups.new('Abrupt recovery','CompositorNodeTree')
tree.use_fake_user=True
node=nodes.create_grade(tree)
nodes.write_chromatic(node, {'global_gain': .2})
lut.ensure(node,nodes.bake_model(node),force=True)
def interrupted_fixture(*_):
    saved=next(n for n in tree.nodes if nodes.is_grade(n))
    saved['_pg_output_pending']=True
    saved['_pg_output_manifest']='interrupted manifest'
bpy.app.handlers.save_pre.append(interrupted_fixture)
bpy.app.handlers.save_post.insert(0,lambda *_: os._exit(73))
bpy.ops.wm.save_as_mainfile(filepath=__import__('sys').argv[1],check_existing=False)
os._exit(73)
"""
            result = subprocess.run([sys.executable, '-B', '-c', child, path],
                                    env=env, capture_output=True, text=True, timeout=180)
            self.assertEqual(result.returncode, 73, result.stdout + result.stderr)
            addon.register()
            bpy.ops.wm.open_mainfile(filepath=path)
            tree = bpy.data.node_groups['Abrupt recovery']
            node = next(n for n in tree.nodes if nodes.is_grade(n))
            self.assertAlmostEqual(nodes.read_chromatic(node).global_gain, .2)
            name, kernel = node.name, node.node_tree
            self.assertEqual(node.bl_idname, 'CompositorNodeGroup')
            self.finish_recovery()
            # The saved native wrapper is deliberately replaced by its custom
            # editor type. Reacquire the current owner after bounded recovery.
            node = tree.nodes[name]
            self.assertEqual(node.bl_idname, 'PGCompositorGrade')
            self.assertEqual(node.node_tree, kernel)
            self.assertTrue(lut.is_adopted(node))
            self.assertTrue(node.get('_pg_output_pending'))
            self.assertEqual(node.get('_pg_output_manifest'),'interrupted manifest')
            resources=_component('graph.output_resources')
            banks={image.as_pointer() for image in resources.bank_images(node).values()}
            with patch.object(lut,'ensure',side_effect=AssertionError('Idle recovery baked output')), \
                 patch.object(resources,'read_pixels',side_effect=AssertionError('Recovery inspected native pixels')):
                nodes.reset_cache_handler();self.finish_recovery()
                nodes.refresh_node(node,force=True)
            self.assertEqual(banks,{image.as_pointer() for image in resources.bank_images(node).values()})
            self.assertEqual(node.get('_pg_output_manifest'),'interrupted manifest')

    def test_extension_namespace_owns_and_cleans_rna(self):
        for name in ('bl_ext', 'bl_ext.test_repository'):
            parent = ModuleType(name)
            parent.__path__ = []
            sys.modules[name] = parent
        name = 'bl_ext.test_repository.perceptual_grade'
        root = Path(self.enterContext(tempfile.TemporaryDirectory())) / 'perceptual_grade'
        root.mkdir()
        shutil.copytree(Path(addon.__file__).parent.parent, root,
                        ignore=shutil.ignore_patterns('__pycache__'), dirs_exist_ok=True)
        (root / '__init__.py').write_text('from .perceptual_grade_blender import register, unregister\n')
        spec = importlib.util.spec_from_file_location(name, root / '__init__.py', submodule_search_locations=[str(root)])
        extension = importlib.util.module_from_spec(spec)
        sys.modules[name] = extension
        spec.loader.exec_module(extension)
        try:
            extension.register()
            lifecycle = sys.modules[name + '.perceptual_grade_blender.integration.lifecycle']
            self.assertEqual(lifecycle.PACKAGE, name + '.perceptual_grade_blender')
            self.assertFalse((root / '_vendor').exists())
            self.assertFalse(any(key.startswith(name + '._vendor') for key in sys.modules))
            graph = lifecycle.registered_session().component('graph.nodes')
            self.assertTrue(lifecycle.owned(graph.PGLinearSettings))
            tree = bpy.data.node_groups.new('Namespaced extension', 'ShaderNodeTree')
            self.assertTrue(graph.is_grade(graph.create_grade(tree)))
            extension.unregister()
            self.assertFalse(hasattr(bpy.types.Node, 'pg_linear'))
            extension.register()
            graph = lifecycle.registered_session().component('graph.nodes')
            graph.refresh_all()
            self.assertTrue(graph.is_grade(tree.nodes['Grade']))
        finally:
            extension.unregister()
            for key in list(sys.modules):
                if key.startswith('bl_ext.test_repository'):
                    del sys.modules[key]
