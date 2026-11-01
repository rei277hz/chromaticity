"""Recovery progress uses actor-owned generated contracts, never output authority."""
import unittest
from color_tools.invariant import Machine
from color_tools.blender_runtime import App
from color_tools.perceptual_grade_core.graph.coordinators import recovery as policy
from color_tools.perceptual_grade_core.graph.coordinators import _recovery_contracts


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.app=App(package='recovery_test',storage_name='recovery_test')
        self.addCleanup(self.app.close)
        self.store=self.app.store(machine=Machine(policy,contracts=_recovery_contracts))

    def send(self,kind,**values):
        return self.store.dispatch(policy.Event(kind,**(dict(generation=self.store.state.generation)|values)))

    def test_native_replacement_and_physical_retirement_are_distinct(self):
        self.assertEqual(self.send('begin',generation=1,native=True).action,'fence')
        self.assertFalse(self.send('retired',validated=True).accepted)
        self.assertFalse(self.send('replaced',validated=True).accepted)
        self.assertEqual(self.send('replaced',native=True,validated=True).action,'retire_journals')
        self.assertTrue(self.store.state.physical)
        self.assertFalse(self.send('retired',workers=1,validated=True).accepted)
        self.assertEqual(self.send('retired',validated=True).action,'discover')
        self.assertFalse(self.store.state.physical)

    def test_finite_worklist_progress_and_terminal_receipt(self):
        self.send('begin',generation=1);self.send('retired',validated=True)
        self.send('discovered',total=3,validated=True)
        self.assertFalse(self.send('adopted',index=1,validated=True).accepted)
        for index in range(2):
            effect=self.send('adopted',index=index,validated=True)
            self.assertFalse(effect.certified)
            self.assertEqual(self.store.state.settled,index+1)
        self.assertEqual(self.store.state.phase,'restoring')
        self.assertFalse(self.send('reconciled',validated=True).accepted)
        self.assertFalse(self.send('wrapper_restored',index=1,validated=True).accepted)
        self.assertFalse(self.send('wrapper_restored',index=0).accepted)
        for index in range(2):
            effect=self.send('wrapper_restored',index=index,validated=True)
            self.assertFalse(effect.certified)
            self.assertEqual(self.store.state.restored,index+1)
        self.assertEqual(self.store.state.phase,'reconciling')
        self.assertFalse(self.send('reconciled').accepted)
        self.assertEqual(self.send('reconciled',validated=True).action,'activate')
        self.assertEqual(self.store.state.settled,self.store.state.total)

    def test_wrapper_failure_preserves_progress_and_rejects_old_receipt(self):
        self.send('begin',generation=1);self.send('retired',validated=True)
        self.send('discovered',total=3,validated=True)
        for index in range(2):self.send('adopted',index=index,validated=True)
        self.send('wrapper_restored',index=0,validated=True)
        self.send('failed')
        self.assertEqual((self.store.state.settled,self.store.state.restored),(2,1))
        self.assertFalse(self.send('wrapper_restored',index=1,validated=True).accepted)
        self.send('begin',generation=2)
        self.assertFalse(self.send('wrapper_restored',generation=1,index=1,validated=True).accepted)

    def test_failure_retains_obligations_and_retry_rejects_stale_receipts(self):
        self.send('begin',generation=1,native=True)
        self.send('failed');self.assertTrue(self.store.state.physical)
        self.assertFalse(self.send('retired',validated=True).accepted)
        self.send('begin',generation=2)
        self.assertFalse(self.send('replaced',native=True,validated=True).accepted)
        self.assertFalse(self.send('retired',generation=1,validated=True).accepted)
        self.send('supersede');self.assertEqual(self.store.state.phase,'superseded')
        self.assertTrue(self.store.state.physical)
