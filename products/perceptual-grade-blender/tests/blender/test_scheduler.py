"""Real Blender identities and publications paired to the pure scheduler policy."""
from tests.support.session import component as _component, SessionTest, patch
from concurrent.futures import Future
from threading import Event
pass
import time

import bpy
import numpy as np

compositor = _component('graph.compositor'); editing = _component('graph.editing'); gpu = _component('graph.gpu'); grades = _component('graph.grades'); lut = _component('graph.lut'); nodes = _component('graph.nodes'); scheduler = _component('graph.scheduler')
jobs = _component('scopes.jobs'); reference = _component('scopes.reference'); sampling = _component('scopes.sampling')
from tests.support.blender import BlenderTest, sequence, wait_for_scopes
from tests.support.scope import ScopeExecutor


class SchedulerAdapterTests(BlenderTest):
    def setUp(self):
        super().setUp()
        cpu = patch.object(gpu, 'acquire', return_value=(None, None))
        cpu.start()
        self.addCleanup(cpu.stop)

    def node(self):
        tree = bpy.data.node_groups.new('Scheduler adapter', 'CompositorNodeTree')
        return nodes.create_grade(tree)

    def preview(self, node):
        state = lut._states[node.as_pointer()]
        state['due'] = 0.
        state['started'] = True
        state['baker'].finish_preview()
        future = Future()
        future.set_result(None)
        state['future'] = future
        lut.tick()
        cube = lut.installed_cube(node)
        self.assertIsNotNone(cube)
        self.assertEqual(cube.size, 33)

    def final(self, node):
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            lut.tick()
            cube = lut.installed_cube(node)
            if cube is not None and cube.size == 65:
                return cube
            time.sleep(.001)
        self.fail('Final cube was not published')

    def test_release_fences_old_preview_and_commits_each_quality_once(self):
        node = self.node()
        gesture = scheduler.begin(node)
        old_model = nodes.bake_model(node)
        nodes.write_tone(node, {'input_midtones': 44.})
        old_preview = scheduler.lut_candidate(node, old_model, preview=True)
        self.assertTrue(scheduler.publication(old_preview, commit=False))
        scheduler.end(gesture)
        self.assertFalse(scheduler.publication(old_preview, commit=False))

        state = lut._states[node.as_pointer()]
        state['baker'].finish_preview()
        record = scheduler._records['lut', node.as_pointer()]
        with patch.object(compositor, 'can_commit', return_value=False):
            self.assertIsNone(lut.publish(node, state['baker'], preview=True))
            self.assertEqual(record['store'].state.publications, 0)
        with patch.object(compositor, 'can_commit', return_value=True),\
             patch.object(compositor, 'tag_output', wraps=compositor.tag_output) as tag:
            self.assertTrue(lut.publish(node, state['baker'], preview=True))
            self.assertTrue(lut.publish(node, state['baker'], preview=True))
            tag.assert_called_once_with(node)
            self.assertEqual(record['store'].state.publications, 1)
            state['baker'].finish()
            self.assertTrue(lut.publish(node, state['baker']))
            self.assertTrue(lut.publish(node, state['baker']))
            self.assertEqual(tag.call_count, 2)
        self.assertEqual(record['store'].state.publications, 2)

    def test_analytical_scope_requires_frozen_evaluation_identity(self):
        """Regular Grade scopes may publish without a baked cube, but only
        with the evaluator identity captured by their ticket."""
        node=self.node();space=nodes.grading_space(node)
        spec=sampling.describe(node,space)
        ticket=scheduler.scope_request(node,'full',spec);spec['_schedule']=ticket
        self.assertTrue(ticket.evaluation)
        self.assertNotEqual(ticket.evaluation[0],'stack-final-lut')
        self.assertTrue(scheduler.scope_coherent(node,'full',spec))
        self.assertTrue(scheduler.scope_start(ticket));scheduler.scope_complete(ticket)
        bad={'_scope_provenance':(), '_scope_evaluation':('mismatch',)}
        self.assertFalse(scheduler.scope_publish(ticket,bad))
        self.assertIsNone(scheduler.scope_result(node))
        result=jobs.readonly({'_scope_provenance':(), '_scope_evaluation':ticket.evaluation})
        self.assertTrue(scheduler.scope_publish(ticket,result))
        self.assertIs(scheduler.scope_result(node),result)

    def test_native_source_refresh_retains_one_coherent_display_per_editor(self):
        node=self.node();space=nodes.grading_space(node)
        channel=(node.as_pointer(),('editor-a',))
        spec=sampling.describe(node,space,('tone',));spec['_scope_channel']=channel
        old=scheduler.scope_request(node,'full',spec)
        payload={'_scope_provenance':old.provenance,'_scope_evaluation':old.evaluation,
                 'measurement':'first source'}
        self.assertTrue(scheduler.scope_publish(old,payload))
        changed=dict(spec,context=('new native revision',),
                     _scope_display_source=('new native revision',))
        latest=scheduler.scope_request(node,'full',changed)
        self.assertNotEqual(old.owner,latest.owner)
        self.assertFalse(scheduler.scope_publish(old,payload))
        self.assertIs(scheduler.scope_result(node,channel=channel),payload)
        self.assertEqual(scheduler.scope_status(node,channel=channel),'stale')
        other=(node.as_pointer(),('editor-b',))
        scheduler.scope_request(node,'full',dict(changed,_scope_channel=other))
        self.assertIsNone(scheduler.scope_result(node,channel=other))
        replacement={'_scope_provenance':latest.provenance,
                     '_scope_evaluation':latest.evaluation,'measurement':'new source'}
        self.assertTrue(scheduler.scope_publish(latest,replacement))
        self.assertIs(scheduler.scope_result(node,channel=channel),replacement)
        self.assertEqual(scheduler.scope_status(node,channel=channel),'current')

    def test_stack_scope_still_requires_final_provenance(self):
        first=self.node();shared=grades.ensure(first)
        stack=sequence(first.id_data,[shared])
        target=editing.Target(stack,stack.pg_stack_entries[0])
        space=nodes.grading_space(target)
        spec=sampling.describe(target,space)
        ticket=scheduler.scope_request(target,'full',spec);spec['_schedule']=ticket
        self.assertEqual(ticket.evaluation[0],'stack-final-lut')
        self.assertTrue(ticket.provenance)
        self.assertTrue(scheduler.scope_coherent(target,'full',spec))
        self.assertTrue(scheduler.scope_start(ticket));scheduler.scope_complete(ticket)
        bad={'_scope_provenance':tuple((signature,33) for signature,_ in ticket.provenance),
             '_scope_evaluation':ticket.evaluation}
        self.assertFalse(scheduler.scope_publish(ticket,bad))
        result=jobs.readonly({'_scope_provenance':ticket.provenance,
                              '_scope_evaluation':ticket.evaluation})
        self.assertTrue(scheduler.scope_publish(ticket,result))

    def test_cancelled_cpu_future_retires_without_losing_pending_snapshot(self):
        """Adapter retains the payload while the policy slot awaits completion."""
        for return_to_original in (False, True):
            with self.subTest(return_to_original=return_to_original):
                # Exercise physical retirement rather than the independent
                # completed-cube cache shortcut from the preceding subcase.
                lut._ready.clear()
                node = self.node()
                gesture = scheduler.begin(node)
                state = lut._states[node.as_pointer()]
                self.assertTrue(scheduler.scope_start(state['schedule']))
                state['started'] = True
                state['baker'].finish_preview()
                future = Future()
                future.set_running_or_notify_cancel()
                self.addCleanup(lambda f=future: f.set_result(None) if not f.done() else None)
                state['future'] = future
                original = nodes.read_tone(node).input_midtones
                nodes.write_tone(node, {'input_midtones': 44.})
                scheduler.end(gesture)
                if return_to_original:
                    nodes.write_tone(node, {'input_midtones': original})
                expected = lut.cm.signature(nodes.bake_model(node))
                with patch.object(lut, 'publish', wraps=lut.publish) as publish:
                    lut.tick()
                    publish.assert_not_called()
                self.assertIs(lut._states[node.as_pointer()], state)
                self.assertEqual(lut.cm.signature(state['pending']), expected)
                record = scheduler._records['lut', node.as_pointer()]
                self.assertEqual(record['store'].state.worker, state['schedule'].token)
                future.set_result(None)
                deadline=time.monotonic()+30
                while lut._states[node.as_pointer()] is state and time.monotonic()<deadline:
                    lut.tick();time.sleep(.001)
                replacement = lut._states[node.as_pointer()]
                self.assertIsNot(replacement, state)
                self.assertEqual(replacement['baker'].signature, expected)
                self.assertEqual(record['store'].state.worker, 0)
                self.assertEqual(self.final(node).signature, expected)

    def test_gpu_packing_is_not_reported_as_an_idle_cpu_future(self):
        """No CPU future does not mean main-thread GPU work has completed."""
        node = self.node()
        state = lut._states[node.as_pointer()]
        baker = state['baker']
        baker.requires_main_thread = True
        baker.packing = []
        state['started'] = True
        self.assertTrue(scheduler.scope_start(state['schedule']))
        self.assertFalse(lut._finished(state))
        packed = Future()
        packed.set_running_or_notify_cancel()
        self.addCleanup(lambda: packed.set_result(None) if not packed.done() else None)
        baker.packing.append((True, packed))
        lut.stop(state)
        state['superseded'] = True
        self.assertFalse(lut._finished(state))
        record = scheduler._records['lut', node.as_pointer()]
        self.assertEqual(record['store'].state.worker, state['schedule'].token)
        packed.set_result(None)
        lut.collect_retired()
        self.assertTrue(lut._finished(state))
        self.assertEqual(record['store'].state.worker, 0)

    def test_shared_grade_gesture_fans_out_to_grade_and_stack_outputs(self):
        first = self.node()
        shared = grades.ensure(first)
        second = nodes.create_grade(first.id_data)
        second.pg_grade = shared
        stack = sequence(first.id_data, [shared, shared])
        target = editing.Target(stack, stack.pg_stack_entries[0])
        token = scheduler.begin(first)
        try:
            for output in (first, second, stack, target):
                self.assertTrue(scheduler.dragging(output))
                scheduler.lut_request(scheduler.output(output), nodes.bake_model(scheduler.output(output)))
            with patch.object(lut, 'settle') as settle:
                scheduler.end(token)
            settled = {call.args[0].as_pointer() for call in settle.call_args_list}
            self.assertTrue({first.as_pointer(), second.as_pointer(), stack.as_pointer()} <= settled)
            for output in (first, second, stack, target):
                self.assertFalse(scheduler.dragging(output))
        finally:
            scheduler.end(token)

    def test_scope_gesture_follows_primary_reroutes_without_changing_lut_dragging(self):
        upstream=self.node();tree=upstream.id_data
        middle=nodes.create_grade(tree);downstream=nodes.create_grade(tree)
        unrelated=nodes.create_grade(tree);reroute=tree.nodes.new('NodeReroute')
        tree.links.new(upstream.outputs['Color'],reroute.inputs[0])
        tree.links.new(reroute.outputs[0],middle.inputs['Color'])
        tree.links.new(middle.outputs['Color'],downstream.inputs['Color'])
        scheduler.lut_request(downstream,nodes.bake_model(downstream))
        space=nodes.grading_space(downstream)
        before=sampling.describe(downstream,space,(1,True))
        old=scheduler.scope_request(downstream,'full',before)
        self.assertTrue(scheduler.scope_start(old));scheduler.scope_complete(old)
        token=scheduler.begin(upstream)
        try:
            with patch.object(sampling,'source_signature',side_effect=AssertionError('Gesture evaluated source')):
                self.assertTrue(scheduler.scope_dragging(downstream))
                self.assertFalse(scheduler.scope_dragging(unrelated))
            self.assertFalse(scheduler.dragging(downstream))
            self.assertFalse(scheduler._records['lut',downstream.as_pointer()]['store'].state.dragging)
            self.assertTrue(scheduler._records[old.channel]['store'].state.dragging)
            linear=scheduler.scope_request(downstream,'linear',sampling.describe_linear(downstream,space))
            self.assertTrue(scheduler._records[linear.channel]['store'].state.dragging)
            nodes.write_values(upstream,{'exposure':.25})
            after=sampling.describe(downstream,space,(1,True))
            latest=scheduler.scope_request(downstream,'full',after)
            self.assertEqual(before['scope_source'],after['scope_source'])
            self.assertNotEqual(sampling.cache_id(before),sampling.cache_id(after))
            self.assertEqual((old.owner,old.signal),(latest.owner,latest.signal))
            self.assertNotEqual(old.key,latest.key)
            payload={'_scope_provenance':old.provenance,'_scope_evaluation':old.evaluation}
            self.assertTrue(scheduler.scope_publish(old,payload))
            with patch.object(lut,'settle') as settle:scheduler.end(token)
            self.assertNotIn(downstream.as_pointer(),{call.args[0].as_pointer() for call in settle.call_args_list})
            self.assertFalse(scheduler.scope_dragging(downstream))
            self.assertFalse(scheduler._records[old.channel]['store'].state.dragging)
            self.assertFalse(scheduler._records[linear.channel]['store'].state.dragging)
            self.assertTrue(scheduler.scope_publish(old,payload))
            self.assertNotEqual(old.key,latest.key)  # History does not certify the latest request.
        finally:
            scheduler.end(token)

    def test_scope_gesture_follows_arbitrary_intermediate_color_nodes(self):
        upstream=self.node();tree=upstream.id_data
        transform=tree.nodes.new('CompositorNodeTransform')
        downstream=nodes.create_grade(tree)
        tree.links.new(upstream.outputs['Color'],transform.inputs['Image'])
        tree.links.new(transform.outputs['Image'],downstream.inputs['Color'])
        token=scheduler.begin(upstream)
        try:
            self.assertTrue(scheduler.scope_dragging(downstream))
            self.assertFalse(scheduler.dragging(downstream))
        finally:scheduler.end(token)

    def test_scope_gesture_follows_only_visible_root_reference(self):
        edited=self.node();tree=edited.id_data
        direct=nodes.create_grade(tree);middle=nodes.create_grade(tree)
        downstream=nodes.create_grade(tree);unrelated=nodes.create_grade(tree)
        tree.links.new(edited.outputs['Color'],direct.inputs[reference.SOCKET])
        tree.links.new(edited.outputs['Color'],middle.inputs[reference.SOCKET])
        tree.links.new(middle.outputs['Color'],downstream.inputs['Color'])
        space=nodes.grading_space(direct)
        token=scheduler.begin(edited)
        try:
            old=scheduler.scope_request(direct,'full',sampling.describe(direct,space))
            self.assertTrue(scheduler.scope_dragging(direct))
            self.assertTrue(scheduler._records[old.channel]['store'].state.dragging)
            self.assertFalse(scheduler.dragging(direct))
            self.assertFalse(scheduler.scope_dragging(downstream))
            self.assertFalse(scheduler.scope_dragging(unrelated))
            nodes.write_chromatic(edited,{'global_gain':.1})
            latest=scheduler.scope_request(direct,'full',sampling.describe(direct,space))
            self.assertEqual((old.owner,old.signal),(latest.owner,latest.signal))
            self.assertNotEqual(old.key,latest.key)
            self.assertTrue(scheduler.scope_publish(old,dict(_scope_provenance=old.provenance,
                _scope_evaluation=old.evaluation)))
            reference.toggle(direct)
            self.assertFalse(scheduler.scope_dragging(direct))
            hidden=scheduler.scope_request(direct,'full',sampling.describe(direct,space))
            self.assertNotEqual(hidden.signal,old.signal)
            self.assertFalse(scheduler._records[hidden.channel]['store'].state.dragging)
        finally:
            scheduler.end(token)

    def test_scope_gesture_follows_shared_stack_entries_and_target_inputs(self):
        edited=self.node();tree=edited.id_data;shared=grades.ensure(edited)
        sibling=nodes.create_grade(tree);sibling.pg_grade=shared
        stack=sequence(tree,[shared,shared]);disabled=sequence(tree,[shared])
        disabled.pg_stack_entries[0].enabled=False
        consumers=[nodes.create_grade(tree) for _ in range(4)]
        for source,target,socket in ((sibling,consumers[0],'Color'),(stack,consumers[1],'Color'),
                                     (stack,consumers[2],reference.SOCKET),(disabled,consumers[3],'Color')):
            tree.links.new(source.outputs['Color'],target.inputs[socket])
        target=editing.Target(stack,stack.pg_stack_entries[0])
        token=scheduler.begin(edited)
        try:
            for node in consumers[:3]:
                self.assertTrue(scheduler.scope_dragging(node))
                self.assertFalse(scheduler.dragging(node))
            self.assertFalse(scheduler.scope_dragging(consumers[3]))
            self.assertTrue(scheduler.scope_dragging(target))
            self.assertTrue(scheduler.dragging(target))
        finally:
            scheduler.end(token)
        upstream=nodes.create_grade(tree)
        tree.links.new(upstream.outputs['Color'],stack.inputs['Color'])
        token=scheduler.begin(upstream)
        try:
            self.assertTrue(scheduler.scope_dragging(target))
            self.assertFalse(scheduler.dragging(target))
            ticket=scheduler.scope_request(target,'full',sampling.describe(target,nodes.grading_space(target)))
            self.assertTrue(scheduler._records[ticket.channel]['store'].state.dragging)
            self.assertTrue(ticket.provenance)
        finally:
            scheduler.end(token)

    def test_scope_dependency_gestures_reconcile_invalidation_and_pruning(self):
        primary=self.node();tree=primary.id_data
        comparison=nodes.create_grade(tree);downstream=nodes.create_grade(tree)
        tree.links.new(primary.outputs['Color'],downstream.inputs['Color'])
        tree.links.new(comparison.outputs['Color'],downstream.inputs[reference.SOCKET])
        ticket=scheduler.scope_request(downstream,'full',sampling.describe(downstream,nodes.grading_space(downstream)))
        first=scheduler.begin(primary);second=scheduler.begin(comparison)
        try:
            record=scheduler._records[ticket.channel]
            self.assertTrue(record['store'].state.dragging)
            scheduler.invalidate(primary)
            self.assertNotIn(first,scheduler._gestures)
            self.assertTrue(record['store'].state.dragging)
            scheduler.prune((primary,comparison,downstream))
            self.assertTrue(record['store'].state.dragging)
            scheduler.prune((primary,downstream))
            self.assertNotIn(second,scheduler._gestures)
            self.assertFalse(record['store'].state.dragging)
        finally:
            scheduler.end(first);scheduler.end(second)

    def test_stack_dependency_publishes_detached_final65_during_drag_then_native_latest(self):
        """Freeze a Stack dependency while its edited successor bakes natively."""
        source_node=self.node();tree=source_node.id_data
        stack=sequence(tree,[grades.ensure(source_node)])
        consumer=nodes.create_grade(tree)
        tree.links.new(stack.outputs['Color'],consumer.inputs['Color'])
        target=editing.Target(stack,stack.pg_stack_entries[0])
        view=(1,False);space=nodes.grading_space(consumer)

        # Leave no native A bake to adopt: the first captured dependency must
        # travel through the independent frozen-snapshot final-65 lane.
        signature_a=lut.cm.signature(nodes.bake_model(stack))
        for pointer,state in tuple(lut._states.items()):
            if state['baker'].signature==signature_a:
                lut.stop(lut._states.pop(pointer))
        lut._ready.pop(signature_a,None)

        releases=[Event() for _ in range(3)]
        release=releases[0];executor=ScopeExecutor({'scope_update':releases})
        gesture=scheduler.begin(target)
        latest_spec=None
        try:
            with patch.object(jobs,'_submit',executor):
                sampling.get(consumer,space,view)
                jobs.tick()
                state=jobs._states[consumer.as_pointer()]
                old_spec=state['capturing']
                self.assertIsNotNone(old_spec)
                self.assertTrue(scheduler.scope_dragging(consumer))
                provenance_a=old_spec['scope_provenance']
                self.assertTrue(provenance_a)
                signature_a=next(signature for signature,size in provenance_a if size==65)
                self.assertNotIn(signature_a,lut._ready)
                self.assertIn(signature_a,lut._scope_demands)

                # Change the Stack while the old scope capture owns a frozen A
                # signature. The root consumer remains structurally compatible.
                for gain in (.1,.2,.3):
                    nodes.write_chromatic(target,{'global_gain':gain})
                    sampling.get(consumer,space,view);jobs.tick()
                    self.assertIs(state['capturing'],old_spec)
                latest_spec=sampling.describe(consumer,space,view)
                self.assertEqual(old_spec['scope_source'],latest_spec['scope_source'])
                self.assertNotEqual(old_spec['key'],latest_spec['key'])
                signature_b=next(signature for signature,size in latest_spec['scope_provenance'] if size==65)
                self.assertNotEqual(signature_a,signature_b)

                # An explicit real capture creates B's native protection while
                # A is detached. Its expected ScopePreparing receipt proves the
                # dependency is frozen rather than approximated from a preview.
                try:
                    sampling.capture(latest_spec)
                except lut.ScopePreparing:
                    pass
                self.assertIn(signature_b,lut._scope_demands)
                native=lut._states[stack.as_pointer()]
                self.assertEqual(native['baker'].signature,signature_b)
                self.assertTrue(lut._scope_protected(native))

                lut.tick()
                self.assertIsNotNone(lut._scope_running)
                self.assertEqual(lut._scope_running[0],signature_a)
                self.assertNotEqual(lut._scope_running[1].signature,native['baker'].signature)

                deadline=time.monotonic()+90
                while not executor.started['scope_update'].is_set() and time.monotonic()<deadline:
                    lut.tick();sampling.get(consumer,space,view);jobs.tick();time.sleep(.001)
                self.assertTrue(executor.started['scope_update'].is_set(),
                                'Detached final-65 source did not reach helper registration/update')
                running=jobs._running
                self.assertIsNotNone(running)
                self.assertEqual(running[2]['key'],old_spec['key'])
                captured=executor.snapshots['scope_register'][0]
                self.assertEqual(captured['_scope_provenance'],provenance_a)
                self.assertTrue(all(size==65 for _,size in captured['_scope_provenance']))
                self.assertTrue(scheduler.scope_dragging(consumer))

                release.set()
                deadline=time.monotonic()+30
                while (state.get('result') is None or state['result'].get('_scope_key')!=old_spec['key']) and time.monotonic()<deadline:
                    lut.tick();sampling.get(consumer,space,view);jobs.tick();time.sleep(.001)
                self.assertIsNotNone(state.get('result'))
                self.assertEqual(state['result']['_scope_key'],old_spec['key'])
                self.assertNotEqual(state['result']['_scope_key'],state['spec']['key'])
                self.assertTrue(scheduler._records['full',consumer.as_pointer()]['store'].state.dragging)

                # A second full publication must arrive before release, now
                # from the native final-65 successor protected alongside A.
                releases[1].set()
                second=wait_for_scopes(consumer,view,timeout=90)
                self.assertEqual(second['_scope_key'],latest_spec['key'])
                self.assertNotEqual(second['_scope_key'],old_spec['key'])
                self.assertTrue(all(size==65 for _,size in second['_scope_provenance']))
                self.assertTrue(scheduler.scope_dragging(consumer))

                # A third compatible receipt remains useful after release;
                # the newest pending request is still required for current.
                nodes.write_chromatic(target,{'global_gain':.4})
                sampling.get(consumer,space,view)
                deadline=time.monotonic()+90
                while len(executor.snapshots['scope_update'])<3 and time.monotonic()<deadline:
                    lut.tick();sampling.get(consumer,space,view);jobs.tick();time.sleep(.001)
                self.assertEqual(len(executor.snapshots['scope_update']),3)
                stale=jobs._running[2]
                nodes.write_chromatic(target,{'global_gain':.5})
                sampling.get(consumer,space,view)
                scheduler.end(gesture);gesture=None
                self.assertFalse(scheduler.scope_dragging(consumer))
                releases[2].set();jobs.tick()
                self.assertEqual(state['result']['_scope_key'],stale['key'])
                self.assertNotEqual(state['completed'],state['spec']['key'])
                final=wait_for_scopes(consumer,view,timeout=90)
                self.assertEqual(final['_scope_key'],state['spec']['key'])
                self.assertTrue(final['_scope_provenance'])
                self.assertTrue(all(size==65 for _,size in final['_scope_provenance']))
                self.assertNotEqual(final['_scope_provenance'],provenance_a)
        finally:
            for item in releases:item.set()
            if latest_spec is not None:sampling.release(latest_spec)
            if gesture is not None:scheduler.end(gesture)

    def test_stack_inspector_repeatedly_publishes_protected_native_final65_during_drag(self):
        """The edited Stack inspector keeps publishing before mouse release."""
        source_node=self.node();tree=source_node.id_data
        stack=sequence(tree,[grades.ensure(source_node)])
        stack.inputs['Color'].default_value=(.2,.3,.7,1.)
        target=editing.Target(stack,stack.pg_stack_entries[0])
        view=(1,False);space=nodes.grading_space(target)
        releases=[Event() for _ in range(4)]
        executor=ScopeExecutor({'scope_update':releases})
        gesture=scheduler.begin(target)
        published=[]
        try:
            with patch.object(jobs,'_submit',executor):
                for index,gain in enumerate((.1,.2,.3,.4)):
                    nodes.write_chromatic(target,{'global_gain':gain})
                    sampling.get(target,space,view);jobs.tick()
                    state=jobs._states[target.as_pointer()]
                    spec=state['capturing']
                    self.assertIsNotNone(spec)
                    signature=next(signature for signature,size in spec['scope_provenance'] if size==65)
                    native=lut._states[stack.as_pointer()]
                    self.assertEqual(native['baker'].signature,signature)
                    self.assertTrue(lut._scope_protected(native))
                    self.assertTrue(scheduler.scope_dragging(target))

                    deadline=time.monotonic()+90
                    while len(executor.snapshots['scope_update'])<=index and time.monotonic()<deadline:
                        lut.tick();sampling.get(target,space,view);jobs.tick();time.sleep(.001)
                        self.assertIsNone(lut._scope_running,'A matching native baker must serve the inspector demand')
                    self.assertEqual(len(executor.snapshots['scope_update']),index+1)
                    captured=executor.snapshots['scope_register'][index]
                    self.assertEqual(captured['_scope_provenance'],spec['scope_provenance'])
                    self.assertTrue(all(size==65 for _,size in captured['_scope_provenance']))
                    self.assertTrue(scheduler.scope_dragging(target))
                    if index==3:
                        # Release preserves the compatible held result, while
                        # the newest edit still needs its own final-65 receipt.
                        stale=jobs._running[2]
                        nodes.write_chromatic(target,{'global_gain':.5})
                        sampling.get(target,space,view)
                        scheduler.end(gesture);gesture=None
                        releases[index].set();jobs.tick()
                        self.assertEqual(state['result']['_scope_key'],stale['key'])
                        self.assertNotEqual(state['completed'],state['spec']['key'])
                    else:
                        releases[index].set()
                        result=wait_for_scopes(target,view,timeout=90)
                        self.assertEqual(result['_scope_key'],spec['key'])
                        self.assertTrue(all(size==65 for _,size in result['_scope_provenance']))
                        self.assertTrue(scheduler.scope_dragging(target))
                        published.append(result['_scope_key'])

                self.assertEqual(len(set(published)),3)
                final=wait_for_scopes(target,view,timeout=90)
                self.assertEqual(final['_scope_key'],state['spec']['key'])
                self.assertNotIn(final['_scope_key'],published)
                self.assertTrue(all(size==65 for _,size in final['_scope_provenance']))
        finally:
            for item in releases:item.set()
            if gesture is not None:scheduler.end(gesture)

    def test_cleared_scope_lifetime_rejects_completed_worker(self):
        node = self.node()
        spec = sampling.describe_linear(node, nodes.grading_space(node))
        ticket = scheduler.scope_request(node, 'linear', spec)
        self.assertTrue(scheduler.scope_start(ticket))
        scheduler.scope_clear('linear')
        scheduler.scope_complete(ticket)
        self.assertFalse(scheduler.scope_publish(ticket))

    def test_stage_one_worker_publishes_during_drag_and_queues_latest_matrix(self):
        """Real captures and worker completions exercise the policy classifier."""
        node = self.node()
        node.inputs['Color'].default_value = (.2, .3, .7, 1.)
        space = nodes.grading_space(node)
        gesture = scheduler.begin(node)
        self.addCleanup(scheduler.end, gesture)
        released = [Event() for _ in range(3)]
        executor = ScopeExecutor({'scope_linear':released})
        snapshots = executor.snapshots['scope_linear']

        try:
            with patch.object(jobs, '_submit', executor):
                jobs.request_linear(node, space)
                jobs.linear_tick()
                self.assertEqual(len(snapshots),1)
                first = jobs._linear_running
                nodes.write_values(node, {'source_x': .33, 'source_y': .34})
                jobs.request_linear(node, space)
                pending = jobs._linear_pending[2]['_schedule']
                original = first[2]['_schedule']
                self.assertNotEqual(original.key, pending.key)
                self.assertEqual(original.signal, pending.signal)
                self.assertEqual((original.quality, pending.quality), (1, 1))
                released[0].set()
                first[3].result(timeout=10)
                jobs.linear_tick()
                self.assertEqual(len(snapshots),2)
                state = jobs._linear_states[node.as_pointer()]
                self.assertEqual(state['result']['_scope_key'], first[2]['key'])
                np.testing.assert_allclose(state['result']['stage1_rgb'],
                    state['result']['source_rgb'] @ snapshots[0]['matrix'].T)
                self.assertEqual(jobs._linear_running[2]['key'], state['spec']['key'])
                self.assertEqual(scheduler._records['linear', node.as_pointer()]['store'].state.publications, 0)

                second = jobs._linear_running
                nodes.write_values(node, {'source_x': .35, 'source_y': .36})
                jobs.request_linear(node, space)
                scheduler.end(gesture)
                released[1].set()
                second[3].result(timeout=10)
                jobs.linear_tick()
                self.assertEqual(len(snapshots),3)
                self.assertEqual(state['result']['_scope_key'], second[2]['key'])
                self.assertNotEqual(state['completed'],state['spec']['key'])
                latest = jobs._linear_running
                released[2].set()
                latest[3].result(timeout=10)
                jobs.linear_tick()
                self.assertEqual(state['result']['_scope_key'], state['spec']['key'])
                self.assertEqual(state['completed'], state['spec']['key'])
                self.assertEqual(scheduler._records['linear', node.as_pointer()]['store'].state.publications, 1)
                self.assertFalse(jobs.linear_pending())
        finally:
            for event in released:
                event.set()

    def test_stage_one_source_and_reference_changes_retire_captured_tickets(self):
        node = self.node()
        space = nodes.grading_space(node)
        comparison = node.id_data.nodes.new('CompositorNodeRGB')
        comparison.outputs[0].default_value = (.3, .2, .6, .7)
        node.id_data.links.new(comparison.outputs[0], node.inputs[reference.SOCKET])
        gesture = scheduler.begin(node)
        self.addCleanup(scheduler.end, gesture)
        for change in (
            lambda: setattr(node.inputs['Color'], 'default_value', (.7, .1, .2, 1.)),
            lambda: setattr(comparison.outputs[0], 'default_value', (.1, .7, .2, 1.)),
            lambda: reference.toggle(node),
        ):
            old = scheduler.scope_request(node, 'linear', sampling.describe_linear(node, space))
            change()
            current = scheduler.scope_request(node, 'linear', sampling.describe_linear(node, space))
            self.assertNotEqual(old.signal, current.signal)
            self.assertNotEqual(old.owner, current.owner)
            self.assertFalse(scheduler.scope_publish(old,{'_scope_provenance':old.provenance}))
            self.assertTrue(scheduler.scope_publish(current,{'_scope_provenance':current.provenance}))

    def test_scope_worker_publishes_current_final_signal(self):
        node = self.node()
        nodes.write_tone(node, {'input_midtones': 44.})
        lut.ensure(node, nodes.bake_model(node))
        result = wait_for_scopes(node, (1, False))
        state = jobs._states[node.as_pointer()]
        ticket = state['spec']['_schedule']
        self.assertEqual(ticket.quality, 2)
        self.assertEqual(result['_scope_key'], state['spec']['key'])
        self.assertEqual(result['_scope_key'].stack_signature,
                         sampling.describe(node,nodes.grading_space(node),(1,False))['key'].stack_signature)
        self.assertEqual(result['_scope_provenance'],ticket.provenance)
        self.assertTrue(all(size==65 for _,size in ticket.provenance))
        self.assertEqual(scheduler._records['full', node.as_pointer()]['store'].state.publications, 1)

    def test_effect_failures_rollback_without_consuming_publication(self):
        """Every registered phase has the same real exception/rollback route."""
        node=self.node()
        for phase in scheduler.EFFECT_PHASES:
            with self.subTest(phase=phase):
                ticket=scheduler.lut_candidate(node,nodes.bake_model(node),False)
                record=scheduler._records[ticket.channel]
                count=record['store'].state.publications
                staged=[]
                def mutate():
                    staged.append('partial')
                    raise RuntimeError('injected '+phase)
                with self.assertRaisesRegex(RuntimeError,'injected'):
                    scheduler.effect(ticket,phase,mutate,rollback=staged.clear)
                self.assertFalse(staged)
                self.assertEqual(record['store'].state.effect,0)
                self.assertEqual(record['store'].state.publications,count)
                self.assertEqual(scheduler.effect(ticket,phase,lambda:17),17)
                self.assertEqual(record['store'].state.effect,0)

    def test_failed_submission_releases_worker_and_retains_display(self):
        node=self.node();space=nodes.grading_space(node)
        first=scheduler.scope_request(node,'linear',sampling.describe_linear(node,space))
        result=jobs.readonly({'_scope_provenance':first.provenance})
        self.assertTrue(scheduler.scope_publish(first,result))
        nodes.write_values(node,{'exposure':.2})
        ticket=scheduler.scope_request(node,'linear',sampling.describe_linear(node,space))
        self.assertTrue(scheduler.scope_start(ticket))
        def fail_submit():raise RuntimeError('executor rejected submit')
        with self.assertRaisesRegex(RuntimeError,'executor rejected'):
            scheduler.effect(ticket,'submit',fail_submit)
        record=scheduler._records[ticket.channel]
        self.assertEqual(record['store'].state.worker,0)
        self.assertIs(scheduler.scope_result(node,'linear'),result)
        self.assertEqual(scheduler.scope_status(node,'linear'),'error')

    def test_reentrant_channel_replacement_rolls_back_stale_effect(self):
        for failed in (False, True):
            with self.subTest(native_failure=failed):
                node = self.node()
                ticket = scheduler.lut_candidate(node, nodes.bake_model(node), False)
                staged, replacement = [], []

                def mutate():
                    staged.append('partial native write')
                    _, record = scheduler._record(node, 'lut', ('new native context',))
                    replacement.append((record['store'], record['store'].state))
                    if failed:
                        raise RuntimeError('native action failed after replacement')

                message = 'native action failed' if failed else 'invalidated before commit'
                with self.assertRaisesRegex(RuntimeError, message):
                    scheduler.effect(ticket, 'install', mutate, rollback=staged.clear)
                self.assertFalse(staged)
                store, before = replacement[0]
                self.assertIs(scheduler._records[ticket.channel]['store'], store)
                self.assertIs(store.state, before)
                self.assertEqual(store.state.effect, 0)

    def test_recovery_fences_leases_and_scope_payloads(self):
        node=self.node();space=nodes.grading_space(node)
        ticket=scheduler.scope_request(node,'linear',sampling.describe_linear(node,space))
        result={'_scope_provenance':ticket.provenance}
        self.assertTrue(scheduler.scope_start(ticket))
        lease=scheduler.effect_begin(ticket,'capture')
        self.assertIsNotNone(lease)
        before=scheduler.session();scheduler.recover()
        self.assertNotEqual(scheduler.session(),before)
        self.assertFalse(scheduler.finish_effect(lease))
        self.assertFalse(scheduler.scope_publish(ticket,result))
        self.assertFalse(scheduler._gestures)
        fresh=scheduler.scope_request(node,'linear',sampling.describe_linear(node,space))
        self.assertTrue(scheduler.scope_start(fresh));scheduler.scope_complete(fresh)
        self.assertTrue(scheduler.scope_publish(fresh,{'_scope_provenance':fresh.provenance}))

    def test_lifecycle_fence_blocks_otherwise_current_work_until_recovery_receipt(self):
        node=self.node();space=nodes.grading_space(node)
        ticket=scheduler.scope_request(node,'linear',sampling.describe_linear(node,space))
        payload={'_scope_provenance':ticket.provenance}
        scheduler.lifecycle_event('recover')
        self.assertFalse(scheduler.scope_start(ticket))
        self.assertIsNone(scheduler.effect_begin(ticket,'capture'))
        self.assertFalse(scheduler.scope_publish(ticket,payload))
        self.assertFalse(scheduler.publication(ticket))
        def callback():return None
        scheduler.wake(callback,1000.)
        self.assertTrue(bpy.app.timers.is_registered(scheduler.timer_callback(callback)))
        scheduler.unwake(callback)
        scheduler.lifecycle_event('fail')
        self.assertFalse(scheduler.scope_start(ticket))
        self.assertFalse(scheduler.scope_publish(ticket,payload))
        scheduler.lifecycle_event('recover')
        scheduler.lifecycle_event('recovered')
        self.assertTrue(scheduler.scope_start(ticket))
        scheduler.scope_complete(ticket)
        self.assertTrue(scheduler.scope_publish(ticket,payload))

    def test_failed_rollback_retires_lifetime_but_next_request_recovers(self):
        node=self.node();ticket=scheduler.lut_candidate(node,nodes.bake_model(node),False)
        def fail():raise RuntimeError('failed resource')
        with self.assertRaisesRegex(RuntimeError,'failed resource'):
            scheduler.effect(ticket,'install',fail,rollback=fail)
        self.assertNotIn(ticket.channel,scheduler._records)
        fresh=scheduler.lut_candidate(node,nodes.bake_model(node),False)
        self.assertNotEqual(fresh.owner,ticket.owner)
        self.assertEqual(scheduler.effect(fresh,'install',lambda:42),42)

    def test_timer_registration_partial_failure_rolls_back_real_callback(self):
        def callback():return None
        register=bpy.app.timers.register
        def fail_after_registration(fn,**kwargs):
            register(fn,**kwargs)
            raise RuntimeError('after native registration')
        with patch.object(bpy.app.timers,'register',side_effect=fail_after_registration):
            with self.assertRaisesRegex(RuntimeError,'after native registration'):
                scheduler.wake(callback,60.)
        self.assertFalse(bpy.app.timers.is_registered(scheduler.timer_callback(callback)))
        self.assertNotIn(callback,scheduler._timers)
        scheduler.wake(callback,60.)
        self.assertTrue(bpy.app.timers.is_registered(scheduler.timer_callback(callback)))
        scheduler.unwake(callback)

