"""Automatic demand runs through the generated contract and real actor."""
import unittest
from color_tools.invariant import Machine
from color_tools.blender_runtime import App
from color_tools.perceptual_grade_core.graph.coordinators import scope_demand as policy
from color_tools.perceptual_grade_core.graph.coordinators import _scope_demand_contracts


class ScopeDemandTests(unittest.TestCase):
    def setUp(self):
        self.app=App(package='scope_demand_test',storage_name='scope_demand_test')
        self.addCleanup(self.app.close)
        self.store=self.app.store(machine=Machine(policy,contracts=_scope_demand_contracts),initial={'generation':1})

    def event(self,kind,**values):
        return self.store.dispatch(policy.Event(kind,**dict(epoch=self.store.state.epoch,**values)))

    def demand(self,request,source=None,continuity=7):
        return self.event('demand',request=request,source=source or request+100,continuity=continuity)

    def test_running_snapshot_survives_updates_and_only_latest_runs_next(self):
        self.demand(1);first=self.event('start')
        receipt=self.store.event(policy.Event('complete',epoch=first.epoch,request=first.request,
                                             source=first.source,validated=True))
        for revision in range(2,30):self.demand(revision)
        self.assertEqual(self.store.state.active,1)
        self.assertFalse(self.event('start').accepted)
        self.assertEqual(self.store.dispatch(receipt).action,'publish')
        self.assertEqual(self.store.state.accepted,1)
        self.assertEqual(self.event('start').request,29)
        self.assertFalse(self.store.dispatch(receipt).accepted)

    def test_playback_epoch_rejects_old_receipt_even_after_stop(self):
        self.demand(1);active=self.event('start')
        receipt=self.store.event(policy.Event('complete',epoch=active.epoch,request=active.request,
                                             source=active.source,validated=True))
        self.event('pause');self.assertFalse(self.event('start').accepted)
        self.event('resume');self.demand(2);self.event('start')
        self.assertFalse(self.store.dispatch(receipt).accepted)
        self.assertEqual(self.store.state.accepted,0)

    def test_foreign_source_and_incompatible_route_cannot_publish(self):
        self.demand(1);self.event('start');self.demand(2,continuity=8)
        self.assertFalse(self.event('complete',request=1,source=999,validated=True).accepted)
        self.assertEqual(self.event('complete',request=1,source=101,validated=True).action,'discard')
        self.assertEqual(self.store.state.accepted,0)
        self.assertEqual(self.event('start').request,2)

    def test_failed_source_waits_for_retry_or_semantic_successor(self):
        self.demand(1);self.event('start');self.event('failed',request=1,source=101)
        self.assertFalse(self.event('start').accepted)
        self.event('retry');self.assertEqual(self.event('start').request,1)
        self.event('failed',request=1,source=101);self.demand(2)
        self.assertEqual(self.event('start').request,2)

