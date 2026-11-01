"""Native public boundaries contain failures without retaining native objects."""
import gc
from types import SimpleNamespace
import unittest
import weakref

import bpy

from color_tools.perceptual_grade_blender.integration.outcomes import create


class OutcomeTests(unittest.TestCase):
    def setUp(self):
        self.application = SimpleNamespace(outcome_epoch=1)
        self.application.component = lambda _: SimpleNamespace(
            tr=lambda code, **values: code, tip=lambda code: code,
            wrap=lambda message, columns: [message])
        self.outcomes = create(self.application)
        self.node = SimpleNamespace(as_pointer=lambda: 42, id_data=SimpleNamespace(session_uid=9), inputs=(), outputs=())

    def test_status_is_local_and_fenced_by_native_generation(self):
        other = SimpleNamespace(as_pointer=lambda: 43, id_data=self.node.id_data)
        self.outcomes.set(self.node, 'bake', 'blocked.engine')
        self.assertIsNone(self.outcomes.get(other, 'bake'))
        self.assertEqual(self.outcomes.get(self.node, 'bake').code, 'blocked.engine')
        self.application.outcome_epoch += 1
        self.assertIsNone(self.outcomes.get(self.node, 'bake'))

    def test_callback_logs_details_but_draws_only_localized_outcome(self):
        class NativeOwner:pass
        owners = []
        def fail():
            owner = NativeOwner()
            owners.append(weakref.ref(owner))
            error = RuntimeError('private diagnostic')
            error.native_owner = owner
            raise error
        with self.assertLogs(level='ERROR') as logs:
            self.assertIsNone(self.outcomes.callback(fail, control='timer')())
        gc.collect()
        self.assertIsNone(owners[0]())
        self.assertIn('private diagnostic', '\n'.join(logs.output))
        labels = []
        layout = SimpleNamespace(column=lambda **_: SimpleNamespace(label=lambda **v: labels.append(v['text'])))
        self.outcomes.draw(layout)
        self.assertEqual(labels, ['outcome.failed'])

    def test_registered_operator_and_poll_do_not_report_or_escape(self):
        cancelled = []
        class PG_OT_outcome_fixture(bpy.types.Operator):
            bl_idname = 'perceptual_grade.outcome_fixture'
            bl_label = 'Failure boundary fixture'
            @classmethod
            def poll(cls, context):raise ValueError('poll detail')
            def execute(self, context):raise RuntimeError('operation detail')
            def cancel(self, context):cancelled.append(True)
            def report(self, *_):raise AssertionError('Unexpected native report')
        self.outcomes.protect_class(PG_OT_outcome_fixture)
        bpy.utils.register_class(PG_OT_outcome_fixture)
        try:
            context = SimpleNamespace(pg_node=self.node)
            instance = SimpleNamespace(bl_options=set(), cancel=lambda ctx: cancelled.append(True))
            with self.assertLogs(level='ERROR'):
                self.assertFalse(PG_OT_outcome_fixture.poll(context))
                self.assertEqual(PG_OT_outcome_fixture.execute(instance, context), {'CANCELLED'})
            self.assertEqual(cancelled, [True])
            self.assertEqual(self.outcomes.get(self.node, PG_OT_outcome_fixture.bl_idname).code, 'outcome.failed')
        finally:
            bpy.utils.unregister_class(PG_OT_outcome_fixture)

    def test_undoable_failure_keeps_undo_and_cleanup_failure_visible(self):
        class PG_OT_outcome_undo(bpy.types.Operator):
            bl_idname = 'perceptual_grade.outcome_undo'
            bl_label = 'Undo failure boundary fixture'
            bl_options = {'UNDO'}
            def execute(self, context):raise RuntimeError('partially applied')
            def cancel(self, context):raise RuntimeError('rollback failed')
        self.outcomes.protect_class(PG_OT_outcome_undo)
        bpy.utils.register_class(PG_OT_outcome_undo)
        try:
            context = SimpleNamespace(pg_node=self.node)
            instance = SimpleNamespace(bl_options={'UNDO'})
            instance.cancel = lambda ctx: PG_OT_outcome_undo.cancel(instance, ctx)
            with self.assertLogs(level='ERROR'):
                self.assertEqual(PG_OT_outcome_undo.execute(instance, context), {'FINISHED'})
            # FINISHED preserves native Undo; it does not clear the failed state.
            status = self.outcomes.get(self.node, PG_OT_outcome_undo.bl_idname)
            self.assertEqual(status.code, 'outcome.failed')
            self.assertIn('rollback failed', status.diagnostic)
            with self.assertLogs(level='ERROR'):
                self.assertEqual(bpy.ops.perceptual_grade.outcome_undo(), {'FINISHED'})
        finally:
            bpy.utils.unregister_class(PG_OT_outcome_undo)

    def test_rna_property_callbacks_have_safe_fallbacks(self):
        def fail(*args):raise RuntimeError('RNA detail')
        deferred = bpy.props.FloatProperty(default=.5, get=fail, set=fail, update=fail)
        self.outcomes.property(deferred, control='slider')
        with self.assertLogs(level='ERROR'):
            self.assertEqual(deferred.keywords['get'](self.node), .5)
            self.assertIsNone(deferred.keywords['set'](self.node, 1.))
            self.assertIsNone(deferred.keywords['update'](self.node, None))
        self.assertEqual(self.outcomes.get(self.node, 'slider').code, 'outcome.failed')

    def test_shared_property_group_failure_has_visible_global_status(self):
        settings = SimpleNamespace(as_pointer=lambda: 90, id_data=self.node.id_data)
        def fail(*_):raise ValueError('settings failure')
        deferred = bpy.props.FloatProperty(default=0., update=fail)
        self.outcomes.property(deferred, control='settings')
        with self.assertLogs(level='ERROR'):
            deferred.keywords['update'](settings, None)
        self.assertEqual(self.outcomes.get(None, 'settings').code, 'outcome.failed')

    def test_panel_poll_failure_does_not_require_operator_message_api(self):
        class PG_PT_outcome_fixture(bpy.types.Panel):
            bl_idname = 'PG_PT_outcome_fixture'
            bl_label = 'Outcome panel fixture'
            bl_space_type = 'NODE_EDITOR'
            bl_region_type = 'UI'
            @classmethod
            def poll(cls, context):raise RuntimeError('panel failure')
            def draw(self, context):pass
        self.outcomes.protect_class(PG_PT_outcome_fixture)
        with self.assertLogs(level='ERROR'):
            self.assertFalse(PG_PT_outcome_fixture.poll(SimpleNamespace(pg_node=self.node)))

    def test_removed_property_owner_failure_remains_contained(self):
        class RemovedOwner:
            @property
            def inputs(self):raise ReferenceError('removed RNA')
        def fail(*_):raise RuntimeError('update interrupted')
        with self.assertLogs(level='ERROR'):
            self.assertIsNone(self.outcomes.callback(fail,control='removed',node_argument=True)(RemovedOwner()))
        self.assertEqual(self.outcomes.get(None,'removed').code,'outcome.failed')

    def test_successful_edit_clears_failure_but_drawing_property_does_not(self):
        self.outcomes.set(None,'settings','outcome.failed')
        settings=SimpleNamespace()
        deferred=bpy.props.FloatProperty(get=lambda owner: .5,set=lambda owner,value: None)
        self.outcomes.property(deferred,control='settings')
        self.assertEqual(deferred.keywords['get'](settings),.5)
        self.assertIsNotNone(self.outcomes.get(None,'settings'))
        deferred.keywords['set'](settings,1.)
        self.assertIsNone(self.outcomes.get(None,'settings'))

    def test_successful_callback_keeps_new_outcome_and_clears_previous_failure(self):
        self.outcomes.set(None,'timer','outcome.failed')
        callback=self.outcomes.callback(lambda: .1,control='timer')
        self.assertEqual(callback(),.1)
        self.assertIsNone(self.outcomes.get(None,'timer'))
        self.outcomes.set(None,'timer','old')
        callback=self.outcomes.callback(lambda: self.outcomes.set(None,'timer','new'),control='timer')
        callback()
        self.assertEqual(self.outcomes.get(None,'timer').code,'new')

    def test_completed_recovery_only_clears_its_own_outcomes(self):
        self.outcomes.set(None,'timer','outcome.failed',recovery='perceptual_grade.retry_recovery')
        self.outcomes.set(self.node,'bake','outcome.failed',recovery='perceptual_grade.bake_compositor')
        self.outcomes.recovered('perceptual_grade.retry_recovery')
        self.assertIsNone(self.outcomes.get(None,'timer'))
        self.assertIsNotNone(self.outcomes.get(self.node,'bake'))


if __name__ == '__main__':unittest.main()
