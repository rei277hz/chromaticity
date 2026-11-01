"""Actual Blender output transaction failures and persisted graph adoption."""
from tests.support.session import component as _component, SessionTest, patch
import json
import time
from contextlib import ExitStack

import bpy
import numpy as np
gpu = _component('graph.gpu'); lut = _component('graph.lut'); nodes = _component('graph.nodes'); output_guard = _component('graph.output_guard'); scheduler = _component('graph.scheduler'); spaces = _component('graph.spaces')
from tests.support.blender import BlenderTest


class RecoveryTests(BlenderTest):
    def setUp(self):
        super().setUp()
        cpu = patch.object(gpu, 'acquire', return_value=(None, None))
        cpu.start()
        self.addCleanup(cpu.stop)

    def simple_node(self, tree_type='CompositorNodeTree'):
        tree=bpy.data.node_groups.new('Adopted output',tree_type)
        return nodes.create_grade(tree)

    def finish_recovery(self, limit=100):
        states=[]
        for _ in range(limit):
            states.append(nodes.recovery_status())
            if states[-1]['state'] in ('completed','failed','superseded'):break
            nodes.recovery_tick()
        self.assertEqual(nodes.recovery_status()['state'],'completed',nodes.recovery_status())
        self.assertFalse(nodes.recovery_pending())
        return states

    def forbid_recovery_writes(self):
        scope=ExitStack()
        for target,name in ((lut.resources,'read_pixels'),(lut.resources,'pixel_digest'),
                (lut.resources,'pack_image'),(lut.resources,'transfer_payload'),
                (lut,'_write_rows'),(lut,'ensure'),(lut,'request'),
                (nodes.grades,'representations')):
            scope.enter_context(patch.object(target,name,side_effect=AssertionError('Recovery invoked '+name)))
        return scope

    def test_native_replacement_adopts_bounded_work_without_native_writes(self):
        first=self.simple_node();second=self.simple_node('ShaderNodeTree')
        spaces.write_rows(first,((.7,.2,.1),*spaces.read_rows(first)[1:]))
        first[lut.MANIFEST]='externally edited metadata'
        before=tuple(lut._graph_snapshot(node) for node in (first,second))
        with self.forbid_recovery_writes():
            nodes.undo_redo_pre_handler();nodes.reset_cache_handler()
            self.assertEqual(nodes.recovery_status()['state'],'retiring')
            self.assertTrue(nodes.recovery_pending())
            states=self.finish_recovery()
            for node in (first,second):
                self.assertTrue(lut.is_adopted(node))
                nodes.refresh_node(node,force=True,immediate=True)
        self.assertEqual(tuple(lut._graph_snapshot(node) for node in (first,second)),before)
        self.assertEqual(nodes.recovery_status()['completed'],3)
        self.assertTrue(any(a['completed']+1==b['completed'] for a,b in zip(states,states[1:])))
        for node in (first,second):
            state=lut.resources.record(node.node_tree,node)['state']
            self.assertTrue(state.adopted)
            self.assertFalse(any(slot.valid for slot in state.slots))

    def test_recovery_waits_for_actual_retirement_and_retry_keeps_ownership_epoch(self):
        self.simple_node()
        nodes.undo_redo_pre_handler();nodes.reset_cache_handler()
        ownership=_component('ownership')
        tokens=tuple((arena,arena.state.token,arena.state.epoch) for arena in ownership.snapshots())
        with patch.object(lut,'collect_retired',return_value=False),patch.object(time,'monotonic',return_value=time.monotonic()+10):
            with self.assertLogs(nodes.LOG,level='ERROR'):nodes.recovery_tick()
        self.assertEqual(nodes.recovery_status()['state'],'failed')
        self.assertTrue(nodes.recovery_pending())
        self.assertIsNone(nodes.recovery_tick())
        with patch.object(ownership,'native_replaced',side_effect=AssertionError('Retry fabricated replacement')):
            self.assertTrue(nodes.retry_recovery())
            self.finish_recovery()
        self.assertEqual(tuple((arena,arena.state.token,arena.state.epoch) for arena in ownership.snapshots()),tokens)

    def test_pre_cleanup_failure_still_accepts_real_native_post(self):
        self.simple_node()
        with patch.object(nodes,'clear_transient_caches',side_effect=RuntimeError('cleanup interrupted')):
            with self.assertLogs(nodes.LOG,level='ERROR'):nodes.undo_redo_pre_handler()
        self.assertEqual(nodes.recovery_status()['state'],'failed')
        nodes.reset_cache_handler()
        self.finish_recovery()

    def test_only_actual_replacement_retires_old_evaluation_tokens(self):
        self.simple_node()
        output_guard.evaluation_started('composite',987654)
        nodes.undo_redo_pre_handler();nodes.reset_cache_handler()
        self.finish_recovery()
        self.assertTrue(output_guard.available())
        output_guard.evaluation_started('composite',123456)
        try:
            self.assertTrue(nodes.retry_recovery())
            self.assertEqual(nodes.recovery_tick(),.02)
            self.assertFalse(output_guard.available())
        finally:output_guard.evaluation_finished('composite',123456)
        self.finish_recovery()

    def test_native_reader_arrival_during_reconcile_defers_without_failure(self):
        self.simple_node()
        nodes.undo_redo_pre_handler();nodes.reset_cache_handler()
        for _ in range(10):
            if nodes.recovery_status()['state']=='reconciling':break
            nodes.recovery_tick()
        before=nodes.recovery_status()
        self.assertEqual(before['state'],'reconciling')
        with patch.object(output_guard,'available',side_effect=output_guard.PublicationDeferred('Native reader arrived')):
            self.assertEqual(nodes.recovery_tick(),.02)
        self.assertEqual(nodes.recovery_status(),before)
        self.finish_recovery()

    def test_initial_scan_preserves_new_runtime_output_intent(self):
        node=self.simple_node()
        nodes.write_chromatic(node,{'global_gain':.13})
        pending=lut._states[node.as_pointer()]
        self.assertTrue(lut.has_runtime_intent(node))
        nodes.poll_working_space()
        self.finish_recovery()
        self.assertFalse(lut.is_adopted(node))
        self.assertIs(lut._states[node.as_pointer()],pending)
        lut.ensure(node,nodes.bake_model(node),force=True)
        lut.validate_output(node,nodes.bake_model(node),final=True)

    def test_save_failure_without_coordinator_exposes_explicit_retry(self):
        self.simple_node()
        nodes._lifecycle_event('fail')
        self.assertEqual(nodes.recovery_status()['state'],'failed')
        nodes.poll_working_space()
        self.assertEqual(nodes.recovery_status()['state'],'failed')
        self.assertTrue(nodes.retry_recovery())
        self.finish_recovery()

    def test_newer_native_replacement_supersedes_partial_worklist(self):
        self.simple_node()
        nodes.undo_redo_pre_handler();nodes.reset_cache_handler();nodes.recovery_tick()
        old=nodes.recovery_status()['generation']
        nodes.undo_redo_pre_handler();nodes.reset_cache_handler()
        self.assertGreater(nodes.recovery_status()['generation'],old)
        self.finish_recovery()

    def test_control_change_exits_adoption_but_force_and_external_rows_do_not(self):
        node=self.simple_node()
        lut.adopt_native(node,nodes.output_intent(node))
        spaces.write_rows(node,((.3,.4,.5),*spaces.read_rows(node)[1:]))
        with patch.object(lut,'request',side_effect=AssertionError('Unchanged adopted output requested')):
            nodes.refresh_node(node,force=True,immediate=True)
        self.assertTrue(lut.is_adopted(node))
        with patch.object(nodes,'refresh_node'):
            nodes.write_values(node,{'exposure':.75})
        self.assertTrue(lut.request_intent(node,nodes.output_intent(node)))
        self.assertFalse(lut.is_adopted(node))

    def test_stack_order_and_references_change_semantic_intent(self):
        from tests.support.blender import grade_data,sequence
        stacks=_component('graph.stacks')
        first,second=grade_data(),grade_data()
        tree=bpy.data.node_groups.new('Restored Stack','ShaderNodeTree')
        node=sequence(tree,(first,second))
        initial=nodes.output_intent(node)
        lut.adopt_native(node,initial)
        with patch.object(stacks,'bind_dependencies',side_effect=AssertionError('Adoption rewrote drivers')),self.forbid_recovery_writes():
            stacks.refresh(node,force=True,immediate=True)
        with nodes.grades.guarded(node):node.pg_stack_entries.move(0,1)
        changed=nodes.output_intent(node)
        self.assertNotEqual(initial,changed)
        self.assertTrue(lut.request_intent(node,changed))


    def node(self, tree_type='CompositorNodeTree'):
        tree = bpy.data.node_groups.new('Recovery output', tree_type)
        node = nodes.create_grade(tree)
        nodes.write_chromatic(node, {'global_gain': .1})
        lut.ensure(node, nodes.bake_model(node), force=True)
        lut.validate_output(node, nodes.bake_model(node), final=True)
        return node


    @staticmethod
    def pixels(image):
        values = np.empty(len(image.pixels), np.float32)
        image.pixels.foreach_get(values)
        return values


    def bank_snapshot(self, node):
        return {index: (image.as_pointer(), lut.resources.pixel_digest(self.pixels(image)),
                        image.get(lut.resources.REVISION), image.get('_pg_payload_record'))
                for index, image in lut.resources.bank_images(node).items()}


    @staticmethod
    def forget_runtime():
        """Lose volatile authority without pretending this performs native undo."""
        lut.clear()
        lut.resources.clear()
        lut._ready.clear()


    def test_payload_validation_enforces_finite_float32_bounds_and_layout(self):
        image=bpy.data.images.new('Numeric payload bounds',width=1,height=1,float_buffer=True,alpha=True)
        image['_pg_cube_encoding']='RGB'
        limit=np.float32(2.**120)
        for values in (np.zeros(4,np.float32),np.array((limit,-limit,0.,-0.),np.float32),
                       np.full(4,np.nextafter(limit,np.float32(0)),np.float32)):
            np.testing.assert_array_equal(lut.resources.validate_pixels(image,values),values)
        for bad in (np.nextafter(limit,np.float32(np.inf)),np.nextafter(-limit,np.float32(-np.inf)),
                    np.float32(np.nan),np.float32(np.inf),np.float32(-np.inf)):
            for channel in range(4):
                with self.subTest(value=bad,channel=channel):
                    values=np.zeros(4,np.float32);values[channel]=bad
                    with self.assertRaises(ValueError):lut.resources.validate_pixels(image,values)
        for values in (np.zeros(4,np.float64),np.zeros(3,np.float32),np.empty(0,np.float32)):
            with self.assertRaises(ValueError):lut.resources.validate_pixels(image,values)
        # Numeric validation permits a genuinely empty buffer. Bank layout
        # validation separately requires the full supported atlas dimensions.
        class EmptyImage(dict):pixels=()
        empty=EmptyImage(_pg_cube_encoding='RGBE_DIFFERENCES')
        self.assertEqual(lut.resources.validate_pixels(empty,np.empty(0,np.float32)).size,0)


    def test_rgbe_payload_validation_enforces_rgb_bounds_and_integral_exponents(self):
        image=bpy.data.images.new('RGBE payload bounds',width=1,height=1,float_buffer=True,alpha=True)
        image['_pg_cube_encoding']='RGBE_DIFFERENCES'
        for channel in range(4):
            for invalid in (np.nan,np.inf,-np.inf):
                values=np.zeros(4,np.float32);values[channel]=invalid
                with self.assertRaisesRegex(ValueError,'not finite bounded float32'):
                    lut.resources.validate_pixels(image,values)
        for exponent in (-149.,0.,120.):
            values=np.array((-1.,1.,np.nextafter(np.float32(0),np.float32(1)),exponent),np.float32)
            np.testing.assert_array_equal(lut.resources.validate_pixels(image,values),values)
        for channel in range(3):
            for bound in (-1.,1.):
                values=np.zeros(4,np.float32)
                values[channel]=np.nextafter(np.float32(bound),np.float32(bound*2))
                with self.assertRaises(ValueError):lut.resources.validate_pixels(image,values)
        for exponent in (-150.,-149.5,-148.5,.5,119.5,120.5,121.,np.nan,np.inf,-np.inf,
                         np.nextafter(np.float32(0),np.float32(1))):
            with self.subTest(exponent=exponent):
                values=np.zeros(4,np.float32);values[3]=exponent
                with self.assertRaises(ValueError):lut.resources.validate_pixels(image,values)


    def candidate(self, node, gain=.2):
        nodes.write_chromatic(node, {'global_gain': gain})
        baker = lut._states[node.as_pointer()]['baker']
        baker.finish()
        return baker


    def test_repeated_payloads_keep_native_resources_bounded(self):
        measurements = []
        for tree_type in ('ShaderNodeTree', 'CompositorNodeTree'):
            tree = bpy.data.node_groups.new('Bounded output', tree_type)
            node = nodes.create_grade(tree)
            # The first explicit edit creates the independent Grade asset.
            # Measure steady publication after that structural edit completes.
            offset = 0. if tree_type == 'ShaderNodeTree' else 1.
            nodes.write_chromatic(node, {'global_gain': .05 + offset})
            lut.ensure(node, nodes.bake_model(node))
            banks = lut.resources.bank_images(node)
            images = {image.as_pointer() for image in bpy.data.images}
            kernels = {group.as_pointer() for group in bpy.data.node_groups}
            links = tuple((link.from_socket.as_pointer(), link.to_socket.as_pointer())
                          for link in node.node_tree.links)
            durations = []
            transfer = lut.resources.transfer_payload
            def timed(*args, **kwargs):
                started = time.perf_counter()
                result = transfer(*args, **kwargs)
                durations.append(time.perf_counter() - started)
                return result
            with patch.object(lut.resources, 'transfer_payload', side_effect=timed):
                for index in range(12):
                    baker = self.candidate(node, .1 + offset + index * .025)
                    self.assertTrue(lut.publish(node, baker, force=True, preview=True))
                    self.assertTrue(lut.publish(node, baker, force=True))
                    lut.validate_output(node, nodes.bake_model(node), final=True)
                    self.assertEqual({image.as_pointer() for image in bpy.data.images}, images)
                    self.assertEqual({group.as_pointer() for group in bpy.data.node_groups}, kernels)
                    self.assertEqual(tuple((link.from_socket.as_pointer(), link.to_socket.as_pointer())
                                           for link in node.node_tree.links), links)
            measurements.append(dict(tree_type=tree_type, publications=len(durations),
                banks=len(banks), payload_bytes=sum(len(image.pixels) * 4 for image in banks.values()),
                transfer_median_ms=float(np.median(durations)) * 1000,
                transfer_max_ms=max(durations) * 1000))
        print('PG_OUTPUT_RESOURCES_PROFILE ' + json.dumps(measurements, sort_keys=True), flush=True)


    def assert_snapshot(self, node, snapshot):
        self.assertEqual(lut._graph_snapshot(node), snapshot)
        self.assertFalse(node.get(lut.INCOMPLETE))
        self.assertEqual(json.loads(node[lut.MANIFEST]), lut.validate_output(node, final=True))


    def test_every_precommit_phase_restores_complete_previous_output(self):
        for index, phase in enumerate(('reserved', 'armed', 'transferred', 'verified', 'rows', 'selector', 'validated', 'manifest')):
            with self.subTest(phase=phase):
                node = self.node()
                baker = self.candidate(node, .2 + index * .01)
                before = lut._graph_snapshot(node)
                prior_policy = scheduler._records['lut', node.as_pointer()]['store'].state
                images = set(image.as_pointer() for image in bpy.data.images)
                def fail(checkpoint):
                    if checkpoint == phase:
                        raise RuntimeError('Injected ' + phase)
                with patch.object(lut, '_publication_checkpoint', side_effect=fail):
                    with self.assertRaisesRegex(RuntimeError, 'Injected ' + phase):
                        lut.publish(node, baker, force=True)
                self.assert_snapshot(node, before)
                self.assertEqual(set(image.as_pointer() for image in bpy.data.images), images)
                # Failure neither acknowledges a final publication nor strands
                # the effect lane; explicit Retry can publish a complete cube.
                policy = scheduler._records['lut', node.as_pointer()]['store'].state
                self.assertEqual((policy.quality, policy.publications),
                                 (prior_policy.quality, prior_policy.publications))
                self.assertEqual(policy.effect, 0)
                lut.scope_retry()
                self.assertTrue(lut.publish(node, baker, force=True))
                lut.validate_output(node, nodes.bake_model(node), final=True)
                bpy.data.node_groups.remove(node.id_data)


    def test_rejected_install_and_authorization_release_known_unwritten_reservations(self):
        for ordinal,failure in enumerate(('authorization','effect_begin')):
            with self.subTest(failure=failure):
                node=self.node()
                baker=self.candidate(node,.314159+ordinal*.271828)
                before=self.bank_snapshot(node),lut._graph_snapshot(node)
                if failure=='authorization':
                    injection=patch.object(baker,'authorize_publication',side_effect=RuntimeError('No write admitted'))
                else:
                    begin=scheduler.effect_begin
                    injection=patch.object(scheduler,'effect_begin',side_effect=lambda ticket,phase:
                        None if phase=='install' else begin(ticket,phase))
                with injection:
                    with self.assertRaises(RuntimeError):lut.publish(node,baker,force=True)
                current=lut.resources.record(node.node_tree,node)
                self.assertEqual(current['state'].pending,-1)
                self.assertFalse(current['publication_protocol'].state.debt)
                self.assertEqual(current['publication_protocol'].state.phase,'idle')
                self.assertNotIn('publication_repair',current)
                self.assertEqual((self.bank_snapshot(node),lut._graph_snapshot(node)),before)
                self.assertTrue(lut.publish(node,baker,force=True))


    def test_shared_rows_are_written_only_with_verified_fallback_during_install_and_rollback(self):
        node = self.node()
        baker = self.candidate(node)
        before = lut._graph_snapshot(node)
        write = lut._write_rows
        observed = []
        def checked(owner, rows):
            observed.append(lut.resources.selected_index(owner))
            self.assertEqual(observed[-1], -1)
            return write(owner, rows)
        def fail(phase):
            if phase == 'rows':
                raise RuntimeError('Rows written before completion')
        with patch.object(lut, '_write_rows', side_effect=checked), \
                patch.object(lut, '_publication_checkpoint', side_effect=fail):
            with self.assertRaisesRegex(RuntimeError, 'Rows written before completion'):
                lut.publish(node, baker, force=True)
        self.assertGreaterEqual(len(observed), 2)
        self.assert_snapshot(node, before)


    def test_failed_fallback_admission_does_not_write_candidate_rows(self):
        node = self.node()
        baker = self.candidate(node)
        before = lut._graph_snapshot(node)
        select = lut.resources.select_payload
        attempts = []
        def first_fallback_fails(owner, index):
            attempts.append(index)
            if len(attempts) == 1 and index == -1:
                raise RuntimeError('Selector clear rejected')
            return select(owner, index)
        rows = []
        write = lut._write_rows
        def capture(owner, values):
            rows.append(values)
            return write(owner, values)
        with patch.object(lut.resources, 'select_payload', side_effect=first_fallback_fails), \
                patch.object(lut, '_write_rows', side_effect=capture):
            with self.assertRaisesRegex(RuntimeError, 'Selector clear rejected'):
                lut.publish(node, baker, force=True)
        # The only row write belongs to compensation after admission failed.
        self.assertEqual(rows, [before['rows']])
        self.assert_snapshot(node, before)


    def test_postcommit_cleanup_failure_keeps_successful_final_output(self):
        node = self.node()
        baker = self.candidate(node)
        def fail(phase):
            if phase == 'cleanup':
                raise RuntimeError('Injected cleanup')
        with self.assertLogs(lut.LOG, level='ERROR'), patch.object(lut, '_publication_checkpoint', side_effect=fail):
            self.assertTrue(lut.publish(node, baker, force=True))
        self.assertFalse(node.get(lut.INCOMPLETE))
        lut.validate_output(node, nodes.bake_model(node), final=True)
        self.assertIsNone(lut.adopt_native(node,nodes.output_intent(node)))


    def test_gpu_completed_install_failure_is_manual_retry_not_cpu_fallback(self):
        node = self.node()
        baker = self.candidate(node)
        baker.requires_main_thread = True
        state = lut._states[node.as_pointer()]
        state['preview_published'] = True
        prior = lut._graph_snapshot(node)
        def fail(phase):
            if phase == 'transferred':
                raise RuntimeError('Injected GPU output install failure')
        with self.assertLogs(lut.LOG, level='ERROR'),                 patch.object(lut, '_publication_checkpoint', side_effect=fail),                 patch.object(lut, 'cpu_baker', side_effect=AssertionError('Installation cannot restart compute')):
            lut.tick()
        self.assert_snapshot(node, prior)
        self.assertIn('Injected GPU output install failure', node['_pg_bake_error'])
        self.assertNotIn(node.as_pointer(), lut._states)
        with patch.object(lut, 'cpu_baker', side_effect=AssertionError('Unchanged failure automatically retried')):
            lut.request(node, nodes.bake_model(node))
            lut.tick()
        self.assertNotIn(node.as_pointer(), lut._states)
        lut.scope_retry()
        lut.ensure(node, nodes.bake_model(node), force=True)
        self.assertFalse(node.get('_pg_bake_error'))
        lut.validate_output(node, nodes.bake_model(node), final=True)


    def test_row_only_stage1_edit_updates_manifest_and_is_adopted_without_rebake(self):
        node = self.node()
        image = lut.image_for(node)
        before = node[lut.MANIFEST]
        nodes.write_values(node, {'exposure': .5})
        nodes.refresh_node(node, force=True, immediate=True)
        self.assertEqual(lut.image_for(node), image)
        self.assertNotEqual(node[lut.MANIFEST], before)
        self.assertEqual(json.loads(node[lut.MANIFEST]),
                         lut.validate_output(node, nodes.bake_model(node), final=True))
        with patch.object(lut, 'cpu_baker', side_effect=AssertionError('Row-only rebake')):
            self.assertIsNone(lut.adopt_native(node,nodes.output_intent(node)))


    def test_renamed_tagged_texture_is_valid_but_missing_banks_are_not(self):
        node = self.node()
        original = lut.validate_output(node, final=True)
        texture = next(item for item in node.node_tree.nodes.values() if item.get('_pg_cube_image'))
        texture.name = 'User renamed LUT texture'
        self.assertEqual(lut.validate_output(node, final=True), original)
        image = texture.image
        texture.image = None
        with self.assertRaisesRegex(ValueError, 'Incomplete permanent LUT bank'):
            lut.validate_output(node, final=True)
        texture.image = image
        self.assertEqual(lut.validate_output(node, final=True), original)


    def test_scope_demand_owners_are_independent_and_reuse_native_baker(self):
        node = self.node()
        nodes.write_chromatic(node, {'global_gain': .3})
        model = nodes.bake_model(node)
        key = lut.cm.signature(model)
        state = lut._states[node.as_pointer()]
        first, second = object(), object()
        for owner in (first, second):
            with self.assertRaises(lut.ScopePreparing):
                lut.scope_signal(node, model, owner=owner)
        self.assertEqual(len(lut._scope_demands[key]['owners']), 2)
        lut.scope_release(node, model, owner=first)
        self.assertEqual(set(lut._scope_demands[key]['owners']), {('snapshot', second)})
        with patch.object(lut, 'cpu_baker', side_effect=AssertionError('Duplicate scope baker')):
            lut.scope_tick()
            self.assertIsNone(lut._scope_running)
            self.assertIs(lut._states[node.as_pointer()], state)
            state['baker'].finish()
            lut.scope_tick()
            cube, before, after = lut.scope_signal(node, model, owner=second)
        self.assertEqual(cube.size, 65)
        self.assertIs(cube, state['baker'].cube)
        self.assertNotIn(key, lut._scope_demands)
        self.assertFalse(before.flags.writeable or after.flags.writeable)


    def test_final_scope_cache_does_not_require_replacing_preview_image(self):
        node = self.node()
        baker = self.candidate(node)
        self.assertTrue(lut.publish(node, baker, force=True, preview=True))
        preview = lut.image_for(node)
        self.assertEqual(preview['_pg_cube_size'], 33)
        lut._remember_final(baker.cube)
        with patch.object(lut, 'cpu_baker', side_effect=AssertionError('Unexpected rebake')):
            cube, *_ = lut.scope_signal(node)
        self.assertEqual(cube.size, 65)
        self.assertIs(cube, baker.cube)
        self.assertIs(lut.image_for(node), preview)
        self.assertEqual(preview['_pg_cube_size'], 33)


